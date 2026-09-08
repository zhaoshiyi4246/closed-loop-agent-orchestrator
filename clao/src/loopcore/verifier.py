"""Independent read-only Verifier — the "is it actually correct?" role.

Orthogonal to the Auditor:
  Auditor : diagnoses WHAT WENT WRONG from incident evidence (alerts, events).
  Verifier: independently checks IS THE RESULT CORRECT — per-AC verdicts
            against the diff + gate output, plus anti-gaming review
            (worker modified tests, self-modified ACs, fabricated evidence,
            gate output inconsistent with claims).

Verifiers are READ-ONLY model agents using the shared ephemeral Codex CLI
boundary. Deterministic findings (path violations, changed-path facts) are
pre-computed by trusted code and injected into the prompt as facts; the model
does semantic review on top of them — never the reverse.

Providers:
  FakeVerifierProvider     - deterministic, for unit tests.
  CodexCliVerifierProvider - production verifier via the shared Codex CLI
                             structured-output boundary.
Transport failures propagate to the Controller's bounded step retry.  A
schema-invalid response is retried once; a second invalid response is a
provider protocol error, never a semantic FAIL verdict.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .diagnostics import phase_call

from .codex_cli import run_codex_json
from .structured import role_result
from .mission_contracts import AcCheck, VerifierResult, check_verifier
from .structured import (correlate, evidence_part, evidence_metadata,
                         require_complete, protocol_call)

PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
SCHEMA_DIR = PROMPT_DIR.parent / "schemas"


@dataclass
class VerifierInput:
    """Everything the Verifier sees. Assembled by trusted controller code."""
    task_spec: Dict
    diff: str = ""                     # git diff vs frozen base (trusted)
    gate_output: str = ""              # real command output from the gate
    changed_paths: List[str] = field(default_factory=list)
    deterministic_findings: List[str] = field(default_factory=list)
    # e.g. ["path violation: tests/test_x.py modified",
    #       "tests/ file changed by worker"]  (facts, pre-computed)
    # User directives addressed to the Verifier (panel channel,
    # owner-ruled): shown to the verifier alongside the trusted evidence.
    user_notes: List[str] = field(default_factory=list)

    def evidence_parts(self):
        return {
            "git_diff": evidence_part(self.diff, 6000, missing=bool(self.changed_paths) and not self.diff.strip()),
            "gate_output": evidence_part(self.gate_output, 6000, missing=not self.gate_output.strip()),
            "changed_paths": evidence_part(self.changed_paths, 6000),
            "deterministic_findings": evidence_part(self.deterministic_findings, 6000),
            "user_notes": evidence_part(self.user_notes, 6000),
        }

    def validate_evidence(self):
        correlate(self.task_spec, task_id=self.task_spec.get("task_id"))
        parts = self.evidence_parts()
        require_complete(parts)
        return evidence_metadata(parts)

    def to_prompt_text(self) -> str:
        parts = self.evidence_parts()
        return json.dumps({
            "task_spec": self.task_spec,
            "evidence": parts,
        }, ensure_ascii=False, indent=2, allow_nan=False)

    def validation_record(self, verify_id):
        import hashlib
        raw = self.to_prompt_text()
        return dict(version=1, request_id=verify_id,
                    target_id=self.task_spec["task_id"],
                    input_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                    evidence=self.validate_evidence())


class VerifierProvider:
    def verify(self, inp: VerifierInput, verify_id: str) -> VerifierResult:
        raise NotImplementedError


class FakeVerifierProvider(VerifierProvider):
    """Deterministic verifier for tests.

    PASS unless: any deterministic finding mentions a violation/tests change,
    or the gate output shows a failing summary line, or the diff contains no
    change at all (nothing to verify). Returns per-AC checks derived from the
    task spec AC ids.
    """
    def verify(self, inp: VerifierInput, verify_id: str) -> VerifierResult:
        acs = [a.get("id", "AC?") for a in
               (inp.task_spec.get("acceptance_criteria") or [])]
        red_flags = [f for f in inp.deterministic_findings
                     if "violation" in f.lower() or "tests/" in f.lower()
                     or "mutated head" in f.lower()]
        gate_bad = any(s in inp.gate_output for s in
                       (" failed", "FAILED", "ERROR", "Traceback"))
        nothing_done = not inp.changed_paths and not inp.diff.strip()
        verdict = "FAIL" if (red_flags or gate_bad or nothing_done) else "PASS"
        ac_checks = [AcCheck(ac_id=a,
                             verdict=("FAIL" if verdict == "FAIL" else "PASS"))
                     for a in acs]
        anti = []
        if red_flags:
            anti.append(AcCheck(ac_id="anti-gaming", verdict="FAIL",
                                note="; ".join(red_flags)))
        return VerifierResult(
            verify_id=verify_id,
            task_id=inp.task_spec["task_id"],
            verdict=verdict, ac_checks=ac_checks, anti_gaming=anti,
            summary="fake verifier: verdict=%s red_flags=%d gate_bad=%s"
                    % (verdict, len(red_flags), gate_bad))


class CodexCliVerifierProvider(VerifierProvider):
    """Production Verifier using ephemeral, read-only Codex CLI calls."""

    def __init__(self, *, codex_bin: str = "codex", timeout: int = 180,
                 model: Optional[str] = None, cwd: Optional[Path] = None,
                 system_prompt_path: Optional[str] = None, transport=None):
        self.codex_bin = codex_bin
        self.transport = transport
        self.retry_options = transport.retry_options if transport else {}
        self.timeout = timeout
        self.model = model or "gpt-5.6-sol"
        self.cwd = Path(cwd) if cwd is not None else PROMPT_DIR.parent
        prompt_path = Path(system_prompt_path) if system_prompt_path \
            else PROMPT_DIR / "verifier.md"
        self.system_prompt = prompt_path.read_text("utf-8")
        self.schema_path = SCHEMA_DIR / "verifier-result.schema.json"

    def _call(self, inp: VerifierInput, verify_id: str) -> Dict:
        task_input = json.dumps({
            "verify_id": verify_id,
            "task_id": inp.task_spec["task_id"],
            "verifier_input": json.loads(inp.to_prompt_text()),
            "instruction": ("Output ONLY a VerifierResult JSON object "
                            "matching the schema with the supplied verify_id "
                            "and task_id."),
        }, ensure_ascii=False, indent=2)
        prompt = "%s\n\n# VerifierInput\n%s" % (
            self.system_prompt, task_input)
        if self.transport is not None:
            return self.transport(prompt=prompt, schema_path=self.schema_path)
        return run_codex_json(
            prompt=prompt,
            schema_path=self.schema_path,
            model=self.model,
            timeout=self.timeout,
            codex_bin=self.codex_bin,
            cwd=self.cwd,
        )

    @phase_call("verifier", role="verifier")
    def verify(self, inp: VerifierInput, verify_id: str) -> VerifierResult:
        inp.validate_evidence()
        obj = protocol_call(lambda: self._call(inp, verify_id),
                            lambda obj: check_verifier(obj, verify_id, inp.task_spec), **self.retry_options)
        return role_result(VerifierResult, obj)


# Compatibility for legacy CLI modules outside this migration's edit scope.
# There is only one production Verifier implementation.
ClaudeCliVerifierProvider = CodexCliVerifierProvider
