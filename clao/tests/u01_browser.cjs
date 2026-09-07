/* Development-only actual Edge tests. No page scripts are replaced; no AO calls.
 * Run through test_u01_panel.py against its isolated SQLite/HTTP fixture.
 */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'), os=require('node:os'), path=require('node:path');
const [origin,out]=process.argv.slice(2);
assert(/^http:\/\/127\.0\.0\.1:\d+$/.test(origin), 'isolated loopback origin required');
fs.mkdirSync(out,{recursive:true});
let checks=0;
function check(value,message){assert(value,message);checks++;}
async function noOverflow(page){check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'page horizontal overflow');}
async function shot(page,name){await page.screenshot({path:path.join(out,name+'.png'),animations:'disabled'});}
async function view(page,name){await page.locator('[data-view="'+name+'"]').click();await page.locator('#view-'+name).waitFor({state:'visible'});}
function luminance(c){return c.map(n=>{n/=255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4;}).reduce((a,n,i)=>a+n*[.2126,.7152,.0722][i],0);}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const errors=[];
  try{
    const context=await browser.newContext({viewport:{width:1440,height:900},reducedMotion:'reduce'});
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    const writes=[],reads=[];
    page.on('request',r=>{if(r.method()==='POST') writes.push(r.url());if(r.url().includes('/api/')) reads.push(r.url());});
    for(const [width,height] of [[1440,900],[1366,768],[768,1024],[390,844]]){
      await page.setViewportSize({width,height});
      for(const theme of ['light','dark']){
        await page.goto(origin+'/?preview=running');await page.waitForFunction(()=>LAST && PROJECTS.length);
        await view(page,'settings');await page.locator('button[data-theme="'+theme+'"]').click();await view(page,'overview');
        await noOverflow(page);
        check(await page.locator('.navigation button').count()===4,'four fixed entries');
        check(await page.locator('.navigation').evaluate(n=>{const r=n.getBoundingClientRect();return r.bottom<=innerHeight && r.top>=0;}),'navigation reachable');
        check(await page.locator('.navigation use').first().evaluate(n=>n.getBBox().width>0),'SVG symbol must actually render');
        const pairs=await page.evaluate(()=>{
          const style=getComputedStyle(document.documentElement), rgb=color=>{const e=document.createElement('span');e.style.color=color;document.body.append(e);const result=getComputedStyle(e).color.match(/[\d.]+/g).map(Number).slice(0,3);e.remove();return result;};
          const val=k=>rgb(style.getPropertyValue(k));
          return [[val('--ink'),val('--surface')],[val('--dim'),val('--bg')],[val('--blue'),val('--blue-soft')],[val('--red'),val('--red-soft')],[val('--amber'),val('--amber-soft')],[val('--green'),val('--green-soft')]];
        });
        pairs.forEach(pair=>check(contrast(...pair)>=4.5,'semantic text contrast >=4.5:1'));
        for(const name of ['tasks','models','settings']) {
          await view(page,name);await noOverflow(page);
          if(name==='models' && width===390) check((await page.locator('#view-models .list-row .grow').first().boundingBox()).width>=200,'mobile service description is not squeezed by trailing status');
        }
        await view(page,'overview');
        check(await page.locator('#btnNew').evaluate(n=>n.getBoundingClientRect().height>=44),'primary action target >=44px');
        await shot(page,'overview-'+width+'-'+theme);
        // Controls at the bottom remain reachable after scroll, including narrow screens.
        await page.locator('#recentResults').scrollIntoViewIfNeeded();await noOverflow(page);
      }
    }
    check(reads.length===0 && writes.length===0,'preview must not connect to real read/write APIs');
    await page.setViewportSize({width:1440,height:900});
    await page.goto(origin+'/?preview=empty');await view(page,'settings');
    await page.locator('button[data-theme="light"]').click();await page.reload();
    check(await page.locator('html').getAttribute('data-theme')==='light','theme persists refresh');
    await view(page,'settings');await page.locator('button[data-theme="system"]').click();await page.emulateMedia({colorScheme:'dark'});await page.waitForFunction(()=>document.documentElement.dataset.theme==='dark');
    check(await page.locator('html').getAttribute('data-theme')==='dark','system theme reacts');
    await page.emulateMedia({colorScheme:'light'});await page.waitForFunction(()=>document.documentElement.dataset.theme==='light');check(await page.locator('html').getAttribute('data-theme')==='light','system theme returns');
    // Keyboard navigation, focus return, and modal trapping use actual browser events.
    await page.locator('[data-view="tasks"]').focus();await page.keyboard.press('Enter');
    check(await page.locator('#view-tasks').isVisible(),'keyboard top navigation');
    await view(page,'overview');await page.locator('#btnNew').focus();await page.keyboard.press('Enter');
    check(await page.locator('#newMission').isVisible(),'keyboard opens form');
    await page.locator('#stepNext').focus();await page.keyboard.press('Enter');
    check(await page.locator('#f_project_error').textContent()!=='','inline project error');
    check(await page.locator('#f_project').inputValue()==='','no implicit project choice');
    await page.selectOption('#f_project','sample-project');await page.locator('#stepNext').focus();await page.keyboard.press('Enter');
    const unsafe='中文 " <img src=x onerror=window.PWNED=1> & \' 长目标';
    await page.fill('#f_obj',unsafe);await page.fill('#f_ac','正常输入能完成\n错误给出行号');
    await page.locator('#stepNext').focus();await page.keyboard.press('Enter');
    await page.fill('#f_paths','src/**\ntests/**');await page.fill('#f_gate','python -m pytest tests -q');
    await page.locator('#stepBack').focus();await page.keyboard.press('Enter');
    check(await page.locator('#f_obj').inputValue()===unsafe,'back preserves draft');
    await page.click('#stepNext');await page.click('#stepNext');
    check((await page.locator('#formReview').textContent()).includes(unsafe),'review preserves safe text');
    check(await page.locator('img,[onerror],[onload]').count()===0,'no executable DOM');
    await page.click('#formReview button');check(await page.locator('#f_project').inputValue()==='sample-project','edit preserves selection');
    await page.click('#stepNext');await page.click('#stepNext');await page.click('#stepNext');
    await page.click('#btnStart');
    check((await page.locator('#formSubmitError').textContent()).includes('不会发送写请求'),'preview does not fake success');
    await shot(page,'form-confirm-light');
    await page.locator('#closeMission').focus();await page.keyboard.press('Shift+Tab');
    check(await page.evaluate(()=>document.getElementById('newMission').contains(document.activeElement)),'dialog traps focus');
    await page.keyboard.press('Escape');
    check(await page.locator('#btnNew').evaluate(n=>n===document.activeElement),'dialog restores original focus');
    await page.click('#btnPreview');await page.keyboard.press('Escape');
    check(await page.locator('#btnPreview').evaluate(n=>n===document.activeElement),'preview dialog restores focus');
    // The full required state set shares the production renderer, with explicit differences.
    const expected={empty:'尚无任务',running:'进行中',approval:'等待审批',success:'已完成',failure:'执行失败',cancelling:'取消中',cancelled:'已取消',stop_unknown:'停止尚未确认',disconnected:'进行中',gate_read_error:'需要人工处理'};
    for(const [state,label] of Object.entries(expected)){
      await page.selectOption('#previewSelect',state);check(await page.locator('#overviewState').textContent()===label,'distinct state '+state);
      if(state!=='empty'){
        await page.locator('#currentTask button').click();
        check(await page.locator('#taskDetail').isVisible(),'shared task detail '+state);
        if(state==='failure') check((await page.locator('#evidence').textContent()).includes('overall=fail') && (await page.locator('#evidence').textContent()).includes('command=pass'),'exit zero never overrides scope failure');
        if(state==='gate_read_error') check((await page.locator('#evidence').textContent()).includes('Gate 读取失败'),'read_error visible');
        if(state==='disconnected') check((await page.locator('#connectionStatus').textContent()).includes('断连'),'disconnect visible');
        if(['failure','stop_unknown','gate_read_error'].includes(state)) await shot(page,'detail-'+state+'-light');
      }
      await view(page,'overview');
    }
    await page.selectOption('#previewSelect','approval');await shot(page,'overview-approval-light');
    await view(page,'tasks');await shot(page,'tasks-light');await page.locator('#missionsList button').first().click();
    await page.locator('#loadedDetail > details > summary').click();
    check(await page.locator('#diagnostics').isVisible(),'advanced diagnostic opens');
    await view(page,'models');await shot(page,'models-light');await view(page,'settings');await shot(page,'settings-light');
    check(writes.length===0 && reads.length===0,'all preview actions remain isolated');
    await page.setViewportSize({width:390,height:844});await page.selectOption('#previewSelect','empty');
    await view(page,'settings');await page.locator('button[data-theme="dark"]').click();
    await view(page,'models');await shot(page,'models-390-dark');
    await view(page,'overview');await page.click('#btnNew');
    check(await page.locator('#f_project').inputValue()==='sample-project','reopened form retains project');
    // Reopened progressive form retains the earlier confirmation step and drafts.
    await page.locator('#formReview').waitFor({state:'visible'});await noOverflow(page);
    check(await page.locator('#newMission').evaluate(n=>n.scrollWidth<=n.clientWidth),'390px dialog has no horizontal overflow');
    await shot(page,'form-390-dark');await page.keyboard.press('Escape');
    await page.setViewportSize({width:1440,height:900});
    // A real HTTP/SQLite page must not be supplemented with preview data.
    await page.goto(origin+'/');await page.waitForFunction(()=>LAST && PROJECTS.length);
    check(await page.locator('#previewBanner').isHidden(),'normal mode is not sample mode');
    check((await page.locator('#currentTask').textContent()).includes('正常中文 objective'),'production SQLite objective shown');
    check(!(await page.locator('#currentTask').textContent()).includes('数据导入'),'no sample fallback');
    await view(page,'settings');await page.fill('#k_poll','0.375');await page.locator('#k_idle').focus();
    await page.evaluate(()=>render(structuredClone(LAST)));
    check(await page.locator('#k_poll').inputValue()==='0.375','snapshot cannot erase unfocused dirty settings');
    await view(page,'overview');await page.click('#btnNew');await page.selectOption('#f_project','safe-project');await page.click('#stepNext');await page.fill('#f_obj',unsafe);
    await page.evaluate(()=>render(structuredClone(LAST)));
    check(await page.locator('#f_obj').evaluate((n,value)=>n===document.activeElement && n.value===value,unsafe),'background does not steal form focus or draft');
    await page.keyboard.press('Escape');await view(page,'tasks');
    const button=page.locator('#missionsList button').first();await button.focus();
    await page.evaluate(()=>{window.savedSnapshot=structuredClone(LAST);const s=structuredClone(LAST);s.mission.objective='new safe title';render(s);render(window.savedSnapshot);});
    check(await button.evaluate(n=>n===document.activeElement),'focused task button survives changed snapshot');
    await view(page,'overview');
    check((await page.locator('#missionsList').textContent()).includes('正常中文 objective') && !(await page.locator('#missionsList').textContent()).includes('new safe title'),'deferred updates keep latest facts');
    await page.evaluate(()=>{const s=structuredClone(LAST);s.mission.state='__proto__';render(s);});
    check(await page.locator('#overviewState').textContent()==='状态未知','unsupported state remains safe unknown');
    await page.evaluate(()=>{const s=structuredClone(LAST);s.mission.objective='中文 < > & " \' long-title '.repeat(80);s.mission.reason='error <script> '.repeat(800)+' LONG_END';render(s);});
    await page.setViewportSize({width:390,height:844});await noOverflow(page);
    check((await page.locator('#currentTask').textContent()).includes('LONG_END'),'long reason is retained as scrollable text');
    check(errors.length===0,'no page errors: '+errors.join('; '));
    await context.close();
  }finally{await browser.close();}
  // Actual browser zoom (chrome.tabs.setZoom), NOT CSS zoom or device emulation.
  // Extension/profile live only in this generated, verified temporary test directory.
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'clao-u01-zoom-')), ext=path.join(root,'extension');
  fs.mkdirSync(ext);fs.writeFileSync(path.join(ext,'manifest.json'),JSON.stringify({manifest_version:3,name:'Isolated U01 zoom test',version:'1.0',permissions:['tabs'],background:{service_worker:'zoom.js'}}));
  fs.writeFileSync(path.join(ext,'zoom.js'),'chrome.runtime.onInstalled.addListener(()=>{});');
  let zoomContext;
  try{
    zoomContext=await chromium.launchPersistentContext(path.join(root,'profile'),{channel:'msedge',headless:true,viewport:null,reducedMotion:'reduce',args:['--window-size=1440,900','--disable-extensions-except='+ext,'--load-extension='+ext]});
    const worker=zoomContext.serviceWorkers()[0] || await zoomContext.waitForEvent('serviceworker');
    const page=await zoomContext.newPage();await page.goto(origin+'/?preview=empty');
    const zoom=await worker.evaluate(async origin=>{const tabs=await chrome.tabs.query({});const tab=tabs.find(t=>t.url?.startsWith(origin));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id);},origin);
    check(zoom===2,'actual browser zoom is 200%');await noOverflow(page);
    for(const name of ['overview','tasks','models','settings']){await view(page,name);await noOverflow(page);}
    await view(page,'overview');await page.click('#btnNew');await page.selectOption('#f_project','sample-project');await page.click('#stepNext');await page.fill('#f_obj','200% 缩放测试');await page.fill('#f_ac','主要操作可达');await page.click('#stepNext');await page.fill('#f_paths','src/**');await page.click('#stepNext');
    await page.locator('#btnStart').scrollIntoViewIfNeeded();const cdp=await zoomContext.newCDPSession(page);
    const screenshot=await cdp.send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false});
    fs.writeFileSync(path.join(out,'form-200-percent-light.png'),Buffer.from(screenshot.data,'base64'));
    check(await page.locator('#btnStart').evaluate(n=>{const r=n.getBoundingClientRect();return r.bottom<=innerHeight && r.right<=innerWidth && r.top>=0;}),'200% primary action reachable');
    await page.keyboard.press('Escape');check(await page.locator('#btnNew').evaluate(n=>n===document.activeElement),'200% focus return');
  }finally{
    await zoomContext?.close();
    const target=path.resolve(root), parent=path.resolve(os.tmpdir());
    assert(path.dirname(target)===parent && path.basename(target).startsWith('clao-u01-zoom-'));
    fs.rmSync(target,{recursive:true,force:true});
  }
  console.log('U01_BROWSER_PASS '+checks+' assertions; actual Edge, 8 overview widths/themes, 200% browser zoom; '+out);
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
