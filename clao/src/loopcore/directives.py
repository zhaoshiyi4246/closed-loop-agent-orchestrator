"""Durable command receipts and real consumer boundaries in the existing Store."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import re
import uuid


@dataclass
class Directive:
    target: str
    text: str
    at: str
    command_id: str
    status: str
    reason: str


class DirectiveChannel:
    def __init__(self, store, mission_id):
        self.store, self.mission_id = store, mission_id

    def post(self, target, text, command_id=None):
        if not isinstance(target, str) or not isinstance(text, str) or not text.strip():
            raise ValueError('target and nonempty text are required')
        target, text = target.strip(), text.strip()
        if len(text) > 8000:
            raise ValueError('directive exceeds 8000 characters; no silent truncation')
        command_id = ('CMD-' + uuid.uuid4().hex) if command_id is None else command_id
        if not isinstance(command_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', command_id):
            raise ValueError('invalid command_id')
        rejection = None
        if target not in ('planner', 'auditor', 'verifier'):
            if target.startswith('worker:'):
                session = target[7:]
                tasks = [self.store.load_task(t) or {} for t in self.store.all_task_ids()]
                if not session or not any(t.get('subtask_of') == self.mission_id and t.get('worker_session_id') == session for t in tasks):
                    rejection = 'Worker target does not belong to this Mission'
            else:
                rejection = 'target has no semantic input consumer (Observer/Gate are deterministic)'
        row = self.store.receive_directive(self.mission_id, command_id, target, text, rejection)
        return Directive(**{key: row[key] for key in Directive.__dataclass_fields__})

    def records(self):
        return self.store.directives(self.mission_id)

    def pending_count(self):
        return sum(r['status'] == 'received' for r in self.records())

    def for_role(self, role):
        return [r for r in self.records() if r['status'] != 'rejected'
                and (r['target'] == role or role == 'planner')]

    @staticmethod
    def text(row, role):
        prefix = '[用户指令 %s]' % row['at'][:19]
        if row['target'] != role:
            prefix = '[镜像·发给 %s] %s' % (row['target'], prefix)
        return prefix + ' ' + row['text']

    def notes(self, role):
        return [self.text(row, role) for row in self.for_role(role)]

    @contextmanager
    def consume(self, role, consumer, rows=None):
        # Persist ambiguity BEFORE entering the actual provider call. If the
        # process dies here, input delivery is not guessed or blindly retried.
        rows = self.for_role(role) if rows is None else rows
        from .action_executor import ExternalOperationUnknown
        if any(r['consumers'].get(consumer, {}).get('status') == 'unknown' for r in rows):
            raise ExternalOperationUnknown('directive consumer completion unknown: ' + consumer)
        pending = [r for r in rows if consumer not in r['consumers']]
        for row in pending:
            self.store.directive_consumer(row['command_id'], consumer, 'unknown',
                'entering actual input call; completion not yet confirmed', primary=row['target'] == role)
        try:
            yield [self.text(r, role) for r in rows]
        except BaseException:
            raise
        else:
            for row in pending:
                self.store.directive_consumer(row['command_id'], consumer, 'applied',
                    'input consumed by provider call; not a claim of task completion', primary=row['target'] == role)
