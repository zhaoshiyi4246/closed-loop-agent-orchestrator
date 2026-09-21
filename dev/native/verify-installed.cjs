// Windows installed-product journey. Playwright/Node are test-driver tools only:
// the application receives a fresh profile and PATH containing Windows, Git and
// the prebuilt external-engine fixture. No source/dev runtime is handed to it.
// Usage: node dev/native/verify-installed.cjs --application <clao-native.exe>
//   --engine <prebuilt opencode.exe> --git <git.exe> --evidence <NEW directory>
//   [--port 7340] [--expect-gate-import-failure]
const { _electron } = require('../../ao/frontend/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');

const options = {};
for (let i = 2; i < process.argv.length; i++) {
  const key = process.argv[i];
  if (key === '--expect-gate-import-failure') options.negative = true;
  else if (['--application', '--engine', '--git', '--evidence', '--port'].includes(key)) options[key.slice(2)] = process.argv[++i];
  else throw Error(`Unknown option: ${key}`);
}
for (const key of ['application', 'engine', 'git', 'evidence']) if (!options[key]) throw Error(`Missing --${key}`);
const application = fs.realpathSync(options.application);
const engine = fs.realpathSync(options.engine);
const git = fs.realpathSync(options.git);
assert.equal(path.basename(application).toLowerCase(), 'clao-native.exe');
assert.equal(path.basename(engine).toLowerCase(), 'opencode.exe');
const repo = path.resolve(__dirname, '../..');
assert(!application.toLowerCase().startsWith(repo.toLowerCase() + path.sep), 'Use an outside installed/extracted candidate');
const evidence = path.resolve(options.evidence);
assert(!fs.existsSync(evidence), 'Choose a new evidence directory; prior runs are immutable');
fs.mkdirSync(evidence, { recursive: true });
const home = path.join(evidence, 'test profile');
for (const part of ['', 'appdata', 'local', 'config', 'share']) fs.mkdirSync(path.join(home, part), { recursive: true });
const source = path.join(home, '普通 source with spaces');
fs.mkdirSync(source);
const sourceFiles = {
  'source.txt': 'original ordinary directory, unchanged\n',
  'solution.py': "EXPECTED = 'accepted\\n'\n",
  'check.py': "from pathlib import Path\nimport solution\nassert Path('result.txt').read_text() == solution.EXPECTED\nprint('INSTALLED_LOCAL_MODULE_GATE_OK')\n",
  'yaml.py': "raise RuntimeError('the isolated acceptance core must not import project yaml.py')\n",
};
for (const [name, value] of Object.entries(sourceFiles)) fs.writeFileSync(path.join(source, name), value);
const system = process.env.SystemRoot || 'C:\\Windows';
const port = Number(options.port || 7340);
assert(Number.isInteger(port) && port > 1024 && port < 65536);
const env = {
  SystemRoot: system, WINDIR: system, COMSPEC: path.join(system, 'System32/cmd.exe'),
  TEMP: process.env.TEMP, TMP: process.env.TMP, PATHEXT: '.COM;.EXE;.BAT;.CMD',
  USERPROFILE: home, HOME: home, APPDATA: path.join(home, 'appdata'), LOCALAPPDATA: path.join(home, 'local'),
  XDG_CONFIG_HOME: path.join(home, 'config'), XDG_DATA_HOME: path.join(home, 'share'),
  CLAO_NATIVE_HOME: path.join(home, 'clao-data'), CLAO_NATIVE_PORT: String(port),
  // Deliberately invalid inherited core paths prove the package owns its runtime.
  CLAO_CORE_PYTHON: path.join(home, 'not-a-python.exe'), CLAO_CORE_ROOT: path.join(home, 'not-a-checkout'),
  PATH: [path.join(system, 'System32'), path.join(system, 'System32/WindowsPowerShell/v1.0'), path.dirname(git), path.dirname(engine)].join(';'),
};
const base = `http://127.0.0.1:${port}`;
const bundledPython = path.join(path.dirname(application), 'resources/python/python.exe');
const report = {
  test: 'installed-complete-journey', expectedGateImportFailure: Boolean(options.negative),
  sourceCommit: JSON.parse(fs.readFileSync(path.join(path.dirname(application), 'resources/third-party/SOURCE.json'), 'utf8')).commit,
  executableSHA256: crypto.createHash('sha256').update(fs.readFileSync(application)).digest('hex'),
  engine: 'prebuilt external protocol fixture; no real model request',
  applicationPathTools: ['Windows system tools', 'Git', 'external fixture'], steps: [],
};
let app, page;
async function waitFor(fn, why, timeout = 120000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) { const result = await fn(); if (result) return result; await new Promise(resolve => setTimeout(resolve, 250)); }
  throw Error(why);
}
async function missions() {
  const response = await fetch(base + '/api/v1/clao/missions', { signal: AbortSignal.timeout(10000) });
  assert(response.ok, `Mission read failed: ${response.status}`);
  return (await response.json()).missions;
}
function unchangedSource() {
  assert.deepEqual(fs.readdirSync(source).sort(), Object.keys(sourceFiles).sort(), 'Original directory file set changed');
  for (const [name, text] of Object.entries(sourceFiles)) assert.equal(fs.readFileSync(path.join(source, name), 'utf8'), text, `Original ${name} changed`);
}
function runPython(args, cwd = home) {
  return cp.execFileSync(bundledPython, ['-B', ...args], { cwd, env, encoding: 'utf8', windowsHide: true, timeout: 60000 });
}

(async () => {
  app = await _electron.launch({ executablePath: application, args: [], cwd: home, env, timeout: 90000 });
  const identity = await app.evaluate(({ app }) => ({ name: app.getName(), version: app.getVersion(), packaged: app.isPackaged, userData: app.getPath('userData') }));
  assert.equal(identity.name, 'CLAO Native'); assert.equal(identity.version, '0.3.0-rc.1'); assert(identity.packaged);
  assert(identity.userData.startsWith(home), 'Electron userData escaped the isolated test profile');
  report.steps.push('real installed Electron identity and independent profile');
  page = app.context().pages()[0] || await app.firstWindow();
  // A new installed profile opens the welcome screen. Enter the existing
  // project chooser before using its CLAO ordinary-directory action.
  await page.getByRole('button', { name: 'New project', exact: true }).first().waitFor({ timeout: 60000 });
  if (!await page.getByRole('button', { name: '打开本地项目', exact: true }).first().isVisible()) {
    await page.getByRole('button', { name: 'New project', exact: true }).first().click();
  }
  await app.evaluate(({ BaseWindow }) => BaseWindow.getAllWindows()[0].setSize(1440, 1000));
  await page.getByRole('button', { name: '打开本地项目', exact: true }).first().click();
  await page.getByLabel('本地项目名称').fill('Installed ordinary source');
  await page.getByLabel('本地项目目录').fill(source);
  await page.getByRole('button', { name: '打开项目', exact: true }).click();
  await page.getByText('Installed ordinary source', { exact: true }).first().waitFor({ timeout: 30000 });
  report.steps.push('open an ordinary directory through installed GUI');
  await page.getByRole('button', { name: 'New task', exact: true }).first().click();
  await page.getByRole('dialog').waitFor();
  await page.getByLabel('CLAO 闭环验收').check();
  await page.getByLabel('使用上述当前内容快照').check({ timeout: 30000 });
  await page.getByLabel('验收条件（每行一项）').fill('result.txt equals accepted plus newline; original source stays unchanged');
  await page.getByLabel('检查命令（每行一条）').fill('python check.py');
  await page.getByLabel('允许修改范围').fill('result.txt');
  await page.getByLabel('最多修复次数').fill('0');
  await page.getByLabel('执行安排').selectOption('1');
  await page.getByRole('button', { name: 'Agent', exact: true }).click();
  await page.getByRole('menu').getByText('opencode', { exact: true }).click();
  await page.getByRole('button', { name: 'Model', exact: true }).click();
  await page.getByRole('menu').getByText('test/native', { exact: true }).click({ timeout: 20000 });
  const objective = 'Installed candidate writes accepted result and verifies local module imports';
  await page.getByRole('textbox', { name: 'Task', exact: true }).fill(objective);
  await page.screenshot({ path: path.join(evidence, 'installed-source-confirmation.png') });
  await page.getByRole('button', { name: 'Start task', exact: true }).click();
  const mission = await waitFor(async () => {
    const mission = (await missions())[0];
    return mission && ['DONE', 'FAILED', 'HUMAN', 'UNKNOWN', 'PAUSED', 'CANCELLED'].includes(mission.state) ? mission : null;
  }, 'Installed mission did not reach a terminal result');
  report.mission = { id: mission.request.id, state: mission.state, model: mission.request.model, resultHead: mission.resultHead, worker: mission.sessionId, verifier: mission.verifierSessionId };
  unchangedSource();
  if (options.negative) {
    // maxRepairs=0 hands a deterministic Gate failure to the user.
    assert.equal(mission.state, 'HUMAN', mission.reason);
    assert.match(JSON.stringify(mission.evidence), /ModuleNotFoundError|No module named .solution/);
    assert(!mission.resultHead && !mission.verifierSessionId, 'A failed Gate must not materialize or invoke the final verifier');
    report.steps.push('real Gate rejects broken embedded Python local-module imports; source preserved');
    await page.screenshot({ path: path.join(evidence, 'installed-gate-import-negative.png') });
    return;
  }
  assert.equal(mission.state, 'DONE', mission.reason);
  assert.equal(mission.request.model, 'test/native'); assert.equal(mission.source.originalPath, source); assert(mission.resultHead);
  const finalEvidence = mission.evidence.at(-1);
  assert(finalEvidence?.ok && finalEvidence.scopeOK, 'Program acceptance did not pass');
  assert.equal(finalEvidence.verification?.verdict, 'PASS', 'Independent verifier did not pass');
  assert.match(JSON.stringify(mission.evidence), /INSTALLED_LOCAL_MODULE_GATE_OK/, 'No real local-module Gate success evidence');
  assert(mission.verifierSessionId && mission.verifierSessionId !== mission.sessionId, 'Verifier must be independent');
  report.steps.push('external fixture Worker -> real bundled Python Gate importing solution -> independent fixture Verifier -> DONE');
  if (!await page.getByRole('dialog').isVisible()) await page.getByRole('button', { name: '查看原请求：' + objective, exact: true }).click();
  await page.getByText('CLAO · 验收通过', { exact: true }).waitFor();
  const center = page.getByRole('dialog').getByTestId('clao-result-center');
  await center.locator('summary').first().click();
  await center.getByText('固定成果可读取', { exact: true }).waitFor({ timeout: 30000 });
  await center.locator('summary').filter({ hasText: 'result.txt' }).first().click();
  await center.locator('[data-diff-row]').first().waitFor();
  await page.screenshot({ path: path.join(evidence, 'installed-result-diff.png') });
  const archive = path.join(home, 'downloaded-result.zip');
  await app.evaluate(({ session }, destination) => {
    globalThis.__claoInstallDownloadState = 'waiting';
    session.defaultSession.once('will-download', (_event, item) => {
      item.setSavePath(destination);
      item.once('done', (_doneEvent, state) => { globalThis.__claoInstallDownloadState = state; });
    });
  }, archive);
  await center.getByRole('button', { name: '导出独立结果包', exact: true }).click();
  await waitFor(async () => {
    const state = await app.evaluate(() => globalThis.__claoInstallDownloadState);
    if (state === 'cancelled' || state === 'interrupted') throw Error(`Installed download ${state}`);
    return state === 'completed' && fs.existsSync(archive) && fs.statSync(archive).size > 100;
  }, 'Installed GUI export did not download');
  await center.getByText('下载已保存结果包', { exact: true }).waitFor({ timeout: 30000 });
  const target = path.join(home, 'independent application');
  const unpack = path.join(home, 'export extraction');
  const applyScript = [
    'import sys,zipfile,shutil,subprocess', 'from pathlib import Path',
    'source,archive,target,unpack=map(Path,sys.argv[1:])', 'shutil.copytree(source,target)',
    'unpack.mkdir()', 'with zipfile.ZipFile(archive) as bundle:',
    ' for item in bundle.infolist():',
    '  destination=(unpack/item.filename).resolve()',
    '  assert destination.is_relative_to(unpack.resolve()), "unsafe export member"',
    ' bundle.extractall(unpack)', 'patches=list(unpack.rglob("*.patch"))', 'assert len(patches)==1',
    'subprocess.run(["git","apply","--check",str(patches[0])],cwd=target,check=True)',
    'subprocess.run(["git","apply",str(patches[0])],cwd=target,check=True)',
    'subprocess.run([sys.executable,"-B","check.py"],cwd=target,check=True)',
    'print("INDEPENDENT_RESULT_APPLY_OK")',
  ].join('\n');
  assert.match(runPython(['-c', applyScript, source, archive, target, unpack]), /INDEPENDENT_RESULT_APPLY_OK/);
  unchangedSource();
  report.exportSHA256 = crypto.createHash('sha256').update(fs.readFileSync(archive)).digest('hex');
  report.steps.push('GUI ZIP download -> bundled Python extraction -> Git apply in independent directory -> same Gate passes; original source preserved');
  await page.screenshot({ path: path.join(evidence, 'installed-export-saved.png') });
})().then(() => { report.passed = true; }).catch(async error => {
  report.passed = false; report.error = String(error.message || error);
  if (page) await page.screenshot({ path: path.join(evidence, 'installed-failure.png') }).catch(() => {});
  process.exitCode = 1;
}).finally(async () => {
  if (app) await app.close().catch(error => { report.closeError = String(error); process.exitCode = 1; });
  fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
});
