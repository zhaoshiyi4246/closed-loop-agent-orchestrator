"""External native CLI process substitute. No network or real authentication."""
import json
import os
from pathlib import Path
import sys
import time

sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
if '--version' in sys.argv:
    print('2.1.205 (Claude Code)')
    raise SystemExit(0)
prompt = sys.stdin.read()
trace = Path(os.environ['CLAO_TEST_NATIVE_TRACE'])
with trace.open('a', encoding='utf-8') as stream:
    stream.write(json.dumps({'argv': sys.argv[1:], 'prompt': prompt,
                            'base_url': os.environ.get('ANTHROPIC_BASE_URL'),
                            'codex_key': bool(os.environ.get('CODEX_API_KEY')),
                            'claude_key': bool(os.environ.get('ANTHROPIC_AUTH_TOKEN'))}) + '\n')
if os.environ.get('CLAO_TEST_NATIVE_DELAY'):
    time.sleep(float(os.environ['CLAO_TEST_NATIVE_DELAY']))
response = json.loads(os.environ['CLAO_TEST_NATIVE_RESPONSE'])
if response == 'auto-verifier':
    inp = json.loads(prompt.split('# VerifierInput\n', 1)[1])
    response = {'verify_id': inp['verify_id'], 'task_id': inp['task_id'], 'verdict': 'PASS',
                'ac_checks': [{'ac_id': a['id'], 'verdict': 'PASS', 'note': 'native process fixture evidence'}
                              for a in inp['verifier_input']['task_spec']['acceptance_criteria']],
                'anti_gaming': [], 'summary': 'isolated native reply'}
    if 'exec' not in sys.argv:
        response = {'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': response}
if 'exec' in sys.argv:
    assert '--ignore-user-config' in sys.argv and 'shell_environment_policy.inherit="none"' in sys.argv
    output = Path(sys.argv[sys.argv.index('--output-last-message') + 1])
    output.write_text(json.dumps(response), encoding='utf-8')
    print('native output')
else:
    assert sys.argv[sys.argv.index('--tools') + 1] == ''
    assert sys.argv[sys.argv.index('--setting-sources') + 1] == ''
    assert '--no-session-persistence' in sys.argv and '--bare' in sys.argv
    assert '--max-turns' in sys.argv and sys.argv[sys.argv.index('--max-turns') + 1] == '1'
    print(json.dumps(response))
