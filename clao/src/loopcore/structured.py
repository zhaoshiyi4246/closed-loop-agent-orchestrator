"""Small shared JSON/Schema boundary; never repairs role responses."""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache


class ContractConfigurationError(RuntimeError):
    """Installation/schema fault: stop before invoking a semantic role."""


try:
    from jsonschema import Draft7Validator
except ImportError as exc:
    raise ContractConfigurationError(
        "Full JSON Schema validation requires jsonschema; rerun bootstrap.ps1") from exc


class ProtocolError(RuntimeError):
    """Untrusted output or incomplete input, distinct from semantic FAIL."""
    def __init__(self, category, detail, *, evidence=None):
        self.category = category
        self.detail = detail
        self.evidence = evidence or {}
        self.attempts = 1
        super().__init__("protocol failure [%s]: %s" % (category, detail))

    def payload(self):
        return dict(alert_type="PROTOCOL_FAILURE", category=self.category,
                    error=str(self), attempts=self.attempts, evidence=self.evidence)


def require_finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ProtocolError("SCHEMA", "non-finite number")
    if isinstance(value, dict):
        for item in value.values():
            require_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            require_finite(item)


def response_digest(value):
    raw = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=lambda _: "<non-JSON>")
    return dict(original_length=len(raw),
                sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest())


def parse_json(raw):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ProtocolError("JSON_PARSE", "duplicate object key")
            obj[key] = value
        return obj
    try:
        obj = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as exc:
        raise ProtocolError("JSON_PARSE", "not valid JSON",
                            evidence={"response": response_digest(raw)}) from exc
    try:
        require_finite(obj)
    except ProtocolError as exc:
        exc.evidence["response"] = response_digest(raw)
        raise
    return obj


@lru_cache(maxsize=32)
def _validator(schema_text):
    try:
        schema = parse_json(schema_text)
        Draft7Validator.check_schema(schema)
        if schema.get("$schema", "http://json-schema.org/draft-07/schema#") != \
                "http://json-schema.org/draft-07/schema#":
            raise ValueError("unsupported schema dialect")
        return Draft7Validator(schema)
    except Exception as exc:
        raise ContractConfigurationError(
            "Invalid local JSON Schema; repair installation/configuration") from exc


def schema_validator(schema):
    return _validator(json.dumps(schema, sort_keys=True))


def check_schema(obj, schema):
    validator = schema_validator(schema)
    require_finite(obj)
    error = next(validator.iter_errors(obj), None)
    if error is not None:
        # Do not put model strings / code / secrets in diagnostics.
        raise ProtocolError("SCHEMA", "constraint %s at %s" % (
            error.validator, "/".join(map(str, error.absolute_schema_path))))


def correlate(obj, **expected):
    for field, value in expected.items():
        if not isinstance(value, str) or not value.strip():
            raise ProtocolError("CORRELATION", "trusted %s is missing" % field)
        if obj.get(field) != value:
            raise ProtocolError("CORRELATION", "%s does not match request" % field)


def protocol_call(call, validate, *, max_attempts=2, retry_categories=None, retry_delay_seconds=0):
    """A single role-call budget. Controllers never retry ProtocolError.

    Transport errors escape immediately to the existing three-tick boundary:
    three pure transport attempts, at most six mixed protocol/transport calls
    in a consecutive failed step episode. Protocol exhaustion halts immediately.
    A valid semantic FAIL returns immediately and is never refreshed into PASS.
    BigModel supplies a total budget (1..3) including transient HTTP errors;
    its transport does not retry underneath this boundary.
    """
    from .execution_control import checkpoint
    import time
    errors = []
    categories = {"JSON_PARSE", "SCHEMA", "CORRELATION", "COHERENCE"} if retry_categories is None else retry_categories
    for attempt in range(1, max_attempts + 1):
        checkpoint()
        try:
            obj = call()
            validate(obj)
            checkpoint()
            # Keep earlier invalid attempts visible without retaining raw prompts
            # or repairing any model-authored field. Reserved metadata is ours.
            return dict(obj, _protocol_errors=errors)
        except ProtocolError as exc:
            exc.attempts = attempt
            errors.append(exc.payload())
            if attempt == max_attempts or exc.category not in categories:
                exc.evidence = dict(exc.evidence, prior_errors=errors[:-1])
                raise
            from .diagnostics import CURRENT
            from contextlib import nullcontext
            current = CURRENT.get()
            phase = (current[0].phase("retry_wait", role=current[1].get("role"), attempt=attempt + 1,
                                     reason="bounded semantic retry after " + exc.category)
                     if current else nullcontext())
            with phase:
                until = time.monotonic() + retry_delay_seconds
                while time.monotonic() < until:
                    checkpoint()
                    time.sleep(min(0.05, max(0, until - time.monotonic())))
        except Exception as exc:
            exc.protocol_errors = errors
            raise


def role_result(cls, obj):
    result = cls.from_dict(obj)
    result._protocol_errors = obj["_protocol_errors"]
    return result


def role_dict(result, payload):
    if getattr(result, "_protocol_errors", None):
        payload["_protocol_errors"] = result._protocol_errors
    return payload


def evidence_part(value, limit, *, missing=False):
    raw = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    unavailable = missing or (isinstance(value, str) and
        value.startswith("[loopcore]") and "unavailable" in value)
    upstream = isinstance(value, str) and "[loopcore] ..." in value and "chars elided" in value
    return dict(content=raw[:limit], original_length=len(raw),
                sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                truncated=len(raw) > limit or upstream, missing=unavailable,
                omitted_chars=max(0, len(raw) - limit),
                upstream_fragment=upstream)


def evidence_metadata(parts):
    return {name: {k: v for k, v in part.items() if k != "content"}
            for name, part in parts.items()}


def require_complete(parts):
    if any(p["missing"] or p["truncated"] for p in parts.values()):
        category = "EVIDENCE_MISSING" if any(p["missing"] for p in parts.values()) else "TRUNCATED"
        raise ProtocolError(category, "critical evidence incomplete within request bound",
                            evidence=evidence_metadata(parts))
