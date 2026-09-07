"""R02: isolated SQLite/Git/public fake AO and actual Panel HTTP boundaries."""
import copy
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import run_mission
from panel import server
from loopcore import worktree as wt
from loopcore.action_executor import ActionExecutor, ExternalOperationUnknown, operation_id
from loopcore.directives import DirectiveChannel
from loopcore.effective_config import resolve_config
from loopcore.execution_control import run as controlled_run
from loopcore.mission import MissionController, MISSION_TERMINAL
from loopcore.mission_contracts import MissionSpec, MissionPlan, SubtaskPlan, ProjectState
from loopcore.recovery import source_identity, validate_checkpoint, RecoveryError
from loopcore.state_store import StateStore
from loopcore.verifier import FakeVerifierProvider
from tests.sidecar_port.test_mission import _mc, SINGLE_MISSION
from tests.test_f04_panel_boundaries import panel, http_panel, request
from tests.test_f05_external_operations import ao, Crash
from tests.test_f03_git_evidence import git, write


def repository(tmp_path):
    repo = tmp_path / 'source 中文'
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    git(repo, 'config', 'user.name', 'Test')
    write(repo, 'app.py', 'x=1\n')
    git(repo, 'add', 'app.py'); git(repo, 'commit', '-m', 'base')
    remote = tmp_path / 'origin.git'
    git(repo, 'clone', '--bare', str(repo), str(remote))
    git(repo, 'remote', 'add', 'origin', str(remote))
    git(repo, 'fetch', 'origin')
    return repo


def seeded(tmp_path, ao):
    repo = repository(tmp_path)
    mc, store = _mc(tmp_path, mission_data=dict(SINGLE_MISSION, project_id='p'))
    cfg = resolve_config({})
    source = source_identity('p', repo, {'defaultBranch': 'main'})
    store.record_mission(mc.mission.mission_id, {'mission': mc.mission.to_dict(),
        'effective_config': cfg.snapshot(), 'source': source})
    mc.adapter = ao.adapter
    mc.executor.adapter = ao.adapter
    mc.executor._run = ao.run
    ao.adapter.get_project = lambda pid: dict(id='p', path=str(repo), defaultBranch='main')
    workspaces = {}
    ao.adapter.get_session_workspace = lambda sid: str(workspaces[sid])
    original = ao.run
    def spawn(args, **kw):
        try:
            return original(args, **kw)
        finally:
            if args[0] == 'spawn':
                sid = list(ao.sessions)[-1]
                path = tmp_path / sid
                if not path.exists():
                    git(repo, 'worktree', 'add', '-b', sid, str(path), 'origin/main')
                workspaces[sid] = path
    mc.executor._run = spawn
    mc.step()
    return mc, store, repo, workspaces


def bind_panel(http_panel, monkeypatch, ao):
    mc, old = _mc(http_panel.root / 'scratch', mission_data=dict(SINGLE_MISSION, mission_id='M-F04', project_id='p'))
    old.close()
    mc.store = http_panel.store
    mc.control.store = mc.store
    mc.executor.store = mc.store
    mc.gate.store = mc.store
    mc.directives = DirectiveChannel(mc.store, 'M-F04')
    mc.adapter = ao.adapter
    mc.executor.adapter = ao.adapter
    mc.executor._run = ao.run
    mc.store.record_mission('M-F04', {'mission': mc.mission.to_dict()})
    rt = SimpleNamespace(controller=mc, runtime=http_panel.runtime,
                         mission=mc.mission, mission_dict=mc.mission.to_dict())
    http_panel.state.rt = rt
    return mc


def receipt(store, mid, cid):
    return next(r for r in store.directives(mid) if r['command_id'] == cid)


def test_http_receipt_failure_never_enqueues_or_consumes(http_panel, monkeypatch, ao):
    mc = bind_panel(http_panel, monkeypatch, ao)
    with monkeypatch.context() as patch:
        patch.setattr(mc.store, 'receive_directive', MagicMock(side_effect=OSError('disk full')))
        status, _, result = request(http_panel, 'POST', '/api/directive', {'command_id':'cmd1','target':'planner','text':'优先边界'})
    assert status != 200 and not result['ok']
    assert mc.directives.pending_count() == 0
    mc.step(); mc._apply_directives()
    assert not ao.calls and mc.store.directives('M-F04') == []


def test_http_receipt_idempotency_conflict_and_no_consumer(http_panel, monkeypatch, ao):
    mc = bind_panel(http_panel, monkeypatch, ao)
    body = dict(command_id='same', target='planner', text='中文 <tag> "quoted"')
    one = request(http_panel, 'POST', '/api/directive', body)
    two = request(http_panel, 'POST', '/api/directive', body)
    assert one[0] == two[0] == 200
    assert one[2]['directive']['at'] == two[2]['directive']['at']
    assert len(mc.directives.records()) == 1
    assert request(http_panel, 'POST', '/api/directive', dict(body, text='conflict'))[0] != 200
    for target in ('observer', 'gate', 'worker:outside'):
        assert request(http_panel, 'POST', '/api/directive', dict(command_id=target.replace(':','-'), target=target,text='x'))[0] == 422
    assert receipt(mc.store,'M-F04','same')['status'] == 'received'
    assert request(http_panel)[2]['directive_receipts']['records'][0]['text'] == body['text']


def test_worker_send_crash_receipt_reopens_without_repeat(tmp_path, ao):
    mc, store = _mc(tmp_path, mission_data=dict(SINGLE_MISSION, project_id='p'))
    mc.step(); task = next(iter(mc.tasks.values()))
    task.worker_session_id='w'; store.record_task(task.task_id, task.to_dict())
    ao.session('w'); mc.executor.adapter=ao.adapter; mc.executor._run=ao.run
    command = mc.directives.post('worker:w','修复源码','cmd-worker')
    ao.fault='crash'
    with pytest.raises(Crash): mc._apply_directives()
    assert receipt(store,mc.mission.mission_id,command.command_id)['status']=='unknown'
    store.close()
    mc, store = _mc(tmp_path, mission_data=dict(SINGLE_MISSION, project_id='p'))
    mc.executor.adapter=ao.adapter; mc.executor._run=ao.run; ao.fault=None
    for _ in range(2):
        with pytest.raises(ExternalOperationUnknown): mc._apply_directives()
    assert len(ao.messages)==1
    assert receipt(store,mc.mission.mission_id,command.command_id)['status']=='unknown'
    store.close()


def test_actual_planner_and_auditor_inputs_and_mirror(tmp_path, monkeypatch):
    from tests.test_crash_resume import _parked_loop, _pass_audit
    loop, store = _parked_loop(tmp_path, monkeypatch, ProjectState.PLANNER_PENDING)
    channel = DirectiveChannel(store,'parent')
    loop.directives=channel
    channel.post('planner','规划边界','planner-cmd')
    channel.post('auditor','审计边界','audit-cmd')
    captured=[]
    original=loop.planner.plan
    def plan(*args,**kw):
        captured.append(kw['instruct']); return original(*args,**kw)
    loop.planner.plan=plan
    from loopcore.mission_contracts import AuditResult
    loop._to_planner(AuditResult.from_dict(_pass_audit(loop.task.task_id)))
    assert '规划边界' in captured[0] and '审计边界' in captured[0]
    audit_receipt=receipt(store,'parent','audit-cmd')
    assert audit_receipt['status']=='received'
    assert any(not c['primary'] and c['status']=='applied' for c in audit_receipt['consumers'].values())
    assert receipt(store,'parent','planner-cmd')['status']=='applied'
    from loopcore.auditor import EvidenceBundle
    bundle=EvidenceBundle(task_spec=loop.task.to_dict(),worker_id='w',alert={},history={})
    audit=AuditResult.from_dict(_pass_audit(loop.task.task_id));audit.decision='LOCAL_FIX'
    def check_bundle(value, identity):
        assert '审计边界' in str(value.history['user_directives'])
        return audit
    loop.auditor.audit=check_bundle
    audit.evidence = [dict(type='observation', summary='controlled input-boundary fixture')]
    loop._checked_audit(bundle, audit.audit_id)
    assert receipt(store,'parent','audit-cmd')['status']=='applied'
    store.close()


def test_final_verifier_receives_notes_and_deterministic_scope_still_blocks(tmp_path, monkeypatch):
    mc, store = _mc(tmp_path, mission_data=SINGLE_MISSION)
    repo=repository(tmp_path)
    base=git(repo,'rev-parse','HEAD').decode().strip()
    wt.freeze_base(str(repo),store,mc.mission.mission_id,scope='integration',expected=base)
    write(repo,'app.py','x=2\n');git(repo,'add','app.py');git(repo,'commit','-m','delivery')
    mc.mission.gate_commands=['python -c "pass"']
    mc._integration_wt=lambda: str(repo)
    captured=[]
    original=mc.verifier.verify
    def verify(inp,identity):
        captured.append(inp);return original(inp,identity)
    mc.verifier.verify=verify
    mc.directives.post('verifier','核对用户边界 <x>','final-note')
    from loopcore.verifier import VerifierInput
    original_validation = VerifierInput.validation_record
    def post_during_input_validation(inp, identity):
        mc.directives.post('verifier', '输入已固定后到达', 'late-note')
        return original_validation(inp, identity)
    monkeypatch.setattr(VerifierInput, 'validation_record', post_during_input_validation)
    mc._final_verify()
    assert captured and '核对用户边界' in captured[0].user_notes[0]
    assert receipt(store,mc.mission.mission_id,'final-note')['status']=='applied'
    assert all('输入已固定后到达' not in note for note in captured[0].user_notes)
    late = receipt(store,mc.mission.mission_id,'late-note')
    assert late['status']=='rejected' and 'verifier:mission-final' not in late['consumers']
    monkeypatch.setattr(VerifierInput, 'validation_record', original_validation)
    store.close()
    # Separate mission with forbidden real edit: no Verifier PASS can override.
    other, db = _mc(tmp_path/'other',mission_data=SINGLE_MISSION)
    other.mission.gate_commands=['python -c "pass"'];other._integration_wt=lambda:str(repo)
    wt.freeze_base(str(repo),db,other.mission.mission_id,scope='integration',expected=base)
    write(repo,'forbidden.txt','x');git(repo,'add','forbidden.txt');git(repo,'commit','-m','out of scope')
    other.verifier.verify=MagicMock()
    other._final_verify()
    assert other.state=='HUMAN';other.verifier.verify.assert_not_called();db.close()


@pytest.mark.parametrize('phase',['worker','planner','gate'])
def test_http_cancel_is_prompt_and_waits_for_real_stops(http_panel, monkeypatch, ao, tmp_path, phase):
    mc=bind_panel(http_panel,monkeypatch,ao)
    mc.step();task=next(iter(mc.tasks.values()))
    task.worker_session_id='w';mc.store.record_task(task.task_id,task.to_dict());ao.session('w')
    entered=threading.Event()
    if phase=='worker':
        original=ao.run
        def slow_kill(*args,**kw):
            entered.set();time.sleep(.35);return original(*args,**kw)
        mc.executor._run=slow_kill
    else:
        def slow_stage():
            entered.set()
            if phase=='gate':
                repo=repository(tmp_path)
                task.gate_commands=['python -c "import time; time.sleep(30)"']
                mc.gate.run(task,str(repo))
            else:
                controlled_run([sys.executable,'-c','import time; time.sleep(30)'],capture_output=True,text=True,timeout=40)
            pytest.fail('cancelled result must not advance Mission')
        mc._step_impl=slow_stage
    if phase!='worker':
        thread=threading.Thread(target=mc.step);http_panel.state.thread=thread;thread.start()
        assert entered.wait(5)
        # Wait for a real owned process before sending cancellation.
        for _ in range(100):
            if mc.store.mission_config('M-F04').get('local_execution',{}).get('status')=='running':break
            time.sleep(.01)
        assert mc.store.mission_config('M-F04')['local_execution']['status']=='running'
    else:
        # Existing idle runner is represented by the normal next Controller step.
        http_panel.state._run=lambda:mc.step()
    begin=time.monotonic()
    status,_,data=request(http_panel,'POST','/api/stop',{})
    assert status==200 and data['stop_requested']
    assert time.monotonic()-begin < .3
    assert mc.store.mission_stop_requested('M-F04')
    http_panel.state.thread.join(8)
    assert not http_panel.state.thread.is_alive()
    row=mc.store.mission_config('M-F04')
    assert row['state']=='CANCELLED' and row['cancellation']['status']=='cancelled'
    assert row['worker_stop']['status']=='CONFIRMED'
    assert ao.sessions['w']['isTerminated']
    assert len(ao.calls)==1


def test_cancel_unknown_never_claims_done(http_panel,monkeypatch,ao):
    mc=bind_panel(http_panel,monkeypatch,ao);mc.step()
    task=next(iter(mc.tasks.values()));task.worker_session_id='w';mc.store.record_task(task.task_id,task.to_dict())
    ao.session('w');ao.terminate=False;ao.fault='timeout'
    http_panel.state._run=lambda:mc.step()
    assert request(http_panel,'POST','/api/stop',{})[0]==200
    http_panel.state.thread.join(5)
    row=mc.store.mission_config('M-F04')
    assert row['state']=='HUMAN' and row['cancellation']['status']=='unknown'
    assert row['worker_stop']['status']=='UNKNOWN'
    mc.step();assert len(ao.calls)==1


def test_cancel_receipt_failure_has_no_side_effect(http_panel,monkeypatch,ao):
    mc=bind_panel(http_panel,monkeypatch,ao)
    monkeypatch.setattr(mc.store,'request_mission_stop',MagicMock(side_effect=OSError('disk full')))
    status,_,data=request(http_panel,'POST','/api/stop',{})
    assert status==503 and not data['ok']
    assert not mc._stop_event.is_set() and not http_panel.state.stop_flag.is_set()
    assert not mc.store.mission_stop_requested('M-F04') and not ao.calls


def test_source_freeze_prompt_and_readonly_recovery(tmp_path,ao):
    mc,store,repo,workspaces=seeded(tmp_path,ao)
    mc._dispatch_ready()
    task=next(iter(mc.tasks.values()))
    source=store.mission_config(mc.mission.mission_id)['source']
    prompt=ao.calls[0][ao.calls[0].index('--prompt')+1]
    for part in (task.objective,'app.py','.git/**',task.acceptance_criteria[0].description,
                 task.gate_commands[0],mc.mission.user_instruction):
        assert part in prompt
    before=store._conn.total_changes
    row,cfg=validate_checkpoint(store,mc.mission.mission_id,ao.adapter)
    assert row['source']['source_commit']==git(repo,'rev-parse','HEAD').decode().strip()
    assert store._conn.total_changes==before and len(ao.calls)==1
    # main/origin can drift without rewriting the existing Mission/checkpoint.
    write(repo,'app.py','x=3\n');git(repo,'add','app.py');git(repo,'commit','-m','source moved');git(repo,'push','origin','main')
    validate_checkpoint(store,mc.mission.mission_id,ao.adapter)
    assert store.mission_config(mc.mission.mission_id)['source']==source
    next_task=copy.deepcopy(task);next_task.task_id+='-NEXT';next_task.worker_session_id=None
    with pytest.raises(RecoveryError,match='drift'):
        mc.executor.spawn_initial_worker(next_task)
    assert len(ao.calls)==1
    integ=mc._integration_wt(str(workspaces[task.worker_session_id]))
    assert git(integ,'rev-parse','HEAD').decode().strip()==source['source_commit']
    store.close()


@pytest.mark.parametrize('missing',['source','config','workspace','base','session','operation','verification'])
def test_resume_refuses_missing_material_without_mutation(tmp_path,ao,missing):
    mc,store,repo,workspaces=seeded(tmp_path,ao);mc._dispatch_ready()
    task=next(iter(mc.tasks.values()));mid=mc.mission.mission_id
    if missing=='source':store.record_mission(mid,{'source':None})
    if missing=='config':store.record_mission(mid,{'effective_config':None})
    if missing=='workspace':ao.adapter.get_session_workspace=lambda sid:str(tmp_path/'missing')
    if missing=='base':wt._sidecar_path(str(workspaces[task.worker_session_id]),task.task_id+':'+task.worker_session_id).unlink()
    if missing=='session':ao.sessions[task.worker_session_id]['projectId']='wrong'
    if missing=='operation':
        store.ensure_operation('lost-send','send',mid,task.worker_session_id,{})
        store.operation_claim('lost-send');store.operation_observe('lost-send','UNKNOWN',{'reason':'lost ACK'})
    if missing=='verification':store.record_verification('bad',mid,{'task_id':'wrong'})
    before=store._conn.total_changes;calls=len(ao.calls)
    with pytest.raises((RecoveryError,ValueError)):validate_checkpoint(store,mid,ao.adapter)
    assert store._conn.total_changes==before and len(ao.calls)==calls
    store.close()


def test_lost_spawn_ack_full_resume_adopts_existing_worker(tmp_path,ao):
    mc,store,repo,workspaces=seeded(tmp_path,ao)
    ao.fault='crash'
    with pytest.raises(Crash):mc._dispatch_ready()
    mid=mc.mission.mission_id
    store.close();ao.fault=None
    reopened=StateStore(tmp_path/'m.db',readonly=True)
    row,cfg=validate_checkpoint(reopened,mid,ao.adapter)
    reopened.close()
    mc2,store2=_mc(tmp_path,mission_data=dict(SINGLE_MISSION,project_id='p'))
    mc2.adapter=ao.adapter;mc2.executor.adapter=ao.adapter;mc2.executor._run=ao.run
    assert mc2._hydrate()
    mc2._dispatch_ready()
    assert next(iter(mc2.tasks.values())).worker_session_id=='worker-0'
    assert len(ao.calls)==1
    assert store2.operations(mid)[0]['status']=='SUCCEEDED'
    store2.close()


def test_real_http_history_is_readonly_and_terminal_attempt_is_new(http_panel,monkeypatch):
    mid='M-F04';store=http_panel.store
    old=dict(SINGLE_MISSION,mission_id=mid)
    store.record_mission(mid,{'state':'HUMAN','mission':old})
    store._conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    before=Path(store.path).read_bytes();mtime=Path(store.path).stat().st_mtime_ns
    monkeypatch.setattr(run_mission,'ROOT',http_panel.root)
    monkeypatch.setattr(run_mission,'mission_preflight',MagicMock(side_effect=AssertionError('no AO on history/terminal resume')))
    monkeypatch.setattr(run_mission,'MissionRuntime',MagicMock(side_effect=AssertionError('no runtime assembly')))
    status,_,_=request(http_panel,'POST','/api/attach',{'mission_id':mid})
    assert status==200 and http_panel.state.rt.controller is None
    assert request(http_panel)[2]['mission_config']['status']=='historical_missing'
    assert request(http_panel,'POST','/api/resume',{'mission_id':mid})[0]!=200
    assert Path(store.path).read_bytes()==before and Path(store.path).stat().st_mtime_ns==mtime
    captured=[]
    monkeypatch.setattr(http_panel.state,'start_mission',lambda spec:captured.append(spec))
    result=request(http_panel,'POST','/api/new-attempt',{'mission_id':mid})
    assert result[0]==200 and captured[0]['mission_id']!=mid
    assert captured[0]['previous_attempt']==mid
    assert Path(store.path).read_bytes()==before and store.mission_config(mid)['state']=='HUMAN'


def test_dependent_plan_rejected_before_spawn_independent_two_allowed(tmp_path):
    from loopcore.planner_adapter import FakePlannerProvider
    planner=FakePlannerProvider()
    for dependent in (True,False):
        def decompose(spec,identity):
            return MissionPlan(mission_id=spec['mission_id'],strategy='two',subtasks=[
                SubtaskPlan(subtask_id=spec['mission_id']+'-S1',objective='a',allowed_paths=['app.py'],acceptance_criteria=MissionSpec.from_dict(spec).acceptance_criteria,gate_commands=[],dependencies=[]),
                SubtaskPlan(subtask_id=spec['mission_id']+'-S2',objective='b',allowed_paths=['math2.py'],acceptance_criteria=MissionSpec.from_dict(spec).acceptance_criteria,gate_commands=[],dependencies=[spec['mission_id']+'-S1'] if dependent else [])])
        planner.plan_decompose=decompose
        mc,store=_mc(tmp_path/str(dependent),planner=planner)
        mc.executor.spawn_initial_worker=MagicMock(return_value=None)
        mc.step()
        if dependent:
            assert mc.state=='HUMAN' and 'dependent' in mc._read_state()['reason']
            assert not mc.tasks
        else:
            mc._dispatch_ready();assert mc.executor.spawn_initial_worker.call_count==2
        store.close()


def test_source_mismatch_rejected_and_later_worker_creation_is_checked(tmp_path,ao):
    from loopcore.recovery import worker_source
    repo=repository(tmp_path)
    source=source_identity('p',repo,{'defaultBranch':'main'})
    write(repo,'app.py','x=10\n');git(repo,'add','app.py');git(repo,'commit','-m','local only')
    with pytest.raises(RecoveryError,match='differ'):
        source_identity('p',repo,{'defaultBranch':'main'})
    wrong=tmp_path/'wrong-base'
    git(repo,'worktree','add','-b','wrong',str(wrong),'HEAD')
    with pytest.raises(RecoveryError,match='creation base'):
        worker_source(source,str(wrong))


def test_build_runtime_refuses_bad_resume_before_provider_or_store_writes(tmp_path,ao,monkeypatch):
    mc,store,repo,workspaces=seeded(tmp_path,ao);mc._dispatch_ready()
    mid=mc.mission.mission_id
    store.close()
    root=tmp_path/'runtime-root';dest=root/'runtime'/mid/'state.db'
    dest.parent.mkdir(parents=True);dest.write_bytes((tmp_path/'m.db').read_bytes())
    monkeypatch.setattr(run_mission,'ROOT',root)
    monkeypatch.setattr(run_mission,'mission_preflight',lambda *a,**k:dict(ao_bin='ao',ao_run_file=tmp_path/'none'))
    monkeypatch.setattr(run_mission,'AOAdapter',lambda **k:ao.adapter)
    build=MagicMock(side_effect=AssertionError('must not construct Provider/runtime'))
    monkeypatch.setattr(run_mission,'MissionRuntime',build)
    ao.adapter.get_session_workspace=lambda sid:str(tmp_path/'lost-worker')
    before=dest.read_bytes();stamp=dest.stat().st_mtime_ns
    with pytest.raises(RecoveryError):run_mission.build_runtime(mc.mission.to_dict(),resolve_config({}))
    build.assert_not_called()
    assert dest.read_bytes()==before and dest.stat().st_mtime_ns==stamp
    assert len(ao.calls)==1


def test_real_edge_r02_status_receipts_and_new_attempt_pending(http_panel,monkeypatch,tmp_path):
    import re
    from tests.test_f04_panel_boundaries import _browser_executable
    browser=_browser_executable()
    if not browser:pytest.skip('Edge/Chromium unavailable')
    injected='\"><img src=x onerror=window.PWNED=1> 中文 & R02_MARKER'
    mission=dict(SINGLE_MISSION,mission_id='M-F04')
    http_panel.store.record_mission('M-F04',{'state':'HUMAN','mission':mission,
        'source':dict(source_ref=injected,source_commit='a'*40),
        'cancellation':dict(status='unknown',reason=injected),'reason':injected})
    channel=DirectiveChannel(http_panel.store,'M-F04')
    channel.post('gate',injected,'browser-cmd')
    monkeypatch.setattr(server,'_load_ao_projects',lambda:[])
    calls=[]
    def new_attempt(handler,body):
        calls.append(body);time.sleep(.03)
        return dict(ok=True,mission_id='NEW-ATTEMPT')
    monkeypatch.setattr(server.Handler,'_new_attempt',new_attempt)
    def snapshot_once(handler):
        handler.send_response(200);handler.send_header('Content-Type','text/event-stream');handler.end_headers()
        handler.wfile.write(('data: '+json.dumps(server.snapshot())+'\n\n').encode())
    monkeypatch.setattr(server.Handler,'_sse',snapshot_once)
    html=(server.PANEL_DIR/'index.html').read_text(encoding='utf-8')
    probe=r'''<script nonce="__PANEL_NONCE__">
    (async()=>{try{
      const check=(x,m)=>{if(!x)throw new Error(m)};
      const wait=async f=>{for(let i=0;i<800&&!f();i++)await new Promise(r=>setTimeout(r,10));check(f(),'wait timeout')};
      await wait(()=>LAST?.mission);
      check(!window.PWNED&&!document.querySelector('img,[onerror]'),'unsafe DOM');
      check($('diagnostics').textContent.includes('R02_MARKER'),'lost source/reason text');
      check($('diagnostics').textContent.includes('browser-cmd'),'receipt missing');
      check(document.querySelector('#d_target [value="gate"]').disabled,'Gate falsely available');
      check(document.querySelector('#d_target [value="observer"]').disabled,'Observer falsely available');
      openTask(LAST.mission.id);
      const find=()=>[...document.querySelectorAll('#detailExtraActions button')].find(b=>b.textContent==='新 attempt');
      check(find()?.disabled,'unknown stop must block new attempt');find().click();
      check(!PENDING.has('mission'),'unknown stop initiated a write');
      render({...LAST,mission:{...LAST.mission,state:'CANCELLED',cancellation:{status:'cancelled'},worker_stop:{status:'CONFIRMED'}}});
      check(find(),'terminal missing new attempt');find().click();render(LAST);find().click();await wait(()=>!PENDING.has('mission'));
      for(const state of ['requested','cancelling','cancelled','unknown']){
        render({...LAST,mission:{...LAST.mission,cancellation:{status:state,reason:'真实取消阶段 中文'},stop_request:{source:'user'}}});
        check($('diagnostics').textContent.includes('取消状态：'+state),'cancellation status missing '+state);
        check($('btnStop').disabled,'duplicate stop enabled');
      }
      render({...LAST,directive_receipts:{status:'historical_unknown',records:[]}});
      check($('diagnostics').textContent.includes('指令回执：historical_unknown'),'missing historical receipt status');
      check(!window.PWNED,'late XSS');document.documentElement.dataset.r02Result='PASS';
    }catch(e){document.documentElement.dataset.r02Result='FAIL: '+e.message}})();
    </script>'''
    assets=tmp_path/'assets';assets.mkdir();(assets/'index.html').write_text(html.replace('</body>',probe+'</body>'),encoding='utf-8')
    monkeypatch.setattr(server,'PANEL_DIR',assets)
    result=subprocess.run([browser,'--headless','--disable-gpu','--no-first-run','--disable-background-networking',
        '--user-data-dir='+str(tmp_path/'edge-profile'),'--virtual-time-budget=15000','--dump-dom',http_panel.origin+'/'],
        capture_output=True,timeout=50,encoding='utf-8',errors='replace')
    outcome=re.search(r'data-r02-result="([^"]*)"',result.stdout)
    assert outcome and outcome.group(1)=='PASS',outcome.group(1) if outcome else result.stdout[-1200:]
    assert calls==[{'mission_id':'M-F04'}]



def test_closed_history_does_not_create_wal_or_runtime_files(tmp_path,monkeypatch):
    root=tmp_path/'history';db=root/'runtime'/'OLD'/'state.db'
    store=StateStore(db);store.record_mission('OLD',{'mission':dict(SINGLE_MISSION,mission_id='OLD'),'state':'HUMAN'})
    store.close()
    before={str(p.relative_to(root)):(p.read_bytes(),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    monkeypatch.setattr(run_mission,'ROOT',root)
    handle=run_mission.inspect_runtime('OLD')
    assert handle.controller is None
    after={str(p.relative_to(root)):(p.read_bytes(),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    assert before==after


def test_cancel_after_crash_does_not_guess_local_process_stopped(tmp_path):
    mc,store=_mc(tmp_path,mission_data=SINGLE_MISSION)
    mc.step();mc.request_stop()
    store.record_mission(mc.mission.mission_id,{'local_execution':{'status':'running','pid':12345}})
    result=mc.step()
    assert result['state']=='HUMAN'
    row=store.mission_config(mc.mission.mission_id)
    assert row['cancellation']['status']=='unknown' and row['cancellation']['local_unconfirmed']==[12345]
    store.close()


def test_final_checkpoint_does_not_require_already_merged_worker_workspace(tmp_path,ao):
    mc,store,repo,workspaces=seeded(tmp_path,ao);mc._dispatch_ready()
    task=next(iter(mc.tasks.values()))
    write(workspaces[task.worker_session_id],'app.py','x=2\n')
    store.record_transition(task_id=task.task_id,from_state='WORKER_RUNNING',to_state='DONE',actor='test',reason='done',evidence={})
    mc._merge_done()
    assert mc.merged==[task.task_id]
    ao.adapter.get_session_workspace=MagicMock(side_effect=AssertionError('merged workspace no longer required'))
    before=len(ao.calls)
    validate_checkpoint(store,mc.mission.mission_id,ao.adapter)
    assert len(ao.calls)==before
    ao.adapter.get_session_workspace.assert_not_called()
    store.close()


@pytest.mark.parametrize('status', ['running', 'unknown'])
def test_new_attempt_refuses_unconfirmed_old_local_execution(http_panel, monkeypatch, status):
    mid = 'M-F04'
    store = http_panel.store
    store.record_mission(mid, {'state': 'HUMAN', 'mission': dict(SINGLE_MISSION, mission_id=mid),
                              'local_execution': {'status': status, 'pid': 12345}})
    start = MagicMock()
    monkeypatch.setattr(http_panel.state, 'start_mission', start)
    before = store.mission_config(mid)
    result = request(http_panel, 'POST', '/api/new-attempt', {'mission_id': mid})
    assert result[0] == 409
    start.assert_not_called()
    assert store.mission_config(mid) == before


def test_http_new_attempt_freezes_new_source_and_config_without_rewriting_old(http_panel, monkeypatch, tmp_path):
    repo = repository(tmp_path)
    old_source = source_identity('p', repo, {'defaultBranch': 'main'})
    old_config = resolve_config({'worker': {'model': 'old-worker-model'}}).snapshot()
    mid = 'M-F04'
    http_panel.store.record_mission(mid, {'state': 'HUMAN',
        'mission': dict(SINGLE_MISSION, mission_id=mid, project_id='p'),
        'source': old_source, 'effective_config': old_config})
    before = http_panel.store.mission_config(mid)
    write(repo, 'app.py', 'x=2\n');git(repo, 'add', 'app.py');git(repo, 'commit', '-m', 'new source')
    git(repo, 'push', 'origin', 'main');git(repo, 'fetch', 'origin')
    monkeypatch.setattr(run_mission, 'ROOT', http_panel.root)
    monkeypatch.setattr(run_mission, 'setup_environment', lambda **kw: None)
    monkeypatch.setattr(run_mission, 'mission_preflight', lambda *a, **kw: dict(
        ao_bin='fake-ao', ao_run_file=tmp_path/'no-runfile',
        source=source_identity('p', repo, {'defaultBranch': 'main'})))
    # Exercise the real runtime and providers' configuration, but never step them.
    monkeypatch.setattr(http_panel.state, '_run', lambda: None)
    http_panel.state.set_config({'worker': {'model': 'new-worker-model'}})
    status, _, result = request(http_panel, 'POST', '/api/new-attempt', {'mission_id': mid})
    assert status == 200
    http_panel.state.thread.join(2)
    new = http_panel.state.rt
    try:
        row = new.store.mission_config(result['mission_id'])
        assert result['mission_id'] != mid and row['previous_attempt'] == mid
        assert row['source']['source_commit'] != old_source['source_commit']
        assert row['source']['source_commit'] == git(repo, 'rev-parse', 'HEAD').decode().strip()
        assert row['effective_config']['revision'] != old_config['revision']
        assert new.executor.worker_model == 'new-worker-model'
        assert new.store.all_task_ids() == [] and new.store.operations(result['mission_id']) == []
        assert http_panel.store.mission_config(mid) == before
    finally:
        new.close()


def test_cancel_during_materialization_cannot_start_integration(tmp_path, ao, monkeypatch):
    from loopcore.execution_control import ExecutionCancelled
    mc, store, repo, workspaces = seeded(tmp_path, ao)
    mc._dispatch_ready()
    task = next(iter(mc.tasks.values()))
    store.record_transition(task_id=task.task_id, from_state='WORKER_RUNNING', to_state='DONE',
                            actor='test', reason='done', evidence={})
    original = wt.commit_all
    def cancel_after_delivery(*args, **kwargs):
        result = original(*args, **kwargs)
        mc.request_stop()
        return result
    monkeypatch.setattr(wt, 'commit_all', cancel_after_delivery)
    integration = MagicMock(side_effect=AssertionError('must not initialize/merge integration after cancellation'))
    monkeypatch.setattr(mc, '_integration_wt', integration)
    with mc.control.bind(), pytest.raises(ExecutionCancelled):
        mc._merge_done()
    integration.assert_not_called()
    assert not mc.merged
    assert mc.step()['state'] == 'CANCELLED'
    store.close()
