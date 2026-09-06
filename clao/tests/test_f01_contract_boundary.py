"""F01 product regressions: scripted roles, real Windows Git/Gate/SQLite."""
import json
from copy import deepcopy

import pytest

from loopcore.mission_contracts import VerifierResult
from tests.test_final_gate_baseline import _seed_done_mission


class RawResult:
    def __init__(self, payload):
        self.__dict__.update(payload)
        self.payload = payload

    def to_dict(self):
        return deepcopy(self.payload)


class ScriptedVerifier:
    def __init__(self, change=lambda p: None):
        self.change = change
        self.calls = 0

    def verify(self, inp, verify_id):
        self.calls += 1
        payload = dict(verify_id=verify_id,
                       task_id=inp.task_spec.get("task_id", ""),
                       verdict="PASS", summary="scripted review",
                       ac_checks=[dict(ac_id=a["id"], verdict="PASS")
                                  for a in inp.task_spec["acceptance_criteria"]],
                       anti_gaming=[])
        self.change(payload)
        return RawResult(payload)


CASES = [
    ("ac_fail", lambda p: p["ac_checks"][0].update(verdict="FAIL")),
    ("anti_fail", lambda p: p["anti_gaming"].append(dict(ac_id="gaming", verdict="FAIL"))),
    ("missing_ac", lambda p: p["ac_checks"].pop()),
    ("duplicate_ac", lambda p: p["ac_checks"].append(p["ac_checks"][0].copy())),
    ("unknown_ac", lambda p: p["ac_checks"][0].update(ac_id="UNKNOWN")),
    ("unverifiable", lambda p: p["ac_checks"][0].update(verdict="UNVERIFIABLE")),
    ("wrong_verify", lambda p: p.update(verify_id="OTHER")),
    ("missing_verify", lambda p: p.pop("verify_id")),
    ("wrong_mission", lambda p: p.update(mission_id="OTHER")),
    ("wrong_target", lambda p: p.update(task_id="OTHER")),
    ("missing_target", lambda p: p.pop("task_id")),
    ("bad_list", lambda p: p.update(anti_gaming="not a list")),
    ("nested_type", lambda p: p["ac_checks"][0].update(note=[])),
    ("nan", lambda p: p.update(extra={"nested": [float("nan")]})),
    ("infinity", lambda p: p.update(extra={"nested": [float("inf")]})),
]


@pytest.mark.parametrize("name,change", CASES, ids=[c[0] for c in CASES])
def test_final_controller_rejects_protocol_failure(tmp_path, name, change):
    mc, store, _ = _seed_done_mission(tmp_path)
    mc.mission.gate_commands = ['python -c "pass"']
    role = ScriptedVerifier(change)
    mc.verifier = role
    for _ in range(5):
        mc.step()
    assert mc.state == "HUMAN"
    assert "protocol" in mc._read_state()["reason"].lower()
    assert role.calls <= 2
    assert store._conn.execute("SELECT count(*) FROM verifications").fetchone()[0] == 0
    rows = store._conn.execute("SELECT payload_json FROM alerts").fetchall()
    assert any(json.loads(r[0]).get("alert_type") == "PROTOCOL_FAILURE" for r in rows)


def test_final_valid_pass_has_explicit_mission_target(tmp_path):
    mc, store, _ = _seed_done_mission(tmp_path)
    mc.mission.gate_commands = ['python -c "pass"']
    mc.verifier = ScriptedVerifier()
    assert mc.step()["state"] == "MISSION_DONE"
    payload = json.loads(store._conn.execute("SELECT payload_json FROM verifications").fetchone()[0])
    assert payload["task_id"] == mc.mission.mission_id
    assert payload["_validation"]["target_id"] == mc.mission.mission_id


@pytest.mark.parametrize("evidence", ["x" * 13000, "[loopcore] git diff unavailable (git error)\n"], ids=["truncated", "missing"])
def test_final_evidence_gap_blocks_model_pass(tmp_path, monkeypatch, evidence):
    mc, store, _ = _seed_done_mission(tmp_path)
    mc.mission.gate_commands = ['python -c "pass"']
    mc.verifier = ScriptedVerifier()
    monkeypatch.setattr("loopcore.mission.wt.git_diff_text", lambda *a, **k: evidence)
    mc.step()
    assert mc.state == "HUMAN"
    assert mc.verifier.calls == 0
    rows = store._conn.execute("SELECT payload_json FROM alerts").fetchall()
    assert any("original_length" in r[0] and "sha256" in r[0] for r in rows)


def test_final_semantic_fail_is_not_retried_even_with_legacy_summary(tmp_path):
    mc, store, _ = _seed_done_mission(tmp_path)
    mc.mission.gate_commands = ['python -c "pass"']
    mc.verifier = ScriptedVerifier(lambda p: p.update(
        verdict="FAIL", summary="verifier invalid output: other semantic problem"))
    mc.step()
    assert mc.state == "HUMAN"
    assert mc.verifier.calls == 1
    payload = json.loads(store._conn.execute("SELECT payload_json FROM verifications").fetchone()[0])
    assert payload["verdict"] == "FAIL"
    assert payload["summary"] == "verifier invalid output: other semantic problem"


def test_final_large_gate_output_is_preserved_and_blocks_review(tmp_path):
    mc, store, _ = _seed_done_mission(tmp_path)
    mc.mission.gate_commands = ['python -c "print(\'x\' * 14000)"']
    mc.verifier = ScriptedVerifier()
    mc.step()
    assert mc.state == "HUMAN"
    assert mc.verifier.calls == 0
    rows = store._conn.execute("SELECT stdout FROM gate_runs").fetchall()
    assert any(len(r[0]) > 14000 for r in rows)
    alerts = store._conn.execute("SELECT payload_json FROM alerts").fetchall()
    assert any('"TRUNCATED"' in r[0] and '"original_length"' in r[0] for r in alerts)


@pytest.mark.parametrize("kind", ["gate", "scope", "integrity"])
def test_final_deterministic_failure_never_calls_passing_model(tmp_path, kind):
    mc, store, _ = _seed_done_mission(tmp_path)
    mc.mission.gate_commands = ['python -c "pass"']
    if kind == "gate":
        mc.mission.gate_commands = ['python -c "raise SystemExit(1)"']
    elif kind == "scope":
        mc.mission.forbidden_paths.append("math2.py")
    else:
        mc.mission.gate_commands = ['python -c "from pathlib import Path; Path(\'app.py\').write_text(\'changed\')"']
    mc.verifier = ScriptedVerifier()
    mc.step()
    assert mc.state == "HUMAN"
    assert mc.verifier.calls == 0
    assert store._conn.execute("SELECT count(*) FROM verifications").fetchone()[0] == 0
    assert mc._read_state()["reason"]


@pytest.mark.parametrize("kind", ["legacy_pass", "missing_field", "wrong_id", "ac_fail"])
def test_historical_verifier_record_is_revalidated_without_rewriting(tmp_path, monkeypatch, kind):
    from loopcore.event_normalizer import stable_id
    from tests.test_crash_resume import _parked_loop
    loop, store = _parked_loop(tmp_path, monkeypatch, "VERIFIER_PENDING")
    vid = stable_id("VERIFY", loop.task.task_id, loop.task.worker_session_id, length=16)
    payload = dict(verify_id=vid, task_id=loop.task.task_id, verdict="PASS", summary="old result",
                   ac_checks=[dict(ac_id=a.id, verdict="PASS") for a in loop.task.acceptance_criteria],
                   anti_gaming=[])
    if kind == "missing_field":
        payload.pop("ac_checks")
    elif kind == "wrong_id":
        payload["task_id"] = "OTHER"
    elif kind == "ac_fail":
        payload["ac_checks"][0]["verdict"] = "FAIL"
    store.record_verification(vid, loop.task.task_id, payload)
    loop.verifier = ScriptedVerifier()
    loop.step()
    assert loop.state == "HUMAN"
    assert loop.verifier.calls == 0
    assert store.get_verification(vid) == payload
    assert "protocol" in store._conn.execute(
        "SELECT reason FROM state_transitions ORDER BY id DESC LIMIT 1").fetchone()[0]


def test_validated_task_replay_does_not_reinvoke_model(tmp_path, monkeypatch):
    from tests.test_crash_resume import _parked_loop
    loop, store = _parked_loop(tmp_path, monkeypatch, "VERIFIER_PENDING")
    loop.verifier = ScriptedVerifier()
    transition = loop._transition
    def crash(target, *args, **kwargs):
        if target == "DONE":
            raise RuntimeError("simulated crash after record")
        return transition(target, *args, **kwargs)
    monkeypatch.setattr(loop, "_transition", crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        loop._run_verifier()
    monkeypatch.setattr(loop, "_transition", transition)
    loop.step()
    assert loop.state == "DONE"
    assert loop.verifier.calls == 1
    assert store._conn.execute("SELECT count(*) FROM verifications").fetchone()[0] == 1


@pytest.mark.parametrize("verdict", ["PASS", "FAIL"])
def test_final_crash_after_result_replays_validated_result(tmp_path, monkeypatch, verdict):
    mc, store, _ = _seed_done_mission(tmp_path)
    mc.mission.gate_commands = ['python -c "pass"']
    mc.verifier = ScriptedVerifier(lambda p: p.update(verdict=verdict))
    set_state = mc._set_state
    def crash(state, reason):
        if state in ("MISSION_DONE", "HUMAN"):
            raise RuntimeError("simulated crash after final record")
        return set_state(state, reason)
    monkeypatch.setattr(mc, "_set_state", crash)
    first = mc.step()
    assert "simulated crash" in first["error"]
    monkeypatch.setattr(mc, "_set_state", set_state)
    second = mc.step()
    assert second["state"] == ("MISSION_DONE" if verdict == "PASS" else "HUMAN")
    assert mc.verifier.calls == 1
    assert store.latest_verification(mc.mission.mission_id)["verdict"] == verdict


@pytest.mark.parametrize("role", ["verifier", "auditor", "planner"])
def test_protocol_retry_exhaustion_at_controller_has_no_semantic_record(tmp_path, monkeypatch, role):
    from tests.test_crash_resume import _parked_loop
    from loopcore.auditor import CodexCliAuditorProvider, FakeAuditorProvider, EvidenceBundle
    from loopcore.verifier import CodexCliVerifierProvider
    from loopcore.planner_adapter import CodexCliPlannerProvider
    target = dict(verifier="VERIFIER_PENDING", auditor="AUDIT_PENDING", planner="PLANNER_PENDING")[role]
    loop, store = _parked_loop(tmp_path, monkeypatch, target)
    provider = dict(verifier=CodexCliVerifierProvider, auditor=CodexCliAuditorProvider,
                    planner=CodexCliPlannerProvider)[role]()
    calls = []
    monkeypatch.setattr(provider, "_call", lambda *a, **k: calls.append(1) or {})
    setattr(loop, role, provider)
    if role == "planner":
        audit = FakeAuditorProvider().audit(EvidenceBundle(loop.task.to_dict(), None), "AUDIT-TEST")
        store.record_audit(audit.audit_id, loop.task.task_id, audit.to_dict())
    for _ in range(8):
        loop.step()
    assert loop.state == "HUMAN"
    assert len(calls) == 2
    table = dict(verifier="verifications", auditor="audits", planner="planner_actions")[role]
    assert store._conn.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
    alerts = [json.loads(r[0]) for r in store._conn.execute("SELECT payload_json FROM alerts")]
    assert any(a.get("alert_type") == "PROTOCOL_FAILURE" and a["attempts"] == 2 for a in alerts)


def test_auditor_pass_cannot_override_failed_gate_or_recurse(tmp_path, monkeypatch):
    from tests.test_crash_resume import _parked_loop
    from loopcore.mission_contracts import AuditResult, AuditEvidence
    loop, store = _parked_loop(tmp_path, monkeypatch, "AUDIT_PENDING")
    loop.task.gate_commands = ['python -c "raise SystemExit(1)"']
    calls = []
    def false_pass(bundle, audit_id):
        calls.append(1)
        return AuditResult(audit_id, loop.task.task_id, "PASS",
                           [AuditEvidence("claim", "all good")], "all good", 1.0)
    loop.auditor.audit = false_pass
    loop.step()
    assert loop.state == "HUMAN"
    assert len(calls) == 1
    assert store._conn.execute("SELECT count(*) FROM audits").fetchone()[0] == 0
    assert store._conn.execute("SELECT count(*) FROM planner_actions").fetchone()[0] == 0


def test_mixed_protocol_transport_failures_have_explicit_six_call_ceiling(tmp_path, monkeypatch):
    from tests.test_crash_resume import _parked_loop
    from loopcore.codex_cli import CodexCliError
    from loopcore.verifier import CodexCliVerifierProvider
    loop, store = _parked_loop(tmp_path, monkeypatch, "VERIFIER_PENDING")
    provider = CodexCliVerifierProvider()
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        if len(calls) % 2:
            return {}
        raise CodexCliError("offline transport failure")
    monkeypatch.setattr(provider, "_call", fail)
    loop.verifier = provider
    for _ in range(8):
        loop.step()
    assert loop.state == "HUMAN"
    assert len(calls) == 6
    assert store._conn.execute("SELECT count(*) FROM verifications").fetchone()[0] == 0
    alerts = [json.loads(r[0]) for r in store._conn.execute("SELECT payload_json FROM alerts")]
    assert any(a.get("protocol_errors") for a in alerts)


@pytest.mark.parametrize("target", ["task", "mission"])
@pytest.mark.parametrize("raw", ["{broken", "null", "[]"])
def test_corrupt_saved_review_is_not_treated_as_absent(tmp_path, monkeypatch, target, raw):
    from loopcore.event_normalizer import stable_id
    from tests.test_crash_resume import _parked_loop
    if target == "task":
        controller, store = _parked_loop(tmp_path, monkeypatch, "VERIFIER_PENDING")
        target_id = controller.task.task_id
        vid = stable_id("VERIFY", target_id, controller.task.worker_session_id, length=16)
    else:
        controller, store, _ = _seed_done_mission(tmp_path)
        controller.mission.gate_commands = ['python -c "pass"']
        target_id, vid = controller.mission.mission_id, "OLD-REVIEW"
    role = ScriptedVerifier()
    controller.verifier = role
    store.record_verification(vid, target_id, {})
    store._conn.execute("UPDATE verifications SET payload_json=? WHERE verify_id=?", (raw, vid))
    store._conn.commit()
    controller.step()
    assert controller.state == "HUMAN"
    assert role.calls == 0
    assert store._conn.execute("SELECT payload_json FROM verifications").fetchone()[0] == raw
