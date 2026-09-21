"""Offline safety regression: synthetic data/processes, no provider or credential calls."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = load('live_kimi_safety_harness', 'verify-live-kimi.py')
budget = load('live_kimi_safety_budget', 'live-core-budget.py')


def fixed_source(tmp_path):
    for name, content in harness.SOURCE.items():
        (tmp_path/name).write_bytes(content.encode('utf-8'))
    (tmp_path/'solution.py').write_text('def add(a,b): return a+b\n', encoding='utf-8')
    return tmp_path


@pytest.mark.parametrize('mutation', ['check', 'extra-file', 'extra-directory', 'nested-file'])
def test_modified_check_or_extra_scope_never_executes_gate(tmp_path, mutation):
    folder = fixed_source(tmp_path)
    if mutation == 'check':
        (folder/'check.py').write_text('raise RuntimeError("must not run")')
    elif mutation == 'extra-file':
        (folder/'extra.py').write_text('')
    else:
        (folder/'extra').mkdir()
        if mutation == 'nested-file': (folder/'extra'/'data').write_text('')
    def forbidden(*args, **kwargs):
        pytest.fail('out-of-scope Gate executed')
    assert harness.run_gate(folder, {'KIMI_API_KEY': 'synthetic-secret'}, forbidden) is False


def test_gate_receives_only_safe_environment_after_scope_validation(tmp_path):
    folder = fixed_source(tmp_path)
    seen = []
    def runner(*args, **kwargs):
        seen.append(kwargs['env'])
        return SimpleNamespace(returncode=0, stdout=b'SYNTHETIC_ADD_GATE_OK')
    env = dict(PATH='synthetic-path', SystemRoot='synthetic-windows', KIMI_API_KEY='synthetic-secret',
               KIMI_MODEL_API_KEY='synthetic-secret', CLAO_LIVE_LEDGER='private-ledger', NODE_OPTIONS='--import private-hook',
               OPENAI_API_KEY='synthetic-other', PYTHONPATH='untrusted')
    assert harness.run_gate(folder, env, runner)
    assert seen == [{'PATH': 'synthetic-path', 'SystemRoot': 'synthetic-windows'}]


def test_real_synthetic_gate_works_without_key(tmp_path):
    assert harness.run_gate(fixed_source(tmp_path), dict(os.environ, KIMI_API_KEY='synthetic-secret'))


def test_gate_rejects_check_mutation_during_execution(tmp_path):
    folder = fixed_source(tmp_path)
    (folder/'solution.py').write_text('from pathlib import Path\nPath("extra.txt").write_text("unexpected")\ndef add(a,b): return a+b\n', encoding='utf-8')
    assert harness.run_gate(folder, os.environ) is False


def report():
    return dict(worker_completed=True, gate_pass=True, scope_pass=True, source_unchanged=True,
                processes_stopped=True, key_persisted_or_logged=False, budget_evidence_valid=True, exit_code=0,
                state='DONE', mission_pass=True, export_gate_pass=True, verifier='PASS')


@pytest.mark.parametrize('mode,changed', [
    ('baseline', {'exit_code': 1}), ('baseline', {'worker_completed': False}),
    ('native', {'export_gate_pass': False}), ('native', {'state': 'HUMAN'}),
    ('native', {'verifier': 'FAIL'}), ('native', {'mission_pass': False}),
    ('native', {'processes_stopped': False}), ('native', {'error_type': 'SyntheticFailure'}),
    ('baseline', {'key_persisted_or_logged': True}),
    ('baseline', {'budget_evidence_valid': False}), ('native', {'budget_evidence_valid': None}),
])
def test_incomplete_trials_cannot_return_success(mode, changed):
    candidate = report()
    assert harness.successful_report(candidate, mode)
    candidate.update(changed)
    assert not harness.successful_report(candidate, mode)


def metered_row(case, number=1):
    return dict(case=case, number=number, service='moonshot_cn', model='kimi-k3',
                confirmed_model='kimi-k3', http_status=200,
                outcome='http_response' if case.endswith(':semantic') else 'completed',
                input_tokens_upper=24000, output_tokens_upper=2048, reserved_cny=1.6448,
                usage=dict(prompt_tokens=100, completion_tokens=20, total_tokens=120))


@pytest.mark.parametrize('mode,workers', [('baseline', 1), ('baseline', 3), ('native', 1), ('native', 3)])
def test_report_accepts_actual_bounded_model_and_usage_evidence(mode, workers):
    case = 'kimi-' + mode
    rows = [metered_row(case, i + 1) for i in range(workers)]
    if mode == 'native': rows.append(metered_row(case + ':semantic', workers + 1))
    assert harness.valid_budget_evidence({'attempts': rows}, case, mode)


@pytest.mark.parametrize('mode,workers,semantic', [
    ('baseline', 0, 0), ('baseline', 4, 0), ('baseline', 1, 1),
    ('native', 0, 1), ('native', 1, 0), ('native', 1, 2), ('native', 4, 1),
])
def test_report_rejects_missing_or_extra_actual_requests(mode, workers, semantic):
    case = 'kimi-' + mode
    rows = [metered_row(case, i + 1) for i in range(workers)]
    rows += [metered_row(case + ':semantic', workers + i + 1) for i in range(semantic)]
    assert not harness.valid_budget_evidence({'attempts': rows}, case, mode)


@pytest.mark.parametrize('changed', [
    {'service': 'other'}, {'model': 'other'}, {'confirmed_model': None}, {'confirmed_model': 'other'},
    {'http_status': 429}, {'outcome': 'unconfirmed'}, {'outcome': 'http_response'}, {'case_frozen': True},
    {'number': True}, {'input_tokens_upper': 24001}, {'output_tokens_upper': 2049},
    {'reserved_cny': 0}, {'reserved_cny': float('nan')}, {'reserved_cny': float('inf')},
    {'usage': None}, {'usage': {'prompt_tokens': 1}},
    {'usage': {'prompt_tokens': True, 'completion_tokens': 20, 'total_tokens': 21}},
    {'usage': {'prompt_tokens': -1, 'completion_tokens': 20, 'total_tokens': 19}},
    {'usage': {'prompt_tokens': 24001, 'completion_tokens': 20, 'total_tokens': 24021}},
    {'usage': {'prompt_tokens': 100, 'completion_tokens': 2049, 'total_tokens': 2149}},
    {'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 121}},
])
def test_report_rejects_unconfirmed_or_invalid_paid_worker_evidence(changed):
    row = metered_row('kimi-baseline')
    row.update(changed)
    assert not harness.valid_budget_evidence({'attempts': [row]}, 'kimi-baseline', 'baseline')


@pytest.mark.parametrize('fault', ['frozen', 'unknown-case', 'duplicate-number', 'semantic-failed', 'over-money', 'over-attempts'])
def test_report_rejects_frozen_or_inconsistent_trial_ledger(fault):
    ledger = {'attempts': [metered_row('kimi-native'), metered_row('kimi-native:semantic', 2)]}
    if fault == 'frozen': ledger['frozen'] = True
    elif fault == 'unknown-case': ledger['attempts'].append(metered_row('kimi-native:unexpected', 3))
    elif fault == 'duplicate-number': ledger['attempts'][1]['number'] = 1
    elif fault == 'semantic-failed': ledger['attempts'][1]['outcome'] = 'unconfirmed'
    elif fault == 'over-money': ledger['attempts'].append(dict(case='previous', reserved_cny=20))
    elif fault == 'over-attempts': ledger['attempts'] += [dict(case='previous', reserved_cny=0)] * 39
    assert not harness.valid_budget_evidence(ledger, 'kimi-native', 'native')


def test_success_requires_budget_flag_even_when_all_other_checks_pass():
    candidate = report()
    del candidate['budget_evidence_valid']
    assert not harness.successful_report(candidate, 'baseline')
    assert not harness.successful_report(candidate, 'native')


def semantic_request():
    return json.dumps(dict(model='kimi-k3', stream=False, max_completion_tokens=2048,
                           messages=[dict(role='user', content='synthetic')])).encode()


def transport():
    return SimpleNamespace(service='moonshot_cn', profile={'endpoint': 'https://api.moonshot.cn/v1/chat/completions'})


def envelope(usage=None, **overrides):
    return json.dumps(dict(model='kimi-k3', usage=usage if usage is not None else dict(prompt_tokens=10, completion_tokens=5, total_tokens=15), **overrides)).encode()


@pytest.mark.parametrize('usage', [{}, {'prompt_tokens': 1, 'completion_tokens': 2},
    {'prompt_tokens': True, 'completion_tokens': 2, 'total_tokens': 3},
    {'prompt_tokens': 10, 'completion_tokens': 2049, 'total_tokens': 2059},
    {'prompt_tokens': 24001, 'completion_tokens': 1, 'total_tokens': 24002},
    {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 99}])
def test_semantic_invalid_usage_freezes_without_refunding(tmp_path, usage):
    ledger = tmp_path/'ledger.json'
    ledger.write_text('{"attempts": []}')
    calls = []
    def original(*args):
        calls.append(True)
        return 200, envelope(usage)
    exchange = budget.create_exchange(ledger, 'native:semantic', original)
    with pytest.raises(RuntimeError): exchange(transport(), semantic_request(), 'synthetic-key')
    after = json.loads(ledger.read_text())
    assert after['frozen'] is True
    assert after['attempts'][0]['reserved_cny'] > 0
    assert after['attempts'][0]['outcome'] == 'unconfirmed'
    with pytest.raises(RuntimeError): exchange(transport(), semantic_request(), 'synthetic-key')
    assert len(calls) == 1


def test_semantic_fsync_precedes_socket_and_result_is_sanitized(tmp_path, monkeypatch):
    ledger = tmp_path/'ledger.json'
    ledger.write_text('{"attempts": []}')
    events = []
    actual_fsync = budget.os.fsync
    def fsync(fd):
        actual_fsync(fd)
        events.append('fsync')
    monkeypatch.setattr(budget.os, 'fsync', fsync)
    def original(*args):
        assert events == ['fsync']
        assert json.loads(ledger.read_text())['attempts'][0]['outcome'] == 'unconfirmed'
        events.append('socket')
        return 200, envelope(content='synthetic response content')
    exchange = budget.create_exchange(ledger, 'native:semantic', original)
    status, _ = exchange(transport(), semantic_request(), 'synthetic-key')
    assert status == 200 and events == ['fsync', 'socket', 'fsync']
    saved = ledger.read_text()
    assert 'synthetic-key' not in saved and 'synthetic response content' not in saved
    assert json.loads(saved)['attempts'][0]['usage']['total_tokens'] == 15
    with pytest.raises(RuntimeError): exchange(transport(), semantic_request(), 'synthetic-key')
    assert events.count('socket') == 1


def test_semantic_failed_durable_reservation_never_opens_socket(tmp_path, monkeypatch):
    ledger = tmp_path/'ledger.json'
    ledger.write_text('{"attempts": []}')
    def fail(fd): raise OSError('synthetic disk failure')
    monkeypatch.setattr(budget.os, 'fsync', fail)
    exchange = budget.create_exchange(ledger, 'native:semantic', lambda *a: pytest.fail('socket sent before durable reservation'))
    with pytest.raises(OSError): exchange(transport(), semantic_request(), 'synthetic-key')
    assert json.loads(ledger.read_text())['attempts'] == []
    assert list(tmp_path.iterdir()) == [ledger]


@pytest.mark.skipif(os.name != 'nt', reason='real Windows Job Object regression')
def test_windows_owned_job_stops_descendants_even_after_parent_exit(tmp_path):
    marker = tmp_path/'child-ready'
    child = 'import pathlib,time;pathlib.Path(' + repr(str(marker)) + ').write_text("ready");time.sleep(120)'
    parent = ('import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",' + repr(child) + '],'
              'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);time.sleep(0.5)')
    tree = harness.WindowsProcessTree()
    try:
        process = tree.start([sys.executable, '-c', parent], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline: time.sleep(.02)
        assert marker.exists()
        process.wait(timeout=10)
        assert process.returncode == 0
        assert tree.active_count() >= 1  # parent exit alone leaves child running.
        assert tree.stop() is True
        assert tree.stop() is True
    finally:
        tree.stop()


@pytest.mark.skipif(os.name != 'nt', reason='real Windows Job Object regression')
def test_windows_job_assignment_failure_refuses_start_before_execution(tmp_path, monkeypatch):
    marker = tmp_path/'must-not-exist'
    tree = harness.WindowsProcessTree()
    monkeypatch.setattr(tree.api, 'AssignProcessToJobObject', lambda *args: False)
    with pytest.raises(RuntimeError, match='launch refused'):
        tree.start([sys.executable, '-c', f'import pathlib;pathlib.Path({str(marker)!r}).write_text("unsafe")'])
    assert not marker.exists()


@pytest.mark.parametrize('path', ['solution.py', './solution.py'])
def test_synthetic_approval_uses_original_input_and_offered_once(tmp_path, path):
    activity = dict(activityKind='approval', status='pending', requestId='current', detail=dict(protocol='acp', toolKind='edit', input={'path': path}, decisions=[{'id':'once','kind':'allow_once'},{'id':'always','kind':'allow_always'}]))
    assert harness.synthetic_approval(activity, tmp_path) == ('current', 'once')

@pytest.mark.parametrize('mutation', ['missing-input', 'unknown-kind', 'check', 'outside', 'no-once', 'ambiguous'])
def test_synthetic_approval_rejects_incomplete_or_other_targets(tmp_path, mutation):
    activity = dict(activityKind='approval', status='pending', requestId='current', detail=dict(protocol='acp', toolKind='edit', input={'path':'solution.py'}, decisions=[{'id':'once','kind':'allow_once'}]))
    detail = activity['detail']
    if mutation == 'missing-input': detail.pop('input')
    if mutation == 'unknown-kind': detail['toolKind'] = 'execute'
    if mutation == 'check': detail['input']['path'] = 'check.py'
    if mutation == 'outside': detail['input']['path'] = '../solution.py'
    if mutation == 'no-once': detail['decisions'] = [{'id':'always','kind':'allow_always'}]
    if mutation == 'ambiguous': detail['decisions'].append({'id':'second','kind':'allow_once'})
    with pytest.raises(RuntimeError): harness.synthetic_approval(activity, tmp_path)


@pytest.mark.skipif(os.name != 'nt', reason='real Windows protected DACL regression')
def test_private_home_atomic_creation_and_existing_acl_preserved(tmp_path):
    home = tmp_path/'private-test-home'
    harness.create_private_test_home(home)
    child = home/'config.toml'; child.write_text('[tools]\nenabled=[]\n')
    command = "$ErrorActionPreference='Stop'; $acl=if([IO.Directory]::Exists($env:CLAO_TEST_PATH)){[IO.Directory]::GetAccessControl($env:CLAO_TEST_PATH)}else{[IO.File]::GetAccessControl($env:CLAO_TEST_PATH)}; [pscustomobject]@{protected=$acl.AreAccessRulesProtected;sddl=$acl.Sddl;rules=@($acl.Access|ForEach-Object{[pscustomobject]@{sid=$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value;type=$_.AccessControlType.ToString();rights=[int]$_.FileSystemRights}})}|ConvertTo-Json -Depth 4 -Compress"
    def acl(path):
        result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
            env=dict(os.environ, CLAO_TEST_PATH=str(path)),capture_output=True,text=True,check=True,timeout=15)
        return json.loads(result.stdout)
    before = acl(home)
    assert before['protected'] is True
    assert len(before['rules']) == 3
    sids = {row['sid'] for row in before['rules']}
    assert {'S-1-5-18','S-1-5-32-544'} <= sids
    assert all(row['type']=='Allow' and row['rights']==2032127 for row in before['rules'])
    assert {row['sid'] for row in acl(child)['rules']} == sids
    with pytest.raises(RuntimeError, match='existing objects remain unchanged'):
        harness.create_private_test_home(home)
    assert acl(home) == before
    assert child.read_text() == '[tools]\nenabled=[]\n'
