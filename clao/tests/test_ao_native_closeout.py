"""Integrated native journeys; only external executable boundaries are replaced."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
import zipfile

import pytest
from tests.test_ao_native import native, native_engine, native_core_python, git


def wait_mission(api, ident):
    for _ in range(500):
        status, value = api('/api/v1/clao/missions/' + ident)
        assert status == 200, value
        m = value['mission']
        if m['state'] in {'DONE', 'FAILED', 'HUMAN', 'UNKNOWN', 'PAUSED', 'CANCELLED'}:
            return m
        time.sleep(.12)
    pytest.fail(json.dumps(m, ensure_ascii=False))


def create_local(api, nonce, path, name='独立项目'):
    status, out = api('/api/v1/clao/projects', {'path': str(path), 'name': name, 'create': True}, {'X-CLAO-Nonce': nonce})
    assert status == 201, out
    return out['project']['id']


def spec(api, project, ident, parallel=False):
    status, source = api(f'/api/v1/clao/projects/{project}/source')
    assert status == 200, source
    return {'id': ident, 'projectId': project, 'sourceRevision': source['source']['revision'],
            'objective': 'Independent parallel outputs' if parallel else 'Create result.txt containing accepted',
            'agent': 'opencode', 'model': 'test/native', 'allowedPaths': ['left.txt', 'right.txt'] if parallel else ['result.txt'],
            'forbiddenPaths': ['private/**'], 'criteria': ([{'id': 'AC1', 'description': 'left.txt accepted'}, {'id': 'AC2', 'description': 'right.txt accepted'}]
                                                        if parallel else [{'id': 'AC1', 'description': 'result.txt accepted'}]),
            'gateCommands': ['python check.py left.txt', 'python check.py right.txt'] if parallel else ['python check.py result.txt'],
            'maxTasks': 2 if parallel else 1, 'maxRepairs': 0, 'maxReplans': 0, 'gateTimeout': 10}


def check_source(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'check.py').write_text("import sys\nfrom pathlib import Path\nassert Path(sys.argv[1]).read_text() == 'accepted\\n'\n", encoding='utf-8')
    (folder/'原有 文本.txt').write_text('原始用户内容\n', encoding='utf-8')


@pytest.mark.parametrize('source_kind', ['plain', 'dirty_git', 'empty'])
def test_native_private_source_complete_export(native, source_kind):
    _, api, nonce, _, _, temp = native
    original=temp/('本地 '+source_kind)
    check_source(original)
    index=None
    if source_kind=='dirty_git':
        git(original,'init','-b','user-branch');git(original,'config','user.email','fixture@example.invalid');git(original,'config','user.name','Fixture')
        git(original,'add','.');git(original,'commit','-m','user base')
        (original/'原有 文本.txt').write_text('用户未提交版本\n',encoding='utf-8')
        (original/'staged.txt').write_text('staged user\n',encoding='utf-8');git(original,'add','staged.txt')
        index=(original/'.git/index').read_bytes()
        status_before=git(original,'status','--porcelain')
    if source_kind=='empty':
        for child in original.iterdir(): child.unlink()
    before={p.name:p.read_bytes() for p in original.iterdir() if p.is_file()}
    pid=create_local(api,nonce,original)
    request=spec(api,pid,'closeout-'+source_kind)
    if source_kind=='empty':request['gateCommands']=['python -c "from pathlib import Path; assert Path(\'result.txt\').read_text()==\'accepted\\n\'"']
    status, out=api('/api/v1/clao/missions',request,{'X-CLAO-Nonce':nonce});assert status==202,out
    m=wait_mission(api,request['id']);assert m['state']=='DONE',m
    assert m['source']['originalPath']==str(original)
    assert Path(m['workspace'])!=original
    assert {p.name:p.read_bytes() for p in original.iterdir() if p.is_file()}==before
    if index is not None:
        assert (original/'.git/index').read_bytes()==index
        assert git(original,'status','--porcelain')==status_before
        assert git(original,'branch','--show-current')=='user-branch'
    else: assert not (original/'.git').exists()
    assert m['evidence'][-1]['verification']['verdict']=='PASS'
    status,view=api('/api/v1/clao/missions/'+m['request']['id']+'/result');assert status==200,view
    assert 'result.txt' in view['result']['diff']
    status,export=api('/api/v1/clao/missions/'+m['request']['id']+'/export',{}, {'X-CLAO-Nonce':nonce});assert status==200,export
    package=export['package']
    assert api('/api/v1/clao/missions/'+m['request']['id']+'/export',{}, {'X-CLAO-Nonce':nonce})[1]['package']['identity']==package['identity']
    saved=temp/'isolated-home/native/data/clao/missions'/m['request']['id']/'exports'/(package['identity']+'.zip')
    # Request actual served bytes over the daemon's regular protected read API.
    url=f'{api.base_url}/api/v1/clao/missions/{m["request"]["id"]}/exports/{package["identity"]}'
    blob=urllib.request.urlopen(url).read();assert blob==saved.read_bytes()
    independent=temp/'independent baseline';independent.mkdir()
    archive=subprocess.check_output(['git','-C',m['source']['projectPath'],'archive','--format=zip',m['base']])
    with zipfile.ZipFile(io.BytesIO(archive)) as baseline_zip:baseline_zip.extractall(independent)
    unpack=temp/'unpacked';unpack.mkdir()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        assert all('.git' not in Path(n).parts for n in z.namelist());z.extractall(unpack)
    patch=next(unpack.rglob('*.patch'))
    subprocess.run(['git','apply','--check',str(patch)],cwd=independent,check=True)
    subprocess.run(['git','apply',str(patch)],cwd=independent,check=True)
    assert (independent/'result.txt').read_text()=='accepted\n'
    for name,data in before.items():assert (independent/name).read_bytes()==data
    if source_kind!='empty':subprocess.run([__import__('sys').executable,'check.py','result.txt'],cwd=independent,check=True)
    # Only this isolated test's temporary integration is made unavailable.
    workspace=Path(m['workspace']);workspace.rename(workspace.with_name(workspace.name+'-unavailable'))
    assert urllib.request.urlopen(url).read()==blob
    status,view=api('/api/v1/clao/missions/'+m['request']['id']+'/result');assert status==200,view
    assert view['result']['location']['status']!='available'


def test_native_two_independent_workers_final_acceptance(native):
    _,api,nonce,_,_,temp=native
    original=temp/'two outputs';check_source(original)
    pid=create_local(api,nonce,original)
    request=spec(api,pid,'closeout-parallel',True)
    status,out=api('/api/v1/clao/missions',request,{'X-CLAO-Nonce':nonce});assert status==202,out
    m=wait_mission(api,request['id']);assert m['state']=='DONE',m
    assert len(m['subtasks'])==2
    assert len({s['sessionId'] for s in m['subtasks']})==2
    assert all(s['state']=='DONE' and not s.get('verifierSessionId') for s in m['subtasks'])
    assert [r['role'] for r in m['roleCalls']]==['planner','verifier']
    for name in ('left.txt','right.txt'):
        assert (Path(m['workspace'])/name).read_text()=='accepted\n'
        assert not (original/name).exists()
    assert m['evidence'][-1]['verification']['verdict']=='PASS'
    assert len(m['evidence'][-1]['verification']['ac_checks'])==2
    assert api('/api/v1/clao/missions/'+m['subtasks'][0]['request']['id']+'/continue',{}, {'X-CLAO-Nonce':nonce})[0]==409


def test_native_changed_source_and_dependency_rejected(native):
    _,api,nonce,_,_,temp=native
    original=temp/'source changes';check_source(original)
    pid=create_local(api,nonce,original)
    request=spec(api,pid,'closeout-stale',True)
    (original/'unconfirmed.txt').write_text('new content')
    assert api('/api/v1/clao/missions',request,{'X-CLAO-Nonce':nonce})[0]==400
    request=spec(api,pid,'closeout-dependency',True);request['objective']='DEPENDENT_PLAN'
    status,out=api('/api/v1/clao/missions',request,{'X-CLAO-Nonce':nonce});assert status==202,out
    m=wait_mission(api,request['id']);assert m['state']=='HUMAN',m
    assert 'dependent plan' in m['reason']
    assert not m.get('subtasks') and not m.get('sessionId')


def test_child_success_does_not_export_mission_acceptance(native):
    _,api,nonce,_,_,temp=native
    original=temp/'partial success';check_source(original)
    pid=create_local(api,nonce,original)
    request=spec(api,pid,'closeout-final-fail',True);request['objective']='FINAL_REVIEW_FAIL'
    assert api('/api/v1/clao/missions',request,{'X-CLAO-Nonce':nonce})[0]==202
    mission=wait_mission(api,request['id'])
    assert mission['state']!='DONE' and mission.get('resultHead'),mission
    assert all(child['state']=='DONE' for child in mission['subtasks']),mission
    for child in mission['subtasks']:
        url='/api/v1/clao/missions/'+child['request']['id']
        status,result=api(url+'/result');assert status==200,result
        assert result['result']['evidence']['mission']['accepted'] is False
        assert result['result']['evidence']['mission']['acceptanceLevel']=='subtask'
        status,refusal=api(url+'/export',{}, {'X-CLAO-Nonce':nonce})
        assert status==409 and 'Mission' in json.dumps(refusal),refusal
    status,export=api('/api/v1/clao/missions/'+request['id']+'/export',{}, {'X-CLAO-Nonce':nonce})
    assert status==200 and export['package']['accepted'] is False,export
    data=urllib.request.urlopen(api.base_url+'/api/v1/clao/missions/'+request['id']+'/exports/'+export['package']['identity']).read()
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        assert json.loads(package.read('manifest.json'))['accepted'] is False
        assert '未通过最终验收' in package.read('README.md').decode('utf-8')


def test_native_two_workers_restart_reuses_confirmed_progress(native):
    from tests.test_ao_native_recovery import fault, clear_fault, trace
    from concurrent.futures import ThreadPoolExecutor
    _,api,nonce,_,_,temp=native
    original=temp/'resume both';check_source(original)
    pid=create_local(api,nonce,original)
    request=spec(api,pid,'closeout-continue-pair',True);request['maxRepairs']=1
    # Fail only the local checkpoint write after a real Worker has stopped.
    fault(temp,"json_extract(OLD.document,'$.subtasks[0].checkpoint.stage')='worker' AND json_extract(NEW.document,'$.subtasks[0].checkpoint.stage')='gate'")
    assert api('/api/v1/clao/missions',request,{'X-CLAO-Nonce':nonce})[0]==202
    first=wait_mission(api,request['id'])
    assert first['state'] in {'PAUSED','UNKNOWN'},first
    ids=[s['sessionId'] for s in first['subtasks']];before=trace(temp)
    clear_fault(temp)
    nonce=api.restart()
    restored=api('/api/v1/clao/missions/'+request['id'])[1]['mission']
    assert restored['recovery']['canContinue'],restored
    assert [s['sessionId'] for s in restored['subtasks']]==ids
    assert len(trace(temp))==len(before)
    with ThreadPoolExecutor(2) as pool:
        answers=list(pool.map(lambda _: api('/api/v1/clao/missions/'+request['id']+'/continue',{}, {'X-CLAO-Nonce':nonce}),range(2)))
    assert all(status==202 for status,_ in answers),answers
    final=wait_mission(api,request['id']);assert final['state']=='DONE',final
    assert final['request']==first['request'] and final['roles']==first['roles']
    assert final['repairs']==first['repairs']==0
    assert [s['sessionId'] for s in final['subtasks']]==ids
    assert all(sum(op['kind']=='spawn' for op in s['operations'])==1 for s in final['subtasks'])
    assert sum(c['role']=='planner' for c in final['roleCalls'])==1


def test_native_two_workers_cancel_and_shared_budget(native):
    _,api,nonce,_,_,temp=native
    original=temp/'limited pair';check_source(original)
    pid=create_local(api,nonce,original)
    request=spec(api,pid,'closeout-cancel-pair',True);request['objective']='PARALLEL_HOLD'
    assert api('/api/v1/clao/missions',request,{'X-CLAO-Nonce':nonce})[0]==202
    for _ in range(200):
        live=api('/api/v1/clao/missions/'+request['id'])[1]['mission']
        if len(live.get('subtasks',[]))==2 and all(s.get('sessionId') for s in live['subtasks']):break
        time.sleep(.1)
    assert all(s.get('sessionId') for s in live['subtasks']),live
    cancel='/api/v1/clao/missions/'+request['id']+'/cancel'
    assert api(cancel,{}, {'X-CLAO-Nonce':nonce})[0]==202
    assert api(cancel,{}, {'X-CLAO-Nonce':nonce})[0]==202
    for _ in range(200):
        stopped=api('/api/v1/clao/missions/'+request['id'])[1]['mission']
        if stopped['state']=='CANCELLED':break
        time.sleep(.1)
    assert stopped['state']=='CANCELLED' and not stopped.get('resultHead'),stopped
    assert all(s['state']=='CANCELLED' for s in stopped['subtasks']),stopped
    # A new pair is allowed after confirmed stop; one shared repair allowance.
    request=spec(api,pid,'closeout-budget-pair',True)
    request.update(objective='PARALLEL_REPAIR',maxRepairs=1)
    assert api('/api/v1/clao/missions',request,{'X-CLAO-Nonce':nonce})[0]==202
    limited=wait_mission(api,request['id'])
    assert limited['state']!='DONE' and not limited.get('resultHead'),limited
    assert limited['repairs']==sum(s['repairs'] for s in limited['subtasks'])==1,limited
    assert sum(op['kind']=='repair_send' for s in limited['subtasks'] for op in s['operations'])==1,limited
    assert api('/api/v1/clao/missions/'+request['id']+'/cancel',{}, {'X-CLAO-Nonce':nonce})[0]==202
