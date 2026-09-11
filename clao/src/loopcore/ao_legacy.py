"""Explicit legacy import and semantic transport bridge for the native daemon.

No discovery, credential migration, Controller or database writes. Only the
selected legacy files are read; the daemon stores the returned safe projection
in its existing SQLite. Credential references are resolved solely at execution.
"""
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

import yaml

from .model_profiles import validate_profiles, SERVICE, KIMI_SERVICE, LABELS
from .state_store import StateStore
from .structured import ProtocolError


class ImportError(ValueError):
    pass


def _text(value, limit=8000):
    from .results import _sensitive, ResultError
    if not isinstance(value, str):
        return None
    try:
        _sensitive(value)
    except ResultError:
        return "[内容含禁止材料，未导入]"
    return value[:limit] + (" [显示截断]" if len(value) > limit else "")


def _identity(origin, kind, key):
    return "legacy-" + hashlib.sha256((os.path.normcase(str(origin)) + "\0" + kind + "\0" + key).encode()).hexdigest()[:40]


def _read_file(path, limit):
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ImportError("请选择实际存在的本地文件；不读取链接目标")
    before = path.stat()
    if before.st_size > limit:
        raise ImportError("所选文件超过导入大小限制")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    after = path.stat()
    if before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size or len(raw) > limit:
        raise ImportError("导入期间来源发生变化，请在旧任务停止后重试")
    return raw


def _entry(origin, kind, key, value):
    return dict(id=_identity(origin, kind, key), kind=kind, document=value)


def import_config(path):
    path = Path(path)
    if path.suffix.lower() not in (".yaml", ".yml", ".json"):
        raise ImportError("配置导入只支持旧 CLAO YAML / JSON 文件")
    raw = _read_file(path, 1_048_576)
    try:
        cfg = yaml.safe_load(raw)
    except (ValueError, yaml.YAMLError, UnicodeError):
        raise ImportError("配置格式不可读取；未回显文件内容") from None
    if not isinstance(cfg, dict) or not any(k in cfg for k in ("model_profiles", "roles", "worker", "gate", "budgets")):
        raise ImportError("所选文件不是受支持的旧 CLAO 配置")
    rows, issues, connections, ambiguous = [], [], {}, set()
    profiles = cfg.get("model_profiles", [])
    if not isinstance(profiles, list) or len(profiles) > 12:
        raise ImportError("旧连接列表格式无效或超过 12 项")
    for index, profile in enumerate(profiles):
        # Do not persist unknown fields (including pasted tokens), even for an
        # incompatible profile. Such a row remains visible as needing reconnect.
        item = profile if isinstance(profile, dict) else {}
        name = _text(item.get("id"), 100) or "连接 " + str(index + 1)
        service = item.get("service") if item.get("service") in LABELS else "unsupported"
        model = item.get("model")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", model):
            model = "unknown"
        value = dict(name=name, service=service, model=model, billing="standard_api",
                     roles=["planner", "auditor", "verifier"], compatible=False,
                     reason="原配置不能安全映射，请重新连接；未更改原凭据")
        try:
            validate_profiles([profile])
        except (ValueError, TypeError, KeyError):
            issues.append(name + "：不支持的服务、参数或凭据引用；保留重新连接提示")
        else:
            value.update(profile=copy.deepcopy(profile), endpoint=profile["endpoint"],
                         compatible=True, reason="已导入标准 API 配置；未检测或迁移系统凭据，未测试连接")
        entry = _entry(path, "connection", service + ":" + name, value)
        if name in connections:
            ambiguous.add(name)
            issues.append(name + "：旧配置使用了重复连接身份；按服务分开保留，但不猜测角色指向")
        connections[name] = entry["id"]
        rows.append(entry)
    # Only map inputs that have actual native consumers. Never copy old globals,
    # AO endpoint, runtime paths, credentials, or arbitrary config sections.
    values, warnings = {}, []
    gate = cfg.get("gate", {})
    budgets = cfg.get("budgets", {})
    if isinstance(gate, dict) and "timeout_seconds" in gate:
        timeout = gate["timeout_seconds"]
        if type(timeout) in (int, float) and 1 <= timeout <= 600:
            values["gateTimeout"] = timeout
        else:
            warnings.append("原 Gate 超时不在原生支持的 1–600 秒范围，未应用")
    if isinstance(budgets, dict):
        count = budgets.get("max_subtasks")
        if type(count) is int and count in (1, 2):
            values["maxTasks"] = count
        sub = budgets.get("subtask_budgets", {})
        if isinstance(sub, dict):
            fixes, replans = sub.get("max_local_fixes"), sub.get("max_replans")
            if type(fixes) is int and type(replans) is int and 0 <= fixes + replans <= 3:
                values.update(maxRepairs=fixes + replans, maxReplans=replans)
            elif fixes is not None or replans is not None:
                warnings.append("旧修复预算不符合原生总动作 0–3 次边界，未应用")
    roles = cfg.get("roles", {})
    mapped = {}
    if isinstance(roles, dict):
        for role in ("planner", "auditor", "verifier"):
            choice = roles.get(role, {})
            if not isinstance(choice, dict):
                continue
            profile = choice.get("profile", "codex")
            if profile in ambiguous:
                warnings.append(role + " 原连接身份不唯一，未应用")
            elif profile in connections:
                mapped[role] = {"connectionId": connections[profile]}
            elif profile == "codex":
                model = choice.get("model")
                if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", model):
                    mapped[role] = {"agent": "codex", "model": model}
            else:
                warnings.append(role + " 原连接缺失，未应用")
    worker = cfg.get("worker", {})
    if isinstance(worker, dict):
        model = worker.get("model")
        if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", model):
            values.update(agent="codex", model=model)
    if mapped:
        values["roles"] = mapped
    if profiles:
        warnings.append("连接的 max_attempts / retry_delay_seconds 仅保留为旧来源参数；原生语义调用每次发送一次，不叠加旧自动重试，未知结果不重发")
    warnings.append("只应用列出的新任务字段；旧 AO/轮询/诊断及其他运行设置不覆盖原生默认。已有任务不变")
    # Defaults are immutable versions of the safe, actually applicable inputs.
    # A later role binding or budget can coexist with the earlier configuration;
    # connection identities above remain stable and reject in-place changes.
    projection = dict(values=values, warnings=warnings)
    revision = hashlib.sha256(json.dumps(projection, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode("utf-8")).hexdigest()
    rows.append(_entry(path, "configuration", "defaults:" + revision,
                       dict(name=path.name + " · " + revision[:8], revision=revision,
                            sourceName=path.name, **projection)))
    return rows, issues


@contextmanager
def _database_snapshot(path):
    # A read-only SQLite connection may still touch a WAL shared-memory file.
    # Copy only the explicitly selected DB+WAL into a temporary private directory
    # first, checking a stable source signature. Never open the original SQLite.
    def signature():
        return [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in
                (path, Path(str(path) + "-wal")) if p.exists()]
    before = signature()
    with tempfile.TemporaryDirectory(prefix="clao-legacy-read-") as folder:
        target = Path(folder) / "state.db"
        for source in (path, Path(str(path) + "-wal")):
            if source.exists():
                suffix = "-wal" if source != path else ""
                Path(str(target) + suffix).write_bytes(_read_file(source, 128 * 1024 * 1024))
        if before != signature():
            raise ImportError("旧数据库正在变化，请停止旧任务后导入")
        conn = sqlite3.connect(str(target))
        try:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            yield conn
        finally:
            conn.close()


def _safe_tree(value, depth=0):
    if depth > 8:
        return "[历史字段过深，未导入]"
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, list):
        return [_safe_tree(v, depth + 1) for v in value[:100]]
    if isinstance(value, dict):
        denied = re.compile(r"prompt|messages|conversation|api.?key|token|password|authorization|credential|environment|^cwd$", re.I)
        return {k: _safe_tree(v, depth + 1) for k, v in value.items() if isinstance(k, str) and not denied.search(k)}
    return value if value is None or type(value) in (bool, int, float) else None


def _history_file(path):
    if path.name != "state.db":
        raise ImportError("请选择旧 runtime 目录或其中的 state.db")
    _read_file(path, 128 * 1024 * 1024)
    rows = []
    with _database_snapshot(path) as conn:
        try:
            missions = conn.execute("SELECT mission_id,payload_json,recorded_at FROM missions ORDER BY mission_id LIMIT 501").fetchall()
        except sqlite3.Error:
            raise ImportError("旧 missions 表读取失败；没有导入空成功记录") from None
        if len(missions) > 500:
            raise ImportError("单个数据库超过 500 个任务，请选择具体 runtime/state.db")
        for mid, raw, at in missions:
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict) or not isinstance(mid, str):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ImportError("旧任务记录不可读取；未猜测历史结论") from None
            mission = payload.get("mission", {})
            if not isinstance(mission, dict):
                mission = {}
            snap = payload.get("effective_config")
            source = payload.get("source") or mission.get("source") or {}
            value = dict(originalId=_text(mid, 200), sourceVersion="CLAO legacy / " +
                         ("config schema " + str(snap.get("schema_version")) if isinstance(snap, dict) else "historical version unknown"),
                         objective=_text(mission.get("objective")) or "历史目标未提供",
                         state=_text(payload.get("state"), 80) or "unknown", reason=_text(payload.get("reason")),
                         project=_text(mission.get("project_id"), 200), recordedAt=_text(at, 100),
                         criteria=_safe_tree(mission.get("acceptance_criteria", [])),
                         gateCommands=_safe_tree(mission.get("gate_commands", [])),
                         backend=_text(mission.get("execution_backend"), 100),
                         source={k: _text(source.get(k), 300) for k in ("source_commit", "source_kind", "backend", "content_digest") if isinstance(source, dict) and k in source},
                         resultHead=_text(payload.get("integration_head"), 100),
                         configurationRevision=_text(snap.get("revision"), 100) if isinstance(snap, dict) else None,
                         readOnly=True, canContinue=False,
                         limitations=["旧任务只读导入，不补造原生 Session、配置或恢复事实", "原始数据库、Prompt、会话和凭据未复制到当前数据库"])
            task_ids = {mid}
            try:
                for (task_raw,) in conn.execute("SELECT spec_json FROM tasks"):
                    task = json.loads(task_raw)
                    if task.get("subtask_of") == mid:
                        task_ids.add(task.get("task_id"))
            except (sqlite3.Error, ValueError, TypeError, AttributeError):
                value["limitations"].append("子任务关联读取失败")
            gates = StateStore.query_gate_runs(conn, limit=1000)
            if gates["status"] == "read_error":
                value["gates"] = {"status": "read_error", "records": [], "error": "旧 Gate 记录不可读取"}
            else:
                selected = [g for g in gates["records"] if g.get("task_id") in task_ids]
                # Old output and logs can include arbitrary model material. Keep
                # actual command/assessment/timing; never synthesize PASS.
                keep = ("id", "task_id", "command", "exit_code", "started_at", "ended_at", "phase", "command_status", "integrity", "scope", "overall", "historical_fields_missing")
                value["gates"] = dict(status="ok" if selected else "no_records", records=[_safe_tree({k: g[k] for k in keep if k in g}) for g in selected])
            try:
                verification = []
                for task_id, verify_raw in conn.execute("SELECT task_id,payload_json FROM verifications ORDER BY rowid"):
                    if task_id in task_ids:
                        item = json.loads(verify_raw)
                        verification.append(_safe_tree({k: item[k] for k in ("verify_id", "task_id", "verdict", "ac_checks", "anti_gaming", "criteria_results", "summary", "reason", "failed_criteria") if k in item}))
                value["verification"] = dict(status="ok" if verification else "no_records", records=verification)
            except (sqlite3.Error, ValueError, TypeError):
                value["verification"] = dict(status="read_error", records=[], error="旧 Verifier 记录不可读取")
            rows.append(_entry(path, "history", mid, value))
    return rows


def import_files(request):
    rows, issues = [], []
    if request.get("configPath"):
        values, warnings = import_config(request["configPath"])
        rows.extend(values)
        issues.extend(warnings)
    if request.get("historyPath"):
        path = Path(request["historyPath"])
        if not path.is_absolute() or path.is_symlink():
            raise ImportError("请选择明确的本地旧 runtime 目录或 state.db")
        if path.is_dir():
            paths = ([path / "state.db"] if (path / "state.db").is_file() else
                     sorted(p / "state.db" for p in path.iterdir() if p.is_dir() and not p.is_symlink() and (p / "state.db").is_file()))
            if len(paths) > 200:
                raise ImportError("一次最多导入 200 个旧 runtime；请选择更小的范围")
        else:
            paths = [path]
        if not paths:
            raise ImportError("所选目录没有旧 state.db")
        for db in paths:
            rows.extend(_history_file(db))
    if not request.get("configPath") and not request.get("historyPath"):
        raise ImportError("请明确选择要导入的旧配置或 runtime；不会自动扫描")
    return dict(ok=True, rows=rows, issues=issues)


def semantic(request, *, transport_factory=None):
    """Exactly one HTTP call; native operation owner controls persistence.

    The old transport still enforces provider-specific parameters, strict JSON,
    schema and complete evidence. Role correlation/coherence is checked again by
    the native caller's existing pure contract boundary.
    """
    from .bigmodel import BigModelTransport
    from .credentials import credentials
    from .auditor import SCHEMA_DIR
    from .diagnostics import Diagnostics
    profile = request["profile"]
    validate_profiles([profile])
    if request.get("action") == "check":
        return dict(ok=True, configured=credentials(profile["service"]).configured(profile["credential_ref"]))
    role = request.get("role")
    schema_name = {"planner": "planner-action", "decomposition": "mission-plan", "auditor": "audit-result", "verifier": "verifier-result"}.get(role)
    if not schema_name:
        raise ImportError("所选连接只能用于已支持的语义角色")
    class Facts:
        def __init__(self):
            self.records = []
        def record_phase(self, _, payload, phase_id=None):
            self.records.append(copy.deepcopy(payload))
            return 1
    facts = Facts()
    with Diagnostics(facts, "native").phase("semantic", role=role):
        result = (transport_factory or BigModelTransport)(profile)(prompt=request["prompt"], schema_path=SCHEMA_DIR / (schema_name + ".schema.json"))
    model = next((r for r in reversed(facts.records) if r.get("phase") == "model_request"), {})
    return dict(ok=True, text=json.dumps(result, ensure_ascii=False), confirmedModel=model.get("confirmed_model"),
                modelFactSource=model.get("confirmed_model_source"), usage=model.get("usage"), cost=None)


def evaluate(request):
    action = request.get("action")
    if action == "import":
        return import_files(request)
    if action == "validate":
        validate_profiles([request["profile"]])
        return {"ok": True}
    if action == "credential":
        from .credentials import credentials
        profile = request["profile"]
        validate_profiles([profile])
        credentials(profile["service"]).save(profile["credential_ref"], request["apiKey"])
        return dict(ok=True, configured=True)
    if action in ("semantic", "check"):
        return semantic(request)
    raise ImportError("不支持的旧数据操作")


def main():
    try:
        raw = sys.stdin.buffer.read(2_097_153)
        if len(raw) > 2_097_152:
            raise ImportError("请求超过支持大小")
        result = evaluate(json.loads(raw))
    except ProtocolError as exc:
        result = dict(ok=False, category=exc.category, error=str(exc))
    except ImportError as exc:
        result = dict(ok=False, category="IMPORT", error=str(exc))
    except Exception:
        # Parsing/credential/OS exceptions can quote selected file contents or
        # provider input. The caller gets a stable category, never raw contents.
        result = dict(ok=False, category="CONFIGURATION", error="旧数据或连接不可读取；未回显内容、未迁移凭据")
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
