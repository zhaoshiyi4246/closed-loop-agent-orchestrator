"""Persistent state store for the closed-loop sidecar.

SQLite-backed (stdlib only). Provides idempotency across process restarts:

  - same AO event_id is never processed twice
  - same alert_id is never fired twice
  - same AuditResult never sent to Planner twice
  - same PlannerAction never executed twice

Also records project state-machine transitions, gate runs, tasks.

Tables are created on first connect. Tests pass a temp DB path and may wipe it.
This store is the ONLY persistence layer; it must not depend on AO's internal DB.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

def now_iso() -> str:
    """UTC ISO-8601 timestamp (local copy; avoids the event_normalizer dep)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  spec_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state_transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT,
  from_state TEXT,
  to_state TEXT,
  actor TEXT,
  reason TEXT,
  evidence_json TEXT,
  timestamp TEXT
);
CREATE TABLE IF NOT EXISTS processed_events (
  event_id TEXT PRIMARY KEY,
  payload_json TEXT,
  recorded_at TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
  alert_id TEXT PRIMARY KEY,
  payload_json TEXT,
  recorded_at TEXT
);
CREATE TABLE IF NOT EXISTS audits (
  audit_id TEXT PRIMARY KEY,
  task_id TEXT,
  payload_json TEXT,
  recorded_at TEXT
);
CREATE TABLE IF NOT EXISTS verifications (
  verify_id TEXT PRIMARY KEY,
  task_id TEXT,
  payload_json TEXT,
  recorded_at TEXT
);
CREATE TABLE IF NOT EXISTS missions (
  mission_id TEXT PRIMARY KEY,
  payload_json TEXT,
  recorded_at TEXT
);
CREATE TABLE IF NOT EXISTS planner_actions (
  action_id TEXT PRIMARY KEY,
  task_id TEXT,
  payload_json TEXT,
  recorded_at TEXT
);
CREATE TABLE IF NOT EXISTS executed_actions (
  action_id TEXT PRIMARY KEY,
  executed_at TEXT,
  result_json TEXT
);
CREATE TABLE IF NOT EXISTS gate_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT,
  command TEXT,
  cwd TEXT,
  exit_code INTEGER,
  started_at TEXT,
  ended_at TEXT,
  stdout TEXT,
  stderr TEXT,
  assessment_json TEXT
);
CREATE TABLE IF NOT EXISTS counters (
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS external_operations (
  operation_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  target TEXT NOT NULL,
  request_json TEXT NOT NULL,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  result_json TEXT NOT NULL DEFAULT '{}',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL
);
"""


class StateStore:
    def __init__(self, db_path: str | Path):
        self.path = str(db_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # check_same_thread=False: the store is shared by poll + SSE threads.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        columns = {r[1] for r in self._conn.execute("PRAGMA table_info(gate_runs)")}
        if "assessment_json" not in columns:
            self._conn.execute("ALTER TABLE gate_runs ADD COLUMN assessment_json TEXT")
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --------------------------------------------------- external effects
    def operation(self, operation_id: str) -> Optional[Dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT operation_id,kind,owner_id,target,request_json,status,attempts,"
                "result_json,evidence_json,updated_at FROM external_operations WHERE operation_id=?",
                (operation_id,)).fetchone()
            if row is None:
                return None
            out = dict(zip(("operation_id", "kind", "owner_id", "target", "request",
                            "status", "attempts", "result", "evidence", "updated_at"), row))
            for key in ("request", "result", "evidence"):
                out[key] = json.loads(out[key])
            return out

    def operations(self, owner_id: Optional[str] = None) -> List[Dict]:
        with self._lock:
            sql = "SELECT operation_id FROM external_operations"
            rows = self._conn.execute(sql + (" WHERE owner_id=?" if owner_id else ""),
                                      (owner_id,) if owner_id else ()).fetchall()
            return [self.operation(row[0]) for row in rows]

    def ensure_operation(self, operation_id: str, kind: str, owner_id: str,
                         target: str, request: Dict) -> Dict:
        """Commit intent before invocation. A reused identity cannot change its input.

        request contains hashes/correlation metadata, never the prompt/message.
        """
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO external_operations(operation_id,kind,owner_id,target,"
                "request_json,status,updated_at) VALUES(?,?,?,?,?,'NOT_STARTED',?)",
                (operation_id, kind, owner_id, target,
                 json.dumps(request, sort_keys=True), now_iso()))
        old = self.operation(operation_id)
        # A random correlation token is chosen by the first committed intent.
        expected = {k: v for k, v in request.items() if k != "marker"}
        actual = {k: v for k, v in old["request"].items() if k != "marker"}
        if (old["kind"], old["owner_id"], old["target"], actual) != (kind, owner_id, target, expected):
            raise ValueError("external operation identity/input conflict: " + operation_id)
        return old

    def operation_claim(self, operation_id: str, max_attempts: int = 3) -> bool:
        """Single durable claimant even with another Store/process on the same DB.

        IN_FLIGHT is written BEFORE invoking AO. A crash on either side of the
        invocation is intentionally ambiguous; no lease expiry authorizes retry.
        """
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            op = self.operation(operation_id)
            if op["status"] != "NOT_STARTED" or op["attempts"] >= max_attempts:
                return False
            if op["kind"] != "kill":
                mission = self._conn.execute("SELECT payload_json FROM missions WHERE mission_id=?",
                                             (op["owner_id"],)).fetchone()
                payload = json.loads(mission[0]) if mission else {}
                if payload.get("stop_request") or payload.get("state") in ("HUMAN", "FAILED", "MISSION_DONE"):
                    return False
                other = self._conn.execute(
                    "SELECT 1 FROM external_operations WHERE owner_id=? AND operation_id<>? "
                    "AND status IN ('IN_FLIGHT','UNKNOWN') LIMIT 1",
                    (op["owner_id"], operation_id)).fetchone()
                if other:
                    return False
            cur = self._conn.execute(
                "UPDATE external_operations SET status='IN_FLIGHT',attempts=attempts+1,updated_at=? "
                "WHERE operation_id=? AND status='NOT_STARTED'", (now_iso(), operation_id))
            return cur.rowcount == 1

    def operation_observe(self, operation_id: str, status: str, evidence: Dict,
                          result: Optional[Dict] = None, success_counters=()) -> Dict:
        if status not in ("NOT_STARTED", "IN_FLIGHT", "SUCCEEDED", "FAILED", "UNKNOWN"):
            raise ValueError("invalid external operation status")
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            old = self.operation(operation_id)
            # A late, weaker reconciliation cannot erase an acknowledged
            # spawn/send. Kill is different: a later AO restore invalidates
            # its current stop precondition and must be recorded as unknown.
            if old["kind"] != "kill" and old["status"] == "SUCCEEDED":
                return old
            history = old["evidence"]
            # Repeated identical read-only observations do not grow the record.
            if not history or history[-1]["fact"] != evidence:
                history.append({"at": now_iso(), "fact": evidence})
            values = old["result"] if result is None else result
            if status == "SUCCEEDED" and not old["result"].get("counters_applied"):
                for key in success_counters:
                    self._conn.execute(
                        "INSERT INTO counters(name,value) VALUES(?,1) "
                        "ON CONFLICT(name) DO UPDATE SET value=value+1", (key,))
                values["counters_applied"] = True
            elif old["result"].get("counters_applied"):
                values["counters_applied"] = True
            self._conn.execute(
                "UPDATE external_operations SET status=?,result_json=?,evidence_json=?,updated_at=? "
                "WHERE operation_id=?", (status, json.dumps(values), json.dumps(history), now_iso(), operation_id))
        return self.operation(operation_id)

    def request_mission_stop(self, mission_id: str) -> None:
        """Receipt is durable before any in-memory latch or external kill."""
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute("SELECT payload_json FROM missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            payload = json.loads(row[0]) if row else {}
            payload.setdefault("stop_request", {"requested_at": now_iso(), "source": "user"})
            self._conn.execute(
                "INSERT INTO missions(mission_id,payload_json,recorded_at) VALUES(?,?,?) "
                "ON CONFLICT(mission_id) DO UPDATE SET payload_json=excluded.payload_json,recorded_at=excluded.recorded_at",
                (mission_id, json.dumps(payload), now_iso()))

    def mission_stop_requested(self, mission_id: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT payload_json FROM missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            return bool(row and json.loads(row[0]).get("stop_request"))

    # ------------------------------------------------------------ tasks
    def record_task(self, task_id: str, spec_json: Dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO tasks(task_id,spec_json) VALUES(?,?)",
                (task_id, json.dumps(spec_json, ensure_ascii=False)))
            self._conn.commit()

    def load_task(self, task_id: str) -> Optional[Dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT spec_json FROM tasks WHERE task_id=?", (task_id,))
            r = cur.fetchone()
        return json.loads(r[0]) if r else None

    def all_task_ids(self) -> list:
        with self._lock:
            cur = self._conn.execute("SELECT task_id FROM tasks")
            return [r[0] for r in cur.fetchall()]

    # ------------------------------------------------------------ events
    def event_seen(self, event_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM processed_events WHERE event_id=?", (event_id,))
            return cur.fetchone() is not None

    def record_event(self, event_id: str, payload: Dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO processed_events(event_id,payload_json,recorded_at)"
                " VALUES(?,?,?)",
                (event_id, json.dumps(payload, ensure_ascii=False), now_iso()))
            self._conn.commit()

    # ------------------------------------------------------------ alerts
    def alert_seen(self, alert_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM alerts WHERE alert_id=?", (alert_id,))
            return cur.fetchone() is not None

    def record_alert(self, alert_id: str, payload: Dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO alerts(alert_id,payload_json,recorded_at)"
                " VALUES(?,?,?)",
                (alert_id, json.dumps(payload, ensure_ascii=False), now_iso()))
            self._conn.commit()

    # ------------------------------------------------------------ audits
    def audit_seen(self, audit_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM audits WHERE audit_id=?", (audit_id,))
            return cur.fetchone() is not None

    def record_audit(self, audit_id: str, task_id: str, payload: Dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO audits(audit_id,task_id,payload_json,recorded_at)"
                " VALUES(?,?,?,?)",
                (audit_id, task_id, json.dumps(payload, ensure_ascii=False),
                 now_iso()))
            self._conn.commit()

    # ------------------------------------------------------- verifications
    def verification_seen(self, verify_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM verifications WHERE verify_id=?", (verify_id,))
            return cur.fetchone() is not None

    def get_verification(self, verify_id: str) -> Optional[Dict]:
        """Return the recorded verification payload for ``verify_id``, or None.

        Used by crash-resume: when a verifier PASS was recorded but the
        DONE transition did not land (process killed in the narrow window
        between record_verification and _transition), re-entry can read the
        prior verdict instead of re-running the non-deterministic LLM.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT payload_json FROM verifications WHERE verify_id=?",
                (verify_id,))
            r = cur.fetchone()
            if not r:
                return None
            return self._verification_payload(r[0])

    @staticmethod
    def _verification_payload(raw: str) -> Dict:
        from .structured import parse_json, ProtocolError
        payload = parse_json(raw)
        if not isinstance(payload, dict):
            raise ProtocolError("SCHEMA", "saved verification is not an object")
        return payload

    def record_verification(self, verify_id: str, task_id: str,
                            payload: Dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO verifications(verify_id,task_id,payload_json,recorded_at)"
                " VALUES(?,?,?,?)",
                (verify_id, task_id, json.dumps(payload, ensure_ascii=False),
                 now_iso()))
            self._conn.commit()

    def latest_verification(self, task_id: str) -> Optional[Dict]:
        """Read final-review evidence for crash recovery; callers revalidate it."""
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM verifications WHERE task_id=? "
                "ORDER BY rowid DESC LIMIT 1", (task_id,)).fetchone()
            if row is None:
                return None
            # Corrupt persisted JSON must not be interpreted as no prior result.
            return self._verification_payload(row[0])

    # ---------------------------------------------------------- missions
    def record_mission(self, mission_id: str, payload: Dict) -> None:
        with self._lock:
            # Merge into any existing row (new keys win) instead of a blind
            # REPLACE: a terminal state written by request_stop() must survive
            # a later plan-only write from an unwinding in-flight tick
            # (real race, PV S9: stop during decompose -> the decompose
            # record_mission({"mission","plan"}) clobbered the HUMAN row and
            # the panel showed state "?").
            cur = self._conn.execute(
                "SELECT payload_json FROM missions WHERE mission_id=?",
                (mission_id,))
            row = cur.fetchone()
            merged: Dict = {}
            if row:
                try:
                    merged = json.loads(row[0])
                except (ValueError, TypeError):
                    merged = {}
            merged.update(payload)
            self._conn.execute(
                "INSERT OR REPLACE INTO missions(mission_id,payload_json,recorded_at)"
                " VALUES(?,?,?)",
                (mission_id, json.dumps(merged, ensure_ascii=False),
                 now_iso()))
            self._conn.commit()

    # Terminal states that must never be overwritten by a different state.
    _MISSION_TERMINAL = frozenset({"MISSION_DONE", "HUMAN", "FAILED"})

    def record_mission_state_atomic(self, mission_id: str, state: str,
                                    payload: Dict) -> bool:
        """Atomically record a state transition ONLY if the mission is not
        already in a terminal state (or is already in ``state``).

        Closes the check-then-act window in MissionController._set_state: the
        terminal-state check and the write happen under one store lock, so a
        mission thread writing MISSION_DONE and a panel thread writing HUMAN
        cannot both pass the check and have the loser clobber the winner. The
        first terminal write wins; later different-state writes are dropped.

        Returns True if the write landed, False if suppressed (already
        terminal with a different state).
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT payload_json FROM missions WHERE mission_id=?",
                (mission_id,))
            row = cur.fetchone()
            merged: Dict = {}
            if row:
                try:
                    merged = json.loads(row[0])
                except (ValueError, TypeError):
                    merged = {}
            cur_state = merged.get("state")
            if cur_state in self._MISSION_TERMINAL and cur_state != state:
                return False
            if merged.get("stop_request") and state != "HUMAN":
                return False
            merged.update(payload)
            merged["state"] = state
            self._conn.execute(
                "INSERT OR REPLACE INTO missions(mission_id,payload_json,recorded_at)"
                " VALUES(?,?,?)",
                (mission_id, json.dumps(merged, ensure_ascii=False),
                 now_iso()))
            self._conn.commit()
            return True

    # ------------------------------------------------------- planner actions
    def action_seen(self, action_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM planner_actions WHERE action_id=?", (action_id,))
            return cur.fetchone() is not None

    def record_action(self, action_id: str, task_id: str, payload: Dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO planner_actions(action_id,task_id,payload_json,recorded_at)"
                " VALUES(?,?,?,?)",
                (action_id, task_id, json.dumps(payload, ensure_ascii=False),
                 now_iso()))
            self._conn.commit()

    def action_executed(self, action_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM executed_actions WHERE action_id=?", (action_id,))
            return cur.fetchone() is not None

    def action_executed_result(self, action_id: str) -> Optional[Dict]:
        """Stored result payload of an executed action (for crash-resume)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT result_json FROM executed_actions WHERE action_id=?",
                (action_id,))
            row = cur.fetchone()
            return json.loads(row[0]) if row else None

    def latest_audit(self, task_id: str) -> Optional[Dict]:
        """Most recent audit payload for a task (planner crash-resume)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT payload_json FROM audits WHERE task_id=? "
                "ORDER BY rowid DESC LIMIT 1", (task_id,))
            row = cur.fetchone()
            return json.loads(row[0]) if row else None

    def latest_action(self, task_id: str) -> Optional[Dict]:
        """Most recent planner-action payload for a task (crash-resume)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT payload_json FROM planner_actions WHERE task_id=? "
                "ORDER BY rowid DESC LIMIT 1", (task_id,))
            row = cur.fetchone()
            return json.loads(row[0]) if row else None

    def mark_action_executed(self, action_id: str, result: Dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO executed_actions(action_id,executed_at,result_json)"
                " VALUES(?,?,?)",
                (action_id, now_iso(), json.dumps(result, ensure_ascii=False)))
            self._conn.commit()

    # ------------------------------------------------------------ transitions
    def record_transition(self, *, task_id: str, from_state: str,
                          to_state: str, actor: str, reason: str,
                          evidence: Dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO state_transitions(task_id,from_state,to_state,actor,reason,evidence_json,timestamp)"
                " VALUES(?,?,?,?,?,?,?)",
                (task_id, from_state, to_state, actor, reason,
                 json.dumps(evidence, ensure_ascii=False), now_iso()))
            self._conn.commit()

    def latest_state(self, task_id: str) -> Optional[str]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT to_state FROM state_transitions WHERE task_id=? "
                "ORDER BY id DESC LIMIT 1", (task_id,))
            row = cur.fetchone()
            return row[0] if row else None

    # ------------------------------------------------------------ gate
    def record_gate_run(self, *, task_id: str, command: str, cwd: str,
                       exit_code: Optional[int], started_at: str, ended_at: str,
                       stdout: str, stderr: str, assessment: Optional[Dict] = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO gate_runs(task_id,command,cwd,exit_code,started_at,ended_at,stdout,stderr,assessment_json)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (task_id, command, cwd, exit_code, started_at, ended_at,
                 stdout, stderr, json.dumps(assessment) if assessment is not None else None))
            self._conn.commit()
            return cur.lastrowid

    @staticmethod
    def gate_assessment(*, phase="task", command="unknown", integrity="unknown",
                        integrity_reason="", scope="unknown", scope_reason="") -> Dict:
        statuses = (command, integrity, scope)
        overall = ("fail" if "fail" in statuses else
                   "unknown" if "unknown" in statuses else
                   "not_run" if "not_run" in statuses else
                   "pass" if all(s in ("pass", "not_applicable") for s in statuses)
                   else "unknown")
        return {"phase": phase, "command_status": command,
                "integrity": {"status": integrity, "reason": integrity_reason},
                "scope": {"status": scope, "reason": scope_reason}, "overall": overall}

    def annotate_gate_runs(self, record_ids: list, assessment: Dict) -> None:
        with self._lock:
            self._conn.executemany("UPDATE gate_runs SET assessment_json=? WHERE id=?",
                                   [(json.dumps(assessment, ensure_ascii=False), i)
                                    for i in record_ids])
            self._conn.commit()

    def record_gate_scope(self, run, *, status: str, reason: str = "") -> None:
        """Persist the Controller's scope finding on exactly this Gate batch."""
        ids = getattr(run, "record_ids", None)
        if not isinstance(ids, list) or not ids:
            return
        with self._lock:
            for record_id in ids:
                row = self._conn.execute(
                    "SELECT assessment_json FROM gate_runs WHERE id=?", (record_id,)).fetchone()
                if not row or not row[0]:
                    continue
                old = json.loads(row[0])
                assessment = self.gate_assessment(
                    phase=old["phase"], command=old["command_status"],
                    integrity=old["integrity"]["status"],
                    integrity_reason=old["integrity"]["reason"],
                    scope=status, scope_reason=reason)
                self._conn.execute("UPDATE gate_runs SET assessment_json=? WHERE id=?",
                                   (json.dumps(assessment, ensure_ascii=False), record_id))
            self._conn.commit()

    @staticmethod
    def query_gate_runs(conn: sqlite3.Connection, limit: int = 12) -> Dict:
        """Panel DTO from the existing table; reading never migrates old stores.

        Missing historical assessment is unknown. SQLite/JSON failures are
        explicit read_error, never a successful empty list or guessed PASS.
        """
        try:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(gate_runs)")}
            assessment_column = "assessment_json" if "assessment_json" in columns else "NULL"
            cursor = conn.execute(
                "SELECT id,task_id,command,cwd,exit_code,started_at,ended_at,stdout,stderr," +
                assessment_column + " FROM gate_runs ORDER BY id DESC LIMIT ?", (limit,))
            records = []
            for row in cursor:
                item = dict(zip(("id", "task_id", "command", "cwd", "exit_code",
                                 "started_at", "ended_at", "stdout", "stderr"), row[:9]))
                legacy = row[9] is None
                assessment = (StateStore.gate_assessment(
                    phase="unknown", command="unknown" if row[4] is None else
                    "pass" if row[4] == 0 else "fail") if legacy
                              else json.loads(row[9]))
                if (not isinstance(assessment, dict)
                        or assessment.get("phase") not in ("task", "baseline", "final", "unknown")
                        or assessment.get("command_status") not in ("pass", "fail", "not_run", "unknown")):
                    raise ValueError("invalid Gate assessment")
                for key in ("integrity", "scope"):
                    part = assessment.get(key)
                    if (not isinstance(part, dict) or part.get("status") not in
                            ("pass", "fail", "not_run", "unknown", "not_applicable")
                            or not isinstance(part.get("reason"), str)):
                        raise ValueError("invalid Gate " + key)
                expected = StateStore.gate_assessment(
                    phase=assessment["phase"], command=assessment["command_status"],
                    integrity=assessment["integrity"]["status"],
                    scope=assessment["scope"]["status"])["overall"]
                if assessment.get("overall") != expected:
                    raise ValueError("inconsistent Gate overall result")
                if not legacy and assessment["command_status"] == "pass" and row[4] != 0:
                    raise ValueError("inconsistent Gate command result")
                item.update(assessment)
                item["command_result"] = ("not_run" if row[4] is None else
                                          "pass" if row[4] == 0 else "fail")
                item["historical_fields_missing"] = legacy
                records.append(item)
            return {"status": "ok" if records else "no_records", "records": records,
                    "error": None}
        except (sqlite3.Error, ValueError, TypeError) as exc:
            return {"status": "read_error", "records": [], "error": str(exc)}

    # ------------------------------------------------------------ counters
    def counter_get(self, name: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "SELECT value FROM counters WHERE name=?", (name,))
            row = cur.fetchone()
            return row[0] if row else 0

    def counter_incr(self, name: str) -> int:
        with self._lock:
            self._conn.execute(
                "INSERT INTO counters(name,value) VALUES(?,1) "
                "ON CONFLICT(name) DO UPDATE SET value=value+1", (name,))
            self._conn.commit()
            cur = self._conn.execute(
                "SELECT value FROM counters WHERE name=?", (name,))
            return cur.fetchone()[0]

    def counter_set(self, name: str, value: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO counters(name,value) VALUES(?,?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                (name, int(value)))
            self._conn.commit()

    def counter_delete_prefix(self, prefix: str) -> int:
        """Delete all counters whose name starts with `prefix` (used to reset
        same-alert escalation counters after a successful audit — a fixed
        worker must not carry a lifetime escalation debt, review 簇二)."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM counters WHERE name LIKE ?", (prefix + "%",))
            self._conn.commit()
            return cur.rowcount
