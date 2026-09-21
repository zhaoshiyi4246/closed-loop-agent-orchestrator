import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { aoBridge } from "../lib/bridge";
import { request } from "./CLAOAcceptance";

export function CLAOLocalProject({
  onOpened,
  disabled = false,
}: {
  onOpened?: () => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [create, setCreate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const cache = useQueryClient();
  const navigate = useNavigate();
  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const { project } = await request<{
        project: { id: string; name: string; path: string };
      }>("/projects", { path: path.trim(), name: name.trim(), create });
      await cache.invalidateQueries({ queryKey: ["workspaces"] });
      setOpen(false);
      onOpened?.();
      void navigate({
        to: "/projects/$projectId",
        params: { projectId: project.id },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "项目未能打开");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          disabled={disabled}
          className="rounded border border-border px-3 py-2 text-sm"
        >
          打开本地项目
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-overlay w-dialog max-w-[95vw] -translate-x-1/2 -translate-y-1/2 space-y-3 rounded-lg border border-border bg-popover p-4 shadow-xl">
          <Dialog.Title>本地闭环项目</Dialog.Title>
          <Dialog.Description className="text-sm">
            使用普通目录、空项目或 Git 当前内容；不初始化或提交原目录。
          </Dialog.Description>
          <label className="block text-sm">
            名称
            <input
              aria-label="本地项目名称"
              className="mt-1 w-full rounded border border-border bg-background p-2"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="block text-sm">
            目录
            <input
              aria-label="本地项目目录"
              className="mt-1 w-full rounded border border-border bg-background p-2"
              value={path}
              onChange={(e) => setPath(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="underline"
            disabled={busy}
            onClick={() =>
              void aoBridge.app
                .chooseDirectory("选择本地项目目录")
                .then((value) => {
                  if (value) {
                    setPath(value);
                    setCreate(false);
                  }
                })
                .catch((e) =>
                  setError(
                    e instanceof Error
                      ? e.message
                      : "目录选择不可用，请输入完整路径",
                  ),
                )
            }
          >
            选择已有目录
          </button>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={create}
              onChange={(e) => setCreate(e.target.checked)}
            />
            在上述位置创建新的空目录
          </label>
          {error && (
            <p
              role="alert"
              className="whitespace-pre-wrap text-sm text-destructive"
            >
              {error}
            </p>
          )}
          <div className="flex gap-3">
            <button
              type="button"
              className="rounded border border-border px-3 py-2"
              disabled={busy || !path.trim()}
              onClick={() => void submit()}
            >
              {busy ? "正在打开…" : create ? "创建并打开" : "打开项目"}
            </button>
            <Dialog.Close className="rounded border border-border px-3 py-2">
              取消
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
