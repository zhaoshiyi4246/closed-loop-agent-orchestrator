/* Actual product page and local HTTP/SQLite/Git result paths. No sample mode. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const [origin,mid,out]=process.argv.slice(2);fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:900},acceptDownloads:true,permissions:['clipboard-read','clipboard-write']});
 const page=await context.newPage(),errors=[],writes=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST') writes.push({path:new URL(r.url()).pathname,body:r.postDataJSON()});});
 await page.goto(origin);await page.waitForFunction(()=>LIVE?.mission?.id==='M-F04');
 async function open(id){
  await page.locator('[data-view="tasks"]').first().click();
  if(await page.locator('#backToTasks').isVisible())await page.click('#backToTasks');
  await page.locator('[data-mission-id="'+id+'"] .link-row').click();
  await page.waitForFunction(id=>LAST?.mission?.id===id && RESULTS.get(id)?.status==='loaded',id);
 }
 await open(mid);
 assert((await page.locator('#resultAC').textContent()).includes('x equals 2 <script> & "'));
 assert.equal(await page.locator('#resultAC script,#resultAC img').count(),0);
 assert((await page.locator('#resultChanges').textContent()).includes('重命名'));
 assert((await page.locator('#resultIdentity').textContent()).includes('冻结来源'));
 await page.getByRole('button',{name:'复制结果路径',exact:true}).click();
 await page.waitForFunction(()=>document.getElementById('resultOperation').textContent==='结果路径已复制');
 assert((await page.evaluate(()=>navigator.clipboard.readText())).endsWith('integration'));
 await page.getByRole('button',{name:'打开结果目录',exact:true}).click();
 await page.waitForFunction(()=>document.getElementById('resultOperation').textContent.includes('Windows'));
 // Hold only delivery of a successful real export response; current runtime A stays attached.
 let release,received;
 const ready=new Promise(r=>received=r),gate=new Promise(r=>release=r);
 await page.route('**/api/result/export',async route=>{const response=await route.fetch();assert(response.ok());received();await gate;await route.fulfill({response});});
 await page.getByRole('button',{name:'生成结果包',exact:true}).evaluate(b=>{b.click();b.click();});
 await ready;await open('M-F04');
 const prior=await page.locator('#resultOperation').textContent();release();
 await page.waitForFunction(()=>!PENDING.size);
 assert.equal(await page.locator('#resultOperation').textContent(),prior);
 assert.equal(writes.filter(r=>r.path==='/api/result/export').length,1);
 assert(writes.every(r=>!r.path.startsWith('/api/result/') || r.body.mission_id===mid));
 assert.equal(await page.evaluate(()=>LIVE.mission.id),'M-F04');
 await open(mid);
 assert((await page.locator('#resultOperation').textContent()).includes('已保存'));
 const downloadEvent=page.waitForEvent('download');
 await page.getByRole('button',{name:'下载结果包',exact:true}).click();
 const download=await downloadEvent;assert.equal(await download.failure(),null);
 const raw=fs.readFileSync(await download.path());
 const result=await (await page.request.get(origin+'/api/result?mission_id='+mid)).json();
 assert.equal(crypto.createHash('sha256').update(raw).digest('hex'),result.result.exports[0].sha256);
 await page.screenshot({path:path.join(out,'result-center.png'),fullPage:true});
 await page.locator('#resultDiff summary').click();
 await page.locator('#resultDiff').scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(out,'file-diff-and-acceptance.png'),fullPage:true});
 // Clipboard rejection is visible and is not a fake success toast.
 await page.evaluate(()=>Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:async()=>{throw new Error('denied by browser');}}));
 await page.getByRole('button',{name:'复制结果路径',exact:true}).click();
 await page.waitForFunction(()=>document.getElementById('resultOperation').textContent.includes('复制失败'));
 for(const width of [1440,1366,768,390]){
  await page.setViewportSize({width,height:900});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page overflow at '+width);
 }
 await page.locator('[data-view="settings"]').first().click();
 // Exercise the product theme input; selectors are the existing U01 contract.
 await page.locator('#themeControl [data-theme="dark"]').click();
 await open(mid);await page.locator('#resultExports').scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(out,'export-390-dark.png'),fullPage:true});
 await page.locator('#refreshResult').focus();await page.keyboard.press('Enter');
 await page.waitForFunction(mid=>RESULTS.get(mid)?.status==='loaded',mid);
 assert.deepEqual(errors,[]);
 console.log('PASS: real Edge result/AC/diff/export/download, clipboard success/failure, delayed B response while viewing A, keyboard, four widths, dark theme; no models.');
 await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
