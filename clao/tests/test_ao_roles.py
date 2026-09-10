"""Native bridge reuses the retained contracts; only external calls are elsewhere."""
import json
import pytest
from loopcore.ao_roles import evaluate
from loopcore.mission_contracts import TaskSpec
from loopcore.structured import ProtocolError


def inputs(role):
    spec = TaskSpec.from_dict({"task_id":"mission-1","project_id":"project-1","objective":"keep source safe", "allowed_paths":["**"],"forbidden_paths":["private/**"],"acceptance_criteria":[{"id":"AC1","description":"pass Gate"}],"gate_commands":["python check.py"]})
    audit = {"audit_id":"audit-1","task_id":"mission-1","decision":"LOCAL_FIX","diagnosis":"Gate failed","confidence":.8,"failed_criteria":[],"evidence":[{"type":"test_failure","summary":"actual output"}]}
    context={"id":"audit-1" if role=="auditor" else "plan-1","auditId":"audit-1","audit":audit,"workerId":"worker-1","incidentId":"incident-1","proof":{"records":[]},"workerStatus":{"stopped":True},"history":{},"remainingActions":1,"remainingReplans":0}
    result = audit.copy() if role=="auditor" else {"action_id":"plan-1","task_id":"mission-1","action":"SEND_LOCAL_FIX","target_session_id":"worker-1","message":"repair", "reason":"actual diagnosis"}
    return spec,{"role":role,"roleContext":context,"base":"base"},result


@pytest.mark.parametrize("role,patch",[("auditor",{"task_id":"other"}),("auditor",{"audit_id":"other"}),("auditor",{"failed_criteria":["unknown"]}),("auditor",{"decision":"PASS","failed_criteria":["AC1"]}),("auditor",{"evidence":[]}),("planner",{"target_session_id":"old-worker"}),("planner",{"action":"OTHER"}),("planner",{"action":"REPLAN_SPAWN","replacement_task_spec":{"objective":"plan","allowed_paths":["**"]}}),("planner",{"message":""})])
def test_native_role_contract_refuses_unexecutable_results(tmp_path,role,patch):
    spec,request,result=inputs(role);result.update(patch);request["roleText"]=json.dumps(result)
    with pytest.raises((ProtocolError,ValueError)):
        evaluate(request,spec,tmp_path)


@pytest.mark.parametrize("text",["", "not JSON", "```json {} ```",'{"action":NaN}'])
def test_native_does_not_repair_json_or_parse_thoughts(tmp_path,text):
    spec,request,result=inputs("planner");request["roleText"]=text
    with pytest.raises((ProtocolError,ValueError)):evaluate(request,spec,tmp_path)


def test_native_human_is_valid_and_cannot_be_overridden(tmp_path):
    spec,request,result=inputs("planner");request["roleContext"]["audit"]["decision"]="HUMAN"
    request["roleText"]=json.dumps(result)
    with pytest.raises(ProtocolError):evaluate(request,spec,tmp_path)
    result["action"]="HUMAN";request["roleText"]=json.dumps(result)
    assert evaluate(request,spec,tmp_path)["roleResult"]["action"]=="HUMAN"


def test_native_full_evidence_bound_does_not_silently_truncate(tmp_path,monkeypatch):
    from loopcore import ao_roles
    spec,request,_=inputs("auditor")
    monkeypatch.setattr(ao_roles.wt,"git_diff_text",lambda *a,**k:"x"*4001)
    with pytest.raises(ProtocolError):evaluate(request,spec,tmp_path)
