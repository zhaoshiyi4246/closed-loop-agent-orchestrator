"""Two explicit domestic service contracts; no discovery or credential values."""
import copy
import math
import re

ENDPOINT = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
SERVICE = 'bigmodel_general'
MODELS = ('glm-4.7',)
KIMI_SERVICE = 'moonshot_cn'
KIMI_ENDPOINT = 'https://api.moonshot.cn/v1/chat/completions'
KIMI_MODEL = 'kimi-k3'
ENDPOINTS = {SERVICE: ENDPOINT, KIMI_SERVICE: KIMI_ENDPOINT}
LABELS = {SERVICE: 'BigModel 通用服务', KIMI_SERVICE: 'Kimi 国内通用服务'}
ROLES = ('planner', 'auditor', 'verifier')
REFERENCE = re.compile(r'[a-z][a-z0-9_-]{0,47}')
KEYS = {'id', 'service', 'endpoint', 'model', 'credential_ref', 'timeout_seconds',
        'max_attempts', 'retry_delay_seconds', 'thinking', 'max_tokens', 'temperature'}
KIMI_KEYS = (KEYS - {'thinking', 'max_tokens', 'temperature'}) | {'reasoning_effort', 'max_completion_tokens'}


def validate_profiles(profiles):
    if not isinstance(profiles, list) or len(profiles) > 12:
        raise ValueError('model_profiles must be a list with at most 12 connections')
    ids = set()
    for p in profiles:
        if not isinstance(p, dict) or not isinstance(p.get('service'), str) or p['service'] not in ENDPOINTS:
            raise ValueError('unsupported model service; only BigModel general and Kimi domestic general are supported')
        kimi = p['service'] == KIMI_SERVICE
        if set(p) != (KIMI_KEYS if kimi else KEYS):
            raise ValueError('profile fields missing or unsupported for selected service; do not mix provider parameters')
        if not isinstance(p['id'], str) or not REFERENCE.fullmatch(p['id']) or p['id'] == 'codex' or p['id'] in ids:
            raise ValueError('profile id invalid or duplicated')
        ids.add(p['id'])
        if p['endpoint'] != ENDPOINTS[p['service']]:
            raise ValueError('service endpoint mismatch; international, proxy and Coding endpoints are not interchangeable')
        if kimi:
            if p['model'] != KIMI_MODEL or p['reasoning_effort'] not in ('low', 'high', 'max'):
                raise ValueError('Kimi model/reasoning_effort unsupported; targets kimi-k3, live admission pending')
        elif p['model'] not in MODELS or p['thinking'] not in ('enabled', 'disabled'):
            raise ValueError('BigModel model/thinking unsupported; targets glm-4.7, live admission pending')
        if not isinstance(p['credential_ref'], str) or not REFERENCE.fullmatch(p['credential_ref']):
            raise ValueError('credential_ref must be a local credential name')
        for key,low,high in [('timeout_seconds',0,600), ('retry_delay_seconds',0,30)] + ([] if kimi else [('temperature',0,1)]):
            v=p[key]
            if type(v) not in (int,float) or not low <= v <= high or not math.isfinite(v) or key=='timeout_seconds' and v==0:
                raise ValueError('invalid profile '+key)
        if not kimi and round(p['temperature'],2) != p['temperature']:
            raise ValueError('temperature supports at most two decimal places')
        for key,high in [('max_attempts',3), ('max_completion_tokens',1048576) if kimi else ('max_tokens',131072)]:
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


def consent_services(value):
    # The old scalar is only BigModel permission, never a wildcard for new services.
    if value is None:
        return set()
    if value == SERVICE:
        return {SERVICE}
    if (not isinstance(value, list) or any(not isinstance(v, str) or v not in ENDPOINTS for v in value)
            or len(value) != len(set(value))):
        raise ValueError('外发确认必须列出本次服务；旧单项确认仅适用于 BigModel')
    return set(value)


def checked_consent(value):
    services = consent_services(value)
    return SERVICE if value == SERVICE else sorted(services) if services else None


def check_start(cfg, mission):
    """A task's frozen selection, consent and credentials before any Worker."""
    from .credentials import credentials
    selected_roles = external_roles(cfg)
    missing = {p['service'] for p in selected_roles.values()} - consent_services(mission.get('external_service_consent'))
    if missing:
        raise ValueError('请先确认：所选角色将向 '+ '、'.join(LABELS[s] for s in sorted(missing)) +'发送任务、代码差异与验收证据，可能计费')
    for role,p in selected_roles.items():
        if not credentials(p['service']).configured(p['credential_ref']):
            raise ValueError(role+' 的 '+LABELS[p['service']]+'凭据未配置；请在模型页保存对应服务的凭据')


def connection_status(cfg):
    from .credentials import credentials, CredentialError
    rows=[]
    for p in cfg.get('model_profiles',[]):
        row={k:p[k] for k in ('id','service','endpoint','model','credential_ref')}
        try:
            row['credential_status']='configured' if credentials(p['service']).configured(p['credential_ref']) else 'missing'
        except CredentialError:
            row['credential_status']='unavailable'
        row.update(configuration='saved', offline_check='valid', live_check='not_run', verified_roles=[])
        rows.append(row)
    return rows
