"""Native material bridge: actual Git snapshots, fixed exports and application."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from loopcore import ao_materials as materials, results, worktree as wt


def git(path, *args, input=None):
    return subprocess.check_output(["git", "-c", "core.hooksPath=" + os.devnull,
        "-c", "user.name=Test", "-c", "user.email=test@local", "-c", "commit.gpgsign=false",
        "-c", "core.autocrlf=false", "-C", str(path), *args], env=wt._read_env(), input=input)


def write(root, files):
    for name, content in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if content is None:
            p.unlink()
        else:
            p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def bridge(request):
    completed = subprocess.run([sys.executable, "-m", "loopcore.ao_acceptance"],
        input=json.dumps(request, ensure_ascii=False).encode(), capture_output=True, check=True)
    return json.loads(completed.stdout)


def setup(tmp_path, *, initial=None, git_source=False):
    original = tmp_path / "用户 项目"
    original.mkdir()
    write(original, initial if initial is not None else {"app.py": "x=0\n", "旧 名称.txt": "原内容\n", "delete.txt": "delete\n"})
    if git_source:
        git(original, "init", "-q", "--initial-branch=original", "--template=")
        git(original, "add", "."); git(original, "commit", "--allow-empty", "-qm", "original")
    data = tmp_path / "native-data"
    preview = materials.source_preview("project-a", str(original))
    source = materials.freeze_source(data, "mission-materials", "project-a", str(original), preview["revision"])
    repo = Path(source["projectPath"])
    worker = tmp_path / "worker"
    git(repo, "worktree", "add", "--detach", str(worker), source["base"])
    return original, data, source, repo, worker


def mission(source, worker, head, *, state="DONE"):
    mid = "mission-materials"
    return {"request": {"id": mid, "projectId": "project-a", "objective": "修改源码 <中文>",
                        "criteria": [{"id": "AC1", "description": "x equals 2"}]},
            "state": state, "reason": "final stored reason", "base": source["base"], "source": source,
            "workspace": str(worker), "resultHead": head, "exports": [],
            "evidence": [{"records": [{"task_id": mid, "command": "python -c \"assert 2 == 2\"",
                "stdout": "FULL PROMPT MUST NOT EXPORT", "exit_code": 0,
                "assessment": {"phase": "final", "command_status": "pass", "integrity": {"status": "pass"},
                               "scope": {"status": "pass"}, "overall": "pass"}}],
                "verification": {"task_id": mid, "verify_id": mid + ":verify", "verdict": "PASS",
                    "summary": "已验证", "ac_checks": [{"ac_id": "AC1", "verdict": "PASS", "note": "checked"}],
                    "anti_gaming": [], "raw_prompt": "FULL PROMPT MUST NOT EXPORT"}}]}


def commit(worker):
    git(worker, "add", "-A"); git(worker, "commit", "--allow-empty", "-qm", "result")
    return git(worker, "rev-parse", "HEAD").decode().strip()


def assert_manifest(root, rows):
    for row in rows:
        content = (root / row["path"]).read_bytes()
        assert len(content) == row["bytes"]
        assert hashlib.sha256(content).hexdigest() == row["sha256"]


@pytest.mark.parametrize("kind", ["folder", "empty", "dirty_git"])
def test_native_source_actual_bridge_freezes_current_bytes_without_writing_original(tmp_path, kind):
    original = tmp_path / "中文 source"; original.mkdir()
    if kind != "empty":
        write(original, {"app.py": "original\n", "data.pyconfig": "config\n", ".coverage_policy.py": "policy\n"})
    if kind == "dirty_git":
        git(original, "init", "-q", "--initial-branch=mine", "--template=")
        git(original, "add", "."); git(original, "commit", "-qm", "baseline")
        write(original, {"app.py": "staged\n"}); git(original, "add", "app.py")
        write(original, {"app.py": "current disk\n", "new.txt": "not committed\n"})
    write(original, {"__pycache__/module.pyc": b"cache", ".env": "DO NOT COPY", "node_modules/dependency.js": "skip"})
    if kind == "dirty_git":
        before = ((original / ".git" / "index").read_bytes(), git(original, "rev-parse", "HEAD"),
                  git(original, "status", "--porcelain=v1", "-z"))
    args = {"projectId": "project-a", "path": str(original), "dataRoot": str(tmp_path / "data")}
    preview = bridge({**args, "materials": "source_preview"})["sourcePreview"]
    frozen = bridge({**args, "materials": "source_freeze", "missionId": "mission-materials", "revision": preview["revision"]})
    assert frozen["ok"], frozen
    private = Path(frozen["source"]["projectPath"])
    assert not (private / ".env").exists() and not (private / "node_modules").exists()
    assert not (private / "__pycache__").exists()
    if kind == "dirty_git":
        assert (private / "app.py").read_text() == "current disk\n"
        assert (private / "new.txt").read_text() == "not committed\n"
        assert before == ((original / ".git" / "index").read_bytes(), git(original, "rev-parse", "HEAD"),
                          git(original, "status", "--porcelain=v1", "-z"))
    else:
        assert not (original / ".git").exists()
    if kind != "empty":
        assert (private / "data.pyconfig").exists() and (private / ".coverage_policy.py").exists()


def test_native_source_confirmation_and_receipt_idempotency(tmp_path):
    original, data, source, repo, worker = setup(tmp_path)
    (original / "app.py").write_text("changed later")
    # Same accepted source adopts the immutable receipt, not current disk.
    assert materials.freeze_source(data, "mission-materials", "project-a", str(original), source["revision"]) == source
    with pytest.raises(ValueError, match="已固定"):
        materials.freeze_source(data, "mission-materials", "project-a", str(original), "different")
    with pytest.raises(ValueError, match="内容变化"):
        materials.freeze_source(data, "another-mission", "project-a", str(original), source["revision"])
    partial = materials.runtime(data, "partial-mission", create=True) / "source"
    partial.mkdir()
    with pytest.raises(ValueError, match="中断"):
        materials.freeze_source(data, "partial-mission", "project-a", str(original), source["revision"])


def test_native_fixed_result_export_application_and_survival(tmp_path):
    original, data, source, repo, worker = setup(tmp_path, git_source=True)
    original_before = (git(original, "rev-parse", "HEAD"), (original / ".git" / "index").read_bytes())
    write(worker, {"app.py": "x=2\napi_key = os.getenv(\"API_KEY\")\n", "旧 名称.txt": None,
                   "新 名称.txt": "原内容\n", "delete.txt": None, "added.txt": "新增\n"})
    head = commit(worker)
    m = mission(source, worker, head)
    snapshot = (git(worker, "rev-parse", "HEAD"), (Path(git(worker, "rev-parse", "--git-path", "index").decode().strip())).read_bytes())
    result = bridge({"materials": "results", "dataRoot": str(data), "mission": m})["result"]
    assert result["status"] == "ok" and result["evidence"]["mission"]["accepted"]
    assert result["evidence"]["acceptance_criteria"][0]["verdict"] == "PASS"
    assert {c["kind"] for c in result["changes"]} >= {"A", "M", "D", "R"}
    assert all("diff" in c for c in result["changes"])
    package = bridge({"materials": "export", "dataRoot": str(data), "mission": m})["package"]
    m["exports"] = [package]
    assert materials.export_result(data, m) == package
    assert snapshot == (git(worker, "rev-parse", "HEAD"), (Path(git(worker, "rev-parse", "--git-path", "index").decode().strip())).read_bytes())
    raw = materials._package(data, m, package)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert set(z.namelist()) == {"changes.patch", "manifest.json", "evidence.json", "README.md"}
        manifest = json.loads(z.read("manifest.json")); patch = z.read("changes.patch")
        assert b"FULL PROMPT MUST NOT EXPORT" not in z.read("evidence.json")
        assert str(original).encode() not in z.read("evidence.json")
        assert b"api_key = os.getenv" in patch
    independent = tmp_path / "independent"; shutil.copytree(original, independent, ignore=shutil.ignore_patterns(".git"))
    assert_manifest(independent, manifest["baseline_files"])
    patchfile = tmp_path / "changes.patch"; patchfile.write_bytes(patch)
    git(independent, "apply", "--whitespace=nowarn", str(patchfile))
    assert_manifest(independent, manifest["result_files"])
    assert not (independent / "delete.txt").exists() and not (independent / "旧 名称.txt").exists()
    subprocess.run([sys.executable, "-c", "from pathlib import Path; assert Path('app.py').read_text().startswith('x=2')"], cwd=independent, check=True)
    assert original_before == (git(original, "rev-parse", "HEAD"), (original / ".git" / "index").read_bytes())
    write(worker, {"app.py": "unreviewed later content\n"})
    commit(worker)
    assert materials.result_view(data, m)["resultCommit"] == head
    assert "unreviewed later content" not in materials.result_view(data, m)["diff"]
    assert materials._package(data, m, package) == raw
    worker.rename(tmp_path / "worker-unavailable"); repo.rename(repo.with_name("source-unavailable"))
    assert materials._package(data, m, package) == raw
    saved = materials.result_view(data, m)
    assert saved["status"] == "saved" and saved["location"]["status"] == "missing"
    assert materials.export_result(data, m) == package


@pytest.mark.parametrize("content", [b"api_key = 'not-for-export'\n", b"-----BEGIN PRIVATE KEY-----\n", b"BEGIN FULL PROMPT\n", b"\x00binary"])
def test_native_export_rejects_complete_sensitive_or_unsupported_material_without_redaction(tmp_path, content):
    original, data, source, repo, worker = setup(tmp_path)
    write(worker, {"app.py": "x=2\n"}); good_head = commit(worker)
    m = mission(source, worker, good_head)
    package = materials.export_result(data, m); m["exports"] = [package]
    saved = materials._package(data, m, package)
    write(worker, {"unsafe.txt": content}); m["resultHead"] = commit(worker)
    with pytest.raises(results.ResultError):
        materials.export_result(data, m)
    assert materials._package(data, m, package) == saved
    assert materials.result_view(data, m)["status"] in ("restricted", "unsupported")


def test_native_export_display_truncation_failure_and_absent_facts(tmp_path):
    original, data, source, repo, worker = setup(tmp_path)
    write(worker, {"long.txt": "0123456789\n" * 4000}); head = commit(worker)
    m = mission(source, worker, head, state="FAILED")
    m["evidence"] = []
    m["exports"] = None  # Native nil optional slice is not a read failure.
    view = materials.result_view(data, m)
    assert view["diffTruncated"] and not view["evidence"]["mission"]["accepted"]
    assert view["evidence"]["acceptance_criteria"][0]["verdict"] == "unknown"
    package = materials.export_result(data, m)
    with zipfile.ZipFile(io.BytesIO(materials._package(data, m, package))) as z:
        assert len(z.read("changes.patch")) > results.DISPLAY_LIMIT
        assert not json.loads(z.read("manifest.json"))["accepted"]
    m["resultHead"] = ""
    assert materials.result_view(data, m)["status"] == "not_produced"
    with pytest.raises(results.ResultError, match="固定成果"):
        materials.export_result(data, m)
    m["exports"] = {"invalid": "shape"}
    with pytest.raises(results.ResultError, match="回执字段"):
        materials.result_view(data, m)


def test_native_integration_uses_fixed_two_deliveries_and_excludes_committed_cache(tmp_path):
    original, data, source, repo, first = setup(tmp_path)
    second = tmp_path / "second"; git(repo, "worktree", "add", "--detach", str(second), source["base"])
    write(first, {"app.py": "x=2\n", "__pycache__/unsafe.pyc": b"cache"})
    worker_head = commit(first)
    delivery = wt.commit_all(str(first), "fixed delivery", base_commit=source["base"])
    assert delivery != worker_head
    write(second, {"independent.txt": "second task\n"}); second_head = commit(second)
    parts = [{"workspace": str(first), "resultHead": delivery}, {"workspace": str(second), "resultHead": second_head}]
    result = materials.integrate(data, "mission-materials", str(repo), source["base"], parts)
    destination = Path(result["workspace"])
    assert (destination / "app.py").read_text() == "x=2\n"
    assert (destination / "independent.txt").read_text() == "second task\n"
    assert not (destination / "__pycache__").exists()
    assert git(first, "rev-parse", "HEAD").decode().strip() == worker_head
    assert materials.integrate(data, "mission-materials", str(repo), source["base"], parts) == result
    assert (original / "app.py").read_text() == "x=0\n"


def test_native_integration_refuses_overlap_and_unfixed_artifacts(tmp_path):
    original, data, source, repo, first = setup(tmp_path)
    second = tmp_path / "second"; git(repo, "worktree", "add", "--detach", str(second), source["base"])
    write(first, {"app.py": "x=1\n"}); one = commit(first)
    write(second, {"app.py": "x=2\n"}); two = commit(second)
    with pytest.raises(ValueError, match="重叠"):
        materials.integrate(data, "mission-materials", str(repo), source["base"], [{"workspace": str(first), "resultHead": one}, {"workspace": str(second), "resultHead": two}])
    write(first, {"__pycache__/one.pyc": b"cache"}); unsafe = commit(first)
    with pytest.raises(ValueError, match="缓存"):
        materials.integrate(data, "mission-materials", str(repo), source["base"], [{"workspace": str(first), "resultHead": unsafe}])
    assert not (materials.runtime(data, "mission-materials") / "integration").exists()


def test_native_export_write_failure_does_not_publish_partial_or_damage_saved_package(tmp_path, monkeypatch):
    original, data, source, repo, worker = setup(tmp_path)
    write(worker, {"app.py": "x=2\n"}); m = mission(source, worker, commit(worker))
    good = materials.export_result(data, m); m["exports"] = [good]
    prior = materials._package(data, m, good)
    write(worker, {"new.txt": "another result\n"}); m["resultHead"] = commit(worker)
    def failed_replace(*args):
        raise OSError("injected final file publication failure")
    monkeypatch.setattr(materials.os, "replace", failed_replace)
    with pytest.raises(OSError, match="publication"):
        materials.export_result(data, m)
    directory = materials.runtime(data, m["request"]["id"]) / "exports"
    assert [p.name for p in directory.iterdir()] == [good["identity"] + ".zip"]
    assert materials._package(data, m, good) == prior
