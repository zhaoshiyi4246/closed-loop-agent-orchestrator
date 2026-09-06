"""Deterministic worktree introspection for the closed loop.

A plain PROGRAM (not an agent): no model, no AO control, only read-only git
inspection inside the worker's worktree. Used by the Integration Gate (path
gating) and the closed-loop controller (progress fingerprinting / thrash
detection).

All scope/evidence reads use a frozen base, NUL-delimited Git paths and
separate committed/index/working layers. Untracked evidence uses a disposable
index outside the repository. Artifact filtering never changes ignore policy.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import shutil
import tempfile
from contextlib import contextmanager
import os
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


def _git(worktree: str, *args: str, timeout: int = 30) -> Optional[str]:
    """Run a read-only git command; None on ANY failure (fail-closed).

    Previously every error (missing repo, timeout, non-zero exit) was
    swallowed into "" which downstream read as "no changes" — the path gate
    and the Verifier then waved through unaudited work (review 簇四).
    """
    try:
        return _snapshot_git(worktree, *args, timeout=timeout).decode("utf-8")
    except (GitStateSnapshotError, UnicodeDecodeError):
        return None


def _current_head(worktree: str) -> Optional[str]:
    out = _git(worktree, "rev-parse", "HEAD")
    if not out:
        return None
    return out.strip() or None


def freeze_base(worktree: str, store, task_id: str, scope: str = "") -> str:
    """Return the base commit for this task, freezing HEAD on first call.

    The SHA is kept in a JSON sidecar OUTSIDE the worktree (worker edits cannot
    tamper with it); a marker counter in the store signals "already frozen" so a
    later call returns the frozen SHA instead of re-reading HEAD (the worker may
    have committed since, which would hide its edits from the gate).

    `scope` isolates concurrent workers on the SAME task: the counter key
    becomes base_commit:<task>:<scope> and the sidecar file is named per
    scope. Without it, two parallel workers would share one frozen SHA and
    each diff/path-gate would be computed against the WRONG worktree's HEAD.
    """
    tag = ("%s:%s" % (task_id, scope)) if scope else task_id
    key = "base_commit:" + tag
    existing = store.counter_get(key)
    if existing:
        # Counter says frozen: the sidecar MUST hold the SHA. A crash between
        # the two writes used to leave base "" (fail-open); write order is
        # now sidecar-first, and an unreadable sidecar returns "" so callers
        # escalate instead of diffing against nothing.
        return _read_base_sidecar(worktree, tag)
    head = _current_head(worktree)
    if not head:
        return ""
    _write_base_sidecar(worktree, tag, head)
    store.counter_set(key, 1)
    return head


def _sidecar_path(worktree: str, tag: str) -> Path:
    # lives outside the worktree so worker edits cannot tamper with it
    return Path(worktree).parent / (".base-" + tag.replace(":", "-") + ".json")


def _read_base_sidecar(worktree: str, tag: str) -> str:
    import json
    p = _sidecar_path(worktree, tag)
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("base_commit", "")
    except Exception:
        return ""


def _write_base_sidecar(worktree: str, tag: str, sha: str) -> None:
    import json
    p = _sidecar_path(worktree, tag)
    p.write_text(json.dumps({"base_commit": sha}), encoding="utf-8")


def changed_paths(worktree: str, base_commit: str) -> Optional[List[str]]:
    """Union of committed, staged and working changes; None means UNKNOWN.

    Working evidence includes untracked files through a disposable index.
    R/C records contribute BOTH endpoints, even when their source is unchanged.
    """
    try:
        with _change_layers(worktree, base_commit) as layers:
            return sorted({p for _label, _revision, paths, _env in layers
                           for p in paths})
    except GitStateSnapshotError:
        return None


_ARTIFACT_DIRS = frozenset({
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".hypothesis", ".eggs",
})


def _is_artifact(path: str) -> bool:
    """Git paths use '/' separators. Match directory segments or exact suffixes.

    A literal backslash in a POSIX Git name is not a directory separator.
    Coverage's parallel files have the documented .coverage.host.pid.random
    form; .coverage_policy.py and .coverage.config remain ordinary files.
    """
    parts = path.split("/")
    name = parts[-1]
    return (any(part in _ARTIFACT_DIRS for part in parts[:-1])
            or name.endswith((".pyc", ".pyo"))
            or name == ".coverage"
            or re.fullmatch(r"\.coverage\.[^.]+\.[0-9]+\.[A-Za-z0-9]+", name) is not None)


@dataclass(frozen=True)
class GitStateSnapshot:
    """Content-sensitive, read-only state of a Git worktree.

    ``digest`` distinguishes HEAD, the index, tracked working-tree content,
    and non-artifact untracked path/content.  It intentionally omits the
    underlying diffs so Gate evidence stays bounded.
    """

    head: str
    digest: str
    clean: bool


class GitStateSnapshotError(RuntimeError):
    """A required Git probe, parse, or untracked-file read failed."""


def _read_env(overrides=None):
    env = os.environ.copy()
    # A parent Git process must not redirect probes to a different index/repo.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS",
                "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS"):
        env.pop(key, None)
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1")
    env.update(overrides or {})
    return env


def _snapshot_git(worktree: str, *args: str, timeout: int = 30,
                  env=None, input=None) -> bytes:
    """Required byte probe; temporary-index writes require an explicit env.

    Disable optional index refresh and external diff/textconv at each diff
    call. No read path acquires or rewrites the real index.
    """
    try:
        command = ["git", "--no-optional-locks", "-c", "diff.autoRefreshIndex=false",
                   "-c", "core.fsmonitor=false", "-C", str(worktree)]
        read_env = _read_env(env)
        if args[0] == "diff" or "add" in args[:6]:
            configured = subprocess.run(
                [*command, "config", "--null", "--name-only", "--get-regexp",
                 r"^filter\..*\.(clean|process)$"], capture_output=True,
                timeout=timeout, shell=False, check=False, env=read_env)
            if configured.returncode not in (0, 1):
                raise GitStateSnapshotError("unable to inspect Git content filters")
            for raw_key in _nul_fields(configured.stdout, "Git content filters"):
                key = raw_key.decode("utf-8")
                if not re.fullmatch(r"filter\.[^\r\n]+\.(clean|process)", key):
                    raise GitStateSnapshotError("unsupported Git content-filter key")
                command += ["-c", key + "="]
        proc = subprocess.run(
            [*command, *args], capture_output=True, timeout=timeout,
            shell=False, check=False, env=read_env, input=input,
        )
    except Exception as exc:
        raise GitStateSnapshotError(
            "git %s could not run: %s" %
            (" ".join(args[:3]), str(exc)[:500])) from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or b"").decode(
            "utf-8", errors="replace").strip()
        raise GitStateSnapshotError(
            "git %s exited with code %d%s" %
            (" ".join(args[:3]), proc.returncode,
             (": " + detail[:500]) if detail else ""))
    return proc.stdout or b""


def _nul_fields(raw: bytes, probe: str) -> List[bytes]:
    if not raw:
        return []
    if not raw.endswith(b"\0") or any(not p for p in raw[:-1].split(b"\0")):
        raise GitStateSnapshotError("%s returned malformed NUL data" % probe)
    return raw[:-1].split(b"\0")


def _decode_path(raw: bytes) -> str:
    try:
        path = os.fsdecode(raw)
        if (os.fsencode(path) != raw or path.startswith("/")
                or any(p in ("", ".", "..") for p in path.split("/"))
                or (os.name == "nt" and ("\\" in path or ":" in path))):
            raise ValueError("not an exact repository-relative path")
        return path
    except Exception as exc:
        raise GitStateSnapshotError("invalid Git path: %r" % raw[:300]) from exc


def _nul_paths(raw: bytes, probe: str) -> List[str]:
    return [_decode_path(item) for item in _nul_fields(raw, probe)]


def _name_status_paths(raw: bytes, *, filter_artifacts=False) -> List[str]:
    fields = _nul_fields(raw, "git name-status")
    paths = set()
    i = 0
    while i < len(fields):
        status = fields[i]
        i += 1
        if not re.fullmatch(rb"(?:[ADT]|M[0-9]{0,3}|[RC][0-9]{1,3})", status):
            raise GitStateSnapshotError("unsupported Git status: %r" % status)
        if len(status) > 1 and int(status[1:]) > 100:
            raise GitStateSnapshotError("invalid Git similarity score")
        count = 2 if status[:1] in (b"R", b"C") else 1
        if i + count > len(fields):
            raise GitStateSnapshotError("incomplete Git rename/copy/path record")
        record = [_decode_path(p) for p in fields[i:i + count]]
        i += count
        if filter_artifacts:
            # Copying into a cache does not modify its source. A rename away
            # from source DOES delete it, even when the destination is cache.
            if status.startswith(b"C") and _is_artifact(record[-1]):
                continue
            record = [p for p in record if not _is_artifact(p)]
        paths.update(record)
    return sorted(paths)


_DIFF_OPTIONS = ("--no-ext-diff", "--no-textconv", "--no-relative", "--no-color",
                 "--ignore-submodules=none")


def _layer_paths(worktree, revision=(), *, env=None, detect_copies=True):
    detection = ("--find-renames", "--find-copies", "--find-copies-harder", "-l0") \
        if detect_copies else ("--no-renames",)
    raw = _snapshot_git(worktree, "diff", *_DIFF_OPTIONS, *detection,
                        "--name-status", "-z", *revision, "--", env=env)
    return _name_status_paths(raw, filter_artifacts=True)


def _layer_diff(worktree, revision, paths, *, env=None):
    if not paths:
        return b""
    return _snapshot_git(
        worktree, "diff", *_DIFF_OPTIONS, "--no-renames", "--binary",
        "--full-index", *revision, "--",
        *[":(top,literal)%s" % p for p in paths], env=env)


def _untracked_paths(worktree):
    return sorted(set(p for p in _nul_paths(_snapshot_git(
        worktree, "ls-files", "--others", "--exclude-standard", "--full-name",
        "-z", "--"), "git untracked") if not _is_artifact(p)))


def _check_index(worktree):
    """Do not report clean when index flags or gitlinks hide user content."""
    raw = _snapshot_git(worktree, "ls-files", "--stage", "-v", "--full-name", "-z")
    for record in _nul_fields(raw, "git index entries"):
        # Only the fixed metadata header contains the FIRST tab separator;
        # the complete remaining path can itself contain arbitrary tabs.
        header, separator, path_bytes = record.partition(b"\t")
        if not separator:
            raise GitStateSnapshotError("malformed Git index entry")
        path = _decode_path(path_bytes)
        if _is_artifact(path):
            continue
        if not re.fullmatch(rb"H (?:100644|100755|120000) [0-9a-f]{40}(?:[0-9a-f]{24})? 0", header):
            raise GitStateSnapshotError(
                "index entry requires manual inspection (hidden/unmerged/submodule): %r" % path)


def _absolute_git_path(worktree, *args):
    raw = _snapshot_git(worktree, "rev-parse", "--path-format=absolute", *args)
    if not raw.endswith(b"\n"):
        raise GitStateSnapshotError("Git filesystem path missing terminator")
    return Path(os.fsdecode(raw[:-1]))


def _read_untracked(root, path):
    candidate = root / path
    try:
        # Read a leaf symlink's target string, never the target's content.
        if not candidate.parent.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
            raise ValueError("untracked parent escapes repository")
        mode = candidate.lstat().st_mode
        if stat.S_ISLNK(mode):
            return b"symlink", os.fsencode(os.readlink(candidate))
        if stat.S_ISREG(mode):
            return b"file", candidate.read_bytes()
        raise ValueError("unsupported untracked file type")
    except Exception as exc:
        raise GitStateSnapshotError("unable to read untracked %r: %s" %
                                    (path, str(exc)[:500])) from exc


@contextmanager
def _working_index(worktree):
    """Overlay untracked intent-to-add in an external disposable index.

    Objects written by Git also go to the disposable directory. No reset,
    restore, ignore-policy change, or real-index write is needed on success
    OR exception. Disabling splitIndex prevents shared-index writes.
    """
    untracked = _untracked_paths(worktree)
    if not untracked:
        yield None, []
        return
    root = _absolute_git_path(worktree, "--show-toplevel")
    for path in untracked:
        _read_untracked(root, path)
    index = _absolute_git_path(worktree, "--git-path", "index")
    objects = _absolute_git_path(worktree, "--git-path", "objects")
    try:
        with tempfile.TemporaryDirectory(prefix="clao-git-evidence-") as temp:
            temp = Path(temp)
            shutil.copyfile(index, temp / "index")
            (temp / "objects" / "info").mkdir(parents=True)
            # Git's alternates file uses one object directory per line.
            if "\n" in str(objects) or "\r" in str(objects):
                raise GitStateSnapshotError("unsupported object-directory line break")
            (temp / "objects" / "info" / "alternates").write_bytes(
                os.fsencode(objects.as_posix()) + b"\n")
            env = {"GIT_INDEX_FILE": str(temp / "index"),
                   "GIT_OBJECT_DIRECTORY": str(temp / "objects")}
            _snapshot_git(
                worktree, "-c", "core.splitIndex=false",
                "-c", "core.hooksPath=" + str(temp / "no-hooks"), "add", "-N",
                "--pathspec-from-file=-", "--pathspec-file-nul", env=env,
                input=b"".join(os.fsencode(":(top,literal)" + p) + b"\0"
                               for p in untracked))
            yield env, untracked
    except GitStateSnapshotError:
        raise
    except Exception as exc:
        raise GitStateSnapshotError("temporary Git evidence failed: %s" % exc) from exc


@contextmanager
def _change_layers(worktree, base_commit):
    if not isinstance(base_commit, str) or not re.fullmatch(
            r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", base_commit):
        raise GitStateSnapshotError("frozen base commit unavailable or invalid")
    _check_index(worktree)
    # Two endpoints, not ... (which would silently substitute the merge-base).
    committed = (base_commit, "HEAD")
    staged = ("--cached", "HEAD")
    committed_paths = _layer_paths(worktree, committed)
    staged_paths = _layer_paths(worktree, staged)
    with _working_index(worktree) as (env, untracked):
        working_paths = sorted(set(_layer_paths(worktree, env=env)) | set(untracked))
        yield [("committed", committed, committed_paths, None),
               ("staged", staged, staged_paths, None),
               ("unstaged / untracked", (), working_paths, env)]


def _non_artifact_diff(worktree: str, *, cached: bool) -> tuple[bytes, bytes]:
    revision = ("--cached", "HEAD") if cached else ()
    paths = _layer_paths(worktree, revision)
    return (b"\0".join(os.fsencode(p) for p in paths),
            _layer_diff(worktree, revision, paths))


def _hash_frame(hasher, label: bytes, payload: bytes) -> None:
    hasher.update(label)
    hasher.update(len(payload).to_bytes(8, byteorder="big"))
    hasher.update(payload)


def git_state_snapshot(worktree: str) -> GitStateSnapshot:
    """Capture Gate-relevant repository state without changing it.

    Required probes fail explicitly.  Tracked artifact paths and untracked
    test/build artifacts use the same ``_is_artifact`` policy as the existing
    path gate.  External diff drivers and textconv are disabled.
    """
    _check_index(worktree)
    raw_head = _snapshot_git(worktree, "rev-parse", "HEAD")
    try:
        head = raw_head.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise GitStateSnapshotError(
            "git rev-parse HEAD returned non-ASCII data") from exc
    if (len(head) not in (40, 64) or
            any(ch not in "0123456789abcdefABCDEF" for ch in head)):
        raise GitStateSnapshotError(
            "git rev-parse HEAD did not return one commit SHA")

    cached_paths, cached_diff = _non_artifact_diff(worktree, cached=True)
    unstaged_paths, unstaged_diff = _non_artifact_diff(
        worktree, cached=False)
    untracked_paths = _untracked_paths(worktree)
    root = _absolute_git_path(worktree, "--show-toplevel")
    untracked = hashlib.sha256()
    for path in untracked_paths:
        kind, content = _read_untracked(root, path)
        _hash_frame(untracked, b"path", os.fsencode(path))
        _hash_frame(untracked, b"kind", kind)
        _hash_frame(untracked, b"content-sha256", hashlib.sha256(content).digest())

    state = hashlib.sha256()
    _hash_frame(state, b"head", head.encode("ascii"))
    _hash_frame(state, b"cached-paths", cached_paths)
    _hash_frame(state, b"cached-diff-sha256",
                hashlib.sha256(cached_diff).digest())
    _hash_frame(state, b"unstaged-paths", unstaged_paths)
    _hash_frame(state, b"unstaged-diff-sha256",
                hashlib.sha256(unstaged_diff).digest())
    _hash_frame(state, b"untracked-sha256", untracked.digest())
    clean = not (cached_paths or unstaged_paths or untracked_paths)
    return GitStateSnapshot(head=head, digest=state.hexdigest(), clean=clean)


def diff_fingerprint(worktree: str, base_commit: str) -> str:
    """Stable fingerprint of the current change set + HEAD.

    Changes when the worker edits, commits, or reverts any file; stable on
    repeated reads of an unchanged tree. Used to detect thrash (same diff
    reappearing / being undone).
    """
    paths = changed_paths(worktree, base_commit)
    head = _current_head(worktree) or ""
    if paths is None:
        # git failed: a constant error marker keeps the fingerprint stable
        # across reads (no false thrash) but distinct from any real change.
        raw = "GIT-ERROR\n" + head
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()
    raw = json.dumps([head, paths], ensure_ascii=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def path_violations(worktree: str, base_commit: str, *,
                    allowed_paths: List[str],
                    forbidden_paths: List[str]) -> Tuple[List[str], List[str]]:
    """Return (forbidden_violations, allowed_violations).

    forbidden_violations: changed paths matching any forbidden pattern.
    allowed_violations : changed paths OUTSIDE every allowed pattern
                         (empty allowed_paths authorizes no changes).
    """
    changed = changed_paths(worktree, base_commit)
    if changed is None:
        # fail-closed: an unauditable tree must never read as "clean"
        return ["<git-error: changed paths unavailable>"], []
    return scope_violations(changed, allowed_paths=allowed_paths,
                            forbidden_paths=forbidden_paths)


def scope_violations(changed: List[str], *, allowed_paths: List[str],
                     forbidden_paths: List[str]) -> Tuple[List[str], List[str]]:
    """Check already-collected exact paths; forbidden rules take precedence."""
    forbidden = []
    for path in changed:
        for pat in forbidden_paths or []:
            p = pat.replace("\\", "/").rstrip("/")
            if fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path, p + "/*"):
                forbidden.append(path)
                break
    allowed = []
    if changed:
        for path in changed:
            if path in forbidden:
                continue
            if not any(
                fnmatch.fnmatch(path, a.replace("\\", "/").rstrip("/")) or
                fnmatch.fnmatch(path, a.replace("\\", "/").rstrip("/") + "/*")
                for a in allowed_paths or []):
                allowed.append(path)
    return forbidden, allowed


def _head_tail(text: str, limit: Optional[int]) -> str:
    """Truncate keeping BOTH ends: the head carries the diff headers/stat,
    the tail carries the final hunks — plain [:limit] slicing used to drop
    the verdict-critical tail of a large diff entirely (review: verifier
    evidence)."""
    if limit is None or len(text) <= limit:
        return text
    head = int(limit * 0.65)
    tail = limit - head - 64
    return (text[:head]
            + "\n[loopcore] ... %d chars elided ...\n"
              % (len(text) - head - tail)
            + text[-tail:])


def git_diff_text(worktree: str, base_commit: str, limit: Optional[int] = 12000) -> str:
    """Full layer evidence, including new files, without writing the real index.

    JSON path lists preserve exact endpoints even when patch display quotes
    names. Errors invalidate the entire evidence rather than returning a
    partial diff as successful. Existing role consumers recognize unavailable.
    """
    try:
        chunks = []
        with _change_layers(worktree, base_commit) as layers:
            for label, revision, paths, env in layers:
                if paths:
                    chunks.append("[loopcore] %s paths=%s\n" %
                                  (label, json.dumps(paths, ensure_ascii=True)))
                    chunks.append(_layer_diff(worktree, revision, paths, env=env)
                                  .decode("utf-8", errors="backslashreplace"))
        return _head_tail("".join(chunks), limit)
    except GitStateSnapshotError as exc:
        return "[loopcore] git diff unavailable (git error): %s\n" % str(exc)[:1000]


# ------------------------------------------------------ integration merge
def _git_check(worktree: str, *args: str, timeout: int = 60) -> Tuple[bool, str]:
    """Run git and require success; returns (ok, combined output)."""
    try:
        proc = subprocess.run(["git", "-C", worktree, *args],
                              capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace",
                              env=_read_env())
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode == 0, out
    except Exception as e:  # noqa
        return False, str(e)


def _materializable_paths(worktree, head):
    untracked = set(_untracked_paths(worktree))
    changed = set(_layer_paths(worktree, (head,), detect_copies=False)) | untracked
    indexed = set(_nul_paths(_snapshot_git(
        worktree, "ls-files", "--cached", "--full-name", "-z", "--"), "git index"))
    # Already-staged deletions no longer have an index/worktree entry; git add
    # on those pathspecs fails. They remain in the explicit commit path list.
    return sorted(changed), sorted(changed & (indexed | untracked))


def _tree_entries(worktree, revision):
    """Exact leaf entries, also suitable for NUL-delimited index-info input."""
    if not isinstance(revision, str) or not re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise GitStateSnapshotError("materialization requires an exact frozen base/commit")
    entries = {}
    raw = _snapshot_git(worktree, "ls-tree", "-r", "-z", "--full-tree", revision, "--")
    for record in _nul_fields(raw, "git tree"):
        metadata, sep, path = record.partition(b"\t")
        if not sep or not re.fullmatch(
                rb"(?:(?:100644|100755|120000) blob|160000 commit) "
                rb"(?:[0-9a-f]{40}|[0-9a-f]{64})", metadata):
            raise GitStateSnapshotError("invalid git tree entry")
        name = _decode_path(path)
        if name in entries:
            raise GitStateSnapshotError("duplicate git tree path")
        entries[name] = record
    return entries


def _delivery_commit(worktree, head, base_entries, message):
    """Append a delivery commit object; leave Worker refs/index/files intact.

    Artifact entries come from the frozen base, including their original mode
    and blob. All other entries come from the materialized Worker HEAD. The
    original commits remain parents; no existing history is rewritten.
    """
    current = _tree_entries(worktree, head)
    delivery = {p: entry for p, entry in current.items() if not _is_artifact(p)}
    delivery.update({p: entry for p, entry in base_entries.items() if _is_artifact(p)})
    if delivery == current:
        return head
    try:
        with tempfile.TemporaryDirectory(prefix="clao-git-delivery-") as temp:
            env = {"GIT_INDEX_FILE": str(Path(temp) / "index")}
            # This index is built exclusively from existing tree entries. No
            # worktree checkout, filters, hooks or real-index updates occur.
            # Git for Windows otherwise silently skips tree-only Tab/newline
            # paths. This override is confined to the disposable index; real
            # checkout/merge retains the user's filesystem protections.
            options = ("-c", "core.splitIndex=false", "-c", "core.protectNTFS=false")
            _snapshot_git(worktree, *options, "read-tree", "--empty", env=env)
            if delivery:
                _snapshot_git(worktree, *options, "update-index", "-z", "--index-info",
                              env=env, input=b"".join(
                                  delivery[p] + b"\0" for p in sorted(delivery)))
            tree = _snapshot_git(worktree, *options, "write-tree", env=env).strip().decode("ascii")
            # In particular, a file/directory collision with a baseline cache
            # must fail, never silently replace a normal user entry.
            if _tree_entries(worktree, tree) != delivery:
                raise GitStateSnapshotError("materialized tree does not match delivery entries")
            commit = _snapshot_git(worktree, "commit-tree", tree, "-p", head,
                                   "-m", message + "\n\nPreserve frozen-base artifact entries.")
            sha = commit.strip().decode("ascii")
            if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
                raise GitStateSnapshotError("invalid materialized commit id")
            return sha
    except (OSError, UnicodeError) as exc:
        raise GitStateSnapshotError("unable to form materialized delivery: %s" % exc) from exc


def commit_all(worktree: str, message: str, *, base_commit: Optional[str] = None) -> str:
    """Commit user edits and, with a frozen base, return a clean delivery SHA.

    Called ONLY by trusted controller code (never the worker) so the merge
    pipeline has an explicit commit to fetch. With a frozen base, committed
    artifacts are restored to that base in a separate commit object, without
    moving Worker HEAD or changing its staged artifacts. Materialization gets
    one short retry for transient local Git failures; persistent failures
    raise with bounded, stage-specific Git
    output so the controller can preserve the real evidence.
    """
    head = _current_head(worktree)
    if not head:
        raise RuntimeError("git inspection failed: unable to read current HEAD")
    base_entries = _tree_entries(worktree, base_commit) if base_commit is not None else None

    # Validate every layer first; stage only the net working delivery. Sources
    # of copies belong to scope, but are not themselves edits to materialize.
    if changed_paths(worktree, head) is None:
        raise RuntimeError("git inspection failed: unable to inspect Worker changes")
    try:
        changed, to_add = _materializable_paths(worktree, head)
    except GitStateSnapshotError as exc:
        raise RuntimeError("git inspection failed: %s" % exc) from exc
    if not changed:
        return (_delivery_commit(worktree, head, base_entries, message)
                if base_entries is not None else head)
    pathspecs = [":(top,literal)%s" % path for path in changed]
    add_specs = [":(top,literal)%s" % path for path in to_add]

    last_stage = "git commit"
    last_detail = ""
    for attempt in range(2):
        ok, detail = (_git_check(worktree, "add", "-A", "--", *add_specs)
                      if add_specs else (True, ""))
        if not ok:
            last_stage, last_detail = "git add", detail
        else:
            # --only excludes already-staged caches without unstaging them.
            ok, detail = _git_check(worktree, "commit", "-q", "--only", "-m",
                                    message, "--", *pathspecs)
            if ok:
                committed_head = _current_head(worktree)
                if not committed_head:
                    raise RuntimeError(
                        "git commit succeeded but reading HEAD failed")
                return (_delivery_commit(worktree, committed_head, base_entries, message)
                        if base_entries is not None else committed_head)
            last_stage, last_detail = "git commit", detail

        if attempt == 0:
            time.sleep(0.5)

    detail = (last_detail or "<no git output>").strip()
    raise RuntimeError("%s failed: %s" %
                       (last_stage, _head_tail(detail, 1000)))


def _main_head(repo_path: str) -> Optional[str]:
    """HEAD of the MAIN worktree of the repo containing `repo_path`.

    `git worktree list --porcelain` always lists the main worktree first.
    """
    try:
        raw = _snapshot_git(repo_path, "worktree", "list", "--porcelain", "-z")
        if not raw.endswith(b"\0\0"):
            return None
        first = raw.split(b"\0\0", 1)[0].split(b"\0")
        heads = [f[5:] for f in first if f.startswith(b"HEAD ")]
        if len(heads) != 1 or not re.fullmatch(rb"[0-9a-f]{40}|[0-9a-f]{64}", heads[0]):
            return None
        return heads[0].decode("ascii")
    except GitStateSnapshotError:
        return None


def add_integration_worktree(repo_path: str, branch: str,
                             target_path: str) -> Optional[str]:
    """Create (or reuse) an integration worktree for a mission.

    The new branch starts at the MAIN worktree's HEAD — never at a worker
    worktree's HEAD. Branching from the first-finished worker used to bake
    that subtask's whole delivery into the mission "base", so the final
    mission diff showed only the LAST merged subtask (root cause of
    MISSION-QUICK-010's phantom 'square missing' verdict).
    """
    start = _main_head(repo_path)
    if not start:
        return None
    Path(target_path).mkdir(parents=True, exist_ok=True)
    args = ["worktree", "add", "--checkout", "-B", branch, target_path]
    if start:
        args.append(start)
    ok, out = _git_check(repo_path, *args)
    if ok:
        return target_path
    # "already exists" variants: try plain add (branch exists), then reuse
    ok, _ = _git_check(repo_path, "worktree", "add", target_path, branch)
    if ok:
        return target_path
    # already registered AND directory present -> reuse as-is
    if Path(target_path).exists() and (Path(target_path) / ".git").exists():
        return target_path
    return None


class MergeOutcome:
    """Result of merging one worker worktree into the integration worktree."""
    OK = "ok"
    CONFLICT = "conflict"
    ERROR = "error"

    def __init__(self, status: str, detail: str = ""):
        self.status = status
        self.detail = detail

    def __repr__(self):
        return "MergeOutcome(%s, %r)" % (self.status, self.detail[:120])


def merge_worktree(integration_wt: str, source_wt: str, *,
                   source_commit: Optional[str] = None) -> MergeOutcome:
    """Merge a materialized commit (or the caller's HEAD) into integration.

    Works for linked worktrees and independent clones alike: fetch from the
    source PATH (a local path is a valid git remote URL), then merge
    FETCH_HEAD. Conflicts are detected deterministically and reported — the
    controller routes them back to the Planner (bounded by mission budgets).
    """
    if source_commit is not None and not re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}", source_commit):
        return MergeOutcome(MergeOutcome.ERROR, "invalid materialized commit id")
    ok, out = _git_check(integration_wt, "fetch", "--quiet", source_wt,
                         source_commit if source_commit is not None else "HEAD")
    if not ok:
        return MergeOutcome(MergeOutcome.ERROR, "fetch: " + out[:400])
    ok, out = _git_check(integration_wt, "merge", "--no-edit", "--no-ff",
                         "FETCH_HEAD",
                         "-m", "merge: subtask from %s" %
                         Path(source_wt).name)
    if ok:
        return MergeOutcome(MergeOutcome.OK, out[:200])
    if "CONFLICT" in out or "conflict" in out.lower():
        # deterministically abort a conflicted merge state
        _git_check(integration_wt, "merge", "--abort")
        return MergeOutcome(MergeOutcome.CONFLICT, out[:400])
    return MergeOutcome(MergeOutcome.ERROR, out[:400])
