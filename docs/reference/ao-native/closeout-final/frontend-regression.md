# Windows 前端回归记录 · 2026-09-21–22

本记录为 Windows 开发工作树回归，不替代安装包、干净机器或真实模型验收。没有真实供应商调用。没有新增 skip，没有恢复官方 AO 数据发现或自动更新。

## 完整首轮

在 `ao/frontend` 使用 Node 22.23.2 执行 `npm test -- --maxWorkers=2`。默认高并发的更早运行已中断，不计入完成结果。

- 完成的受控并发首轮：287 文件，262 通过、25 失败；3,859 测试，3,698 通过、153 失败、8 原有跳过；1,706.14 秒。
- 原始日志：外部证据目录的 `frontend-full-bounded.log`。首轮真实失败保留，不将后续复核合并改写成“完整全绿”。

## 修复及复核

- 更新器：原上游逻辑仅在测试 fixture 中显式启用；新增使用实际产品常量的测试，验证自动检查、手动检查、下载、返回原通道和安装均被派生产品禁用。
- 连接保存：网络丢响应或 503 后锁定同一 UUID 和参数；后续临时 403 不解锁；成功确认后结束。相同请求重试及字段锁定均有 UI 回归。
- 看板：补齐测试 Session 必填状态；精确选择目标错误提示和看板列，不把 CLAO 概览 section 当成原生列。CLAO 拥有的会话默认折叠、混合普通会话保持原语义的回归通过。
- 运行图：总规划先于分支、未发生的整体后续阶段隐藏、Gate 与最终语义复核分开、断连不显示实时活动的回归通过。
- 隔离目录：测试明确期待 `.clao-ao`。日期测试按系统区域格式断言；中文中的产品和协议名称逐个精确列入原有本地化检查白名单，未豁免整个文件。
- 异步 UI：设置和 Markdown 使用真实懒加载模块。只对相关等待设置 10 秒上限，保留原内容及角色断言。

定向命令（在 `ao/frontend`）：

```text
npm test -- --maxWorkers=2 src/main/auto-updater.test.ts src/shared/daemon-discovery.test.ts src/shared/daemon-launch.test.ts src/renderer/components/CLAO src/renderer/components/SessionsBoard.test.tsx src/renderer/components/GlobalSettingsForm.test.tsx src/renderer/__tests__/integration/board-empty-states.test.tsx src/renderer/components/chat/ChatWorkspace.test.tsx src/renderer/components/chat/ChatTimelineItems.test.tsx src/renderer/components/markdown/MarkdownFileView.test.tsx src/renderer/i18n/renderer-coverage.test.ts
```

此复核 16 文件：13 通过、3 失败；373 测试通过、9 失败。全部 6 个 CLAO 测试文件、看板、运行图、本地化检查和隔离目录通过。剩余 9 条是下述 macOS 更新器用例 5 条及懒加载等待 4 条。后者修复后执行：

```text
npm test -- --maxWorkers=1 src/renderer/components/GlobalSettingsForm.test.tsx src/renderer/components/markdown/MarkdownFileView.test.tsx
```

结果 2 文件、42 测试全部通过，23.78 秒。日志分别为 `frontend-repaired-targets.log`、`frontend-lazy-modules.log`。

## 原生依赖复核

开发依赖中的 `better_sqlite3.node` 为 Electron 33 的 ABI 130；Node 22 要求 ABI 127，首轮浏览器导入 12 条因此失败。未重建或替换依赖。使用 Electron 自带 Node 20.18.3、`ELECTRON_RUN_AS_NODE=1`，并提供临时 Node 环境配置，运行原测试：

```js
export default { test: { environment: "node", maxWorkers: 1, testTimeout: 20000 } };
```

```text
electron.exe node_modules/vitest/vitest.mjs run --config ../../.native-dev/vitest-native.config.mjs --maxWorkers=1 src/main/browser-profile-import.test.ts src/main/supervisor-link.test.ts
```

配置不加载 renderer 构建插件，避免 Electron 的较旧 Node 与 Vitest 配置 CJS/ESM 装载不兼容；业务断言不变。连接测试仅将 Windows 端点改为本机 named pipe，保留连接、重连、断开和释放断言。

结果 2 文件、20 测试全部通过，18.11 秒。日志 `frontend-native-runtime.log`。

## 保留的平台与独立子项目失败

- 29 条平台语义失败：更新器 5 条 macOS 安装位置/权限模拟；DMG maker 1、editor handoff 4、relocation 1 的 macOS 路径语义；mac artifact shell 12 的 Unix 执行权限及本机 WSL/bash；ACP 分发裁剪 1 条 Unix symlink；telemetry policy/controller 5 条 Linux fsync、权限或 POSIX 路径夹具。Windows telemetry fail-closed 专用用例在首轮通过。
- landing 为独立站点子项目：5 条 Markdown 生成测试缺少其依赖，另 6 个测试文件因 `cheerio` 或 landing 专用 `@ao/shared/constants` 映射无法载入。它们不属于桌面 runtime 发布清单。

这些是实际失败及适用性分类，不是通过或未执行。未修改这些平台断言，未广泛跳过文件。修复后未重复完整 287 文件测试集。所有测试修订完成后 `tsc --noEmit` 与本次文件 `git diff --check` 均通过；类型检查日志 `frontend-tsc-repaired.log`。
