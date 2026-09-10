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
  AO_DEV_DAEMON_BINARY: process.env.CLAO_NATIVE_BINARY || path.join(front, 'daemon/ao.exe'),
  CLAO_CORE_PYTHON: process.env.CLAO_CORE_PYTHON, CLAO_CORE_ROOT: path.join(root, 'clao'),
  HOME: home, USERPROFILE: home, APPDATA: path.join(home, 'appdata'), LOCALAPPDATA: path.join(home, 'local'),
  XDG_CONFIG_HOME: path.join(home, 'config'), XDG_DATA_HOME: path.join(home, 'share'),
  CLAO_FIXTURE_LONG_HOLD: '1', CLAO_FIXTURE_RELEASE_CONFIG: path.join(home, 'release-config'), CLAO_FIXTURE_FAIL_START: path.join(home, 'reject-start'), CLAO_FIXTURE_TRACE: path.join(home, 'external.jsonl'),
  PATH: engine + path.delimiter + path.dirname(process.env.CLAO_CORE_PYTHON) + path.delimiter + env.PATH,
});
const evidence = process.env.CLAO_SCREENSHOTS || path.join(home, 'screenshots');
fs.mkdirSync(evidence, { recursive: true });
(async () => {
  const foreign = process.env.CLAO_TEST_FOREIGN_PORT === '1';
  let foreignRequests = 0;
  const holder = foreign ? require('http').createServer((_req, res) => { foreignRequests++; res.end('{}'); }) : null;
  if (holder) await new Promise(resolve => holder.listen(Number(env.CLAO_NATIVE_PORT), '127.0.0.1', resolve));
  let app = await _electron.launch({ executablePath: path.join(front, 'node_modules/electron/dist/electron.exe'), args: [front], cwd: front, env, timeout: 60000 });
  try {
    let page = app.context().pages()[0] || await app.firstWindow();
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
      const retry = page.getByRole('button', { name: '创建新的尝试（保留草稿）', exact: true });
      if (await retry.isVisible()) await retry.click();
      await page.getByRole('button', { name: 'Agent', exact: true }).click();
      await page.getByRole('menu').getByText('opencode', { exact: true }).click();
      await page.getByRole('button', { name: 'Model', exact: true }).click();
      await page.getByRole('menu').getByText('test/native', { exact: true }).waitFor();
    };
    const start = async (objective) => {
      await page.getByLabel('CLAO 闭环验收').check();
      await page.getByLabel('验收条件（每行一项）').fill('result.txt 内容为 accepted；原项目保持不变');
      await page.getByLabel('Gate 命令（每行一条）').fill('python check.py');
      await page.getByLabel('允许修改范围').fill('**');
      await page.getByLabel('最多修复次数').fill('1');
      if (process.env.CLAO_TEST_ROLES === '1') {
        const details=page.getByText('角色与决策预算',{exact:true});
        await details.click();
        for(const [role,model] of [['auditor','test/second'],['planner','test/native'],['verifier','test/second']]) {
          const row=page.getByTestId('clao-role-'+role);
          await row.getByRole('checkbox').uncheck();
          await row.getByRole('button',{name:'Model',exact:true}).click();
          await page.getByPlaceholder('Search models…').fill(model.split('/')[1]);
          await page.getByRole('menu').getByText(model,{exact:true}).waitFor();
          if(role==='verifier') await page.screenshot({path:path.join(evidence,'roles-native-model-menu.png')});
          await page.getByRole('menu').getByText(model,{exact:true}).click();
        }
        await details.click();
      }
      await page.getByRole('textbox', { name: 'Task', exact: true }).fill(objective);
      await page.getByRole('button', { name: 'Start task', exact: true }).click();
    };
    await open();
    await page.screenshot({ path: path.join(evidence, 'native-model-menu.png') });
    await page.getByPlaceholder('Search models…').fill('second');
    await page.getByRole('menu').getByText('test/second', { exact: true }).click();
    if (!(await page.getByRole('button', { name: 'Model', exact: true }).innerText()).includes('test/second')) throw Error('native model pick not retained');
    if (process.env.CLAO_TEST_RECOVERY === '1') {
      await require('./test-clao-recovery.cjs')({getPage:()=>page,base,home,env,evidence,start,open,git,sourceHead,sourceIndex,
        restart:async()=>{
          const old=JSON.parse(fs.readFileSync(path.join(home,'running.json'),'utf8')).pid;
          await app.close();
          try {process.kill(old,0);process.kill(old);} catch {}
          await new Promise(r=>setTimeout(r,1500));
          app=await _electron.launch({executablePath:path.join(front,'node_modules/electron/dist/electron.exe'),args:[front],cwd:front,env,timeout:60000});
          page=app.context().pages()[0]||await app.firstWindow();
          await page.getByText('原生闭环验证',{exact:true}).first().waitFor({timeout:30000});
          await page.keyboard.press('Escape');
          await page.getByText('原生闭环验证',{exact:true}).first().click({timeout:30000});
          await app.evaluate(({BaseWindow})=>BaseWindow.getAllWindows()[0].setSize(1440,900));
          const next=JSON.parse(fs.readFileSync(path.join(home,'running.json'),'utf8')).pid;
          if(old===next)throw Error('daemon did not restart');
        }});
      return;
    }
    if (process.env.CLAO_TEST_START_FAILURE === '1') {
      const missions = async () => (await (await fetch(base + '/api/v1/clao/missions')).json()).missions;
      fs.writeFileSync(env.CLAO_FIXTURE_FAIL_START, 'controlled external failure');
      await start('启动失败测试：保留这份原请求 <中文>');
      await page.getByText('CLAO · 验收未通过', { exact: true }).waitFor({ timeout: 60000 });
      const first = (await missions())[0];
      if (first.state !== 'FAILED' || first.sessionId || first.operations[0].state !== 'CONFIRMED_FAILURE' || !first.reason.includes('controlled session/new failure')) throw Error('no-start classification failed');
      if (fs.readFileSync(env.CLAO_FIXTURE_TRACE, 'utf8').includes('"kind":"prompt"')) throw Error('failed startup delivered a prompt');
      await page.getByRole('button', { name: '关闭', exact: true }).click();
      await page.reload();
      await page.getByRole('button', { name: '查看原请求：' + first.request.objective, exact: true }).click({ timeout: 15000 });
      await page.getByText('CLAO · 验收未通过', { exact: true }).waitFor();
      await page.screenshot({ path: path.join(evidence, 'startup-failure-visible.png') });
      await page.getByRole('button', { name: '创建新的尝试（保留草稿）', exact: true }).click();
      const task = page.getByRole('textbox', { name: 'Task', exact: true });
      await task.waitFor();
      if (await task.inputValue() !== first.request.objective || await page.getByLabel('允许修改范围').inputValue() !== '**' || !(await page.getByRole('button', { name: 'Model', exact: true }).innerText()).includes('test/second')) throw Error('retry draft lost its project/model/scope');
      await page.getByRole('button', { name: '关闭', exact: true }).click();
      await page.getByRole('button', { name: 'New task', exact: true }).first().click();
      if (await task.inputValue() !== first.request.objective) throw Error('closing lost draft');
      fs.unlinkSync(env.CLAO_FIXTURE_FAIL_START);
      let posts = 0;
      await page.route('**/api/v1/clao/missions', async route => {
        if (route.request().method() !== 'POST') return route.continue();
        posts++;
        await route.fetch(); // Real backend accepts; lose only the HTTP ACK.
        await route.abort('failed');
      });
      await task.fill('新的尝试：正常创建 accepted 结果');
      await page.getByRole('button', { name: 'Start task', exact: true }).click();
      await page.getByText('CLAO · 验收通过', { exact: true }).waitFor({ timeout: 60000 });
      await page.unroute('**/api/v1/clao/missions');
      const rows = await missions(), second = rows.find(m => m.request.id !== first.request.id);
      if (posts !== 1 || rows.length !== 2 || second?.state !== 'DONE' || second.request.projectId !== first.request.projectId || second.request.model !== first.request.model || JSON.stringify(rows.find(m => m.request.id === first.request.id)) !== JSON.stringify(first)) throw Error('ACK loss/new attempt changed identity or replayed');
      await page.getByRole('button', { name: '打开原生 Session', exact: true }).click();
      await page.getByTestId('clao-result').waitFor();
      await page.screenshot({ path: path.join(evidence, 'startup-new-attempt-pass.png') });
      cp.execFileSync(env.CLAO_CORE_PYTHON, ['-c', `import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as db:
 db.execute("""CREATE TRIGGER fixture_receipt_failure BEFORE UPDATE ON clao_missions
 WHEN json_extract(NEW.document, '$.state') = 'SPAWNING'
 AND json_extract(NEW.document, '$.operations[0].state') = 'CONFIRMED_SUCCESS'
 BEGIN SELECT RAISE(ABORT, 'injected receipt write failure'); END""")`, path.join(home,'data/ao.db')]);
      await open(); await page.getByRole('menu').getByText('test/native', { exact: true }).click();
      await start('WAIT_CANCEL：已有 Session，关联回执写入失败');
      await page.getByText('CLAO · 结果尚未确认', { exact: true }).waitFor({ timeout: 60000 });
      await page.getByRole('button', { name: '打开原生 Session', exact: true }).waitFor();
      const uncertain = (await missions()).find(m => m.state === 'UNKNOWN');
      if (!uncertain?.sessionId || uncertain.operations[0].state !== 'UNKNOWN' || !uncertain.reason.includes('injected receipt write failure')) throw Error('immutable owner association missing');
      if (await page.getByRole('button', { name: '创建新的尝试（保留草稿）', exact: true }).isVisible()) throw Error('UNKNOWN offers a replacement');
      await page.screenshot({ path: path.join(evidence, 'startup-unknown-linked.png') });
      const nonce = (await (await fetch(base + '/api/v1/clao/session')).json()).nonce;
      const blocked = await fetch(base + '/api/v1/clao/missions', { method:'POST', headers:{'Content-Type':'application/json','X-CLAO-Nonce':nonce,Origin:base},body:JSON.stringify({...uncertain.request,id:uncertain.request.id+'-new'})});
      if (blocked.ok) throw Error('UNKNOWN did not block admission');
      await page.getByRole('button', { name: '取消闭环', exact: true }).click();
      await page.getByText('CLAO · 已取消', { exact: true }).waitFor({ timeout: 20000 });
      if (fs.readFileSync(env.CLAO_FIXTURE_TRACE,'utf8').split('"kind":"waiting"').length !== 2) throw Error('initial turn repeated');
      if (git('status', '--porcelain') || git('rev-parse', 'HEAD') !== sourceHead || !fs.readFileSync(path.join(project, '.git/index')).equals(sourceIndex)) throw Error('source changed');
      console.log('STARTUP_REPAIR_DESKTOP_PASS', JSON.stringify({ first: first.request.id, second: second.request.id, posts }), evidence);
      return;
    }
    if (process.env.CLAO_TEST_ROLES === '1') {
      const missions=async()=>(await(await fetch(base+'/api/v1/clao/missions')).json()).missions;
      await start('正常任务：独立 Verifier 检查 result.txt');
      await page.getByText('CLAO · 验收通过',{exact:true}).waitFor({timeout:90000});
      let first=(await missions())[0];
      if(first.roleCalls.length!==1||first.roleCalls[0].role!=='verifier'||first.roleCalls[0].choice.model!=='test/second')throw Error('normal gate-first role isolation failed');
      await page.getByText('角色与决策',{exact:true}).click();
      await page.screenshot({path:path.join(evidence,'roles-independent-verifier.png')});
      await page.getByRole('button',{name:'打开原生 Session',exact:true}).click();
      await open();await page.getByRole('menu').getByText('test/native',{exact:true}).click();
      await start('REPAIR_ONCE：依据 Gate 和代码证据修复');
      await page.getByText('CLAO · 验收通过',{exact:true}).waitFor({timeout:90000});
      const repair=(await missions()).find(m=>m.request.objective.startsWith('REPAIR_ONCE'));
      if(repair.roleCalls.map(c=>c.role).join(',')!=='auditor,planner,verifier'||repair.decisions[0].action!=='SEND_LOCAL_FIX'||repair.decisions[0].state!=='APPLIED'||repair.repairs!==1)throw Error('UI repair decision did not reach native services');
      for(const c of repair.roleCalls)if(c.choice.model!==repair.request.roles[c.role].model||c.choice.agent!==repair.request.roles[c.role].agent)throw Error('role config changed at execution');
      await page.getByText('角色与决策',{exact:true}).click();
      await page.getByText('实际 Gate 失败；按输入中的差异和失败输出定位',{exact:true}).waitFor();
      await page.screenshot({path:path.join(evidence,'roles-audit-planner-repair.png')});
      await page.getByRole('button',{name:'打开 auditor 会话',exact:true}).click();
      await page.getByTestId('clao-result').waitFor();
      await open();await page.getByRole('menu').getByText('test/native',{exact:true}).click();
      await start('PLAN_HUMAN：保留证据并交给用户处理');
      await page.getByText('CLAO · 需要处理',{exact:true}).waitFor({timeout:90000});
      await page.getByText('角色与决策',{exact:true}).click();
      const human=(await missions()).find(m=>m.request.objective.startsWith('PLAN_HUMAN'));
      if(human.state!=='HUMAN'||human.resultHead||human.repairs||human.roleCalls.length!==2)throw Error('legal human decision did not stop');
      await page.getByRole('button',{name:'创建新的尝试（保留草稿）',exact:true}).waitFor();
      await page.screenshot({path:path.join(evidence,'roles-human-decision.png')});
      if(git('status','--porcelain')||git('rev-parse','HEAD')!==sourceHead||!fs.readFileSync(path.join(project,'.git/index')).equals(sourceIndex))throw Error('original source changed');
      console.log('ROLE_DESKTOP_PASS',JSON.stringify({normal:first.request.id,repair:repair.request.id,human:human.request.id}),evidence);return;
    }
    await start('创建 result.txt，写入 accepted 和换行。');
    await page.getByText('CLAO · 验收通过', { exact: true }).waitFor({ timeout: 60000 });
    await page.getByText('验收条件、文件与证据', { exact: true }).click();
    await page.screenshot({ path: path.join(evidence, 'closed-loop-pass.png') });
    if (await page.getByRole('button', { name: 'Resume agent', exact: true }).count()) throw Error('closed-loop resume bypass remains visible');
    console.log('PASS', await page.getByTestId('clao-result').innerText());
    await page.getByRole('button', { name: '打开原生 Session', exact: true }).click();
    await open(); await page.getByRole('menu').getByText('test/native', { exact: true }).click();
    await start('FAIL_GATE：保留失败，验证有界修复。');
    await page.getByText('CLAO · 需要处理', { exact: true }).waitFor({ timeout: 60000 });
    await page.getByText('验收条件、文件与证据', { exact: true }).click();
    await page.screenshot({ path: path.join(evidence, 'closed-loop-fail.png') });
    const rows = (await (await fetch(base + '/api/v1/clao/missions')).json()).missions;
    const pass = rows.find(m => m.state === 'DONE'), fail = rows.find(m => m.state === 'HUMAN');
    if (pass?.request.model !== 'test/second' || fail?.repairs !== 1 || fail.resultHead || fail.operations.filter(o => o.kind === 'repair_send').length !== 1) throw Error('UI choice or acceptance facts mismatch');
    if (git('status', '--porcelain') || git('rev-parse', 'HEAD') !== sourceHead || !fs.readFileSync(path.join(project, '.git/index')).equals(sourceIndex) || fs.existsSync(path.join(project, 'result.txt'))) throw Error('source changed');
    console.log('FAIL', await page.getByTestId('clao-result').innerText());
    console.log('DESKTOP_CHECK_PASS', evidence);
  } catch (error) {
    const page = app.context().pages()[0];
    if (page) { await page.screenshot({ path: path.join(home, 'failed-check.png') }); console.error('FAILED_UI', home, (await page.locator('body').innerText()).slice(-5000)); }
    throw error;
  } finally { await app.close(); if (holder) await new Promise(resolve => holder.close(resolve)); }
})().catch(e => { console.error(e); process.exitCode = 1; });
