# 2026-09-21 原生 UI 收尾证据

> 当前图片拍摄于最终3942d65界面收敛之前，包含旧布局，只作为中间开发记录。已由版本标识的实际安装截图接替；不得将本组截图冒充最终界面验收。

任务：V03-NATIVE-CLOSEOUT / PR #49。本目录是 Windows 实际 Electron 开发版界面证据，由 Codex 自查；不是负责人体验验收或安装包验收。

## 实际旅程

`ao/frontend/scripts/test-clao-desktop.cjs` 的 `CLAO_TEST_CLOSEOUT=1` 路径，使用本轮集成 daemon、正式 renderer、原生 Session/Chat/SQLite/Git/Python 验收核心。只有外部执行器/模型使用隔离协议替身；全部项目、结果和登录环境属于独立临时测试数据，无真实模型/供应商请求。

- 普通目录确认当前内容，原生菜单搜索选择模型，单任务最终通过；[来源](source-confirmation.png)、[模型菜单](native-model-selection.png)。
- 固定文件差异、独立 ZIP 下载与 SHA 校验、解压后在独立副本 `git apply` 并再次运行真实检查命令；[差异](frozen-result-diff.png)、[已保存结果包](saved-independent-package.png)。原项目文件/无 Git 状态保持不变。
- 两个实际原生 Session 同时执行（当时仍有重复分支布局，后续3942d65才收敛为一个整体图）；[两个执行节点](two-worker-process.png)。阻断页面实际任务轮询后高亮消失并明确最后已知非实时；恢复网络后两个节点重新高亮；[断连记录](disconnected-last-known.png)。整体最终验收随后通过：[整体结果](integrated-acceptance.png)。
- 旧配置仅在设置中的显式迁移入口导入：[迁移](explicit-legacy-import.png)。设置中搜索并创建 GLM-5.3 连接：[新连接](new-model-connection.png)；未保存 API Key、未向供应商发请求，不代表真实型号权限或可用性已验证。

## 主题与缩放

通过实际 Settings → Theme 菜单切换浅/深色；使用 Electron 窗口尺寸与 `webContents.setZoomFactor(2)`，不是 CSS zoom。检查主题值、dialog 视口边界及横向溢出，并使用 Electron `capturePage` 保存完整窗口。

| 实际窗口 / 缩放 | 浅色 | 深色 |
|---|---|---|
| 1440×900 / 100% | [查看](native-light-1440-100pct.png) | [查看](native-dark-1440-100pct.png) |
| 960×900 / 100% | [查看](native-light-960-100pct.png) | [查看](native-dark-960-100pct.png) |
| 1440×900 / 200% | [查看](native-light-1440-200pct.png) | [查看](native-dark-1440-200pct.png) |

本机系统缩放为 150%；200% 页面缩放的 CSS viewport 为 720×450，dialog 为 560×382.5，左右边界仍在视口内；纵向内容可滚动。AO 最小窗口宽度为 960，尝试 900 后读取到实际 960，证据按实际尺寸命名。

首轮自动脚本只检查图内部溢出，且 Playwright 在非默认 Electron zoom 下的截图被裁切、系统主题切换未改变实际选中主题，因此首轮六张图不计视觉通过。本组后续六张图由实际设置切换、完整窗口捕获和边界断言复查得到，但仍早于最终布局修改；未通过修改产品事实或放宽断言制造成功。复用已完成任务进行视觉复查，没有重跑模型任务。

可复演入口：`scripts/test-clao-closeout.cjs` 调用 `scripts/test-clao-visual.cjs`。复查后仅作术语可读性微调（如 Gate → 检查、服务标识 → 服务名称），不改变布局或状态推导；最终集成审查仍需核对当前代码。

## 证据边界

这是开发版实际桌面和受控本地集成测试，不能替代真实账户、真实供应商、安装包、两套干净 Windows 或负责人完整体验验收。单元/组件合同及最终完整回归结果由本轮总报告记录，不能与本目录截图重复累计。
