"""Read-only source/checkpoint validation shared by CLI and Panel."""
from pathlib import Path
import hashlib
import re

from .state_store import StateStore
from .effective_config import restore_snapshot
from . import worktree as wt


class RecoveryError(ValueError):
    pass


def git(path, *args):
    try:
        value = wt._snapshot_git(str(path), *args).decode('utf-8', errors='strict').strip()
    except (wt.GitStateSnapshotError, UnicodeError) as exc:
        raise RecoveryError('Git recovery evidence unavailable: ' + str(exc)) from exc
    return value


def commit(path, ref):
    value = git(path, 'rev-parse', '--verify', ref + '^{commit}')
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value):
        raise RecoveryError('invalid exact Git commit')
    return value


def source_identity(project_id, path, detail):
    path = str(Path(path).resolve())
    policy = detail.get('defaultBranch') or 'auto'
    if not isinstance(policy, str):
        raise RecoveryError('invalid AO defaultBranch')
    ref = (git(path, 'symbolic-ref', '--quiet', 'refs/remotes/origin/HEAD') if policy == 'auto'
           else 'refs/remotes/origin/' + policy)
    prefix = 'refs/remotes/origin/'
    if not ref.startswith(prefix) or ref == prefix + 'HEAD':
        raise RecoveryError('AO remote-backed source ref unavailable')
    branch = ref[len(prefix):]
    sha = commit(path, ref)
    local = commit(path, 'refs/heads/' + branch)
    if local != sha:
        raise RecoveryError('local source branch and AO origin base differ; synchronize or explicitly choose a matching project')
    remote = git(path, 'ls-remote', '--exit-code', 'origin', 'refs/heads/' + branch).splitlines()
    if len(remote) != 1 or remote[0].split('\t') != [sha, 'refs/heads/' + branch]:
        raise RecoveryError('origin source differs from the local tracking ref; fetch before starting')
    return dict(project_id=project_id, project_path=path, policy=policy, source_ref=ref,
                source_commit=sha, origin_sha256=hashlib.sha256(git(path, 'remote', 'get-url', 'origin').encode()).hexdigest())


def check_spawn_source(source, adapter):
    detail = adapter.get_project(source['project_id'])
    if str(Path(detail.get('path', '')).resolve()) != source['project_path']:
        raise RecoveryError('AO project path changed from frozen source')
    current = source_identity(source['project_id'], source['project_path'], detail)
    if current != source:
        raise RecoveryError('frozen source drift: no new Worker may spawn from a different base')


def worker_source(source, workspace):
    sha = source['source_commit']
    if commit(workspace, sha) != sha:
        raise RecoveryError('Worker frozen source object unavailable')
    git(workspace, 'merge-base', '--is-ancestor', sha, 'HEAD')
    # The oldest HEAD reflog entry records worktree creation, including a
    # Worker which already committed before CLAO received the spawn ACK.
    entries = git(workspace, 'reflog', 'show', '--format=%H', 'HEAD').splitlines()
    if not entries or entries[-1] != sha:
        raise RecoveryError('Worker creation base cannot be confirmed as frozen source')
    return dict(path=str(Path(workspace).resolve()), base=sha)


def validate_checkpoint(store, mission_id, adapter):
    """No Store writes, provider construction, spawn/send/kill, or Git mutation."""
    row = store.mission_config(mission_id)
    if not row or row.get('mission', {}).get('mission_id') != mission_id:
        raise RecoveryError('checkpoint Mission association missing or mismatched')
    if row.get('state') in StateStore._MISSION_TERMINAL:
        raise RecoveryError('terminal Mission is read-only; create a new attempt')
    if row.get('effective_config') is None:
        raise RecoveryError('historical Mission has no effective config snapshot; inspect only')
    cfg = restore_snapshot(row['effective_config'])
    source = row.get('source')
    if not isinstance(source, dict) or source.get('project_id') != row['mission']['project_id']:
        raise RecoveryError('frozen source identity missing or mismatched')
    if commit(source['project_path'], source['source_commit']) != source['source_commit']:
        raise RecoveryError('frozen source commit unavailable')
    local = getattr(adapter, 'backend', None) == 'codex_app_server'
    if local:
        if row.get('execution_backend') != 'codex_app_server' or source.get('backend') != 'codex_app_server':
            raise RecoveryError('local execution/source backend mismatch')
        if Path(source['project_path']).resolve() != (Path(store.path).parent / 'source').resolve():
            raise RecoveryError('local source is outside Mission managed directory')
        for worker in adapter.workers.values():
            if worker.get('state') in ('active', 'waiting_input', 'starting', 'unknown'):
                raise RecoveryError('interrupted local Worker execution cannot be assumed stopped; inspect only')
    else:
        detail = adapter.get_project(source['project_id'])
        if str(Path(detail.get('path', '')).resolve()) != source['project_path']:
            raise RecoveryError('AO project does not match frozen source')
    plan = row.get('plan') or {}
    if any(t.get('dependencies') for t in plan.get('subtasks', [])):
        raise RecoveryError('dependent MissionPlan unsupported: no upstream code delivery')
    phases = StateStore.query_phases(store._conn, mission_id, active=True)
    if phases['status'] == 'read_error':
        raise RecoveryError('phase recovery evidence unreadable')
    for phase in phases.get('records', []):
        if phase.get('status') == 'running' and phase.get('phase') in (
                'model_request', 'task_gate', 'baseline_gate', 'final_gate', 'materialization', 'merge'):
            raise RecoveryError('interrupted local execution requires human stop/evidence confirmation: ' + phase['phase'])
    if row.get('local_execution', {}).get('status') in ('running', 'unknown'):
        raise RecoveryError('local execution stop is unknown; cannot recover automatically')
    workspaces = row.get('workspaces', {})
    merged = row.get('merged', [])
    tasks = {}
    for sub in plan.get('subtasks', []):
        task = store.load_task(sub['subtask_id'])
        if not task or task.get('subtask_of') != mission_id or task.get('project_id') != source['project_id']:
            raise RecoveryError('Task checkpoint missing or mismatched')
        tasks[task['task_id']] = task
    # Only unresolved operations and unbound confirmed initial spawns need
    # adoption evidence. Superseded/merged Worker workspaces are not inputs
    # to a checkpoint which already has their verified integration commit.
    from .action_executor import ActionExecutor, operation_id
    executor = ActionExecutor.__new__(ActionExecutor)
    executor.adapter = adapter
    unbound = {operation_id('spawn-initial', t['task_id']) for t in tasks.values() if not t.get('worker_session_id')}
    for op in store.operations(mission_id):
        if op['status'] in ('IN_FLIGHT', 'UNKNOWN'):
            fact = executor.reconciliation_fact(op)
            if fact['status'] != 'SUCCEEDED':
                raise RecoveryError('operation remains UNKNOWN: ' + op['operation_id'])
            if op['kind'] == 'spawn':
                worker_source(source, adapter.get_session_workspace(fact['result']['session_id']))
        elif op['kind'] == 'spawn' and op['status'] == 'SUCCEEDED' and op['operation_id'] in unbound:
            if local:
                worker_source(source, adapter.get_session_workspace(op['result']['session_id']))
                continue
            session = adapter.operation_session(op['result']['session_id'])
            if session.get('projectId') != source['project_id']:
                raise RecoveryError('unbound Worker Session project mismatch')
            worker_source(source, adapter.get_session_workspace(session['id']))
    for receipt in store.directives(mission_id):
        if any(c['status'] == 'unknown' for c in receipt['consumers'].values()) and not receipt['target'].startswith('worker:'):
            raise RecoveryError('directive input completion unknown: ' + receipt['command_id'])
    for task in tasks.values():
        sid = task.get('worker_session_id')
        if not sid:
            continue
        if local:
            if not adapter.stopped(sid):
                raise RecoveryError('local Worker stop is unconfirmed')
            if task['task_id'] in merged:
                continue
            expected = workspaces.get(sid)
            path = adapter.get_session_workspace(sid)
            if not expected or worker_source(source, path) != expected:
                raise RecoveryError('local Worker workspace/source mismatch')
            if wt._read_base_sidecar(path, task['task_id'] + ':' + sid) != source['source_commit']:
                raise RecoveryError('local Worker frozen base missing or mismatched')
            continue
        session = adapter.operation_session(sid)
        if session.get('projectId') != source['project_id']:
            raise RecoveryError('Worker Session project mismatch')
        if task['task_id'] in merged:
            if not session['isTerminated'] or session['status'] != 'terminated':
                raise RecoveryError('merged Worker is not confirmed stopped')
            continue
        expected = workspaces.get(sid)
        if not expected:
            raise RecoveryError('Worker workspace checkpoint missing')
        path = adapter.get_session_workspace(sid)
        if str(Path(path).resolve()) != expected['path'] or worker_source(source, path) != expected:
            raise RecoveryError('Worker workspace/source mismatch')
        if wt._read_base_sidecar(path, task['task_id'] + ':' + sid) != source['source_commit']:
            raise RecoveryError('Worker frozen diff base missing or mismatched')
    integ = Path(store.path).parent / 'integration'
    if merged or integ.exists():
        if not integ.is_dir() or commit(integ, 'HEAD') != row.get('integration_head'):
            raise RecoveryError('integration checkpoint commit missing or mismatched')
        if wt._read_base_sidecar(str(integ), mission_id + ':integration') != source['source_commit']:
            raise RecoveryError('integration frozen base mismatch')
        git(integ, 'merge-base', '--is-ancestor', source['source_commit'], 'HEAD')
        if not wt.git_state_snapshot(str(integ)).clean:
            raise RecoveryError('integration checkpoint is not clean')
    gate_records = StateStore.query_gate_runs(store._conn)
    if gate_records['status'] == 'read_error':
        raise RecoveryError('saved Gate evidence unreadable')
    # Saved verification associations must be intact before the existing F01
    # exact-input replay check runs in the normal consumer.
    for identity in [mission_id] + list(tasks):
        verification = store.latest_verification(identity)
        if verification and (verification.get('task_id') != identity or not verification.get('_validation')):
            raise RecoveryError('saved verification association/evidence missing')
    return row, cfg
