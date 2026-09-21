"""Explicit live-test bootstrap; never included in the product runtime.

Runs the unchanged native semantic bridge with per-socket budget accounting.
No keys, request bodies or response text are written to the ledger.
"""
import json
import math
import os
from pathlib import Path
import runpy
import sys
import time
import uuid
from datetime import datetime, timezone


def accounted_micros(row):
    """Conservative charge bound; immutable pre-request reservations stay intact.

    Official chat usage includes every cached/write/uncached input token. Charge
    ALL input at 20+40 CNY/M and output at 100; never infer a bill or cache discount.
    Unknown/error rows retain their whole reservation and existing service freeze.
    """
    reserved = row.get('reserved_cny')
    if type(reserved) not in (int, float) or not math.isfinite(reserved) or reserved < 0:
        raise ValueError('Invalid original cost reservation')
    micros = round(reserved * 1_000_000)
    if row.get('service') != 'moonshot_cn' or row.get('outcome') not in ('completed', 'http_response') or row.get('case_frozen'):
        return micros
    validation = row.get('validation') or {}
    if not isinstance(validation, dict): raise ValueError('Invalid validation record')
    usage = row.get('usage', validation.get('usage'))
    confirmed = row.get('confirmed_model', validation.get('confirmed_model'))
    upper_in, upper_out = row.get('input_tokens_upper'), row.get('output_tokens_upper')
    if (row.get('model') != 'kimi-k3' or confirmed != 'kimi-k3' or row.get('http_status') != 200
            or type(upper_in) is not int or not 2048 <= upper_in <= 24000
            or type(upper_out) is not int or not 1 <= upper_out <= 8192
            or abs(reserved * 1_000_000 - (upper_in * 60 + upper_out * 100)) > 0.00001
            or not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0
                for k in ('prompt_tokens','completion_tokens','total_tokens'))
            or usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']
            or usage['prompt_tokens'] > upper_in or usage['completion_tokens'] > upper_out):
        raise ValueError('Confirmed cost facts are invalid; no new request admitted')
    return usage['prompt_tokens'] * 60 + usage['completion_tokens'] * 100


def accounted_total_micros(ledger):
    return sum(accounted_micros(row) for row in ledger['attempts'])


def service_ready(ledger):
    if ledger.get('frozen'): return False
    for row in ledger['attempts']:
        if row.get('service') != 'moonshot_cn': continue
        validation = row.get('validation') or {}
        if not isinstance(validation, dict): return False
        if (row.get('case_frozen') or row.get('outcome') not in ('completed', 'http_response')
                or row.get('http_status') != 200
                or row.get('confirmed_model', validation.get('confirmed_model')) != 'kimi-k3'):
            return False
    return True


def mutate_ledger(ledger, callback):
    """Short exclusive transaction, compatible with the Node transport lock."""
    ledger = Path(ledger)
    lock = ledger.with_suffix('.lock')
    for _ in range(100):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            break
        except FileExistsError:
            time.sleep(.01)
    else:
        raise RuntimeError('live ledger is busy; no request sent')
    temporary = ledger.with_name(ledger.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        data = json.loads(ledger.read_text('utf-8'))
        value = callback(data)
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, ledger)
        return value
    finally:
        temporary.unlink(missing_ok=True)
        lock.unlink()


def create_exchange(ledger, case, original):
    def mutate(callback):
        return mutate_ledger(ledger, callback)

    def exchange(self, body, key):
        request = json.loads(body)
        if self.service != 'moonshot_cn' or self.profile['endpoint'] != 'https://api.moonshot.cn/v1/chat/completions' or request.get('model') != 'kimi-k3':
            raise RuntimeError('live service or model is not admitted')
        output = request.get('max_completion_tokens')
        upper = len(body) + 2048
        if type(output) is not int or not 0 < output <= 2048 or upper > 24000 or request.get('stream') is not False or request.get('tools') or 'max_tokens' in request:
            raise RuntimeError('live semantic request exceeds admitted bounds')
        reserve = round((upper * 60 + output * 100) / 1_000_000, 6)
        def reserve_row(data):
            if not service_ready(data):
                raise RuntimeError('live service frozen after unconfirmed or failed result')
            rows = data['attempts']
            if any(r.get('case') == case for r in rows) or len(rows) >= 40 or accounted_total_micros(data) + round(reserve * 1_000_000) > 20_000_000:
                raise RuntimeError('live budget exhausted; no request sent')
            number = len(rows) + 1
            rows.append(dict(number=number, at=datetime.now(timezone.utc).isoformat(),
                service='moonshot_cn', model='kimi-k3', case=case,
                input_tokens_upper=upper, output_tokens_upper=output,
                reserved_cny=reserve, outcome='unconfirmed', http_status=None))
            return number
        number = mutate(reserve_row)
        start = time.monotonic()
        result = dict(outcome='unconfirmed', http_status=None)
        try:
            status, raw = original(self, body, key)
            result['http_status'] = status
            if status != 200 or key.encode() in raw:
                raise RuntimeError('live semantic response rejected')
            envelope = json.loads(raw)
            if envelope.get('model') != 'kimi-k3':
                raise RuntimeError('live model identity unconfirmed')
            usage = envelope.get('usage', {})
            keys = ('prompt_tokens', 'completion_tokens', 'total_tokens')
            if not isinstance(usage, dict) or not all(type(usage.get(k)) is int and usage[k] >= 0 for k in keys):
                raise RuntimeError('live usage unconfirmed')
            if usage['prompt_tokens'] > upper or usage['completion_tokens'] > output or usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']:
                raise RuntimeError('live usage exceeds admitted bounds')
            result.update(outcome='http_response', confirmed_model='kimi-k3', usage={k: usage[k] for k in keys})
            return status, raw
        finally:
            result['elapsed_seconds'] = round(time.monotonic() - start, 3)
            def finish(data):
                row = next(r for r in data['attempts'] if r['number'] == number)
                row.update(result)
                if result['outcome'] != 'http_response': data['frozen'] = True
            mutate(finish)

    return exchange


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / 'clao' / 'src'))
    from loopcore import bigmodel
    ledger = Path(os.environ['CLAO_LIVE_LEDGER'])
    case = os.environ['CLAO_LIVE_CASE'] + ':semantic'

    bigmodel.BigModelTransport._exchange = create_exchange(ledger, case, bigmodel.BigModelTransport._exchange)
    sys.argv = ['loopcore.ao_legacy']
    runpy.run_module('loopcore.ao_legacy', run_name='__main__')


if __name__ == '__main__':
    main()
