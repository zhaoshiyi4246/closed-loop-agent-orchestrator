"""Codex 0.150.1 public App Server JSONL/stdio Worker boundary.

Business state stays in StateStore/Controller. No AO DTOs, private engine
database, automatic login, socket service or transport replay lives here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .local_projects import BACKEND
from .models import NormalizedEvent
from . import worktree as wt

SUPPORTED_VERSION = "0.150.1"


class CodexUnknown(RuntimeError):
    pass


class CodexRejected(RuntimeError):
    """A protocol error response, not a missing acknowledgement."""


class CodexNotStarted(RuntimeError):
    pass


class StdioClient:
    def __init__(self, executable, cwd, on_message=None, on_disconnect=None, *, config=None):
        self.lock = threading.RLock()
        self.pending = {}
        self.serial = 0
        self.on_message = on_message or (lambda message: None)
        self.on_disconnect = on_disconnect or (lambda: None)
        self.closed = False
        argv = [executable, "app-server", "--listen", "stdio://",
                "-c", "features.multi_agent=false", "-c", 'web_search="disabled"',
                "-c", "features.default_mode_request_user_input=true"]
        # Process-local public config overrides; never edit global settings.
        for feature in ("apps", "connectors", "plugins", "hooks", "codex_hooks", "plugin_hooks",
                        "browser_use", "computer_use", "image_generation", "js_repl"):
            argv.extend(["-c", "features." + feature + "=false"])
        for value in config or ():
            argv.extend(['-c', value])
        from .native_models import process_environment
        try:
            self.proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=process_environment(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except OSError as exc:
            raise CodexNotStarted("Codex App Server 进程未启动：" + type(exc).__name__) from exc
        self.reader = threading.Thread(target=self._read, daemon=True, name="codex-stdio")
        self.reader.start()

    def _write(self, message):
        with self.lock:
            if self.closed or self.proc.poll() is not None:
                raise CodexUnknown("App Server 连接已断开")
            try:
                self.proc.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
                self.proc.stdin.flush()
            except OSError as exc:
                raise CodexUnknown("App Server 写入结果未知") from exc

    def _read(self):
        try:
            while True:
                line = self.proc.stdout.readline(8 * 1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 8 * 1024 * 1024 or not line.endswith(b"\n"):
                    raise ValueError("oversized/incomplete App Server frame")
                def unique(pairs):
                    result = {}
                    for k, v in pairs:
                        if k in result:
                            raise ValueError("duplicate JSON field")
                        result[k] = v
                    return result
                message = json.loads(line, object_pairs_hook=unique)
                if not isinstance(message, dict):
                    raise ValueError("invalid protocol frame")
                if "method" in message:
                    self.on_message(message)
                elif "id" in message:
                    with self.lock:
                        waiter = self.pending.get(message["id"])
                    if waiter:
                        waiter[1].append(message)
                        waiter[0].set()
                else:
                    raise ValueError("unsupported protocol frame")
        except Exception:
            # Do not log raw frames, prompts, stderr, credentials or argv.
            pass
        finally:
            self.closed = True
            self.on_disconnect()
            with self.lock:
                for event, result in self.pending.values():
                    event.set()

    def request(self, method, params, timeout=30):
        with self.lock:
            self.serial += 1
            identity = self.serial
            event, result = threading.Event(), []
            self.pending[identity] = (event, result)
        try:
            self._write({"id": identity, "method": method, "params": params})
            if not event.wait(timeout) or not result:
                raise CodexUnknown(method + " 确认丢失；不会自动重发")
            reply = result[0]
            if "error" in reply:
                error = reply["error"]
                # Engine diagnostics can include prompt material. Only protocol
                # category/code is persisted; the original stays with the engine.
                code = error.get("code") if isinstance(error, dict) else None
                if type(code) is not int:
                    code = 'unknown'
                exception = CodexRejected if code in (-32600, -32601, -32602) else CodexUnknown
                raise exception(method + " 返回错误 (code=" + str(code) + ")")
            if not isinstance(reply.get("result"), dict):
                raise CodexUnknown(method + " 返回字段不完整")
            return reply["result"]
        finally:
            with self.lock:
                self.pending.pop(identity, None)

    def initialize(self, timeout=30):
        result = self.request("initialize", {"clientInfo": {"name": "clao", "version": "0.3"}}, timeout)
        self._write({"method": "initialized"})
        return result

    def close(self):
        # This closes the transport, never asserts that a Worker stopped.
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
        self.reader.join(timeout=3)


def preflight(cwd, profile=None):
    executable = shutil.which("codex")
    if not executable:
        raise ValueError("未找到 Codex；安装官方 Codex CLI 后重试")
    result = subprocess.run([executable, "--version"], capture_output=True, timeout=15)
    version = result.stdout.decode("utf-8", "replace").strip()
    if result.returncode or version != "codex-cli " + SUPPORTED_VERSION:
        raise ValueError("当前本地后端仅核对 Codex " + SUPPORTED_VERSION + "；发现 " + version + "，未自动升级")
    from .native_models import client_config, authenticate_client
    from .model_profiles import CODEX_API
    client = StdioClient(executable, cwd, config=client_config(profile))
    try:
        client.initialize()
        authenticate_client(client, profile)
        account = client.request("account/read", {"refreshToken": False})
        required = 'apiKey' if profile and profile['service'] == CODEX_API else 'chatgpt'
        if (account.get("account") or {}).get("type") != required:
            raise ValueError("Codex 认证方式不符；请检查所选连接或在官方 Codex 登录 ChatGPT（codex login）")
        if os.name == "nt":
            ready = client.request("windowsSandbox/readiness", None)
            if ready.get("status") != "ready":
                raise ValueError("Codex Windows 沙箱未就绪；请在官方 Codex 完成沙箱设置后重试")
    finally:
        client.close()
    return {"backend": BACKEND, "version": SUPPORTED_VERSION, "transport": "stdio", "executable": executable}


class CodexBackend:
    backend = BACKEND

    def __init__(self, store, mission_id, executable, model, source, timeout=30, profile=None):
        self.store, self.mission_id = store, mission_id
        self.executable, self.model, self.source, self.timeout = executable, model, source, timeout
        self.profile = copy.deepcopy(profile)
        self.lock = threading.RLock()
        self.client = None
        self.approval_lock = threading.RLock()
        self.events = []
        self.requests = {}
        self._loaded = set()
        self.workers = copy.deepcopy((store.mission_config(mission_id) or {}).get("local_workers", {}))

    def _save(self):
        from .action_executor import _sanitize_spawn_error
        rows = copy.deepcopy(self.workers)
        for row in rows.values():
            row["items"] = {key: {k: v for k, v in item.items() if k in ("id", "type", "status", "exitCode", "processId")}
                            for key, item in row.get("items", {}).items()}
            row["reason"] = _sanitize_spawn_error(row.get("reason", ""))[:1600]
            if row.get("terminal_error"):
                row["terminal_error"] = _sanitize_spawn_error(row["terminal_error"])[:1600]
        self.store.record_mission(self.mission_id, {"local_workers": rows})

    def _connect(self):
        if self.client is None:
            from .native_models import client_config, authenticate_client
            client = StdioClient(self.executable, Path(self.store.path).parent,
                                 self._message, self._disconnected, config=client_config(self.profile))
            try:
                client.initialize(self.timeout)
                authenticate_client(client, self.profile, self.timeout)
            except BaseException:
                client.close()
                raise
            self.client = client
        if self.client.closed:
            raise CodexUnknown("Worker 传输已断开；需人工确认，不自动连接重发")
        return self.client

    def worker_ids(self):
        with self.lock:
            return list(self.workers)

    def _tool_config(self, client, cwd):
        # Read the public effective config only to disable inherited MCP tools.
        # Never persist/log its contents (it may contain sensitive settings).
        reply = client.request("config/read", {"cwd": cwd, "includeLayers": False}, self.timeout)
        config = reply.get("config")
        if not isinstance(config, dict) or not isinstance(config.get("mcp_servers", {}), dict):
            raise CodexUnknown("无法确认继承的 MCP 配置；不启动执行")
        return {"mcp_servers": {name: {"enabled": False} for name in config.get("mcp_servers", {})}}

    def _disconnected(self):
        with self.lock:
            for row in self.workers.values():
                if row.get("state") not in ("idle", "failed", "interrupted", "stopped"):
                    row.update(state="unknown", reason="App Server 连接中断，执行停止未确认")
            try:
                self._save()
            except Exception:
                pass

    def _message(self, message):
        method, params = message.get("method"), message.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("invalid event params")
        with self.lock:
            pairs = [(wid, row) for wid, row in self.workers.items() if row.get("thread_id") == params.get("threadId")]
            if not pairs:
                return
            wid, row = pairs[0]
            turn = params.get("turn") or {}
            turn_id = turn.get("id") or params.get("turnId")
            if method == "turn/started":
                if row.get("pending") or any(i.get("status") == "inProgress" for i in row.get("items", {}).values()):
                    raise ValueError("new turn before previous tool resolved")
                row["items"] = {}
                row.pop("terminal_error", None)
                row.update(turn_id=turn_id, state="active", ended=False, reason="Worker 执行中")
                self._event(wid, "worker_started", "Codex 回合开始", turn_id)
            elif method == "turn/completed":
                if turn_id != row.get("turn_id") or turn.get("status") not in ("completed", "failed", "interrupted"):
                    row.update(state="unknown", ended=False, reason="回合结束关联或状态无法确认")
                else:
                    status = turn["status"]
                    if status == "completed" and row.get("terminal_error"):
                        status = "failed"
                    row.update(state="idle" if status == "completed" else status, ended=True,
                               reason=(turn.get("error") or {}).get("message") or row.get("terminal_error") or ("Worker 回合完成，等待验收" if status == "completed" else "Worker " + status))
                for receipt in row.get("approval_receipts", {}).values():
                    if receipt["turn_id"] == turn_id:
                        receipt["turn_end"] = turn.get("status")
                self._event(wid, "worker_finished" if row.get("state") == "idle" else "error", row["reason"], turn_id)
            elif method in ("item/started", "item/completed"):
                item = params.get("item") or {}
                if turn_id != row.get("turn_id"):
                    raise ValueError("item turn mismatch")
                # Live request correlation needs proposed file changes, not a
                # finished diff or human-facing parsed commandActions.
                row.setdefault("items", {})[item["id"]] = copy.deepcopy(item)
                if method == "item/completed":
                    for receipt in row.get("approval_receipts", {}).values():
                        if receipt["turn_id"] == turn_id and receipt["item_id"] == item["id"]:
                            receipt.update(item_status=item.get("status"), exit_code=item.get("exitCode"))
                    kind = item.get("type")
                    text = item.get("text") or item.get("command") or kind or "item"
                    failure = item.get("status") in ("failed", "declined") or item.get("exitCode") not in (None, 0)
                    event_type = "error" if failure else "file_changed" if kind == "fileChange" else "command_executed" if kind == "commandExecution" else "task_state_changed"
                    self._event(wid, event_type, text, str(turn_id) + ":" + str(item.get("id")))
            elif method == "serverRequest/resolved":
                key = str(params.get("requestId"))
                receipt = row.get("approval_receipts", {}).get(key)
                if receipt:
                    receipt["request_closed"] = True
                    if not receipt.get("response_written"):
                        receipt["invalidated"] = True
                self.requests.pop((wid, key), None)
                row.setdefault("pending", {}).pop(key, None)
                if row.get("state") == "waiting_input" and not row.get("pending"):
                    row["state"] = "active"
            elif "id" in message:
                if turn_id != row.get("turn_id"):
                    raise ValueError("approval turn mismatch")
                key = str(message["id"])
                self.requests[(wid, key)] = copy.deepcopy(message)
                # Store identity and category, never complete tool input/patch.
                row.setdefault("pending", {})[key] = {"method": method, "item_id": params.get("itemId"), "turn_id": turn_id}
                row.setdefault("approval_receipts", {})[key] = {
                    "method": method, "turn_id": turn_id, "item_id": params.get("itemId"),
                    "request_id": key, "response_written": False, "request_closed": False}
                row.update(state="waiting_input", reason="等待审批或补充信息")
            elif method == "error":
                row.update(state="failed" if not params.get("willRetry") else "active",
                           reason=(params.get("error") or {}).get("message") or "Codex 执行错误")
                if not params.get("willRetry"):
                    row["terminal_error"] = row["reason"]
            elif method == "model/rerouted" and turn_id == row.get("turn_id"):
                row["reroute"] = {k: params.get(k) for k in ("fromModel", "toModel", "turnId")}
            else:
                return  # token/output deltas do not rewrite the durable Worker row
            self._save()

    def _event(self, wid, kind, text, identity):
        self.events.append({"worker": wid, "kind": kind, "text": str(text), "id": str(identity),
                            "at": datetime.now(timezone.utc).isoformat()})

    def normalized_events(self, worker_id, project_id):
        with self.lock:
            rows = [e for e in self.events if e["worker"] == worker_id]
        return [NormalizedEvent(event_id="codex:" + hashlib.sha256((worker_id + e["kind"] + e["id"]).encode()).hexdigest(),
            timestamp=e["at"], project_id=project_id, worker_id=worker_id, event_type=e["kind"],
            task_id=None, source="codex_stdio", activity=True, progress=e["kind"] == "file_changed",
            progress_strength="weak" if e["kind"] == "file_changed" else "none",
            message=e["text"], evidence={"backend": BACKEND}) for e in rows]

    def start(self, op, prompt):
        wid = "codex-" + hashlib.sha256(op["operation_id"].encode()).hexdigest()[:24]
        client = self._connect()  # a failed Popen is provable non-invocation
        workspace = Path(self.store.path).parent / "workers" / wid
        workspace.parent.mkdir(exist_ok=True)
        if workspace.exists():
            raise CodexUnknown("隔离工作区已存在；不能猜测此前执行未发生")
        p = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-C", self.source["project_path"],
            "worktree", "add", "--detach", str(workspace), self.source["source_commit"]], capture_output=True, timeout=30, env=wt._read_env())
        if p.returncode:
            raise CodexRejected("无法建立 CLAO 隔离工作区")
        with self.lock:
            self.workers[wid] = {"workspace": str(workspace), "operation_id": op["operation_id"],
                                 "state": "starting", "ended": False, "items": {}, "pending": {}}
            self._save()
        reply = client.request("thread/start", {"cwd": str(workspace), "model": self.model,
            "approvalPolicy": "untrusted", "approvalsReviewer": "user", "sandbox": "read-only",
            "config": self._tool_config(client, str(workspace)), "ephemeral": False}, self.timeout)
        thread = reply.get("thread") or {}
        if (not isinstance(thread.get("id"), str) or not thread["id"] or
            Path(reply.get("cwd", "")).resolve() != workspace.resolve() or
            (reply.get("sandbox") or {}).get("type") != "readOnly" or reply.get("approvalPolicy") != "untrusted" or
            (reply.get("sandbox") or {}).get("networkAccess", False) is not False or
            reply.get("approvalsReviewer") != "user"):
            raise CodexUnknown("Codex 未确认工作区、沙箱或审批策略")
        with self.lock:
            self.workers[wid].update(thread_id=thread["id"], resolved_model=reply.get("model"))
            self._save()  # binding before the first executable turn
        result = client.request("turn/start", {"threadId": thread["id"], "input": [{"type": "text", "text": prompt}]}, self.timeout)
        self._accepted_turn(wid, result)
        self._loaded.add(wid)
        with self.lock:
            self.workers[wid].setdefault("accepted_operations", {})[op["operation_id"]] = result["turn"]["id"]
            self._save()
        return {"session_id": wid, "thread_id": thread["id"], "turn_id": result["turn"]["id"]}

    def _accepted_turn(self, wid, reply):
        turn = reply.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str) or not turn["id"]:
            raise CodexUnknown("turn/start 缺少回合 ID")
        with self.lock:
            row = self.workers[wid]
            # A completed notification may precede the response on the wire.
            if row.get("turn_id") != turn["id"]:
                row.update(turn_id=turn["id"], state="active", ended=False)
            self._save()

    def send(self, op, message):
        wid = op["target"]
        with self.lock:
            row = copy.deepcopy(self.workers[wid])
        if self._stop_intended(wid) or row.get("state") in ("unknown", "starting", "stopped") or row.get("pending"):
            raise CodexUnknown("当前 Worker 不具备明确的补充输入前提")
        client = self._connect()
        params = {"threadId": row["thread_id"], "input": [{"type": "text", "text": message}]}
        if row.get("state") == "active":
            params["expectedTurnId"] = row["turn_id"]
            reply = client.request("turn/steer", params, getattr(self, "send_timeout", self.timeout))
            if reply.get("turnId") != row["turn_id"]:
                raise CodexUnknown("补充输入回合关联无法确认")
            with self.lock:
                self.workers[wid].setdefault("accepted_operations", {})[op["operation_id"]] = reply["turnId"]
                self._save()
            return {"turn_id": reply["turnId"]}
        if wid not in getattr(self, "_loaded", set()):
            reply = client.request("thread/resume", {"threadId": row["thread_id"], "cwd": row["workspace"],
                "model": self.model, "approvalPolicy": "untrusted", "approvalsReviewer": "user", "sandbox": "read-only",
                "config": self._tool_config(client, row["workspace"])}, self.timeout)
            if ((reply.get("thread") or {}).get("id") != row["thread_id"] or (reply.get("sandbox") or {}).get("type") != "readOnly"
                    or (reply.get("sandbox") or {}).get("networkAccess", False) is not False
                    or Path(reply.get("cwd", "")).resolve() != Path(row["workspace"]).resolve()
                    or reply.get("approvalPolicy") != "untrusted" or reply.get("approvalsReviewer") != "user"):
                raise CodexUnknown("恢复线程或沙箱无法确认")
        reply = client.request("turn/start", params, getattr(self, "send_timeout", self.timeout))
        self._accepted_turn(wid, reply)
        self._loaded.add(wid)
        with self.lock:
            self.workers[wid].setdefault("accepted_operations", {})[op["operation_id"]] = reply["turn"]["id"]
            self._save()
        return {"turn_id": reply["turn"]["id"]}

    def stop(self, op):
        wid = op["target"]
        with self.lock:
            row = copy.deepcopy(self.workers.get(wid, {}))
        if self.stopped(wid):
            return
        if not row.get("thread_id") or not row.get("turn_id") or row.get("state") == "unknown":
            raise CodexUnknown("无法确认需要中断的执行回合")
        timeout = getattr(self, "kill_timeout", self.timeout)
        self._connect().request("turn/interrupt", {"threadId": row["thread_id"], "turnId": row["turn_id"]}, timeout)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stopped(wid):
                return
            time.sleep(.02)
        raise CodexUnknown("取消请求已送达，但回合结束未确认")

    def stopped(self, wid):
        with self.lock:
            row = self.workers.get(wid, {})
            # Engine turn completion is necessary; unfinished command/file
            # items (including background commands) additionally block delivery.
            return bool(row.get("ended") and not row.get("pending") and row.get("state") in ("idle", "failed", "interrupted", "stopped")
                        and not any(i.get("type") in ("commandExecution", "fileChange") and i.get("status") == "inProgress"
                                    for i in row.get("items", {}).values()))

    def reconciliation_fact(self, op):
        with self.lock:
            accepted = [(wid, row) for wid, row in self.workers.items()
                        if op["operation_id"] in row.get("accepted_operations", {})]
            if len(accepted) == 1 and op["kind"] in ("spawn", "send"):
                wid, row = accepted[0]
                return dict(status="SUCCEEDED", evidence={"reason": "persisted matching Codex protocol ACK"},
                            result={"session_id": wid, "thread_id": row["thread_id"],
                                    "turn_id": row["accepted_operations"][op["operation_id"]]})
        if op["kind"] == "approval":
            return self._approval_fact(op["target"], op["request"]["request_id"], op["request"].get("turn_id"))
        if op["kind"] == "kill" and self.stopped(op["target"]):
            return dict(status="SUCCEEDED", evidence={"reason": "Codex matching turn ended; no in-flight command/file item"}, result={"session_id": op["target"]})
        return dict(status="UNKNOWN", evidence={"reason": "App Server 无已持久唯一 ACK；未确认结果，不重发"}, result=None)

    def get_worker_status(self, wid):
        with self.lock:
            row = self.workers.get(wid)
            if not row:
                raise CodexUnknown("Worker 记录不存在")
            diag = getattr(self, "diagnostics", None)
            if diag is not None:
                diag.worker_fact(wid, activity=row["state"], requested_model=self.model,
                                 spawn_resolved_model=row.get("resolved_model"), reroute=row.get("reroute"), backend=BACKEND)
            return {"backend": BACKEND, "execution_state": row["state"], "reason": row.get("reason"),
                    "thread_id": row.get("thread_id"), "turn_id": row.get("turn_id"), "ended": row.get("ended")}

    def get_session_workspace(self, wid):
        with self.lock:
            row = self.workers.get(wid) or {}
            path = Path(row.get("workspace", ""))
            root = (Path(self.store.path).parent / "workers").resolve()
            if not path.is_absolute() or not path.resolve(strict=True).is_relative_to(root):
                raise CodexUnknown("Worker 工作区不可确认")
            return str(path)

    def pending_approvals(self, wid):
        with self.lock:
            result = []
            for (worker, key), message in self.requests.items():
                if worker != wid:
                    continue
                params = copy.deepcopy(message["params"])
                item = self.workers[wid].get("items", {}).get(params.get("itemId"))
                result.append({"backend": BACKEND, "request_id": key, "method": message["method"],
                               "params": params, "item": copy.deepcopy(item)})
            return result

    def _stop_intended(self, wid):
        from .action_executor import operation_id
        return self.store.operation(operation_id("kill", wid)) is not None

    def resolve_approval(self, wid, request_id, decision, answers=None):
        # A live HTTP submission is not a crashed operation. Serialize its
        # short acknowledgement window with Controller reconciliation.
        with self.approval_lock:
            return self._resolve_approval(wid, request_id, decision, answers)

    def approval_policy(self, wid, request):
        from .approvals import decide_codex_approval
        tasks = [self.store.load_task(t) for t in self.store.all_task_ids()]
        tasks = [t for t in tasks if t and t.get("worker_session_id") == wid]
        if len(tasks) != 1:
            raise ValueError("无法唯一确认审批所属任务及范围")
        task = tasks[0]
        return decide_codex_approval(request, allowed_paths=task["allowed_paths"],
            forbidden_paths=task["forbidden_paths"], gate_commands=task["gate_commands"],
            worktree_root=self.get_session_workspace(wid))

    def _approval_fact(self, wid, key, turn_id):
        with self.lock:
            row = self.workers.get(wid, {})
            receipt = row.get("approval_receipts", {}).get(key, {})
            saved = self.store.operation(receipt['operation_id']) if receipt.get('operation_id') else None
            if saved and saved['status'] == 'SUCCEEDED' and receipt.get('turn_id') == turn_id:
                return dict(status='SUCCEEDED', evidence=saved['evidence'][-1]['fact'], result=saved['result'])
            written, closed = receipt.get("response_written", False), receipt.get("request_closed", False)
            result = {"request_id": key, "response_written": written, "request_closed": closed,
                      "adoption": "UNKNOWN", "status": "UNKNOWN", "observation_only": False,
                      "turn_end": receipt.get('turn_end'), "item_status": receipt.get('item_status')}
            status, reason = "UNKNOWN", "响应结果无法确认；不会重复发送"
            result['reason'] = reason
            if receipt.get("turn_id") != turn_id:
                return dict(status=status, evidence={"reason": reason}, result=result)
            invalidated = receipt.get("invalidated") or receipt.get("turn_end") == "interrupted"
            if invalidated:
                result["status"] = "INVALIDATED" if written else "EXPIRED"
                status = "UNKNOWN" if written else "FAILED"
                reason = "请求因取消或生命周期变化关闭；不能确认本次响应已被采纳" if written else "请求已失效，未发送响应"
            elif written and closed:
                item_status = receipt.get("item_status")
                decision = receipt.get("decision")
                if decision in ("accept", "decline") and item_status == "declined":
                    status = "SUCCEEDED" if decision == "decline" else "FAILED"
                    result.update(status="DECLINED", adoption="DECLINED")
                    reason = "关联 item 明确拒绝；不代表命令执行成功"
                elif decision == "accept" and (item_status == "completed" or
                        item_status == "failed" and receipt.get("exit_code") is not None):
                    status = "SUCCEEDED"
                    result.update(status="CONFIRMED", adoption="CONFIRMED")
                    reason = "关联请求关闭且同一回合 item 有执行结果；不等于 Gate PASS"
                else:
                    # v0.150.1 has no public answer-adoption receipt. Closing a
                    # request is insufficient, even on a normal completed turn.
                    # Observation/Gate can consume subsequent independent facts;
                    # this closed response must never be sent again.
                    result["observation_only"] = True
                    reason = ("回合已结束且请求关闭；采纳未知，无法区分响应采纳与生命周期清理，不重发"
                              if receipt.get('turn_end') else "响应已写入且请求已关闭；采纳未知，继续观察独立执行事实，不重发")
            result["reason"] = reason
            return dict(status=status, evidence={"reason": reason, "turn_id": turn_id,
                        "item_id": receipt.get("item_id"), "request_closed": closed}, result=result)

    def approval_receipts(self):
        with self.lock:
            return [dict(self._approval_fact(wid, key, r["turn_id"])["result"], worker_id=wid)
                    for wid, row in self.workers.items() for key, r in row.get("approval_receipts", {}).items()
                    if r.get("response_written") or r.get("request_closed")]

    def _resolve_approval(self, wid, request_id, decision, answers=None):
        with self.lock:
            message = self.requests.get((wid, request_id))
            if not message or not self.client or self.client.closed or self._stop_intended(wid) or self.workers[wid].get("ended"):
                raise CodexUnknown("请求已失效或连接断开；未重发审批")
            method, params = message["method"], message["params"]
            if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
                if decision not in ("accept", "decline"):
                    raise ValueError("仅支持允许一次或拒绝")
                current = next(r for r in self.pending_approvals(wid) if r['request_id'] == request_id)
                policy = self.approval_policy(wid, current)
                if decision == "accept" and not (policy.allow or policy.reviewable):
                    raise ValueError("本任务禁止或不支持授权：" + policy.reason)
                result = {"decision": decision}
            elif method == "item/tool/requestUserInput":
                questions = params.get("questions") or []
                if decision != "answer" or not isinstance(answers, dict) or set(answers) != {q["id"] for q in questions} or any(not isinstance(v, str) or not v.strip() for v in answers.values()):
                    raise ValueError("请回答每个问题")
                result = {"answers": {k: {"answers": [v]} for k, v in answers.items()}}
            else:
                raise ValueError("不支持的引擎请求；请取消任务并人工处理")
            turn_id = params["turnId"]
            identity = "codex-approval:" + wid + ":" + turn_id + ":" + request_id
            op = self.store.ensure_operation(identity, "approval", self.mission_id, wid,
                    {"request_id": request_id, "decision": decision, "turn_id": turn_id, "backend": BACKEND,
                     "answer_sha256": hashlib.sha256(json.dumps(answers, sort_keys=True).encode()).hexdigest()})
            if not self.store.operation_claim(identity, 1):
                raise CodexUnknown("审批已提交或结果未知；不会重复提交")
            receipt = self.workers[wid]["approval_receipts"][request_id]
            receipt.update(decision=decision, operation_id=identity)
            try:
                self.client._write({"id": message["id"], "result": result})
                receipt["response_written"] = True
                self._save()
            except Exception:
                self.store.operation_observe(identity, "UNKNOWN", {"reason": "响应写入或持久确认失败；不重发"})
                raise
        deadline = time.monotonic() + self.timeout
        while True:
            if self._stop_intended(wid) or self.store.mission_stop_requested(self.mission_id):
                with self.lock:
                    receipt['invalidated'] = True
                    self._save()
            fact = self._approval_fact(wid, request_id, turn_id)
            if (fact["status"] != "UNKNOWN" or fact["result"]["status"] == "INVALIDATED"
                    or decision == "answer" and fact["result"]["request_closed"]
                    or time.monotonic() >= deadline or self.client.closed):
                break
            time.sleep(.02)
        self.store.operation_observe(identity, fact["status"], fact["evidence"], fact["result"])
        ok = fact['status'] != 'FAILED' and fact['result']['status'] not in ('INVALIDATED', 'EXPIRED')
        return dict(fact["result"], ok=ok, error=None if ok else fact['result']['reason'], operation_status=fact["status"])

    def close(self):
        if self.client:
            self.client.close()
