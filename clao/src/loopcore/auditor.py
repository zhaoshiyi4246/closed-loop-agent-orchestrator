"""Read-only Auditor.

Takes a prepared EvidenceBundle (TaskSpec + alert + events + diff + test output
+ AC status + history) and returns an AuditResult (PASS/LOCAL_FIX/REPLAN/HUMAN).

Providers:
  FakeAuditorProvider    - deterministic, for unit tests.
  CodexCliAuditorProvider- production auditor via the shared Codex CLI
                           structured-output boundary.

Auditor is READ-ONLY: it never edits files, runs shell, or controls the Worker.
Transport failures propagate to the Controller's bounded step retry.  A
schema-invalid response is retried once; a second invalid response is a
provider protocol error, never a semantic HUMAN decision.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .diagnostics import phase_call

from .codex_cli import run_codex_json
from .structured import role_result
from .mission_contracts import (AuditResult, AuditEvidence, AuditDecision,
                        check_role)
from .structured import (evidence_part, evidence_metadata, require_complete,
                         protocol_call)

PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
SCHEMA_DIR = PROMPT_DIR.parent / "schemas"


@dataclass
class EvidenceBundle:
    task_spec: Dict
    alert: Optional[Dict]
    events: List[Dict] = field(default_factory=list)
    alerts: List[Dict] = field(default_factory=list)   # aggregated incident
    worker_status: Optional[Dict] = None
    git_diff: str = ""
    test_output: str = ""
    satisfied_criteria: List[str] = field(default_factory=list)
    failed_criteria: List[str] = field(default_factory=list)
    history: Dict = field(default_factory=dict)   # local_fixes/replans counts
    audit_type: str = "ALERT"                     # ALERT | COMPLETION
    # multi-worker attribution: WHICH worker / subtask is this audit about
    worker_id: Optional[str] = None
    subtask_id: Optional[str] = None

    def evidence_parts(self):
        return {"git_diff": evidence_part(self.git_diff, 4000),
                "test_output": evidence_part(self.test_output, 4000),
                "events": evidence_part(self.events, 8000),
                "alerts": evidence_part(self.alerts, 8000)}

    def validate_evidence(self):
        parts = self.evidence_parts()
        require_complete(parts)
        return evidence_metadata(parts)

    def to_prompt_text(self) -> str:
        return json.dumps({
            "task_spec": self.task_spec, "audit_type": self.audit_type,
            "worker_id": self.worker_id, "subtask_id": self.subtask_id,
            "alert": self.alert, "worker_status": self.worker_status,
            "evidence": self.evidence_parts(),
            "satisfied_criteria": self.satisfied_criteria,
            "failed_criteria": self.failed_criteria, "history": self.history,
        }, ensure_ascii=False, indent=2, allow_nan=False)


class AuditorProvider:
    def audit(self, bundle: EvidenceBundle, audit_id: str) -> AuditResult:
        raise NotImplementedError


class FakeAuditorProvider(AuditorProvider):
    """Deterministic auditor for tests: LOCAL_FIX if any AC failed, else PASS."""
    def audit(self, bundle: EvidenceBundle, audit_id: str) -> AuditResult:
        if bundle.failed_criteria:
            decision = AuditDecision.LOCAL_FIX
            evidence = [AuditEvidence(
                type="test_failure",
                summary="acceptance criteria not satisfied: %s"
                        % ", ".join(bundle.failed_criteria),
                reference="bundle.failed_criteria")]
            diagnosis = "Worker has not satisfied failed criteria; local fix needed."
            recommended = ("Implement missing functionality in allowed paths; "
                           "do not modify tests or forbidden paths.")
            confidence = 0.9
        else:
            decision = AuditDecision.PASS
            evidence = [AuditEvidence(
                type="test_pass", summary="all acceptance criteria satisfied",
                reference="bundle")]
            diagnosis = "All criteria met."
            recommended = ""
            confidence = 0.95
        return AuditResult(
            audit_id=audit_id, task_id=bundle.task_spec.get("task_id", ""),
            decision=decision, evidence=evidence, diagnosis=diagnosis,
            confidence=confidence, failed_criteria=list(bundle.failed_criteria),
            recommended_action=recommended)


class CodexCliAuditorProvider(AuditorProvider):
    """Production Auditor using ephemeral, read-only Codex CLI calls."""

    def __init__(self, *, codex_bin: str = "codex", timeout: int = 180,
                 model: Optional[str] = None, cwd: Optional[Path] = None,
                 system_prompt_path: Optional[str] = None):
        self.codex_bin = codex_bin
        self.timeout = timeout
        self.model = model or "gpt-5.6-sol"
        self.cwd = Path(cwd) if cwd is not None else PROMPT_DIR.parent
        prompt_path = Path(system_prompt_path) if system_prompt_path \
            else PROMPT_DIR / "auditor.md"
        self.system_prompt = prompt_path.read_text("utf-8")
        self.schema_path = SCHEMA_DIR / "audit-result.schema.json"

    def _call(self, bundle: EvidenceBundle, audit_id: str) -> Dict:
        task_input = json.dumps({
            "audit_id": audit_id,
            "task_id": bundle.task_spec.get("task_id", ""),
            "evidence_bundle": json.loads(bundle.to_prompt_text()),
            "instruction": ("Output ONLY an AuditResult JSON object matching "
                            "the schema with the supplied audit_id and "
                            "task_id."),
        }, ensure_ascii=False, indent=2)
        prompt = "%s\n\n# EvidenceBundle input\n%s" % (
            self.system_prompt, task_input)
        return run_codex_json(
            prompt=prompt,
            schema_path=self.schema_path,
            model=self.model,
            timeout=self.timeout,
            codex_bin=self.codex_bin,
            cwd=self.cwd,
        )

    @phase_call("auditor", role="auditor")
    def audit(self, bundle: EvidenceBundle, audit_id: str) -> AuditResult:
        obj = protocol_call(lambda: self._call(bundle, audit_id),
                            lambda obj: check_role(obj, "audit-result",
                                audit_id=audit_id, task_id=bundle.task_spec.get("task_id")))
        if obj["decision"] == "PASS":
            bundle.validate_evidence()
        return role_result(AuditResult, obj)


# Compatibility for legacy CLI modules outside this migration's edit scope.
# There is only one production Auditor implementation.
ClaudeCliAuditorProvider = CodexCliAuditorProvider
