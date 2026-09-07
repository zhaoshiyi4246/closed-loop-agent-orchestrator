"""ActionExecutor: a plain PROGRAM (not an agent).

Executes a fixed mapping from PlannerAction -> concrete AO CLI calls, with
idempotency (same action_id executes once) and budget enforcement
(max_local_fixes, max_replans, max_same_alerts from TaskSpec).

Forbidden: executing arbitrary Planner shell; handing Planner text to a shell;
auto-merge; deleting branches; modifying TaskSpec/tests; bypassing budgets.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from .mission_contracts import (PlannerAction, PlannerActionType, TaskSpec,
                        ProjectState)
from .event_normalizer import _epoch_seconds
from .state_store import StateStore
from .ao_adapter import AOAdapter


class ExternalOperationUnknown(RuntimeError):
    """Uncertain effect: callers park for human handling, never blindly replay."""


class AOProcessNotStarted(RuntimeError):
    """Only the CLI process-creation boundary can prove non-invocation."""


def operation_id(kind: str, *parts) -> str:
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return kind + ":" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class ActionResult:
    action_id: str
    action: str
    ok: bool
    detail: str
    new_state: Optional[str] = None
    new_worker_session_id: Optional[str] = None


import re as _re

# Shell-ish content guard for Planner-authored messages (簇六). Word
# boundaries matter: the old substring check matched "del " inside
# "model ", so a Planner message containing the word 'model' was rejected
# as shell injection and routed straight to HUMAN.
_SHELLISH = _re.compile(
    r"(&&|\||\brm\b|\bdel\b|\bRemove-Item\b)", _re.IGNORECASE)


def _shellish(text: str) -> bool:
    return bool(_SHELLISH.search(text or ""))


_SPAWN_SUMMARY_LIMIT = 1600
_HUMAN_SPAWN_SUMMARY_LIMIT = 400


def _sanitize_spawn_error(text: str) -> str:
    """Redact credentials, prompts and user-home paths from AO diagnostics."""
    value = str(text or "")
    value = _re.sub(
        r"(?is)(--prompt(?:=|\s+))(.+?)(?=\s+--[a-z][a-z-]*(?:=|\s)|$)",
        lambda match: match.group(1) + "[REDACTED]", value)
    value = _re.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)\S+",
        lambda match: match.group(1) + "[REDACTED]", value)
    value = _re.sub(
        r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}",
        "Bearer [REDACTED]", value)
    value = _re.sub(
        r"(?i)\b([A-Z0-9_]*(?:api[_-]?key|access[_-]?token|"
        r"refresh[_-]?token)|token|cookie)\b(\s*[:=]\s*)[^\s,;]+",
        lambda match: match.group(1) + match.group(2) + "[REDACTED]",
        value)
    value = _re.sub(
        r"(?i)\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,})\b",
        "[REDACTED]", value)
    value = _re.sub(
        r"(?i)(\[\s*request\s+)[^\]]+(\])",
        lambda match: match.group(1) + "[REDACTED]" + match.group(2),
        value)
    home = str(Path.home())
    for form in {home, home.replace("\\", "/")}:
        if form:
            value = _re.sub(_re.escape(form), "[HOME]", value,
                            flags=_re.IGNORECASE)
    value = _re.sub(
        r"(?i)\b[A-Z]:[\\/]Users[\\/][^\\/\s\"'<>]+",
        "[HOME]", value)
    value = _re.sub(
        r"(?i)(?<!\w)/(?:home|Users)/[^/\s\"'<>]+",
        "[HOME]", value)
    return " ".join(value.split())


class ActionExecutor:
    def __init__(self, ao_bin: str, data_dir: Optional[str],
                 run_file: Optional[str],
                 store: StateStore, worker_model: str = "",
                 max_spawn_attempts: int = 3,
                 spawn_backoff_seconds: int = 30,
                 max_transient_spawn_attempts: int = 8,
                 transient_spawn_backoff_seconds: int = 90,
                 adapter: Optional[AOAdapter] = None):
        self.ao_bin = ao_bin
        self.data_dir = data_dir
        self.run_file = str(run_file) if run_file else None
        self.store = store
        self.adapter = adapter or AOAdapter(run_file=run_file)
        # `ao spawn --model <m>`; empty deliberately selects the daemon
        # default. Production config pins gpt-5.6-sol for the Codex worker.
        self.worker_model = worker_model or ""
        self.local_fixes = 0
        self.replans = 0
        # 簇五: bounded initial-spawn retries (real-run evidence: session-38
        # was rebuilt 3 times by the dispatch loop while the daemon kept
        # rejecting the spawn). Cap attempts per task with linear backoff;
        # the caller escalates to HUMAN once the cap is reached.
        self.max_spawn_attempts = int(max_spawn_attempts or 3)
        self.spawn_backoff_seconds = int(spawn_backoff_seconds or 30)
        # Preserve historical counters/config compatibility. F05 never uses
        # transport diagnostics to authorize another invocation.
        self.max_transient_spawn_attempts = int(
            max_transient_spawn_attempts or 8)
        self.transient_spawn_backoff_seconds = int(
            transient_spawn_backoff_seconds or 90)
        self._last_spawn_error = ""
        self._last_spawn_classification = ""

    def _observe(self, op, status, reason, *, result=None, counters=(), **facts):
        saved = self.store.operation_observe(
            op["operation_id"], status, {"reason": reason, **facts}, result, counters)
        if saved["status"] == "UNKNOWN":
            self.store.record_alert("operation:" + op["operation_id"], {
                "alert_type": "EXTERNAL_OPERATION_UNKNOWN", "operation_id": op["operation_id"],
                "operation_kind": op["kind"], "target": op["target"],
                "summary": reason, "requires_human": True})
        return saved

    def _reconcile(self, op, counters=()):
        """AO 0.12.9 public reads only. Absence is NEVER proof of non-execution."""
        counters = op["request"].get("success_counters", counters)
        try:
            if op["kind"] == "spawn":
                req = op["request"]
                matches = [s for s in self.adapter.operation_sessions()
                           if s.get("displayName") == req["marker"]]
                if len(matches) != 1:
                    return self._observe(op, "UNKNOWN", "spawn correlation is absent or ambiguous",
                                         matches=len(matches))
                candidate = matches[0]
                sid = candidate.get("id")
                if not isinstance(sid, str) or not _re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", sid):
                    raise ValueError("invalid correlated session id")
                fact = self.adapter.operation_session(sid)
                if any(fact.get(k) != v for k, v in {
                        "projectId": op["target"], "displayName": req["marker"],
                        "harness": req["harness"], "kind": "worker", "mode": "chat"}.items()):
                    raise ValueError("correlated Session fields do not match intent")
                return self._observe(op, "SUCCEEDED", "exact persisted spawn marker identifies one Session",
                                     result={"session_id": sid}, counters=counters,
                                     isTerminated=fact["isTerminated"])
            if op["kind"] == "kill":
                fact = self.adapter.operation_session(op["target"])
                if fact["isTerminated"] is True and fact["status"] == "terminated":
                    return self._observe(op, "SUCCEEDED", "AO Session confirms termination",
                                         result={"session_id": op["target"]},
                                         isTerminated=True, session_status="terminated")
                # A current live fact also invalidates an old stop result after
                # an external restore. Never re-kill that new episode blindly.
                return self._observe(op, "UNKNOWN", "AO Session has not confirmed termination",
                                     isTerminated=fact["isTerminated"], session_status=fact["status"])
            conversation = self.adapter.operation_conversation(op["target"])
            return self._observe(op, "UNKNOWN", "ao send exposes no caller correlation key; conversation cannot prove this delivery",
                                 observed_messages=len(conversation["messages"]))
        except Exception as exc:
            return self._observe(op, "UNKNOWN", "AO reconciliation unavailable: " + type(exc).__name__)

    @staticmethod
    def _require_known(op):
        if op["status"] in ("UNKNOWN", "IN_FLIGHT", "NOT_STARTED"):
            reason = op["evidence"][-1]["fact"]["reason"] if op["evidence"] else "operation not dispatched"
            raise ExternalOperationUnknown("%s %s target=%s: %s" % (
                op["status"], op["operation_id"], op["target"], reason))
        return op["status"] == "SUCCEEDED"

    def reconcile_pending(self, owner_id: str) -> None:
        """A restart cannot skip an unresolved side effect to run later work."""
        for op in self.store.operations(owner_id):
            if op["status"] in ("IN_FLIGHT", "UNKNOWN"):
                self._require_known(self._reconcile(op))

    def _effect(self, op, args, *, timeout=120, counters=(), max_attempts=3):
        if op["status"] in ("SUCCEEDED", "FAILED"):
            return op
        if op["status"] in ("IN_FLIGHT", "UNKNOWN"):
            return self._reconcile(op, counters)
        if not self.store.operation_claim(op["operation_id"], max_attempts):
            current = self.store.operation(op["operation_id"])
            if current["status"] == "NOT_STARTED":
                raise ExternalOperationUnknown("operation not dispatched: stop, budget or unresolved operation blocks " + op["operation_id"])
            return current
        op = self.store.operation(op["operation_id"])
        try:
            proc = self._run(args, timeout=timeout)
        except AOProcessNotStarted:
            # Popen did not create a CLI process; unlike a transport error this
            # proves AO was not invoked. The same intent may retry within cap.
            return self._observe(op, "FAILED" if op["attempts"] >= max_attempts else "NOT_STARTED",
                                 "AO CLI process could not be created")
        except Exception as exc:
            # Do not stringify TimeoutExpired/CalledProcessError: their cmd
            # contains the full prompt or message. BaseException/crash leaves
            # the committed IN_FLIGHT record for a later read-only reconcile.
            self._observe(op, "IN_FLIGHT", "AO acknowledgement lost: " + type(exc).__name__)
            return self._reconcile(op, counters)
        if op["kind"] == "kill":
            self._observe(op, "IN_FLIGHT", "kill CLI returned; termination still requires AO fact",
                          returncode=proc.returncode)
            return self._reconcile(op)
        if proc.returncode == 0:
            if op["kind"] == "send":
                return self._observe(op, "SUCCEEDED", "AO accepted send (not proof of Worker consumption)",
                                     counters=counters)
            match = _re.fullmatch(r"spawned session ([A-Za-z0-9][A-Za-z0-9_-]{0,127}) \([^\r\n]+\)(?:[^\r\n]*)\s*",
                                 proc.stdout or "")
            if match:
                return self._observe(op, "SUCCEEDED", "AO spawn acknowledgement", counters=counters,
                                     result={"session_id": match.group(1)})
        self._observe(op, "IN_FLIGHT", "CLI failure or incomplete reply is not proof of no AO effect",
                      returncode=proc.returncode,
                      diagnostic=_sanitize_spawn_error((proc.stderr or "") + " " + (proc.stdout or ""))[:_SPAWN_SUMMARY_LIMIT])
        return self._reconcile(op, counters)

    def _spawn_args(self, project_id: str, harness: str, name: str,
                    prompt: str, include_model: bool = True) -> list:
        args = ["spawn", "--kind", "worker", "--project", project_id,
                "--harness", harness, "--name", name,
                "--mode", "chat", "--prompt", prompt]
        if include_model and self.worker_model:
            args += ["--model", self.worker_model]
        return args

    def _spawn(self, project_id: str, harness: str, name: str,
               prompt: str, *, identity: str, owner_id: str, counters=()) -> Optional[str]:
        request = {"harness": harness, "model": self.worker_model,
                   "success_counters": list(counters),
                   "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                   # AO echoes the exact 20-character displayName. This random
                   # 120-bit marker is correlation, NOT an AO idempotency key.
                   "marker": secrets.token_urlsafe(15)}
        op = self.store.ensure_operation(identity, "spawn", owner_id, project_id, request)
        op = self._effect(op, self._spawn_args(project_id, harness, op["request"]["marker"], prompt),
                          counters=counters, max_attempts=self.max_spawn_attempts)
        if op["status"] in ("UNKNOWN", "IN_FLIGHT"):
            self._require_known(op)
        if op["status"] == "SUCCEEDED":
            self._last_spawn_error = self._last_spawn_classification = ""
            return op["result"]["session_id"]
        self._last_spawn_error = (op["evidence"][-1]["fact"]["reason"] if op["evidence"]
                                  else "spawn not dispatched: stopped or blocked")
        self._last_spawn_classification = "persistent"
        return None

    def load_counters(self, task_id: str) -> None:
        """Reload budget counters from the persistent store (survives restart)."""
        self.local_fixes = self.store.counter_get("local_fixes:" + task_id)
        self.replans = self.store.counter_get("replans:" + task_id)

    def _env(self) -> Dict[str, str]:
        e = dict(os.environ)
        if self.run_file:
            e["AO_RUN_FILE"] = self.run_file
        return e

    def _run(self, args: list, timeout: float = 120) -> subprocess.CompletedProcess:
        argv = [self.ao_bin] + args
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, env=self._env(), encoding="utf-8", errors="replace")
        except (FileNotFoundError, PermissionError) as exc:
            raise AOProcessNotStarted(type(exc).__name__) from exc
        with proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()  # Stop the CLI child, not an AO Worker.
                proc.communicate()
                raise
            except BaseException:
                proc.kill()
                raise
            return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)

    def execute(self, action: PlannerAction, task: TaskSpec) -> ActionResult:
        # Idempotency: never execute the same action_id twice. On a
        # crash-resume the state machine may sit in the action's pending
        # state while the side effect already happened; the early return
        # must still carry the new_state the original execution produced,
        # otherwise the loop parks forever (real-run evidence: LOCAL_FIX
        # executed, process killed before the WORKER_RETRYING transition).
        if self.store.action_executed(action.action_id):
            prev = self.store.action_executed_result(action.action_id) or {}
            ok = bool(prev.get("ok", True))
            resume_state = {
                PlannerActionType.CONTINUE: ProjectState.WORKER_RUNNING,
                PlannerActionType.SEND_LOCAL_FIX:
                    ProjectState.WORKER_RETRYING if ok else ProjectState.HUMAN,
                PlannerActionType.REPLAN_SPAWN:
                    ProjectState.WORKER_RUNNING if ok else ProjectState.HUMAN,
                PlannerActionType.CANDIDATE_DONE: ProjectState.GATE_PENDING,
                PlannerActionType.HUMAN: ProjectState.HUMAN,
            }.get(action.action)
            # 簇五: a crash AFTER a successful REPLAN spawn but BEFORE the
            # task re-bind must still hand the new worker id back, or the
            # resumed loop keeps tracking the killed old worker.
            return ActionResult(action.action_id, action.action, ok,
                                "already executed (idempotent)",
                                new_state=resume_state,
                                new_worker_session_id=prev.get(
                                    "new_worker_session_id"))
        self.load_counters(task.task_id)
        try:
            if action.action == PlannerActionType.CONTINUE:
                res = self._continue(action, task)
            elif action.action == PlannerActionType.SEND_LOCAL_FIX:
                res = self._send_local_fix(action, task)
            elif action.action == PlannerActionType.REPLAN_SPAWN:
                res = self._replan_spawn(action, task)
            elif action.action == PlannerActionType.CANDIDATE_DONE:
                res = ActionResult(action.action_id, action.action, True,
                                   "candidate done -> GATE_PENDING",
                                   new_state=ProjectState.GATE_PENDING)
            elif action.action == PlannerActionType.HUMAN:
                res = ActionResult(action.action_id, action.action, True,
                                   "halted for human",
                                   new_state=ProjectState.HUMAN)
            else:
                return ActionResult(action.action_id, action.action, False,
                                    "unknown action")
            if not res.ok and res.new_state is None:
                # Proven non-invocation stays pending for a bounded retry;
                # recording it as executed would permanently suppress it.
                return res
            self.store.mark_action_executed(
                action.action_id,
                {"ok": res.ok, "detail": res.detail,
                 # 簇五: persisted so a crash-resume idempotent return can
                 # hand the replacement worker id back to the loop.
                 "new_worker_session_id": res.new_worker_session_id})
            return res
        except ExternalOperationUnknown as exc:
            return ActionResult(action.action_id, action.action, False,
                                str(exc), new_state=ProjectState.HUMAN)
        except Exception as exc:
            return ActionResult(action.action_id, action.action, False,
                                "action interrupted: " + type(exc).__name__,
                                new_state=ProjectState.HUMAN)

    def _continue(self, action, task) -> ActionResult:
        return ActionResult(action.action_id, action.action, True,
                            "continue observing",
                            new_state=ProjectState.WORKER_RUNNING)

    def spawn_cap_reached(self, task_id: str) -> bool:
        """Honor prior caps; new attempts require proven non-execution."""
        return (self.store.counter_get("spawn_attempts:" + task_id)
                >= self.max_spawn_attempts) or \
            (self.store.counter_get("spawn_transient:" + task_id)
             >= self.max_transient_spawn_attempts)

    def spawn_budget_detail(self, task_id: str) -> str:
        """Human-readable budget usage for halt messages / panel display."""
        detail = ("persistent %d/%d, transient %d/%d" % (
            self.store.counter_get("spawn_attempts:" + task_id),
            self.max_spawn_attempts,
            self.store.counter_get("spawn_transient:" + task_id),
            self.max_transient_spawn_attempts))
        if self._last_spawn_error:
            detail += "; last spawn failure: " + \
                self._last_spawn_error[:_HUMAN_SPAWN_SUMMARY_LIMIT]
        return detail

    def _spawn_backoff_pending(self, task_id: str) -> bool:
        next_at = self.store.counter_get("spawn_next_at:" + task_id)
        return bool(next_at) and _epoch_seconds() < next_at

    def spawn_initial_worker(self, task: TaskSpec) -> Optional[str]:
        """Spawn the first worker for a task (no prior worker_session_id).

        Uses task.objective as the prompt and task.worker_harness (default
        codex; the harness remains a TaskSpec field so the operator can switch
        without touching code).
        Returns the new session id or None on failure.

        Only proven CLI non-start may retry with bounded linear backoff.
        Missing/failed transport acknowledgement is reconciled or UNKNOWN.
        Historical retry counters are retained, but cannot authorize replay
        of an operation that might already have reached AO.
        """
        identity = operation_id("spawn-initial", task.task_id)
        prior = self.store.operation(identity)
        if (not prior or prior["status"] == "NOT_STARTED") and (
                self.spawn_cap_reached(task.task_id) or self._spawn_backoff_pending(task.task_id)):
            return None
        harness = getattr(task, "worker_harness", "codex") or "codex"
        gate = "; ".join(task.gate_commands or [])
        prompt = ("Task: %s\n\nAcceptance criteria:\n%s\n\n"
                  "Work within allowed paths only. Do not modify tests or "
                  "forbidden paths. Run the gate command when ready.\n\n"
                  "Environment (do NOT waste turns exploring):\n"
                  "- Your working directory IS your private worktree; all "
                  "paths above are relative to it. Do not cd elsewhere.\n"
                  "- python and pytest are installed and on PATH. Use "
                  "`python -m pytest ...` directly.\n"
                  "- Create/edit files with the Write/Edit tools directly; "
                  "no need for ls/cat/command -v probing.\n"
                  "- The gate command for this task: %s\n"
                  "- If python/pytest turns out to be unavailable in YOUR "
                  "shell, do NOT probe the environment (no which/where/"
                  "python -c exploration): just complete the file edits and "
                  "reply DONE — an external deterministic gate runs the "
                  "tests authoritatively.\n"
                  "- When the gate is green, reply DONE and stop."
                  % (task.objective,
                     "\n".join("- %s: %s" % (ac.id, ac.description)
                               for ac in task.acceptance_criteria),
                     gate or "(none)"))
        sid = self._spawn(task.project_id, harness,
                          ("worker-%s" % task.task_id)[:20], prompt,
                          identity=identity, owner_id=task.subtask_of or task.task_id)
        if sid:
            # success: clear ALL retry counters so a future legitimately
            # needed spawn (e.g. after a replan kill) starts fresh.
            for pfx in ("spawn_attempts:", "spawn_transient:",
                        "spawn_next_at:"):
                self.store.counter_delete_prefix(pfx + task.task_id)
            return sid
        final = self.store.operation(identity)
        if final["status"] == "FAILED":
            self.store.counter_set("spawn_attempts:" + task.task_id, self.max_spawn_attempts)
            return None
        classification = "persistent"
        n = self.store.counter_incr("spawn_attempts:" + task.task_id)
        backoff = self.spawn_backoff_seconds * n
        summary = self._last_spawn_error or "AO spawn failed without output"
        fingerprint = hashlib.sha256(
            summary.encode("utf-8")).hexdigest()[:12]
        alert_id = "spawn-failure:%s:%s:%d:%s" % (
            task.task_id, classification, n, fingerprint)
        self.store.record_alert(alert_id, {
            "alert_type": "SPAWN_FAILURE",
            "task_id": task.task_id,
            "classification": classification,
            "attempt": n,
            "summary": summary,
        })
        self.store.counter_set("spawn_next_at:" + task.task_id,
                               _epoch_seconds() + backoff)
        return None

    def _send_local_fix(self, action, task) -> ActionResult:
        identity = operation_id("send-action", action.action_id)
        prior = self.store.operation(identity)
        if not prior and self.local_fixes >= task.budgets["max_local_fixes"]:
            return ActionResult(action.action_id, action.action, False,
                                "max_local_fixes exceeded", ProjectState.HUMAN)
        if not action.target_session_id or _shellish(action.message or ""):
            return ActionResult(action.action_id, action.action, False,
                                "missing target or shell-like message", ProjectState.HUMAN)
        op = self._send(identity, task.subtask_of or task.task_id,
                        action.target_session_id, action.message or "",
                        counters=("local_fixes:" + task.task_id,))
        if op["status"] == "NOT_STARTED":
            return ActionResult(action.action_id, action.action, False,
                                "NOT_STARTED: CLI was not created; bounded retry pending")
        ok = self._require_known(op)
        self.load_counters(task.task_id)
        return ActionResult(action.action_id, action.action, ok,
                            "%s %s" % (op["status"], identity),
                            ProjectState.WORKER_RETRYING if ok else ProjectState.HUMAN)

    def _send(self, identity, owner_id, session_id, message, counters=()):
        op = self.store.ensure_operation(identity, "send", owner_id, session_id,
            {"message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
             "success_counters": list(counters)})
        # Ordinary AO send has no caller key. A missing ACK is reconciled to
        # UNKNOWN, even when an identical message appears in the conversation.
        return self._effect(op, ["send", "--session", session_id, "--message", message],
                            timeout=60, counters=counters)

    def _replan_spawn(self, action, task) -> ActionResult:
        identity = operation_id("spawn-replan", action.action_id)
        prior = self.store.operation(identity)
        if not prior and self.replans >= task.budgets["max_replans"]:
            return ActionResult(action.action_id, action.action, False,
                                "max_replans exceeded",
                                new_state=ProjectState.HUMAN)
        # Mission-level total-replan cap (budgets.max_total_replans): every
        # subtask of one mission shares ONE spawn budget so N subtasks can't
        # each burn max_replans spawns (N× the intended ceiling). Counted in
        # the store, so it survives restarts and applies across processes.
        parent = getattr(task, "subtask_of", None)
        if parent:
            limit = 0
            try:
                # read the parent mission's budget from its recorded spec
                row = self.store.load_task(parent)
                # mission budgets live on the MissionSpec, not TaskSpec —
                # read them from the missions table instead
                with self.store._lock:
                    cur = self.store._conn.execute(
                        "SELECT payload_json FROM missions WHERE mission_id=?",
                        (parent,))
                    r = cur.fetchone()
                if r:
                    limit = int((json.loads(r[0]).get("mission", {})
                                 .get("budgets", {})
                                 .get("max_total_replans", 0)) or 0)
            except Exception:
                limit = 0
            if limit > 0:
                key = "mission_replans:" + parent
                used = self.store.counter_get(key)
                if not prior and used >= limit:
                    return ActionResult(action.action_id, action.action,
                                        False,
                                        "mission max_total_replans exceeded "
                                        "(%d>=%d)" % (used, limit),
                                        new_state=ProjectState.HUMAN)
                # NOTE: the mission-level counter is incremented ONLY after a
                # successful spawn (below). Incrementing here (before spawn)
                # would (a) burn a slot on a failed spawn, and (b) on a crash
                # during spawn, double-charge on resume AND orphan the first
                # spawned worker (re-entry spawns a second one). The per-task
                # `replans:` counter follows the same "success-only" rule.
                mission_replan_key = key
            else:
                mission_replan_key = None
        else:
            mission_replan_key = None
        spec = action.replacement_task_spec or {}
        prompt = spec.get("objective", task.objective)
        harness = getattr(task, "worker_harness", "codex") or "codex"
        # Stop the old worker before spawning a new one (re-route, not fork).
        # `ao session kill` terminates the session cleanly; the worktree is kept.
        old_sid = action.target_session_id or task.worker_session_id
        if old_sid:
            if not self.kill_worker(old_sid, owner_id=task.subtask_of or task.task_id):
                raise ExternalOperationUnknown("replacement blocked: old Worker stop unconfirmed: " + old_sid)
        new_sid = self._spawn(task.project_id, harness,
                              ("replan-%s" % task.task_id)[:20], prompt,
                              identity=identity, owner_id=task.subtask_of or task.task_id,
                              counters=("replans:" + task.task_id,) +
                              ((mission_replan_key,) if mission_replan_key else ()))
        ok = new_sid is not None
        if not ok and self.store.operation(identity)["status"] == "NOT_STARTED":
            return ActionResult(action.action_id, action.action, False,
                                "NOT_STARTED: CLI was not created; bounded retry pending")
        self.load_counters(task.task_id)
        return ActionResult(action.action_id, action.action, ok,
                            ("spawned %s" % new_sid) if ok
                            else "replan spawn failed",
                            new_state=ProjectState.WORKER_RUNNING if ok
                            else ProjectState.HUMAN,
                            new_worker_session_id=new_sid)

    def kill_worker(self, session_id: str, *, owner_id: str = "") -> bool:
        """One stop intent per Session, with a fresh external stop fact.

        Stored success alone is insufficient after an external AO restore.
        UNKNOWN is only read again; no second kill is sent for that episode.
        """
        if not session_id:
            return False
        identity = operation_id("kill", session_id)
        prior = self.store.operation(identity)
        owner_id = prior["owner_id"] if prior else (owner_id or session_id)
        op = self.store.ensure_operation(identity, "kill", owner_id, session_id, {})
        if op["status"] != "NOT_STARTED":
            return self._reconcile(op)["status"] == "SUCCEEDED"
        try:
            fact = self.adapter.operation_session(session_id)
            if fact["isTerminated"] is True and fact["status"] == "terminated":
                return self._reconcile(op)["status"] == "SUCCEEDED"
        except Exception:
            pass  # first authorized kill may proceed, but never counts as stopped
        op = self._effect(op, ["session", "kill", session_id], timeout=30)
        return op["status"] == "SUCCEEDED"

    def nudge_worker(self, session_id: str, message: str, *, identity: str = "",
                     owner_id: str = "") -> bool:
        """L0/directive send uses the same intent barrier without fix-budget use."""
        if not session_id or not message or _shellish(message):
            return False
        identity = identity or operation_id("send-nudge", session_id, message)
        op = self._send(identity, owner_id or session_id, session_id, message)
        return self._require_known(op)
