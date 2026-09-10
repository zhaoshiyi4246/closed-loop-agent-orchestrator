"""AO's acceptance subprocess: reuse Git/Gate logic, without a Controller or DB.

AO owns scheduling and persists the returned facts in its existing SQLite DB.
This module never starts a Worker, reads model credentials or writes user main.
"""
from dataclasses import asdict
import json
from pathlib import Path
import re
import sys

from .mission_contracts import TaskSpec, check_verifier
from .verifier import VerifierInput, PROMPT_DIR, SCHEMA_DIR
from .mission_gate import IntegrationGate
from .state_store import StateStore
from . import worktree as wt
from . import approvals


class EvidenceCapture:
    """Transient output adapter for IntegrationGate, not a second state store."""
    gate_assessment = staticmethod(StateStore.gate_assessment)

    def __init__(self):
        self.records = []

    def record_gate_run(self, **record):
        self.records.append(record)
        return len(self.records)

    def annotate_gate_runs(self, ids, assessment):
        for key in ids:
            self.records[key - 1]["assessment"] = assessment


def evaluate(request):
    root = Path(request["workspace"]).resolve(strict=True)
    base = request["base"]
    if not root.is_dir() or not re.fullmatch(r"[0-9a-f]{40,64}", base):
        raise ValueError("missing workspace or frozen base")
    spec = TaskSpec.from_dict(request["task"])
    if not spec.allowed_paths or not spec.acceptance_criteria or not spec.gate_commands:
        raise ValueError("explicit scope, AC and Gate are required")
    if "role" in request:
        from .ao_roles import evaluate as role_evaluate
        return role_evaluate(request, spec, root)
    if "approval" in request:
        activity = request["approval"]
        detail = activity.get("detail", {})
        if detail.get("method") == "item/commandExecution/requestApproval":
            raw = detail.get("approvalRequest")
            known = {"threadId", "turnId", "itemId", "approvalId", "command", "cwd", "reason", "commandActions",
                     "networkApprovalContext", "additionalPermissions", "availableDecisions", "environmentId", "kind",
                     "proposedExecpolicyAmendment", "proposedNetworkPolicyAmendments"}
            if (not isinstance(raw, dict) or set(raw) - known
                    or raw.get("environmentId") not in (None, "local")
                    or raw.get("kind", "command") != "command"
                    or any(raw.get(k) is not None for k in ("approvalId", "networkApprovalContext", "additionalPermissions"))
                    or raw.get("command") != detail.get("rawCommand") or raw.get("cwd") != detail.get("cwd")):
                return {"ok": False, "readError": "执行环境或完整权限请求无法确认；不允许扩大授权"}
        forbidden = spec.forbidden_paths + [".git", ".git/**", "**/.git", "**/.git/**"]
        decision = approvals.decide_approval(activity, allowed_paths=spec.allowed_paths,
                    forbidden_paths=forbidden, gate_commands=spec.gate_commands,
                    worktree_root=str(root))
        if decision is None or not decision.allow:
            return {"ok": False, "readError": decision.reason if decision else "请求不是当前待审批请求"}
        detail = activity["detail"]
        if detail.get("subjectKind") == "command" or detail.get("method") == "item/commandExecution/requestApproval":
            inputs = detail.get("input", {})
            command = detail.get("rawCommand", inputs.get("command"))
            cwd = approvals._cwd(detail.get("cwd", inputs.get("cwd", str(root))), root)
            # A Gate match cannot override Git control protection or forbidden
            # targets. Reuse the stricter F02 command boundary as well.
            approvals._codex_command(command, spec.gate_commands, root, cwd, forbidden)
        return {"ok": True}
    if request.get("readOnly") or request.get("prepareVerification"):
        # Recovery must not run a Gate (which is arbitrary user-authorized
        # shell work), commit, or alter the real index merely to check inputs.
        if wt._snapshot_git(str(root), "rev-parse", "--verify", base + "^{commit}").decode().strip() != base:
            raise ValueError("frozen source object unavailable")
        wt._snapshot_git(str(root), "merge-base", "--is-ancestor", base, "HEAD")
        snapshot = wt.git_state_snapshot(str(root))
        if request.get("expectedHead") and (wt._current_head(str(root)) != request["expectedHead"] or not snapshot.clean):
            raise ValueError("recorded result HEAD or working content changed")
        result = {"ok": True, "digest": snapshot.digest}
        if request.get("prepareVerification"):
            proof = request["proof"]
            if not request.get("expectedHead") or proof.get("resultHead") != request["expectedHead"] or not proof.get("ok"):
                raise ValueError("frozen result/acceptance association missing")
            inp = VerifierInput(task_spec=spec.to_dict(), diff=wt.git_diff_text(str(root), base, limit=None),
                                gate_output=json.dumps(proof["records"], ensure_ascii=False), changed_paths=proof["paths"])
            inp.validate_evidence()
            result["verifierPrompt"] = (PROMPT_DIR / "verifier.md").read_text("utf-8") + "\n" + json.dumps({
                "verify_id": spec.task_id + ":verify", "task_id": spec.task_id,
                "verifier_input": json.loads(inp.to_prompt_text()),
                "schema": json.loads((SCHEMA_DIR / "verifier-result.schema.json").read_text("utf-8")),
                "instruction": "Read-only independent review. Do not modify files or run tools. Output ONLY the VerifierResult JSON; no markdown fences."
            }, ensure_ascii=False)
        return result
    changed = wt.changed_paths(str(root), base)
    if changed is None:
        raise ValueError("Git evidence unavailable")
    forbidden, outside = wt.scope_violations(changed, allowed_paths=spec.allowed_paths,
                                           forbidden_paths=spec.forbidden_paths + [".git", ".git/**"])
    # Deleted paths remain scope facts; extant targets must resolve inside root.
    for name in changed:
        path = root / name
        try:
            path.resolve(strict=False).relative_to(root)
        except (ValueError, OSError, RuntimeError):
            outside.append(name)
    evidence = EvidenceCapture()
    gate = IntegrationGate(evidence, timeout_seconds=request["timeout"],
                           output_limit_chars=request["outputLimit"]).run(spec, str(root), phase="final")
    for record in evidence.records:
        prior = record["assessment"]
        record["assessment"] = StateStore.gate_assessment(
            phase="final", command=prior["command_status"],
            integrity=prior["integrity"]["status"], integrity_reason=prior["integrity"]["reason"],
            scope="fail" if forbidden or outside else "pass",
            scope_reason=json.dumps({"forbidden": forbidden, "outside": outside}, ensure_ascii=False) if forbidden or outside else "")
    result = {"gate": asdict(gate), "records": evidence.records, "paths": changed,
              "forbidden": forbidden, "outside": outside,
              "scopeOK": not forbidden and not outside,
              "ok": gate.ok and not forbidden and not outside,
              "base": base, "digest": wt.git_state_snapshot(str(root)).digest}
    if request.get("expectedHead") and (wt._current_head(str(root)) != request["expectedHead"] or not wt.git_state_snapshot(str(root)).clean):
        raise ValueError("recorded result HEAD changed")
    if request.get("verificationText"):
        obj = json.loads(request["verificationText"])
        check_verifier(obj, spec.task_id + ":verify", spec.to_dict())
        result["verification"] = obj
        result["ok"] = result["ok"] and obj["verdict"] == "PASS"
    if request.get("materialize"):
        if not result["ok"]:
            raise ValueError("acceptance failed; materialization refused")
        if result["digest"] != request.get("expectedDigest"):
            raise ValueError("workspace changed after acceptance; materialization refused")
        inp = VerifierInput(task_spec=spec.to_dict(), diff=wt.git_diff_text(str(root), base, limit=None),
                            gate_output=json.dumps(evidence.records, ensure_ascii=False), changed_paths=changed)
        inp.validate_evidence()
        result["verifierPrompt"] = (PROMPT_DIR / "verifier.md").read_text("utf-8") + "\n" + json.dumps({
            "verify_id": spec.task_id + ":verify", "task_id": spec.task_id,
            "verifier_input": json.loads(inp.to_prompt_text()),
            "schema": json.loads((SCHEMA_DIR / "verifier-result.schema.json").read_text("utf-8")),
            "instruction": "Read-only independent review. Do not modify files or run tools. Output ONLY the VerifierResult JSON; no markdown fences."
        }, ensure_ascii=False)
        result["resultHead"] = wt.commit_all(str(root), "CLAO accepted result " + spec.task_id,
                                              base_commit=base)
    return result


def main():
    try:
        raw = sys.stdin.buffer.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("acceptance request too large")
        result = evaluate(json.loads(raw))
    except Exception as exc:
        result = {"ok": False, "readError": str(exc)[:2000]}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
