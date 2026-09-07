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

PANEL_DIR = Path(__file__).resolve().parent
ROOT = PANEL_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import run_mission  # noqa: E402
from loopcore.ao_adapter import AOAdapter  # noqa: E402
from loopcore.envelope import MessageKind  # noqa: E402
from loopcore.mission import MISSION_TERMINAL  # noqa: E402
from loopcore.mission_contracts import new_mission_max_subtasks  # noqa: E402
from loopcore.event_normalizer import now_iso  # noqa: E402
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
        rows = _rows(conn, "SELECT payload_json FROM missions LIMIT 1")
        mission = json.loads(rows[0][0]).get("mission") if rows else None
    finally:
        conn.close()
    if not isinstance(mission, dict) or _mission_id(mission.get("mission_id")) != mid:
        raise ClientError("存档 mission 定义或 mission_id 不匹配")
    return mission


# ------------------------------------------------------------------ state
class PanelState:
    """Owns the active mission runtime (if any) and the runner thread."""

    def __init__(self):
        self.lock = threading.RLock()
        self.rt = None                 # run_mission.MissionRuntime | None
        self.thread = None
        self.stop_flag = threading.Event()
        self.started_mono = None
        self.last_summary = None
        self.live = {                   # live-tunable time knobs (seconds)
            "poll_seconds": 5,
            "idle_audit_cooldown_seconds": 300,
            "blocked_escalation_seconds": 600,
            "l0_nudge_grace_seconds": 300,
        }
        self.errors = []

    # ---- mission lifecycle
    def start_mission(self, mission_dict: dict) -> str:
        _runtime_dir(mission_dict.get("mission_id"))
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise RuntimeError("已有任务在运行，先停止或等待完成")
            run_mission.setup_environment()
            cfg = run_mission.load_config()
            cfg.setdefault("observer", {})
            for k in ("idle_audit_cooldown_seconds",
                      "blocked_escalation_seconds", "l0_nudge_grace_seconds"):
                cfg["observer"][k] = self.live[k]
            self.rt = run_mission.build_runtime(mission_dict, cfg)
            self.stop_flag.clear()
            self.started_mono = time.monotonic()
            self.last_summary = None
            self.thread = threading.Thread(target=self._run, daemon=True,
                                           name="mission-runner")
            self.thread.start()
            return mission_dict["mission_id"]

    def _run(self):
        rt = self.rt
        try:
            started = time.monotonic()
            while True:
                rt.controller.step()
                rt.projector.project_once()
                state = rt.controller.state
                if state in MISSION_TERMINAL or self.stop_flag.is_set():
                    break
                if time.monotonic() - started >= 7200:      # 2h hard cap
                    break
                time.sleep(max(1.0, float(self.live["poll_seconds"])))
            rt.projector.project_once()
            self.last_summary = {
                "mission_id": rt.mission.mission_id,
                "final_state": rt.controller.state,
                "stopped_by_user": self.stop_flag.is_set(),
            }
        except Exception as e:                               # never die mute
            self.errors.append("%s: runner: %s" % (now_iso(), e))

    def stop(self):
        self.stop_flag.set()
        # Land the mission in HUMAN right away (the terminal transition reaps
        # every bound worker) so the user-visible state stops progressing NOW
        # instead of after the in-flight tick unwinds. Controller internals
        # are store-locked/idempotent; runs outside self.lock so a slow AO
        # kill can never freeze the panel API.
        rt = self.rt
        if rt is not None:
            try:
                rt.controller.request_stop()
            except Exception as e:                       # never die mute
                self.errors.append("%s: stop: %s" % (now_iso(), e))

    def running(self) -> bool:
        # Once a stop is requested the mission does no further work (stop
        # checkpoints + absorbing terminal state); report stopped immediately
        # rather than wait for an in-flight agent call to unwind.
        return bool(self.thread and self.thread.is_alive()
                    and not self.stop_flag.is_set())

    # ---- directive channel
    def post_directive(self, target: str, text: str) -> dict:
        target, text = (target or "").strip(), (text or "").strip()
        if not target or not text:
            raise RuntimeError("target 和 text 都不能为空")
        with self.lock:
            if not self.rt:
                raise RuntimeError("没有已加载的任务")
            d = self.rt.controller.directives.post(target, text)
            # Capture the log path under the lock (rt may be torn down), then
            # do the disk write OUTSIDE the lock — a slow/full disk must not
            # stall snapshot/start/stop/set_config, which all need the lock.
            log = self.rt.runtime / "bus_traffic.jsonl"
        # 真实投递走上面的 DirectiveChannel（内核 _apply_directives 消费）。
        # LoopBus 按设计拒绝 user 端点（"no handler for endpoint"），不经过它。
        # 流量记录由面板自己直写 bus_traffic.jsonl：每条用户指令必须落盘，
        # 写失败必须冒泡成 API 错误——绝不返回假成功（PV 缺陷 D4）。
        kind = MessageKind.USER_DIRECTIVE.value
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(
                {"at": now_iso(), "kind": kind,
                 "sender": "user", "receiver": target,
                 "payload": {"directive": text}},
                ensure_ascii=False) + "\n")
        return {"target": d.target, "text": d.text, "at": d.at,
                "mirrored_to_planner": target != "planner"}

    # ---- live config
    def set_config(self, updates: dict) -> dict:
        if ("auto_ff_master" in updates
                and updates["auto_ff_master"] is not False):
            raise RuntimeError(
                "auto_ff_master is disabled in the competition runtime")
        with self.lock:
            for k in self.live:
                if k in updates:
                    self.live[k] = max(1, int(updates[k]))
            if self.rt:      # controller reads these per call -> instant
                obs = self.rt.controller.cfg.setdefault("observer", {})
                for k in ("idle_audit_cooldown_seconds",
                          "blocked_escalation_seconds",
                          "l0_nudge_grace_seconds"):
                    obs[k] = self.live[k]
            return dict(self.live)


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
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True,
                           timeout=3)
    return conn


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
                r = _rows(conn, "SELECT payload_json FROM missions LIMIT 1")
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
    with PANEL.lock:
        rt = PANEL.rt
        running = PANEL.running()
        live = dict(PANEL.live)
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
        mstate = mission_payload.get("state") or "unknown"
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
            "directives_pending": rt.controller.directives.pending_count(),
        })
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
                self._json({"ok": True, "projects": _load_ao_projects()})
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
        path = urllib.parse.urlparse(self.path).path
        try:
            try:
                self._write_boundary()
            except ClientError:
                self._discard_rejected_body()
                raise
            body = self._body()
            if path == "/api/mission":
                self._json(self._start_mission(body))
                return
            if path == "/api/resume":
                self._json(self._resume(body))
                return
            if path == "/api/attach":
                self._json(self._attach(body))
                return
            if path == "/api/stop":
                PANEL.stop()
                self._json({"ok": True})
                return
            if path == "/api/directive":
                d = PANEL.post_directive(str(body.get("target") or ""),
                                         str(body.get("text") or ""))
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
        max_subtasks = new_mission_max_subtasks({
            "max_subtasks": body.get("max_subtasks", 1)})
        mission = {
            "mission_id": mid,
            "project_id": project_id,
            "objective": objective,
            "allowed_paths": allowed,
            "forbidden_paths": [".git/**"],
            "acceptance_criteria": acs,
            "gate_commands": gates,
            "user_instruction": body.get("user_instruction") or "",
            "worker_harness": "codex",
            "budgets": {"max_subtasks": max_subtasks,
                        "max_total_replans": 2,
                        "max_runtime_seconds": 3600,
                        "subtask_budgets": {
                            "max_local_fixes": 2, "max_replans": 1,
                            "max_same_alerts": 2,
                            "max_runtime_seconds": 1800}},
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
            if PANEL.running():
                raise RuntimeError("任务运行中，先停止再查看其它存档")
            run_mission.setup_environment()
            cfg = run_mission.load_config()
            PANEL.rt = run_mission.build_runtime(
                mission, cfg, dry_run=True, require_ao=False)
            PANEL.last_summary = None
            PANEL.started_mono = None
        return {"ok": True, "mission_id": mid, "attached": True}

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
                payload = json.dumps(snapshot(), ensure_ascii=False)
                self.wfile.write(("data: %s\n\n" % payload).encode("utf-8"))
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
