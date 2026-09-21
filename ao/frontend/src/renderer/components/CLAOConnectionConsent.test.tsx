import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { NewTaskDialog } from "./NewTaskDialog";
const { api, create } = vi.hoisted(() => ({ api: vi.fn(), create: vi.fn() }));
vi.mock("./CLAOAcceptance", () => ({
  request: api,
  createAcceptance: create,
  AcceptanceForm: () => null,
  CLAOMissionDetail: ({
    onNewAttempt,
  }: {
    onNewAttempt: (v: unknown) => void;
  }) => (
    <button onClick={() => onNewAttempt({ id: "previous" })}>新的尝试</button>
  ),
}));
vi.mock("./CLAOSource", () => ({
  CLAOSource: ({ onConfirm }: { onConfirm: (r: string) => void }) => (
    <button onClick={() => onConfirm("confirmed-source")}>确认来源</button>
  ),
}));
vi.mock("./CLAORoleForm", () => ({
  CLAORoleForm: ({
    fields,
    onChange,
  }: {
    fields: Record<string, unknown>;
    onChange: (v: unknown) => void;
  }) => (
    <>
      <button
        onClick={() =>
          onChange({
            ...fields,
            roles: {
              verifier: { agent: "", model: "glm", connectionId: "glm" },
            },
          })
        }
      >
        选择 GLM
      </button>
      <button
        onClick={() =>
          onChange({
            ...fields,
            roles: {
              verifier: { agent: "", model: "kimi", connectionId: "kimi" },
            },
          })
        }
      >
        选择 Kimi
      </button>
    </>
  ),
}));
// The real submit boundary remains in NewTaskDialog. The native composer is
// isolated here so this case can control repeated submissions and project swaps.
vi.mock("./TaskComposer", () => ({
  TaskComposer: ({
    createClosedLoop,
    projectId,
  }: {
    createClosedLoop?: (v: unknown) => Promise<void>;
    projectId: string;
  }) => (
    <button
      onClick={() =>
        void createClosedLoop?.({
          projectId,
          brief: "目标",
          agent: "opencode",
          model: "native",
        }).catch(() => {})
      }
    >
      提交任务
    </button>
  ),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it("外发确认绑定项目、角色连接与新尝试；同草稿切页不失效", async () => {
  api.mockResolvedValue({
    histories: [],
    configurations: [],
    connections: [
      {
        id: "glm",
        name: "GLM",
        service: "bigmodel_general",
        model: "glm",
        endpoint: "https://bigmodel.invalid",
        billing: "standard_api",
        compatible: true,
      },
      {
        id: "kimi",
        name: "Kimi",
        service: "moonshot_cn",
        model: "kimi",
        endpoint: "https://kimi.invalid",
        billing: "standard_api",
        compatible: true,
      },
    ],
  });
  create.mockResolvedValue({ request: { id: "accepted" } });
  const client = new QueryClient();
  const view = (projectId: string, open = true) => (
    <QueryClientProvider client={client}>
      <NewTaskDialog
        open={open}
        projectId={projectId}
        onCreated={vi.fn()}
        onOpenChange={vi.fn()}
      />
    </QueryClientProvider>
  );
  const r = render(view("a"));
  const user = userEvent.setup();
  await user.click(screen.getByLabelText("CLAO 闭环验收"));
  await user.click(screen.getByText("选择 GLM"));
  await user.click(screen.getByText("确认来源"));
  const check = await screen.findByLabelText("同意本次外发材料");
  await user.click(check);
  r.rerender(view("a", false));
  r.rerender(view("a"));
  expect(screen.getByLabelText("同意本次外发材料")).toBeChecked();
  await user.click(screen.getByText("选择 Kimi"));
  expect(screen.getByLabelText("同意本次外发材料")).not.toBeChecked();
  await user.click(screen.getByLabelText("同意本次外发材料"));
  r.rerender(view("b"));
  expect(screen.getByLabelText("同意本次外发材料")).not.toBeChecked();
  await user.click(screen.getByText("提交任务"));
  expect(create).not.toHaveBeenCalled();
  await user.click(screen.getByText("确认来源"));
  await user.click(screen.getByLabelText("同意本次外发材料"));
  await user.click(screen.getByText("提交任务"));
  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  expect(create.mock.calls[0][1]).toMatchObject({
    externalServiceConsent: ["moonshot_cn"],
    sourceRevision: "confirmed-source",
    roles: { verifier: { connectionId: "kimi" } },
  });
  expect(create.mock.calls[0][2].projectId).toBe("b");
  await user.click(screen.getByText("新的尝试"));
  expect(screen.getByLabelText("同意本次外发材料")).not.toBeChecked();
});
