"""The one P01 service contract; no discovery, fallback or credential values."""
import copy
import math
import re

ENDPOINT = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
SERVICE = 'bigmodel_general'
MODELS = ('glm-4.7',)
ROLES = ('planner', 'auditor', 'verifier')
REFERENCE = re.compile(r'[a-z][a-z0-9_-]{0,47}')
KEYS = {'id', 'service', 'endpoint', 'model', 'credential_ref', 'timeout_seconds',
        'max_attempts', 'retry_delay_seconds', 'thinking', 'max_tokens', 'temperature'}


def validate_profiles(profiles):
    if not isinstance(profiles, list) or len(profiles) > 12:
        raise ValueError('model_profiles must be a list with at most 12 connections')
    ids = set()
    for p in profiles:
        if not isinstance(p, dict) or set(p) != KEYS:
            raise ValueError('profile fields missing or unsupported; secrets and Codex effort are not profile parameters')
        if not isinstance(p['id'], str) or not REFERENCE.fullmatch(p['id']) or p['id'] == 'codex' or p['id'] in ids:
            raise ValueError('profile id invalid or duplicated')
        ids.add(p['id'])
        if p['service'] != SERVICE or p['endpoint'] != ENDPOINT:
            raise ValueError('only BigModel general HTTPS endpoint is supported; Z.AI/Coding endpoints are not interchangeable')
        if p['model'] not in MODELS or p['thinking'] not in ('enabled', 'disabled'):
            raise ValueError('profile model/thinking unsupported; P01 targets glm-4.7, live admission pending')
        if not isinstance(p['credential_ref'], str) or not REFERENCE.fullmatch(p['credential_ref']):
            raise ValueError('credential_ref must be a local credential name')
        for key,low,high in [('timeout_seconds',0,600), ('retry_delay_seconds',0,30), ('temperature',0,1)]:
            v=p[key]
            if type(v) not in (int,float) or not low <= v <= high or not math.isfinite(v) or key=='timeout_seconds' and v==0:
                raise ValueError('invalid profile '+key)
        if round(p['temperature'],2) != p['temperature']:
            raise ValueError('temperature supports at most two decimal places')
        for key,high in [('max_attempts',3),('max_tokens',131072)]:
            if type(p[key]) is not int or not 1 <= p[key] <= high:
                raise ValueError('invalid profile '+key)


def selected(cfg, role):
    identity = cfg['roles'][role].get('profile', 'codex')
    if identity == 'codex':
        return None
    rows = [p for p in cfg.get('model_profiles', []) if p['id'] == identity]
    if len(rows) != 1:
        raise ValueError('selected '+role+' profile is missing')
    return copy.deepcopy(rows[0])


def external_roles(cfg):
    return {role: p for role in ROLES if (p := selected(cfg, role)) is not None}


def check_start(cfg, mission):
    """A task's frozen selection, consent and credentials before any Worker."""
    from .credentials import credentials
    selected_roles = external_roles(cfg)
    if selected_roles and mission.get('external_service_consent') != 'bigmodel_general':
        raise ValueError('请先确认：所选 GLM 角色将向 BigModel 通用服务发送任务、代码差异与验收证据，可能计费')
    for role,p in selected_roles.items():
        if not credentials().configured(p['credential_ref']):
            raise ValueError(role+' 的 GLM 凭据未配置；请在模型页保存对应凭据')


def connection_status(cfg):
    from .credentials import credentials, CredentialError
    rows=[]
    for p in cfg.get('model_profiles',[]):
        row={k:p[k] for k in ('id','service','endpoint','model','credential_ref')}
        try:
            row['credential_status']='configured' if credentials().configured(p['credential_ref']) else 'missing'
        except CredentialError:
            row['credential_status']='unavailable'
        row.update(configuration='saved', offline_check='valid', live_check='not_run', verified_roles=[])
        rows.append(row)
    return rows
