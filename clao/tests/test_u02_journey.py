"""U02 user journey: production HTTP/Controller, isolated Git and stdio engine."""
import copy
import json
import os
from pathlib import Path
import subprocess
import threading
import time

import pytest

import run_mission
from panel import server
from loopcore.effective_config import resolve_config
from loopcore.state_store import StateStore
from tests.test_f04_panel_boundaries import panel, http_panel, request
from tests.test_u02_local_execution import engine


@pytest.fixture
def journey(http_panel, engine, monkeypatch):
    monkeypatch.setattr(run_mission, 'ROOT', http_panel.root)
    http_panel.state.rt = None
    http_panel.state._run = server.PanelState._run.__get__(http_panel.state)
    cfg = resolve_config(engine.cfg, overrides={'runner': {'cap_seconds': 90}})
    http_panel.state.config_path.write_text(json.dumps(dict(cfg)), encoding='utf-8')
    http_panel.engine = engine
    yield http_panel
    if http_panel.state.running():
        http_panel.state.stop()
    if http_panel.state.thread:
        http_panel.state.thread.join(timeout=8)
    if http_panel.state.rt and hasattr(http_panel.state.rt, 'close'):
        http_panel.state.rt.close()


def until(panel, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = request(panel)[2]
        if predicate(data):
            return data
        time.sleep(.04)
    raise AssertionError(data)


def form(panel, folder):
    folder.mkdir()
    (folder/'app.py').write_text('x=0\n')
    row = request(panel, 'POST', '/api/projects/open', {'path': str(folder)})[2]['project']
    source = request(panel, 'POST', '/api/projects/source', {'project_id': row['id']})[2]['source']
    return {'project_id': row['id'], 'source_revision': source['revision'],
            'objective': '真实旅程 中文 <tag> "', 'acceptance_criteria': 'x equals 2',
            'allowed_paths': 'app.py', 'forbidden_paths': 'private/**\ncredentials.txt',
            'gate_commands': 'python -c "import runpy; assert runpy.run_path(\'app.py\')[\'x\'] == 2"\npython -c "pass"'}


def methods(panel):
    path = panel.engine.trace
    return [json.loads(line).get('method') for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize('scenario', ['normal', 'no_login', 'no_sandbox', 'missing_git', 'missing_codex', 'unsupported_version'])
def test_readiness_uses_startup_checks_without_mission_or_model(journey, monkeypatch, scenario):
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO', scenario)
    if scenario == 'unsupported_version':
        monkeypatch.setenv('CLAO_TEST_CODEX_VERSION', '0.0.0')
    original = run_mission.shutil.which
    if scenario.startswith('missing_'):
        monkeypatch.setattr(run_mission.shutil, 'which', lambda name: None if name == scenario[8:] else original(name))
    before = set(journey.root.rglob('*'))
    assert request(journey)[2]['readiness']['status'] == 'unchecked'
    assert request(journey, 'POST', '/api/readiness', {}, headers={'X-Panel-Nonce': 'wrong'})[0] == 403
    assert request(journey, 'POST', '/api/readiness', {})[0] == 202
    data = until(journey, lambda d: d['readiness']['status'] != 'checking')
    assert data['readiness']['status'] == ('ready' if scenario == 'normal' else 'needs_action')
    if scenario != 'normal':
        assert data['readiness']['reason'] and data['readiness']['action']
    assert data['mission'] is None and journey.state.rt is None
    assert set(journey.root.rglob('*')) == before
    assert not {'thread/start', 'turn/start', 'turn/steer'} & set(methods(journey))


def test_readiness_inflight_is_visible_and_deduplicated(journey, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []
    real = run_mission.local_preflight
    def slow(path):
        calls.append(path); started.set(); release.wait(5)
        return real(path)
    monkeypatch.setattr(run_mission, 'local_preflight', slow)
    try:
        request(journey, 'POST', '/api/readiness', {})
        assert started.wait(2)
        for _ in range(3):
            assert request(journey)[2]['readiness']['status'] == 'checking'
            request(journey, 'POST', '/api/readiness', {})
        assert len(calls) == 1
    finally:
        release.set()
    until(journey, lambda d: d['readiness']['status'] == 'ready')


@pytest.mark.parametrize('field,value', [('allowed_paths',''), ('gate_commands',''), ('acceptance_criteria','')])
def test_no_demo_scope_or_gate_fallback(journey, tmp_path, field, value):
    body = form(journey, tmp_path/'项目')
    body[field] = value
    assert request(journey, 'POST', '/api/mission', body)[0] == 400
    assert journey.state.rt is None and not methods(journey)
    assert not (journey.root/'tasks').exists()


def test_confirmed_config_freezes_across_defaults_change_and_real_execution(journey, tmp_path, monkeypatch):
    body = form(journey, tmp_path/'项目')
    base = request(journey)[2]['default_config']
    overrides = {'worker': {'model': 'confirmed-worker'}, 'roles': {'verifier': {'model': 'confirmed-review'}},
                 'budgets': {'max_runtime_seconds': 333.25}, 'gate': {'timeout_seconds': 1.25, 'output_limit_chars': 400}}
    response = request(journey, 'POST', '/api/mission-config', {'base': base, 'overrides': overrides})
    assert response[0] == 200, response
    confirmed = response[2]['snapshot']
    monkeypatch.setattr(journey.state, 'defaults', lambda: resolve_config({'worker': {'model': 'later-default'}}))
    body['config_snapshot'] = confirmed
    response = request(journey, 'POST', '/api/mission', body)
    assert response[0] == 200, response
    data = until(journey, lambda d: d['mission']['state'] in run_mission.MISSION_TERMINAL)
    assert data['mission']['state'] == 'MISSION_DONE', data
    assert data['mission_config']['snapshot']['values'] == confirmed['values']
    assert data['mission_config']['snapshot']['revision'] == confirmed['revision']
    assert data['default_config']['values']['worker']['model'] == 'later-default'
    stored = journey.state.rt.store.mission_config(data['mission']['id'])
    assert stored['mission']['forbidden_paths'] == ['.git/**','private/**','credentials.txt']
    assert len(stored['mission']['gate_commands']) == 2
    assert stored['effective_config']['values']['gate']['timeout_seconds'] == 1.25
    assert journey.state.rt.adapter.model == 'confirmed-worker'
    assert data['result']['status'] == 'available' and data['result']['accepted']
    assert 'final' in {r['phase'] for r in data['gate_query']['records']}
    assert data['verifications'] and journey.engine.verifier.verify.call_count == 1
    assert (tmp_path/'项目'/'app.py').read_text() == 'x=0\n'


def test_invalid_config_confirmation_cannot_partially_start(journey, tmp_path):
    body = form(journey, tmp_path/'p')
    base = request(journey)[2]['default_config']
    invalid = {'base': base, 'overrides': {'worker': {'model': 'new'}, 'gate': {'timeout_seconds': 0}}}
    assert request(journey, 'POST', '/api/mission-config', invalid)[0] == 400
    damaged = copy.deepcopy(base); damaged['values']['worker']['model'] = 'tampered'
    body['config_snapshot'] = damaged
    assert request(journey, 'POST', '/api/mission', body)[0] == 400
    assert journey.state.rt is None and not methods(journey)
    assert request(journey)[2]['default_config'] == base


def test_failed_start_keeps_reason_and_next_start_clears_old_error(journey, tmp_path, monkeypatch):
    body = form(journey, tmp_path/'p')
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO','no_login')
    assert request(journey,'POST','/api/mission',body)[0] == 400
    assert 'ChatGPT' in request(journey)[2]['panel_errors'][0]
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO','normal')
    response = request(journey,'POST','/api/mission',body)
    assert response[0] == 200, response
    data = until(journey,lambda d:d['mission']['state']=='MISSION_DONE')
    assert not data['panel_errors']


def test_preparation_visible_before_preflight_returns(journey, tmp_path, monkeypatch):
    body=form(journey,tmp_path/'p')
    entered, release=threading.Event(), threading.Event()
    original=run_mission.local_preflight
    def slow(path):
        entered.set();release.wait(5);return original(path)
    monkeypatch.setattr(run_mission,'local_preflight',slow)
    result=[]
    t=threading.Thread(target=lambda:result.append(request(journey,'POST','/api/mission',body)))
    t.start()
    try:
        assert entered.wait(3)
        data=request(journey)[2]
        assert data['preparing'] and data['mission']['state']=='preflight'
        assert data['mission']['objective']==body['objective']
        assert request(journey,'POST','/api/mission',body)[0] == 400
    finally:release.set();t.join(8)
    assert result[0][0] == 200


def test_history_b_while_running_a_is_readonly_and_target_bound(journey,tmp_path,monkeypatch):
    body=form(journey,tmp_path/'B')
    bid=request(journey,'POST','/api/mission',body)[2]['mission_id']
    until(journey,lambda d:d['mission']['state']=='MISSION_DONE')
    journey.state.thread.join(5);journey.state.rt.close();journey.state.rt=None
    bpath=journey.root/'runtime'/bid/'state.db';before=bpath.read_bytes()
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO','manual')
    body_a=form(journey,tmp_path/'A');body_a['objective']='进行中的 A'
    aid=request(journey,'POST','/api/mission',body_a)[2]['mission_id']
    until(journey,lambda d:bool(d.get('approvals')))
    current=journey.state.rt;effects=methods(journey)
    for _ in range(3):
        historical=request(journey,path='/api/mission?mission_id='+bid)[2]
        assert historical['mission']['id']==bid and historical['mission']['inspection_only']
        assert historical['result']['accepted'] and not historical['approvals']
        assert historical['active_mission_id']==aid and historical['active_running']
        assert not historical['actions']['new_attempt']
        assert request(journey,path='/api/file?name=memory.md&mission_id='+bid)[0]==200
    assert request(journey,'POST','/api/stop',{'mission_id':bid})[0]==409
    assert request(journey,'POST','/api/directive',{'mission_id':bid,'target':'planner','text':'wrong target'})[0]==409
    assert journey.state.rt is current and bpath.read_bytes()==before
    assert methods(journey)==effects
    assert request(journey)[2]['mission']['id']==aid


@pytest.mark.parametrize('value',['..','%2e%2e','%252e%252e','C%3A%5CWindows','%FF','x&mission_id=y'])
def test_readonly_history_id_boundary(journey,value):
    assert request(journey,path='/api/mission?mission_id='+value)[0]==400


def test_stale_result_is_not_available_or_accepted_by_directory_alone(journey, tmp_path):
    mid='HISTORY-RESULT'; rt=journey.root/'runtime'/mid
    store=StateStore(rt/'state.db')
    try:store.record_mission(mid,{'mission':{'mission_id':mid,'objective':'历史'},'state':'FAILED','merged':['task']})
    finally:store.close()
    data=request(journey,path='/api/mission?mission_id='+mid)[2]
    assert data['result']['status']=='missing' and not data['result']['accepted']
    (rt/'integration').mkdir()
    data=request(journey,path='/api/mission?mission_id='+mid)[2]
    assert data['result']['status']=='available' and not data['result']['accepted']


def test_stop_unknown_cannot_launch_another_worker(journey, tmp_path, monkeypatch):
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO','kill_live')
    body=form(journey,tmp_path/'A')
    aid=request(journey,'POST','/api/mission',body)[2]['mission_id']
    until(journey,lambda d:bool(d.get('subtasks')) and bool(d['subtasks'][0]['worker_session_id']))
    request(journey,'POST','/api/stop',{'mission_id':aid})
    data=until(journey,lambda d:(d['mission'].get('worker_stop') or {}).get('status')=='UNKNOWN')
    journey.state.thread.join(5)
    assert data['launch_blocked']
    second=form(journey,tmp_path/'B')
    assert request(journey,'POST','/api/mission',second)[0]==409
    assert methods(journey).count('thread/start')==1


@pytest.mark.parametrize('scenario',['no_login','normal','manual','kill_live'])
def test_actual_journey_browser(journey,tmp_path,monkeypatch,scenario):
    node=os.environ.get('U01_NODE')
    assert node, 'Set development U01_NODE and NODE_PATH; do not skip browser coverage'
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO',scenario)
    if scenario == 'manual':
        monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO', 'manual_file')
        monkeypatch.setenv('CLAO_TEST_CODEX_EDIT_PATH', 'private/block.py')
    historical='HISTORY-B'
    store=StateStore(journey.root/'runtime'/historical/'state.db')
    try:
        store.record_mission(historical, {'mission': {'mission_id':historical,'objective':'历史 B <tag>','project_id':'old-project'},
            'state':'FAILED','reason':'B 的失败原因','execution_backend':'ao','merged':['old']})
    finally:store.close()
    folder=tmp_path/'浏览器 本地';folder.mkdir();(folder/'app.py').write_text('x=0\n')
    output=Path(os.environ.get('U02_JOURNEY_SCREENSHOTS',str(tmp_path/'screenshots')))
    script=Path(__file__).resolve().parents[2]/'dev'/'panel'/'u02-journey.cjs'
    result=subprocess.run([node,str(script),journey.origin,str(folder),scenario,str(output)],capture_output=True,
                          encoding='utf-8',errors='replace',timeout=110)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    print(result.stdout)
    assert (folder/'app.py').read_text()=='x=0\n'
