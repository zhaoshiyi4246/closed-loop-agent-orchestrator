"""Shared, minimal boundary for structured Codex CLI calls."""
from __future__ import annotations

import json
import shutil
import subprocess
from .execution_control import run as controlled_run, checkpoint
import tempfile
from pathlib import Path
from typing import Optional, Union
from .diagnostics import model_attempt
from .structured import (ContractConfigurationError, ProtocolError, parse_json,
                         check_schema, schema_validator)


class CodexCliError(RuntimeError):
    """A Codex CLI invocation did not produce a usable JSON object."""


def run_codex_json(
        prompt: str,
        schema_path: Union[str, Path],
        model: str = "gpt-5.6-sol",
        timeout: float = 180,
        codex_bin: str = "codex",
        cwd: Optional[Union[str, Path]] = None,
        connection: Optional[dict] = None) -> dict:
    """Run one ephemeral, read-only Codex turn and return its JSON object.

    The task prompt is sent only through stdin.  Codex's
    ``--output-last-message`` file is the sole response source; stdout and
    stderr are used only for short diagnostics.
    """
    from .structured import evidence_part, require_complete
    require_complete({"role_prompt": evidence_part(prompt, 64000)})
    source_schema_path = Path(schema_path).resolve()
    workdir = str(Path(cwd).resolve()) if cwd is not None else None
    executable = shutil.which(codex_bin) or codex_bin

    def summary(value: object, limit: int = 400) -> str:
        if connection is not None:
            return 'native output withheld'
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        # CLI startup warnings precede the actionable terminal error, so keep
        # the tail while still bounding diagnostics and never including input.
        return text[-limit:]

    with tempfile.TemporaryDirectory(prefix="codex-json-") as temp_dir:
        # Codex structured output requires strict object schemas, while the
        # repository's existing local-validation schemas intentionally allow
        # extra fields and optional properties. Derive an ephemeral strict
        # transport schema without modifying those authoritative files; the
        # Provider still runs the existing local validator on the result.
        try:
            transport_schema = json.loads(
                source_schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractConfigurationError("codex schema could not be read: %s"
                                % summary(exc)) from exc

        def make_strict(node: object) -> None:
            if isinstance(node, dict):
                node_type = node.get("type")
                is_object = node_type == "object" or (
                    isinstance(node_type, list) and "object" in node_type)
                if is_object:
                    if "properties" not in node or not isinstance(
                            node["properties"], dict):
                        raise ContractConfigurationError(
                            "object schema must declare properties")
                    properties = node["properties"]
                    node["additionalProperties"] = False
                    node["required"] = list(properties)
                for value in node.values():
                    make_strict(value)
            elif isinstance(node, list):
                for value in node:
                    make_strict(value)

        local_schema = json.loads(json.dumps(transport_schema))
        schema_validator(local_schema)
        make_strict(transport_schema)
        transport_schema_path = Path(temp_dir) / source_schema_path.name
        transport_schema_path.write_text(
            json.dumps(transport_schema, ensure_ascii=False), encoding="utf-8")
        output_path = Path(temp_dir) / "last-message.json"
        command = [
            executable,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox", "read-only",
            "--model", model,
            "--output-schema", str(transport_schema_path),
            "--output-last-message", str(output_path),
            "-",
        ]
        native_kwargs = {}
        secret = None
        if connection is not None:
            from .native_models import process_environment, key_for
            from .model_profiles import CODEX_API
            env = process_environment()
            # Nothing from user/project plugin, MCP or hook settings is loaded
            # by an explicitly bound native semantic connection. The temporary
            # cwd has no project config; command children receive no API key.
            command[2:2] = ['--ignore-user-config', '-c', 'shell_environment_policy.inherit="none"',
                            '-c', 'features.multi_agent=false', '-c', 'web_search="disabled"']
            for feature in ('apps', 'connectors', 'plugins', 'hooks', 'codex_hooks', 'plugin_hooks',
                            'browser_use', 'computer_use', 'image_generation', 'js_repl'):
                command[2:2] = ['-c', 'features.' + feature + '=false']
            if connection['service'] == CODEX_API:
                secret = key_for(connection)
                env['CODEX_API_KEY'] = secret
                # API invocation is separate from the user's stored ChatGPT auth.
                env['CODEX_HOME'] = temp_dir
                command[2:2] = ['-c', 'cli_auth_credentials_store="ephemeral"']
            else:
                # Read public account facts without forcing a login method
                # (forced_login_method could log an existing account out).
                from .codex_backend import StdioClient
                client = StdioClient(executable, temp_dir)
                try:
                    client.initialize()
                    if (client.request('account/read', {'refreshToken': False}).get('account') or {}).get('type') != 'chatgpt':
                        raise CodexCliError('需要在官方 Codex 登录 ChatGPT；未自动切换账号')
                finally:
                    client.close()
            native_kwargs['env'] = env
            workdir = temp_dir
        with model_attempt(model) as fact:
            if fact is not None and connection is not None:
                fact.update(provider=connection['service'], profile_id=connection['id'])
            try:
                completed = controlled_run(
                    command,
                    input=prompt,
                    cwd=workdir,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    encoding="utf-8",
                    errors="replace",
                    **native_kwargs,
                )
            except subprocess.TimeoutExpired as exc:
                raise CodexCliError(
                    "codex timed out after %ss; stdout=%s stderr=%s"
                    % (timeout, summary(exc.stdout), summary(exc.stderr))) from exc
            except OSError as exc:
                raise CodexCliError("codex launch failed: %s" % summary(exc)) from exc

            if completed.returncode != 0:
                raise CodexCliError(
                    "codex exited %s; stdout=%s stderr=%s"
                    % (completed.returncode, summary(completed.stdout),
                       summary(completed.stderr)))
            if not output_path.exists():
                raise ProtocolError("JSON_PARSE", "codex output-last-message file is missing")
            try:
                raw = output_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise CodexCliError(
                    "codex output-last-message could not be read: %s"
                    % summary(exc)) from exc
            if not raw:
                raise ProtocolError("JSON_PARSE", "codex output-last-message file is empty")
            if secret and secret in raw:
                raise ProtocolError('CAPABILITY', 'response contains credential material; withheld')
            result = parse_json(raw)
            if secret and secret in json.dumps(result, ensure_ascii=False):
                raise ProtocolError('CAPABILITY', 'response contains credential material; withheld')
            if not isinstance(result, dict):
                raise ProtocolError("JSON_PARSE", "codex output-last-message is not a JSON object")
            check_schema(result, local_schema)
            if fact is not None:
                fact["result"] = "structured response validated"
            return result
