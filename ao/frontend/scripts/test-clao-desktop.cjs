// Actual Electron + native AO services; only the external coding engine is substituted.
// Start ao/dev-clao.ps1 first to serve the compiled development renderer.
const { _electron } = require('playwright');
const fs = require('fs'), path = require('path'), cp = require('child_process'), os = require('os');
const root = path.resolve(__dirname, '../../..'), front = path.join(root, 'ao/frontend');
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'clao-native-desktop-')), env = {};
if (!process.env.CLAO_CORE_PYTHON) throw Error('Set CLAO_CORE_PYTHON to the product venv Python');
const engine = path.join(home, 'engine'); fs.mkdirSync(engine);
cp.execFileSync('go', ['build', '-o', path.join(engine, 'opencode.exe'), path.join(root, 'ao/backend/internal/service/claoloop/testdata/engine.go')], { cwd: path.join(root, 'ao/backend'), stdio: 'inherit' });
for (const key of ['PATH', 'SystemRoot', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'PATHEXT']) if (process.env[key]) env[key] = process.env[key];
Object.assign(env, {
  CLAO_NATIVE_HOME: home, CLAO_NATIVE_PORT: process.env.CLAO_DESKTOP_TEST_PORT || '7314',
  AO_DEV_DAEMON_BINARY: path.join(front, 'daemon/ao.exe'),
  CLAO_CORE_PYTHON: process.env.CLAO_CORE_PYTHON, CLAO_CORE_ROOT: path.join(root, 'clao'),
  HOME: home, USERPROFILE: home, APPDATA: path.join(home, 'appdata'), LOCALAPPDATA: path.join(home, 'local'),
  XDG_CONFIG_HOME: path.join(home, 'config'), XDG_DATA_HOME: path.join(home, 'share'),
  PATH: engine + path.delimiter + path.dirname(process.env.CLAO_CORE_PYTHON) + path.delimiter + env.PATH,
});
const evidence = process.env.CLAO_SCREENSHOTS || path.join(home, 'screenshots');
fs.mkdirSync(evidence, { recursive: true });
(async () => {
  const foreign = process.env.CLAO_TEST_FOREIGN_PORT === '1';
  let foreignRequests = 0;
  const holder = foreign ? require('http').createServer((_req, res) => { foreignRequests++; res.end('{}'); }) : null;
  if (holder) await new Promise(resolve => holder.listen(Number(env.CLAO_NATIVE_PORT), '127.0.0.1', resolve));
  const app = await _electron.launch({ executablePath: path.join(front, 'node_modules/electron/dist/electron.exe'), args: [front], cwd: front, env, timeout: 60000 });
  try {
    const page = app.context().pages()[0] || await app.firstWindow();
    await page.waitForSelector('body'); await new Promise(r => setTimeout(r, 4000));
    if (foreign) {
      await new Promise(r => setTimeout(r, 7000));
      if (foreignRequests || !holder.listening) throw Error('foreign port was contacted or closed');
      console.log('FOREIGN_PORT_UNTOUCHED');
      return;
    }
    await app.evaluate(({ BaseWindow }) => BaseWindow.getAllWindows()[0].setSize(1440, 900));
    const project = path.join(home, '验证项目'); fs.mkdirSync(project);
    const git = (...args) => cp.execFileSync('git', ['-C', project, ...args], { env, encoding: 'utf8' }).trim();
    git('init', '-b', 'main'); git('config', 'user.email', 'fixture@example.invalid'); git('config', 'user.name', 'Fixture');
    fs.writeFileSync(path.join(project, 'source.txt'), 'frozen source\n');
    fs.writeFileSync(path.join(project, 'check.py'), "from pathlib import Path\nassert Path('result.txt').read_text() == 'accepted\\n'\n");
    git('add', '.'); git('commit', '-m', 'base');
    const sourceHead = git('rev-parse', 'HEAD');
    const sourceIndex = fs.readFileSync(path.join(project, '.git/index'));
    const base = 'http://127.0.0.1:' + env.CLAO_NATIVE_PORT;
    const registration = await fetch(base + '/api/v1/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ projectId: 'native-example', name: '原生闭环验证', path: project }) });
    if (!registration.ok) throw Error('isolated project registration failed: ' + await registration.text());
    await page.reload(); await page.getByText('原生闭环验证', { exact: true }).first().click({ timeout: 15000 });
    const open = async () => {
      await page.getByText('原生闭环验证', { exact: true }).first().click();
      await page.getByRole('button', { name: 'New task', exact: true }).first().click();
      await page.getByRole('dialog').waitFor();
      await page.getByRole('button', { name: 'Agent', exact: true }).click();
      await page.getByText('opencode', { exact: true }).click();
      await page.getByRole('button', { name: 'Model', exact: true }).click();
      await page.getByText('test/native', { exact: true }).waitFor();
    };
    const start = async (objective) => {
      await page.getByLabel('CLAO 闭环验收').check();
      await page.getByLabel('验收条件（每行一项）').fill('result.txt 内容为 accepted；原项目保持不变');
      await page.getByLabel('Gate 命令（每行一条）').fill('python check.py');
      await page.getByLabel('允许修改范围').fill('**');
      await page.getByLabel('最多修复次数').fill('1');
      await page.getByRole('textbox', { name: 'Task', exact: true }).fill(objective);
      await page.getByRole('button', { name: 'Start task', exact: true }).click();
    };
    await open();
    await page.screenshot({ path: path.join(evidence, 'native-model-menu.png') });
    await page.getByPlaceholder('Search models…').fill('second');
    await page.getByText('test/second', { exact: true }).click();
    if (!(await page.getByRole('button', { name: 'Model', exact: true }).innerText()).includes('test/second')) throw Error('native model pick not retained');
    await start('创建 result.txt，写入 accepted 和换行。');
    await page.getByText('CLAO · 验收通过', { exact: true }).waitFor({ timeout: 60000 });
    await page.getByText('验收条件、文件与证据', { exact: true }).click();
    await page.screenshot({ path: path.join(evidence, 'closed-loop-pass.png') });
    if (await page.getByRole('button', { name: 'Resume agent', exact: true }).count()) throw Error('closed-loop resume bypass remains visible');
    console.log('PASS', await page.getByTestId('clao-result').innerText());
    await open(); await page.getByText('test/native', { exact: true }).click();
    await start('FAIL_GATE：保留失败，验证有界修复。');
    await page.getByText('CLAO · 验收未通过', { exact: true }).waitFor({ timeout: 60000 });
    await page.getByText('验收条件、文件与证据', { exact: true }).click();
    await page.screenshot({ path: path.join(evidence, 'closed-loop-fail.png') });
    const rows = (await (await fetch(base + '/api/v1/clao/missions')).json()).missions;
    const pass = rows.find(m => m.state === 'DONE'), fail = rows.find(m => m.state === 'FAILED');
    if (pass?.request.model !== 'test/second' || fail?.repairs !== 1 || fail.resultHead || fail.operations.filter(o => o.kind === 'repair_send').length !== 1) throw Error('UI choice or acceptance facts mismatch');
    if (git('status', '--porcelain') || git('rev-parse', 'HEAD') !== sourceHead || !fs.readFileSync(path.join(project, '.git/index')).equals(sourceIndex) || fs.existsSync(path.join(project, 'result.txt'))) throw Error('source changed');
    console.log('FAIL', await page.getByTestId('clao-result').innerText());
    console.log('DESKTOP_CHECK_PASS', evidence);
  } finally { await app.close(); if (holder) await new Promise(resolve => holder.close(resolve)); }
})().catch(e => { console.error(e); process.exitCode = 1; });
