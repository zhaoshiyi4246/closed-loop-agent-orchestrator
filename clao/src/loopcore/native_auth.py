"""Native login entry points adapted from AO v0.12.12 agentauth/plans.go.

Apache-2.0; see clao/AO-LICENSE.txt. Commands are fixed product policy. The
user completes native authentication; CLAO neither records terminal input nor
copies login state. Starting login does not mean authentication succeeded.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .native_catalog import BINARY, REGISTRY, native_environment


class NativeLogins:
    def __init__(self):
        self.lock = threading.RLock()
        self.running = {}

    def start(self, identity):
        if identity not in REGISTRY:
            raise ValueError('未知执行器')
        plan = PLANS[identity]
        if not plan['argv']:
            raise ValueError('此工具没有原生登录命令，请按其认证说明配置')
        if os.name != 'nt':
            raise ValueError('当前登录窗口仅支持 Windows')
        binary = shutil.which(BINARY[identity])
        if not binary:
            raise ValueError('PATH 中未找到 '+BINARY[identity]+'；请检查原生工具安装与 PATH')
        with self.lock:
            previous = self.running.get(identity)
            if previous is not None and previous.poll() is None:
                return dict(state='waiting', instruction=plan['input'])
            # Fixed argv, literal PowerShell strings, no URL/key/browser command
            # interpolation. Native terminal owns secret entry and storage.
            quote = lambda value: "'" + value.replace("'", "''") + "'"
            script = '& ' + ' '.join(quote(v) for v in [binary, *plan['argv'][1:]])
            encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
            process = subprocess.Popen(['powershell.exe','-NoProfile','-NoExit','-EncodedCommand',encoded],
                                       cwd=tempfile.gettempdir(), env=native_environment(identity),
                                       creationflags=subprocess.CREATE_NEW_CONSOLE,
                                       stdin=None, stdout=None, stderr=None, close_fds=True)
            self.running[identity] = process
            return dict(state='waiting', instruction=plan['input'])


def status(identity):
    if identity not in REGISTRY:
        raise ValueError('未知执行器')
    binary = shutil.which(BINARY[identity])
    result = dict(installed=bool(binary), auth='unknown', documentation=PLANS[identity]['documentation'],
                  login_supported=bool(PLANS[identity]['argv']))
    if not binary:
        result['auth'] = 'not_checked'
        return result
    try:
        with tempfile.TemporaryDirectory(prefix='clao-auth-status-') as directory:
            if identity == 'codex':
                from .codex_backend import StdioClient
                client = StdioClient(binary, directory)
                try:
                    client.initialize()
                    account = client.request('account/read', {'refreshToken':False})
                    result['auth'] = 'connected' if account.get('account') else 'login_required'
                    result['method'] = (account.get('account') or {}).get('type')
                finally:
                    client.close()
            elif identity == 'claude-code':
                environment=native_environment(identity)
                response = subprocess.run([binary,'auth','status'],cwd=directory,env=environment,
                                          capture_output=True,text=True,encoding='utf-8',timeout=10)
                if len(response.stdout)>65536:
                    raise ValueError('status response too large')
                fact = json.loads(response.stdout)
                if type(fact.get('loggedIn')) is bool:
                    result['auth'] = 'connected' if fact['loggedIn'] else 'login_required'
                result['method'] = fact.get('authMethod') if fact.get('authMethod') in ('claude.ai','api_key','none') else None
            elif identity in ('cursor','devin','kiro'):
                argv={'cursor':['status'],'devin':['auth','status'],'kiro':['whoami','--format','json']}[identity]
                response=subprocess.run([binary,*argv],cwd=directory,env=native_environment(identity),
                                        capture_output=True,text=True,encoding='utf-8',timeout=10)
                if len(response.stdout)+len(response.stderr)>65536:raise ValueError('status response too large')
                # Only status categories escape this boundary; never identity,
                # token-shaped output or CLI error bodies. Negative wins.
                raw=(response.stdout+'\n'+response.stderr).lower()
                compact=re.sub(r'\s+','',raw)
                if any(v in raw for v in ('not logged in','not authenticated','unauthenticated','unauthorized','login required','no credentials')) or re.search(r'"(?:loggedin|logged_in|authenticated|authorized)":false',compact):
                    result['auth']='login_required'
                elif response.returncode==0 and (re.search(r'"(?:loggedin|logged_in|authenticated|authorized)":true',compact) or any(v in raw for v in ('logged in as','successfully authenticated'))):
                    result['auth']='connected'
            # Other native tools lack a uniform public auth fact. In particular
            # do not port AO's OMP/Kilo private database or token-file probes.
    except Exception:
        result['auth'] = 'unknown'
        result['error'] = '登录状态无法确认；请在原生工具中完成连接后重新检查'
    return result

PLANS = {'claude-code': {'argv': ['claude', 'auth', 'login'],
                 'documentation': 'https://code.claude.com/docs/en/installation',
                 'input': None},
 'codex': {'argv': ['codex', 'login'], 'documentation': 'https://github.com/openai/codex', 'input': None},
 'cursor': {'argv': ['cursor-agent', 'login'],
            'documentation': 'https://docs.cursor.com/en/cli/installation',
            'input': None},
 'opencode': {'argv': ['opencode', 'auth', 'login'],
              'documentation': 'https://github.com/anomalyco/opencode',
              'input': None},
 'aider': {'argv': [], 'documentation': 'https://aider.chat/docs/config/api-keys.html', 'input': None},
 'copilot': {'argv': ['copilot', 'login'],
             'documentation': 'https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli',
             'input': None},
 'grok': {'argv': ['grok', 'login'], 'documentation': 'https://docs.x.ai/build/overview', 'input': None},
 'kimi': {'argv': ['kimi', 'login'],
          'documentation': 'https://moonshotai.github.io/kimi-code/en/',
          'input': None},
 'pi': {'argv': ['pi'], 'documentation': 'https://github.com/earendil-works/pi', 'input': '/login'},
 'amp': {'argv': ['amp', 'login'], 'documentation': 'https://ampcode.com/manual', 'input': None},
 'auggie': {'argv': ['auggie', 'login'],
            'documentation': 'https://docs.augmentcode.com/cli/overview',
            'input': None},
 'droid': {'argv': ['droid'],
           'documentation': 'https://docs.factory.ai/droid-cli/cli-reference',
           'input': '/login'},
 'crush': {'argv': ['crush', 'login'],
           'documentation': 'https://github.com/charmbracelet/crush',
           'input': None},
 'cline': {'argv': ['cline', 'auth'], 'documentation': 'https://github.com/cline/cline', 'input': None},
 'goose': {'argv': ['goose', 'configure'],
           'documentation': 'https://block.github.io/goose/index.html',
           'input': None},
 'qwen': {'argv': ['qwen'],
          'documentation': 'https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/',
          'input': '/auth'},
 'continue': {'argv': ['cn', 'login'],
              'documentation': 'https://docs.continue.dev/cli/quickstart',
              'input': None},
 'devin': {'argv': ['devin', 'auth', 'login'],
           'documentation': 'https://docs.devin.ai/get-started/devin-intro',
           'input': None},
 'kiro': {'argv': ['kiro-cli', 'login'],
          'documentation': 'https://kiro.dev/docs/getting-started/installation/',
          'input': None},
 'kilocode': {'argv': ['kilo', 'auth', 'login'],
              'documentation': 'https://kilo.ai/docs/code-with-ai/platforms/cli',
              'input': None},
 'vibe': {'argv': ['vibe', '--setup'],
          'documentation': 'https://github.com/mistralai/mistral-vibe',
          'input': None},
 'muse': {'argv': ['muse', 'login'], 'documentation': 'https://ai.meta.com/llama/', 'input': None},
 'agy': {'argv': ['agy'],
         'documentation': 'https://github.com/google-antigravity/antigravity-cli',
         'input': None},
 'autohand': {'argv': ['autohand', 'login'],
              'documentation': 'https://docs.autohand.ai/working-with-autohand-code/cli-reference',
              'input': None},
 'kimchi': {'argv': ['kimchi', 'login'],
            'documentation': 'https://docs.kimchi.dev/docs/service-keys',
            'input': None},
 'prime-agent': {'argv': ['prime-agent'],
                 'documentation': 'https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/quickstart.md',
                 'input': '/login'},
 'omp': {'argv': ['omp'], 'documentation': 'https://github.com/can1357/oh-my-pi', 'input': '/login'}}
