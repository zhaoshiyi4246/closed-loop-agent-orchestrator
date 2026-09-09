"""Native model discovery, adapted from AO v0.12.12 modelcatalog.

Upstream: Untrivial-ai/agent-orchestrator, commit 84fb37ce5aa947ceb9b19b0c2435b242ac92ce26.
Apache-2.0; see clao/AO-LICENSE.txt. Python adaptation adds bounded, safe
metadata projection and deliberately does not inspect private credential DBs.
Native authentication and execution are separate capabilities, not inferred
from a successful catalog or the presence of an executable.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib

import yaml

from .model_profiles import MODEL_ID, AO_EXECUTORS

# Exact registry identities; argv are code-owned, never accepted from HTTP.
COMMANDS = {
    'aider': ('aider', ['--no-check-update', '--no-git', '--no-gitignore', '--no-analytics', '--list-models', '.']),
    'opencode': ('opencode', ['--pure', 'models']), 'grok': ('grok', ['models']),
    'cursor': ('cursor-agent', ['models']), 'agy': ('agy', ['models']),
    'kilocode': ('kilo', ['models']), 'pi': ('pi', ['--list-models']),
    'kimchi': ('kimchi', ['--list-models']), 'prime-agent': ('prime-agent', ['model', 'list']),
    'kimi': ('kimi', ['provider', 'list', '--json']), 'auggie': ('auggie', ['models', 'list', '--json']),
    'devin': ('devin', ['models', 'list', '--format', 'json']), 'kiro': ('kiro-cli', ['chat', '--list-models', '--format', 'json']),
    'omp': ('omp', ['models', '--json']), 'copilot': ('copilot', ['help', 'config']),
    'droid': ('droid', ['exec', '--help']), 'crush': ('crush', ['models']),
}
CONFIG_PATHS = {'qwen': '.qwen/settings.json', 'continue': '.continue/config.yaml',
                'goose': '.config/goose/config.yaml', 'vibe': '.vibe/config.toml',
                'cline': '.cline/data/settings/providers.json', 'autohand': '.autohand/config.json'}
CUSTOM_DIRECT = {'claude-code','codex','opencode','grok','cursor','qwen','kimi','muse','aider','goose','autohand'}
CUSTOM_CONFIGURED = {'continue','cline','kilocode','vibe','pi','kimchi','prime-agent'}
REGISTRY = AO_EXECUTORS
BINARY = {name: COMMANDS[name][0] if name in COMMANDS else
          {'claude-code':'claude','continue':'cn'}.get(name, name) for name in REGISTRY}


def native_environment(identity):
    """Carry only this tool's public configuration-directory override, never keys."""
    from .native_models import process_environment
    environment = process_environment()
    if identity != 'codex':
        environment.pop('CODEX_HOME', None)
    for name in {'claude-code': ('CLAUDE_CONFIG_DIR',), 'qwen': ('QWEN_HOME',),
                 'vibe': ('VIBE_HOME',), 'goose': ('GOOSE_PATH_ROOT',)}.get(identity, ()):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    return environment


def normalize(rows):
    result = {}
    for row in rows:
        identity = row.get('id')
        if not isinstance(identity, str) or not MODEL_ID.fullmatch(identity) or identity.lower() in ('model','models','provider'):
            continue
        clean = {k: v for k,v in row.items() if k in ('id','label','provider','description')
                 and isinstance(v,str) and len(v) <= 1000 and not any(ord(c)<32 for c in v)}
        if 'id' not in clean:
            continue
        clean['label'] = clean.get('label') or identity
        clean['is_default'] = row.get('is_default') is True
        if identity in result:
            clean['is_default'] |= result[identity]['is_default']
        result[identity] = clean
    if len(result)>2000:
        raise ValueError('原生模型目录超过读取上限')
    return sorted(result.values(),key=lambda m:(not m['is_default'],m['label'].lower()))


def json_models(root):
    rows=[]
    def text(node,*keys):
        return next((node[k].strip() for k in keys if isinstance(node.get(k),str) and node[k].strip()),'')
    def walk(node,depth=0):
        if depth>30: raise ValueError('模型目录嵌套过深')
        if isinstance(node,list):
            for child in node: walk(child,depth+1)
        elif isinstance(node,dict):
            identity=text(node,'selector','modelId','model_id','model_uid','slug','model')
            if not identity and 'models' not in node: identity=text(node,'id')
            if identity:
                rows.append(dict(id=identity,label=text(node,'displayName','display_name','model_name','label','name'),
                                 provider=text(node,'provider','providerId','provider_id'),
                                 is_default=any(node.get(k) is True for k in ('isDefault','is_default','default'))))
            # Traverse catalog containers only, not auth/usage/arbitrary objects.
            for key in ('data','providers','models','families','variants'):
                child=node.get(key)
                if key=='models' and isinstance(child,dict):
                    for alias,value in child.items():
                        if isinstance(value,dict) and 'models' not in value and text(value,'modelId','model_id','model','provider'):
                            rows.append(dict(id=alias,label=text(value,'displayName','name','label') or alias,
                                             provider=text(value,'provider'),is_default=value.get('default') is True))
                        else: walk(value,depth+1)
                elif isinstance(child,dict):
                    for value in child.values(): walk(value,depth+1)
                else: walk(child,depth+1)
    walk(root)
    return normalize(rows)


def parse_output(identity,raw):
    if identity in ('kimi','auggie','devin','kiro','omp'):
        return json_models(json.loads(raw))
    raw=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',raw)
    rows=[]; started=identity not in ('grok','cursor','copilot','droid')
    markers={'grok':'Available models:', 'cursor':'Available models','copilot':'`model`:','droid':'Available Models:'}
    for original in raw.splitlines():
        line=original.strip()
        if not started:
            started=line.startswith(markers[identity]);continue
        if identity=='cursor' and line.startswith('Tip:') or identity=='copilot' and line.startswith('`contextTier`:'):break
        if identity=='droid' and rows and (not line or line.endswith(':')):break
        if identity=='copilot' and not line.startswith('-'):continue
        line=line.lstrip('•*-✓>│├└ ').strip(); fields=line.split()
        if not fields:continue
        model=fields[0].strip('`"\'(),:')
        label=model;provider=None
        if identity in ('pi','kimchi','prime-agent'):
            if len(fields)<2 or fields[0].lower()=='provider':continue
            provider,model=fields[:2];label=model;model=provider+'/'+model
        elif identity in ('agy','droid'):
            if len(fields)<2:continue
            label=line[len(fields[0]):].strip().removesuffix('(default)').strip()
        elif identity in ('grok','cursor'):
            if ' - ' in line:label=line.split(' - ',1)[1].split(' (',1)[0].strip()
        elif len(fields)!=1:continue
        rows.append(dict(id=model,label=label,provider=provider,is_default='(default)' in line.lower()))
    return normalize(rows)


def parse_config(identity,value):
    rows=[]
    if not isinstance(value,dict):raise ValueError('原生模型配置格式无效')
    def add(model,label=None,provider=None,default=False):
        rows.append(dict(id=model,label=label or model,provider=provider,is_default=default))
    if identity=='qwen':
        selected=(value.get('model') or {}).get('name')
        for provider,models in value.get('modelProviders',{}).items():
            for m in models:add(m.get('id'),m.get('name'),provider,m.get('id')==selected)
    elif identity=='continue':
        defaults=list(value.get('defaults',{}).values())
        for m in value.get('models',[]):add(m.get('model'),m.get('name'),m.get('provider'),m.get('model') in defaults or m.get('name') in defaults)
    elif identity=='goose':
        provider=value.get('active_provider');m=value.get('providers',{}).get(provider,{})
        for model in m.get('models',[])+([m['model']] if m.get('model') else []):add(model,provider=provider,default=model==m.get('model'))
    elif identity=='vibe':
        for m in value.get('models',[]):
            model=m.get('alias') or m.get('name');add(model,m.get('name'),m.get('provider'),model==value.get('active_model'))
    elif identity=='autohand':
        provider=value.get('provider');m=value.get(provider,{}) if isinstance(provider,str) else {}
        model=m.get('model')
        if isinstance(model,str):add(model if '/' in model else provider+'/'+model,model,provider,True)
    elif identity=='cline':
        def walk(v,provider,depth=0):
            if depth>30:raise ValueError('配置嵌套过深')
            if isinstance(v,dict):
                for k,child in v.items():
                    if k.lower() in ('model','modelid','apimodelid') and isinstance(child,str):add(child,provider=provider,default=provider==value.get('lastUsedProvider'))
                    elif isinstance(child,(list,dict)):walk(child,provider,depth+1)
            elif isinstance(v,list):
                for child in v:walk(child,provider,depth+1)
        for provider,config in value.get('providers',{}).items():walk(config,provider)
    return normalize(rows)


def config_path(identity,home,env):
    if identity=='qwen' and env.get('QWEN_HOME'):return Path(env['QWEN_HOME']).expanduser()/'settings.json'
    if identity=='vibe' and env.get('VIBE_HOME'):return Path(env['VIBE_HOME']).expanduser()/'config.toml'
    if identity=='goose' and env.get('GOOSE_PATH_ROOT'):return Path(env['GOOSE_PATH_ROOT']).expanduser()/'config/config.yaml'
    return home/CONFIG_PATHS[identity]


def discover(identity, *, home=None, env=None):
    if identity not in REGISTRY:raise ValueError('未知执行器')
    home=Path.home() if home is None else Path(home)
    environment=native_environment(identity) if env is None else dict(env)
    if identity=='claude-code':
        return [dict(id=i,label=label,is_default=False) for i,label in [('sonnet','Sonnet'),('fable','Fable 5.1'),('opus','Opus'),('haiku','Haiku'),('opus[1m]','Opus (1M context)')]],'AO v0.12.12 Claude aliases'
    if identity=='muse':
        return [dict(id=i,label=i,is_default=i=='muse-spark') for i in ('muse-spark','muse-spark-1.1','muse-spark-1.2')],'AO v0.12.12 Muse catalog'
    if identity=='amp':
        return [dict(id=i,label=i,is_default=i=='medium') for i in ('low','medium','high','ultra')],'AO v0.12.12 Amp modes'
    if identity in CONFIG_PATHS:
        path=config_path(identity,home,environment)
        with path.open('rb') as f:raw=f.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise ValueError('原生配置过大')
        text=raw.decode('utf-8')
        value=tomllib.loads(text) if path.suffix=='.toml' else yaml.safe_load(text) if path.suffix=='.yaml' else json.loads(text)
        return parse_config(identity,value),'native configured models'
    if identity=='codex':raise ValueError('Codex 目录通过公开 App Server 读取')
    binary=shutil.which(BINARY[identity])
    if not binary:raise FileNotFoundError('PATH 中未找到 '+BINARY[identity])
    with tempfile.TemporaryDirectory(prefix='clao-native-catalog-') as directory:
        result=subprocess.run([binary,*COMMANDS[identity][1]],cwd=directory,env=environment,
                              capture_output=True,timeout=20,encoding='utf-8',errors='strict',check=False)
    if result.returncode or len(result.stdout.encode('utf-8'))>2*1024*1024:raise ValueError('原生目录查询失败')
    rows=parse_output(identity,result.stdout)
    if not rows and result.stdout.strip():raise ValueError('原生目录返回了无法识别的格式')
    return rows,'native CLI model catalog'
