import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { request, type Mission } from "./CLAOAcceptance";
import { getApiBaseUrl, hasTrustedApiBaseUrl } from "../lib/api-client";
import { ReviewDiffBody, type FileAnnotationModel } from "./WorkspaceDiffView";
import type { WorkspaceFileDetail } from "../hooks/useSessionWorkspaceFiles";

type ResultPackage = {
  identity: string;
  sha256: string;
  bytes: number;
  created_at: string;
  accepted: boolean;
  status?: string;
  reason?: string;
};
type Change = {
  kind: string;
  old_path?: string;
  path: string;
  diff?: string;
  diffTruncated?: boolean;
};
type ResultView = {
  missionId: string;
  status: string;
  reason?: string;
  location: { status: string; path: string };
  baseCommit?: string;
  resultCommit?: string;
  changes: Change[];
  diff: string;
  diffTruncated: boolean;
  noChanges: boolean;
  exports: ResultPackage[];
  evidence: {
    mission?: { state: string; reason: string; accepted: boolean };
    acceptance_criteria?: {
      id: string;
      description: string;
      verdict: string;
      note?: string;
    }[];
    gates?: {
      status: string;
      records: {
        id: string;
        task_id: string;
        phase: string;
        command: string;
        exit_code?: number;
        command_status: string;
        integrity?: { status: string; reason?: string };
        scope?: unknown;
        overall: string;
      }[];
    };
    verifier?: {
      status: string;
      record?: { verdict?: string; [key: string]: unknown };
    };
  };
};
const noop = () => {};
const annotation: FileAnnotationModel = {
  readonly: true,
  target: null,
  draft: "",
  status: "idle",
  error: "",
  begin: noop,
  setDraft: noop,
  cancel: noop,
  submit: async () => {},
};
const statusLabels: Record<string, string> = {
  ok: "固定成果可读取",
  saved: "原工作区不可用，已保存结果包仍可读取",
  not_produced: "尚未生成固定成果",
  missing: "原结果材料已失效",
  read_error: "结果读取失败",
  restricted: "结果包含不能导出的材料",
  unsupported: "当前文件类型不能完整导出",
};
const verdict = (value?: string) =>
  (
    ({
      PASS: "通过",
      FAIL: "未通过",
      UNKNOWN: "未提供",
      unknown: "未提供",
      pass: "通过",
      fail: "未通过",
      not_run: "未运行",
      no_records: "无记录",
      ok: "记录已读取",
      read_error: "读取失败",
    }) as Record<string, string>
  )[value || ""] ||
  value ||
  "未提供";

function FrozenDiff({
  change,
  missionId,
}: {
  change: Change;
  missionId: string;
}) {
  const detail: WorkspaceFileDetail = {
    path: change.path,
    previousPath: change.old_path,
    sessionId: missionId,
    status:
      (
        {
          A: "added",
          D: "deleted",
          R: "renamed",
          added: "added",
          deleted: "deleted",
          renamed: "renamed",
          rename: "renamed",
          delete: "deleted",
          add: "added",
        } as Record<string, WorkspaceFileDetail["status"]>
      )[change.kind] || "modified",
    additions: 0,
    deletions: 0,
    binary: false,
    content: "",
    contentTruncated: false,
    deleted: change.kind === "D",
    diff: change.diff || "",
    diffTruncated: !!change.diffTruncated,
    size: 0,
  };
  return (
    <div data-files-scroll-root className="max-h-80 overflow-auto">
      <div className="session-files-review-list">
        <ReviewDiffBody
          annotation={annotation}
          detail={detail}
          detailLoadedAt={0}
          filePath={change.path}
          sessionId={missionId}
          onActiveSelectionChange={noop}
          split={false}
          wrap
        />
      </div>
    </div>
  );
}

export function CLAOResults({ m }: { m: Mission }) {
  const id = m.request.id;
  const cache = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState<string>();
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const result = useQuery({
    queryKey: ["clao-result", id, m.resultHead, m.state],
    queryFn: () =>
      request<{ result: ResultView }>(
        "/missions/" + encodeURIComponent(id) + "/result",
      ),
    enabled: expanded,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const value = result.data?.result;
  const action = async (name: string, fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(name);
    setError("");
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "结果操作失败");
    } finally {
      setBusy(undefined);
    }
  };
  const download = async (pkg: ResultPackage) => {
    if (!hasTrustedApiBaseUrl()) throw new Error("本地服务尚未就绪");
    const response = await fetch(
      getApiBaseUrl() +
        "/api/v1/clao/missions/" +
        encodeURIComponent(id) +
        "/exports/" +
        encodeURIComponent(pkg.identity),
      { cache: "no-store" },
    );
    if (!response.ok)
      throw new Error("已保存结果包无法下载；请重新读取对应任务");
    const blob = await response.blob();
    if (blob.size !== pkg.bytes) throw new Error("下载长度与已保存结果包不符");
    const bytes = await blob.arrayBuffer();
    const hash = Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    )
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    if (hash !== pkg.sha256) throw new Error("下载内容与已保存结果包不符");
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `clao-result-${id}.zip`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setMessage("完整结果包已校验，已交给浏览器保存。");
  };
  return (
    <details
      className="mt-3"
      onToggle={(e) => setExpanded(e.currentTarget.open)}
      data-testid="clao-result-center"
    >
      <summary className="cursor-pointer py-1">结果与验收材料</summary>
      <div className="space-y-3 py-2">
        {result.isFetching && <p role="status">正在读取固定成果…</p>}
        {result.error && (
          <p role="alert" className="text-destructive">
            {result.error instanceof Error
              ? result.error.message
              : "结果读取失败"}
          </p>
        )}
        {value && (
          <>
            <p className={value.status === "ok" ? "" : "text-amber-600"}>
              {statusLabels[value.status] || value.status}
              {value.reason ? " · " + value.reason : ""}
            </p>
            <p>
              {m.coordinatorId
                ? "子任务成果；整体最终验收请查看所属任务"
                : value.evidence?.mission
                  ? value.evidence.mission.accepted
                    ? "通过最终验收"
                    : ["FAILED", "CANCELLED", "HUMAN"].includes(
                          value.evidence.mission.state,
                        )
                      ? "未通过最终验收"
                      : "尚未通过最终验收"
                  : "历史未提供最终验收事实"}
            </p>
            {value.location.path && (
              <div>
                <p className="break-all">{value.location.path}</p>
                <p className="text-muted-foreground">
                  {["available", "ok"].includes(value.location.status)
                    ? "结果目录可用"
                    : "原结果目录不可用；历史验收结论不因此改变"}
                </p>
              </div>
            )}
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                disabled={
                  !!busy || !["available", "ok"].includes(value.location.status)
                }
                className="rounded border border-border px-3 py-2"
                onClick={() =>
                  void action("copy", async () => {
                    await navigator.clipboard.writeText(value.location.path);
                    setMessage("结果路径已复制。");
                  })
                }
              >
                复制结果路径
              </button>
              <button
                type="button"
                disabled={
                  !!busy || !["available", "ok"].includes(value.location.status)
                }
                className="rounded border border-border px-3 py-2"
                onClick={() =>
                  void action("open", async () => {
                    await request(
                      "/missions/" + encodeURIComponent(id) + "/open-result",
                      {},
                    );
                    setMessage("已向系统请求打开对应结果目录。");
                  })
                }
              >
                打开结果目录
              </button>
              {!m.coordinatorId && (
                <button
                  type="button"
                  disabled={!!busy || !["ok", "saved"].includes(value.status)}
                  className="rounded border border-border px-3 py-2"
                  onClick={() =>
                    void action("export", async () => {
                      const { package: pkg } = await request<{
                        package: ResultPackage;
                      }>("/missions/" + encodeURIComponent(id) + "/export", {});
                      await cache.invalidateQueries({
                        queryKey: ["clao-result", id],
                      });
                      await download(pkg);
                    })
                  }
                >
                  {busy === "export" ? "正在生成…" : "导出独立结果包"}
                </button>
              )}
              <button
                type="button"
                className="underline"
                disabled={!!busy || result.isFetching}
                onClick={() => void result.refetch()}
              >
                重新读取
              </button>
            </div>
            {message && <p role="status">{message}</p>}
            {error && (
              <p role="alert" className="whitespace-pre-wrap text-destructive">
                {error}
              </p>
            )}
            {value.exports?.map((pkg) => (
              <div
                className="rounded border border-border p-2"
                key={pkg.identity}
              >
                <p>
                  已保存结果包 · {pkg.created_at} ·{" "}
                  {(pkg.bytes / 1024).toFixed(1)} KB ·{" "}
                  {pkg.accepted ? "通过最终验收" : "未通过最终验收"}
                </p>
                {pkg.reason && <p>{pkg.reason}</p>}
                <button
                  type="button"
                  className="underline"
                  disabled={
                    !!busy ||
                    ["missing", "read_error"].includes(pkg.status || "")
                  }
                  onClick={() => void action("download", () => download(pkg))}
                >
                  下载已保存结果包
                </button>
              </div>
            ))}
            <section>
              <strong>文件变化</strong>
              {value.noChanges && value.status === "ok" && (
                <p>没有代码净变化。</p>
              )}
              <div className="space-y-2">
                {value.changes?.map((change, index) => (
                  <details
                    key={change.path + ":" + index}
                    className="rounded border border-border"
                  >
                    <summary className="cursor-pointer break-all p-2">
                      {(
                        {
                          add: "新增",
                          added: "新增",
                          A: "新增",
                          delete: "删除",
                          deleted: "删除",
                          D: "删除",
                          rename: "重命名",
                          renamed: "重命名",
                          R: "重命名",
                          copy: "复制",
                          C: "复制",
                        } as Record<string, string>
                      )[change.kind] || "修改"}{" "}
                      ·{" "}
                      {change.old_path && change.old_path !== change.path
                        ? change.old_path + " → "
                        : ""}
                      {change.path}
                    </summary>
                    {change.diff !== undefined ? (
                      <FrozenDiff change={change} missionId={id} />
                    ) : (
                      <p className="p-2 text-muted-foreground">
                        此文件未保存独立差异预览，请查看下方完整补丁预览或下载结果包。
                      </p>
                    )}
                  </details>
                ))}
              </div>
              {value.diff && (
                <details className="mt-2">
                  <summary className="cursor-pointer">
                    补丁文本预览
                    {value.diffTruncated ? "（展示已截断，下载补丁完整）" : ""}
                  </summary>
                  <pre className="max-h-80 overflow-auto whitespace-pre text-xs">
                    {value.diff}
                  </pre>
                </details>
              )}
            </section>
            <section>
              <strong>逐项验收</strong>
              <ul className="space-y-1">
                {value.evidence?.acceptance_criteria?.map((ac) => (
                  <li key={ac.id} className="break-words">
                    {ac.description} — {verdict(ac.verdict)}
                    {ac.note ? " · " + ac.note : ""}
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <strong>Gate</strong>
              <p>{verdict(value.evidence?.gates?.status)}</p>
              {value.evidence?.gates?.records?.map((gate, i) => (
                <details
                  className="mt-2 rounded border border-border p-2"
                  key={gate.id || i}
                >
                  <summary className="cursor-pointer break-words">
                    {gate.phase || "历史未提供阶段"} · {gate.command} — 整体{" "}
                    {verdict(gate.overall)}
                  </summary>
                  <p>
                    命令 {verdict(gate.command_status)} · exit{" "}
                    {gate.exit_code ?? "unknown"}
                  </p>
                  <p>
                    完整性 {verdict(gate.integrity?.status)} ·{" "}
                    {gate.integrity?.reason}
                  </p>
                  <pre className="overflow-auto whitespace-pre-wrap break-words text-xs">
                    {JSON.stringify(
                      { scope: gate.scope, task: gate.task_id },
                      null,
                      2,
                    )}
                  </pre>
                </details>
              ))}
            </section>
            <section>
              <strong>Verifier</strong>
              <p>
                {verdict(
                  value.evidence?.verifier?.record?.verdict ||
                    value.evidence?.verifier?.status,
                )}
              </p>
              <details>
                <summary>复核记录</summary>
                <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words text-xs">
                  {JSON.stringify(
                    value.evidence?.verifier?.record ?? "历史未提供",
                    null,
                    2,
                  )}
                </pre>
              </details>
            </section>
            <details>
              <summary>基线与结果标识</summary>
              <p className="break-all">
                {value.baseCommit || "历史缺失"} →{" "}
                {value.resultCommit || "尚无固定成果"}
              </p>
              <p>
                独立结果包不包含完整基线或项目依赖；在符合包内说明的基线副本上应用，不自动写回原项目。
              </p>
            </details>
          </>
        )}
      </div>
    </details>
  );
}
