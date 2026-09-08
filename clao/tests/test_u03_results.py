"""Frozen results through real Git/SQLite/HTTP; only engine/provider boundaries fake."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from panel import server
from loopcore import results, local_projects, worktree as wt
from loopcore.state_store import StateStore
from loopcore.mission_gate import IntegrationGate
from loopcore.mission_contracts import TaskSpec
from tests.sidecar_port.test_contracts import _task_spec
from tests.test_f04_panel_boundaries import panel, http_panel, request
from tests.test_u02_local_execution import engine
from tests.test_u02_journey import journey, form, until, methods


def git(repo, *args, input=None):
    return subprocess.check_output(['git', '-c', 'core.hooksPath='+os.devnull,
        '-c', 'commit.gpgsign=false', '-C', str(repo), *args], input=input, env=wt._read_env())


def write(repo, files):
    for name, data in files.items():
        p = repo/name
        if data is None:
            p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data.encode('utf-8') if isinstance(data, str) else data)


def archive_task(panel, tmp_path, *, mid='B-RESULT', initial=None, updates=None, state='MISSION_DONE', kind='folder'):
    original = tmp_path / (mid+' 原项目')
    original.mkdir()
    write(original, initial if initial is not None else {'app.py':'x=0\n','old name.txt':'原文件\n','delete.txt':'deleted\n'})
    if kind == 'git':
        git(original,'init','-q');git(original,'config','user.email','test@local');git(original,'config','user.name','Test')
        git(original,'add','.');git(original,'commit','--allow-empty','-qm','original')
        write(original, {'dirty.txt':'用户未提交\n'})
    row = local_projects.register(panel.root, str(original))
    runtime = panel.root/'runtime'/mid
    runtime.mkdir(parents=True)
    source = local_projects.snapshot(row, runtime, local_projects.inspect(row)['revision'])
    repo = runtime/'source'; integ = runtime/'integration'
    git(repo,'worktree','add','--detach',str(integ),source['source_commit'])
    change = updates if updates is not None else {'app.py':'x=2\n','old name.txt':None,'中文 new.txt':'原文件\n','delete.txt':None,'added.txt':'new\n'}
    write(integ,change)
    git(integ,'add','-A');git(integ,'commit','--allow-empty','-qm','worker materialized result')
    head = git(integ,'rev-parse','HEAD').decode().strip()
    store = StateStore(runtime/'state.db')
    mission={'mission_id':mid,'project_id':row['id'],'objective':'检查中文 <tag> " 与结果',
             'acceptance_criteria':[{'id':'AC-1','description':'x equals 2 <script> & "'}]}
    store.record_mission(mid, {'mission':mission,'source':source,'integration_head':head,'merged':['T-1'],
                              'execution_backend':'codex_app_server','state':state,'reason':'stored final reason'})
    verdict='PASS' if state=='MISSION_DONE' else 'FAIL'
    store.record_verification('V-'+mid,mid,{'verify_id':'V-'+mid,'task_id':mid,'verdict':verdict,
        'summary':'已记录的复核 <tag>','ac_checks':[{'ac_id':'AC-1','verdict':verdict,'note':'x tested'}],
        'anti_gaming':[{'ac_id':'AC-1','verdict':verdict}], '_validation':{'raw_prompt':'FULL PRIVATE PROMPT DO NOT EXPORT'}})
    for phase in ('task','final'):
        store.record_gate_run(task_id=mid if phase=='final' else 'T-1', command='python -c "assert 2 == 2"',
            cwd=str(integ), exit_code=0, started_at='start',ended_at='end',stdout='PRIVATE OUTPUT DO NOT EXPORT',stderr='',
            assessment=store.gate_assessment(phase=phase,command='pass',integrity='pass',scope='pass'))
    store.close()
    return SimpleNamespace(mid=mid,runtime=runtime,original=original,repo=repo,integ=integ,base=source['source_commit'],head=head)


def get_result(panel, task):
    status,_,data=request(panel,path='/api/result?mission_id='+task.mid)
    assert status==200,data
    return data['result']


def get_export(panel, task):
    status,_,data=request(panel,'POST','/api/result/export',{'mission_id':task.mid})
    assert status==200,data
    identity=data['export']['identity']
    status,headers,raw=request(panel,path='/api/result/download?mission_id='+task.mid+'&export_id='+identity)
    assert status==200 and headers['Content-Type']=='application/zip',raw
    assert hashlib.sha256(raw).hexdigest()==data['export']['sha256']
    return data['export'],raw


def extracted(raw, destination):
    import zipfile
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert set(z.namelist())=={'changes.patch','manifest.json','evidence.json','README.md'}
        assert z.testzip() is None
        z.extractall(destination)
    return json.loads((destination/'manifest.json').read_text('utf-8'))


def content_matches(repo, entries):
    for entry in entries:
        p=repo/entry['path'];data=p.read_bytes()
        assert hashlib.sha256(data).hexdigest()==entry['sha256'],entry['path']
        assert len(data)==entry['bytes']


@pytest.mark.parametrize('kind', ['folder','git','empty'])
def test_http_export_applies_independently_and_survives_lost_worktrees(http_panel,tmp_path,kind):
    t=archive_task(http_panel,tmp_path,kind=kind,initial={} if kind=='empty' else None,
                   updates={'app.py':'x=2\n','新增 中文.txt':'new\n'} if kind=='empty' else None)
    # Capture an independent baseline BEFORE deleting any private worktree.
    independent=tmp_path/'independent';independent.mkdir()
    before=results.frozen(t.runtime,results.facts(t.runtime,t.mid)[0])
    for e in before['baseline_files']:
        write(independent,{e['path']:git(t.repo,'cat-file','blob',t.base+':'+e['path'])})
    original={p.relative_to(t.original).as_posix():p.read_bytes() for p in t.original.rglob('*') if p.is_file()}
    idx=(t.repo/'.git'/'index').read_bytes();head=git(t.repo,'rev-parse','HEAD')
    # Later staged/unstaged/committed changes must not be exported as accepted output.
    write(t.integ,{'app.py':'x=999\n','untracked.txt':'not accepted'})
    git(t.integ,'add','app.py');git(t.integ,'commit','-qm','after acceptance')
    staged=(Path(git(t.integ,'rev-parse','--path-format=absolute','--git-path','index').decode().strip())).read_bytes()
    detail=get_result(http_panel,t)
    assert detail['status']=='ok' and detail['evidence']['mission']['accepted']
    assert detail['result_commit']==t.head and 'x=999' not in detail['diff']
    if kind!='empty':
        assert {'M','R','D','A'} <= {r['kind'] for r in detail['changes']}
    record,raw=get_export(http_panel,t)
    assert get_export(http_panel,t)==(record,raw)
    assert len(list((t.runtime/'exports').glob('*.zip')))==1
    assert idx==(t.repo/'.git'/'index').read_bytes() and head==git(t.repo,'rev-parse','HEAD')
    assert staged==Path(git(t.integ,'rev-parse','--path-format=absolute','--git-path','index').decode().strip()).read_bytes()
    assert original=={p.relative_to(t.original).as_posix():p.read_bytes() for p in t.original.rglob('*') if p.is_file()}
    # Move only these isolated test directories, making both recorded paths unavailable.
    for src, name in ((t.integ,'unavailable-integration'),(t.repo,'unavailable-source')):
        dest=tmp_path/name
        assert src.resolve().is_relative_to(tmp_path.resolve()) and dest.resolve().is_relative_to(tmp_path.resolve())
        src.rename(dest)
    detail=get_result(http_panel,t)
    assert detail['location']['status']=='missing' and detail['exports'][0]['status']=='ready'
    assert detail['status']=='saved' and 'x=999' not in detail['diff']
    again=request(http_panel,path='/api/result/download?mission_id='+t.mid+'&export_id='+record['identity'])
    assert again[0]==200 and again[2]==raw
    package=tmp_path/'result-package';manifest=extracted(raw,package)
    content_matches(independent,manifest['baseline_files'])
    git(independent,'-c','core.autocrlf=false','apply','--check',str(package/'changes.patch'))
    git(independent,'-c','core.autocrlf=false','apply','--whitespace=nowarn',str(package/'changes.patch'))
    content_matches(independent,manifest['result_files'])
    assert {p.relative_to(independent).as_posix() for p in independent.rglob('*') if p.is_file()}=={e['path'] for e in manifest['result_files']}
    subprocess.run([os.sys.executable,'-c','import runpy; assert runpy.run_path("app.py")["x"]==2'],cwd=independent,check=True)
    summary=(package/'evidence.json').read_text('utf-8')
    assert 'PRIVATE OUTPUT' not in summary and 'FULL PRIVATE PROMPT' not in summary and str(t.runtime) not in summary
    assert '无需也不能要求原仓库 checkout' in (package/'README.md').read_text('utf-8')


def test_formal_mission_controller_gate_verifier_to_export(journey,tmp_path):
    body=form(journey,tmp_path/'真实项目')
    response=request(journey,'POST','/api/mission',body)
    assert response[0]==200,response
    data=until(journey,lambda d:(d.get('mission') or {}).get('state') in server.MISSION_TERMINAL)
    assert data['mission']['state']=='MISSION_DONE',data
    rt=journey.state.rt;t=SimpleNamespace(mid=rt.mission.mission_id)
    calls=methods(journey);verifies=journey.engine.verifier.verify.call_count
    detail=get_result(journey,t)
    assert detail['evidence']['acceptance_criteria'][0]['verdict']=='PASS'
    assert {r['phase'] for r in detail['evidence']['gates']['records']} >= {'task','final'}
    record,raw=get_export(journey,t)
    package=tmp_path/'bundle';manifest=extracted(raw,package)
    independent=tmp_path/'independent';shutil.copytree(tmp_path/'真实项目',independent)
    content_matches(independent,manifest['baseline_files'])
    git(independent,'apply',str(package/'changes.patch'))
    content_matches(independent,manifest['result_files'])
    # Run the real deterministic Gate on the independently applied copy in an isolated repository.
    git(independent,'init','-q');git(independent,'config','user.name','Test');git(independent,'config','user.email','test@local')
    git(independent,'add','.');git(independent,'commit','-qm','applied')
    store=StateStore(tmp_path/'apply-check.db')
    spec=_task_spec();spec['gate_commands']=body['gate_commands'].splitlines()
    run=IntegrationGate(store).run(TaskSpec.from_dict(spec),str(independent),phase='final')
    assert run.ok;store.close()
    assert (tmp_path/'真实项目'/'app.py').read_text()=='x=0\n'
    assert methods(journey)==calls and journey.engine.verifier.verify.call_count==verifies


@pytest.mark.parametrize('state',['FAILED','CANCELLED','HUMAN','CANCELLING'])
def test_partial_frozen_results_are_not_accepted_or_materialized(http_panel,tmp_path,state):
    t=archive_task(http_panel,tmp_path,state=state)
    store=StateStore(t.runtime/'state.db');store.record_mission(t.mid,{'worker_stop':{'status':'UNKNOWN'}});store.close()
    before=git(t.integ,'rev-parse','HEAD')
    detail=get_result(http_panel,t);record,raw=get_export(http_panel,t)
    assert not detail['evidence']['mission']['accepted'] and not record['accepted']
    package=tmp_path/'package';extracted(raw,package)
    assert '未通过最终验收' in (package/'README.md').read_text('utf-8')
    assert git(t.integ,'rev-parse','HEAD')==before


def test_missing_not_produced_query_errors_and_historical_unknown(http_panel,tmp_path):
    t=archive_task(http_panel,tmp_path)
    store=StateStore(t.runtime/'state.db')
    store._conn.execute('DELETE FROM verifications');store._conn.execute('DELETE FROM gate_runs');store._conn.commit()
    detail=get_result(http_panel,t)
    assert detail['evidence']['verifier']['status']=='no_records'
    assert detail['evidence']['acceptance_criteria'][0]['verdict']=='unknown'
    assert detail['evidence']['gates']['status']=='no_records'
    store._conn.execute('DROP TABLE gate_runs');store._conn.execute('DROP TABLE verifications');store._conn.commit()
    detail=get_result(http_panel,t)
    assert detail['evidence']['gates']['status']==detail['evidence']['verifier']['status']=='read_error'
    store.record_mission(t.mid,{'source':{},'integration_head':None,'merged':[]})
    assert get_result(http_panel,t)['status']=='not_produced'
    assert request(http_panel,'POST','/api/result/export',{'mission_id':t.mid})[0]!=200
    store.record_mission(t.mid,{'merged':['old'],'integration_head':t.head})
    assert get_result(http_panel,t)['status']=='historical_missing'
    store.close()


@pytest.mark.parametrize('updates,initial,expected',[
    ({'blob.bin':b'\0binary'},None,'unsupported'),
    ({'large.dat':'version https://git-lfs.github.com/spec/v1\noid sha256:'+'a'*64+'\nsize 999\n'},None,'unsupported'),
    ({'auth.json':'{}'},None,'restricted'),
    ({'__pycache__/a.pyc':b'cache'},None,'restricted'),
    ({'code.txt':'safe\n'},{'code.txt':'token="sk-abcdefghijklmnopqrstuvwxyz123456"\n'},'restricted'),
    ({'code.txt':None},{'code.txt':'-----BEGIN PRIVATE KEY-----\nprivate\n'},'restricted'),
    ({'code.txt':'Bearer abcdefghijklmnop\n'},None,'restricted'),
    ({'code.txt':'password="short"\n'},None,'restricted'),
])
def test_restricted_old_new_context_or_binary_rejects_whole_package(http_panel,tmp_path,updates,initial,expected):
    t=archive_task(http_panel,tmp_path,initial=initial,updates=updates)
    detail=get_result(http_panel,t)
    assert detail['status']==expected and detail['changes']
    response=request(http_panel,'POST','/api/result/export',{'mission_id':t.mid})
    assert response[0]!=200,response
    assert not (t.runtime/'exports').exists()


def test_lookalikes_full_patch_copy_and_modes(http_panel,tmp_path):
    t=archive_task(http_panel,tmp_path,initial={'copy.txt':'same\n'},updates={'copy2.txt':'same\n','data.pyconfig':'normal\n','.coverage_policy.py':'source\n','long.txt':'\n'.join('line '+str(i) for i in range(20000))})
    git(t.integ,'update-index','--chmod=+x','copy2.txt');git(t.integ,'commit','-qm','mode')
    store=StateStore(t.runtime/'state.db');store.record_mission(t.mid,{'integration_head':git(t.integ,'rev-parse','HEAD').decode().strip()});store.close()
    detail=get_result(http_panel,t)
    assert detail['diff_truncated'] and len(detail['diff'])<=results.DISPLAY_LIMIT
    assert any(r['kind']=='C' and r['old_path']=='copy.txt' and r['path']=='copy2.txt' for r in detail['changes'])
    _,raw=get_export(http_panel,t);package=tmp_path/'package';m=extracted(raw,package)
    assert (package/'changes.patch').stat().st_size==detail['diff_bytes']
    assert b'line 19999' in (package/'changes.patch').read_bytes()
    assert next(e for e in m['result_files'] if e['path']=='copy2.txt')['mode']=='100755'
    independent=tmp_path/'copy-application';independent.mkdir()
    write(independent,{'copy.txt':'same\n'})
    git(independent,'init','-q');git(independent,'config','core.autocrlf','false')
    git(independent,'config','user.name','Test');git(independent,'config','user.email','test@local')
    git(independent,'add','.');git(independent,'commit','-qm','independent matching baseline')
    git(independent,'apply','--index',str(package/'changes.patch'))
    content_matches(independent,m['result_files'])
    assert git(independent,'ls-files','--stage','copy2.txt').startswith(b'100755 ')


def test_failure_atomicity_and_concurrent_dedup(http_panel,tmp_path,monkeypatch):
    t=archive_task(http_panel,tmp_path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        exported=list(pool.map(lambda _:get_export(http_panel,t),range(3)))
    assert all(item==exported[0] for item in exported)
    old,raw=exported[0]
    store=StateStore(t.runtime/'state.db');store.record_mission(t.mid,{'reason':'later evidence'});store.close()
    monkeypatch.setattr(results.os,'replace',lambda *a:(_ for _ in ()).throw(OSError('injected disk failure')))
    response=request(http_panel,'POST','/api/result/export',{'mission_id':t.mid})
    assert response[0]!=200 and 'disk failure' in response[2]['error']
    assert not list((t.runtime/'exports').glob('*.partial'))
    assert request(http_panel,path='/api/result/download?mission_id='+t.mid+'&export_id='+old['identity'])[2]==raw
    assert len(get_result(http_panel,t)['exports'])==1


@pytest.mark.parametrize('endpoint',['/api/result/export','/api/result/open'])
@pytest.mark.parametrize('headers',[{'Host':'evil.test'},{'Origin':'http://evil.test'},{'X-Panel-Nonce':None},{'X-Panel-Nonce':'bad'},{'Content-Type':'text/plain'}])
def test_result_write_boundary_has_no_side_effect(http_panel,tmp_path,monkeypatch,endpoint,headers):
    t=archive_task(http_panel,tmp_path);opened=[]
    monkeypatch.setattr(server.os,'startfile',lambda *a:opened.append(a),raising=False)
    assert request(http_panel,'POST',endpoint,{'mission_id':t.mid},headers=headers)[0] in (403,415)
    assert not opened and not (t.runtime/'exports').exists()


def test_result_operations_are_bound_to_history_b_not_active_a(http_panel,tmp_path,monkeypatch):
    t=archive_task(http_panel,tmp_path);rt=http_panel.state.rt
    active_before=http_panel.store.mission_config('M-F04');opened=[]
    monkeypatch.setattr(server.os,'startfile',lambda *args:opened.append(args),raising=False)
    assert request(http_panel,'POST','/api/result/open',{'mission_id':t.mid})[0]==200
    assert opened==[(str(t.integ),'explore')]
    record,raw=get_export(http_panel,t)
    assert request(http_panel,path='/api/result/download?mission_id=M-F04&export_id='+record['identity'])[0]==400
    for mid in ('../B-RESULT','C:\\Windows','%2e%2e','%252e%252e','B-RESULT/..'):
        assert request(http_panel,'POST','/api/result/open',{'mission_id':mid})[0]==400
    for query in ('mission_id=%ZZ','mission_id=%ff','mission_id=..','mission_id=B-RESULT&path=C:/Windows'):
        assert request(http_panel,path='/api/result?'+query)[0]==400
    assert request(http_panel,'POST','/api/result/open',{'mission_id':t.mid,'path':'C:/Windows'})[0]==400
    assert http_panel.state.rt is rt and http_panel.store.mission_config('M-F04')==active_before
    monkeypatch.setattr(server.os,'startfile',lambda *a:(_ for _ in ()).throw(OSError('shell rejected')))
    response=request(http_panel,'POST','/api/result/open',{'mission_id':t.mid})
    assert response[0]!=200 and 'shell rejected' in response[2]['error']


def test_actual_browser_result_center_and_mission_ownership(http_panel,tmp_path,monkeypatch):
    t=archive_task(http_panel,tmp_path)
    output=Path(os.environ.get('U03_SCREENSHOTS',str(tmp_path/'shots')))
    script=Path(__file__).resolve().parents[2]/'dev'/'panel'/'u03-results.cjs'
    opened=[];monkeypatch.setattr(server.os,'startfile',lambda *a:opened.append(a),raising=False)
    result=subprocess.run([os.environ['U01_NODE'],str(script),http_panel.origin,t.mid,str(output)],
        capture_output=True,encoding='utf-8',errors='replace',timeout=100)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert opened==[(str(t.integ),'explore')]
    assert http_panel.state.rt.mission.mission_id=='M-F04'
    print(result.stdout)


def test_empty_patch_is_explicit_not_a_git_failure(http_panel,tmp_path,monkeypatch):
    t=archive_task(http_panel,tmp_path,initial={},updates={})
    detail=get_result(http_panel,t)
    assert detail['status']=='ok' and detail['no_changes'] and detail['diff_bytes']==0
    _,raw=get_export(http_panel,t);package=tmp_path/'package';m=extracted(raw,package)
    assert m['no_changes'] and (package/'changes.patch').read_bytes()==b''
    original=results._git
    def fail(repo,*args,**kw):
        if 'diff' in args:raise results.ResultError('injected Git read failure','read_error')
        return original(repo,*args,**kw)
    monkeypatch.setattr(results,'_git',fail)
    # Existing saved package stays readable; generating from a failed Git probe is refused.
    assert get_result(http_panel,t)['status']=='saved'
    assert request(http_panel,'POST','/api/result/export',{'mission_id':t.mid})[0]!=200


@pytest.mark.parametrize('mode',['120000','160000'])
def test_special_git_types_are_explicitly_rejected(http_panel,tmp_path,mode):
    t=archive_task(http_panel,tmp_path)
    oid=t.base if mode=='160000' else git(t.repo,'hash-object','-w','--stdin',input=b'../outside').decode().strip()
    git(t.integ,'update-index','--add','--cacheinfo',mode,oid,'special')
    tree=git(t.integ,'write-tree').decode().strip()
    head=git(t.integ,'commit-tree',tree,'-p',t.head,'-m','special').decode().strip()
    store=StateStore(t.runtime/'state.db');store.record_mission(t.mid,{'integration_head':head});store.close()
    assert get_result(http_panel,t)['status']=='unsupported'
    assert request(http_panel,'POST','/api/result/export',{'mission_id':t.mid})[0]!=200


def test_probe_failure_and_sensitive_summary_leave_index_and_old_package_unchanged(http_panel,tmp_path,monkeypatch):
    t=archive_task(http_panel,tmp_path)
    record,raw=get_export(http_panel,t)
    index=Path(git(t.integ,'rev-parse','--path-format=absolute','--git-path','index').decode().strip())
    before=index.read_bytes();snapshot=wt.git_state_snapshot(str(t.integ))
    store=StateStore(t.runtime/'state.db')
    store.record_mission(t.mid,{'reason':'Authorization: Bearer abcdefghijklmnopqrstuvwxyz'})
    store.close()
    response=request(http_panel,'POST','/api/result/export',{'mission_id':t.mid})
    assert response[0]!=200 and '凭据' in response[2]['error']
    assert 'abcdefghijkl' not in response[2]['error']
    assert index.read_bytes()==before and wt.git_state_snapshot(str(t.integ))==snapshot
    assert request(http_panel,path='/api/result/download?mission_id='+t.mid+'&export_id='+record['identity'])[2]==raw
    monkeypatch.setattr(results,'_git',lambda *a,**kw:(_ for _ in ()).throw(results.ResultError('probe failed','read_error')))
    assert request(http_panel,'POST','/api/result/export',{'mission_id':t.mid})[0]!=200
    assert index.read_bytes()==before


def test_export_path_junction_cannot_open_or_download_outside(http_panel,tmp_path,monkeypatch):
    t=archive_task(http_panel,tmp_path)
    record,raw=get_export(http_panel,t)
    destination=tmp_path/'outside';destination.mkdir()
    t.integ.rename(tmp_path/'held-integration')
    # Native junction in this isolated runtime, not a symlink requiring elevation.
    subprocess.run(['cmd','/c','mklink','/J',str(t.integ),str(destination)],check=True,capture_output=True)
    opened=[];monkeypatch.setattr(server.os,'startfile',lambda *a:opened.append(a),raising=False)
    try:
        assert request(http_panel,'POST','/api/result/open',{'mission_id':t.mid})[0]!=200
        assert request(http_panel,'POST','/api/result/export',{'mission_id':t.mid})[0]!=200
        assert not opened and not list(destination.iterdir())
        detail=get_result(http_panel,t)
        assert detail['location']['status']=='read_error' and detail['exports'][0]['status']=='ready'
        assert request(http_panel,path='/api/result/download?mission_id='+t.mid+'&export_id='+record['identity'])[2]==raw
    finally:
        os.rmdir(t.integ)


def test_historical_ao_fixed_results_are_read_without_ao(http_panel,tmp_path,monkeypatch):
    t=archive_task(http_panel,tmp_path)
    store=StateStore(t.runtime/'state.db');store.record_mission(t.mid,{'execution_backend':'ao'});store.close()
    monkeypatch.setattr(server,'AOAdapter',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('no AO for results')))
    detail=get_result(http_panel,t)
    assert detail['status']=='ok' and 'FULL PRIVATE PROMPT' not in json.dumps(detail)
    assert get_export(http_panel,t)[0]['accepted']


@pytest.mark.parametrize('payload',[[],{'mission':{'mission_id':'B-RESULT','acceptance_criteria':{}}}])
def test_malformed_saved_facts_remain_read_error(http_panel,tmp_path,payload):
    t=archive_task(http_panel,tmp_path)
    store=StateStore(t.runtime/'state.db')
    store._conn.execute('UPDATE missions SET payload_json=? WHERE mission_id=?',(json.dumps(payload),t.mid));store._conn.commit();store.close()
    response=request(http_panel,path='/api/result?mission_id='+t.mid)
    assert response[0]==500 and response[2]['status']=='read_error'


def test_preexisting_artifact_is_neither_exported_nor_deleted(http_panel,tmp_path):
    t=archive_task(http_panel,tmp_path)
    artifact={'__pycache__/baseline.pyc':b'\0existing cache'}
    write(t.repo,artifact);git(t.repo,'add','-f','__pycache__/baseline.pyc');git(t.repo,'commit','-qm','baseline artifact')
    write(t.integ,artifact);git(t.integ,'add','-f','__pycache__/baseline.pyc');git(t.integ,'commit','-qm','same baseline artifact')
    store=StateStore(t.runtime/'state.db');payload=store.mission_config(t.mid)
    payload['source']['source_commit']=git(t.repo,'rev-parse','HEAD').decode().strip()
    store.record_mission(t.mid,{'source':payload['source'],'integration_head':git(t.integ,'rev-parse','HEAD').decode().strip()});store.close()
    _,raw=get_export(http_panel,t);package=tmp_path/'package';m=extracted(raw,package)
    patch=(package/'changes.patch').read_bytes()
    assert b'__pycache__' not in patch and all('__pycache__' not in e['path'] for e in m['baseline_files']+m['result_files'])
    independent=tmp_path/'independent';independent.mkdir()
    for e in m['baseline_files']:
        write(independent,{e['path']:git(t.repo,'cat-file','blob',m['base_commit']+':'+e['path'])})
    write(independent,artifact);git(independent,'-c','core.autocrlf=false','apply',str(package/'changes.patch'))
    content_matches(independent,m['result_files'])
    assert (independent/'__pycache__'/'baseline.pyc').read_bytes()==artifact['__pycache__/baseline.pyc']


def test_corrupt_package_metadata_is_not_successful_empty_history(http_panel,tmp_path):
    t=archive_task(http_panel,tmp_path);get_export(http_panel,t)
    store=StateStore(t.runtime/'state.db')
    store._conn.execute("UPDATE result_exports SET payload_json='{}'");store._conn.commit();store.close()
    response=request(http_panel,path='/api/result?mission_id='+t.mid)
    assert response[0]==500 and response[2]['status']=='read_error'
