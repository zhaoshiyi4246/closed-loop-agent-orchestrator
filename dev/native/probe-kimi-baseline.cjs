// Official Kimi prompt mode with an in-process offline transport substitute. No paid
// request, real credential, user profile or model-generated task is used.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');

async function main() {
  const [node, cli, folder, tool = 'none', mode = 'prompt', argumentMode = 'complete'] = process.argv.slice(2);
  assert(node && cli && folder, 'Usage: node probe-kimi-baseline.cjs NODE KIMI_MAIN NEW_DIRECTORY [none|Write|Edit] [prompt|conflict] [complete|fragmented]');
  assert(['none', 'Write', 'Edit'].includes(tool), 'Optional tool must be Write or Edit');
  assert(['prompt', 'conflict'].includes(mode), 'Optional mode must be prompt or conflict');
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
globalThis.fetch = createBudgetFetch({ledgerPath:${JSON.stringify(ledger)},caseName:'offline-baseline',apiKey:process.env.KIMI_MODEL_API_KEY,
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
    KIMI_LOOP_MAX_STEPS_PER_TURN:'3', KIMI_LOOP_MAX_ATTEMPTS_PER_STEP:'1',
    KIMI_CODE_INFINITE_RETRY:'0', KIMI_DISABLE_CRON:'1', KIMI_DISABLE_TELEMETRY:'1',
    KIMI_CODE_NO_AUTO_UPDATE:'1', KIMI_LOG_LEVEL:'off', OPENAI_LOG:'off',
  });
  const prompt=tool==='none'?'Reply with a short acknowledgement. Do not use tools.':'Change only solution.py so add(a, b) returns a + b using '+tool+'.';
  const completed=cp.spawnSync(node,['--import',pathToFileURL(preload).href,cli,...(mode==='conflict'?['--auto']:[]),'-p',prompt],{cwd:workspace,env,windowsHide:true,encoding:'utf8',timeout:45000,maxBuffer:1024*1024});
  const output=(completed.stdout??'')+(completed.stderr??'');
  assert(!output.includes(marker),'Credential appeared in prompt output');
  fs.writeFileSync(path.join(folder,'startup-output.txt'),output);
  for(const file of fs.readdirSync(folder,{recursive:true})){
    const full=path.join(folder,file);if(fs.statSync(full).isFile())assert(!fs.readFileSync(full).includes(Buffer.from(marker)),'Credential appeared in isolated files');
  }
  const data=JSON.parse(fs.readFileSync(ledger));
  const result={offline:true,mode,tool,exitCode:completed.status,signal:completed.signal,error:completed.error?.code,attempts:data.attempts.length,keyPersisted:false,solution:fs.readFileSync(path.join(workspace,'solution.py'),'utf8')};
  fs.writeFileSync(path.join(folder,'report.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
  console.log(output);
  assert.equal(completed.error,undefined,'CLI failed to exit within the offline bound');
  if(mode==='conflict') {
    assert.equal(completed.status,1);
    assert.equal(data.attempts.length,0);
    assert.match(output,/Cannot combine --prompt with --auto/);
    assert.equal(result.solution,'def add(a, b):\n    return a - b\n');
  } else {
    assert.equal(completed.status,0);
    assert.equal(data.attempts.length,tool==='none'?1:2);
    assert.equal(result.solution,tool==='none'?'def add(a, b):\n    return a - b\n':'def add(a, b):\n    return a + b\n');
  }
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
