"""Explicit, bounded synthetic Kimi native/CLAO comparison; never auto-run.

Both workers use the official installed CLI, the same source, objective and
external Gate. A test-only single-request transport meters every paid socket;
the CLAO semantic core uses the same ledger. No secret is put in argv or files.
"""
import argparse
import copy
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
import math
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'clao' / 'src'))
import yaml
from loopcore.credentials import credentials

budget_helpers = runpy.run_path(str(ROOT / 'dev/native/live-core-budget.py'))
accounted_total_micros = budget_helpers['accounted_total_micros']
service_ready = budget_helpers['service_ready']

OBJECTIVE = ('Fix solution.py so add(a, b) returns integer addition, including positive, negative and zero inputs. '
             'Only edit solution.py. Its current complete content is: def add(a, b): return a - b. '
             'Do not modify check.py or create extra files. The independent acceptance check is python check.py.')
SOURCE = {'solution.py': 'def add(a, b):\n    return a - b\n',
          'check.py': 'from solution import add\nfor a,b in [(7,2),(-2,5),(0,0),(-3,-4)]:\n    assert add(a,b)==a+b\nprint("SYNTHETIC_ADD_GATE_OK")\n'}


def create_private_test_home(path):
    """Atomically create a new test-owned Windows home; never repair an existing ACL."""
    if os.name != 'nt':
        raise RuntimeError('This acceptance harness requires Windows')
    sid = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],
        check=True, capture_output=True, text=True, timeout=15).stdout.strip()
    if not sid.startswith('S-1-5-') or any(part and not part.isdecimal() for part in sid.split('-')[1:]):
        raise RuntimeError('Cannot identify isolated test owner')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    class Attributes(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('descriptor', ctypes.c_void_p), ('inherit', wintypes.BOOL)]
    kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(Attributes)]
    kernel.CreateDirectoryW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    sddl = f'O:{sid}D:P(A;OICI;FA;;;{sid})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'
    if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise RuntimeError('Cannot prepare isolated test permissions')
    try:
        attributes = Attributes(ctypes.sizeof(Attributes), descriptor, False)
        if not kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)):
            raise RuntimeError('Private test home creation refused; existing objects remain unchanged')
    finally:
        kernel.LocalFree(descriptor)


class WindowsProcessTree:
    """Own a newly suspended process and descendants; never enumerate/kill peers."""
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('This acceptance harness requires Windows')
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        for name, args in {
            'SetInformationJobObject': [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
            'AssignProcessToJobObject': [wintypes.HANDLE, wintypes.HANDLE],
            'TerminateJobObject': [wintypes.HANDLE, wintypes.UINT],
            'QueryInformationJobObject': [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p],
            'CloseHandle': [wintypes.HANDLE],
        }.items():
            getattr(self.api, name).argtypes = args
            getattr(self.api, name).restype = wintypes.BOOL
        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', wintypes.DWORD),
                        ('min_working', ctypes.c_size_t), ('max_working', ctypes.c_size_t), ('active_limit', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', BasicLimits), ('io', ctypes.c_uint64 * 6), ('memory', ctypes.c_size_t * 4)]
        self.handle = self.api.CreateJobObjectW(None, None)
        self.process = None
        if not self.handle:
            raise RuntimeError('Cannot create isolated process job')
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.api.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError('Cannot protect isolated process job')

    def start(self, argv, **kwargs):
        if self.process is not None:
            raise RuntimeError('Process job already used')
        # CREATE_SUSPENDED prevents a child spawning before job assignment.
        self.process = subprocess.Popen(argv, creationflags=subprocess.CREATE_NO_WINDOW | 0x4, **kwargs)
        try:
            if not self.api.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(self.process._handle))):
                raise RuntimeError('Cannot contain isolated process')
            resume = ctypes.WinDLL('ntdll').NtResumeProcess
            resume.argtypes = [wintypes.HANDLE]
            resume.restype = wintypes.LONG
            if resume(wintypes.HANDLE(int(self.process._handle))) < 0:
                raise RuntimeError('Cannot resume isolated process')
            return self.process
        except Exception:
            self.process.kill()
            self.process.wait(timeout=10)
            self.stop()
            raise RuntimeError('Isolated process launch refused') from None

    def active_count(self):
        class Accounting(ctypes.Structure):
            _fields_ = [('times', ctypes.c_int64 * 4), ('faults', wintypes.DWORD), ('total', wintypes.DWORD),
                        ('active', wintypes.DWORD), ('terminated', wintypes.DWORD)]
        value = Accounting()
        if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
            raise RuntimeError('Cannot confirm isolated process stop')
        return value.active

    def stop(self):
        if self.handle is None:
            return getattr(self, 'stopped', False)
        self.stopped = False
        try:
            if not self.api.TerminateJobObject(self.handle, 1):
                raise RuntimeError('Cannot stop isolated process job')
            deadline = time.monotonic() + 15
            while self.active_count() != 0:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Isolated process stop unconfirmed')
                time.sleep(.02)
            if self.process is not None:
                self.process.wait(timeout=10)
            self.stopped = True
            return True
        finally:
            self.api.CloseHandle(self.handle)
            self.handle = None


def scope_facts(folder):
    folder = Path(folder)
    try:
        entries = list(folder.rglob('*'))
        if any(p.is_symlink() or getattr(p.lstat(), 'st_file_attributes', 0) & 0x400 for p in entries):
            return False, []
        files = {p.relative_to(folder).as_posix() for p in entries if p.is_file()}
        if files != set(SOURCE) or any(p.is_dir() for p in entries):
            return False, sorted(files)
        changed = [name for name, content in SOURCE.items() if (folder/name).read_bytes() != content.encode('utf-8')]
        return changed == ['solution.py'] and (folder/'check.py').read_bytes() == SOURCE['check.py'].encode('utf-8'), changed
    except OSError:
        return False, []


def safe_gate_env(env):
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP', 'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'}
    return {k: v for k, v in env.items() if k.upper() in allowed}


def run_gate(folder, env, runner=None):
    if not scope_facts(folder)[0]:
        return False
    argv = [sys.executable, '-B', 'check.py']
    if runner is not None or os.name != 'nt':
        result = (runner or subprocess.run)(argv, cwd=folder, env=safe_gate_env(env), capture_output=True, timeout=15)
        passed = result.returncode == 0 and b'SYNTHETIC_ADD_GATE_OK' in result.stdout
    else:
        tree = WindowsProcessTree()
        try:
            process = tree.start(argv, cwd=folder, env=safe_gate_env(env), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output, _ = process.communicate(timeout=15)
            passed = process.returncode == 0 and b'SYNTHETIC_ADD_GATE_OK' in output
        finally:
            tree.stop()
    return passed and scope_facts(folder)[0]


def valid_budget_evidence(ledger, case, mode):
    """Require actual metered worker/semantic calls, not only a working patch."""
    if not isinstance(ledger, dict) or ledger.get('frozen') or mode not in ('baseline', 'native'):
        return False
    attempts = ledger.get('attempts')
    if not isinstance(attempts, list) or len(attempts) > 40:
        return False
    if any(not isinstance(row, dict) or type(row.get('reserved_cny')) not in (int, float)
           or not math.isfinite(row['reserved_cny']) or row['reserved_cny'] < 0 for row in attempts):
        return False
    try:
        if not service_ready(ledger) or accounted_total_micros(ledger) > 20_000_000: return False
    except (ValueError, TypeError, KeyError):
        return False
    related = [row for row in attempts if isinstance(row.get('case'), str) and row['case'].startswith(case)]
    workers = [row for row in related if row['case'] == case]
    semantic = [row for row in related if row['case'] == case + ':semantic']
    limits = {row.get('case_attempt_limit', 3) for row in workers}
    if len(limits) != 1 or next(iter(limits)) not in (3, 4): return False
    if not 1 <= len(workers) <= next(iter(limits)) or len(semantic) != (1 if mode == 'native' else 0):
        return False
    if len(related) != len(workers) + len(semantic):
        return False
    numbers = []
    for row in related:
        expected_outcome = 'http_response' if row['case'].endswith(':semantic') else 'completed'
        if (row.get('service') != 'moonshot_cn' or row.get('model') != 'kimi-k3'
                or row.get('confirmed_model') != 'kimi-k3' or row.get('http_status') != 200
                or row.get('case_frozen') or row.get('outcome') != expected_outcome):
            return False
        number, upper_in, upper_out = (row.get(k) for k in ('number', 'input_tokens_upper', 'output_tokens_upper'))
        if (type(number) is not int or number < 1 or number in numbers
                or type(upper_in) is not int or not 2048 <= upper_in <= 24000
                or type(upper_out) is not int or not 1 <= upper_out <= 2048):
            return False
        numbers.append(number)
        reservation = (upper_in * 60 + upper_out * 100) / 1_000_000
        if abs(row['reserved_cny'] - reservation) > 1e-9:
            return False
        usage = row.get('usage')
        if not isinstance(usage, dict) or not all(type(usage.get(k)) is int and usage[k] >= 0
                for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')):
            return False
        if (usage['prompt_tokens'] > upper_in or usage['completion_tokens'] > upper_out
                or usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']):
            return False
    return True



def synthetic_approval(activity, workspace):
    """Admit only the current synthetic write; product scope validates again."""
    if activity.get('activityKind') != 'approval' or activity.get('status') != 'pending':
        return None
    detail = activity.get('detail', {})
    raw = detail.get('input')
    if detail.get('protocol') != 'acp' or detail.get('toolKind') != 'edit' or not isinstance(raw, dict):
        raise RuntimeError('Synthetic approval has no original edit facts')
    name = raw.get('path')
    if not isinstance(name, str) or not name:
        raise RuntimeError('Synthetic approval target is unknown')
    target = Path(name)
    if not target.is_absolute(): target = Path(workspace) / target
    if target.resolve() != (Path(workspace) / 'solution.py').resolve():
        raise RuntimeError('Synthetic approval target is outside the admitted file')
    choices = [d['id'] for d in detail.get('decisions', []) if d.get('kind') == 'allow_once' and isinstance(d.get('id'), str)]
    if len(choices) != 1 or not isinstance(activity.get('requestId'), str):
        raise RuntimeError('Synthetic approval has no unique offered once decision')
    return activity['requestId'], choices[0]


def successful_report(report, mode):
    common = all(report.get(k) is True for k in ('worker_completed', 'gate_pass', 'scope_pass', 'source_unchanged', 'processes_stopped', 'budget_evidence_valid'))
    if not common or report.get('key_persisted_or_logged') is not False or report.get('error_type'):
        return False
    if mode == 'baseline':
        return report.get('exit_code') == 0
    return report.get('state') == 'DONE' and report.get('mission_pass') is True and report.get('export_gate_pass') is True and report.get('verifier') == 'PASS'


def main():
    parser = argparse.ArgumentParser()
    for name in ('config', 'ledger', 'evidence', 'node', 'kimi', 'daemon', 'go'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--profile', default='kimi-live')
    parser.add_argument('--mode', choices=['baseline', 'native'], required=True)
    parser.add_argument('--worker-requests', type=int, choices=[3, 4], default=3)
    parser.add_argument('--trial-id', default='', help='Distinct corrected trial; prior attempts remain charged')
    parser.add_argument('--live', action='store_true', required=True)
    args = parser.parse_args()
    if not args.live: raise RuntimeError('Explicit live opt-in required')
    ledger = json.loads(args.ledger.read_text('utf-8'))
    if len(args.trial_id) > 32 or any(not (c.isascii() and (c.isalnum() or c in '_-')) for c in args.trial_id):
        raise RuntimeError('Invalid trial identifier')
    case = 'kimi-' + args.mode + ('-' + args.trial_id if args.trial_id else '')
    if not service_ready(ledger) or any(r.get('case', '').startswith(case) for r in ledger['attempts']):
        raise RuntimeError('Case already attempted or service frozen; no replay')
    launches = ledger.get('worker_tasks', [])
    if len(launches) >= 6 or any(r['case'] == case for r in launches):
        raise RuntimeError('Worker task allowance exhausted or case already admitted')
    # Reserve a complete bounded trial; finished requests use their confirmed
    # conservative charge upper bound, never a guessed invoice or deleted row.
    maximum_attempts = args.worker_requests + (1 if args.mode == 'native' else 0)
    maximum = 1.6448 * maximum_attempts
    if accounted_total_micros(ledger) + round(maximum * 1_000_000) > 20_000_000 or len(ledger['attempts']) + maximum_attempts > 40:
        raise RuntimeError('Complete trial upper bound exceeds remaining allowance')
    args.evidence.mkdir(parents=True, exist_ok=False)
    home = args.evidence / 'home'; create_private_test_home(home)
    source = args.evidence / 'source'; source.mkdir()
    for name, content in SOURCE.items(): (source / name).write_bytes(content.encode('utf-8'))
    profile = copy.deepcopy(next(p for p in yaml.safe_load(args.config.read_text('utf-8'))['model_profiles'] if p['id'] == args.profile))
    if profile['service'] != 'moonshot_cn' or profile['model'] != 'kimi-k3' or profile['endpoint'] != 'https://api.moonshot.cn/v1/chat/completions':
        raise RuntimeError('Only the explicitly priced project Kimi service is admitted')
    key = credentials('moonshot_cn').read(profile['credential_ref'])
    if not key: raise RuntimeError('Project Kimi credential is not configured')
    env = {k: v for k, v in os.environ.items() if k.upper() in ('PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','TEMP','TMP')}
    data = home / 'native' / 'data'
    kimi_home = data / 'kimi' if args.mode == 'native' else home / 'kimi'
    kimi_home.mkdir(parents=True)
    (kimi_home / 'config.toml').write_text('[tools]\nenabled = ["Read", "Write", "Edit"]\n', 'utf-8')
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home/'appdata'), LOCALAPPDATA=str(home/'local'),
               XDG_CONFIG_HOME=str(home/'config'), XDG_DATA_HOME=str(home/'share'),
               KIMI_CODE_HOME=str(kimi_home), KIMI_MODEL_NAME='kimi-k3', KIMI_MODEL_API_KEY=key, KIMI_API_KEY=key,
               KIMI_MODEL_BASE_URL='https://api.moonshot.cn/v1', KIMI_MODEL_PROVIDER_TYPE='kimi',
               KIMI_MODEL_MAX_COMPLETION_TOKENS='2048', KIMI_MODEL_MAX_CONTEXT_SIZE='32000',
               KIMI_LOOP_MAX_STEPS_PER_TURN=str(args.worker_requests), KIMI_LOOP_MAX_ATTEMPTS_PER_STEP='1',
               KIMI_CODE_INFINITE_RETRY='0', KIMI_DISABLE_CRON='1', KIMI_DISABLE_TELEMETRY='1',
               KIMI_CODE_NO_AUTO_UPDATE='1', KIMI_LOG_LEVEL='off', OPENAI_LOG='off',
               CLAO_LIVE_LEDGER=str(args.ledger), CLAO_LIVE_CASE=case,
               CLAO_LIVE_MAX_WORKER_REQUESTS=str(args.worker_requests))
    if args.mode == 'native':
        # Native ACP chooses its managed home. The daemon's user profile stays
        # distinct so preparation never mistakes managed files for source login.
        env.pop('KIMI_CODE_HOME')
    env['PATH'] = str(args.node.parent) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + env['PATH']
    hook = (ROOT/'dev/native/kimi-budget-transport.mjs').as_uri()
    report = dict(case=case, cli_version='2.0.2', service='moonshot_cn', model='kimi-k3',
                  environment=('development daemon with official CLI and test-only budget transport' if args.mode == 'native'
                               else 'standalone official CLI with test-only budget transport'),
                  source_sha256=hashlib.sha256(json.dumps(SOURCE, sort_keys=True).encode()).hexdigest(),
                  human_interventions=0, worker_completed=False, gate_pass=False)
    process = None
    process_tree = None
    collector = None
    raw_logs = bytearray()
    start = time.monotonic()
    stage = 'setup'
    report['automated_scope_approvals'] = 0
    def gate(folder):
        return run_gate(folder, env)
    def record_launch():
        mutate = runpy.run_path(str(ROOT/'dev/native/live-core-budget.py'))['mutate_ledger']
        def admit(current):
            tasks = current.setdefault('worker_tasks', [])
            if not service_ready(current) or len(tasks) >= 6 or any(task['case'] == case for task in tasks):
                raise RuntimeError('Worker admission refused')
            if any(row.get('case', '').startswith(case) for row in current['attempts']):
                raise RuntimeError('Case replay refused')
            if accounted_total_micros(current) + round(maximum * 1_000_000) > 20_000_000 or len(current['attempts']) + maximum_attempts > 40:
                raise RuntimeError('Complete trial budget unavailable')
            tasks.append(dict(case=case, status='admitted', max_worker_http=args.worker_requests))
        mutate(args.ledger, admit)
    try:
        if args.mode == 'baseline':
            workspace = args.evidence/'baseline'; shutil.copytree(source, workspace)
            stage = 'baseline_worker'
            record_launch()
            process_tree = WindowsProcessTree()
            process = process_tree.start([str(args.node), '--import', hook, str(args.kimi), '-p', OBJECTIVE],
                cwd=workspace, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output, _ = process.communicate(timeout=420)
            raw_logs.extend(output)
            report['processes_stopped'] = process_tree.stop()
            report.update(worker_completed=process.returncode == 0, gate_pass=gate(workspace), exit_code=process.returncode)
            report['scope_pass'], report['changed_files'] = scope_facts(workspace)
        else:
            shims = args.evidence/'bin'; shims.mkdir()
            (shims/'kimi.cmd').write_text('@echo off\r\n"'+str(args.node)+'" --import "'+hook+'" "'+str(args.kimi)+'" %*\r\n', 'utf-8')
            # The shim inserts only ledger references for the selected semantic
            # bridge. Acceptance/Git modules still run the normal core command.
            core = ROOT/'dev/native/live-core-budget.py'
            shim_source = '''package main
import("os";"os/exec")
func main(){ args:=os.Args[1:]; if len(args)==3 && args[0]=="-B" && args[1]=="-m" && args[2]=="loopcore.ao_legacy" { args=[]string{"-B",CORE} }; cmd:=exec.Command(PYTHON,args...);cmd.Stdin=os.Stdin;cmd.Stdout=os.Stdout;cmd.Stderr=os.Stderr;cmd.Env=append(os.Environ(),LEDGER,CASE);if err:=cmd.Run();err!=nil{os.Exit(1)} }
'''
            for name, value in {'CORE':str(core), 'PYTHON':sys.executable, 'LEDGER':'CLAO_LIVE_LEDGER='+str(args.ledger), 'CASE':'CLAO_LIVE_CASE='+case}.items():
                shim_source = shim_source.replace(name, json.dumps(value))
            shim_go = shims/'core.go'; shim_go.write_text(shim_source, 'utf-8')
            build_env = dict(os.environ, GOWORK='off', GOTOOLCHAIN='local')
            subprocess.run([str(args.go),'build','-o',str(shims/'core.exe'),str(shim_go)],env=build_env,check=True,capture_output=True,timeout=60)
            with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
            url='http://127.0.0.1:'+str(port)
            env.update(AO_DATA_DIR=str(data), AO_RUN_FILE=str(home/'native/running.json'), AO_PORT=str(port),
                       AO_ALLOWED_ORIGINS=url, AO_TELEMETRY_EVENTS='off', AO_TELEMETRY_REMOTE='off', AO_SENTRY_DSN='',
                       CLAO_CORE_PYTHON=str(shims/'core.exe'), CLAO_CORE_ROOT=str(ROOT/'clao'))
            env['PATH']=str(shims)+os.pathsep+env['PATH']
            stage = 'native_daemon_start'
            process_tree = WindowsProcessTree()
            process=process_tree.start([str(args.daemon),'daemon'],cwd=home,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            def collect():
                for chunk in iter(lambda: process.stdout.read(4096), b''):
                    if len(raw_logs)<2*1024*1024: raw_logs.extend(chunk)
            collector=threading.Thread(target=collect,daemon=True)
            collector.start()
            nonce=None
            def api(path, body=None):
                request=urllib.request.Request(url+path,data=None if body is None else json.dumps(body).encode(),
                    headers={'Origin':url,'Content-Type':'application/json',**({'X-CLAO-Nonce':nonce} if nonce else {})})
                try:
                    with urllib.request.urlopen(request,timeout=35) as response: return {} if response.status == 204 else json.load(response)
                except urllib.error.HTTPError as exc: raise RuntimeError('Native API rejected '+path+' status '+str(exc.code)) from None
            for _ in range(100):
                if process.poll() is not None: raise RuntimeError('Native Kimi test daemon exited')
                try: nonce=api('/api/v1/clao/session')['nonce'];break
                except OSError: time.sleep(.1)
            if not nonce: raise RuntimeError('Native Kimi test daemon unavailable')
            profile.update(id='bounded-kimi-review',max_attempts=1,timeout_seconds=120,retry_delay_seconds=0,max_completion_tokens=2048)
            selected=args.evidence/'semantic-profile.yaml'
            profile_text = yaml.safe_dump({'model_profiles':[profile],'roles':{'verifier':{'profile':profile['id']}}})
            if key in profile_text: raise RuntimeError('Credential must not be serialized')
            selected.write_text(profile_text, 'utf-8')
            stage = 'native_connection_import'
            catalog=api('/api/v1/clao/imports',{'configPath':str(selected)})
            connection=catalog['connections'][0]
            role=dict(connectionId=connection['id'],connectionRevision=connection.get('authRevision',0),model='kimi-k3',agent='')
            project=api('/api/v1/clao/projects',{'path':str(source),'name':'Bounded synthetic addition','create':True})['project']['id']
            revision=api('/api/v1/clao/projects/'+project+'/source')['source']['revision']
            request=dict(id='bounded-kimi-addition',projectId=project,sourceRevision=revision,objective=OBJECTIVE,
                agent='kimi',model='',allowedPaths=['solution.py'],forbiddenPaths=['check.py','.git/**'],
                criteria=[dict(id='AC1',description='add returns the sum for positive, negative and zero integers')],
                gateCommands=['python check.py'],maxTasks=1,maxRepairs=0,maxReplans=0,gateTimeout=15,
                roles={name:role for name in ('planner','auditor','verifier')},externalServiceConsent=['moonshot_cn'])
            stage = 'native_mission_create'
            record_launch(); api('/api/v1/clao/missions',request)
            stage = 'native_worker'
            resolved_approvals = set()
            mission=None
            for _ in range(840):
                mission=api('/api/v1/clao/missions/'+request['id'])['mission']
                if mission['state'] in ('DONE','FAILED','HUMAN','UNKNOWN','PAUSED','CANCELLED'):break
                if mission.get('sessionId') and mission['state'] == 'RUNNING':
                    sid = mission['sessionId']
                    snapshot = api('/api/v1/sessions/'+sid+'/conversation')
                    for activity in snapshot.get('activities', []):
                        admitted = synthetic_approval(activity, mission['workspace'])
                        if admitted and admitted[0] not in resolved_approvals:
                            stage = 'native_approval'
                            api('/api/v1/sessions/'+sid+'/conversation/approvals/'+admitted[0]+'/resolve', {'decisionId':admitted[1]})
                            resolved_approvals.add(admitted[0])
                            report['automated_scope_approvals'] += 1
                            stage = 'native_worker'
                time.sleep(.5)
            report.update(state=mission['state'],worker_completed=mission['state']=='DONE',
                          mission_pass=mission['state']=='DONE')
            if mission['state']=='DONE':
                stage = 'native_export'
                evidence=mission['evidence'][-1]
                report.update(gate_pass=evidence['ok'],scope_pass=evidence['scopeOK'],verifier=evidence['verification']['verdict'])
                package=api('/api/v1/clao/missions/'+request['id']+'/export',{})['package']
                with urllib.request.urlopen(url+'/api/v1/clao/missions/'+request['id']+'/exports/'+package['identity'],timeout=20) as response: blob=response.read()
                archive=zipfile.ZipFile(io.BytesIO(blob)); independent=args.evidence/'independent';shutil.copytree(source,independent)
                patch=next(name for name in archive.namelist() if name.endswith('.patch'))
                patch_path=args.evidence/'result.patch';patch_path.write_bytes(archive.read(patch))
                subprocess.run(['git','-C',str(independent),'apply',str(patch_path)],env=safe_gate_env(env),check=True,capture_output=True,timeout=15)
                report['export_gate_pass']=gate(independent)
        report['source_unchanged']=all((source/name).read_bytes()==content.encode('utf-8') for name,content in SOURCE.items()) and set(p.name for p in source.iterdir())==set(SOURCE)
    except Exception as exc:
        report['error_type']=type(exc).__name__
        report['error_stage']=stage
        # Never serialize arbitrary provider, command or environment errors.
        report['completed']=False
    finally:
        if process_tree is not None:
            try: report['processes_stopped'] = process_tree.stop()
            except Exception:
                report['processes_stopped'] = False
                report['error_type'] = 'ProcessStopUnconfirmed'
        if collector is not None:
            collector.join(timeout=5)
            if collector.is_alive(): report['error_type'] = 'LogDrainUnconfirmed'
        report['elapsed_seconds']=round(time.monotonic()-start,3)
        leaked=key.encode() in raw_logs
        for path in args.evidence.rglob('*'):
            if path.is_file() and key.encode() in path.read_bytes(): leaked=True
        report['key_persisted_or_logged']=leaked
        final_ledger=json.loads(args.ledger.read_text('utf-8'))
        report['budget_evidence_valid']=valid_budget_evidence(final_ledger, case, args.mode)
        rows=final_ledger['attempts']
        report['attempts']=[r['number'] for r in rows if r.get('case','').startswith(case)]
        report['reserved_cny']=round(sum(r['reserved_cny'] for r in rows if r.get('case','').startswith(case)),6)
        try:
            report['accounted_upper_cny'] = accounted_total_micros({'attempts':[r for r in rows if r.get('case','').startswith(case)]}) / 1_000_000
            report['total_accounted_upper_cny'] = accounted_total_micros(final_ledger) / 1_000_000
        except (ValueError, TypeError, KeyError):
            report['accounted_upper_cny'] = report['total_accounted_upper_cny'] = None
            report['budget_evidence_valid'] = False
            report['error_type'] = 'CostEvidenceInvalid'
        (args.evidence/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(report,ensure_ascii=False))
    return 0 if successful_report(report, args.mode) else 1


if __name__=='__main__':raise SystemExit(main())
