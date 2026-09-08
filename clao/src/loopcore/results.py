"""Frozen Mission results and portable patch packages. No Worker or model calls.

Git object reads never stage or refresh the real index. Packages contain only
an exact commit-to-commit patch, content manifests and whitelisted summaries.
The existing StateStore records completed packages, independently of worktrees.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import threading
import zipfile
from pathlib import Path

from . import worktree as wt
from .local_projects import excluded, MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES
from .state_store import StateStore, now_iso

FORMAT = 'clao-result-v1'
DISPLAY_LIMIT = 24000
_LOCK = threading.RLock()
_OID = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?')
_IDENTITY = re.compile(r'[0-9a-f]{64}')
_SECRET = re.compile(
    r'-----BEGIN (?:[A-Z ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----|'
    r'\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|AKIA[A-Z0-9]{16})\b|'
    r'(?i:authorization\s*[:=]\s*["\']?bearer\s+\S+|bearer\s+[A-Za-z0-9._~+/=-]{8,})|'
    r'(?i:["\']?\b(?:[\w-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token)|'
    r'password|secret|token|cookie)["\']?\s*[:=]\s*["\']?[^\s,;"\']{8,})|'
    r'(?i:["\']?\b(?:[\w-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token)|'
    r'password|secret|token|cookie)["\']?\s*[:=]\s*["\'][^"\'\r\n]+["\'])|'
    r'(?i:--prompt(?:=|\s)|<system>|\[system\]|BEGIN (?:SYSTEM|FULL) PROMPT)')


class ResultError(ValueError):
    def __init__(self, message, status='unavailable'):
        super().__init__(message)
        self.status = status


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _known(root, name):
    root = Path(root).resolve(strict=True)
    path = root / name
    # Artifact destinations must not be symlinks/junctions, even within runtime.
    current = root
    for part in Path(name).parts:
        current /= part
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if current.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ResultError('结果路径含链接或 junction', 'read_error')
    if not path.resolve().is_relative_to(root):
        raise ResultError('结果路径超出该任务目录', 'read_error')
    return path


def facts(runtime, mid):
    """One read transaction, no runtime attachment and no historical migration."""
    conn = StateStore.read_connection(_known(runtime, 'state.db'), timeout=3)
    try:
        conn.execute('BEGIN')
        row = conn.execute('SELECT payload_json FROM missions WHERE mission_id=?', (mid,)).fetchone()
        payload = json.loads(row[0]) if row else {}
        if not isinstance(payload, dict):
            raise ResultError('Mission 记录不是对象', 'read_error')
        mission = payload.get('mission')
        if not isinstance(mission, dict) or mission.get('mission_id') != mid:
            raise ResultError('缺少匹配的 Mission 记录', 'read_error')
        gates = StateStore.query_gate_runs(conn, limit=10001)
        if len(gates['records']) > 10000:
            gates = {'status': 'read_error', 'records': [], 'error': 'Gate 记录超过当前读取上限'}
        try:
            rows = conn.execute('SELECT payload_json FROM verifications WHERE task_id=? ORDER BY rowid DESC', (mid,)).fetchall()
            verifier = json.loads(rows[0][0]) if rows else None
            if verifier is not None and (not isinstance(verifier, dict) or verifier.get('task_id') != mid):
                raise ValueError('Verifier 关联字段不可读取')
            if verifier is not None:
                verifier = {k: verifier.get(k) for k in ('verify_id', 'task_id', 'verdict', 'summary', 'ac_checks', 'anti_gaming')}
                for field in ('ac_checks', 'anti_gaming'):
                    values = verifier[field]
                    if values is not None:
                        if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
                            raise ValueError('Verifier 条目不可读取')
                        verifier[field] = [{k: v.get(k) for k in ('ac_id', 'verdict', 'note')} for v in values]
            verification = {'status': 'ok' if verifier else 'no_records', 'record': verifier}
        except (sqlite3.Error, ValueError, TypeError) as exc:
            verification = {'status': 'read_error', 'record': None, 'error': str(exc)}
        checks = (verification.get('record') or {}).get('ac_checks') or []
        if not isinstance(checks, list) or any(not isinstance(c, dict) for c in checks):
            checks = []
            verification = {'status': 'read_error', 'record': None, 'error': 'AC 记录不可读取'}
        acs = []
        criteria = mission.get('acceptance_criteria', [])
        if not isinstance(criteria, list) or any(not isinstance(ac, dict) for ac in criteria):
            raise ResultError('验收条件记录不可读取', 'read_error')
        for ac in criteria:
            matches = [c for c in checks if c.get('ac_id') == ac.get('id')]
            check = matches[0] if len(matches) == 1 else {}
            acs.append({'id': ac.get('id'), 'description': ac.get('description'),
                        'verdict': check.get('verdict', 'unknown'),
                        'note': check.get('note', '历史字段未提供；不从 Mission 状态推断')})
        evidence = {'mission': {'id': mid, 'project_id': mission.get('project_id'),
                    'objective': mission.get('objective'), 'state': payload.get('state', 'unknown'),
                    'reason': payload.get('reason'), 'accepted': payload.get('state') == 'MISSION_DONE'},
                    'acceptance_criteria': acs, 'gates': gates, 'verifier': verification}
        exports = StateStore.query_result_exports(conn, mid)
        return payload, evidence, exports
    finally:
        conn.close()


def _git(repo, *args, **kwargs):
    if any(k in os.environ for k in ('GIT_CONFIG_COUNT', 'GIT_CONFIG_PARAMETERS')):
        raise ResultError('Git 环境含命令配置覆盖，无法可靠读取', 'read_error')
    try:
        # Replace refs must never substitute the recorded objects.
        return wt._snapshot_git(str(repo), *args, env={'GIT_NO_REPLACE_OBJECTS': '1'}, **kwargs)
    except wt.GitStateSnapshotError as exc:
        raise ResultError('读取已记录的 Git 对象失败；未生成空结果', 'read_error') from exc


def _versions(payload):
    source = payload.get('source') or {}
    base, head = source.get('source_commit'), payload.get('integration_head')
    if not payload.get('merged'):
        raise ResultError('尚未记录任何集成成果；目录存在不代表已经产出', 'not_produced')
    if not base or not head:
        raise ResultError('历史未提供冻结来源或 integration head，不能使用当前 HEAD 替代',
                          'not_produced' if not head and not payload.get('merged') else 'historical_missing')
    if not all(isinstance(s, str) and _OID.fullmatch(s) for s in (base, head)):
        raise ResultError('已保存提交标识不合法', 'read_error')
    return base, head


def _repository(runtime, payload, base, head):
    candidates = []
    if payload.get('execution_backend') == 'codex_app_server':
        source = _known(runtime, 'source')
        if str(source.resolve()) != str(Path(payload['source']['project_path']).resolve()):
            raise ResultError('私有来源与任务目录不匹配', 'read_error')
        candidates.append(source)
    candidates.append(_known(runtime, 'integration'))
    for repo in candidates:
        if not repo.is_dir():
            continue
        try:
            if all(_git(repo, 'rev-parse', '--verify', oid + '^{commit}').decode().strip() == oid for oid in (base, head)):
                return repo
        except ResultError:
            continue
    raise ResultError('冻结基线或集成 Git 对象已不可用；可下载此前保存的结果包', 'missing')


def _path(raw):
    path = wt._decode_path(raw)
    # Portable Windows-safe paths; do not put traversal, ADS or .git aliases in patches.
    parts = path.split('/')
    if (any(not p or p in ('.', '..') or p.endswith((' ', '.')) or any(c in p for c in ':\\<>"|?*')
            or any(ord(c) < 32 for c in p) or re.fullmatch(r'(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p)
            for p in parts) or any(p.lower() == '.git' for p in parts)):
        raise ResultError('文件名无法安全用于当前 Windows 独立补丁', 'unsupported')
    return path


def _tree(repo, oid):
    entries = {}
    folded = set()
    total = 0
    for row in wt._nul_fields(_git(repo, 'ls-tree', '-r', '-l', '-z', oid), 'result tree'):
        header, sep, raw = row.partition(b'\t')
        fields = header.split()
        if not sep or len(fields) != 4:
            raise ResultError('Git tree 记录无法解析', 'read_error')
        mode, kind, blob, size = (s.decode('ascii') for s in fields)
        path = _path(raw)
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ResultError('当前不支持链接、子模块或特殊文件的完整代码导出', 'unsupported')
        if not size.isdecimal() or not _OID.fullmatch(blob):
            raise ResultError('Git blob 元数据无法解析', 'read_error')
        total += int(size)
        if int(size) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(entries) >= MAX_FILES:
            raise ResultError('结果超过 10 MiB/文件、100 MiB/版本或 10000 文件限制', 'unsupported')
        if path.casefold() in folded:
            raise ResultError('结果含重复或 Windows 大小写冲突路径', 'unsupported')
        folded.add(path.casefold())
        entries[path] = {'path': path, 'mode': mode, 'blob': blob, 'bytes': int(size)}
    return entries


def _changes(repo, base, head, before, after):
    fields = wt._nul_fields(_git(repo, 'diff', *wt._DIFF_OPTIONS, '--find-renames', '--find-copies',
                           '--find-copies-harder', '-l0', '--name-status', '-z', base, head, '--'), 'result changes')
    rows = []
    i = 0
    while i < len(fields):
        status = fields[i].decode('ascii'); i += 1
        if not re.fullmatch(r'[AMDT]|[RC][0-9]{1,3}', status):
            raise ResultError('Git 变更类型无法可靠解析', 'read_error')
        count = 2 if status[0] in 'RC' else 1
        if i + count > len(fields):
            raise ResultError('Git 路径记录不完整', 'read_error')
        paths = [_path(p) for p in fields[i:i+count]]; i += count
        old = paths[0] if status[0] != 'A' else None
        new = paths[-1] if status[0] != 'D' else None
        rows.append({'kind': status[0], 'old_path': old, 'path': new or old,
                     'before': before.get(old), 'after': after.get(new)})
    return rows


def _blobs(repo, entries):
    blobs = {v['blob']: v['bytes'] for v in entries}
    if not blobs:
        return {}
    stream = io.BytesIO(_git(repo, 'cat-file', '--batch', input=('\n'.join(blobs)+'\n').encode('ascii')))
    out = {}
    for oid, expected in blobs.items():
        if stream.readline().strip() != f'{oid} blob {expected}'.encode():
            raise ResultError('Git blob 响应不匹配', 'read_error')
        data = stream.read(expected)
        if len(data) != expected or stream.read(1) != b'\n':
            raise ResultError('Git blob 不完整', 'read_error')
        out[oid] = data
    if stream.read():
        raise ResultError('Git blob 响应多出内容', 'read_error')
    return out


def _sensitive(text):
    if _SECRET.search(text):
        raise ResultError('内容含凭据或完整 Prompt 标记；为保持补丁完整性，拒绝代码包而不改写补丁', 'restricted')


def frozen(runtime, payload, *, preview=False):
    base, head = _versions(payload)
    repo = _repository(runtime, payload, base, head)
    before, after = _tree(repo, base), _tree(repo, head)
    changes = _changes(repo, base, head, before, after)
    blobs = _blobs(repo, [e for e in [*before.values(), *after.values()] if not excluded(e['path'])])
    # Reject prohibited changes as a whole. Never drop a file and claim the patch is complete.
    restriction = None
    for row in changes:
        for entry in (row['before'], row['after']):
            if entry is None:
                continue
            if excluded(entry['path']):
                restriction = ResultError('净变化包含来源策略排除的缓存、运行或凭据文件；拒绝完整代码导出', 'restricted')
                continue
            data = blobs[entry['blob']]
            try:
                value = data.decode('utf-8')
            except UnicodeDecodeError as exc:
                restriction = ResultError('当前代码包仅支持 UTF-8 文本；二进制/其他编码需另行交付', 'unsupported')
                continue
            if '\0' in value:
                restriction = ResultError('当前不支持二进制代码导出，不会省略该文件', 'unsupported')
                continue
            if value.startswith('version https://git-lfs.github.com/spec/v1\n'):
                restriction = ResultError('Git LFS 指针不包含独立文件内容，当前拒绝此代码包', 'unsupported')
                continue
            # Inspect both old and new FULL blobs, covering deleted lines and context.
            try:
                _sensitive(value)
            except ResultError as exc:
                restriction = exc
    if restriction:
        if not preview:
            raise restriction
        return {'base_commit': base, 'result_commit': head, 'changes': changes,
                'restriction': str(restriction), 'status': restriction.status}
    patch = _git(repo, '-c', 'diff.noprefix=false', '-c', 'diff.mnemonicPrefix=false',
                 'diff', *wt._DIFF_OPTIONS, '--find-renames', '--find-copies', '--find-copies-harder',
                 '-l0', '--binary', '--full-index', '--src-prefix=a/', '--dst-prefix=b/',
                 '--no-indent-heuristic', '--diff-algorithm=myers', '--unified=3', base, head, '--')
    if bool(changes) != bool(patch):
        raise ResultError('变更清单与补丁空值不一致', 'read_error')
    _sensitive(patch.decode('utf-8'))
    def manifest(tree):
        return [{'path': e['path'], 'mode': e['mode'], 'bytes': e['bytes'], 'sha256': _digest(blobs[e['blob']])}
                for e in tree.values() if not excluded(e['path'])]
    return {'base_commit': base, 'result_commit': head, 'changes': changes,
            'baseline_files': manifest(before), 'result_files': manifest(after), 'patch': patch, 'repo': repo}


def _portable(value):
    """Summaries may omit private paths, but code is never silently redacted."""
    if isinstance(value, str):
        _sensitive(value)
        value = re.sub(r'(?i)(?:[A-Z]:[\\/]|\\\\)[^\s"<>]+|(?<![\w:./])/(?!/)[^\s"<>]+', '[local path]', value)
        return value if len(value) <= 2000 else {'text': value[:2000], 'truncated': True, 'original_chars': len(value), 'sha256': _digest(value.encode())}
    if isinstance(value, list):
        return [_portable(v) for v in value]
    if isinstance(value, dict):
        return {k: _portable(v) for k, v in value.items()}
    return value


def _summary(evidence):
    # No stdout/stderr, full validation input, config, user_notes or raw records.
    g = evidence['gates']
    v = evidence['verifier']
    verifier = v.get('record') or {}
    summary = {'mission': evidence['mission'], 'acceptance_criteria': evidence['acceptance_criteria'],
               'gates': {'status': g['status'], 'error': g.get('error'), 'records': [
                   {k: r.get(k) for k in ('id', 'task_id', 'phase', 'command', 'exit_code', 'command_status',
                       'integrity', 'scope', 'overall', 'started_at', 'ended_at', 'output', 'historical_fields_missing')}
                   for r in g['records']]},
               'verifier': {'status': v['status'], 'error': v.get('error'),
                    **{k: verifier.get(k) for k in ('verify_id', 'task_id', 'verdict', 'summary', 'ac_checks', 'anti_gaming')}}}
    # Only documented AC fields; additionalProperties may contain raw prompts.
    for field in ('ac_checks', 'anti_gaming'):
        rows = summary['verifier'][field]
        summary['verifier'][field] = [{k: r.get(k) for k in ('ac_id', 'verdict', 'note')} for r in rows] if isinstance(rows, list) else None
    for r in summary['gates']['records']:
        for field in ('integrity', 'scope'):
            r[field] = {k: (r.get(field) or {}).get(k) for k in ('status', 'reason')}
        r['output'] = {stream: {k: meta.get(k) for k in ('truncated', 'original_length', 'limit_chars', 'sha256')}
                       for stream, meta in (r.get('output') or {}).items()
                       if stream in ('stdout', 'stderr') and isinstance(meta, dict)}
    return _portable(summary)


def _package_file(runtime, identity):
    if not isinstance(identity, str) or not _IDENTITY.fullmatch(identity):
        raise ResultError('结果包标识不合法', 'invalid')
    return _known(runtime, 'exports/' + identity + '.zip')


def package_bytes(runtime, record):
    path = _package_file(runtime, record['identity'])
    try:
        if path.stat().st_size != record['bytes'] or path.stat().st_size > MAX_TOTAL_BYTES * 3:
            raise ValueError('size')
        data = path.read_bytes()
        if _digest(data) != record['sha256']:
            raise ValueError('checksum')
        return data
    except (OSError, ValueError) as exc:
        raise ResultError('已保存结果包缺失或校验失败', 'read_error') from exc


def overview(runtime, mid):
    payload, evidence, exports = facts(runtime, mid)
    try:
        path = _known(runtime, 'integration')
        produced = bool(payload.get('integration_head') or payload.get('merged'))
        location = {'status': 'available' if path.is_dir() else 'missing' if produced else 'not_produced',
                    'path': str(path) if path.is_dir() or produced else None}
    except (OSError, ResultError) as exc:
        location = {'status': 'read_error', 'path': None, 'reason': str(exc)}
    result = {'mission_id': mid, 'evidence': evidence,
              'location': location,
              'exports': [], 'changes': []}
    for record in exports:
        public = {k: record[k] for k in ('identity', 'sha256', 'bytes', 'created_at', 'base_commit', 'result_commit', 'accepted')}
        try:
            package_bytes(runtime, record)
            public['status'] = 'ready'
        except ResultError as exc:
            public.update(status='read_error', reason=str(exc))
        result['exports'].append(public)
    try:
        frozen_result = frozen(runtime, payload, preview=True)
        result.update(status=frozen_result.get('status', 'ok'), base_commit=frozen_result['base_commit'], result_commit=frozen_result['result_commit'],
                      changes=frozen_result['changes'])
        if frozen_result.get('restriction'):
            result['reason'] = frozen_result['restriction']
            return result
        result.update(
                      changes=frozen_result['changes'], no_changes=not frozen_result['changes'],
                      diff=frozen_result['patch'][:DISPLAY_LIMIT].decode('utf-8', errors='replace'),
                      diff_truncated=len(frozen_result['patch']) > DISPLAY_LIMIT,
                      diff_bytes=len(frozen_result['patch']), diff_sha256=_digest(frozen_result['patch']))
    except (ResultError, wt.GitStateSnapshotError, UnicodeError) as exc:
        result.update(status=getattr(exc, 'status', 'read_error'), reason=str(exc))
        # A verified saved package is an independent frozen copy. Never substitute
        # a different head's package or relabel its acceptance with current facts.
        source = payload.get('source') or {}
        for record in exports:
            if (record.get('base_commit') != source.get('source_commit')
                    or record.get('result_commit') != payload.get('integration_head')):
                continue
            try:
                with zipfile.ZipFile(io.BytesIO(package_bytes(runtime, record))) as archive:
                    manifest = json.loads(archive.read('manifest.json'))
                    patch = archive.read('changes.patch')
                if (manifest['base_commit'] != record['base_commit'] or manifest['result_commit'] != record['result_commit']
                        or manifest['patch_sha256'] != _digest(patch)):
                    raise ValueError('package manifest mismatch')
                result.update(status='saved', reason='Git 对象当前不可读取；以下修改来自已保存的固定结果包',
                    base_commit=record['base_commit'], result_commit=record['result_commit'],
                    changes=manifest['changes'], no_changes=manifest['no_changes'],
                    diff=patch[:DISPLAY_LIMIT].decode('utf-8', errors='replace'),
                    diff_truncated=len(patch)>DISPLAY_LIMIT, diff_bytes=len(patch), diff_sha256=_digest(patch))
                break
            except (ResultError, OSError, ValueError, KeyError, zipfile.BadZipFile):
                continue
    return result


_INSTRUCTIONS = '''# CLAO 独立结果包

验收标记：{acceptance}。详细历史事实见 evidence.json；缺失/未知不代表通过。
本包未自动写回原项目，不含项目依赖或运行环境，不是独立可执行应用。

changes.patch 是冻结基线到已记录集成提交的完整净变化，不是模型证据文本。
manifest.json 给出两个版本的相对文件名、SHA-256、大小和 Git 文件模式。
对本地普通目录/无远端仓库，base_commit 是 CLAO 私有标识；无需也不能要求原仓库 checkout 它。

1. 准备一个独立的基线目录副本（不要在唯一的用户项目上操作）。其文件内容应匹配
   manifest.json 的 baseline_files；允许来源策略排除的未变化本地文件另外保留。
   空项目的基线为空目录；包不附带未修改源码，非空基线须由你保留其副本。
2. 将本包解压在副本之外。从副本根目录执行（需要 Git，不需要 Git 仓库）：

   git -c core.autocrlf=false apply --check ../result-package/changes.patch
   git -c core.autocrlf=false apply --whitespace=nowarn ../result-package/changes.patch

   如 manifest.json 中 no_changes=true，补丁为空，应跳过这两条命令。
   不添加 --index、--3way、--unsafe-paths，也不要初始化仓库或查找私有 commit。
3. 对照 result_files 的 SHA-256/大小逐文件核对，确认删除路径已消失。
   如需验证内容，可使用 Python hashlib.sha256(Path(relative_path).read_bytes()).hexdigest()。
   文件模式在补丁中保留；Windows 普通文件系统不提供 Unix executable bit 的等价执行权限。
4. 阅读 evidence.json 的 Gate 命令，人工确认后在该副本安装项目自己的依赖并运行相应验收。
   原验收结论仅属于已记录结果，应用包本身不会调用模型或自动执行 Gate。

支持 UTF-8 普通文本、新增/修改/删除/重命名/复制及 Git 100644/100755 模式。
二进制、其他编码、链接、子模块、不安全或 Windows 不可表示的路径明确拒绝整包。
变化中含来源排除材料或检测到凭据/完整 Prompt 标记时拒绝整包，不删减补丁脱敏。
这不是通用密钥扫描器；发布或发送成果前仍需检查项目中的敏感业务内容。
'''


def export(runtime, mid):
    with _LOCK:
        payload, evidence, existing = facts(runtime, mid)
        result = frozen(runtime, payload)
        summary = _summary(evidence)
        manifest = {k: result[k] for k in ('base_commit', 'result_commit', 'changes', 'baseline_files', 'result_files')}
        manifest.update(format=FORMAT, no_changes=not result['changes'], patch_sha256=_digest(result['patch']),
                        source_policy='filtered_current_working_content' if payload.get('execution_backend') == 'codex_app_server' else 'historical Git source',
                        accepted=evidence['mission']['accepted'])
        _sensitive(_json(manifest).decode('utf-8'))
        # The identity includes the frozen evidence, so later facts never relabel an older package.
        identity = _digest(_json(manifest) + _json(summary))
        prior = next((r for r in existing if r['identity'] == identity), None)
        if prior:
            package_bytes(runtime, prior)
            return prior
        instructions = _INSTRUCTIONS.format(acceptance='已通过 Mission 最终验收' if manifest['accepted'] else '未通过最终验收').encode('utf-8')
        contents = {'changes.patch': result['patch'], 'manifest.json': _json(manifest),
                    'evidence.json': _json(summary), 'README.md': instructions}
        dest = _package_file(runtime, identity)
        dest.parent.mkdir(exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=dest.parent, suffix='.partial', delete=False) as f:
                temp = Path(f.name)
                with zipfile.ZipFile(f, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                    for name, data in contents.items():
                        info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                        info.compress_type = zipfile.ZIP_DEFLATED
                        archive.writestr(info, data)
                f.flush(); os.fsync(f.fileno())
            data = temp.read_bytes()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if archive.testzip() is not None or set(archive.namelist()) != set(contents):
                    raise ResultError('结果包完整性校验失败', 'read_error')
            os.replace(temp, dest)
            record = {'identity': identity, 'sha256': _digest(data), 'bytes': len(data), 'created_at': now_iso(),
                      'base_commit': result['base_commit'], 'result_commit': result['result_commit'],
                      'accepted': manifest['accepted']}
            StateStore.save_result_export(_known(runtime, 'state.db'), mid, identity, record)
            return record
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)


def download(runtime, mid, identity):
    _package_file(runtime, identity)
    # Download needs only its StateStore record and package, not Git/model/Worker.
    conn = StateStore.read_connection(_known(runtime, 'state.db'), timeout=3)
    try:
        rows = StateStore.query_result_exports(conn, mid)
    finally:
        conn.close()
    record = next((r for r in rows if r.get('identity') == identity), None)
    if not record:
        raise ResultError('该任务没有此结果包记录', 'invalid')
    return package_bytes(runtime, record)
