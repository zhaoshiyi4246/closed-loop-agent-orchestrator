"""Mission-level orchestration: ONE user instruction -> fully automatic run.

Architecture (the leader sits in the Planner, per the V0.1 audit docs —
there is deliberately NO coordinator agent):

    user --one instruction--> MissionSpec
       |
    max_subtasks=1 -> deterministic MissionPlan (no decomposition LLM)
    max_subtasks=2 -> Planner.plan_decompose() (returns 1 or 2 subtasks)
       |
    N x ClosedLoop (one per subtask, each with its own ao-spawned worker,
                    per-worker frozen base, budgets, audit->planner loop,
                    deterministic gate -> DONE)
       |
    integration merge (trusted code: commit + fetch + merge per subtask)
       |
    final gate + mission-level Verifier on the merged tree
       |
    MISSION_DONE / HUMAN (only human touchpoint)

The MissionController polls the project event stream ONCE per tick and routes
items to each subtask loop by session id (avoids N x API calls). Workers run
in parallel server-side (AO); the controller is single-threaded.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from time import time as _epoch_seconds
from .diagnostics import phase_call, Diagnostics, note_error

from . import worktree as wt
from .action_executor import ActionExecutor, ExternalOperationUnknown, operation_id
from .ao_adapter import AOAdapter, AOError
from .auditor import AuditorProvider
from .closed_loop import ClosedLoop
from .mission_contracts import (MissionPlan, MissionSpec, ProjectState,
                                SubtaskPlan, TaskSpec,
                                new_mission_max_subtasks, check_verifier, check_role,
                                VerifierResult)
from .structured import ProtocolError
from .mission_gate import IntegrationGate
from .event_observer import Observer
from .planner_adapter import PlannerProvider
from .state_store import StateStore
from .verifier import VerifierInput, VerifierProvider
from .event_normalizer import now_iso, make_id, stable_id

from .execution_control import ExecutionControl, ExecutionCancelled, checkpoint

MISSION_TERMINAL = ("MISSION_DONE", "HUMAN", "FAILED", "CANCELLED")


def deterministic_single_task_plan(mission: MissionSpec) -> MissionPlan:
    """Build the standard one-lane plan used when no decomposition is needed."""
    return MissionPlan(
        mission_id=mission.mission_id,
        strategy="deterministic single-worker plan",
        subtasks=[SubtaskPlan(
            subtask_id="%s-S1" % mission.mission_id,
            objective=mission.objective,
            allowed_paths=list(mission.allowed_paths),
            acceptance_criteria=list(mission.acceptance_criteria),
            gate_commands=list(mission.gate_commands),
            dependencies=[],
        )],
    )


class MissionController:
    def __init__(self, mission: MissionSpec, cfg: Dict, *,
                 planner: PlannerProvider,
                 auditor: AuditorProvider,
                 verifier: VerifierProvider,
                 executor: ActionExecutor,
                 adapter: AOAdapter,
                 gate: IntegrationGate,
                 store: StateStore,
                 dry_run: bool = False):
        self.mission = mission
        self.cfg = cfg
        self.planner = planner
        self.auditor = auditor
        self.verifier = verifier
        self.executor = executor
        self.adapter = adapter
        self.executor.adapter = adapter
        self.gate = gate
        self.store = store
        self.dry_run = dry_run
        self.plan: Optional[MissionPlan] = None
        self.tasks: Dict[str, TaskSpec] = {}        # subtask_id -> TaskSpec
        self.loops: Dict[str, ClosedLoop] = {}      # subtask_id -> loop
        self.merged: List[str] = []                 # subtask ids merged
        self._shared_observer = Observer(cfg, state_store=store)
        # user directives posted mid-mission (web panel / operator UI);
        # durable receipts are consumed at each target's actual input boundary.
        from .directives import DirectiveChannel
        self.directives = DirectiveChannel(store, mission.mission_id)
        # User-stop latch (panel /api/stop): set by request_stop(); every
        # controller checkpoint and every subtask loop (shared via
        # _build_loop) refuses to act once raised.
        self._stop_event = threading.Event()
        self.control = ExecutionControl(self._stop_event, store, mission.mission_id)
        if self.store.mission_stop_requested(self.mission.mission_id):
            self._stop_event.set()

    # ------------------------------------------------------------- state
    @property
    def state(self) -> str:
        return self._read_state().get("state", "MISSION_READY")

    def _set_state(self, s: str, reason: str) -> None:
        """Mission state lives in the store (per-DB, not a shared file) so
        parallel/renamed stores never cross-contaminate.

        The terminal-state check and the write happen atomically inside the
        store lock (record_mission_state_atomic), so a mission thread writing
        MISSION_DONE and a panel thread writing HUMAN via request_stop() cannot
        both pass the check and have the loser clobber the winner's terminal
        state. The first terminal write wins."""
        prev = self.state
        if self.store.mission_stop_requested(self.mission.mission_id) and s not in ("CANCELLING", "CANCELLED", "HUMAN"):
            return
        # Local pre-check keeps the common (non-racing) path cheap and lets us
        # skip worker cleanup when no transition actually occurs; the store's
        # atomic method is the source of truth under contention.
        if prev in MISSION_TERMINAL and s != prev:
            return
        if s == "MISSION_DONE" and not self.dry_run and not self._stop_workers():
            s, reason = "HUMAN", reason + "; Worker stop remains UNKNOWN"
        self._mission_row = {"state": s, "reason": reason, "at": now_iso()}
        # Only carry the plan when we hold one: with store-level merging, an
        # explicit "plan": null would erase a previously recorded plan.
        payload = {"reason": reason, "at": now_iso(),
                   "mission": {**(self.store.mission_config(self.mission.mission_id) or {}).get("mission", {}), **self.mission.to_dict()}}
        if self.plan is not None:
            payload["plan"] = self.plan.to_dict()
        merged = getattr(self, "merged", None)
        if merged:
            payload["merged"] = list(merged)
        landed = self.store.record_mission_state_atomic(
            self.mission.mission_id, s, payload)
        if not landed:
            # A concurrent terminal write won; do not run terminal cleanup for
            # a transition that did not land.
            self._mission_row = None  # force re-read from store next time
            return
        self._mission_row = None  # Re-read the complete durable payload, including receipts.
        if s in MISSION_TERMINAL:
            self._stop_event.set()
        if s in MISSION_TERMINAL and prev != s and not self.dry_run:
            if s != "CANCELLED" and not self.store.mission_stop_requested(self.mission.mission_id):
                self._stop_workers()
            self.store.reject_pending_directives(self.mission.mission_id, "Mission terminated before target consumption")

    def _stop_workers(self) -> bool:
        """Persist cleanup facts, including a spawn that crashed before binding.

        Recovery only reconciles dispatched operations; it cannot respawn or
        resend. A previously unattempted kill may run once to perform cleanup.
        """
        if self.dry_run:
            return True
        mid = self.mission.mission_id
        sessions = {t.worker_session_id for t in list(self.tasks.values()) if t.worker_session_id}
        if getattr(self.adapter, "backend", None) == "codex_app_server":
            # Include a thread bound before the executable turn ACK was lost.
            # Its spawn remains UNKNOWN even if an owned turn can be stopped.
            sessions.update(self.adapter.worker_ids())
        for tid in self.store.all_task_ids():
            task = self.store.load_task(tid) or {}
            if task.get("subtask_of") == mid and task.get("worker_session_id"):
                sessions.add(task["worker_session_id"])
        unresolved = []
        for op in self.store.operations(mid):
            if op["kind"] != "spawn":
                continue
            if op["status"] in ("IN_FLIGHT", "UNKNOWN"):
                op = self.executor._reconcile(op)
            if op["result"].get("session_id"):
                sessions.add(op["result"]["session_id"])
            if op["status"] in ("IN_FLIGHT", "UNKNOWN"):
                unresolved.append(op["operation_id"])
        unconfirmed = []
        for session in sorted(sessions):
            try:
                stopped = self.executor.kill_worker(session, owner_id=mid) is True
            except Exception as exc:
                stopped = False
                self.store.record_alert(make_id("STOP-UNKNOWN"), {
                    "alert_type": "WORKER_STOP_UNKNOWN", "mission_id": mid,
                    "target": session, "error": type(exc).__name__, "requires_human": True})
            if not stopped:
                unconfirmed.append(session)
        confirmed = not unconfirmed and not unresolved
        facts = {"status": "CONFIRMED" if confirmed else "UNKNOWN",
                 "sessions": sorted(sessions), "unconfirmed": unconfirmed,
                 "unresolved_spawns": unresolved, "checked_at": now_iso()}
        self.store.record_mission(mid, {"worker_stop": facts})
        if not confirmed:
            row = self._read_state()
            reason = row.get("reason", "")
            if "Worker stop remains UNKNOWN" not in reason:
                self.store.record_mission(mid, {"reason": reason + "; Worker stop remains UNKNOWN"})
            self.store.record_alert("stop-unknown:" + mid, {
                "alert_type": "WORKER_STOP_UNKNOWN", "mission_id": mid,
                "summary": "Worker stop remains UNKNOWN; cleanup requires reconciliation",
                "requires_human": True})
        self._mission_row = None
        return confirmed

    def _read_state(self) -> Dict:
        row = getattr(self, "_mission_row", None)
        if row:
            return row
        try:
            with self.store._lock:
                cur = self.store._conn.execute(
                    "SELECT payload_json FROM missions WHERE mission_id=?",
                    (self.mission.mission_id,))
                r = cur.fetchone()
            if r:
                return json.loads(r[0])
        except Exception:
            pass
        return {}

    # ------------------------------------------------------------- stop
    def request_stop(self) -> None:
        """Acknowledge only durable receipt; cleanup belongs to the runner."""
        self.store.request_mission_stop(self.mission.mission_id)
        self._stop_event.set()
        self._mission_row = None

    def _advance_cancel(self):
        mid = self.mission.mission_id
        self._stop_event.set()
        self._mission_row = None
        self.store.record_mission(mid, {'cancellation': dict(status='cancelling', at=now_iso(),
            reason='request received; confirming local execution and Worker stop facts')})
        self._set_state('CANCELLING', 'cancellation in progress')
        stopped = self._stop_workers()
        local_unknown = sorted(self.control.unconfirmed)
        local = (self.store.mission_config(mid) or {}).get('local_execution', {})
        if local.get('status') in ('running', 'unknown') and local.get('pid') not in local_unknown:
            local_unknown.append(local.get('pid'))
        confirmed = stopped and not local_unknown
        self.store.record_mission(mid, {'cancellation': dict(
            status='cancelled' if confirmed else 'unknown', at=now_iso(),
            reason='all controlled execution confirmed stopped' if confirmed else 'stop confirmation unavailable; human reconciliation required',
            local_unconfirmed=local_unknown)})
        self.store.reject_pending_directives(mid, 'cancelled before target consumption')
        self._set_state('CANCELLED' if confirmed else 'HUMAN',
                        'cancellation confirmed' if confirmed else 'cancellation stop facts UNKNOWN')
        return {'state': self.state, 'acted': True}

    # ------------------------------------------------------------- step
    # Consecutive mission-tick exceptions tolerated before halting to HUMAN
    # (mirrors ClosedLoop.MAX_CONSECUTIVE_LOOP_ERRORS; an unbounded retry
    # loop here re-dispatches subtasks and burns model calls every tick).
    MAX_CONSECUTIVE_LOOP_ERRORS = 3

    def step(self) -> Dict:
        """Top-level boundary (簇五): an unexpected error inside a tick must
        be recorded and returned, never propagated into the runner's while
        loop where it would kill the whole mission process.

        Bounded retries: after MAX_CONSECUTIVE_LOOP_ERRORS consecutive
        failures the mission halts to HUMAN instead of retrying forever (a
        successful tick resets the streak)."""
        try:
            if self.store.mission_stop_requested(self.mission.mission_id) and self.state not in MISSION_TERMINAL:
                return self._advance_cancel()
            with self.control.bind():
                result = self._step_impl()
                if self.state not in MISSION_TERMINAL:
                    checkpoint()
            self._loop_error_streak = 0
            return result
        except ExecutionCancelled:
            return self._advance_cancel()
        except ExternalOperationUnknown as exc:
            self._set_state("HUMAN", str(exc))
            return {"state": self.state, "acted": True, "error": str(exc)}
        except ProtocolError as exc:
            self.store.record_alert(make_id("PROTOCOL-MISSION"),
                                    dict(exc.payload(), mission_id=self.mission.mission_id))
            self._set_state("HUMAN", str(exc))
            return {"state": self.state, "acted": True, "error": str(exc)}
        except Exception as e:
            self._loop_error_streak = getattr(self, "_loop_error_streak", 0) + 1
            try:
                self.store.record_alert(
                    "LOOPERR-MISSION-%s-%d" % (self.mission.mission_id,
                                               _epoch_seconds()),
                    {"alert_type": "LOOP_ERROR",
                     "mission_id": self.mission.mission_id,
                     "state": self.state, "error": str(e)[:500],
                     "protocol_errors": getattr(e, "protocol_errors", []),
                     "consecutive": self._loop_error_streak})
            except Exception:
                pass
            if self._loop_error_streak >= self.MAX_CONSECUTIVE_LOOP_ERRORS:
                # Persistent fault: stop the retry loop; a human must look.
                self._loop_error_streak = 0
                try:
                    self._set_state("HUMAN",
                                    "consecutive loop errors (%d): %s: %s"
                                    % (self.MAX_CONSECUTIVE_LOOP_ERRORS,
                                       type(e).__name__, str(e)[:200]))
                except Exception:
                    pass
                return {"state": "HUMAN", "acted": True,
                        "error": "%s: %s" % (type(e).__name__, e)}
            return {"state": self.state, "acted": False,
                    "error": "%s: %s" % (type(e).__name__, e)}

    def _step_impl(self) -> Dict:
        result = {"state": self.state, "acted": False}
        if self.state in MISSION_TERMINAL:
            return result
        checkpoint()
        if not self.dry_run:
            self.executor.reconcile_pending(self.mission.mission_id)
        # mission runtime watchdog
        if self._runtime_exceeded():
            self._set_state("HUMAN", "mission max_runtime_seconds exceeded")
            result["state"] = "HUMAN"
            return result
        if self.plan is None:
            # restart recovery: a previous process may have already
            # decomposed (plan + tasks live in the store) — rehydrate
            # instead of re-decomposing (fresh subtask_ids would orphan
            # already-dispatched workers).
            if not self._hydrate():
                result["acted"] = True
                self._decompose()
            result["state"] = self.state
            return result
        # collect the project event stream ONCE, route per subtask
        self._collect_all_events()
        self._apply_directives()
        for sid, task in list(self.tasks.items()):
            if self._stop_event.is_set():
                result["state"] = self.state
                return result
            loop = self.loops.get(sid)
            if loop is None:
                continue
            if task.worker_session_id:
                evs = self._route_events(loop, task.worker_session_id)
            else:
                evs = []
            loop.step(injected_events=evs)
        if self._stop_event.is_set():
            result["state"] = self.state
            return result
        failed_before_dispatch = [sid for sid in self.tasks if self._subtask_state(sid) == ProjectState.FAILED]
        if failed_before_dispatch:
            self._set_state('FAILED', 'subtask(s) FAILED: ' + ', '.join(failed_before_dispatch))
            return dict(state=self.state, acted=True)
        # Dispatch independent subtasks only while the Mission can still succeed.
        self._dispatch_ready()
        if self._stop_event.is_set():
            result["state"] = self.state
            return result
        # merge finished subtasks into the integration worktree
        self._merge_done()
        # any subtask terminally FAILED -> the mission cannot deliver its
        # scope; escalate (watch loop exits instead of spinning forever)
        failed = [sid for sid in self.tasks
                  if self._subtask_state(sid) == ProjectState.FAILED]
        if failed:
            result["acted"] = True
            self._set_state("FAILED",
                            "subtask(s) FAILED: %s" % ", ".join(failed))
        # every subtask reached HUMAN and none can make progress -> mission
        # escalates too (a HUMAN subtask never self-recovers)
        elif all(self._subtask_state(sid) in (ProjectState.HUMAN,
                                              ProjectState.DONE)
                 for sid in self.tasks) \
                and any(self._subtask_state(sid) == ProjectState.HUMAN
                        for sid in self.tasks) \
                and not self._dispatchable():
            result["acted"] = True
            human = [sid for sid in self.tasks
                     if self._subtask_state(sid) == ProjectState.HUMAN]
            self._set_state("HUMAN",
                            "subtask(s) halted for human: %s" % ", ".join(human))
        # all subtasks DONE (+ merged) -> final gate + mission verifier
        elif not self._stop_event.is_set() \
                and self._all_done() and len(self.merged) == len(self.tasks):
            result["acted"] = True
            self._final_verify()
        result["state"] = self.state
        # refresh derived state
        st = self._read_state().get("state", "MISSION_READY")
        result["state"] = st
        return result

    # ------------------------------------------------------- decomposition
    def _hydrate(self) -> bool:
        """Rebuild plan/tasks/loops from the store after a process restart.
        Returns True when a plan was found (skip decomposition). A corrupted
        mission row is escalated to HUMAN (not re-decomposed) — fresh subtask_ids
        would orphan already-dispatched workers."""
        with self.store._lock:
            cur = self.store._conn.execute(
                "SELECT payload_json FROM missions WHERE mission_id=?",
                (self.mission.mission_id,))
            r = cur.fetchone()
        if not r:
            return False
        try:
            d = json.loads(r[0])
        except (ValueError, TypeError):
            # A partially-written/corrupted mission row (crash mid-write; WAL
            # lowers but does not eliminate this). Re-decomposing would mint
            # new subtask_ids and orphan workers already running under the old
            # ids -> fail closed to HUMAN instead.
            self._set_state("HUMAN",
                            "mission row corrupted on resume; manual review "
                            "required (re-decompose would orphan workers)")
            return True
        try:
            plan_d = d.get("plan")
            if not plan_d or not plan_d.get("subtasks"):
                return False
            self.plan = MissionPlan.from_dict(plan_d)
            if any(sub.dependencies for sub in self.plan.subtasks):
                raise ValueError("dependent MissionPlan is unsupported")
            self._mission_row = d
            # Restore the merged-subtask list so _all_done+merged can re-fire
            # final verify after a crash. Without this, merged==[] on resume;
            # if a subtask's worktree was since cleaned up, _merge_done skips it
            # forever and final verify never triggers (mission never terminates).
            restored = d.get("merged") or []
            if isinstance(restored, list):
                valid = {s.subtask_id for s in self.plan.subtasks}
                self.merged = [s for s in restored if s in valid]
        except Exception:
            self._set_state("HUMAN",
                            "mission plan unreadable on resume; manual review "
                            "required (re-decompose would orphan workers)")
            return True
        # tasks were recorded at decomposition/dispatch time; rebuild loops
        for sub in self.plan.subtasks:
            spec_d = self.store.load_task(sub.subtask_id)
            task = TaskSpec.from_dict(spec_d) if spec_d else None
            if task is None:            # never dispatched; rebuild from plan
                task = TaskSpec(
                    task_id=sub.subtask_id,
                    project_id=self.mission.project_id,
                    objective=sub.objective,
                    allowed_paths=sub.allowed_paths,
                    forbidden_paths=list(self.mission.forbidden_paths),
                    acceptance_criteria=sub.acceptance_criteria,
                    gate_commands=list(sub.gate_commands or
                                       self.mission.gate_commands),
                    dependencies=list(sub.dependencies),
                    worker_harness=self.mission.worker_harness,
                    budgets=dict(self.mission.budgets.get("subtask_budgets", {
                        "max_local_fixes": 2, "max_replans": 1,
                        "max_same_alerts": 2, "max_runtime_seconds": 1800})),
                    subtask_of=self.mission.mission_id)
            self.tasks[sub.subtask_id] = task
            self.loops[sub.subtask_id] = self._build_loop(task)
        return True

    def _build_loop(self, task: TaskSpec) -> ClosedLoop:
        loop = ClosedLoop(
            task=task, cfg=self.cfg, auditor=self.auditor,
            planner=self.planner, executor=self.executor,
            observer=self._shared_observer, adapter=self.adapter,
            gate=self.gate, store=self.store, verifier=self.verifier,
            dry_run=self.dry_run,
            instruct=self.mission.user_instruction,
            stop_event=self._stop_event)
        loop.directives = self.directives
        loop.diagnostics = getattr(self, "diagnostics", None)
        loop.board = self._progress_board
        loop.hold_spawn = True
        return loop

    def _decompose(self) -> None:
        try:
            max_subtasks = new_mission_max_subtasks(self.mission.budgets)
            if max_subtasks == 1:
                plan = deterministic_single_task_plan(self.mission)
            else:
                with self.directives.consume('planner', 'planner:decomposition') as notes:
                    spec = self.mission.to_dict()
                    spec['user_instruction'] = '\n'.join([self.mission.user_instruction] + notes)
                    plan = self.planner.plan_decompose(spec, "DECOMP-%s" % self.mission.mission_id)
                checkpoint()
            check_role(plan.to_dict(), "mission-plan", mission_id=self.mission.mission_id)
        except ProtocolError:
            raise
        except Exception as e:  # noqa
            self._set_state("HUMAN", "new mission decomposition rejected: %s" % e)
            return
        # Stopped while the planner was thinking: drop the plan entirely and
        # keep the cancellation receipt authoritative; do not materialize a plan.
        if self._stop_event.is_set():
            return
        if any(sub.dependencies for sub in plan.subtasks):
            self._set_state('HUMAN', 'dependent MissionPlan unsupported: downstream Worker has no verified upstream code delivery')
            return
        self.plan = plan
        self.store.record_mission(self.mission.mission_id, {
            "mission": {**(self.store.mission_config(self.mission.mission_id) or {}).get("mission", {}), **self.mission.to_dict()},
            "plan": plan.to_dict()})
        # An empty decomposition (LLM returned 0 subtasks) would leave
        # self.tasks empty -> _all_done() False forever, no terminal condition
        # tripped, mission spins until the runtime watchdog (if any) kills it.
        # Fail closed to HUMAN instead of looping on nothing.
        if not plan.subtasks:
            self._set_state("HUMAN",
                            "decomposition produced 0 subtasks "
                            "(empty plan from planner)")
            return
        # materialize one TaskSpec + ClosedLoop per subtask
        for sub in plan.subtasks:
            task = TaskSpec(
                task_id=sub.subtask_id,
                project_id=self.mission.project_id,
                objective=sub.objective,
                allowed_paths=sub.allowed_paths,
                forbidden_paths=list(self.mission.forbidden_paths),
                acceptance_criteria=sub.acceptance_criteria,
                # subtask worktrees lack sibling work — use the subtask's
                # own gates when the Planner provided them; the mission-wide
                # gate runs at final verify on the merged tree instead.
                gate_commands=list(sub.gate_commands or
                                   self.mission.gate_commands),
                dependencies=list(sub.dependencies),
                worker_harness=self.mission.worker_harness,
                budgets=dict(self.mission.budgets.get("subtask_budgets", {
                    "max_local_fixes": 2, "max_replans": 1,
                    "max_same_alerts": 2, "max_runtime_seconds": 1800})),
                subtask_of=self.mission.mission_id)
            self.tasks[sub.subtask_id] = task
            self.store.record_task(task.task_id, task.to_dict())
            self.loops[sub.subtask_id] = self._build_loop(task)

    # ---------------------------------------------------------- dispatch
    def _subtask_state(self, sid: str) -> str:
        return self.store.latest_state(sid) or ProjectState.TASK_READY

    def _dispatch_ready(self) -> None:
        for sid, task in self.tasks.items():
            if self._stop_event.is_set() or self.store.mission_stop_requested(self.mission.mission_id):
                return
            if task.worker_session_id:
                continue
            if self._subtask_state(sid) in (ProjectState.DONE,
                                            ProjectState.HUMAN,
                                            ProjectState.FAILED):
                continue
            if task.dependencies:
                self._set_state("HUMAN", "dependent MissionPlan unsupported: missing upstream code delivery")
                return
            if self.dry_run:
                continue
            # 簇五: bounded spawn retries — a task whose worker cannot be
            # spawned (daemon outage, quota 429) must not be re-attempted
            # every tick forever. After the cap the subtask goes HUMAN,
            # which escalates the mission through the normal path.
            if self.executor.spawn_cap_reached(task.task_id):
                loop = self.loops.get(sid)
                if loop is not None and self._subtask_state(sid) not in (
                        ProjectState.HUMAN, ProjectState.FAILED):
                    loop._halt_budget(
                        "initial worker spawn budget exhausted (%s)"
                        % self.executor.spawn_budget_detail(task.task_id))
                continue
            new_sid = self.executor.spawn_initial_worker(task)
            if new_sid:
                task.worker_session_id = new_sid
                self.store.record_task(task.task_id, task.to_dict())
                if self._stop_event.is_set() or self.store.mission_stop_requested(self.mission.mission_id):
                    return
                # freeze the per-worker diff base AT DISPATCH — before the
                # worker can commit. Freezing lazily (first gate/audit) loses
                # the race against workers that `git commit` mid-task, and
                # task evidence would then see an empty diff (real-run bug:
                # S1 implemented+committed divide yet verified as "no
                # source changes").
                worktree = self._worker_workspace(new_sid)
                if not worktree or not Path(worktree).is_dir():
                    self._set_state(
                        "HUMAN",
                        "AO workspace unavailable after spawning %s" % new_sid)
                    return
                base = wt.freeze_base(worktree, self.store,
                                      task.task_id, scope=new_sid,
                                      expected=(self.store.mission_config(self.mission.mission_id) or {}).get("source", {}).get("source_commit"))
                if not base:
                    self._set_state(
                        "HUMAN",
                        "unable to freeze audit base for Worker %s" % new_sid)
                    return

    # ------------------------------------------------------------ events
    def _apply_directives(self) -> None:
        # Semantic notes are read from durable receipts at actual input boundaries.
        # Only Worker delivery needs an action here, with the F05 stable identity.
        backend = 'codex_app_server' if getattr(self.adapter, 'backend', None) == 'codex_app_server' else 'ao'
        for row in self.directives.records():
            if not row['target'].startswith('worker:') or row['status'] not in ('received', 'unknown'):
                continue
            checkpoint()
            session = row['target'][7:]
            identity = operation_id('send-directive', self.mission.mission_id, row['command_id'])
            prior = self.store.operation(identity)
            if row['status'] == 'unknown' and prior is None:
                raise ExternalOperationUnknown('directive delivery unknown: ' + row['command_id'])
            self.store.directive_consumer(row['command_id'], backend + ':send:' + session, 'unknown',
                                          'Worker input acceptance not yet confirmed')
            try:
                ok = self.executor.nudge_worker(session, self.directives.text(row, row['target']),
                    identity=identity, owner_id=self.mission.mission_id) if not self.dry_run else False
            except ExternalOperationUnknown:
                pending_op = self.store.operation(identity)
                if pending_op and pending_op['status'] == 'NOT_STARTED':
                    self.store.directive_consumer(row['command_id'], backend + ':send:' + session, 'received', 'CLI not started; bounded retry pending')
                    continue
                raise
            op = self.store.operation(identity)
            status = 'applied' if ok else 'received' if op and op['status'] == 'NOT_STARTED' else 'rejected'
            self.store.directive_consumer(row['command_id'], backend + ':send:' + session, status,
                'Worker backend accepted message; execution NOT confirmed' if ok else
                'Worker transport not started; bounded retry pending' if status == 'received' else 'send rejected or confirmed failed')

    @phase_call("observation", role="observer")
    def _collect_all_events(self) -> None:
        """One API call; raw items cached for per-worker routing.
        A transient daemon hiccup (restart/unresponsive window) yields an
        empty snapshot for this tick instead of crashing the mission."""
        if getattr(self.adapter, "backend", None) == "codex_app_server":
            return  # notifications arrive on the existing stdio reader
        try:
            self._last_raw_items = self.adapter.get_recent_events(
                self.mission.project_id, since=0)
        except Exception as exc:
            note_error(exc)
            self._last_raw_items = []

    def _route_events(self, loop: ClosedLoop, worker_id: str) -> List:
        """Normalize raw AO items for ONE worker using the loop's own
        normalizer and per-worker activity cursor.

        Mission polling intentionally receives a replay/full-history project
        snapshot (one AO call per project tick). Sessions and turns retain
        their existing normalization semantics; only activities at or below
        this Worker Session's sequence cursor are suppressed.
        """
        if getattr(self.adapter, "backend", None) == "codex_app_server":
            return self.adapter.normalized_events(worker_id, self.mission.project_id)
        items = getattr(self, "_last_raw_items", []) or []
        diag = getattr(self, "diagnostics", None)
        if isinstance(diag, Diagnostics):
            for item in items:
                session = item.get("session") if item.get("kind") == "session" else None
                if isinstance(session, dict) and session.get("id") == worker_id:
                    activity = session.get("activity")
                    diag.worker_fact(worker_id, activity=(activity.get("state") if isinstance(activity, dict) else None) or session.get("status"),
                                     requested_model=self.cfg["worker"]["model"],
                                     spawn_resolved_model=session.get("model"))
        turn_times: Dict[str, Dict[str, str]] = {}
        pid = self.mission.project_id
        since = loop._event_since.get(worker_id, 0)
        max_seq = since
        for item in items:
            if item["kind"] == "turn":
                t = item["turn"]
                turn_times.setdefault(item["session_id"], {})[
                    str(t.get("id"))] = t.get("requestedAt") or \
                    t.get("completedAt")
        evs = []
        for item in items:
            if item.get("session_id") != worker_id:
                if item["kind"] == "session" and \
                        item["session"].get("id") == worker_id:
                    evs += loop.normalizer().from_session(item["session"])
                continue
            if item["kind"] == "session":
                evs += loop.normalizer().from_session(item["session"])
            elif item["kind"] == "turn":
                evs += loop.normalizer().from_turn(worker_id, pid,
                                                   item["turn"])
            elif item["kind"] == "activity":
                sequence = item["activity"].get("sequence") or 0
                if sequence <= since:
                    continue
                if sequence > max_seq:
                    max_seq = sequence
                evs += loop.normalizer().from_activity(
                    worker_id, pid, item["activity"],
                    turn_times.get(worker_id, {}), None)
        loop._event_since[worker_id] = max_seq
        return evs

    # ------------------------------------------------------------- merge
    def _worker_workspace(self, session_id: str) -> Optional[str]:
        """Resolve one live AO Session workspace, failing closed."""
        try:
            return self.adapter.get_session_workspace(session_id)
        except AOError:
            return None

    @phase_call("preparation")
    def _integration_wt(
            self, source_worktree: Optional[str] = None) -> Optional[str]:
        integ = Path(self.store.path).parent / "integration"
        if integ.exists():
            row = self.store.mission_config(self.mission.mission_id) or {}
            if row.get('source') and (
                    wt._read_base_sidecar(str(integ), self.mission.mission_id + ':integration') != row['source']['source_commit']
                    or wt._current_head(str(integ)) != row.get('integration_head')):
                return None
            return str(integ) if wt._current_head(str(integ)) else None

        # A caller that already resolved a live Worker workspace supplies it.
        # Recovery may instead find the first still-live task through the same
        # AO endpoint; neither path infers AO's filesystem layout.
        src = source_worktree
        if not src:
            for task in self.tasks.values():
                if not task.worker_session_id:
                    continue
                candidate = self._worker_workspace(task.worker_session_id)
                if candidate and Path(candidate).is_dir():
                    src = candidate
                    break
        if not src or not Path(src).is_dir():
            return None
        out = wt.add_integration_worktree(src, "integration-%s"
                                          % self.mission.mission_id,
                                          str(integ), source_commit=(self.store.mission_config(self.mission.mission_id) or {}).get("source", {}).get("source_commit"))
        if out:
            # freeze the mission base NOW — at integration-worktree creation,
            # BEFORE any subtask merge lands — so the final mission diff shows
            # what the whole mission delivered (freezing after the merges
            # would yield an empty diff vs the merge commits themselves).
            if not wt.freeze_base(out, self.store, self.mission.mission_id,
                                  scope="integration", expected=(self.store.mission_config(self.mission.mission_id) or {}).get("source", {}).get("source_commit")):
                self._set_state("HUMAN", "integration frozen base unavailable")
                return None
            self.store.record_mission(self.mission.mission_id, {"integration_head": wt._current_head(out)})
            if not self.merged:
                # Baseline failure set on the PRISTINE tree: pre-existing red
                # tests are recorded here so the final gate can separate them
                # from mission-caused failures (review 簇一).
                self._capture_baseline(out)
                if self.state == "HUMAN":
                    return None
        return out

    # ------------------------------------------------------ baseline gate
    def _baseline_sidecar(self) -> Path:
        return Path(str(self.store.path) + ".baseline-%s.json"
                    % self.mission.mission_id)

    def _capture_baseline(self, integ: str) -> List[str]:
        """Use the same clean-before/content-after watchdog as the Final Gate.

        Only a baseline with intact Git evidence may exempt known failures.
        Keep the existing sidecar and Gate records; do not invent a second
        executor or re-run an already captured baseline on a merged tree.
        """
        from .test_failures import extract_failure_ids
        p = self._baseline_sidecar()
        if p.exists():
            return self._baseline_failures()
        task = TaskSpec(
            task_id=self.mission.mission_id + "-baseline",
            project_id=self.mission.project_id,
            objective=self.mission.objective,
            allowed_paths=list(self.mission.allowed_paths),
            forbidden_paths=list(self.mission.forbidden_paths),
            acceptance_criteria=self.mission.acceptance_criteria,
            gate_commands=list(self.mission.gate_commands))
        run = self.gate.run(task, integ, require_clean=True, phase="baseline")
        checkpoint()
        failures = sorted({failure for result in run.results
                           if result.get("exit_code") != 0
                           for failure in result.get("failure_ids", extract_failure_ids(
                               (result.get("stdout") or "") + (result.get("stderr") or "")))})
        record = dict(failures=failures, integrity_ok=run.integrity_ok,
                      integrity_error=run.integrity_error,
                      initial_clean=run.initial_clean,
                      head_before=run.head_before, head_after=run.head_after,
                      state_digest_before=run.state_digest_before,
                      state_digest_after=run.state_digest_after,
                      commands=list(self.mission.gate_commands))
        try:
            p.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            self._set_state("HUMAN", "baseline evidence could not be saved: %s" % exc)
            return []
        if not run.integrity_ok:
            self._set_state("HUMAN", "baseline repository integrity failed: %s" %
                            run.integrity_error)
            return []
        return failures

    def _baseline_failures(self) -> List[str]:
        import re
        try:
            data = json.loads(self._baseline_sidecar().read_text(encoding="utf-8"))
            base = wt._read_base_sidecar(
                str(Path(self.store.path).parent / "integration"),
                self.mission.mission_id + ":integration")
            if (data.get("integrity_ok") is not True
                    or data.get("initial_clean") is not True
                    or not base or data.get("head_before") != base
                    or data.get("head_after") != base
                    or data.get("commands") != list(self.mission.gate_commands)
                    or not isinstance(data.get("state_digest_before"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", data["state_digest_before"])
                    or data.get("state_digest_before") != data.get("state_digest_after")
                    or not isinstance(data.get("failures"), list)
                    or any(not isinstance(f, str) or not f for f in data["failures"])):
                return []
            return sorted(set(data["failures"]))
        except (OSError, ValueError, TypeError, AttributeError):
            # Legacy/missing/damaged evidence never grants a red-test exemption.
            return []

    def _merge_done(self) -> None:
        if self.dry_run or self._stop_event.is_set() or self.state in MISSION_TERMINAL:
            return
        self.executor.reconcile_pending(self.mission.mission_id)
        for sid, task in self.tasks.items():
            if self.store.mission_stop_requested(self.mission.mission_id):
                return
            if sid in self.merged:
                continue
            if self._subtask_state(sid) != ProjectState.DONE:
                continue
            if not task.worker_session_id:
                continue
            worktree = self._worker_workspace(task.worker_session_id)
            if not worktree or not Path(worktree).is_dir():
                self._set_state(
                    "HUMAN", "Worker workspace unavailable for %s" % sid)
                return
            # No commit/materialization/merge until the backend's current
            # stop fact is confirmed. A transport acknowledgement is not it.
            if self.executor.kill_worker(task.worker_session_id, owner_id=self.mission.mission_id) is not True:
                self._set_state("HUMAN", "materialization blocked: Worker stop remains UNKNOWN: " + task.worker_session_id)
                return
            if self._stop_event.is_set() or self.store.mission_stop_requested(self.mission.mission_id):
                return
            try:
                # Dispatch froze this base before the Worker could commit.
                # Never refreeze at delivery time or merge an unfiltered HEAD.
                base = wt._read_base_sidecar(
                    worktree, task.task_id + ":" + task.worker_session_id)
                if not base:
                    raise RuntimeError("materialization requires an exact frozen base")
                diag = getattr(self, "diagnostics", None)
                if isinstance(diag, Diagnostics):
                    with diag.phase("materialization", task_id=sid, reason="Worker stop confirmed; constructing delivery commit") as fact:
                        delivery = wt.commit_all(worktree, "subtask %s" % sid, base_commit=base)
                        fact["result"] = "delivery commit constructed"
                else:
                    delivery = wt.commit_all(worktree, "subtask %s" % sid, base_commit=base)
            except RuntimeError as exc:
                detail = str(exc)[:1200]
                self._set_state(
                    "HUMAN",
                    "unable to commit Worker workspace for %s: %s"
                    % (sid, detail))
                return
            checkpoint()
            integ = self._integration_wt(source_worktree=worktree)
            if not integ:
                self._set_state("HUMAN",
                                "integration worktree unavailable for %s" % sid)
                return
            checkpoint()
            diag = getattr(self, "diagnostics", None)
            if isinstance(diag, Diagnostics):
                with diag.phase("merge", task_id=sid, reason="merging materialized commit into integration") as fact:
                    r = wt.merge_worktree(integ, worktree, source_commit=delivery)
                    fact["result"] = str(r.status)
            else:
                r = wt.merge_worktree(integ, worktree, source_commit=delivery)
            if r.status == wt.MergeOutcome.OK:
                self.merged.append(sid)
                # Persist merged so a crash-resume can re-fire final verify
                # even if this subtask's worktree is later cleaned up.
                self.store.record_mission(self.mission.mission_id,
                                          {"merged": list(self.merged), "integration_head": wt._current_head(integ)})
            elif r.status == wt.MergeOutcome.CONFLICT:
                # deterministic conflict -> human escalation (bounded)
                self._set_state("HUMAN",
                                "merge conflict on %s: %s" % (sid,
                                                              r.detail[:200]))
                return
            else:
                self._set_state("HUMAN",
                                "merge error on %s: %s" % (sid,
                                                           r.detail[:200]))
                return

    def _all_done(self) -> bool:
        # empty tasks means decomposition hasn't materialized anything (or
        # failed) — NOT "vacuously all done"
        if not self.plan or not self.tasks:
            return False
        return all(self._subtask_state(sid) == ProjectState.DONE
                   for sid in self.tasks)

    # ------------------------------------------------------ final verify
    def _final_verify(self) -> None:
        integ = self._integration_wt()
        if not integ:
            self._set_state("HUMAN", "no integration worktree")
            return
        # mission base was frozen at integration-worktree creation (BEFORE
        # any merge) — reuse it; the final diff is the whole mission's work.
        base = wt.freeze_base(integ, self.store, self.mission.mission_id,
                              scope="integration")
        final_task = TaskSpec(
            task_id=self.mission.mission_id,
            project_id=self.mission.project_id,
            objective=self.mission.objective,
            allowed_paths=list(self.mission.allowed_paths),
            forbidden_paths=list(self.mission.forbidden_paths),
            acceptance_criteria=self.mission.acceptance_criteria,
            gate_commands=list(self.mission.gate_commands))
        run = self.gate.run(final_task, integ, require_clean=True, phase="final")
        checkpoint()
        integrity_value = getattr(run, "integrity_ok", True)
        integrity_ok = integrity_value \
            if isinstance(integrity_value, bool) else True
        if not integrity_ok:
            detail = getattr(run, "integrity_error", None)
            if not isinstance(detail, str) or not detail:
                detail = "unknown repository integrity failure"
            self._set_state(
                "HUMAN", "final gate repository integrity failed: %s" %
                detail[:1000])
            return
        gate_output = "\n".join(
            "$ %s\n%s%s" % (r.get("command", ""), r.get("stdout", ""),
                            r.get("stderr", "")) for r in run.results)
        changed = wt.changed_paths(integ, base)
        if changed is None:
            # fail-closed: an unauditable merged tree must not reach the
            # verifier as 'clean' (review 簇四).
            self.store.record_gate_scope(run, status="fail", reason="Git scope evidence unavailable")
            self._set_state("HUMAN", "final evidence unavailable: git error "
                                     "reading the integration tree")
            return
        # Separate mission-caused failures from pre-existing (baseline) ones.
        # Legacy red tests are reported but never block MISSION_DONE; NEW
        # failures remain fatal (review 簇一).
        from .test_failures import extract_failure_ids
        command_value = getattr(run, "command_ok", run.ok)
        command_ok = command_value \
            if isinstance(command_value, bool) else bool(run.ok)
        current_failures = (sorted({f for r in run.results for f in r["failure_ids"]})
                            if all("failure_ids" in r for r in run.results) else extract_failure_ids(gate_output)) if not command_ok else []
        baseline = set(self._baseline_failures())
        new_failures = [f for f in current_failures if f not in baseline]
        legacy_failures = [f for f in current_failures if f in baseline]
        gate_clean = integrity_ok and (
            command_ok or (current_failures and not new_failures))
        findings = []
        if legacy_failures:
            findings.append("pre-existing (baseline) test failures, not "
                            "caused by this mission: %s"
                            % ", ".join(legacy_failures))
        if new_failures:
            findings.append("final gate commands failed on NEW failures: %s"
                            % ", ".join(new_failures))
        elif not command_ok and not current_failures:
            findings.append("final gate commands failed")
        # Scope and the Verifier use the exact same complete path set.
        forbidden, outside = wt.scope_violations(
            changed, allowed_paths=self.mission.allowed_paths,
            forbidden_paths=self.mission.forbidden_paths)
        self.store.record_gate_scope(
            run, status="fail" if forbidden or outside else "pass",
            reason="; ".join("path violation: " + p for p in forbidden + outside))
        if forbidden or outside or not gate_clean:
            self._set_state("HUMAN", "final deterministic failure: " +
                            "; ".join(findings + ["path violation: " + p for p in forbidden + outside]))
            return
        # Existing VerifierResult.task_id represents the mission target here.
        # The trusted caller supplies this mapping explicitly.
        final_spec = final_task.to_dict()
        final_spec["mission_id"] = self.mission.mission_id
        directive_rows = self.directives.for_role("verifier")
        inp = VerifierInput(
            task_spec=final_spec,
            diff=wt.git_diff_text(integ, base, limit=None),
            gate_output=gate_output,
            changed_paths=changed,
            deterministic_findings=findings,
            user_notes=[self.directives.text(row, "verifier") for row in directive_rows])
        vid = stable_id("VERIFY-MISSION", self.mission.mission_id, base, length=16)
        validation = inp.validation_record(vid)
        prior = self.store.latest_verification(self.mission.mission_id)
        if prior is not None:
            check_verifier(prior, vid, final_spec)
            if prior.get("_validation") != validation:
                raise ProtocolError("EVIDENCE_MISSING", "saved final verification lacks matching validated input",
                                    evidence=validation["evidence"])
            res = VerifierResult.from_dict(prior)
        else:
            with self.directives.consume('verifier', 'verifier:mission-final', rows=directive_rows):
                res = self.verifier.verify(inp, vid)
            checkpoint()
            payload = res.to_dict()
            check_verifier(payload, vid, final_spec)
            res = VerifierResult.from_dict(payload)
            payload["_validation"] = validation
            self.store.record_verification(vid, self.mission.mission_id, payload)
        if res.verdict == "PASS" and gate_clean:
            note = "final gate pass + verifier PASS"
            if legacy_failures:
                note += " (legacy baseline failures tolerated: %s)" \
                        % ", ".join(legacy_failures)
            self._set_state("MISSION_DONE", note)
        else:
            self._set_state("HUMAN",
                            "final verification failed: %s"
                            % res.summary[:200])

    def _dispatchable(self) -> bool:
        """Any not-yet-dispatched subtask whose deps are all DONE?"""
        for sid, task in self.tasks.items():
            if task.worker_session_id:
                continue
            if self._subtask_state(sid) in (ProjectState.DONE,
                                            ProjectState.HUMAN,
                                            ProjectState.FAILED):
                continue
            if all(self._subtask_state(d) == ProjectState.DONE
                   for d in task.dependencies):
                return True
        return False

    # ------------------------------------------------------------ budgets
    def _runtime_exceeded(self) -> bool:
        limit = float(self.mission.budgets.get("max_runtime_seconds", 0) or 0)
        if limit <= 0:
            return False
        key = "mission_started_at:" + self.mission.mission_id
        started = self.store.counter_get(key)
        if not started:
            self.store.counter_set(key, _epoch_seconds())
            return False
        return (_epoch_seconds() - float(started)) > limit

    # ------------------------------------------------------------ board
    def _progress_board(self) -> Dict:
        """Global view for the Planner prompt: subtasks/workers/states/
        budgets/recent audits + verifier results + last plan."""
        subs = []
        for sid, task in self.tasks.items():
            loop = self.loops.get(sid)
            subs.append({
                "subtask_id": sid,
                "worker_session_id": task.worker_session_id,
                "state": self._subtask_state(sid),
                "merged": sid in self.merged,
                "local_fixes": self.executor.local_fixes if loop else 0,
                "replans": self.executor.replans if loop else 0,
                "objective": task.objective[:200],
            })
        return {
            "mission_id": self.mission.mission_id,
            "user_instruction": self.mission.user_instruction,
            "strategy": self.plan.strategy if self.plan else "",
            "subtasks": subs,
            "merged_count": len(self.merged),
        }
