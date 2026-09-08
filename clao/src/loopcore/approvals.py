"""Shared bounded AO approval policy. Unknown requests stay pending.

AO v0.12.9 (4cbb4b6): codexappserver/conversation.go exposes
method/rawCommand/command/cwd; acp/client.go exposes
protocol/subjectKind/toolKind/input. The DTO supplies requestId and offered
options in detail.decisions. Only an offered allow_once option may be sent.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Protocol


class ApprovalClient(Protocol):
    def get_conversation(self, session_id: str, **kwargs: Any) -> dict: ...
    def resolve_approval(self, session_id: str, request_id: str, decision: str) -> bool: ...


class DedupStore(Protocol):
    def counter_get(self, key: str) -> int: ...
    def counter_set(self, key: str, value: int) -> None: ...
    def record_event(self, event_id: str, payload: dict) -> None: ...


@dataclass(frozen=True)
class ApprovalDecision:
    request_id: str
    allow: bool
    reason: str
    decision_id: str = ""


def codex_reviewable(request):
    """Whether a human can review this exact one-request effect in the Panel."""
    params = request.get("params") or {}
    if request.get("method") == "item/commandExecution/requestApproval":
        return (isinstance(params.get("command"), str) and bool(params["command"])
                and isinstance(params.get("cwd"), str) and bool(params["cwd"])
                and params.get("kind", "command") == "command"
                and not params.get("environmentId") and not params.get("networkApprovalContext"))
    if request.get("method") == "item/fileChange/requestApproval" and not params.get("grantRoot"):
        item = request.get("item") or {}
        changes = item.get("changes")
        return bool(item.get("id") == params.get("itemId") and item.get("type") == "fileChange"
                    and item.get("status") == "inProgress" and isinstance(changes, list) and changes
                    and all(isinstance(c, dict) and isinstance(c.get("path"), str) and c["path"]
                            and (c.get("kind") or {}).get("type") in ("add", "update", "delete")
                            and isinstance(c.get("diff"), str) for c in changes))
    return False


def decide_codex_approval(request, *, allowed_paths, forbidden_paths, gate_commands, worktree_root):
    """Native 0.150.1 facts; reuse the exact path/command policy, not AO DTOs."""
    identity = request.get("request_id", "")
    try:
        root = _root(worktree_root)
        allowed, forbidden = _patterns(allowed_paths), _patterns(forbidden_paths)
        # Local detached worktrees use a .git pointer FILE, not a directory.
        # It is control metadata, never an automatically editable deliverable.
        forbidden += [".git", ".git/**", "**/.git", "**/.git/**"]
        params, method = request["params"], request["method"]
        if method == "item/commandExecution/requestApproval":
            if not isinstance(params.get("cwd"), str) or not params["cwd"]:
                raise ValueError("缺少真实执行 cwd")
            if params.get("kind", "command") != "command" or params.get("networkApprovalContext") or params.get("additionalPermissions") or params.get("environmentId"):
                raise ValueError("特殊执行、网络或额外权限请求需人工处理")
            reason = _command_reason(params.get("command"), gate_commands, root, _cwd(params.get("cwd"), root))
        elif method == "item/fileChange/requestApproval":
            if params.get("grantRoot"):
                raise ValueError("拒绝扩大目录或会话授权")
            item = request.get("item")
            if not isinstance(item, dict) or item.get("id") != params.get("itemId") or item.get("type") != "fileChange" or item.get("status") != "inProgress":
                raise ValueError("缺少同一回合 item/started 的完整拟修改清单")
            changes = item.get("changes")
            if not isinstance(changes, list) or not changes:
                raise ValueError("缺少拟修改路径")
            for change in changes:
                if not isinstance(change, dict) or not isinstance(change.get("diff"), str):
                    raise ValueError("拟修改条目不完整")
                kind = change.get("kind") or {}
                if kind.get("type") not in ("add", "delete", "update"):
                    raise ValueError("未知文件修改类型")
                _edit_path(change.get("path"), root, root, allowed, forbidden)
                if kind.get("move_path") is not None:
                    _edit_path(kind["move_path"], root, root, allowed, forbidden)
            reason = "全部拟修改路径在工作区和授权范围内"
        else:
            raise ValueError("需要人工输入或不支持的引擎请求")
        return ApprovalDecision(identity, True, reason, "accept")
    except (KeyError, ValueError, TypeError, OSError, RuntimeError) as exc:
        return ApprovalDecision(identity, False, str(exc))


def pending_approvals(conversation: Any) -> list[dict]:
    activities = conversation.get("activities") if isinstance(conversation, dict) else None
    if not isinstance(activities, list):
        return []
    return [a for a in activities if isinstance(a, dict)
            and (a.get("activityKind") or a.get("kind")) == "approval"
            and a.get("status") == "pending"]


def _detail(activity: dict) -> dict:
    detail = activity.get("detail")
    if isinstance(detail, str):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate detail key")
                result[key] = value
            return result
        detail = json.loads(detail, object_pairs_hook=unique)
    if not isinstance(detail, dict):
        raise ValueError("approval detail must be an object")
    return detail


def _controls(value: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in value)


def _request_id(activity: dict) -> str:
    # requestId is authoritative; providerItemId supports recorded older AO
    # activities. A local activity id is NOT a provider approval request id.
    value = activity.get("requestId", activity.get("providerItemId"))
    return value if isinstance(value, str) and value and value not in (".", "..") and not _controls(value) else ""


def _path(value: Any) -> Path:
    if not isinstance(value, str) or not value or _controls(value):
        raise ValueError("missing or invalid path")
    win = PureWindowsPath(value)
    if value.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
        raise ValueError("device path is unsupported")
    if os.name == "nt":
        if bool(win.drive) != bool(win.root):
            raise ValueError("drive-relative or current-drive path is ambiguous")
        for part in win.parts[1:] if win.anchor else win.parts:
            if part not in (".", "..") and (
                part.endswith((".", " ")) or any(c in part for c in ':*?"<>|')
                or PureWindowsPath(part).is_reserved()
            ):
                raise ValueError("ambiguous Windows path component")
    elif win.drive or "\\" in value:
        raise ValueError("foreign-platform path is unsupported")
    return Path(value)


def _root(value: str) -> Path:
    root = _path(value)
    if not root.is_absolute():
        raise ValueError("actual Worker workspace is required")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Worker workspace is not a directory")
    return root


def _target(value: str, root: Path, cwd: Path) -> tuple[Path, str]:
    """Containment before glob, resolving existing ancestors strictly.

    Walk links/junctions before '..'. Missing children are allowed only below
    a confirmed directory; a broken link is not a new-file authorization.
    """
    path = _path(value)
    absolute = path if path.is_absolute() else cwd / path
    try:
        parts = absolute.relative_to(root).parts
    except ValueError:
        raise ValueError("outside Worker worktree") from None
    current, lexical, missing = root, [], False
    for part in parts:
        if part == "..":
            current = current.parent
            if lexical:
                lexical.pop()
            if not current.is_relative_to(root):
                raise ValueError("outside Worker worktree")
            if missing:
                raise ValueError("unresolved parent traversal")
            continue
        lexical.append(part)
        if not missing and not current.is_dir():
            raise ValueError("path parent is not a directory")
        current = current / part
        if missing:
            continue
        try:
            current.lstat()
        except FileNotFoundError:
            missing = True
            continue
        current = current.resolve(strict=True)
        if not current.is_relative_to(root):
            raise ValueError("link target outside Worker worktree")
    return current, "/".join(lexical) or "."


def _cwd(value: Any, root: Path, current: Path | None = None) -> Path:
    if value is None:
        return root
    target, _ = _target(value, root, current or root)
    if not target.is_dir():
        raise ValueError("request cwd is not a confirmed directory")
    return target


def path_matches(rel_path: str, patterns: list[str]) -> bool:
    """Match already-contained relative paths, including directory prefixes."""
    rel = rel_path.replace("\\", "/")
    return any(fnmatch.fnmatch(rel, p.replace("\\", "/").rstrip("/"))
               or fnmatch.fnmatch(rel, p.replace("\\", "/").rstrip("/") + "/*")
               for p in patterns)


def _patterns(patterns: Any) -> list[str]:
    if not isinstance(patterns, (list, tuple)):
        raise ValueError("invalid scope patterns")
    for value in patterns:
        if not isinstance(value, str) or not value or _controls(value):
            raise ValueError("invalid scope pattern")
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ":" in normalized or ".." in normalized.split("/"):
            raise ValueError("scope patterns must be worktree-relative")
    return list(patterns)


def _edit_path(value, root, cwd, allowed, forbidden) -> str:
    target, lexical = _target(value, root, cwd)
    if target.exists() and not target.is_file():
        raise ValueError("edit target must be a regular file or a new file")
    real = target.relative_to(root).as_posix()
    if any(path_matches(p, forbidden) for p in (lexical, real)):
        raise ValueError("forbidden path")
    if not allowed or not all(path_matches(p, allowed) for p in (lexical, real)):
        raise ValueError("outside allowed_paths")
    return real


def _tokens(command: Any) -> list[str]:
    """Literal argv subset: preserve Windows backslashes and quoted spaces.

    Partial-token quoting and ambiguous escapes require human review. This
    intentionally does not attempt to interpret arbitrary shell syntax.
    """
    if not isinstance(command, str) or not command:
        raise ValueError("command must be a nonempty string")
    if any((ord(c) < 32 and c != "\t") or ord(c) == 127 for c in command):
        raise ValueError("control character/newline in raw command")
    tokens, i = [], 0
    while i < len(command):
        if command[i] in " \t":
            i += 1
            continue
        if command[i] in "\"'":
            quote = command[i]
            end = command.find(quote, i + 1)
            if end < 0 or command[end - 1:end] == "\\":
                raise ValueError("ambiguous command quoting")
            tokens.append(command[i + 1:end])
            i = end + 1
            if i < len(command) and command[i] not in " \t":
                raise ValueError("partial-token quoting is unsupported")
        else:
            end = i
            while end < len(command) and command[end] not in " \t":
                end += 1
            token = command[i:end]
            if any(c in token for c in "\"'"):
                raise ValueError("partial-token quoting is unsupported")
            tokens.append(token)
            i = end
    if not tokens:
        raise ValueError("empty command")
    return tokens


def _unwrap(command: str) -> str:
    tokens = _tokens(command)
    # Known harness wrappers only; never trust AO's display-only unwrapping.
    head = tokens[0]
    shells = {"sh", "bash", "zsh", "/bin/sh", "/bin/bash", "/bin/zsh"}
    if head in shells and len(tokens) == 3 and tokens[1] in ("-c", "-lc"):
        return tokens[2]
    ps = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
    if os.name == "nt":
        ps.add(str(Path(os.environ.get("SystemRoot", "C:\\Windows")) /
                   "System32/WindowsPowerShell/v1.0/powershell.exe").lower())
        ps.add(str(Path(os.environ.get("ProgramFiles", "C:\\Program Files")) /
                   "PowerShell/7/pwsh.exe").lower())
    if head.lower() in ps:
        flags = [s.lower() for s in tokens[1:-1]]
        if flags and flags[-1] in ("-command", "-c") and all(
            s in ("-noprofile", "-noninteractive") for s in flags[:-1]
        ):
            return tokens[-1]
    return command


def _command(command: str, root: Path, cwd: Path) -> tuple[list[str], Path]:
    # Check original input before normalization or removal of shell wrappers.
    _tokens(command)
    if any(c in command for c in "\n\r;|<>`$%^#\x00"):
        raise ValueError("shell control, expansion or redirection is unsupported")
    command = _unwrap(command)
    segments = command.split("&&")
    if len(segments) == 2:
        prefix = _tokens(segments[0])
        if len(prefix) != 2 or prefix[0].lower() != "cd":
            raise ValueError("additional command is not authorized")
        cwd = _cwd(prefix[1], root, cwd)
        command = segments[1]
    elif len(segments) != 1:
        raise ValueError("additional commands are not authorized")
    if any(c in command for c in "&()"):
        raise ValueError("command chaining or subshell is unsupported")
    tokens = _tokens(command)
    if tokens[0].lower() in ("cd", "chdir", "set-location"):
        raise ValueError("standalone directory change is not authorized")
    return tokens, cwd


def _read_command(tokens: list[str], root: Path, cwd: Path) -> bool:
    head, args = tokens[0].lower(), tokens[1:]
    if head in ("pwd", "get-location"):
        return not args
    if head in ("python", "python3", "py"):
        return args in (["--version"], ["-V"])
    if head in ("which", "where", "where.exe", "command"):
        if head == "command":
            if args[:1] != ["-v"]:
                return False
            args = args[1:]
        return len(args) == 1 and args[0] in ("python", "python3", "py", "pytest", "git")
    if head == "git":
        if args[:1] == ["--no-pager"]:
            args = args[1:]
        if not args:
            return False
        sub, args = args[0], args[1:]
        options = {
            "status": {"-s", "--short", "-b", "--branch", "--porcelain", "--porcelain=v1",
                       "--porcelain=v2", "-uno", "-unormal", "-uall"},
            "diff": {"--no-ext-diff", "--no-textconv", "--stat", "--name-only", "--name-status",
                     "--cached", "--staged", "--exit-code"},
            "log": {"--oneline", "--no-decorate", "-1", "-5", "-10"},
        }
        if sub not in options:
            return False
        flags, paths = args, []
        if "--" in args:
            split = args.index("--")
            flags, paths = args[:split], args[split + 1:]
        if not all(arg in options[sub] for arg in flags):
            return False
        if sub == "diff" and not {"--no-ext-diff", "--no-textconv"}.issubset(flags):
            return False
        for value in paths:
            if value.startswith(("-", ":")) or any(c in value for c in "*?["):
                return False
            _target(value, root, cwd)
        return True
    if head in ("ls", "dir", "get-childitem", "cat", "type", "get-content", "head", "tail"):
        listing = head in ("ls", "dir", "get-childitem")
        paths = []
        for arg in args:
            if listing and arg.lower() in ("-l", "-a", "-la", "-al", "-force"):
                continue
            if arg.startswith("-") or any(c in arg for c in "*?["):
                return False
            target, _ = _target(arg, root, cwd)
            if not listing and not target.is_file():
                return False
            paths.append(target)
        return listing or bool(paths)
    return False


def _command_reason(cmd, gate_commands, root, cwd) -> str:
    tokens, effective = _command(cmd, root, cwd)
    if tokens[0].lower() == "git" and any(
        t in ("restore", "checkout", "reset", "clean", "push", "add", "commit") for t in tokens[1:]
    ):
        raise ValueError("Git write/state change requires human approval")
    for gate in gate_commands:
        try:
            authorized, gate_cwd = _command(gate, root, root)
        except (ValueError, OSError, RuntimeError):
            continue
        if tokens == authorized and effective == gate_cwd:
            return "exact authorized Gate and cwd"
    if _read_command(tokens, root, effective):
        return "bounded worktree inspection"
    raise ValueError("command/arguments/cwd do not match an explicit authorization")


def is_safe_command(cmd: str, gate_commands: list[str], *, worktree_root: str = "",
                    cwd: str | None = None) -> bool:
    try:
        root = _root(worktree_root)
        _command_reason(cmd, gate_commands, root, _cwd(cwd, root))
        return True
    except (ValueError, TypeError, OSError, RuntimeError):
        return False


def decide_approval(activity: dict[str, Any], *, allowed_paths: list[str],
                    forbidden_paths: list[str], gate_commands: list[str],
                    worktree_root: str = "") -> ApprovalDecision | None:
    if not pending_approvals({"activities": [activity]}):
        return None
    request_id = _request_id(activity)
    try:
        if not request_id:
            raise ValueError("missing/invalid provider request id")
        detail = _detail(activity)
        options = detail.get("decisions")
        if not isinstance(options, list) or not options:
            raise ValueError("offered single-request decisions are missing")
        if any(not isinstance(o, dict) or not isinstance(o.get("id"), str)
               or not o["id"] or _controls(o["id"]) for o in options):
            raise ValueError("invalid offered decision")
        if len({o["id"] for o in options}) != len(options):
            raise ValueError("duplicate offered decision id")
        once = [o["id"] for o in options if o.get("kind") == "allow_once"]
        if len(once) != 1:
            raise ValueError("no unambiguous allow_once option")
        root = _root(worktree_root)
        allowed, forbidden = _patterns(allowed_paths), _patterns(forbidden_paths)
        method = detail.get("method")
        if "method" in detail and (not isinstance(method, str) or not method):
            raise ValueError("invalid provider request method")
        if method == "item/commandExecution/requestApproval":
            if once != ["accept"]:
                raise ValueError("Codex single-request decision must be accept")
            if ("input" in detail or "protocol" in detail
                    or detail.get("subjectKind") not in (None, "command")
                    or detail.get("toolKind") not in (None, "execute")):
                raise ValueError("conflicting approval request shapes")
            command = detail.get("rawCommand")
            if not isinstance(command, str) or not command:
                raise ValueError("original Codex command is missing")
            if not isinstance(detail.get("cwd"), str) or not detail["cwd"]:
                raise ValueError("Codex request cwd is missing")
            reason = _command_reason(command, gate_commands, root, _cwd(detail["cwd"], root))
        elif method:
            # v0.12.9 fileChange approvals have itemId/reason but no complete
            # target list. Labels and finished diffs cannot supply authorization.
            raise ValueError("unsupported provider request or missing complete file targets")
        else:
            if any(k in detail for k in ("rawCommand", "command", "files")):
                raise ValueError("conflicting approval request shapes")
            if detail.get("protocol") not in (None, "acp"):
                raise ValueError("unsupported approval protocol")
            inputs = detail.get("input")
            if not isinstance(inputs, dict):
                raise ValueError("approval input must be an object")
            subject, tool = detail.get("subjectKind"), detail.get("toolKind")
            cwd_values = [m["cwd"] for m in (detail, inputs) if "cwd" in m]
            if any(not isinstance(v, str) or not v for v in cwd_values):
                raise ValueError("invalid request cwd")
            cwds = [_cwd(v, root) for v in cwd_values] or [root]
            if any(p != cwds[0] for p in cwds):
                raise ValueError("conflicting request cwd")
            cwd = cwds[0]
            if subject == "command" and tool == "execute":
                if set(inputs) - {"command", "cwd", "description", "timeout"}:
                    raise ValueError("unsupported execution options")
                if "description" in inputs and not isinstance(inputs["description"], str):
                    raise ValueError("invalid command description")
                if "timeout" in inputs and (type(inputs["timeout"]) is not int or inputs["timeout"] <= 0):
                    raise ValueError("invalid command timeout")
                reason = _command_reason(inputs.get("command"), gate_commands, root, cwd)
            elif subject == "file_change" and tool == "edit":
                if detail.get("providerToolName") not in (None, "Edit", "Write", "MultiEdit"):
                    raise ValueError("unsupported file tool")
                if set(inputs) - {"file_path", "path", "cwd", "content", "old_string", "new_string",
                                  "replace_all", "edits"}:
                    raise ValueError("unsupported file input or additional targets")
                paths = [inputs[k] for k in ("file_path", "path") if k in inputs]
                if len(paths) != 1:
                    raise ValueError("a single unambiguous edit target is required")
                for field in ("content", "old_string", "new_string"):
                    if field in inputs and not isinstance(inputs[field], str):
                        raise ValueError("invalid edit text")
                if "replace_all" in inputs and type(inputs["replace_all"]) is not bool:
                    raise ValueError("invalid replace_all option")
                edits = inputs.get("edits")
                if "edits" in inputs and (not isinstance(edits, list) or not edits or any(
                    not isinstance(e, dict) or set(e) - {"old_string", "new_string", "replace_all"}
                    or not isinstance(e.get("old_string"), str) or not isinstance(e.get("new_string"), str)
                    or ("replace_all" in e and type(e["replace_all"]) is not bool)
                    for e in edits
                )):
                    raise ValueError("unsupported multi-edit targets")
                _edit_path(paths[0], root, cwd, allowed, forbidden)
                reason = "edit inside worktree and allowed_paths; not forbidden"
            else:
                raise ValueError("unsupported/ambiguous approval subject or tool")
        return ApprovalDecision(request_id, True, reason, once[0])
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "request/path could not be resolved"
        return ApprovalDecision(request_id, False, reason)


def apply_approval(activity: dict, decision: ApprovalDecision, *, task_id: str,
                   session_id: str, store: DedupStore, resolve) -> bool:
    """Use existing counters/events for one request; do not expand AO policy."""
    encoded = json.dumps(activity, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    identity = decision.request_id or "malformed-" + digest
    key = f"approved:{task_id}:{session_id}:{identity}"
    if store.counter_get(key) != 0:
        return False
    payload = {"kind": "approval_policy", "task_id": task_id, "session_id": session_id,
               "request_id": decision.request_id, "activity_id": activity.get("id"),
               "request_sha256": digest, "allow": decision.allow,
               "reason": decision.reason, "decision_id": decision.decision_id,
               "requires_human": True, "outcome": "pending_human"}
    try:
        detail = _detail(activity)
        inputs = detail.get("input")
        inputs = inputs if isinstance(inputs, dict) else {}
        payload["request_paths"] = [inputs[k] for k in ("file_path", "path")
                                    if isinstance(inputs.get(k), str)]
        command = detail.get("rawCommand", inputs.get("command"))
        if isinstance(command, str):
            payload["command_sha256"] = hashlib.sha256(command.encode("utf-8")).hexdigest()
            payload["command_length"] = len(command)
    except (ValueError, TypeError):
        pass
    # The original request is in AO's conversation, correlated by IDs/digest.
    # Do not duplicate file contents or command secrets into SQLite.
    store.counter_set(key, -1)
    store.record_event(key + ":policy", payload)
    if not decision.allow:
        return False
    try:
        ok = bool(resolve(session_id, decision.request_id, decision.decision_id))
    except Exception:
        ok = False
    store.counter_set(key, 1 if ok else -1)
    store.record_event(key + ":result", dict(payload,
                       outcome="resolved_once" if ok else "resolve_unconfirmed",
                       requires_human=not ok))
    return ok


class AutoApprover:
    """Compatibility entry point, using the same policy/records as ClosedLoop."""
    def __init__(self, client: ApprovalClient, store: DedupStore, *, task_id: str,
                 worker_session_id: str, allowed_paths: list[str], forbidden_paths: list[str],
                 gate_commands: list[str], worktree_root: str = "") -> None:
        self.client, self.store = client, store
        self.task_id, self.worker_session_id = task_id, worker_session_id
        self.allowed_paths, self.forbidden_paths = allowed_paths, forbidden_paths
        self.gate_commands, self.worktree_root = gate_commands, worktree_root

    def sweep(self) -> list[ApprovalDecision]:
        try:
            conversation = self.client.get_conversation(self.worker_session_id)
        except Exception:
            return []
        acted = []
        for activity in pending_approvals(conversation):
            decision = decide_approval(activity, allowed_paths=self.allowed_paths,
                forbidden_paths=self.forbidden_paths, gate_commands=self.gate_commands,
                worktree_root=self.worktree_root)
            if decision and apply_approval(activity, decision, task_id=self.task_id,
                session_id=self.worker_session_id, store=self.store, resolve=self.client.resolve_approval):
                acted.append(decision)
        return acted
