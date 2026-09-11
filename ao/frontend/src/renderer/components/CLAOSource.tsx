import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request } from "./CLAOAcceptance";

export type SourcePreview = {
  originalPath: string;
  projectPath?: string;
  revision: string;
  base?: string;
  policy: string;
  fileCount: number;
  bytes: number;
  excluded: { path: string; reason: string }[];
};

export function CLAOSource({
  projectId,
  revision,
  onConfirm,
}: {
  projectId: string;
  revision?: string;
  onConfirm: (revision: string) => void;
}) {
  const [error, setError] = useState("");
  const source = useQuery({
    queryKey: ["clao-source", projectId],
    queryFn: () =>
      request<{ source: SourcePreview }>(
        "/projects/" + encodeURIComponent(projectId) + "/source",
      ),
    enabled: !!projectId,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const value = source.data?.source;
  const refresh = async () => {
    setError("");
    onConfirm("");
    try {
      await source.refetch({ throwOnError: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "来源读取失败");
    }
  };
  return (
    <section
      className="mx-4 my-3 rounded-md border border-border p-3 text-sm"
      data-testid="clao-source-confirm"
    >
      <div className="flex items-center justify-between gap-3">
        <strong>本次来源</strong>
        <button
          type="button"
          className="underline"
          disabled={source.isFetching}
          onClick={() => void refresh()}
        >
          {source.isFetching ? "正在读取…" : "重新读取"}
        </button>
      </div>
      {value && (
        <>
          <p className="my-1 break-all">{value.originalPath}</p>
          <p>
            {value.fileCount} 个文件 · {(value.bytes / 1024).toFixed(1)} KB ·
            当前磁盘内容
          </p>
          <details className="my-2">
            <summary className="cursor-pointer">来源范围与排除项</summary>
            <p>
              包含当前未提交修改，在 CLAO 私有工作区执行；不提交或改写原目录。
            </p>
            <p className="break-words">{value.policy}</p>
            <ul className="max-h-32 overflow-auto">
              {value.excluded?.map((item) => (
                <li className="break-all" key={item.path}>
                  {item.path} · {item.reason}
                </li>
              ))}
            </ul>
          </details>
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={revision === value.revision}
              disabled={source.isFetching}
              onChange={(e) =>
                onConfirm(e.target.checked ? value.revision : "")
              }
            />
            使用上述当前内容快照
          </label>
        </>
      )}
      {!projectId && <p>先选择项目。</p>}
      {(error || source.error) && (
        <p role="alert" className="whitespace-pre-wrap text-destructive">
          {error ||
            (source.error instanceof Error
              ? source.error.message
              : "来源读取失败")}
        </p>
      )}
    </section>
  );
}
