import { useCallback, useState } from "react";
import { AgentModelPicker } from "./AgentModelPicker";
import { RequiredAgentField } from "./CreateProjectAgentSheet";
import { useAgentReadinessQuery } from "../hooks/useAgentReadinessQuery";
import type { AcceptanceFields, RoleChoice, RoleChoices } from "./CLAOAcceptance";

const labels = { auditor: "Auditor · 异常诊断", planner: "Planner · 规划决策", verifier: "Verifier · 最终复核" };
function RoleRow({ role, value, worker, projectId, onChange }: { role: keyof RoleChoices; value?: RoleChoice; worker?: RoleChoice; projectId: string; onChange: (v?: RoleChoice) => void }) {
 const agents = useAgentReadinessQuery();
 const [warning,setWarning] = useState<string>();
 const onModeChange = useCallback(() => setWarning("此模式通道尚无可确认的只读语义能力；请选择支持的 Chat 执行器"), []);
 return <div className="space-y-2 rounded-md border border-border p-3" data-testid={`clao-role-${role}`}>
  <div className="flex flex-wrap items-center justify-between gap-2"><strong>{labels[role]}</strong><label className="flex items-center gap-2"><input type="checkbox" checked={!value} onChange={e=>onChange(e.target.checked ? undefined : { agent: worker?.agent || "", model: worker?.model || "" })} />沿用 Worker 选择</label></div>
  {!value ? <p>{worker?.agent || "先选择 Worker"} · {worker?.model || "执行器默认"}</p> : <div className="grid grid-cols-2 gap-3">
   <RequiredAgentField id={`clao-agent-${role}`} label={`${role} 执行器`} placeholder="选择执行器" agents={agents.data?.agents} value={value.agent} onChange={agent=>onChange({ agent, model:"" })} />
   <div className="min-w-0"><span className="block pb-1 text-sm">模型</span><AgentModelPicker agentId={value.agent} agentLabel={agents.data?.agents.find(a=>a.id===value.agent)?.label || value.agent} projectId={projectId} value={value.model} mode="" onModelChange={model=>onChange({...value,model})} onModeChange={onModeChange} onWarningChange={setWarning} /></div>
  </div>}
  {warning && <p role="status" className="break-words text-destructive">{warning}</p>}
 </div>;
}
export function CLAORoleForm({ fields, onChange, projectId, worker }: { fields: AcceptanceFields; onChange: (f: AcceptanceFields) => void; projectId: string; worker?: RoleChoice }) {
 return <details className="mx-4 mb-3 text-sm"><summary className="cursor-pointer py-2">角色与决策预算</summary>
  <div className="space-y-3"><p>独立只读会话；正常通过不调用 Auditor / Planner。账号使用执行器原生连接。</p>
   {(Object.keys(labels) as (keyof RoleChoices)[]).map(role=><RoleRow key={role} role={role} value={fields.roles?.[role]} worker={worker} projectId={projectId} onChange={v=>{const roles={...fields.roles};if(v)roles[role]=v;else delete roles[role];onChange({...fields,roles});}} />)}
   <label className="block">其中最多替换 Worker 次数<input aria-label="最多替换 Worker 次数" type="number" min={0} max={fields.repairs} step={1} value={fields.replans ?? 0} onChange={e=>onChange({...fields,replans:e.target.valueAsNumber})} className="ml-2 w-16 rounded border border-border bg-background p-1" /></label>
   <p>局部修复和替换共用上述修复预算；替换先确认旧 Worker 停止，保留旧会话，从冻结来源重新执行。</p>
  </div>
 </details>;
}
