"""AO-native integration: real daemon/SQLite/Session/Git, external CLI substitute.

Set CLAO_NATIVE_BINARY to a locally built derived daemon. No real credentials,
provider requests or installed AO state are used.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[2]
AO = ROOT / "ao"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE).decode("utf-8").strip()


@pytest.fixture(scope="module")
def native_engine(tmp_path_factory):
    binary = os.environ.get("CLAO_NATIVE_BINARY")
    if not binary:
        pytest.skip("CLAO_NATIVE_BINARY requires the derived development build")
    folder = tmp_path_factory.mktemp("ao-external-engine")
    exe = folder / "opencode.exe"
    subprocess.run(["go", "build", "-o", str(exe), str(AO / "backend/internal/service/claoloop/testdata/engine.go")], check=True, cwd=AO / "backend")
    shutil.copy2(exe, folder / "codex.exe")
    shutil.copy2(exe, folder / "kimi.exe")
    return Path(binary), folder


@pytest.fixture
def native_core_python():
    return sys.executable


@pytest.fixture
def native(tmp_path, native_engine, native_core_python):
    binary, engine = native_engine
    home = tmp_path / "isolated-home"
    home.mkdir()
    source = tmp_path / "项目 source"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.email", "fixture@example.invalid")
    git(source, "config", "user.name", "Fixture")
    (source / "source.txt").write_text("frozen source\n", encoding="utf-8")
    (source / "check.py").write_text("from pathlib import Path\nassert Path('result.txt').read_text() == 'accepted\\n'\n", encoding="utf-8")
    git(source, "add", ".")
    git(source, "commit", "-m", "base")
    base = git(source, "rev-parse", "HEAD")
    index = (source / ".git/index").read_bytes()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT"}}
    env.update({"PATH": str(engine) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + env["PATH"],
                "USERPROFILE": str(home), "HOME": str(home), "APPDATA": str(home / "appdata"), "LOCALAPPDATA": str(home / "local"),
                "XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "share"),
                "AO_DATA_DIR": str(home / "native/data"), "AO_RUN_FILE": str(home / "native/running.json"),
                "AO_PORT": str(port), "AO_ALLOWED_ORIGINS": f"http://127.0.0.1:{port}",
                "AO_TELEMETRY_EVENTS": "off", "AO_TELEMETRY_REMOTE": "off", "AO_SENTRY_DSN": "",
                "CLAO_CORE_PYTHON": str(native_core_python), "CLAO_CORE_ROOT": str(ROOT / "clao"),
                "CLAO_FIXTURE_TRACE": str(tmp_path / "external.jsonl"),
                "CLAO_FIXTURE_RELEASE_CONFIG": str(tmp_path / "release-config"),
                "CLAO_FIXTURE_FAIL_START": str(tmp_path / "reject-start")})
    log_path = tmp_path / "daemon.log"
    log = log_path.open("wb")
    proc = subprocess.Popen([str(binary), "daemon"], env=env, cwd=AO / "frontend", stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"

    def api(path, body=None, headers=None, method=None):
        request = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                         headers={"Origin": url, "Content-Type": "application/json", **(headers or {})}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                return response.status, json.load(response) if response.status != 204 else {}
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def restart():
        nonlocal proc
        previous_pid = proc.pid
        proc.terminate()
        proc.wait(timeout=10)
        proc = subprocess.Popen([str(binary), "daemon"], env=env, cwd=AO / "frontend", stdout=log, stderr=subprocess.STDOUT)
        assert proc.pid != previous_pid
        for _ in range(150):
            if proc.poll() is not None:
                pytest.fail(log_path.read_text("utf-8", errors="replace")[-8000:])
            try:
                if api("/api/v1/clao/session")[0] == 200:
                    return api("/api/v1/clao/session")[1]["nonce"]
            except OSError:
                pass
            time.sleep(.1)
        pytest.fail("restarted daemon unavailable")
    api.restart = restart
    api.base_url = url

    try:
        for _ in range(100):
            if proc.poll() is not None:
                pytest.fail(log_path.read_text("utf-8", errors="replace")[-10000:])
            try:
                if api("/api/v1/projects")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(.1)
        else:
            pytest.fail("native daemon did not become ready")
        status, project = api("/api/v1/projects", {"projectId": "fixture-project", "path": str(source)})
        assert status in (200, 201), project
        project_id = project["project"]["id"]
        status, nonce = api("/api/v1/clao/session")
        assert status == 200, nonce

        def submit(objective, repairs=1, agent="opencode", on_running=None, roles=None, replans=0, model="test/native"):
            spec = {"id": "clao-test-" + hashlib.sha256(objective.encode()).hexdigest()[:12], "projectId": project_id,
                    "objective": objective, "agent": agent, "model": model, "allowedPaths": ["**"], "forbiddenPaths": ["private/**"],
                    "criteria": [{"id": "AC1", "description": "result.txt contains accepted"}], "gateCommands": ["python check.py"],
                    "maxRepairs": repairs, "maxReplans": replans, "roles": roles or {}, "gateTimeout": 10}
            spec["sourceRevision"] = api(f"/api/v1/clao/projects/{project_id}/source")[1]["source"]["revision"]
            status, result = api("/api/v1/clao/missions", spec, {"X-CLAO-Nonce": nonce["nonce"]})
            assert status == 202, (result, log_path.read_text("utf-8", errors="replace")[-7000:])
            # Replay the exact receipt: it may observe progress but cannot spawn twice.
            assert api("/api/v1/clao/missions", spec, {"X-CLAO-Nonce": nonce["nonce"]})[0] == 202
            for _ in range(200):
                status, result = api("/api/v1/clao/missions/" + spec["id"])
                assert status == 200, result
                if on_running and result["mission"].get("sessionId"):
                    on_running(result["mission"])
                if result["mission"]["state"] in {"DONE", "FAILED", "UNKNOWN", "CANCELLED", "HUMAN", "PAUSED"}:
                    return result["mission"]
                time.sleep(.15)
            pytest.fail("mission did not settle: " + json.dumps(result) + "\n" + log_path.read_text("utf-8", errors="replace")[-8000:])

        yield submit, api, nonce["nonce"], source, base, tmp_path
        assert git(source, "rev-parse", "HEAD") == base
        assert git(source, "branch", "--show-current") == "main"
        assert git(source, "status", "--porcelain") == ""
        assert (source / ".git/index").read_bytes() == index
        assert not (source / "result.txt").exists()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log.close()


def test_native_opencode_pass_and_frozen_result(native):
    submit, api, nonce, source, base, temp = native
    result = submit("Create result.txt containing accepted")
    assert result["state"] == "DONE", json.dumps(result, ensure_ascii=False)
    assert [c["role"] for c in result["roleCalls"]] == ["verifier"]
    assert result.get("decisions", []) == []
    assert result["base"] == base
    assert result["sessionId"] != result["verifierSessionId"]
    assert (Path(result["workspace"]) / "result.txt").read_text() == "accepted\n"
    assert git(Path(result["workspace"]), "show", result["resultHead"] + ":result.txt") == "accepted"
    assert result["evidence"][-1]["verification"]["verdict"] == "PASS"
    assert all(op["state"] == "CONFIRMED_SUCCESS" for op in result["operations"])


def test_native_failed_start_is_visible_and_new_attempt_does_not_replay(native):
    submit, api, nonce, source, base, temp = native
    marker = temp / "reject-start"
    marker.write_text("controlled external failure")
    first = submit("First attempt: fail before initial turn")
    assert first["state"] == "FAILED", first
    assert "controlled session/new failure" in first["reason"]
    assert first["operations"][0]["state"] == "CONFIRMED_FAILURE"
    assert not first.get("sessionId")
    status, rows = api("/api/v1/clao/missions")
    assert status == 200 and any(m["request"]["id"] == first["request"]["id"] for m in rows["missions"])
    trace = (temp / "external.jsonl").read_text(encoding="utf-8")
    assert '"kind":"prompt"' not in trace
    marker.unlink()
    assert api("/api/v1/clao/missions", first["request"], {"X-CLAO-Nonce": nonce})[1]["mission"] == first
    edited = {**first["request"], "objective": "do not overwrite"}
    assert api("/api/v1/clao/missions", edited, {"X-CLAO-Nonce": nonce})[0] == 400
    second = submit("New attempt: create accepted output")
    assert second["state"] == "DONE", second
    assert second["request"]["id"] != first["request"]["id"]
    assert api("/api/v1/clao/missions/" + first["request"]["id"])[1]["mission"] == first


def test_native_spawn_receipt_loss_adopts_owner_and_requires_stop(native):
    submit, api, nonce, source, base, temp = native
    # Fail the local operation ACK write, after real native Session/turn creation.
    # Reconciliation writes UNKNOWN and is deliberately not rejected by the trigger.
    with sqlite3.connect(temp / 'isolated-home/native/data/ao.db') as db:
        db.execute("""CREATE TRIGGER fixture_receipt_failure BEFORE UPDATE ON clao_missions
          WHEN json_extract(NEW.document, '$.state') = 'SPAWNING'
           AND json_extract(NEW.document, '$.operations[0].state') = 'CONFIRMED_SUCCESS'
          BEGIN SELECT RAISE(ABORT, 'injected receipt write failure'); END""")
    first = submit("WAIT_CANCEL preserve native ownership after receipt loss")
    for _ in range(60):
        first = api("/api/v1/clao/missions/" + first["request"]["id"])[1]["mission"]
        if first.get("sessionId"):
            break
        time.sleep(.1)
    assert first["state"] == "UNKNOWN" and first.get("sessionId"), first
    assert first["operations"][0]["state"] == "UNKNOWN"
    assert "injected receipt write failure" in first["reason"]
    assert not first.get("resultHead")
    assert api("/api/v1/clao/missions", first["request"], {"X-CLAO-Nonce": nonce})[0] == 202
    next_request = {**first["request"], "id": first["request"]["id"] + "-new"}
    assert api("/api/v1/clao/missions", next_request, {"X-CLAO-Nonce": nonce})[0] == 400
    assert (temp / "external.jsonl").read_text(encoding="utf-8").count('"kind":"waiting"') == 1
    status, receipt = api("/api/v1/clao/missions/" + first["request"]["id"] + "/cancel", {}, {"X-CLAO-Nonce": nonce})
    assert status == 202 and receipt["mission"]["cancelRequested"]
    for _ in range(60):
        result = api("/api/v1/clao/missions/" + first["request"]["id"])[1]["mission"]
        if result["state"] == "CANCELLED":
            break
        time.sleep(.1)
    assert result["state"] == "CANCELLED", result
    assert result["sessionId"] == first["sessionId"]
    assert len([op for op in result["operations"] if op["kind"] == "spawn"]) == 1


def test_native_gate_failure_sends_only_one_repair(native):
    submit, api, nonce, source, base, temp = native
    result = submit("FAIL_GATE always keep the failure visible", repairs=1)
    assert result["state"] == "HUMAN", json.dumps(result, ensure_ascii=False)
    assert not result.get("resultHead")
    assert not result.get("verifierSessionId")
    assert result["repairs"] == 1
    assert len([op for op in result["operations"] if op["kind"] == "repair_send"]) == 1
    assert len([op for op in result["operations"] if op["kind"] == "spawn"]) == 1
    assert all(not ev["ok"] for ev in result["evidence"])


def test_native_write_boundary_rejects_missing_consent(native):
    submit, api, nonce, source, base, temp = native
    status, _ = api("/api/v1/clao/missions", {})
    assert status == 403
    status, _ = api("/api/v1/clao/missions", {}, {"X-CLAO-Nonce": nonce, "Origin": "https://example.invalid"})
    assert status == 403
    assert api("/api/v1/clao/missions")[1]["missions"] == []


def test_native_cancel_confirms_stop_before_any_materialization(native):
    submit, api, nonce, source, base, temp = native
    cancelled = []
    def cancel(m):
        if not cancelled:
            status, receipt = api('/api/v1/clao/missions/' + m['request']['id'] + '/cancel', {}, {'X-CLAO-Nonce': nonce})
            assert status == 202 and receipt['mission']['cancelRequested']
            cancelled.append(True)
    result = submit('WAIT_CANCEL do not complete the external turn', on_running=cancel)
    assert result['state'] == 'CANCELLED', result
    assert not result.get('resultHead') and not result['evidence']
    assert result['operations'][-1]['kind'] == 'stop'
    assert result['operations'][-1]['state'] == 'CONFIRMED_SUCCESS'


def test_native_approval_is_once_and_native_retry_cannot_bypass_owner(native):
    submit, api, nonce, source, base, temp = native
    answered = []
    def resolve(m):
        if answered:
            return
        sid = m['sessionId']
        status, snap = api('/api/v1/sessions/' + sid + '/conversation')
        assert status == 200, snap
        activities = snap.get('activities', [])
        pending = [a for a in activities if a.get('activityKind') == 'approval' and a.get('status') == 'pending']
        if not pending:
            return
        path = '/api/v1/sessions/' + sid + '/conversation/approvals/' + pending[0]['requestId'] + '/resolve'
        assert api(path, {'decisionId': 'always'})[0] >= 400
        assert api(path, {'decisionId': 'allow'})[0] == 204
        answered.append(True)
    result = submit('NEED_APPROVAL then create accepted output', on_running=resolve)
    assert answered and result['state'] == 'DONE', result
    status, _ = api('/api/v1/sessions/' + result['sessionId'] + '/resume-agent', {})
    assert status >= 400


def test_native_codex_uses_same_acceptance_service(native):
    submit, api, nonce, source, base, temp = native
    result = submit('Create accepted output using the Codex protocol', agent='codex')
    if result['state'] in {'UNKNOWN', 'FAILED'} and 'Codex account setup did not complete' in result['reason']:
        assert not result.get('resultHead') and not result['evidence']
        pytest.xfail('AO v0.12.12 Windows account_storage_unsafe in isolated profile; native account checks remain enforced')
    assert result['state'] == 'DONE', result


@pytest.mark.parametrize("case", ["DANGEROUS", "FORBIDDEN", "GIT_CONTROL"])
def test_native_manual_accept_cannot_override_mission_scope(native, case):
    submit, api, nonce, source, base, temp = native
    answered = []
    def resolve(m):
        if answered:
            return
        sid = m['sessionId']
        status, snap = api('/api/v1/sessions/' + sid + '/conversation')
        assert status == 200
        pending = [a for a in snap.get('activities', []) if a.get('activityKind') == 'approval' and a.get('status') == 'pending']
        if not pending:
            return
        path = '/api/v1/sessions/' + sid + '/conversation/approvals/' + pending[0]['requestId'] + '/resolve'
        code, reason = api(path, {'decisionId': 'allow'})
        assert code >= 400, reason
        assert api(path, {'decisionId': 'reject'})[0] == 204
        assert api('/api/v1/clao/missions/' + m['request']['id'] + '/cancel', {}, {'X-CLAO-Nonce': nonce})[0] == 202
        answered.append(True)
    result = submit('NEED_APPROVAL ' + case, on_running=resolve)
    assert answered and result['state'] == 'CANCELLED', result
    assert not result.get('resultHead') and not (Path(result['workspace']) / 'result.txt').exists()


def test_native_empty_review_cannot_be_final_pass(native):
    submit, api, nonce, source, base, temp = native
    result = submit('EMPTY_REVIEW create accepted output')
    assert result['state'] == 'FAILED', result
    assert result.get('resultHead') and result.get('verifierSessionId')
    assert 'Verifier' in result['reason']


@pytest.mark.parametrize('context,allow', [({}, True), ({'environmentId': 'local'}, True),
    ({'environmentId': 'remote'}, False), ({'additionalPermissions': {'network': True}}, False),
    ({'futurePermission': True}, False)])
def test_native_codex_approval_uses_original_permission_facts(tmp_path, context, allow):
    from loopcore.ao_acceptance import evaluate
    raw = {'threadId': 'thread', 'turnId': 'turn', 'itemId': 'item', 'command': 'python check.py',
           'cwd': str(tmp_path), 'availableDecisions': ['accept', 'decline'], **context}
    activity = {'activityKind': 'approval', 'status': 'pending', 'requestId': 'request',
                'detail': {'method': 'item/commandExecution/requestApproval', 'approvalRequest': raw,
                           'rawCommand': raw['command'], 'cwd': raw['cwd'],
                           'decisions': [{'id': 'accept', 'kind': 'allow_once'}, {'id': 'decline', 'kind': 'reject_once'}]}}
    result = evaluate({'workspace': str(tmp_path), 'base': 'a' * 40, 'approval': activity,
                       'task': {'task_id': 'task-1', 'project_id': 'project', 'objective': 'check',
                                'allowed_paths': ['**'], 'forbidden_paths': [],
                                'acceptance_criteria': [{'id': 'AC1', 'description': 'check'}], 'gate_commands': ['python check.py']}})
    assert result['ok'] is allow



def test_native_independent_roles_repair_and_frozen_models(native):
    submit, api, nonce, source, base, temp = native
    roles = {r: {"agent": "opencode", "model": "test/second"} for r in ("auditor", "planner", "verifier")}
    result = submit("REPAIR_ONCE use full evidence and repair result", roles=roles)
    assert result["state"] == "DONE", result
    assert [c["role"] for c in result["roleCalls"]] == ["auditor", "planner", "verifier"]
    assert all(c["state"] == "VALIDATED" for c in result["roleCalls"])
    assert all(c["choice"]["model"] == "test/second" and not c["choice"]["inherited"] for c in result["roleCalls"])
    assert all(c["resolvedModel"] == "test/second" and not c.get("confirmedModel") for c in result["roleCalls"])
    assert len({c["sessionId"] for c in result["roleCalls"]} | {result["sessionId"]}) == 4
    assert result["decisions"][0]["action"] == "SEND_LOCAL_FIX"
    assert result["decisions"][0]["state"] == "APPLIED" and result["repairs"] == 1
    assert result["roles"]["worker"]["model"] == "test/native"
    trace = [json.loads(line) for line in (temp / "external.jsonl").read_text("utf-8").splitlines()]
    audit_prompt = next(t["text"] for t in trace if t["kind"] == "prompt" and '"audit_id":' in t["text"])
    assert "AssertionError" in audit_prompt and "broken" in audit_prompt and "source.txt" not in git(source, "status", "--porcelain")
    policies = [json.loads(t["text"]) for t in trace if t["kind"] == "policy" and t["text"]]
    readonly = [c for c in policies if c.get("permission") == "deny"]
    assert len(readonly) >= 3
    assert all(c["agent"][c["default_agent"]]["permission"] == {"*": "deny"} for c in readonly)
    for _ in range(3):
        assert api("/api/v1/clao/missions/" + result["request"]["id"])[1]["mission"] == result
    assert api("/api/v1/clao/missions", result["request"], {"X-CLAO-Nonce": nonce})[1]["mission"] == result
    assert len([t for t in trace if t["kind"] == "prompt"]) == 5  # worker, audit, plan, fix, verifier


@pytest.mark.parametrize("marker,action,replans,expected", [
    ("PLAN_REPLACE", "REPLAN_SPAWN", 1, "DONE"),
    ("PLAN_REPLACE", "REPLAN_SPAWN", 0, "HUMAN"),
    ("PLAN_HUMAN", "HUMAN", 0, "HUMAN"),
    ("PLAN_CANDIDATE", "CANDIDATE_DONE", 0, "HUMAN"),
    ("PLAN_CONTINUE", "CONTINUE", 0, "HUMAN"),
])
def test_native_planner_actions_have_distinct_bounded_effects(native, marker, action, replans, expected):
    submit, api, nonce, source, base, temp = native
    result = submit(marker + " preserve original task contract", replans=replans)
    assert result["state"] == expected, result
    assert result["decisions"][0]["action"] == action
    assert result["repairs"] == 0
    assert not any(o["kind"] == "repair_send" for o in result["operations"])
    replacements = [o for o in result["operations"] if o["kind"] == "spawn_replacement"]
    if expected == "DONE":
        assert len(replacements) == result["replans"] == 1
        old = result["decisions"][0]["workerId"]
        assert old != result["sessionId"]
        replacement_index = result["operations"].index(replacements[0])
        assert any(o["kind"] == "stop" and o["target"] == old and o["state"] == "CONFIRMED_SUCCESS" for o in result["operations"][:replacement_index])
        assert git(Path(result["workspace"]), "show", result["resultHead"] + ":result.txt") == "accepted"
        assert result["request"]["objective"].startswith(marker)
    else:
        assert not replacements and not result.get("resultHead") and not result.get("verifierSessionId")
        assert result["reason"]
        next_result = submit("New attempt after legal HUMAN " + action)
        assert next_result["state"] == "DONE"


def test_native_bad_role_correlation_does_not_send_or_spawn(native):
    submit, api, nonce, source, base, temp = native
    result = submit("BAD_ROLE_ID reject other task result")
    assert result["state"] == "HUMAN", result
    assert [c["state"] for c in result["roleCalls"]] == ["PROTOCOL_ERROR"]
    assert not any(o["kind"] in {"repair_send", "spawn_replacement", "spawn_planner"} for o in result["operations"])
    assert not result.get("resultHead")


@pytest.mark.parametrize("role", ["auditor", "planner"])
def test_native_cancel_during_semantic_wait_stops_every_owner(native, role):
    submit, api, nonce, source, base, temp = native
    cancelled = []
    def cancel(m):
        calls = m.get("roleCalls", [])
        if not cancelled and any(c["role"] == role and c["state"] == "RUNNING" for c in calls):
            status, receipt = api('/api/v1/clao/missions/' + m['request']['id'] + '/cancel', {}, {'X-CLAO-Nonce': nonce})
            assert status == 202 and receipt['mission']['cancelRequested']
            cancelled.append(True)
    result = submit("HOLD_" + role.upper() + " cancel a waiting role", on_running=cancel)
    assert cancelled and result["state"] == "CANCELLED", result
    assert not result.get("resultHead") and result["repairs"] == result["replans"] == 0
    assert next(c for c in result["roleCalls"] if c["role"] == role)["state"] == "CANCELLED"
    assert not any(o["kind"] in {"repair_send", "spawn_replacement"} for o in result["operations"])
    assert api("/api/v1/clao/missions", result["request"], {"X-CLAO-Nonce": nonce})[1]["mission"] == result


def test_native_role_receipt_loss_adopts_exact_owner_without_replay(native):
    submit, api, nonce, source, base, temp = native
    with sqlite3.connect(temp / 'isolated-home/native/data/ao.db') as db:
        db.execute("""CREATE TRIGGER role_receipt_failure BEFORE UPDATE ON clao_missions
          WHEN json_extract(NEW.document, '$.operations[#-1].kind') = 'spawn_auditor'
           AND json_extract(NEW.document, '$.operations[#-1].state') = 'CONFIRMED_SUCCESS'
          BEGIN SELECT RAISE(ABORT, 'injected role receipt write failure'); END""")
    result = submit("HOLD_AUDITOR reconcile role ACK")
    for _ in range(60):
        result = api("/api/v1/clao/missions/" + result["request"]["id"])[1]["mission"]
        if result["roleCalls"][-1].get("sessionId"):
            break
        time.sleep(.1)
    assert result["state"] == "UNKNOWN" and result["roleCalls"][-1]["state"] == "UNKNOWN", result
    assert result["roleCalls"][-1].get("sessionId")
    assert api("/api/v1/clao/missions", result["request"], {"X-CLAO-Nonce": nonce})[0] == 202
    assert api("/api/v1/clao/missions", {**result["request"], "id": result["request"]["id"] + "-new"}, {"X-CLAO-Nonce": nonce})[0] == 400
    assert (temp / "external.jsonl").read_text("utf-8").count('"kind":"waiting"') == 1
    assert api('/api/v1/clao/missions/' + result['request']['id'] + '/cancel', {}, {'X-CLAO-Nonce': nonce})[0] == 202
    for _ in range(60):
        result = api("/api/v1/clao/missions/" + result["request"]["id"])[1]["mission"]
        if result["state"] == "CANCELLED": break
        time.sleep(.1)
    assert result["state"] == "CANCELLED", result
    assert sum(o["kind"] == "spawn_auditor" for o in result["operations"]) == 1


def test_native_mixed_engine_worker_and_semantic_roles(native):
    submit,api,nonce,source,base,temp=native
    roles={r:{"agent":"opencode","model":"test/second"} for r in ("auditor","planner","verifier")}
    result=submit("REPAIR_ONCE mixed native engines",agent="kimi",roles=roles)
    assert result["state"]=="DONE",result
    assert result["roles"]["worker"]["agent"]=="kimi"
    assert all(c["choice"]["agent"]=="opencode" for c in result["roleCalls"])
    assert result["repairs"]==1


def test_native_identical_failure_stops_before_repeating_diagnosis(native):
    submit,api,nonce,source,base,temp=native
    result=submit("FAIL_GATE no-progress across a repair",repairs=3)
    assert result["state"]=="HUMAN",result
    assert result["repairs"]==1 and len(result["decisions"])==1
    assert [c["role"] for c in result["roleCalls"]]==["auditor","planner"]
    assert "没有新的文件进展" in result["reason"]


def test_native_reported_model_is_separate_from_frozen_choice(native):
    submit,api,nonce,source,base,temp=native
    result=submit("REPORT_MODEL record an explicit native model fact",roles={"verifier":{"agent":"opencode","model":"test/second"}})
    assert result["state"]=="DONE",result
    call=result["roleCalls"][0]
    assert call["choice"]["model"]==call["resolvedModel"]=="test/second"
    assert call["confirmedModel"]=="test/provider-confirmed" and call["modelFactSource"]=="ACP session/catalog"


@pytest.mark.parametrize("agent,model,marker,roles", [
    ("kimi", "test/second", "PLAN_REPLACE", {
        "auditor": {"agent": "opencode", "model": ""},
        "planner": {"agent": "opencode", "model": "test/native"},
        "verifier": {"agent": "opencode", "model": ""},
    }),
    ("kimi", "", "PLAN_REPLACE", {r: {"agent": "opencode", "model": ""} for r in ("auditor", "planner", "verifier")}),
    ("opencode", "", "REPAIR_ONCE", {}),
    ("opencode", "test/second", "REPAIR_ONCE", {
        "auditor": {"agent": "opencode", "model": ""},
        "planner": {"agent": "opencode", "model": "test/native"},
    }),
])
def test_native_chat_uses_frozen_model_defaults(native, agent, model, marker, roles):
    submit, api, nonce, source, base, temp = native
    project_id = next(p["id"] for p in api("/api/v1/projects")[1]["projects"] if Path(p["path"]) == source)

    def configure(value):
        config = {"defaultBranch": "main", "worker": {"agent": "kimi", "agentConfig": {"model": value}}}
        status, response = api(f"/api/v1/projects/{project_id}/config", {"config": config}, method="PUT")
        assert status == 200, response

    configure("test/second")
    changed = []

    def change_while_worker_waits(mission):
        if changed:
            return
        traces = [json.loads(line) for line in (temp / "external.jsonl").read_text("utf-8").splitlines()]
        if not any(t["kind"] == "config_wait" for t in traces):
            return
        assert not mission.get("roleCalls", []) and not mission["replans"]
        configure("test/native")
        changed.append(True)
        (temp / "release-config").write_text("release", encoding="utf-8")

    result = submit(marker + " HOLD_CONFIG confirmed model choices", agent=agent, model=model,
                    roles=roles, replans=1 if marker == "PLAN_REPLACE" else 0, on_running=change_while_worker_waits)
    assert changed and result["state"] == "DONE", result
    assert [c["role"] for c in result["roleCalls"]] == ["auditor", "planner", "verifier"]
    assert result["roles"]["worker"]["model"] == model
    assert result["request"]["model"] == model and result["request"].get("roles", {}) == roles
    traces = [json.loads(line) for line in (temp / "external.jsonl").read_text("utf-8").splitlines()]
    sessions = {result["sessionId"]: (model, False)}
    if marker == "PLAN_REPLACE":
        sessions[result["decisions"][0]["workerId"]] = (model, False)
    for call in result["roleCalls"]:
        expected = roles.get(call["role"], {"model": model})["model"]
        assert call["choice"]["model"] == expected
        assert call["choice"]["inherited"] == (call["role"] not in roles)
        assert call.get("resolvedModel", "") == expected
        # A missing override has a native catalog fact, never the project value.
        if not expected:
            assert call["confirmedModel"] == "test/native"
        sessions[call["sessionId"]] = (expected, True)
    for sid, (expected, readonly) in sessions.items():
        status, view = api("/api/v1/sessions/" + sid)
        assert status == 200, view
        assert view["session"].get("model", "") == expected
        with sqlite3.connect(temp / "isolated-home/native/data/ao.db") as db:
            workspace, saved_model, permissions = db.execute("SELECT workspace_path, model, session_permissions FROM sessions WHERE id = ?", (sid,)).fetchone()
        assert (saved_model or "") == expected
        assert permissions == ("read-only" if readonly else "default")
        starts = [t for t in traces if t["workspace"] == workspace and t["kind"] in {"session/new", "session/load", "session/resume"}]
        assert starts, (sid, traces)
        selected = [json.loads(t["text"]) for t in traces if t["workspace"] == workspace and t["kind"] == "selection"]
        selected = [v.get("value", v.get("modelId")) for v in selected if v.get("configId") == "model" or "modelId" in v]
        if expected:
            assert selected and set(selected) == {expected}, (sid, expected, selected)
        else:
            assert not selected, (sid, selected)
        if sid == result["sessionId"] and marker == "REPAIR_ONCE":
            assert len(starts) == 2  # initial spawn and actual Chat resume
        if readonly:
            policies = [json.loads(t["text"]) for t in traces if t["workspace"] == workspace and t["kind"] == "policy" and t["text"]]
            assert policies and all(p["permission"] == "deny" for p in policies)
    # Historical reads do not recompute choices from new project defaults.
    assert api("/api/v1/clao/missions/" + result["request"]["id"])[1]["mission"] == result


def test_native_ordinary_chat_keeps_project_model_inheritance(native):
    _, api, _, source, _, temp = native
    project_id = next(p["id"] for p in api("/api/v1/projects")[1]["projects"] if Path(p["path"]) == source)
    for project_model, explicit in [("test/second", ""), ("test/native", "test/second")]:
        status, response = api(f"/api/v1/projects/{project_id}/config", {"config": {
            "defaultBranch": "main", "worker": {"agent": "opencode", "agentConfig": {"model": project_model}}
        }}, method="PUT")
        assert status == 200, response
        status, response = api("/api/v1/sessions", {"projectId": project_id, "kind": "worker", "mode": "chat", "model": explicit})
        assert status in (200, 201), response
        session = response["session"]
        expected = explicit or project_model
        assert session["model"] == expected
        traces = [json.loads(line) for line in (temp / "external.jsonl").read_text("utf-8").splitlines()]
        with sqlite3.connect(temp / "isolated-home/native/data/ao.db") as db:
            workspace, saved = db.execute("SELECT workspace_path, model FROM sessions WHERE id = ?", (session["id"],)).fetchone()
        assert saved == expected
        choices = [json.loads(t["text"]) for t in traces if t["kind"] == "selection" and t["workspace"] == workspace]
        assert any(t.get("value", t.get("modelId")) == expected for t in choices), choices
        assert api("/api/v1/sessions/" + session["id"] + "/kill", {})[0] == 200
