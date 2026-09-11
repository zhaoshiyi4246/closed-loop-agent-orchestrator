import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import type { Mission } from "./CLAOAcceptance";
import { CLAORunView, runNodes } from "./CLAORunView";
import { CLAOSource } from "./CLAOSource";
import { CLAOResults } from "./CLAOResults";
import { CLAOLegacy } from "./CLAOLegacy";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./CLAOAcceptance", () => ({ request: api }));
vi.mock("../lib/api-client", () => ({
  getApiBaseUrl: () => "http://127.0.0.1:7312",
  hasTrustedApiBaseUrl: () => true,
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
const mission = (id = "m") =>
  ({
    request: { id, projectId: "p", objective: "目标", criteria: [] },
    state: "RUNNING",
    reason: "等待当前 Worker",
    sessionId: "s",
    evidence: [],
    operations: [],
    checkpoint: { stage: "worker" },
    roles: { worker: { agent: "opencode", model: "", inherited: false } },
    repairs: 0,
    revision: 1,
    cancelRequested: false,
  }) as unknown as Mission;
const wrap = (ui: React.ReactNode) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    {ui}
  </QueryClientProvider>
);

it("运行过程按实际子任务事实同时高亮，未调用角色不伪造", async () => {
  const a = mission("a"),
    b = { ...mission("b"), state: "UNKNOWN" };
  const parent = {
    ...mission("parent"),
    state: "RUNNING",
    sessionId: undefined,
    checkpoint: { stage: "children" },
    subtasks: [a, b],
  };
  render(<CLAORunView m={parent} onOpenSession={vi.fn()} />);
  expect(runNodes(parent)[0].state).toBe("unused");
  expect(runNodes({...parent,checkpoint:{stage:"integration_gate"}}).find(n=>n.label.startsWith("Gate"))?.state).toBe("active");
  expect(runNodes({...a,activeWait:"approval"})[0]).toMatchObject({state:"waiting",reason:"等待用户审批"});
  expect(runNodes({...a,activeWait:"read_error"})[0]).toMatchObject({state:"unknown",reason:"执行状态读取失败"});
  const nodes = runNodes(a);
  expect(nodes.find((n) => n.label === "Worker")?.state).toBe("active");
  expect(runNodes(b)[0].state).toBe("unknown");
  expect(nodes.find((n) => n.label.startsWith("Auditor"))?.state).toBe(
    "unused",
  );
  await userEvent.click(screen.getAllByRole("button", { name: /Worker/ })[0]);
  expect(screen.getByText("此阶段未记录独立计时")).toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
});

it("来源重新读取撤销原确认，并明确展示排除事实", async () => {
  const source = {
    originalPath: "E:\\普通 中文",
    revision: "rev-a",
    policy: "当前磁盘",
    fileCount: 2,
    bytes: 90,
    excluded: [{ path: ".env", reason: "认证材料" }],
  };
  api.mockResolvedValue({ source });
  const onConfirm = vi.fn();
  render(
    wrap(<CLAOSource projectId="p" revision="rev-a" onConfirm={onConfirm} />),
  );
  expect(await screen.findByLabelText("使用上述当前内容快照")).toBeChecked();
  expect(screen.getByText(".env · 认证材料")).toBeInTheDocument();
  await userEvent.click(screen.getByText("重新读取"));
  expect(onConfirm).toHaveBeenCalledWith("");
  expect(
    api.mock.calls.every((c) => c[0] === "/projects/p/source" && !c[1]),
  ).toBe(true);
});

it("固定结果按目标任务读取，命令成功不能覆盖完整性失败", async () => {
  api.mockResolvedValue({
    result: {
      missionId: "b",
      status: "ok",
      location: { path: "E:\\result-b", status: "available" },
      changes: [],
      exports: [],
      noChanges: true,
      evidence: {
        mission: { state: "FAILED", accepted: false },
        acceptance_criteria: [
          { id: "AC1", description: "完整结果", verdict: "FAIL" },
        ],
        gates: {
          status: "ok",
          records: [
            {
              id: "g",
              phase: "Final Gate",
              command: "check",
              exit_code: 0,
              command_status: "PASS",
              integrity: { status: "FAIL", reason: "index 改变" },
              overall: "FAIL",
            },
          ],
        },
      },
      diff: "",
    },
  });
  render(wrap(<CLAOResults m={{ ...mission("b"), state: "FAILED" }} />));
  await userEvent.click(screen.getByText("结果与验收材料"));
  expect(await screen.findByText("未通过最终验收")).toBeInTheDocument();
  expect(
    screen.getByText(/Final Gate · check — 整体 未通过/),
  ).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/missions/b/result");
  expect(screen.getByText(/命令 通过 · exit 0/)).toBeInTheDocument();
  expect(screen.getByText(/完整性 未通过 · index 改变/)).toBeInTheDocument();
});

it("历史包仍可见，工作区失效不会伪称目录可打开", async () => {
  api.mockResolvedValue({
    result: {
      missionId: "m",
      status: "saved",
      location: { path: "E:\\gone", status: "missing" },
      changes: [],
      exports: [
        {
          identity: "saved",
          sha256: "f",
          bytes: 1,
          created_at: "today",
          accepted: false,
          status: "ready",
        },
      ],
      evidence: { mission: { state: "CANCELLED", accepted: false } },
      diff: "",
    },
  });
  render(wrap(<CLAOResults m={mission()} />));
  await userEvent.click(screen.getByText("结果与验收材料"));
  expect(await screen.findByText("下载已保存结果包")).toBeEnabled();
  expect(screen.getByText("打开结果目录")).toBeDisabled();
  expect(screen.getByText("未通过最终验收")).toBeInTheDocument();
});

it("切换任务后迟到的目录操作响应不会覆盖新任务", async () => {
  let release!: (value: unknown) => void;
  api.mockImplementation((path: string, body?: unknown) =>
    body
      ? new Promise((resolve) => (release = resolve))
      : Promise.resolve({
          result: {
            missionId: path.includes("/a/") ? "a" : "b",
            status: "ok",
            location: { path: "E:\\frozen", status: "available" },
            changes: [],
            exports: [],
            evidence: {},
            diff: "",
          },
        }),
  );
  const client = new QueryClient();
  const view = (id: string) => (
    <QueryClientProvider client={client}>
      <CLAOResults key={id} m={mission(id)} />
    </QueryClientProvider>
  );
  const r = render(view("a"));
  await userEvent.click(screen.getByText("结果与验收材料"));
  await userEvent.click(await screen.findByText("打开结果目录"));
  r.rerender(view("b"));
  await userEvent.click(screen.getByText("结果与验收材料"));
  await act(async () => release({ location: {} }));
  expect(
    screen.queryByText("已向系统请求打开对应结果目录。"),
  ).not.toBeInTheDocument();
  expect(api.mock.calls.filter((c) => c[1]).map((c) => c[0])).toEqual([
    "/missions/a/open-result",
  ]);
});

it("旧历史只在显式读取路径后导入，不自动寻找用户配置", async () => {
  api.mockResolvedValue({
    histories: [],
    connections: [],
    configurations: [],
    issues: [],
  });
  render(wrap(<CLAOLegacy />));
  expect(api).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText("旧 CLAO 历史与连接"));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/imports"));
  fireEvent.change(screen.getByLabelText("旧配置文件"), {
    target: { value: "E:\\isolated\\default.yaml" },
  });
  await userEvent.click(screen.getByText("读取并导入所选内容"));
  expect(api).toHaveBeenCalledWith("/imports", {
    configPath: "E:\\isolated\\default.yaml",
    historyPath: undefined,
  });
});

it("子任务成果不冒充整体最终验收，也不能单独导出", async () => {
  api.mockResolvedValue({result:{missionId:"child",status:"ok",location:{path:"E:/child",status:"available"},changes:[],exports:[],noChanges:true,evidence:{mission:{state:"DONE",accepted:false}},diff:""}});
  render(wrap(<CLAOResults m={{...mission("child"),state:"DONE",coordinatorId:"parent"}}/>));
  await userEvent.click(screen.getByText("结果与验收材料"));
  expect(await screen.findByText("子任务成果；整体最终验收请查看所属任务")).toBeInTheDocument();
  expect(screen.queryByText("通过最终验收")).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"导出独立结果包"})).not.toBeInTheDocument();
});
