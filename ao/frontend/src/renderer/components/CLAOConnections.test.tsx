import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { CLAOConnections } from "./CLAOConnections";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./CLAOAcceptance", () => ({ request: api }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const catalog = { services: [{ id: "bigmodel_general", name: "智谱", billing: "standard_api", models: [{ id: "glm-5.3", label: "GLM-5.3" }, { id: "glm-4.7", label: "GLM-4.7" }] }] };
function setup(post: (body: unknown) => unknown) {
  api.mockImplementation(async (path: string, body?: unknown) => path === "/connections/catalog" ? catalog : path === "/connections" ? post(body) : { histories: [], configurations: [], connections: [] });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><CLAOConnections /></QueryClientProvider>);
}
async function fill() {
  await userEvent.click(screen.getByText("新建模型连接"));
  await userEvent.type(screen.getByLabelText("连接名称"), "我的智谱");
  await userEvent.selectOptions(screen.getByLabelText("模型服务"), "bigmodel_general");
  await userEvent.type(screen.getByLabelText("搜索 API 型号"), "5.3");
  expect(screen.queryByRole("button", { name: "GLM-4.7" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "GLM-5.3" }));
  await userEvent.click(screen.getByText("保存连接"));
}
it("型号来自服务目录；保存连接不发送凭据或模型请求", async () => {
  setup(body => ({ connection: body })); await fill();
  expect(await screen.findByText(/已保存 我的智谱/)).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/connections", { id: expect.any(String), name: "我的智谱", service: "bigmodel_general", model: "glm-5.3" });
  expect(api.mock.calls.every(([path]) => ["/imports", "/connections", "/connections/catalog"].includes(path))).toBe(true);
});
it.each([undefined, 503])("保存结果未确认（status %s）后使用同一身份和内容查询保存结果", async (status) => {
  let fail = true; setup(body => { if (fail) { fail = false; throw Object.assign(new Error("保存结果未确认"), { status }); } return { connection: body }; }); await fill();
  const retry = await screen.findByText("确认同一连接的保存结果");
  expect(screen.getByLabelText("连接名称")).toBeDisabled();
  expect(screen.getByLabelText("模型服务")).toBeDisabled();
  expect(screen.getByLabelText("搜索 API 型号")).toBeDisabled();
  expect(screen.getByRole("button", { name: "GLM-5.3" })).toBeDisabled();
  await userEvent.click(retry);
  await waitFor(() => expect(screen.getByText(/已保存 我的智谱/)).toBeInTheDocument());
  const posts = api.mock.calls.filter(([path]) => path === "/connections"); expect(posts).toHaveLength(2); expect(posts[0][1]).toEqual(posts[1][1]);
});
it("明确拒绝的字段可修正，保存身份不变化", async () => {
  setup(() => { throw Object.assign(new Error("名称不合法"), { status: 400 }); }); await fill();
  expect(await screen.findByText("名称不合法")).toBeInTheDocument();
  expect(screen.getByLabelText("连接名称")).not.toBeDisabled();
});
it("首次 503 后的临时 403 不会解锁可能已保存的连接", async () => {
  let attempts = 0;
  setup(body => {
    attempts += 1;
    if (attempts < 3) throw Object.assign(new Error("暂时无法确认"), { status: attempts === 1 ? 503 : 403 });
    return { connection: body };
  });
  await fill();
  await userEvent.click(await screen.findByText("确认同一连接的保存结果"));
  await waitFor(() => expect(api.mock.calls.filter(([path]) => path === "/connections")).toHaveLength(2));
  expect(screen.getByLabelText("连接名称")).toBeDisabled();
  expect(screen.getByLabelText("模型服务")).toBeDisabled();
  expect(screen.getByRole("button", { name: "GLM-5.3" })).toBeDisabled();
  await userEvent.click(await screen.findByText("确认同一连接的保存结果"));
  expect(await screen.findByText(/已保存 我的智谱/)).toBeInTheDocument();
  const posts = api.mock.calls.filter(([path]) => path === "/connections");
  expect(posts).toHaveLength(3);
  expect(posts[1][1]).toEqual(posts[0][1]);
  expect(posts[2][1]).toEqual(posts[0][1]);
});
