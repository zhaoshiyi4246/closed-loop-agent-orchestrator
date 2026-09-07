"""F05 public AO v0.12.9 facts + real SQLite/Git, never a live AO/model.

CLI spawn/send have no idempotency key. The HTTP fake echoes the documented
SessionView fields and ordinary conversation messages, including their limits.
"""
import json
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock

import pytest

from loopcore.action_executor import ActionExecutor, ExternalOperationUnknown, AOProcessNotStarted, operation_id
from loopcore.ao_adapter import AOAdapter
from loopcore.mission_contracts import PlannerAction, PlannerActionType, TaskSpec
from loopcore.state_store import StateStore
from tests.sidecar_port.test_contracts import _task_spec
from tests.sidecar_port.test_mission import _mc, SINGLE_MISSION
from tests.test_f03_git_evidence import git, write


class Crash(BaseException):
    """Process death: bypass application Exception handlers."""


class FakeAO:
    def __init__(self):
        self.sessions = {}
        self.messages = []
        self.calls = []
        self.fault = None
        self.terminate = True
        self.read_error = False
        self.list_override = None
        self.before = None

    def session(self, sid, **fields):
        row = dict(id=sid, projectId="p", displayName="old", harness="codex",
                   kind="worker", mode="chat", isTerminated=False, status="running")
        row.update(fields)
        self.sessions[sid] = row
        return row

    def run(self, args, **kwargs):
        if self.before:
            self.before(args)
        self.calls.append(args)
        if args[0] == "spawn":
            sid = "worker-%s" % len(self.sessions)
            self.session(sid, projectId=args[args.index("--project") + 1],
                         displayName=args[args.index("--name") + 1])
            stdout = "spawned session %s (worker) with prompt (18 bytes)\n" % sid
        elif args[0] == "send":
            self.messages.append({"role": "user", "text": args[-1]})
            stdout = "sent\n"
        else:
            if self.terminate:
                self.sessions[args[-1]].update(isTerminated=True, status="terminated")
            stdout = "killed\n"
        if self.fault == "crash":
            raise Crash()
        if self.fault == "timeout":
            raise subprocess.TimeoutExpired(args, 1)
        if self.fault == "transport":
            raise ConnectionError("lost ACK")
        if self.fault == "file_error":
            raise FileNotFoundError("after effect, not a process-creation proof")
        return subprocess.CompletedProcess(args, 1 if self.fault == "false" else 0,
                                           "" if self.fault == "incomplete" else stdout, "")


@pytest.fixture
def ao():
    fake = FakeAO()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if fake.read_error:
                self.send_error(503)
                return
            if self.path == "/api/v1/sessions":
                payload = {"sessions": list(fake.sessions.values()) if fake.list_override is None else fake.list_override}
            elif self.path.endswith("/conversation"):
                payload = {"messages": fake.messages, "hasMore": False}
            else:
                sid = self.path.rsplit("/", 1)[-1]
                if sid not in fake.sessions:
                    self.send_error(404)
                    return
                payload = {"session": fake.sessions[sid]}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.adapter = AOAdapter(base_url="http://127.0.0.1:%d" % server.server_port, timeout=1)
    yield fake
    server.shutdown()
    server.server_close()
    thread.join()


def executor(path, ao):
    store = StateStore(path)
    ex = ActionExecutor("ao", None, None, store, adapter=ao.adapter)
    ex._run = ao.run
    return ex, store


def task():
    spec = _task_spec()
    spec.update(project_id="p", worker_session_id=None)
    return TaskSpec.from_dict(spec)


@pytest.mark.parametrize("fault", [None, "timeout", "transport", "file_error", "incomplete", "crash"])
def test_spawn_ack_loss_reopen_adopts_exact_worker(tmp_path, ao, fault):
    ex, store = executor(tmp_path / "state.db", ao)
    t = task()
    ao.fault = fault
    ao.before = lambda args: assert_intent_committed(store, "spawn")
    if fault == "crash":
        with pytest.raises(Crash):
            ex.spawn_initial_worker(t)
        assert store.operations()[0]["status"] == "IN_FLIGHT"
    else:
        assert ex.spawn_initial_worker(t) == "worker-0"
    marker = store.operations()[0]["request"]["marker"]
    assert len(marker) == 20
    store.close()
    ex, store = executor(tmp_path / "state.db", ao)
    for _ in range(3):
        assert ex.spawn_initial_worker(t) == "worker-0"
    assert len(ao.calls) == 1
    assert store.operations()[0]["status"] == "SUCCEEDED"
    assert store.operations()[0]["request"]["marker"] == marker
    store.close()


def assert_intent_committed(store, kind):
    # A second connection observes the intent before fake AO creates effects.
    other = StateStore(store.path)
    assert any(o["kind"] == kind and o["status"] == "IN_FLIGHT" for o in other.operations())
    other.close()


@pytest.mark.parametrize("mismatch", ["multiple", "absent", "renamed", "wrong_project", "malformed", "read_error"])
def test_spawn_ambiguous_unknown_never_reissues(tmp_path, ao, mismatch):
    ex, store = executor(tmp_path / "state.db", ao)
    ao.fault = "crash"
    t = task()
    with pytest.raises(Crash):
        ex.spawn_initial_worker(t)
    row = ao.sessions["worker-0"]
    if mismatch == "multiple":
        ao.sessions["other"] = dict(row, id="other")
    elif mismatch == "absent":
        ao.sessions.clear()
    elif mismatch == "renamed":
        row["displayName"] += "similar"
    elif mismatch == "wrong_project":
        row["projectId"] = "other"
    elif mismatch == "malformed":
        row["isTerminated"] = "false"
    else:
        ao.read_error = True
    for _ in range(3):
        store.close()
        ex, store = executor(tmp_path / "state.db", ao)
        with pytest.raises(ExternalOperationUnknown):
            ex.spawn_initial_worker(t)
        assert store.operations()[0]["status"] == "UNKNOWN"
    assert len(ao.calls) == 1
    assert store.operations()[0]["attempts"] == 1
    store.close()


@pytest.mark.parametrize("crash_at", ["effect", "before_save", "after_save"])
def test_send_crash_resume_no_duplicate_and_atomic_counter(tmp_path, ao, monkeypatch, crash_at):
    ex, store = executor(tmp_path / "state.db", ao)
    t = task()
    ao.session("w1")
    action = PlannerAction("fix-1", t.task_id, PlannerActionType.SEND_LOCAL_FIX,
                           "fix", target_session_id="w1", message="修复中文 output")
    ao.before = lambda args: assert_intent_committed(store, "send")
    original = store.operation_observe
    if crash_at == "effect":
        ao.fault = "crash"
    else:
        def crash_save(*args, **kw):
            if args[1] == "SUCCEEDED":
                if crash_at == "after_save":
                    original(*args, **kw)
                raise Crash()
            return original(*args, **kw)
        monkeypatch.setattr(store, "operation_observe", crash_save)
    with pytest.raises(Crash):
        ex.execute(action, t)
    store.close()
    ex, store = executor(tmp_path / "state.db", ao)
    for _ in range(3):
        result = ex.execute(action, t)
        assert result.ok is (crash_at == "after_save")
    assert len(ao.messages) == 1
    op = store.operations()[0]
    assert op["status"] == ("SUCCEEDED" if crash_at == "after_save" else "UNKNOWN")
    assert store.counter_get("local_fixes:" + t.task_id) == (1 if crash_at == "after_save" else 0)
    if crash_at != "after_save":
        assert result.new_state == "HUMAN"
        assert "no caller correlation key" in op["evidence"][-1]["fact"]["reason"]
    store.close()


@pytest.mark.parametrize("fault", [None, "false", "timeout", "transport", "crash"])
@pytest.mark.parametrize("terminated", [True, False])
def test_kill_requires_external_fact_and_never_blindly_repeats(tmp_path, ao, fault, terminated):
    ex, store = executor(tmp_path / "state.db", ao)
    ao.session("w1")
    ao.fault, ao.terminate = fault, terminated
    if fault == "crash":
        with pytest.raises(Crash):
            ex.kill_worker("w1")
    else:
        assert ex.kill_worker("w1") is terminated
    store.close()
    ex, store = executor(tmp_path / "state.db", ao)
    for _ in range(3):
        assert ex.kill_worker("w1") is terminated
    assert len(ao.calls) == 1
    assert store.operations()[0]["status"] == ("SUCCEEDED" if terminated else "UNKNOWN")
    # A later public fact resolves UNKNOWN; no second kill is necessary.
    ao.sessions["w1"].update(isTerminated=True, status="terminated")
    assert ex.kill_worker("w1") is True
    # An external restore invalidates an old stop fact, without killing anew.
    ao.sessions["w1"].update(isTerminated=False, status="idle")
    assert ex.kill_worker("w1") is False
    assert len(ao.calls) == 1
    store.close()


@pytest.mark.parametrize("status,flag", [("idle", False), ("exited", False), ("terminated", False), ("idle", True)])
def test_activity_and_inconsistent_termination_are_not_stop_proof(tmp_path, ao, status, flag):
    ex, store = executor(tmp_path / "state.db", ao)
    ao.session("w1", status=status, isTerminated=flag)
    ao.terminate = False
    assert ex.kill_worker("w1") is False
    assert store.operations()[0]["status"] == "UNKNOWN"
    store.close()


def test_prelaunch_failure_is_proven_not_executed_and_bounded(tmp_path, ao, monkeypatch):
    ex, store = executor(tmp_path / "state.db", ao)
    t = task()
    run = MagicMock(side_effect=AOProcessNotStarted("no CLI"))
    ex._run = run
    for i in range(3):
        monkeypatch.setattr("loopcore.action_executor._epoch_seconds", lambda: 1000 * (i + 1))
        assert ex.spawn_initial_worker(t) is None
        assert store.operations()[0]["status"] == ("FAILED" if i == 2 else "NOT_STARTED")
    assert ex.spawn_initial_worker(t) is None
    assert run.call_count == 3
    assert not ao.calls
    store.close()


@pytest.mark.parametrize("fault", ["false", "timeout", "transport"])
def test_replan_live_old_worker_blocks_replacement(tmp_path, ao, fault):
    ex, store = executor(tmp_path / "state.db", ao)
    ao.session("w1")
    ao.terminate, ao.fault = False, fault
    t = task()
    t.worker_session_id = "w1"
    action = PlannerAction("replan-1", t.task_id, PlannerActionType.REPLAN_SPAWN, "replan")
    for _ in range(3):
        result = ex.execute(action, t)
        assert not result.ok and result.new_state == "HUMAN"
    assert [a[0] for a in ao.calls] == ["session"]
    assert store.counter_get("replans:" + t.task_id) == 0
    store.close()


def test_replan_spawn_crash_recovers_session_and_charges_once(tmp_path, ao):
    ex, store = executor(tmp_path / "state.db", ao)
    ao.session("w1", isTerminated=True, status="terminated")
    t = task()
    t.worker_session_id = "w1"
    action = PlannerAction("replan-1", t.task_id, PlannerActionType.REPLAN_SPAWN, "replan")
    ao.fault = "crash"
    with pytest.raises(Crash):
        ex.execute(action, t)
    store.close()
    ex, store = executor(tmp_path / "state.db", ao)
    for _ in range(3):
        result = ex.execute(action, t)
        assert result.ok and result.new_worker_session_id == "worker-1"
    assert store.counter_get("replans:" + t.task_id) == 1
    assert len(ao.calls) == 1
    store.close()


def mission_with_ao(tmp_path, ao):
    mc, store = _mc(tmp_path, mission_data=SINGLE_MISSION)
    mc.adapter.operation_session.side_effect = ao.adapter.operation_session
    mc.adapter.operation_sessions.side_effect = ao.adapter.operation_sessions
    mc.adapter.operation_conversation.side_effect = ao.adapter.operation_conversation
    mc.executor._run = ao.run
    return mc, store


def worker_repo(tmp_path):
    path = tmp_path / "Worker 中文"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.name", "test")
    git(path, "config", "user.email", "test@example.invalid")
    write(path, "app.py", "source = 1\n")
    git(path, "add", ".")
    git(path, "commit", "-qm", "base")
    return path


@pytest.mark.parametrize("terminated", [True, False])
def test_real_mission_merge_only_after_termination(tmp_path, ao, monkeypatch, terminated):
    worker = worker_repo(tmp_path)
    mc, store = mission_with_ao(tmp_path, ao)
    mc.adapter.get_session_workspace.return_value = str(worker)
    mc.step()
    mc._dispatch_ready()
    sid, t = next(iter(mc.tasks.items()))
    write(worker, "app.py", "source = 2\n")
    store.record_transition(task_id=sid, from_state="WORKER_RUNNING", to_state="DONE", actor="test", reason="completed", evidence={})
    before = git(worker, "rev-parse", "HEAD")
    ao.fault, ao.terminate = "timeout", terminated
    commit = __import__("loopcore.worktree", fromlist=["commit_all"]).commit_all
    calls = []
    def checked_commit(*args, **kw):
        assert ao.sessions[t.worker_session_id]["isTerminated"] is True
        assert store.operation(operation_id("kill", t.worker_session_id))["status"] == "SUCCEEDED"
        calls.append("materialize")
        return commit(*args, **kw)
    monkeypatch.setattr("loopcore.worktree.commit_all", checked_commit)
    mc._merge_done()
    if terminated:
        assert calls == ["materialize"] and mc.merged == [sid]
        integration = mc._integration_wt()
        assert (Path(integration) / "app.py").read_text() == "source = 2\n"
    else:
        assert not calls and not mc.merged and mc.state == "HUMAN"
        assert git(worker, "rev-parse", "HEAD") == before
        assert store.operations(mc.mission.mission_id)[-1]["status"] == "UNKNOWN"
    assert len([a for a in ao.calls if a[0] == "session"]) == 1
    store.close()


def test_mission_crash_spawn_rehydrates_and_binds_without_second_spawn(tmp_path, ao):
    worker = worker_repo(tmp_path)
    mc, store = mission_with_ao(tmp_path, ao)
    mc.adapter.get_session_workspace.return_value = str(worker)
    mc.step()
    ao.fault = "crash"
    with pytest.raises(Crash):
        mc.step()
    assert len(ao.sessions) == 1
    store.close()
    mc, store = mission_with_ao(tmp_path, ao)
    mc.adapter.get_session_workspace.return_value = str(worker)
    mc.step()  # reconcile + hydrate persistent plan/tasks
    mc._dispatch_ready()
    assert next(iter(mc.tasks.values())).worker_session_id == "worker-0"
    assert len(ao.calls) == 1
    assert store.operations(mc.mission.mission_id)[0]["status"] == "SUCCEEDED"
    store.close()


def test_stop_receipt_survives_crash_and_unknown_cleanup_restarts(tmp_path, ao):
    mc, store = mission_with_ao(tmp_path, ao)
    mc.step()
    t = next(iter(mc.tasks.values()))
    t.worker_session_id = "w1"
    store.record_task(t.task_id, t.to_dict())
    ao.session("w1")
    ao.fault, ao.terminate = "crash", False
    ao.before = lambda args: assert_stop_received(store, mc.mission.mission_id)
    with pytest.raises(Crash):
        mc.request_stop()
    store.close()
    ao.before = None
    for _ in range(3):
        mc, store = mission_with_ao(tmp_path, ao)
        assert mc.step()["state"] == "HUMAN"
        row = mc._read_state()
        assert row["stop_request"]["source"] == "user"
        assert row["worker_stop"]["status"] == "UNKNOWN"
        assert "stop requested" in row["reason"]
        store.close()
    assert len(ao.calls) == 1


def assert_stop_received(store, mid):
    other = StateStore(store.path)
    assert other.mission_stop_requested(mid)
    other.close()


def test_stop_after_unbound_spawn_crash_reconciles_and_cleans_existing_worker(tmp_path, ao):
    mc, store = mission_with_ao(tmp_path, ao)
    mc.step()
    ao.fault = "crash"
    with pytest.raises(Crash):
        mc._dispatch_ready()
    assert not next(iter(mc.tasks.values())).worker_session_id
    ao.fault = None
    mc.request_stop()
    assert ao.sessions["worker-0"]["isTerminated"] is True
    assert mc._read_state()["worker_stop"]["status"] == "CONFIRMED"
    assert [a[0] for a in ao.calls] == ["spawn", "session"]
    store.close()


def test_two_store_claims_never_dispatch_same_intent_twice(tmp_path, ao):
    ex, store = executor(tmp_path / "state.db", ao)
    other = StateStore(store.path)
    op = store.ensure_operation("same", "send", "owner", "w1", {})
    assert store.operation_claim(op["operation_id"])
    assert not other.operation_claim(op["operation_id"])
    other.operation_observe("same", "UNKNOWN", {"reason": "ACK pending"})
    store.operation_observe("same", "SUCCEEDED", {"reason": "late ACK"})
    other.operation_observe("same", "UNKNOWN", {"reason": "stale read"})
    assert other.operation("same")["status"] == "SUCCEEDED"
    assert other.operation("same")["attempts"] == 1
    assert ex._observe(op, "UNKNOWN", "stale reconciliation")["status"] == "SUCCEEDED"
    assert not store.alert_seen("operation:same")
    other.close()
    store.close()


def test_real_missing_executable_can_retry_without_any_ao_effect(tmp_path, ao):
    store = StateStore(tmp_path / "state.db")
    ex = ActionExecutor(str(tmp_path / "missing.exe"), None, None, store, adapter=ao.adapter)
    assert ex.spawn_initial_worker(task()) is None
    assert store.operations()[0]["status"] == "NOT_STARTED"
    assert store.operations()[0]["attempts"] == 1
    assert not ao.sessions
    store.close()


@pytest.mark.parametrize("reply", [
    '{"session":{"id":"w1","isTerminated":false,"isTerminated":true,"status":"terminated"}}',
    '{"session":{"id":"other","isTerminated":true,"status":"terminated"}}',
    '{"session":{"id":"w1","status":"terminated"}}',
    'not JSON',
])
def test_unreliable_public_fact_is_unknown(tmp_path, ao, monkeypatch, reply):
    ex, store = executor(tmp_path / "state.db", ao)
    ao.session("w1")
    monkeypatch.setattr(ao.adapter, "_get_raw", lambda path: reply)
    assert ex.kill_worker("w1") is False
    assert store.operations()[0]["status"] == "UNKNOWN"
    assert ex.kill_worker("w1") is False
    assert len(ao.calls) == 1
    store.close()


def test_stop_receipt_blocks_a_prepared_effect_after_restart(tmp_path, ao):
    ex, store = executor(tmp_path / "state.db", ao)
    store.ensure_operation("prepared", "spawn", "mission", "p", {})
    store.request_mission_stop("mission")
    store.close()
    ex, store = executor(tmp_path / "state.db", ao)
    assert not store.operation_claim("prepared")
    assert store.operation("prepared")["status"] == "NOT_STARTED"
    assert not ao.calls
    assert not store.record_mission_state_atomic("mission", "MISSION_DONE", {})
    store.close()


def test_panel_stop_flag_follows_persisted_receipt(tmp_path, ao, monkeypatch):
    from panel.server import PanelState
    from types import SimpleNamespace
    mc, store = mission_with_ao(tmp_path, ao)
    panel = PanelState()
    panel.rt = SimpleNamespace(controller=mc)
    original = store.request_mission_stop
    def checked_receipt(mid):
        assert not panel.stop_flag.is_set()
        original(mid)
    monkeypatch.setattr(store, "request_mission_stop", checked_receipt)
    panel.stop()
    assert panel.stop_flag.is_set()
    assert store.mission_stop_requested(mc.mission.mission_id)
    assert mc._read_state()["worker_stop"]["status"] == "CONFIRMED"
    store.close()


def test_panel_failed_receipt_does_not_claim_stop(tmp_path, ao, monkeypatch):
    from panel.server import PanelState
    from types import SimpleNamespace
    mc, store = mission_with_ao(tmp_path, ao)
    panel = PanelState()
    panel.rt = SimpleNamespace(controller=mc)
    monkeypatch.setattr(store, "request_mission_stop", MagicMock(side_effect=OSError("disk full")))
    panel.stop()
    assert not panel.stop_flag.is_set()
    assert not store.mission_stop_requested(mc.mission.mission_id)
    assert "disk full" in panel.errors[-1]
    assert not ao.calls
    store.close()


def test_mission_resume_unknown_send_parks_before_any_materialization(tmp_path, ao, monkeypatch):
    mc, store = mission_with_ao(tmp_path, ao)
    mc.step()
    t = next(iter(mc.tasks.values()))
    t.worker_session_id = "w1"
    store.record_task(t.task_id, t.to_dict())
    ao.session("w1")
    action = PlannerAction("fix", t.task_id, PlannerActionType.SEND_LOCAL_FIX,
                           "fix", target_session_id="w1", message="fix source")
    ao.fault = "crash"
    with pytest.raises(Crash):
        mc.executor.execute(action, t)
    store.close()
    ao.fault = None
    mc, store = mission_with_ao(tmp_path, ao)
    materialize = MagicMock()
    monkeypatch.setattr("loopcore.worktree.commit_all", materialize)
    for _ in range(3):
        assert mc.step()["state"] == "HUMAN"
    materialize.assert_not_called()
    assert len(ao.messages) == 1
    assert store.operation(operation_id("send-action", "fix"))["status"] == "UNKNOWN"
    assert "no caller correlation key" in mc._read_state()["reason"]
    store.close()


def test_stop_during_spawn_adopts_late_ack_only_for_cleanup(tmp_path, ao):
    mc, store = mission_with_ao(tmp_path, ao)
    mc.step()
    def stop_before_ack(args):
        ao.before = None
        mc.request_stop()
    ao.before = stop_before_ack
    mc._dispatch_ready()
    assert mc.state == "HUMAN"
    assert ao.sessions["worker-0"]["isTerminated"] is True
    assert mc._read_state()["worker_stop"]["status"] == "CONFIRMED"
    mc.adapter.get_session_workspace.assert_not_called()
    assert [a[0] for a in ao.calls] == ["spawn", "session"]
    store.close()


@pytest.mark.parametrize("kind", [PlannerActionType.SEND_LOCAL_FIX, PlannerActionType.REPLAN_SPAWN])
@pytest.mark.parametrize("recover", [True, False])
def test_proven_unstarted_action_retries_bounded_across_reopen(tmp_path, ao, kind, recover):
    t = task()
    t.worker_session_id = "w1"
    ao.session("w1", isTerminated=True, status="terminated")
    action = PlannerAction("retry", t.task_id, kind, "retry",
                           target_session_id="w1", message="fix source")
    for attempt in range(3):
        ex, store = executor(tmp_path / "state.db", ao)
        if attempt < 2 or not recover:
            ex._run = MagicMock(side_effect=AOProcessNotStarted("CLI unavailable"))
        result = ex.execute(action, t)
        if attempt < 2:
            assert not result.ok and result.new_state is None
            assert not store.action_executed("retry")
        else:
            assert result.ok is recover
            assert store.action_executed("retry")
            op = next(o for o in store.operations() if o["kind"] != "kill")
            assert op["attempts"] == 3
            assert op["status"] == ("SUCCEEDED" if recover else "FAILED")
            assert ex.execute(action, t).ok is recover
        store.close()
    assert len(ao.calls) == (1 if recover else 0)


def test_closed_loop_unstarted_resume_keeps_one_pending_action(tmp_path, monkeypatch):
    from tests.test_crash_resume import _parked_loop, _pass_audit
    from loopcore.event_normalizer import stable_id
    from loopcore.mission_contracts import ProjectState
    loop, store = _parked_loop(tmp_path, monkeypatch, ProjectState.LOCAL_FIX_PENDING)
    audit = _pass_audit(loop.task.task_id)
    store.record_audit(audit["audit_id"], loop.task.task_id, audit)
    identity = stable_id("ACTION", audit["audit_id"], length=16)
    action = PlannerAction(identity, loop.task.task_id, PlannerActionType.SEND_LOCAL_FIX,
                           "fix", target_session_id=loop.task.worker_session_id, message="fix source")
    store.record_action(identity, loop.task.task_id, action.to_dict())
    loop.executor._run = MagicMock(side_effect=AOProcessNotStarted("unavailable CLI"))
    loop._collect_events = MagicMock()
    for expected in [ProjectState.LOCAL_FIX_PENDING, ProjectState.LOCAL_FIX_PENDING, ProjectState.HUMAN]:
        assert loop.step()["state"] == expected
    assert loop.executor._run.call_count == 3
    assert len(store.operations()) == 1
    assert store.operations()[0]["status"] == "FAILED"
    loop._collect_events.assert_not_called()  # do not create a different action while retrying
    store.close()
