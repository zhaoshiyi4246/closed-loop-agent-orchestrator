"""Native AO source/result bridge using retained CLAO material rules.

AO owns Mission persistence and execution. These operations read chosen source
content, write only the daemon's private material directory, and return facts.
They never attach a legacy runtime or open its database.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import zipfile

from . import local_projects as local
from . import results
from . import worktree as wt
from .state_store import now_iso

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,79}")


def _directory(value, *, create=False):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("材料目录必须是绝对路径")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("材料目录含链接或 junction")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path.resolve(strict=True)


def runtime(data_root, mission_id, *, create=False):
    if not isinstance(mission_id, str) or not _ID.fullmatch(mission_id):
        raise ValueError("任务标识无效")
    root = _directory(data_root, create=create)
    target = root / "clao" / "missions" / mission_id
    if create:
        return _directory(target, create=True)
    # Read-only queries do not create a runtime as a side effect.
    if target.exists():
        return _directory(target)
    return target


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".partial", delete=False) as f:
            temporary = Path(f.name)
            f.write(results._json(value)); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def source_preview(project_id, path):
    original = local.local_path(path)
    if original == Path(original.anchor) or original == Path.home().resolve():
        raise ValueError("请选择具体项目目录，不能选择磁盘根或用户主目录")
    value = local.inspect({"id": project_id, "path": str(original)})
    return {"projectId": project_id, "originalPath": value["path"], "kind": value["kind"],
            "revision": value["revision"], "policy": value["policy"],
            "fileCount": value["file_count"], "bytes": value["bytes"],
            "excluded": value["excluded"]}


def freeze_source(data_root, mission_id, project_id, path, revision):
    private = runtime(data_root, mission_id, create=True)
    original = local.local_path(path)
    managed = _directory(data_root)
    if managed == original or managed.is_relative_to(original) or original.is_relative_to(managed):
        raise ValueError("来源不能包含或位于 CLAO 运行数据目录")
    receipt = results._known(private, "source-receipt.json")
    if receipt.exists():
        value = json.loads(receipt.read_text("utf-8"))
        if (value.get("revision") != revision or value.get("projectId") != project_id
                or value.get("originalPath") != str(original)):
            raise ValueError("同一任务来源确认已固定，不能替换")
        source = results._known(private, "source")
        if str(source) != value.get("projectPath"):
            raise ValueError("来源目录记录不匹配")
        if (results._git(source, "rev-parse", "--verify", value["base"] + "^{commit}")
                .decode().strip() != value["base"]):
            raise ValueError("固定来源 Git 对象不可读取")
        return value
    if (private / "source").exists():
        raise ValueError("来源快照写入曾中断且回执不完整；保留现场，不能重新采用变化后的目录")
    # Legacy snapshot copies exact bytes and creates Git metadata only here.
    saved = local.snapshot({"id": project_id, "path": str(original)}, private, revision)
    manifest = saved["manifest"]
    value = {"projectId": project_id, "originalPath": str(original), "projectPath": saved["project_path"],
             "revision": revision, "base": saved["source_commit"], "policy": saved["policy"],
             "fileCount": manifest["file_count"], "bytes": manifest["bytes"], "excluded": manifest["excluded"]}
    _atomic_json(receipt, value)
    return value


def _write_git(repo, *args):
    p = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
                        "-c", "user.name=CLAO", "-c", "user.email=clao@localhost",
                        "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
                        "-C", str(repo), *args], env=wt._read_env(), capture_output=True, timeout=60)
    if p.returncode:
        # Do not expose remote/config contents or conflict file contents.
        raise ValueError("私有成果集成失败（" + args[0] + "）；原项目未改变，保留现场供检查")
    return p.stdout.decode("utf-8", errors="replace").strip()


def integrate(data_root, mission_id, source, base, children):
    if not 1 <= len(children) <= 2 or not results._OID.fullmatch(base or ""):
        raise ValueError("仅支持一至两个已固定的独立子任务成果")
    private = runtime(data_root, mission_id, create=True)
    source = _directory(source)
    # Source must be the private source of this parent, never the user's repo.
    if source != results._known(private, "source"):
        raise ValueError("集成来源不属于该任务的私有快照")
    signature = results._digest(results._json({"base": base, "children": children}))
    receipt = results._known(private, "integration-receipt.json")
    target = results._known(private, "integration")
    if receipt.exists():
        value = json.loads(receipt.read_text("utf-8"))
        if value.get("identity") != signature or value.get("workspace") != str(target):
            raise ValueError("已有集成回执不属于本次成果")
        results._git(target, "rev-parse", "--verify", value["resultHead"] + "^{commit}")
        return value
    if target.exists():
        raise ValueError("集成操作中断且未完成回执；不能再次执行")
    # Validate every exact delivery before creating a worktree or merging.
    paths = set()
    for child in children:
        workspace = _directory(child["workspace"])
        head = child["resultHead"]
        if not results._OID.fullmatch(head or ""):
            raise ValueError("子任务没有固定成果")
        results._git(workspace, "merge-base", "--is-ancestor", base, head)
        # Scope parsing includes rename/copy sources, not just destinations.
        changed = set(wt._layer_paths(str(workspace), (base, head), detect_copies=True))
        if paths & changed:
            raise ValueError("子任务实际修改范围重叠；不能当作独立成果自动集成")
        paths.update(changed)
        # Base artifacts must be preserved, new/changed artifacts must be absent.
        old, new = wt._tree_entries(str(workspace), base), wt._tree_entries(str(workspace), head)
        if {p: v for p, v in old.items() if wt._is_artifact(p)} != {p: v for p, v in new.items() if wt._is_artifact(p)}:
            raise ValueError("子任务固定成果仍含新增或修改的缓存；拒绝集成")
    _write_git(source, "worktree", "add", "--detach", str(target), base)
    for child in children:
        _write_git(target, "fetch", "--no-tags", "--", child["workspace"], child["resultHead"])
        if _write_git(target, "rev-parse", "FETCH_HEAD") != child["resultHead"]:
            raise ValueError("取得的子任务对象与记录不一致")
        _write_git(target, "merge", "--no-edit", "--no-ff", "-m", "CLAO integrate fixed subtask", "FETCH_HEAD")
    value = {"identity": signature, "workspace": str(target), "resultHead": _write_git(target, "rev-parse", "HEAD")}
    _atomic_json(receipt, value)
    return value


def _native_evidence(m):
    request = m["request"]
    verification = next((e["verification"] for e in reversed(m.get("evidence", [])) if e.get("verification")), None)
    if verification is not None and (not isinstance(verification, dict) or verification.get("task_id") != request["id"]):
        raise results.ResultError("Verifier 关联不可读取", "read_error")
    checks = (verification or {}).get("ac_checks") or []
    criteria = []
    for ac in request.get("criteria", []):
        found = [c for c in checks if c.get("ac_id") == ac["id"]]
        check = found[0] if len(found) == 1 else {}
        criteria.append({"id": ac["id"], "description": ac["description"], "verdict": check.get("verdict", "unknown"),
                         "note": check.get("note", "尚无对应的已保存验收字段")})
    gates = []
    for i, evidence in enumerate(m.get("evidence", [])):
        for j, record in enumerate(evidence.get("records") or []):
            assessment = record.get("assessment") or {}
            gates.append({"id": f"{i}:{j}", "task_id": record.get("task_id"),
                          "phase": assessment.get("phase", "unknown"), "command": record.get("command"),
                          "exit_code": record.get("exit_code"), "command_status": assessment.get("command_status", "unknown"),
                          "integrity": assessment.get("integrity", {"status": "unknown"}),
                          "scope": assessment.get("scope", {"status": "unknown"}),
                          "overall": assessment.get("overall", "unknown"), "started_at": record.get("started_at"),
                          "ended_at": record.get("ended_at"), "output": assessment.get("output", {}),
                          "historical_fields_missing": not bool(assessment)})
    return {"mission": {"id": request["id"], "project_id": request["projectId"], "objective": request["objective"],
                        "state": m["state"], "reason": m.get("reason", ""),
                        "acceptanceLevel": "subtask" if m.get("coordinatorId") else "mission",
                        "accepted": m["state"] == "DONE" and not m.get("coordinatorId")},
            "acceptance_criteria": criteria, "gates": {"status": "ok" if gates else "no_records", "records": gates},
            "verifier": {"status": "ok" if verification else "no_records", "record": verification}}


def _frozen(m, *, preview=False):
    if not m.get("resultHead"):
        raise results.ResultError("尚无已记录的固定成果；工作区存在不代表已验收", "not_produced")
    candidates = [m.get("workspace"), (m.get("source") or {}).get("projectPath")]
    failure = None
    for path in candidates:
        if not path or not Path(path).is_dir():
            continue
        try:
            return results.frozen_repository(_directory(path), m.get("base"), m["resultHead"], preview=preview)
        except results.ResultError as exc:
            if exc.status in ("restricted", "unsupported"):
                raise
            failure = exc
    raise failure or results.ResultError("固定 Git 对象当前不可读取；此前已保存结果包仍可下载", "missing")


def _package(data_root, m, record):
    private = runtime(data_root, m["request"]["id"])
    return results.package_bytes(private, record)


def _exports(m):
    value = m.get("exports")
    if value is None:
        return []  # AO omits an as-yet empty optional receipt slice.
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise results.ResultError("结果包回执字段不可读取", "read_error")
    return value


def _matching(m):
    return [r for r in _exports(m) if r.get("base_commit") == m.get("base")
            and r.get("result_commit") == m.get("resultHead")]


def result_view(data_root, m):
    location = m.get("workspace")
    view = {"missionId": m["request"]["id"], "status": "not_produced", "changes": [], "exports": [],
            "location": {"status": "available" if location and Path(location).is_dir() else "missing" if m.get("resultHead") else "not_produced",
                         "path": location or ""}, "evidence": _native_evidence(m)}
    for record in _exports(m):
        item = dict(record)
        try:
            _package(data_root, m, record)
            item["status"] = "ready"
        except (results.ResultError, OSError, ValueError):
            item.update(status="read_error", reason="已保存结果包缺失或校验失败")
        view["exports"].append(item)
    try:
        value = _frozen(m, preview=True)
        view.update(status=value.get("status", "ok"), baseCommit=value["base_commit"], resultCommit=value["result_commit"], changes=value["changes"])
        if value.get("restriction"):
            view["reason"] = value["restriction"]
            return view
        patch = value["patch"]
        # Native AO's file reviewer receives a real Git patch for this exact
        # path pair. Never infer filenames by parsing human diff headers.
        remaining = results.DISPLAY_LIMIT
        file_changes = []
        for change in value["changes"]:
            row = dict(change)
            if remaining:
                paths = list(dict.fromkeys(p for p in (row.get("old_path"), row.get("path")) if p))
                diff = results._git(value["repo"], "diff", *wt._DIFF_OPTIONS, "--find-renames", "--find-copies",
                                    "--find-copies-harder", "--full-index", "--src-prefix=a/", "--dst-prefix=b/",
                                    value["base_commit"], value["result_commit"], "--",
                                    *[":(top,literal)" + p for p in paths])
                row.update(diff=diff[:remaining].decode("utf-8", errors="replace"), diffTruncated=len(diff) > remaining)
                remaining = max(0, remaining - len(diff))
            else:
                row.update(diff="", diffTruncated=True)
            file_changes.append(row)
        view["changes"] = file_changes
    except (results.ResultError, wt.GitStateSnapshotError, OSError, ValueError) as exc:
        view.update(status=getattr(exc, "status", "read_error"), reason=str(exc))
        for record in _matching(m):
            try:
                with zipfile.ZipFile(io.BytesIO(_package(data_root, m, record))) as z:
                    manifest = json.loads(z.read("manifest.json")); patch = z.read("changes.patch")
                if (manifest["base_commit"] != m.get("base") or manifest["result_commit"] != m.get("resultHead")
                        or manifest["patch_sha256"] != results._digest(patch)):
                    continue
                view.update(status="saved", reason="原目录不可用；以下为已保存的固定成果", baseCommit=manifest["base_commit"],
                            resultCommit=manifest["result_commit"], changes=manifest["changes"])
                break
            except (results.ResultError, OSError, ValueError, KeyError, zipfile.BadZipFile):
                continue
        else:
            return view
    view.update(diff=patch[:results.DISPLAY_LIMIT].decode("utf-8", errors="replace"), diffTruncated=len(patch) > results.DISPLAY_LIMIT,
                diffBytes=len(patch), diffSHA256=results._digest(patch), noChanges=not view["changes"])
    return view


def export_result(data_root, m):
    if m.get("coordinatorId"):
        raise results.ResultError("子任务不代表 Mission 最终验收，请从原任务导出统一成果", "unsupported")
    private = runtime(data_root, m["request"]["id"], create=True)
    # A saved immutable package needs no working tree, source or engine.
    for record in _matching(m):
        if record.get("accepted") == (m["state"] == "DONE"):
            try:
                _package(data_root, m, record)
                return record
            except results.ResultError:
                pass
    result = _frozen(m)
    summary = results._summary(_native_evidence(m))
    manifest = {key: result[key] for key in ("base_commit", "result_commit", "changes", "baseline_files", "result_files")}
    manifest.update(format=results.FORMAT, no_changes=not result["changes"], patch_sha256=results._digest(result["patch"]),
                    source_policy=(m.get("source") or {}).get("policy", "historical Git source"), accepted=m["state"] == "DONE")
    results._sensitive(results._json(manifest).decode("utf-8"))
    identity = results._digest(results._json(manifest) + results._json(summary))
    dest = results._package_file(private, identity)
    dest.parent.mkdir(exist_ok=True)
    contents = {"changes.patch": result["patch"], "manifest.json": results._json(manifest), "evidence.json": results._json(summary),
                "README.md": results._INSTRUCTIONS.format(acceptance="已通过 Mission 最终验收" if manifest["accepted"] else "未通过最终验收").encode("utf-8")}
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=dest.parent, suffix=".partial", delete=False) as f:
            temp = Path(f.name)
            with zipfile.ZipFile(f, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in contents.items():
                    item = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)); item.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(item, data)
            f.flush(); os.fsync(f.fileno())
        data = temp.read_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if archive.testzip() is not None or set(archive.namelist()) != set(contents):
                raise results.ResultError("结果包完整性验证失败", "read_error")
        os.replace(temp, dest)
        return {"identity": identity, "sha256": results._digest(data), "bytes": len(data), "created_at": now_iso(),
                "base_commit": result["base_commit"], "result_commit": result["result_commit"], "accepted": manifest["accepted"]}
    finally:
        if temp:
            temp.unlink(missing_ok=True)


def evaluate(request):
    action = request["materials"]
    if action == "source_preview":
        return {"ok": True, "sourcePreview": source_preview(request["projectId"], request["path"])}
    if action == "source_freeze":
        return {"ok": True, "source": freeze_source(request["dataRoot"], request["missionId"], request["projectId"], request["path"], request["revision"])}
    if action == "integrate":
        return {"ok": True, "integration": integrate(request["dataRoot"], request["missionId"], request["source"], request["base"], request["children"])}
    if action == "results":
        return {"ok": True, "result": result_view(request["dataRoot"], request["mission"])}
    if action == "export":
        return {"ok": True, "package": export_result(request["dataRoot"], request["mission"])}
    raise ValueError("不支持的材料操作")
