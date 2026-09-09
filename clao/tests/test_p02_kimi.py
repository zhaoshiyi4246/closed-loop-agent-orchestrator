"""P02: two distinguishable local sockets, real roles/HTTP/Git/SQLite/WinCred.

No user keys or supplier traffic. Controller is never replaced for execution.
"""
import copy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid
import zipfile

import pytest
import run_mission
from panel import server
from loopcore import credentials, effective_config as config
from loopcore.model_profiles import (SERVICE, KIMI_SERVICE, KIMI_ENDPOINT, KIMI_MODEL,
                                     ENDPOINTS, check_start)
from loopcore.diagnostics import Diagnostics
from loopcore.execution_control import ExecutionControl, ExecutionCancelled
from loopcore.structured import ProtocolError
from loopcore.state_store import StateStore
from loopcore.verifier import CodexCliVerifierProvider
from tests.test_p01_bigmodel import profile, envelope, roles
from tests.test_codex_planner import _plan, _action, _audit, MISSION
from tests.test_codex_auditor import _bundle, _result as audit_result
from tests.test_codex_verifier import _input, _result as verify_result
from tests.test_f04_panel_boundaries import panel, http_panel, request
from tests.test_u02_local_execution import engine
from tests.test_u02_journey import journey, form, until, methods
from tests.test_r01_effective_config import runtime_root, mission

KEYS={SERVICE:'p02-fake-glm-not-a-real-key', KIMI_SERVICE:'p02-fake-kimi-not-a-real-key'}
CREDENTIAL_FACTORY=credentials.credentials


def kimi_profile(**changes):
    p=dict(id='kimi-review',service=KIMI_SERVICE,endpoint=KIMI_ENDPOINT,model=KIMI_MODEL,
        credential_ref='test-key',timeout_seconds=2.25,max_attempts=2,retry_delay_seconds=0,
        reasoning_effort='high',max_completion_tokens=8192)
    p.update(changes)
    return p


def settings(service=KIMI_SERVICE, **changes):
    p=kimi_profile() if service==KIMI_SERVICE else profile()
    p.update(changes)
    return config.resolve_config({'model_profiles':[p], 'roles':{r:{'profile':p['id']} for r in ('planner','auditor','verifier')}})


@pytest.fixture
def services_http(monkeypatch):
    nodes={};servers=[];threads=[]
    def handler(service,node):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                assert service==KIMI_SERVICE and self.path=='/v1/models'
                assert self.headers['Authorization']=='Bearer '+KEYS[service]
                raw=json.dumps({'data':[{'id':'kimi-k3'},{'id':'kimi-new-official'}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_POST(self):
                assert self.path==ENDPOINTS[service].split('.cn',1)[1]
                assert self.headers['Authorization']=='Bearer '+KEYS[service]
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                node.calls.append(body);node.entered.set();node.release.wait(8)
                reply=node.responder(body) if node.responder else node.replies[min(len(node.calls)-1,len(node.replies)-1)]
                if reply=='disconnect': self.connection.close();return
                status,data=reply
                raw=data if isinstance(data,bytes) else json.dumps(data).encode()
                try:
                    self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                except OSError: pass
        return Handler
    for service in (SERVICE, KIMI_SERVICE):
        node=SimpleNamespace(calls=[],replies=[],responder=None,entered=threading.Event(),release=threading.Event())
        node.release.set();nodes[service]=node
        httpd=ThreadingHTTPServer(('127.0.0.1',0),handler(service,node));node.port=httpd.server_port
        thread=threading.Thread(target=httpd.serve_forever,kwargs={'poll_interval':.02},daemon=True)
        thread.start();servers.append(httpd);threads.append(thread)
    original_http=http.client.HTTPConnection
    def connect(host,*,timeout):
        service={'open.bigmodel.cn':SERVICE,'api.moonshot.cn':KIMI_SERVICE}[host]
        return original_http('127.0.0.1',nodes[service].port,timeout=timeout)
    monkeypatch.setattr(http.client,'HTTPSConnection',connect)
    monkeypatch.setattr(credentials,'credentials',lambda service=SERVICE:SimpleNamespace(
        read=lambda ref:KEYS[service],configured=lambda ref:True))
    yield nodes
    for node in nodes.values():node.release.set()
    for httpd in servers:httpd.shutdown();httpd.server_close()
    for thread in threads:thread.join(3)


@pytest.fixture
def native_vaults(services_http,monkeypatch):
    assert os.name=='nt'
    prefix='CLAO-P02-Isolated-Test/'+uuid.uuid4().hex+'/'
    original=credentials.WindowsCredentials
    # Exercise the production service-to-target mapping, prefixing the OS
    # boundary so no production credential target can be read or written.
    monkeypatch.setattr(credentials,'WindowsCredentials',lambda namespace:original(prefix+namespace))
    monkeypatch.setattr(credentials,'credentials',CREDENTIAL_FACTORY)
    vaults={s:credentials.credentials(s) for s in (SERVICE, KIMI_SERVICE)}
    yield vaults
    for vault in vaults.values():
        for ref in ('test-key','shared'):
            vault.delete(ref);assert vault.read(ref) is None


@pytest.mark.parametrize('service',[SERVICE,KIMI_SERVICE])
def test_all_actual_roles_wire_contract_and_diagnostics(services_http,service,tmp_path):
    node=services_http[service]
    node.replies=[(200,dict(envelope(r),model='returned-'+service)) for r in (_plan(),_action(),audit_result(),verify_result())]
    cfg=settings(service);planner,auditor,verifier=roles(cfg)
    db=StateStore(tmp_path/'state.db');diag=Diagnostics(db,'M')
    for p in (planner,auditor,verifier):p.diagnostics=diag
    try:
        assert planner.plan_decompose(MISSION,'DECOMP').mission_id==MISSION['mission_id']
        assert planner.plan(_audit(),{'task_id':'TASK-1'},'ACT-1').action=='CANDIDATE_DONE'
        assert auditor.audit(_bundle(),'AUD-CODEX').decision=='LOCAL_FIX'
        assert verifier.verify(_input(),'VERIFY-CODEX').verdict=='PASS'
        assert len(node.calls)==4 and not services_http[KIMI_SERVICE if service==SERVICE else SERVICE].calls
        for i,call in enumerate(node.calls):
            p=cfg['model_profiles'][0]
            assert call['model']==p['model'] and call['stream'] is False
            assert call['response_format']=={'type':'json_object'} and 'tools' not in call
            assert (planner.decompose_prompt,planner.system_prompt,auditor.system_prompt,verifier.system_prompt)[i] in call['messages'][1]['content']
            if service==KIMI_SERVICE:
                assert call['reasoning_effort']=='high' and call['max_completion_tokens']==8192
                assert not {'thinking','temperature','top_p','max_tokens'} & call.keys()
            else:
                assert call['thinking']=={'type':'disabled'} and call['temperature']==.25 and call['max_tokens']==4096
                assert not {'reasoning_effort','max_completion_tokens'} & call.keys()
        facts=StateStore.query_phases(db._conn,'M')['roles']
        for role in ('planner','auditor','verifier'):
            assert facts[role]['provider']==service and facts[role]['confirmed_model']=='returned-'+service
            assert facts[role]['cost'] is None
        assert all(key.encode() not in (tmp_path/'state.db').read_bytes() for key in KEYS.values())
    finally:db.close()


@pytest.mark.parametrize('service',[SERVICE,KIMI_SERVICE])
@pytest.mark.parametrize('case,category,attempts',[
    ('json','JSON_PARSE',2),('id','CORRELATION',2),('ac','COHERENCE',2),('coherence','COHERENCE',2),
    ('auth','AUTH',1),('rate','RATE_LIMIT',2),('refusal','REFUSAL',1),('length','TRUNCATED',1),
    ('reasoning_only','JSON_PARSE',2),('tool','CAPABILITY',1),('echo','CAPABILITY',1),('redirect','CAPABILITY',1)])
def test_shared_errors_have_one_budget_no_fallback(services_http,service,case,category,attempts):
    obj=verify_result();data=envelope(obj);status=200
    if case=='id':obj['task_id']='wrong';data=envelope(obj)
    if case=='ac':obj['ac_checks'][0]['ac_id']='wrong';data=envelope(obj)
    if case=='coherence':obj['ac_checks'][0]['verdict']='FAIL';data=envelope(obj)
    if case=='json':data['choices'][0]['message']['content']='broken JSON'
    if case=='auth':status=401;data={'error':KEYS[service]}
    if case=='rate':status=429
    if case=='redirect':status=302
    if case=='refusal':data['choices'][0]['message']['refusal']='refused'
    if case=='length':data['choices'][0]['finish_reason']='length'
    if case=='reasoning_only':data['choices'][0]['message']={'role':'assistant','reasoning_content':json.dumps(obj)}
    if case=='tool':data['choices'][0]['message']['tool_calls']=[{'type':'function'}]
    if case=='echo':data['choices'][0]['message']['content']=KEYS[service]
    services_http[service].replies=[(status,data)]
    with pytest.raises(ProtocolError) as err:roles(settings(service))[2].verify(_input(),'VERIFY-CODEX')
    assert err.value.category==category and err.value.attempts==attempts
    assert len(services_http[service].calls)==attempts
    assert not services_http[KIMI_SERVICE if service==SERVICE else SERVICE].calls
    assert all(key not in str(err.value)+json.dumps(err.value.payload()) for key in KEYS.values())


@pytest.mark.parametrize('service',[SERVICE,KIMI_SERVICE])
def test_fail_unknown_usage_timeout_and_transient_recovery(services_http,service,tmp_path):
    node=services_http[service];data=envelope(verify_result('FAIL'));data.pop('model');data.pop('usage')
    data['choices'][0]['message']['reasoning_content']=json.dumps(verify_result('PASS'))
    node.replies=[(200,data)]
    p=roles(settings(service))[2];db=StateStore(tmp_path/'state.db');p.diagnostics=Diagnostics(db,'M')
    try:
        assert p.verify(_input(),'VERIFY-CODEX').verdict=='FAIL' and len(node.calls)==1
        fact=StateStore.query_phases(db._conn,'M')['roles']['verifier']
        assert fact['confirmed_model'] is None and fact['usage'] is None and fact['cost'] is None
        node.calls.clear();node.replies=[(429,{}),(200,envelope(verify_result()))]
        assert p.verify(_input(),'VERIFY-CODEX').verdict=='PASS' and len(node.calls)==2
        node.calls.clear();node.release.clear()
        with pytest.raises(ProtocolError) as err:roles(settings(service,timeout_seconds=.08,max_attempts=1))[2].verify(_input(),'VERIFY-CODEX')
        assert err.value.category=='TIMEOUT' and len(node.calls)==1
    finally:node.release.set();db.close()


@pytest.mark.parametrize('service',[SERVICE,KIMI_SERVICE])
@pytest.mark.parametrize('during',['request','retry_wait'])
def test_cancel_discards_late_result_and_no_further_attempt(services_http,service,during):
    node=services_http[service];stop=threading.Event();out=[]
    node.replies=[(429,{})] if during=='retry_wait' else [(200,envelope(verify_result()))]
    if during=='request':node.release.clear()
    def invoke():
        try:
            with ExecutionControl(stop).bind():out.append(roles(settings(service,retry_delay_seconds=2))[2].verify(_input(),'VERIFY-CODEX'))
        except BaseException as exc:out.append(exc)
    thread=threading.Thread(target=invoke);thread.start()
    try:
        assert node.entered.wait(3)
        if during=='retry_wait':time.sleep(.15)
        stop.set();thread.join(2);node.release.set();time.sleep(.1)
        assert not thread.is_alive() and len(out)==1 and isinstance(out[0],ExecutionCancelled)
        assert len(node.calls)==1
    finally:stop.set();node.release.set();thread.join(3)


@pytest.mark.parametrize('change',[
    {'endpoint':'https://api.moonshot.ai/v1/chat/completions'}, {'endpoint':ENDPOINTS[SERVICE]},
    {'service':'kimi-coding'}, {'model':'kimi-k2.5'}, {'thinking':'disabled'}, {'temperature':1.0},
    {'max_tokens':8192}, {'reasoning_effort':'medium'}, {'max_completion_tokens':1048577},
    {'max_completion_tokens':1.5}, {'max_attempts':4}, {'api_key':'private-never-show'}])
def test_kimi_unsupported_fields_fail_without_partial_updates(http_panel,change):
    before=http_panel.state.config_path.read_bytes()
    body={'runner':{'poll_seconds':.5},'model_profiles':[kimi_profile(**change)]}
    result=request(http_panel,'POST','/api/config',body)
    assert result[0]==400 and 'private-never-show' not in json.dumps(result)
    assert http_panel.state.config_path.read_bytes()==before


def test_native_credentials_same_reference_and_legacy_service_http(http_panel,native_vaults):
    # Legacy no-service request writes the unchanged GLM target, not a migrated key.
    legacy={'action':'save','ref':'shared','value':KEYS[SERVICE]}
    assert request(http_panel,'POST','/api/credentials',legacy)[0]==200
    kimi=dict(legacy,service=KIMI_SERVICE,value=KEYS[KIMI_SERVICE])
    assert request(http_panel,'POST','/api/credentials',kimi)[0]==200
    assert native_vaults[SERVICE].read('shared')==KEYS[SERVICE]
    assert native_vaults[KIMI_SERVICE].read('shared')==KEYS[KIMI_SERVICE]
    assert native_vaults[SERVICE].namespace.endswith('/CLAO/BigModel')
    assert native_vaults[KIMI_SERVICE].namespace.endswith('/CLAO/MoonshotCN')
    for headers in ({'Origin':'https://evil.invalid'},{'X-Panel-Nonce':None},{'Host':'evil.invalid'},{'Content-Type':'text/plain'}):
        assert request(http_panel,'POST','/api/credentials',dict(kimi,value='replacement'),headers=headers)[0]>=400
    assert request(http_panel,'POST','/api/credentials',dict(kimi,value=KEYS[KIMI_SERVICE]+'-new'))[0]==200
    assert native_vaults[SERVICE].read('shared')==KEYS[SERVICE]
    assert native_vaults[KIMI_SERVICE].read('shared')==KEYS[KIMI_SERVICE]+'-new'
    assert request(http_panel,'POST','/api/credentials',dict(kimi,service='unknown'))[0]==400
    assert request(http_panel,'POST','/api/credentials',{'service':KIMI_SERVICE,'action':'delete','ref':'shared'})[0]==200
    assert native_vaults[KIMI_SERVICE].read('shared') is None and native_vaults[SERVICE].read('shared')==KEYS[SERVICE]
    cfg={'model_profiles':[dict(profile(),credential_ref='shared'),kimi_profile(credential_ref='shared')]}
    assert request(http_panel,'POST','/api/config',cfg)[0]==200
    result=request(http_panel,path='/api/model-connections')
    assert [c['credential_status'] for c in result[2]['connections']]==['configured','missing']
    assert all(key not in json.dumps(result)+http_panel.state.config_path.read_text() for key in KEYS.values())
    cfg=config.resolve_config(cfg,overrides={'roles':{'verifier':{'profile':'kimi-review'}}})
    with pytest.raises(ValueError,match='Kimi'):check_start(cfg,{'external_service_consent':[KIMI_SERVICE]})
    with pytest.raises(ProtocolError) as err:roles(cfg)[2].verify(_input(),'VERIFY-CODEX')
    assert err.value.category=='AUTH'


def test_three_services_use_actual_role_consumers(services_http,monkeypatch):
    cfg=config.resolve_config({'model_profiles':[profile(),kimi_profile()],
        'roles':{'planner':{'profile':'kimi-review'},'auditor':{'profile':'glm-review'}}})
    services_http[KIMI_SERVICE].replies=[(200,envelope(_plan())),(200,envelope(_action()))]
    services_http[SERVICE].replies=[(200,envelope(audit_result()))]
    codex=[]
    def reply(**kw):codex.append(kw);return verify_result()
    monkeypatch.setattr('loopcore.verifier.run_codex_json',reply)
    planner,auditor,verifier=roles(cfg)
    assert planner.plan_decompose(MISSION,'DECOMP').mission_id==MISSION['mission_id']
    assert planner.plan(_audit(),{'task_id':'TASK-1'},'ACT-1').action=='CANDIDATE_DONE'
    assert auditor.audit(_bundle(),'AUD-CODEX').decision=='LOCAL_FIX'
    assert verifier.verify(_input(),'VERIFY-CODEX').verdict=='PASS'
    assert len(services_http[KIMI_SERVICE].calls)==2 and len(services_http[SERVICE].calls)==1 and len(codex)==1
    assert codex[0]['model']=='gpt-5.6-sol'
    assert all(key not in json.dumps(codex,default=str) for key in KEYS.values())


@pytest.mark.parametrize('service',[SERVICE,KIMI_SERVICE])
def test_formal_cli_planning_checks_consent_and_reports_service(services_http,tmp_path,monkeypatch,capsys,service):
    cfg=settings(service);monkeypatch.setattr(run_mission,'load_config',lambda:cfg)
    monkeypatch.setattr(run_mission,'ROOT',tmp_path)
    spec=copy.deepcopy(MISSION);spec['budgets']['max_subtasks']=2
    path=tmp_path/'mission.json';path.write_text(json.dumps(spec),encoding='utf-8')
    monkeypatch.setattr(sys,'argv',['run_mission.py',str(path),'--dry-run'])
    assert run_mission.main()==2 and not services_http[service].calls
    capsys.readouterr()
    spec['external_service_consent']=[service];path.write_text(json.dumps(spec),encoding='utf-8')
    services_http[service].replies=[(200,envelope(_plan()))]
    assert run_mission.main()==0
    data=json.loads(capsys.readouterr().out)
    assert data['planner_service']==service and data['model']==cfg['model_profiles'][0]['model']
    assert len(services_http[service].calls)==1 and not (tmp_path/'runtime').exists()


@pytest.mark.parametrize('consent',[None,SERVICE,[SERVICE],True,'*',[KIMI_SERVICE,KIMI_SERVICE],{'service':KIMI_SERVICE}])
def test_consent_cannot_authorize_missing_or_ambiguous_service(services_http,consent):
    with pytest.raises(ValueError):check_start(settings(),{'external_service_consent':consent})
    assert all(not node.calls for node in services_http.values())


def test_cli_panel_frozen_mixed_profiles_resume_and_missing_key(runtime_root,services_http,monkeypatch):
    cfg=config.resolve_config({'model_profiles':[profile(),kimi_profile()],
        'roles':{'planner':{'profile':'kimi-review'},'auditor':{'profile':'glm-review'}}})
    config.save_defaults(runtime_root/'config'/'default.yaml',dict(cfg))
    state=server.PanelState();monkeypatch.setattr(state,'_run',lambda:None)
    spec=dict(mission('P02-PANEL'),external_service_consent=[SERVICE,KIMI_SERVICE])
    state.start_mission(spec);state.thread.join(3)
    cli=run_mission.build_runtime(dict(spec,mission_id='P02-CLI'),cfg)
    try:
        for rt in (cli,state.rt):
            assert rt._planner.transport.profile['service']==KIMI_SERVICE
            assert rt._auditor.transport.profile['service']==SERVICE
            assert rt._verifier.transport is None and rt._verifier.model=='gpt-5.6-sol'
        frozen=state.rt.store.mission_config('P02-PANEL')['effective_config'];state.rt.close()
        # Other/default connections removed; historical providers retain original identities.
        state.set_config({'model_profiles':[], 'roles':{r:{'profile':'codex'} for r in ('planner','auditor','verifier')}})
        restored=run_mission.build_runtime(spec,state.defaults())
        try:
            assert restored._planner.transport.profile==kimi_profile()
            assert restored._auditor.transport.profile==profile()
            assert restored.store.mission_config('P02-PANEL')['effective_config']==frozen
        finally:restored.close()
        monkeypatch.setattr(credentials,'credentials',lambda service=SERVICE:SimpleNamespace(configured=lambda ref:service==SERVICE))
        with pytest.raises(ValueError,match='Kimi'):run_mission.build_runtime(spec,state.defaults())
        assert all(not node.calls for node in services_http.values())
    finally:cli.close();state.rt.close()


def pipeline(journey,services_http,monkeypatch,verdict='PASS'):
    monkeypatch.setattr(run_mission,'CodexCliVerifierProvider',CodexCliVerifierProvider)
    # This suite checks semantic routing, not a 300 ms subprocess launch race.
    # Keep normal local-engine deadlines explicit under Windows browser load.
    journey.state.set_config({'worker':{'spawn_timeout_seconds':3,'send_timeout_seconds':1,'kill_timeout_seconds':1}})
    previous_popen=subprocess.Popen
    def popen(args,*a,**kw):
        assert all(key not in json.dumps(args)+json.dumps(kw.get('env')) for key in KEYS.values())
        return previous_popen(args,*a,**kw)
    monkeypatch.setattr(subprocess,'Popen',popen)
    def responder(service):
        def respond(body):
            inp=json.loads(body['messages'][1]['content'].split('# VerifierInput\n',1)[1])
            result={'verify_id':inp['verify_id'],'task_id':inp['task_id'],'verdict':verdict,
                'ac_checks':[{'ac_id':a['id'],'verdict':verdict,'note':'isolated HTTP evidence'} for a in inp['verifier_input']['task_spec']['acceptance_criteria']],
                'anti_gaming':[],'summary':'isolated '+service+' '+verdict}
            return 200,dict(envelope(result),model='returned-'+service)
        return respond
    for service,node in services_http.items():node.responder=responder(service)


@pytest.mark.parametrize('route,verdict',[(SERVICE,'PASS'),(KIMI_SERVICE,'PASS'),('mixed','PASS'),(KIMI_SERVICE,'FAIL')])
def test_formal_http_controller_and_export(journey,services_http,tmp_path,monkeypatch,route,verdict):
    pipeline(journey,services_http,monkeypatch,verdict)
    selected_service=SERVICE if route==SERVICE else KIMI_SERVICE
    cfg=config.resolve_config(journey.state.defaults(),overrides={'model_profiles':[profile(),kimi_profile()],
        'roles':{'verifier':{'profile':'glm-review' if route==SERVICE else 'kimi-review'},'auditor':{'profile':'glm-review' if route=='mixed' else 'codex'}}})
    journey.state.set_config(dict(cfg));body=form(journey,tmp_path/'实际项目')
    body['config_snapshot']=cfg.snapshot()
    denied=request(journey,'POST','/api/mission',body)
    assert denied[0]==400 and not methods(journey) and all(not n.calls for n in services_http.values())
    if route!=SERVICE:
        assert request(journey,'POST','/api/mission',dict(body,external_service_consent=SERVICE))[0]==400
        assert not methods(journey) and not services_http[KIMI_SERVICE].calls
    consent=[SERVICE,KIMI_SERVICE] if route=='mixed' else [selected_service]
    body['external_service_consent']=consent
    assert request(journey,'POST','/api/mission',body)[0]==200
    data=until(journey,lambda d:d.get('mission',{}).get('state') in run_mission.MISSION_TERMINAL)
    assert (data['mission']['state']=='MISSION_DONE')==(verdict=='PASS'),data['mission']
    assert len(services_http[selected_service].calls)==1
    assert not services_http[KIMI_SERVICE if selected_service==SERVICE else SERVICE].calls
    fact=data['phases']['roles']['verifier'];assert fact['provider']==selected_service
    assert fact['confirmed_model']=='returned-'+selected_service and fact['cost'] is None
    assert data['mission_config']['snapshot']['values']==cfg.snapshot()['values']
    exported=request(journey,'POST','/api/result/export',{'mission_id':data['mission']['id']})
    assert exported[0]==200,exported
    raw=request(journey,path='/api/result/download?mission_id='+data['mission']['id']+'&export_id='+exported[2]['export']['identity'])[2]
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        assert all(key.encode() not in package.read(n) for n in package.namelist() for key in KEYS.values())
    assert (tmp_path/'实际项目'/'app.py').read_text()=='x=0\n'


def test_kimi_inflight_mission_cancel_preserves_stop_boundary(journey,services_http,tmp_path,monkeypatch):
    pipeline(journey,services_http,monkeypatch)
    cfg=config.resolve_config(journey.state.defaults(),overrides={'model_profiles':[kimi_profile()], 'roles':{'verifier':{'profile':'kimi-review'}}})
    journey.state.set_config(dict(cfg));body=form(journey,tmp_path/'cancel')
    services_http[KIMI_SERVICE].release.clear()
    body['external_service_consent']=[KIMI_SERVICE]
    try:
        assert request(journey,'POST','/api/mission',body)[0]==200
        assert services_http[KIMI_SERVICE].entered.wait(12)
        mid=request(journey)[2]['mission']['id']
        assert request(journey,'POST','/api/stop',{'mission_id':mid})[0]==200
        result=until(journey,lambda d:d.get('mission',{}).get('state')=='CANCELLED')
        assert result['mission']['worker_stop']['status']=='CONFIRMED' and not result['verifications']
        services_http[KIMI_SERVICE].release.set();journey.state.thread.join(3)
        assert not request(journey)[2]['verifications'] and len(services_http[KIMI_SERVICE].calls)==1
    finally:services_http[KIMI_SERVICE].release.set()


def test_browser_mixed_consent_credentials_and_pipeline(journey,services_http,native_vaults,tmp_path,monkeypatch):
    pipeline(journey,services_http,monkeypatch)
    journey.state.set_config({'model_profiles':[profile(),kimi_profile(reasoning_effort='low',timeout_seconds=3.125)], 'roles':{'verifier':{'profile':'glm-review'}}})
    native_vaults[SERVICE].save('test-key',KEYS[SERVICE])
    native_vaults[KIMI_SERVICE].save('test-key',KEYS[KIMI_SERVICE])
    codex=[]
    def reply(**kw):
        codex.append(kw['model'])
        _,data=services_http[SERVICE].responder({'messages':[{}, {'content':kw['prompt']}]})
        return json.loads(data['choices'][0]['message']['content'])
    monkeypatch.setattr('loopcore.verifier.run_codex_json',reply)
    a=form(journey,tmp_path/'项目 A 中文');b=form(journey,tmp_path/'项目 B 中文')
    output=Path(os.environ.get('P02_SCREENSHOTS',str(tmp_path/'shots')))
    script=Path(__file__).resolve().parents[2]/'dev'/'panel'/'p01-consent.cjs'
    result=subprocess.run([os.environ['U01_NODE'],str(script),journey.origin,a['project_id'],b['project_id'],'kimi',str(output)],
        capture_output=True,encoding='utf-8',errors='replace',timeout=180)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert len(services_http[SERVICE].calls)==2 and len(services_http[KIMI_SERVICE].calls)==1 and len(codex)==1
    assert methods(journey).count('thread/start')==4
    assert all(native_vaults[s].read('test-key')==KEYS[s] for s in (SERVICE, KIMI_SERVICE))
    for folder in ('项目 A 中文','项目 B 中文'):
        assert (tmp_path/folder/'app.py').read_text()=='x=0\n' and not (tmp_path/folder/'.git').exists()
    print(result.stdout)
