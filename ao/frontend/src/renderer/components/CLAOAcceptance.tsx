import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useNavigate } from "@tanstack/react-router";
import { useUiStore } from "../stores/ui-store";
import { getApiBaseUrl, hasTrustedApiBaseUrl } from "../lib/api-client";
import { CLAODirectives, type DirectiveReceipt } from "./CLAODirectives";
import { CLAOResults } from "./CLAOResults";
import { CLAORunView } from "./CLAORunView";
import { CLAOLocalProject } from "./CLAOLocalProject";
import { acceptanceFacts, factLabel, readableRunReason } from "./CLAOFacts";
import type { SourcePreview } from "./CLAOSource";

export type RoleChoice = { agent: string; model: string; connectionId?: string; connectionRevision?: number; connection?: {name:string;service:string;billing:string} };
export type RoleChoices = Partial<Record<"planner" | "auditor" | "verifier", RoleChoice>>;
export type AcceptanceFields = { criteria: string; allowed: string; forbidden: string; gates: string; repairs: number; timeout: number; replans?: number; roles?: RoleChoices; parentId?: string; maxTasks?: number; sourceRevision?: string; externalServiceConsent?: string[] };
export type AcceptanceRequest = {
	parentId?: string; maxTasks?: number; sourceRevision?: string; externalServiceConsent?: string[];
	id: string; projectId: string; objective: string; agent: string; model: string;
	criteria: { id: string; description: string }[]; allowedPaths: string[]; forbiddenPaths: string[];
	gateCommands: string[]; maxRepairs: number; gateTimeout: number; maxReplans?: number; roles?: RoleChoices;
};
type Evidence = { ok: boolean; scopeOK: boolean; readError?: string; paths: string[]; forbidden: string[]; outside: string[]; gate?: { command_ok: boolean; integrity_ok: boolean }; records?: unknown; verification?: { verdict: string; summary: string; ac_checks: { ac_id: string; verdict: string; note: string }[] }; resultHead?: string };
type RoleCall = { id: string; role: string; incidentId?: string; sessionId?: string; choice: RoleChoice & { accountRef?: string; inherited: boolean }; resolvedModel?: string; confirmedModel?: string; modelFactSource?: string; state: string; startedAt: string; finishedAt?: string; result?: { verdict?: string; diagnosis?: string; decision?: string; action?: string; reason?: string; evidence?: {summary: string;reference?:string}[] }; error?: string };
type Decision = { id: string; workerId: string; auditId: string; plannerId: string; action?: string; reason?: string; state: string; outcome?: string };
export type Mission = { activeWait?:string; source?: SourcePreview; sourcePath?: string; base?: string; subtasks?: Mission[]; coordinatorId?: string; directives?: DirectiveReceipt[]; checkpoint?: {stage:string; localState?:string}; recovery?: {canContinue:boolean;reason:string;stage?:string}; request: AcceptanceRequest; state: string; reason: string; revision: number; sessionId?: string; verifierSessionId?: string; workspace?: string; resultHead?: string; repairs: number; cancelRequested: boolean; evidence: Evidence[]; operations: {id:string;kind:string;target:string;state:string;reason?:string}[]; roles?: Record<string, RoleChoice & {inherited: boolean; accountRef?: string}>; roleCalls?: RoleCall[]; decisions?: Decision[]; replans?: number };
const terminal = new Set(["DONE", "FAILED", "CANCELLED", "UNKNOWN", "HUMAN"]);
const states: Record<string, string> = { PAUSED:"已暂停", RESUMING:"继续原任务", HUMAN: "需要处理", DIAGNOSING: "异常诊断", PLANNING: "规划决策", REPLANNING: "重新安排执行", SPAWNING: "准备中", RUNNING: "执行中", STOPPING: "确认停止", GATE: "验收中", REPAIRING: "修复中", MATERIALIZING: "固定结果", VERIFYING: "独立复核", DONE: "验收通过", FAILED: "验收未通过", CANCELLED: "已取消", UNKNOWN: "结果尚未确认" };
const lines = (value: string) => value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);

export async function request<T>(path: string, body?: unknown): Promise<T> {
	if (!hasTrustedApiBaseUrl()) throw new Error("开发版运行服务尚未就绪");
	const base = getApiBaseUrl();
	let headers: Record<string, string> = {};
	if (body !== undefined) {
		const session = await fetch(base + "/api/v1/clao/session", { cache: "no-store" });
		if (!session.ok) throw new Error("无法取得当前本地会话凭据");
		const { nonce } = await session.json();
		headers = { "Content-Type": "application/json", "X-CLAO-Nonce": nonce };
	}
	const response = await fetch(base + "/api/v1/clao" + path, { method: body === undefined ? "GET" : "POST", headers, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
	const data = await response.json();
	if (!response.ok) throw Object.assign(new Error(data.directive?.reason || data.message || data.error?.message || "闭环请求失败"), { status: response.status });
	return data as T;
}
export async function createAcceptance(id: string, fields: AcceptanceFields, input: { projectId: string; brief: string; agent?: string; model?: string; mode?: string; approvalMode?: string; attachments?: unknown[] }): Promise<Mission> {
	if (input.mode || input.approvalMode || input.attachments?.length) throw new Error("闭环使用原生 Chat 审批；本轮不接受终端降级、跳过审批或附件");
	const body: AcceptanceRequest = { id, parentId:fields.parentId, projectId: input.projectId, objective: input.brief, agent: input.agent || "", model: input.model || "", criteria: lines(fields.criteria).map((description, i) => ({ id: `AC${i + 1}`, description })), allowedPaths: lines(fields.allowed), forbiddenPaths: lines(fields.forbidden), gateCommands: lines(fields.gates), maxRepairs: fields.repairs, gateTimeout: fields.timeout, maxReplans: fields.replans ?? 0, roles: fields.roles, maxTasks: fields.maxTasks ?? 1, sourceRevision: fields.sourceRevision, externalServiceConsent: fields.externalServiceConsent };
	if (![body.maxRepairs,body.maxReplans ?? 0].every(Number.isInteger) || body.maxRepairs<0 || body.maxRepairs>3 || (body.maxReplans ?? 0)<0 || (body.maxReplans ?? 0)>body.maxRepairs || !Number.isFinite(body.gateTimeout) || body.gateTimeout<1 || body.gateTimeout>600) throw new Error("请填写合法的修复/替换次数与 Gate 超时");
	if (!body.sourceRevision) throw new Error("请读取并确认本次来源快照");
	if (![1,2].includes(body.maxTasks ?? 1)) throw new Error("仅支持单 Worker 或最多两个独立子任务");
	if (!body.criteria.length || !body.allowedPaths.length || !body.gateCommands.length) throw new Error("请填写验收条件、允许范围和 Gate");
	try {
		return (await request<{ mission: Mission }>("/missions", body)).mission;
	} catch (error) {
		// A lost POST response may still have a durable receipt. Observe the same
		// identity; never create a fresh attempt as a network retry.
		try {
			const { mission } = await request<{ mission: Mission }>("/missions/" + encodeURIComponent(id));
			return mission;
		} catch { throw error; }
	}
}
export function AcceptanceForm({ value, onChange }: { value: AcceptanceFields; onChange: (value: AcceptanceFields) => void }) {
	const field = (key: "criteria" | "allowed" | "forbidden" | "gates", label: string, placeholder: string) => <label className="flex min-w-0 flex-col gap-1 text-sm">{label}<textarea className="min-h-16 rounded-md border border-border bg-background p-2" aria-label={label} value={value[key]} placeholder={placeholder} onChange={e => onChange({ ...value, [key]: e.target.value })} /></label>;
	return <div className="grid max-h-72 grid-cols-1 sm:grid-cols-2 gap-3 overflow-y-auto px-4 py-3" data-testid="clao-acceptance-form">
		{field("criteria", "验收条件（每行一项）", "说明什么结果才算通过")}
		{field("gates", "检查命令（每行一条）", "使用项目真实的检查命令")}
		{field("allowed", "允许修改范围", "例如 src/**；请明确填写")}
		{field("forbidden", "禁止修改范围", "可留空")}
		<label className="sm:col-span-2 text-sm">执行安排<select aria-label="执行安排" value={value.maxTasks ?? 1} onChange={e=>onChange({...value,maxTasks:Number(e.target.value)})} className="ml-2 rounded border border-border bg-background p-2"><option value={1}>单任务（默认）</option><option value={2}>最多两个独立子任务</option></select></label>
		<label className="text-sm">最多修复次数<input aria-label="最多修复次数" type="number" min={0} max={3} step={1} value={value.repairs} onChange={e => onChange({ ...value, repairs: e.target.valueAsNumber })} className="ml-2 w-16 rounded border border-border bg-background p-1" /></label>
		<label className="text-sm">检查超时（秒）<input aria-label="检查超时（秒）" type="number" min={1} max={600} step="any" value={value.timeout} onChange={e => onChange({ ...value, timeout: e.target.valueAsNumber })} className="ml-2 w-20 rounded border border-border bg-background p-1" /></label>
	</div>;
}
export function CLAOAcceptance({ sessionId }: { sessionId: string }) {
	const query = useQuery({ queryKey: ["clao-missions"], queryFn: () => request<{ missions: Mission[] }>("/missions"), refetchInterval: 1500, retry: false });
	const candidates = query.data?.missions.flatMap(m=>[m,...(m.subtasks ?? [])]);
	const selected = candidates?.find(m => m.sessionId === sessionId || m.verifierSessionId === sessionId || m.roleCalls?.some(c => c.sessionId === sessionId) || m.decisions?.some(d => d.workerId === sessionId));
	const m = selected?.coordinatorId ? query.data?.missions.find(parent => parent.request.id === selected.coordinatorId) || selected : selected;
	if (!m) return query.isError ? <p className="px-4 text-sm text-destructive">验收记录读取失败</p> : null;
	return <MissionContent key={m.request.id} m={m} readError={query.isError} />;
}

export function CLAOMissionDetail({ missionId, onNewAttempt, onOpenSession, onBack }: { missionId: string; onNewAttempt?: (request: AcceptanceRequest) => void; onOpenSession?: (id: string) => void; onBack?: () => void }) {
	const query = useQuery({ queryKey: ["clao-missions", missionId], queryFn: () => request<{ mission: Mission }>("/missions/" + encodeURIComponent(missionId)), refetchInterval: 1500, retry: false });
	return query.data ? <MissionContent key={missionId} m={query.data.mission} readError={query.isError} onNewAttempt={onNewAttempt} onOpenSession={onOpenSession} /> : <p role="status" className="p-4 text-sm">{query.isError ? "原请求读取失败；未创建新的尝试。" : "正在读取原请求…"}<button type="button" className="ml-3 underline" onClick={() => void query.refetch()}>重新读取</button>{onBack && <button type="button" className="ml-3 underline" onClick={onBack}>返回当前草稿（保留提交身份）</button>}</p>;
}

// A project-level receipt list also includes missions that never got a Session.
// It is a projection of the same stored records used by the Session panel.
export function CLAOMissionList({ projectId }: { projectId?: string }) {
	const query = useQuery({ queryKey: ["clao-missions"], queryFn: () => request<{ missions: Mission[] }>("/missions"), refetchInterval: 1500, retry: false });
	const [selected, setSelected] = useState<string | null>(null);
	const newTask = useUiStore(s => s.requestNewTask);
	const rows = query.data?.missions.filter(m => !projectId || m.request.projectId === projectId) ?? [];

	return <section className="shrink-0 border-b border-border px-4 py-2 text-sm" data-testid="clao-mission-list">
		<div className="mb-2 flex items-center justify-between gap-3"><strong>闭环任务</strong><CLAOLocalProject /></div>
		<details open><summary className="cursor-pointer">任务记录 · {rows.length}</summary>
		{query.isError && <p role="alert" className="text-destructive">闭环记录读取失败，保留最后已知状态。</p>}
		<ul className="max-h-32 overflow-auto">{rows.map(m => <li key={m.request.id} className="flex items-center gap-3 py-1"><button type="button" className="min-w-0 flex-1 truncate text-left underline" onClick={() => setSelected(m.request.id)} aria-label={"查看原请求：" + m.request.objective}>{m.request.objective}</button><span>{(m.coordinatorId && m.state === "DONE" ? "子任务已完成，待整体验收" : states[m.state] || m.state)}</span></li>)}</ul></details>
		<Dialog.Root open={selected !== null} onOpenChange={open => { if (!open) setSelected(null); }}><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="fixed left-1/2 top-1/2 z-overlay max-h-[85vh] w-[min(56rem,95vw)] max-w-[95vw] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-lg border border-border bg-popover p-4 shadow-xl">
		<Dialog.Title>闭环请求与验收</Dialog.Title><Dialog.Description className="sr-only">持久请求、执行事实与处理操作</Dialog.Description>
		{selected && <CLAOMissionDetail missionId={selected} onNewAttempt={r => { setSelected(null); newTask(r.projectId, r); }} onOpenSession={() => setSelected(null)} />}
		<Dialog.Close className="mt-3 rounded-md border border-border px-3 py-2">关闭</Dialog.Close>
		</Dialog.Content></Dialog.Portal></Dialog.Root>
	</section>;
}

function MissionContent({ m, readError, onNewAttempt, onOpenSession }: { m: Mission; readError: boolean; onNewAttempt?: (request: AcceptanceRequest) => void; onOpenSession?: (id: string) => void }) {
	const queryClient = useQueryClient();
    const [now,setNow]=useState(Date.now());
    useEffect(()=>{if(terminal.has(m.state)||readError)return;const timer=setInterval(()=>setNow(Date.now()),1000);return ()=>clearInterval(timer)},[m.state,readError]);
	const navigate = useNavigate();
	const [pending, setPending] = useState(false);
	const [error, setError] = useState<{ id: string; text: string } | null>(null);
	const cancel = async () => {
		if (pending) return; setPending(true); setError(null);
		const id = m.coordinatorId || m.request.id;
		try { await request("/missions/" + encodeURIComponent(id) + "/cancel", {}); await queryClient.invalidateQueries({ queryKey: ["clao-missions"] }); }
		catch (e) { setError({ id:m.request.id, text: e instanceof Error ? e.message : "取消请求失败" }); }
		finally { setPending(false); }
	};
    const resume = async () => {
        if (pending) return; setPending(true);setError(null);
        const id=m.coordinatorId || m.request.id;
        try { await request("/missions/"+encodeURIComponent(id)+"/continue",{});await queryClient.invalidateQueries({queryKey:["clao-missions"]}); }
        catch(e){setError({id,text:e instanceof Error?e.message:"继续请求未确认，请查看原任务；不会重新提交"});}
        finally{setPending(false);}
    };
	const facts = acceptanceFacts(m);
	return <section className="shrink-0 border-b border-border bg-background px-4 py-3 text-sm" data-testid="clao-result">
		<div className="flex flex-wrap items-center justify-between gap-3"><strong className={m.state === "DONE" ? "text-green-600" : m.state === "FAILED" || m.state === "UNKNOWN" ? "text-destructive" : ""}>CLAO · {m.cancelRequested && !terminal.has(m.state) ? "取消中" : (m.coordinatorId && m.state === "DONE" ? "子任务已完成，待整体验收" : states[m.state] || m.state)}</strong>
		{(!terminal.has(m.state) || m.state === "UNKNOWN") && <button type="button" onClick={() => void cancel()} disabled={pending || m.cancelRequested && m.state !== "UNKNOWN"} className="rounded-md border border-border px-3 py-1.5">{m.cancelRequested ? m.state === "UNKNOWN" ? "重新确认停止" : "取消已接收" : "取消任务"}</button>}</div>
		<p className="mt-1 whitespace-pre-wrap break-words">{m.request.objective}</p>
		<p className="mt-1 break-words">{readableRunReason(m.reason)}</p>
        {m.coordinatorId && <p className="mt-2">这是整体任务中的独立子任务；继续与取消由整体任务统一处理。</p>}
        {m.checkpoint && ["PAUSED","UNKNOWN","RESUMING"].includes(m.state) && <p>保存的阶段：{({worker:"Worker 回合",gate:"Gate 验收",decide:"审核／规划",action:"已校验动作",materialize:"固定结果",verify:"独立复核",final:"最终验收"} as Record<string,string>)[m.checkpoint.stage] || m.checkpoint.stage}</p>}
        {m.recovery && m.recovery.reason!==m.reason && <p className="text-destructive">{m.recovery.reason}</p>}
        {!m.coordinatorId && ["PAUSED","UNKNOWN"].includes(m.state) && !m.cancelRequested && <button type="button" className="mt-2 rounded border border-border px-3 py-2" disabled={pending||readError} onClick={()=>void resume()}>继续原任务</button>}
		{readError && <p className="text-destructive">连接中断，保留最后已知验收状态。</p>}
		<div className="mt-2 flex flex-wrap gap-3">
		{m.sessionId && <button type="button" className="underline" onClick={() => { void navigate({ to: "/projects/$projectId/sessions/$sessionId", params: { projectId: m.request.projectId, sessionId: m.sessionId! } }); onOpenSession?.(m.sessionId!); }}>打开执行会话</button>}
		{onNewAttempt && ["FAILED", "CANCELLED", "DONE", "HUMAN"].includes(m.state) && <button type="button" className="rounded-md border border-border px-3 py-2" disabled={readError} onClick={() => onNewAttempt(m.request)}>创建新的尝试（保留草稿）</button>}
		</div>
		{error?.id === m.request.id && <p role="alert" className="text-destructive">{error.text}</p>}
        <CLAORunView key={"run:"+m.request.id} m={m} readError={readError} onOpenSession={id=>{void navigate({to:"/projects/$projectId/sessions/$sessionId",params:{projectId:m.request.projectId,sessionId:id}});onOpenSession?.(id);}}/>
        <CLAODirectives key={m.request.id} m={m} readError={readError}/>
        <section className="mt-4 space-y-3" aria-label="验收摘要"><strong>结果与验收</strong><div className="flex flex-wrap gap-x-5 gap-y-2"><span>命令：{factLabel(facts.command)}</span><span>完整性：{factLabel(facts.integrity)}</span><span>范围：{factLabel(facts.scope)}</span><span>取证：{factLabel(facts.collection)}</span><span>独立复核：{factLabel(facts.semantic)}</span></div><ul>{m.request.criteria.map(ac => {const check=facts.verification?.ac_checks?.find(c=>c.ac_id===ac.id);return <li key={ac.id} className="break-words">{ac.description} — {check?.verdict === "PASS" ? "通过" : check?.verdict === "FAIL" ? "未通过" : "尚无复核结果"}</li>;})}</ul><CLAOResults key={"result:"+m.request.id} m={m}/></section>
        <details className="mt-4" data-testid="clao-advanced"><summary className="cursor-pointer text-muted-foreground">高级详情</summary>
        <details className="mt-3" data-testid="clao-role-facts"><summary className="cursor-pointer">角色与决策</summary>
        <div className="mt-2 space-y-3">{["worker", "auditor", "planner", "verifier"].map(role => {
            const chosen=m.roles?.[role]; const calls=m.roleCalls?.filter(c=>c.role===role) ?? [];
            return <div key={role} className="rounded border border-border p-2"><strong>{role}</strong>
                <p>{chosen ? `${chosen.connection ? chosen.connection.name+" · "+chosen.connection.service : chosen.agent} · ${chosen.model || "执行器默认（不覆盖）"}${chosen.inherited ? " · 沿用 Worker 选择" : ""}` : "历史未提供独立角色配置"}</p>
                {chosen?.accountRef && <details><summary>原生账号引用</summary><span>{chosen.accountRef}</span></details>}
                {role === "worker" ? <span>当前执行对象：{m.sessionId || "尚未启动"}</span> : calls.length===0 ? <span>{chosen ? "未调用" : role==="verifier" && m.verifierSessionId ? "历史已记录 Verifier Session，未提供角色调用明细" : "历史未提供角色调用记录"}</span> : calls.map(c=><div key={c.id} className="mt-2 space-y-1">
                    <p>{({STARTING:"正在启动",RUNNING:"调用中",RECEIVED:"已收到回复，等待校验",VALIDATED:"已校验结构化结果",PROTOCOL_ERROR:"回复契约不符合要求",FAILED:"调用失败",UNKNOWN:"结果尚未确认",CANCELLED:"已停止"} as Record<string,string>)[c.state] || c.state}</p>
                    {c.result?.diagnosis && <p className="whitespace-pre-wrap break-words">{c.result.diagnosis}</p>}
                    {c.result?.action && <p>{c.result.action} · {c.result.reason}</p>}
                    {c.error && <p className="text-destructive break-words">{c.error}</p>}
                    <details><summary>模型、计时与证据关联</summary><p>请求：{c.choice.model || "执行器默认"} · AO 解析：{c.resolvedModel || "unknown"} · 执行器报告：{c.confirmedModel || "unknown"}（{c.modelFactSource || "未提供事实"}，非单次 provider 请求证明）</p><p>开始：{c.startedAt} · 结束：{c.finishedAt || "尚未返回"} · {c.startedAt && Number.isFinite(Date.parse(c.startedAt)) ? `已等待 ${Math.max(0, ((c.finishedAt ? Date.parse(c.finishedAt) : now) - Date.parse(c.startedAt)) / 1000).toFixed(1)} 秒` : "耗时 unknown"}</p><p>事件：{c.incidentId || "最终验收"} · 用量/费用：unknown</p>{c.result?.evidence?.map((e,i)=><p key={i} className="break-words">{e.summary} · {e.reference}</p>)}</details>
                    {c.sessionId && <button type="button" className="underline" onClick={()=>{void navigate({to:"/projects/$projectId/sessions/$sessionId",params:{projectId:m.request.projectId,sessionId:c.sessionId!}});onOpenSession?.(c.sessionId!);}}>打开 {role} 会话</button>}
                </div>)}
            </div>;
        })}{m.decisions?.map(d=><div key={d.id} className="rounded border border-border p-2"><strong>程序动作：{d.action || "等待决策"}</strong><p>{d.reason}</p><p>{d.outcome !== d.reason ? d.outcome || "尚未执行" : "已交给用户处理；未执行自动修复"}</p><details><summary>关联执行与状态</summary>{d.workerId} · {d.state}</details></div>)}</div></details>
        <details className="mt-2"><summary className="cursor-pointer">原始请求与验收记录</summary><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ request: m.request, state: m.state, reason: m.reason, evidence: m.evidence, operations: m.operations, resultHead: m.resultHead, revision: m.revision }, null, 2)}</pre></details>
        {m.subtasks?.map(child=><details key={child.request.id} className="mt-3 rounded border border-border p-2"><summary className="cursor-pointer break-words">子任务材料：{child.request.objective} · {child.state === "DONE" ? "子任务已完成" : states[child.state] || child.state}</summary><p className="break-words">{child.reason}</p><CLAODirectives m={child} readError={readError}/><CLAOResults m={child}/></details>)}
        </details>
	</section>;
}
