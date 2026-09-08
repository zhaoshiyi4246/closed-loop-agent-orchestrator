#!/usr/bin/env python
"""CLAO shared Mission runner: local Codex Worker or explicit legacy AO.

Usage (from the CLAO product directory):
    PYTHONPATH=src .venv/Scripts/python.exe run_mission.py tasks/mission-quick.json
    ... add --dry-run to preflight Planner decomposition without touching AO.

Wires: frozen config/source -> MissionController -> selected Worker backend.
Planner/Auditor/Verifier retain Codex CLI and the existing configured models.
Observer/Gate use no model) -> LoopBus projection -> memory.md / project.md
-> FINAL_REPORT.

The same wiring is importable (build_runtime / run_loop) so the web panel
drives the EXACT code path this CLI validates — no second implementation.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import copy

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from loopcore.effective_config import (resolve_config, load_config as read_config,
                                      restore_snapshot, ConfigError)
from loopcore.diagnostics import Diagnostics
from loopcore.action_executor import ActionExecutor          # noqa: E402
from loopcore.ao_adapter import AOAdapter                    # noqa: E402
from loopcore.auditor import CodexCliAuditorProvider         # noqa: E402
from loopcore.bus import BusConfig, LoopBus                  # noqa: E402
from loopcore.bus_projector import StoreBusProjector         # noqa: E402
from loopcore.memory import ProjectMemory                    # noqa: E402
from loopcore.mission import (MISSION_TERMINAL, MissionController,
                              deterministic_single_task_plan)  # noqa: E402
from loopcore.mission_contracts import (MissionSpec,
                                        new_mission_max_subtasks)  # noqa: E402
from loopcore.mission_gate import IntegrationGate            # noqa: E402
from loopcore.planner_adapter import CodexCliPlannerProvider       # noqa: E402
from loopcore.state_store import StateStore                  # noqa: E402
from loopcore.verifier import CodexCliVerifierProvider       # noqa: E402


SAMPLE_PROJECT_PLACEHOLDER = "REPLACE_WITH_AO_PROJECT_ID"


class PreflightError(RuntimeError):
    """A bounded, user-actionable Mission environment failure."""


def resolve_ao_bin(*, environ=None, which=None) -> str:
    """Resolve the external AO CLI without assuming a machine layout."""
    env = os.environ if environ is None else environ
    configured = str(env.get("CLAO_AO_BIN") or "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise RuntimeError(
                "CLAO_AO_BIN does not point to an AO executable file: %s"
                % configured)
        return str(path)

    finder = shutil.which if which is None else which
    discovered = finder("ao")
    if discovered:
        return str(discovered)
    raise RuntimeError(
        "AO executable not found; set CLAO_AO_BIN to the installed AO CLI "
        "or make 'ao' available on PATH")


def resolve_ao_run_file(*, environ=None, home=None) -> Path:
    """Resolve AO's daemon runfile from the portable public contract."""
    env = os.environ if environ is None else environ
    configured = str(env.get("CLAO_AO_RUN_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    home_dir = Path.home() if home is None else Path(home)
    return home_dir / ".ao" / "running.json"


def setup_environment(*, ao_run_file: Path | str | None = None) -> None:
    """Process-level env every entry point needs (CLI, panel, scripts).

    AO Desktop remains an external dependency and is never started here.  A
    resolved runfile may be published for compatibility with AO consumers;
    no developer-specific AO data directory is injected.  Codex role
    providers do not use llm_env.
    """
    if ao_run_file is not None:
        os.environ["AO_RUN_FILE"] = str(ao_run_file)
    # the mission gate runs `python -m pytest` argv-style: make sure the
    # venv python (with pytest) wins PATH resolution.
    venv_scripts = str(ROOT / ".venv" / "Scripts")
    if venv_scripts not in os.environ.get("PATH", ""):
        os.environ["PATH"] = venv_scripts + os.pathsep + \
            os.environ.get("PATH", "")


def load_config() -> dict:
    return read_config(ROOT / "config" / "default.yaml")


def _run_preflight_command(argv: list[str], *, cwd: Path | None = None):
    """Run one read-only capability probe without a shell."""
    try:
        return subprocess.run(
            argv, cwd=str(cwd) if cwd is not None else None,
            capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreflightError("command probe failed: %s" % argv[0]) from exc


_AO_ORIGIN_REQUIRED = (
    "AO Project has no origin remote required by the validated AO 0.12.9 "
    "workspace contract."
)


def _workspace_ref_error(ref: str) -> PreflightError:
    display_ref = ref if len(ref) <= 160 else ref[:157] + "..."
    return PreflightError(
        "AO Project is not workspace-ready for AO 0.12.9: remote-backed "
        "base %s is unavailable. Fetch/configure origin before running "
        "CLAO." % display_ref)


def _validate_project_default_branch(
        git_bin: str, project_path: Path, project_detail: dict) -> str:
    """Validate AO 0.12.9's observed remote-backed workspace contract."""
    configured = str(project_detail.get("defaultBranch") or "auto").strip()
    remote_result = _run_preflight_command(
        [git_bin, "remote"], cwd=project_path)
    if remote_result.returncode != 0:
        raise PreflightError(_AO_ORIGIN_REQUIRED)
    remotes = [line.strip() for line in remote_result.stdout.splitlines()
               if line.strip()]
    if "origin" not in remotes:
        raise PreflightError(_AO_ORIGIN_REQUIRED)

    if configured.lower() == "auto":
        origin_head = "refs/remotes/origin/HEAD"
        symbolic = _run_preflight_command(
            [git_bin, "symbolic-ref", "--quiet", origin_head],
            cwd=project_path)
        target_ref = symbolic.stdout.strip() if symbolic.returncode == 0 \
            else ""
        prefix = "refs/remotes/origin/"
        if not target_ref.startswith(prefix) or target_ref == origin_head:
            raise _workspace_ref_error(origin_head)
        branch = target_ref[len(prefix):]
    else:
        branch = configured
        target_ref = "refs/remotes/origin/" + branch

    exists = _run_preflight_command(
        [git_bin, "rev-parse", "--verify", "--quiet",
         target_ref + "^{commit}"], cwd=project_path)
    if exists.returncode != 0:
        raise _workspace_ref_error(target_ref)
    return branch


def mission_preflight(mission_dict: dict, cfg: dict, *, freeze_source=True) -> dict:
    """Validate shared CLI/Panel Mission prerequisites before runtime state.

    This is deliberately capability-based and read-only: it never installs
    tools, writes Git configuration, creates runtime state, or calls a model.
    """
    if platform.python_implementation() != "CPython" \
            or sys.version_info[:2] != (3, 12):
        raise PreflightError("CPython 3.12.x is required")

    git_bin = shutil.which("git")
    if not git_bin:
        raise PreflightError("Git executable not found on PATH")

    project_id = str(mission_dict.get("project_id") or "").strip()
    if project_id == SAMPLE_PROJECT_PLACEHOLDER:
        raise PreflightError(
            "replace sample project_id with a registered AO Project id")
    if not project_id:
        raise PreflightError("mission project_id is required")

    try:
        ao_bin = resolve_ao_bin()
    except RuntimeError as exc:
        raise PreflightError(str(exc)) from exc
    ao_run_file = resolve_ao_run_file()
    if not ao_run_file.is_file():
        raise PreflightError(
            "AO daemon runfile not found: set CLAO_AO_RUN_FILE or start AO")

    ao_cfg = cfg.get("ao") or {}
    adapter = AOAdapter(
        base_url=ao_cfg.get("base_url") or "http://127.0.0.1:3001",
        timeout=float(ao_cfg.get("request_timeout_seconds", 15)),
        run_file=ao_run_file)
    try:
        projects = adapter.get_projects()
    except Exception as exc:
        raise PreflightError("AO daemon/API unavailable") from exc
    project = next(
        (item for item in projects
         if isinstance(item, dict) and str(item.get("id")) == project_id),
        None)
    if project is None:
        raise PreflightError("AO Project is not registered: %s" % project_id)
    project_text = str(project.get("path") or "").strip()
    project_path = Path(project_text) if project_text else None
    if project_path is None or not project_path.is_dir():
        raise PreflightError("AO Project path is unavailable: %s" % project_id)
    try:
        project_detail = adapter.get_project(project_id)
    except Exception as exc:
        raise PreflightError("AO Project detail is unavailable: %s"
                             % project_id) from exc

    worktree = _run_preflight_command(
        [git_bin, "rev-parse", "--is-inside-work-tree"], cwd=project_path)
    if worktree.returncode != 0 or worktree.stdout.strip().lower() != "true":
        raise PreflightError("selected AO Project path is not a Git worktree")
    for key in ("user.name", "user.email"):
        identity = _run_preflight_command(
            [git_bin, "config", "--get", key], cwd=project_path)
        if identity.returncode != 0 or not identity.stdout.strip():
            raise PreflightError("Git identity is missing: %s" % key)
    _validate_project_default_branch(
        git_bin, project_path, project_detail)

    codex_bin = shutil.which("codex")
    if not codex_bin:
        raise PreflightError("Codex CLI executable not found on PATH")
    login = _run_preflight_command([codex_bin, "login", "status"])
    login_text = "%s\n%s" % (login.stdout or "", login.stderr or "")
    if login.returncode != 0 or "chatgpt" not in login_text.lower():
        raise PreflightError("Codex CLI is not logged in with ChatGPT")

    roles = cfg.get("roles") or {}
    required_models = {
        "roles.planner.model": ((roles.get("planner") or {}).get("model")),
        "roles.auditor.model": ((roles.get("auditor") or {}).get("model")),
        "roles.verifier.model": ((roles.get("verifier") or {}).get("model")),
        "worker.model": ((cfg.get("worker") or {}).get("model")),
    }
    missing = [name for name, value in required_models.items()
               if not str(value or "").strip()]
    if missing:
        raise PreflightError("model configuration is missing: %s" % missing[0])

    from loopcore.recovery import source_identity
    source = source_identity(project_id, project_path, project_detail) if freeze_source else None
    return {
        "source": source,
        "ao_bin": ao_bin,
        "ao_run_file": ao_run_file,
        "project_path": project_path,
    }


def build_planner(cfg: dict, *, timeout: float | None = None,
                  codex_bin: str = "codex",
                  cwd: Path | None = None) -> CodexCliPlannerProvider:
    """Build the one production Planner used by normal and dry-run paths."""
    cfg = resolve_config(cfg)
    planner_cfg = cfg["roles"]["planner"]
    model = planner_cfg["model"]
    return CodexCliPlannerProvider(
        model=model,
        timeout=timeout if timeout is not None else planner_cfg["timeout_seconds"],
        codex_bin=codex_bin,
        cwd=cwd or ROOT,
    )


class MissionRuntime:
    """Everything a running (or resumable) mission is made of."""

    def __init__(self, mission_dict: dict, cfg: dict, *, ao_bin: str = "",
                 ao_run_file: Path | None = None, dry_run: bool = False, local_engine=None):
        cfg = resolve_config(cfg)
        self.mission_dict = copy.deepcopy(mission_dict)
        self.cfg = cfg
        self.dry_run = dry_run
        self.ao_bin = ao_bin
        self.ao_run_file = str(ao_run_file)
        self.runtime = ROOT / "runtime" / mission_dict["mission_id"]
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.store = StateStore(str(self.runtime / "state.db"))
        self.diagnostics = Diagnostics(self.store, mission_dict["mission_id"])
        ao_cfg = cfg["ao"]
        if local_engine:
            from loopcore.codex_backend import CodexBackend
            source = self.store.mission_config(mission_dict["mission_id"])["source"]
            self.adapter = CodexBackend(self.store, mission_dict["mission_id"], local_engine["executable"],
                cfg["worker"]["model"], source, timeout=cfg["worker"]["spawn_timeout_seconds"])
            self.ao_base_url = None
        else:
            self.adapter = AOAdapter(base_url=ao_cfg["base_url"], timeout=ao_cfg["request_timeout_seconds"], run_file=ao_run_file)
            self.ao_base_url = self.adapter.base_url
        wcfg = cfg["worker"]
        self.executor = ActionExecutor(
            ao_bin=ao_bin, data_dir=None, run_file=str(ao_run_file),
            store=self.store,
            adapter=self.adapter,
            worker_model=wcfg["model"],
            max_spawn_attempts=wcfg["spawn_max_attempts"],
            spawn_backoff_seconds=wcfg["spawn_backoff_seconds"],
            spawn_timeout_seconds=wcfg["spawn_timeout_seconds"],
            send_timeout_seconds=wcfg["send_timeout_seconds"],
            kill_timeout_seconds=wcfg["kill_timeout_seconds"])
        if local_engine:
            self.adapter.send_timeout = wcfg["send_timeout_seconds"]
            self.adapter.kill_timeout = wcfg["kill_timeout_seconds"]
        self.gate = IntegrationGate(self.store, **cfg["gate"])
        planner = build_planner(cfg, cwd=ROOT)
        roles = cfg["roles"]
        auditor_cfg = roles["auditor"]
        verifier_cfg = roles["verifier"]
        auditor = CodexCliAuditorProvider(
            model=auditor_cfg["model"],
            timeout=auditor_cfg["timeout_seconds"], cwd=ROOT)
        verifier = CodexCliVerifierProvider(
            model=verifier_cfg["model"],
            timeout=verifier_cfg["timeout_seconds"], cwd=ROOT)
        for component in (self.executor, self.adapter, self.gate, planner, auditor, verifier):
            component.diagnostics = self.diagnostics
        # Keep references for lifecycle introspection and compatibility with
        # any provider that exposes optional cleanup.
        self._planner = planner
        self._auditor = auditor
        self._verifier = verifier
        self.mission = MissionSpec.from_dict(mission_dict)
        self.controller = MissionController(
            self.mission, cfg,
            planner=planner, auditor=auditor, verifier=verifier,
            executor=self.executor, adapter=self.adapter, gate=self.gate,
            store=self.store, dry_run=dry_run)
        self.controller.diagnostics = self.diagnostics
        bus_cfg = cfg["bus"]
        self.bus = LoopBus(BusConfig(
            max_hops_per_thread=bus_cfg["max_hops_per_thread"],
            max_audits_per_thread=bus_cfg["max_audits_per_thread"],
            overall_timeout_seconds=bus_cfg["overall_timeout_seconds"]))
        # run memory lands in runtime/, never pollutes the target repo
        self.memory = ProjectMemory(str(self.runtime))
        self.projector = StoreBusProjector(
            self.store, self.bus, self.memory,
            traffic_log=self.runtime / "bus_traffic.jsonl")

    def close(self) -> None:
        """Release optional provider resources and sqlite. Idempotent.
        The panel calls this when a mission is unloaded; the CLI path relies
        on process exit, but close() keeps long-running panel use leak-free."""
        for prov in (self._planner, self._auditor, self._verifier, self.adapter):
            fn = getattr(prov, "close", None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
        try:
            self.store.close()
        except Exception:
            pass


def inspect_runtime(mission_id):
    """History handle, with no runtime assembly, AO, Provider or writable DB."""
    from types import SimpleNamespace
    runtime = ROOT / 'runtime' / mission_id
    with_store = StateStore(runtime / 'state.db', readonly=True)
    try:
        row = with_store.mission_config(mission_id)
        if not row or row.get('mission', {}).get('mission_id') != mission_id:
            raise ValueError('historical Mission identity missing or mismatched')
        mission = row['mission']
    finally:
        with_store.close()
    return SimpleNamespace(runtime=runtime, mission_dict=mission,
                           mission=SimpleNamespace(mission_id=mission_id), controller=None)


def build_runtime(mission_dict: dict, cfg: dict, *, dry_run: bool = False,
                  require_ao: bool = True) -> MissionRuntime:
    from loopcore.recovery import validate_checkpoint, RecoveryError
    if not require_ao:
        if not dry_run:
            raise ValueError('require_ao=False is only valid for read-only inspection')
        return inspect_runtime(mission_dict['mission_id'])
    mission_dict = copy.deepcopy(mission_dict)
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', str(mission_dict.get('mission_id', ''))):
        raise ValueError('invalid Mission id')
    runtime = ROOT / 'runtime' / mission_dict['mission_id']
    db = runtime / 'state.db'
    # Stored backend is authoritative on resume. Never reinterpret AO history
    # or an old snapshot using the new local default.
    if db.exists():
        with_store = StateStore(db, readonly=True)
        try:
            existing = with_store.mission_config(mission_dict['mission_id']) or {}
            backend = existing.get('execution_backend', 'ao')
            requested = mission_dict.get('execution_backend')
            if requested is not None and requested != backend:
                raise RecoveryError('saved execution backend differs; history cannot switch backend')
        finally:
            with_store.close()
    else:
        backend = mission_dict.get('execution_backend', 'ao')
    if backend not in ('ao', 'codex_app_server'):
        raise ValueError('unsupported execution backend: ' + str(backend))
    if backend == 'codex_app_server':
        return build_local_runtime(mission_dict, cfg, dry_run=dry_run)
    if backend != 'ao':
        raise ValueError('unsupported execution backend')
    if db.exists():
        store = StateStore(db, readonly=True)
        try:
            row = store.mission_config(mission_dict['mission_id'])
            if not row or row.get('state') in MISSION_TERMINAL:
                raise RecoveryError('terminal or missing Mission; inspect or create a new attempt')
            if row.get('effective_config') is None:
                raise ConfigError('historical Mission has no effective config snapshot; inspect only')
            cfg = restore_snapshot(row['effective_config'])
            mission_dict = copy.deepcopy(row['mission'])
            checked = mission_preflight(mission_dict, cfg, freeze_source=False)
            adapter = AOAdapter(base_url=cfg['ao']['base_url'], timeout=cfg['ao']['request_timeout_seconds'],
                                run_file=checked['ao_run_file'])
            validate_checkpoint(store, mission_dict['mission_id'], adapter)
        finally:
            store.close()
    else:
        cfg = resolve_config(cfg, overrides={'budgets': mission_dict.get('budgets', {})})
        for key in cfg.sources:
            if cfg.sources[key] == 'invocation override' and key.startswith('budgets.'):
                cfg.sources[key] = 'mission input'
        mission_dict['budgets'] = copy.deepcopy(cfg['budgets'])
        store = StateStore(db)
        try:
            store.freeze_config(mission_dict['mission_id'], mission_dict, cfg.snapshot())
            if mission_dict.get('previous_attempt'):
                store.record_mission(mission_dict['mission_id'], {'previous_attempt': mission_dict['previous_attempt']})
            diag = Diagnostics(store, mission_dict['mission_id'])
            with diag.phase('preflight', reason='checking local tools, AO project and exact source'):
                checked = mission_preflight(mission_dict, cfg)
            if not checked.get('source'):
                raise RecoveryError('preflight did not confirm an exact source')
            store.record_mission(mission_dict['mission_id'], {'source': checked['source']})
        finally:
            store.close()
    setup_environment(ao_run_file=checked['ao_run_file'])
    rt = MissionRuntime(mission_dict, cfg, ao_bin=checked['ao_bin'], ao_run_file=checked['ao_run_file'], dry_run=dry_run)
    try:
        rt.store.interrupt_open_phases(mission_dict['mission_id'])
    except Exception as exc:
        rt.diagnostics.errors.append('diagnostic recovery unavailable: ' + type(exc).__name__)
    return rt


def build_local_runtime(mission_dict, cfg, *, dry_run=False):
    from loopcore import local_projects
    from loopcore.codex_backend import preflight, CodexBackend
    from loopcore.recovery import validate_checkpoint, RecoveryError
    runtime = ROOT / 'runtime' / mission_dict['mission_id']
    db = runtime / 'state.db'
    if db.exists():
        store = StateStore(db, readonly=True)
        try:
            row = store.mission_config(mission_dict['mission_id']) or {}
            if row.get('state') in MISSION_TERMINAL:
                raise RecoveryError('terminal Mission is read-only; create a new attempt')
            if row.get('execution_backend') != local_projects.BACKEND or not row.get('engine'):
                raise RecoveryError('local backend snapshot missing')
            cfg = restore_snapshot(row.get('effective_config'))
            mission_dict = copy.deepcopy(row['mission'])
            engine = preflight(runtime)
            if engine['version'] != row['engine']['version']:
                raise RecoveryError('Codex protocol version differs from frozen Mission')
            adapter = CodexBackend(store, mission_dict['mission_id'], engine['executable'], cfg['worker']['model'], row['source'])
            validate_checkpoint(store, mission_dict['mission_id'], adapter)
        finally:
            store.close()
    else:
        cfg = resolve_config(cfg, overrides={'budgets': mission_dict.get('budgets', {})})
        mission_dict['budgets'] = copy.deepcopy(cfg['budgets'])
        mission_dict['execution_backend'] = local_projects.BACKEND
        # Validate before creating a source or contacting any engine.
        mission = MissionSpec.from_dict(mission_dict)
        if not mission.objective or not mission.allowed_paths or not mission.acceptance_criteria:
            raise ValueError('objective, allowed_paths and acceptance criteria are required')
        if mission.worker_harness != 'codex':
            raise ValueError('local backend supports only the Codex Worker harness')
        project = local_projects.project(ROOT, mission.project_id)
        store = StateStore(db)
        try:
            store.freeze_config(mission.mission_id, mission_dict, cfg.snapshot())
            store.record_mission(mission.mission_id, {'execution_backend': local_projects.BACKEND})
            if mission_dict.get('previous_attempt'):
                store.record_mission(mission.mission_id, {'previous_attempt': mission_dict['previous_attempt']})
            with Diagnostics(store, mission.mission_id).phase('preflight', reason='确认本地来源与 Codex 登录/沙箱能力'):
                engine = preflight(runtime)
                source = local_projects.snapshot(project, runtime, mission_dict.get('source_revision'))
            store.record_mission(mission.mission_id, {'source': source, 'engine': engine})
        finally:
            store.close()
    setup_environment()
    rt = MissionRuntime(mission_dict, cfg, dry_run=dry_run, local_engine=engine)
    rt.store.interrupt_open_phases(mission_dict['mission_id'])
    return rt



def run_loop(rt: MissionRuntime, *, cap_seconds: float | None = None,
             poll_seconds: float | None = None, on_tick=None,
             should_stop=None) -> dict:
    """Drive the controller until terminal / cap / external stop.

    on_tick(result, projected_n, elapsed) fires every iteration (the panel
    uses it for heartbeats); should_stop() lets the panel abort without
    killing the thread (state stays resumable in the store).
    """
    cap_seconds = rt.cfg["runner"]["cap_seconds"] if cap_seconds is None else cap_seconds
    poll_seconds = rt.cfg["runner"]["poll_seconds"] if poll_seconds is None else poll_seconds
    if cap_seconds != rt.cfg["runner"]["cap_seconds"] or poll_seconds != rt.cfg["runner"]["poll_seconds"]:
        raise ConfigError("runner overrides must be resolved before the Mission configuration is frozen")
    started = time.monotonic()
    while True:
        result = rt.controller.step()
        with rt.diagnostics.phase("projection", reason="projecting StateStore facts to bus/Markdown"):
            n = rt.projector.project_once()
        state = result.get("state", "?")
        elapsed = time.monotonic() - started
        if on_tick:
            try:
                on_tick(result, n, elapsed)
            except Exception:
                pass
        if state in MISSION_TERMINAL:
            break
        if elapsed >= cap_seconds:
            break
        if should_stop and should_stop() and not rt.store.mission_stop_requested(rt.mission.mission_id):
            break
        wait_phase = "retry_wait" if result.get("error") else "observation_wait"
        blocked = False
        try:
            if rt.store.has_unstarted_operations():
                wait_phase = "retry_wait"
            blocked = any(getattr(loop, "_waiting_for_approval", False) for loop in rt.controller.loops.values())
        except Exception as exc:
            rt.diagnostics.errors.append("wait diagnosis unavailable: " + type(exc).__name__)
        if blocked:
            wait_phase = "approval_wait"
        with rt.diagnostics.phase(wait_phase, reason=("waiting for next poll; Worker may still be executing" if wait_phase == "observation_wait" else
                                                     "waiting for unresolved approval" if blocked else "bounded retry; no unknown effect is resent")):
            rt.controller._stop_event.wait(poll_seconds)
    rt.projector.project_once()
    return {
        "mission_id": rt.mission.mission_id,
        "final_state": rt.controller.state,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "bus_envelopes": len(rt.projector.projected),
        "bus_errors": rt.projector.errors,
        "runtime_dir": str(rt.runtime),
        "memory_md": str(rt.memory.memory_path),
        "project_md": str(rt.memory.project_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mission_json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--project-path", help="open a local project; use --confirm-source with its printed revision")
    ap.add_argument("--confirm-source", help="exact source revision accepted after reviewing --project-path summary")
    ap.add_argument("--poll-seconds", type=float, default=None)
    ap.add_argument("--cap-seconds", type=float, default=None,
                    help="override runner.cap_seconds for a new Mission")
    args = ap.parse_args()

    try:
        mission_dict = json.loads(Path(args.mission_json).read_text("utf-8"))
    except Exception as exc:
        if args.dry_run:
            print("planning dry-run error: invalid mission JSON: %s" % exc,
                  file=sys.stderr)
            return 2
        raise
    if args.project_path:
        from loopcore import local_projects
        project = local_projects.register(ROOT, args.project_path)
        source = local_projects.inspect(project)
        if not args.confirm_source:
            print(json.dumps({'project': project, 'source': source,
                              'next': 'review exclusions, then repeat with --confirm-source <revision>'}, ensure_ascii=False, indent=2))
            return 0
        if source['revision'] != args.confirm_source:
            print('source changed; review a fresh summary', file=sys.stderr)
            return 2
        mission_dict.update(project_id=project['id'], execution_backend=local_projects.BACKEND,
                            source_revision=args.confirm_source)
    try:
        overrides = {k: v for k, v in {"poll_seconds": args.poll_seconds, "cap_seconds": args.cap_seconds}.items() if v is not None}
        cfg = resolve_config(load_config(), overrides={"runner": overrides})
    except (ConfigError, OSError) as exc:
        print("configuration rejected: %s" % exc, file=sys.stderr)
        return 2

    if args.dry_run:
        try:
            if not isinstance(mission_dict, dict):
                raise ValueError("mission must be a JSON object")
            for field in ("allowed_paths", "forbidden_paths",
                          "acceptance_criteria", "gate_commands"):
                if not isinstance(mission_dict.get(field), list):
                    raise ValueError("%s must be a list" % field)
            if not isinstance(mission_dict.get("budgets", {}), dict):
                raise ValueError("budgets must be an object")
            if not all(isinstance(path, str)
                       for path in mission_dict["allowed_paths"]
                       + mission_dict["forbidden_paths"]):
                raise ValueError("mission paths must be strings")
            if not all(isinstance(command, str)
                       for command in mission_dict["gate_commands"]):
                raise ValueError("gate_commands entries must be strings")
            if not all(isinstance(item, dict) and item.get("id")
                       and item.get("description")
                       for item in mission_dict["acceptance_criteria"]):
                raise ValueError(
                    "acceptance criteria require id and description")
            cfg = resolve_config(cfg, overrides={"budgets": mission_dict.get("budgets", {})})
            mission_dict = dict(mission_dict, budgets=copy.deepcopy(cfg["budgets"]))
            mission = MissionSpec.from_dict(mission_dict)
            if not mission.mission_id or not mission.project_id \
                    or not mission.objective:
                raise ValueError(
                    "mission_id, project_id, and objective are required")
            if not mission.allowed_paths:
                raise ValueError("allowed_paths must be non-empty")
            if not mission.acceptance_criteria:
                raise ValueError("acceptance_criteria must be non-empty")
            max_subtasks = new_mission_max_subtasks(mission.budgets)
            if max_subtasks == 1:
                planner = None
                plan = deterministic_single_task_plan(mission)
            else:
                planner = build_planner(cfg, cwd=ROOT)
                plan = planner.plan_decompose(
                    mission.to_dict(), "DECOMP-%s" % mission.mission_id)
            summary = {
                "mission_id": mission.mission_id,
                "dry_run": True,
                "planner_provider": (type(planner).__name__
                                     if planner is not None else None),
                "model": planner.model if planner is not None else None,
                "subtask_count": len(plan.subtasks),
                "plan": plan.to_dict(),
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2),
                  flush=True)
            return 0
        except Exception as exc:
            detail = str(exc).replace("\r", " ").replace("\n", " ")[:400]
            print("planning dry-run error: %s" % detail, file=sys.stderr)
            return 2

    setup_environment()
    try:
        rt = build_runtime(mission_dict, cfg, dry_run=False)
    except (PreflightError, ValueError) as exc:
        detail = str(exc).replace("\r", " ").replace("\n", " ")[:400]
        print("preflight failed: %s" % detail, file=sys.stderr)
        return 2

    print(f"[runner] mission={rt.mission.mission_id} "
          f"project={rt.mission.project_id} dry_run={args.dry_run} "
          f"cap={rt.cfg['runner']['cap_seconds']:g}s", flush=True)

    def _tick(result, n, elapsed):
        print(f"[runner] {elapsed:6.1f}s state={result.get('state', '?')} "
              f"acted={result.get('acted')} bus+{n}", flush=True)

    try:
        summary = run_loop(rt, on_tick=_tick)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return 0 if summary["final_state"] == "MISSION_DONE" else 2
    finally:
        rt.close()  # closes stdio; never manufactures a Worker stop fact


if __name__ == "__main__":
    raise SystemExit(main())
