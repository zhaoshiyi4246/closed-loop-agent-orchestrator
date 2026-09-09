import { useRef, useState } from "react";
import { AcceptanceForm, CLAOMissionDetail, createAcceptance, type AcceptanceFields, type AcceptanceRequest } from "./CLAOAcceptance";
import * as Dialog from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";
import { TaskComposer } from "./TaskComposer";

type NewTaskDialogProps = {
	open: boolean;
	projectId?: string;
	initialRequest?: AcceptanceRequest;
	onCreated: (sessionId: string) => void;
	onOpenChange: (open: boolean) => void;
};

export function NewTaskDialog({ open, projectId, initialRequest, onCreated, onOpenChange }: NewTaskDialogProps) {
	const { t } = useTranslation();
	const [closedLoop,setClosedLoop] = useState(Boolean(initialRequest));
	const [fields,setFields] = useState<AcceptanceFields>(initialRequest ? { criteria: initialRequest.criteria.map(ac => ac.description).join("\n"), allowed: initialRequest.allowedPaths.join("\n"), forbidden: initialRequest.forbiddenPaths.join("\n"), gates: initialRequest.gateCommands.join("\n"), repairs: initialRequest.maxRepairs, timeout: initialRequest.gateTimeout } : {criteria:"",allowed:"",forbidden:"",gates:"",repairs:1,timeout:120});
	const requestId = useRef(crypto.randomUUID());
	const [receiptId, setReceiptId] = useState<string | null>(null);
	const [attempted, setAttempted] = useState(false);
	const [submitting, setSubmitting] = useState(false);
	const [draft, setDraft] = useState<{ brief: string; agent: string; model: string; mode?: string } | undefined>(initialRequest ? { brief: initialRequest.objective, agent: initialRequest.agent, model: initialRequest.model } : undefined);
	const created = (sessionId: string) => {
		requestId.current = crypto.randomUUID();
		setReceiptId(null); setAttempted(false);
		onCreated(sessionId); onOpenChange(false);
	};
	return (
		<Dialog.Root open={open} onOpenChange={onOpenChange}>
			<Dialog.Portal>
				<Dialog.Overlay className="dialog-overlay data-[state=open]:animate-overlay-in" />
				<Dialog.Content className="fixed left-1/2 top-1/2 z-overlay max-h-[90vh] w-dialog-xl max-w-[95vw] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-lg border border-border bg-popover p-0 text-popover-foreground shadow-xl data-[state=open]:animate-modal-in motion-reduce:animate-none">
					{/* One title line names the dialog, styled like every other settings-style
					    modal; everything else stays the composer's surface, no bordered header. */}
					<Dialog.Title className="settings-dialog-title px-4 pt-3">{t("newTask.title")}</Dialog.Title>
					<Dialog.Description className="sr-only">{t("newTask.description")}</Dialog.Description>
					{receiptId && <CLAOMissionDetail missionId={receiptId} onBack={() => setReceiptId(null)} onOpenSession={created} onNewAttempt={() => { requestId.current = crypto.randomUUID(); setReceiptId(null); setAttempted(false); }} />}
					<div hidden={receiptId !== null}>
					<fieldset disabled={submitting}>
					<label className="flex items-center gap-2 px-4 pt-3 text-sm"><input type="checkbox" checked={closedLoop} onChange={e=>setClosedLoop(e.target.checked)} />CLAO 闭环验收</label>
					{closedLoop && <AcceptanceForm value={fields} onChange={setFields} />}
					</fieldset>
					<TaskComposer
						initialInput={draft}
						onDraftChange={setDraft}
						createClosedLoop={closedLoop ? async input => { setAttempted(true); const mission = await createAcceptance(requestId.current, fields, input); setReceiptId(mission.request.id); } : undefined}
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
