
let LAST = null, ACTIVE_TAB = "ev", PROJECTS = [];
let SOURCE=null, LIVE=null, HISTORY=null, HISTORY_REQUEST=0;
let FORM_BASE=null, FORM_CONFIG=null, CONFIG_VERSION=0;
const DIRECTIVE_DRAFTS=new Map();let DIRECTIVE_MISSION=null;
const RESULTS=new Map(), RESULT_NOTICES=new Map();
let VIEW="overview", DETAIL_ID=null, WIZARD_STEP=0, PROJECT_ERROR="";
const $ = id => document.getElementById(id);
const PANEL_NONCE = document.currentScript.nonce;
const PENDING = new Set(), UI_ERRORS = new Map(), ERROR_MISSIONS=new Map();
const text = value => value == null ? "" : (typeof value === "object" ? JSON.stringify(value) : String(value));
function el(tag, value, cls){
  const node=document.createElement(tag);
  if(value!=null) node.textContent=text(value);
  if(cls) node.className=cls;
  return node;
}
const STATES=new Set(["RUNNING","MISSION_READY","MISSION_DONE","DONE","HUMAN","FAILED","CANCELLING","CANCELLED","WORKER_RUNNING","WORKER_RETRYING"]);
function toast(msg){ const node=$("toast"); node.textContent=msg; node.style.display="block";
  setTimeout(()=>node.style.display="none",2600); }
function uiError(source,error,missionId=null){
  if(error){UI_ERRORS.set(source,text(error));if(missionId)ERROR_MISSIONS.set(source,missionId);}else{UI_ERRORS.delete(source);ERROR_MISSIONS.delete(source);}
  showClientErrors();
  if(source==="mission" && !missionId) {$("formSubmitError").textContent=error?text(error):"";if(error) $("formSubmitStatus").textContent="启动未完成，草稿已保留。";if(error && /来源|source|revision/.test(text(error))){$("sourceConfirmError").textContent=text(error);$("sourceConfirmed").checked=false;}}
  if(source==="config-preview") $("missionParametersError").textContent=error?text(error):"";
  if(source==="config") $("settingsError").textContent=error?text(error):"";
  if(source==="project" || source==="source") {$("projectPathError").textContent=error?text(error):"";if(source==="source" && error) $("sourceSummary").textContent="来源读取失败，请重试。";}
  if($("retryMission").open) $("retryError").textContent=error?text(error):"";
}
function showClientErrors(){
  const visible=[...UI_ERRORS].filter(([key])=>!ERROR_MISSIONS.has(key) || ERROR_MISSIONS.get(key)===(VIEW==="tasks"?DETAIL_ID:LIVE?.mission?.id)).filter(([key])=>!(key==="config" && VIEW==="settings") && !(key==="mission" && $("newMission").open));
  $("clientErrors").textContent=visible.map(([key,value])=>(key.startsWith("approval:")?"审批":({mission:"新任务",directive:"补充指令",stop:"取消",readiness:"环境检查",source:"来源",project:"项目",config:"设置","config-preview":"本次配置"})[key] || key)+"："+value).join("\n");
  $("clientErrors").hidden=visible.length===0;
}
function syncButtons(){
  document.querySelectorAll("[data-write-key]").forEach(b=>b.disabled=PENDING.has(b.dataset.writeKey) || b.dataset.blocked==="1");
  const activeView=LAST?.mission?.id===LIVE?.mission?.id;
  $("btnStop").disabled=PENDING.has("stop") || !activeView || !LIVE?.running || !!LAST?.mission?.stop_request;
  $("btnSend").disabled=PENDING.has("directive") || !activeView || !LIVE?.running || !!LAST?.mission?.stop_request || !!LAST?.mission?.inspection_only || !$("d_target").value || !!$("d_target").selectedOptions[0]?.disabled;
  $("btnStart").disabled=!!LIVE?.launch_blocked || PENDING.has("mission") || $("f_project").disabled || !PROJECTS.length || !$("f_project").value || !!(LIVE?.running || LIVE?.preparing);
}
async function writeAction(key,path,body,success){
  if(PENDING.has(key)) return;
  PENDING.add(key); uiError(key,null); syncButtons();
  const requestStarted=performance.now();
  try{
    const response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-Panel-Nonce":PANEL_NONCE},body:JSON.stringify(body)});
    const data=await response.json();
    REQUEST_TIMING={key, round_trip_seconds:(performance.now()-requestStarted)/1000, ...data.request_timing};
    renderTiming();
    if(!response.ok || !data.ok) throw new Error(data.error || "请求失败（HTTP "+response.status+"）");
    uiError(key,null); if(success) await success(data);
  }catch(error){ uiError(key,error.message,body.mission_id); if(!body.mission_id || body.mission_id===DETAIL_ID) toast(error.message); }
  finally{ PENDING.delete(key); syncButtons(); }
}
function actionButton(label,key,action){
  const button=el("button",label); button.dataset.writeKey=key;
  button.disabled=PENDING.has(key); button.onclick=action; return button;
}

/* ---------------- tabs / files ---------------- */
document.querySelectorAll(".tabs button").forEach(b=>{
  b.onclick=()=>{
    document.querySelectorAll(".tabs button").forEach(x=>x.classList.remove("on"));
    b.classList.add("on"); ACTIVE_TAB=b.dataset.tab;
    document.querySelectorAll(".tabpage").forEach(p=>p.classList.remove("on"));
    $("tab-"+ACTIVE_TAB).classList.add("on");
    if(ACTIVE_TAB==="mem"||ACTIVE_TAB==="proj") loadFile(ACTIVE_TAB==="mem"?"memory.md":"project.md");
  };
});
async function loadFile(name){
  const target=$(name==="memory.md"?"memPre":"projPre");
  const mid=DETAIL_ID || LAST?.mission?.id;
  if(!mid) return;
  try{
    const response=await fetch("/api/file?name="+encodeURIComponent(name)+"&mission_id="+encodeURIComponent(mid));
    const data=await response.json();
    if(!response.ok || !data.ok) throw new Error(data.error || "文件读取失败");
    if(mid!==DETAIL_ID) return;
    target.textContent=data.content; uiError(name,null);
  }catch(error){ if(mid!==DETAIL_ID) return; target.textContent=error.message; uiError(name,error.message,mid); }
}

/* ---------------- render: dynamic values are text, never markup ---------------- */
function drawGate(query){
  const box=$("evidence");box.replaceChildren();
  const labels={not_run:"Gate 尚未运行",no_records:"没有 Gate 记录",read_error:"Gate 读取失败",ok:""};
  const label=Object.hasOwn(labels,query?.status)?labels[query.status]:"Gate 状态未知";
  if(label) box.append(el("p",label,query?.status==="read_error"?"field-error":"subtle"));
  if(query?.error) box.append(el("pre",query.error,"diagnostic"));
  if(query?.reason) {const d=el("details");d.append(el("summary","读取详情"),el("pre",query.reason,"diagnostic"));box.append(d);}
  const phases={task:"子任务验收",baseline:"基线验收",final:"最终验收",unknown:"验收阶段未知"};
  const result=value=>value==="pass"?"通过":value==="fail"?"失败":"未知";
  for(const run of query?.records || []){
    const row=el("div",null,"ev"),head=el("div",null,"section-heading");
    head.append(el("b",Object.hasOwn(phases,run.phase)?phases[run.phase]:phases.unknown),el("span",result(run.overall),"status "+(run.overall==="pass"?"good":run.overall==="fail"?"bad":"wait")));row.append(head);
    row.append(el("p","命令："+result(run.command_status)+" · 仓库完整性："+result(run.integrity?.status)+" · 修改范围："+result(run.scope?.status)));
    if(run.historical_fields_missing) row.append(el("p","历史字段未提供；unknown"));
    for(const [label,fact] of [["仓库完整性",run.integrity],["修改范围",run.scope]]){
      if(fact?.reason && fact.status!=="pass") row.append(el("pre",label+"："+text(fact.reason),"diagnostic"));
    }
    const d=el("details");d.append(el("summary","命令与证据详情"));
    d.append(el("p",text(run.task_id)),el("pre",run.command || "（命令未执行）","diagnostic"));
    d.append(el("p","command="+text(run.command_result)+" · exit="+(run.exit_code==null?"未执行":text(run.exit_code))+" · command batch="+text(run.command_status)));
    d.append(el("p","repository integrity="+text(run.integrity?.status)+" · scope="+text(run.scope?.status)+" · overall="+text(run.overall)));
    for(const [label,fact] of [["integrity",run.integrity],["scope",run.scope]]) if(fact?.reason && fact.status==="pass") d.append(el("pre",label+"："+text(fact.reason),"diagnostic"));
    if(run.output) for(const [stream,meta] of Object.entries(run.output)) if(meta?.truncated){
      row.append(el("p",stream+" 输出已截断，完整性信息见证据详情。","field-error"));
      d.append(el("pre",stream+" 已截断：original="+text(meta.original_length)+" chars · limit="+text(meta.limit_chars)+" · SHA-256="+text(meta.sha256),"diagnostic"));
    }
    if(run.output?.error_category) row.append(el("p","命令错误："+text(run.output.error_category)+" · timeout="+text(run.output.timeout_seconds)+"s","field-error"));
    if(run.stdout || run.stderr) d.append(el("pre",text(run.stdout)+"\n"+text(run.stderr),"diagnostic"));
    row.append(d);box.append(row);
  }
}
let STREAM_EPOCH=null, STREAM_SEQ=-1, CONNECTED=false, RECEIVED_MONO=null, DISCONNECTED_MONO=null, REQUEST_TIMING=null;
const OLD_EPOCHS=new Set();
function acceptSnapshot(s){
  const stream=s.stream;
  if(stream){
    if(OLD_EPOCHS.has(stream.epoch)) return false;
    if(STREAM_EPOCH===stream.epoch && stream.sequence<=STREAM_SEQ) return false;
    if(STREAM_EPOCH && STREAM_EPOCH!==stream.epoch){OLD_EPOCHS.add(STREAM_EPOCH);HISTORY=null;HISTORY_REQUEST++;loadHistory.target=null;}
    STREAM_EPOCH=stream.epoch; STREAM_SEQ=stream.sequence;
  }
  const runtimeChanged=LIVE && (LIVE.mission?.id!==s.mission?.id || !!(LIVE.running || LIVE.preparing)!==!!(s.running || s.preparing) || LIVE.launch_blocked!==s.launch_blocked);
  RECEIVED_MONO=performance.now(); DISCONNECTED_MONO=null; CONNECTED=true; LIVE=s; renderSelected();
  if(DETAIL_ID && DETAIL_ID!==s.mission?.id && (HISTORY?.mission?.id!==DETAIL_ID || runtimeChanged)) loadHistory(DETAIL_ID,!!runtimeChanged);
  return true;
}
function configText(snapshot,fields){
  if(!snapshot) return "unknown";
  const lines=["revision="+text(snapshot.revision)];
  function walk(node,prefix=""){
    for(const [key,value] of Object.entries(node || {})){
      const path=prefix+key;
      if(value && typeof value==="object" && !Array.isArray(value)) walk(value,path+".");
      else lines.push(path+" = "+JSON.stringify(value)+" · 来源="+text(snapshot.sources?.[path])+" · 类型="+text(fields?.[path]?.kind)+" · 范围="+text(fields?.[path]?.minimum ?? "n/a")+".."+text(fields?.[path]?.maximum ?? "n/a")+"（秒数下限不含） · 消费者="+text(fields?.[path]?.consumer));
    }
  }
  walk(snapshot.values); return lines.concat(snapshot.warnings || []).join("\n");
}
function seconds(value){return value==null?"unknown":Number(value).toFixed(3)+"s";}
function renderTiming(){
  const t=REQUEST_TIMING, stream=LAST?.stream;
  $("timingStatus").textContent=(t?"最近本地请求 "+t.key+"：浏览器往返="+seconds(t.round_trip_seconds)+" · HTTP处理="+seconds(t.handler_seconds)+"（包含处理，不等于模型耗时）\n":"")+
    "状态快照生成="+text(stream?.generated_at ?? "unknown")+" · 查询/投影耗时="+seconds(stream?.snapshot_seconds)+" · 最近阶段记录至快照="+seconds(stream?.phase_record_to_snapshot_seconds)+" · seq="+text(stream?.sequence ?? "unknown")+
    (CONNECTED?" · 已连接":" · 断连，保留最后已知状态");
}
function renderPhases(){
  const query=LAST?.phases, records=query?.records || [];
  const active=records.filter(p=>p.status==="running");
  const elapsed=p=>p.elapsed_seconds==null?null:p.elapsed_seconds+((p.status==="running" && RECEIVED_MONO!=null)?((CONNECTED?performance.now():(DISCONNECTED_MONO ?? RECEIVED_MONO))-RECEIVED_MONO)/1000:0);
  $("phaseStatus").textContent=active.length?active.map(p=>text(p.phase)+" · "+text(p.reason)+" · attempt="+text(p.attempt)+" · 已等待="+seconds(elapsed(p))).join("\n"):
    records.length?"最近阶段 "+text(records[0].phase)+" · "+text(records[0].status)+" · "+text(records[0].reason):"阶段 "+text(query?.status || "unknown");
  $("phaseHistory").textContent=records.map(p=>"#"+text(p.sequence)+" "+text(p.task_id || p.mission_id)+" · "+text(p.phase)+" · "+text(p.status)+" · attempt="+text(p.attempt)+" · elapsed="+seconds(elapsed(p))+" · result="+text(p.result ?? "unknown")+" · error="+text(p.error_category ?? "none")).join("\n");
  $("modelStatus").textContent=["worker","planner","auditor","verifier"].map(role=>{
    const p=query?.roles?.[role] || records.find(p=>p.role===role && ["model_request","spawn"].includes(p.phase));
    return !p?role+"："+((LAST?.mission_config?.status==="ok" && ["ok","not_called"].includes(query?.status))?"未调用":"历史 unknown"):
      role+"：请求="+text(p.requested_model ?? "unknown")+" · 传入="+text(p.passed_model ?? "unknown")+(role==="worker"?" · 模型确认见下方执行后端事实":" · 外部确认="+text(p.confirmed_model ?? "unknown"))+" · transport="+text(p.transport ?? "unknown")+" · attempt="+text(p.attempt)+" · 调用耗时="+seconds(elapsed(p))+" · usage="+text(p.usage ?? "unknown")+" · cost="+text(p.cost ?? "unknown");
  }).join("\n") + (query?.workers || []).map(w=>{
    // Old R01 records confirmed only a reroute; never relabel it as spawn model.
    const legacy=w.model_evidence==="AO conversation.modelReroute.toModel (conversation-level, not per-call timing)";
    const reroute=w.model_reroute ?? (legacy?{to_model:w.confirmed_model,source:w.model_evidence}:null);
    return "\nWorker "+text(w.session_id)+" · activity="+text(w.activity ?? "unknown")+
      " · 请求="+text(w.requested_model ?? "unknown")+" · 传入="+text(w.passed_model ?? "unknown")+
      (w.transport==="codex_stdio"?" · Codex thread model=":" · AO spawn-resolved=")+text(w.spawn_resolved_model ?? "unknown")+"（创建时解析） · 来源="+text(w.spawn_model_evidence ?? "外部 model 未提供/unknown")+
      " · conversation reroute="+(reroute?text(reroute.from_model ?? "unknown")+" → "+text(reroute.to_model ?? "unknown")+" · 来源="+text(reroute.source):"未提供/unknown")+
      "（会话后续模型变更） · 本次观察到该 activity 持续="+seconds(w.activity_elapsed_seconds)+"（非模型请求耗时） · 单次 provider 请求模型/耗时 unknown · usage="+text(w.usage ?? "unknown")+" · cost="+text(w.cost ?? "unknown");
  }).join("");
  renderTiming();
  renderFriendlyPhase();
}
function rememberDirective(edited=false){
  if(!DIRECTIVE_MISSION) return;
  const draft=DIRECTIVE_DRAFTS.get(DIRECTIVE_MISSION);
  if(edited || draft.text!==$("d_text").value || draft.target!==$("d_target").value){
    draft.text=$("d_text").value;draft.target=$("d_target").value;draft.version++;draft.request=null;
  }
  return draft;
}
function renderDirectiveInput(s,workers){
  rememberDirective();
  const mid=s.mission?.id, selector=$("d_target");
  DIRECTIVE_MISSION=mid;
  if(mid && !DIRECTIVE_DRAFTS.has(mid)) DIRECTIVE_DRAFTS.set(mid,{text:"",target:"planner",version:0});
  const draft=DIRECTIVE_DRAFTS.get(mid) || {text:"",target:"planner"};
  // Install this mission's options before restoring its saved recipient.
  const options=workers.map((t,i)=>({value:"worker:"+t.worker_session_id,label:`Worker ${i+1}（同步 Planner）`,
    disabled:["DONE","FAILED","HUMAN","CANCELLED"].includes(t.state) || !!s.mission?.stop_request || TERMINAL.has(s.mission?.state)}));
  if(draft.target.startsWith("worker:") && !options.some(o=>o.value===draft.target)) options.push({value:draft.target,label:"原 Worker（当前不可接收）",disabled:true});
  const key=JSON.stringify([mid,options]);
  if(selector.dataset.workers!==key){
    selector.dataset.workers=key;selector.querySelectorAll("option[data-w]").forEach(n=>n.remove());
    for(const item of options){const option=el("option",item.label);option.value=item.value;option.disabled=item.disabled;option.dataset.w="1";selector.append(option);}
  }
  selector.value=draft.target;$("d_text").value=draft.text;
  $("d_hint").textContent=!mid?"（先启动或查看一个任务）":!selector.value || selector.selectedOptions[0]?.disabled?"原接收对象当前不可接收；草稿已保留，请明确选择可用对象。":"";
}
$("d_text").addEventListener("input",()=>rememberDirective(true));
$("d_target").addEventListener("change",()=>{rememberDirective(true);renderDirectiveInput(LAST,(LAST?.subtasks || []).filter(t=>t.worker_session_id));syncButtons();});
function render(s){
  LAST=s;
  const m=s.mission, st=m?m.state:"空闲";
  $("missionState").textContent=m?text(m.id)+" · "+text(st):"空闲（新建或查看历史任务）";
  $("missionState").className="badge"+(STATES.has(st)?" "+st:"");
  $("runDot").className="dot"+(s.running?" on":"");
  $("elapsed").textContent=s.elapsed!=null?"已运行 "+text(s.elapsed)+"s":"";
  const diagnostics=[];
  if(m?.cancellation) diagnostics.push("取消状态："+text(m.cancellation.status)+" · "+text(m.cancellation.reason || "历史字段未提供")+" · Worker stop="+text(m.worker_stop?.status ?? "unknown"));
  if(m?.source) diagnostics.push("冻结 source："+text(m.source.source_ref)+" @ "+text(m.source.source_commit));
  else if(m) diagnostics.push("冻结 source：historical unknown / unavailable");
  if(m?.previous_attempt) diagnostics.push("前一 attempt："+text(m.previous_attempt));
  if(m && s.directive_receipts?.status!=="ok") diagnostics.push("指令回执："+text(s.directive_receipts?.status ?? "historical unknown / unavailable"));
  for(const r of s.directive_receipts?.records || []) diagnostics.push("指令 "+text(r.command_id)+" → "+text(r.target)+" · "+text(r.status)+" · "+text(r.reason)+"\n消费者："+text(r.consumers));
  if(m?.reason) diagnostics.push("Mission reason："+text(m.reason));
  if(m?.error) diagnostics.push("Mission read_error："+text(m.error));
  for(const error of s.panel_errors || []) diagnostics.push("Panel runner/error："+text(error));
  for(const error of s.read_errors || []) diagnostics.push(text(error.source)+" read_error："+text(error.error));
  $("diagnostics").textContent=diagnostics.join("\n");
  for(const [id,key] of [["k_poll","poll_seconds"],["k_idle","idle_audit_cooldown_seconds"],["k_block","blocked_escalation_seconds"],["k_grace","l0_nudge_grace_seconds"]]){
    if(document.activeElement!==$(id) && !$(id).dataset.dirty) $(id).value=s.config?.[key] ?? "";
  }
  if(s.default_config && document.activeElement!==$("configJson") && !$("configJson").dataset.dirty) $("configJson").value=JSON.stringify(s.default_config.values,null,2);
  $("defaultConfigInfo").textContent=configText(s.default_config,s.config_fields);
  $("missionConfig").textContent=s.mission_config?.status==="ok"?configText(s.mission_config.snapshot,s.config_fields):"本次配置："+text(s.mission_config?.status || "unknown")+"；不使用最新默认值伪造历史";
  if(s.mission?.execution_backend==="codex_app_server") $("missionConfig").textContent="执行后端：Codex App Server；ao.* 仅用于旧后端，本次不消费。\n"+$("missionConfig").textContent;
  renderPhases();
  const subs=s.subtasks || [];
  region("subtasks",[subs,m?.state,m?.cancellation],tasks=>{
  for(const task of subs){
    const card=el("div",null,"subtask");
    card.append(taskStatus(task),el("div",task.objective,"obj"));
    const details=el("details"), key=text(task.task_id);
    details.dataset.taskId=key;
    details.open=OPEN_SUBTASKS.has(key);
    details.ontoggle=()=>{if(details.open) OPEN_SUBTASKS.add(key); else OPEN_SUBTASKS.delete(key);};
    details.append(el("summary","执行记录"),el("p",key+" · "+text(task.worker_session_id)+" · "+text(task.state),"tid"),el("p",`LOCAL_FIX ${text(task.local_fixes)}/${text(task.max_local_fixes)} · REPLAN ${text(task.replans)}/${text(task.max_replans)}`,"tid"));
    card.append(details); tasks.append(card);
  }
  if(!subs.length) tasks.append(el("span","该任务尚未拆解子任务"));
  });
  const workers=subs.filter(t=>t.worker_session_id), group=$("workers"); group.replaceChildren();
  function svg(tag,attrs,value){
    const node=document.createElementNS("http://www.w3.org/2000/svg",tag);
    for(const [key,value] of Object.entries(attrs)) node.setAttribute(key,String(value));
    if(value!=null) node.textContent=text(value); return node;
  }
  workers.forEach((task,i)=>{
    const x=workers.length===1?210:145+i*(130/(workers.length-1)), y=416;
    const node=svg("g",{class:"node",id:"n-w"+i});
    node.append(svg("circle",{cx:x,cy:y,r:18,fill:"#b54708"}),svg("text",{x,y:y+4,"text-anchor":"middle"},"W"+(i+1)),svg("text",{x,y:y+31,"text-anchor":"middle",class:"sub"},task.state));
    group.append(node);
  });
  renderDirectiveInput(s,workers);
  document.querySelectorAll(".node").forEach(node=>node.classList.remove("active"));
  const latest=(s.transitions || [])[0];
  if(latest){
    const ids={observer:"n-observer",auditor:"n-auditor",planner:"n-planner",verifier:"n-verifier",integration_gate:"n-gate",closed_loop:"n-controller",executor:"n-controller",user:"n-user"};
    const id=Object.hasOwn(ids,latest.actor)?ids[latest.actor]:null; if(id) $(id)?.classList.add("active");
    $("lastAction").textContent=`最近：${text(latest.task)} → ${text(latest.to)}（${text(latest.actor)}：${text(latest.reason)}）`;
  }else $("lastAction").textContent="—";
  region("evidence",[s.gate_query,s.verifications],box=>{
    drawGate(s.gate_query);
    for(const v of s.verifications || []) box.append(el("pre","Verifier "+text(v.verdict)+" — "+text(v.summary),"diagnostic"));
  });
  const events=$("tab-ev"); events.replaceChildren();
  for(const t of s.transitions || []) events.append(el("div",text(t.at)+" "+text(t.actor)+" "+text(t.task)+" → "+text(t.to)+" "+text(t.reason),"ev diagnostic"));
  for(const t of (s.traffic || []).slice(-8)) events.append(el("div",text(t.at)+" 事件投影 "+text(t.sender)+" → "+text(t.receiver)+" "+text(t.kind),"ev diagnostic"));
  const alerts=$("tab-al"); alerts.replaceChildren();
  for(const a of s.alerts || []){
    const row=el("div",null,"ev"); row.append(el("b",text(a.detected_at)+" "+text(a.alert_type)));
    for(const key of ["summary","description","error","reason"]) if(a[key]!=null) row.append(el("pre",key+"："+text(a[key]),"diagnostic"));
    alerts.append(row);
  }
  if(!alerts.childNodes.length) alerts.append(el("span","无告警"));
  renderWorkbench(LIVE || s);
  syncButtons();
}

/* ---------------- workbench: live state presentation ---------------- */
const OPEN_SUBTASKS=new Set();
const TERMINAL=new Set(["MISSION_DONE","HUMAN","FAILED","CANCELLED"]);
const PHASE_NAMES={preflight:"准备与环境检查",prepare:"准备执行",preparation:"准备隔离工作树",projection:"同步状态记录",ao_read:"读取 AO 执行事实",observation_wait:"等待下次观察",approval_waiting:"等待审批",reconciliation:"核对外部操作结果",send:"发送受控指令",spawn:"创建 Worker",worker:"Worker 执行",worker_execution:"Worker 执行",observe:"观察执行进展",observation:"观察执行进展",approval_wait:"等待人工审批",approval:"检查审批请求",model_request:"语义模型复核",planner:"Planner 规划",auditor:"Auditor 审计",baseline_gate:"基线检查",task_gate:"任务验收",final_gate:"最终验收",gate:"确定性检查",materialization:"整理交付改动",materialize:"整理交付改动",merge:"合并隔离成果",verifier:"最终复核",retry_wait:"等待下一次尝试",stop:"确认 Worker 停止",kill:"确认 Worker 停止"};
function icon(name,tile){
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.setAttribute("class","icon"); svg.setAttribute("aria-hidden","true");
  const use=document.createElementNS(svg.namespaceURI,"use");use.setAttribute("href","/icons.svg#"+name);svg.append(use);
  if(!tile) return svg;
  const box=el("span",null,"icon-tile "+tile);box.append(svg);return box;
}
function factsFor(m){return (m?.id || m?.mission_id)===LIVE?.mission?.id?LIVE:(m?.id || m?.mission_id)===LAST?.mission?.id?LAST:null;}
function stateInfo(m){
  if(!m) return ["待开始","neutral"];
  if(m.cancellation?.status==="unknown" || m.worker_stop?.status==="UNKNOWN" && m.state!=="CANCELLING") return ["需处理","wait"];
  if(m.state==="CANCELLING") return ["取消中","wait"];
  if(m.state==="CANCELLED") return ["已取消","neutral"];
  if(m.state==="MISSION_DONE") return ["已完成","good"];
  if(m.state==="FAILED") return ["需处理","bad"];
  if(m.state==="HUMAN") return ["需处理","wait"];
  const facts=factsFor(m),phase=latestPhase(facts);
  if(facts?.approvals?.length) return ["需处理","wait"];
  if((m.id || m.mission_id)===facts?.mission?.id && phase?.status==="running" && ["approval_wait","approval_waiting"].includes(phase.phase)) return ["需处理","wait"];
  if(m.state==="MISSION_READY" && !((m.id || m.mission_id)===LAST?.mission?.id && LAST?.running)) return ["待开始","neutral"];
  if(["MISSION_READY","RUNNING","preflight","VERIFIER_PENDING"].includes(m.state)) return ["进行中","active"];
  return ["需处理","wait"];
}
function taskStatus(task){
  if(task.state==="DONE") return el("span","子任务已完成","status good");
  if(LAST?.mission?.state==="CANCELLED" && LAST.mission.cancellation?.status==="cancelled") return el("span","执行已停止","status neutral");
  if(["TASK_READY","PLANNER_PENDING"].includes(task.state)) return el("span","待开始","status neutral");
  if(["WORKER_RUNNING","WORKER_RETRYING","GATE_PENDING","AUDIT_PENDING","LOCAL_FIX_PENDING","REPLAN_PENDING"].includes(task.state)) return el("span","进行中","status active");
  return el("span","需处理","status "+(task.state==="FAILED"?"bad":"wait"));
}
function taskReason(m){
  const source=factsFor(m);
  if(source?.panel_errors?.length) return text(source.panel_errors.at(-1));
  if(m?.error) return text(m.error);
  if(m?.reason==="cancellation stop facts UNKNOWN") return "取消请求已接收，但执行停止尚未确认。";
  if(m?.reason==="final gate pass + verifier PASS") return "最终验收与复核通过。";
  if(m?.reason) return text(m.reason);
  if(m?.cancellation?.status==="unknown" || m?.worker_stop?.status==="UNKNOWN") return "停止尚未确认。";
  if(m?.state==="CANCELLING") return "取消请求已接收，正在确认停止。";
  const facts=factsFor(m),p=latestPhase(facts);
  if(facts?.approvals?.length) return facts.approvals.some(r=>r.method==="item/tool/requestUserInput")?"需要补充回答。":"有请求等待审批。";
  if((m?.id || m?.mission_id)===facts?.mission?.id && p?.status==="running") return p.reason || phaseLabel(p);
  return "";
}
function statusBadge(m){const [label,tone]=stateInfo(m);return el("span",label,"status "+tone);}
function putStatus(id,m){const [label,tone]=stateInfo(m);$(id).textContent=label;$(id).className="status "+tone;}
function phaseLabel(p){if(p?.phase==="model_request") return ({planner:"规划模型执行",auditor:"审计模型执行",verifier:"最终复核模型执行",worker:"Worker 模型执行"})[p.role] || "模型执行（角色未知）";return Object.hasOwn(PHASE_NAMES,p?.phase)?PHASE_NAMES[p.phase]:(p?.phase?"执行阶段（详见高级记录）":"阶段尚未提供");}
function latestPhase(snapshot=LAST){const rows=snapshot?.phases?.records || [];return rows.find(p=>p.status==="running") || rows[0];}
function friendlyElapsed(p){
  if(p?.elapsed_seconds==null) return "耗时未知";
  const delta=p.status==="running" && RECEIVED_MONO!=null?Math.max(0,((CONNECTED?performance.now():(DISCONNECTED_MONO ?? RECEIVED_MONO))-RECEIVED_MONO)/1000):0;
  return "已记录 "+Math.floor(p.elapsed_seconds+delta)+" 秒";
}
function renderFriendlyPhase(){
  const p=latestPhase();
  $("connectionStatus").textContent=CONNECTED?"已连接":"连接中断 · 保留记录";
  $("connectionStatus").classList.toggle("offline",!CONNECTED);
  if(DETAIL_ID===LAST?.mission?.id) $("friendlyPhase").textContent=LAST?.mission?.cancellation?.status==="unknown" || LAST?.mission?.worker_stop?.status==="UNKNOWN"?"等待停止确认":LAST?.mission?.state==="CANCELLING"?"取消中 · 正在确认停止":LAST?.mission?.state==="MISSION_DONE"?"最终验收已完成":LAST?.mission?.state==="CANCELLED"?"执行已取消":LAST?.preparing?"正在准备任务":LAST?.approvals?.length?(LAST.approvals.some(r=>r.method==="item/tool/requestUserInput")?"等待回答":"等待审批"):p?phaseLabel(p)+" · "+friendlyElapsed(p)+(p.attempt!=null?" · 第 "+text(p.attempt)+" 次尝试":""):"尚无阶段记录，耗时未知。";
}
function empty(title,description){const n=el("div",null,"empty");n.append(el("h3",title));if(description) n.append(el("p",description));return n;}
function navigate(view,focus=false){
  if(!["overview","tasks","models","settings"].includes(view)) return;
  VIEW=view;
  history.replaceState(null,"", "#"+view+(view==="tasks" && DETAIL_ID?"/"+encodeURIComponent(DETAIL_ID):""));
  document.querySelectorAll(".view").forEach(n=>n.hidden=n.id!=="view-"+view);
  document.querySelectorAll("[data-view]").forEach(n=>{if(n.dataset.view===view)n.setAttribute("aria-current","page");else n.removeAttribute("aria-current");});
  $("locationName").textContent=({overview:"概览",tasks:"任务",models:"模型",settings:"设置"})[view];
  showClientErrors();
  if(focus) $(view+"Heading").focus();
}
// Keep actionable regions stable while the user is interacting with them. Apply the
// newest snapshot when focus leaves; timers never replace focused buttons/inputs.
const REGION_KEYS=new Map(), DEFERRED_REGIONS=new Map();
function region(id,key,build){
  const node=$(id), signature=JSON.stringify(key);
  if(REGION_KEYS.get(id)===signature) {DEFERRED_REGIONS.delete(id);return;}
  if(node.contains(document.activeElement)) {DEFERRED_REGIONS.set(id,()=>region(id,key,build));return;}
  REGION_KEYS.set(id,signature);DEFERRED_REGIONS.delete(id);node.replaceChildren();build(node);
}
document.addEventListener("focusout",()=>setTimeout(()=>{
  for(const [id,update] of DEFERRED_REGIONS) if(!$(id).contains(document.activeElement)) update();
},0));
function renderSelected(){
  if(!LIVE) return;
  const selected=DETAIL_ID && DETAIL_ID!==LIVE.mission?.id && HISTORY?.mission?.id===DETAIL_ID?HISTORY:LIVE;
  render({...selected,missions:LIVE.missions,default_config:LIVE.default_config,config:LIVE.config,config_fields:LIVE.config_fields,
    readiness:LIVE.readiness,active_running:LIVE.running || LIVE.preparing,active_mission_id:LIVE.mission?.id});
}
async function loadHistory(mid,force=false){
  if(!force && HISTORY_REQUEST && loadHistory.target===mid) return;
  const generation=++HISTORY_REQUEST;loadHistory.target=mid;
  try{
    const response=await fetch("/api/mission?mission_id="+encodeURIComponent(mid));
    const data=await response.json();
    if(generation!==HISTORY_REQUEST || DETAIL_ID!==mid) return;
    if(!response.ok || data.mission?.id!==mid) throw new Error(data.error || "任务详情读取失败");
    HISTORY=data;uiError("历史",null);renderSelected();
  }catch(error){if(generation===HISTORY_REQUEST && DETAIL_ID===mid){uiError("历史",error.message,mid);$("detailUnloaded").textContent=error.message;}}
  finally{if(generation===HISTORY_REQUEST) loadHistory.target=null;}
}
function openTask(mid){
  DETAIL_ID=mid;HISTORY=null;navigate("tasks");renderSelected();
  if(mid!==LIVE?.mission?.id) loadHistory(mid);
  $("detailTitle").focus();
}
function taskRows(){
  const rows=[...(LIVE?.missions || LAST?.missions || [])];
  const currentMission=LIVE?.mission || LAST?.mission;
  if(currentMission){
    const current=rows.findIndex(r=>r.mission_id===currentMission.id), fact={mission_id:currentMission.id,...currentMission};
    if(current===-1) rows.unshift(fact);else rows[current]={...rows[current],...fact};
  }
  return rows;
}
function projectLabel(row){const registered=row.execution_backend==="codex_app_server"?PROJECTS.find(p=>p.id===row.project_id):null;const location=row.project_path || row.source?.original_path || row.source?.project_path;return registered?.name || (location?location.split(/[\\/]/).filter(Boolean).at(-1):row.project_id) || "项目未提供";}
function renderTaskList(){
  const filter=$("taskFilter").value, search=$("taskSearch").value.trim().toLocaleLowerCase(), project=$("projectFilter").value;
  region("projectFilter",[...new Set(taskRows().map(r=>r.project_id).filter(Boolean))],box=>{const first=el("option","全部项目");first.value="";box.append(first);for(const id of new Set(taskRows().map(r=>r.project_id).filter(Boolean))){const option=el("option",projectLabel(taskRows().find(r=>r.project_id===id)));option.value=id;box.append(option);}box.value=project;});
  region("missionsList",[taskRows(),filter,search,project,LIVE?.running,latestPhase()?.phase,latestPhase()?.status],box=>{
    const rows=taskRows().filter(r=>(!search || text(r.objective).toLocaleLowerCase().includes(search)) && (!project || r.project_id===project)).filter(r=>filter==="all" || filter==="active" && !TERMINAL.has(r.state) || filter==="needs" && stateInfo(r)[0]==="需处理" || filter==="done" && ["MISSION_DONE","CANCELLED"].includes(r.state));
    for(const item of rows){
      const row=el("div",null,"mrow");row.dataset.missionId=item.mission_id;
      const body=el("div",null,"grow"), title=el("button",null,"link-row");
      title.append(el("h3",item.objective || "目标未提供"),icon("chevron-right"));title.onclick=()=>openTask(item.mission_id);
      body.append(title,statusBadge(item));
      if(item.project_id) body.append(el("p",projectLabel(item),"subtle"));
      if(item.error) body.append(el("pre","读取失败："+text(item.error),"diagnostic"));
      const actions=el("div",null,"row-actions");
      const view=el("button","查看");view.onclick=()=>openTask(item.mission_id);actions.append(view);
      row.append(icon("list-checks","green"),body,actions);box.append(row);
    }
    if(!rows.length) box.append(empty("这里还没有任务记录",filter==="all"?"新建一个任务，写清目标与验收条件。":"换一个状态筛选，查看其他记录。"));
  });
}
function nextStep(m){
  if(m?.cancellation?.status==="unknown" || m?.worker_stop?.status==="UNKNOWN" && m?.state!=="CANCELLING") return m.execution_backend==="codex_app_server"?"Codex 停止尚未确认；保留工作区并人工核对执行记录。":"请在 AO 核对执行是否已停止。";
  if(m?.state==="CANCELLING") return "等待停止确认。";
  if(m?.state==="CANCELLED") return "可查看记录，或重新执行。";
  if(m?.state==="MISSION_DONE") return "查看成果与验收记录。";
  if(["HUMAN","FAILED"].includes(m?.state)) return "处理原因中指出的问题后，再决定是否重新执行。";
  if(m?.inspection_only) return "当前仅查看存档。恢复前需通过已有材料检查。";
  return "可等待执行，或补充指令。";
}
function renderTaskDetail(){
  $("taskListArea").hidden=!!DETAIL_ID;$("taskDetail").hidden=!DETAIL_ID;
  if(!DETAIL_ID) return;
  const loaded=DETAIL_ID===LAST?.mission?.id, live=loaded && DETAIL_ID===LIVE?.mission?.id;
  const m=loaded?LAST.mission:taskRows().find(r=>r.mission_id===DETAIL_ID);
  $("detailTitle").textContent=m?.objective || "正在读取任务…";putStatus("detailState",m);
  const reason=taskReason(m);
  $("detailReason").textContent=reason;$("detailReason").hidden=!reason;
  $("detailNext").textContent=LIVE?.launch_blocked || (loaded && LAST.actions?.reason?LAST.actions.reason:nextStep(m));
  $("loadedDetail").hidden=!loaded;$("detailUnloaded").hidden=loaded;
  if(!loaded) $("detailUnloaded").textContent="正在只读加载任务详情…";
  $("btnStop").hidden=!live || !LIVE?.running;
  const busy=LIVE?.running || LIVE?.preparing;
  region("detailExtraActions",[DETAIL_ID,m?.state,loaded,busy,LIVE?.launch_blocked,LAST?.actions],box=>{
    if(!loaded || busy) return;
    const capability=TERMINAL.has(m?.state)?"new_attempt":"resume";
    const button=actionButton(capability==="new_attempt"?"重新执行":"检查并恢复","mission",()=>capability==="new_attempt"?newAttempt(m.id):resume(m.id));
    if(LIVE?.launch_blocked || LAST.actions && !LAST.actions[capability]){button.dataset.blocked="1";button.disabled=true;button.title=LIVE?.launch_blocked || LAST.actions.reason;}
    box.append(button);
  });
  $("friendlyPhase").textContent=loaded?"阶段尚未提供":"正在读取阶段记录…";
  if(!loaded) return;
  const p=latestPhase(), phase=p?.phase || "", index=/preflight|prepare|spawn/.test(phase)?0:/gate/.test(phase)?2:/materializ|merge|verifier/.test(phase) || phase==="model_request" && p.role==="verifier"?3:/worker|observ|approval|model_request|planner|auditor|retry/.test(phase)?1:-1;
  region("phaseRail",index,box=>["准备","执行与观察","验收","成果复核"].forEach((label,i)=>box.append(el("span",label,i===index?"reached":""))));
  renderApprovals();
  const result=LAST.result;
  $("resultConclusion").textContent=m.state==="MISSION_DONE"?"任务已通过最终验收":m.state==="CANCELLED"?"任务已取消，未交付通过验收的结果":TERMINAL.has(m.state)?"本次任务未通过最终验收":"任务尚未完成验收";
  $("resultLocation").textContent=result?.status==="available"?(result.accepted?"成果目录：":"未通过验收的产物目录：")+text(result.path):result?.status==="missing"?"历史结果位置已失效："+text(result.path):result?.status==="read_error"?"结果位置读取失败："+text(result.reason):"尚无可用成果目录";
  const final=(LAST.verifications || []).find(v=>v.task_id===m.id || v.mission_id===m.id);
  $("verifierSummary").textContent=final?"复核："+text(final.verdict || "unknown")+" · "+text(final.summary || final.reason || "历史未提供摘要"):"最终复核尚未提供记录";
  renderResult(m);
  const draft=DIRECTIVE_DRAFTS.get(m.id), receipts=LAST.directive_receipts?.records || [];
  if(draft?.receipt && receipts.some(r=>r.command_id===draft.receipt.command_id)) draft.receipt=null;
  region("receiptSummary",[m.id,LAST.directive_receipts,draft?.receipt],box=>{
    for(const receipt of [...(draft?.receipt?[draft.receipt]:[]),...receipts].slice(0,6)) box.append(el("p",text(receipt.target)+" · "+text(receipt.status)+" · "+text(receipt.reason)));
  });
  renderFriendlyPhase();syncButtons();
}
function resultKey(){return JSON.stringify([LAST?.mission?.state,LAST?.result?.recorded_head,LAST?.verifications,LAST?.gate_query]);}
async function loadResult(mid,force=false){
  const key=mid===LAST?.mission?.id?resultKey():RESULTS.get(mid)?.key;
  const previous=RESULTS.get(mid);
  if(!force && previous?.key===key) return;
  const request={key,status:"loading",data:previous?.data};RESULTS.set(mid,request);
  try{
    const response=await fetch("/api/result?mission_id="+encodeURIComponent(mid)),data=await response.json();
    if(!response.ok || !data.ok || data.result?.mission_id!==mid) throw new Error(data.error || "结果读取失败");
    if(RESULTS.get(mid)!==request) return;
    Object.assign(request,{status:"loaded",data:data.result});
  }catch(error){if(RESULTS.get(mid)===request) Object.assign(request,{status:"read_error",error:error.message});}
  finally{if(DETAIL_ID===mid && LAST?.mission?.id===mid) renderTaskDetail();}
}
function resultNotice(mid,message){RESULT_NOTICES.set(mid,message);if(DETAIL_ID===mid) $("resultOperation").textContent=message;}
async function copyResult(mid,path){
  const key="copy-result:"+mid;if(PENDING.has(key)) return;PENDING.add(key);syncButtons();
  try{
    if(!navigator.clipboard?.writeText) throw new Error("浏览器不支持剪贴板写入，请手动选择结果路径复制");
    await navigator.clipboard.writeText(path);resultNotice(mid,"结果路径已复制");
  }catch(error){resultNotice(mid,"复制失败："+error.message);}
  finally{PENDING.delete(key);syncButtons();}
}
async function downloadResult(mid,identity){
  const key="download-result:"+mid;if(PENDING.has(key)) return;PENDING.add(key);syncButtons();
  try{
    const response=await fetch("/api/result/download?mission_id="+encodeURIComponent(mid)+"&export_id="+encodeURIComponent(identity));
    if(!response.ok || !response.headers.get("Content-Type")?.startsWith("application/zip")){
      const error=await response.json();throw new Error(error.error || "下载失败");
    }
    const blob=await response.blob(),url=URL.createObjectURL(blob),a=el("a");
    a.href=url;a.download="clao-result-"+identity+".zip";document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),30000);
    resultNotice(mid,"结果包已交给浏览器下载；请在下载列表确认保存位置");
  }catch(error){resultNotice(mid,"下载失败："+error.message);}
  finally{PENDING.delete(key);syncButtons();}
}
function renderResult(m){
  const mid=m.id;
  loadResult(mid);
  const view=RESULTS.get(mid),r=view?.data;
  $("resultOperation").textContent=RESULT_NOTICES.get(mid) || "";
  $("resultReadStatus").textContent=view?.status==="loading"?"正在读取固定结果…":view?.status==="read_error"?"结果读取失败："+text(view.error):r?.status!=="ok"?text(r?.reason):r.no_changes?"已记录结果没有代码净变化":"";
  $("resultIdentity").textContent=r?"项目："+text(r.evidence?.mission?.project_id)+"\n冻结来源："+text(r.base_commit || "历史未提供")+"\n结果提交："+text(r.result_commit || "历史未提供")+"\n只读取已记录版本；当前工作目录的新改动不属于本次验收。":"正在读取…";
  if(r && view.status==="loaded"){
    const location=r.location;
    $("resultLocation").textContent=location.status==="available"?"结果目录："+text(location.path):location.status==="missing"?"原结果目录已失效；已保存的包仍可下载":location.status==="read_error"?"结果目录读取失败："+text(location.reason):"尚无结果目录";
    const v=r.evidence?.verifier;
    $("verifierSummary").textContent=v?.status==="read_error"?"复核记录读取失败："+text(v.error):v?.record?"复核："+text(v.record.verdict || "unknown")+" · "+text(v.record.summary || "历史未提供摘要"):"最终复核未提供记录；不从 Mission 结论推断";
  }
  region("resultActions",[mid,view?.status,r?.status,r?.location],box=>{
    if(view?.status!=="loaded" || !r) return;
    if(r.location?.status==="available"){
      box.append(actionButton("复制结果路径","copy-result:"+mid,()=>copyResult(mid,r.location.path)));
      box.append(actionButton("打开结果目录","open-result:"+mid,()=>writeAction("open-result:"+mid,"/api/result/open",{mission_id:mid},data=>resultNotice(mid,data.message))));
    }
    if(r.status==="ok") box.append(actionButton("生成结果包","export-result:"+mid,()=>writeAction("export-result:"+mid,"/api/result/export",{mission_id:mid},async data=>{
      resultNotice(mid,data.export.accepted?"完整结果包已保存，可以下载":"结果包已保存，未通过最终验收");await loadResult(mid,true);
    })));
  });
  region("resultExports",[mid,r?.exports],box=>{
    for(const pkg of r?.exports || []){
      const row=el("div");row.append(el("p",(pkg.accepted?"已通过验收的结果包":"未通过最终验收的结果包")+" · "+text(pkg.bytes)+" 字节"));
      if(pkg.status==="ready") row.append(actionButton("下载结果包","download-result:"+mid,()=>downloadResult(mid,pkg.identity)));
      else row.append(el("p",pkg.reason,"field-error"));
      const d=el("details");d.append(el("summary","包标识与校验"),el("pre","SHA-256："+text(pkg.sha256)+"\n结果："+text(pkg.result_commit)+"\n保存："+text(pkg.created_at),"diagnostic"));row.append(d);box.append(row);
    }
  });
  region("resultChanges",[mid,r?.changes],box=>{
    if(!r?.changes?.length) return;
    box.append(el("h3","修改文件 · "+r.changes.length));
    for(const change of r.changes){
      const row=el("div",null,"result-file");row.append(el("span",({A:"新增",M:"修改",D:"删除",R:"重命名",C:"复制",T:"类型变化"})[change.kind] || "未知","status neutral"),el("span",change.old_path && change.old_path!==change.path?change.old_path+" → "+change.path:change.path));box.append(row);
    }
  });
  $("resultDiff").hidden=!r || !["ok","saved"].includes(r.status);
  $("resultDiffNote").textContent=r?.diff_truncated?"页面差异已截断（完整 "+text(r.diff_bytes)+" 字节）；下载包中的补丁完整保留。":"";
  $("resultDiffText").textContent=r?.diff || "没有代码净变化";
  region("resultAC",[mid,r?.evidence?.acceptance_criteria],box=>{
    box.append(el("h3","验收条件"));
    const acs=r?.evidence?.acceptance_criteria || [];
    if(!acs.length) box.append(el("p","历史未提供验收条目","subtle"));
    for(const ac of acs){const row=el("div",null,"ev");row.append(el("b",ac.description || ac.id),el("p",({PASS:"通过",FAIL:"未通过",UNVERIFIABLE:"无法验证"})[ac.verdict] || "未知"),el("p",ac.note,"subtle"));box.append(row);}
  });
  if(view?.status==="loaded" && r?.evidence?.gates) region("evidence",[mid,r.evidence.gates],()=>drawGate(r.evidence.gates));
  syncButtons();
}
$("refreshResult").onclick=()=>{if(DETAIL_ID) loadResult(DETAIL_ID,true);};
function renderReadiness(){
  const state=LIVE?.readiness || {status:"unchecked"};
  $("environmentStatus").textContent=({unchecked:"尚未检查",checking:"检查中",ready:"可运行",needs_action:"需要处理"})[state.status] || "检查状态未知";
  $("environmentStatus").className="status "+(state.status==="ready"?"good":state.status==="needs_action"?"bad":"neutral");
  $("environmentReason").textContent=[state.reason,state.version?"Codex "+state.version:null,state.python?"Python "+state.python:null,state.action,state.checked_at?"检查于 "+new Date(state.checked_at*1000).toLocaleTimeString():null].filter(Boolean).join(" · ");
  $("checkEnvironment").textContent=state.status==="unchecked"?"检查环境":"重新检查";
  $("checkEnvironment").disabled=state.status==="checking" || PENDING.has("readiness");
  $("readiness").textContent=PROJECT_ERROR;$("readiness").hidden=!!LIVE?.mission || !PROJECT_ERROR;
}
$("checkEnvironment").onclick=()=>writeAction("readiness","/api/readiness",{},d=>{if(LIVE){LIVE.readiness=d.readiness;renderReadiness();}});
function renderWorkbench(s){
  const m=s.mission;putStatus("overviewState",m);
  region("currentTask",[m,s.running,s.phases?.records?.[0]?.phase],box=>{
    if(!m){const card=empty("还没有任务","点击“新建任务”开始。");card.prepend(icon("plus","blue"));box.append(card);return;}
    box.append(el("h3",m.objective || "目标未提供"),el("p",taskReason(m),"task-lead"));
    const meta=el("div",null,"current-meta");
    for(const [label,value] of [["当前阶段",phaseLabel(latestPhase(s))]]){const pair=el("div");pair.append(el("span",label),el("p",value));meta.append(pair);}
    const button=el("button","查看任务详情","primary");button.append(icon("arrow-right"));button.onclick=()=>openTask(m.id);box.append(meta,button);
  });
  region("attention",[m?.state,m?.reason,m?.worker_stop,s.launch_blocked,s.alerts,s.panel_errors,s.read_errors,s.gate_query?.status,s.approvals,CONNECTED],box=>{
    const notes=[], seen=new Set([taskReason(m)]);
    if(s.approvals?.length){const button=el("button",s.approvals.some(r=>r.method==="item/tool/requestUserInput")?"有问题等待回答 · 去处理":"有审批等待处理 · 去处理","primary");button.onclick=()=>{openTask(m.id);$("approvalCard").scrollIntoView({block:"center"});};box.append(button);}
    function note(title,values,tone){
      const fresh=[...new Set(values.filter(v=>v!=null).map(text))].filter(v=>v && !seen.has(v));
      fresh.forEach(v=>seen.add(v));
      if(fresh.length) notes.push([title,fresh.join("\n"),tone]);
    }
    if(s.launch_blocked) note("执行限制",[s.launch_blocked],"warning");
    for(const error of s.panel_errors || []) note("运行器错误",[error],"error");
    for(const error of s.read_errors || []) {
      if(/gate/.test(error.source)) continue; // Gate errors belong to the evidence card.
      note("记录读取失败",[error.error],"error");
    }
    for(const a of s.alerts || []) note(a.summary || "告警",[a.description,a.error,a.reason].filter(v=>v!=null).length?[a.description,a.error,a.reason]:[a.summary],"warning");
    for(const [title,reason,tone] of notes){const n=el("div",null,"notice "+tone);n.append(el("strong",title));if(reason!==text(title)) n.append(el("p",reason));box.append(n);}
    if(s.gate_query?.status==="read_error"){
      const link=el(m?"button":"p",m?"Gate 记录读取失败 · 查看证据":"Gate 记录读取失败："+text(s.gate_query.error),"text-button");if(m) link.onclick=()=>{openTask(m.id);$("evidence").scrollIntoView({block:"center"});};
      box.append(link);
    }
    if(!notes.length && !s.approvals?.length && s.gate_query?.status!=="read_error") box.append(el("p",m && stateInfo(m)[0]==="需处理"?"请查看当前任务的原因与处理入口。":"暂无待处理事项。","subtle"));
  });
  region("recentResults",s.missions,box=>{
    const rows=(s.missions || []).filter(r=>TERMINAL.has(r.state)).slice(0,3);
    for(const r of rows){const row=el("div",null,"list-row"),button=el("button",null,"link-row");button.append(el("span",r.objective || "目标未提供"),statusBadge(r));button.onclick=()=>openTask(r.mission_id);row.append(button);box.append(row);}
    if(!rows.length) box.append(el("p","暂无结果。","subtle"));
  });
  region("roleCards",s.default_config,box=>{
    const values=s.default_config?.values;
    for(const role of ["worker","planner","auditor","verifier"]){
      const row=el("div",null,"list-row"), body=el("div",null,"grow");body.append(el("h3",role==="worker"?"执行 · Worker":({planner:"规划 · Planner",auditor:"审计 · Auditor",verifier:"复核 · Verifier"})[role]));
      row.append(icon(role==="worker"?"list-checks":"cpu",role==="worker"?"green":"purple"),body,el("div",(role==="worker"?values?.worker?.model:values?.roles?.[role]?.model) || "配置尚未提供","model-value"));box.append(row);
    }
  });
  renderReadiness();renderTaskList();renderTaskDetail();renderFriendlyPhase();
}

/* ---------------- navigation, dialogs and progressive form ---------------- */
$("detailActions").append(el("span",null,"button-row"));$("detailActions").lastChild.id="detailExtraActions";
document.querySelectorAll("[data-view],[data-go]").forEach(b=>b.onclick=()=>navigate(b.dataset.view || b.dataset.go,true));
$("backToTasks").onclick=()=>{DETAIL_ID=null;HISTORY=null;navigate("tasks");renderSelected();renderTaskDetail();$("tasksHeading").focus();};
$("taskFilter").onchange=renderTaskList;$("taskSearch").oninput=renderTaskList;$("projectFilter").onchange=renderTaskList;
const DIALOG_OPENERS=new Map();
function showDialog(id){const dialog=$(id);DIALOG_OPENERS.set(id,document.activeElement);if(!dialog.open) dialog.showModal();showClientErrors();}
function closeDialog(id){$(id).close();}
for(const id of ["newMission","retryMission"]) $(id).addEventListener("close",()=>{const opener=DIALOG_OPENERS.get(id);if(opener?.isConnected) opener.focus();showClientErrors();});
$("closeMission").onclick=()=>closeDialog("newMission");
function showSelectedProject(){
  const selected=PROJECTS.find(p=>String(p.id)===$("f_project").value);
  $("f_project_meta").textContent=selected?"项目路径："+text(selected.path || "未提供")+" · 类型："+text(selected.kind || "未提供"):"尚未选择项目。";
  syncButtons();
}
async function loadProjects(){
  const selector=$("f_project"), selected=selector.value;
  selector.disabled=true;$("btnProjects").disabled=true;syncButtons();
  try{
    const d=await (await fetch("/api/projects")).json();
    if(!d.ok) throw new Error(d.error || "本地项目读取失败");
    PROJECTS=d.projects || [];
    const prompt=el("option",PROJECTS.length?"请选择一个项目":"请打开本地目录或创建空项目");prompt.value="";selector.replaceChildren(prompt);
    PROJECTS.forEach(p=>{const option=el("option",p.name);option.value=String(p.id);selector.append(option);});
    selector.value=selected;if(!selector.value) selector.value="";selector.disabled=!PROJECTS.length;
    PROJECT_ERROR=PROJECTS.length?"":"请打开本地目录或创建空项目";
  }catch(error){PROJECTS=[];PROJECT_ERROR=error.message;const prompt=el("option","本地项目加载失败");prompt.value="";selector.replaceChildren(prompt);}
  finally{$("f_project_error").textContent=PROJECT_ERROR;$("btnProjects").disabled=false;showSelectedProject();renderReadiness();}
}
$("f_project").onchange=()=>{SOURCE=null;$("sourceConfirmed").checked=false;loadSource();$("f_project_error").textContent="";$("f_project").removeAttribute("aria-invalid");showSelectedProject();};
$("btnProjects").onclick=loadProjects;

async function loadSource(){
  SOURCE=null;$("sourceConfirmed").checked=false;$("sourceSummary").textContent="正在读取来源…";$("sourceFiles").textContent="";
  if(!$("f_project").value) return;
  if(PENDING.has("source")) return;
  const projectId=$("f_project").value;
  await writeAction("source","/api/projects/source",{project_id:projectId},d=>{
    if(d.source.project_id!==$("f_project").value) return;
    SOURCE=d.source;$("sourceSummary").textContent=SOURCE.file_count+" 个文件 · "+SOURCE.bytes+" 字节";
    $("sourceFiles").textContent="纳入当前目录内容：\n"+SOURCE.files.map(f=>f.path).join("\n")+"\n\n排除：\n"+SOURCE.excluded.map(f=>f.path+" · "+f.reason).join("\n");
    if(WIZARD_STEP===3) renderReview();
  });
  if($("f_project").value && $("f_project").value!==projectId) loadSource();
}
$("refreshSource").dataset.writeKey="source";$("refreshSource").onclick=loadSource;
for(const [id,path] of [["openProject","/api/projects/open"],["createProject","/api/projects/create"]]){
  $(id).dataset.writeKey="project";
  $(id).onclick=()=>{
    const value=$("projectPath").value.trim();
    if(!value){$("projectPathError").textContent="请填写本地目录的完整路径。";$("projectPath").focus();return;}
    $("projectPathError").textContent="";
    writeAction("project",path,{path:value},async d=>{await loadProjects();$("f_project").value=d.project.id;showSelectedProject();await loadSource();});
  };
}
function renderApprovals(){
  const requests=LAST?.approvals || [], receipts=LAST?.approval_receipts || [], mid=LAST?.mission?.id;
  $("approvalCard").hidden=!requests.length && !receipts.length;
  $("approvalReceipts").textContent=receipts.map(r=>text(r.reason)+"（"+text(r.adoption || r.status)+"）").join("\n");
  const keys=new Set(requests.map(r=>r.worker_id+":"+r.request_id));
  // Retire closed requests immediately, even while a focused region defers replacement.
  $("approvalRequests").querySelectorAll("[data-request-key]").forEach(n=>{
    if(!keys.has(n.dataset.requestKey)){n.querySelectorAll("button,input,textarea,select").forEach(b=>{b.disabled=true;b.dataset.blocked="1";});n.dataset.closed="true";}
  });
  region("approvalRequests",[mid,requests],box=>{
    for(const request of requests){
      const row=el("div",null,"list-row"),body=el("div",null,"grow"),actions=el("div",null,"button-row");
      row.dataset.requestKey=request.worker_id+":"+request.request_id;
      body.append(el("h3",request.method==="item/tool/requestUserInput"?"等待回答":"待审阅请求"),el("p",request.task_objective || "任务归属："+text(request.task_id)),
        el("p",request.reason || request.policy_reason),el("pre",[request.command,request.cwd,...(request.paths || [])].filter(Boolean).join("\n"),"diagnostic"));
      if(request.reason && request.policy_reason && request.policy_reason!==request.reason) body.append(el("p",request.policy_reason,"subtle"));
      for(const change of request.changes || []){const d=el("details");d.append(el("summary",text(change.path)+" · 查看文件差异"),el("pre",change.diff || "引擎未提供差异正文","diagnostic"));if(change.truncated)d.append(el("p","差异展示已截断；此处不是完整审阅材料。","field-error"));body.append(d);}
      const key="approval:"+request.worker_id+":"+request.request_id;
      const send=(decision,answers)=>{
        if(LAST?.mission?.id!==mid || LIVE?.mission?.id!==mid || !(LAST.approvals || []).some(r=>r.worker_id===request.worker_id && r.request_id===request.request_id)) return;
        // Receipts are rendered only from the mission-bound durable projection.
        // A delayed HTTP ACK must never write into another mission's card.
        return writeAction(key,"/api/approval",{mission_id:mid,worker_id:request.worker_id,request_id:request.request_id,decision,answers});
      };
      if(request.method==="item/tool/requestUserInput"){
        const fields=[];
        for(const question of request.questions || []){
          const label=el("label",question.question),input=el(question.isSecret?"input":"textarea");if(question.isSecret)input.type="password";else input.rows=2;input.setAttribute("aria-label",question.question);input.autocomplete="off";
          if(question.options?.length){const selector=el("select");selector.setAttribute("aria-label",question.question+" 可用选项");const prompt=el("option","选择一个选项");prompt.value="";selector.append(prompt);
            for(const option of question.options){const node=el("option",option.label+(option.description?" · "+option.description:""));node.value=option.label;selector.append(node);}selector.onchange=()=>{input.value=selector.value;};label.append(selector);}
          // The existing backend supports one text answer per question; secret
          // questions are not echoed or stored as a browser draft.
          label.append(input);fields.push([question.id,input]);
          body.append(label);
        }
        const error=el("p",null,"field-error");body.append(error);
        actions.append(actionButton("提交回答",key,()=>{const missing=fields.find(([,input])=>!input.value.trim());if(missing){error.textContent="请回答每个问题。";missing[1].focus();return;}send("answer",Object.fromEntries(fields.map(([id,input])=>[id,input.value])));}));
      }else{
        if(request.allow_once_supported) actions.append(actionButton("允许一次",key,()=>send("accept")));
        else body.append(el("p","本任务禁止或当前不支持授权，不能允许一次。","field-error"));
        if(request.decline_supported) actions.append(actionButton("拒绝",key,()=>send("decline")));
      }
      body.append(actions);row.append(body);box.append(row);
    }
  });
}

const MISSION_FIELDS=[
 ["worker.model","Worker 模型","model"],["roles.planner.model","Planner 模型","model"],["roles.auditor.model","Auditor 模型","model"],["roles.verifier.model","Verifier 模型","model"],
 ["budgets.max_runtime_seconds","任务预算（秒）","seconds"],["runner.cap_seconds","本次运行上限（秒）","seconds"],
 ["budgets.max_total_replans","总重新规划次数","count"],["budgets.subtask_budgets.max_local_fixes","每个子任务修正次数","count"],
 ["gate.timeout_seconds","每条 Gate 超时（秒）","seconds"],["gate.output_limit_chars","每段 Gate 输出上限（字符）","count"]
];
function configValue(values,path){return path.split(".").reduce((v,k)=>v?.[k],values);}
function configSet(values,path,value){const parts=path.split(".");let node=values;for(const key of parts.slice(0,-1)) node=node[key] ||= {};node[parts.at(-1)]=value;}
function initializeParameters(){
  if(FORM_BASE || !LIVE?.default_config) return;
  FORM_BASE=structuredClone(LIVE.default_config);
  const box=$("missionParameters");
  for(const [path,label,kind] of MISSION_FIELDS){const l=el("label",label),input=el("input");input.id="param_"+path.replaceAll(".","_");input.dataset.configPath=path;input.type=kind==="model"?"text":"number";input.value=configValue(FORM_BASE.values,path);if(kind!=="model")input.step=kind==="seconds"?"any":"1";input.oninput=()=>{FORM_CONFIG=null;CONFIG_VERSION++;$("configConfirmStatus").textContent="配置已修改，正在核对…";confirmConfig();};l.append(input);box.append(l);}
  if(!$("f_sub").dataset.dirty) $("f_sub").value=String(FORM_BASE.values.budgets.max_subtasks);
}
async function confirmConfig(){
  initializeParameters();if(!FORM_BASE || PENDING.has("config-preview")) return;
  const version=CONFIG_VERSION, overrides={budgets:{max_subtasks:Number($("f_sub").value)}};
  for(const [path,,kind] of MISSION_FIELDS){const input=$("param_"+path.replaceAll(".","_"));configSet(overrides,path,kind==="model"?input.value:input.value.trim()?Number(input.value):null);}
  FORM_CONFIG=null;
  await writeAction("config-preview","/api/mission-config",{base:FORM_BASE,overrides},d=>{
    if(version!==CONFIG_VERSION) return;
    FORM_CONFIG=d.snapshot;renderReview();$("missionParametersError").textContent="";$("configConfirmStatus").textContent="以上配置将在本次任务中固定；新默认设置不改动本次确认。";
  });
  if(version!==CONFIG_VERSION && $("newMission").open) confirmConfig();
}
function showStep(step,focus=true){
  WIZARD_STEP=step;
  document.querySelectorAll("[data-step]").forEach(n=>n.hidden=Number(n.dataset.step)!==step);
  document.querySelectorAll("#wizardSteps>li").forEach((n,i)=>{if(i===step)n.setAttribute("aria-current","step");else n.removeAttribute("aria-current");});
  $("stepBack").hidden=step===0;$("stepNext").hidden=step===3;$("btnStart").hidden=step!==3;
  $("stepCounter").textContent="第 "+(step+1)+" 步，共 4 步";
  if(step===3){renderReview();confirmConfig();}
  if(focus) document.querySelector('[data-step="'+step+'"] input, [data-step="'+step+'"] select, [data-step="'+step+'"] textarea')?.focus();
}
function fieldError(id,message){$(id+"_error").textContent=message;$(id).setAttribute("aria-invalid",message?"true":"false");return !message;}
function validateStep(step){
  const ids=step===0?["f_project"]:step===1?["f_obj","f_ac"]:step===2?["f_paths","f_gate"]:["f_sub"];
  let first=null;
  for(const id of ids){let error=$(id).value.trim()?"":"请填写此项。";
    if(id==="f_project" && !PROJECTS.some(p=>String(p.id)===$(id).value)) error="请选择一个可用的本地项目。";
    if(id==="f_sub" && !["1","2"].includes($(id).value)) error="当前仅支持 1 或 2 个独立子任务。";
    if(!fieldError(id,error) && !first) first=$(id);
  }
  first?.focus();return !first;
}
function renderReview(){
  const box=$("formReview");box.replaceChildren();
  for(const [label,value,step] of [["项目",PROJECTS.find(p=>String(p.id)===$("f_project").value)?.name || "未选择",0],["目标与验收",$("f_obj").value+"\n"+$("f_ac").value,1],["范围与 Gate","允许：\n"+$("f_paths").value+"\n禁止：\n.git/**\n"+$("f_forbidden").value+"\nGate：\n"+$("f_gate").value,2]]){
    const row=el("div",null,"review-row"),body=el("div",null,"grow"),edit=el("button","编辑");edit.type="button";edit.onclick=()=>showStep(step);body.append(el("span",label,"subtle"),el("p",value));row.append(body,edit);box.append(row);
  }
  box.append(el("p","执行后端：Codex App Server · 来源："+text(SOURCE?.path || "尚未确认")+" · "+text(SOURCE?.file_count ?? "unknown")+" 个文件"));
  const values=FORM_CONFIG?.values;
  if(LIVE?.launch_blocked) box.append(el("p",LIVE.launch_blocked,"notice warning"));
  if(LIVE?.running || LIVE?.preparing) box.append(el("p","当前已有任务运行，不能同时启动另一任务。表单输入会保留。","notice warning"));
  box.append(el("p","Worker："+text(values?.worker?.model || "unknown")+"；Planner / Auditor / Verifier："+["planner","auditor","verifier"].map(r=>text(values?.roles?.[r]?.model || "unknown")).join(" / ")+"。可在下方调整本次参数。","notice"));
}
function openNew(){
  initializeParameters();
  showDialog("newMission");showStep(WIZARD_STEP);if(!PROJECTS.length) loadProjects();else if(!SOURCE && $("f_project").value) loadSource();
}
$("btnNew").onclick=openNew;document.querySelectorAll("[data-new]").forEach(b=>b.onclick=openNew);
$("f_sub").onchange=()=>{$("f_sub").dataset.dirty="1";FORM_CONFIG=null;CONFIG_VERSION++;confirmConfig();};
$("stepBack").onclick=()=>showStep(Math.max(0,WIZARD_STEP-1));
$("stepNext").onclick=()=>{if(validateStep(WIZARD_STEP)) showStep(Math.min(3,WIZARD_STEP+1));};
$("missionForm").onsubmit=e=>{e.preventDefault();if(WIZARD_STEP<3) $("stepNext").click();else $("btnStart").click();};
for(const [id,key] of [["btnStart","mission"],["btnStop","stop"],["btnCfg","config"],["btnConfigAll","config"],["btnSend","directive"]]) $(id).dataset.writeKey=key;
$("btnStop").onclick=()=>writeAction("stop","/api/stop",{mission_id:DETAIL_ID},()=>toast("取消请求已持久接收；正在确认停止，详见任务记录"));
const CONFIG_INPUTS={k_poll:"poll_seconds",k_idle:"idle_audit_cooldown_seconds",k_block:"blocked_escalation_seconds",k_grace:"l0_nudge_grace_seconds"};
for(const id of Object.keys(CONFIG_INPUTS)) $(id).oninput=()=>{$(id).dataset.dirty="1";};
$("btnCfg").onclick=()=>{
  const values={};
  for(const [id,key] of Object.entries(CONFIG_INPUTS)){
    const input=$(id), value=Number(input.value);
    if(!input.value || !Number.isFinite(value) || value<=0 || value>604800){input.setAttribute("aria-invalid","true");uiError("config","请填写大于 0 且不超过 604800 的秒数，允许小数。");input.focus();return;}
    input.removeAttribute("aria-invalid");values[key]=value;
  }
  writeAction("config","/api/config",values,()=>{Object.keys(CONFIG_INPUTS).forEach(id=>delete $(id).dataset.dirty);toast("新任务默认参数已保存；当前任务配置不变");});
};
$("configJson").oninput=()=>{$("configJson").dataset.dirty="1";};
$("btnConfigAll").onclick=()=>{
  try{const values=JSON.parse($("configJson").value);writeAction("config","/api/config",values,()=>{delete $("configJson").dataset.dirty;toast("新任务默认配置已保存；当前任务保持冻结配置");});}
  catch(error){uiError("config",error.message);}
};
$("btnStart").onclick=()=>{
  for(let step=0;step<4;step++) if(!validateStep(step)){showStep(step);validateStep(step);return;}
  if(!SOURCE || SOURCE.project_id!==$("f_project").value || !$("sourceConfirmed").checked){$("sourceConfirmError").textContent="请先读取并确认本次来源摘要。";return;}
  $("sourceConfirmError").textContent="";
  if(!FORM_CONFIG){$("missionParametersError").textContent="请等待配置核对完成，或修正参数后重试。";confirmConfig();return;}
  $("formSubmitStatus").textContent="正在准备任务与隔离工作区…";
  writeAction("mission","/api/mission",{config_snapshot:FORM_CONFIG,forbidden_paths:$("f_forbidden").value,source_revision:SOURCE.revision,project_id:$("f_project").value,objective:$("f_obj").value,acceptance_criteria:$("f_ac").value,allowed_paths:$("f_paths").value,gate_commands:$("f_gate").value,max_subtasks:Number($("f_sub").value),user_instruction:$("f_instr").value},d=>{
    toast("任务已启动");closeDialog("newMission");FORM_BASE=null;FORM_CONFIG=null;CONFIG_VERSION++;$("missionParameters").replaceChildren();delete $("f_sub").dataset.dirty;SOURCE=null;$("sourceConfirmed").checked=false;openTask(d.mission_id);
  });
};
$("btnSend").onclick=()=>{
  syncButtons();if($("btnSend").disabled || DETAIL_ID!==DIRECTIVE_MISSION) return;
  const mid=DETAIL_ID, draft=rememberDirective(), target=draft.target, message=draft.text.trim();if(!message) return;
  const version=draft.version;
  if(!draft.request) draft.request={command_id:"CMD-"+crypto.randomUUID()};
  const sent=draft.request;
  writeAction("directive","/api/directive",{mission_id:mid,target,text:message,command_id:sent.command_id},d=>{
    if(DIRECTIVE_MISSION===mid) rememberDirective();
    if(draft.request===sent) draft.request=null;
    draft.receipt=d.directive;
    if(draft.version===version){draft.text="";if(DIRECTIVE_MISSION===mid) $("d_text").value="";}
    if(DETAIL_ID===mid && LAST?.mission?.id===mid){renderTaskDetail();toast("指令已持久接收；消费结果见回执");}
  });
};
$("d_text").addEventListener("keydown",e=>{if(e.key==="Enter") $("btnSend").click();});
function submitAttempt(target){return writeAction("mission","/api/new-attempt",target,d=>{toast("已创建新的执行记录");if($("retryMission").open) closeDialog("retryMission");openTask(d.mission_id);});}
let RETRY_TARGET=null;
function newAttempt(mid){
  const target={mission_id:mid};RETRY_TARGET=target;
  showDialog("retryMission");$("retrySource").textContent="正在读取目标任务的项目…";$("confirmRetry").dataset.blocked="1";$("confirmRetry").disabled=true;
  $("retryError").textContent="";$("confirmRetry").onclick=null;
  return writeAction("retry-source:"+mid,"/api/projects/source",{mission_id:mid},d=>{
    if(RETRY_TARGET!==target || !$("retryMission").open) return;
    if(d.mission_id!==mid) throw new Error("历史任务关联不一致");
    const source=d.source;
    Object.assign(target,{project_id:d.project_id,execution_backend:d.execution_backend,source_revision:source?.revision});
    $("retrySource").textContent="任务："+mid+"\n项目："+d.project_id+"\n位置："+(d.project_path || "历史未提供")+"\n后端："+d.execution_backend+(source?"\n"+source.file_count+" 个文件\n\n纳入：\n"+source.files.map(f=>f.path).join("\n")+"\n\n排除：\n"+source.excluded.map(f=>f.path+" · "+f.reason).join("\n"):"\n使用旧 AO 执行路径，启动时仍需核对其前置条件。");
    $("confirmRetry").dataset.blocked="0";$("confirmRetry").disabled=false;$("confirmRetry").onclick=()=>submitAttempt(target);
  });
}
$("confirmRetry").dataset.writeKey="mission";$("closeRetry").onclick=()=>closeDialog("retryMission");
function resume(mid){return writeAction("mission","/api/resume",{mission_id:mid},()=>{toast("检查通过，已恢复 "+mid);openTask(mid);});}
function attach(mid){return writeAction("mission","/api/attach",{mission_id:mid},()=>{toast("已加载 "+mid);DETAIL_ID=mid;renderTaskDetail();});}

/* ---------------- theme and ordered live feed ---------------- */
const SYSTEM_THEME=matchMedia("(prefers-color-scheme: dark)");let THEME="light";
try{THEME=localStorage.getItem("clao.theme") || "light";}catch{/* restricted storage: keep a usable theme */}
function applyTheme(value,persist=true){
  THEME=["light","dark","system"].includes(value)?value:"light";
  document.documentElement.dataset.theme=THEME==="system"?(SYSTEM_THEME.matches?"dark":"light"):THEME;
  document.querySelectorAll("[data-theme]").forEach(b=>{if(b.tagName==="BUTTON") b.setAttribute("aria-pressed",String(b.dataset.theme===THEME));});
  if(persist) try{localStorage.setItem("clao.theme",THEME);}catch{uiError("主题","浏览器未允许保存外观偏好，本次选择仅在当前页面有效。");}
}
document.querySelectorAll("button[data-theme]").forEach(b=>b.onclick=()=>applyTheme(b.dataset.theme));
SYSTEM_THEME.addEventListener("change",()=>{if(THEME==="system") applyTheme(THEME,false);});applyTheme(THEME,false);
function disconnect(){
  if(CONNECTED || DISCONNECTED_MONO===null) DISCONNECTED_MONO=performance.now();
  CONNECTED=false;renderPhases();if(LAST) renderWorkbench(LIVE || LAST);
}
function connect(){
  const stream=new EventSource("/api/stream");
  stream.onmessage=event=>{try{acceptSnapshot(JSON.parse(event.data));uiError("状态连接",null);}catch(error){uiError("状态连接",error.message);}};
  stream.onerror=()=>{disconnect();stream.close();setTimeout(connect,4000);};
}
const savedRoute=location.hash.slice(1).split("/");
if(["overview","tasks","models","settings"].includes(savedRoute[0])){if(savedRoute[0]==="tasks" && savedRoute[1]){try{DETAIL_ID=decodeURIComponent(savedRoute[1]);}catch{/* invalid URL is never a write */}}navigate(savedRoute[0]);}
connect();loadProjects();
setInterval(()=>{if(LAST && CONNECTED) renderPhases();},1000);
setInterval(()=>{if(VIEW==="tasks" && (ACTIVE_TAB==="mem"||ACTIVE_TAB==="proj")) loadFile(ACTIVE_TAB==="mem"?"memory.md":"project.md");},10000);
