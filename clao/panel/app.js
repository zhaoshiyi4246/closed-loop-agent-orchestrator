
let LAST = null, ACTIVE_TAB = "ev", PROJECTS = [];
const PREVIEW = new URLSearchParams(location.search).has("preview");
let VIEW="overview", DETAIL_ID=null, WIZARD_STEP=0, PROJECT_ERROR="";
const $ = id => document.getElementById(id);
const PANEL_NONCE = document.currentScript.nonce;
const PENDING = new Set(), UI_ERRORS = new Map();
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
function uiError(source,error){
  if(error) UI_ERRORS.set(source,text(error)); else UI_ERRORS.delete(source);
  $("clientErrors").textContent=[...UI_ERRORS].map(([key,value])=>key+"："+value).join("\n");
  $("clientErrors").hidden=UI_ERRORS.size===0;
  if(source==="mission") $("formSubmitError").textContent=error?text(error):"";
  if(source==="config") $("settingsError").textContent=error?text(error):"";
}
function syncButtons(){
  document.querySelectorAll("[data-write-key]").forEach(b=>b.disabled=PENDING.has(b.dataset.writeKey) || b.dataset.blocked==="1");
  $("btnStop").disabled=PENDING.has("stop") || !LAST?.running || !!LAST?.mission?.stop_request;
  $("btnSend").disabled=PENDING.has("directive") || !LAST?.running || !!LAST?.mission?.stop_request || !!LAST?.mission?.inspection_only;
  $("btnStart").disabled=PENDING.has("mission") || $("f_project").disabled || !PROJECTS.length || !$("f_project").value || !!LAST?.running;
}
async function writeAction(key,path,body,success){
  if(PREVIEW){uiError(key,"样例预览不会发送写请求。返回真实工作台后才能操作。");return;}
  if(PENDING.has(key)) return;
  PENDING.add(key); syncButtons();
  const requestStarted=performance.now();
  try{
    const response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-Panel-Nonce":PANEL_NONCE},body:JSON.stringify(body)});
    const data=await response.json();
    REQUEST_TIMING={key, round_trip_seconds:(performance.now()-requestStarted)/1000, ...data.request_timing};
    renderTiming();
    if(!response.ok || !data.ok) throw new Error(data.error || "请求失败（HTTP "+response.status+"）");
    uiError(key,null); if(success) success(data);
  }catch(error){ uiError(key,error.message); toast(error.message); }
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
  if(PREVIEW){target.textContent="样例预览：这里展示运行投影；未读取真实任务文件。";return;}
  try{
    const response=await fetch("/api/file?name="+encodeURIComponent(name));
    const data=await response.json();
    if(!response.ok || !data.ok) throw new Error(data.error || "文件读取失败");
    target.textContent=data.content; uiError(name,null);
  }catch(error){ target.textContent=error.message; uiError(name,error.message); }
}

/* ---------------- render: dynamic values are text, never markup ---------------- */
function drawGate(query){
  const box=$("evidence"); box.replaceChildren();
  const labels={not_run:"Gate 尚未运行",no_records:"没有 Gate 记录；不能推断执行结果",read_error:"Gate 读取失败",ok:"Gate 记录"};
  box.append(el("div",labels[query?.status] || "Gate 状态 unknown"));
  if(query?.error) box.append(el("pre",query.error,"diagnostic"));
  if(query?.reason) box.append(el("div",query.reason));
  const phases={task:"Task Gate",baseline:"baseline Gate",final:"Final Gate",unknown:"阶段 unknown"};
  for(const run of query?.records || []){
    const row=el("div",null,"ev");
    row.append(el("b",(phases[run.phase] || "阶段 unknown")+" · "+text(run.task_id)));
    if(run.historical_fields_missing) row.append(el("div","历史字段未提供；unknown"));
    row.append(el("pre",run.command || "（命令未执行）","diagnostic"));
    row.append(el("div","command="+text(run.command_result)+" · exit="+(run.exit_code==null?"未执行":text(run.exit_code))+" · command batch="+text(run.command_status)));
    row.append(el("div","repository integrity="+text(run.integrity?.status)+" · scope="+text(run.scope?.status)));
    const overall=el("strong","overall="+text(run.overall));
    overall.style.color=run.overall==="pass"?"var(--green)":run.overall==="fail"?"var(--red)":"var(--amber)";
    row.append(overall);
    if(run.output) for(const [stream,meta] of Object.entries(run.output)){
      if(meta?.truncated) row.append(el("pre",stream+" 已截断：original="+text(meta.original_length)+" chars · limit="+text(meta.limit_chars)+" · SHA-256="+text(meta.sha256),"diagnostic"));
    }
    for(const [label,reason] of [["integrity",run.integrity?.reason],["scope",run.scope?.reason]]){
      if(reason) row.append(el("pre",label+"："+text(reason),"diagnostic"));
    }
    if(run.output?.error_category) row.append(el("div","command error="+text(run.output.error_category)+" · timeout="+text(run.output.timeout_seconds)+"s"));
    if(run.stdout || run.stderr){
      const details=el("details"); details.open=run.overall==="fail";
      details.append(el("summary","stdout / stderr"));
      details.append(el("pre",text(run.stdout)+"\n"+text(run.stderr),"diagnostic")); row.append(details);
    }
    box.append(row);
  }
}
let STREAM_EPOCH=null, STREAM_SEQ=-1, CONNECTED=false, RECEIVED_MONO=null, DISCONNECTED_MONO=null, REQUEST_TIMING=null;
const OLD_EPOCHS=new Set();
function acceptSnapshot(s){
  const stream=s.stream;
  if(stream){
    if(OLD_EPOCHS.has(stream.epoch)) return false;
    if(STREAM_EPOCH===stream.epoch && stream.sequence<=STREAM_SEQ) return false;
    if(STREAM_EPOCH && STREAM_EPOCH!==stream.epoch) OLD_EPOCHS.add(STREAM_EPOCH);
    STREAM_EPOCH=stream.epoch; STREAM_SEQ=stream.sequence;
  }
  RECEIVED_MONO=performance.now(); DISCONNECTED_MONO=null; CONNECTED=true; render(s); return true;
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
      role+"：请求="+text(p.requested_model ?? "unknown")+" · 传入="+text(p.passed_model ?? "unknown")+(role==="worker"?" · 模型确认见下方 AO Session 事实":" · 外部确认="+text(p.confirmed_model ?? "unknown"))+" · transport="+text(p.transport ?? "unknown")+" · attempt="+text(p.attempt)+" · 调用耗时="+seconds(elapsed(p))+" · usage="+text(p.usage ?? "unknown")+" · cost="+text(p.cost ?? "unknown");
  }).join("\n") + (query?.workers || []).map(w=>{
    // Old R01 records confirmed only a reroute; never relabel it as spawn model.
    const legacy=w.model_evidence==="AO conversation.modelReroute.toModel (conversation-level, not per-call timing)";
    const reroute=w.model_reroute ?? (legacy?{to_model:w.confirmed_model,source:w.model_evidence}:null);
    return "\nWorker "+text(w.session_id)+" · AO activity="+text(w.activity ?? "unknown")+
      " · 请求="+text(w.requested_model ?? "unknown")+" · 传入="+text(w.passed_model ?? "unknown")+
      " · AO spawn-resolved="+text(w.spawn_resolved_model ?? "unknown")+"（创建时解析） · 来源="+text(w.spawn_model_evidence ?? "Session model 未提供/unknown")+
      " · conversation reroute="+(reroute?text(reroute.from_model ?? "unknown")+" → "+text(reroute.to_model ?? "unknown")+" · 来源="+text(reroute.source):"未提供/unknown")+
      "（会话后续模型变更） · 本次观察到该 activity 持续="+seconds(w.activity_elapsed_seconds)+"（非模型请求耗时） · 单次 provider 请求模型/耗时 unknown · usage="+text(w.usage ?? "unknown")+" · cost="+text(w.cost ?? "unknown");
  }).join("");
  renderTiming();
  renderFriendlyPhase();
}
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
  renderPhases();
  const subs=s.subtasks || [];
  region("subtasks",subs,tasks=>{
  for(const task of subs){
    const card=el("div",null,"subtask");
    card.append(statusBadge(task),el("div",task.objective,"obj"));
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
  const selector=$("d_target"), selected=selector.value;
  const workerKeys=JSON.stringify(workers.map(t=>t.worker_session_id));
  if(selector.dataset.workers!==workerKeys){
    selector.dataset.workers=workerKeys;
    selector.querySelectorAll("option[data-w]").forEach(node=>node.remove());
    workers.forEach((task,i)=>{
    const id=text(task.worker_session_id), option=el("option",`Worker ${i+1} (${id})（同步 Planner）`);
    option.value="worker:"+id; option.dataset.w="1"; selector.append(option);
    });
    selector.value=selected; if(!selector.value) selector.value="planner";
  }
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
  $("d_hint").textContent=m?"":"（先启动或查看一个任务）";
  renderWorkbench(s);
  syncButtons();
}

/* ---------------- workbench: the same components for live facts and fixtures ---------------- */
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
function stateInfo(m){
  if(!m) return ["尚无任务","neutral"];
  if(m.cancellation?.status==="unknown" || m.worker_stop?.status==="UNKNOWN" && m.stop_request && m.state!=="CANCELLING") return ["停止尚未确认","wait"];
  const current=(m.id || m.mission_id)===LAST?.mission?.id, phase=latestPhase();
  if(current && LAST?.running && phase?.status==="running" && !TERMINAL.has(m.state) && m.state!=="CANCELLING"){
    if(phase.phase==="approval_wait") return ["等待审批","wait"];
    if(m.state==="MISSION_READY" && !["preflight","preparation","spawn"].includes(phase.phase)) return ["进行中","active"];
  }
  const labels={MISSION_DONE:["已完成","good"],DONE:["已完成","good"],FAILED:["执行失败","bad"],HUMAN:["需要人工处理","wait"],CANCELLING:["取消中","wait"],CANCELLED:["已取消","neutral"],MISSION_READY:["准备执行","active"],preflight:["准备与检查","active"],RUNNING:["进行中","active"],WORKER_RUNNING:["正在执行","active"],WORKER_RETRYING:["准备重试","wait"],TASK_READY:["等待执行","neutral"],GATE_PENDING:["等待验收","active"],AUDIT_PENDING:["等待审计","active"],LOCAL_FIX_PENDING:["等待局部修复","active"],REPLAN_PENDING:["等待重规划","active"],PLANNER_PENDING:["等待规划","active"],VERIFIER_PENDING:["等待复核","active"]};
  return Object.hasOwn(labels,m.state)?labels[m.state]:["状态未知","wait"];
}
function statusBadge(m){const [label,tone]=stateInfo(m);return el("span",label,"status "+tone);}
function putStatus(id,m){const [label,tone]=stateInfo(m);$(id).textContent=label;$(id).className="status "+tone;}
function phaseLabel(p){return Object.hasOwn(PHASE_NAMES,p?.phase)?PHASE_NAMES[p.phase]:(p?.phase?"执行阶段（详见高级记录）":"阶段尚未提供");}
function latestPhase(){const rows=LAST?.phases?.records || [];return rows.find(p=>p.status==="running") || rows[0];}
function friendlyElapsed(p){
  if(p?.elapsed_seconds==null) return "耗时未知";
  const delta=!PREVIEW && p.status==="running" && RECEIVED_MONO!=null?Math.max(0,((CONNECTED?performance.now():(DISCONNECTED_MONO ?? RECEIVED_MONO))-RECEIVED_MONO)/1000):0;
  return "已记录 "+Math.floor(p.elapsed_seconds+delta)+" 秒";
}
function renderFriendlyPhase(){
  const p=latestPhase();
  $("connectionStatus").textContent=PREVIEW?"样例 · "+(CONNECTED?"非实时数据":"模拟断连"):CONNECTED?"状态已连接":"连接中断 · 保留记录";
  $("connectionStatus").classList.toggle("offline",!CONNECTED);
  if(DETAIL_ID===LAST?.mission?.id) $("friendlyPhase").textContent=p?phaseLabel(p)+" · "+friendlyElapsed(p)+(p.attempt!=null?" · 第 "+text(p.attempt)+" 次尝试":"")+(p.reason?"\n"+text(p.reason):""):"尚无阶段记录，耗时未知。";
}
function empty(title,description){const n=el("div",null,"empty");n.append(el("h3",title),el("p",description));return n;}
function navigate(view,focus=false){
  if(!["overview","tasks","models","settings"].includes(view)) return;
  VIEW=view;
  document.querySelectorAll(".view").forEach(n=>n.hidden=n.id!=="view-"+view);
  document.querySelectorAll("[data-view]").forEach(n=>{if(n.dataset.view===view)n.setAttribute("aria-current","page");else n.removeAttribute("aria-current");});
  $("locationName").textContent=({overview:"概览",tasks:"任务",models:"模型",settings:"设置"})[view];
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
function openTask(mid){
  DETAIL_ID=mid;navigate("tasks");renderTaskDetail();$("detailTitle").focus();
}
function taskRows(){
  const rows=[...(LAST?.missions || [])];
  if(LAST?.mission){
    const current=rows.findIndex(r=>r.mission_id===LAST.mission.id), fact={mission_id:LAST.mission.id,...LAST.mission};
    if(current===-1) rows.unshift(fact);else rows[current]={...rows[current],...fact};
  }
  return rows;
}
function renderTaskList(){
  const filter=$("taskFilter").value;
  region("missionsList",[taskRows(),filter,LAST?.running],box=>{
    const rows=taskRows().filter(r=>filter==="all" || filter==="active" && !TERMINAL.has(r.state) || filter==="needs" && ["HUMAN","FAILED","CANCELLING"].includes(r.state) || filter==="done" && ["MISSION_DONE","CANCELLED"].includes(r.state));
    for(const item of rows){
      const row=el("div",null,"mrow");row.dataset.missionId=item.mission_id;
      const body=el("div",null,"grow"), title=el("button",null,"link-row");
      title.append(el("h3",item.objective || "目标未提供"),icon("chevron-right"));title.onclick=()=>openTask(item.mission_id);
      body.append(title,statusBadge(item));
      if(item.error) body.append(el("pre","读取失败："+text(item.error),"diagnostic"));
      const actions=el("div",null,"row-actions");
      const view=el("button","查看");view.onclick=()=>openTask(item.mission_id);actions.append(view);
      row.append(icon("list-checks","green"),body,actions);box.append(row);
    }
    if(!rows.length) box.append(empty("这里还没有任务记录",filter==="all"?"新建一个任务，写清目标与验收条件。":"换一个状态筛选，查看其他记录。"));
  });
}
function nextStep(m){
  if(m?.worker_stop?.status==="UNKNOWN" || m?.cancellation?.status==="unknown") return "请在 AO 核对 Session 状态；停止未确认前不整理或合并成果。";
  if(m?.state==="CANCELLING") return "请求已收到。等待外部停止确认，接收请求不等于已经停止。";
  if(m?.state==="CANCELLED") return "查看保留的记录；如需重新执行，可创建关联的新 attempt。";
  if(m?.state==="MISSION_DONE") return "查看验收证据与隔离目录中的成果，自行决定后续交付。";
  if(["HUMAN","FAILED"].includes(m?.state)) return "先阅读失败原因与证据，处理阻塞后再决定下一步。";
  if(m?.inspection_only) return "当前仅查看存档。恢复前需通过已有材料检查。";
  return "可继续观察，或通过补充指令说明约束。";
}
function renderTaskDetail(){
  $("taskListArea").hidden=!!DETAIL_ID;$("taskDetail").hidden=!DETAIL_ID;
  if(!DETAIL_ID) return;
  const loaded=DETAIL_ID===LAST?.mission?.id;
  const m=loaded?LAST.mission:taskRows().find(r=>r.mission_id===DETAIL_ID);
  $("detailTitle").textContent=m?.objective || "任务目标未提供";putStatus("detailState",m);
  $("detailReason").textContent=m?.reason || (loaded?"此记录尚未提供原因。":"当前是任务摘要，加载存档后才能读取详细证据。");
  $("detailNext").textContent=nextStep(m);
  $("loadedDetail").hidden=!loaded;$("detailUnloaded").hidden=loaded;
  $("detailUnloaded").textContent=LAST?.running?"当前另有任务运行，暂不能切换存档。此处只显示已有摘要，不展示其他任务的证据。":"选择“加载存档”读取这个任务的证据。";
  $("btnStop").hidden=!loaded || !LAST?.running;
  // Leave the stable Stop button in place during status updates.
  region("detailExtraActions",[m?.state,loaded,LAST?.running,m?.inspection_only,m?.worker_stop,m?.cancellation],box=>{
    if(!loaded && !LAST?.running) box.append(actionButton("加载存档","mission",()=>attach(DETAIL_ID)));
    if(!LAST?.running && m){
      if(TERMINAL.has(m.state)){
        const next=actionButton("新 attempt","mission",()=>newAttempt(DETAIL_ID));
        if(m.worker_stop?.status==="UNKNOWN" || m.cancellation?.status==="unknown") {next.dataset.blocked="1";next.disabled=true;next.title="Worker 停止尚未确认，不能开始替代执行。";}
        box.append(next);
      }
      else box.append(actionButton("检查并恢复","mission",()=>resume(DETAIL_ID)));
    }
  });
  $("friendlyPhase").textContent=loaded?"阶段尚未提供":"存档尚未加载，耗时未知。";
  const p=loaded?latestPhase():null;
  // This is a stage key, never an invented percentage or a claim of completed checks.
  const phase=p?.phase || "", index=/preflight|prepare|spawn/.test(phase)?0:/gate/.test(phase)?2:/materializ|merge|verifier/.test(phase)?3:/worker|observ|approval|model_request|planner|auditor|retry/.test(phase)?1:-1;
  region("phaseRail",index,box=>["准备","执行与观察","验收","成果复核"].forEach((label,i)=>box.append(el("span",label,i===index?"reached":""))));
  const summary=LAST?.last_summary;
  $("resultLocation").textContent=summary?.runtime_dir?"运行目录："+text(summary.runtime_dir):"运行材料：runtime/"+text(LAST?.mission?.id)+"/ · integration 为隔离成果目录；是否交付以实际终局与证据为准。";
  region("receiptSummary",LAST?.directive_receipts,box=>{
    for(const receipt of (LAST?.directive_receipts?.records || []).slice(0,6)) box.append(el("p",text(receipt.target)+" · "+text(receipt.status)+" · "+text(receipt.reason)));
  });
  renderFriendlyPhase();syncButtons();
}
function renderReadiness(){
  region("readiness",[PROJECTS,PROJECT_ERROR,PREVIEW],box=>{
    box.append(el("p",PROJECT_ERROR?"项目读取需要处理":PROJECTS.length?"可以选择项目":"等待项目资料","ready-label"));
    const row=el("div",null,"list-row"), body=el("div",null,"grow");
    body.append(el("h3",PREVIEW?"示例 AO 项目":PROJECTS.length?"AO 项目列表已读取":"AO 项目列表"),el("p",PROJECT_ERROR || (PROJECTS.length?"新建任务时明确选择工作项目。":"可打开新建任务并重试读取；空列表不会补入样例。")));row.append(body);box.append(row);
    const check=el("div",null,"list-row");check.append(el("p","完整环境、工作树与来源提交在实际启动时检查。读取项目列表不代表全部就绪。"));box.append(check);
  });
}
function renderWorkbench(s){
  const m=s.mission;putStatus("overviewState",m);
  region("currentTask",[m,s.running,s.phases?.records?.[0]?.phase],box=>{
    if(!m){const card=empty("下一件事，从这里开始","选择项目，写清目标，让每一步都有可检查的结果。");card.prepend(icon("plus","blue"));box.append(card);return;}
    box.append(el("h3",m.objective || "目标未提供"),el("p",m.reason || "等待新的执行记录。","task-lead"));
    const meta=el("div",null,"current-meta");
    for(const [label,value] of [["当前阶段",phaseLabel(latestPhase())],["执行方式",m.inspection_only?"仅查看历史":s.running?"本地隔离执行":"查看已有结果"]]){const pair=el("div");pair.append(el("span",label),el("p",value));meta.append(pair);}
    const button=el("button","查看任务详情","primary");button.append(icon("arrow-right"));button.onclick=()=>openTask(m.id);box.append(meta,button);
  });
  region("attention",[m?.state,m?.reason,m?.worker_stop,s.alerts,s.panel_errors,s.read_errors,s.gate_query?.status,CONNECTED],box=>{
    const notes=[];
    if(!CONNECTED) notes.push(["状态连接已断开","保留最后一次已知状态。重连只读取状态，不会重新提交写操作。","warning"]);
    if(m && ["HUMAN","FAILED","CANCELLING"].includes(m.state)) notes.push([stateInfo(m)[0],m.reason || nextStep(m),m.state==="FAILED"?"error":"warning"]);
    for(const error of s.panel_errors || []) notes.push(["运行器错误",text(error),"error"]);
    for(const error of s.read_errors || []) notes.push([text(error.source)+" 读取失败",text(error.error),"error"]);
    for(const a of s.alerts || []) notes.push([a.summary || "需要检查的告警",[a.description,a.error,a.reason].filter(v=>v!=null).map(text).join("\n"),"warning"]);
    if(s.gate_query?.status==="read_error" && !(s.read_errors || []).some(e=>/gate/.test(e.source))) notes.push(["Gate 读取失败",s.gate_query.error || "读取结果未知，不能判断通过。","error"]);
    for(const [title,reason,tone] of notes){const note=el("div",null,"notice "+tone);note.append(el("strong",title),el("p",reason));box.append(note);}
    if(!notes.length) box.append(empty("暂无待处理事项",m?"现有记录没有新的告警；后续更新会显示在这里。":"任务运行后，需要你处理的事项会保留在这里。"));
  });
  region("recentResults",s.missions,box=>{
    const rows=(s.missions || []).filter(r=>TERMINAL.has(r.state)).slice(0,3);
    for(const r of rows){const row=el("div",null,"list-row"),button=el("button",null,"link-row");button.append(el("span",r.objective || "目标未提供"),statusBadge(r));button.onclick=()=>openTask(r.mission_id);row.append(button);box.append(row);}
    if(!rows.length) box.append(empty("还没有最近结果","完成、失败或取消的任务都会保留记录。"));
  });
  region("roleCards",s.default_config,box=>{
    const values=s.default_config?.values;
    for(const [role,description] of [["worker","在 AO 工作树执行任务"],["planner","理解目标，规划与给出受控指令"],["auditor","按现有触发条件进行只读审计"],["verifier","对最终成果与证据独立复核"]]){
      const row=el("div",null,"list-row"), body=el("div",null,"grow");body.append(el("h3",role==="worker"?"Worker · 执行角色":role[0].toUpperCase()+role.slice(1)+" · 语义角色"),el("p",description));
      row.append(icon(role==="worker"?"list-checks":"cpu",role==="worker"?"green":"purple"),body,el("div",(role==="worker"?values?.worker?.model:values?.roles?.[role]?.model) || "配置尚未提供","model-value"));box.append(row);
    }
  });
  renderReadiness();renderTaskList();renderTaskDetail();renderFriendlyPhase();
}

/* ---------------- navigation, dialogs and progressive form ---------------- */
$("detailActions").append(el("span",null,"button-row"));$("detailActions").lastChild.id="detailExtraActions";
document.querySelectorAll("[data-view],[data-go]").forEach(b=>b.onclick=()=>navigate(b.dataset.view || b.dataset.go,true));
$("backToTasks").onclick=()=>{DETAIL_ID=null;renderTaskDetail();$("tasksHeading").focus();};
$("taskFilter").onchange=renderTaskList;
const DIALOG_OPENERS=new Map();
function showDialog(id){const dialog=$(id);DIALOG_OPENERS.set(id,document.activeElement);if(!dialog.open) dialog.showModal();}
function closeDialog(id){$(id).close();}
for(const id of ["newMission","previewDialog"]) $(id).addEventListener("close",()=>{const opener=DIALOG_OPENERS.get(id);if(opener?.isConnected) opener.focus();});
$("closeMission").onclick=()=>closeDialog("newMission");$("closePreview").onclick=()=>closeDialog("previewDialog");
$("btnPreview").onclick=$("settingsPreview").onclick=()=>showDialog("previewDialog");
function showSelectedProject(){
  const selected=PROJECTS.find(p=>String(p.id)===$("f_project").value);
  $("f_project_meta").textContent=selected?"项目路径："+text(selected.path || "未提供")+" · 类型："+text(selected.kind || "未提供"):"尚未选择项目。";
  syncButtons();
}
async function loadProjects(){
  const selector=$("f_project"), selected=selector.value;
  selector.disabled=true;$("btnProjects").disabled=true;syncButtons();
  try{
    const d=PREVIEW?{ok:true,projects:[{id:"sample-project",name:"示例 · 数据工具",path:"示例项目 / data-tools",kind:"git"}]}:await (await fetch("/api/projects")).json();
    if(!d.ok) throw new Error(d.error || "AO Project API 请求失败");
    PROJECTS=d.projects || [];
    const prompt=el("option",PROJECTS.length?"请选择一个项目":"AO 中没有已注册项目");prompt.value="";selector.replaceChildren(prompt);
    PROJECTS.forEach(p=>{const option=el("option",p.name+" ("+p.id+")");option.value=String(p.id);selector.append(option);});
    selector.value=selected;if(!selector.value) selector.value="";selector.disabled=!PROJECTS.length;
    PROJECT_ERROR=PROJECTS.length?"":"AO 中没有已注册项目";
  }catch(error){PROJECTS=[];PROJECT_ERROR=error.message;const prompt=el("option","AO 项目加载失败");prompt.value="";selector.replaceChildren(prompt);}
  finally{$("f_project_error").textContent=PROJECT_ERROR;$("btnProjects").disabled=false;showSelectedProject();renderReadiness();}
}
$("f_project").onchange=()=>{$("f_project_error").textContent="";$("f_project").removeAttribute("aria-invalid");showSelectedProject();};
$("btnProjects").onclick=loadProjects;
function showStep(step,focus=true){
  WIZARD_STEP=step;
  document.querySelectorAll("[data-step]").forEach(n=>n.hidden=Number(n.dataset.step)!==step);
  document.querySelectorAll("#wizardSteps>li").forEach((n,i)=>{if(i===step)n.setAttribute("aria-current","step");else n.removeAttribute("aria-current");});
  $("stepBack").hidden=step===0;$("stepNext").hidden=step===3;$("btnStart").hidden=step!==3;
  $("stepCounter").textContent="第 "+(step+1)+" 步，共 4 步";
  if(step===3) renderReview();
  if(focus) document.querySelector('[data-step="'+step+'"] input, [data-step="'+step+'"] select, [data-step="'+step+'"] textarea')?.focus();
}
function fieldError(id,message){$(id+"_error").textContent=message;$(id).setAttribute("aria-invalid",message?"true":"false");return !message;}
function validateStep(step){
  const ids=step===0?["f_project"]:step===1?["f_obj","f_ac"]:step===2?["f_paths","f_gate"]:["f_sub"];
  let first=null;
  for(const id of ids){let error=$(id).value.trim()?"":"请填写此项。";
    if(id==="f_project" && !PROJECTS.some(p=>String(p.id)===$(id).value)) error="请选择一个可用的 AO 项目。";
    if(id==="f_sub" && !["1","2"].includes($(id).value)) error="当前仅支持 1 或 2 个独立子任务。";
    if(!fieldError(id,error) && !first) first=$(id);
  }
  first?.focus();return !first;
}
function renderReview(){
  const box=$("formReview");box.replaceChildren();
  for(const [label,value,step] of [["项目",PROJECTS.find(p=>String(p.id)===$("f_project").value)?.name || "未选择",0],["目标与验收",$("f_obj").value+"\n"+$("f_ac").value,1],["范围与 Gate",$("f_paths").value+"\n"+$("f_gate").value,2]]){
    const row=el("div",null,"review-row"),body=el("div",null,"grow"),edit=el("button","编辑");edit.type="button";edit.onclick=()=>showStep(step);body.append(el("span",label,"subtle"),el("p",value));row.append(body,edit);box.append(row);
  }
  const values=LAST?.default_config?.values;
  if(LAST?.running) box.append(el("p","当前已有任务运行，不能同时启动另一任务。表单输入会保留。","notice warning"));
  box.append(el("p","模型采用启动时的新任务默认值，并由后端冻结快照。当前可见 Worker："+text(values?.worker?.model || "unknown")+"；Planner / Auditor / Verifier："+["planner","auditor","verifier"].map(r=>text(values?.roles?.[r]?.model || "unknown")).join(" / ")+"。模型配置在设置的高级区域编辑。","notice"));
}
function openNew(){
  if(!$("f_sub").dataset.dirty) $("f_sub").value=String(LAST?.default_config?.values?.budgets?.max_subtasks ?? 1);
  showDialog("newMission");showStep(WIZARD_STEP);if(!PROJECTS.length) loadProjects();
}
$("btnNew").onclick=openNew;document.querySelectorAll("[data-new]").forEach(b=>b.onclick=openNew);
$("f_sub").onchange=()=>{$("f_sub").dataset.dirty="1";};
$("stepBack").onclick=()=>showStep(Math.max(0,WIZARD_STEP-1));
$("stepNext").onclick=()=>{if(validateStep(WIZARD_STEP)) showStep(Math.min(3,WIZARD_STEP+1));};
$("missionForm").onsubmit=e=>{e.preventDefault();if(WIZARD_STEP<3) $("stepNext").click();else $("btnStart").click();};
for(const [id,key] of [["btnStart","mission"],["btnStop","stop"],["btnCfg","config"],["btnConfigAll","config"],["btnSend","directive"]]) $(id).dataset.writeKey=key;
$("btnStop").onclick=()=>writeAction("stop","/api/stop",{},()=>toast("取消请求已持久接收；正在确认停止，详见任务记录"));
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
  writeAction("mission","/api/mission",{project_id:$("f_project").value,objective:$("f_obj").value,acceptance_criteria:$("f_ac").value,allowed_paths:$("f_paths").value,gate_commands:$("f_gate").value,max_subtasks:Number($("f_sub").value),user_instruction:$("f_instr").value},d=>{
    toast("已启动 "+d.mission_id);closeDialog("newMission");DETAIL_ID=d.mission_id;navigate("tasks");renderTaskDetail();
  });
};
$("btnSend").onclick=()=>{
  const target=$("d_target").value, message=$("d_text").value.trim();if(!message) return;
  const signature=target+"\n"+message;
  if(!window.directiveDraft || window.directiveDraft.signature!==signature) window.directiveDraft={signature,command_id:"CMD-"+crypto.randomUUID()};
  writeAction("directive","/api/directive",{target,text:message,command_id:window.directiveDraft.command_id},d=>{
    toast("指令已持久接收："+d.directive.command_id+"；消费结果见回执");window.directiveDraft=null;
    if($("d_text").value.trim()===message) $("d_text").value="";
  });
};
$("d_text").addEventListener("keydown",e=>{if(e.key==="Enter") $("btnSend").click();});
function newAttempt(mid){return writeAction("mission","/api/new-attempt",{mission_id:mid},d=>{toast("已创建关联 attempt "+d.mission_id);DETAIL_ID=d.mission_id;navigate("tasks");renderTaskDetail();});}
function resume(mid){return writeAction("mission","/api/resume",{mission_id:mid},()=>{toast("检查通过，已恢复 "+mid);DETAIL_ID=mid;renderTaskDetail();});}
function attach(mid){return writeAction("mission","/api/attach",{mission_id:mid},()=>{toast("已加载 "+mid);DETAIL_ID=mid;renderTaskDetail();});}

/* ---------------- theme, preview and ordered live feed ---------------- */
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
for(const [key,label] of Object.entries(PREVIEW_STATES)){
  const option=el("option",label);option.value=key;$("previewSelect").append(option);
  const link=el("a",label);link.href="/?preview="+key;link.append(icon("chevron-right"));$("previewOptions").append(link);
}
function choosePreview(name){
  const valid=Object.hasOwn(PREVIEW_STATES,name)?name:"empty";
  $("previewSelect").value=valid;DETAIL_ID=null;REGION_KEYS.clear();DEFERRED_REGIONS.clear();UI_ERRORS.clear();uiError("preview",null);
  RECEIVED_MONO=performance.now();DISCONNECTED_MONO=null;CONNECTED=valid!=="disconnected";
  if(!CONNECTED) DISCONNECTED_MONO=RECEIVED_MONO;
  render(previewSnapshot(valid));history.replaceState(null,"","/?preview="+valid);
}
$("previewSelect").onchange=()=>choosePreview($("previewSelect").value);
function disconnect(){
  if(CONNECTED || DISCONNECTED_MONO===null) DISCONNECTED_MONO=performance.now();
  CONNECTED=false;renderPhases();if(LAST) renderWorkbench(LAST);
}
function connect(){
  const stream=new EventSource("/api/stream");
  stream.onmessage=event=>{try{acceptSnapshot(JSON.parse(event.data));uiError("状态连接",null);}catch(error){uiError("状态连接",error.message);}};
  stream.onerror=()=>{disconnect();uiError("状态连接","连接中断，正在重连；保留最后一次已知状态");stream.close();setTimeout(connect,4000);};
}
if(PREVIEW){$("previewBanner").hidden=false;choosePreview(new URLSearchParams(location.search).get("preview"));loadProjects();}
else {connect();loadProjects();}
setInterval(()=>{if(LAST && CONNECTED && !PREVIEW) renderPhases();},1000);
setInterval(()=>{if(!PREVIEW && VIEW==="tasks" && (ACTIVE_TAB==="mem"||ACTIVE_TAB==="proj")) loadFile(ACTIVE_TAB==="mem"?"memory.md":"project.md");},10000);
