"""AO v0.12.12 native mappings; external commands only use isolated substitutes."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from types import SimpleNamespace

import pytest
import run_mission
from loopcore import native_catalog, native_auth, native_terminal
from loopcore.effective_config import resolve_config, restore_snapshot, ConfigError
from loopcore.model_profiles import AO_EXECUTORS, TERMINAL_SERVICES, CODEX_ACCOUNT, CLAUDE_ACCOUNT
from loopcore.local_projects import register, inspect
from loopcore.state_store import StateStore
from tests.test_m4_connections import modern, vaults, native, engine, settings
from tests.test_f04_panel_boundaries import panel, http_panel, request
from tests.test_u02_local_execution import engine
from tests.test_u02_journey import journey, form


OUTPUTS = {
 'aider':'  anthropic/model-one\n  openai/model-two\n', 'opencode':'anthropic/model-one\nopenai/model-two\n',
 'grok':'Available models:\n  grok-one - Grok One (default)\n  grok-two - Grok Two\n',
 'cursor':'Available models\nmodel-one - Model One (default)\nmodel-two - Model Two\nTip: ignored\n',
 'agy':'model-one Model One\nmodel-two Model Two\n', 'kilocode':'anthropic/model-one\nopenai/model-two\n',
 'pi':'provider model context\nanthropic model-one 1M\nopenai model-two 1M\n',
 'kimchi':'provider model context\nkimchi-dev model-one 1M\nkimchi-dev/anthropic model-two 1M\n',
 'prime-agent':'provider model context\nprime model-one 1M\nprime model-two 1M\n',
 'kimi':json.dumps({'models':{'kimi-code/one':{'provider':'managed:kimi-code','model':'one','displayName':'Kimi One'},'kimi-code/two':{'provider':'managed:kimi-code','model':'two'}}}),
 'auggie':json.dumps({'models':[{'id':'one','displayName':'One'},{'id':'two','displayName':'Two'}]}),
 'devin':json.dumps({'families':[{'slug':'one','variants':[{'model_uid':'two','label':'Two'}]}]}),
 'kiro':json.dumps({'models':[{'model_name':'Auto','model_id':'auto'},{'model_name':'One','model_id':'one'}]}),
 'omp':json.dumps({'models':[{'selector':'anthropic/one','name':'One','provider':'anthropic'},{'selector':'openai/two','name':'Two'}]}),
 'copilot':'`model`: AI model to use.\n - "one"\n - "two"\n`contextTier`: ignored\n - ignored\n',
 'droid':'Available Models:\n  one One (default)\n  two Two\n\nTool Controls:\n --list-tools List tools\n',
 'crush':'anthropic/one\nopenai/two\n',
}
CONFIGS = {
 'qwen':{'modelProviders':{'openai':[{'id':'one','name':'One'},{'id':'two','name':'Two'}]},'model':{'name':'one'}},
 'continue':{'models':[{'model':'one','name':'One','provider':'openai'},{'model':'two','name':'Two','provider':'anthropic'}],'defaults':{'chat':'One'}},
 'goose':{'active_provider':'openai','providers':{'openai':{'model':'one','models':['one','two']},'ignored':{'model':'outside'}}},
 'vibe':{'active_model':'one','models':[{'alias':'one','name':'actual-one','provider':'mistral'},{'alias':'two','name':'actual-two'}]},
 'cline':{'lastUsedProvider':'one','providers':{'one':{'apiModelId':'one','apiKey':'test-never-return'},'two':{'model':'two'}}},
 'autohand':{'provider':'openrouter','openrouter':{'model':'provider/one','apiKey':'test-never-return'}},
}


def terminal_profile(executor, model=''):
    service=next((s for s,e in TERMINAL_SERVICES.items() if e==executor),
                 CODEX_ACCOUNT if executor=='codex' else CLAUDE_ACCOUNT)
    return modern(service,model,credential_ref='native')


@pytest.mark.parametrize('executor', AO_EXECUTORS)
def test_native_model_selection_reaches_documented_launch(executor,tmp_path,monkeypatch):
    workspace=tmp_path/'中文 space';workspace.mkdir()
    model='medium' if executor=='amp' else 'provider/model-one'
    monkeypatch.setenv('UNRELATED_SECRET','test-secret-never-forward')
    argv,env=native_terminal.launch_command(executor,model,workspace,tmp_path/'settings',binary=executor+'.exe')
    assert argv[0]==executor+'.exe' and 'UNRELATED_SECRET' not in env
    assert not {'--yolo','--dangerously-skip-permissions','--trust-all-tools','--full-auto','--trust'} & set(argv)
    if executor=='amp':assert argv[1:]==['--mode','medium']
    elif executor=='droid':assert json.loads(Path(argv[argv.index('--settings')+1]).read_text())=={'model':model}
    elif executor=='kilocode':assert json.loads(env['KILO_CONFIG_CONTENT'])['agent']['clao-selection']['model']==model
    elif executor=='vibe':
        import tomllib
        assert tomllib.loads((tmp_path/'settings/.vibe/agents/clao-selection.toml').read_text())['active_model']==model
    elif executor=='kiro':assert json.loads(next((workspace/'.kiro/agents').glob('*.json')).read_text())['model']==model
    elif executor=='crush':assert json.loads((workspace/'.crush.json').read_text())['models']['large']=={'provider':'provider','model':'model-one'}
    else:assert argv[argv.index('--model')+1]==model
    plain,default_env=native_terminal.launch_command(executor,'',workspace,tmp_path/'default',binary=executor+'.exe')
    assert '--model' not in plain and '--mode' not in plain and '--settings' not in plain
    assert 'KILO_CONFIG_CONTENT' not in default_env


@pytest.mark.parametrize('executor',tuple(OUTPUTS))
def test_native_catalog_calls_exact_public_command_and_preserves_metadata(executor,tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(native_catalog.shutil,'which',lambda name:str(tmp_path/(name+'.exe')))
    def run(argv,**kwargs):
        calls.append(argv);assert Path(kwargs['cwd']).is_dir()
        return SimpleNamespace(returncode=0,stdout=OUTPUTS[executor],stderr='')
    monkeypatch.setattr(native_catalog.subprocess,'run',run)
    models,source=native_catalog.discover(executor,home=tmp_path,env={})
    assert calls==[[str(tmp_path/(native_catalog.BINARY[executor]+'.exe')),*native_catalog.COMMANDS[executor][1]]]
    assert len(models)==2,(executor,models)
    assert not any(m['id'] in ('ignored','Tool','Controls') for m in models)
    if executor in ('grok','cursor','droid'):assert sum(m['is_default'] for m in models)==1
    if executor=='kimi':assert models[0]['id']=='kimi-code/one' and models[0]['provider']=='managed:kimi-code'
    if executor=='omp':assert models[0]['id']=='anthropic/one'


@pytest.mark.parametrize('executor',tuple(CONFIGS))
def test_native_config_catalog_uses_public_models_not_secrets(executor,tmp_path):
    models=native_catalog.parse_config(executor,CONFIGS[executor])
    assert len(models)==(1 if executor=='autohand' else 2)
    assert 'test-never-return' not in json.dumps(models) and 'outside' not in json.dumps(models)
    if executor=='vibe':assert [m['id'] for m in models]==['one','two']


@pytest.mark.parametrize('executor,name',[('qwen','QWEN_HOME'),('vibe','VIBE_HOME'),('goose','GOOSE_PATH_ROOT'),('claude-code','CLAUDE_CONFIG_DIR')])
def test_native_configuration_directory_belongs_only_to_selected_tool(executor,name,tmp_path,monkeypatch):
    for variable in ('QWEN_HOME','VIBE_HOME','GOOSE_PATH_ROOT','CLAUDE_CONFIG_DIR'):
        monkeypatch.setenv(variable,str(tmp_path/variable))
    monkeypatch.setenv('ANTHROPIC_API_KEY','test-not-forwarded')
    environment=native_catalog.native_environment(executor)
    assert environment[name]==str(tmp_path/name)
    assert all(v not in environment for v in ('QWEN_HOME','VIBE_HOME','GOOSE_PATH_ROOT','CLAUDE_CONFIG_DIR') if v!=name)
    assert 'ANTHROPIC_API_KEY' not in environment and 'CODEX_HOME' not in environment
    if executor in native_catalog.CONFIG_PATHS:
        target=native_catalog.config_path(executor,tmp_path,environment)
        target.parent.mkdir(parents=True,exist_ok=True)
        if executor=='vibe':target.write_text('active_model = "one"\n[[models]]\nname = "one"\n',encoding='utf8')
        else:target.write_text(json.dumps(CONFIGS[executor]),encoding='utf8')
        models,_=native_catalog.discover(executor,home=tmp_path)
        assert models


def test_catalog_before_save_all_native_services_no_credentials_or_default_rewrite(http_panel,monkeypatch):
    prior=http_panel.state.defaults().snapshot();calls=[]
    original=native_catalog.discover
    def discover(identity):
        calls.append(identity)
        if identity in OUTPUTS:return native_catalog.parse_output(identity,OUTPUTS[identity]),'native fixture command'
        if identity in CONFIGS:return native_catalog.parse_config(identity,CONFIGS[identity]),'native fixture config'
        return original(identity,home=Path('/isolated'),env={})
    monkeypatch.setattr(native_catalog,'discover',discover)
    for service,executor in TERMINAL_SERVICES.items():
        code,_,data=request(http_panel,'POST','/api/model-catalog',{'service':service})
        assert code==200 and data['catalog']['status']=='ready',(executor,data)
        assert data['catalog']['executor_default'] is True
        assert data['catalog']['custom_model']==(executor in native_catalog.CUSTOM_DIRECT|native_catalog.CUSTOM_CONFIGURED)
    assert set(calls)==set(TERMINAL_SERVICES.values())
    assert http_panel.state.defaults().snapshot()==prior


def test_native_terminal_isolated_launch_receipt_restart_no_replay(http_panel,tmp_path,monkeypatch):
    from panel import server
    executor='droid';p=terminal_profile(executor,'one');original_runtime=http_panel.state.rt
    http_panel.state.set_config({'model_profiles':[p]})
    cfg=http_panel.state.defaults();original=tmp_path/'用户原目录';original.mkdir();(original/'代码.txt').write_text('original',encoding='utf8')
    row=register(server.ROOT,str(original));source=inspect(row)
    binary=str(tmp_path/'droid.exe');old_which=native_terminal.shutil.which
    monkeypatch.setattr(native_terminal.shutil,'which',lambda name:binary if name=='droid' else old_which(name))
    opened=[]
    def console(argv,workspace,environment):
        assert json.loads(Path(argv[argv.index('--settings')+1]).read_text())=={'model':'one'}
        proc=subprocess.Popen([sys.executable,'-c',"from pathlib import Path; Path('new.txt').write_text('manual result')"],cwd=workspace,env=environment)
        proc.wait(timeout=10);opened.append((argv,workspace));return proc
    monkeypatch.setattr(native_terminal,'open_console',console)
    identity=uuid.uuid4().hex
    body=dict(operation_id=identity,profile_id=p['id'],project_id=row['id'],source_revision=source['revision'],config_revision=cfg.snapshot()['revision'],confirmed=True)
    code,_,data=request(http_panel,'POST','/api/native-terminal',body)
    assert code==200,data
    assert data['terminal']['status']=='SUCCEEDED' and data['terminal']['acceptance']=='not_run'
    assert data['terminal']['window']=='closed' and len(opened)==1
    assert (original/'代码.txt').read_text(encoding='utf8')=='original' and not (original/'new.txt').exists()
    assert (opened[0][1]/'new.txt').read_text()=='manual result'
    frozen=StateStore(opened[0][1].parent/'state.db',readonly=True)
    try:assert frozen.operation(identity)['request']['profile']==p
    finally:frozen.close()
    http_panel.state.native_terminals=native_terminal.NativeTerminals()
    again=request(http_panel,'POST','/api/native-terminal',body)
    assert again[2]['terminal']['status']=='SUCCEEDED' and again[2]['terminal']['window']=='unknown' and len(opened)==1
    assert request(http_panel,path='/api/native-terminal?operation_id='+identity)[0]==200
    assert request(http_panel,path='/api/native-terminal?operation_id=..%2Foutside')[0]==400
    assert request(http_panel,'POST','/api/native-terminal',dict(body,operation_id=uuid.uuid4().hex,source_revision='bad'))[0]==400
    assert len(opened)==1 and http_panel.state.rt is original_runtime
    http_panel.state.set_config({'model_profiles':[dict(p,model='changed')]})
    assert request(http_panel,'POST','/api/native-terminal',dict(body,operation_id=uuid.uuid4().hex))[0]==400
    assert len(opened)==1


def test_native_terminal_crash_unknown_cannot_replay_or_be_assigned_semantic(http_panel,tmp_path,monkeypatch):
    from panel import server
    p=terminal_profile('aider');http_panel.state.set_config({'model_profiles':[p]})
    with pytest.raises(ConfigError):resolve_config(http_panel.state.defaults(),overrides={'roles':{'verifier':{'profile':p['id']}}})
    with pytest.raises(ConfigError):resolve_config(http_panel.state.defaults(),overrides={'worker':{'profile':p['id']}})
    root=tmp_path/'source';root.mkdir();row=register(server.ROOT,str(root));summary=inspect(row)
    old=native_terminal.shutil.which;monkeypatch.setattr(native_terminal.shutil,'which',lambda name:'fake-aider.exe' if name=='aider' else old(name))
    attempts=[]
    def crash(*args):attempts.append(1);raise OSError('lost creation acknowledgement')
    monkeypatch.setattr(native_terminal,'open_console',crash)
    body=dict(operation_id=uuid.uuid4().hex,profile_id=p['id'],project_id=row['id'],source_revision=summary['revision'],config_revision=http_panel.state.defaults().snapshot()['revision'],confirmed=True)
    assert request(http_panel,'POST','/api/native-terminal',body)[0]>=400
    http_panel.state.native_terminals=native_terminal.NativeTerminals()
    replay=request(http_panel,'POST','/api/native-terminal',body)
    assert replay[2]['terminal']['status']=='UNKNOWN' and attempts==[1]


def test_login_commands_are_native_no_key_or_automatic_success(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(native_auth.shutil,'which',lambda name:str(tmp_path/(name+'.exe')))
    monkeypatch.setenv('OPENAI_API_KEY','test-never-inherit')
    monkeypatch.setattr(native_auth.subprocess,'Popen',lambda argv,**kw:(calls.append((argv,kw)) or SimpleNamespace(poll=lambda:None)))
    logins=native_auth.NativeLogins()
    for executor in AO_EXECUTORS:
        if executor=='aider':
            with pytest.raises(ValueError,match='没有原生登录'):logins.start(executor)
            continue
        result=logins.start(executor);assert result['state']=='waiting'
        argv,kwargs=calls[-1];script=base64.b64decode(argv[-1]).decode('utf-16-le')
        assert str(tmp_path/(native_catalog.BINARY[executor]+'.exe')) in script
        assert 'OPENAI_API_KEY' not in kwargs['env'] and 'test-never-inherit' not in json.dumps(argv)
        count=len(calls);assert logins.start(executor)['state']=='waiting' and len(calls)==count
    assert len(calls)==26


def test_linked_worktree_uses_main_default_without_copying(tmp_path,monkeypatch):
    main=tmp_path/'主 工作树';(main/'clao/config').mkdir(parents=True)
    original=b'model_profiles: []\n';(main/'clao/config/default.yaml').write_bytes(original)
    subprocess.run(['git','init','--initial-branch=main',str(main)],check=True,capture_output=True)
    subprocess.run(['git','-C',str(main),'-c','user.name=Test','-c','user.email=test@localhost','commit','--allow-empty','-m','base'],check=True,capture_output=True)
    linked=tmp_path/'关联 中文';subprocess.run(['git','-C',str(main),'worktree','add','-b','test',str(linked)],check=True,capture_output=True)
    (linked/'clao/config').mkdir(parents=True);(linked/'clao/config/default.yaml').write_text('different: true')
    monkeypatch.delenv('CLAO_CONFIG',raising=False);monkeypatch.setattr(run_mission,'ROOT',linked/'clao')
    assert run_mission.default_config_path()==main/'clao/config/default.yaml'
    assert (main/'clao/config/default.yaml').read_bytes()==original
    explicit=tmp_path/'custom.yaml';explicit.write_text('model_profiles: []')
    monkeypatch.setenv('CLAO_CONFIG',str(explicit));assert run_mission.default_config_path()==explicit


def test_native_browser_connection_model_and_terminal(journey,tmp_path,monkeypatch):
    project=form(journey,tmp_path/'原生项目 中文')
    old_which=native_catalog.shutil.which;old_run=native_catalog.subprocess.run;old_popen=native_auth.subprocess.Popen
    binary=str(tmp_path/'opencode.exe');launches=[];logins=[]
    monkeypatch.setattr(native_catalog.shutil,'which',lambda name:binary if name=='opencode' else old_which(name))
    def run(argv,**kwargs):
        if argv[0]==binary:
            assert argv[1:]==['--pure','models']
            return SimpleNamespace(returncode=0,stdout='provider/first\nprovider/second\n',stderr='')
        return old_run(argv,**kwargs)
    monkeypatch.setattr(native_catalog.subprocess,'run',run)
    def popen(argv,*args,**kwargs):
        if argv[0]=='powershell.exe':
            script=base64.b64decode(argv[-1]).decode('utf-16-le')
            assert "'auth' 'login'" in script;logins.append(script)
            return SimpleNamespace(poll=lambda:None,pid=8888)
        return old_popen(argv,*args,**kwargs)
    monkeypatch.setattr(native_auth.subprocess,'Popen',popen)
    def console(argv,workspace,environment):
        assert argv==[binary,'--model','provider/second'];launches.append(workspace)
        proc=old_popen([sys.executable,'-c',"from pathlib import Path; Path('manual.txt').write_text('done')"],cwd=workspace,env=environment)
        proc.wait(timeout=10);return proc
    monkeypatch.setattr(native_terminal,'open_console',console)
    script=Path(__file__).resolve().parents[2]/'dev/panel/m4-native.cjs'
    out=Path(os.environ.get('M4_SCREENSHOTS',str(tmp_path/'shots')))
    result=old_run([os.environ['U01_NODE'],str(script),journey.origin,project['project_id'],str(out)],
                   capture_output=True,encoding='utf-8',timeout=100)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert len(logins)==1 and len(launches)==1
    assert (tmp_path/'原生项目 中文/app.py').read_text()=='x=0\n'
    assert not (tmp_path/'原生项目 中文/manual.txt').exists()
    assert (launches[0]/'manual.txt').read_text()=='done'
    assert journey.state.rt is None
    print(result.stdout)
