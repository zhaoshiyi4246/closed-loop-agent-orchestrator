"""Integration Gate: run the pre-configured gate_commands in the Worker's
actual worktree and record exit code / stdout / stderr. All commands must
exit 0 to reach DONE. Gate failure -> INTEGRATION_FAILED evidence, re-enters
the loop (still bounded by budgets).

Gate NEVER runs commands invented by Auditor/Planner — only
TaskSpec.gate_commands, and NEVER through a shell (argv only): a gate command
is author-controlled configuration, so `>`/`|`/`&&` are not interpreted — a
command that needs a shell simply fails closed (visible in the evidence).

Repository-integrity watchdog: a read-only, content-sensitive Git snapshot is
captured before and after the command batch.  Gate commands may inspect the
Worker's existing dirty state, but may not change HEAD, index, tracked source,
or non-artifact untracked content while producing verification evidence.
"""
from __future__ import annotations

import os
import hashlib
from contextlib import nullcontext
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import worktree as wt
from .mission_contracts import TaskSpec
from .event_normalizer import now_iso
from .state_store import StateStore
from .diagnostics import Diagnostics
from .test_failures import extract_failure_ids


def _to_argv(cmd: str) -> List[str]:
    """Split a gate command into argv WITHOUT a shell.

    posix mode off on Windows (shlex posix=True would eat backslashes in
    paths); surrounding quotes stripped per token. Returns [] when the
    command cannot be parsed (fail-closed: caller records exit -1).

    The head token is resolved through PATH via shutil.which: on Windows,
    CreateProcess searches the PARENT PROCESS image directory before PATH —
    for a venv interpreter that is the BASE runtime's directory, so a bare
    `python` would silently resolve to the base interpreter (no pytest)
    instead of the venv the operator activated. which() honors PATH order.
    """
    import shutil
    try:
        parts = shlex.split(cmd or "", posix=(os.name != "nt"))
    except ValueError:
        return []
    if os.name == "nt":
        parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1]
                 and p[0] in ("\"", "'") else p for p in parts]
    parts = [p for p in parts if p]
    if parts:
        parts[0] = shutil.which(parts[0]) or parts[0]
    return parts


@dataclass
class GateRun:
    ok: bool
    results: List[dict]
    head_before: Optional[str] = None
    head_after: Optional[str] = None
    command_ok: bool = True
    integrity_ok: bool = True
    integrity_error: Optional[str] = None
    initial_clean: Optional[bool] = None
    state_digest_before: Optional[str] = None
    state_digest_after: Optional[str] = None
    record_ids: List[int] = field(default_factory=list)

    @property
    def head_mutated(self) -> bool:
        """True when running the gate MOVED the worktree's HEAD ref."""
        return bool(self.head_before and self.head_after
                    and self.head_before != self.head_after)

    def evidence(self) -> List[dict]:
        ev = [{"type": "integration_gate",
               "summary": ("pass" if self.ok else "fail") +
                          " commands=" + str(len(self.results)),
               "reference": "; ".join(
                   "exit=%s" % r.get("exit_code") for r in self.results)}]
        if not self.integrity_ok:
            ev.append({
                "type": "gate_repository_integrity",
                "summary": self.integrity_error or
                           "Gate repository integrity failed",
                "reference": (
                    "initial_clean=%s; head_before=%s; head_after=%s; "
                    "state_digest_before=%s; state_digest_after=%s" %
                    (self.initial_clean, self.head_before, self.head_after,
                     self.state_digest_before, self.state_digest_after)),
            })
        if self.head_mutated:
            ev.append({"type": "gate_head_mutation",
                       "summary": "gate execution moved HEAD %s -> %s"
                                  % (self.head_before, self.head_after),
                       "reference": "git rev-parse HEAD before/after"})
        return ev


class IntegrationGate:
    def __init__(self, store: StateStore, *, timeout_seconds=300, output_limit_chars=20000):
        self.store = store
        self.timeout_seconds = timeout_seconds
        self.output_limit_chars = output_limit_chars
        self.diagnostics = None

    def run(self, task: TaskSpec, worktree_path: str, *,
            require_clean: bool = False, phase: str = "task") -> GateRun:
        context = self.diagnostics.phase(phase + "_gate", task_id=task.task_id,
                                        reason="running configured Gate and repository integrity checks") if isinstance(self.diagnostics, Diagnostics) else nullcontext({})
        with context as fact:
            run = self._run(task, worktree_path, require_clean=require_clean, phase=phase)
            fact["result"] = "pass" if run.ok else "fail"
            return run

    def _run(self, task, worktree_path, *, require_clean=False, phase="task"):
        results = []
        record_ids = []
        cwd = Path(worktree_path)

        def finish(run):
            if not record_ids:
                record_ids.append(self.store.record_gate_run(
                    task_id=task.task_id, command="", cwd=str(cwd), exit_code=None,
                    started_at=now_iso(), ended_at=now_iso(), stdout="", stderr=""))
            run.record_ids = record_ids
            self.store.annotate_gate_runs(record_ids, self.store.gate_assessment(
                phase=phase,
                command=("pass" if run.command_ok else "fail") if results else "not_run",
                integrity="pass" if run.integrity_ok else "fail",
                integrity_reason=run.integrity_error or "",
                scope="not_applicable" if phase == "baseline" else "unknown"))
            return run

        try:
            before = wt.git_state_snapshot(str(cwd))
        except wt.GitStateSnapshotError as exc:
            return finish(GateRun(
                ok=False, results=results, command_ok=False,
                integrity_ok=False,
                integrity_error=("pre-Gate Git probe failed: %s" %
                                 str(exc)[:1000])))
        if require_clean and not before.clean:
            return finish(GateRun(
                ok=False, results=results, head_before=before.head,
                command_ok=False, integrity_ok=False,
                integrity_error="initial repository not clean",
                initial_clean=False, state_digest_before=before.digest))

        command_ok = True
        for cmd in task.gate_commands:
            started = now_iso()
            error_category = None
            argv = _to_argv(cmd)
            if not argv:
                exit_code, stdout, stderr = -1, "", \
                    "gate command unparseable as argv (shell is disabled)"
            else:
                try:
                    proc = subprocess.run(argv, shell=False, cwd=str(cwd),
                                          capture_output=True, text=True,
                                          timeout=self.timeout_seconds, encoding="utf-8",
                                          errors="replace")
                    exit_code = proc.returncode
                    stdout = (proc.stdout or "")
                    stderr = (proc.stderr or "")
                except subprocess.TimeoutExpired:
                    error_category = "TIMEOUT"
                    exit_code, stdout, stderr = -1, "", "Gate command timed out after %s seconds" % self.timeout_seconds
                except Exception as e:
                    error_category = type(e).__name__
                    exit_code, stdout, stderr = -1, "", str(e)
            ended = now_iso()
            failures = extract_failure_ids(stdout + stderr) if exit_code != 0 else []
            output = {"error_category": error_category, "timeout_seconds": self.timeout_seconds}
            def bounded(value, stream):
                metadata = {"original_length": len(value), "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                            "truncated": len(value) > self.output_limit_chars, "limit_chars": self.output_limit_chars}
                output[stream] = metadata
                if metadata["truncated"]:
                    return value[:self.output_limit_chars] + ("\n[loopcore] ... %d chars elided; original_length=%d sha256=%s" %
                           (len(value) - self.output_limit_chars, len(value), metadata["sha256"]))
                return value
            stdout, stderr = bounded(stdout, "stdout"), bounded(stderr, "stderr")
            results.append({"command": cmd, "argv": argv, "cwd": str(cwd),
                            "exit_code": exit_code, "failure_ids": failures, "output": output, "stdout": stdout,
                            "stderr": stderr, "started_at": started,
                            "ended_at": ended})
            record_ids.append(self.store.record_gate_run(task_id=task.task_id, command=cmd,
                cwd=str(cwd), exit_code=exit_code, started_at=started,
                ended_at=ended, stdout=stdout, stderr=stderr, output=output))
            if exit_code != 0:
                command_ok = False

        try:
            after = wt.git_state_snapshot(str(cwd))
        except wt.GitStateSnapshotError as exc:
            return finish(GateRun(
                ok=False, results=results, head_before=before.head,
                command_ok=command_ok, integrity_ok=False,
                integrity_error=("post-Gate Git probe failed: %s" %
                                 str(exc)[:1000]),
                initial_clean=before.clean,
                state_digest_before=before.digest))

        integrity_error = None
        if before.head != after.head:
            integrity_error = "Gate changed HEAD"
        elif before.digest != after.digest:
            integrity_error = "Gate changed repository state"
        integrity_ok = integrity_error is None
        return finish(GateRun(
            ok=command_ok and integrity_ok,
            results=results,
            head_before=before.head,
            head_after=after.head,
            command_ok=command_ok,
            integrity_ok=integrity_ok,
            integrity_error=integrity_error,
            initial_clean=before.clean,
            state_digest_before=before.digest,
            state_digest_after=after.digest,
        ))
