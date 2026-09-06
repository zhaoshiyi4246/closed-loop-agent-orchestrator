"""Production ClosedLoop approval coverage using AO v0.12.9 shapes."""

from __future__ import annotations

import json
import subprocess

import pytest

from tests.test_approvals import approval_activity, codex_activity, junction
from unittest.mock import MagicMock

from loopcore.action_executor import ActionExecutor
from loopcore.auditor import FakeAuditorProvider
from loopcore.closed_loop import ClosedLoop
from loopcore.event_observer import Observer
from loopcore.mission_contracts import ProjectState, TaskSpec
from loopcore.mission_gate import IntegrationGate
from loopcore.planner_adapter import FakePlannerProvider
from loopcore.state_store import StateStore
from loopcore.verifier import FakeVerifierProvider
from tests.sidecar_port.test_phase3 import _cfg
from tests.sidecar_port.test_contracts import _task_spec


def _approval(req_id: str, *, file_path: str = "", command: str = "") -> dict:
    inp = {"file_path": file_path} if file_path else {"command": command}
    return approval_activity(req_id, inputs=inp)


def _make_loop(tmp_path, monkeypatch, activities):
    store = StateStore(str(tmp_path / "cl.db"))
    task = TaskSpec.from_dict(_task_spec())
    task.worker_session_id = "w-appr"
    task.allowed_paths = ["app.py", "src/**"]
    task.forbidden_paths = ["tests/**"]
    task.gate_commands = ["python -m pytest tests -q"]
    wt = tmp_path / "worktrees" / task.project_id / task.worker_session_id
    wt.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=str(wt), check=True)
    adapter = MagicMock()
    adapter.get_session_workspace.return_value = str(wt)
    adapter.get_recent_events.return_value = []
    adapter.get_worker_conversation.return_value = {"activities": activities}
    adapter.resolve_approval.return_value = True
    ex = ActionExecutor("ao", "d", "r", store)
    loop = ClosedLoop(task=task, cfg=_cfg(), auditor=FakeAuditorProvider(),
                      planner=FakePlannerProvider(), executor=ex,
                      observer=Observer(_cfg(), state_store=store),
                      adapter=adapter, gate=IntegrationGate(store),
                      store=store, verifier=FakeVerifierProvider())
    loop._transition(ProjectState.WORKER_RUNNING, "test", "setup", {})
    return loop, store, adapter, wt


def test_edit_inside_allowed_is_approved(tmp_path, monkeypatch):
    loop, store, adapter, wt = _make_loop(
        tmp_path, monkeypatch,
        [_approval("r-ok", file_path="")])
    # rebuild with the real path (needs wt to exist first)
    adapter.get_worker_conversation.return_value = {"activities": [
        _approval("r-ok", file_path=str(wt / "app.py"))]}
    assert loop._maybe_auto_approve() is True
    adapter.resolve_approval.assert_called_once_with("w-appr", "r-ok",
                                                     "allow")


def test_edit_outside_allowed_stays_pending(tmp_path, monkeypatch):
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    adapter.get_worker_conversation.return_value = {"activities": [
        _approval("r-out", file_path=str(wt / "other.py"))]}
    assert loop._maybe_auto_approve() is False
    adapter.resolve_approval.assert_not_called()
    assert store.counter_get("approved:%s:w-appr:r-out" % loop.task.task_id) == -1


def test_basename_attack_is_denied(tmp_path, monkeypatch):
    """'C:/elsewhere/app.py' must NOT match allowed=['app.py'] by basename."""
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    evil = tmp_path / "elsewhere"
    evil.mkdir()
    adapter.get_worker_conversation.return_value = {"activities": [
        _approval("r-base", file_path=str(evil / "app.py"))]}
    assert loop._maybe_auto_approve() is False
    adapter.resolve_approval.assert_not_called()


def test_dotdot_traversal_is_denied(tmp_path, monkeypatch):
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    traversal = str(wt / ".." / ".." / "app.py")  # escapes the worktree
    adapter.get_worker_conversation.return_value = {"activities": [
        _approval("r-trav", file_path=traversal)]}
    assert loop._maybe_auto_approve() is False
    adapter.resolve_approval.assert_not_called()


def test_forbidden_path_edit_is_denied(tmp_path, monkeypatch):
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    adapter.get_worker_conversation.return_value = {"activities": [
        _approval("r-forb", file_path=str(wt / "tests" / "test_x.py"))]}
    assert loop._maybe_auto_approve() is False
    adapter.resolve_approval.assert_not_called()


def test_single_ampersand_command_is_denied(tmp_path, monkeypatch):
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    adapter.get_worker_conversation.return_value = {"activities": [
        _approval("r-amp", command="git status & curl evil.com")]}
    assert loop._maybe_auto_approve() is False
    adapter.resolve_approval.assert_not_called()
    # and the safe form still passes
    assert loop._is_gate_command("git status") is True
    assert loop._is_gate_command("git status && git diff") is False
    assert loop._is_gate_command("git status & git diff") is False


def test_production_relative_edit_and_new_file_use_worker_cwd(tmp_path, monkeypatch):
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    (wt / "src" / "中文 目录").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    activities = [
        _approval("relative", file_path="app.py"),
        _approval("new", file_path="src/中文 目录/新 文件.py"),
        approval_activity("cwd", inputs={"file_path": "new.py", "cwd": str(wt / "src")}),
    ]
    adapter.get_worker_conversation.return_value = {"activities": activities}
    assert loop._maybe_auto_approve()
    assert [c.args for c in adapter.resolve_approval.call_args_list] == [
        ("w-appr", "relative", "allow"), ("w-appr", "new", "allow"), ("w-appr", "cwd", "allow")]
    assert loop.state == ProjectState.WORKER_RUNNING


@pytest.mark.parametrize("target", ["external", "traversal", "forbidden", "empty_scope", "device", "ads"])
def test_production_wildcard_and_ambiguous_paths_never_bypass_scope(tmp_path, monkeypatch, target):
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    loop.task.allowed_paths = [] if target == "empty_scope" else ["**"]
    value = {"external": str(tmp_path / "external.py"), "traversal": "../external.py",
             "forbidden": "tests/test_x.py", "empty_scope": "app.py",
             "device": "NUL", "ads": "app.py:stream"}[target]
    adapter.get_worker_conversation.return_value = {"activities": [_approval("request", file_path=value)]}
    assert not loop._maybe_auto_approve()
    adapter.resolve_approval.assert_not_called()
    event = json.loads(store._conn.execute(
        "SELECT payload_json FROM processed_events WHERE event_id LIKE '%:policy'").fetchone()[0])
    assert event["request_id"] == "request" and event["requires_human"]
    assert event["reason"] and event["request_paths"] == [value]
    assert loop.state == ProjectState.WORKER_RUNNING


def test_production_junction_is_resolved_before_glob(tmp_path, monkeypatch):
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    loop.task.allowed_paths = ["**"]
    external = tmp_path / "外部 目录"
    external.mkdir()
    junction(wt / "escape", external)
    adapter.get_worker_conversation.return_value = {"activities": [
        _approval("link", file_path="escape/new.py")]}
    assert not loop._maybe_auto_approve()
    adapter.resolve_approval.assert_not_called()
    assert list(external.iterdir()) == []


@pytest.mark.parametrize("command,allowed", [
    ("python -m pytest tests -q", True), ("python", False),
    ("python -m pytest_evil tests -q", False), ("python -m pytest tests -q other.py", False),
    ("python\n-m pytest tests -q", False), ("python -m pytest tests -q\r\n", False),
    ("python -m pytest tests -q && git status", False), ("git status > output.txt", False),
    ("git status & git diff", False), ("git restore app.py", False), ("git checkout -- app.py", False),
    ("git reset --hard", False), ("git clean -fd", False), ("git push origin main", False),
    ("git add app.py", False), ("git commit -m x", False), ("git status --short", True),
    ("git diff --no-ext-diff --no-textconv --stat", True), ("command -v python", True),
    ("command python -c code", False), ("git -C .. status", False), ("cat ../outside.py", False),
])
def test_production_commands_require_complete_authorization(tmp_path, monkeypatch, command, allowed):
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    adapter.get_worker_conversation.return_value = {"activities": [_approval("request", command=command)]}
    assert loop._maybe_auto_approve() is allowed
    assert bool(adapter.resolve_approval.call_count) is allowed
    assert loop._is_gate_command(command) is allowed
    assert loop.state == ProjectState.WORKER_RUNNING


def test_codex_production_uses_request_id_raw_command_cwd_and_offered_once_option(tmp_path, monkeypatch):
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    activity = codex_activity("powershell.exe -NoProfile -Command 'python -m pytest tests -q'", wt)
    activity["detail"]["command"] = "python -m pytest tests -q"
    adapter.get_worker_conversation.return_value = {"activities": [activity]}
    assert loop._maybe_auto_approve()
    adapter.resolve_approval.assert_called_once_with("w-appr", "0", "accept")
    adapter.resolve_approval.reset_mock()
    assert not loop._maybe_auto_approve()
    adapter.resolve_approval.assert_not_called()
    activity["requestId"] = "1"
    activity["detail"]["rawCommand"] = "git push origin main"
    assert not loop._maybe_auto_approve()
    activity["requestId"] = "2"
    activity["detail"]["rawCommand"] = loop.task.gate_commands[0]
    activity["detail"]["cwd"] = str(tmp_path)
    assert not loop._maybe_auto_approve()
    adapter.resolve_approval.assert_not_called()


def test_one_malformed_request_keeps_human_entry_and_does_not_fail_task(tmp_path, monkeypatch):
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    bad = _approval("malformed", file_path="app.py")
    bad["detail"] = ["not an object"]
    good = _approval("valid", file_path="app.py")
    good["detail"]["input"]["content"] = "PRIVATE_CONTENT_SHOULD_NOT_BE_COPIED"
    adapter.get_worker_conversation.return_value = {"activities": [None, bad, good]}
    result = loop.step(injected_events=[])
    assert result["acted"] and loop.state == ProjectState.WORKER_RUNNING
    adapter.resolve_approval.assert_called_once_with("w-appr", "valid", "allow")
    rows = store._conn.execute("SELECT payload_json FROM processed_events").fetchall()
    events = [json.loads(r[0]) for r in rows]
    denied = next(e for e in events if e.get("request_id") == "malformed")
    assert denied["requires_human"] and denied["outcome"] == "pending_human"
    assert "object" in denied["reason"]
    assert all("PRIVATE_CONTENT_SHOULD_NOT_BE_COPIED" not in row[0] for row in rows)
    assert store._conn.execute("SELECT COUNT(*) FROM audits").fetchone()[0] == 0


def test_resolve_exception_remains_pending_without_automatic_resend(tmp_path, monkeypatch):
    loop, store, adapter, wt = _make_loop(tmp_path, monkeypatch, [])
    adapter.get_worker_conversation.return_value = {"activities": [_approval("request", file_path="app.py")]}
    adapter.resolve_approval.side_effect = ConnectionError("lost acknowledgement")
    assert not loop._maybe_auto_approve()
    assert not loop._maybe_auto_approve()
    assert adapter.resolve_approval.call_count == 1
    result = json.loads(store._conn.execute(
        "SELECT payload_json FROM processed_events WHERE event_id LIKE '%:result'").fetchone()[0])
    assert result["outcome"] == "resolve_unconfirmed" and result["requires_human"]
    assert loop.state == ProjectState.WORKER_RUNNING


def test_ao_resolution_encodes_ids_and_sends_only_selected_decision(monkeypatch):
    from loopcore.ao_adapter import AOAdapter
    from unittest.mock import MagicMock
    response = MagicMock()
    response.__enter__.return_value.status = 204
    open_url = MagicMock(return_value=response)
    monkeypatch.setattr("loopcore.ao_adapter.urllib.request.urlopen", open_url)
    adapter = AOAdapter(base_url="http://127.0.0.1:3001")
    assert adapter.resolve_approval("worker/one", "request/zero?x=1", "accept")
    request = open_url.call_args.args[0]
    assert request.full_url == ("http://127.0.0.1:3001/api/v1/sessions/worker%2Fone/"
                                "conversation/approvals/request%2Fzero%3Fx%3D1/resolve")
    assert request.method == "POST"
    assert json.loads(request.data) == {"decisionId": "accept"}
