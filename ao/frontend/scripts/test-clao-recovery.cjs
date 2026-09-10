// Runs inside the existing real Electron/daemon/Git fixture, never a fake runtime.
const fs=require('fs'),path=require('path'),cp=require('child_process');
module.exports=async({getPage,base,home,env,evidence,start,open,git,sourceHead,sourceIndex,restart})=>{
 let page=getPage();
 const rows=async()=>(await(await fetch(base+'/api/v1/clao/missions')).json()).missions;
 const fault=sql=>cp.execFileSync(env.CLAO_CORE_PYTHON,['-c','import sqlite3,sys\nwith sqlite3.connect(sys.argv[1]) as db: db.executescript(sys.argv[2])',path.join(home,'data/ao.db'),sql]);
 fault("CREATE TRIGGER ui_checkpoint_loss BEFORE UPDATE ON clao_missions WHEN json_extract(NEW.document,'$.checkpoint.stage')='gate' AND json_extract(OLD.document,'$.checkpoint.stage')='worker' BEGIN SELECT RAISE(ABORT,'controlled gate boundary receipt loss'); END;");
 await start('原任务：固定 Worker 进度后继续验收');
 await page.getByText('CLAO · 已暂停',{exact:true}).waitFor({timeout:60000});
 const original=(await rows())[0];
 fault('DROP TRIGGER ui_checkpoint_loss;');
 await restart();page=getPage();
 await page.getByRole('button',{name:'查看原请求：'+original.request.objective,exact:true}).click();
 await page.getByText('CLAO · 已暂停',{exact:true}).waitFor();
 await page.screenshot({path:path.join(evidence,'continue-original.png')});
 await page.getByRole('button',{name:'继续原任务',exact:true}).click();
 await page.getByText('CLAO · 验收通过',{exact:true}).waitFor({timeout:60000});
 const done=(await rows())[0];
 if(done.sessionId!==original.sessionId||done.request.id!==original.request.id||done.operations.filter(o=>o.kind==='spawn').length!==1)throw Error('continue created a new Worker');
 await page.screenshot({path:path.join(evidence,'continued-result.png')});
 await page.getByRole('button',{name:'关闭',exact:true}).click();
 await open();await page.getByRole('menu').getByText('test/native',{exact:true}).click();
 await start('HOLD_CONFIG REPAIR_ONCE：界面补充与原生 Chat');
 await page.getByText('CLAO · 执行中',{exact:true}).waitFor({timeout:30000});
 const active=(await rows()).find(m=>m.state==='RUNNING');
 const details=()=>page.getByTestId('clao-directives');
 await details().locator('summary').first().click();
 await page.getByLabel('指令接收对象').selectOption('auditor');
 await page.getByLabel('补充要求').fill('界面审核要求 <中文>：不得修改验收条件');
 let release,arrived;
 const waitArrived=new Promise(r=>arrived=r),hold=new Promise(r=>release=r);
 let posts=0;
 await page.route('**/clao/missions/'+active.request.id+'/directives',async route=>{
  if(route.request().method()!=='POST')return route.continue();
  posts++;const response=await route.fetch();arrived();await hold;await route.fulfill({response});
 });
 await page.getByRole('button',{name:'提交补充要求',exact:true}).click();await waitArrived;
 // Read B while A's acknowledged write is held in transit. Returning to A
 // preserves its target and later edits; B never displays A's receipt.
 await page.getByRole('button',{name:'关闭',exact:true}).click();
 await page.getByRole('button',{name:'查看原请求：'+original.request.objective,exact:true}).click();
 if((await page.getByRole('dialog').innerText()).includes('界面审核要求'))throw Error('A receipt leaked to B');
 await page.getByRole('button',{name:'关闭',exact:true}).click();
 await page.getByRole('button',{name:'查看原请求：'+active.request.objective,exact:true}).click();
 await details().locator('summary').first().click();
 if(await page.getByLabel('指令接收对象').inputValue()!=='auditor')throw Error('draft target lost');
 await page.getByLabel('补充要求').fill('后续草稿，旧响应不得清空');release();
 await page.waitForTimeout(1000);
 if(await page.getByLabel('补充要求').inputValue()!=='后续草稿，旧响应不得清空'||posts!==1)throw Error('late response cleared new draft or repeated send');
 await page.unroute('**/clao/missions/'+active.request.id+'/directives');
 await page.getByRole('button',{name:'打开原生 Session',exact:true}).click();
 const editor=page.getByRole('combobox',{name:'Message the agent',exact:true});
 await editor.fill('REPAIR_ONCE 原生 Chat 补充 <中文>');await editor.press('Enter');
 for(let i=0;i<60;i++){
  if((await rows()).find(m=>m.request.id===active.request.id)?.directives?.some(d=>d.text==='REPAIR_ONCE 原生 Chat 补充 <中文>'))break;
  await page.waitForTimeout(100);
 }
 fs.writeFileSync(env.CLAO_FIXTURE_RELEASE_CONFIG,'release');
 await page.getByText('CLAO · 验收通过',{exact:true}).waitFor({timeout:90000});
 const result=(await rows()).find(m=>m.request.id===active.request.id);
 if(result.directives?.length!==2||result.directives.some(d=>d.state!=='applied'))throw Error('UI/native Chat did not reach real consumers: '+JSON.stringify(result.directives));
 if(!result.directives.find(d=>d.target==='auditor').consumers.some(c=>c.mirror))throw Error('Planner mirror missing');
 if(!(await details().locator('summary').first().evaluate(el=>el.parentElement.open)))await details().locator('summary').first().click();
 await page.screenshot({path:path.join(evidence,'directive-consumers.png')});
 if(git('status','--porcelain')||git('rev-parse','HEAD')!==sourceHead||!fs.readFileSync(path.join(home,'验证项目/.git/index')).equals(sourceIndex))throw Error('original project changed');
 console.log('RECOVERY_DIRECTIVE_DESKTOP_PASS',JSON.stringify({original:original.request.id,active:active.request.id,posts}),evidence);
};
