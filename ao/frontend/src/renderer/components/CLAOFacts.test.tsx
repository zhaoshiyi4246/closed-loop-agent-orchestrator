import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Mission } from "./CLAOAcceptance";
import { acceptanceFacts } from "./CLAOFacts";
import { CLAORunView, runNodes } from "./CLAORunView";

afterEach(cleanup);
const mission = (): Mission => ({ request: { id: "m", projectId: "p", objective: "测试任务", criteria: [], agent: "codex", model: "", allowedPaths: [], forbiddenPaths: [], gateCommands: [], maxRepairs: 0, gateTimeout: 20 }, state: "FAILED", reason: "语义复核未通过", revision: 1, repairs: 0, cancelRequested: false, operations: [], checkpoint: { stage: "final" }, evidence: [{ ok: false, scopeOK: true, gate: { command_ok: true, integrity_ok: true }, paths: [], forbidden: [], outside: [], verification: { verdict: "FAIL", summary: "未满足目标", ac_checks: [] } }], roleCalls: [{ id: "v", role: "verifier", state: "VALIDATED", startedAt: "2026-09-21T00:00:00Z", choice: { agent: "codex", model: "", inherited: true }, result: { verdict: "FAIL" } }] });

it("语义失败不改写命令、范围和完整性事实", () => {
  const m = mission();
  expect(acceptanceFacts(m)).toMatchObject({ command: "done", scope: "done", integrity: "done", deterministic: "done", semantic: "failed" });
  expect(runNodes(m).find(n => n.id === "m:gate")?.state).toBe("done");
  expect(runNodes(m).find(n => n.id === "m:verifier")?.state).toBe("failed");
});

it.each(["command", "integrity", "scope", "collection"] as const)("%s 失败独立可见，模型通过不能覆盖", kind => {
  const m = mission();
  m.evidence[0].verification!.verdict = "PASS";
  if (kind === "command") m.evidence[0].gate!.command_ok = false;
  if (kind === "integrity") m.evidence[0].gate!.integrity_ok = false;
  if (kind === "scope") m.evidence[0].scopeOK = false;
  if (kind === "collection") m.evidence[0].readError = "读取失败";
  expect(acceptanceFacts(m)[kind]).toBe("failed");
  expect(acceptanceFacts(m).deterministic).toBe("failed");
  expect(acceptanceFacts(m).semantic).toBe("done");
});

it("最终复核完成但尚在检查程序结果时，不伪造模型在途活动", () => {
  const m = { ...mission(), state: "VERIFYING", checkpoint: { stage: "final", localState: "IN_FLIGHT" } };
  expect(runNodes(m).filter(n => n.state === "active").map(n => n.id)).toEqual(["m:gate"]);
  expect(runNodes({ ...m, checkpoint: { stage: "verify" }, roleCalls: [{ ...m.roleCalls![0], state: "RUNNING", result: undefined }] }).filter(n => n.state === "active").map(n => n.id)).toEqual(["m:verifier"]);
});

it("断连后所有在途节点显示最后已知状态，恢复才继续高亮", () => {
  const m = { ...mission(), state: "VERIFYING", checkpoint: { stage: "verify" }, evidence: [], roleCalls: [{ ...mission().roleCalls![0], state: "RUNNING", result: undefined }] };
  const ui = render(<CLAORunView m={m} readError onOpenSession={vi.fn()} />);
  expect(ui.container.querySelectorAll('[data-state="active"]')).toHaveLength(0);
  expect(screen.getByText(/最后已知记录，非实时活動|最后已知记录，非实时活动/)).toBeInTheDocument();
  ui.rerender(<CLAORunView m={m} onOpenSession={vi.fn()} />);
  expect(ui.container.querySelectorAll('[data-state="active"]')).toHaveLength(1);
});

it("缺失布尔字段不产生成功，VALIDATED 缺失 verdict 也不产生成功", () => {
  const m = mission(); m.evidence = [{ ...m.evidence[0], verification: undefined, gate: {} as never }]; m.roleCalls![0].result = {};
  expect(acceptanceFacts(m)).toMatchObject({ command: "unknown", integrity: "unknown", deterministic: "unknown", semantic: "unknown" });
});
