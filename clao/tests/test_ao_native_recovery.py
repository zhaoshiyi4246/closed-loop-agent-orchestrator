"""Real daemon restart and receipt boundaries; only external engines are fake."""
import json
from pathlib import Path
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from .test_ao_native import native, native_engine, native_core_python, git


def wait(api, ident, states=("DONE", "FAILED", "HUMAN", "UNKNOWN", "PAUSED", "CANCELLED")):
    for _ in range(300):
        status, data = api("/api/v1/clao/missions/" + ident)
        assert status == 200, data
        if data["mission"]["state"] in states:
            return data["mission"]
        time.sleep(.1)
    pytest.fail("Mission did not settle: " + json.dumps(data, ensure_ascii=False))


def fault(temp, predicate):
    # Only a failing write seam, never fabricated Mission/Session/result data.
    with sqlite3.connect(temp / "isolated-home/native/data/ao.db") as db:
        db.execute("CREATE TRIGGER recovery_receipt_fault BEFORE UPDATE ON clao_missions WHEN " + predicate +
                   " BEGIN SELECT RAISE(ABORT, 'controlled checkpoint receipt loss'); END")


def clear_fault(temp):
    with sqlite3.connect(temp / "isolated-home/native/data/ao.db") as db:
        db.execute("DROP TRIGGER recovery_receipt_fault")


def trace(temp):
    return [json.loads(line) for line in (temp / "external.jsonl").read_text("utf-8").splitlines()]


@pytest.mark.parametrize("boundary,objective,predicate", [
    ("before_gate", "Create accepted output before daemon restart",
     "json_extract(NEW.document,'$.checkpoint.stage')='gate' AND json_extract(OLD.document,'$.checkpoint.stage')='worker'"),
    ("checked_decision", "REPAIR_ONCE persist diagnosis then continue",
     "json_extract(NEW.document,'$.checkpoint.stage')='action' AND json_extract(OLD.document,'$.checkpoint.stage')='decide'"),
    ("frozen_result", "Create accepted output pending final review",
     "json_extract(NEW.document,'$.checkpoint.stage')='verify' AND json_array_length(NEW.document,'$.roleCalls')>COALESCE(json_array_length(OLD.document,'$.roleCalls'),0)"),
    ("checked_verifier", "Reuse completed review before final deterministic check",
     "json_extract(NEW.document,'$.checkpoint.stage')='final' AND json_extract(OLD.document,'$.checkpoint.stage')='verify'"),
    ("unsent_action", "REPAIR_ONCE resume same Session after unsent action",
     "json_extract(NEW.document,'$.operations[#-1].kind')='repair_send'"),
])
def test_restart_continues_confirmed_original_checkpoint(native, boundary, objective, predicate):
    submit, api, nonce, source, base, temp = native
    fault(temp, predicate)
    first = submit(objective, roles={"auditor": {"agent": "opencode", "model": "test/second"},
                                     "planner": {"agent": "opencode", "model": ""},
                                     "verifier": {"agent": "opencode", "model": "test/second"}})
    assert first["state"] == "PAUSED", first
    ident = first["request"]["id"]
    before = trace(temp)
    clear_fault(temp)
    # Modify only future project defaults, not the frozen contract.
    status, result = api("/api/v1/projects/" + first["request"]["projectId"] + "/config",
                         {"config":{"defaultBranch":"main","worker":{"agent":"opencode","agentConfig": {"model": "changed/future"}}}}, method="PUT")
    assert status == 200, result
    nonce = api.restart()  # real Windows process termination and new daemon PID
    restored = api("/api/v1/clao/missions/" + ident)[1]["mission"]
    assert restored["state"] == "PAUSED", restored
    assert restored["recovery"]["canContinue"], restored
    assert restored["sessionId"] == first["sessionId"]
    assert restored["base"] == first["base"] == first["source"]["base"] and restored["roles"] == first["roles"]
    assert git(source, 'rev-parse', 'HEAD') == base

    original_workspace = Path(first['workspace'])
    assert original_workspace.is_dir()
    assert not original_workspace.with_name(original_workspace.name+'.stray').exists()
    assert len([e for e in trace(temp) if e["kind"] == "prompt"]) == len([e for e in before if e["kind"] == "prompt"])
    # Two windows cannot start two scheduling owners.
    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(lambda _: api("/api/v1/clao/missions/"+ident+"/continue", {}, {"X-CLAO-Nonce": nonce}), range(2)))
    assert all(status == 202 for status, _ in replies), replies
    final = wait(api, ident)
    assert final["state"] == "DONE", final
    assert final["request"] == first["request"] and final["roles"] == first["roles"]
    assert final["sessionId"] == first["sessionId"] and final["base"] == first["base"]
    assert len([op for op in final["operations"] if op["kind"] == "spawn"]) == 1
    assert len({c["id"] for c in final["roleCalls"]}) == len(final["roleCalls"])
    for c in first.get("roleCalls", []):
        assert next(x for x in final["roleCalls"] if x["id"] == c["id"])["sessionId"] == c["sessionId"]
    if boundary in ("checked_decision", "unsent_action"):
        assert final["repairs"] == 1 and len(final["decisions"]) == 1
        assert len([op for op in final["operations"] if op["kind"] == "repair_send"]) == 1
    if boundary == "frozen_result":
        assert final["resultHead"] == first["resultHead"]
    assert (Path(final["workspace"]) / "result.txt").read_text() == "accepted\n"
    assert original_workspace.is_dir()
    assert not original_workspace.with_name(original_workspace.name+'.stray').exists()
    revision = final["revision"]
    assert api("/api/v1/clao/missions/"+ident+"/continue", {}, {"X-CLAO-Nonce": nonce})[0] == 409
    assert api("/api/v1/clao/missions/"+ident)[1]["mission"]["revision"] == revision


def test_lost_spawn_ack_reconciles_completed_native_session_without_second_worker(native):
    submit, api, nonce, source, base, temp = native
    fault(temp, "json_extract(NEW.document,'$.operations[0].state')='CONFIRMED_SUCCESS' AND json_extract(OLD.document,'$.operations[0].state')='IN_FLIGHT'")
    first = submit("Complete original Worker before lost local ACK")
    assert first["state"] == "UNKNOWN" and first.get("sessionId"), first
    clear_fault(temp)
    time.sleep(.5)
    nonce = api.restart()
    ident = first["request"]["id"]
    # Native background process reconciliation may settle the exited process.
    for _ in range(100):
        status, data = api("/api/v1/clao/missions/"+ident+"/continue", {}, {"X-CLAO-Nonce": nonce})
        if status == 202:
            break
        time.sleep(.1)
    assert status == 202, data
    final = wait(api, ident)
    assert final["state"] == "DONE", final
    assert final["sessionId"] == first["sessionId"]
    assert len([op for op in final["operations"] if op["kind"] == "spawn"]) == 1


def test_restart_after_executed_repair_ack_loss_does_not_recharge_or_resend(native):
    submit, api, nonce, source, base, temp = native
    fault(temp, "json_extract(NEW.document,'$.operations[#-1].kind')='repair_send' AND json_extract(NEW.document,'$.operations[#-1].state')='CONFIRMED_SUCCESS'")
    first = submit("REPAIR_ONCE keep executed action identity across restart")
    assert first["state"] == "UNKNOWN" and first["repairs"] == 1, first
    clear_fault(temp)
    time.sleep(.5)
    nonce = api.restart()
    ident = first["request"]["id"]
    status, data = api("/api/v1/clao/missions/"+ident+"/continue", {}, {"X-CLAO-Nonce": nonce})
    assert status == 202, data
    final = wait(api, ident)
    assert final["state"] == "DONE", final
    assert final["repairs"] == 1 and len(final["decisions"]) == 1
    assert len([op for op in final["operations"] if op["kind"] == "repair_send"]) == 1
    assert sum(e["kind"] == "prompt" and "处理本次局部修复" in e["text"] for e in trace(temp)) == 1
    assert final["sessionId"] == first["sessionId"]


def test_interrupted_gate_receipt_is_not_treated_as_read_only(native):
    submit, api, nonce, source, base, temp = native
    fault(temp, "json_extract(OLD.document,'$.checkpoint.localState')='IN_FLIGHT' AND json_extract(NEW.document,'$.checkpoint.localState') IS NULL")
    first = submit("Gate ran but local evidence write failed")
    assert first["state"] == "UNKNOWN", first
    clear_fault(temp)
    nonce = api.restart()
    ident = first["request"]["id"]
    before = trace(temp)
    assert api("/api/v1/clao/missions/"+ident+"/continue", {}, {"X-CLAO-Nonce": nonce})[0] == 409
    assert len(trace(temp)) == len(before)
    assert api("/api/v1/clao/missions/"+ident+"/cancel", {}, {"X-CLAO-Nonce": nonce})[0] == 202
    assert wait(api, ident, ("CANCELLED",))["state"] == "CANCELLED"


def test_real_consumers_native_chat_and_mirror_receipts(native):
    submit, api, nonce, source, base, temp = native
    saved = {}
    def on_running(m):
        if saved:
            return
        saved["id"] = m["request"]["id"]
        for role in ("auditor", "planner", "verifier"):
            request = {"id": str(uuid.uuid4()), "target": role, "text": "保留原范围；补充要求 " + role}
            status, data = api("/api/v1/clao/missions/"+saved["id"]+"/directives", request, {"X-CLAO-Nonce": nonce})
            assert status == 202 and data["directive"]["state"] == "received", data
            saved[role] = request
        # Native Chat and dedicated input share exactly the same durable key.
        request = {"text": "REPAIR_ONCE Worker 收到补充，不改变 Gate", "clientMessageId": str(uuid.uuid4())}
        status, data = api("/api/v1/sessions/"+m["sessionId"]+"/conversation/messages", request)
        assert status in (200, 202), data
        saved["worker"] = request
        (temp / "release-config").write_text("release")
    final = submit("HOLD_CONFIG REPAIR_ONCE collect scoped inputs", on_running=on_running)
    assert final["state"] == "DONE", final
    receipts = final["directives"]
    assert len(receipts) == 4
    for d in receipts:
        assert d["state"] == "applied", d
        if d["target"] == "auditor":
            assert {c["mirror"] for c in d["consumers"]} == {True, False}
        if d["target"] == "verifier":
            assert any(c["mirror"] for c in d["consumers"])
        if d["target"].startswith("worker:"):
            assert d["turnId"] and d["sessionId"] == final["sessionId"]
            assert sum(e["kind"] == "prompt" and e["text"] == saved["worker"]["text"] for e in trace(temp)) == 1
    for role in ("auditor", "planner", "verifier"):
        assert any(e["kind"] == "prompt" and saved[role]["text"] in e["text"] for e in trace(temp))
    # Replay the receipt is a read; changing its target cannot reuse the identity.
    req = saved["auditor"]
    url = "/api/v1/clao/missions/"+saved["id"]+"/directives"
    assert api(url, req, {"X-CLAO-Nonce": nonce})[0] == 202
    assert api(url, {**req, "target": "planner"}, {"X-CLAO-Nonce": nonce})[0] == 409
    rejected = api(url, {"id": str(uuid.uuid4()), "target": "worker:"+final["sessionId"], "text": "do not restart"}, {"X-CLAO-Nonce": nonce})
    assert rejected[0] == 409 and rejected[1]["directive"]["state"] == "rejected"


def test_directive_receipt_failure_never_sends_and_unused_role_stays_received(native):
    submit, api, nonce, source, base, temp = native
    saved = {}
    def on_running(m):
        if saved:
            return
        saved["id"] = m["request"]["id"]
        url = "/api/v1/clao/missions/"+saved["id"]+"/directives"
        fault(temp, "json_array_length(NEW.document,'$.directives')>COALESCE(json_array_length(OLD.document,'$.directives'),0)")
        status, _ = api(url, {"id": str(uuid.uuid4()), "target": "worker:"+m["sessionId"], "text": "NEVER_SEND"}, {"X-CLAO-Nonce": nonce})
        assert status == 409
        assert not api("/api/v1/clao/missions/"+saved["id"])[1]["mission"].get("directives")
        clear_fault(temp)
        status, data = api(url, {"id": str(uuid.uuid4()), "target": "auditor", "text": "仅在需要诊断时使用"}, {"X-CLAO-Nonce": nonce})
        assert status == 202, data
        (temp / "release-config").write_text("release")
    # The HOLD_CONFIG substitute intentionally fails its first gate; no repair
    # budget means Auditor is never invoked just to consume this note.
    final = submit("HOLD_CONFIG no extra role calls", repairs=0, on_running=on_running)
    assert final["state"] == "HUMAN", final
    assert final["directives"][0]["state"] == "received"
    assert not final.get("roleCalls")
    assert not any("NEVER_SEND" in e["text"] for e in trace(temp))


def test_worker_delivery_ack_loss_is_reconciled_after_daemon_restart(native):
    submit, api, nonce, source, base, temp = native
    saved = {}
    def on_running(m):
        if saved:
            return
        req = {"id": str(uuid.uuid4()), "target": "worker:"+m["sessionId"], "text": "REPAIR_ONCE durable user delivery"}
        saved.update(req)
        fault(temp, "EXISTS(SELECT 1 FROM json_each(NEW.document,'$.operations') WHERE json_extract(value,'$.kind')='directive_send' AND json_extract(value,'$.state')='CONFIRMED_SUCCESS')")
        status, data = api("/api/v1/clao/missions/"+m["request"]["id"]+"/directives", req, {"X-CLAO-Nonce": nonce})
        assert status == 202, data  # receipt exists; delivery is separately unknown
        (temp / "release-config").write_text("release")
    first = submit("HOLD_CONFIG REPAIR_ONCE directive result lost", on_running=on_running)
    assert first["state"] == "UNKNOWN", first
    time.sleep(1)
    clear_fault(temp)
    nonce = api.restart()
    ident = first["request"]["id"]
    status, data = api("/api/v1/clao/missions/"+ident+"/continue", {}, {"X-CLAO-Nonce": nonce})
    assert status == 202, data
    final = wait(api, ident)
    assert final["state"] == "DONE", final
    d = next(d for d in final["directives"] if d["id"] == saved["id"])
    assert d["state"] == "applied" and d["turnId"]
    assert sum(e["kind"] == "prompt" and e["text"] == saved["text"] for e in trace(temp)) == 1


def test_late_role_note_is_not_claimed_by_an_already_frozen_call(native):
    submit, api, nonce, source, base, temp = native
    fault(temp, "json_extract(NEW.document,'$.operations[#-1].kind')='spawn_auditor'")
    first = submit("REPAIR_ONCE late role note")
    # Role input is already frozen; no external role request has been sent.
    assert first["state"] == "PAUSED" and first["roleCalls"][0]["state"] == "STARTING", first
    clear_fault(temp)
    ident = first["request"]["id"]
    req = {"id": str(uuid.uuid4()), "target": "auditor", "text": "LATE_AUDITOR_NOTE"}
    assert api("/api/v1/clao/missions/"+ident+"/directives", req, {"X-CLAO-Nonce": nonce})[0] == 202
    assert api("/api/v1/clao/missions/"+ident+"/continue", {}, {"X-CLAO-Nonce": nonce})[0] == 202
    final = wait(api, ident)
    assert final["state"] == "DONE", final
    d = final["directives"][0]
    assert d["state"] == "received"
    assert d["consumers"] and all(c["mirror"] and c["role"] == "planner" for c in d["consumers"])
    assert len([c for c in final["roleCalls"] if c["role"] == "auditor"]) == 1


@pytest.mark.parametrize("after_dispatch", [False, True])
def test_replacement_uses_remaining_budget_and_immutable_owner_on_restart(native, after_dispatch):
    submit, api, nonce, source, base, temp = native
    predicate = "json_extract(NEW.document,'$.operations[#-1].kind')='spawn_replacement'"
    if after_dispatch:
        predicate += " AND json_extract(NEW.document,'$.operations[#-1].state')='CONFIRMED_SUCCESS'"
    fault(temp, predicate)
    first = submit("PLAN_REPLACE original replacement identity", replans=1)
    assert first["state"] in ("PAUSED", "UNKNOWN"), first
    assert first["replans"] == 1
    clear_fault(temp)
    time.sleep(.5)
    nonce = api.restart()
    ident = first["request"]["id"]
    status, data = api("/api/v1/clao/missions/"+ident+"/continue", {}, {"X-CLAO-Nonce":nonce})
    assert status == 202, data
    final = wait(api,ident)
    assert final["state"] == "DONE", final
    assert final["replans"] == 1 and final["base"] == base
    assert len([o for o in final["operations"] if o["kind"] == "spawn_replacement"]) == 1
    assert sum(e["kind"] == "prompt" and "replacement-pass" in e["text"] and "执行方案调整" in e["text"] for e in trace(temp)) == 1


def test_changed_decision_input_blocks_recovery_before_dispatch(native):
    submit, api, nonce, source, base, temp = native
    fault(temp,"json_extract(NEW.document,'$.operations[#-1].kind')='repair_send'")
    first=submit("REPAIR_ONCE do not reuse a changed action input")
    assert first["state"] == "PAUSED", first
    clear_fault(temp)
    (Path(first["workspace"])/"result.txt").write_text("unreviewed content\n")
    nonce=api.restart()
    ident=first["request"]["id"]
    status,data=api("/api/v1/clao/missions/"+ident+"/continue",{}, {"X-CLAO-Nonce":nonce})
    assert status == 409, data
    assert not any(e["kind"] == "prompt" and "处理本次局部修复" in e["text"] for e in trace(temp))
    assert api("/api/v1/clao/missions/"+ident+"/cancel",{}, {"X-CLAO-Nonce":nonce})[0] == 202
    assert wait(api,ident,("CANCELLED",))["state"] == "CANCELLED"
