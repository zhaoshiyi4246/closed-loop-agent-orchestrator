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
                             SERVICE, KIMI_SERVICE)
from .effective_config import resolve_config

SERVICES = [dict(id=s, label=LABELS[s], endpoint=ENDPOINTS[s],
                 default_model=('glm-5.3' if s in (SERVICE, CODING_SERVICE) else
                                'kimi-k3' if s == KIMI_SERVICE else 'gpt-5.6-sol'),
                 billing=('subscription' if s in (CODEX_ACCOUNT, CODING_SERVICE) else 'api'),
                 executor=('claude_code' if s == CODING_SERVICE else 'codex' if s in (CODEX_API, CODEX_ACCOUNT) else 'chat_completions'),
                 roles=(['worker', 'planner', 'auditor', 'verifier'] if s in (CODEX_API, CODEX_ACCOUNT) else ['planner', 'auditor', 'verifier']))
            for s in (CODEX_ACCOUNT, CODEX_API, SERVICE, CODING_SERVICE, KIMI_SERVICE)]


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
        if service == CODEX_ACCOUNT and new_key:
            raise ValueError('账号登录使用官方 Codex，不接收账号 token')
        same_service = previous and previous['service'] == service
        ref = ('native' if service == CODEX_ACCOUNT else 'c-' + secrets.token_hex(12) if new_key
               else previous['credential_ref'] if same_service else None)
        if ref is None:
            raise ValueError('请为所选服务填写 API Key')
        profile = {k: body[k] for k in NEW_KEYS if k in body}
        profile.update(id=identity or 'c-' + secrets.token_hex(12), credential_ref=ref, endpoint=ENDPOINTS[service])
        validate_profiles([profile])
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
            for model in entry['models']:
                model['is_default'] = model['id'] == profile['model']
            entry['stale'] = entry.get('status') == 'read_error' or time.time() - (entry.get('fetched_at') or 0) > 600
            return entry
        model = profile['model']
        return dict(models=[dict(id=model, label=model, is_default=True)], source='configured',
                    status='not_checked', fetched_at=None, stale=True, error=None,
                    custom_model=True, connection_status='configured')

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
                models, source, connected = self._discover(profile)
                ids = list(dict.fromkeys(m for m in models if isinstance(m, str) and MODEL_ID.fullmatch(m)))
                if not ids:
                    raise ValueError('服务没有提供可识别的模型目录')
                entry = dict(models=[dict(id=m, label=m, is_default=m == profile['model']) for m in ids[:2000]],
                             source=source, status='ready', fetched_at=time.time(), stale=False, error=None,
                             custom_model=True, connection_status='connected' if connected else 'configured')
            except Exception as exc:
                # Supplier bodies and native output may echo auth; do not expose.
                entry = dict(prior, status='read_error', stale=True,
                             connection_status=exc.status if isinstance(exc, CatalogUnavailable) else 'failed',
                             error=str(exc) if isinstance(exc, CatalogUnavailable) else
                             '目录刷新失败；保留上次列表，可重试或填写模型 ID。请检查连接、登录和工具。')
            self.cache[key] = entry
            return copy.deepcopy(entry)

    def _discover(self, profile):
        service = profile['service']
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
            key = key_for(profile)
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
                return [m['id'] for m in data['data']], 'Moonshot GET /v1/models', True
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
                authenticate_client(client, profile)
                account = client.request('account/read', {'refreshToken': False})
                if (account.get('account') or {}).get('type') != ('apiKey' if service == CODEX_API else 'chatgpt'):
                    raise CatalogUnavailable('需要登录所选 Codex 账号；请使用官方 codex login，未自动切换账号。', 'login_required')
                models, cursor = [], None
                for _ in range(20):
                    page = client.request('model/list', {'cursor': cursor, 'limit': 100})
                    models.extend(m['model'] for m in page['data'])
                    cursor = page.get('nextCursor')
                    if cursor is None:
                        return models, 'Codex 0.150.1 model/list', True
                raise ValueError('incomplete model catalog')
            finally:
                client.close()
