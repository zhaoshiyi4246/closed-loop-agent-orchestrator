"""Native authentication and semantic invocations; no native tool controls CLAO.

Codex uses its documented per-invocation API key or existing account. GLM
Coding Plan uses the actual Claude Code CLI and vendor Anthropic endpoint,
never CLAO's Chat Completions transport. No login cache is copied or edited.
"""
import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .credentials import credentials, CredentialError
from .diagnostics import model_attempt
from .execution_control import checkpoint, run
from .model_profiles import (validate_profiles, CODEX_API, CODEX_ACCOUNT,
                             CODING_SERVICE, CODING_ENDPOINT, CLAUDE_ACCOUNT, CLAUDE_API)
from .structured import (ProtocolError, ContractConfigurationError, parse_json,
                         check_schema, schema_validator, evidence_part, require_complete)


def process_environment():
    # Explicit infrastructure only: never inherit arbitrary provider credentials,
    # native routing overrides, plugins, proxy credentials or unrelated env.
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP',
               'USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'PROGRAMFILES',
               'PROGRAMFILES(X86)', 'PROGRAMDATA', 'LANG', 'LC_ALL', 'CODEX_HOME'}
    return {k: v for k, v in os.environ.items() if k.upper() in allowed}


def key_for(profile):
    try:
        value = credentials(profile['service']).read(profile['credential_ref'])
    except CredentialError:
        raise ProtocolError('AUTH', '所选连接的系统凭据不可用') from None
    if not value:
        raise ProtocolError('AUTH', '所选连接未配置 API Key')
    return value


def authenticate_client(client, profile, timeout=30):
    if profile and profile['service'] == CODEX_API:
        # App Server's ephemeral credential store keeps this key out of the
        # environment inherited by Worker shell commands and global auth files.
        result = client.request('account/login/start', {'type': 'apiKey', 'apiKey': key_for(profile)}, timeout)
        if result.get('type') != 'apiKey':
            raise ValueError('Codex 未确认 API 认证方式')


def client_config(profile):
    if profile and profile['service'] == CODEX_API:
        return ['cli_auth_credentials_store="ephemeral"', 'model_provider="openai"']
    if profile and profile['service'] == CODEX_ACCOUNT:
        return ['model_provider="openai"']
    return []


def claude_executable():
    executable = shutil.which('claude')
    if not executable:
        raise ValueError('需要安装官方 Claude Code；模型页提供安装说明')
    return executable


def check_claude(executable, env):
    try:
        result = run([executable, '--version'], capture_output=True, text=True,
                     timeout=15, env=env, encoding='utf-8', errors='replace')
    except (OSError, subprocess.TimeoutExpired):
        raise ProtocolError('CAPABILITY', 'Claude Code 版本检查失败') from None
    match = re.fullmatch(r'2\.1\.(\d+) \(Claude Code\)\s*', result.stdout)
    if result.returncode or not match or int(match[1]) < 205:
        raise ProtocolError('CAPABILITY', '需要 Claude Code 2.1.205 或更高的 2.1.x（严格结构化输出）；未自动安装或升级')


class NativeSemanticTransport:
    def __init__(self, profile):
        validate_profiles([profile])
        self.profile = copy.deepcopy(profile)
        # Native tools have their own HTTP retries. Do not multiply them with
        # CLAO's semantic retries; JSON/business validation still runs normally.
        self.retry_options = dict(max_attempts=1, retry_delay_seconds=0,
                                  retry_categories=set())

    def __call__(self, *, prompt, schema_path):
        p = self.profile
        if p['service'] in (CODEX_API, CODEX_ACCOUNT):
            from .codex_cli import run_codex_json
            return run_codex_json(prompt, schema_path, model=p['model'],
                                  timeout=p['timeout_seconds'], connection=p)
        if p['service'] not in (CODING_SERVICE, CLAUDE_ACCOUNT, CLAUDE_API):
            raise ContractConfigurationError('unsupported native semantic connection')
        require_complete({'role_prompt': evidence_part(prompt, 64000)})
        try:
            schema = json.loads(Path(schema_path).read_text('utf-8'))
        except (OSError, ValueError):
            raise ContractConfigurationError('semantic schema unavailable') from None
        schema_validator(schema)
        executable = claude_executable()
        env = process_environment()
        # Probe before obtaining the key. This process never sees credentials.
        check_claude(executable, env)
        checkpoint()
        key = None
        if p['service'] == CLAUDE_ACCOUNT:
            # --bare explicitly disables OAuth/keychain. Never pretend that a
            # successful auth probe makes a bare invocation use the account.
            help_result=run([executable,'--help'],capture_output=True,text=True,encoding='utf-8',
                            errors='strict',env=env,timeout=15)
            if help_result.returncode or '--safe-mode' not in help_result.stdout:
                raise ProtocolError('CAPABILITY','此 Claude Code 缺少保留账号认证的 --safe-mode；请按官方说明准备受支持版本')
            from .native_auth import status
            auth=status('claude-code')
            if auth['auth'] != 'connected' or auth.get('method')!='claude.ai':
                raise ProtocolError('AUTH', '需要在 Claude Code 完成原生账号登录')
            if os.environ.get('CLAUDE_CONFIG_DIR'):
                env['CLAUDE_CONFIG_DIR'] = os.environ['CLAUDE_CONFIG_DIR']
        else:
            key = key_for(p)
        with tempfile.TemporaryDirectory(prefix='clao-claude-') as directory:
            if p['service'] == CODING_SERVICE:
                env.update(ANTHROPIC_AUTH_TOKEN=key, ANTHROPIC_BASE_URL=CODING_ENDPOINT,
                           ANTHROPIC_DEFAULT_OPUS_MODEL=p['model'], ANTHROPIC_DEFAULT_SONNET_MODEL=p['model'],
                           ANTHROPIC_DEFAULT_HAIKU_MODEL=p['model'], CLAUDE_CONFIG_DIR=directory)
            elif p['service'] == CLAUDE_API:
                env.update(ANTHROPIC_API_KEY=key, ANTHROPIC_BASE_URL='https://api.anthropic.com',CLAUDE_CONFIG_DIR=directory)
            env.update(CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
                       CLAUDE_CODE_SKIP_PROMPT_HISTORY='1', DISABLE_AUTOUPDATER='1',
                       API_TIMEOUT_MS=str(math.ceil(p['timeout_seconds'] * 1000)))
            command = [executable, '--safe-mode' if p['service']==CLAUDE_ACCOUNT else '--bare', '--print', '--tools', '', '--disallowedTools', 'mcp__*',
                       '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                       '--setting-sources', '', '--no-session-persistence',
                       '--output-format', 'json', '--json-schema', json.dumps(schema),
                       '--max-turns', '1']
            if p['service']==CLAUDE_ACCOUNT:
                command.extend(['--settings', '{"disableAllHooks":true}'])
            if p['model']:
                command.extend(['--model', p['model']])
            with model_attempt(p['model'], transport='claude_code') as fact:
                if fact is not None:
                    fact.update(provider=p['service'], profile_id=p['id'], confirmed_model_source=None)
                try:
                    completed = run(command, input=prompt, cwd=directory, env=env, shell=False,
                                    capture_output=True, text=True, encoding='utf-8', errors='strict',
                                    timeout=p['timeout_seconds'])
                except subprocess.TimeoutExpired:
                    raise ProtocolError('TIMEOUT', 'Claude Code 等待超时；远端计算和计费状态未知') from None
                except (OSError, UnicodeError):
                    raise ProtocolError('NETWORK', 'Claude Code 执行未确认；输出已隐藏') from None
                finally:
                    env.pop('ANTHROPIC_AUTH_TOKEN', None)
                    env.pop('ANTHROPIC_API_KEY', None)
                checkpoint()
                if completed.returncode:
                    raise ProtocolError('CAPABILITY', 'Claude Code 未成功返回；请检查工具、套餐权限与模型，未切换服务')
                raw = completed.stdout
                if len(raw.encode('utf-8')) > 2 * 1024 * 1024:
                    raise ProtocolError('TRUNCATED', 'native response exceeds complete response bound')
                if key and key in raw:
                    raise ProtocolError('CAPABILITY', 'response contains credential material; withheld')
                envelope = parse_json(raw)
                if not isinstance(envelope, dict) or envelope.get('type') != 'result':
                    raise ProtocolError('CAPABILITY', 'Claude Code result envelope missing')
                if envelope.get('is_error') or envelope.get('subtype') != 'success':
                    raise ProtocolError('CAPABILITY', 'Claude Code 未完成结构化结果；未采用错误正文或工具结果')
                result = envelope.get('structured_output')
                if not isinstance(result, dict):
                    raise ProtocolError('JSON_PARSE', 'Claude Code structured_output missing')
                if key and key in json.dumps(result, ensure_ascii=False):
                    raise ProtocolError('CAPABILITY', 'response contains credential material; withheld')
                check_schema(result, schema)
                if fact is not None:
                    # Native usage is tool-reported, never an invented bill or
                    # evidence that a particular vendor quota was charged.
                    usage = envelope.get('usage')
                    if isinstance(usage, dict):
                        fact['usage'] = {k: v for k, v in usage.items() if k in ('input_tokens', 'output_tokens')
                                         and type(v) is int and v >= 0} or None
                    fact['result'] = 'native structured response validated; billing source unconfirmed'
                checkpoint()
                return result
