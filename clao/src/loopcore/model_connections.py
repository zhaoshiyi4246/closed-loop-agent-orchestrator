"""Panel connection editing and read-only catalogs; defaults remain authoritative."""
import copy
import json
import re
import secrets
import shutil
import tempfile
import threading
import time
import urllib.request

from .model_profiles import (ENDPOINTS, LABELS, NEW_KEYS, MODEL_ID, validate_profiles,
                             CODEX_API, CODEX_ACCOUNT, CODING_SERVICE,
                             SERVICE, KIMI_SERVICE, CLAUDE_ACCOUNT, CLAUDE_API, NATIVE_ACCOUNTS, NATIVE_DEFAULTS, TERMINAL_SERVICES)
from .effective_config import resolve_config

SERVICES = [dict(id=s, label=LABELS[s], endpoint=ENDPOINTS[s],
                 recommended_model=('glm-5.3' if s in (SERVICE, CODING_SERVICE) else
                                'kimi-k3' if s == KIMI_SERVICE else 'sonnet' if s in (CLAUDE_ACCOUNT, CLAUDE_API) else 'gpt-5.6-sol'),
                 billing=('native_account' if s in NATIVE_ACCOUNTS else 'subscription' if s == CODING_SERVICE else 'api'),
                 executor=('claude_code' if s in (CODING_SERVICE, CLAUDE_ACCOUNT, CLAUDE_API) else 'codex' if s in (CODEX_API, CODEX_ACCOUNT) else 'chat_completions'),
                 roles=(['worker', 'planner', 'auditor', 'verifier'] if s in (CODEX_API, CODEX_ACCOUNT) else ['planner', 'auditor', 'verifier']))
            for s in (CODEX_ACCOUNT, CODEX_API, CLAUDE_ACCOUNT, CLAUDE_API, SERVICE, CODING_SERVICE, KIMI_SERVICE)]
SERVICES += [dict(id=s, label=LABELS[s], endpoint=ENDPOINTS[s], recommended_model=None,
                 billing='native_account', executor=name, roles=[], terminal=True)
             for s,name in TERMINAL_SERVICES.items()]


class CatalogUnavailable(ValueError):
    """Only locally authored, safe reasons may reach the connection UI."""
    def __init__(self, reason, status):
        super().__init__(reason)
        self.status = status


def edit_connection(panel, body):
    """One validated default update, with a new OS credential identity on change.

    Never enumerate, migrate or overwrite old credentials: a frozen Mission
    retains its original service/ref. Only a newly allocated key is rolled back.
    """
    from .credentials import credentials
    with panel.lock:
        cfg = panel.defaults()
        if body.get('revision') != cfg.snapshot()['revision']:
            raise ValueError('默认设置已改变，请重新读取连接后保存')
        profiles = copy.deepcopy(cfg.get('model_profiles', []))
        identity = body.get('id')
        previous = next((p for p in profiles if p['id'] == identity), None)
        if identity is not None and previous is None:
            raise ValueError('找不到目标连接')
        if body.get('action') == 'delete':
            if set(body) != {'action', 'id', 'revision'} or previous is None:
                raise ValueError('连接删除参数不完整')
            return panel.set_config({'model_profiles': [p for p in profiles if p['id'] != identity]})
        fields = {'action', 'revision', 'id', 'label', 'service', 'model', 'parameters',
                  'timeout_seconds', 'max_attempts', 'retry_delay_seconds', 'key'}
        if body.get('action') != 'save' or set(body) - fields or not fields - {'id', 'key'} <= set(body):
            raise ValueError('连接参数不完整或包含不支持的字段')
        service = body['service']
        if service not in ENDPOINTS:
            raise ValueError('不支持的服务')
        # Changing a service needs a new key even when the visible name matches.
        value = body.get('key')
        new_key = value is not None and value != ''
        if service in NATIVE_ACCOUNTS and new_key:
            raise ValueError('原生认证由所选工具管理，不接收账号 token')
        same_service = previous and previous['service'] == service
        ref = ('native' if service in NATIVE_ACCOUNTS else 'c-' + secrets.token_hex(12) if new_key
               else previous['credential_ref'] if same_service else None)
        if ref is None:
            raise ValueError('请为所选服务填写 API Key')
        profile = {k: body[k] for k in NEW_KEYS if k in body}
        profile.update(id=identity or 'c-' + secrets.token_hex(12), credential_ref=ref, endpoint=ENDPOINTS[service])
        validate_profiles([profile])
        if service in TERMINAL_SERVICES and profile['model'] and (previous is None or not same_service or previous['model']!=profile['model']):
            from .native_catalog import CUSTOM_DIRECT
            if TERMINAL_SERVICES[service] not in CUSTOM_DIRECT:
                catalog=panel.model_catalogs.draft(service)
                if catalog['status']!='ready' or profile['model'] not in {m['id'] for m in catalog['models']}:
                    raise ValueError('此执行器需要从原生目录选择；自定义型号须先在原生工具中配置并刷新')
        profiles = [profile if p['id'] == identity else p for p in profiles]
        if previous is None:
            profiles.append(profile)
        updates = {'model_profiles': profiles}
        resolve_config(cfg, overrides=updates)  # Before storing even the new key.
        vault = credentials(service) if new_key else None
        if vault:
            vault.save(ref, value)
        try:
            return panel.set_config(updates)
        except BaseException:
            if vault:
                vault.delete(ref)
            raise


def public_document(url):
    # Fixed unauthenticated official URLs only; redirects cannot forward keys.
    with urllib.request.urlopen(url, timeout=20) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('模型目录过大')
    return raw.decode('utf-8')


class ModelCatalogs:
    def __init__(self):
        self.lock = threading.RLock()
        self.cache = {}

    @staticmethod
    def fingerprint(profile):
        # Keys never participate, while a newly saved key gets a new ref.
        return tuple(profile.get(k) for k in ('service', 'endpoint', 'credential_ref'))

    def read(self, profile):
        with self.lock:
            entry = copy.deepcopy(self.cache.get(self.fingerprint(profile)))
        if entry:
            entry['stale'] = entry.get('status') == 'read_error' or time.time() - (entry.get('fetched_at') or 0) > 600
            return entry
        return dict(models=[], source='not_checked',
                    status='not_checked', fetched_at=None, stale=True, error=None,
                    custom_model=True, connection_status='configured')

    def draft(self, service, secret=None):
        """Discover before saving a connection; secret lives only in this call.

        Draft results are not cached server-side and never create a credential
        reference or a model profile. Saved catalogs use their existing ref.
        """
        if service not in ENDPOINTS:
            raise ValueError('不支持的服务')
        profile = dict(service=service, endpoint=ENDPOINTS[service], credential_ref=None, model='')
        try:
            return self._entry(profile, secret)
        except Exception as exc:
            return self._failure(self.read(profile), exc)

    @staticmethod
    def _failure(prior, exc):
        return dict(prior, status='read_error', stale=True,
                    connection_status=exc.status if isinstance(exc, CatalogUnavailable) else 'failed',
                    error=str(exc) if isinstance(exc, CatalogUnavailable) else
                    '目录读取失败；保留当前选择，请检查连接后重试。')

    def _entry(self, profile, secret=None):
        models, source, connected = self._discover(profile, secret)
        rows, seen = [], set()
        for value in models:
            row = dict(id=value, label=value) if isinstance(value, str) else value
            if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not MODEL_ID.fullmatch(row['id']) or row['id'] in seen:
                continue
            seen.add(row['id'])
            # Only documented public metadata, never arbitrary server objects.
            normalized = {k: row[k] for k in ('id', 'label', 'description', 'provider')
                          if isinstance(row.get(k), str) and len(row[k]) <= 1000}
            normalized['is_default'] = row.get('is_default') is True
            normalized['label'] = normalized.get('label') or row['id']
            rows.append(normalized)
        if models and not rows:
            raise ValueError('无法识别模型目录')
        if len(rows) > 2000:
            raise ValueError('模型目录过大')
        from .native_catalog import CUSTOM_DIRECT, CUSTOM_CONFIGURED
        executor = TERMINAL_SERVICES.get(profile['service'])
        return dict(models=rows, source=source, status='ready' if rows else 'empty',
                    fetched_at=time.time(), stale=False, error=None,
                    custom_model=executor is None or executor in CUSTOM_DIRECT | CUSTOM_CONFIGURED,
                    custom_requires_configuration=executor in CUSTOM_CONFIGURED,
                    executor_default=profile['service'] in NATIVE_DEFAULTS,
                    connection_status='connected' if connected else 'configured')

    def refresh(self, profile):
        key = self.fingerprint(profile)
        initial_entry = self.cache.get(key)
        # Concurrent refreshes reuse the result that arrived after they started.
        # Catalog reads never create a thread.
        with self.lock:
            prior = self.read(profile)
            if self.cache.get(key) is not initial_entry:
                return prior
            try:
                entry = self._entry(profile)
            except Exception as exc:
                # Supplier bodies and native output may echo auth; do not expose.
                entry = self._failure(prior, exc)
            self.cache[key] = entry
            return copy.deepcopy(entry)

    def _discover(self, profile, secret=None):
        service = profile['service']
        if service in TERMINAL_SERVICES:
            from .native_catalog import discover
            models, source = discover(TERMINAL_SERVICES[service])
            return models, source, False
        if service in (CLAUDE_ACCOUNT, CLAUDE_API):
            from .native_catalog import discover
            models, source = discover('claude-code')
            return models, source, False
        if service in (SERVICE, CODING_SERVICE):
            url = ('https://docs.bigmodel.cn/cn/guide/start/model-overview.md' if service == SERVICE else
                   'https://docs.bigmodel.cn/cn/coding-plan/latest-model.md')
            raw = public_document(url)
            # Only published GLM identifiers. Catalog availability says nothing
            # about account quota or the parameter capabilities below.
            return re.findall(r'\bglm-[a-zA-Z0-9]+(?:[.\-][a-zA-Z0-9]+)*', raw.lower()), url, False
        if service == KIMI_SERVICE:
            import http.client
            from .native_models import key_for
            key = secret or (key_for(profile) if profile['credential_ref'] else None)
            if not key:
                raise CatalogUnavailable('请先填写 Kimi API Key，再读取账号模型目录。', 'login_required')
            conn = http.client.HTTPSConnection('api.moonshot.cn', timeout=20)
            try:
                conn.request('GET', '/v1/models', headers={'Authorization': 'Bearer ' + key})
                response = conn.getresponse()
                raw = response.read(1024 * 1024 + 1)
                if response.status != 200 or len(raw) > 1024 * 1024 or key.encode() in raw:
                    raise ValueError('catalog unavailable')
                data = json.loads(raw)
                if key in json.dumps(data):
                    raise ValueError('catalog contains credential material')
                return [dict(id=m['id'], label=m['id'], provider=m.get('owned_by')) for m in data['data']], 'Moonshot GET /v1/models', True
            finally:
                conn.close()
        from .codex_backend import StdioClient
        from .native_models import client_config, authenticate_client
        executable = shutil.which('codex')
        if not executable:
            raise CatalogUnavailable('未找到 Codex；请按官方说明安装后重新检查。', 'unavailable')
        with tempfile.TemporaryDirectory(prefix='clao-model-list-') as directory:
            client = StdioClient(executable, directory, config=client_config(profile))
            try:
                client.initialize()
                if service == CODEX_API and secret:
                    if client.request('account/login/start', {'type': 'apiKey', 'apiKey': secret}).get('type') != 'apiKey':
                        raise CatalogUnavailable('Codex 未确认 API 认证方式', 'login_required')
                elif service == CODEX_API and not profile['credential_ref']:
                    raise CatalogUnavailable('请先填写 OpenAI API Key，再读取模型目录。', 'login_required')
                else:
                    authenticate_client(client, profile)
                account = client.request('account/read', {'refreshToken': False})
                if (account.get('account') or {}).get('type') != ('apiKey' if service == CODEX_API else 'chatgpt'):
                    raise CatalogUnavailable('需要登录所选 Codex 账号；请使用官方 codex login，未自动切换账号。', 'login_required')
                models, cursor = [], None
                for _ in range(20):
                    page = client.request('model/list', {'cursor': cursor, 'limit': 100})
                    models.extend(dict(id=m['model'], label=m.get('displayName', m['model']),
                                       description=m.get('description'), is_default=m.get('isDefault', False))
                                  for m in page['data'])
                    cursor = page.get('nextCursor')
                    if cursor is None:
                        return models, 'Codex 0.150.1 model/list', True
                raise ValueError('incomplete model catalog')
            finally:
                client.close()
