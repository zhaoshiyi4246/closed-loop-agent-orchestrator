"""Bounded, explicitly invoked live semantic verification using synthetic inputs.

Never run from the offline suite. The ledger reserves worst-case cost before
each socket attempt, including failures, and contains no keys or prompt text.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'clao' / 'src'))
import yaml
from loopcore.bigmodel import BigModelTransport
from loopcore.diagnostics import Diagnostics
from loopcore.model_profiles import SERVICE, KIMI_SERVICE
from loopcore.verifier import CodexCliVerifierProvider, VerifierInput
from loopcore.auditor import CodexCliAuditorProvider, EvidenceBundle
from loopcore.planner_adapter import CodexCliPlannerProvider
from loopcore.mission_contracts import AuditResult, AuditDecision

# Official CNY / million tokens, checked 2026-09-21. Kimi reserves both
# uncached input (20) and the more expensive 1h cache write (40).
PRICES = {(SERVICE, 'glm-5.3'): (8, 28), (KIMI_SERVICE, 'kimi-k3'): (60, 100)}


class Facts:
    def __init__(self): self.rows = []
    def record_phase(self, mission, value, phase_id=None):
        self.rows.append(copy.deepcopy(value))
        return len(self.rows)


class BudgetedTransport(BigModelTransport):
    def __init__(self, profile, ledger, case):
        super().__init__(profile)
        self.ledger, self.case = ledger, case
    def _exchange(self, body, key):
        data = json.loads(body)
        rate_in, rate_out = PRICES[(self.service, self.profile['model'])]
        # Text-only input: use encoded request bytes plus generous framing
        # overhead as an upper bound, not a characters/token estimate.
        input_upper = len(body) + 2048
        output_upper = data.get('max_tokens', data.get('max_completion_tokens'))
        reserve = (input_upper * rate_in + output_upper * rate_out) / 1_000_000
        ledger = json.loads(self.ledger.read_text('utf-8')) if self.ledger.exists() else {'attempts': []}
        rows = ledger['attempts']
        if len(rows) >= 40 or sum(r['reserved_cny'] for r in rows) + reserve > 20:
            raise RuntimeError('Live test budget exhausted; no request sent')
        if input_upper > 24000 or reserve > 3:
            raise RuntimeError('Synthetic request exceeds per-attempt bound; no request sent')
        row = dict(number=len(rows) + 1, at=datetime.now(timezone.utc).isoformat(),
                   service=self.service, model=self.profile['model'], case=self.case,
                   input_tokens_upper=input_upper, output_tokens_upper=output_upper,
                   reserved_cny=round(reserve, 6), outcome='unconfirmed', http_status=None)
        rows.append(row)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), 'utf-8')
        start = time.monotonic()
        try:
            status, raw = super()._exchange(body, key)
            row['http_status'] = status
            row['outcome'] = 'http_response'
            return status, raw
        except Exception as exc:
            row['outcome'] = getattr(exc, 'category', type(exc).__name__)
            raise
        finally:
            row['elapsed_seconds'] = round(time.monotonic() - start, 3)
            self.ledger.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), 'utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--model')
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--case', choices=['correct', 'defect'], required=True)
    parser.add_argument('--role', choices=['verifier', 'auditor', 'planner'], default='verifier')
    args = parser.parse_args()
    lock = args.ledger.with_suffix('.lock')
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('x'):
        pass
    try:
        previous_count = len(json.loads(args.ledger.read_text('utf-8'))['attempts']) if args.ledger.exists() else 0
        config = yaml.safe_load(args.config.read_text('utf-8'))
        profile = copy.deepcopy(next(p for p in config['model_profiles'] if p['id'] == args.profile))
        profile.update(timeout_seconds=120, max_attempts=1, retry_delay_seconds=0)
        if args.model: profile['model'] = args.model
        if (profile['service'], profile['model']) not in PRICES:
            raise RuntimeError('Service/model price has not been admitted')
        if profile['service'] == SERVICE:
            profile.update(thinking='enabled', reasoning_effort='low', max_tokens=8192)
        else:
            profile.update(reasoning_effort='low', max_completion_tokens=8192)
        code = 'return a + b' if args.case == 'correct' else 'return a - b'
        inp = VerifierInput(task_spec={
            'task_id': 'SYNTHETIC-ADD', 'objective': 'Implement integer addition',
            'acceptance_criteria': [{'id': 'AC1', 'description': 'add(a,b) returns the sum of two integers, including add(7,2)==9 and add(-2,5)==3'}]},
            diff='diff --git a/add.py b/add.py\nnew file mode 100644\n--- /dev/null\n+++ b/add.py\n@@ -0,0 +1,2 @@\n+def add(a, b):\n+    '+code+'\n',
            gate_output='Syntax compilation passed; no behavioral checks were run.',
            changed_paths=['add.py'], deterministic_findings=[])
        facts = Facts()
        transport = BudgetedTransport(profile, args.ledger, args.role + ':' + args.case)
        provider = {'verifier': CodexCliVerifierProvider, 'auditor': CodexCliAuditorProvider,
                    'planner': CodexCliPlannerProvider}[args.role](model=profile['model'], transport=transport)
        provider.diagnostics = Diagnostics(facts, 'SYNTHETIC-ADD')
        expected = {'verifier': ('PASS', 'FAIL'), 'auditor': ('PASS', 'LOCAL_FIX'),
                    'planner': ('CANDIDATE_DONE', 'SEND_LOCAL_FIX')}[args.role][args.case == 'defect']
        try:
            if args.role == 'verifier':
                result = provider.verify(inp, 'VERIFY-SYNTHETIC-ADD')
                verdict = result.verdict
            elif args.role == 'auditor':
                result = provider.audit(EvidenceBundle(task_spec=inp.task_spec, alert=None,
                    git_diff=inp.diff, test_output=inp.gate_output, audit_type='COMPLETION'), 'AUDIT-SYNTHETIC-ADD')
                verdict = result.decision
            else:
                audit = AuditResult(audit_id='AUDIT-SYNTHETIC-ADD', task_id='SYNTHETIC-ADD',
                    decision=AuditDecision.PASS if args.case == 'correct' else AuditDecision.LOCAL_FIX,
                    evidence=[{'type': 'code_review', 'summary': 'Reviewed the synthetic two-line integer-addition implementation.'}],
                    diagnosis='Addition is implemented correctly.' if args.case == 'correct' else 'add.py subtracts b; add(7,2) returns 5 instead of 9.',
                    recommended_action='' if args.case == 'correct' else 'Change add.py to add the integers; retain the scope and acceptance checks.',
                    confidence=0.99, failed_criteria=[] if args.case == 'correct' else ['AC1'])
                task = {**inp.task_spec, 'allowed_paths': ['add.py'], 'forbidden_paths': ['check.py']}
                result = provider.plan(audit, task, 'PLAN-SYNTHETIC-ADD', target_session_id='synthetic-worker', remaining_replans=0)
                verdict = result.action
            quality = verdict == expected
            if args.role == 'planner' and args.case == 'defect':
                quality = quality and result.target_session_id == 'synthetic-worker' and bool(result.message and 'add' in result.message.lower())
            summary = {'verdict': verdict, 'expected': expected, 'quality_pass': quality}
        except Exception as exc:
            summary = {'quality_pass': False, 'category': getattr(exc, 'category', type(exc).__name__)}
        attempt = next((r for r in reversed(facts.rows) if r.get('phase') == 'model_request'), {})
        summary.update(role=args.role, case=args.case, model=profile['model'], usage=attempt.get('usage'), confirmed_model=attempt.get('confirmed_model'))
        print(json.dumps(summary, ensure_ascii=False))
        if args.ledger.exists():
            ledger = json.loads(args.ledger.read_text('utf-8'))
            if len(ledger['attempts']) > previous_count:
                ledger['attempts'][-1]['validation'] = summary
                args.ledger.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), 'utf-8')
        return 0 if summary['quality_pass'] else 1
    finally:
        lock.unlink()


if __name__ == '__main__':
    raise SystemExit(main())
