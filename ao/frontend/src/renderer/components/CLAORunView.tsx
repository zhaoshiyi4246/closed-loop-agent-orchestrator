import { useState } from "react";
import type { Mission } from "./CLAOAcceptance";

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
  active: "border-primary bg-primary/10",
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

export function runNodes(m: Mission): RunNode[] {
  const current = (active: boolean, fallback: NodeState): NodeState =>
    active
      ? m.activeWait === "read_error"
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
    label: "Worker",
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
    label: "Gate · 范围与完整性",
    state: current(
      ["gate", "recheck", "final", "integration_gate"].includes(
        m.checkpoint?.stage || "",
      ) && !["DONE", "FAILED", "CANCELLED", "HUMAN"].includes(m.state),
      gates.length
        ? gates.at(-1)?.ok
          ? "done"
          : "failed"
        : m.checkpoint
          ? "unused"
          : "unknown",
    ),
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
          label: role === "auditor" ? "Auditor · 诊断" : "Planner · 决策",
          state:
            (
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
            )[call.state] || "unknown",
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
            label: role === "auditor" ? "Auditor · 诊断" : "Planner · 决策",
            state: m.roles ? "unused" : "unknown",
            reason: m.roles ? undefined : "历史未提供调用记录",
            facts: [],
          },
        ];
  });
  const integration: RunNode = {
    id: m.request.id + ":integration",
    label: "集成与固定结果",
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
    label: "Verifier · 最终复核",
    state: current(
      m.state === "VERIFYING",
      verifierCalls.length
        ? verifierCalls.at(-1)?.state === "VALIDATED"
          ? verifierCalls.at(-1)?.result?.verdict === "FAIL"
            ? "failed"
            : "done"
          : verifierCalls.at(-1)?.state === "UNKNOWN"
            ? "unknown"
            : "failed"
        : m.verifierSessionId
          ? "unknown"
          : "unused",
    ),
    session: m.verifierSessionId,
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
}: {
  m: Mission;
  onOpenSession: (id: string) => void;
}) {
  const [selected, setSelected] = useState<string>();
  const groups = [
    ...(m.subtasks ?? []).map((child) => ({
      mission: child,
      label: child.request.objective,
    })),
    { mission: m, label: m.subtasks?.length ? "整体任务" : "本次执行" },
  ];
  const all = groups.flatMap((g) => runNodes(g.mission));
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
    <details className="mt-3" data-testid="clao-run-view">
      <summary className="cursor-pointer py-1">运行过程</summary>
      <div className="space-y-3 py-2">
        {groups.map((group) => (
          <div key={group.mission.request.id}>
            <p className="mb-2 break-words font-medium">{group.label}</p>
            <ol
              aria-label={group.label + "运行过程"}
              className="flex flex-wrap items-stretch gap-2"
            >
              {runNodes(group.mission).map((n) => (
                <li key={n.id} className="min-w-32 flex-1">
                  <button
                    type="button"
                    data-state={n.state}
                    aria-pressed={n.id === selected}
                    className={
                      "h-full w-full rounded-lg border p-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary " +
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
            {!!recordedPath(group.mission).length && (
              <p
                className="mt-2 break-words text-xs text-muted-foreground"
                aria-label="已记录的执行路径"
              >
                {recordedPath(group.mission).join(" · ")}
              </p>
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
            <p className="whitespace-pre-wrap break-words">{node.reason}</p>
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
              打开对应原生 Session
            </button>
          )}
          <details>
            <summary className="cursor-pointer">动作与验收证据</summary>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs">
              {JSON.stringify(node.facts, null, 2)}
            </pre>
          </details>
        </section>
      )}
    </details>
  );
}
