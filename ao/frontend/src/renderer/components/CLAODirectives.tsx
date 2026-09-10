import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { request, type Mission } from "./CLAOAcceptance";

export type DirectiveReceipt = {
	id: string; target: string; text: string; state: string; reason: string; receivedAt: string; sessionId?: string; turnId?: string;
	consumers?: { callId: string; role: string; sessionId?: string; turnId?: string; mirror: boolean; state: string }[];
};
type Draft = { text: string; target: string; version: number; pending?: boolean; error?: string; unresolved?: { id: string; target: string; text: string; version: number } };
// Only unsent form state. Durable receipts remain in the Mission/query cache.
const drafts = new Map<string, Draft>();
const closed = new Set(["DONE", "FAILED", "CANCELLED", "HUMAN"]);
const labels: Record<string,string> = { received: "已接收", applied: "已交付／已用于本轮输入", rejected: "已拒绝", unknown: "交付待确认" };

export function CLAODirectives({ m, readError }: {m: Mission; readError: boolean}) {
	const id = m.request.id;
	const [, render] = useState(0);
	const mounted = useRef(true);
	useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
	const query = useQueryClient();
	if (!drafts.has(id)) drafts.set(id, {text:"",target:"planner",version:0});
	const draft = drafts.get(id)!;
	const refresh = () => { if (mounted.current) render(v=>v+1); };
	const update = (patch: Partial<Draft>) => { Object.assign(draft,patch,{version:draft.version+1});refresh(); };
	const worker = m.sessionId ? "worker:"+m.sessionId : "";
	const stale = draft.target.startsWith("worker:") && (draft.target!==worker || m.state!=="RUNNING");
	const inspect = async () => {
		const submission = draft.unresolved;
		if (!submission) return;
		const {mission} = await request<{mission:Mission}>("/missions/"+encodeURIComponent(id));
		const receipt = mission.directives?.find(d=>d.id===submission.id);
		if (!receipt) throw new Error("尚未找到该次接收记录；保留原指令身份，请查询原回执，不重新发送。");
		if (draft.version===submission.version && receipt.state!=="rejected") {draft.text="";draft.version++;}
		draft.unresolved=undefined;draft.error=receipt.state==="rejected"?receipt.reason:undefined;
		await query.invalidateQueries({queryKey:["clao-missions"]});
		refresh();
	};
	const submit = async () => {
		if (draft.pending || draft.unresolved || !draft.text.trim() || stale) return;
		const submission={id:crypto.randomUUID(),target:draft.target,text:draft.text,version:draft.version};
		draft.pending=true;draft.error=undefined;draft.unresolved=submission;refresh();
		try {
			await request("/missions/"+encodeURIComponent(id)+"/directives",{id:submission.id,target:submission.target,text:submission.text});
			await inspect();
		} catch (e) {
			try {await inspect();} catch {draft.error=e instanceof Error?e.message:"接收结果待查询；不会重发";}
		} finally {draft.pending=false;refresh();}
	};
	return <details className="mt-3" data-testid="clao-directives"><summary className="cursor-pointer">补充要求与回执{m.directives?.length ? `（${m.directives.length}）` : ""}</summary>
		{!closed.has(m.state) && !m.cancelRequested && <div className="mt-2 space-y-2">
			<label className="block">接收对象<select aria-label="指令接收对象" className="ml-2 rounded border border-border bg-background p-2" value={draft.target} onChange={e=>update({target:e.target.value})}>
				{["planner","auditor","verifier"].map(role=><option value={role} key={role}>{role}</option>)}
				{worker && <option value={worker}>当前 Worker · {m.sessionId}</option>}
				{draft.target.startsWith("worker:") && draft.target!==worker && <option value={draft.target}>原 Worker（不再接收）</option>}
			</select></label>
			{stale && <p className="text-destructive">原 Worker 已替换或不再接收。请确认接收对象；不会自动改发 Planner 或新 Worker。</p>}
			<textarea aria-label="补充要求" className="min-h-20 w-full rounded border border-border bg-background p-2" value={draft.text} onChange={e=>update({text:e.target.value})}/>
			<button type="button" className="rounded border border-border px-3 py-2" disabled={readError||draft.pending||!!draft.unresolved||stale||!draft.text.trim()} onClick={()=>void submit()}>提交补充要求</button>
			{draft.unresolved && <button type="button" className="ml-3 underline" disabled={draft.pending} onClick={()=>void inspect().catch(e=>{draft.error=String(e);refresh();})}>查询原回执（不重发）</button>}
		</div>}
		{draft.error && <p role="alert" className="mt-2 whitespace-pre-wrap text-destructive">{draft.error}</p>}
		<ul className="mt-2 space-y-2">{m.directives?.map(d=><li key={d.id} className="rounded border border-border p-2">
			<strong>{d.target} · {labels[d.state]||d.state}</strong><p className="whitespace-pre-wrap break-words">{d.text}</p>
			<p>{d.state==="received" && closed.has(m.state)?"任务已结束；原目标未调用，未用于该目标输入。":d.reason}</p>
			{d.consumers?.map(c=><p key={c.callId}>{c.mirror?"Planner 镜像上下文（不代表原目标收到）":"原目标输入"} · {labels[c.state]||c.state}</p>)}
			<details><summary>回合与调用关联</summary><p>{d.id} · {d.sessionId||"尚无 Session"} · {d.turnId||"尚无回合"}</p>{d.consumers?.map(c=><p key={c.callId}>{c.callId} · {c.sessionId} · {c.turnId}</p>)}</details>
		</li>)}</ul>
	</details>;
}
