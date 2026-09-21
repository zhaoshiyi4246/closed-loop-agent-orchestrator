"""Native Planner decomposition using the retained MissionPlan contract."""
import json
from pathlib import PurePosixPath

from .mission_contracts import check_role
from .planner_adapter import CodexCliPlannerProvider, PROMPT_DIR
from .verifier import SCHEMA_DIR
from .worktree import scope_violations


def evaluate(request, spec):
    mission = {"mission_id": spec.task_id, "project_id": spec.project_id,
               "objective": spec.objective, "allowed_paths": spec.allowed_paths,
               "forbidden_paths": spec.forbidden_paths,
               "acceptance_criteria": [vars(x) for x in spec.acceptance_criteria],
               "gate_commands": spec.gate_commands, "budgets": {"max_subtasks": 2}}
    if "roleText" not in request:
        return {"ok": True, "rolePrompt": (PROMPT_DIR / "planner-decompose.md").read_text("utf-8") + "\n" + json.dumps({
            "mission": mission, "plan_id": spec.task_id + ":decompose",
            "schema": json.loads((SCHEMA_DIR / "mission-plan.schema.json").read_text("utf-8")),
            "instruction": CodexCliPlannerProvider._decompose_instruction(2) +
            " Dependencies are unsupported. Each subtask must use unchanged original AC IDs/descriptions and a subset of original Gate commands. "
            "Two tasks require disjoint literal files or directory/** scopes and a concrete parallel-benefit strategy; otherwise return one task."
        }, ensure_ascii=False)}
    obj = json.loads(request["roleText"], parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))
    check_role(obj, "mission-plan", mission_id=spec.task_id)
    ok, why = CodexCliPlannerProvider._validate_mission_plan(obj, 2)
    if not ok:
        raise ValueError(why)
    if any(sub.get("dependencies") for sub in obj["subtasks"]):
        raise ValueError("dependent plan unsupported: isolated Workers cannot read unintegrated sibling results")
    if len(obj["subtasks"]) == 1:
        # A no-split decision executes the unchanged original contract.
        return {"ok": True, "roleResult": obj}
    if not obj.get("strategy", "").strip():
        raise ValueError("two tasks require an explicit parallel-benefit strategy")
    expected = {x.id: x.description for x in spec.acceptance_criteria}
    covered, scopes = set(), []
    for sub in obj["subtasks"]:
        acs = sub["acceptance_criteria"]
        if not acs:
            raise ValueError("independent subtask requires acceptance criteria")
        for ac in acs:
            if ac["id"] in covered or expected.get(ac["id"]) != ac["description"]:
                raise ValueError("subtask AC must be disjoint unchanged original criteria")
            covered.add(ac["id"])
        gates = sub.get("gate_commands", [])
        if not gates or any(cmd not in spec.gate_commands for cmd in gates):
            raise ValueError("subtask gates must be explicitly authorized original commands")
        for pattern in sub["allowed_paths"]:
            name = pattern[:-3] if pattern.endswith("/**") else pattern
            parts = PurePosixPath(name).parts
            if not parts or name.startswith("/") or "\\" in name or any(c in name for c in "*?[]:\x00\r\n") or any(p in (".", "..", ".git") for p in parts):
                raise ValueError("parallel scope must be an unambiguous file or directory/**")
            forbidden, outside = scope_violations([name, name + "/__scope_probe__"] if pattern.endswith("/**") else [name],
                allowed_paths=spec.allowed_paths, forbidden_paths=spec.forbidden_paths)
            if forbidden or outside:
                raise ValueError("subtask scope exceeds original mission")
            # Enforce pairwise paths, including case-insensitive Windows aliases.
            key = name.casefold().rstrip("/")
            for previous, owner in scopes:
                if owner != sub["subtask_id"] and (key == previous or key.startswith(previous + "/") or previous.startswith(key + "/")):
                    raise ValueError("parallel subtask scopes overlap")
            scopes.append((key, sub["subtask_id"]))
    if covered != set(expected):
        raise ValueError("subtasks must cover every original AC exactly once")
    return {"ok": True, "roleResult": obj}
