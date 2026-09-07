"""R01 product paths: shared runtime, persisted config, SQLite/HTTP and real Gate."""
import copy
import json
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import run_mission
from panel import server
from loopcore import effective_config as config
from loopcore.diagnostics import Diagnostics
from loopcore.mission import deterministic_single_task_plan
from loopcore.mission_contracts import MissionSpec, TaskSpec
from loopcore.mission_gate import IntegrationGate
from loopcore.state_store import StateStore
from loopcore.structured import ProtocolError, evidence_part, require_complete
from tests.test_f04_panel_boundaries import panel, http_panel, request, _browser_executable
from tests.test_mission_gate import _repo
from tests.sidecar_port.test_contracts import _task_spec


def mission(mid):
    return {"mission_id": mid, "project_id": "P", "objective": "normal source change 中文",
            "allowed_paths": ["app.py"], "forbidden_paths": [".git/**"],
            "acceptance_criteria": [{"id": "AC1", "description": "works"}], "gate_commands": []}


@pytest.fixture
def runtime_root(tmp_path, monkeypatch):
    root = tmp_path / "产品 中文"
    (root / "config").mkdir(parents=True)
    (root / "config" / "default.yaml").write_bytes((run_mission.ROOT / "config" / "default.yaml").read_bytes())
    monkeypatch.setattr(run_mission, "ROOT", root)
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(run_mission, "setup_environment", lambda **kw: None)
    monkeypatch.setattr(run_mission, "mission_preflight", lambda *a: {
        "ao_bin": "fake-ao", "ao_run_file": root / "no-runfile", "project_path": root})
    return root


@pytest.mark.parametrize("updates", [
    {"runner": {"poll_seconds": 0}}, {"runner": {"poll_seconds": -1}},
    {"gate": {"timeout_seconds": True}}, {"gate": {"timeout_seconds": float("nan")}},
    {"gate": {"timeout_seconds": 10**1000}}, {"ao": {"base_url": "http://127.0.0.1:\n3001"}},
    {"gate": {"timeout_seconds": float("inf")}}, {"gate": {"output_limit_chars": 3.1}},
    {"worker": {"spawn_max_attempts": "3"}}, {"budgets": {"max_total_replans": False}},
    {"roles": {"worker": {"model": "a"}}, "worker": {"model": "b"}},
    {"roles": {"planner": {"temperature": 0.2}}}, {"api_key": "SECRET_MUST_NOT_APPEAR"},
    {"ao": {"base_url": "http://user:SECRET@localhost:3001"}},
])
def test_invalid_config_rejected_without_values_in_error(updates):
    with pytest.raises(config.ConfigError) as caught:
        config.resolve_config(updates)
    assert "SECRET" not in str(caught.value)


def test_legacy_alias_and_dead_options_are_explicit(tmp_path):
    cfg = config.resolve_config({"roles": {"worker": {"model": "old-model"}, "max_parallel_workers": 2},
                                 "ao": {"poll_interval_seconds": 3}})
    assert cfg["worker"]["model"] == "old-model"
    assert "worker" not in cfg["roles"] and "max_parallel_workers" not in cfg["roles"]
    assert "poll_interval_seconds" not in cfg["ao"]
    assert any("migrated" in w for w in cfg.warnings)
    assert sum("NOT effective" in w for w in cfg.warnings) == 2
    path = tmp_path / "duplicate.yaml"
    path.write_text("worker:\n  model: a\n  model: b\n", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="duplicate"):
        config.load_config(path)


def test_http_defaults_restart_fractional_atomic_failure(http_panel, monkeypatch):
    active_cfg = copy.deepcopy(http_panel.state.rt.controller.cfg)
    status, _, data = request(http_panel, "POST", "/api/config", {"poll_seconds": 0.125, "gate": {"timeout_seconds": 0.375}})
    assert status == 200 and data["ok"]
    restarted = server.PanelState(config_path=http_panel.state.config_path)
    assert restarted.defaults()["runner"]["poll_seconds"] == 0.125
    assert restarted.defaults()["gate"]["timeout_seconds"] == 0.375
    assert http_panel.state.rt.controller.cfg == active_cfg
    before = http_panel.state.config_path.read_bytes()
    status, _, data = request(http_panel, "POST", "/api/config", {"poll_seconds": 9, "gate": {"output_limit_chars": 0.5}})
    assert status == 400 and data["ok"] is False
    assert http_panel.state.config_path.read_bytes() == before
    monkeypatch.setattr(config.os, "replace", MagicMock(side_effect=OSError("disk full")))
    status, _, data = request(http_panel, "POST", "/api/config", {"poll_seconds": 8})
    assert status != 200 and not data["ok"]
    assert http_panel.state.config_path.read_bytes() == before
    assert http_panel.state.live["poll_seconds"] == 0.125


def consumers(rt):
    return {"config": dict(rt.cfg), "ao_timeout": rt.adapter.timeout,
            "worker": rt.executor.worker_model, "spawn_timeout": rt.executor.spawn_timeout_seconds,
            "send_timeout": rt.executor.send_timeout_seconds, "kill_timeout": rt.executor.kill_timeout_seconds,
            "gate": (rt.gate.timeout_seconds, rt.gate.output_limit_chars),
            "models": [(p.model, p.timeout) for p in (rt._planner, rt._auditor, rt._verifier)],
            "observer": rt.controller.cfg["observer"], "budgets": rt.mission.budgets}


def test_cli_panel_real_consumers_snapshot_freeze_and_restart(runtime_root, monkeypatch):
    path = runtime_root / "config" / "default.yaml"
    updates = {"runner": {"poll_seconds": 0.125}, "gate": {"timeout_seconds": 0.75, "output_limit_chars": 19},
               "worker": {"model": "worker-model", "spawn_timeout_seconds": 2.5, "send_timeout_seconds": 3.5, "kill_timeout_seconds": 4.5},
               "ao": {"request_timeout_seconds": 1.5},
               "roles": {role: {"model": role + "-model", "timeout_seconds": 2.25} for role in ("planner", "auditor", "verifier")}}
    state = server.PanelState()
    state.set_config(updates)
    monkeypatch.setattr(state, "_run", lambda: None)
    state.start_mission(mission("M-PANEL-R01"))
    state.thread.join(3)
    cli = run_mission.build_runtime(mission("M-CLI-R01"), run_mission.load_config())
    assert consumers(cli) == consumers(state.rt)
    saved = state.rt.store.mission_config("M-PANEL-R01")["effective_config"]
    assert saved["revision"] == cli.store.mission_config("M-CLI-R01")["effective_config"]["revision"]
    state.set_config({"worker": {"model": "later-model"}, "gate": {"timeout_seconds": 1.75}})
    assert state.rt.executor.worker_model == "worker-model" and state.rt.gate.timeout_seconds == 0.75
    state.rt.close()
    restored = run_mission.build_runtime(mission("M-PANEL-R01"), run_mission.load_config())
    newer = run_mission.build_runtime(mission("M-NEW-R01"), run_mission.load_config())
    assert restored.executor.worker_model == "worker-model" and restored.gate.timeout_seconds == 0.75
    assert restored.store.mission_config("M-PANEL-R01")["effective_config"] == saved
    assert newer.executor.worker_model == "later-model" and newer.gate.timeout_seconds == 1.75
    assert not any(key in json.dumps(saved) for key in ("SECRET", "user_instruction", "objective", "environ"))
    for rt in (cli, restored, newer):
        rt.close()


def test_current_recovery_does_not_fabricate_legacy_config(runtime_root):
    m = mission("M-OLD-R01")
    store = StateStore(runtime_root / "runtime" / m["mission_id"] / "state.db")
    store.record_mission(m["mission_id"], {"mission": m, "state": "RUNNING"})
    store.close()
    with pytest.raises(config.ConfigError, match="no effective config snapshot"):
        run_mission.build_runtime(m, run_mission.load_config())
    rt = run_mission.build_runtime(m, run_mission.load_config(), dry_run=True, require_ao=False)
    assert "effective_config" not in rt.store.mission_config(m["mission_id"])
    rt.close()


@pytest.mark.parametrize("phase", ["task", "baseline", "final"])
def test_real_gate_timeout_output_bound_failure_ids_and_evidence(http_panel, tmp_path, phase):
    repo = tmp_path / phase
    _repo(repo)
    task = TaskSpec.from_dict(_task_spec())
    task.gate_commands = ['python -c "import time;time.sleep(0.3)"']
    gate = IntegrationGate(http_panel.store, timeout_seconds=0.05, output_limit_chars=24)
    run = gate.run(task, str(repo), phase=phase)
    assert not run.ok and run.results[0]["exit_code"] != 0
    assert run.results[0]["output"]["error_category"] == "TIMEOUT"
    gate.timeout_seconds = 2.25
    assert gate.run(task, str(repo), phase=phase).ok
    task.gate_commands = ['python -c "import sys;print(\'x\'*300);print(\'FAILED tests/test_app.py::test_NEW - failed\');sys.exit(1)"']
    run = gate.run(task, str(repo), phase=phase)
    item = run.results[0]
    assert not run.ok and item["exit_code"] == 1
    assert item["failure_ids"] == ["tests/test_app.py::test_NEW"]
    assert "FAILED" not in item["stdout"] and "chars elided" in item["stdout"]
    assert item["output"]["stdout"]["original_length"] > 300
    assert len(item["output"]["stdout"]["sha256"]) == 64
    with pytest.raises(ProtocolError, match="TRUNCATED"):
        require_complete({"gate": evidence_part(item["stdout"], 9999)})
    _, _, data = request(http_panel)
    row = data["gate_query"]["records"][0]
    assert row["overall"] == "fail" and row["output"]["stdout"]["truncated"] is True


def test_tail_new_failure_still_blocks_final_deterministic_gate(tmp_path):
    from tests.test_final_gate_baseline import _seed_done_mission
    mc, store, integ = _seed_done_mission(tmp_path)
    mc.gate = IntegrationGate(store, output_limit_chars=12)
    mc.mission.gate_commands = ['python -c "import sys;print(\'x\'*200);print(\'FAILED tests/test_x.py::test_NEW - failure\');sys.exit(1)"']
    mc.verifier.verify = MagicMock()
    mc._final_verify()
    assert mc.state == "HUMAN"
    assert "test_NEW" in mc._read_state()["reason"]
    mc.verifier.verify.assert_not_called()
    store.close()


def test_slow_preflight_visible_before_http_start_returns(runtime_root, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        assert release.wait(8)
        raise run_mission.PreflightError("controlled preflight failure")
    monkeypatch.setattr(run_mission, "mission_preflight", slow)
    state = server.PanelState()
    monkeypatch.setattr(server, "PANEL", state)
    failures = []
    def start():
        try: state.start_mission(mission("M-PREFLIGHT-R01"))
        except Exception as exc: failures.append(exc)
    thread = threading.Thread(target=start)
    thread.start()
    try:
        assert entered.wait(5)
        snap = server.snapshot()
        assert snap["mission"]["id"] == "M-PREFLIGHT-R01"
        assert snap["mission_config"]["status"] == "ok"
        active = snap["phases"]["records"][0]
        assert active["phase"] == "preflight" and active["status"] == "running"
        assert active["elapsed_seconds"] >= 0
    finally:
        release.set(); thread.join(5)
    assert failures and server.snapshot()["phases"]["records"][0]["status"] == "failed"


def test_semantic_transport_inflight_protocol_retry_and_unknown_model(http_panel, monkeypatch, tmp_path):
    from loopcore.planner_adapter import CodexCliPlannerProvider
    from loopcore import codex_cli
    m = mission("M-F04"); m["budgets"] = {"max_subtasks": 2}
    provider = CodexCliPlannerProvider(model="requested-model", timeout=1.25)
    provider.diagnostics = Diagnostics(http_panel.store, "M-F04")
    entered, release = threading.Event(), threading.Event()
    calls, results = [], []
    payload = deterministic_single_task_plan(MissionSpec.from_dict(m)).to_dict()
    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if len(calls) == 1:
            entered.set(); assert release.wait(8)
        Path(argv[argv.index("--output-last-message") + 1]).write_text(json.dumps({} if len(calls) == 1 else payload), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(codex_cli.subprocess, "run", fake_run)
    thread = threading.Thread(target=lambda: results.append(provider.plan_decompose(m, "DECOMP-M-F04")))
    http_panel.state.thread = thread
    thread.start()
    try:
        assert entered.wait(5)
        status, _, data = request(http_panel)
        assert status == 200
        model = data["phases"]["roles"]["planner"]
        assert model["status"] == "running" and model["elapsed_seconds"] >= 0 and model["attempt"] == 1
        assert model["requested_model"] == model["passed_model"] == "requested-model"
        assert model["confirmed_model"] is None and model["usage"] is None and model["cost"] is None
        assert "auditor" not in data["phases"]["roles"]
    finally:
        release.set(); thread.join(8)
    assert results and len(calls) == 2
    assert all(c[1]["timeout"] == 1.25 for c in calls)
    rows = request(http_panel)[2]["phases"]["records"]
    attempts = [r for r in rows if r["phase"] == "model_request"]
    assert [r["attempt"] for r in attempts] == [2, 1]
    assert attempts[1]["status"] == "failed" and attempts[1]["error_category"] == "SCHEMA"
    assert attempts[0]["status"] == "completed"
    raw = json.dumps(rows)
    assert "normal source change" not in raw and "# Task input" not in raw


def test_existing_ao_read_reports_rerouted_model_without_extra_call(tmp_path, monkeypatch):
    from loopcore.ao_adapter import AOAdapter
    store = StateStore(tmp_path / "state.db")
    diag = Diagnostics(store, "M")
    adapter = AOAdapter(run_file=tmp_path / "absent")
    adapter.diagnostics = diag
    diag.worker_fact("w1", requested_model="requested-model", activity="working")
    get = MagicMock(return_value={"sessionId": "w1", "messages": [], "settings": {"model": "requested-model"},
                                 "modelReroute": {"fromModel": "requested-model", "toModel": "confirmed-model", "reason": "provider"}})
    monkeypatch.setattr(adapter, "_get", get)
    adapter.get_worker_conversation("w1")
    get.assert_called_once_with("/api/v1/sessions/w1/conversation")
    worker = StateStore.query_phases(store._conn, "M")["workers"][0]
    assert worker["confirmed_model"] == "confirmed-model" and worker["passed_model"] == "requested-model"
    assert worker["elapsed_seconds"] is None
    store.close()


def test_fractional_runner_poll_consumed_and_snapshot_sequence(runtime_root, monkeypatch):
    rt = run_mission.build_runtime(mission("M-POLL-R01"), config.resolve_config(overrides={"runner": {"poll_seconds": 0.125}}))
    state = server.PanelState(); state.rt = rt
    monkeypatch.setattr(server, "PANEL", state)
    results = iter([{"state": "RUNNING"}, {"state": "HUMAN"}])
    monkeypatch.setattr(rt.controller, "step", lambda: next(results))
    pauses = []
    monkeypatch.setattr(run_mission.time, "sleep", pauses.append)
    run_mission.run_loop(rt)
    assert pauses == [0.125]
    a, b = server.snapshot(), server.snapshot()
    assert a["stream"]["mission_id"] == b["stream"]["mission_id"] == "M-POLL-R01"
    assert a["stream"]["epoch"] == b["stream"]["epoch"] and b["stream"]["sequence"] > a["stream"]["sequence"]
    rt.close()

def test_browser_config_phases_and_sse_reconnect_are_safe(http_panel, monkeypatch, tmp_path):
    browser = _browser_executable()
    if not browser:
        pytest.skip("No local Edge/Chromium executable")
    cfg = config.resolve_config()
    http_panel.store.record_mission("M-F04", {"effective_config": cfg.snapshot()})
    diag = Diagnostics(http_panel.store, "M-F04")
    phase = diag.phase("model_request", role="planner", requested_model="requested", passed_model="passed",
                       reason='waiting 中文 <img src=x onerror=window.PWNED=1> " &', attempt=2)
    phase.__enter__()
    http_panel.state.thread = SimpleNamespace(is_alive=lambda: True)
    monkeypatch.setattr(server, "_load_ao_projects", lambda: [])
    connections = []
    def finite_sse(handler):
        connections.append(1)
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        snap = server.snapshot()
        handler.wfile.write(("id: %s:%s\ndata: %s\n\n" % (snap["stream"]["epoch"], snap["stream"]["sequence"], json.dumps(snap))).encode())
    monkeypatch.setattr(server.Handler, "_sse", finite_sse)
    html = (server.PANEL_DIR / "index.html").read_text("utf-8")
    probe = r'''
<script nonce="__PANEL_NONCE__">
(async()=>{
 const check=(ok,msg)=>{if(!ok) throw new Error(msg);};
 const wait=ms=>new Promise(r=>setTimeout(r,ms));
 try{
  for(let i=0;i<800 && !LAST;i++) await wait(10);
  check(LAST,'no SSE state');
  check(document.getElementById('missionConfig').textContent.includes('revision='),'lost frozen config');
  check(document.getElementById('defaultConfigInfo').textContent.includes('消费者='),'lost consumers');
  check(![...document.querySelectorAll('h3')].some(n=>n.textContent.includes('实时生效')),'old live promise');
  check(document.getElementById('phaseStatus').textContent.includes('attempt=2'),'missing in-flight attempt');
  check(document.getElementById('phaseStatus').textContent.includes('waiting 中文 <img'),'lost safe text');
  check(!window.PWNED && !document.querySelector('img,[onerror]'),'phase XSS');
  check(document.getElementById('modelStatus').textContent.includes('外部确认=unknown'),'guessed model');
  check(document.getElementById('modelStatus').textContent.includes('auditor：未调用'),'guessed called role');
  const original=structuredClone(LAST), originalSeq=STREAM_SEQ;
  const duplicate=structuredClone(original);duplicate.mission.reason='STALE';
  check(acceptSnapshot(duplicate)===false && LAST.mission.reason!=='STALE','duplicate snapshot applied');
  duplicate.stream.sequence-=1;
  check(acceptSnapshot(duplicate)===false,'older sequence applied');
  disconnect();const frozen=document.getElementById('phaseStatus').textContent;
  await wait(300);renderPhases();check(document.getElementById('phaseStatus').textContent===frozen,'disconnected timer accumulated');
  check(document.getElementById('timingStatus').textContent.includes('断连'),'lost disconnected status');
  await wait(4200);
  check(STREAM_SEQ>originalSeq,'SSE did not reconnect with fresh sequence');
  check(LAST.mission.id==='M-F04','wrong task attribution');
  check(!PENDING.size,'reconnect submitted a write');
  const defaults=JSON.parse(document.getElementById('configJson').value);defaults.runner.poll_seconds=0.375;
  document.getElementById('configJson').value=JSON.stringify(defaults);
  document.getElementById('btnConfigAll').click();document.getElementById('btnConfigAll').click();
  for(let i=0;i<800 && PENDING.has('config');i++) await wait(10);
  check(!PENDING.has('config') && !UI_ERRORS.has('config'),'full config save failed');
  check(document.getElementById('missionConfig').textContent.includes('runner.poll_seconds = 5'),'defaults changed current snapshot');
  document.documentElement.dataset.r01Result='PASS';
 }catch(error){document.documentElement.dataset.r01Result='FAIL: '+error.message;}
})();
</script>
'''
    assets = tmp_path / "r01-browser-assets"
    assets.mkdir()
    (assets / "index.html").write_text(html.replace("</body>", probe + "</body>"), encoding="utf-8")
    monkeypatch.setattr(server, "PANEL_DIR", assets)
    try:
        result = subprocess.run([browser, "--headless", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                                 "--user-data-dir=" + str(tmp_path / "r01-browser-profile"), "--virtual-time-budget=12000", "--dump-dom", http_panel.origin],
                                capture_output=True, timeout=45, encoding="utf-8", errors="replace")
        assert 'data-r01-result="PASS"' in result.stdout, result.stdout[:1500]
        assert len(connections) >= 2
        assert http_panel.state.defaults()["runner"]["poll_seconds"] == 0.375
        assert not http_panel.store.operations()
    finally:
        phase.__exit__(None, None, None)


def test_reentry_keeps_incomplete_phase_unknown_and_snapshot_intact(runtime_root):
    m = mission("M-INTERRUPTED")
    rt = run_mission.build_runtime(m, run_mission.load_config())
    rt.store.record_phase(m["mission_id"], {"phase": "spawn", "status": "running", "started_epoch": time.time(),
                          "role": "worker", "attempt": 1, "elapsed_seconds": None})
    saved = rt.store.mission_config(m["mission_id"])["effective_config"]
    rt.close()
    rt = run_mission.build_runtime(m, run_mission.load_config())
    rows = StateStore.query_phases(rt.store._conn, m["mission_id"], active=True)["records"]
    spawn = next(r for r in rows if r["phase"] == "spawn")
    assert spawn["status"] == "unknown" and spawn["elapsed_seconds"] is None
    assert spawn["error_category"] == "INTERRUPTED"
    assert rt.store.mission_config(m["mission_id"])["effective_config"] == saved
    assert not rt.store.operations()
    rt.close()


def test_snapshot_missing_field_never_borrows_a_default():
    frozen = config.resolve_config().snapshot()
    del frozen["values"]["gate"]["timeout_seconds"]
    with pytest.raises(config.ConfigError, match="fields missing"):
        config.restore_snapshot(frozen)


def test_effect_timeouts_reach_existing_spawn_send_kill_boundary(runtime_root, monkeypatch):
    rt = run_mission.build_runtime(mission("M-EFFECT-TIMEOUT"), config.resolve_config(overrides={"worker": {
        "spawn_timeout_seconds": 2.25, "send_timeout_seconds": 3.25, "kill_timeout_seconds": 4.25}}))
    calls = []
    def invoke(args, timeout):
        calls.append((args[0], timeout))
        return SimpleNamespace(returncode=0, stdout="spawned session w1 (worker)" if args[0] == "spawn" else "", stderr="")
    monkeypatch.setattr(rt.executor, "_run", invoke)
    monkeypatch.setattr(rt.adapter, "operation_session", lambda sid: {"id": sid, "isTerminated": bool(calls and calls[-1][0] == "session"), "status": "terminated" if calls and calls[-1][0] == "session" else "working"})
    assert rt.executor._spawn("P", "codex", "ignored", "secret prompt", identity="spawn-once", owner_id="M-EFFECT-TIMEOUT") == "w1"
    assert rt.executor._send("send-once", "M-EFFECT-TIMEOUT", "w1", "secret message")["status"] == "SUCCEEDED"
    assert rt.executor.kill_worker("w1", owner_id="M-EFFECT-TIMEOUT") is True
    assert calls == [("spawn", 2.25), ("send", 3.25), ("session", 4.25)]
    phases = StateStore.query_phases(rt.store._conn, "M-EFFECT-TIMEOUT")["records"]
    assert "secret prompt" not in json.dumps(phases) and "secret message" not in json.dumps(phases)
    rt.close()


def test_fractional_mission_and_task_watchdogs_keep_persisted_precision(runtime_root, monkeypatch):
    from loopcore import closed_loop, mission as mission_module
    rt = run_mission.build_runtime(mission("M-FRACTIONAL"), config.resolve_config(overrides={"budgets": {
        "max_runtime_seconds": 0.125, "subtask_budgets": {"max_runtime_seconds": 0.125}}}))
    task = TaskSpec.from_dict(_task_spec())
    task.worker_session_id = "w-fractional"
    task.budgets = dict(rt.cfg["budgets"]["subtask_budgets"])
    loop = rt.controller._build_loop(task)
    for owner, module, key in ((rt.controller, mission_module, "mission_started_at:M-FRACTIONAL"),
                               (loop, closed_loop, "started_at:" + task.task_id)):
        before = time.time()
        assert owner._runtime_exceeded() is False
        started = rt.store.counter_get(key)
        assert before <= started <= time.time()
        monkeypatch.setattr(module, "_epoch_seconds", lambda: started + 0.124)
        assert owner._runtime_exceeded() is False
        monkeypatch.setattr(module, "_epoch_seconds", lambda: started + 0.126)
        assert owner._runtime_exceeded() is True
    rt.close()


@pytest.mark.parametrize("corruption", ["snapshot", "phases", "database"])
def test_http_config_and_phase_read_errors_are_not_unknown_or_uncalled(http_panel, monkeypatch, corruption):
    import sqlite3
    if corruption == "snapshot":
        http_panel.store.record_mission("M-F04", {"effective_config": {}})
    elif corruption == "phases":
        http_panel.store._conn.execute("INSERT INTO execution_phases(mission_id,phase_id,payload_json) VALUES('M-F04',1,'bad-json')")
        http_panel.store._conn.commit()
    else:
        monkeypatch.setattr(server, "_ro_conn", MagicMock(side_effect=sqlite3.OperationalError("injected read error")))
    status, _, data = request(http_panel)
    assert status == 200 and data["ok"] is False
    target = "phases" if corruption == "phases" else "mission_config"
    assert data[target]["status"] == "read_error"
    assert data["read_errors"]
    assert not http_panel.store.operations()


def test_diagnostic_recovery_failure_is_visible_without_changing_runtime(runtime_root, monkeypatch):
    monkeypatch.setattr(StateStore, "interrupt_open_phases", MagicMock(side_effect=OSError("injected")))
    rt = run_mission.build_runtime(mission("M-DIAG-ERROR"), run_mission.load_config())
    assert rt.diagnostics.errors == ["diagnostic recovery unavailable: OSError"]
    assert rt.store.mission_config("M-DIAG-ERROR")["effective_config"]["revision"]
    assert not rt.store.operations()
    rt.close()


def test_model_timeout_has_transport_category_without_prompt_or_fake_result(tmp_path, monkeypatch):
    from loopcore import codex_cli
    store = StateStore(tmp_path / "state.db")
    diag = Diagnostics(store, "M-TIMEOUT")
    invoke = MagicMock(side_effect=subprocess.TimeoutExpired(["codex", "SECRET_ARG"], 0.125))
    monkeypatch.setattr(codex_cli.subprocess, "run", invoke)
    schema = Path(codex_cli.__file__).parents[2] / "schemas" / "mission-plan.schema.json"
    with pytest.raises(codex_cli.CodexCliError):
        with diag.phase("planner", role="planner"):
            codex_cli.run_codex_json("SECRET_PROMPT", schema, timeout=0.125)
    phases = StateStore.query_phases(store._conn, "M-TIMEOUT")["records"]
    fact = next(p for p in phases if p["phase"] == "model_request")
    assert fact["status"] == "failed" and fact["error_category"] == "TimeoutExpired"
    assert fact["result"] is None and fact["confirmed_model"] is None
    assert "SECRET" not in json.dumps(phases)
    invoke.assert_called_once()
    store.close()


def test_ao_read_is_visible_before_slow_response_without_extra_request(http_panel, monkeypatch):
    from loopcore.ao_adapter import AOAdapter
    adapter = AOAdapter()
    adapter.diagnostics = Diagnostics(http_panel.store, "M-F04")
    entered, release = threading.Event(), threading.Event()
    response = MagicMock()
    def read():
        entered.set()
        assert release.wait(8)
        return b'{"session":{"id":"w1","status":"working"}}'
    response.__enter__.return_value.read.side_effect = read
    transport = MagicMock(return_value=response)
    monkeypatch.setattr("urllib.request.urlopen", transport)
    results = []
    thread = threading.Thread(target=lambda: results.append(adapter.get_worker_status("w1")))
    http_panel.state.thread = thread
    thread.start()
    try:
        assert entered.wait(5)
        data = request(http_panel)[2]
        phase = data["phases"]["records"][0]
        assert phase["phase"] == "ao_read" and phase["status"] == "running"
        assert phase["elapsed_seconds"] >= 0
    finally:
        release.set(); thread.join(8)
    assert results == [{"id": "w1", "status": "working"}]
    transport.assert_called_once()
    assert not http_panel.store.operations()
