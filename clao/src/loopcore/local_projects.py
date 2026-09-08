"""Local project registration and explicit, filtered working-content snapshots.

Only CLAO's runtime holds Git metadata. Source directories are read, never
initialized, staged, committed or given remotes by this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
from pathlib import Path

from .worktree import _is_artifact as is_artifact, _read_env

BACKEND = "codex_app_server"
_LOCK = threading.RLock()
_SKIP_DIRS = {".git", ".ao", ".codex", ".ssh", ".aws", ".azure", ".venv", "venv",
              "node_modules", "vendor", "runtime", "dist", "build", ".idea", ".vscode"}
_SECRET_NAMES = {"credentials", "credentials.json", "auth.json", "id_rsa", "id_ed25519",
                 ".npmrc", ".pypirc", ".netrc"}
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_FILES = 10000


def local_path(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError("项目路径必须是明确的本地绝对路径")
    path = Path(value)
    if not path.is_absolute() or value.startswith(("\\\\", "//")):
        raise ValueError("请选择本机绝对路径；不支持网络或设备路径")
    return path.resolve()


def _registry(root):
    return Path(root) / "runtime" / "projects.json"


def projects(root):
    with _LOCK:
        path = _registry(root)
        data = json.loads(path.read_text("utf-8")) if path.exists() else []
        if not isinstance(data, list) or any(not isinstance(p, dict) for p in data):
            raise ValueError("本地项目登记不可读取")
        return data


def project(root, identity):
    found = [p for p in projects(root) if p.get("id") == identity]
    if len(found) != 1:
        raise ValueError("本地项目不存在；请先打开或创建项目")
    return found[0]


def register(root, value, *, create=False):
    path = local_path(value)
    managed = (Path(root) / "runtime").resolve()
    if path == Path(path.anchor) or path == Path.home().resolve() or path.is_relative_to(managed) or managed.is_relative_to(path):
        raise ValueError("请选择具体项目目录，不能选择磁盘根、用户主目录或 CLAO 运行目录")
    if create:
        # One explicitly named empty directory; never create a hidden Git repo.
        path.mkdir(exist_ok=False)
    if not path.is_dir():
        raise ValueError("项目目录不存在")
    row = {"id": "local-" + hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()[:24],
           "name": path.name, "path": str(path), "kind": "local", "backend": BACKEND}
    with _LOCK:
        rows = [p for p in projects(root) if p.get("id") != row["id"]] + [row]
        dest = _registry(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=dest.parent, delete=False) as f:
            temp = Path(f.name)
            json.dump(rows, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(temp, dest)
        finally:
            temp.unlink(missing_ok=True)
    return row


def excluded(relative, directory=False):
    p = Path(relative)
    names = [part.lower() for part in p.parts]
    if any(n in _SKIP_DIRS for n in names) or is_artifact(p.as_posix() + ("/entry" if directory else "")):
        return "缓存、依赖或运行工具目录"
    name = p.name.lower()
    if (name in _SECRET_NAMES or p.suffix.lower() in {".pem", ".key", ".pfx", ".p12"}
            or (name.startswith(".env") and name not in {".env.example", ".env.sample", ".env.template"})):
        return "凭据文件"
    return None


def _read_file(path, root):
    # Refuse links, junctions and nonregular entries, including ancestor links.
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("不支持链接或 junction 来源：" + path.relative_to(root).as_posix())
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError("来源文件不是普通文件或超过 10 MiB：" + path.relative_to(root).as_posix())
    with path.open("rb") as f:
        opened = os.fstat(f.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("读取时来源文件已替换")
        data = f.read(MAX_FILE_BYTES + 1)
        after = os.fstat(f.fileno())
    if len(data) > MAX_FILE_BYTES or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("读取时来源内容变化，请重新确认")
    return data, bool(before.st_mode & stat.S_IXUSR)


def inspect(row, *, include_content=False):
    root = local_path(row["path"])
    if os.path.normcase(str(root)) != os.path.normcase(row["path"]):
        raise ValueError("登记项目路径已被替换，请重新打开并确认")
    if not root.is_dir():
        raise ValueError("项目目录不可读取")
    if not shutil.which("git"):
        raise ValueError("未找到 Git；本地隔离快照需要已安装的 Git")
    # Git queries are optional and read-only; an ordinary folder is supported.
    if any(k in os.environ for k in ("GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS")):
        raise ValueError("当前进程含 Git 命令配置覆盖；请在普通终端启动 CLAO 后重试")
    git_env = _read_env()
    read_git = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull, "-C", str(root)]
    proc = subprocess.run([*read_git, "rev-parse", "--show-toplevel"],
                          env=git_env, capture_output=True, timeout=15)
    is_git = proc.returncode == 0
    eligible = None
    eligible_dirs = set()
    if is_git:
        if Path(os.fsdecode(proc.stdout.strip())).resolve() != root:
            raise ValueError("请选择 Git 仓库根目录，避免来源范围含糊")
        proc = subprocess.run([*read_git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                              env=git_env, capture_output=True, timeout=15)
        if proc.returncode:
            raise ValueError("Git 来源清单读取失败")
        eligible = set(os.fsdecode(p) for p in proc.stdout.split(b"\0") if p)
        eligible_dirs = {parent.as_posix() for name in eligible for parent in Path(name).parents}
    records, omitted, content = [], [], {}
    total = visited = 0
    def walk(folder):
        nonlocal total, visited
        info = folder.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("来源目录变为链接，请重新确认")
        for path in folder.iterdir():
            visited += 1
            if visited > MAX_FILES * 2:
                raise ValueError("来源目录项目过多；请选择更小项目范围")
            rel = path.relative_to(root).as_posix()
            info = path.lstat()
            reason = excluded(rel, stat.S_ISDIR(info.st_mode))
            if reason:
                omitted.append({"path": rel, "reason": reason})
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("来源含链接/junction，请移出选定项目范围：" + rel)
            if stat.S_ISDIR(info.st_mode):
                if eligible is not None and rel not in eligible_dirs:
                    omitted.append({"path": rel, "reason": "Git ignore（未跟踪目录）"})
                    continue
                walk(path)
                continue
            if eligible is not None and rel not in eligible:
                omitted.append({"path": rel, "reason": "Git ignore（未跟踪）"})
                continue
            data, executable = _read_file(path, root)
            total += len(data)
            if total > MAX_TOTAL_BYTES or len(records) >= MAX_FILES:
                raise ValueError("来源超过 100 MiB 或 10000 文件；请选择更小项目范围")
            records.append({"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "executable": executable})
            if include_content:
                content[rel] = data
    walk(root)
    records.sort(key=lambda entry: entry['path'])
    omitted.sort(key=lambda entry: entry['path'])
    revision = hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    summary = {"project_id": row["id"], "path": str(root), "kind": "git" if is_git else "folder",
               "policy": "filtered_current_working_content", "revision": revision, "files": records,
               "excluded": omitted, "file_count": len(records), "bytes": total}
    return (summary, content) if include_content else summary


def snapshot(row, runtime, expected_revision):
    summary, content = inspect(row, include_content=True)
    if not expected_revision or summary["revision"] != expected_revision:
        raise ValueError("项目内容变化或尚未确认来源；请刷新来源摘要后再启动")
    if inspect(row)["revision"] != summary["revision"]:
        raise ValueError("读取过程中项目内容变化，请重新确认")
    repo = Path(runtime) / "source"
    repo.mkdir(parents=True, exist_ok=False)
    for rel, data in content.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    env = _read_env()
    def git(*args):
        p = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
                            "-c", "user.name=CLAO", "-c", "user.email=clao@localhost",
                            "-c", "commit.gpgsign=false", "-C", str(repo), *args],
                           env=env, capture_output=True, timeout=30)
        if p.returncode:
            raise ValueError("CLAO 来源快照 Git 操作失败：" + args[0])
        return p.stdout.decode().strip()
    git("init", "--initial-branch=source", "--template=")
    for key, value in (("user.name", "CLAO"), ("user.email", "clao@localhost"),
                       ("core.hooksPath", os.devnull), ("commit.gpgsign", "false"),
                       ("core.autocrlf", "false"), ("core.fsmonitor", "false")):
        git("config", "--local", key, value)
    # A source .gitattributes must not execute inherited smudge/process drivers
    # during Worker/integration checkout. Override only the private repo config.
    filters = subprocess.run(["git", "-C", str(repo), "config", "--null", "--name-only",
                              "--get-regexp", r"^filter\..*\.(clean|smudge|process)$"],
                             env=env, capture_output=True, timeout=15)
    if filters.returncode not in (0, 1):
        raise ValueError("无法检查 Git 内容过滤器")
    for raw in filters.stdout.split(b"\0"):
        if not raw:
            continue
        key = raw.decode("utf-8")
        if not re.fullmatch(r"filter\.[^\r\n]+\.(clean|smudge|process)", key):
            raise ValueError("无法确认 Git 内容过滤器名称")
        git("config", "--local", key, "")
        git("config", "--local", key.rsplit(".", 1)[0] + ".required", "false")
    # Do not execute source .gitattributes filters; use explicit blob/index input.
    for entry in summary["files"]:
        p = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
                           input=content[entry["path"]], env=env, capture_output=True, check=True)
        mode = "100755" if entry["executable"] else "100644"
        git("update-index", "--add", "--cacheinfo", mode, p.stdout.decode().strip(), entry["path"])
    git("commit", "--allow-empty", "-m", "CLAO confirmed local source")
    return {"backend": BACKEND, "project_id": row["id"], "project_path": str(repo.resolve()),
            "original_path": row["path"], "policy": summary["policy"], "source_ref": "refs/heads/source",
            "source_commit": git("rev-parse", "HEAD"), "manifest": summary}
