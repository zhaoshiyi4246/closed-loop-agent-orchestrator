/* Product page + real local HTTP/Controller. Only engine/providers are fixtures. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const [origin,project,scenario,out]=process.argv.slice(2);
assert(/^http:\/\/127\.0\.0\.1:\d+$/.test(origin));fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:900},reducedMotion:'reduce'});
  const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST')writes.push({path:new URL(r.url()).pathname,body:r.postDataJSON()});});
  await page.goto(origin);await page.waitForFunction(()=>document.getElementById('connectionStatus').textContent==='已连接');
  assert.equal(await page.locator('#environmentStatus').textContent(),'尚未检查');
  await page.locator('#checkEnvironment').evaluate(b=>{b.click();b.click();});
  await page.waitForFunction(()=>['可运行','需要处理'].includes(document.getElementById('environmentStatus').textContent));
  assert.equal(writes.filter(r=>r.path==='/api/readiness').length,1);
  if(scenario==='no_login'){
   assert((await page.locator('#environmentReason').textContent()).includes('ChatGPT'));
   await page.screenshot({path:path.join(out,'environment-unready.png')});
   await page.click('#btnNew');await page.fill('#projectPath',project);await page.click('#openProject');
   await page.waitForFunction(()=>document.getElementById('sourceSummary').textContent.includes('个文件'));
   await page.click('#stepNext');await page.fill('#f_obj','未就绪时仍可编辑草稿');await page.click('#closeMission');
   await page.click('[data-view="tasks"]');await page.fill('#taskSearch','历史 B');
   await page.locator('#missionsList .link-row').first().click();await page.waitForFunction(()=>document.getElementById('detailReason').textContent==='B 的失败原因');
   await page.click('[data-new]');assert.equal(await page.locator('#f_obj').inputValue(),'未就绪时仍可编辑草稿');
   assert.equal(writes.filter(r=>r.path==='/api/mission').length,0);
  }else{
   assert.equal(await page.locator('#environmentStatus').textContent(),'可运行');
   await page.click('#btnNew');await page.fill('#projectPath',project);await page.click('#openProject');
   await page.waitForFunction(()=>document.getElementById('sourceSummary').textContent.includes('个文件'));
   await page.locator('#stepNext').focus();await page.keyboard.press('Enter');
   const goal='本次目标 中文 " <img src=x onerror=window.PWNED=1> & 长目标 '.repeat(3);
   await page.fill('#f_obj',goal);await page.fill('#f_ac','通过指定检查');await page.click('#stepNext');
   await page.fill('#f_paths','app.py');await page.fill('#f_forbidden','private/**');
   await page.fill('#f_gate',scenario==='normal'?`python -c "import runpy; assert runpy.run_path('app.py')['x'] == 2"\npython -c "pass"`:'python -c "pass"');
   await page.click('#stepBack');assert.equal(await page.locator('#f_obj').inputValue(),goal);await page.click('#stepNext');await page.click('#stepNext');
   await page.fill('#param_worker_model','journey-worker');await page.fill('#param_gate_timeout_seconds','2.25');
   await page.fill('#param_budgets_max_runtime_seconds','89.5');
   await page.waitForFunction(()=>FORM_CONFIG?.values?.worker?.model==='journey-worker' && FORM_CONFIG.values.gate.timeout_seconds===2.25 && FORM_CONFIG.values.budgets.max_runtime_seconds===89.5);
   assert((await page.locator('#formReview').textContent()).includes('private/**'));
   await page.check('#sourceConfirmed');await page.locator('#btnStart').evaluate(b=>{b.click();b.click();});
   await page.waitForFunction(()=>!document.getElementById('newMission').open);
   const mid=await page.evaluate(()=>DETAIL_ID);
   assert.equal(writes.filter(r=>r.path==='/api/mission').length,1);
   const submitted=writes.find(r=>r.path==='/api/mission').body;
   assert.equal(submitted.config_snapshot.values.worker.model,'journey-worker');
   assert.equal(submitted.config_snapshot.values.gate.timeout_seconds,2.25);
   const snap=await (await page.request.get(origin+'/api/mission?mission_id='+mid)).json();
   assert.equal(snap.mission_config.snapshot.revision,submitted.config_snapshot.revision);
   if(scenario==='manual' || scenario==='kill_live'){
    if(scenario==='manual') await page.getByRole('button',{name:'拒绝',exact:true}).waitFor();
    else await page.waitForFunction(()=>!document.getElementById('btnStop').disabled);
    await page.click('[data-view="overview"]');
    if(scenario==='manual') assert((await page.locator('#attention').textContent()).includes('去处理'));
    let delayedFile, fileStarted;
    const fileHeld=new Promise(resolve=>{fileStarted=resolve;});
    if(scenario==='manual'){
     await page.route('**/api/file?*',route=>{delayedFile=route;fileStarted();});
     await page.evaluate(()=>{window.fileProbe=loadFile('memory.md');});await fileHeld;
    }
    await page.click('[data-view="tasks"]');await page.click('#backToTasks');await page.fill('#taskSearch','历史 B');
    assert.equal(await page.locator('#missionsList .mrow').count(),1);await page.locator('#missionsList .link-row').first().click();
    await page.waitForFunction(()=>document.getElementById('detailReason').textContent==='B 的失败原因');
    if(scenario==='manual'){
     await delayedFile.fulfill({status:503,contentType:'application/json',body:JSON.stringify({ok:false,error:'A 的延迟读取错误'})});
     await page.evaluate(()=>window.fileProbe);await page.unroute('**/api/file?*');
     assert(!(await page.locator('#memPre').textContent()).includes('A 的延迟读取错误'));
     assert(!(await page.locator('#clientErrors').textContent()).includes('A 的延迟读取错误'));
    }
    assert(await page.locator('#btnStop').isHidden());assert.equal(await page.locator('#approvalRequests button').count(),0);
    assert((await page.locator('#resultLocation').textContent()).includes('已失效'));
    const active=(await (await page.request.get(origin+'/api/state')).json()).mission.id;assert.equal(active,mid);
    await page.reload();await page.waitForFunction(()=>document.getElementById('detailReason').textContent==='B 的失败原因');
    assert.equal((await (await page.request.get(origin+'/api/state')).json()).mission.id,mid);
    assert.equal(writes.filter(r=>r.path==='/api/attach').length,0);
    assert.equal(writes.filter(r=>r.path==='/api/mission').length,1);
    if(scenario==='manual') await page.screenshot({path:path.join(out,'history-during-execution.png')});
    await page.click('[data-view="overview"]');await page.getByRole('button',{name:'查看任务详情',exact:true}).click();
    if(scenario==='manual'){
     await page.getByRole('button',{name:'拒绝',exact:true}).waitFor();
     assert.equal(await page.getByRole('button',{name:'允许一次',exact:true}).count(),0);
     await page.locator('#approvalRequests details summary').click();
     assert((await page.locator('#approvalRequests').textContent()).includes('+x=2'));
     await page.locator('#approvalCard').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'approval-review.png')});
     await page.getByRole('button',{name:'拒绝',exact:true}).click();
     await page.waitForFunction(()=>!document.querySelector('#approvalRequests button') || [...document.querySelectorAll('#approvalRequests button')].every(b=>b.disabled));
     assert.equal(writes.filter(r=>r.path==='/api/approval').length,1);
     await page.waitForFunction(()=>['需处理','已取消'].includes(document.getElementById('detailState').textContent));
     assert(!(await page.locator('#resultConclusion').textContent()).includes('已通过最终'));
    }else{
     await page.locator('#btnStop').evaluate(b=>{b.click();b.click();});
     await page.waitForFunction(()=>document.getElementById('detailNext').textContent.includes('停止尚未确认'));
     assert.equal(writes.filter(r=>r.path==='/api/stop').length,1);
     assert(!(await page.locator('#detailState').textContent()).includes('已取消'));
     assert.equal(await page.locator('#friendlyPhase').textContent(),'等待停止确认');
     await page.click('[data-view="settings"]');await page.click('button[data-theme="dark"]');await page.setViewportSize({width:390,height:844});
     await page.click('[data-view="tasks"]');await page.locator('#toast').waitFor({state:'hidden'});await page.screenshot({path:path.join(out,'stop-unknown-dark.png')});
    }
   }else{
    await page.waitForFunction(()=>document.getElementById('detailState').textContent==='已完成',{},{timeout:25000});
    assert((await page.locator('#resultLocation').textContent()).includes('integration'));
    assert((await page.locator('#verifierSummary').textContent()).includes('PASS'));
    await page.screenshot({path:path.join(out,'task-result.png')});
    await page.click('[data-view="settings"]');
    await page.getByText('高级配置',{exact:false}).first().click();
    const defaults=JSON.parse(await page.locator('#configJson').inputValue());defaults.worker.model='next-mission-default';
    await page.fill('#configJson',JSON.stringify(defaults));await page.click('#btnConfigAll');
    await page.waitForFunction(()=>LIVE.default_config.values.worker.model==='next-mission-default');
    assert.equal(await page.evaluate(()=>LAST.mission_config.snapshot.values.worker.model),'journey-worker');
    await page.click('[data-view="tasks"]');await page.click('[data-new]');
    assert.equal(await page.locator('#param_worker_model').inputValue(),'next-mission-default');
    assert.equal(await page.locator('#sourceConfirmed').isChecked(),false);
    await page.click('#closeMission');
    assert.equal(await page.evaluate(()=>phaseLabel({phase:'model_request',role:'planner'})),'规划模型执行');
    assert.equal(await page.evaluate(()=>phaseLabel({phase:'model_request',role:'auditor'})),'审计模型执行');
    // Ordered snapshots reject late events; disconnection never replays writes.
    const accepted=await page.evaluate(()=>{const old=structuredClone(LIVE);old.stream.sequence-=1;old.mission.state='FAILED';return acceptSnapshot(old);});assert.equal(accepted,false);
    await page.evaluate(()=>disconnect());assert((await page.locator('#connectionStatus').textContent()).includes('断'));
    await page.waitForFunction(()=>document.getElementById('connectionStatus').textContent==='已连接');
    assert.equal(await page.locator('#detailState').textContent(),'已完成');
    for(const theme of ['light','dark']){
     await page.click('[data-view="settings"]');await page.click('button[data-theme="'+theme+'"]');await page.click('[data-view="tasks"]');
     for(const [width,height] of [[1440,900],[1366,768],[768,900],[390,844]]){
      await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      assert(await page.locator('#backToTasks').isVisible());
     }
    }
    // 200% equivalent layout viewport, plus actual CSS zoom for operation reachability.
    await page.setViewportSize({width:720,height:450});await page.evaluate(()=>document.body.style.zoom='2');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.locator('#backToTasks').scrollIntoViewIfNeeded();await page.click('#backToTasks');
    await page.evaluate(()=>document.body.style.zoom='');await page.setViewportSize({width:1366,height:768});
    assert.equal(writes.filter(r=>r.path==='/api/mission').length,1);
   }
   assert.equal(await page.evaluate(()=>Boolean(window.PWNED)),false);
  }
  assert.deepEqual(errors,[]);console.log('U02_JOURNEY_BROWSER_PASS '+scenario);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
