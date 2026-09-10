# CLAO 当前执行计划

> 规划版本：0.3-plan-r1，2026-09-06。已批准 / IN EFFECT；规划入库与基线核对已完成。
> 已发布基线：v0.2，4d3e8e6b5e70bab868b2eef0d28c7742dea044ba。
> 当前批准路线：AO 原生底座 + CLAO 闭环；旧阶段实现与验收作为历史保留。

## 当前唯一执行指针

- 当前阶段：**M4 IN_PROGRESS**；M0 / M1 / M2 / M3 保持 COMPLETE。
- 当前唯一下一开发内容：**运行恢复与用户指令回执迁移，TODO**，本轮不开始。整体“AO 原生底座 + CLAO 闭环迁移”与 M4 保持 IN_PROGRESS；PR #45 被替代、不合并，保留分支与证据；P01/P02 联合真实评测继续暂缓。
- 最近完成：**Planner/Auditor 异常决策与独立角色配置迁移，DONE**。[PR #47](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/47) 再次外部代码审计 PASS，默认模型在实际 Chat 启动/恢复中的接线已修正，2026-09-10 已 rebase 合入 main。完成范围为单 Worker 异常诊断、五类动作、独立只读语义会话、四角色执行器/模型配置、冻结选择贯通启动/恢复和原生角色/决策展示；不是全部 Planner、所有执行器、逐角色独立账号或完整迁移完成。详细证据与空账户开发入口见 [开发说明](ao/CLAO.md) 和 [迁移台账](docs/V03_BACKLOG.md)。
- 此前完成：**P02 工程接入与离线验证切片 DONE**；[PR #44](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/44) 外部工程审计 PASS，无返修阻塞项，2026-09-09 已 rebase 合入 main `c112e25d332a284e857c9b2b0d3bd1ad32856485`，合入 tree 与已审计 head `d140e5d14e152ad1a64a4643bcbb1b775bac4a38` 一致。P01 工程切片保持 DONE；P01/P02 整卡及 M4 保持 IN_PROGRESS。
- P02 已合入 Moonshot 国内通用 `kimi-k3`，复用原传输/角色校验与模型页；凭据及外发许可按实际服务隔离，旧 GLM/Codex 配置兼容、当前快照冻结。最终 Windows P02/浏览器定向 65 passed，Codex/Worker 停止兼容 41 passed；实际 Edge 截图自查及首轮修正见 P02 卡。仅外部边界使用替身，真实模型仍 NOT_RUN，P02 整卡与 M4 不标完成；不开始 P03。
- 此前完成：**P01 工程实现与离线验证切片 DONE**；[PR #43](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/43) 再次外部审计 PASS，外发确认归属问题已解决，2026-09-09 已 rebase merge 到 main `d1738b5337aecdfbc063fd284fb1e7bfa6fe7fcc`，合入 tree 与已审计 head `c629890d6fa3e740ffaa48a3117961f59dbe4988` 一致。P01 整卡 IN_PROGRESS，剩余为实际 GLM 服务/角色准入，非本次代码返修；U01 / U02 / U03 保持 DONE。
- P01 工程已接通 BigModel 通用 `glm-4.7`、三个语义角色独立绑定、Windows 系统凭据和任务外发确认；复用原角色协议/Controller，有界重试与取消不改变 Worker UNKNOWN。Windows P01/安全引用导出定向 54 passed；Panel/草稿归属与兼容复查 31 passed；其余 R01/Codex 证据与夹具修正见 P01 卡，不累计为全量。真实模型及准入未运行，M4 未完成；两家工程均已完成，真实服务/角色准入与质量、延迟、用量评测仍待验证。
- 此前完成：**V03-U03 — 结果中心与独立导出**；[PR #42](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/42) 再次外部审计 PASS、无继续返修阻塞项，2026-09-08 已 rebase merge 到 main `b755c1abe3c69167ddb62bc3489d513d97ea918d`；已审计 head `6ccaa5673052e30f3a77bf947b6be6812ec8b728`，合入内容一致。
- U03 已实现：任务内固定结果/差异/AC 与分项验收；复制路径/受保护打开目录；完整文本补丁、清单、摘要与说明的独立 ZIP，原 StateStore 保存已完成包。Git/目录失效后已有包仍可下载；不使用当前 HEAD 或模型证据截断生成补丁。
- 沿用 U03 Windows 定向（本轮不重跑） **39 passed / 84.44s**（真实 Git/SQLite/HTTP、原 Controller/Gate/Verifier + 仅引擎/Provider 替身，含实际 Edge）；U02 四旅程复查 **4 passed / 34 deselected / 35.25s**，此前其余兼容定向 30 passed；另补基线缓存独立应用 1 passed，失败修正及证据分类见 U03 卡。未运行全量、安装、smoke、真实 AO/模型或 CLAO 发行打包；结果包生成/下载/解压/独立应用和内容/Gate 检查已执行。
- U03 / PR #42 误拦截返修：凭据读取、精确环境占位及普通 CLI prompt 参数不再仅因名称被拒绝；明确凭据/私钥/认证与 Prompt 材料仍拦截。真实 Git/HTTP 补丁独立应用与旧包保留定向已验证，具体结果见 U03 卡。
- 基础切片保持完成：**AO 原生底座 + 单 Worker 验收闭环基础集成，DONE**。[PR #46](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/46) 启动失败返修已通过外部代码审计，2026-09-10 已 rebase 合入 main。已接原生项目/模型入口、Session/工作区、Gate/范围/完整性、有界修复、独立 Verifier、启动请求可见/失败处理及验收面板；不等于整体迁移完成。
- 尚未迁移：上述下一切片、多子任务分解/并行、普通目录/未提交来源、旧历史/连接/凭据导入、结果中心与独立导出、闭环运行图和正式发布入口。本轮仅合并、文档与差异检查；主目录已有 `clao/config/default.yaml` 修改原样保留，不纳入提交；开发工作树、依赖和独立数据保留。完成后停止。
- PR #47 证据：沿用已有 Windows/Go/纯契约与初始 Electron 检查、Codex 截图自查；默认模型返修未重测浏览器，合并收尾不重跑测试/构建。再次源码审计 PASS 不等于负责人完整体验；`account_storage_unsafe` 待解决，xfailed 不计执行通过，真实账号/模型/套餐额度、全量与发布验收仍未完成。
- PR #46 证据：沿用既有 Windows/离线集成、开发构建与 Electron 操作检查、Codex 截图自查；本次外部代码审计 PASS 不等于负责人完整体验验收。`account_storage_unsafe` 仍待解决，xfailed 不算执行通过；真实账户/模型、全量及发布验收未完成。PR #46 收尾仅做文档链接与差异检查。准确的空账户隔离启动命令见 [开发说明](ao/CLAO.md)，既有检查见 [原生证据](docs/reference/ao-native/README.md)。
- PR #44 收尾历史：完成合并、背景同步及本地 main fast-forward。本轮仅文档链接、差异与产品 blob 不变检查，沿用既有证据，不重跑测试/构建/smoke、不读取真实 Key 或请求供应商。两家工程均已完成，当时拟进行的联合真实验证现已暂缓；工程审计、离线 HTTP/浏览器通过不等于真实准入或质量评测通过。完整 GUI 体验、全量、安装与发布验收尚未完成；“任务闭环运行视图”仍仅为未授权候选。
- U03 收尾仅检查文档链接与差异；未重跑测试、构建、smoke、结果包应用或真实模型。文件类型支持不变，结果包不含完整基线或项目依赖；敏感检测仍为有限规则。
- 此前完成：**V03-U02 — 完整任务旅程与 GUI 数据接线**；[PR #41](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/41) 代码与返修再次外部审计 PASS，2026-09-08 已 rebase merge 到 main `e78738d0c11774b8163feb344256355a32ae5fb2`，合入 tree 与已审计 head `73b5a8055094bc09b4c6ee119034f09a4ff93903` 完全相同。
- 已合入切片接通真实环境检查、四步表单配置确认/冻结、审批差异与拒绝/结构化回答、取消及只读历史/结果导航；查看 B 不替换运行 A，停止未知阻断新任务。复用正式 Controller/Git/Gate/Verifier，未改执行引擎主体。
- 沿用实施阶段 Windows 定向：最终 HTTP/配置/历史及兼容浏览器 27 passed，实际页面旅程 4 passed；此前 F04 119 passed、U02 兼容节点 17 passed，集合重叠不累计。截图为实际 Edge + 隔离协议进程的 Codex 自查；外部代码与返修审计 PASS 不等同负责人完整 GUI 体验验收，真实模型仍 NOT_RUN。200% 证据为等效布局/CSS zoom，非原生浏览器缩放验收；具体命令、修正及 NOT_RUN 见 U02 卡。
- PR #41 审计返修：启动限制读取全部现有存档的持久停止 UNKNOWN，重启/只读历史不解除；草稿接收对象与编辑版本按任务保留，延迟指令/审批成功不串任务。新增/调整返修定向 12 passed，兼容 HTTP/浏览器 16 passed；三项返修已再次外部审计 PASS 并合入，本切片及整卡 DONE。
- U02 收尾（历史）仅同步文档并检查链接/路径、差异与产品 blob，未重跑测试、构建、smoke 或真实模型；当时下一任务为 U03。“任务闭环运行视图”仅在设计文档记录为未授权候选。
- 首切片保持完成：**V03-U02 首切片 — 独立项目入口与本地执行**，DONE；[PR #40](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/40) 再次外部审计 PASS，2026-09-08 已 rebase merge 到 main `3d0a33ebd69b6184f9e47dffca87895aba2d960a`；合入 tree 与已审计 head `4dc536cfa493d1b4ea8a8c36b8c78f5c7e9e7b43` 完全相同。
- U01 保持完成：**V03-U01 — iPhone 风格界面骨架与状态夹具**，DONE；[PR #39](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/39) 本轮代码与产品收敛整改外部审计 PASS、无继续返修问题，2026-09-07 已 rebase merge 到 main `014e9123a842e8ecd1f42f4ca3845b929835ca2b`；已审计 head `01dfd935c7f55d0800edd526a707387744933423`；合入 tree 与该 head 完全相同。
- R02 保持完成：**V03-R02 — 指令回执、取消恢复、固定基线**，DONE；[PR #38](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/38) 外部审计 PASS、无返修，2026-09-07 已 rebase merge 到 main `2377dd03c172461c63d26835e23abe7171e883a9`；合入 tree 与已审计 head `7d91443cd10b95d8238b5febdee4dfa59026e28e` 完全相同。
- R01 保持完成：**V03-R01 — 有效配置与阶段诊断**，DONE；[PR #37](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/37) 再次外部审计 PASS、无其他返修；2026-09-07 已 rebase merge 到 main `551f7f49198e033b1331ec341ff0d352553bacb1`，合入 tree 与已审计 head `e88c698a211ee5cd179709701ada1a7aa3079d3a` 完全相同。
- F01 / F02 / F03 / F04 / F05 保持 DONE；[PR #32](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/32) / [PR #33](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/33) / [PR #34](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/34) / [PR #35](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/35) / [PR #36](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/36) 均已审计 PASS 并合入，历史证据仍有效，详见对应卡。
- F05 已实现：同一 StateStore 持久 intent / IN_FLIGHT / confirmed result / UNKNOWN；spawn 精确随机标记对账、普通 send 未确认不重发、kill 需 AO Session 终止事实。Stop 先持久接收，HTTP 回执反映 receipt 保存事实；未知停止阻断 replan 和 materialization，不扩展 Mission 生命周期。
- 沿用 F05 既有验证：Windows operation/预算定向 **114 passed / 79.75s**、ClosedLoop 恢复入口 **9 passed / 29.08s**（集合重叠不累计）；Stop receipt 返修 F05/Panel 定向 **122 passed / 44.87s**，含真实 HTTP 与浏览器错误提示。compileall 等详细证据及 AO 契约边界见 F05 卡。
- R01 当前实现：CLI/Panel 共用严格配置解析与原子默认设置保存；Mission 快照冻结；模型、AO/轮询与各 Gate 参数接到真实消费者；同一 StateStore 记录在途阶段与请求计时，SSE 用有序完整快照恢复。配置迁移、消费者及剩余边界见 PROJECT / R01 卡。
- 沿用 R01 定向证据（本轮未重跑）：Windows 配置/Panel/角色/契约集合 311 passed；最终 R01 37 passed，含 Edge 配置与 SSE 交互；补充 F05/Gate/审批及 AO 适配复查见 R01 卡，重叠不累计。compileall、diff-check、21 个本地链接及现有发布映射前缀检查通过。NOT_RUN：全量、安装、打包、smoke、真实 AO/模型、GUI 视觉重设计验收。
- R01 审计返修：复用正常 Session/详情读取中的公开 `model`，记录独立 spawn-resolved 事实；conversation reroute 单列，缺失不猜测，旧 reroute 不重标为 spawn。Windows R01/AO/Panel 定向 **184 passed / 37.84s**，含 Edge 模型来源/安全渲染/SSE；compileall、diff-check、本地链接通过，未重跑 311 项大集合或 live。
- R01 剩余边界：历史缺配置快照仅查看；R02 已补齐受支持的恢复检查；无法确认的模型、用量和费用保持 unknown，不伪造历史事实。
- U02 首切片已接入本地项目/来源确认、Codex App Server stdio 和现有闭环。Windows U02/Panel 合同最终 57 passed（含正式 CLI、Edge 和内容过滤器负例）；生成协议校验与兼容补查见 U02 卡，集合重叠不累计。未运行真实模型、全量、安装、打包或 smoke；首切片与后续完整旅程现均已审计合入，U02 整卡 DONE。
- [PR #40](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/40) 审计返修：支持固定协议的本地 environmentId 与 raw/display 命令差异；人工确认受任务硬性边界约束；请求关闭与采纳分开记录，回答无公开采纳证据时保持 UNKNOWN；重新执行按目标历史任务确认项目/后端。四项返修已再次外部审计 PASS 并合入，首切片 DONE；验证分类见 U02 卡。本次仅文档与差异检查，未重跑既有验证。
- U01 已合入实现：四入口、浅/深/系统主题、桌面侧栏/窄屏底栏、四步表单；10 种同组件夹具仅在独立开发入口提供，正式产品不提供/加载样例；保留现有写保护、SSE 顺序、Gate/配置/停止事实和高级诊断。
- U01 首轮历史验证（返修前）：Windows 定向集合 **166 passed / 29.07s**；最终窄屏调整后实际 Edge 浏览器 **184 项断言通过 / 8.68s**；图标子集/许可复查 **1 passed / 1.15s**，集合重叠不累计。19 张实际截图属于 Codex 自查证据；首轮当时待审计，最终收尾事实见 U01 卡。compileall、JS 语法、diff-check、链接和既有 panel 发布前缀检查通过。NOT_RUN：全量、安装、打包、smoke、真实 AO/模型和完整任务旅程验收。

- U01 已审计返修：删除宣传/重复文案和产品预览；六类主状态与错误/停止事实保持一致。开发夹具移出发布映射。当时负责人批准的 D10/U02/Q01 目标已记入设计，U01 未改 AO 后端；U02 首切片与完整旅程的后续实现见 U02 卡。返修最终定向 28 passed；最后错误去重的 3 个既有浏览器回归与 U01 浏览器单项复查通过（集合重叠）。五张当前截图已自查，静态/文档检查通过；外部代码与产品整改审计已通过；截图仍按 Codex 自查记录，不宣称外部已逐张验收，详见 U01 卡。

- R02 已合入：StateStore durable directive receipt 与真实角色/Worker 消费记录；取消 requested/cancelling/cancelled/unknown 与 F05 停止事实分开；历史只读，非终态先检查真实恢复材料，终态关联新 attempt；冻结 Mission source、漂移阻断新 spawn，明确拒绝 dependent plan，保留两个独立子任务。
- 沿用 R02 Windows 定向证据（本轮未重跑）：125 passed；Panel/恢复相关复查 148 passed；F05 59 passed；最后输入/attempt 边界 9 passed、materialization/新快照 2 passed（集合重叠，不累计）。含隔离 Git/SQLite、真实本地 HTTP 与 Edge；具体命令、静态检查及边界见 R02 卡。
- R02 剩余边界：AO 当前没有 exact-commit spawn 参数，source 检查与 AO 创建不是原子事务；漂移/创建基线不匹配继续 fail closed，不宣称 exactly-once；无法确认的 operation/本地进程/历史材料仍交人工。无自动历史补建、无暂停调度器，未知模型/用量/费用不伪造。NOT_RUN：全量、安装、打包、smoke、真实 AO/模型、完整 GUI 视觉验收。

## 快速查询

- [设计主文档](docs/V03_PLAN.md)：范围、架构、GUI和模型设计、退出门。
- [任务/验收台账](docs/V03_BACKLOG.md)：对应卡、依赖、状态和证据。
- [当前架构事实](docs/PROJECT.md)：只记录已实现行为。
- [原审计PDF](docs/reference/CLAO_v0.2_audit_20260905.pdf)：A01—A12与证据等级。

## 阶段看板

| 阶段 | 状态 | 退出条件 |
|---|---|---|
| M0 基线与目录整理 | COMPLETE（DOC-00 / LAYOUT DONE） | 规划已批准入库；纯路径迁移验证；副本分类整理含保留项；人工审计 PASS |
| M1 修复冻结 | COMPLETE（F01–F05 DONE，均已审计 PASS 并合入） | F01—F05负例与正常路径通过 |
| M2 使用契约 | COMPLETE（R01 / R02 DONE，均已审计 PASS 并合入） | 配置、回执、取消恢复、基线可追溯 |
| M3 GUI与交付体验 | COMPLETE（U01 / U02 / U03 DONE，开发与代码审计完成） | 四入口＋任务旅程＋结果导出；完整 GUI 体验与发布验收仍待后续 |
| M4 模型扩展 | IN_PROGRESS | GLM与Kimi语义profile；Worker明确支持/拒绝决策 |
| M5 发布候选 | TODO | 最终ZIP、Windows、真实模型/GUI/恢复与来源证据 |

## 最近已验证基线（历史，不是本轮重跑）

v0.2已发布，原干净产品回归438项；CLI MISSION-R5-FINAL-CLI-20260905-101005、人工GUI MISSION-PANEL-20260905-103636均完成；Task/Final Gate和Mission Verifier通过，目标main/origin未自动写回。发布ZIP hash：

`73397cb066f6991681dc8404b1a85c10e80b1169a8a85b278b88ee7bdf035986`

新的 A01—A12 缺陷不被上述历史 PASS 清零；F01 当前状态以顶部指针为准。DOC-00 本次核对为 `DOC00_BASELINE_PASS`：预期 7 项规划文件已入库，106 个产品 blob 与 builder／manifest 未变，DOC-00 核对时的 17 个 Markdown 本地链接有效。本轮目录迁移：定向 88 passed；全量 438 passed in 105.61s；compileall／diff-check／本地链接 PASS；clean HEAD builder exit 0，92 个产品文件 + checksum，顶层 clao/，产品文件集变化 0。

## M0 开发验证环境

目录：仓库根的 `clao/`；CPython 3.12.7，`bootstrap.ps1` 创建本地 `.venv`，安装既有锁定依赖 PyYAML 6.0.3 / pytest 9.1.1，无新增依赖。

```powershell
cd clao
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
$env:PATH = "$(Resolve-Path '.\.venv\Scripts');$env:PATH"
$env:PYTHONPATH = (Resolve-Path '.\src').Path
.\.venv\Scripts\python.exe -m pytest .\tests -q
.\.venv\Scripts\python.exe -m compileall -q src panel run_mission.py
```

从仓库根在 clean committed HEAD 上运行 `packaging/build-release.ps1 -OutputDirectory <仓库外的新目录>`；release 映射只读 tracked blobs，顶层仍为 `clao/`。当前事实与路径审计见 [M0 证据](docs/V03_M0_EVIDENCE.md)。

## 更新规则

本文件只维护当前指针、阶段、最近关键证据、阻塞和下一步；详细测试记录放BACKLOG对应卡。Codex不能把实现中、待审计、mock通过或外部blocked写成DONE。

每次收尾提供：任务ID、base/head、PR、测试实际环境/命令/结果、NOT_RUN、产品变化、阻塞、下一任务建议。涉及scope变化先由负责人确认，不靠修改PLANS静默裁掉目标。

## 冻结历史入口

R0—R5完整历史仍在[v0.2固定提交的PLANS](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/blob/4d3e8e6b5e70bab868b2eef0d28c7742dea044ba/PLANS.md)；旧PROJECT和AGENTS同样可按固定提交查询。新执行计划不复制几百行旧日志，不修改旧tag，也不把旧时间线重新标注为当前任务。
