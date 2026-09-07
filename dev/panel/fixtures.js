/* Explicit UI examples, never a source of production state or Controller actions. */
const PREVIEW_STATES = Object.freeze({
  empty:"空记录", running:"正常运行", approval:"等待审批", success:"成功",
  failure:"失败", cancelling:"取消中", cancelled:"已取消",
  stop_unknown:"停止未知", disconnected:"断连", gate_read_error:"Gate read_error"
});
function previewSnapshot(name){
  const values={runner:{poll_seconds:5,cap_seconds:7200}, observer:{idle_audit_cooldown_seconds:120,blocked_escalation_seconds:600,l0_nudge_grace_seconds:120}, worker:{model:"gpt-5.6-sol"}, roles:{planner:{model:"gpt-5.6-sol"},auditor:{model:"gpt-5.6-sol"},verifier:{model:"gpt-5.6-sol"}}, gate:{timeout_seconds:300,output_limit_chars:20000},budgets:{max_subtasks:1,max_runtime_seconds:3600}};
  const snapshot={revision:"sample-only",values,sources:{},warnings:["样例配置，仅供界面预览，不代表本机设置。"]};
  const states={running:"RUNNING",approval:"RUNNING",success:"MISSION_DONE",failure:"FAILED",cancelling:"CANCELLING",cancelled:"CANCELLED",stop_unknown:"HUMAN",disconnected:"RUNNING",gate_read_error:"RUNNING"};
  const reasons={running:"正在为导入流程补充格式校验，随后运行约定的验收命令。",approval:"Worker 请求执行授权范围以外的命令。请在 AO 审批入口检查原始请求；CLAO 没有自动放行。",success:"确定性检查与最终复核通过，成果已保留在隔离的 integration 目录。",failure:"Final Gate 范围检查失败：发现对 config/private.json 的未授权修改。命令退出码为 0，整体结果仍为失败。",cancelling:"取消请求已持久接收，正在查询 Worker 是否确实停止。",cancelled:"本次执行已取消，Worker 停止事实已确认。不会继续合并成果。",stop_unknown:"取消请求已收到，但 AO 连接中断，无法确认 Worker 已停止。自动执行已暂停，不继续 materialization。",disconnected:"正在为导入流程补充格式校验。",gate_read_error:"正在等待验收结果。"};
  const m={id:"MISSION-SAMPLE-01",state:states[name] || "RUNNING",objective:"为数据导入增加格式校验与清晰的错误提示",reason:reasons[name] || "样例任务",source:{source_ref:"main",source_commit:"sample-source-not-a-real-commit"}};
  if(["cancelling","cancelled","stop_unknown"].includes(name)){
    m.stop_request={received_at:"2026-09-07T09:30:00Z",reason:"用户请求取消"};
    m.worker_stop={status:name==="cancelled"?"CONFIRMED":"UNKNOWN"};
    m.cancellation={status:name==="cancelled"?"cancelled":name==="stop_unknown"?"unknown":"cancelling",reason:m.reason};
  }
  const s={mission:m,running:["running","approval","cancelling","disconnected","gate_read_error"].includes(name),elapsed:84,missions:[{mission_id:m.id,objective:m.objective,state:m.state}],subtasks:[{task_id:"TASK-SAMPLE-01",objective:"校验输入格式，保留正常导入行为",state:name==="success"?"DONE":"WORKER_RUNNING",worker_session_id:"SESSION-SAMPLE-01",local_fixes:0,max_local_fixes:2,replans:0,max_replans:1}],panel_errors:[],read_errors:[],alerts:[],transitions:[],verifications:[],traffic:[],config:{poll_seconds:5,idle_audit_cooldown_seconds:120,blocked_escalation_seconds:600,l0_nudge_grace_seconds:120},default_config:snapshot,mission_config:{status:"ok",snapshot},config_fields:{},directive_receipts:{status:"ok",records:[]},gate_query:{status:"not_run",records:[]},phases:{status:"ok",records:[{sequence:1,mission_id:m.id,task_id:"TASK-SAMPLE-01",phase:({approval:"approval_wait",success:"verifier",failure:"final_gate",cancelling:"kill",cancelled:"kill",stop_unknown:"reconciliation",gate_read_error:"final_gate"})[name] || "worker_execution",status:["running","approval","cancelling","disconnected","gate_read_error"].includes(name)?"running":"completed",reason:m.reason,attempt:1,elapsed_seconds:32}],roles:{},workers:[{session_id:"SESSION-SAMPLE-01",requested_model:"gpt-5.6-sol",passed_model:"gpt-5.6-sol",spawn_resolved_model:"gpt-5.6-sol",spawn_model_evidence:"AO SessionView.model (sample)",activity:name==="cancelled"?"terminated":"working",usage:null,cost:null}]}};
  if(name==="success" || name==="failure"){
    const pass=name==="success";
    s.gate_query={status:"ok",records:[{phase:"final",task_id:"MISSION-SAMPLE-01",command:"python -m pytest tests -q",command_result:"pass",command_status:"pass",exit_code:0,integrity:{status:"pass"},scope:{status:pass?"pass":"fail",reason:pass?"修改位于已授权范围":"forbidden path: config/private.json"},overall:pass?"pass":"fail",stdout:"样例命令输出；不代表真实测试证据。"}]};
  }
  if(name==="approval") s.alerts=[{alert_type:"approval",summary:"需要人工检查命令授权",description:m.reason,error:"请求：python -m pytest tests -q && other-command"}];
  if(name==="failure") s.alerts=[{alert_type:"scope",summary:"最终范围检查未通过",error:m.reason}];
  if(name==="gate_read_error") {s.gate_query={status:"read_error",error:"SQLite database is locked",records:[]};s.read_errors=[{source:"gate_runs",error:"SQLite database is locked"}];}
  if(name==="empty" || !Object.hasOwn(PREVIEW_STATES,name)) Object.assign(s,{mission:null,running:false,elapsed:null,missions:[],subtasks:[],mission_config:{status:"no_mission"},gate_query:{status:"no_records",records:[]},phases:{status:"not_called",records:[],workers:[]}});
  return s;
}
