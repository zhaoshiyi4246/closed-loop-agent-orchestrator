"""Frozen connections and parameter capabilities, independent of model catalogs.

Legacy P01/P02 dictionaries are validated in place, never rewritten on read.
New connections carry an explicit parameter map; an unknown model can use the
minimal JSON protocol, but cannot inherit another model's tuning parameters.
"""
import copy
import math
import re

ENDPOINT = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
SERVICE = 'bigmodel_general'
CODEX_API = 'codex_api'
CODEX_ACCOUNT = 'codex_account'
CODING_SERVICE = 'bigmodel_coding'
CODING_ENDPOINT = 'https://open.bigmodel.cn/api/anthropic'
KIMI_SERVICE = 'moonshot_cn'
KIMI_ENDPOINT = 'https://api.moonshot.cn/v1/chat/completions'
KIMI_MODEL = 'kimi-k3'
ENDPOINTS = {SERVICE: ENDPOINT, KIMI_SERVICE: KIMI_ENDPOINT,
             CODING_SERVICE: CODING_ENDPOINT, CODEX_API: 'https://api.openai.com/v1',
             CODEX_ACCOUNT: 'codex://chatgpt'}
LABELS = {SERVICE: 'BigModel · GLM API', KIMI_SERVICE: 'Kimi · 国内 API',
          CODING_SERVICE: 'GLM · Coding Plan', CODEX_API: 'Codex · API', CODEX_ACCOUNT: 'Codex · ChatGPT 账号'}
ROLES = ('planner', 'auditor', 'verifier')
REFERENCE = re.compile(r'[a-z][a-z0-9_-]{0,47}')
KEYS = {'id', 'service', 'endpoint', 'model', 'credential_ref', 'timeout_seconds',
        'max_attempts', 'retry_delay_seconds', 'thinking', 'max_tokens', 'temperature'}
KIMI_KEYS = (KEYS - {'thinking', 'max_tokens', 'temperature'}) | {'reasoning_effort', 'max_completion_tokens'}
BASE_KEYS = KEYS - {'thinking', 'max_tokens', 'temperature'}
NEW_KEYS = BASE_KEYS | {'label', 'parameters'}
MODEL_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/:@+\[\]-]{0,127}')


def parameter_defaults(service, model):
    if service == SERVICE and model == 'glm-4.7':
        return dict(thinking='disabled', temperature=0.2, max_tokens=8192)
    if service == SERVICE and model == 'glm-5.3':
        return dict(thinking='enabled', reasoning_effort='max', temperature=1.0, max_tokens=8192)
    if service == KIMI_SERVICE and model == KIMI_MODEL:
        return dict(reasoning_effort='max', max_completion_tokens=8192)
    # Native tools own their parameters. Unknown API models get no borrowed knobs.
    return {}


def parameters(profile):
    return copy.deepcopy(profile['parameters'] if 'parameters' in profile else
                         {k: profile[k] for k in set(profile) - BASE_KEYS})


def request_parameters(profile):
    params = parameters(profile)
    if 'thinking' in params:
        params['thinking'] = {'type': params['thinking']}
    return params


def validate_profiles(profiles):
    if not isinstance(profiles, list) or len(profiles) > 12:
        raise ValueError('model_profiles must be a list with at most 12 connections')
    ids = set()
    for p in profiles:
        if not isinstance(p, dict) or not isinstance(p.get('service'), str) or p['service'] not in ENDPOINTS:
            raise ValueError('unsupported model service')
        kimi = p['service'] == KIMI_SERVICE
        modern = 'parameters' in p
        if set(p) != (NEW_KEYS if modern else KIMI_KEYS if kimi else KEYS):
            raise ValueError('profile fields missing or unsupported for selected service; do not mix provider parameters')
        if not isinstance(p['id'], str) or not REFERENCE.fullmatch(p['id']) or p['id'] == 'codex' or p['id'] in ids:
            raise ValueError('profile id invalid or duplicated')
        ids.add(p['id'])
        if p['endpoint'] != ENDPOINTS[p['service']]:
            raise ValueError('service endpoint mismatch; international, proxy and Coding endpoints are not interchangeable')
        if not isinstance(p['model'], str) or not MODEL_ID.fullmatch(p['model']):
            raise ValueError('invalid model ID')
        if modern and (not isinstance(p['label'], str) or not p['label'].strip() or len(p['label']) > 80
                       or any(ord(c) < 32 for c in p['label'])):
            raise ValueError('connection label must be 1–80 printable characters')
        params = parameters(p)
        supported = parameter_defaults(p['service'], p['model'])
        if not isinstance(params, dict) or set(params) != set(supported):
            raise ValueError('model parameters unsupported; use this model\'s declared parameters, or none for a custom model')
        if p['service'] in (CODEX_API, CODEX_ACCOUNT, CODING_SERVICE) and (p['max_attempts'] != 1 or p['retry_delay_seconds'] != 0):
            raise ValueError('native executors own request retries; CLAO max_attempts must be 1 and retry delay 0')
        if 'thinking' in params and (params['thinking'] not in ('enabled', 'disabled') or
                                    p['model'] == 'glm-5.3' and params['thinking'] != 'enabled'):
            raise ValueError('GLM-5.3 requires enabled thinking; invalid thinking setting')
        if 'reasoning_effort' in params and params['reasoning_effort'] not in ('low', 'high', 'max'):
            raise ValueError('unsupported reasoning_effort')
        if not isinstance(p['credential_ref'], str) or not REFERENCE.fullmatch(p['credential_ref']):
            raise ValueError('credential_ref must be a local credential name')
        for key,low,high in [('timeout_seconds',0,600), ('retry_delay_seconds',0,30)]:
            v=p[key]
            if type(v) not in (int,float) or not low <= v <= high or not math.isfinite(v) or key=='timeout_seconds' and v==0:
                raise ValueError('invalid profile '+key)
        if 'temperature' in params:
            v = params['temperature']
            if type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 or round(v, 2) != v:
                raise ValueError('temperature must be 0–1 with at most two decimal places')
        for key, high in [('max_attempts', 3), ('max_completion_tokens', 1048576), ('max_tokens', 131072)]:
            v = p[key] if key == 'max_attempts' else params.get(key)
            if key != 'max_attempts' and key not in params:
                continue
            if type(v) is not int or not 1 <= v <= high:
                raise ValueError('invalid profile '+key)


def selected(cfg, role):
    identity = (cfg['worker'] if role == 'worker' else cfg['roles'][role]).get('profile', 'codex')
    if identity == 'codex':
        return None
    rows = [p for p in cfg.get('model_profiles', []) if p['id'] == identity]
    if len(rows) != 1:
        raise ValueError('selected '+role+' profile is missing')
    return copy.deepcopy(rows[0])


def external_roles(cfg):
    return {role: p for role in ROLES if (p := selected(cfg, role)) is not None
            and p['service'] not in (CODEX_API, CODEX_ACCOUNT)}


def worker_model(cfg):
    p = selected(cfg, 'worker')
    return p['model'] if p else cfg['worker']['model']


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
    for role in (*ROLES, 'worker'):
        p = selected(cfg, role)
        if p is None or p['service'] == CODEX_ACCOUNT:
            continue
        if not credentials(p['service']).configured(p['credential_ref']):
            raise ValueError(role+' 的 '+LABELS[p['service']]+'凭据未配置；请在模型页保存对应服务的凭据')
        if p['service'] == CODING_SERVICE:
            from .native_models import claude_executable
            claude_executable()


def connection_status(cfg):
    from .credentials import credentials, CredentialError
    rows=[]
    for p in cfg.get('model_profiles',[]):
        row={k:p[k] for k in ('id','service','endpoint','model','credential_ref')}
        row['label'] = p.get('label', p['id'])
        try:
            row['credential_status']=('native' if p['service'] == CODEX_ACCOUNT else
                                      'configured' if credentials(p['service']).configured(p['credential_ref']) else 'missing')
        except CredentialError:
            row['credential_status']='unavailable'
        row.update(configuration='saved', offline_check='valid', live_check='not_run', verified_roles=[])
        rows.append(row)
    return rows
