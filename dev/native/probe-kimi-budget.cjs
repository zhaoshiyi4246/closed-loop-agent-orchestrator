// Official Kimi ACP with an in-process offline transport substitute. No paid
// request, real credential, user profile or model-generated task is used.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');

async function main() {
  const [node, cli, folder, tool = 'none', permissionDecision = 'allow_once', argumentMode = 'complete'] = process.argv.slice(2);
  assert(node && cli && folder, 'Usage: node probe-kimi-budget.cjs NODE KIMI_MAIN NEW_DIRECTORY');
  assert(['none', 'Write', 'Edit'].includes(tool), 'Optional tool must be Write or Edit');
  assert(['allow_once', 'reject'].includes(permissionDecision), 'Optional decision must be allow_once or reject');
  assert(['complete', 'fragmented'].includes(argumentMode), 'Optional argument mode must be complete or fragmented');
  fs.mkdirSync(folder, { recursive: false });
  const home = path.join(folder, 'home'), workspace = path.join(folder, 'project');
  fs.mkdirSync(home); fs.mkdirSync(workspace);
  fs.writeFileSync(path.join(home, 'config.toml'), '[tools]\nenabled = ["Read", "Write", "Edit"]\n');
  fs.writeFileSync(path.join(workspace, 'solution.py'), 'def add(a, b):\n    return a - b\n');
  const ledger = path.join(folder, 'ledger.json');
  fs.writeFileSync(ledger, JSON.stringify({ attempts: [] }));
  const marker = 'isolated-not-a-real-key-' + crypto.randomUUID();
  const preload = path.join(folder, 'preload.mjs');
  const hook = pathToFileURL(path.join(__dirname, 'kimi-budget-transport.mjs')).href;
  fs.writeFileSync(preload, `import { createBudgetFetch } from ${JSON.stringify(hook)};
import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';
const noNetwork=()=>{throw Error('Offline probe forbids network');};
http.request=http.get=https.request=https.get=noNetwork;
let calls=0;
globalThis.fetch = createBudgetFetch({ledgerPath:${JSON.stringify(ledger)},caseName:'offline-acp',apiKey:process.env.KIMI_MODEL_API_KEY,
 send:async ({body}) => {
  calls++;
  const request=JSON.parse(body);
  fs.writeFileSync(${JSON.stringify(path.join(folder, 'request-shape.json'))},JSON.stringify({model:request.model,bodyBytes:Buffer.byteLength(body),tools:request.tools?.map(t=>t.function?.name),output:request.max_completion_tokens,calls}));
  const tool=${JSON.stringify(tool)};
  const toolTurn=tool!=='none' && calls===1;
  const args=tool==='Write'?{path:'solution.py',content:'def add(a, b):\\n    return a + b\\n'}:{path:'solution.py',old_string:'return a - b',new_string:'return a + b'};
  const delta=toolTurn?{role:'assistant',tool_calls:[{index:0,id:'offline-tool-1',type:'function',function:{name:tool,arguments:JSON.stringify(args)}}]}:{role:'assistant',content:'Offline transport probe complete.'};
  const event={id:'offline-id',object:'chat.completion.chunk',model:'kimi-k3',choices:[{index:0,delta,finish_reason:null}]};
  const events=[event];
  if(toolTurn && ${JSON.stringify(argumentMode)}==='fragmented') {
    const serialized=JSON.stringify(args);
    event.choices[0].delta.tool_calls[0].function.arguments='';
    for(let i=0;i<serialized.length;i+=3) events.push({...event,choices:[{index:0,delta:{tool_calls:[{index:0,function:{arguments:serialized.slice(i,i+3)}}]},finish_reason:null}]});
  }
  const final={...event,choices:[{index:0,delta:{},finish_reason:toolTurn?'tool_calls':'stop'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}};
  return {status:200,headers:{'content-type':'text/event-stream'},body:(async function*(){ for(const chunk of [...events,final]) yield Buffer.from('data: '+JSON.stringify(chunk)+'\\n\\n'); yield Buffer.from('data: [DONE]\\n\\n'); })()};
 }});
`);
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => ['PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','TEMP','TMP'].includes(k.toUpperCase())));
  Object.assign(env, {
    HOME: home, USERPROFILE: home, APPDATA: path.join(home,'appdata'), LOCALAPPDATA: path.join(home,'local'),
    XDG_CONFIG_HOME: path.join(home,'config'), XDG_DATA_HOME: path.join(home,'share'),
    KIMI_CODE_HOME: home, KIMI_MODEL_NAME:'kimi-k3', KIMI_MODEL_API_KEY:marker, KIMI_API_KEY:marker,
    KIMI_MODEL_BASE_URL:'https://api.moonshot.cn/v1', KIMI_MODEL_PROVIDER_TYPE:'kimi',
    KIMI_MODEL_MAX_COMPLETION_TOKENS:'2048', KIMI_MODEL_MAX_CONTEXT_SIZE:'32000',
    KIMI_LOOP_MAX_STEPS_PER_TURN:'2', KIMI_LOOP_MAX_ATTEMPTS_PER_STEP:'1',
    KIMI_CODE_INFINITE_RETRY:'0', KIMI_DISABLE_CRON:'1', KIMI_DISABLE_TELEMETRY:'1',
    KIMI_CODE_NO_AUTO_UPDATE:'1', KIMI_LOG_LEVEL:'off', OPENAI_LOG:'off',
  });
  const child = cp.spawn(node, ['--import', pathToFileURL(preload).href, cli, 'acp'], {cwd:workspace, env, windowsHide:true, stdio:['pipe','pipe','pipe']});
  let buffer='', stderr='', seq=0;
  const permissions=[], updates=[], permissionFacts=[];
  const pending = new Map();
  child.stderr.on('data', b => { stderr += b.toString(); });
  child.on('exit', code => {
    for(const {reject,timer} of pending.values()) {clearTimeout(timer);reject(Error('ACP exited with code '+code));}
    pending.clear();
  });
  child.stdout.on('data', b => {
    buffer+=b.toString(); let newline;
    while((newline=buffer.indexOf('\n'))>=0){
      const line=buffer.slice(0,newline); buffer=buffer.slice(newline+1);
      let message; try{message=JSON.parse(line);}catch{continue;}
      if(message.method==='session/request_permission' && message.id!==undefined){
        permissions.push(message.params);
        permissionFacts.push({toolCallId:message.params.toolCall?.toolCallId,updatesBeforeRequest:updates.filter(update=>update.toolCallId===message.params.toolCall?.toolCallId)});
        const choice=message.params.options?.find(option=>option.kind===(permissionDecision==='allow_once'?'allow_once':'reject_once'));
        const admitted=tool!=='none' && message.params.toolCall?.toolCallId==='0:offline-tool-1' && message.params.toolCall?.title===tool && choice;
        child.stdin.write(JSON.stringify({jsonrpc:'2.0',id:message.id,result:{outcome:admitted?{outcome:'selected',optionId:choice.optionId}:{outcome:'cancelled'}}})+'\n');
      }
      else if(message.method==='session/update'){ updates.push(message.params.update); }
      else if(message.method && message.id!==undefined){ child.stdin.write(JSON.stringify({jsonrpc:'2.0',id:message.id,error:{code:-32601,message:'Offline probe has no client tools'}})+'\n'); }
      else if(pending.has(message.id)){ const {resolve,reject,timer}=pending.get(message.id);pending.delete(message.id);clearTimeout(timer);message.error?reject(Error('ACP returned error '+message.error.code)):resolve(message.result); }
    }
  });
  function rpc(method,params){return new Promise((resolve,reject)=>{const id=++seq;const timer=setTimeout(()=>{pending.delete(id);reject(Error('ACP probe timed out: '+method));},45000);pending.set(id,{resolve,reject,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});}
  let result;
  try {
    const initialized=await rpc('initialize',{protocolVersion:1,clientCapabilities:{},clientInfo:{name:'clao-offline-probe',version:'1'}});
    const session=await rpc('session/new',{cwd:workspace,mcpServers:[]});
    const turn=await rpc('session/prompt',{sessionId:session.sessionId,prompt:[{type:'text',text:tool==='none'?'Reply with a short acknowledgement. Do not use tools.':'Change only solution.py so add(a, b) returns a + b using '+tool+'.'}]});
    result={protocolVersion:initialized.protocolVersion,stopReason:turn.stopReason,offline:true,tool,permissionDecision,argumentMode,permissions,permissionFacts,updates};
  } finally {
    child.kill();
    await new Promise(resolve=>{if(child.exitCode!==null)resolve();else child.once('exit',resolve);});
    for(const {timer} of pending.values())clearTimeout(timer);
    fs.writeFileSync(path.join(folder,'startup-stderr.txt'),stderr.split(marker).join('[FAKE_KEY_REDACTED]'));
  }
  assert(!stderr.includes(marker),'Credential appeared in stderr');
  for(const file of fs.readdirSync(folder,{recursive:true})){
    const full=path.join(folder,file);if(fs.statSync(full).isFile())assert(!fs.readFileSync(full).includes(Buffer.from(marker)),'Credential appeared in isolated files');
  }
  const data=JSON.parse(fs.readFileSync(ledger));
  assert(!JSON.stringify(result).includes(marker),'Credential appeared in protocol facts');
  fs.writeFileSync(path.join(folder,'protocol.json'),JSON.stringify(result,null,2));
  assert.equal(data.attempts.length,tool==='none'?1:2,'Unexpected intercepted offline call count');
  assert.equal(result.stopReason,'end_turn');
  if(tool!=='none') {
    assert.equal(fs.readFileSync(path.join(workspace,'solution.py'),'utf8'),permissionDecision==='allow_once'?'def add(a, b):\n    return a + b\n':'def add(a, b):\n    return a - b\n');
    assert.equal(permissions.length,1,'Expected exactly one explicit permission');
    // Official 2.0.2 requests permission before tool.call.started publishes
    // rawInput. Do not mistake the post-decision upgrade for approval evidence.
    const before=permissionFacts[0].updatesBeforeRequest;
    assert(before.length>0,'Expected an initial tool call before permission');
    assert(before.every(update=>update.rawInput===undefined),'Official approval ordering changed; review the new contract');
    assert(updates.some(update=>update.toolCallId===permissionFacts[0].toolCallId && update.rawInput!==undefined),'Expected the canonical input only after the explicit decision');
    if(argumentMode==='fragmented') assert(before.length>2,'Expected cumulative argument fragments before permission');
  }
  result.shape=JSON.parse(fs.readFileSync(path.join(folder,'request-shape.json')));
  result.keyPersisted=false;
  fs.writeFileSync(path.join(folder,'report.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({...result,permissionFacts:permissionFacts.map(f=>({toolCallId:f.toolCallId,updatesBeforeRequest:f.updatesBeforeRequest.length,rawInputsBeforeRequest:f.updatesBeforeRequest.filter(u=>u.rawInput!==undefined).length})),updates:updates.map(u=>({sessionUpdate:u.sessionUpdate,toolCallId:u.toolCallId,status:u.status}))}));
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
