import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "./CLAOAcceptance";

export type ImportedConnection = {
  authRevision?: number;
  authPending?: boolean;
  id: string;
  name: string;
  service: string;
  model: string;
  endpoint: string;
  billing: string;
  compatible: boolean;
  reason?: string;
  roles: string[];
};
type History = {
  id: string;
  originalId: string;
  sourceVersion: string;
  objective: string;
  state: string;
  reason: string;
  project: string;
  source?: unknown;
  base?: string;
  resultHead?: string;
  criteria?: unknown;
  gates?: unknown;
  verification?: unknown;
  limitations?: string[];
  importedAt: string;
};
export type ImportedDefaults = {
  gateTimeout?: number;
  maxTasks?: number;
  maxRepairs?: number;
  maxReplans?: number;
  agent?: string;
  model?: string;
  roles?: Record<
    string,
    { connectionId?: string; agent?: string; model?: string }
  >;
};
export type LegacyProjection = {
  histories: { id: string; document: History }[];
  connections: ImportedConnection[];
  configurations: {
    id: string;
    document: { name: string; values: ImportedDefaults; warnings?: string[] };
  }[];
  issues?: string[];
};
export const legacyQuery = {
  queryKey: ["clao-imports"],
  queryFn: () => request<LegacyProjection>("/imports"),
  retry: false,
  refetchOnWindowFocus: false,
};

function ConnectionCredential({
  connection,
}: {
  connection: ImportedConnection;
}) {
  const cache = useQueryClient();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const save = async () => {
    if (busy || !key.trim()) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await request(
        "/imports/" + encodeURIComponent(connection.id) + "/credential",
        { apiKey: key },
      );
      setKey("");
      await cache.invalidateQueries({ queryKey: ["clao-imports"] });
      setMessage("已配置。尚未向服务发送测试请求。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "凭据保存失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <details
      className="mt-2"
      onToggle={(e) => {
        if (!e.currentTarget.open) setKey("");
      }}
    >
      <summary className="cursor-pointer">连接 / 更新 API Key</summary>
      <div className="mt-2 space-y-2">
        {connection.authPending && (
          <p role="status" className="text-amber-600">
            上次凭据保存尚未确认。请重新连接；当前连接不能用于新任务。
          </p>
        )}
        <p>{connection.service} · 标准 API</p>
        <input
          type="password"
          autoComplete="new-password"
          aria-label={connection.name + " API Key"}
          className="w-full rounded border border-border bg-background p-2"
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
        <button
          type="button"
          className="rounded border border-border px-3 py-2"
          disabled={busy || !key.trim()}
          onClick={() => void save()}
        >
          保存到系统凭据
        </button>
        {message && <p role="status">{message}</p>}
        {error && (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        )}
      </div>
    </details>
  );
}

export function CLAOLegacy() {
  const cache = useQueryClient();
  const [opened, setOpened] = useState(false);
  const records = useQuery({ ...legacyQuery, enabled: opened });
  const [configPath, setConfigPath] = useState("");
  const [historyPath, setHistoryPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [issues, setIssues] = useState<string[]>([]);
  const run = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    setIssues([]);
    try {
      const result = await request<LegacyProjection>("/imports", {
        configPath: configPath.trim() || undefined,
        historyPath: historyPath.trim() || undefined,
      });
      setIssues(result.issues || []);
      await cache.invalidateQueries({ queryKey: ["clao-imports"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <details
      className="mt-2"
      onToggle={(e) => setOpened(e.currentTarget.open)}
      data-testid="clao-legacy"
    >
      <summary className="cursor-pointer">旧 CLAO 历史与连接</summary>
      <div className="space-y-3 py-3">
        <p>
          只读取你指定的旧配置或运行记录，不迁移登录令牌。旧任务作为只读记录保留。
        </p>
        <label className="block">
          旧配置文件
          <input
            aria-label="旧配置文件"
            value={configPath}
            onChange={(e) => setConfigPath(e.target.value)}
            placeholder="default.yaml 的完整路径"
            className="mt-1 w-full rounded border border-border bg-background p-2"
          />
        </label>
        <label className="block">
          旧运行目录或数据库
          <input
            aria-label="旧运行目录或数据库"
            value={historyPath}
            onChange={(e) => setHistoryPath(e.target.value)}
            placeholder="runtime 目录或 state.db 的完整路径"
            className="mt-1 w-full rounded border border-border bg-background p-2"
          />
        </label>
        <button
          type="button"
          className="rounded border border-border px-3 py-2"
          disabled={busy || (!configPath.trim() && !historyPath.trim())}
          onClick={() => void run()}
        >
          {busy ? "正在导入…" : "读取并导入所选内容"}
        </button>
        {(error || records.error) && (
          <p role="alert" className="whitespace-pre-wrap text-destructive">
            {error ||
              (records.error instanceof Error
                ? records.error.message
                : "导入记录读取失败")}
          </p>
        )}
        {issues.map((issue, i) => (
          <p role="status" className="break-words text-amber-600" key={i}>
            {issue}
          </p>
        ))}
        {records.data?.connections.map((c) => (
          <div key={c.id} className="rounded border border-border p-2">
            <strong>
              {c.name} · {c.service}
            </strong>
            <p>
              {c.model} ·{" "}
              {c.billing === "standard_api" ? "标准 API" : c.billing}
            </p>
            <p>
              {c.authPending ? "凭据保存待确认，请重新连接后再选择本连接。" : c.compatible
                ? "可用于语义角色；运行前仍需确认外发范围"
                : (c.reason || "无法映射") +
                  "；请在旧配置中新建不同名称的标准 API 连接，再显式导入；已有连接与冻结任务不会被覆盖。也可在任务角色中选择原生执行器。"}
            </p>
            {c.compatible && <ConnectionCredential key={c.id} connection={c} />}
          </div>
        ))}
        {records.data?.configurations?.map((c) => (
          <details key={c.id}>
            <summary>已读取的兼容配置 · {c.document.name}</summary>
            <p>这些值供查阅，不覆盖当前项目或已冻结任务。</p>
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words text-xs">
              {JSON.stringify(c.document.values, null, 2)}
            </pre>
            {c.document.warnings?.map((w) => (
              <p key={w}>{w}</p>
            ))}
          </details>
        ))}
        {records.data?.histories.map((item) => {
          const h = item.document;
          return (
            <details className="rounded border border-border p-2" key={item.id}>
              <summary className="cursor-pointer break-words">
                {h.objective || h.originalId} · {h.state} · 旧记录只读
              </summary>
              <p className="whitespace-pre-wrap break-words">{h.reason}</p>
              <p>
                {h.project} · 来源版本 {h.sourceVersion}
              </p>
              {h.limitations?.map((l) => (
                <p key={l}>{l}</p>
              ))}
              <details>
                <summary>原验收与来源事实</summary>
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">
                  {JSON.stringify(
                    {
                      criteria: h.criteria,
                      gates: h.gates,
                      verification: h.verification,
                      source: h.source,
                      base: h.base,
                      resultHead: h.resultHead,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </details>
          );
        })}
      </div>
    </details>
  );
}
