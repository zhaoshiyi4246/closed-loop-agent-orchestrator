import { CLAORoleForm } from "./CLAORoleForm";
import { useEffect, useRef, useState } from "react";
import { AcceptanceForm, CLAOMissionDetail, createAcceptance, type AcceptanceFields, type AcceptanceRequest } from "./CLAOAcceptance";
import * as Dialog from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";
import { TaskComposer } from "./TaskComposer";
import { CLAOSource } from "./CLAOSource";
import { useQuery } from "@tanstack/react-query";
import { legacyQuery } from "./CLAOLegacy";

type NewTaskDialogProps = {
	open: boolean;
	projectId?: string;
	initialRequest?: AcceptanceRequest;
	onCreated: (sessionId: string) => void;
	onOpenChange: (open: boolean) => void;
};

export function NewTaskDialog({ open, projectId, initialRequest, onCreated, onOpenChange }: NewTaskDialogProps) {
	const { t } = useTranslation();
	const [closedLoop,setClosedLoop] = useState(Boolean(initialRequest)||!!projectId?.startsWith("clao-local-"));
	const modeTouched=useRef(false);
	useEffect(()=>{if(!modeTouched.current&&!initialRequest)setClosedLoop(!!projectId?.startsWith("clao-local-"));},[projectId,initialRequest]);
	const [fields,setFields] = useState<AcceptanceFields>(initialRequest ? { parentId:initialRequest.id, criteria: initialRequest.criteria.map(ac => ac.description).join("\n"), allowed: initialRequest.allowedPaths.join("\n"), forbidden: initialRequest.forbiddenPaths.join("\n"), gates: initialRequest.gateCommands.join("\n"), repairs: initialRequest.maxRepairs, timeout: initialRequest.gateTimeout, roles: initialRequest.roles, replans: initialRequest.maxReplans ?? 0, maxTasks:initialRequest.maxTasks ?? 1 } : {criteria:"",allowed:"",forbidden:"",gates:"",repairs:1,timeout:120});
	const imports=useQuery({...legacyQuery,enabled:closedLoop});
	const [source,setSource]=useState<{projectId:string;revision:string}>();
	const [consentScope,setConsentScope]=useState("");
	const [composerRevision,setComposerRevision]=useState(0);
	const [importSelection,setImportSelection]=useState("");
	const external=Object.entries(fields.roles||{}).flatMap(([role,value])=>{const c=imports.data?.connections.find(c=>c.id===value.connectionId);return c?[{role,...c}]:[];});
	const scope=JSON.stringify([projectId,external.map(c=>[c.role,c.id,c.service,c.endpoint,c.model,c.billing,c.authRevision??0,fields.roles?.[c.role as "planner"|"auditor"|"verifier"]?.connectionRevision??0]).sort()]);
	const services=[...new Set(external.map(c=>c.service))];
	const requestId = useRef(crypto.randomUUID());
	const [receiptId, setReceiptId] = useState<string | null>(null);
	const [attempted, setAttempted] = useState(false);
	const [submitting, setSubmitting] = useState(false);
	const [draft, setDraft] = useState<{ brief: string; agent: string; model: string; mode?: string } | undefined>(initialRequest ? { brief: initialRequest.objective, agent: initialRequest.agent, model: initialRequest.model } : undefined);
	const applyImported=()=>{
		const chosen=imports.data?.configurations.find(c=>c.id===importSelection)?.document.values;if(!chosen)return;
		const roles=chosen.roles ? Object.fromEntries(Object.entries(chosen.roles).map(([role,value])=>{const c=imports.data?.connections.find(c=>c.id===value.connectionId);return [role,{agent:value.agent||"",model:value.model||c?.model||"",connectionId:value.connectionId,connectionRevision:c?.authRevision??0}];})) : fields.roles;
		setFields(v=>({...v,timeout:chosen.gateTimeout??v.timeout,repairs:chosen.maxRepairs??v.repairs,replans:chosen.maxReplans??v.replans,maxTasks:chosen.maxTasks??v.maxTasks,roles}));
		setDraft(v=>({brief:v?.brief||"",agent:chosen.agent??v?.agent??"",model:chosen.model??v?.model??"",mode:v?.mode}));setComposerRevision(v=>v+1);setConsentScope("");
	};
	const created = (sessionId: string) => {
		requestId.current = crypto.randomUUID();
		setReceiptId(null); setAttempted(false);
		setConsentScope(""); setSource(undefined);
		onCreated(sessionId); onOpenChange(false);
	};
	return (
		<Dialog.Root open={open} onOpenChange={onOpenChange}>
			<Dialog.Portal>
				<Dialog.Overlay className="dialog-overlay data-[state=open]:animate-overlay-in" />
				<Dialog.Content className="fixed left-1/2 top-1/2 z-overlay max-h-[90vh] w-dialog-xl max-w-[95vw] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-lg border border-border bg-popover p-0 text-popover-foreground shadow-xl data-[state=open]:animate-modal-in motion-reduce:animate-none">
					{/* One title line names the dialog, styled like every other settings-style
					    modal; everything else stays the composer's surface, no bordered header. */}
					<Dialog.Title className="settings-dialog-title px-4 pt-3">{receiptId ? "闭环任务详情" : t("newTask.title")}</Dialog.Title>
					<Dialog.Description className="sr-only">{t("newTask.description")}</Dialog.Description>
					{receiptId && <CLAOMissionDetail missionId={receiptId} onBack={() => setReceiptId(null)} onOpenSession={created} onNewAttempt={original => { setFields(v=>({...v,parentId:original.id})); setSource(undefined);setConsentScope("");requestId.current = crypto.randomUUID(); setReceiptId(null); setAttempted(false); }} />}
					<div hidden={receiptId !== null}>
					<fieldset disabled={submitting}>
					<label className="flex items-center gap-2 px-4 pt-3 text-sm"><input type="checkbox" checked={closedLoop} onChange={e=>{modeTouched.current=true;setClosedLoop(e.target.checked);}} />CLAO 闭环验收</label>
					{closedLoop && !!imports.data?.configurations.length && <details className="mx-4 mt-2 text-sm"><summary>使用已导入的旧配置</summary><select aria-label="已导入配置" className="my-2 rounded border border-border bg-background p-2" value={importSelection} onChange={e=>setImportSelection(e.target.value)}><option value="">选择配置</option>{imports.data.configurations.map(c=><option key={c.id} value={c.id}>{c.document.name}</option>)}</select><button type="button" className="ml-3 underline" disabled={!importSelection} onClick={applyImported}>应用到当前草稿</button><p>仅应用兼容的角色与预算，保留目标、范围、验收条件。</p></details>}
					{closedLoop && <><CLAOSource key={projectId} projectId={projectId||""} revision={source?.projectId===projectId?source?.revision:undefined} onConfirm={revision=>setSource({projectId:projectId||"",revision})}/><AcceptanceForm value={fields} onChange={setFields} /><CLAORoleForm fields={fields} onChange={setFields} projectId={projectId || ""} worker={draft} />{external.length>0 && <section className="mx-4 mb-3 rounded border border-border p-3 text-sm"><strong>本次外部服务</strong>{external.map(c=><p key={c.role}>{c.role} → {c.name} · {c.service} · {c.model}</p>)}<label className="mt-2 flex items-start gap-2"><input type="checkbox" aria-label="同意本次外发材料" checked={consentScope===scope} onChange={e=>setConsentScope(e.target.checked?scope:"")}/>同意将本次任务材料发送至以上服务</label></section>}</>}
					</fieldset>
					<TaskComposer
						key={composerRevision}
						initialInput={draft}
						onDraftChange={setDraft}
						createClosedLoop={closedLoop ? async input => { if(external.some(c=>(fields.roles?.[c.role as "planner"|"auditor"|"verifier"]?.connectionRevision??0)!==(c.authRevision??0))) throw new Error("连接凭据已更新，请在角色设置中重新确认版本"); if(services.length && consentScope!==scope) throw new Error("请确认本次外部服务与材料范围"); setAttempted(true); const mission = await createAcceptance(requestId.current, {...fields,sourceRevision:source?.projectId===input.projectId?source?.revision:undefined,externalServiceConsent:consentScope===scope?services:[]}, input); setReceiptId(mission.request.id);setConsentScope(""); } : undefined}
						onSubmittingChange={setSubmitting}
						projectId={projectId}
						autoFocusTitle
						onCreated={created}
					/>
					{attempted && closedLoop && <button type="button" disabled={submitting} className="m-4 underline" onClick={() => setReceiptId(requestId.current)}>查看原请求（不重新提交）</button>}
					</div>
					<Dialog.Close className="m-3 rounded-md border border-border px-3 py-2">关闭</Dialog.Close>
				</Dialog.Content>
			</Dialog.Portal>
		</Dialog.Root>
	);
}
