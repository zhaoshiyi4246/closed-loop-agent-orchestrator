"""User-operated native terminals, separate from an automated CLAO Worker.

Launch/model mappings adapted from AO v0.12.12, Apache-2.0 (AO-LICENSE.txt).
Only fixed native commands are accepted. No prompt injection, approval proxy,
credential copying, terminal transcript, or inference of Mission success.
"""
import base64
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading

from .model_profiles import TERMINAL_SERVICES, MODEL_ID, CODEX_ACCOUNT, CLAUDE_ACCOUNT
from .native_catalog import BINARY, REGISTRY, native_environment
from .state_store import StateStore


def executor_for(profile):
    return TERMINAL_SERVICES.get(profile['service']) or {
        CODEX_ACCOUNT:'codex', CLAUDE_ACCOUNT:'claude-code'}.get(profile['service'])


def launch_command(executor, model, workspace, settings, *, binary):
    """Materialize only process/workspace-local native model overrides."""
    if executor not in REGISTRY or not isinstance(model, str) or model and not MODEL_ID.fullmatch(model):
        raise ValueError('执行器或模型无效')
    workspace, settings = Path(workspace), Path(settings)
    settings.mkdir(parents=True, exist_ok=True)
    argv, env = [binary], native_environment(executor)
    if executor == 'codex':
        argv += ['--sandbox','workspace-write','--ask-for-approval','untrusted']
    elif executor == 'grok':
        argv += ['--no-auto-update']
    elif executor == 'aider':
        argv += ['--no-check-update','--no-auto-commits']
    elif executor == 'goose':
        argv += ['run','-t','','--interactive']
    elif executor == 'agy':
        argv += ['--add-dir',str(workspace)]
    elif executor == 'crush':
        argv += ['--cwd',str(workspace)]
    elif executor == 'kiro':
        argv += ['chat']
    if model:
        if executor == 'amp':
            if model not in ('low','medium','high','ultra'):raise ValueError('Amp 需要选择运行模式')
            argv += ['--mode',model]
        elif executor == 'droid':
            path=settings/'droid.json';path.write_text(json.dumps({'model':model}),encoding='utf-8')
            argv += ['--settings',str(path)]
        elif executor == 'kilocode':
            env['KILO_CONFIG_CONTENT']=json.dumps({'agent':{'clao-selection':{'model':model}}})
            argv += ['--agent','clao-selection']
        elif executor == 'vibe':
            agents=settings/'.vibe'/'agents';agents.mkdir(parents=True,exist_ok=True)
            (agents/'clao-selection.toml').write_text('agent_type = "agent"\ndisplay_name = "CLAO selection"\nsafety = "neutral"\nactive_model = '+json.dumps(model)+'\n',encoding='utf-8')
            argv += ['--add-dir',str(settings),'--agent','clao-selection']
        elif executor == 'kiro':
            agents=workspace/'.kiro'/'agents';agents.mkdir(parents=True,exist_ok=True)
            name='clao-'+settings.parent.name
            (agents/(name+'.json')).write_text(json.dumps({'name':name,'model':model,'tools':['*'],
                'allowedTools':[],'resources':[],'mcpServers':{},'includeMcpJson':False}),encoding='utf-8')
            argv += ['--agent',name]
        elif executor == 'crush':
            provider,sep,model_id=model.partition('/')
            if not sep or not model_id:raise ValueError('Crush 型号必须包含 provider/model-id')
            path=workspace/'.crush.json'
            cfg=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            cfg.setdefault('models',{})['large']={'provider':provider,'model':model_id}
            path.write_text(json.dumps(cfg,ensure_ascii=False),encoding='utf-8')
        else:
            argv += ['--model',model]
    return argv,env


def open_console(argv, workspace, environment):
    if os.name != 'nt':raise ValueError('原生终端窗口目前需要 Windows')
    # PowerShell literals prevent model/path characters from becoming shell code.
    quote=lambda value:"'"+str(value).replace("'","''")+"'"
    script='& '+' '.join(quote(v) for v in argv)
    encoded=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return subprocess.Popen(['powershell.exe','-NoProfile','-NoExit','-EncodedCommand',encoded],
        cwd=str(workspace),env=environment,creationflags=subprocess.CREATE_NEW_CONSOLE,
        stdin=None,stdout=None,stderr=None,close_fds=True)


class NativeTerminals:
    def __init__(self):
        self.lock=threading.RLock()
        self.processes={}

    @staticmethod
    def directory(root, identity):
        if not isinstance(identity,str) or not re.fullmatch(r'[a-f0-9]{32}',identity):
            raise ValueError('原生终端记录 ID 无效')
        root=Path(root).resolve()
        path=root/'runtime'/'native-terminals'/identity
        for parent in (path,*path.parents):
            if parent==root:break
            if parent.exists() and (parent.is_symlink() or getattr(parent.lstat(),'st_file_attributes',0)&0x400):
                raise ValueError('原生终端目录不能是链接或 junction')
        return path

    def start(self, root, cfg, body):
        from .local_projects import project,snapshot
        if set(body)!={'operation_id','profile_id','project_id','source_revision','config_revision','confirmed'} or body['confirmed'] is not True:
            raise ValueError('请确认原生终端、本次连接与项目来源')
        if body['config_revision'] != cfg.snapshot()['revision']:
            raise ValueError('默认连接配置已变化，请重新确认本次选择')
        identity=body['operation_id'];directory=self.directory(root,identity)
        profile=next((copy.deepcopy(p) for p in cfg['model_profiles'] if p['id']==body['profile_id']),None)
        if profile is None or not (executor:=executor_for(profile)):
            raise ValueError('该连接不能用于原生终端；请选择原生工具认证连接')
        binary=shutil.which(BINARY[executor])
        if not binary:raise ValueError('PATH 中未找到 '+BINARY[executor]+'；请检查原生工具安装与 PATH')
        source_project=project(root,body['project_id'])
        request=dict(project_id=source_project['id'],source_revision=body['source_revision'],profile=profile)
        with self.lock:
            store=StateStore(directory/'state.db')
            try:
                op=store.ensure_operation(identity,'native_terminal',identity,executor,request)
                if op['status']!='NOT_STARTED':return self._view(store,identity)
                # Claim before preparing source or launching. A crash never replays
                # the native executable. The same receipt can always be queried.
                if not store.operation_claim(identity,max_attempts=1):return self._view(store,identity)
                try:
                    frozen=snapshot(source_project,directory,body['source_revision'])
                    workspace=directory/'workspace'
                    shutil.copytree(directory/'source',workspace)
                    argv,environment=launch_command(executor,profile['model'],workspace,directory/'settings',binary=binary)
                except Exception:
                    store.operation_observe(identity,'FAILED',{'stage':'prepare'},result={'reason':'隔离来源或原生启动配置准备失败，未启动工具'})
                    raise
                try:
                    process=open_console(argv,workspace,environment)
                    self.processes[identity]=process
                    store.operation_observe(identity,'SUCCEEDED',{'stage':'console_created'},result={
                        'workspace':str(workspace),'source_commit':frozen['source_commit'],'pid':process.pid,
                        'meaning':'仅确认原生窗口已创建；不代表登录、工具完成或验收通过'})
                except BaseException:
                    store.operation_observe(identity,'UNKNOWN',{'stage':'launch'},result={'reason':'无法确认原生窗口启动结果；不会自动重发'})
                    raise
                return self._view(store,identity)
            finally:store.close()

    def read(self, root, identity):
        directory=self.directory(root,identity)
        if not (directory/'state.db').is_file():raise ValueError('找不到原生终端记录')
        store=StateStore(directory/'state.db',readonly=True)
        try:return self._view(store,identity)
        finally:store.close()

    def _view(self, store, identity):
        op=store.operation(identity)
        if op is None:raise ValueError('找不到原生终端操作')
        process=self.processes.get(identity)
        return dict(operation_id=identity,executor=op['target'],project_id=op['request']['project_id'],
            model=op['request']['profile']['model'] or None,
            status='UNKNOWN' if op['status']=='IN_FLIGHT' else op['status'],result=op['result'],
            window='unknown' if process is None else 'open' if process.poll() is None else 'closed',
            acceptance='not_run',tier='native_terminal')
