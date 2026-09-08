"""BigModel general Chat Completions, non-streaming glm-4.7 only.

One call per attempt. The existing role protocol boundary owns the *entire*
retry budget. No redirects, fallback, tools, child environment or prompt logs.
"""
import copy
import http.client
import json
from pathlib import Path
import re
import socket
import threading
import time

from . import credentials
from .diagnostics import model_attempt
from .execution_control import checkpoint
from .model_profiles import validate_profiles, SERVICE
from .structured import (ProtocolError, ContractConfigurationError, parse_json,
                         check_schema, schema_validator, evidence_part, require_complete)


class BigModelTransport:
    def __init__(self, profile):
        validate_profiles([profile])
        self.profile = copy.deepcopy(profile)
        self.retry_options = dict(max_attempts=profile['max_attempts'],
            retry_delay_seconds=profile['retry_delay_seconds'],
            retry_categories={'NETWORK', 'TIMEOUT', 'RATE_LIMIT', 'JSON_PARSE',
                              'SCHEMA', 'CORRELATION', 'COHERENCE'})

    def __call__(self, *, prompt, schema_path):
        p = self.profile
        require_complete({'role_prompt': evidence_part(prompt, 64000)})
        try:
            schema = json.loads(Path(schema_path).read_text('utf-8'))
        except (OSError, ValueError):
            raise ContractConfigurationError('semantic JSON schema unavailable') from None
        schema_validator(schema)
        # JSON mode is a transport capability, not a substitute for our schemas.
        body = json.dumps(dict(model=p['model'], stream=False,
            messages=[{'role': 'system', 'content': 'Return only a JSON object matching this schema:\n' + json.dumps(schema)},
                      {'role': 'user', 'content': prompt}],
            response_format={'type': 'json_object'}, thinking={'type': p['thinking']},
            temperature=p['temperature'], max_tokens=p['max_tokens']), ensure_ascii=False).encode('utf-8')
        with model_attempt(p['model'], transport='bigmodel_https') as fact:
            if fact is not None:
                fact.update(provider=SERVICE, profile_id=p['id'], confirmed_model_source=None)
            checkpoint()
            try:
                key = credentials.credentials().read(p['credential_ref'])
            except credentials.CredentialError:
                raise ProtocolError('AUTH', 'Windows credential unavailable; configure the selected reference') from None
            if not key:
                raise ProtocolError('AUTH', 'selected credential is not configured')
            status, raw = self._exchange(body, key)
            checkpoint()
            if status != 200:
                category = ('AUTH' if status in (401, 403) else 'RATE_LIMIT' if status == 429 else
                            'TIMEOUT' if status == 408 else 'NETWORK' if 500 <= status <= 599 else 'CAPABILITY')
                # Do not retain provider bodies, headers or echoed inputs.
                raise ProtocolError(category, 'BigModel HTTP status %d; response body withheld' % status)
            if key.encode() in raw:
                raise ProtocolError('CAPABILITY', 'response contains credential material; withheld')
            try:
                envelope = parse_json(raw.decode('utf-8'))
            except UnicodeError:
                raise ProtocolError('JSON_PARSE', 'response is not UTF-8 JSON') from None
            if not isinstance(envelope, dict):
                raise ProtocolError('JSON_PARSE', 'response envelope is not an object')
            if key in json.dumps(envelope, ensure_ascii=False):
                raise ProtocolError('CAPABILITY', 'response contains credential material; withheld')
            if fact is not None:
                model = envelope.get('model')
                if isinstance(model, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,127}', model):
                    fact.update(confirmed_model=model, confirmed_model_source='Chat Completions response.model')
                usage = envelope.get('usage')
                if isinstance(usage, dict):
                    fact['usage'] = {k: usage[k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                                     if type(usage.get(k)) is int and usage[k] >= 0} or None
            choices = envelope.get('choices')
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ProtocolError('CAPABILITY', 'expected exactly one completion choice')
            choice = choices[0]
            message = choice.get('message')
            if not isinstance(message, dict) or message.get('role') != 'assistant':
                raise ProtocolError('CAPABILITY', 'assistant message missing')
            if message.get('refusal') or choice.get('finish_reason') in ('content_filter', 'sensitive'):
                raise ProtocolError('REFUSAL', 'provider refused or filtered the response')
            if choice.get('finish_reason') == 'length':
                raise ProtocolError('TRUNCATED', 'provider output token limit reached; incomplete evidence is not PASS')
            if choice.get('finish_reason') != 'stop' or message.get('tool_calls') or message.get('function_call'):
                raise ProtocolError('CAPABILITY', 'only complete text responses are supported; tools are not executed')
            content = message.get('content')
            if not isinstance(content, str) or not content.strip():
                raise ProtocolError('JSON_PARSE', 'formal message.content missing; reasoning is not a role result')
            result = parse_json(content)
            if key in json.dumps(result, ensure_ascii=False):
                raise ProtocolError('CAPABILITY', 'response contains credential material; withheld')
            check_schema(result, schema)
            checkpoint()
            if fact is not None:
                fact['result'] = 'structured response validated; role correlation/coherence checked by caller'
            return result

    def _exchange(self, body, key):
        """Interruptible wait; discard late results, never claim remote compute stopped."""
        timeout = self.profile['timeout_seconds']
        conn = http.client.HTTPSConnection('open.bigmodel.cn', timeout=timeout)
        done = threading.Event()
        answer = []
        abandoned = threading.Event()

        def request():
            try:
                if abandoned.is_set():
                    return
                conn.connect()
                if abandoned.is_set():
                    return
                conn.request('POST', '/api/paas/v4/chat/completions', body,
                             {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
                response = conn.getresponse()
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    answer.append(ProtocolError('TRUNCATED', 'HTTP response exceeds complete response bound'))
                else:
                    answer.append((response.status, raw))
            except (TimeoutError, socket.timeout):
                answer.append(ProtocolError('TIMEOUT', 'BigModel response timeout; remote computation may continue'))
            except Exception:
                answer.append(ProtocolError('NETWORK', 'BigModel transport failed; remote computation may continue'))
            finally:
                conn.close()
                done.set()

        checkpoint()
        thread = threading.Thread(target=request, daemon=True, name='clao-bigmodel-request')
        thread.start()
        end = time.monotonic() + timeout
        try:
            while not done.wait(0.05):
                checkpoint()
                if time.monotonic() >= end:
                    raise ProtocolError('TIMEOUT', 'BigModel response timeout; remote computation may continue')
            checkpoint()
            if not answer:
                raise ProtocolError('NETWORK', 'request did not return a result')
            if isinstance(answer[0], ProtocolError):
                raise answer[0]
            return answer[0]
        finally:
            abandoned.set()
            if not done.is_set() and conn.sock is not None:
                try:
                    conn.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


def role_options(cfg, role):
    """One selector used by normal, decomposition and resume assembly."""
    from .model_profiles import selected
    profile = selected(cfg, role)
    if profile is None:
        return dict(model=cfg['roles'][role]['model'], timeout=cfg['roles'][role]['timeout_seconds'])
    return dict(model=profile['model'], timeout=profile['timeout_seconds'], transport=BigModelTransport(profile))
