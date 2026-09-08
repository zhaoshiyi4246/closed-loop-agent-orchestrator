"""Controlled JSONL process, using the public Codex 0.150.1 method shapes.

No model, network, AO, shell commands, login or environment modification.
Only edits the thread/start cwd supplied by the isolated product test.
"""
import json
import os
from pathlib import Path
import sys
import time

# Codex stdio frames are UTF-8, independent of the Windows console code page.
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

if "--version" in sys.argv:
    print("codex-cli 0.150.1")
    raise SystemExit(0)

scenario = os.environ.get("CLAO_TEST_CODEX_SCENARIO", "normal")
trace = Path(os.environ["CLAO_TEST_CODEX_TRACE"])
workers = {}
pending = {}
serial = 0


def output(message):
    print(json.dumps(message), flush=True)


def reply(identity, result):
    output({"id": identity, "result": result})


def notify(method, params):
    if method == 'item/started':params['startedAtMs'] = int(time.time()*1000)
    if method == 'item/completed':params['completedAtMs'] = int(time.time()*1000)
    output({"method": method, "params": params})


def ended(w, status="completed"):
    w["status"] = status
    notify("turn/completed", {"threadId": w["id"], "turn": {
        "id": w["turn"], "status": status, "items": [], "error": {"message": "controlled failure"} if status == "failed" else None}})


def approval(w, item, kind):
    global serial
    serial += 1
    rid = 1000 + serial
    params = {"threadId": w["id"], "turnId": w["turn"], "itemId": item["id"], "startedAtMs": int(time.time()*1000)}
    if kind == "commandExecution":
        params.update(command=item["command"], cwd=w["cwd"], kind="command")
    notify("item/started", {"threadId": w["id"], "turnId": w["turn"], "item": item})
    pending[rid] = (w, item, kind)
    output({"id": rid, "method": "item/" + kind + "/requestApproval", "params": params})


for line in sys.stdin:
    message = json.loads(line)
    method, params, identity = message.get("method"), message.get("params", {}), message.get("id")
    with trace.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"method": method, "id": identity}) + "\n")
    if method == "initialize":
        reply(identity, {"userAgent": "codex-cli/0.150.1", "platformFamily": "windows", "platformOs": "windows", "codexHome": str(trace.parent)})
    elif method == "initialized":
        assert "params" not in message
    elif method == "account/read":
        assert params == {"refreshToken": False}
        reply(identity, {"account": None if scenario == "no_login" else {"type": "chatgpt", "email": "fixture@example.invalid", "planType": "unknown"}, "requiresOpenaiAuth": True})
    elif method == "windowsSandbox/readiness":
        assert params is None
        reply(identity, {"status": "notConfigured" if scenario == "no_sandbox" else "ready"})
    elif method == "config/read":
        assert params['includeLayers'] is False
        reply(identity, {"config": {"mcp_servers": {"unrelated": {"command": "never-launch", "env": {"SECRET": "never-persist"}}}}, "layers": None, "origins": {}})
    elif method in ("thread/start", "thread/resume"):
        assert params["sandbox"] == "read-only" and params["approvalPolicy"] == "untrusted" and params["approvalsReviewer"] == "user"
        assert params['config']=={'mcp_servers':{'unrelated':{'enabled':False}}}
        wid = params.get("threadId") or "01900000-0000-7000-8000-" + str(len(workers)+1).zfill(12)
        workers[wid] = {"id": wid, "cwd": params["cwd"], "status": "idle"}
        if scenario != "spawn_ack_lost":
            thread = {"id": wid, "cliVersion": "0.150.1", "createdAt": int(time.time()), "updatedAt": int(time.time()),
                      "cwd": params['cwd'], "ephemeral": False, "modelProvider": "openai", "preview": "", "projectId": None,
                      "sessionId": wid, "source": "appServer", "status": {"type": "idle"}, "turns": []}
            reply(identity, {"thread": thread, "model": "resolved-test-model", "modelProvider": "openai",
                             "cwd": params["cwd"], "sandbox": {"type": "readOnly", "networkAccess": False},
                             "approvalPolicy": "untrusted", "approvalsReviewer": "user"})
    elif method == "turn/start":
        w = workers[params["threadId"]]
        assert params["input"][0]["type"] == "text" and params["input"][0]["text"]
        serial += 1
        w.update(turn="turn-" + str(serial), status="inProgress")
        notify("turn/started", {"threadId": w["id"], "turn": {"id": w["turn"], "status": "inProgress", "items": []}})
        reply(identity, {"turn": {"id": w["turn"], "status": "inProgress", "items": []}})
        if scenario == "reroute":
            notify("model/rerouted", {"threadId": w["id"], "turnId": w["turn"], "fromModel": "resolved-test-model", "toModel": "rerouted-test-model", "reason": "highRiskCyberActivity"})
        if scenario in ("hold", "send_ack_lost", "kill_ack_lost", "kill_live", "disconnect", "background"):
            if scenario == "disconnect":
                raise SystemExit(0)
            if scenario == "background":
                notify("item/started", {"threadId": w["id"], "turnId": w["turn"], "item": {
                    "type": "commandExecution", "id": "background", "command": "long task", "cwd": w["cwd"], "commandActions": [], "status": "inProgress"}})
                ended(w)
            continue
        if scenario == "error_then_completed":
            notify("error", {"threadId": w["id"], "turnId": w["turn"], "willRetry": False, "error": {"message": "controlled terminal error"}})
            ended(w)
            continue
        if scenario == "worker_failed":
            ended(w, "failed")
            continue
        if scenario == "outside":
            (Path(w["cwd"]) / "forbidden.txt").write_text("scope failure")
            ended(w)
            continue
        if scenario == "manual":
            approval(w, {"type": "commandExecution", "id": "manual", "status": "inProgress", "command": "git reset --hard", "cwd": w["cwd"], "commandActions": []}, "commandExecution")
            continue
        if scenario == "question":
            serial += 1
            pending[1000 + serial] = (w, {}, "question")
            output({"id": 1000 + serial, "method": "item/tool/requestUserInput", "params": {
                "threadId": w["id"], "turnId": w["turn"], "itemId": "q", "isBlocking": True,
                "questions": [{"id": "choice", "header": "范围", "question": "是否保留中文 <tag>？", "options": None}]}})
            continue
        item = {"type": "fileChange", "id": "edit", "status": "inProgress", "changes": [
            {"path": str(Path(w["cwd"]) / "app.py"), "kind": {"type": "update", "move_path": None}, "diff": "+x=2"}]}
        approval(w, item, "fileChange")
    elif method == "turn/steer":
        w = workers[params["threadId"]]
        assert params["expectedTurnId"] == w["turn"]
        if scenario != "send_ack_lost":
            reply(identity, {"turnId": w["turn"]})
    elif method == "turn/interrupt":
        w = workers[params["threadId"]]
        assert params["turnId"] == w["turn"]
        if scenario != "kill_live" and scenario != "background":
            ended(w, "interrupted")
            for key, (pw, _, _) in list(pending.items()):
                if pw == w:
                    pending.pop(key)
                    notify("serverRequest/resolved", {"threadId": w["id"], "requestId": key})
        if scenario != "kill_ack_lost":
            reply(identity, {})
    elif method is None and identity in pending:
        w, item, kind = pending.pop(identity)
        result = message["result"]
        notify("serverRequest/resolved", {"threadId": w["id"], "requestId": identity})
        if kind == "question":
            assert result["answers"]["choice"]["answers"]
            approval(w, {"type": "fileChange", "id": "after-question", "status": "inProgress", "changes": [
                {"path": str(Path(w["cwd"]) / "app.py"), "kind": {"type": "update", "move_path": None}, "diff": "+x=2"}]}, "fileChange")
            continue
        accepted = result["decision"] == "accept"
        assert result["decision"] in ("accept", "decline")
        if accepted and kind == "fileChange":
            (Path(w["cwd"]) / "app.py").write_text("x=2\n", encoding="utf-8")
        item["status"] = "completed" if accepted else "declined"
        notify("item/completed", {"threadId": w["id"], "turnId": w["turn"], "item": item})
        ended(w, "completed" if accepted else "failed")
    else:
        output({"id": identity, "error": {"code": -32601, "message": "unsupported test protocol method"}})
