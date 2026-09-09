"""M4 first slice: real config/roles/Git/Store/HTTP, isolated external boundaries."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid
import zipfile
from types import SimpleNamespace

import pytest
import run_mission
from panel import server
from loopcore import credentials, effective_config as config
from loopcore.model_profiles import (SERVICE, KIMI_SERVICE, CODEX_API, CODEX_ACCOUNT,
    CODING_SERVICE, CLAUDE_ACCOUNT, CLAUDE_API, NATIVE_SERVICES, NATIVE_ACCOUNTS, TERMINAL_SERVICES, ENDPOINTS, parameter_defaults, check_start)
from loopcore.model_connections import ModelCatalogs
from loopcore.native_models import NativeSemanticTransport
from loopcore.execution_control import ExecutionControl, ExecutionCancelled
from loopcore.state_store import StateStore
from loopcore.diagnostics import Diagnostics
from loopcore.structured import ProtocolError
from tests.test_p01_bigmodel import profile, roles, envelope, BUILD_PLANNER
from tests.test_p02_kimi import services_http, pipeline as http_pipeline, kimi_profile, KEYS
from loopcore.auditor import CodexCliAuditorProvider
from tests.test_codex_planner import _plan, _action, _audit, MISSION
from tests.test_codex_auditor import _bundle, _result as audit_result
from tests.test_codex_verifier import _input, _result as verify_result
from tests.test_f04_panel_boundaries import panel, http_panel, request
from tests.test_u02_local_execution import engine
from tests.test_u02_journey import journey, form, until, methods

FACTORY = credentials.credentials


def pipeline(journey, services_http, monkeypatch):
    http_pipeline(journey, services_http, monkeypatch)
    # No role/Controller substitute in M4's end-to-end path, even for roles that
    # should remain uncalled on the normal gate-first route.
    monkeypatch.setattr(run_mission,'build_planner',BUILD_PLANNER)
    monkeypatch.setattr(run_mission,'CodexCliAuditorProvider',CodexCliAuditorProvider)


def modern(service=SERVICE, model='glm-5.3', **changes):
    native = service in (*NATIVE_SERVICES, *TERMINAL_SERVICES)
    p = dict(id='m4-'+service, label='工作账号 中文 <tag> "', service=service, endpoint=ENDPOINTS[service],
             model=model, credential_ref='m4-key', parameters=parameter_defaults(service, model),
             timeout_seconds=5.125, max_attempts=1 if native else 2, retry_delay_seconds=0)
    p.update(changes)
    return p


def settings(p):
    return config.resolve_config({'model_profiles': [p], 'roles': {r: {'profile': p['id']} for r in ('planner', 'auditor', 'verifier')}})


@pytest.fixture
def vaults(monkeypatch):
    # Exercise real WinCred, but prefix EVERY target at the native boundary.
    namespace = 'CLAO-M4-Isolated/'+uuid.uuid4().hex+'/'
    original = credentials.WindowsCredentials
    touched = set()
    def create(service=SERVICE):
        vault = FACTORY(service)
        save = vault.save
        def isolated_save(ref, key):
            touched.add((service, ref)); save(ref, key)
        vault.save = isolated_save
        return vault
    monkeypatch.setattr(credentials, 'WindowsCredentials', lambda value: original(namespace+value))
    monkeypatch.setattr(credentials, 'credentials', create)
    yield create
    for service, ref in touched:
        vault = FACTORY(service); vault.delete(ref); assert vault.read(ref) is None


def edit(panel, service=SERVICE, model='glm-5.3', **changes):
    p = modern(service, model)
    body = {k: v for k, v in p.items() if k not in ('id', 'endpoint', 'credential_ref')}
    body.update(action='save', revision=panel.state.defaults().snapshot()['revision'])
    if service not in NATIVE_ACCOUNTS:
        body['key'] = 'm4-fake-'+service
    body.update(changes)
    return request(panel, 'POST', '/api/model-connections', body)


def test_connection_atomic_save_namespaces_rotation_and_v2_history(http_panel, vaults, monkeypatch):
    legacy = config.resolve_config({'model_profiles': [profile(), kimi_profile()]})
    # A byte-for-byte v2 snapshot continues to restore without adding v3 fields.
    old = config.EffectiveConfig(config.nest({k: v for k, v in config.flatten(legacy).items() if k in config.V2_FIELDS}),
        {k: legacy.sources[k] for k in config.V2_FIELDS}, schema_version=2).snapshot()
    assert config.restore_snapshot(old).snapshot() == old
    http_panel.state.set_config(dict(legacy))
    vaults(KIMI_SERVICE).save('test-key', 'm4-fake-retained-kimi')
    for service in (SERVICE, KIMI_SERVICE, CODING_SERVICE, CODEX_API):
        vaults(service).save('shared', 'm4-fake-'+service)
    for service in (SERVICE, KIMI_SERVICE, CODING_SERVICE, CODEX_API):
        assert vaults(service).read('shared') == 'm4-fake-'+service
    result = edit(http_panel)
    assert result[0] == 200, result
    saved = result[2]['config']['values']['model_profiles'][-1]
    frozen = result[2]['config']
    assert 'm4-fake-' not in json.dumps(frozen)
    assert saved['credential_ref'].startswith('c-') and saved['id'].startswith('c-')
    rotated = edit(http_panel, id=saved['id'], key='m4-fake-replacement')
    assert rotated[0] == 200, rotated
    changed = rotated[2]['config']['values']['model_profiles'][-1]
    assert changed['credential_ref'] != saved['credential_ref']
    assert vaults(SERVICE).read(saved['credential_ref']) == 'm4-fake-'+SERVICE
    assert config.restore_snapshot(frozen)['model_profiles'][-1] == saved
    assert http_panel.state.defaults()['model_profiles'][:2] == [profile(), kimi_profile()]
    assert vaults(KIMI_SERVICE).read('test-key') == 'm4-fake-retained-kimi'
    before = http_panel.state.config_path.read_bytes()
    assert edit(http_panel, parameters={'thinking': 'disabled'})[0] == 400
    assert http_panel.state.config_path.read_bytes() == before
    restarted = server.PanelState(config_path=http_panel.state.config_path)
    assert restarted.defaults()['model_profiles'][-1] == changed
    monkeypatch.setattr(http_panel.state, 'set_config', lambda updates: (_ for _ in ()).throw(OSError('isolated save failure')))
    assert edit(http_panel)[0] == 400
    assert http_panel.state.config_path.read_bytes() == before


@pytest.mark.parametrize('headers', [{'Host':'evil.invalid'}, {'Origin':'https://evil.invalid'},
    {'X-Panel-Nonce':None}, {'X-Panel-Nonce':'wrong'}, {'Content-Type':'text/plain'}])
def test_new_connection_and_catalog_keep_write_boundaries(http_panel, vaults, headers):
    before=http_panel.state.config_path.read_bytes()
    for path in ('/api/model-connections', '/api/model-catalog', '/api/model-parameters'):
        assert request(http_panel,'POST',path,{},headers=headers)[0]>=400
    assert http_panel.state.config_path.read_bytes()==before


def test_glm53_all_real_role_consumers_and_custom_models(services_http):
    node=services_http[SERVICE]
    node.replies=[(200,envelope(r)) for r in (_plan(),_action(),audit_result(),verify_result())]
    planner,auditor,verifier=roles(settings(modern()))
    assert planner.plan_decompose(MISSION,'DECOMP').mission_id==MISSION['mission_id']
    assert planner.plan(_audit(),{'task_id':'TASK-1'},'ACT-1').action=='CANDIDATE_DONE'
    assert auditor.audit(_bundle(),'AUD-CODEX').decision=='LOCAL_FIX'
    assert verifier.verify(_input(),'VERIFY-CODEX').verdict=='PASS'
    assert len(node.calls)==4
    for call in node.calls:
        assert call['model']=='glm-5.3' and call['thinking']=={'type':'enabled'}
        assert call['reasoning_effort']=='max' and call['temperature']==1.0
        assert call['response_format']=={'type':'json_object'} and call['max_tokens']==8192
    p=modern(model='glm-custom-official-id')
    node.calls.clear();node.replies=[(200,envelope(verify_result()))]
    assert roles(settings(p))[2].verify(_input(),'VERIFY-CODEX').verdict=='PASS'
    assert not {'thinking','reasoning_effort','temperature','max_tokens'} & set(node.calls[0])
    with pytest.raises(ValueError):settings(modern(parameters=dict(parameter_defaults(SERVICE,'glm-5.3'),thinking='disabled')))
    assert roles(settings(profile()))[0].transport.profile['model']=='glm-4.7'


def test_catalog_cache_failure_custom_and_freeze(http_panel, vaults, monkeypatch):
    p=edit(http_panel)[2]['config']['values']['model_profiles'][-1]
    frozen=http_panel.state.defaults().snapshot();calls=[]
    def document(url):calls.append(url);return '# Models\n[GLM-5.3](url)\n[GLM-new-official](url)'
    monkeypatch.setattr('loopcore.model_connections.public_document',document)
    body={'id':p['id'],'refresh':False}
    assert request(http_panel,'POST','/api/model-catalog',body)[2]['catalog']['status']=='not_checked' and not calls
    body['refresh']=True
    c=request(http_panel,'POST','/api/model-catalog',body)[2]['catalog']
    assert c['status']=='ready' and c['custom_model'] and c['connection_status']=='configured'
    assert [m['id'] for m in c['models']]==['glm-5.3','glm-new-official']
    monkeypatch.setattr('loopcore.model_connections.public_document',lambda url:(_ for _ in ()).throw(OSError('secret must not echo')))
    failed=request(http_panel,'POST','/api/model-catalog',body)[2]['catalog']
    assert failed['status']=='read_error' and failed['models']==c['models'] and 'secret' not in failed['error']
    assert http_panel.state.defaults().snapshot()==frozen
    assert request(http_panel,'POST','/api/model-catalog',{'id':'../../outside','refresh':True})[0]==400


@pytest.fixture
def native(engine, monkeypatch, tmp_path):
    prior=subprocess.Popen
    trace=tmp_path/'native-trace.jsonl'
    response={'value': 'unused'}
    calls=[]
    claude=str(tmp_path/'fake-claude.exe')
    original_which=run_mission.shutil.which
    monkeypatch.setattr(run_mission.shutil,'which',lambda name:claude if name=='claude' else original_which(name))
    def popen(argv,*args,**kwargs):
        if argv[0]==claude or argv[0]==engine.executable and 'exec' in argv:
            env=kwargs.get('env',{})
            service=(CODING_SERVICE if 'ANTHROPIC_AUTH_TOKEN' in env else CLAUDE_API if 'ANTHROPIC_API_KEY' in env else CLAUDE_ACCOUNT) if argv[0]==claude else CODEX_API if 'CODEX_API_KEY' in env else CODEX_ACCOUNT
            if '--version' not in argv and '--help' not in argv and argv[1:]!=['auth','status']:
                assert all(k not in env for k in ('KIMI_API_KEY','GLM_API_KEY','UNRELATED_SECRET'))
                assert 'm4-fake-' not in json.dumps(argv)
                if service==CODING_SERVICE:
                    assert env['ANTHROPIC_AUTH_TOKEN']=='m4-fake-'+CODING_SERVICE and 'CODEX_API_KEY' not in env
                elif service==CLAUDE_API:
                    assert env['ANTHROPIC_API_KEY']=='m4-fake-'+CLAUDE_API and 'CODEX_API_KEY' not in env
                elif service==CODEX_API:
                    assert env['CODEX_API_KEY']=='m4-fake-'+CODEX_API and 'ANTHROPIC_AUTH_TOKEN' not in env
                else:
                    assert 'CODEX_API_KEY' not in env and 'ANTHROPIC_AUTH_TOKEN' not in env
                calls.append((service,copy.deepcopy(argv),copy.deepcopy(env)))
            kwargs['env']=dict(env,CLAO_TEST_NATIVE_TRACE=str(trace),CLAO_TEST_NATIVE_RESPONSE=json.dumps(response['value']),
                               CLAO_TEST_NATIVE_DELAY=response.get('delay',''))
            argv=[sys.executable,str(Path(__file__).parent/'fixtures/native_semantic.py'),*argv[1:]]
        return prior(argv,*args,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',popen)
    monkeypatch.setenv('UNRELATED_SECRET','never-forward')
    return SimpleNamespace(response=response,trace=trace,calls=calls)


@pytest.mark.parametrize('service',[CODING_SERVICE,CODEX_API,CODEX_ACCOUNT,CLAUDE_API,CLAUDE_ACCOUNT])
def test_native_semantic_all_roles_and_no_key_leak(native,vaults,service,tmp_path):
    if service not in NATIVE_ACCOUNTS:vaults(service).save('m4-key','m4-fake-'+service)
    p=modern(service,'glm-5.3' if service==CODING_SERVICE else 'gpt-5.6-sol')
    planner,auditor,verifier=roles(settings(p))
    results=(_plan(),_action(),audit_result(),verify_result())
    operations=(lambda:planner.plan_decompose(MISSION,'DECOMP'),lambda:planner.plan(_audit(),{'task_id':'TASK-1'},'ACT-1'),
                lambda:auditor.audit(_bundle(),'AUD-CODEX'),lambda:verifier.verify(_input(),'VERIFY-CODEX'))
    for reply,operation in zip(results,operations):
        native.response['value']=dict(type='result',subtype='success',is_error=False,structured_output=reply) if service in (CODING_SERVICE,CLAUDE_API,CLAUDE_ACCOUNT) else reply
        assert operation()
    assert len(native.calls)==4
    assert all(argv[argv.index('--model')+1]==p['model'] for _,argv,_ in native.calls)
    assert 'm4-fake-' not in native.trace.read_text('utf-8')
    if service==CODING_SERVICE:
        assert all(env['ANTHROPIC_BASE_URL']==ENDPOINTS[CODING_SERVICE] for _,_,env in native.calls)


@pytest.mark.parametrize('service',[CODEX_ACCOUNT,CLAUDE_ACCOUNT,CLAUDE_API])
def test_native_model_default_is_omitted_not_current_or_recommended(native,vaults,service):
    if service==CLAUDE_API:vaults(service).save('m4-key','m4-fake-'+service)
    native.response['value']=verify_result() if service==CODEX_ACCOUNT else dict(type='result',subtype='success',is_error=False,structured_output=verify_result())
    cfg=settings(modern(service,''));frozen=cfg.snapshot()
    assert roles(cfg)[2].verify(_input(),'VERIFY-CODEX').verdict=='PASS'
    assert len(native.calls)==1 and '--model' not in native.calls[0][1]
    assert config.restore_snapshot(frozen)['model_profiles'][0]['model']==''


def test_claude_account_does_not_accept_native_api_identity(native,monkeypatch):
    monkeypatch.setattr('loopcore.native_auth.status',lambda _:dict(auth='connected',method='api_key'))
    with pytest.raises(ProtocolError,match='账号登录'):
        roles(settings(modern(CLAUDE_ACCOUNT,'')))[2].verify(_input(),'VERIFY-CODEX')
    assert not native.calls


@pytest.mark.parametrize('mode',['error','missing','bad-schema','cancel'])
def test_native_failure_cancel_do_not_fake_pass_or_retry(native,vaults,mode,tmp_path):
    vaults(CODING_SERVICE).save('m4-key','m4-fake-'+CODING_SERVICE)
    result=dict(type='result',subtype='success',is_error=False,structured_output=verify_result())
    if mode=='error':result.update(is_error=True,result='PASS')
    if mode=='missing':result.pop('structured_output');result['result']='PASS'
    if mode=='bad-schema':result['structured_output']={'verdict':'PASS'}
    native.response['value']=result
    verifier=roles(settings(modern(CODING_SERVICE)))[2]
    if mode=='cancel':
        native.response['delay']='4'
        event=threading.Event();timer=threading.Timer(.6,event.set);timer.start()
        try:
            with ExecutionControl(event).bind(),pytest.raises(ExecutionCancelled):verifier.verify(_input(),'VERIFY-CODEX')
        finally:timer.cancel()
    else:
        with pytest.raises(Exception):verifier.verify(_input(),'VERIFY-CODEX')
    assert len(native.calls)<=1


@pytest.mark.parametrize('route',[SERVICE,CODING_SERVICE,CODEX_API])
def test_actual_http_controller_gate_result_native_or_glm53(journey,services_http,native,vaults,monkeypatch,tmp_path,route):
    pipeline(journey,services_http,monkeypatch)
    # Only isolated OS credential targets; native and HTTP readers use real storage.
    for service in (SERVICE,CODING_SERVICE,CODEX_API):
        vaults(service).save('m4-key',KEYS[service] if service in KEYS else 'm4-fake-'+service)
    p=modern(route,'gpt-5.6-sol' if route==CODEX_API else 'glm-5.3')
    worker=modern(CODEX_API,'gpt-5.6-sol',id='api-worker')
    cfg=config.resolve_config(journey.state.defaults(),overrides={'model_profiles':[p,worker],
        'roles':{'verifier':{'profile':p['id']}},'worker':{'profile':worker['id']}})
    journey.state.set_config(dict(cfg));body=form(journey,tmp_path/'原项目 中文')
    body['config_snapshot']=cfg.snapshot()
    if route!=CODEX_API:
        assert request(journey,'POST','/api/mission',body)[0]==400
        assert not methods(journey)
        # GLM standard consent is not consent to the Coding Plan path.
        if route==CODING_SERVICE:assert request(journey,'POST','/api/mission',dict(body,external_service_consent=SERVICE))[0]==400
        body['external_service_consent']=[route]
    native.response['value']='auto-verifier'
    response=request(journey,'POST','/api/mission',body);assert response[0]==200,json.dumps(response[2],ensure_ascii=True)
    data=until(journey,lambda d:d.get('mission',{}).get('state') in run_mission.MISSION_TERMINAL,timeout=30)
    assert data['mission']['state']=='MISSION_DONE',data['mission']
    assert {'account/login/start','thread/start','turn/start'} <= set(methods(journey))
    assert journey.state.rt.store.mission_config(data['mission']['id'])['worker_stop']['status']=='CONFIRMED'
    assert data['mission_config']['snapshot']['values']==cfg.snapshot()['values']
    assert (tmp_path/'原项目 中文'/'app.py').read_text()=='x=0\n'
    exported=request(journey,'POST','/api/result/export',{'mission_id':data['mission']['id']});assert exported[0]==200,exported
    raw=request(journey,path='/api/result/download?mission_id='+data['mission']['id']+'&export_id='+exported[2]['export']['identity'])[2]
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        assert all(b'm4-fake-' not in package.read(n) for n in package.namelist())


def test_codex_catalog_uses_public_protocol_without_worker(journey,vaults):
    p=modern(CODEX_API,'gpt-5.6-sol');vaults(CODEX_API).save('m4-key','m4-fake-'+CODEX_API)
    cfg=journey.state.defaults();journey.state.set_config({'model_profiles':[p]})
    result=request(journey,'POST','/api/model-catalog',{'id':p['id'],'refresh':True})
    assert result[2]['catalog']['status']=='ready',result
    assert result[2]['catalog']['models'][0]['id']=='gpt-test-catalog'
    assert not {'thread/start','turn/start'} & set(methods(journey))


def test_custom_native_model_and_legacy_ao_cannot_borrow_new_worker_auth(tmp_path,monkeypatch):
    from loopcore.model_profiles import validate_profiles
    validate_profiles([modern(CODING_SERVICE,'glm-5.3[1m]')])
    from loopcore.bigmodel import BigModelTransport
    from loopcore.structured import ContractConfigurationError
    with pytest.raises(ContractConfigurationError,match='native'):
        BigModelTransport(modern(CODING_SERVICE))
    monkeypatch.setattr(run_mission,'ROOT',tmp_path)
    cfg=config.resolve_config({'model_profiles':[modern(CODEX_API)],'worker':{'profile':'m4-'+CODEX_API}})
    with pytest.raises(config.ConfigError,match='Worker'):
        run_mission.build_runtime({'mission_id':'OLD-AO','execution_backend':'ao'},cfg)
    assert not (tmp_path/'runtime'/'OLD-AO'/'state.db').exists()


def test_kimi_catalog_same_service_key_and_default_are_not_shared_between_profiles(services_http,vaults):
    p=modern(KIMI_SERVICE,'kimi-k3')
    vaults(KIMI_SERVICE).save(p['credential_ref'],KEYS[KIMI_SERVICE])
    catalogs=ModelCatalogs();result=catalogs.refresh(p)
    assert result['status']=='ready' and result['connection_status']=='connected'
    assert [m['id'] for m in result['models']]==['kimi-k3','kimi-new-official']
    other=dict(p,model='kimi-new-official')
    # Current selection is not evidence of an executor/account default.
    assert not any(m['is_default'] for m in catalogs.read(other)['models'])
    assert catalogs.read(other)['models']==catalogs.read(p)['models']
    assert all(not node.calls for node in services_http.values())


def test_browser_unified_connections_and_real_journey(journey,services_http,vaults,monkeypatch,tmp_path):
    pipeline(journey,services_http,monkeypatch)
    # HTTP fixture expects its isolated BigModel credential; new UI fields still
    # store/read only the OS targets prefixed by vaults above.
    from tests.test_p02_kimi import KEYS
    KEY = 'm4-fake-'+SERVICE
    monkeypatch.setitem(KEYS,SERVICE,KEY)
    old=kimi_profile();vaults(KIMI_SERVICE).save(old['credential_ref'],'m4-fake-kimi-retained')
    journey.state.set_config({'model_profiles':[old]})
    catalog_calls=[]
    def catalog_document(url):
        catalog_calls.append(url)
        if len(catalog_calls)==3:raise OSError('isolated catalog unavailable')
        return '# Models\nGLM-5.3\nGLM-custom-official'
    monkeypatch.setattr('loopcore.model_connections.public_document',catalog_document)
    a=form(journey,tmp_path/'项目 A');b=form(journey,tmp_path/'项目 B')
    output=Path(os.environ.get('M4_SCREENSHOTS',str(tmp_path/'shots')))
    script=Path(__file__).resolve().parents[2]/'dev/panel/m4-connections.cjs'
    result=subprocess.run([os.environ['U01_NODE'],str(script),journey.origin,a['project_id'],b['project_id'],str(output)],
                          capture_output=True,encoding='utf-8',errors='replace',timeout=150)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert len(services_http[SERVICE].calls)==1 and methods(journey).count('thread/start')==1
    assert vaults(KIMI_SERVICE).read(old['credential_ref'])=='m4-fake-kimi-retained'
    assert (tmp_path/'项目 A'/'app.py').read_text()=='x=0\n'
    print(result.stdout)
