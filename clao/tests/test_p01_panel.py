"""P01 native Windows credentials and formal Panel/runtime paths, isolated keys only."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid
import zipfile

import pytest
import run_mission
from panel import server
from loopcore import credentials, effective_config as config
from loopcore.model_profiles import SERVICE
from loopcore.verifier import CodexCliVerifierProvider
from loopcore.state_store import StateStore
from tests.test_f04_panel_boundaries import panel, http_panel, request
from tests.test_u02_local_execution import engine
from tests.test_u02_journey import journey, form, until, methods
from tests.test_r01_effective_config import runtime_root, mission, consumers
from tests.test_p01_bigmodel import (glm_http, configuration, profile, envelope, FAKE_KEY, BUILD_PLANNER)


@pytest.fixture
def native_vault(monkeypatch):
    assert os.name == 'nt', 'P01 credential acceptance must run on Windows'
    vault = credentials.WindowsCredentials('CLAO-P01-Isolated-Test/' + uuid.uuid4().hex)
    monkeypatch.setattr(credentials, 'credentials', lambda: vault)
    yield vault
    # Never enumerate or access user entries; every touched reference is named here.
    for ref in ('test-key','browser-key'):
        vault.delete(ref)
        assert vault.read(ref) is None


def test_windows_credential_save_replace_restart_delete(native_vault):
    assert native_vault.read('test-key') is None
    native_vault.save('test-key', FAKE_KEY)
    reader = credentials.WindowsCredentials(native_vault.namespace)
    assert reader.configured('test-key') and reader.read('test-key') == FAKE_KEY
    reader.save('test-key', FAKE_KEY + '-replacement')
    assert native_vault.read('test-key') == FAKE_KEY + '-replacement'
    reader.delete('test-key')
    assert native_vault.read('test-key') is None


def test_native_credential_http_no_echo_and_defaults_restart(http_panel, native_vault):
    before = http_panel.state.config_path.read_bytes()
    response = request(http_panel,'POST','/api/credentials',{'action':'save','ref':'test-key','value':FAKE_KEY})
    assert response[0] == 200 and FAKE_KEY not in json.dumps(response)
    assert native_vault.read('test-key') == FAKE_KEY
    assert http_panel.state.config_path.read_bytes() == before
    cfg = configuration(roles=('verifier',),timeout_seconds=3.125)
    assert request(http_panel,'POST','/api/config',dict(cfg))[0] == 200
    restarted = server.PanelState(config_path=http_panel.state.config_path)
    assert restarted.defaults()['model_profiles'][0]['timeout_seconds'] == 3.125
    result = request(http_panel,path='/api/model-connections')
    assert result[2]['connections'][0]['credential_status'] == 'configured'
    assert result[2]['connections'][0]['verified_roles'] == []
    assert result[2]['connections'][0]['live_check'] == 'not_run'
    snapshot = request(http_panel)[2]
    assert FAKE_KEY not in json.dumps(snapshot) + json.dumps(result) + http_panel.state.config_path.read_text()
    assert FAKE_KEY.encode() not in (http_panel.runtime/'state.db').read_bytes()
    before = http_panel.state.config_path.read_bytes()
    invalid = copy.deepcopy(dict(cfg)); invalid['runner']['poll_seconds'] = .125; invalid['model_profiles'][0]['max_attempts'] = 30
    assert request(http_panel,'POST','/api/config',invalid)[0] == 400
    assert http_panel.state.config_path.read_bytes() == before
    assert request(http_panel,'POST','/api/credentials',{'action':'delete','ref':'test-key'})[0] == 200
    assert native_vault.read('test-key') is None


@pytest.mark.parametrize('headers', [ {'Host':'evil.invalid'}, {'Origin':'https://evil.invalid'},
    {'X-Panel-Nonce':None}, {'X-Panel-Nonce':'wrong'}, {'Content-Type':'text/plain'} ])
def test_credential_api_keeps_write_boundaries(http_panel,native_vault,headers):
    response=request(http_panel,'POST','/api/credentials',{'action':'save','ref':'test-key','value':FAKE_KEY},headers=headers)
    assert response[0]>=400 and native_vault.read('test-key') is None
    assert FAKE_KEY not in json.dumps(response)


def test_credential_storage_failure_is_safe_no_plaintext_fallback(http_panel,native_vault,monkeypatch):
    before={str(p):p.read_bytes() for p in http_panel.root.rglob('*') if p.is_file()}
    def fail(): raise credentials.CredentialError('Windows 系统凭据存储不可用')
    with monkeypatch.context() as patch:
        patch.setattr(native_vault,'_api',fail)
        response=request(http_panel,'POST','/api/credentials',{'action':'save','ref':'test-key','value':FAKE_KEY})
        assert response[0]==400 and FAKE_KEY not in json.dumps(response)
        assert before=={str(p):p.read_bytes() for p in http_panel.root.rglob('*') if p.is_file()}


def test_cli_panel_mixed_actual_consumers_and_frozen_profiles(runtime_root,glm_http,monkeypatch):
    cfg=configuration(roles=('planner','verifier'))
    path=runtime_root/'config'/'default.yaml';config.save_defaults(path,dict(cfg))
    state=server.PanelState();monkeypatch.setattr(state,'_run',lambda:None)
    spec=dict(mission('M-P01-PANEL'),external_service_consent=SERVICE)
    state.start_mission(spec);state.thread.join(3)
    cli=run_mission.build_runtime(dict(spec,mission_id='M-P01-CLI'),config.load_config(path))
    try:
        assert consumers(cli)==consumers(state.rt)
        assert state.rt._planner.transport.profile['model']=='glm-4.7'
        assert state.rt._auditor.transport is None and state.rt._verifier.transport is not None
        saved=state.rt.store.mission_config(spec['mission_id'])['effective_config']
        state.set_config({'model_profiles':[dict(profile(),timeout_seconds=6)],'roles':{'verifier':{'profile':'codex'}}})
        state.rt.close()
        restored=run_mission.build_runtime(spec,state.defaults())
        try:
            assert restored._verifier.transport.profile['timeout_seconds']==2.25
            assert restored.store.mission_config(spec['mission_id'])['effective_config']==saved
        finally:restored.close()
        assert not glm_http.calls
    finally:cli.close();state.rt.close()


def test_v1_runtime_resume_never_reads_glm_credentials_or_rewrites_snapshot(runtime_root,monkeypatch):
    cfg=config.resolve_config({})
    legacy=config.EffectiveConfig(config.nest({k:v for k,v in config.flatten(cfg).items() if k in config.LEGACY_FIELDS}),
        {k:cfg.sources[k] for k in config.LEGACY_FIELDS},schema_version=1).snapshot()
    spec=mission('M-P01-LEGACY');rt=run_mission.build_runtime(spec,cfg)
    rt.store.record_mission(spec['mission_id'],{'effective_config':legacy});rt.close()
    def forbidden():raise AssertionError('old Codex snapshot must not query GLM keys')
    monkeypatch.setattr(credentials,'credentials',forbidden)
    restored=run_mission.build_runtime(spec,configuration())
    try:
        assert restored._planner.transport is None and restored._auditor.transport is None and restored._verifier.transport is None
        assert restored.store.mission_config(spec['mission_id'])['effective_config']==legacy
    finally:restored.close()


def use_http_verifier(journey,glm_http,monkeypatch,verdict='PASS'):
    # Restore the production semantic provider replaced by the older engine fixture.
    monkeypatch.setattr(run_mission,'CodexCliVerifierProvider',CodexCliVerifierProvider)
    def respond(body):
        prompt=body['messages'][1]['content']
        task=json.loads(prompt.split('# VerifierInput\n',1)[1])
        acs=task['verifier_input']['task_spec']['acceptance_criteria']
        return 200,envelope({'verify_id':task['verify_id'],'task_id':task['task_id'],'verdict':verdict,
            'ac_checks':[{'ac_id':a['id'],'verdict':verdict,'note':'isolated HTTP fixture evidence'} for a in acs],
            'anti_gaming':[],'summary':'isolated HTTP fixture '+verdict})
    glm_http.responder=respond
    cfg=config.resolve_config(journey.state.defaults(),overrides={
        'model_profiles':[profile()], 'roles':{'verifier':{'profile':'glm-review'}}})
    journey.state.set_config(dict(cfg))
    return cfg


@pytest.mark.parametrize('verdict',['PASS','FAIL'])
def test_actual_controller_git_gate_http_verifier_and_result_export(journey,glm_http,tmp_path,monkeypatch,verdict):
    original_popen=subprocess.Popen
    def checked_popen(args,*a,**kw):
        assert FAKE_KEY not in json.dumps(args) + json.dumps(kw.get('env'))
        return original_popen(args,*a,**kw)
    monkeypatch.setattr(subprocess,'Popen',checked_popen)
    cfg=use_http_verifier(journey,glm_http,monkeypatch,verdict)
    body=form(journey,tmp_path/'实际项目')
    denied=request(journey,'POST','/api/mission',body)
    assert denied[0]==400 and not methods(journey) and not glm_http.calls
    body.update(external_service_consent=SERVICE,config_snapshot=cfg.snapshot())
    response=request(journey,'POST','/api/mission',body);assert response[0]==200,response
    data=until(journey,lambda d:d.get('mission',{}).get('state') in run_mission.MISSION_TERMINAL)
    assert (data['mission']['state']=='MISSION_DONE')==(verdict=='PASS'),data
    assert len(glm_http.calls)==1  # Valid semantic FAIL is not refreshed into PASS.
    assert data['verifications'][0]['verdict']==verdict
    assert data['phases']['roles']['verifier']['provider']==SERVICE
    assert (tmp_path/'实际项目'/'app.py').read_text()=='x=0\n'
    assert FAKE_KEY not in json.dumps(data)
    assert FAKE_KEY.encode() not in (journey.state.rt.runtime/'state.db').read_bytes()
    exported=request(journey,'POST','/api/result/export',{'mission_id':data['mission']['id']})
    assert exported[0]==200,exported
    identity=exported[2]['export']['identity']
    raw=request(journey,path='/api/result/download?mission_id='+data['mission']['id']+'&export_id='+identity)[2]
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        assert all(FAKE_KEY.encode() not in package.read(n) for n in package.namelist())


def test_controller_exhaustion_not_multiplied_and_unknown_worker_untouched(journey,glm_http,tmp_path,monkeypatch):
    cfg=use_http_verifier(journey,glm_http,monkeypatch)
    glm_http.responder=lambda body:(429, {'error':FAKE_KEY})
    body=form(journey,tmp_path/'p');body.update(external_service_consent=SERVICE,config_snapshot=cfg.snapshot())
    assert request(journey,'POST','/api/mission',body)[0]==200
    data=until(journey,lambda d:d.get('mission',{}).get('state')=='HUMAN')
    journey.state.thread.join(5)
    for _ in range(3):journey.state.rt.controller.step()
    assert len(glm_http.calls)==2 and 'RATE_LIMIT' in data['mission']['reason']
    assert not data['verifications'] and FAKE_KEY not in json.dumps(data)


def test_mission_cancel_during_http_drops_response(journey,glm_http,tmp_path,monkeypatch):
    cfg=use_http_verifier(journey,glm_http,monkeypatch)
    glm_http.release.clear()
    body=form(journey,tmp_path/'cancel');body.update(external_service_consent=SERVICE,config_snapshot=cfg.snapshot())
    assert request(journey,'POST','/api/mission',body)[0]==200
    try:
        assert glm_http.entered.wait(12)
        data=request(journey)[2];mid=data['mission']['id']
        assert any(p['phase']=='model_request' and p['status']=='running' for p in data['phases']['records'])
        assert request(journey,'POST','/api/stop',{'mission_id':mid})[0]==200
        data=until(journey,lambda d:d['mission']['state']=='CANCELLED')
        assert not data['verifications'] and len(glm_http.calls)==1
    finally:glm_http.release.set()


def test_browser_profiles_credentials_consent_and_real_pipeline(journey,glm_http,native_vault,tmp_path,monkeypatch):
    # Credential bytes traverse real browser -> protected HTTP -> real WinCred.
    use_http_verifier(journey,glm_http,monkeypatch)
    native_vault.save('test-key',FAKE_KEY)
    body=form(journey,tmp_path/'浏览器项目')
    output=Path(os.environ.get('P01_SCREENSHOTS',str(tmp_path/'shots')))
    script=Path(__file__).resolve().parents[2]/'dev'/'panel'/'p01-models.cjs'
    result=subprocess.run([os.environ['U01_NODE'],str(script),journey.origin,body['project_id'],str(output)],
        capture_output=True,encoding='utf-8',errors='replace',timeout=100)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert len(glm_http.calls)==1 and native_vault.read('browser-key')==FAKE_KEY
    assert journey.state.rt.cfg['roles']['verifier']['profile']=='browser-glm'
    assert journey.state.rt.cfg['model_profiles'][-1]['timeout_seconds']==4.125
    print(result.stdout)


def test_audit_browser_consent_scope_and_new_missions(journey,glm_http,tmp_path,monkeypatch):
    use_http_verifier(journey,glm_http,monkeypatch)
    journey.state.set_config({'model_profiles':[profile(),dict(profile(),id='glm-other',credential_ref='other-key')]})
    codex_calls=[]
    def codex_response(**kwargs):
        # Replace only the Codex model call; keep the production role validation.
        codex_calls.append(kwargs['model'])
        _,reply=glm_http.responder({'messages':[{}, {'content':kwargs['prompt']}]})
        return json.loads(reply['choices'][0]['message']['content'])
    monkeypatch.setattr('loopcore.verifier.run_codex_json',codex_response)
    a=form(journey,tmp_path/'项目 A 中文')
    b=form(journey,tmp_path/'项目 B 中文')
    script=Path(__file__).resolve().parents[2]/'dev'/'panel'/'p01-consent.cjs'
    result=subprocess.run([os.environ['U01_NODE'],str(script),journey.origin,a['project_id'],b['project_id']],
        capture_output=True,encoding='utf-8',errors='replace',timeout=150)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert len(glm_http.calls)==3 and len(codex_calls)==1
    assert methods(journey).count('thread/start')==4
    for folder in ('项目 A 中文','项目 B 中文'):
        assert (tmp_path/folder/'app.py').read_text()=='x=0\n'
        assert not (tmp_path/folder/'.git').exists()
    print(result.stdout)
