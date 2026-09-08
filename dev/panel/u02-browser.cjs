/* Actual production UI + HTTP + Controller, with only engine/model boundaries
 * replaced by test_u02_local_execution's isolated protocol process. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const [origin,project,scenario,out]=process.argv.slice(2);
assert(/^http:\/\/127\.0\.0\.1:\d+$/.test(origin));
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1366,height:768},reducedMotion:'reduce'});
  const errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST') writes.push(new URL(r.url()).pathname);});
  await page.goto(origin);
  await page.click('#btnNew');
  await page.fill('#projectPath',project);
  await page.click('#openProject');
  await page.waitForFunction(()=>document.getElementById('sourceSummary').textContent.includes('个文件'));
  assert((await page.locator('#f_project_meta').textContent()).includes(project));
  await page.locator('#stepNext').focus();await page.keyboard.press('Enter');
  const goal='保留中文与引号 " <img src=x onerror=window.PWNED=1> & 内容';
  await page.fill('#f_obj',goal);await page.fill('#f_ac','x 等于 2');
  await page.click('#stepNext');await page.fill('#f_paths','app.py');
  await page.fill('#f_gate',scenario==='normal'?'python -c "import app; assert app.x == 2"':'python -c "pass"');
  await page.click('#stepBack');assert.equal(await page.locator('#f_obj').inputValue(),goal);
  await page.click('#stepNext');await page.click('#stepNext');
  await page.click('#btnStart');
  assert((await page.locator('#sourceConfirmError').textContent()).includes('确认'));
  assert.equal(writes.filter(p=>p==='/api/mission').length,0);
  await page.check('#sourceConfirmed');
  await page.locator('#btnStart').evaluate(b=>{b.click();b.click();});
  await page.waitForFunction(()=>!document.getElementById('newMission').open);
  assert.equal(writes.filter(p=>p==='/api/mission').length,1);
  if(scenario==='question'){
   await page.locator('#approvalRequests textarea').waitFor();
   await page.fill('#approvalRequests textarea','保留中文 <tag>');
   // An SSE update may refresh facts, but must preserve the in-progress answer.
   await page.waitForTimeout(2200);
   assert.equal(await page.locator('#approvalRequests textarea').inputValue(),'保留中文 <tag>');
   await page.getByRole('button',{name:'提交回答',exact:true}).click();
   await page.waitForFunction(()=>document.getElementById('approvalCard').hidden);
  }
  await page.waitForFunction(()=>document.getElementById('detailState').textContent.includes('已完成'),{},{timeout:20000});
  assert((await page.locator('#resultLocation').textContent()).includes('integration'));
  assert.equal(await page.evaluate(()=>Boolean(window.PWNED)),false);
  assert.equal(await page.locator('img,[onerror],[onload]').count(),0);
  assert.equal(writes.filter(p=>p==='/api/mission').length,1);
  await page.screenshot({path:path.join(out,scenario+'-task.png'),animations:'disabled'});
  await page.click('[data-view="settings"]');await page.click('button[data-theme="dark"]');
  await page.setViewportSize({width:390,height:844});
  await page.click('[data-view="tasks"]');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(out,scenario+'-390-dark.png'),animations:'disabled'});
  assert.deepEqual(errors,[]);
  console.log('U02_BROWSER_PASS '+scenario+' screenshots='+out);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
