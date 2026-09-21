// Test-only official-CLI protocol fixture. It never starts the CLI or reads a key.
// Consumer supplies a synthetic key in memory and owns permission decisions.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');

const [folder, tool = 'Edit', target = 'solution.py'] = process.argv.slice(2);
assert(folder && path.isAbsolute(folder), 'Supply a new absolute fixture directory');
assert(['Write', 'Edit'].includes(tool), 'Tool must be Write or Edit');
assert(['solution.py', 'check.py'].includes(target), 'Target must be a synthetic fixture file');
fs.mkdirSync(folder, {recursive: false});
const home = path.join(folder, 'home');
const workspace = path.join(folder, 'project');
fs.mkdirSync(home);
fs.mkdirSync(workspace);
fs.writeFileSync(path.join(home, 'config.toml'), '[tools]\nenabled = ["Read", "Write", "Edit"]\n');
for (const name of ['solution.py', 'check.py']) {
  fs.writeFileSync(path.join(workspace, name), 'def add(a, b):\n    return a - b\n');
}
const countPath = path.join(folder, 'calls.json');
const preload = path.join(folder, 'preload.mjs');
fs.writeFileSync(preload, `import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
const deny=()=>{throw Error('Offline fixture forbids network');};
http.request=http.get=https.request=https.get=net.connect=net.createConnection=tls.connect=deny;
let calls=0;
globalThis.fetch=async (url,init)=>{
 if(String(url)!=='https://api.moonshot.cn/v1/chat/completions'||init?.method!=='POST') throw Error('Unexpected offline request');
 const request=JSON.parse(init.body);
 if(request.model!=='kimi-k3'||++calls>2) throw Error('Unexpected offline request shape or count');
 fs.writeFileSync(${JSON.stringify(countPath)},JSON.stringify({calls}));
 const base={id:'offline-id',object:'chat.completion.chunk',model:'kimi-k3'};
 const chunk=delta=>({...base,choices:[{index:0,delta,finish_reason:null}]});
 const events=[];
 if(calls===1){
  const args=${JSON.stringify(tool === 'Write' ? {path:target, content:'def add(a, b):\n    return a + b\n'} : {path:target, old_string:'return a - b', new_string:'return a + b'})};
  events.push(chunk({role:'assistant',tool_calls:[{index:0,id:'offline-tool-1',type:'function',function:{name:${JSON.stringify(tool)},arguments:''}}]}));
  const text=JSON.stringify(args);
  for(let i=0;i<text.length;i+=3) events.push(chunk({tool_calls:[{index:0,function:{arguments:text.slice(i,i+3)}}]}));
 }else events.push(chunk({role:'assistant',content:'Offline fixture completed.'}));
 events.push({...base,choices:[{index:0,delta:{},finish_reason:calls===1?'tool_calls':'stop'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}});
 return new Response(events.map(event=>'data: '+JSON.stringify(event)+'\\n\\n').join('')+'data: [DONE]\\n\\n',{status:200,headers:{'content-type':'text/event-stream'}});
};
`);
const env = {
  HOME:home, USERPROFILE:home, APPDATA:path.join(home,'appdata'), LOCALAPPDATA:path.join(home,'local'),
  XDG_CONFIG_HOME:path.join(home,'config'), XDG_DATA_HOME:path.join(home,'share'), KIMI_CODE_HOME:home,
  KIMI_MODEL_NAME:'kimi-k3', KIMI_MODEL_BASE_URL:'https://api.moonshot.cn/v1', KIMI_MODEL_PROVIDER_TYPE:'kimi',
  KIMI_MODEL_MAX_COMPLETION_TOKENS:'2048', KIMI_MODEL_MAX_CONTEXT_SIZE:'32000',
  KIMI_LOOP_MAX_STEPS_PER_TURN:'2', KIMI_LOOP_MAX_ATTEMPTS_PER_STEP:'1', KIMI_CODE_INFINITE_RETRY:'0',
  KIMI_DISABLE_CRON:'1', KIMI_DISABLE_TELEMETRY:'1', KIMI_CODE_NO_AUTO_UPDATE:'1', KIMI_LOG_LEVEL:'off', OPENAI_LOG:'off',
};
const fixture = {offline:true, tool, target, workspace, preload, preloadURL:pathToFileURL(preload).href, countPath, env};
fs.writeFileSync(path.join(folder,'fixture.json'),JSON.stringify(fixture,null,2));
process.stdout.write(JSON.stringify(fixture));
