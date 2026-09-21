// Test-only preload: never included in the product runtime or CLI distribution.
// Input reservation follows verify-live-semantics.py: full UTF-8 request bytes
// plus 2048 framing tokens, not an observed or character-based token estimate.
import fs from 'node:fs/promises';
import path from 'node:path';
import https from 'node:https';
import { randomUUID } from 'node:crypto';

const ENDPOINT = 'https://api.moonshot.cn/v1/chat/completions';
const MODEL = 'kimi-k3';
const TOOLS = new Set(['Read', 'Write', 'Edit']);
const error = (code) => Object.assign(new Error(`CLAO live transport: ${code}`), { code });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const integer = (n) => Number.isSafeInteger(n) && n >= 0;
const record = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const only = (v, keys) => record(v) && Object.keys(v).every((key) => keys.includes(key));

function validateRequest(input, init, key) {
  if ((typeof input !== 'string' && !(input instanceof URL)) || String(input) !== ENDPOINT ||
      init?.method?.toUpperCase() !== 'POST' || typeof init.body !== 'string' || !key ||
      init.body.includes(key)) throw error('request_rejected');
  const headers = new Headers(init.headers);
  if (headers.get('authorization') !== `Bearer ${key}` ||
      !/^application\/json(?:\s*;|$)/i.test(headers.get('content-type') ?? '') ||
      headers.has('host') || headers.has('cookie') || headers.has('content-encoding')) throw error('request_rejected');
  let body;
  try { body = JSON.parse(init.body); } catch { throw error('request_rejected'); }
  if (!only(body, ['model', 'messages', 'tools', 'stream', 'stream_options', 'max_completion_tokens',
    'n', 'thinking', 'reasoning_effort', 'temperature', 'top_p', 'parallel_tool_calls', 'tool_choice', 'prompt_cache_key']) ||
      body.model !== MODEL || !integer(body.max_completion_tokens) || body.max_completion_tokens < 1 ||
      body.max_completion_tokens > 2048 || (body.n !== undefined && body.n !== 1) ||
      body.stream !== true || !only(body.stream_options ?? {}, ['include_usage']) ||
      body.stream_options?.include_usage !== true || !Array.isArray(body.messages) || body.messages.length === 0) throw error('request_rejected');
  const textContent = (value) => typeof value === 'string' || value === null ||
    (Array.isArray(value) && value.every((part) => only(part, ['type', 'text']) && part.type === 'text' && typeof part.text === 'string'));
  for (const message of body.messages) {
    if (!only(message, ['role', 'content', 'name', 'tool_call_id', 'tool_calls', 'reasoning_content']) ||
        !['system', 'user', 'assistant', 'tool'].includes(message.role) ||
        (message.content !== undefined && !textContent(message.content)) ||
        (message.reasoning_content !== undefined && typeof message.reasoning_content !== 'string')) throw error('request_rejected');
    if (message.tool_calls !== undefined && (!Array.isArray(message.tool_calls) || !message.tool_calls.every((call) =>
      only(call, ['id', 'type', 'function']) && call.type === 'function' &&
      only(call.function, ['name', 'arguments']) && TOOLS.has(call.function.name) && typeof call.function.arguments === 'string'))) throw error('request_rejected');
  }
  if (body.tools !== undefined && (!Array.isArray(body.tools) || !body.tools.every((tool) =>
    only(tool, ['type', 'function']) && tool.type === 'function' &&
    only(tool.function, ['name', 'description', 'parameters', 'strict']) && TOOLS.has(tool.function.name)))) throw error('request_rejected');
  if (body.tool_choice !== undefined && !['auto', 'none', 'required'].includes(body.tool_choice)) throw error('request_rejected');
  const inputUpper = Buffer.byteLength(init.body, 'utf8') + 2048;
  if (inputUpper > 24000) throw error('input_bound_exceeded');
  headers.set('accept-encoding', 'identity');
  headers.set('content-length', String(Buffer.byteLength(init.body, 'utf8')));
  return { headers, body: init.body, inputUpper, outputUpper: body.max_completion_tokens };
}

export function accountedMicros(row) {
  const reserved = row.reserved_cny;
  if (!Number.isFinite(reserved) || reserved < 0) throw error('ledger_unavailable');
  const micros = Math.round(reserved * 1e6);
  if (row.service !== 'moonshot_cn' || !['completed', 'http_response'].includes(row.outcome) || row.case_frozen) return micros;
  const usage = row.usage ?? row.validation?.usage;
  const confirmed = row.confirmed_model ?? row.validation?.confirmed_model;
  if (row.model !== MODEL || confirmed !== MODEL || row.http_status !== 200 ||
      !integer(row.input_tokens_upper) || row.input_tokens_upper < 2048 || row.input_tokens_upper > 24000 ||
      !integer(row.output_tokens_upper) || row.output_tokens_upper < 1 || row.output_tokens_upper > 8192 ||
      Math.abs(reserved * 1e6 - (row.input_tokens_upper * 60 + row.output_tokens_upper * 100)) > 0.00001 ||
      !record(usage) || !['prompt_tokens', 'completion_tokens', 'total_tokens'].every(k => integer(usage[k])) ||
      usage.total_tokens !== usage.prompt_tokens + usage.completion_tokens ||
      usage.prompt_tokens > row.input_tokens_upper || usage.completion_tokens > row.output_tokens_upper) throw error('ledger_unavailable');
  // All cache classifications are inside prompt_tokens. Retain the deliberately
  // conservative 20+40 rate, without claiming invoice settlement or a discount.
  return usage.prompt_tokens * 60 + usage.completion_tokens * 100;
}

function lockPath(ledgerPath) {
  const parsed = path.parse(ledgerPath);
  return path.join(parsed.dir, `${parsed.name}.lock`); // Python Path.with_suffix('.lock').
}

async function acquire(ledgerPath) {
  await fs.mkdir(path.dirname(ledgerPath), { recursive: true });
  const lock = lockPath(ledgerPath);
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      const handle = await fs.open(lock, 'wx', 0o600);
      await handle.close();
      return async () => { await fs.unlink(lock); };
    } catch (err) {
      if (err.code !== 'EEXIST') throw error('ledger_unavailable');
      await sleep(10);
    }
  }
  throw error('ledger_busy');
}

async function readLedger(ledgerPath) {
  let ledger;
  try { ledger = JSON.parse(await fs.readFile(ledgerPath, 'utf8')); }
  catch (err) {
    if (err.code === 'ENOENT') return { attempts: [] };
    throw error('ledger_unavailable');
  }
  if (!record(ledger) || !Array.isArray(ledger.attempts) || ledger.attempts.some((row) =>
    !record(row) || !Number.isFinite(row.reserved_cny) || row.reserved_cny < 0)) throw error('ledger_unavailable');
  return ledger;
}

async function saveLedger(ledgerPath, ledger) {
  const temp = `${ledgerPath}.${randomUUID()}.tmp`;
  try {
    const handle = await fs.open(temp, 'wx', 0o600);
    try { await handle.writeFile(JSON.stringify(ledger, null, 2), 'utf8'); await handle.sync(); }
    finally { await handle.close(); }
    await fs.rename(temp, ledgerPath);
  } catch { throw error('ledger_unavailable'); }
  finally { await fs.unlink(temp).catch(() => {}); }
}

// No fetch, redirect handler, proxy, retry agent or third-party HTTP client.
export function sendHttpsOnce({ headers, body, signal }) {
  return new Promise((resolve, reject) => {
    const req = https.request(ENDPOINT, {
      method: 'POST', headers: Object.fromEntries(headers), signal, agent: false,
    }, (res) => resolve({ status: res.statusCode, headers: res.headers, body: res }));
    req.on('error', () => reject(error('network_error')));
    req.end(body);
  });
}

function usageFacts(value) {
  if (!record(value)) return undefined;
  const keys = ['prompt_tokens', 'completion_tokens', 'total_tokens'];
  if (!keys.every((key) => integer(value[key])) || value.total_tokens !== value.prompt_tokens + value.completion_tokens) throw error('invalid_usage');
  return Object.fromEntries(keys.map((key) => [key, value[key]]));
}

// This live-test transport deliberately admits only the two synthetic files.
// It is not a general Kimi sandbox or a product runtime permission policy.
async function validateToolCalls(calls, workspaceRoot) {
  const equalPath = (a, b) => process.platform === 'win32' ? a.toLowerCase() === b.toLowerCase() : a === b;
  const text = (value) => typeof value === 'string' && value.isWellFormed() && !/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(value);
  for (const call of calls.values()) {
    if (!call.id || call.type !== 'function' || !TOOLS.has(call.name)) throw error('tool_scope_rejected');
    let args;
    try { args = JSON.parse(call.arguments); } catch { throw error('tool_scope_rejected'); }
    const keys = call.name === 'Read' ? ['path', 'line_offset', 'column_offset', 'n_lines', 'max_chars'] :
      call.name === 'Write' ? ['path', 'content', 'mode'] : ['path', 'old_string', 'new_string', 'replace_all'];
    if (!only(args, keys) || !text(args.path) || !args.path || /[\r\n\t]/.test(args.path) ||
        /^(?:\\\\|\/\/|[a-z][a-z0-9+.-]*:\/\/)/i.test(args.path) ||
        args.path.split(/[\\/]/).includes('..') ||
        args.path.replace(/^[a-z]:[\\/]/i, '').includes(':')) throw error('tool_scope_rejected');
    const target = path.resolve(workspaceRoot, args.path);
    const admitted = (call.name === 'Read' ? ['solution.py', 'check.py'] : ['solution.py'])
      .some(name => equalPath(target, path.join(workspaceRoot, name)));
    if (!admitted) throw error('tool_scope_rejected');
    if (call.name === 'Read') {
      if (args.line_offset !== undefined && (!Number.isSafeInteger(args.line_offset) || args.line_offset === 0) ||
          args.column_offset !== undefined && !integer(args.column_offset) ||
          ['n_lines', 'max_chars'].some(key => args[key] !== undefined && (!integer(args[key]) || args[key] < 1))) throw error('tool_scope_rejected');
    } else if (call.name === 'Write') {
      if (!text(args.content) || args.mode !== undefined && !['overwrite', 'append'].includes(args.mode)) throw error('tool_scope_rejected');
    } else if (!text(args.old_string) || !args.old_string || !text(args.new_string) ||
        args.replace_all !== undefined && typeof args.replace_all !== 'boolean') throw error('tool_scope_rejected');
    try {
      // No symlink/junction aliases or hard-linked targets may expose another
      // file through an otherwise admitted lexical name in this tiny fixture.
      const stat = await fs.lstat(target);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 ||
          !equalPath(await fs.realpath(workspaceRoot), workspaceRoot) ||
          !equalPath(await fs.realpath(target), target)) throw error('tool_scope_rejected');
    } catch { throw error('tool_scope_rejected'); }
  }
}

export function createBudgetFetch({ ledgerPath, caseName, apiKey, send = sendHttpsOnce, timeoutMs = 120000, workspaceRoot = process.cwd(), maxAttempts = 3 }) {
  if (!path.isAbsolute(ledgerPath ?? '') || !/^[a-zA-Z0-9][a-zA-Z0-9:_-]{0,79}$/.test(caseName ?? '') ||
      typeof apiKey !== 'string' || !apiKey ||
      !path.isAbsolute(workspaceRoot ?? '') || workspaceRoot !== path.resolve(workspaceRoot) ||
      !Number.isSafeInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 4 ||
      !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120000) throw error('configuration_rejected');
  let frozen = false;
  return async function budgetFetch(input, init) {
    if (frozen) throw error('case_frozen');
    const request = validateRequest(input, init, apiKey);
    if (init.signal?.aborted) throw error('aborted');
    const started = Date.now();
    const release = await acquire(ledgerPath);
    let ledger;
    let row;
    try {
      ledger = await readLedger(ledgerPath);
      if (ledger.frozen || ledger.attempts.some((previous) => previous.service === 'moonshot_cn' &&
          (previous.case_frozen || !['completed', 'http_response'].includes(previous.outcome) || previous.http_status !== 200 ||
           (previous.confirmed_model ?? previous.validation?.confirmed_model) !== MODEL))) throw error('case_frozen');
      const priorCase = ledger.attempts.filter(previous => previous.case === caseName);
      if (priorCase.length >= maxAttempts || priorCase.some(previous => (previous.case_attempt_limit ?? 3) !== maxAttempts)) throw error('case_budget_exhausted');
      const reserveMicros = request.inputUpper * 60 + request.outputUpper * 100;
      const usedMicros = ledger.attempts.reduce((sum, previous) => sum + accountedMicros(previous), 0);
      if (ledger.attempts.length >= 40 || usedMicros + reserveMicros > 20000000) throw error('budget_exhausted');
      row = {
        number: ledger.attempts.length + 1, at: new Date().toISOString(), service: 'moonshot_cn', model: MODEL,
        case: caseName, case_attempt_limit: maxAttempts, input_tokens_upper: request.inputUpper, output_tokens_upper: request.outputUpper,
        reserved_cny: reserveMicros / 1e6, outcome: 'unconfirmed', http_status: null,
      };
      ledger.attempts.push(row);
      await saveLedger(ledgerPath, ledger);
    } catch (err) {
      await release().catch(() => {});
      throw error(['case_frozen', 'case_budget_exhausted', 'budget_exhausted'].includes(err.code) ? err.code : 'ledger_unavailable');
    }
    const controller = new AbortController();
    let timedOut = false;
    const abort = () => controller.abort();
    init.signal?.addEventListener('abort', abort, { once: true });
    if (init.signal?.aborted) abort();
    const timer = setTimeout(() => { timedOut = true; abort(); }, Math.max(1, timeoutMs - (Date.now() - started)));
    let terminal;
    const finish = (outcome) => {
      if (terminal) return terminal;
      clearTimeout(timer);
      init.signal?.removeEventListener('abort', abort);
      row.outcome = outcome;
      row.case_frozen = outcome !== 'completed';
      frozen ||= row.case_frozen;
      row.elapsed_seconds = Math.round((Date.now() - started) / 10) / 100;
      terminal = (async () => {
        try { await saveLedger(ledgerPath, ledger); }
        catch { frozen = true; throw error('ledger_unavailable'); }
        finally { await release().catch(() => { frozen = true; }); }
      })();
      return terminal;
    };
    let rejectAbort;
    const interrupted = new Promise((_, reject) => { rejectAbort = reject; });
    // Each race subscribes immediately; never leak an unhandled rejection.
    interrupted.catch(() => {});
    const interruptedError = () => error(timedOut ? 'timeout' : 'aborted');
    controller.signal.addEventListener('abort', () => rejectAbort(interruptedError()), { once: true });
    if (controller.signal.aborted) rejectAbort(interruptedError());
    let response;
    let iterator;
    try {
      if (controller.signal.aborted) throw interruptedError();
      response = await Promise.race([send({ ...request, signal: controller.signal }), interrupted]);
      row.http_status = Number.isInteger(response.status) ? response.status : null;
      if (response.status !== 200) throw error('http_error');
      const headers = new Headers(response.headers);
      if (headers.has('content-encoding') && headers.get('content-encoding') !== 'identity') throw error('compressed_response');
      const contentType = headers.get('content-type') ?? '';
      if (!/^(text\/event-stream|application\/json)(?:\s*;|$)/i.test(contentType)) throw error('unexpected_response');
      const sse = /^text\/event-stream/i.test(contentType);
      iterator = response.body[Symbol.asyncIterator]();
      const chunks = [];
      const calls = new Map();
      let bytes = 0;
      let pending = '';
      let sawDone = false;
      const decoder = new TextDecoder('utf-8', { fatal: true });
      function observe(data) {
        if (!record(data) || data.error !== undefined) throw error('invalid_response');
        if (data.model !== undefined) {
          if (data.model !== MODEL) throw error('model_mismatch');
          row.confirmed_model = MODEL;
        }
        if (data.usage !== undefined && data.usage !== null) {
          row.usage = usageFacts(data.usage);
          if (row.usage.prompt_tokens > request.inputUpper || row.usage.completion_tokens > request.outputUpper) throw error('usage_bound_exceeded');
        }
        if (data.choices !== undefined && !Array.isArray(data.choices)) throw error('invalid_response');
        for (const choice of data.choices ?? []) {
          if (choice.index !== 0 || choice.delta !== undefined && choice.message !== undefined) throw error('invalid_response');
          const delta = choice.delta ?? choice.message ?? {};
          if (!only(delta, ['role', 'content', 'reasoning_content', 'tool_calls', 'refusal']) ||
              delta.role !== undefined && delta.role !== 'assistant' ||
              ['content', 'reasoning_content', 'refusal'].some(key => delta[key] != null && typeof delta[key] !== 'string')) throw error('invalid_response');
          if (delta.tool_calls !== undefined && !Array.isArray(delta.tool_calls)) throw error('tool_scope_rejected');
          for (const [position, fragment] of (delta.tool_calls ?? []).entries()) {
            if (!only(fragment, ['index', 'id', 'type', 'function']) || !only(fragment.function ?? {}, ['name', 'arguments'])) throw error('tool_scope_rejected');
            const index = sse ? fragment.index : position;
            if (!integer(index) || index > 63) throw error('tool_scope_rejected');
            const call = calls.get(index) ?? { id: '', type: '', name: '', arguments: '' };
            for (const key of ['id', 'type']) {
              if (fragment[key] !== undefined) {
                if (call[key] || typeof fragment[key] !== 'string' || !fragment[key]) throw error('tool_scope_rejected');
                call[key] = fragment[key];
              }
            }
            if (fragment.function?.name !== undefined) {
              if (call.name || !TOOLS.has(fragment.function.name)) throw error('tool_scope_rejected');
              call.name = fragment.function.name;
            }
            if (fragment.function?.arguments !== undefined) {
              if (typeof fragment.function.arguments !== 'string') throw error('tool_scope_rejected');
              call.arguments += fragment.function.arguments;
            }
            calls.set(index, call);
          }
        }
      }
      function frame(value) {
        const data = value.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n');
        if (!data) return;
        if (data === '[DONE]') { sawDone = true; return; }
        if (sawDone) throw error('invalid_response');
        try { observe(JSON.parse(data)); } catch (err) {
          throw error(['model_mismatch', 'usage_bound_exceeded', 'invalid_usage', 'tool_scope_rejected'].includes(err.code) ? err.code : 'invalid_response');
        }
      }
      // Buffer before exposing even the first SSE byte: an SDK can execute a
      // completed tool call while later chunks are still arriving.
      while (!sawDone) {
        const next = await Promise.race([iterator.next(), interrupted]);
        if (next.done) break;
        const chunk = Buffer.from(next.value);
        bytes += chunk.length;
        if (bytes > 4 * 1024 * 1024) throw error('response_bound_exceeded');
        pending += decoder.decode(chunk, { stream: true });
        if (sse) {
          pending = pending.replace(/\r\n/g, '\n');
          let boundary;
          while ((boundary = pending.indexOf('\n\n')) !== -1) {
            frame(pending.slice(0, boundary));
            pending = pending.slice(boundary + 2);
          }
        }
        if (pending.length > 1024 * 1024) throw error('response_bound_exceeded');
        chunks.push(chunk);
      }
      if (!sse) {
        pending += decoder.decode();
        try { observe(JSON.parse(pending)); } catch (err) {
          throw error(['model_mismatch', 'usage_bound_exceeded', 'invalid_usage', 'tool_scope_rejected'].includes(err.code) ? err.code : 'invalid_response');
        }
      } else if (!sawDone) throw error('stream_incomplete');
      else if ((pending + decoder.decode()).trim()) throw error('invalid_response');
      if (!row.confirmed_model || !row.usage) throw error('response_unconfirmed');
      const buffered = Buffer.concat(chunks);
      if (buffered.includes(Buffer.from(apiKey))) throw error('credential_in_response');
      await Promise.race([validateToolCalls(calls, workspaceRoot), interrupted]);
      await finish('completed');
      return new Response(buffered, { status: 200, headers });
    } catch (err) {
      controller.abort();
      response?.body?.destroy?.();
      const code = ['http_error', 'compressed_response', 'unexpected_response', 'timeout', 'aborted', 'model_mismatch',
        'usage_bound_exceeded', 'invalid_usage', 'invalid_response', 'response_bound_exceeded', 'stream_incomplete',
        'response_unconfirmed', 'tool_scope_rejected', 'credential_in_response'].includes(err.code) ? err.code : 'network_error';
      await finish(code);
      throw error(code);
    } finally {
      controller.abort();
      response?.body?.destroy?.();
      // Do not await a blocked generator return after timeout.
      Promise.resolve(iterator?.return?.()).catch(() => {});
    }
  };
}

// Mere import is inert. The actual CLI preload must explicitly opt in with all
// three env references; no credential value is written to disk or diagnostics.
if (process.env.CLAO_LIVE_LEDGER !== undefined || process.env.CLAO_LIVE_CASE !== undefined) {
  globalThis.fetch = createBudgetFetch({
    ledgerPath: process.env.CLAO_LIVE_LEDGER, caseName: process.env.CLAO_LIVE_CASE,
    apiKey: process.env.KIMI_API_KEY,
    workspaceRoot: process.cwd(),
    maxAttempts: process.env.CLAO_LIVE_MAX_WORKER_REQUESTS === undefined ? 3 : Number(process.env.CLAO_LIVE_MAX_WORKER_REQUESTS),
  });
}
