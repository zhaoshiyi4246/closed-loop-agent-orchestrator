"""Validated, secret-free configuration shared by CLI and Panel.

Priority: built-in defaults < config/default.yaml < explicit invocation overrides.
Only this module resolves aliases, ranges, sources and revision. Saved defaults
are replaced atomically after whole-document validation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import yaml

# path: (default, kind, minimum, consumer). Seconds are finite numbers, never ints.
FIELDS = {
    "runner.poll_seconds": (5, "seconds", 0, "run_loop wait"),
    "runner.cap_seconds": (7200, "seconds", 0, "run_loop wall-clock cap"),
    "observer.blocked_escalation_seconds": (600, "seconds", 0, "ClosedLoop approvals"),
    "observer.l0_nudge_grace_seconds": (120, "seconds", 0, "ClosedLoop L0 grace"),
    "observer.idle_audit_cooldown_seconds": (120, "seconds", 0, "ClosedLoop idle audit"),
    "observer.audit_cooldown_seconds": (60, "seconds", 0, "ClosedLoop audit cooldown"),
    "observer.turn_diff_counts_as_progress": (True, "bool", None, "EventNormalizer"),
    "thresholds.repeated_error.window_seconds": (600, "seconds", 0, "Observer"),
    "thresholds.repeated_error.count": (3, "count", 1, "Observer"),
    "thresholds.repeated_error.cooldown_seconds": (600, "seconds", 0, "Observer"),
    "thresholds.no_progress.window_seconds": (300, "seconds", 0, "Observer"),
    "thresholds.no_progress.min_activity_events": (8, "count", 1, "Observer"),
    "thresholds.no_progress.max_progress_events": (0, "count", 0, "Observer"),
    "thresholds.no_progress.cooldown_seconds": (300, "seconds", 0, "Observer"),
    "thresholds.no_progress.progress_mode": ("weak", "progress", None, "Observer"),
    "ao.base_url": ("http://127.0.0.1:3001", "url", None, "AOAdapter fallback; valid AO runfile port wins"),
    "ao.request_timeout_seconds": (15, "seconds", 0, "AOAdapter REST requests"),
    "worker.model": ("gpt-5.6-sol", "model", None, "ActionExecutor ao spawn --model"),
    "worker.spawn_max_attempts": (3, "count", 1, "ActionExecutor proven-nonstart bounded retry"),
    "worker.spawn_backoff_seconds": (30, "seconds", 0, "ActionExecutor initial spawn retry wait"),
    "worker.spawn_timeout_seconds": (120, "seconds", 0, "ActionExecutor spawn CLI"),
    "worker.send_timeout_seconds": (60, "seconds", 0, "ActionExecutor send CLI"),
    "worker.kill_timeout_seconds": (30, "seconds", 0, "ActionExecutor kill CLI; AO termination still required"),
    "gate.timeout_seconds": (300, "seconds", 0, "IntegrationGate per command: Task/baseline/Final"),
    "gate.output_limit_chars": (20000, "count", 1, "Gate per stdout/stderr evidence and storage; full failure IDs retained"),
    "budgets.max_subtasks": (1, "subtasks", 1, "Mission decomposition"),
    "budgets.max_total_replans": (2, "count", 0, "Mission/ActionExecutor"),
    "budgets.max_runtime_seconds": (3600, "seconds", 0, "Mission watchdog"),
    "budgets.subtask_budgets.max_local_fixes": (2, "count", 0, "ActionExecutor"),
    "budgets.subtask_budgets.max_replans": (1, "count", 0, "ActionExecutor"),
    "budgets.subtask_budgets.max_same_alerts": (2, "count", 0, "ClosedLoop"),
    "budgets.subtask_budgets.max_runtime_seconds": (1800, "seconds", 0, "ClosedLoop watchdog"),
    "bus.max_hops_per_thread": (24, "count", 1, "LoopBus projection bound, not Controller budget"),
    "bus.max_audits_per_thread": (3, "count", 1, "LoopBus projection bound, not Controller budget"),
    "bus.overall_timeout_seconds": (600, "seconds", 0, "LoopBus projection bound, not Mission timeout"),
}
for _role in ("planner", "auditor", "verifier"):
    FIELDS[f"roles.{_role}.model"] = ("gpt-5.6-sol", "model", None, f"CodexCli{_role.title()}Provider --model")
    FIELDS[f"roles.{_role}.timeout_seconds"] = (180, "seconds", 0, f"CodexCli{_role.title()}Provider per attempt")
for _key in ("strip_ansi", "normalize_timestamps", "normalize_ids", "normalize_paths", "normalize_line_numbers", "collapse_whitespace"):
    FIELDS["fingerprint." + _key] = (True, "bool", None, "Fingerprinter")
FIELDS["fingerprint.max_length"] = (200, "count", 1, "Fingerprinter")
LEGACY_FIELDS = frozenset(FIELDS)
FIELDS["model_profiles"] = ([], "profiles", None, "service/native executor connection and role parameters")
for _role in ("planner", "auditor", "verifier"):
    FIELDS[f"roles.{_role}.profile"] = ("codex", "profile", None, "semantic role transport selection")
V2_FIELDS = frozenset(FIELDS)
FIELDS['worker.profile'] = ('codex', 'profile', None, 'Codex Worker authentication/model connection')

# Historical options without production consumers are visible warnings, never
# members of the effective values. No new functionality is invented for them.
DEPRECATED = {
    "observer.interval_seconds", "observer.stall_threshold_seconds", "observer.failure_threshold",
    "observer.early_warning.failure_first_occurrence", "observer.early_warning.budget_usage_ratio",
    "observer.activity_kinds", "observer.progress_kinds", "auditor.audit_interval_seconds",
    "ao.sse_idle_timeout_seconds", "ao.poll_interval_seconds", "roles.max_parallel_workers",
    "worker.spawn_max_transient_attempts", "worker.spawn_transient_backoff_seconds",
}
ALIASES = {"roles.worker.model": "worker.model", "poll_seconds": "runner.poll_seconds"}
for _key in ("idle_audit_cooldown_seconds", "blocked_escalation_seconds", "l0_nudge_grace_seconds"):
    ALIASES[_key] = "observer." + _key


class ConfigError(ValueError):
    pass


class EffectiveConfig(dict):
    def __init__(self, values, sources, warnings=(), schema_version=3):
        super().__init__(copy.deepcopy(values))
        self.sources = dict(sources)
        self.warnings = list(warnings)
        self.schema_version = schema_version

    def snapshot(self):
        values = copy.deepcopy(dict(self))
        raw = json.dumps(values, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        return {"schema_version": self.schema_version, "revision": hashlib.sha256(raw.encode()).hexdigest(),
                "values": values, "sources": dict(self.sources), "warnings": list(self.warnings)}


def flatten(value, prefix=""):
    if not isinstance(value, dict):
        raise ConfigError("configuration must be an object")
    out = {}
    for key, item in value.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ConfigError("invalid configuration key format")
        path = prefix + key
        if isinstance(item, dict):
            if not any(k.startswith(path + ".") for k in (*FIELDS, *DEPRECATED, *ALIASES)):
                raise ConfigError("unsupported configuration section: " + path)
            out.update(flatten(item, path + "."))
        else:
            out[path] = item
    return out


def nest(flat):
    out = {}
    for path, value in flat.items():
        node = out
        *parents, key = path.split(".")
        for parent in parents:
            node = node.setdefault(parent, {})
        node[key] = copy.deepcopy(value)
    return out


def _validate(key, value):
    _, kind, minimum, _ = FIELDS[key]
    valid = False
    if kind == "seconds":
        valid = type(value) in (int, float) and minimum < value <= 604800 and math.isfinite(value)
    elif kind in ("count", "subtasks"):
        valid = type(value) is int and minimum <= value <= 1000000 and (kind != "subtasks" or value <= 2)
    elif kind == "bool":
        valid = type(value) is bool
    elif kind == "progress":
        valid = value in ("weak", "strong")
    elif kind == "model":
        valid = isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", value))
    elif kind == "profile":
        from .model_profiles import REFERENCE
        valid = isinstance(value, str) and bool(REFERENCE.fullmatch(value))
    elif kind == "profiles":
        from .model_profiles import validate_profiles
        try:
            validate_profiles(value)
        except ValueError as exc:
            raise ConfigError(str(exc)) from None
        valid = True
    elif kind == "url" and isinstance(value, str):
        try:
            u = urlsplit(value)
            valid = (bool(re.fullmatch(r"http://(?:127\.0\.0\.1|localhost|\[::1\]):[0-9]{1,5}/?", value)) and u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1")
                     and u.port is not None and 0 < u.port < 65536 and not u.username
                     and not u.password and not u.query and not u.fragment and u.path in ("", "/"))
        except ValueError:
            pass
    if not valid:
        maximum = 604800 if kind == "seconds" else 2 if kind == "subtasks" else 1000000
        limits = f" (minimum {minimum}{', exclusive' if kind == 'seconds' else ''}; maximum {maximum})" if minimum is not None else ""
        raise ConfigError(f"invalid {key}: expected {kind}" + limits)


def resolve_config(values=None, *, overrides=None, source="explicit input"):
    flat = {key: spec[0] for key, spec in FIELDS.items()}
    sources = {key: "built-in default" for key in FIELDS}
    warnings = []
    for data, label in ((values if values is not None else {}, source), (overrides if overrides is not None else {}, "invocation override")):
        incoming = flatten(data)
        if isinstance(data, EffectiveConfig):
            warnings.extend(data.warnings)
        for old, new in ALIASES.items():
            if old in incoming:
                if new in incoming and incoming[new] != incoming[old]:
                    raise ConfigError(f"conflicting configuration: {old} / {new}")
                incoming[new] = incoming.pop(old)
                warnings.append(f"{old} migrated to {new}")
        for key, value in incoming.items():
            if key in DEPRECATED:
                warnings.append(f"{key}: deprecated, unsupported and NOT effective")
                continue
            if key not in FIELDS:
                raise ConfigError("unsupported configuration key: " + key)
            _validate(key, value)
            flat[key] = value
            sources[key] = data.sources.get(key, label) if isinstance(data, EffectiveConfig) else label
    values = nest(flat)
    names = {p["id"] for p in values["model_profiles"]} | {"codex"}
    if any(values["roles"][r]["profile"] not in names for r in ("planner", "auditor", "verifier")):
        raise ConfigError("role profile does not name a saved connection")
    from .model_profiles import selected, CODEX_ACCOUNT, CODEX_API, TERMINAL_SERVICES
    for role in ('planner','auditor','verifier'):
        profile = selected(values, role)
        if profile and profile['service'] in TERMINAL_SERVICES:
            raise ConfigError('原生终端连接仅供手动执行，不能分配为自动语义角色')
    worker = selected(values, 'worker')
    if worker and worker['service'] not in (CODEX_ACCOUNT, CODEX_API):
        raise ConfigError('Worker requires the Codex executor; semantic API/Claude connections cannot control a Worker')
    return EffectiveConfig(values, sources, list(dict.fromkeys(warnings)))


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ConfigError("duplicate or invalid YAML key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_config(path):
    try:
        values = yaml.load(Path(path).read_text("utf-8"), Loader=_UniqueLoader)
    except (yaml.YAMLError, UnicodeError) as exc:
        raise ConfigError("invalid configuration YAML") from exc
    if not isinstance(values, dict):
        raise ConfigError("configuration YAML must contain an object")
    return resolve_config(values, source="config/default.yaml")


def save_defaults(path, updates):
    path = Path(path)
    current = load_config(path)
    updated = resolve_config(current, overrides=updates)
    # A settings write may not claim that a newly submitted dead option worked.
    if any(k in DEPRECATED for k in flatten(updates)):
        raise ConfigError("deprecated option cannot be saved as effective; see configuration warnings")
    text = yaml.safe_dump(dict(updated), allow_unicode=True, sort_keys=False)
    fd, name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    # Return exactly what was committed, without a second fallible disk read.
    return EffectiveConfig(dict(updated), {k: "config/default.yaml" for k in FIELDS})


def restore_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") not in (1, 2, 3):
        raise ConfigError("Mission effective config snapshot missing or unsupported")
    fields = {1: LEGACY_FIELDS, 2: V2_FIELDS, 3: set(FIELDS)}[snapshot['schema_version']]
    if set(flatten(snapshot.get("values"))) != fields:
        raise ConfigError("Mission effective config fields missing or unsupported")
    cfg = resolve_config(snapshot["values"])
    if snapshot["schema_version"] < 3:
        cfg = EffectiveConfig(snapshot["values"], {k: cfg.sources[k] for k in fields}, cfg.warnings, schema_version=snapshot['schema_version'])
    if cfg.warnings or cfg.snapshot()["revision"] != snapshot.get("revision"):
        raise ConfigError("Mission effective config snapshot invalid; defaults were not substituted")
    sources = snapshot.get("sources")
    if not isinstance(sources, dict) or set(sources) != fields:
        raise ConfigError("Mission config sources missing")
    cfg.sources = {k: v for k, v in sources.items() if isinstance(v, str) and v in
                   ("built-in default", "config/default.yaml", "explicit input", "invocation override", "mission input")}
    if len(cfg.sources) != len(fields):
        raise ConfigError("Mission config source is unsupported")
    allowed_warnings = {f"{old} migrated to {new}" for old, new in ALIASES.items()} | {f"{key}: deprecated, unsupported and NOT effective" for key in DEPRECATED}
    warnings = snapshot.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(w, str) or w not in allowed_warnings for w in warnings):
        raise ConfigError("Mission config warnings invalid")
    cfg.warnings = warnings
    return cfg
