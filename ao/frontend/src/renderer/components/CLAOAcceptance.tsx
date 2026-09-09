import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useNavigate } from "@tanstack/react-router";
import { useUiStore } from "../stores/ui-store";
import { getApiBaseUrl, hasTrustedApiBaseUrl } from "../lib/api-client";

export type AcceptanceFields = { criteria: string; allowed: string; forbidden: string; gates: string; repairs: number; timeout: number };
export type AcceptanceRequest = {
	id: string; projectId: string; objective: string; agent: string; model: string;
	criteria: { id: string; description: string }[]; allowedPaths: string[]; forbiddenPaths: string[];
	gateCommands: string[]; maxRepairs: number; gateTimeout: number;
};
type Evidence = { ok: boolean; scopeOK: boolean; readError?: string; paths: string[]; forbidden: string[]; outside: string[]; gate?: { command_ok: boolean; integrity_ok: boolean }; records?: unknown; verification?: { verdict: string; summary: string; ac_checks: { ac_id: string; verdict: string; note: string }[] }; resultHead?: string };
export type Mission = { request: AcceptanceRequest; state: string; reason: string; revision: number; sessionId?: string; verifierSessionId?: string; workspace?: string; resultHead?: string; repairs: number; cancelRequested: boolean; evidence: Evidence[]; operations: unknown[] };
const terminal = new Set(["DONE", "FAILED", "CANCELLED", "UNKNOWN"]);
const states: Record<string, string> = { SPAWNING: "准备中", RUNNING: "执行中", STOPPING: "确认停止", GATE: "验收中", REPAIRING: "修复中", MATERIALIZING: "固定结果", VERIFYING: "独立复核", DONE: "验收通过", FAILED: "验收未通过", CANCELLED: "已取消", UNKNOWN: "结果尚未确认" };
const lines = (value: string) => value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);

async function request<T>(path: string, body?: unknown): Promise<T> {
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
	if (!response.ok) throw new Error(data.message || data.error?.message || "闭环请求失败");
	return data as T;
}
export async function createAcceptance(id: string, fields: AcceptanceFields, input: { projectId: string; brief: string; agent?: string; model?: string; mode?: string; approvalMode?: string; attachments?: unknown[] }): Promise<Mission> {
	if (input.mode || input.approvalMode || input.attachments?.length) throw new Error("闭环使用原生 Chat 审批；本轮不接受终端降级、跳过审批或附件");
	const body: AcceptanceRequest = { id, projectId: input.projectId, objective: input.brief, agent: input.agent || "", model: input.model || "", criteria: lines(fields.criteria).map((description, i) => ({ id: `AC${i + 1}`, description })), allowedPaths: lines(fields.allowed), forbiddenPaths: lines(fields.forbidden), gateCommands: lines(fields.gates), maxRepairs: fields.repairs, gateTimeout: fields.timeout };
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
	return <div className="grid max-h-64 grid-cols-2 gap-3 overflow-y-auto px-4 py-3" data-testid="clao-acceptance-form">
		{field("criteria", "验收条件（每行一项）", "说明什么结果才算通过")}
		{field("gates", "Gate 命令（每行一条）", "使用项目真实的检查命令")}
		{field("allowed", "允许修改范围", "例如 src/**；请明确填写")}
		{field("forbidden", "禁止修改范围", "可留空")}
		<label className="text-sm">最多修复次数<input aria-label="最多修复次数" type="number" min={0} max={3} step={1} value={value.repairs} onChange={e => onChange({ ...value, repairs: e.target.valueAsNumber })} className="ml-2 w-16 rounded border border-border bg-background p-1" /></label>
		<label className="text-sm">Gate 超时（秒）<input aria-label="Gate 超时（秒）" type="number" min={1} max={600} step="any" value={value.timeout} onChange={e => onChange({ ...value, timeout: e.target.valueAsNumber })} className="ml-2 w-20 rounded border border-border bg-background p-1" /></label>
	</div>;
}
export function CLAOAcceptance({ sessionId }: { sessionId: string }) {
	const query = useQuery({ queryKey: ["clao-missions"], queryFn: () => request<{ missions: Mission[] }>("/missions"), refetchInterval: 1500, retry: false });
	const m = query.data?.missions.find(m => m.sessionId === sessionId || m.verifierSessionId === sessionId);
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
	if (!rows.length && !query.isError) return null;
	return <section className="shrink-0 border-b border-border px-4 py-2 text-sm" data-testid="clao-mission-list">
		<details open><summary className="cursor-pointer">闭环任务 · {rows.length}</summary>
		{query.isError && <p role="alert" className="text-destructive">闭环记录读取失败，保留最后已知状态。</p>}
		<ul className="max-h-32 overflow-auto">{rows.map(m => <li key={m.request.id} className="flex items-center gap-3 py-1"><button type="button" className="min-w-0 flex-1 truncate text-left underline" onClick={() => setSelected(m.request.id)} aria-label={"查看原请求：" + m.request.objective}>{m.request.objective}</button><span>{states[m.state] || m.state}</span></li>)}</ul></details>
		<Dialog.Root open={selected !== null} onOpenChange={open => { if (!open) setSelected(null); }}><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="fixed left-1/2 top-1/2 z-overlay max-h-[85vh] w-dialog-xl max-w-[95vw] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-lg border border-border bg-popover p-4 shadow-xl">
		<Dialog.Title>闭环请求与验收</Dialog.Title><Dialog.Description className="sr-only">持久请求、执行事实与处理操作</Dialog.Description>
		{selected && <CLAOMissionDetail missionId={selected} onNewAttempt={r => { setSelected(null); newTask(r.projectId, r); }} onOpenSession={() => setSelected(null)} />}
		<Dialog.Close className="mt-3 rounded-md border border-border px-3 py-2">关闭</Dialog.Close>
		</Dialog.Content></Dialog.Portal></Dialog.Root>
	</section>;
}

function MissionContent({ m, readError, onNewAttempt, onOpenSession }: { m: Mission; readError: boolean; onNewAttempt?: (request: AcceptanceRequest) => void; onOpenSession?: (id: string) => void }) {
	const queryClient = useQueryClient();
	const navigate = useNavigate();
	const [pending, setPending] = useState(false);
	const [error, setError] = useState<{ id: string; text: string } | null>(null);
	const cancel = async () => {
		if (pending) return; setPending(true); setError(null);
		const id = m.request.id;
		try { await request("/missions/" + encodeURIComponent(id) + "/cancel", {}); await queryClient.invalidateQueries({ queryKey: ["clao-missions"] }); }
		catch (e) { setError({ id, text: e instanceof Error ? e.message : "取消请求失败" }); }
		finally { setPending(false); }
	};
	const latest = m.evidence.at(-1);
	return <section className="shrink-0 border-b border-border bg-background px-4 py-3 text-sm" data-testid="clao-result">
		<div className="flex items-center justify-between gap-3"><strong className={m.state === "DONE" ? "text-green-600" : m.state === "FAILED" || m.state === "UNKNOWN" ? "text-destructive" : ""}>CLAO · {states[m.state] || m.state}</strong>
		{(!terminal.has(m.state) || m.state === "UNKNOWN") && <button type="button" onClick={() => void cancel()} disabled={pending || m.cancelRequested && m.state !== "UNKNOWN"} className="rounded-md border border-border px-3 py-1.5">{m.cancelRequested ? m.state === "UNKNOWN" ? "重新确认停止" : "取消已接收" : "取消闭环"}</button>}</div>
		<p className="mt-1 whitespace-pre-wrap break-words">{m.request.objective}</p>
		<p className="mt-1 break-words">{m.reason}</p>
		{readError && <p className="text-destructive">连接中断，保留最后已知验收状态。</p>}
		<div className="mt-2 flex flex-wrap gap-3">
		{m.sessionId && <button type="button" className="underline" onClick={() => { void navigate({ to: "/projects/$projectId/sessions/$sessionId", params: { projectId: m.request.projectId, sessionId: m.sessionId! } }); onOpenSession?.(m.sessionId!); }}>打开原生 Session</button>}
		{onNewAttempt && ["FAILED", "CANCELLED", "DONE"].includes(m.state) && <button type="button" className="rounded-md border border-border px-3 py-2" disabled={readError} onClick={() => onNewAttempt(m.request)}>创建新的尝试（保留草稿）</button>}
		</div>
		{error?.id === m.request.id && <p role="alert" className="text-destructive">{error.text}</p>}
		{m.resultHead && <p className="mt-1 break-all">结果：{m.workspace} {m.state !== "DONE" && "（尚未通过最终验收）"}</p>}
		<details className="mt-2"><summary className="cursor-pointer">验收条件、文件与证据</summary><div className="mt-2 max-h-56 space-y-2 overflow-auto">
		<div className="flex flex-wrap gap-x-6 gap-y-1">
            <span>Gate 命令：{latest?.gate ? latest.gate.command_ok ? "通过" : "未通过" : "尚未提供"}</span>
            <span>仓库完整性：{latest?.gate ? latest.gate.integrity_ok ? "通过" : "未通过" : "尚未提供"}</span>
            <span>范围：{latest?.readError ? "取证失败" : latest ? latest.scopeOK ? "通过" : "未通过" : "尚未提供"}</span>
            <span>Verifier：{latest?.verification?.verdict || "未提供结论"}</span>
        </div>
        <ul>{m.request.criteria.map(ac => { const check=latest?.verification?.ac_checks?.find(c=>c.ac_id===ac.id);return <li key={ac.id}>{ac.id} · {ac.description} — {check ? check.verdict : "尚无复核结果"}</li>; })}</ul>
		{latest?.paths?.length ? <ul>{latest.paths.map(p => <li key={p} className="break-all">{p}</li>)}</ul> : <p>尚无文件证据</p>}
		<details><summary className="cursor-pointer">原始请求与操作记录</summary><pre className="overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ request: m.request, evidence: m.evidence, operations: m.operations, resultHead: m.resultHead, revision: m.revision }, null, 2)}</pre></details>
		</div></details>
	</section>;
}
