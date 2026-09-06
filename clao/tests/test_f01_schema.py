"""Production role boundaries and installation failures, without live calls."""
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from loopcore import mission_contracts as contracts
from loopcore.structured import (ContractConfigurationError, ProtocolError,
                                check_schema, parse_json)
from loopcore.auditor import CodexCliAuditorProvider
from loopcore.verifier import CodexCliVerifierProvider
from loopcore.planner_adapter import CodexCliPlannerProvider
from tests.test_codex_auditor import _bundle, _result as _audit_result
from tests.test_codex_verifier import _input, _result
from tests.test_codex_planner import _action, _audit, _plan, MISSION


@pytest.mark.parametrize("raw", ["{bad", "[]", '{"x":NaN}', '{"x":[Infinity]}',
                                  '{"x":{"y":-Infinity}}', '{"x":1e999}',
                                  '{"x":1,"x":2}'])
def test_shared_runner_rejects_invalid_or_nonfinite_json(tmp_path, monkeypatch, raw):
    from loopcore.codex_cli import run_codex_json
    from types import SimpleNamespace
    schema = tmp_path / "schema.json"
    schema.write_text('{"type":"object","properties":{}}', encoding="utf-8")
    def fake_run(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text(raw, encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ProtocolError):
        run_codex_json("offline prompt", schema)


def test_missing_dependency_stops_import_with_bootstrap_instruction():
    result = subprocess.run([sys.executable, "-c",
        "import sys; sys.modules['jsonschema']=None; import loopcore.mission_contracts"],
        capture_output=True, text=True)
    assert result.returncode != 0
    assert "requires jsonschema; rerun bootstrap.ps1" in result.stderr


def test_invalid_schema_is_configuration_error_before_any_role_call(tmp_path, monkeypatch):
    from loopcore.codex_cli import run_codex_json
    schema = tmp_path / "broken.schema.json"
    schema.write_text('{"type":"object","properties":{"x":{"type":"broken"}}}')
    def forbidden(*args, **kwargs):
        pytest.fail("invalid schema must not invoke model")
    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(ContractConfigurationError, match="Invalid local JSON Schema"):
        run_codex_json("unused", schema)


@pytest.mark.parametrize("schema,obj", [
    ("audit-result", dict(audit_id="A", task_id="T", decision="PASS", evidence=[42], diagnosis="ok", confidence=.5)),
    ("audit-result", dict(audit_id="A", task_id="T", decision="PASS", evidence=[dict(type="x", summary="y")], diagnosis="ok", confidence=1.1)),
    ("planner-action", dict(action_id="A", task_id="T", action="HUMAN", reason=[])),
    ("mission-plan", dict(mission_id="M", subtasks=[dict(subtask_id="S", objective="x", allowed_paths=[42], acceptance_criteria=[])])),
])
def test_complete_schema_checks_nested_types_and_numeric_bounds(schema, obj):
    assert contracts._validate(obj, schema)[0] is False


@pytest.mark.parametrize("role", ["verifier", "auditor", "planner", "decompose"])
@pytest.mark.parametrize("corruption", ["missing_request", "wrong_request", "missing_target", "wrong_target", "nan"])
def test_every_production_provider_rejects_bad_correlation_and_nested_numbers(monkeypatch, role, corruption):
    if role == "verifier":
        provider = CodexCliVerifierProvider()
        obj, request, target = _result(), "verify_id", "task_id"
        invoke = lambda: provider.verify(_input(), obj_original["verify_id"])
    elif role == "auditor":
        provider = CodexCliAuditorProvider()
        obj, request, target = _audit_result(), "audit_id", "task_id"
        invoke = lambda: provider.audit(_bundle(), obj_original["audit_id"])
    elif role == "planner":
        provider = CodexCliPlannerProvider()
        obj, request, target = _action(), "action_id", "task_id"
        invoke = lambda: provider.plan(_audit(), {"task_id": "TASK-1"}, "ACT-1")
    else:
        provider = CodexCliPlannerProvider()
        # Existing MissionPlan returns mission_id as its sole correlation field.
        obj, request, target = _plan(), "mission_id", "mission_id"
        invoke = lambda: provider.plan_decompose(MISSION, "DECOMP-M-CODEX")
    obj_original = deepcopy(obj)
    if corruption == "nan":
        obj["extra"] = {"nested": [float("nan")]}
    elif corruption.startswith("missing"):
        obj.pop(request if corruption.endswith("request") else target)
    else:
        obj[request if corruption.endswith("request") else target] = "OTHER"
    calls = []
    monkeypatch.setattr(provider, "_call_decompose" if role == "decompose" else "_call",
                        lambda *a, **k: calls.append(1) or deepcopy(obj))
    with pytest.raises(ProtocolError):
        invoke()
    assert len(calls) == 2


def test_actual_verifier_prompt_contains_source_length_digest_and_no_second_slice(monkeypatch):
    from loopcore import verifier
    inp = _input()
    inp.diff = "HEAD\n" + "x" * 5800 + "\nTAIL"
    calls = []
    monkeypatch.setattr(verifier, "run_codex_json", lambda **kwargs: calls.append(kwargs) or _result())
    CodexCliVerifierProvider().verify(inp, "VERIFY-CODEX")
    body = json.loads(calls[0]["prompt"].split("# VerifierInput\n", 1)[1])
    part = body["verifier_input"]["evidence"]["git_diff"]
    assert part["content"] == inp.diff
    assert part["original_length"] == len(inp.diff)
    assert len(part["sha256"]) == 64
    assert part["truncated"] is False and part["missing"] is False


def test_successful_protocol_retry_keeps_error_category_and_digest(monkeypatch):
    provider = CodexCliVerifierProvider()
    values = iter([{}, _result()])
    monkeypatch.setattr(provider, "_call", lambda *a, **k: next(values))
    result = provider.verify(_input(), "VERIFY-CODEX").to_dict()
    assert result["verdict"] == "PASS"
    error, = result["_protocol_errors"]
    assert error["category"] == "SCHEMA"
    assert error["evidence"]["request"]["verify_id"] == "VERIFY-CODEX"
    assert len(error["evidence"]["response"]["sha256"]) == 64
