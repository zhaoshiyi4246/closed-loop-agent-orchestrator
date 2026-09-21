import { useState } from "react";
import type { Mission } from "./CLAOAcceptance";
import { acceptanceFacts, factLabel, readableRunReason } from "./CLAOFacts";

type NodeState =
  | "active"
  | "waiting"
  | "done"
  | "failed"
  | "unknown"
  | "unused";
type RunNode = {
  id: string;
  label: string;
  state: NodeState;
  reason?: string;
  session?: string;
  facts: unknown;
  startedAt?: string;
  finishedAt?: string;
};
const labels: Record<NodeState, string> = {
  active: "正在执行",
  waiting: "等待处理",
  done: "已完成",
  failed: "未通过",
  unknown: "尚未确认",
  unused: "未调用",
};
const tones: Record<NodeState, string> = {
  active: "border-blue-500 bg-blue-500/10 ring-1 ring-blue-500/30",
  waiting: "border-amber-500 bg-amber-500/10",
  done: "border-green-600 bg-green-600/10",
  failed: "border-destructive bg-destructive/10",
  unknown: "border-amber-500 bg-amber-500/10",
  unused: "border-border text-muted-foreground",
};
const activeStates = new Set([
  "SPAWNING",
  "RUNNING",
  "STOPPING",
  "REPAIRING",
  "REPLANNING",
]);

export function runNodes(m: Mission, readError = false): RunNode[] {
  const facts = acceptanceFacts(m);
  const current = (active: boolean, fallback: NodeState): NodeState =>
    active
      ? readError || m.activeWait === "read_error" || ["UNKNOWN", "DONE", "FAILED", "CANCELLED"].includes(m.state)
        ? "unknown"
        : m.cancelRequested ||
            m.activeWait ||
            m.state === "PAUSED" ||
            m.state === "HUMAN"
          ? "waiting"
          : m.state === "UNKNOWN"
            ? "unknown"
            : "active"
      : fallback;
  const workerOps = m.operations.filter((op) => op.target === m.sessionId);
  const worker: RunNode = {
    id: m.request.id + ":worker",
    label: "执行任务",
    state: current(
      ((!!m.sessionId || m.checkpoint?.stage === "worker") &&
        activeStates.has(m.state)) ||
        (m.checkpoint?.stage === "worker" &&
          ["PAUSED", "UNKNOWN"].includes(m.state)),
      m.sessionId
        ? workerOps.some((op) => op.state === "UNKNOWN")
          ? "unknown"
          : m.evidence.length
            ? "done"
            : "unknown"
        : m.checkpoint
          ? "unused"
          : "unknown",
    ),
    reason:
      (
        {
          approval: "等待用户审批",
          user_input: "等待用户回答",
          read_error: "执行状态读取失败",
        } as Record<string, string>
      )[m.activeWait || ""] ||
      (activeStates.has(m.state) ? m.reason : undefined),
    session: m.sessionId,
    facts: { operations: workerOps, repairs: m.repairs, replans: m.replans },
  };
  const gates = m.evidence.filter((e) => e.gate);
  const gate: RunNode = {
    id: m.request.id + ":gate",
    label: "命令与范围检查",
    state: current(
      (["gate", "recheck", "integration_gate"].includes(
        m.checkpoint?.stage || "",
      ) || (m.checkpoint?.stage === "final" && m.checkpoint.localState === "IN_FLIGHT")) && !["DONE", "FAILED", "CANCELLED", "HUMAN"].includes(m.state),
      facts.deterministic,
    ),
    reason: `命令：${factLabel(facts.command)} · 完整性：${factLabel(facts.integrity)} · 范围：${factLabel(facts.scope)} · 取证：${factLabel(facts.collection)}`,
    facts: gates.map((e) => ({
      ok: e.ok,
      scopeOK: e.scopeOK,
      readError: e.readError,
      gate: e.gate,
      records: e.records,
      paths: e.paths,
      forbidden: e.forbidden,
      outside: e.outside,
    })),
  };
  const roles: RunNode[] = ["auditor", "planner"].flatMap<RunNode>((role) => {
    const calls = m.roleCalls?.filter((call) => call.role === role) ?? [];
    return calls.length
      ? calls.map((call) => ({
          id: call.id,
          label: role === "auditor" ? "异常诊断" : "规划决策",
          state:
            current(["STARTING", "RUNNING"].includes(call.state), (
              {
                STARTING: "active",
                RUNNING: "active",
                RECEIVED: "waiting",
                VALIDATED: "done",
                PROTOCOL_ERROR: "failed",
                FAILED: "failed",
                UNKNOWN: "unknown",
                CANCELLED: "waiting",
              } as Record<string, NodeState>
            )[call.state] || "unknown"),
          session: call.sessionId,
          reason: call.error,
          startedAt: call.startedAt,
          finishedAt: call.finishedAt,
          facts: {
            result: call.result,
            decisions: m.decisions?.filter(
              (d) => d.auditId === call.id || d.plannerId === call.id,
            ),
          },
        }))
      : [
          {
            id: m.request.id + ":" + role,
            label: role === "auditor" ? "异常诊断" : "规划决策",
            state: m.roles ? "unused" : "unknown",
            reason: m.roles ? undefined : "历史未提供调用记录",
            facts: [],
          },
        ];
  });
  const integration: RunNode = {
    id: m.request.id + ":integration",
    label: m.coordinatorId ? "固定子任务结果" : "集成与固定结果",
    state: current(
      ["materialize", "integrate"].includes(m.checkpoint?.stage || "") &&
        !["DONE", "FAILED", "CANCELLED", "HUMAN"].includes(m.state),
      m.resultHead ? "done" : m.checkpoint ? "unused" : "unknown",
    ),
    facts: {
      resultHead: m.resultHead,
      operations: m.operations.filter((op) =>
        /material|integrat/i.test(op.kind),
      ),
    },
  };
  const verifierCalls =
    m.roleCalls?.filter((call) => call.role === "verifier") ?? [];
  const verifier: RunNode = {
    id: m.request.id + ":verifier",
    label: "独立最终复核",
    state: current(
      verifierCalls.some(c => ["STARTING", "RUNNING"].includes(c.state)),
      verifierCalls.length
        ? verifierCalls.at(-1)?.state === "VALIDATED"
          ? facts.semantic
          : verifierCalls.at(-1)?.state === "RECEIVED"
            ? "waiting"
          : verifierCalls.at(-1)?.state === "UNKNOWN"
            ? "unknown"
            : "failed"
        : m.verifierSessionId
          ? "unknown"
          : "unused",
    ),
    session: m.verifierSessionId,
    reason: facts.semantic === "failed" ? "语义复核未通过；命令、完整性与范围结论分别保留。" : verifierCalls.at(-1)?.error,
    facts: verifierCalls.map((c) => ({
      state: c.state,
      result: c.result,
      error: c.error,
    })),
    startedAt: verifierCalls.at(-1)?.startedAt,
    finishedAt: verifierCalls.at(-1)?.finishedAt,
  };
  return [worker, gate, ...roles, integration, verifier];
}

export function CLAORunView({
  m,
  onOpenSession,
  readError = false,
}: {
  m: Mission;
  onOpenSession: (id: string) => void;
  readError?: boolean;
}) {
  const [selected, setSelected] = useState<string>();
  const [showUnused, setShowUnused] = useState(false);
  const parentNodes = runNodes(m, readError);
  const planningIds = new Set(m.roleCalls?.filter(c => c.role === "planner").map(c => c.id));
  const groups = m.subtasks?.length ? [
    { mission: m, label: "任务规划", nodes: parentNodes.filter(n => planningIds.has(n.id)), showPath: false },
    ...m.subtasks.map(child => ({ mission: child, label: child.request.objective, nodes: runNodes(child, readError), showPath: true })),
    { mission: m, label: "整体集成与验收", nodes: [parentNodes.find(n => n.id === m.request.id + ":integration")!, parentNodes.find(n => n.id === m.request.id + ":gate")!, ...parentNodes.filter(n => !planningIds.has(n.id) && ![m.request.id + ":worker", m.request.id + ":integration", m.request.id + ":gate"].includes(n.id))], showPath: true },
  ] : [{ mission: m, label: "本次执行", nodes: parentNodes, showPath: true }];
  const all = groups.flatMap(g => g.nodes);
  const node = all.find((n) => n.id === selected);
  const recordedPath = (v: Mission) => {
    const steps: string[] = [];
    if (v.sessionId && v.evidence.some((e) => e.gate))
      steps.push("Worker → Gate");
    if (v.roleCalls?.some((c) => c.role === "auditor"))
      steps.push("Gate 异常 → Auditor");
    if (v.decisions?.some((d) => d.auditId && d.plannerId))
      steps.push("Auditor → Planner");
    for (const decision of v.decisions ?? []) {
      if (
        decision.state === "APPLIED" &&
        ["SEND_LOCAL_FIX", "REPLAN_SPAWN"].includes(decision.action || "")
      )
        steps.push(
          "Planner → Worker（" +
            (decision.action === "SEND_LOCAL_FIX" ? "局部修复" : "替换执行") +
            "）",
        );
    }
    if (v.resultHead)
      steps.push(
        v.subtasks?.length ? "子任务固定成果 → 集成" : "Gate → 固定结果",
      );
    if (v.resultHead && v.roleCalls?.some((c) => c.role === "verifier"))
      steps.push("固定结果 → Verifier");
    return steps;
  };
  return (
    <section className="mt-4 rounded-lg border border-border p-3" data-testid="clao-run-view" aria-label="运行过程">
      <div className="flex flex-wrap items-center justify-between gap-2"><strong>当前执行与待处理</strong><button type="button" className="text-xs text-muted-foreground underline" onClick={() => setShowUnused(!showUnused)}>{showUnused ? "隐藏未调用阶段" : "查看未调用阶段"}</button></div>
      {readError && <p role="status" className="mt-2 text-amber-600">连接中断 · 以下为最后已知记录，非实时活动。</p>}
      <div className="space-y-3 py-2">
        {groups.filter(g => showUnused || g.nodes.some(n => n.state !== "unused")).map((group) => (
          <div key={group.mission.request.id + group.label}>
            <p className="mb-2 break-words font-medium">{group.label}</p>
            <ol
              aria-label={group.label + "运行过程"}
              className="flex flex-wrap items-stretch gap-2"
            >
              {group.nodes.filter(n => showUnused || n.state !== "unused").map((n) => (
                <li key={n.id} className="min-w-0 basis-36 flex-1">
                  <button
                    type="button"
                    data-state={n.state}
                    aria-pressed={n.id === selected}
                    className={
                      "h-full w-full rounded-lg border p-3 text-left break-words focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary " +
                      tones[n.state]
                    }
                    onClick={() => setSelected(n.id)}
                  >
                    <span className="block font-medium">{n.label}</span>
                    <span className="text-xs">{labels[n.state]}</span>
                  </button>
                </li>
              ))}
            </ol>
            {group.showPath && !!recordedPath(group.mission).length && (
              <details className="mt-2 break-words text-xs text-muted-foreground"><summary className="cursor-pointer">查看已记录路径</summary><p aria-label="已记录的执行路径">{recordedPath(group.mission).join(" · ")}</p></details>
            )}
          </div>
        ))}
      </div>
      {node && (
        <section
          className="rounded-lg border border-border p-3"
          aria-label={node.label + "记录"}
        >
          <strong>
            {node.label} · {labels[node.state]}
          </strong>
          {node.reason && (
            <p className="whitespace-pre-wrap break-words">{readableRunReason(node.reason)}</p>
          )}
          {node.startedAt ? (
            <p>
              开始：{node.startedAt} ·{" "}
              {node.finishedAt
                ? `耗时 ${Math.max(0, (Date.parse(node.finishedAt) - Date.parse(node.startedAt)) / 1000).toFixed(1)} 秒`
                : "结束时间尚未提供"}
            </p>
          ) : (
            <p className="text-muted-foreground">此阶段未记录独立计时</p>
          )}
          {node.session && (
            <button
              type="button"
              className="my-2 underline"
              onClick={() => onOpenSession(node.session!)}
            >
              打开对应会话
            </button>
          )}
          <details>
            <summary className="cursor-pointer">高级：动作与验收证据</summary>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs">
              {JSON.stringify(node.facts, null, 2)}
            </pre>
          </details>
        </section>
      )}
    </section>
  );
}
