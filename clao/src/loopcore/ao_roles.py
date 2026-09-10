"""Pure native-role evidence and contract bridge; no model, scheduler or store."""
import json
from .auditor import EvidenceBundle, PROMPT_DIR, SCHEMA_DIR
from .mission_contracts import check_role, check_planner
from .structured import ProtocolError
from . import worktree as wt


def evaluate(request, spec, root):
    role = request["role"]
    if role not in ("auditor", "planner"):
        raise ValueError("unsupported semantic role")
    context = request["roleContext"]
    ident = context["id"]
    audit = context.get("audit")
    target = context["workerId"]
    if "roleText" in request:
        obj = json.loads(request["roleText"], parse_constant=lambda s: (_ for _ in ()).throw(ValueError("non-finite JSON")))
        if role == "auditor":
            check_role(obj, "audit-result", audit_id=ident, task_id=spec.task_id)
            if set(obj.get("failed_criteria", [])) - {a.id for a in spec.acceptance_criteria}:
                raise ProtocolError("CORRELATION", "audit refers to unknown AC")
            if not obj["diagnosis"].strip():
                raise ProtocolError("SCHEMA", "empty diagnosis")
        else:
            check_planner(obj, ident, spec.task_id, target)
            if obj["action"] == "SEND_LOCAL_FIX" and (obj.get("target_session_id") != target or not obj.get("message", "").strip()):
                raise ProtocolError("CORRELATION", "local fix requires current Worker and non-empty message")
            if not obj["reason"].strip():
                raise ProtocolError("SCHEMA", "empty action reason")
            if audit["decision"] == "HUMAN" and obj["action"] != "HUMAN":
                raise ProtocolError("COHERENCE", "human-required diagnosis cannot authorize automatic action")
        return {"ok": True, "roleResult": obj}
    if role == "auditor":
        proof = context["proof"]
        # Preserve full native error/status and history. F01 limits explicitly
        # reject incomplete material rather than silently feeding a fragment.
        bundle = EvidenceBundle(task_spec=spec.to_dict(),
            alert={"id": context["incidentId"], "type": "execution_or_gate_failure", "summary": context.get("executionError") or "deterministic Gate failed"},
            worker_id=target, worker_status=context["workerStatus"],
            git_diff=wt.git_diff_text(str(root), request["base"], limit=None),
            test_output=json.dumps(proof.get("records", []), ensure_ascii=False),
            events=[{"gate": proof.get("gate"), "execution_error": context.get("executionError", "")}],
            history=context["history"])
        bundle.validate_evidence()
        data = {"audit_id": ident, "task_id": spec.task_id, "evidence_bundle": json.loads(bundle.to_prompt_text())}
        schema = "audit-result"
    else:
        check_role(audit, "audit-result", task_id=spec.task_id, audit_id=context["auditId"])
        data = {"action_id": ident, "task_id": spec.task_id, "audit_result": audit,
                "task_spec": spec.to_dict(), "target_session_id": target,
                "remaining_replans": context["remainingReplans"],
                "mission_board": {"history": context["history"], "remaining_actions": context["remainingActions"], "single_worker": True},
                "user_instruction": "Original goal, AC, Gate and scope are immutable. Replacement objective is an execution plan under those constraints. CONTINUE only observes; it does not restart a stopped Worker."}
        schema = "planner-action"
    data["schema"] = json.loads((SCHEMA_DIR / (schema + ".schema.json")).read_text("utf-8"))
    data["instruction"] = "Read-only semantic decision. Output ONLY the correlated schema JSON; no markdown, tools or scheduling."
    prompt = (PROMPT_DIR / (role + ".md")).read_text("utf-8") + "\n\n" + json.dumps(data, ensure_ascii=False, allow_nan=False)
    if len(prompt.encode("utf-8")) > 100_000:
        raise ProtocolError("TRUNCATED", "complete role evidence exceeds native request bound")
    return {"ok": True, "rolePrompt": prompt}
