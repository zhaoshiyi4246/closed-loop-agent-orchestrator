import copy
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import threading

import pytest
import yaml

from loopcore import ao_legacy as legacy
from loopcore import credentials
from loopcore.model_profiles import SERVICE, KIMI_SERVICE, ENDPOINT, KIMI_ENDPOINT
from loopcore.state_store import StateStore
from loopcore.structured import ProtocolError


def profile(service=SERVICE):
    p = dict(id="same-name", service=service, endpoint=ENDPOINT if service == SERVICE else KIMI_ENDPOINT,
             model="glm-4.7" if service == SERVICE else "kimi-k3", credential_ref="same-ref",
             timeout_seconds=1.25, max_attempts=2, retry_delay_seconds=0.25)
    if service == SERVICE:
        p.update(thinking="disabled", temperature=0.2, max_tokens=1000)
    else:
        p.update(reasoning_effort="low", max_completion_tokens=2000)
    return p


def test_import_configuration_keeps_refs_private_without_credentials_or_overwriting(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "credentials", lambda *a: pytest.fail("import must not inspect credentials"))
    cfg = tmp_path / "default.yaml"
    original = dict(model_profiles=[profile(), dict(profile(KIMI_SERVICE), id="kimi")],
                    gate={"timeout_seconds": 2.75}, roles={"planner": {"profile": "kimi"}},
                    budgets={"max_subtasks": 2, "subtask_budgets": {"max_local_fixes": 1, "max_replans": 1}})
    cfg.write_text(yaml.safe_dump(original), encoding="utf-8")
    before = cfg.read_bytes()
    result = legacy.import_files({"configPath": str(cfg)})
    assert result == legacy.import_files({"configPath": str(cfg)})
    assert cfg.read_bytes() == before
    connections = [r for r in result["rows"] if r["kind"] == "connection"]
    assert len(connections) == 2 and connections[0]["id"] != connections[1]["id"]
    assert {r["document"]["profile"]["credential_ref"] for r in connections} == {"same-ref"}
    values = result["rows"][-1]["document"]["values"]
    assert values["gateTimeout"] == 2.75 and values["maxTasks"] == 2
    assert values["roles"]["planner"]["connectionId"] == connections[1]["id"]
    assert values["maxRepairs"] == 2 and values["maxReplans"] == 1


def test_incompatible_connection_has_reconnect_reason_without_secret(tmp_path):
    cfg = tmp_path / "default.json"
    cfg.write_text(json.dumps({"model_profiles": [dict(profile(), api_key="not-a-real-secret")]}, ensure_ascii=False))
    out = legacy.import_files({"configPath": str(cfg)})
    row = out["rows"][0]["document"]
    assert row["compatible"] is False and "重新连接" in row["reason"]
    assert "profile" not in row and "not-a-real-secret" not in json.dumps(out)


def test_explicit_reconnect_saves_only_selected_service_reference(monkeypatch):
    writes = []
    class Store:
        def __init__(self, service): self.service = service
        def save(self, ref, key): writes.append((self.service, ref, key))
    monkeypatch.setattr(credentials, "credentials", Store)
    out = legacy.evaluate(dict(action="credential", profile=profile(KIMI_SERVICE), apiKey="isolated-value"))
    assert out == {"ok": True, "configured": True}
    assert writes == [(KIMI_SERVICE, "same-ref", "isolated-value")]
    assert "isolated-value" not in json.dumps(out)


def test_readonly_history_preserves_conclusions_missing_fields_and_wal(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "credentials", lambda *a: pytest.fail("history must not inspect credentials"))
    folder = tmp_path / "旧任务 中文"
    folder.mkdir()
    db = folder / "state.db"
    st = StateStore(str(db))
    st.freeze_config("old-task", {"mission_id": "old-task", "project_id": "original-project", "objective": "旧任务",
                                  "acceptance_criteria": [{"id": "AC1", "description": "实际验收"}]}, None)
    st.record_mission_state_atomic("old-task", "MISSION_DONE", {"reason": "原结论", "source": {"source_commit": "a" * 40},
                                                              "integration_head": "b" * 40})
    st.record_gate_run(task_id="old-task", command="python check.py", cwd="private-local-path", exit_code=0,
                       started_at="start", ended_at="end", stdout="model full Prompt must not be copied", stderr="")
    st.record_verification("verify-old", "old-task", {"verify_id": "verify-old", "task_id": "old-task", "verdict": "PASS",
                           "ac_checks": [{"ac_id": "AC1", "verdict": "PASS"}], "anti_gaming": [], "prompt": "never import me"})
    st._conn.execute("PRAGMA journal_mode=WAL")
    st._conn.execute("PRAGMA wal_autocheckpoint=0")
    st.record_mission_state_atomic("old-task", "MISSION_DONE", {"reason": "WAL 中的当前结论"})
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    imported = legacy.import_files({"historyPath": str(tmp_path)})
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    assert before == after
    value = imported["rows"][0]["document"]
    assert value["state"] == "MISSION_DONE" and value["reason"] == "WAL 中的当前结论"
    assert value["readOnly"] and not value["canContinue"]
    assert value["configurationRevision"] is None
    gate = value["gates"]["records"][0]
    assert gate["command_status"] == "pass" and gate["overall"] == "unknown"
    assert gate["historical_fields_missing"]
    assert value["verification"]["records"][0]["ac_checks"][0]["verdict"] == "PASS"
    encoded = json.dumps(imported)
    assert "never import me" not in encoded and "private-local-path" not in encoded and "full Prompt" not in encoded
    st.close()


def test_history_damaged_evidence_is_read_error_not_pass(tmp_path):
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE missions(mission_id TEXT,payload_json TEXT,recorded_at TEXT)")
    conn.execute("INSERT INTO missions VALUES(?,?,?)", ("old", json.dumps({"state": "MISSION_DONE", "mission": {"objective": "fact"}}), "now"))
    conn.commit(); conn.close()
    item = legacy.import_files({"historyPath": str(db)})["rows"][0]["document"]
    assert item["gates"]["status"] == "read_error"
    assert item["verification"]["status"] == "read_error"
    assert item["state"] == "MISSION_DONE"  # never rewrite old historical conclusion


@pytest.fixture
def endpoints(monkeypatch):
    servers, seen, answers = {}, [], {}
    for service in (SERVICE, KIMI_SERVICE):
        answers[service] = (200, {})
        def handler(service):
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    seen.append((service, self.path, self.headers["Authorization"], body))
                    status, response = answers[service]
                    raw = json.dumps(response).encode()
                    self.send_response(status); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
            return Handler
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(service))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        servers[service] = server
    def local_connection(host, timeout):
        service = SERVICE if host == "open.bigmodel.cn" else KIMI_SERVICE if host == "api.moonshot.cn" else pytest.fail("unexpected service")
        return http.client.HTTPConnection("127.0.0.1", servers[service].server_port, timeout=timeout)
    monkeypatch.setattr(http.client, "HTTPSConnection", local_connection)
    class Credential:
        def __init__(self, service): self.service = service
        def read(self, ref):
            assert ref == "same-ref"
            return "isolated-fixture-" + self.service
    monkeypatch.setattr(credentials, "credentials", Credential)
    yield seen, answers
    for server in servers.values(): server.shutdown(); server.server_close()


@pytest.mark.parametrize("service", [SERVICE, KIMI_SERVICE])
@pytest.mark.parametrize("role,result", [
    ("decomposition", dict(mission_id="task", strategy="single task", subtasks=[dict(subtask_id="one", objective="goal", allowed_paths=["src/**"], acceptance_criteria=[dict(id="AC1", description="check")])])),
    ("planner", dict(action_id="plan", task_id="task", action="HUMAN", reason="semantic decision")),
    ("auditor", dict(audit_id="audit", task_id="task", decision="LOCAL_FIX", evidence=[dict(type="gate", summary="failed")], diagnosis="fix", confidence=0.8)),
    ("verifier", dict(verify_id="verify", task_id="task", verdict="FAIL", ac_checks=[dict(ac_id="AC1", verdict="FAIL")], anti_gaming=[])),
])
def test_actual_shared_semantic_transport_routes_roles_and_parameters(endpoints, service, role, result):
    seen, answers = endpoints
    answers[service] = (200, dict(model="confirmed-model", usage={"total_tokens": 17}, choices=[dict(finish_reason="stop", message=dict(role="assistant", content=json.dumps(result)))]))
    out = legacy.semantic({"profile": profile(service), "role": role, "prompt": "complete isolated evidence"})
    assert json.loads(out["text"]) == result and out["confirmedModel"] == "confirmed-model"
    assert out["usage"] == {"total_tokens": 17} and out["cost"] is None
    assert len(seen) == 1
    actual, path, auth, body = seen[0]
    assert actual == service and auth == "Bearer isolated-fixture-" + service
    assert body["model"] == profile(service)["model"] and body["response_format"] == {"type": "json_object"}
    assert body["messages"][1]["content"] == "complete isolated evidence"
    assert path == ("/api/paas/v4/chat/completions" if service == SERVICE else "/v1/chat/completions")
    assert ("thinking" in body) == (service == SERVICE)
    assert ("reasoning_effort" in body) == (service == KIMI_SERVICE)


@pytest.mark.parametrize("status,body,category", [
    (401, {"secret": "must not echo"}, "AUTH"),
    (429, {"secret": "must not echo"}, "RATE_LIMIT"),
    (200, {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "{}"}}]}, "TRUNCATED"),
    (200, {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "bad json"}}]}, "JSON_PARSE"),
])
def test_protocol_failures_not_retried_or_echoed(endpoints, status, body, category):
    seen, answers = endpoints
    answers[KIMI_SERVICE] = (status, body)
    with pytest.raises(ProtocolError) as error:
        legacy.semantic({"profile": profile(KIMI_SERVICE), "role": "verifier", "prompt": "evidence"})
    assert error.value.category == category
    assert "must not echo" not in str(error.value) and len(seen) == 1


@pytest.mark.parametrize("value", [{}, {"historyPath": "../outside"}, {"configPath": "C:/Windows/system.ini"}])
def test_import_requires_explicit_supported_source(value):
    with pytest.raises(legacy.ImportError): legacy.import_files(value)
