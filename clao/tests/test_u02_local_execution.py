"""Windows product integration with real Git/SQLite/HTTP and a stdio process.

Only the external engine/provider boundaries are replaced; Controller,
ClosedLoop, source/workspaces, approval policy, Gate and materialization run.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import run_mission
from panel import server
from loopcore import local_projects as projects, worktree as wt
from loopcore.action_executor import ActionExecutor, ExternalOperationUnknown, operation_id
from loopcore.codex_backend import CodexBackend, CodexUnknown
from loopcore.effective_config import resolve_config
from loopcore.state_store import StateStore
from loopcore.verifier import FakeVerifierProvider
from loopcore.auditor import FakeAuditorProvider
from loopcore.planner_adapter import FakePlannerProvider
from loopcore.recovery import RecoveryError
from tests.test_f04_panel_boundaries import panel, http_panel, request


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args]).decode().strip()


@pytest.fixture
def engine(tmp_path, monkeypatch):
    trace = tmp_path / 'protocol.jsonl'
    monkeypatch.setenv('CLAO_TEST_CODEX_TRACE', str(trace))
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO', 'normal')
    original = subprocess.Popen
    executable = str(tmp_path / 'fake-codex.exe')
    fake = Path(__file__).parent / 'fixtures' / 'codex_app_server.py'
    def popen(argv, *args, **kwargs):
        if isinstance(argv, list) and argv[0] == executable:
            argv = [sys.executable, str(fake)] + argv[1:]
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', popen)
    original_which = run_mission.shutil.which
    monkeypatch.setattr(run_mission.shutil, 'which', lambda name: executable if name == 'codex' else original_which(name))
    monkeypatch.setattr(run_mission, 'AOAdapter', MagicMock(side_effect=AssertionError('local path accessed AO')))
    monkeypatch.setattr(run_mission, 'resolve_ao_run_file', MagicMock(side_effect=AssertionError('AO runfile read')))
    monkeypatch.setattr(run_mission, 'resolve_ao_bin', MagicMock(side_effect=AssertionError('AO CLI discovery')))
    monkeypatch.setattr(server, '_load_ao_projects', MagicMock(side_effect=AssertionError('AO project discovery')))
    verifier = FakeVerifierProvider()
    verifier.verify = MagicMock(wraps=verifier.verify)
    monkeypatch.setattr(run_mission, 'CodexCliVerifierProvider', lambda **kw: verifier)
    monkeypatch.setattr(run_mission, 'CodexCliAuditorProvider', lambda **kw: FakeAuditorProvider())
    monkeypatch.setattr(run_mission, 'build_planner', lambda *a, **kw: FakePlannerProvider())
    root = tmp_path / 'CLAO'
    root.mkdir()
    monkeypatch.setattr(run_mission, 'ROOT', root)
    cfg = resolve_config({'runner': {'poll_seconds': .02, 'cap_seconds': 20},
                          'worker': {'spawn_timeout_seconds': .3, 'send_timeout_seconds': .15, 'kill_timeout_seconds': .15}})
    return SimpleNamespace(trace=trace, executable=executable, root=root, cfg=cfg, verifier=verifier)


def mission(engine, folder, **changes):
    row = projects.register(engine.root, str(folder))
    source = projects.inspect(row)
    return dict(mission_id='LOCAL-1', project_id=row['id'], execution_backend=projects.BACKEND,
        source_revision=source['revision'], objective='将 x 设为 2', allowed_paths=['app.py'], forbidden_paths=['.git/**', 'forbidden.txt'],
        acceptance_criteria=[{'id': 'AC-1', 'description': 'x equals 2'}],
        gate_commands=['python -c "import app; assert app.x == 2"'], budgets={'max_subtasks': 1}, **changes)


def drive(rt, predicate=None, limit=40):
    for _ in range(limit):
        result = rt.controller.step()
        if predicate and predicate(rt):
            return result
        if result['state'] in run_mission.MISSION_TERMINAL:
            return result
        time.sleep(.02)
    raise AssertionError(rt.controller._read_state())


@pytest.mark.parametrize('kind', ['git', 'folder', 'empty'])
def test_formal_runtime_real_git_gate_verifier_delivery_without_ao(engine, tmp_path, kind):
    folder = tmp_path / '源码 中文 空格'
    folder.mkdir()
    if kind != 'empty':
        (folder/'app.py').write_text('x=0\n')
        (folder/'data.pyconfig').write_text('config\n')
        (folder/'.coverage_policy.py').write_text('policy\n')
    if kind == 'git':
        git(folder,'init','-b','user-branch');git(folder,'config','user.name','Test');git(folder,'config','user.email','test@localhost')
        git(folder,'add','.');git(folder,'commit','-m','base')
        (folder/'app.py').write_text('x=1\n')
        git(folder,'add','app.py')
        (folder/'app.py').write_text('x=0\n')
    (folder/'.env').write_text('SECRET=never-copy')
    (folder/'__pycache__').mkdir();(folder/'__pycache__'/'ignored.pyc').write_bytes(b'cache')
    before = {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    spec = mission(engine, folder)
    rt = run_mission.build_runtime(spec, engine.cfg)
    try:
        result = drive(rt)
        assert result['state'] == 'MISSION_DONE', rt.controller._read_state()
        row = rt.store.mission_config('LOCAL-1')
        assert row['execution_backend'] == projects.BACKEND and row['worker_stop']['status'] == 'CONFIRMED'
        assert row['source']['manifest']['revision'] == spec['source_revision']
        integ = rt.runtime/'integration'
        assert (integ/'app.py').read_text() == 'x=2\n'
        assert wt.changed_paths(str(integ),row['source']['source_commit']) == ['app.py']
        assert not (integ/'.env').exists() and not (rt.runtime/'source'/'__pycache__').exists()
        if kind != 'empty':
            assert (integ/'data.pyconfig').is_file() and (integ/'.coverage_policy.py').is_file()
        assert engine.verifier.verify.call_count == 1
        records = StateStore.query_gate_runs(rt.store._conn)['records']
        assert {'task','baseline','final'} <= {r['phase'] for r in records}
        assert [r for r in records if r['phase']=='final'][0]['overall'] == 'pass'
        assert all(op['status']=='SUCCEEDED' for op in rt.store.operations())
        assert row['local_workers'] and 'never-copy' not in json.dumps(row)
    finally:
        rt.close()
    after = {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    assert before == after
    if kind == 'git':
        assert git(folder,'branch','--show-current') == 'user-branch' and git(folder,'remote') == ''
    else:
        assert not (folder/'.git').exists()


@pytest.mark.parametrize('scenario', ['outside','worker_failed','disconnect','error_then_completed'])
def test_failed_or_unknown_worker_cannot_become_mission_success(engine, tmp_path, monkeypatch, scenario):
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO',scenario)
    folder=tmp_path/'project';folder.mkdir();(folder/'app.py').write_text('x=0\n')
    rt=run_mission.build_runtime(mission(engine,folder),engine.cfg)
    try:
        result=drive(rt)
        assert result['state'] in ('HUMAN','FAILED')
        assert not (rt.runtime/'integration').exists()
        engine.verifier.verify.assert_not_called()
    finally:rt.close()


def test_green_worker_with_red_real_gate_is_not_done(engine,tmp_path):
    folder=tmp_path/'p';folder.mkdir()
    spec=mission(engine,folder);spec['gate_commands']=['python -c "raise SystemExit(1)"']
    rt=run_mission.build_runtime(spec,engine.cfg)
    try:
        result=drive(rt)
        assert result['state']!='MISSION_DONE'
        assert any(r['overall']=='fail' for r in StateStore.query_gate_runs(rt.store._conn)['records'])
        engine.verifier.verify.assert_not_called()
    finally:rt.close()


@pytest.mark.parametrize('scenario,confirmed', [('kill_live',False),('kill_ack_lost',True),('background',False)])
def test_interrupt_ack_is_not_stop_fact(engine,tmp_path,monkeypatch,scenario,confirmed):
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO',scenario)
    folder=tmp_path/'p';folder.mkdir()
    rt=run_mission.build_runtime(mission(engine,folder),engine.cfg)
    try:
        drive(rt,lambda r:bool(r.controller.tasks and next(iter(r.controller.tasks.values())).worker_session_id))
        rt.controller.request_stop()
        result=drive(rt)
        assert (result['state']=='CANCELLED') is confirmed
        row=rt.store.mission_config('LOCAL-1')
        assert row['stop_request'] and row['worker_stop']['status']==('CONFIRMED' if confirmed else 'UNKNOWN')
        assert not (rt.runtime/'integration').exists()
        for _ in range(2):rt.controller.step()
        methods=[json.loads(line)['method'] for line in engine.trace.read_text().splitlines()]
        assert methods.count('turn/interrupt') <= 1
    finally:rt.close()


def test_send_ack_lost_restart_never_repeats_effect(engine,tmp_path,monkeypatch):
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO','send_ack_lost')
    folder=tmp_path/'p';folder.mkdir()
    spec=mission(engine,folder);rt=run_mission.build_runtime(spec,engine.cfg)
    drive(rt,lambda r:bool(r.controller.tasks and next(iter(r.controller.tasks.values())).worker_session_id))
    task=next(iter(rt.controller.tasks.values()))
    identity=operation_id('send-test',task.worker_session_id)
    with pytest.raises(ExternalOperationUnknown):
        rt.executor.nudge_worker(task.worker_session_id,'补充约束',identity=identity,owner_id='LOCAL-1')
    assert rt.store.operation(identity)['status']=='UNKNOWN'
    source=rt.store.mission_config('LOCAL-1')['source'];path=rt.store.path;rt.close()
    store=StateStore(path)
    backend=CodexBackend(store,'LOCAL-1',engine.executable,engine.cfg['worker']['model'],source)
    executor=ActionExecutor('',None,None,store,adapter=backend)
    try:
        for _ in range(3):
            with pytest.raises(ExternalOperationUnknown):executor.nudge_worker(task.worker_session_id,'补充约束',identity=identity,owner_id='LOCAL-1')
        assert store.operation(identity)['status']=='UNKNOWN'
    finally:store.close()
    with pytest.raises(RecoveryError):run_mission.build_runtime(spec,engine.cfg)
    methods=[json.loads(line)['method'] for line in engine.trace.read_text().splitlines()]
    assert methods.count('turn/steer')==1 and methods.count('thread/start')==1


def test_protocol_ack_persisted_before_action_crash_is_adopted(engine,tmp_path,monkeypatch):
    folder=tmp_path/'p';folder.mkdir();spec=mission(engine,folder)
    rt=run_mission.build_runtime(spec,engine.cfg)
    original=rt.executor._observe
    class Crash(BaseException):pass
    def crash(op,status,*args,**kw):
        if op['kind']=='spawn' and status=='SUCCEEDED':raise Crash()
        return original(op,status,*args,**kw)
    monkeypatch.setattr(rt.executor,'_observe',crash)
    rt.controller.step()
    with pytest.raises(Crash):rt.controller.step()
    op=next(op for op in rt.store.operations() if op['kind']=='spawn')
    assert op['status']=='IN_FLIGHT'
    monkeypatch.setattr(rt.executor,'_observe',original)
    # A new executor reuses the matching persisted protocol ACK; no second turn.
    executor=ActionExecutor('',None,None,rt.store,adapter=rt.adapter,worker_model=engine.cfg['worker']['model'])
    rt.controller.executor=executor
    for loop in rt.controller.loops.values():loop.executor=executor
    try:
        assert drive(rt)['state']=='MISSION_DONE'
        assert rt.store.operation(op['operation_id'])['status']=='SUCCEEDED'
        methods=[json.loads(line)['method'] for line in engine.trace.read_text().splitlines()]
        assert methods.count('thread/start')==methods.count('turn/start')==1
    finally:rt.close()


def test_source_revision_change_and_missing_capability_refuse_before_spawn(engine,tmp_path,monkeypatch):
    folder=tmp_path/'p';folder.mkdir();(folder/'app.py').write_text('x=0')
    spec=mission(engine,folder);(folder/'app.py').write_text('x=1')
    with pytest.raises(ValueError,match='项目内容变化'):run_mission.build_runtime(spec,engine.cfg)
    assert 'thread/start' not in engine.trace.read_text()
    for index,scenario in enumerate(('no_login','no_sandbox')):
        monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO',scenario)
        spec=mission(engine,folder);spec['mission_id']='CAP-'+str(index)
        with pytest.raises(ValueError):run_mission.build_runtime(spec,engine.cfg)


def test_local_project_http_boundary_and_persistence_without_ao(http_panel,engine,tmp_path,monkeypatch):
    folder=tmp_path/'新项目 中文'
    for headers in ({'Host':'evil.example'},{'Origin':'https://evil.example'},{'X-Panel-Nonce':None},{'Content-Type':'text/plain'}):
        result=request(http_panel,'POST','/api/projects/create',{'path':str(folder)},headers=headers)
        assert result[0]!=200 and not folder.exists()
    result=request(http_panel,'POST','/api/projects/create',{'path':str(folder)})
    assert result[0]==200 and not (folder/'.git').exists()
    registered=result[2]['project']
    assert request(http_panel,path='/api/projects')[2]['projects']==[registered]
    assert projects.projects(http_panel.root)==[registered]
    source=request(http_panel,'POST','/api/projects/source',{'project_id':registered['id']})
    assert source[0]==200 and source[2]['source']['file_count']==0
    assert request(http_panel,'POST','/api/projects/open',{'path':'../escape'})[0]!=200


@pytest.mark.parametrize('decision', ['accept','decline'])
def test_actual_panel_mission_and_one_request_approval(http_panel,engine,tmp_path,monkeypatch,decision):
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO','manual')
    monkeypatch.setattr(run_mission,'ROOT',http_panel.root)
    http_panel.state.rt=None
    http_panel.state._run=server.PanelState._run.__get__(http_panel.state)
    # Short frozen polling config; no real model calls.
    monkeypatch.setattr(http_panel.state,'defaults',lambda:engine.cfg)
    folder=tmp_path/'Panel 本地';folder.mkdir()
    row=request(http_panel,'POST','/api/projects/open',{'path':str(folder)})[2]['project']
    source=request(http_panel,'POST','/api/projects/source',{'project_id':row['id']})[2]['source']
    result=request(http_panel,'POST','/api/mission',{'project_id':row['id'],'source_revision':source['revision'],
        'objective':'本地执行','acceptance_criteria':'文件有效','allowed_paths':'app.py','gate_commands':'python -c "pass"','max_subtasks':1})
    assert result[0]==200,result
    try:
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            data=request(http_panel)[2]
            if data.get('approvals'):break
            time.sleep(.03)
        assert data['mission']['execution_backend']==projects.BACKEND and data['approvals'], data
        approval=data['approvals'][0]
        assert 'Git write' in approval['policy_reason']
        before=engine.trace.read_text()
        assert '"method": null' not in before
        body={'worker_id':approval['worker_id'],'request_id':approval['request_id'],'decision':decision}
        assert request(http_panel,'POST','/api/approval',body,headers={'X-Panel-Nonce':'wrong'})[0]==403
        assert request(http_panel,'POST','/api/approval',body)[0]==200
        assert request(http_panel,'POST','/api/approval',body)[0]!=200
    finally:
        if http_panel.state.running():http_panel.state.stop()
        http_panel.state.thread.join(timeout=8)
        http_panel.state.rt.close()



def test_spawn_without_unique_ack_restart_does_not_create_second_worker(engine,tmp_path,monkeypatch):
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO','spawn_ack_lost')
    folder=tmp_path/'p';folder.mkdir();spec=mission(engine,folder)
    rt=run_mission.build_runtime(spec,engine.cfg)
    try:
        assert drive(rt)['state']=='HUMAN'
        op=next(o for o in rt.store.operations() if o['kind']=='spawn')
        assert op['status']=='UNKNOWN'
        for _ in range(3):rt.controller.step()
        assert rt.store.mission_config('LOCAL-1')['worker_stop']['status']=='UNKNOWN'
    finally:rt.close()
    with pytest.raises(RecoveryError):run_mission.build_runtime(spec,engine.cfg)
    methods=[json.loads(line)['method'] for line in engine.trace.read_text().splitlines()]
    assert methods.count('thread/start')==1 and methods.count('turn/start')==0


def test_confirmed_results_and_backend_are_frozen_history_is_readonly(engine,tmp_path):
    folder=tmp_path/'p';folder.mkdir();spec=mission(engine,folder)
    rt=run_mission.build_runtime(spec,engine.cfg)
    try:
        assert drive(rt)['state']=='MISSION_DONE'
        frozen=rt.store.mission_config('LOCAL-1')['effective_config']
    finally:rt.close()
    before=engine.trace.read_bytes()
    history=run_mission.inspect_runtime('LOCAL-1')
    assert history.mission_dict['execution_backend']==projects.BACKEND and history.controller is None
    assert engine.trace.read_bytes()==before
    with pytest.raises(RecoveryError,match='backend differs'):
        run_mission.build_runtime(dict(spec,execution_backend='ao'),engine.cfg)
    with pytest.raises(RecoveryError,match='terminal Mission'):
        run_mission.build_runtime(spec,resolve_config({'runner':{'poll_seconds':12}}))
    store=StateStore(engine.root/'runtime'/'LOCAL-1'/'state.db',readonly=True)
    try:assert store.mission_config('LOCAL-1')['effective_config']==frozen
    finally:store.close()


def test_source_rejects_junctions_large_files_and_keeps_dirty_disk_content(engine,tmp_path,monkeypatch):
    folder=tmp_path/'p';folder.mkdir();(folder/'app.py').write_text('source')
    row=projects.register(engine.root,str(folder))
    (folder/'large').write_bytes(b'x'*20)
    monkeypatch.setattr(projects,'MAX_FILE_BYTES',10)
    with pytest.raises(ValueError,match='10 MiB'):projects.inspect(row)
    (folder/'large').unlink()
    external=tmp_path/'outside';external.mkdir();(external/'secret').write_text('outside')
    link=folder/'link'
    # Windows junction creation needs no symbolic-link privilege.
    subprocess.run(['cmd','/c','mklink','/J',str(link),str(external)],check=True,capture_output=True)
    try:
        with pytest.raises(ValueError,match='junction'):projects.inspect(row)
        assert (external/'secret').read_text()=='outside'
    finally:os.rmdir(link)  # remove this junction only, never recurse into target


@pytest.mark.parametrize('decision',['answer','send'])
def test_actual_http_question_and_supplemental_input(http_panel,engine,tmp_path,monkeypatch,decision):
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO','question' if decision=='answer' else 'hold')
    monkeypatch.setattr(run_mission,'ROOT',http_panel.root)
    http_panel.state.rt=None;http_panel.state._run=server.PanelState._run.__get__(http_panel.state)
    monkeypatch.setattr(http_panel.state,'defaults',lambda:engine.cfg)
    folder=tmp_path/'p';folder.mkdir()
    row=request(http_panel,'POST','/api/projects/open',{'path':str(folder)})[2]['project']
    source=request(http_panel,'POST','/api/projects/source',{'project_id':row['id']})[2]['source']
    result=request(http_panel,'POST','/api/mission',dict(project_id=row['id'],source_revision=source['revision'],
        objective='local',acceptance_criteria='works',allowed_paths='app.py',gate_commands='python -c "pass"',max_subtasks=1))
    assert result[0]==200,result
    try:
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            snap=request(http_panel)[2]
            if snap.get('subtasks') and snap['subtasks'][0]['worker_session_id'] and (decision=='send' or snap.get('approvals')):break
            time.sleep(.03)
        sid=snap['subtasks'][0]['worker_session_id']
        if decision=='answer':
            approval=snap['approvals'][0]
            assert approval['questions'][0]['id']=='choice'
            assert request(http_panel,'POST','/api/approval',dict(worker_id=sid,request_id=approval['request_id'],decision='answer',answers={'choice':'保留 <tag> 中文'}))[0]==200
        else:
            body={'target':'worker:'+sid,'text':'补充：保留接口','command_id':'CMD-ONE'}
            assert request(http_panel,'POST','/api/directive',body)[0]==200
            assert request(http_panel,'POST','/api/directive',body)[0]==200
            deadline=time.monotonic()+4
            while time.monotonic()<deadline and 'turn/steer' not in engine.trace.read_text():time.sleep(.02)
            assert engine.trace.read_text().count('turn/steer')==1
        assert request(http_panel,'POST','/api/stop',{})[0]==200
    finally:
        http_panel.state.thread.join(timeout=8);http_panel.state.rt.close()


@pytest.mark.parametrize('scenario',['normal','question'])
def test_actual_browser_local_project_to_result(http_panel,engine,tmp_path,monkeypatch,scenario):
    import shutil
    node=os.environ.get('U01_NODE') or shutil.which('node')
    if not node:pytest.skip('Development Node/Playwright unavailable')
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO',scenario)
    monkeypatch.setattr(run_mission,'ROOT',http_panel.root)
    http_panel.state.rt=None;http_panel.state._run=server.PanelState._run.__get__(http_panel.state)
    cfg=resolve_config(engine.cfg,overrides={'runner':{'cap_seconds':60}})
    monkeypatch.setattr(http_panel.state,'defaults',lambda:cfg)
    folder=tmp_path/'浏览器 中文 项目';folder.mkdir();(folder/'app.py').write_text('x=0')
    script=Path(__file__).resolve().parents[2]/'dev'/'panel'/'u02-browser.cjs'
    output=Path(os.environ.get('U02_SCREENSHOTS',str(tmp_path/'screenshots')))/scenario
    try:
        result=subprocess.run([node,str(script),http_panel.origin,str(folder),scenario,str(output)],capture_output=True,encoding='utf-8',errors='replace',timeout=75)
        assert result.returncode==0,result.stdout+'\n'+result.stderr
        assert 'U02_BROWSER_PASS' in result.stdout
        print(result.stdout)
        assert (folder/'app.py').read_text()=='x=0'
    finally:
        if http_panel.state.running():http_panel.state.stop()
        if http_panel.state.thread:http_panel.state.thread.join(timeout=8)
        if http_panel.state.rt and hasattr(http_panel.state.rt,'close'):http_panel.state.rt.close()



def test_replan_live_worker_does_not_spawn_replacement(engine,tmp_path,monkeypatch):
    from loopcore.mission_contracts import PlannerAction, PlannerActionType
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO','kill_live')
    folder=tmp_path/'p';folder.mkdir()
    rt=run_mission.build_runtime(mission(engine,folder),engine.cfg)
    try:
        drive(rt,lambda r:bool(r.controller.tasks and next(iter(r.controller.tasks.values())).worker_session_id))
        task=next(iter(rt.controller.tasks.values()))
        action=PlannerAction('replace-one',task.task_id,PlannerActionType.REPLAN_SPAWN,'controlled replan')
        for _ in range(2):
            with pytest.raises(ExternalOperationUnknown):rt.executor._replan_spawn(action,task)
        methods=[json.loads(line)['method'] for line in engine.trace.read_text().splitlines()]
        assert methods.count('thread/start')==1 and methods.count('turn/interrupt')==1
        assert not (rt.runtime/'integration').exists()
    finally:rt.close()


def test_local_native_approval_scope_and_exact_commands(tmp_path):
    from loopcore.approvals import decide_codex_approval
    root=tmp_path/'工作树 空格';root.mkdir()
    def decision(request,**kwargs):
        return decide_codex_approval(request,allowed_paths=['**'],forbidden_paths=['private/**'],
            gate_commands=['python -m pytest tests -q'],worktree_root=str(root),**kwargs)
    for command,allow in [('python -m pytest tests -q',True),('python',False),
        ('python -m pytest_evil tests -q',False),('python -m pytest tests -q --extra',False),
        ('python -m pytest tests -q\nwhoami',False),('git reset --hard',False),('git status --short',True)]:
        request={'request_id':'1','method':'item/commandExecution/requestApproval','params':{'command':command,'cwd':str(root)}}
        assert decision(request).allow is allow
    for value,allow in [('中文 新文件.py',True),('../outside',False),('private/key',False),('.git',False)]:
        request={'request_id':'2','method':'item/fileChange/requestApproval','params':{'itemId':'edit'},
            'item':{'id':'edit','type':'fileChange','status':'inProgress','changes':[{'path':value,'diff':'+x','kind':{'type':'add'}}]}}
        assert decision(request).allow is allow
        request['params']['grantRoot']=str(root)
        assert not decision(request).allow



def test_proven_process_not_started_allows_bounded_retry(engine,tmp_path,monkeypatch):
    from loopcore.codex_backend import CodexNotStarted
    folder=tmp_path/'p';folder.mkdir()
    cfg=resolve_config(engine.cfg,overrides={'worker':{'spawn_backoff_seconds':.01}})
    rt=run_mission.build_runtime(mission(engine,folder),cfg)
    real=rt.adapter._connect;calls=[]
    def connect():
        calls.append(1)
        if len(calls)==1:raise CodexNotStarted('controlled Popen failure')
        return real()
    monkeypatch.setattr(rt.adapter,'_connect',connect)
    try:
        assert drive(rt)['state']=='MISSION_DONE'
        op=next(o for o in rt.store.operations() if o['kind']=='spawn')
        assert op['status']=='SUCCEEDED' and op['attempts']==2
        assert engine.trace.read_text().count('thread/start')==1
        assert 'never-persist' not in json.dumps(rt.store.mission_config('LOCAL-1'))
    finally:rt.close()


def test_new_attempt_requires_fresh_source_and_uses_new_defaults(http_panel,engine,tmp_path,monkeypatch):
    engine.root=http_panel.root
    monkeypatch.setattr(run_mission,'ROOT',engine.root)
    folder=tmp_path/'new attempt';folder.mkdir();(folder/'app.py').write_text('x=0')
    spec=mission(engine,folder)
    rt=run_mission.build_runtime(spec,engine.cfg)
    assert drive(rt)['state']=='MISSION_DONE'
    old=rt.store.mission_config('LOCAL-1')
    http_panel.state.rt=rt
    assert request(http_panel,'POST','/api/new-attempt',{'mission_id':'LOCAL-1'})[0]==422
    (folder/'app.py').write_text('x=9')
    source=request(http_panel,'POST','/api/projects/source',{'project_id':spec['project_id']})[2]['source']
    cfg=resolve_config(engine.cfg,overrides={'runner':{'poll_seconds':.1}})
    monkeypatch.setattr(http_panel.state,'defaults',lambda:cfg)
    http_panel.state._run=server.PanelState._run.__get__(http_panel.state)
    try:
        response=request(http_panel,'POST','/api/new-attempt',{'mission_id':'LOCAL-1','source_revision':source['revision']})
        assert response[0]==200,response
        http_panel.state.thread.join(timeout=15)
        new=http_panel.state.rt.store.mission_config(response[2]['mission_id'])
        assert new['state']=='MISSION_DONE' and new['previous_attempt']=='LOCAL-1'
        assert new['execution_backend']==projects.BACKEND
        assert new['source']['manifest']['revision']==source['revision']!=old['source']['manifest']['revision']
        assert new['effective_config']['values']['runner']['poll_seconds']==.1
        assert old['effective_config']['values']['runner']['poll_seconds']==.02
        assert rt.store.mission_config('LOCAL-1')==old
        assert (folder/'app.py').read_text()=='x=9'
    finally:
        http_panel.state.rt.close();rt.close()



def test_formal_cli_preview_then_confirmed_execution(engine,tmp_path,monkeypatch,capsys):
    folder=tmp_path/'CLI 中文';folder.mkdir();(folder/'app.py').write_text('x=0')
    spec=mission(engine,folder)
    for key in ('project_id','source_revision','execution_backend'):spec.pop(key)
    spec['project_id']='REPLACE_WITH_AO_PROJECT_ID'
    source_file=tmp_path/'mission.json';source_file.write_text(json.dumps(spec),'utf-8')
    args=['run_mission.py',str(source_file),'--project-path',str(folder)]
    monkeypatch.setattr(sys,'argv',args)
    monkeypatch.setattr(run_mission,'load_config',lambda:engine.cfg)
    assert run_mission.main()==0
    preview=json.loads(capsys.readouterr().out)
    assert preview['source']['kind']=='folder' and not (engine.root/'runtime'/'LOCAL-1').exists()
    assert not engine.trace.exists()
    monkeypatch.setattr(sys,'argv',args+['--confirm-source',preview['source']['revision']])
    assert run_mission.main()==0
    assert 'MISSION_DONE' in capsys.readouterr().out
    assert (folder/'app.py').read_text()=='x=0'
    assert (engine.root/'runtime'/'LOCAL-1'/'integration'/'app.py').read_text()=='x=2\n'



def test_native_model_facts_do_not_become_provider_timing(engine,tmp_path,monkeypatch):
    monkeypatch.setenv('CLAO_TEST_CODEX_SCENARIO','reroute')
    folder=tmp_path/'p';folder.mkdir()
    rt=run_mission.build_runtime(mission(engine,folder),engine.cfg)
    try:
        assert drive(rt)['state']=='MISSION_DONE'
        wid=next(iter(rt.adapter.workers));rt.adapter.get_worker_status(wid)
        fact=rt.diagnostics._worker_facts[wid]
        assert fact['requested_model']==fact['passed_model']==engine.cfg['worker']['model']
        assert fact['spawn_resolved_model']=='resolved-test-model'
        assert fact['model_reroute']['to_model']=='rerouted-test-model'
        assert 'thread/start' in fact['spawn_model_evidence']
        assert 'model/rerouted' in fact['model_reroute']['source'] and fact['model_reroute']['turn_id']
        assert engine.trace.read_text().count('thread/start')==1
    finally:rt.close()



def test_managed_checkout_does_not_execute_inherited_content_filter(engine,tmp_path,monkeypatch):
    folder=tmp_path/'filter source';folder.mkdir()
    (folder/'app.py').write_text('x=0')
    (folder/'.gitattributes').write_text('*.py filter=untrusted\n')
    marker=tmp_path/'filter-invoked'
    driver=tmp_path/'driver.py';driver.write_text('import pathlib,sys\npathlib.Path('+repr(str(marker))+').write_text("invoked")\nsys.stdout.buffer.write(sys.stdin.buffer.read())')
    config=tmp_path/'git-config'
    subprocess.run(['git','config','--file',str(config),'filter.untrusted.smudge','"'+Path(sys.executable).as_posix()+'" "'+driver.as_posix()+'"'],check=True)
    monkeypatch.setenv('GIT_CONFIG_GLOBAL',str(config))
    before=config.read_bytes()
    rt=run_mission.build_runtime(mission(engine,folder),engine.cfg)
    try:
        assert drive(rt)['state']=='MISSION_DONE'
        assert not marker.exists() and config.read_bytes()==before
        assert (folder/'app.py').read_text()=='x=0'
    finally:rt.close()
