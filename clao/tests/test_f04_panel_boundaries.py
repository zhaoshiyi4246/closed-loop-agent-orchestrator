"""F04 product regressions: isolated SQLite/Git/HTTP and a real headless browser."""
import http.client
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from panel import server
from loopcore.mission_gate import IntegrationGate
from loopcore.mission_contracts import TaskSpec
from loopcore.state_store import StateStore
from tests.sidecar_port.test_contracts import _task_spec
from tests.test_mission_gate import _repo


@pytest.fixture
def panel(tmp_path, monkeypatch):
    root = tmp_path / "Panel 中文 # root"
    runtime = root / "runtime" / "M-F04"
    runtime.mkdir(parents=True)
    store = StateStore(runtime / "state.db")
    mission = {"mission_id": "M-F04", "objective": "正常中文 objective"}
    store.record_mission("M-F04", {"state": "RUNNING", "mission": mission,
                                    "reason": "persistent Mission reason"})
    config_path = root / "config" / "default.yaml"
    config_path.parent.mkdir()
    config_path.write_bytes((server.run_mission.ROOT / "config" / "default.yaml").read_bytes())
    state = server.PanelState(config_path=config_path)
    state.rt = SimpleNamespace(runtime=runtime, mission=SimpleNamespace(mission_id="M-F04"),
                               mission_dict=mission, controller=SimpleNamespace(
                                   cfg={},
                                   directives=SimpleNamespace(pending_count=lambda: 0),
                                   request_stop=MagicMock(side_effect=lambda: store.request_mission_stop("M-F04")),
                                   _stop_event=threading.Event()))
    state._run = lambda: None  # HTTP boundary fixture has no product execution thread.
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "PANEL", state)
    yield SimpleNamespace(root=root, runtime=runtime, store=store, state=state)
    store.close()


@pytest.fixture
def http_panel(panel):
    httpd = server.PanelHTTPServer(("127.0.0.1", 0))
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    panel.httpd = httpd
    panel.port = httpd.server_address[1]
    panel.origin = "http://127.0.0.1:%d" % panel.port
    yield panel
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def request(panel, method="GET", path="/api/state", body=None, headers=None, raw=None):
    values = {"Host": "127.0.0.1:%d" % panel.port}
    if method == "POST":
        values.update({"Origin": panel.origin, "Content-Type": "application/json",
                       "X-Panel-Nonce": panel.httpd.panel_nonce})
    values.update(headers or {})
    values = {k: v for k, v in values.items() if v is not None}
    data = raw if raw is not None else json.dumps(body if body is not None else {}).encode()
    conn = http.client.HTTPConnection("127.0.0.1", panel.port, timeout=8)
    try:
        conn.request(method, path, body=data if method == "POST" else None, headers=values)
        response = conn.getresponse()
        result = response.read()
        if response.getheader("Content-Type", "").startswith("application/json"):
            result = json.loads(result)
        return response.status, dict(response.getheaders()), result
    finally:
        conn.close()


@pytest.mark.parametrize("phase", ["task", "baseline", "final"])
@pytest.mark.parametrize("mutation", [False, True])
def test_real_gate_rows_through_http_keep_command_and_integrity_separate(http_panel, tmp_path, phase, mutation):
    repo = tmp_path / "Worker"
    _repo(repo)
    task = TaskSpec.from_dict(_task_spec())
    task.gate_commands = ['python -c "open(\'app.py\',\'w\').write(\'changed\')"' if mutation else 'python -c "pass"']
    run = IntegrationGate(http_panel.store).run(task, str(repo), phase=phase)
    if phase != "baseline":
        http_panel.store.record_gate_scope(run, status="pass")
    status, _, data = request(http_panel)
    assert status == 200
    gate = data["gate_query"]["records"][0]
    assert data["gate_query"]["status"] == "ok"
    assert gate["phase"] == phase
    assert gate["exit_code"] == 0 and gate["command_result"] == "pass"
    assert gate["integrity"]["status"] == ("fail" if mutation else "pass")
    assert gate["overall"] == ("fail" if mutation else "pass")
    if mutation:
        assert "Gate changed repository state" in gate["integrity"]["reason"]


def test_not_run_no_records_and_read_error_are_distinct(http_panel):
    active = http_panel.state.rt
    http_panel.state.rt = None
    assert request(http_panel)[2]["gate_query"]["status"] == "not_run"
    http_panel.state.rt = active
    assert request(http_panel)[2]["gate_query"]["status"] == "no_records"
    http_panel.store._conn.execute("DROP TABLE gate_runs")
    http_panel.store._conn.commit()
    _, _, data = request(http_panel)
    assert data["ok"] is False
    assert data["gate_query"]["status"] == "read_error"
    assert "gate_runs" in data["gate_query"]["error"]
    assert data["mission"]["reason"] == "persistent Mission reason"


def test_pre_gate_failure_records_not_executed_commands(panel, tmp_path):
    task = TaskSpec.from_dict(_task_spec())
    run = IntegrationGate(panel.store).run(task, str(tmp_path / "missing"))
    record = StateStore.query_gate_runs(panel.store._conn)["records"][0]
    assert not run.ok and record["command_result"] == "not_run"
    assert record["exit_code"] is None
    assert record["integrity"]["status"] == "fail" and record["overall"] == "fail"


@pytest.mark.parametrize("forbidden", [False, True])
def test_historical_task_verifier_records_its_known_scope(tmp_path, forbidden):
    from loopcore.mission_contracts import ProjectState
    from tests.sidecar_port.test_verifier import _loop, _ScriptedVerifier
    verifier = _ScriptedVerifier("PASS")
    loop, task, store = _loop(tmp_path, verifier)
    try:
        task.gate_commands = ['python -c "pass"']
        task.forbidden_paths = ["app.py"] if forbidden else []
        loop.gate = IntegrationGate(store)
        loop._transition(ProjectState.WORKER_RUNNING, "test", "setup", {})
        loop._transition(ProjectState.GATE_PENDING, "test", "setup", {})
        loop._run_verifier()
        gate = StateStore.query_gate_runs(store._conn)["records"][0]
        assert gate["phase"] == "task" and gate["command_result"] == "pass"
        assert gate["scope"]["status"] == ("fail" if forbidden else "pass")
        assert gate["overall"] == ("fail" if forbidden else "pass")
        assert loop.state == (ProjectState.HUMAN if forbidden else ProjectState.DONE)
        assert len(verifier.inputs) == (0 if forbidden else 1)
        if forbidden:
            assert "app.py" in gate["scope"]["reason"]
    finally:
        store.close()


@pytest.mark.parametrize("exit_code", [0, 1])
def test_read_only_historical_gate_does_not_migrate_or_guess_pass(tmp_path, exit_code):
    db = tmp_path / "old state.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE gate_runs(id INTEGER PRIMARY KEY, task_id TEXT, command TEXT, cwd TEXT, exit_code INTEGER, started_at TEXT, ended_at TEXT, stdout TEXT, stderr TEXT)")
    conn.execute("INSERT INTO gate_runs VALUES(1,'T','python -m pytest','.',?,'start','end','out','err')", (exit_code,))
    conn.commit()
    conn.close()
    before = db.read_bytes()
    ro = server._ro_conn(db)
    result = StateStore.query_gate_runs(ro)
    ro.close()
    row = result["records"][0]
    assert row["historical_fields_missing"] is True
    assert row["integrity"]["status"] == row["scope"]["status"] == "unknown"
    assert row["overall"] == ("unknown" if exit_code == 0 else "fail")
    assert db.read_bytes() == before
    migrated = StateStore(db)
    assert "assessment_json" in {r[1] for r in migrated._conn.execute("PRAGMA table_info(gate_runs)")}
    assert StateStore.query_gate_runs(migrated._conn)["records"][0]["historical_fields_missing"]
    migrated.close()


def test_errors_and_long_fields_survive_snapshot(http_panel):
    message = '<img src=x onerror="window.PWNED=1"> 中文 & \' ' + "long reason " * 500
    http_panel.store.record_mission("M-F04", {"state": "HUMAN", "reason": message,
                                             "mission": http_panel.state.rt.mission_dict})
    http_panel.store.record_alert("A", {"summary": message, "description": "description", "error": "actual error"})
    http_panel.state.errors.append("runner failed: " + message)
    data = request(http_panel)[2]
    assert data["mission"]["reason"] == message
    assert data["panel_errors"] == ["runner failed: " + message]
    assert data["alerts"][0] == {"summary": message, "description": "description", "error": "actual error"}
    http_panel.store._conn.execute("DROP TABLE alerts")
    http_panel.store._conn.commit()
    data = request(http_panel)[2]
    assert data["ok"] is False
    assert any(e["source"] == "alerts" and "alerts" in e["error"] for e in data["read_errors"])
    assert data["mission"]["reason"] == message


BAD_HEADERS = [
    {"Host": "evil.example"}, {"Host": "localhost:1"},
    {"Origin": "https://evil.example"}, {"Origin": "null"}, {"Origin": None},
    {"X-Panel-Nonce": "wrong"}, {"X-Panel-Nonce": None},
    {"Content-Type": "text/plain"}, {"Content-Type": None},
]


@pytest.mark.parametrize("path", ["mission", "resume", "attach", "stop", "directive", "config"])
@pytest.mark.parametrize("headers", BAD_HEADERS)
def test_unauthorized_http_writes_never_reach_actions(http_panel, monkeypatch, path, headers):
    spies = []
    for name in ("_start_mission", "_resume", "_attach"):
        spy = MagicMock(return_value={"ok": True})
        monkeypatch.setattr(server.Handler, name, spy)
        spies.append(spy)
    for name in ("stop", "post_directive", "set_config"):
        spy = MagicMock()
        monkeypatch.setattr(http_panel.state, name, spy)
        spies.append(spy)
    status, _, data = request(http_panel, "POST", "/api/" + path, {"poll_seconds": 88}, headers=headers)
    assert status in (403, 415) and data["ok"] is False
    assert all(spy.call_count == 0 for spy in spies)
    assert http_panel.state.live["poll_seconds"] == 5


@pytest.mark.parametrize("raw", [b"", b"null", b"[]", b"{bad", b'{"poll_seconds":NaN}'])
def test_invalid_json_never_writes(http_panel, raw):
    assert request(http_panel, "POST", "/api/config", raw=raw)[0] in (400, 413)
    assert http_panel.state.live["poll_seconds"] == 5


def test_same_origin_page_nonce_allows_normal_write(http_panel):
    status, headers, html = request(http_panel, path="/")
    assert status == 200
    nonce = re.search(rb'<script nonce="([A-Za-z0-9_-]+)"', html).group(1).decode()
    assert nonce == http_panel.httpd.panel_nonce
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "no-store" in headers["Cache-Control"]
    status, _, data = request(http_panel, "POST", "/api/config", {"poll_seconds": 7},
                              headers={"X-Panel-Nonce": nonce})
    assert status == 200 and data["config"]["values"]["runner"]["poll_seconds"] == 7
    assert http_panel.state.live["poll_seconds"] == 7
    assert nonce not in json.dumps(server.snapshot())
    assert all(nonce.encode() not in p.read_bytes() for p in http_panel.runtime.iterdir() if p.is_file())


def test_server_nonce_is_per_session_and_loopback_only():
    with pytest.raises(ValueError, match="127.0.0.1"):
        server.PanelHTTPServer(("0.0.0.0", 0))
    one, two = server.PanelHTTPServer(("127.0.0.1", 0)), server.PanelHTTPServer(("127.0.0.1", 0))
    try:
        assert one.panel_nonce != two.panel_nonce
    finally:
        one.server_close()
        two.server_close()


@pytest.mark.parametrize("path", ["/", "/api/state", "/api/file?name=memory.md", "/api/stream"])
def test_bad_host_blocks_reads_and_nonce_disclosure(http_panel, path):
    status, _, result = request(http_panel, path=path, headers={"Host": "evil.example"})
    assert status == 403 and http_panel.httpd.panel_nonce not in json.dumps(result)


@pytest.mark.parametrize("mid", ["../outside", "..", "/absolute", "E:\\outside", "x/y", "x\\y", "%2e%2e", "%252e%252e", "bad\x00id", "CON", "中文", " bad "])
@pytest.mark.parametrize("endpoint", ["resume", "attach"])
def test_mission_identifiers_reject_traversal_before_any_read(http_panel, monkeypatch, mid, endpoint):
    read = MagicMock(side_effect=AssertionError("invalid id reached database"))
    monkeypatch.setattr(server, "_ro_conn", read)
    status, _, data = request(http_panel, "POST", "/api/" + endpoint, {"mission_id": mid})
    assert status == 400 and "mission_id" in data["error"]
    read.assert_not_called()


@pytest.mark.parametrize("query", ["name=../state.db", "name=%2e%2e%2fsecret", "name=%252e%252e", "name=E%3A%5Csecret", "name=%FF", "name=%ZZ", "name=memory.md&name=project.md", "name=memory.md&mission_id=other"])
def test_file_query_stays_finite_and_rejects_bad_encoding(http_panel, query):
    assert request(http_panel, path="/api/file?" + query)[0] == 400


def test_normal_file_text_and_missing_file(http_panel):
    assert request(http_panel, path="/api/file?name=memory.md")[2]["content"] == "(尚未生成)"
    content = '<script>alert("x")</script> 中文 & space'
    (http_panel.runtime / "memory.md").write_text(content, encoding="utf-8")
    assert request(http_panel, path="/api/file?name=memory.md")[2]["content"] == content


def test_saved_payload_cannot_redirect_runtime(http_panel, monkeypatch):
    http_panel.store.record_mission("M-F04", {"mission": {"mission_id": "../escape"}})
    build = MagicMock()
    monkeypatch.setattr(server.run_mission, "build_runtime", build)
    for endpoint in ("resume", "attach"):
        assert request(http_panel, "POST", "/api/" + endpoint, {"mission_id": "M-F04"})[0] == 400
    build.assert_not_called()


def test_runtime_junction_escape_is_rejected(http_panel, tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction regression")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "state.db").write_bytes(b"must not read")
    link = http_panel.root / "runtime" / "M-LINK"
    # Isolated temp paths only; no removal or moving of any user repository.
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    assert request(http_panel, "POST", "/api/attach", {"mission_id": "M-LINK"})[0] == 400
    assert (outside / "state.db").read_bytes() == b"must not read"



def _browser_executable():
    candidates = [shutil.which("msedge"), shutil.which("chrome"),
                  str(Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"),
                  str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe")]
    return next((p for p in candidates if p and Path(p).is_file()), None)


def test_real_browser_text_rendering_nonce_and_pending_writes(http_panel, monkeypatch, tmp_path):
    browser = _browser_executable()
    if not browser:
        pytest.skip("No local Chromium/Edge executable for real DOM regression")
    injected = '\"><img src=x onerror=window.PWNED=1> & \' INJECT_MARKER 中文 <svg onload=window.PWNED=1>'
    long_error = injected + " long 中文 reason" * 500 + " LONG_END"
    http_panel.store.record_mission("M-F04", {"state": injected, "reason": long_error,
                                             "mission": http_panel.state.rt.mission_dict})
    http_panel.state.errors.append("runner: " + long_error)
    http_panel.store.record_alert("A", {"alert_type": injected, "summary": long_error,
                                         "description": "ALERT_DESCRIPTION", "error": "ALERT_ERROR"})
    http_panel.store.record_task("T-F04", {"task_id": "T-F04", "objective": injected,
                                           "worker_session_id": injected})
    http_panel.store.record_transition(task_id="T-F04", from_state="TASK_READY", to_state=injected,
                                      actor=injected, reason=long_error, evidence={})
    http_panel.store.record_gate_run(task_id="T-F04", command=injected, cwd=".", exit_code=0,
                                    started_at="start", ended_at="end", stdout=injected, stderr=long_error,
                                    assessment=StateStore.gate_assessment(command="pass", integrity="fail",
                                        integrity_reason=long_error, scope="fail", scope_reason="SCOPE_FAILURE " + injected))
    monkeypatch.setattr(server, "list_missions", lambda: [
        {"mission_id": injected, "objective": injected, "state": injected},
        {"mission_id": "M-ATTACH", "objective": "inspect", "state": "MISSION_DONE"},
        {"mission_id": "M-RESUME", "objective": "resume", "state": "RUNNING"}])
    monkeypatch.setattr(server, "_load_ao_projects", lambda: [{"id": "P", "name": injected,
                                                               "path": injected, "kind": "git"}])
    monkeypatch.setattr(http_panel.state, "running", lambda: True)
    calls = {key: 0 for key in ("start", "resume", "attach", "stop", "directive", "config")}
    original_config = http_panel.state.set_config
    def action(key, result):
        def run(*args, **kwargs):
            import time
            calls[key] += 1
            time.sleep(0.03)
            return result(*args, **kwargs) if callable(result) else result
        return run
    monkeypatch.setattr(http_panel.state, "start_mission", action("start", None))
    def stop_response():
        if calls["stop"] > 1:
            raise server.ClientError("STOP_RECEIPT_NOT_SAVED", 503)
        return {"ok": True, "stop_requested": True}
    monkeypatch.setattr(http_panel.state, "stop", action("stop", stop_response))
    monkeypatch.setattr(http_panel.state, "post_directive", action("directive", {"mirrored_to_planner": False}))
    monkeypatch.setattr(http_panel.state, "set_config", action("config", original_config))
    monkeypatch.setattr(server.Handler, "_resume", action("resume", {"ok": True}))
    monkeypatch.setattr(server.Handler, "_attach", action("attach", {"ok": True}))
    # A finite SSE connection lets dump-dom finish its virtual clock. The
    # browser still consumes the real HTTP snapshot through its EventSource.
    def one_snapshot(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(("data: " + json.dumps(server.snapshot()) + "\n\n").encode())
    monkeypatch.setattr(server.Handler, "_sse", one_snapshot)
    # Use actual page, HTTP boundary, browser DOM/CSP and SQLite snapshot. Only
    # external action execution is replaced. The extra script is test-only.
    html = (server.PANEL_DIR / "index.html").read_text(encoding="utf-8")
    probe = r"""
<script nonce="__PANEL_NONCE__">
(async()=>{
  const check=(value,message)=>{ if(!value) throw new Error(message); };
  const waitFor=async fn=>{ const start=performance.now(); while(!fn()){
    if(performance.now()-start>8000) throw new Error('browser wait timeout');
    await new Promise(r=>setTimeout(r,10));
  }};
  try{
    await waitFor(()=>LAST && PROJECTS.length && !document.getElementById('btnStart').disabled);
    check(!window.PWNED,'executed injected HTML');
    check(!document.querySelector('img,[onerror],[onload],[onmouseover]'),'injected DOM or attribute');
    for(const id of ['missionsList','subtasks','workers','evidence','diagnostics','tab-al']){
      check(document.getElementById(id).textContent.includes('INJECT_MARKER'),'lost text in '+id);
    }
    check(document.getElementById('diagnostics').textContent.includes('LONG_END'),'truncated reason');
    check(document.getElementById('tab-al').textContent.includes('ALERT_DESCRIPTION'),'lost description');
    check(document.getElementById('tab-al').textContent.includes('ALERT_ERROR'),'lost alert error');
    check(document.getElementById('evidence').textContent.includes('overall=fail'),'false overall pass');
    check(document.getElementById('evidence').textContent.includes('command=pass'),'lost command result');
    check(document.getElementById('evidence').textContent.includes('SCOPE_FAILURE'),'lost scope');
    check(document.querySelector('#missionsList [title]').title.includes('INJECT_MARKER'),'lost safe title');
    async function twice(id,key){
      document.getElementById(id).click(); render(LAST); document.getElementById(id).click();
      await waitFor(()=>!PENDING.has(key));
    }
    await twice('btnCfg','config');
    document.getElementById('d_text').value='普通中文 directive';
    await twice('btnSend','directive');
    await twice('btnStop','stop');
    check(document.getElementById('toast').textContent.includes('取消请求已持久接收'),'missing accepted Stop message');
    await twice('btnStop','stop');
    check(document.getElementById('clientErrors').textContent.includes('STOP_RECEIPT_NOT_SAVED'),'lost Stop receipt error');
    check(!document.getElementById('toast').textContent.includes('取消请求已持久接收'),'failed Stop displayed as accepted');
    document.getElementById('f_obj').value='normal objective';
    document.getElementById('f_ac').value='works';
    document.getElementById('newMission').classList.add('open');
    await twice('btnStart','mission');
    render({...LAST,running:false});
    for(const [mid,label] of [['M-ATTACH','查看'],['M-RESUME','检查并恢复']]){
      const find=()=>[...document.querySelectorAll('#missionsList button')].find(b=>b.textContent===label && b.closest('.mrow').textContent.includes(mid));
      find().click(); render(LAST); find().click(); await waitFor(()=>!PENDING.has('mission'));
    }
    await writeAction('failure','/api/missing',{});
    await new Promise(r=>setTimeout(r,3000));
    check(document.getElementById('clientErrors').textContent.includes('not found'),'toast hid root cause');
    check(!window.PWNED && !document.querySelector('img,[onerror],[onload]'),'late injection');
    document.documentElement.dataset.f04Result='PASS';
  }catch(error){ document.documentElement.dataset.f04Result='FAIL: '+error.message; }
})();
</script>
"""
    assets = tmp_path / "browser-assets"
    assets.mkdir()
    (assets / "index.html").write_text(html.replace("</body>", probe + "</body>"), encoding="utf-8")
    monkeypatch.setattr(server, "PANEL_DIR", assets)
    result = subprocess.run([browser, "--headless", "--disable-gpu", "--no-first-run",
                             "--disable-background-networking", "--user-data-dir=" + str(tmp_path / "browser-profile"),
                             "--virtual-time-budget=20000", "--dump-dom", http_panel.origin + "/"],
                            capture_output=True, timeout=55, encoding="utf-8", errors="replace")
    outcome = re.search(r'data-f04-result="([^"]*)"', result.stdout)
    assert outcome and outcome.group(1) == "PASS", (result.returncode, outcome.group(1) if outcome else result.stdout[-1500:], result.stderr[-1000:])
    assert calls == {key: (2 if key == "stop" else 1) for key in calls}
    assert not any(http_panel.httpd.panel_nonce.encode() in p.read_bytes()
                   for p in http_panel.root.rglob("*") if p.is_file())



def test_duplicate_host_and_missing_host_cannot_write(http_panel):
    for hosts in ([], ["127.0.0.1:%d" % http_panel.port, "evil.example"]):
        conn = http.client.HTTPConnection("127.0.0.1", http_panel.port, timeout=5)
        try:
            conn.putrequest("POST", "/api/config", skip_host=True)
            for host in hosts:
                conn.putheader("Host", host)
            conn.putheader("Origin", http_panel.origin)
            conn.putheader("X-Panel-Nonce", http_panel.httpd.panel_nonce)
            conn.putheader("Content-Type", "application/json")
            data = b'{"poll_seconds":99}'
            conn.putheader("Content-Length", str(len(data)))
            conn.endheaders(data)
            response = conn.getresponse()
            assert response.status == 403
            response.read()
        finally:
            conn.close()
    assert http_panel.state.live["poll_seconds"] == 5


def test_file_junction_cannot_read_outside_runtime(http_panel, tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction regression")
    outside = tmp_path / "private"
    outside.mkdir()
    link = http_panel.runtime / "memory.md"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    status, _, data = request(http_panel, path="/api/file?name=memory.md")
    assert status == 400 and "escapes" in data["error"]


def test_corrupt_gate_assessment_is_read_error(http_panel):
    assessment = StateStore.gate_assessment(command="pass", integrity="fail", scope="pass")
    assessment["overall"] = "pass"
    http_panel.store.record_gate_run(task_id="T", command="python", cwd=".", exit_code=0,
                                    started_at="s", ended_at="e", stdout="", stderr="",
                                    assessment=assessment)
    data = request(http_panel)[2]
    assert data["ok"] is False
    assert data["gate_query"]["status"] == "read_error"
    assert "inconsistent Gate overall" in data["gate_query"]["error"]


def test_real_cross_origin_browser_post_has_no_side_effect(http_panel, tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    browser = _browser_executable()
    if not browser:
        pytest.skip("No local Chromium/Edge executable")
    html = ("<html><script>fetch(" + json.dumps(http_panel.origin + "/api/config") +
            ",{method:'POST',headers:{'Content-Type':'text/plain'},body:'{\"poll_seconds\":99}'})"
            ".catch(()=>{}).finally(()=>document.documentElement.dataset.attack='finished');</script></html>").encode()
    class Attacker(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        def log_message(self, *args):
            pass
    attacker = ThreadingHTTPServer(("127.0.0.1", 0), Attacker)
    thread = threading.Thread(target=attacker.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        url = "http://127.0.0.1:%d/" % attacker.server_address[1]
        result = subprocess.run([browser, "--headless", "--disable-gpu", "--no-first-run",
                                 "--disable-background-networking", "--user-data-dir=" + str(tmp_path / "attacker-profile"),
                                 "--virtual-time-budget=8000", "--dump-dom", url],
                                capture_output=True, timeout=45, encoding="utf-8", errors="replace")
        assert 'data-attack="finished"' in result.stdout, result.stderr[-1000:]
        assert http_panel.state.live["poll_seconds"] == 5
    finally:
        attacker.shutdown()
        attacker.server_close()
        thread.join(timeout=5)



def test_rejected_split_request_receives_error_without_writing(http_panel):
    import time
    for _ in range(8):
        conn = http.client.HTTPConnection("127.0.0.1", http_panel.port, timeout=5)
        try:
            body = b'{"poll_seconds":99}'
            conn.putrequest("POST", "/api/config")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(len(body)))
            conn.endheaders()  # Missing Origin/nonce: reject before acting.
            time.sleep(0.03)
            conn.send(body)
            response = conn.getresponse()
            assert response.status == 403
            assert json.loads(response.read())["error"] == "same-origin Origin required"
        finally:
            conn.close()
    assert http_panel.state.live["poll_seconds"] == 5
