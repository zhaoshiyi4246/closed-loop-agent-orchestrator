"""Thin execution instrumentation. Facts only: never retry or decide a task."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import time

CURRENT = ContextVar("clao_phase", default=None)


class Diagnostics:
    def __init__(self, store, mission_id):
        self.store, self.mission_id = store, mission_id
        self.errors = []
        self._worker_facts = {}

    def _record(self, value, phase_id=None):
        try:
            return self.store.record_phase(self.mission_id, value, phase_id)
        except Exception as exc:
            # A projection failure must not repeat/alter an external effect.
            self.errors.append("diagnostic write failed: " + type(exc).__name__)
            del self.errors[:-10]
            return None

    def worker_fact(self, session_id, *, activity=None, confirmed_model=None, requested_model=None):
        import re
        if not isinstance(session_id, str):
            return
        old = self._worker_facts.get(session_id, {})
        value = dict(old, session_id=session_id)
        if activity is not None:
            value["activity"] = str(activity)[:100]
            if value["activity"] != old.get("activity"):
                value["activity_observed_since"] = time.time()
        if requested_model is not None:
            value["requested_model"] = requested_model
            value["passed_model"] = requested_model
        if isinstance(confirmed_model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", confirmed_model):
            value["confirmed_model"] = confirmed_model
            value["model_evidence"] = "AO conversation.modelReroute.toModel (conversation-level, not per-call timing)"
        if value == old:
            return
        self._worker_facts[session_id] = value
        fact = dict(phase="worker_execution", task_id=session_id, role="worker", status="observed",
                    reason="AO Session activity observation", attempt=None, started_epoch=None, ended_epoch=None,
                    elapsed_seconds=None, result=None, error_category=None, usage=None, cost=None,
                    transport="ao_rest", observed_at=time.time(), **value)
        self._record(fact)

    @contextmanager
    def phase(self, name, *, task_id=None, role=None, reason=None, attempt=1,
              requested_model=None, passed_model=None, transport=None):
        value = dict(phase=name, task_id=task_id, role=role, status="running",
                     reason=reason or ("executing " + name), attempt=attempt,
                     started_epoch=time.time(), ended_epoch=None, elapsed_seconds=None,
                     result=None, error_category=None, requested_model=requested_model,
                     passed_model=passed_model, confirmed_model=None, transport=transport,
                     usage=None, cost=None)
        identity = self._record(value)
        started = time.monotonic()
        token = CURRENT.set((self, value))
        try:
            yield value
        except BaseException as exc:
            value["status"] = "unknown" if not isinstance(exc, Exception) else "failed"
            cause = exc.__cause__ or exc
            value["error_category"] = getattr(exc, "category", type(cause).__name__)
            # Exception strings can contain argv, prompts or environment values.
            value["reason"] = "execution raised " + type(exc).__name__
            raise
        finally:
            CURRENT.reset(token)
            if value["status"] == "running":
                value["status"] = "completed"
            value.update(ended_epoch=time.time(), elapsed_seconds=time.monotonic() - started)
            if identity is not None:
                self._record(value, identity)


def phase_call(name, *, role=None):
    """Instrument existing boundaries; objects outside runtime may opt out."""
    def decorate(fn):
        @wraps(fn)
        def call(self, *args, **kwargs):
            diag = getattr(self, "diagnostics", None)
            if not isinstance(diag, Diagnostics):
                return fn(self, *args, **kwargs)
            task = getattr(self, "task", None)
            task_id = getattr(task, "task_id", None)
            if task_id is None and args:
                first = args[0]
                spec = getattr(first, "task_spec", None)
                task_id = (spec.get("task_id") if isinstance(spec, dict) else getattr(first, "task_id", None))
            with diag.phase(name, role=role, task_id=task_id) as fact:
                result = fn(self, *args, **kwargs)
                if hasattr(result, "verdict"):
                    fact["result"] = result.verdict
                elif hasattr(result, "status"):
                    fact["result"] = str(result.status)
                elif isinstance(result, bool):
                    fact["result"] = result
                return result
        return call
    return decorate


@contextmanager
def model_attempt(model, transport="codex_cli"):
    """Nested transport timing, not the elapsed time of an entire Mission."""
    current = CURRENT.get()
    if current is None:
        yield None
        return
    diag, parent = current
    parent["_attempt"] = parent.get("_attempt", 0) + 1
    with diag.phase("model_request", task_id=parent.get("task_id"), role=parent.get("role"),
                    attempt=parent["_attempt"], requested_model=model, passed_model=model,
                    transport=transport, reason="waiting for semantic model response") as fact:
        yield fact


def note_error(exc):
    current = CURRENT.get()
    if current is not None:
        _, fact = current
        fact.update(status="failed", error_category=type(exc).__name__, reason="read failed: " + type(exc).__name__)
