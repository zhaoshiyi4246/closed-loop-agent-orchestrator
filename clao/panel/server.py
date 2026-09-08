#!/usr/bin/env python
"""CLAO web panel — zero-dependency UI for Closed-Loop Agent Orchestrator.

Double-click 启动CLAO.bat (or run this file with the venv python) and the
browser opens on the panel. The panel drives the EXACT runner code path the
CLI uses (run_mission.build_runtime); all state is read from the mission's
SQLite store, so the panel never modifies kernel behavior.

Bind: 127.0.0.1 only. Port: 7100 (override with PANEL_PORT).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

PANEL_DIR = Path(__file__).resolve().parent
# Exact public assets only. Never turn a request path into a filesystem path.
PANEL_ASSETS = {
    "/" + name: (PANEL_DIR / name, mime)
    for name, mime in (
        ("app.css", "text/css"), ("app.js", "text/javascript"),
        ("icons.svg", "image/svg+xml"),
        ("icons-LICENSE.txt", "text/plain"),
    )
}
ROOT = PANEL_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import run_mission  # noqa: E402
from loopcore.ao_adapter import AOAdapter  # noqa: E402
from loopcore.envelope import MessageKind  # noqa: E402
from loopcore.mission import MISSION_TERMINAL  # noqa: E402
from loopcore.event_normalizer import now_iso  # noqa: E402
from loopcore.effective_config import (load_config as read_config, resolve_config,
                                       save_defaults, restore_snapshot, FIELDS)
from loopcore.state_store import StateStore  # noqa: E402

PORT = int(os.environ.get("PANEL_PORT", "7100"))


class ClientError(ValueError):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def _mission_id(value):
    if (not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value)
            or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", value, re.I)):
        raise ClientError("invalid mission_id: use 1–128 ASCII letters, digits, '-' or '_'")
    return value


def _contained(root: Path, path: Path) -> Path:
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise ClientError("file path escapes its allowed directory or cannot be resolved") from exc
    return resolved


def _runtime_dir(mid):
    base = _contained(ROOT, ROOT / "runtime")
    return _contained(base, base / _mission_id(mid))


def _runtime_file(rt, name):
    root = _runtime_dir(rt.mission.mission_id)
    if Path(rt.runtime).resolve() != root:
        raise ClientError("mission runtime does not match mission_id")
    return _contained(root, root / name)


def _saved_mission(mid):
    root = _runtime_dir(mid)
    db = _contained(root, root / "state.db")
    if not db.is_file():
        raise ClientError("找不到该任务的运行存档: " + mid)
    conn = _ro_conn(db)
    try:
        rows = _rows(conn, "SELECT payload_json FROM missions WHERE mission_id=?", (mid,))
        mission = json.loads(rows[0][0]).get("mission") if rows else None
    finally:
        conn.close()
    if not isinstance(mission, dict) or _mission_id(mission.get("mission_id")) != mid:
        raise ClientError("存档 mission 定义或 mission_id 不匹配")
    return mission


# ------------------------------------------------------------------ state
class PanelState:
    """Owns the active mission runtime (if any) and the runner thread."""

    def __init__(self, config_path=None):
        self.config_path = config_path
        self.snapshot_lock = threading.RLock()
        self.stream_epoch = secrets.token_hex(12)
        self.sequence = 0
        self.loading = None
        self.lock = threading.RLock()
        self.rt = None                 # run_mission.MissionRuntime | None
        self.thread = None
        self.stop_flag = threading.Event()
        self.started_mono = None
        self.last_summary = None
        self.errors = []

    # ---- mission lifecycle
    def defaults(self):
        return read_config(self.config_path) if self.config_path is not None else resolve_config(run_mission.load_config())

    @property
    def live(self):
        # Legacy API projection; these are persisted NEW-MISSION defaults.
        cfg = self.defaults()
        return {"poll_seconds": cfg["runner"]["poll_seconds"], **{k: cfg["observer"][k] for k in
                ("idle_audit_cooldown_seconds", "blocked_escalation_seconds", "l0_nudge_grace_seconds")}}

    def start_mission(self, mission_dict: dict) -> str:
        runtime = _runtime_dir(mission_dict.get("mission_id"))
        with self.lock:
            if self.loading or (self.thread and self.thread.is_alive()):
                raise RuntimeError("已有任务在运行，先停止或等待完成")
            cfg = self.defaults()
            self.loading = SimpleNamespace(runtime=runtime, mission_dict=mission_dict,
                mission=SimpleNamespace(mission_id=mission_dict["mission_id"]), controller=None)
            self.rt = None
        # Do not hold the Panel lock over preflight: GET/SSE must see progress
        # before these potentially slow requests return.
        try:
            run_mission.setup_environment()
            rt = run_mission.build_runtime(mission_dict, cfg)
            with self.lock:
                self.rt = rt
                self.stop_flag.clear()
                self.started_mono = time.monotonic()
                self.last_summary = None
                self.thread = threading.Thread(target=self._run, daemon=True, name="mission-runner")
                self.thread.start()
            return mission_dict["mission_id"]
        except Exception as exc:
            with self.lock:
                self.rt = self.loading  # Preserve failed-preflight diagnostics.
                self.errors.append("preflight: " + str(exc))
            raise
        finally:
            with self.lock:
                self.loading = None

    def _run(self):
        rt = self.rt
        try:
            self.last_summary = run_mission.run_loop(rt, should_stop=self.stop_flag.is_set)
            self.last_summary["stopped_by_user"] = self.stop_flag.is_set()
        except Exception as e:
            self.errors.append("%s: runner: %s" % (now_iso(), e))

    def stop(self):
        # The Controller persists receipt before latching/cleanup. A failed
        # receipt must not become an in-memory-only successful Stop request.
        rt = self.rt
        if rt is None or rt.controller is None:
            raise ClientError("没有可停止的已加载任务", 409)
        try:
            rt.controller.request_stop()
        except Exception as e:
            self.errors.append("%s: stop: %s" % (now_iso(), e))
            # Cleanup can fail AFTER receipt committed. Only the existing
            # durable fact may turn that exception into an accepted request.
            try:
                received = rt.controller.store.mission_stop_requested(
                    rt.controller.mission.mission_id)
            except Exception:
                received = False
            if not received:
                raise ClientError("无法确认停止请求已持久接收: %s" % e, 503) from e
        rt.controller._stop_event.set()
        self.stop_flag.set()
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True, name='mission-cancel')
                self.thread.start()
        return {"ok": True, "stop_requested": True, "cancellation_status": "requested"}

    def running(self) -> bool:
        # A receipt is not termination: keep the runner visible while cancelling.
        return bool(self.thread and self.thread.is_alive())

    # ---- directive channel
    def post_directive(self, target, text, command_id=None) -> dict:
        from dataclasses import asdict
        with self.lock:
            if not self.rt or self.rt.controller is None:
                raise ClientError('历史查看没有指令消费者；请先恢复或创建新 attempt', 409)
            directive = self.rt.controller.directives.post(target, text, command_id)
        if directive.status == 'rejected':
            raise ClientError(directive.reason + ' (command_id=' + directive.command_id + ')', 422)
        return dict(asdict(directive), mirrored_to_planner=target != 'planner')

    def approval(self, body):
        with self.lock:
            rt = self.rt
            if not rt or not rt.controller or getattr(rt.adapter, 'backend', None) != 'codex_app_server':
                raise ClientError('当前任务没有本地审批消费者', 409)
            if rt.store.mission_stop_requested(rt.mission.mission_id) or rt.controller.state in MISSION_TERMINAL:
                raise ClientError('任务已结束或正在取消', 409)
            worker = body.get('worker_id')
            request_id = body.get('request_id')
            if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
                raise ClientError('无效审批请求标识', 400)
            if not isinstance(worker, str) or worker not in {t.worker_session_id for t in rt.controller.tasks.values()}:
                raise ClientError('审批不属于当前任务', 400)
        return rt.adapter.resolve_approval(worker, body.get('request_id'), body.get('decision'), body.get('answers'))

    # ---- persisted defaults (never mutate active runtime)
    def set_config(self, updates: dict) -> dict:
        if "auto_ff_master" in updates:
            raise RuntimeError("auto_ff_master is disabled in the competition runtime; remove deprecated option")
        with self.lock:
            path = self.config_path or run_mission.ROOT / "config" / "default.yaml"
            saved = save_defaults(path, updates)
            return saved.snapshot()


PANEL = PanelState()


# -------------------------------------------------------- AO projects
def _load_ao_projects() -> list[dict]:
    """Read the current AO Project registry through the public REST adapter."""
    cfg = run_mission.load_config() or {}
    ao_cfg = cfg.get("ao") or {}
    adapter = AOAdapter(
        base_url=ao_cfg.get("base_url") or "http://127.0.0.1:3001",
        timeout=float(ao_cfg.get("request_timeout_seconds", 15)),
        run_file=run_mission.resolve_ao_run_file(),
    )
    return [
        {key: project.get(key) for key in ("id", "name", "path", "kind")}
        for project in adapter.get_projects()
        if isinstance(project, dict)
    ]


# --------------------------------------------------------------- snapshot
def _ro_conn(db_path: Path) -> sqlite3.Connection:
    return StateStore.read_connection(db_path, timeout=3)


def _rows(conn, sql, args=(), retries=3):
    for i in range(retries):
        try:
            return conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError as exc:
            if i == retries - 1 or not any(word in str(exc).lower() for word in ("locked", "busy")):
                raise
            time.sleep(0.15)


def list_missions() -> list:
    out = []
    base = _contained(ROOT, ROOT / "runtime")
    if not base.exists():
        return out
    for d in sorted(base.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        try:
            root = _runtime_dir(d.name)
            db = _contained(root, root / "state.db")
            if not db.exists():
                continue
            conn = _ro_conn(db)
            try:
                r = _rows(conn, "SELECT payload_json FROM missions WHERE mission_id=?", (d.name,))
                state, objective = "?", ""
                if r:
                    payload = json.loads(r[0][0])
                    state = payload.get("state", "?")
                    objective = (payload.get("mission") or {}
                                 ).get("objective", "")
                out.append({"mission_id": d.name, "state": state,
                            "objective": objective})
            finally:
                conn.close()
        except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError) as exc:
            out.append({"mission_id": d.name, "state": "unknown", "objective": "",
                        "status": "read_error", "error": str(exc)})
    return out


def snapshot() -> dict:
    # Serialize full snapshots, not controller execution. Reconnect gets a full
    # replacement with a session epoch + monotonic sequence; no event replay.
    with PANEL.snapshot_lock:
        started = time.perf_counter()
        snap = _snapshot()
        PANEL.sequence += 1
        snap["stream"] = {"epoch": PANEL.stream_epoch, "sequence": PANEL.sequence,
                          "mission_id": (snap.get("mission") or {}).get("id"),
                          "generated_at": time.time(), "snapshot_seconds": time.perf_counter() - started}
        records = (snap.get("phases") or {}).get("records") or []
        latest = max((r.get("recorded_epoch") or 0 for r in records), default=0)
        snap["stream"]["phase_record_to_snapshot_seconds"] = max(0, time.time() - latest) if latest else None
        return snap


def _snapshot() -> dict:
    with PANEL.lock:
        rt = PANEL.loading or PANEL.rt
        active = bool(PANEL.loading or (PANEL.thread and PANEL.thread.is_alive()))
        running = PANEL.running()
        live = {}
        errs = PANEL.errors[-10:]
        summary = PANEL.last_summary
    snap = {"ok": True, "running": running, "config": live,
            "panel_errors": errs, "last_summary": summary,
            "missions": [], "elapsed": None, "read_errors": [],
            "gate_query": {"status": "not_run", "records": [],
                           "error": None, "reason": "没有已加载的任务"}}

    def read(source, action, default):
        try:
            return action()
        except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError) as exc:
            snap["ok"] = False
            snap["read_errors"].append({"source": source, "error": str(exc)})
            return default

    defaults = read("default configuration", lambda: PANEL.defaults().snapshot(), None)
    snap["default_config"] = defaults
    if defaults:
        values = defaults["values"]
        snap["config"] = {"poll_seconds": values["runner"]["poll_seconds"], **{k: values["observer"][k] for k in
                          ("idle_audit_cooldown_seconds", "blocked_escalation_seconds", "l0_nudge_grace_seconds")}}
    snap["config_fields"] = {k: {"kind": v[1], "minimum": v[2], "maximum": 604800 if v[1] == "seconds" else 2 if v[1] == "subtasks" else 1000000 if v[1] == "count" else None, "consumer": v[3]} for k, v in FIELDS.items()}
    snap["mission_config"] = {"status": "not_loaded", "snapshot": None}
    snap["phases"] = {"status": "not_called", "records": [], "sequence": None}
    snap["missions"] = read("missions", list_missions, [])
    if not rt:
        snap["mission"] = None
        return snap
    if PANEL.started_mono and running:
        snap["elapsed"] = round(time.monotonic() - PANEL.started_mono, 1)
    try:
        conn = _ro_conn(_runtime_file(rt, "state.db"))
    except Exception as e:
        snap["ok"] = False
        snap["read_errors"].append({"source": "state.db", "error": str(e)})
        snap["gate_query"] = {"status": "read_error", "records": [], "error": str(e)}
        snap["mission_config"] = {"status": "read_error", "snapshot": None}
        snap["phases"] = {"status": "read_error", "records": [], "sequence": None, "error": str(e)}
        snap["mission"] = {"id": rt.mission.mission_id, "state": "?",
                           "error": str(e)}
        return snap

    try:
        def _payloads(table, limit=50):
            # rowid works on every table (several store tables have no `id`
            # column — ORDER BY id silently returned nothing via the retry
            # swallow, e.g. verifications showed 0 rows).
            rows = _rows(conn, "SELECT payload_json FROM %s ORDER BY rowid DESC "
                               "LIMIT ?" % table, (limit,))
            out = [json.loads(p) for (p,) in rows]
            if any(not isinstance(p, dict) for p in out):
                raise ValueError("invalid " + table + " payload")
            return out

        mission_rows = read("mission", lambda: _payloads("missions", 1), [])
        mission_payload = mission_rows[0] if mission_rows else {}
        saved = mission_payload.get("effective_config")
        snap["mission_config"] = {"status": "historical_missing" if saved is None else "ok",
                                  "snapshot": read("Mission configuration", lambda: restore_snapshot(saved).snapshot(), None) if saved is not None else None}
        if (saved is not None and snap["mission_config"]["snapshot"] is None) or any(e["source"] == "mission" for e in snap["read_errors"]):
            snap["mission_config"]["status"] = "read_error"
        snap['directive_receipts'] = read('directive receipts', lambda: StateStore.query_directives(conn, rt.mission.mission_id), {'status': 'read_error', 'records': []})
        snap["phases"] = StateStore.query_phases(conn, rt.mission.mission_id, active=active)
        if snap["phases"]["status"] == "read_error":
            snap["read_errors"].append({"source": "phases", "error": snap["phases"]["error"]})
            snap["ok"] = False
        diag = getattr(rt, "diagnostics", None)
        if diag is not None:
            snap["panel_errors"] = snap["panel_errors"] + list(diag.errors)
        mstate = mission_payload.get("state") or ("preflight" if PANEL.loading else "unknown")
        counters = dict(read("counters", lambda: _rows(conn,
                                           "SELECT name, value FROM counters"), []))
        transitions = read("transitions", lambda: _rows(conn,
            "SELECT task_id, to_state, actor, reason, timestamp FROM "
            "state_transitions ORDER BY id DESC LIMIT 40"), [])
        latest_state = {r[0]: r[1:] for r in read("task states", lambda: _rows(conn,
            "SELECT task_id,to_state,actor,timestamp FROM state_transitions WHERE id IN "
            "(SELECT MAX(id) FROM state_transitions GROUP BY task_id)"), [])}
        tasks = []
        for (spec,) in read("tasks", lambda: _rows(conn, "SELECT spec_json FROM tasks"), []):
            t = read("task spec", lambda: json.loads(spec), {})
            if not isinstance(t, dict) or not isinstance(t.get("task_id"), str):
                snap["ok"] = False
                snap["read_errors"].append({"source": "task spec", "error": "invalid task record"})
                continue
            tid = t.get("task_id", "?")
            st = latest_state.get(tid, ("unknown", "", ""))
            tasks.append({
                "task_id": tid, "objective": t.get("objective") or "",
                "state": st[0], "actor": st[1], "at": st[2],
                "worker_session_id": t.get("worker_session_id"),
                "local_fixes": counters.get("local_fixes:" + tid, 0),
                "replans": counters.get("replans:" + tid, 0),
                "max_local_fixes": (t.get("budgets") or {}).get(
                    "max_local_fixes", "?"),
                "max_replans": (t.get("budgets") or {}).get("max_replans", "?"),
            })
        snap.update({
            "mission": {
                "id": rt.mission.mission_id,
                "state": mstate,
                "reason": mission_payload.get("reason", ""),
                "cancellation": mission_payload.get('cancellation', {'status': 'historical_unknown'}),
                "stop_request": mission_payload.get('stop_request'),
                "worker_stop": mission_payload.get('worker_stop'),
                "source": mission_payload.get('source'),
                "execution_backend": mission_payload.get('execution_backend', 'ao'),
                "engine": {k: v for k, v in mission_payload.get('engine', {}).items() if k != 'executable'},
                "result_path": str(rt.runtime / 'integration') if mission_payload.get('merged') else None,
                "previous_attempt": mission_payload.get('previous_attempt'),
                "inspection_only": rt.controller is None,
                "objective": rt.mission_dict.get("objective", ""),
            },
            "subtasks": sorted(tasks, key=lambda t: t["task_id"]),
            "transitions": [{"task": t[0], "to": t[1], "actor": t[2],
                             "reason": t[3] or "", "at": t[4]}
                            for t in transitions[:25]],
            "gate_query": StateStore.query_gate_runs(conn),
            "audits": read("audits", lambda: _payloads("audits", 4), []),
            "verifications": read("verifications", lambda: _payloads("verifications", 4), []),
            "alerts": read("alerts", lambda: _payloads("alerts", 10), []),
            "counters": counters,
            "directives_pending": rt.controller.directives.pending_count() if rt.controller else None,
        })
        snap['approvals'] = []
        snap['approval_receipts'] = []
        if rt.controller is None and mission_payload.get('execution_backend') == 'codex_app_server':
            for target, request_json, result_json in read('approval receipts', lambda: _rows(conn,
                    "SELECT target,request_json,result_json FROM external_operations "
                    "WHERE owner_id=? AND kind='approval' ORDER BY updated_at DESC LIMIT 50", (rt.mission.mission_id,)), []):
                req, result = json.loads(request_json), json.loads(result_json)
                snap['approval_receipts'].append({
                    'worker_id': target, 'request_id': req.get('request_id'),
                    'status': result.get('status', 'UNKNOWN'), 'adoption': result.get('adoption', 'UNKNOWN'),
                    'reason': result.get('reason', '历史审批字段未提供；不推断已采纳')})
        if rt.controller and getattr(getattr(rt, 'adapter', None), 'backend', None) == 'codex_app_server':
            snap['approval_receipts'] = rt.adapter.approval_receipts()
            for task in list(rt.controller.tasks.values()):
                if not task.worker_session_id:
                    continue
                for request in rt.adapter.pending_approvals(task.worker_session_id):
                    policy = rt.adapter.approval_policy(task.worker_session_id, request)
                    params = request['params']
                    snap['approvals'].append({'worker_id': task.worker_session_id,
                        'request_id': request['request_id'], 'method': request['method'],
                        'reason': params.get('reason'), 'command': params.get('command'), 'cwd': params.get('cwd'),
                        'questions': params.get('questions'), 'policy_reason': policy.reason,
                        'policy': 'AUTO' if policy.allow else 'REVIEW' if policy.reviewable else 'PROHIBITED_OR_UNSUPPORTED',
                        'paths': [c.get('path') for c in (request.get('item') or {}).get('changes', [])],
                        'allow_once_supported': policy.allow or policy.reviewable})
        if snap["gate_query"]["status"] == "read_error":
            snap["ok"] = False
    except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError) as exc:
        snap["ok"] = False
        snap["read_errors"].append({"source": "snapshot", "error": str(exc)})
        snap.setdefault("mission", {"id": rt.mission.mission_id, "state": "unknown"})
        snap["gate_query"] = StateStore.query_gate_runs(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    # traffic tail
    def traffic():
        log = _runtime_file(rt, "bus_traffic.jsonl")
        if log.exists():
            lines = log.read_text(encoding="utf-8",
                                  errors="replace").splitlines()[-30:]
            return [json.loads(x) for x in lines if x.strip()]
        return []
    snap["traffic"] = read("traffic", traffic, [])
    return snap


def read_file(rt, name: str) -> str:
    if name not in ("memory.md", "project.md"):
        raise ClientError("bad name")
    p = _runtime_file(rt, name)
    if p.exists():
        return p.read_text(encoding="utf-8", errors="replace")
    return "(尚未生成)"


# ---------------------------------------------------------------- handler
class PanelHTTPServer(ThreadingHTTPServer):
    def __init__(self, address, handler=None):
        if address[0] != "127.0.0.1":
            raise ValueError("Panel must bind to 127.0.0.1")
        self.panel_nonce = secrets.token_urlsafe(32)
        super().__init__(address, handler or Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "ClosedLoopPanel/1.0"

    def log_message(self, *a):           # quiet
        pass

    # -- helpers
    def _host(self):
        hosts = self.headers.get_all("Host", [])
        port = self.server.server_address[1]
        allowed = {"127.0.0.1:%d" % port, "localhost:%d" % port}
        if port == 80:
            allowed.update(("127.0.0.1", "localhost"))
        if len(hosts) != 1 or hosts[0].lower() not in allowed:
            raise ClientError("unsupported Host", 403)
        return hosts[0].lower()

    def _write_boundary(self):
        host = self._host()
        if self.headers.get_all("Origin", []) != ["http://" + host]:
            raise ClientError("same-origin Origin required", 403)
        if (len(self.headers.get_all("Content-Type", [])) != 1
                or self.headers.get_content_type() != "application/json"
                or self.headers.get_content_charset("utf-8").lower() != "utf-8"):
            raise ClientError("application/json with UTF-8 required", 415)
        tokens = self.headers.get_all("X-Panel-Nonce", [])
        if len(tokens) != 1 or not secrets.compare_digest(
                tokens[0].encode("utf-8"), self.server.panel_nonce.encode("ascii")):
            raise ClientError("valid Panel session nonce required", 403)

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _discard_rejected_body(self):
        """Avoid a TCP reset masking the error response when a small body is
        still arriving. Never trust ambiguous framing or wait without a cap.
        """
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1
                or not re.fullmatch(r"[0-9]+", lengths[0])):
            return
        size = int(lengths[0])
        if not 0 < size <= 10 * 1024 * 1024:
            return
        timeout = self.connection.gettimeout()
        try:
            self.connection.settimeout(1)
            self.rfile.read(size)
        except OSError:
            pass
        finally:
            self.connection.settimeout(timeout)

    def _json(self, obj, code=200):
        if hasattr(self, "_received_mono") and isinstance(obj, dict):
            obj["request_timing"] = {"received_at": self._received_epoch,
                                     "response_at": time.time(),
                                     "handler_seconds": time.perf_counter() - self._received_mono}
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        # Bound the body size (local panel, but a malformed Content-Length
        # like 999999999 must not trigger a huge read / OOM) and tolerate a
        # non-numeric Content-Length without crashing the connection.
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1
                or not re.fullmatch(r"[0-9]+", lengths[0])):
            raise ClientError("one valid Content-Length required")
        n = int(lengths[0])
        if not 0 < n <= 10 * 1024 * 1024:
            raise ClientError("JSON body size outside allowed range", 413)
        try:
            def reject_constant(value):
                raise ValueError("non-finite JSON value")
            body = json.loads(self.rfile.read(n).decode("utf-8"), parse_constant=reject_constant)
        except (ValueError, UnicodeError) as exc:
            raise ClientError("invalid UTF-8 JSON body") from exc
        if not isinstance(body, dict):
            raise ClientError("JSON object required")
        return body

    # -- routing
    def do_GET(self):
        try:
            self._host()
            self._get()
        except ClientError as exc:
            self._json({"ok": False, "error": str(exc)}, exc.code)
        except (OSError, sqlite3.Error, ValueError) as exc:
            self._json({"ok": False, "status": "read_error", "error": str(exc)}, 500)

    def _get(self):
        path = urllib.parse.urlparse(self.path).path
        if path in PANEL_ASSETS:
            resource, mime = PANEL_ASSETS[path]
            content = resource.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self._security_headers()
            self.end_headers()
            self.wfile.write(content)
            return
        if path == "/" or path == "/index.html":
            html = (PANEL_DIR / "index.html").read_text(encoding="utf-8").replace(
                "__PANEL_NONCE__", self.server.panel_nonce).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self._security_headers()
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'nonce-%s'; "
                             "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                             "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
                             "form-action 'self'" % self.server.panel_nonce)
            self.end_headers()
            self.wfile.write(html)
            return
        if path == "/api/state":
            self._json(snapshot())
            return
        if path == "/api/projects":
            try:
                from loopcore.local_projects import projects
                self._json({"ok": True, "projects": projects(ROOT)})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 503)
            return
        if path == "/api/stream":
            self._sse()
            return
        if path == "/api/file":
            query = urllib.parse.urlparse(self.path).query
            if re.search(r"%(?![0-9a-fA-F]{2})", query):
                raise ClientError("invalid query encoding")
            try:
                q = urllib.parse.parse_qs(query, keep_blank_values=True, errors="strict")
            except UnicodeError as exc:
                raise ClientError("invalid query encoding") from exc
            if set(q) != {"name"} or len(q["name"]) != 1:
                raise ClientError("one file name required")
            name = (q.get("name") or [""])[0]
            if name not in ("memory.md", "project.md"):
                self._json({"ok": False, "error": "bad name"}, 400)
                return
            with PANEL.lock:
                rt = PANEL.rt
            if not rt:
                self._json({"ok": False, "error": "no mission"}, 400)
                return
            self._json({"ok": True, "name": name,
                        "content": read_file(rt, name)})
            return
        self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        self._received_epoch = time.time()
        self._received_mono = time.perf_counter()
        path = urllib.parse.urlparse(self.path).path
        try:
            try:
                self._write_boundary()
            except ClientError:
                self._discard_rejected_body()
                raise
            body = self._body()
            if path == '/api/projects/open' or path == '/api/projects/create':
                from loopcore.local_projects import register
                self._json({'ok': True, 'project': register(ROOT, body.get('path'), create=path.endswith('/create'))})
                return
            if path == '/api/projects/source':
                from loopcore.local_projects import inspect, project
                if 'mission_id' in body:
                    mid = _mission_id(body['mission_id'])
                    mission = _saved_mission(mid)
                    with_store = StateStore(_runtime_dir(mid) / 'state.db', readonly=True)
                    try:
                        saved = with_store.mission_config(mid)
                    finally:
                        with_store.close()
                    backend = saved.get('execution_backend', 'ao')
                    pid = mission['project_id']
                    source = inspect(project(ROOT, pid)) if backend == 'codex_app_server' else None
                    self._json({'ok': True, 'mission_id': mid, 'project_id': pid, 'execution_backend': backend,
                                'source': source, 'project_path': source['path'] if source else (saved.get('source') or {}).get('project_path')})
                    return
                self._json({'ok': True, 'source': inspect(project(ROOT, body.get('project_id')))})
                return
            if path == '/api/approval':
                receipt = PANEL.approval(body)
                self._json(receipt, 409 if not receipt['ok'] else 202 if receipt['status'] == 'UNKNOWN' else 200)
                return
            if path == "/api/mission":
                self._json(self._start_mission(body))
                return
            if path == '/api/new-attempt':
                self._json(self._new_attempt(body))
                return
            if path == "/api/resume":
                self._json(self._resume(body))
                return
            if path == "/api/attach":
                self._json(self._attach(body))
                return
            if path == "/api/stop":
                self._json(PANEL.stop())
                return
            if path == "/api/directive":
                d = PANEL.post_directive(body.get("target"), body.get("text"), body.get("command_id"))
                self._json({"ok": True, "directive": d})
                return
            if path == "/api/config":
                self._json({"ok": True,
                            "config": PANEL.set_config(body)})
                return
        except ClientError as e:
            self._json({"ok": False, "error": str(e)}, e.code)
            return
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 400)
            return
        self._json({"ok": False, "error": "not found"}, 404)

    # -- mission builders
    def _start_mission(self, body: dict) -> dict:
        project_id = str(body.get("project_id") or "").strip()
        if not project_id:
            raise RuntimeError("project_id is required")

        objective = (body.get("objective") or "").strip()
        if not objective:
            raise RuntimeError("objective 不能为空")
        mid = "MISSION-PANEL-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), secrets.token_hex(4))
        allowed = [p.strip() for p in (body.get("allowed_paths") or "")
                   .splitlines() if p.strip()] or ["app.py", "math2.py",
                                                   "tests/**"]
        acs = []
        for i, line in enumerate((body.get("acceptance_criteria") or "")
                                 .splitlines()):
            line = line.strip()
            if line:
                acs.append({"id": "AC-%02d" % (i + 1), "description": line})
        if not acs:
            raise RuntimeError("至少一条验收条件")
        gates = [g.strip() for g in (body.get("gate_commands") or "")
                 .splitlines() if g.strip()] or ["python -m pytest -q"]
        max_subtasks = body["max_subtasks"] if "max_subtasks" in body else PANEL.defaults()["budgets"]["max_subtasks"]
        if type(max_subtasks) is not int or max_subtasks not in (1, 2):
            raise ClientError("budgets.max_subtasks must be 1 or 2 (integer)")
        mission = {
            "mission_id": mid,
            "project_id": project_id,
            "execution_backend": "codex_app_server",
            "source_revision": body.get("source_revision"),
            "objective": objective,
            "allowed_paths": allowed,
            "forbidden_paths": [".git/**"],
            "acceptance_criteria": acs,
            "gate_commands": gates,
            "user_instruction": body.get("user_instruction") or "",
            "worker_harness": "codex",
            "budgets": {"max_subtasks": max_subtasks},
        }
        # persist for resume/reference
        _runtime_dir(mid)
        tasks_dir = _contained(ROOT, ROOT / "tasks")
        tasks_dir.mkdir(exist_ok=True)
        _contained(tasks_dir, tasks_dir / ("%s.json" % mid.lower())).write_text(
            json.dumps(mission, ensure_ascii=False, indent=2), "utf-8")
        PANEL.start_mission(mission)
        return {"ok": True, "mission_id": mid}

    def _resume(self, body: dict) -> dict:
        mid = _mission_id(body.get("mission_id"))
        mission = _saved_mission(mid)
        PANEL.start_mission(mission)          # store resumes in place
        return {"ok": True, "mission_id": mid, "resumed": True}

    def _attach(self, body: dict) -> dict:
        """Load a stored mission READ-ONLY for inspection (no runner thread,
        no provider calls — the kernel is never stepped)."""
        mid = _mission_id(body.get("mission_id"))
        mission = _saved_mission(mid)
        with PANEL.lock:
            if PANEL.running() or PANEL.loading:
                raise RuntimeError("任务运行中，先停止再查看其它存档")
            PANEL.rt = run_mission.inspect_runtime(mid)
            PANEL.last_summary = None
            PANEL.started_mono = None
        return {"ok": True, "mission_id": mid, "attached": True}

    def _new_attempt(self, body):
        from loopcore import local_projects
        mid = _mission_id(body.get('mission_id'))
        mission = _saved_mission(mid)
        store = StateStore(_runtime_dir(mid) / 'state.db', readonly=True)
        try:
            row = store.mission_config(mid)
            backend = row.get('execution_backend', 'ao')
            if backend not in ('ao', local_projects.BACKEND) or mission.get('execution_backend', backend) != backend:
                raise ClientError('存档执行后端不一致', 409)
            if body.get('project_id') != mission['project_id'] or body.get('execution_backend') != backend:
                raise ClientError('重新执行的项目/后端确认与目标存档不一致', 409)
            if row.get('state') not in MISSION_TERMINAL:
                raise ClientError('非终态应通过材料检查后恢复，不创建替代 attempt', 409)
            tasks = [store.load_task(t) or {} for t in store.all_task_ids()]
            ops = store.operations(mid)
            if ((any(t.get('worker_session_id') for t in tasks) or any(op['kind'] == 'spawn' for op in ops)) and row.get('worker_stop', {}).get('status') != 'CONFIRMED'
                    or row.get('cancellation', {}).get('status') == 'unknown'
                    or row.get('local_execution', {}).get('status') in ('running', 'unknown')):
                raise ClientError('旧 attempt 的停止事实未确认，不能启动替代 Worker', 409)
            mission = dict(mission, mission_id='MISSION-ATTEMPT-' + secrets.token_hex(12), previous_attempt=mid, execution_backend=backend)
            if row.get('execution_backend') == local_projects.BACKEND:
                revision = body.get('source_revision')
                if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{64}', revision):
                    raise ClientError('重新执行前请读取并确认当前项目来源', 422)
                mission.update(execution_backend=local_projects.BACKEND, source_revision=revision)
        finally:
            store.close()
        PANEL.start_mission(mission)
        return {'ok': True, 'mission_id': mission['mission_id'], 'previous_attempt': mid}

    # -- SSE
    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        deadline = time.monotonic() + 300     # client reconnects
        while time.monotonic() < deadline:
            try:
                snap = snapshot()
                cursor = "%s:%s" % (snap["stream"]["epoch"], snap["stream"]["sequence"])
                payload = json.dumps(snap, ensure_ascii=False)
                self.wfile.write(("id: %s\ndata: %s\n\n" % (cursor, payload)).encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            time.sleep(2)


def main() -> int:
    run_mission.setup_environment()
    srv = PanelHTTPServer(("127.0.0.1", PORT))
    url = "http://127.0.0.1:%d/" % PORT
    print("[panel] %s  (Ctrl+C 停止)" % url, flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    PANEL.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
