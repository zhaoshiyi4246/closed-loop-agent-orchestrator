import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createBudgetFetch } from './kimi-budget-transport.mjs';

const endpoint = 'https://api.moonshot.cn/v1/chat/completions';
const fakeKey = 'synthetic-not-a-real-key';
const usage = { prompt_tokens: 17, completion_tokens: 8, total_tokens: 25 };
const facts = (extra = {}) => ({ model: 'kimi-k3', choices: [], usage, ...extra });
const encoder = new TextEncoder();
function request(extra = {}, other = {}) {
  return {
    method: 'POST', headers: { authorization: `Bearer ${fakeKey}`, 'content-type': 'application/json' },
    body: JSON.stringify({ model: 'kimi-k3', messages: [{ role: 'user', content: 'synthetic addition' }],
      max_completion_tokens: 2048, stream: true, stream_options: { include_usage: true }, ...extra }), ...other,
  };
}
const sse = (extra = {}) => `data: ${JSON.stringify(facts(extra))}\n\ndata: [DONE]\n\n`;
function response(text = sse(), { status = 200, headers = {}, split = false } = {}) {
  return {
    status, headers: { 'content-type': 'text/event-stream', ...headers },
    body: (async function* () {
      if (split) for (const byte of encoder.encode(text)) yield new Uint8Array([byte]);
      else yield encoder.encode(text);
    })(),
  };
}
async function fixture(t, options = {}) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'clao-kimi-transport-'));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const ledgerPath = path.join(dir, 'live-ledger.json');
  const calls = [];
  const fetch = createBudgetFetch({ ledgerPath, caseName: 'native-kimi:test', apiKey: fakeKey,
    send: async (input) => { calls.push(input); return response(); }, ...options });
  return { dir, ledgerPath, fetch, calls, ledger: async () => JSON.parse(await fs.readFile(ledgerPath, 'utf8')) };
}
const drain = async (fetch, req = request()) => (await fetch(endpoint, req)).text();

test('SSE preserves bytes, accounts before send and stores only safe facts', async (t) => {
  const f = await fixture(t);
  const fetch = createBudgetFetch({ ledgerPath: f.ledgerPath, caseName: 'native-kimi:stream', apiKey: fakeKey,
    send: async (input) => {
      const rows = (await f.ledger()).attempts;
      assert.equal(rows.length, 1); assert.equal(rows[0].outcome, 'unconfirmed');
      assert.equal(input.headers.get('accept-encoding'), 'identity');
      return response(sse({ choices: [{ index: 0, delta: { content: 'private synthetic response' } }] }), { split: true });
    } });
  assert.match(await drain(fetch), /private synthetic response/);
  const ledger = await f.ledger(); const row = ledger.attempts[0];
  assert.equal(row.outcome, 'completed'); assert.equal(row.confirmed_model, 'kimi-k3');
  assert.deepEqual(row.usage, usage); assert.equal(row.http_status, 200);
  assert.equal(row.input_tokens_upper, Buffer.byteLength(request().body) + 2048);
  const serialized = JSON.stringify(ledger);
  for (const value of [fakeKey, 'private synthetic response', 'synthetic addition', 'authorization']) assert.ok(!serialized.includes(value));
  assert.deepEqual(await fs.readdir(f.dir), ['live-ledger.json']);
});

test('JSON response and existing Python success ledger remain compatible', async (t) => {
  const f = await fixture(t, { send: async () => response(JSON.stringify(facts()), { headers: { 'content-type': 'application/json' } }) });
  await fs.writeFile(f.ledgerPath, JSON.stringify({ attempts: [{ number: 1, service: 'moonshot_cn', model: 'kimi-k3',
    reserved_cny: 8.0988, outcome: 'http_response', http_status: 200, validation: { confirmed_model: 'kimi-k3' } }] }));
  assert.deepEqual(JSON.parse(await drain(f.fetch)), facts());
  assert.equal((await f.ledger()).attempts[1].number, 2);
});

test('invalid identities, media, tools and final caps never send or create a ledger', async (t) => {
  const f = await fixture(t);
  for (const [url, req] of [
    [endpoint.replace('.cn', '.ai'), request()], [endpoint + '?x=1', request()],
    [endpoint, request({ model: 'other' })], [endpoint, request({ max_tokens: 3 })],
    [endpoint, request({ max_completion_tokens: 2049 })], [endpoint, request({ max_completion_tokens: 2.5 })],
    [endpoint, request({ n: 2 })], [endpoint, request({ messages: [{ role: 'user', content: [{ type: 'image_url', image_url: 'data:image/png;base64,AA==' }] }] })],
    [endpoint, request({ tools: [{ type: 'function', function: { name: 'Bash', parameters: {} } }] })],
    [endpoint, request({ messages: [{ role: 'user', content: 'x'.repeat(32000) }] })],
    [endpoint, request({ messages: [{ role: 'user', content: fakeKey }] })],
    [endpoint, request({}, { headers: { authorization: 'Bearer other', 'content-type': 'application/json' } })],
  ]) await assert.rejects(f.fetch(url, req), /CLAO live transport/);
  assert.equal(f.calls.length, 0); assert.deepEqual(await fs.readdir(f.dir), []);
});

test('Read/Write/Edit tool schemas and history are allowed', async (t) => {
  const f = await fixture(t);
  await drain(f.fetch, request({ tools: ['Read', 'Write', 'Edit'].map((name) => ({ type: 'function', function: { name, parameters: { type: 'object' } } })),
    messages: [{ role: 'assistant', tool_calls: [{ id: 'tool-1', type: 'function', function: { name: 'Read', arguments: '{"path":"add.py"}' } }] },
      { role: 'tool', tool_call_id: 'tool-1', content: 'synthetic file' }] }));
  assert.equal(f.calls.length, 1);
});

test('24000-token reservation boundary accepts exact UTF-8 bytes and rejects one byte more', async (t) => {
  const f = await fixture(t);
  const empty = request({ messages: [{ role: 'user', content: '' }] });
  const padding = 24000 - 2048 - Buffer.byteLength(empty.body, 'utf8');
  const exact = request({ messages: [{ role: 'user', content: 'x'.repeat(padding) }] });
  assert.equal(Buffer.byteLength(exact.body, 'utf8') + 2048, 24000);
  await drain(f.fetch, exact);
  const row = (await f.ledger()).attempts[0];
  assert.equal(row.input_tokens_upper, 24000);
  assert.equal(row.reserved_cny, 1.6448);
  await assert.rejects(drain(f.fetch, request({ messages: [{ role: 'user', content: 'x'.repeat(padding + 1) }] })), /input_bound_exceeded/);
  // UTF-8 bytes, not JavaScript character length, determine the bound.
  await assert.rejects(drain(f.fetch, request({ messages: [{ role: 'user', content: 'x'.repeat(padding - 1) + '中' }] })), /input_bound_exceeded/);
  assert.equal(f.calls.length, 1);
  assert.equal((await f.ledger()).attempts.length, 1);
});

test('a case permits exactly three attempts across factory restarts', async (t) => {
  const f = await fixture(t);
  for (let i = 0; i < 3; i++) await drain(f.fetch);
  await assert.rejects(drain(f.fetch), /case_budget_exhausted/);
  const restarted = createBudgetFetch({ ledgerPath: f.ledgerPath, caseName: 'native-kimi:test', apiKey: fakeKey,
    send: async () => assert.fail('fourth case attempt opened a socket') });
  await assert.rejects(drain(restarted), /case_budget_exhausted/);
  assert.equal(f.calls.length, 3);
  assert.equal((await f.ledger()).attempts.length, 3);
  const nextCase = createBudgetFetch({ ledgerPath: f.ledgerPath, caseName: 'native-kimi:next', apiKey: fakeKey,
    send: async () => response() });
  await drain(nextCase);
  assert.equal((await f.ledger()).attempts.length, 4);
});

test('attempt and money boundaries refuse before socket; exact money boundary succeeds', async (t) => {
  const f = await fixture(t);
  const old = { service: 'moonshot_cn', reserved_cny: 0, http_status: 200, outcome: 'completed', confirmed_model: 'kimi-k3' };
  await fs.writeFile(f.ledgerPath, JSON.stringify({ attempts: Array.from({ length: 40 }, () => old) }));
  await assert.rejects(drain(f.fetch), /budget_exhausted/); assert.equal(f.calls.length, 0);
  await fs.writeFile(f.ledgerPath, JSON.stringify({ attempts: [{ ...old, reserved_cny: 19.999999 }] }));
  await assert.rejects(drain(f.fetch), /budget_exhausted/); assert.equal(f.calls.length, 0);
  const reserve = ((Buffer.byteLength(request().body) + 2048) * 60 + 2048 * 100) / 1e6;
  await fs.writeFile(f.ledgerPath, JSON.stringify({ attempts: [{ ...old, reserved_cny: 20 - reserve }] }));
  await drain(f.fetch); assert.equal(f.calls.length, 1);
  assert.equal(Math.round((await f.ledger()).attempts.reduce((sum, row) => sum + row.reserved_cny, 0) * 1e6), 20000000);
});

test('concurrent factories serialize durable attempt numbers with no lost rows', async (t) => {
  const f = await fixture(t);
  const other = createBudgetFetch({ ledgerPath: f.ledgerPath, caseName: 'native-kimi:other', apiKey: fakeKey, send: async () => response() });
  await Promise.all([drain(f.fetch), drain(other)]);
  assert.deepEqual((await f.ledger()).attempts.map((row) => row.number), [1, 2]);
  assert.ok((await f.ledger()).attempts.every((row) => row.outcome === 'completed'));
});

test('HTTP failures and redirects freeze every new case for the service', async (t) => {
  for (const status of [302, 429, 500]) {
    const f = await fixture(t, { send: async () => response('sensitive response', { status }) });
    await assert.rejects(drain(f.fetch), /http_error/);
    const row = (await f.ledger()).attempts[0]; assert.equal(row.http_status, status); assert.equal(row.case_frozen, true);
    const other = createBudgetFetch({ ledgerPath: f.ledgerPath, caseName: 'native-kimi:new', apiKey: fakeKey,
      send: async () => assert.fail('frozen service opened a socket') });
    await assert.rejects(drain(other), /case_frozen/); assert.equal((await f.ledger()).attempts.length, 1);
  }
});

test('wrong model, incomplete or malformed stream and unsupported compression freeze and retain reserve', async (t) => {
  for (const send of [
    async () => response(sse({ model: 'wrong-model' })),
    async () => response(`data: ${JSON.stringify(facts())}\n\n`),
    async () => response('data: secret-not-json\n\n'),
    async () => response(sse(), { headers: { 'content-encoding': 'gzip' } }),
    async () => response(sse({ usage: { ...usage, completion_tokens: 2049 } })),
    async () => ({ ...response(), body: (async function* () { yield encoder.encode('data: '); throw Error(fakeKey); })() }),
  ]) {
    const f = await fixture(t, { send });
    await assert.rejects(drain(f.fetch), (err) => err.message.startsWith('CLAO live transport:') && !err.message.includes(fakeKey));
    const row = (await f.ledger()).attempts[0]; assert.ok(row.reserved_cny > 0); assert.equal(row.case_frozen, true);
    await assert.rejects(drain(f.fetch), /case_frozen/);
    assert.ok(!JSON.stringify(await f.ledger()).includes('secret-not-json'));
  }
});

test('pre-abort sends nothing; timeout during headers and stream retains reserved frozen row', async (t) => {
  const pre = await fixture(t); const aborted = new AbortController(); aborted.abort();
  await assert.rejects(drain(pre.fetch, request({}, { signal: aborted.signal })), /aborted/); assert.equal(pre.calls.length, 0);
  for (const send of [async () => new Promise(() => {}), async () => ({ ...response(), body: (async function* () { await new Promise(() => {}); })() })]) {
    const f = await fixture(t, { send, timeoutMs: 20 });
    await assert.rejects(drain(f.fetch), /timeout/);
    const row = (await f.ledger()).attempts[0]; assert.equal(row.outcome, 'timeout'); assert.ok(row.reserved_cny > 0);
  }
});

test('caller abort during response and missing identity cannot be reported as success', async (t) => {
  const controller = new AbortController();
  const f = await fixture(t, { send: async () => ({ ...response(), body: (async function* () {
    yield encoder.encode(`data: ${JSON.stringify(facts())}\n\n`); controller.abort(); await new Promise(() => {});
  })() }) });
  await assert.rejects(drain(f.fetch, request({}, { signal: controller.signal })), /aborted/);
  assert.equal((await f.ledger()).attempts[0].outcome, 'aborted');
  const missing = await fixture(t, { send: async () => response('data: {"choices":[]}\n\ndata: [DONE]\n\n') });
  await assert.rejects(drain(missing.fetch), /response_unconfirmed/);
});

test('corrupt, locked and unconfirmed ledgers fail closed without sockets', async (t) => {
  const f = await fixture(t);
  await fs.writeFile(f.ledgerPath, 'not json'); await assert.rejects(drain(f.fetch), /ledger_unavailable/);
  await fs.writeFile(f.ledgerPath, JSON.stringify({ attempts: [{ service: 'moonshot_cn', reserved_cny: 1, outcome: 'unconfirmed' }] }));
  await assert.rejects(drain(f.fetch), /case_frozen/);
  await fs.writeFile(path.join(f.dir, 'live-ledger.lock'), '');
  await assert.rejects(drain(f.fetch), /ledger_busy/); assert.equal(f.calls.length, 0);
});

test('explicit frozen ledger refuses even without a failed row', async (t) => {
  const f = await fixture(t);
  await fs.writeFile(f.ledgerPath, JSON.stringify({ frozen: true, attempts: [] }));
  await assert.rejects(drain(f.fetch), /case_frozen/);
  assert.equal(f.calls.length, 0);
  assert.deepEqual((await f.ledger()).attempts, []);
});

test('usage total must equal input plus output and freezes subsequent cases', async (t) => {
  const f = await fixture(t, { send: async () => response(sse({ usage: { ...usage, total_tokens: 26 } })) });
  await assert.rejects(drain(f.fetch), /invalid_usage/);
  const row = (await f.ledger()).attempts[0];
  assert.equal(row.outcome, 'invalid_usage');
  assert.equal(row.case_frozen, true);
  const next = createBudgetFetch({ ledgerPath: f.ledgerPath, caseName: 'new-case', apiKey: fakeKey,
    send: async () => assert.fail('invalid usage must freeze service') });
  await assert.rejects(drain(next), /case_frozen/);
});

function toolSSE(name, args, { splitArguments = false } = {}) {
  const encoded = typeof args === 'string' ? args : JSON.stringify(args);
  const cut = splitArguments ? Math.floor(encoded.length / 2) : encoded.length;
  const first = { index: 0, id: 'synthetic-tool', type: 'function', function: { name, arguments: encoded.slice(0, cut) } };
  const delta = calls => `data: ${JSON.stringify({ model: 'kimi-k3', choices: [{ index: 0, delta: { tool_calls: calls }, finish_reason: null }] })}\n\n`;
  return delta([first]) + (splitArguments ? delta([{ index: 0, function: { arguments: encoded.slice(cut) } }]) : '') + sse();
}

async function toolFixture(t, name, args, options = {}) {
  const f = await fixture(t);
  const workspaceRoot = path.join(f.dir, 'project');
  await fs.mkdir(workspaceRoot);
  await fs.writeFile(path.join(workspaceRoot, 'solution.py'), 'def add(a,b): return a-b\n');
  await fs.writeFile(path.join(workspaceRoot, 'check.py'), 'synthetic check\n');
  const payload = toolSSE(name, typeof args === 'function' ? args(workspaceRoot) : args, options);
  const fetch = createBudgetFetch({ ledgerPath: f.ledgerPath, caseName: 'tool-scope', apiKey: fakeKey, workspaceRoot,
    send: async () => response(payload, { split: true }) });
  return { ...f, fetch, workspaceRoot, payload };
}

test('complete streamed tool arguments admit only the synthetic read/write/edit paths', async (t) => {
  for (const [name, args] of [
    ['Read', { path: 'solution.py', line_offset: 1, n_lines: 10 }],
    ['Read', root => ({ path: path.join(root, 'check.py'), line_offset: -2, max_chars: 100 })],
    ['Write', { path: './solution.py', content: 'def add(a,b): return a+b\n' }],
    ['Edit', { path: 'solution.py', old_string: 'a-b', new_string: 'a+b', replace_all: false }],
  ]) {
    const f = await toolFixture(t, name, args, { splitArguments: true });
    assert.equal(await drain(f.fetch), f.payload);
    assert.equal((await f.ledger()).attempts[0].outcome, 'completed');
  }
});

test('outside, ambiguous, nontext and unknown tool calls never become a Response', async (t) => {
  for (const [name, args] of [
    ['Read', { path: '../secret.txt' }], ['Read', root => ({ path: path.join(path.dirname(root), 'secret.txt') })],
    ['Read', { path: 'kimi-file://private' }], ['Read', { path: 'solution.py:secret' }],
    ['Read', { path: 'solution.py', other_path: 'check.py' }], ['Read', { path: ['solution.py'] }],
    ['Read', { path: 'solution.py', n_lines: 'all' }], ['Write', { path: 'check.py', content: 'modified check' }],
    ['Write', { path: 'solution.py', content: { image: 'nontext' } }],
    ['Write', { path: 'solution.py', content: '\u0000binary' }],
    ['Edit', { path: 'solution.py', old_string: 'a-b', new_string: 'a+b', shell: 'unadmitted' }],
    ['Edit', { path: '../solution.py', old_string: 'a-b', new_string: 'a+b' }],
    ['Bash', { command: 'read private data' }], ['Agent', { prompt: 'private' }], ['MCP', { path: 'solution.py' }],
    ['Write', '{"path":"solution.py","content":'],
  ]) {
    const f = await toolFixture(t, name, args, { splitArguments: true });
    await assert.rejects(f.fetch(endpoint, request()), /tool_scope_rejected/);
    const ledger = await f.ledger();
    assert.equal(ledger.attempts[0].case_frozen, true);
    assert.ok(ledger.attempts[0].reserved_cny > 0);
    assert.ok(!JSON.stringify(ledger).includes('private'));
    await assert.rejects(f.fetch(endpoint, request()), /case_frozen/);
    assert.ok(!(await fs.readdir(f.dir)).includes('live-ledger.lock'));
  }
});

test('no early SSE bytes or Response escape before trailing tool validation', async (t) => {
  const f = await toolFixture(t, 'Read', { path: '../outside' });
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  let firstSeen;
  const first = new Promise(resolve => { firstSeen = resolve; });
  const fetch = createBudgetFetch({ ledgerPath: f.ledgerPath, caseName: 'buffered', apiKey: fakeKey, workspaceRoot: f.workspaceRoot,
    send: async () => ({ ...response(), body: (async function* () {
      yield encoder.encode('data: {"model":"kimi-k3","choices":[{"index":0,"delta":{"content":"safe prefix"}}]}\n\n');
      firstSeen(); await blocked; yield encoder.encode(f.payload);
    })() }) });
  let exposed = false;
  const result = fetch(endpoint, request()).then(value => { exposed = true; return value; });
  await first;
  assert.equal(exposed, false);
  release();
  await assert.rejects(result, /tool_scope_rejected/);
  assert.equal(exposed, false);
});

test('hard-linked allowed name is refused before a tool response is exposed', async (t) => {
  const f = await toolFixture(t, 'Read', { path: 'solution.py' });
  await fs.link(path.join(f.workspaceRoot, 'solution.py'), path.join(f.dir, 'outside-alias'));
  await assert.rejects(f.fetch(endpoint, request()), /tool_scope_rejected/);
});

test('junction or directory symlink root cannot alias an admitted filename', async (t) => {
  const f = await toolFixture(t, 'Read', { path: 'solution.py' });
  const alias = path.join(f.dir, 'aliased-project');
  await fs.symlink(f.workspaceRoot, alias, process.platform === 'win32' ? 'junction' : 'dir');
  const fetch = createBudgetFetch({ ledgerPath: f.ledgerPath, caseName: 'alias', apiKey: fakeKey, workspaceRoot: alias,
    send: async () => response(f.payload) });
  await assert.rejects(fetch(endpoint, request()), /tool_scope_rejected/);
});

test('buffer bound and credential echo fail before any Response is returned', async (t) => {
  for (const [payload, code] of [
    ['x'.repeat(4 * 1024 * 1024 + 1), 'response_bound_exceeded'],
    [sse({ choices: [{ index: 0, delta: { content: fakeKey } }] }), 'credential_in_response'],
  ]) {
    const f = await fixture(t, { send: async () => response(payload) });
    await assert.rejects(f.fetch(endpoint, request()), new RegExp(code));
    assert.equal((await f.ledger()).attempts[0].case_frozen, true);
    assert.ok(!JSON.stringify(await f.ledger()).includes(fakeKey));
    assert.ok(!(await fs.readdir(f.dir)).includes('live-ledger.lock'));
  }
});
