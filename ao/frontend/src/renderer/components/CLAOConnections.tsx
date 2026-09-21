import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "./CLAOAcceptance";
import { CLAOLegacy, ConnectionCredential, legacyQuery, type ImportedConnection } from "./CLAOLegacy";

type Service = { id: string; name: string; billing: string; models: { id: string; label: string }[]; supportsCustomModel?: boolean };

export function CLAOConnections() {
  const cache = useQueryClient();
  const connections = useQuery(legacyQuery);
  const catalog = useQuery({ queryKey: ["clao-connection-catalog"], queryFn: () => request<{ services: Service[] }>("/connections/catalog"), retry: false });
  const [adding, setAdding] = useState(false);
  const [id, setId] = useState(() => crypto.randomUUID());
  const [name, setName] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [model, setModel] = useState("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<ImportedConnection>();
  const [uncertain, setUncertain] = useState(false);
  const service = catalog.data?.services?.find(s => s.id === serviceId);
  const save = async () => {
    if (busy || !service || !name.trim() || !model.trim()) return;
    setBusy(true); setError("");
    try {
      const result = await request<{ connection: ImportedConnection }>("/connections", { id, name: name.trim(), service: service.id, model: model.trim() });
      setCreated(result.connection); setAdding(false); setUncertain(false);
      setId(crypto.randomUUID()); setName(""); setModel(""); setSearch("");
      await cache.invalidateQueries({ queryKey: ["clao-imports"] });
    } catch (e) {
      const status = (e as { status?: number })?.status;
      setUncertain(was => was || !(status && status >= 400 && status < 500));
      setError(e instanceof Error ? e.message : "保存结果未确认");
    } finally { setBusy(false); }
  };
  return <section className="space-y-4 text-sm" data-testid="clao-connections">
    <p className="text-muted-foreground">为规划、诊断和最终复核配置标准 API。执行任务继续使用原生模型与账号。</p>
    <button type="button" className="rounded-md border border-border px-3 py-2" onClick={() => setAdding(!adding)}>{adding ? "收起新连接" : "新建模型连接"}</button>
    {adding && <div className="space-y-3 rounded-lg border border-border p-3">
      <label className="block">连接名称<input aria-label="连接名称" className="mt-1 w-full rounded border border-border bg-background p-2" value={name} disabled={busy || uncertain} onChange={e => setName(e.target.value)} /></label>
      <label className="block">服务<select aria-label="模型服务" className="mt-1 w-full rounded border border-border bg-background p-2" value={serviceId} disabled={busy || uncertain} onChange={e => { setServiceId(e.target.value); setModel(""); setSearch(""); }}><option value="">选择服务</option>{catalog.data?.services?.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
      {service && <><label className="block">搜索型号<input aria-label="搜索 API 型号" value={search} disabled={busy || uncertain} onChange={e => setSearch(e.target.value)} className="mt-1 w-full rounded border border-border bg-background p-2" placeholder="输入型号名称" /></label>
        <div className="flex max-h-40 flex-wrap gap-2 overflow-auto" role="group" aria-label="常用 API 型号">{service.models.filter(m => `${m.id} ${m.label}`.toLowerCase().includes(search.toLowerCase())).map(m => <button type="button" key={m.id} disabled={busy || uncertain} aria-pressed={model === m.id} className={"rounded border px-3 py-2 " + (model === m.id ? "border-primary bg-primary/10" : "border-border")} onClick={() => setModel(m.id)}>{m.label}</button>)}</div>
        {service.supportsCustomModel && <details><summary className="cursor-pointer">填写其他型号</summary><input aria-label="自定义 API 型号" value={model} disabled={busy || uncertain} onChange={e => setModel(e.target.value)} className="mt-2 w-full rounded border border-border bg-background p-2" /><p>具体型号权限和效果以实际服务为准；不会自动更换服务。</p></details>}
        <p>所选型号：{model || "尚未选择"} · 标准 API 计费</p>
      </>}
      <button type="button" className="rounded border border-border px-3 py-2" disabled={busy || !service || !name.trim() || !model.trim()} onClick={() => void save()}>{busy ? "正在保存…" : uncertain ? "确认同一连接的保存结果" : "保存连接"}</button>
      {uncertain && <p>保留本次保存身份。再次确认不会创建重复连接。</p>}
      {error && <p role="alert" className="break-words text-destructive">{error}</p>}
    </div>}
    {(catalog.isError || connections.isError) && <p role="alert" className="text-destructive">连接信息读取失败。<button type="button" className="ml-2 underline" onClick={() => { void catalog.refetch(); void connections.refetch(); }}>重新读取</button></p>}
    {created && <p role="status">已保存 {created.name}。请配置系统凭据；尚未发送模型请求。</p>}
    {connections.data?.connections?.map(c => <div key={c.id} className="rounded-lg border border-border p-3"><strong>{c.name}</strong><p className="break-words">{catalog.data?.services.find(s => s.id === c.service)?.name || "标准 API 服务"} · {c.model} · 标准 API</p><p className="text-muted-foreground">{c.authPending ? "凭据保存待确认" : c.compatible ? "保存配置不代表真实服务已验证" : c.reason || "需要重新配置"}</p>{c.compatible && <ConnectionCredential connection={c}/>}</div>)}
    <CLAOLegacy />
  </section>;
}
