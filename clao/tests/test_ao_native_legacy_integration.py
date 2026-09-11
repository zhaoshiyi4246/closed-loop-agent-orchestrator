"""Formal native HTTP -> imported connection -> real semantic transport.

Only external engine and HTTP sockets are substituted. Native Controller,
SessionManager, source snapshots, SQLite, pure schemas, Git and Gates run as
production. Test keys have random refs, are explicitly saved via the protected
API and deleted in finally; no user credential reference is inspected.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

import pytest
import yaml

from loopcore.credentials import credentials
from loopcore.model_profiles import SERVICE, KIMI_SERVICE
from loopcore.state_store import StateStore
from tests.test_ao_legacy import profile
from tests.test_ao_native import native, native_engine, git


def role_input(prompt):
    decoder = json.JSONDecoder()
    for offset, char in enumerate(prompt):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(prompt[offset:])
        except ValueError:
            continue
        if isinstance(obj, dict) and any(k in obj for k in ("evidence_bundle", "audit_result", "verifier_input")):
            return obj
    raise AssertionError("Actual role prompt did not contain correlated input")


@pytest.fixture
def native_provider_servers():
    servers, seen = {}, []
    for service in (SERVICE, KIMI_SERVICE):
        def handler(service):
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass
                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    data = role_input(body["messages"][1]["content"])
                    if "evidence_bundle" in data:
                        role = "auditor"
                        answer = dict(audit_id=data["audit_id"], task_id=data["task_id"], decision="LOCAL_FIX",
                                      evidence=[dict(type="test_failure", summary="actual Gate failed")],
                                      diagnosis="Repair result.txt under original scope", confidence=0.9)
                    elif "audit_result" in data:
                        role = "planner"
                        answer = dict(action_id=data["action_id"], task_id=data["task_id"], action="SEND_LOCAL_FIX",
                                      target_session_id=data["target_session_id"], reason="Repair original Gate failure",
                                      message="Fix result.txt to accepted; retain original constraints.")
                    else:
                        role = "verifier"
                        acs = data["verifier_input"]["task_spec"]["acceptance_criteria"]
                        answer = dict(verify_id=data["verify_id"], task_id=data["task_id"], verdict="PASS",
                                      ac_checks=[dict(ac_id=ac["id"], verdict="PASS") for ac in acs],
                                      anti_gaming=[dict(ac_id=ac["id"], verdict="PASS") for ac in acs])
                    seen.append(dict(service=service, role=role, authorization=self.headers["Authorization"], path=self.path,
                                     model=body["model"], body=body, task_id=data["task_id"]))
                    raw = json.dumps(dict(model="confirmed-" + service, choices=[dict(finish_reason="stop", message=dict(role="assistant", content=json.dumps(answer)))]), ensure_ascii=False).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
            return Handler
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(service))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers[service] = server
    try:
        yield servers, seen
    finally:
        for server in servers.values():
            server.shutdown()
            server.server_close()


@pytest.fixture
def native_core_python(tmp_path, native_provider_servers):
    servers, _ = native_provider_servers
    ports = {"open.bigmodel.cn": servers[SERVICE].server_port, "api.moonshot.cn": servers[KIMI_SERVICE].server_port}
    bootstrap = "\n".join([
        "import http.client, runpy, sys",
        "ports = " + repr(ports),
        "def local_http(host, timeout):",
        "    if host not in ports: raise RuntimeError('unapproved HTTP test destination')",
        "    return http.client.HTTPConnection('127.0.0.1', ports[host], timeout=timeout)",
        "http.client.HTTPSConnection = local_http",
        "sys.argv = ['loopcore.ao_legacy']",
        "runpy.run_module('loopcore.ao_legacy', run_name='__main__')",
    ])
    # Windows exec.Command requires an executable. This shim forwards all core
    # calls to the real Python; only the external HTTPS constructor is replaced
    # for the legacy transport process. No acceptance/controller result is faked.
    go = tmp_path / "legacy_transport_python.go"
    go.write_text("""package main
import("os";"os/exec")
func main(){
 args:=os.Args[1:]
 if len(args)==2 && args[0]=="-m" && args[1]=="loopcore.ao_legacy" { args=[]string{"-c",BOOTSTRAP} }
 cmd:=exec.Command(PYTHON,args...);cmd.Stdin=os.Stdin;cmd.Stdout=os.Stdout;cmd.Stderr=os.Stderr;cmd.Env=os.Environ()
 if err:=cmd.Run();err!=nil { os.Exit(1) }
}
""".replace("BOOTSTRAP", json.dumps(bootstrap)).replace("PYTHON", json.dumps(sys.executable)), encoding="utf-8")
    exe = tmp_path / "legacy-transport-python.exe"
    subprocess.run(["go", "build", "-o", str(exe), str(go)], check=True)
    return exe


def wait(api, mid):
    for _ in range(400):
        status, value = api("/api/v1/clao/missions/" + mid)
        assert status == 200, value
        mission = value["mission"]
        if mission["state"] in ("DONE", "FAILED", "UNKNOWN", "HUMAN", "CANCELLED", "PAUSED"):
            return mission
        time.sleep(.15)
    pytest.fail("Native legacy semantic mission did not settle")


def test_formal_import_versions_defaults_without_replacing_connections(native, native_provider_servers):
    _, api, nonce, _, _, temp = native
    _, seen = native_provider_servers
    cfg = temp / "旧配置 中文.yaml"
    original = dict(model_profiles=[dict(profile(SERVICE), id="original")],
                    roles={"planner": {"profile": "original"}}, gate={"timeout_seconds": 2.75})
    headers = {"X-CLAO-Nonce": nonce}

    def import_config(value):
        cfg.write_text(yaml.safe_dump(value), encoding="utf-8")
        content = cfg.read_bytes()
        result = api("/api/v1/clao/imports", {"configPath": str(cfg)}, headers)
        assert cfg.read_bytes() == content
        return result

    status, first = import_config(original)
    assert status == 200, first
    assert len(first["connections"]) == 1 and len(first["configurations"]) == 1
    old_connection = first["connections"][0]
    old_config = first["configurations"][0]
    assert old_config["document"]["values"]["roles"]["planner"]["connectionId"] == old_connection["id"]

    # The supported repair is a new connection identity plus a new binding. It
    # must not conflict with the previous immutable defaults in the same batch.
    original["model_profiles"].append(dict(profile(KIMI_SERVICE), id="replacement"))
    original["roles"]["planner"]["profile"] = "replacement"
    status, second = import_config(original)
    assert status == 200, second
    assert len(second["connections"]) == 2 and len(second["configurations"]) == 2
    assert next(c for c in second["connections"] if c["id"] == old_connection["id"]) == old_connection
    assert next(c for c in second["configurations"] if c["id"] == old_config["id"]) == old_config
    new_connection = next(c for c in second["connections"] if c["name"] == "replacement")
    new_config = next(c for c in second["configurations"] if c["id"] != old_config["id"])
    assert new_config["document"]["values"]["roles"]["planner"]["connectionId"] == new_connection["id"]
    for config in (old_config, new_config):
        doc = config["document"]
        assert doc["sourceName"] == cfg.name and len(doc["revision"]) == 64
        assert doc["revision"][:8] in doc["name"]
        assert doc["values"]["gateTimeout"] == 2.75
    assert new_config["document"]["revision"] != old_config["document"]["revision"]

    # Re-reading or changing serialization does not create a third version.
    status, repeated = import_config(original)
    assert status == 200 and repeated == second
    cfg.write_text(json.dumps(original, ensure_ascii=False, indent=4), encoding="utf-8")
    status, reformatted = api("/api/v1/clao/imports", {"configPath": str(cfg)}, headers)
    assert status == 200 and reformatted == second

    # Versioned defaults do not permit replacing an old connection or partially
    # importing the rest of an invalid batch, even with another new role binding.
    original["model_profiles"][0]["model"] = "glm-not-an-imported-model"
    original["model_profiles"].append(dict(profile(SERVICE), id="must-rollback"))
    original["roles"]["planner"]["profile"] = "must-rollback"
    status, rejected = import_config(original)
    assert status == 400, rejected
    assert api("/api/v1/clao/imports")[1] == second
    assert api("/api/v1/clao/missions")[1]["missions"] == [] and seen == []


@pytest.mark.skipif(os.name != "nt", reason="real Windows Credential Manager test with isolated references")
def test_formal_native_import_mixed_semantics_and_consent(native, native_provider_servers):
    _, api, nonce, source, base, temp = native
    _, seen = native_provider_servers
    ref = "migration-test-" + uuid.uuid4().hex
    keys = {SERVICE: "isolated-glm-" + uuid.uuid4().hex, KIMI_SERVICE: "isolated-kimi-" + uuid.uuid4().hex}
    previous_keys = {service: "isolated-old-" + uuid.uuid4().hex for service in keys}
    managed_refs = set()
    profiles = [dict(profile(SERVICE), id="glm-original", credential_ref=ref, timeout_seconds=5),
                dict(profile(KIMI_SERVICE), id="kimi-original", credential_ref=ref, timeout_seconds=5)]
    cfg = temp / "old-default.yaml"
    old_cfg = dict(model_profiles=profiles, roles={"auditor": {"profile": "glm-original"}, "planner": {"profile": "kimi-original"}, "verifier": {"profile": "glm-original"}},
                   budgets={"max_subtasks": 1, "subtask_budgets": {"max_local_fixes": 1, "max_replans": 0}}, gate={"timeout_seconds": 10})
    cfg.write_text(yaml.safe_dump(old_cfg), encoding="utf-8")
    old_runtime = temp / "old-runtime"
    old_runtime.mkdir()
    old = StateStore(str(old_runtime / "state.db"))
    old.freeze_config("historical-one", {"mission_id": "historical-one", "project_id": "different-original-project", "objective": "historical read-only record"}, None)
    old.record_mission_state_atomic("historical-one", "HUMAN", {"reason": "original historical verdict"})
    old.close()
    old_bytes = (old_runtime / "state.db").read_bytes()
    headers = {"X-CLAO-Nonce": nonce}
    try:
        for service in keys:
            credentials(service).save(ref, previous_keys[service])
        status, catalog = api("/api/v1/clao/imports", {"configPath": str(cfg), "historyPath": str(old_runtime)}, headers)
        assert status == 200, catalog
        assert api("/api/v1/clao/imports", {"configPath": str(cfg), "historyPath": str(old_runtime)}, headers)[0] == 200
        assert len(catalog["histories"]) == 1 and catalog["histories"][0]["document"]["state"] == "HUMAN"
        assert catalog["histories"][0]["document"]["canContinue"] is False
        assert (old_runtime / "state.db").read_bytes() == old_bytes
        assert api("/api/v1/clao/missions")[1]["missions"] == []
        assert ref not in json.dumps(catalog)
        connections = {c["service"]: c for c in catalog["connections"]}
        for service, connection in connections.items():
            next_revision = connection.get("authRevision", 0) + 1
            managed_ref = "native-" + hashlib.sha256((connection["id"] + ":" + str(next_revision)).encode()).hexdigest()[:32]
            managed_refs.add((service, managed_ref))
            status, result = api("/api/v1/clao/imports/" + connection["id"] + "/credential", {"apiKey": keys[service]}, headers)
            assert status == 200 and result["status"] == "configured", result
            assert result["authRevision"] == next_revision
            assert credentials(service).read(managed_ref) == keys[service]
            assert credentials(service).read(ref) == previous_keys[service]
        catalog = api("/api/v1/clao/imports")[1]
        assert all(key not in json.dumps(catalog) for key in keys.values())
        values = catalog["configurations"][0]["document"]["values"]
        by_id = {c["id"]: c for c in catalog["connections"]}
        for choice in values["roles"].values():
            connection = by_id[choice["connectionId"]]
            choice.update(connectionRevision=connection["authRevision"], agent="", model=connection["model"])
        project = api("/api/v1/projects")[1]["projects"][0]["id"]
        revision = api(f"/api/v1/clao/projects/{project}/source")[1]["source"]["revision"]
        request = dict(values, id="legacy-native-mixed", projectId=project, sourceRevision=revision,
                       objective="REPAIR_ONCE preserve mixed imported roles", agent="opencode", model="test/native",
                       allowedPaths=["result.txt"], forbiddenPaths=["private/**"], gateCommands=["python check.py"],
                       criteria=[dict(id="AC1", description="result.txt contains accepted")])
        # New UI applies only the snapshot values then confirms service scope.
        # It never sends an imported scalar BigModel permission as all-services.
        request["externalServiceConsent"] = [SERVICE]
        status, rejected = api("/api/v1/clao/missions", request, headers)
        assert status == 400, rejected
        assert seen == [] and api("/api/v1/clao/missions")[1]["missions"] == []
        request["externalServiceConsent"] = [SERVICE, KIMI_SERVICE]
        status, accepted = api("/api/v1/clao/missions", request, headers)
        assert status == 202, accepted
        # Source config is edited only after Mission admission. Re-import cannot
        # overwrite the imported connection or alter frozen consumers.
        old_cfg["model_profiles"][0]["temperature"] = .7
        cfg.write_text(yaml.safe_dump(old_cfg), encoding="utf-8")
        assert api("/api/v1/clao/imports", {"configPath": str(cfg)}, headers)[0] == 400
        mission = wait(api, request["id"])
        assert mission["state"] == "DONE", mission
        assert [c["role"] for c in mission["roleCalls"]] == ["auditor", "planner", "verifier"]
        assert [call["service"] for call in seen] == [SERVICE, KIMI_SERVICE, SERVICE]
        assert [call["role"] for call in seen] == ["auditor", "planner", "verifier"]
        for call in seen:
            assert call["authorization"] == "Bearer " + keys[call["service"]]
            assert call["task_id"] == request["id"]
            assert call["model"] == ("glm-4.7" if call["service"] == SERVICE else "kimi-k3")
            assert ("thinking" in call["body"]) == (call["service"] == SERVICE)
            assert ("reasoning_effort" in call["body"]) == (call["service"] == KIMI_SERVICE)
            if call["service"] == SERVICE:
                assert call["body"]["temperature"] == .2
        for role in ("auditor", "planner", "verifier"):
            frozen = mission["roles"][role]["connection"]
            assert (frozen["service"], frozen["profile"]["credential_ref"]) in managed_refs
            assert frozen["authRevision"] == 1
            assert frozen["billing"] == "standard_api"
        assert mission["repairs"] == 1 and mission["request"]["maxRepairs"] == 1
        assert mission["evidence"][-1]["verification"]["verdict"] == "PASS"
        assert git(Path(mission["workspace"]), "show", mission["resultHead"] + ":result.txt") == "accepted"
        assert not (source / "result.txt").exists()
        assert git(source, "rev-parse", "HEAD") == base
        # Neither HTTP models nor legacy history fabricate native Sessions.
        trace = [json.loads(line) for line in (temp / "external.jsonl").read_text("utf-8").splitlines()]
        assert len({r["workspace"] for r in trace if r["kind"] == "prompt"}) == 1
        db_path = temp / "isolated-home/native/data/ao.db"
        dbbytes = b"".join(p.read_bytes() for p in (db_path, Path(str(db_path) + "-wal")) if p.exists())
        log = (temp / "daemon.log").read_bytes()
        assert all(key.encode() not in dbbytes and key.encode() not in log for key in [*keys.values(), *previous_keys.values()])
        assert all(key not in json.dumps(mission) for key in [*keys.values(), *previous_keys.values()])
    finally:
        for service, managed_ref in managed_refs:
            credentials(service).delete(managed_ref)
        for service in keys:
            credentials(service).delete(ref)
