"""F03: real, isolated Git repositories; no AO or model processes."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from loopcore import worktree as wt
from loopcore.mission_contracts import ProjectState, TaskSpec
from loopcore.mission_gate import IntegrationGate
from loopcore.state_store import StateStore
from tests.sidecar_port.test_contracts import _task_spec
from tests.sidecar_port.test_mission import _mc
from tests.test_cluster7_audit import _make_loop
from tests.test_final_gate_baseline import _seed_done_mission
from tests.test_f01_contract_boundary import ScriptedVerifier


def git(repo, *args, input=None):
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        input=input, capture_output=True, env=wt._read_env(), check=True)
    return result.stdout


def write(repo, name, content="value = 1\n"):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "中文 Git 工作树"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "F03 test")
    git(root, "config", "user.email", "f03@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    write(root, "source.py", "source = 7\n" * 20)
    write(root, "delete.py", "obsolete = True\n")
    git(root, "add", "--all")
    git(root, "commit", "-qm", "base")
    return root


def physical_state(repo):
    """Independent raw-index, stage, HEAD and user-file evidence."""
    index = Path(os.fsdecode(git(repo, "rev-parse", "--path-format=absolute",
                                 "--git-path", "index")[:-1]))
    files = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in repo.rglob("*") if p.is_file() and ".git" not in p.relative_to(repo).parts}
    return (git(repo, "rev-parse", "HEAD"), index.read_bytes(),
            git(repo, "ls-files", "--stage", "-z"), files)


@pytest.mark.parametrize("operation", ["rename", "copy", "delete"])
@pytest.mark.parametrize("layer", ["working", "staged", "committed"])
def test_endpoints_all_layers_and_readonly(repo, operation, layer):
    base = wt._current_head(repo)
    if operation == "rename":
        (repo / "source.py").rename(repo / "中文 renamed.py")
        expected = ["source.py", "中文 renamed.py"]
    elif operation == "copy":
        (repo / "中文 copied.py").write_bytes((repo / "source.py").read_bytes())
        expected = ["source.py", "中文 copied.py"]
    else:
        (repo / "delete.py").unlink()
        expected = ["delete.py"]
    if layer != "working":
        git(repo, "add", "-A")
    if layer == "committed":
        git(repo, "commit", "-qm", operation)
    before = physical_state(repo)
    assert wt.changed_paths(repo, base) == sorted(expected)
    diff = wt.git_diff_text(repo, base, limit=None)
    assert "unavailable" not in diff
    for path in expected:
        assert json.dumps(path) in diff
    assert wt.path_violations(repo, base, allowed_paths=["**"],
                              forbidden_paths=[expected[0]])[0] == [expected[0]]
    wt.git_state_snapshot(repo)
    assert physical_state(repo) == before


def test_staged_and_committed_changes_cannot_cancel_out(repo):
    base = wt._current_head(repo)
    original = (repo / "source.py").read_text(encoding="utf-8")
    write(repo, "source.py", "staged secret = 99\n")
    git(repo, "add", "source.py")
    write(repo, "source.py", original)
    assert wt.changed_paths(repo, base) == ["source.py"]
    assert "staged secret = 99" in wt.git_diff_text(repo, base, limit=None)
    git(repo, "commit", "-qm", "staged version")
    assert wt.changed_paths(repo, base) == ["source.py"]
    assert "staged secret = 99" in wt.git_diff_text(repo, base, limit=None)


@pytest.mark.parametrize("name", ["data.pyconfig", ".coverage_policy.py",
                                  "cache_manager.py", "x.pyc.txt", ".coverage.config",
                                  "not__pycache__/source.py", "x.pytest_cache/a.py"])
def test_source_lookalikes_are_never_artifacts(repo, name):
    base = wt._current_head(repo)
    write(repo, name, "real_source = 123\n")
    assert not wt._is_artifact(name)
    assert wt.changed_paths(repo, base) == [name]
    assert "real_source = 123" in wt.git_diff_text(repo, base)
    assert not wt.git_state_snapshot(repo).clean
    delivered = wt.commit_all(repo, "real source")
    assert name in wt._nul_paths(git(repo, "diff", "--name-only", "-z", base, delivered), "test")


@pytest.mark.parametrize("name", ["__pycache__/module.pyc", "nested/__pycache__/state",
                                  "nested/module.pyc", "module.pyo", ".pytest_cache/v/cache/nodeids",
                                  "nested/.mypy_cache/state", ".ruff_cache/state",
                                  ".hypothesis/state", ".tox/py/state", ".eggs/pkg/state",
                                  ".coverage", ".coverage.hostname.123.aBc123"])
def test_artifacts_consistent_across_reads_and_delivery(repo, name):
    base = wt._current_head(repo)
    original = wt.git_state_snapshot(repo)
    write(repo, name, "generated cache\n")
    before = physical_state(repo)
    assert wt._is_artifact(name)
    assert wt.changed_paths(repo, base) == []
    assert wt.git_diff_text(repo, base) == ""
    assert wt.git_state_snapshot(repo) == original
    assert wt.commit_all(repo, "artifact only") == base
    assert physical_state(repo) == before


def test_staged_artifacts_preserved_but_not_committed(repo):
    base = wt._current_head(repo)
    write(repo, "__pycache__/new.pyc", "cache")
    git(repo, "add", "__pycache__/new.pyc")
    cache_entry = git(repo, "ls-files", "--stage", "-z", "--", "__pycache__/new.pyc")
    write(repo, "real module.py", "delivery = True\n")
    head = wt.commit_all(repo, "source only")
    assert wt._nul_paths(git(repo, "diff", "--name-only", "-z", base, head), "test") == ["real module.py"]
    assert git(repo, "ls-files", "--stage", "-z", "--", "__pycache__/new.pyc") == cache_entry
    assert (repo / "__pycache__/new.pyc").read_text() == "cache"


def test_staged_delete_and_rename_materialize(repo):
    base = wt._current_head(repo)
    (repo / "source.py").rename(repo / "renamed source.py")
    (repo / "delete.py").unlink()
    git(repo, "add", "-A")
    head = wt.commit_all(repo, "rename and delete")
    assert head != base
    assert wt._nul_paths(git(repo, "ls-tree", "-r", "--name-only", "-z", head), "test") == ["renamed source.py"]
    assert not git(repo, "status", "--porcelain=v1", "-z")


@pytest.mark.parametrize("name", ["中文 空格.py", "tab\tname.py", "line\nname.py",
                                  "cr\rname.py", "escape\x1bname.py", 'quote"name.py'])
def test_git_object_paths_are_exact_even_when_windows_cannot_checkout(repo, name):
    # Windows disallows controls in filesystem names; real Git objects can
    # still carry them. Construct tree/commit objects without checking them out.
    base = wt._current_head(repo)
    blob = git(repo, "hash-object", "-w", "--stdin", input=b"control path source\n").strip()
    tree = git(repo, "mktree", "-z", input=b"100644 blob " + blob + b"\t" + name.encode() + b"\0").strip()
    commit = git(repo, "commit-tree", tree.decode(), "-p", base, "-m", "path object").strip()
    git(repo, "update-ref", "HEAD", commit.decode())
    before = physical_state(repo)
    paths = wt.changed_paths(repo, base)
    assert set(paths) == {"source.py", "delete.py", name}
    assert json.dumps(name) in wt.git_diff_text(repo, base, limit=None)
    assert wt.scope_violations(paths, allowed_paths=["source.py", "delete.py"],
                               forbidden_paths=[])[1] == [name]
    assert physical_state(repo) == before


@pytest.mark.parametrize("raw", [b"M\0no-terminator", b"R100\0only-one\0",
                                  b"C100\0old\0\0", b"Q\0file\0", b"U\0conflict\0",
                                  b"M\0../outside\0", b"R101\0old\0new\0"])
def test_malformed_or_unmerged_git_data_is_unknown(repo, monkeypatch, raw):
    base = wt._current_head(repo)
    original = wt._snapshot_git
    def fail(path, *args, **kwargs):
        return raw if "--name-status" in args else original(path, *args, **kwargs)
    monkeypatch.setattr(wt, "_snapshot_git", fail)
    before = physical_state(repo)
    assert wt.changed_paths(repo, base) is None
    assert "unavailable" in wt.git_diff_text(repo, base)
    assert wt.path_violations(repo, base, allowed_paths=["**"], forbidden_paths=[])[0]
    with pytest.raises(wt.GitStateSnapshotError):
        wt.git_state_snapshot(repo)
    assert physical_state(repo) == before


@pytest.mark.parametrize("failure", ["after_temp_add", "working_diff"])
def test_untracked_failure_never_touches_real_index_or_objects(repo, monkeypatch, failure):
    base = wt._current_head(repo)
    write(repo, "staged.py", "staged\n")
    git(repo, "add", "staged.py")
    write(repo, "untracked.py", "untracked\n")
    # Include Git split-index behavior; temporary writes must not create or
    # change shared index files in the real Git directory.
    git(repo, "update-index", "--split-index")
    before = physical_state(repo)
    git_files = {p.relative_to(repo / ".git").as_posix(): p.read_bytes()
                 for p in (repo / ".git").rglob("*") if p.is_file()}
    original = wt._snapshot_git
    def fail(path, *args, **kwargs):
        if failure == "after_temp_add" and "add" in args:
            original(path, *args, **kwargs)
            raise wt.GitStateSnapshotError("injected after temporary write")
        if failure == "working_diff" and kwargs.get("env") and "--binary" in args:
            raise wt.GitStateSnapshotError("injected patch read error")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(wt, "_snapshot_git", fail)
    failure_text = wt.git_diff_text(repo, base, limit=None)
    assert "unavailable" in failure_text and "injected" in failure_text
    assert physical_state(repo) == before
    assert {p.relative_to(repo / ".git").as_posix(): p.read_bytes()
            for p in (repo / ".git").rglob("*") if p.is_file()} == git_files


def test_missing_base_is_unknown(repo):
    assert wt.changed_paths(repo, "") is None
    assert "unavailable" in wt.git_diff_text(repo, "")


@pytest.mark.parametrize("kind", ["rename", "copy", "empty_allow", "lookalike"])
def test_closed_loop_real_gate_blocks_scope(repo, tmp_path, monkeypatch, kind):
    loop, store, worktree = _make_loop(tmp_path, monkeypatch)
    loop.task.gate_commands = ['python -c "pass"']
    loop._base_commit()
    loop.task.allowed_paths = ["**"]
    loop.task.forbidden_paths = ["app.py"]
    if kind == "rename":
        (worktree / "app.py").rename(worktree / "new.py")
    elif kind == "copy":
        (worktree / "new.py").write_bytes((worktree / "app.py").read_bytes())
    elif kind == "empty_allow":
        loop.task.allowed_paths = []
        loop.task.forbidden_paths = []
        write(worktree, "new.py")
    else:
        loop.task.allowed_paths = ["app.py"]
        write(worktree, "data.pyconfig")
    loop._run_gate()
    assert loop.state == ProjectState.HUMAN
    record = store._conn.execute("SELECT stderr FROM gate_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert "path violations" in record[0]


def test_final_scope_copy_source_blocks_passing_verifier(tmp_path):
    mc, store, _ = _seed_done_mission(tmp_path)
    integration = Path(store.path).parent / "integration"
    (integration / "allowed.py").write_bytes((integration / "app.py").read_bytes())
    git(integration, "add", "allowed.py")
    git(integration, "commit", "-qm", "copy forbidden source")
    mc.mission.gate_commands = ['python -c "pass"']
    mc.mission.allowed_paths = ["**"]
    mc.mission.forbidden_paths = ["app.py"]
    mc.verifier = ScriptedVerifier()
    mc._final_verify()
    assert mc.state == "HUMAN"
    assert mc.verifier.calls == 0
    assert "app.py" in mc._read_state()["reason"]


@pytest.mark.parametrize("mode", ["source_mutation", "index_mutation", "probe_error"])
def test_baseline_uses_gate_integrity_and_never_exempts_failed_evidence(repo, tmp_path, monkeypatch, mode):
    mc, store = _mc(tmp_path)
    if mode == "source_mutation":
        code = "from pathlib import Path; Path('data.pyconfig').write_text('changed')"
    else:
        code = "import subprocess; subprocess.run(['git','rm','--cached','source.py'],check=True)"
    mc.mission.gate_commands = ['"%s" -c "%s"' % (sys.executable, code)]
    if mode == "probe_error":
        monkeypatch.setattr(wt, "git_state_snapshot", MagicMock(
            side_effect=wt.GitStateSnapshotError("injected baseline probe failure")))
    mc._capture_baseline(str(repo))
    assert mc.state == "HUMAN"
    assert "baseline repository integrity failed" in mc._read_state()["reason"]
    assert mc._baseline_failures() == []
    assert json.loads(mc._baseline_sidecar().read_text())["integrity_ok"] is False


def test_legacy_baseline_without_integrity_cannot_exempt_red(tmp_path):
    mc, store, _ = _seed_done_mission(tmp_path)
    mc._baseline_sidecar().write_text(json.dumps({"failures": ["test_legacy"]}))
    assert mc._baseline_failures() == []


def test_gate_source_named_like_cache_is_a_mutation(repo, tmp_path):
    task = TaskSpec.from_dict(_task_spec())
    task.gate_commands = ['"%s" -c "from pathlib import Path; '
                          "Path('.coverage_policy.py').write_text('source')\"" % sys.executable]
    run = IntegrationGate(StateStore(tmp_path / "gate.db")).run(task, str(repo))
    assert run.command_ok is True
    assert run.integrity_ok is False


def test_evidence_does_not_execute_hooks_diff_or_content_filters(repo, tmp_path):
    base = wt._current_head(repo)
    # These commands would visibly mutate the temp repository if any evidence
    # command executed a user-configured program.
    program = tmp_path / "unsafe_filter.py"
    program.write_text("from pathlib import Path\nPath('probe-executed').write_text('bad')\n")
    executable = '"%s" "%s"' % (sys.executable, program)
    git(repo, "config", "filter.f03.clean", executable)
    git(repo, "config", "filter.f03.process", executable)
    git(repo, "config", "diff.f03.command", executable)
    git(repo, "config", "diff.f03.textconv", executable)
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir()
    hook = hook_dir / "post-index-change"
    hook.write_bytes(b"#!/bin/sh\nprintf bad > probe-executed\n")
    hook.chmod(0o755)
    git(repo, "config", "core.hooksPath", str(hook_dir))
    write(repo, ".gitattributes", "*.py filter=f03 diff=f03\n")
    write(repo, "source.py", "changed source\n")
    write(repo, "untracked.py", "new source\n")
    before = physical_state(repo)
    paths = wt.changed_paths(repo, base)
    assert paths == [".gitattributes", "source.py", "untracked.py"]
    diff = wt.git_diff_text(repo, base, limit=None)
    assert "changed source" in diff and "new source" in diff
    assert not (repo / "probe-executed").exists()
    assert physical_state(repo) == before


def test_unknown_main_head_never_falls_back_to_worker(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(wt, "_main_head", lambda _path: None)
    target = tmp_path / "must-not-create"
    assert wt.add_integration_worktree(str(repo), "integration", str(target)) is None
    assert not target.exists()


@pytest.mark.parametrize("operation", ["copy", "rename"])
def test_artifact_target_does_not_hide_source_deletion(repo, operation):
    base = wt._current_head(repo)
    (repo / "cache.pyc").write_bytes((repo / "source.py").read_bytes())
    if operation == "rename":
        (repo / "source.py").unlink()
    git(repo, "add", "-A")
    expected = ["source.py"] if operation == "rename" else []
    assert wt.changed_paths(repo, base) == expected
    snapshot = wt.git_state_snapshot(repo)
    assert snapshot.clean is (operation == "copy")
    if operation == "rename":
        assert "source.py" in wt.git_diff_text(repo, base)
    else:
        assert wt.git_diff_text(repo, base) == ""


def test_frozen_base_is_not_replaced_by_merge_base(repo):
    original = wt._current_head(repo)
    write(repo, "base-only.py", "baseline content\n")
    git(repo, "add", "base-only.py")
    git(repo, "commit", "-qm", "frozen base")
    frozen = wt._current_head(repo)
    # Separate branch of the isolated fixture, without a merge-base substitution.
    git(repo, "checkout", "-qb", "other", original)
    write(repo, "other.py", "other content\n")
    git(repo, "add", "other.py")
    git(repo, "commit", "-qm", "other branch")
    assert wt.changed_paths(repo, frozen) == ["base-only.py", "other.py"]
    diff = wt.git_diff_text(repo, frozen)
    assert "-baseline content" in diff and "+other content" in diff


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_hidden_index_changes_are_unknown_not_clean(repo, flag):
    base = wt._current_head(repo)
    git(repo, "update-index", flag, "source.py")
    write(repo, "source.py", "hidden user modification\n")
    before = physical_state(repo)
    assert wt.changed_paths(repo, base) is None
    assert "unavailable" in wt.git_diff_text(repo, base)
    with pytest.raises(wt.GitStateSnapshotError, match="index entry requires manual"):
        wt.git_state_snapshot(repo)
    assert physical_state(repo) == before


def test_git_environment_cannot_redirect_reads_or_materialization(repo, tmp_path, monkeypatch):
    base = wt._current_head(repo)
    foreign_index = tmp_path / "foreign-index"
    foreign_index.write_bytes(b"must remain unchanged")
    monkeypatch.setenv("GIT_INDEX_FILE", str(foreign_index))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "not-this-repo"))
    write(repo, "delivery.py", "delivery = 42\n")
    source_bytes = (repo / "delivery.py").read_bytes()
    assert wt._current_head(repo) == base
    assert wt.changed_paths(repo, base) == ["delivery.py"]
    head = wt.commit_all(repo, "actual Worker repository")
    assert head != base
    assert git(repo, "show", "HEAD:delivery.py") == source_bytes
    assert (repo / "delivery.py").read_bytes() == source_bytes
    assert foreign_index.read_bytes() == b"must remain unchanged"
