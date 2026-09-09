import { useRef, useState } from "react";
import { AcceptanceForm, createAcceptance, type AcceptanceFields } from "./CLAOAcceptance";
import * as Dialog from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";
import { TaskComposer } from "./TaskComposer";

type NewTaskDialogProps = {
	open: boolean;
	projectId?: string;
	onCreated: (sessionId: string) => void;
	onOpenChange: (open: boolean) => void;
};

export function NewTaskDialog({ open, projectId, onCreated, onOpenChange }: NewTaskDialogProps) {
	const { t } = useTranslation();
	const [closedLoop,setClosedLoop] = useState(false);
	const [fields,setFields] = useState<AcceptanceFields>({criteria:"",allowed:"",forbidden:"",gates:"",repairs:1,timeout:120});
	const requestId = useRef(crypto.randomUUID());
	return (
		<Dialog.Root open={open} onOpenChange={onOpenChange}>
			<Dialog.Portal>
				<Dialog.Overlay className="dialog-overlay data-[state=open]:animate-overlay-in data-[state=closed]:animate-overlay-out" />
				<Dialog.Content className="fixed left-1/2 top-1/2 z-overlay w-dialog-xl -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-lg border border-border bg-popover p-0 text-popover-foreground shadow-xl data-[state=open]:animate-modal-in data-[state=closed]:animate-modal-out motion-reduce:animate-none">
					{/* One title line names the dialog, styled like every other settings-style
					    modal; everything else stays the composer's surface, no bordered header. */}
					<Dialog.Title className="settings-dialog-title px-4 pt-3">{t("newTask.title")}</Dialog.Title>
					<Dialog.Description className="sr-only">{t("newTask.description")}</Dialog.Description>
					<label className="flex items-center gap-2 px-4 pt-3 text-sm"><input type="checkbox" checked={closedLoop} onChange={e=>setClosedLoop(e.target.checked)} />CLAO 闭环验收</label>
					{closedLoop && <AcceptanceForm value={fields} onChange={setFields} />}
					<TaskComposer
						createClosedLoop={closedLoop ? input=>createAcceptance(requestId.current,fields,input) : undefined}
						projectId={projectId}
						autoFocusTitle
						onCreated={(sessionId) => {
							requestId.current=crypto.randomUUID();
							onCreated(sessionId);
							onOpenChange(false);
						}}
					/>
				</Dialog.Content>
			</Dialog.Portal>
		</Dialog.Root>
	);
}
