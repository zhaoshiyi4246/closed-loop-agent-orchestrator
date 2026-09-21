import type { Mission } from "./CLAOAcceptance";

export type FactState = "done" | "failed" | "unknown" | "unused";
export const factLabel = (state: FactState) => ({ done: "通过", failed: "未通过", unknown: "尚未确认", unused: "尚未检查" })[state];
const booleanFact = (value?: boolean): FactState => value === true ? "done" : value === false ? "failed" : "unknown";

// Evidence.ok is the combined program + semantic verdict. Never use it to
// infer the outcome of an individual deterministic check.
export function acceptanceFacts(m: Mission) {
  const latest = m.evidence.at(-1);
  const gate = latest?.gate;
  const command = gate ? booleanFact(gate.command_ok) : latest ? "unknown" : "unused";
  const integrity = gate ? booleanFact(gate.integrity_ok) : latest ? "unknown" : "unused";
  const scope = latest?.readError ? "unknown" : latest ? booleanFact(latest.scopeOK) : "unused";
  const collection: FactState = latest?.readError ? "failed" : latest ? "done" : "unused";
  const checks = [command, integrity, scope, collection];
  const deterministic: FactState = checks.includes("failed") ? "failed" : checks.every(s => s === "done") ? "done" : latest ? "unknown" : "unused";
  const call = m.roleCalls?.filter(c => c.role === "verifier").at(-1);
  const verification = latest?.verification;
  // Only a validated structured response is a semantic conclusion.
  const verdict = verification?.verdict || (call?.state === "VALIDATED" ? call.result?.verdict : undefined);
  const semantic: FactState = verdict === "PASS" ? "done" : verdict === "FAIL" ? "failed" : call || m.verifierSessionId ? "unknown" : "unused";
  return { latest, command, integrity, scope, collection, deterministic, semantic, verification, verifierCall: call };
}

export function readableRunReason(reason: string) {
  return reason.replace(/\bWorker\b/g, "执行任务").replace(/\bGate\b/g, "检查")
    .replace(/\bVerifier\b/g, "独立复核").replace(/\bMission\b/g, "整体任务").replace(/\bPASS\b/g, "通过").replace(/独立\s+独立复核/g, "独立复核");
}
