"""P01 real local HTTP + shared role contracts; no external model requests."""
import copy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from types import SimpleNamespace

import pytest

import run_mission
from loopcore import credentials, effective_config as config
from loopcore.bigmodel import BigModelTransport, role_options
from loopcore.model_profiles import ENDPOINT, SERVICE, check_start
from loopcore.planner_adapter import CodexCliPlannerProvider
from loopcore.auditor import CodexCliAuditorProvider
from loopcore.verifier import CodexCliVerifierProvider
from loopcore.diagnostics import Diagnostics
from loopcore.execution_control import ExecutionControl, ExecutionCancelled
from loopcore.structured import ProtocolError
from loopcore.state_store import StateStore
from tests.test_codex_planner import _plan, _action, _audit, MISSION
from tests.test_codex_auditor import _bundle, _result as audit_result
from tests.test_codex_verifier import _input, _result as verify_result

FAKE_KEY = 'p01-isolated-fake-credential-never-a-real-key'
BUILD_PLANNER = run_mission.build_planner


def profile(**changes):
    return dict(id='glm-review', service=SERVICE, endpoint=ENDPOINT, model='glm-4.7',
                credential_ref='test-key', timeout_seconds=2.25, max_attempts=2,
                retry_delay_seconds=0, thinking='disabled', temperature=.25,
                max_tokens=4096, **changes)


def configuration(roles=('planner', 'auditor', 'verifier'), **changes):
    p = profile(); p.update(changes)
    return config.resolve_config({'model_profiles': [p],
        'roles': {r: {'profile': p['id']} for r in roles}})


def envelope(result, **changes):
    return dict(model='glm-4.7-resolved', usage={'prompt_tokens': 20, 'completion_tokens': 30, 'total_tokens': 50},
                choices=[dict(index=0, finish_reason='stop', message=dict(role='assistant', content=json.dumps(result)))], **changes)


@pytest.fixture
def glm_http(monkeypatch):
    # Only the external socket boundary changes; production URL validation,
    # headers, serialization, status parsing, roles and validators all run.
    state = SimpleNamespace(calls=[], replies=[], responder=None, entered=threading.Event(), release=threading.Event())
    state.release.set()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.path == '/api/paas/v4/chat/completions'
            assert self.headers['Authorization'] == 'Bearer ' + FAKE_KEY
            state.calls.append(body); state.entered.set(); state.release.wait(6)
            reply = state.responder(body) if state.responder else state.replies[min(len(state.calls)-1, len(state.replies)-1)]
            if reply == 'disconnect':
                self.connection.close(); return
            status, data = reply
            raw = data if isinstance(data, bytes) else json.dumps(data).encode()
            try:
                self.send_response(status); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
            except OSError: pass
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': .02}, daemon=True); thread.start()
    def connection(host, *, timeout):
        assert host == 'open.bigmodel.cn'
        return http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=timeout)
    monkeypatch.setattr(http.client, 'HTTPSConnection', connection)
    monkeypatch.setattr(credentials, 'credentials', lambda: SimpleNamespace(read=lambda ref: FAKE_KEY, configured=lambda ref: True))
    yield state
    state.release.set(); httpd.shutdown(); httpd.server_close(); thread.join(3)


def roles(cfg=None):
    cfg = cfg or configuration()
    return (BUILD_PLANNER(cfg), CodexCliAuditorProvider(**role_options(cfg, 'auditor')),
            CodexCliVerifierProvider(**role_options(cfg, 'verifier')))


def test_real_http_all_roles_share_prompts_schema_and_formal_content(glm_http, tmp_path):
    glm_http.replies = [(200, envelope(r)) for r in (_plan(), _action(), audit_result(), verify_result())]
    planner, auditor, verifier = roles()
    store = StateStore(tmp_path/'state.db'); diag = Diagnostics(store, 'M-CODEX')
    for p in (planner, auditor, verifier): p.diagnostics = diag
    try:
        assert planner.plan_decompose(MISSION, 'DECOMP').mission_id == 'M-CODEX'
        assert planner.plan(_audit(), {'task_id':'TASK-1'}, 'ACT-1').action == 'CANDIDATE_DONE'
        assert auditor.audit(_bundle(), 'AUD-CODEX').decision == 'LOCAL_FIX'
        assert verifier.verify(_input(), 'VERIFY-CODEX').verdict == 'PASS'
        assert len(glm_http.calls) == 4
        for i, call in enumerate(glm_http.calls):
            assert call['model'] == 'glm-4.7' and call['stream'] is False
            assert call['response_format'] == {'type':'json_object'}
            assert call['thinking'] == {'type':'disabled'} and call['temperature'] == .25
            assert call['max_tokens'] == 4096 and 'reasoning_effort' not in call
            assert FAKE_KEY not in json.dumps(call)
            assert (planner.decompose_prompt, planner.system_prompt, auditor.system_prompt, verifier.system_prompt)[i] in call['messages'][1]['content']
        rows = store._conn.execute('select payload_json from execution_phases').fetchall()
        text = json.dumps([tuple(r) for r in rows])
        assert FAKE_KEY not in text and planner.system_prompt not in text
        assert 'glm-4.7-resolved' in text and 'bigmodel_general' in text and 'completion_tokens' in text
    finally: store.close()


@pytest.mark.parametrize('case,category,attempts', [
    ('auth','AUTH',1), ('rate','RATE_LIMIT',3), ('disconnect','NETWORK',3),
    ('json','JSON_PARSE',3), ('schema','SCHEMA',3), ('correlation','CORRELATION',3),
    ('coherence','COHERENCE',3), ('refusal','REFUSAL',1), ('truncated','TRUNCATED',1),
    ('tool','CAPABILITY',1), ('reasoning_only','JSON_PARSE',3), ('secret_echo','CAPABILITY',1),
    ('wrong_endpoint','CAPABILITY',1),
])
def test_http_and_role_errors_share_one_total_budget(glm_http, case, category, attempts):
    data = envelope(verify_result())
    status = 200
    if case == 'auth': status = 401; data = {'error':FAKE_KEY}
    if case == 'rate': status = 429
    if case == 'wrong_endpoint': status = 302
    if case == 'json': data['choices'][0]['message']['content'] = 'not JSON'
    if case == 'schema': data['choices'][0]['message']['content'] = '{}'
    if case == 'correlation':
        obj = verify_result(); obj['task_id'] = 'OTHER'; data = envelope(obj)
    if case == 'coherence':
        obj = verify_result(); obj['ac_checks'][0]['verdict'] = 'FAIL'; data = envelope(obj)
    if case == 'refusal': data['choices'][0]['message']['refusal'] = 'refused'
    if case == 'truncated': data['choices'][0]['finish_reason'] = 'length'
    if case == 'tool': data['choices'][0]['message']['tool_calls'] = [{'type':'function'}]
    if case == 'reasoning_only': data['choices'][0]['message'] = {'role':'assistant', 'reasoning_content':json.dumps(verify_result())}
    if case == 'secret_echo': data['choices'][0]['message']['content'] = FAKE_KEY
    glm_http.replies = ['disconnect' if case == 'disconnect' else (status, data)]
    verifier = roles(configuration(max_attempts=3))[2]
    with pytest.raises(ProtocolError) as err: verifier.verify(_input(), 'VERIFY-CODEX')
    assert err.value.category == category and err.value.attempts == attempts
    assert FAKE_KEY not in str(err.value) and FAKE_KEY not in json.dumps(err.value.payload())
    assert len(glm_http.calls) == attempts


def test_semantic_fail_never_retried_and_thinking_never_overrides_content(glm_http):
    data = envelope(verify_result('FAIL'))
    data['choices'][0]['message']['reasoning_content'] = json.dumps(verify_result('PASS'))
    glm_http.replies = [(200, data)]
    assert roles()[2].verify(_input(), 'VERIFY-CODEX').verdict == 'FAIL'
    assert len(glm_http.calls) == 1


def test_missing_model_usage_not_guessed_and_encoded_echo_rejected(glm_http,tmp_path):
    data=envelope(verify_result());data.pop('model');data.pop('usage')
    glm_http.replies=[(200,data)]
    provider=roles()[2];store=StateStore(tmp_path/'state.db');provider.diagnostics=Diagnostics(store,'M')
    try:
        assert provider.verify(_input(),'VERIFY-CODEX').verdict=='PASS'
        fact=StateStore.query_phases(store._conn,'M')['roles']['verifier']
        assert fact['requested_model']=='glm-4.7' and fact['passed_model']=='glm-4.7'
        assert fact['confirmed_model'] is None and fact['usage'] is None and fact['cost'] is None
        obj=verify_result();obj['summary']=FAKE_KEY
        content=json.dumps(obj).replace(FAKE_KEY,''.join('\\u%04x'%ord(c) for c in FAKE_KEY))
        data['choices'][0]['message']['content']=content
        glm_http.replies=[(200,data)]
        with pytest.raises(ProtocolError,match='credential material'):
            provider.verify(_input(),'VERIFY-CODEX')
        assert FAKE_KEY.encode() not in (tmp_path/'state.db').read_bytes()
    finally:store.close()


def test_ac_coverage_not_repaired(glm_http):
    obj = verify_result(); obj['ac_checks'][0]['ac_id'] = 'wrong-ac'
    glm_http.replies = [(200, envelope(obj))]
    with pytest.raises(ProtocolError, match='CORRELATION|COHERENCE'):
        roles()[2].verify(_input(), 'VERIFY-CODEX')


@pytest.mark.parametrize('during', ['request','retry_wait'])
def test_cancel_stops_retries_and_discards_late_success(glm_http, during):
    stop = threading.Event(); result = []
    glm_http.replies = [(429, {})] if during == 'retry_wait' else [(200, envelope(verify_result()))]
    if during == 'request': glm_http.release.clear()
    verifier = roles(configuration(retry_delay_seconds=2))[2]
    def invoke():
        try:
            with ExecutionControl(stop).bind(): result.append(verifier.verify(_input(), 'VERIFY-CODEX'))
        except BaseException as exc: result.append(exc)
    thread = threading.Thread(target=invoke); thread.start()
    try:
        assert glm_http.entered.wait(3)
        if during == 'retry_wait': time.sleep(.15)
        stop.set(); thread.join(2)
        assert not thread.is_alive() and len(result) == 1 and isinstance(result[0], ExecutionCancelled)
        glm_http.release.set(); time.sleep(.1)
        assert len(glm_http.calls) == 1
    finally: stop.set(); glm_http.release.set(); thread.join(4)


def test_timeout_and_transient_recovery_are_bounded(glm_http):
    glm_http.replies = [(429, {}), (200, envelope(verify_result()))]
    assert roles()[2].verify(_input(), 'VERIFY-CODEX').verdict == 'PASS'
    assert len(glm_http.calls) == 2
    glm_http.calls.clear(); glm_http.release.clear()
    with pytest.raises(ProtocolError) as caught:
        roles(configuration(timeout_seconds=.08, max_attempts=1))[2].verify(_input(), 'VERIFY-CODEX')
    assert caught.value.category == 'TIMEOUT'


@pytest.mark.parametrize('change', [
    {'endpoint':'https://api.z.ai/api/paas/v4/chat/completions'}, {'endpoint':'http://127.0.0.1:9'},
    {'model':'unadmitted-model'}, {'thinking':'high'}, {'api_key':FAKE_KEY}, {'reasoning_effort':'high'},
    {'temperature':.123}, {'max_attempts':4}, {'max_attempts':1.5}, {'timeout_seconds':0},
    {'retry_delay_seconds':float('nan')}, {'max_tokens':0}, {'credential_ref':'../escape'},
])
def test_unsupported_profiles_rejected_without_values(change):
    with pytest.raises(config.ConfigError) as err: configuration(**change)
    assert FAKE_KEY not in str(err.value)


def test_old_config_and_snapshot_frozen_defaults_compatible():
    cfg = config.resolve_config({'roles': {'worker': {'model':'legacy-worker'}}})
    old = config.EffectiveConfig(config.nest({k:v for k,v in config.flatten(cfg).items() if k in config.LEGACY_FIELDS}),
        {k:cfg.sources[k] for k in config.LEGACY_FIELDS}, cfg.warnings, schema_version=1).snapshot()
    assert config.restore_snapshot(old).snapshot() == old
    assert role_options(config.restore_snapshot(old), 'planner')['model'] == 'gpt-5.6-sol'
    cfg = configuration(roles=('verifier',))
    frozen = cfg.snapshot()
    cfg['model_profiles'][0]['timeout_seconds'] = 33
    assert config.restore_snapshot(frozen)['model_profiles'][0]['timeout_seconds'] == 2.25
    assert isinstance(role_options(config.restore_snapshot(frozen),'verifier')['transport'], BigModelTransport)
    assert 'transport' not in role_options(cfg,'planner')
    with pytest.raises(config.ConfigError): config.resolve_config({'roles':{'worker':{'profile':'glm-review'}}})
    with pytest.raises(config.ConfigError): config.resolve_config({'roles':{'verifier':{'profile':'missing'}}})


def test_consent_and_missing_credentials_stop_before_provider(glm_http, monkeypatch):
    with pytest.raises(ValueError, match='BigModel'): check_start(configuration(), {})
    check_start(configuration(), {'external_service_consent':SERVICE})
    monkeypatch.setattr(credentials, 'credentials', lambda: SimpleNamespace(configured=lambda ref:False))
    with pytest.raises(ValueError, match='凭据'): check_start(configuration(), {'external_service_consent':SERVICE})
    assert not glm_http.calls
