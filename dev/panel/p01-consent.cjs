/* Production Panel/Controller; only isolated external engine/model boundaries. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const [origin,projectA,projectB]=process.argv.slice(2);
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST' && ['/api/mission','/api/new-attempt'].includes(new URL(r.url()).pathname)) writes.push(r.postDataJSON());});
  const readyConfig=()=>page.waitForFunction(()=>FORM_CONFIG && !PENDING.has('config-preview'));
  const consent=()=>page.locator('#externalConsent').isChecked();
  async function navigate(view){await page.locator('[data-view="'+view+'"]').first().click();}
  async function openDraft(){await navigate('overview');await page.click('#btnNew');await readyConfig();await page.waitForFunction(()=>SOURCE && !PENDING.has('source'));}
  async function changeProject(id){
   await page.locator('#formReview .review-row button').first().click();await page.selectOption('#f_project',id);
   await page.waitForFunction(id=>SOURCE?.project_id===id,id);
   for(let i=0;i<3;i++) await page.click('#stepNext');await readyConfig();
  }
  async function bind(role,id){await page.selectOption('#mission_profile_'+role,id);await readyConfig();}
  async function defaults(auditor,verifier){
   await navigate('models');await page.waitForFunction(()=>loadConnections.values && !loadConnections.pending);
   await page.selectOption('#default_profile_auditor',auditor);await page.selectOption('#default_profile_verifier',verifier);await page.click('#saveBindings');
   await page.waitForFunction(({auditor,verifier})=>!PENDING.has('model-config') && LIVE.default_config.values.roles.auditor.profile===auditor && LIVE.default_config.values.roles.verifier.profile===verifier,{auditor,verifier});
  }
  async function blockedStart(){
   await page.check('#sourceConfirmed');const before=writes.length;await page.click('#btnStart');
   assert.equal(writes.length,before);assert.match(await page.locator('#externalConsentError').textContent(),/确认/);
  }
  async function completed(id){
   await page.waitForFunction(id=>LIVE?.mission?.id===id && !LIVE.running && !LIVE.preparing,id,{timeout:30000});
   assert.equal(await page.evaluate(()=>LIVE.mission.state),'MISSION_DONE',await page.evaluate(()=>JSON.stringify({reason:LIVE.mission.reason,errors:LIVE.panel_errors})));
  }
  async function start(expectedProject,external){
   const snapshot=await page.evaluate(()=>FORM_CONFIG);
   assert.equal(await page.inputValue('#f_project'),expectedProject);
   assert((await page.locator('#formReview').textContent()).includes(await page.locator('#f_project option:checked').textContent()));
   const displayed=await page.locator('#formReview details pre').allTextContents();
   if(external){const bindings=JSON.parse(displayed[0]);for(const [role,p] of Object.entries(bindings)) assert.equal(p.id,snapshot.values.roles[role].profile);}
   await page.check('#sourceConfirmed');const before=writes.length;
   const response=page.waitForResponse(r=>r.url().endsWith('/api/mission') && r.request().method()==='POST');
   await page.locator('#btnStart').evaluate(b=>{b.click();b.click();});
   const res=await response,data=await res.json();assert.equal(res.status(),200,JSON.stringify(data));
   assert.equal(writes.length,before+1);const sent=writes.at(-1);
   assert.equal(sent.project_id,expectedProject);assert.deepEqual(sent.config_snapshot,snapshot);
   assert.equal(sent.external_service_consent,external?'bigmodel_general':null);
   await page.waitForFunction(()=>!document.getElementById('newMission').open);
   assert.equal(await consent(),false);
   await completed(data.mission_id);
   const frozen=await page.evaluate(()=>LIVE.mission_config.snapshot);
   assert.deepEqual(frozen.values,snapshot.values);assert.equal(frozen.revision,snapshot.revision);
   // Runtime reattributes merged budget inputs; external routing sources stay frozen.
   for(const key of ['model_profiles','roles.planner.profile','roles.auditor.profile','roles.verifier.profile']) assert.equal(frozen.sources[key],snapshot.sources[key]);
   return data.mission_id;
  }
  await page.goto(origin);await page.waitForFunction(()=>LIVE?.default_config && PROJECTS.length===2);
  await page.click('#btnNew');await page.selectOption('#f_project',projectA);
  await page.waitForFunction(()=>SOURCE && !PENDING.has('source'));
  await page.click('#stepNext');await page.fill('#f_obj','外发草稿 中文 <tag> "');await page.fill('#f_ac','x equals 2');
  await page.click('#stepNext');await page.fill('#f_paths','app.py');await page.fill('#f_gate',"python -c \"import runpy; assert runpy.run_path('app.py')['x'] == 2\"");
  await page.click('#stepNext');await readyConfig();
  await blockedStart();await page.check('#externalConsent');

  // The same unsubmitted draft survives dialog/navigation/live SSE and text edits.
  await page.click('#closeMission');await navigate('settings');
  const seq=await page.evaluate(()=>STREAM_SEQ);await page.waitForFunction(seq=>STREAM_SEQ>seq,seq);
  await openDraft();assert.equal(await consent(),true);assert.equal(await page.inputValue('#f_obj'),'外发草稿 中文 <tag> "');
  await page.locator('#formReview .review-row button').nth(1).click();await page.fill('#f_obj','同一草稿修改目标 中文 <tag> "');
  await page.click('#stepNext');await page.click('#stepNext');await readyConfig();assert.equal(await consent(),true);
  await page.fill('#param_gate_timeout_seconds','11.125');await readyConfig();assert.equal(await consent(),true);

  // Project identity, role set and connection identity each retire consent.
  await changeProject(projectB);assert.equal(await consent(),false);await page.check('#externalConsent');
  await changeProject(projectA);assert.equal(await consent(),false);await page.check('#externalConsent');
  await bind('verifier','glm-other');assert.equal(await consent(),false);await page.check('#externalConsent');
  await bind('auditor','glm-review');assert.equal(await consent(),false);await page.check('#externalConsent');
  await bind('auditor','codex');assert.equal(await consent(),false);
  await bind('verifier','codex');assert(await page.locator('#externalConsentLabel').isHidden());
  await bind('verifier','glm-review');assert.equal(await consent(),false);await page.check('#externalConsent');
  const a=await start(projectA,true);

  // A completed submission cannot authorize B, even on the same project.
  await defaults('glm-other','glm-other');await openDraft();
  assert.equal(await consent(),false);assert.equal(await page.inputValue('#f_project'),projectA);
  assert.equal(await page.inputValue('#mission_profile_auditor'),'glm-other');await blockedStart();
  await changeProject(projectB);assert.equal(await consent(),false);await blockedStart();await page.check('#externalConsent');
  const bSnapshot=await page.evaluate(()=>FORM_CONFIG);
  // New defaults affect C; B's already confirmed draft still submits its frozen selection.
  await page.click('#closeMission');await defaults('codex','codex');await openDraft();
  assert.equal(await consent(),true);assert.deepEqual(await page.evaluate(()=>FORM_CONFIG),bSnapshot);
  const b=await start(projectB,true);assert.notEqual(a,b);

  // Pure Codex has no external consent and still runs the real closed loop.
  await openDraft();assert(await page.locator('#externalConsentLabel').isHidden());assert.equal(await consent(),false);
  assert.equal(await page.inputValue('#mission_profile_verifier'),'codex');
  const c=await start(projectB,false);assert.notEqual(b,c);

  // Existing historical rerun retains its own fresh consent and target A, not C.
  await defaults('codex','glm-review');await navigate('tasks');await page.click('#backToTasks');
  await page.locator('[data-mission-id="'+a+'"] .link-row').click();
  await page.getByRole('button',{name:'重新执行',exact:true}).click();await page.waitForFunction(()=>!document.getElementById('confirmRetry').disabled);
  assert.equal(await page.locator('#retryConsent').isChecked(),false);
  assert((await page.locator('#retrySource').textContent()).includes(projectA));
  const count=writes.length;await page.click('#confirmRetry');assert.equal(writes.length,count);
  assert.match(await page.locator('#retryError').textContent(),/确认/);
  await page.check('#retryConsent');const retrySnapshot=await page.evaluate(()=>RETRY_TARGET.config_snapshot);
  const response=page.waitForResponse(r=>r.url().endsWith('/api/new-attempt') && r.request().method()==='POST');
  await page.click('#confirmRetry');const res=await response,data=await res.json();assert.equal(res.status(),200,JSON.stringify(data));
  assert.equal(writes.at(-1).mission_id,a);assert.equal(writes.at(-1).project_id,projectA);
  assert.equal(writes.at(-1).external_service_consent,'bigmodel_general');assert.deepEqual(writes.at(-1).config_snapshot,retrySnapshot);
  await completed(data.mission_id);assert.equal(await page.evaluate(()=>LIVE.mission.previous_attempt),a);
  assert.deepEqual(errors,[]);assert.equal(writes.length,4);
  console.log('P01 consent browser PASS: draft/project/role/connection scope, A/B/default freeze, Codex and historical rerun; 4 actual isolated missions');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
