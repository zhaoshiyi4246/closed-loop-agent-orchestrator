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
def native(tmp_path, native_engine):
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
                "CLAO_CORE_PYTHON": sys.executable, "CLAO_CORE_ROOT": str(ROOT / "clao"),
                "CLAO_FIXTURE_TRACE": str(tmp_path / "external.jsonl")})
    log_path = tmp_path / "daemon.log"
    log = log_path.open("wb")
    proc = subprocess.Popen([str(binary), "daemon"], env=env, cwd=AO / "frontend", stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"

    def api(path, body=None, headers=None):
        request = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                         headers={"Origin": url, "Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                return response.status, json.load(response) if response.status != 204 else {}
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

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

        def submit(objective, repairs=1, agent="opencode", on_running=None):
            spec = {"id": "clao-test-" + hashlib.sha256(objective.encode()).hexdigest()[:12], "projectId": project_id,
                    "objective": objective, "agent": agent, "model": "test/native", "allowedPaths": ["**"], "forbiddenPaths": ["private/**"],
                    "criteria": [{"id": "AC1", "description": "result.txt contains accepted"}], "gateCommands": ["python check.py"],
                    "maxRepairs": repairs, "gateTimeout": 10}
            status, result = api("/api/v1/clao/missions", spec, {"X-CLAO-Nonce": nonce["nonce"]})
            assert status == 202, (result, log_path.read_text("utf-8", errors="replace")[-7000:])
            # Replay the exact receipt: it may observe progress but cannot spawn twice.
            assert api("/api/v1/clao/missions", spec, {"X-CLAO-Nonce": nonce["nonce"]})[0] == 202
            for _ in range(200):
                status, result = api("/api/v1/clao/missions/" + spec["id"])
                assert status == 200, result
                if on_running and result["mission"].get("sessionId"):
                    on_running(result["mission"])
                if result["mission"]["state"] in {"DONE", "FAILED", "UNKNOWN", "CANCELLED"}:
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
    assert result["base"] == base
    assert result["sessionId"] != result["verifierSessionId"]
    assert (Path(result["workspace"]) / "result.txt").read_text() == "accepted\n"
    assert git(Path(result["workspace"]), "show", result["resultHead"] + ":result.txt") == "accepted"
    assert result["evidence"][-1]["verification"]["verdict"] == "PASS"
    assert all(op["state"] == "CONFIRMED_SUCCESS" for op in result["operations"])


def test_native_gate_failure_sends_only_one_repair(native):
    submit, api, nonce, source, base, temp = native
    result = submit("FAIL_GATE always keep the failure visible", repairs=1)
    assert result["state"] == "FAILED", json.dumps(result, ensure_ascii=False)
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
    if result['state'] == 'UNKNOWN' and 'Codex account setup did not complete' in result['reason']:
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
