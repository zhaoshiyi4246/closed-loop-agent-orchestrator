# CLAO

Closed-Loop Agent Orchestrator

CLAO 是本地闭环软件开发控制层；main 的 v0.3 开发代码中新本地任务通过 Codex App Server 执行，旧 AO 后端保留兼容。默认单Worker执行任务，通过确定性Gate、集成和Mission终局复核保存可检查结果。

**已发布：v0.2（Windows本地比赛版）。v0.3 规划已批准，M0 / M1 COMPLETE；V03-F01 的 [PR #32](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/32)、V03-F02 的 [PR #33](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/33)、V03-F03 的 [PR #34](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/34)、V03-F04 的 [PR #35](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/35) 与 V03-F05 的 [PR #36](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/36) 均已外部审计 PASS 并合入 main（DONE）。V03-R01 — 有效配置与阶段诊断的 [PR #37](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/37) 已再次外部审计 PASS 并合入（DONE）；V03-R02 — 指令回执、取消恢复、固定基线的 [PR #38](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/38) 已外部审计 PASS 并 rebase 合入（DONE）；M2 / M3 COMPLETE（M3 为阶段开发与代码审计完成）；V03-U01 — iPhone 风格界面骨架与状态夹具的 [PR #39](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/39) 本轮代码与产品整改外部审计 PASS，已 rebase 合入（DONE）；U02 整卡 DONE，首切片“独立项目入口与本地执行”的 [PR #40](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/40) 再次外部审计 PASS、已 rebase 合入（DONE）；完整任务旅程切片的 [PR #41](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/41) 代码与返修再次外部审计 PASS，已 rebase 合入（DONE）；V03-U03 — 结果中心与独立导出的 [PR #42](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/42) 再次外部审计 PASS、已 rebase 合入（DONE）；M4 IN_PROGRESS；V03-P01 工程与离线验证切片的 [PR #43](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/43) 再次外部审计 PASS、已 rebase 合入（切片 DONE）；P02 工程接入与离线验证切片的 [PR #44](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/44) 外部工程审计 PASS、已 rebase 合入（DONE）；P01/P02 整卡及 M4 仍 IN_PROGRESS。唯一下一执行内容为两家联合真实服务/角色准入及质量、延迟、用量评测，TODO，等待负责人确认服务/型号权限、外发材料与预算，尚未启动，不开始 P03。**

## 使用已发布产品

前往 [v0.2 Release](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/releases/tag/v0.2)，下载附件 `clao-v0.2-4d3e8e6b5e70.zip`，不要把自动生成的Source code ZIP当作净化产品包。解压后进入 `clao/`，按其中README操作。

v0.2 历史验证环境为Windows、CPython3.12、Git、AO Desktop0.12.9和Codex CLI0.150.1/ChatGPT登录。bootstrap只管理Python venv，不替用户安装外部工具。Git-backed AO Project需要origin与有效remote-backed base；origin可为本地bare repo。

结果保留在 `runtime/<mission-id>/integration`，不自动写回main/master，不自动push。当前版本只按支持环境和指定路径验证；已知权限、结果一致性和GUI证据问题列入v0.3首批修复，重要项目应备份并保留人工监督。

main 已合入的 U01 提供概览、任务、模型、设置四入口，浅/深主题、窄屏导航和四步新建表单。正常页面仅使用真实数据；开发夹具与产品服务/发布资源隔离。参见[工作台说明](clao/README.md#任务工作台v03-u01)与[返修截图和开发检查](docs/V03_BACKLOG.md#v03-u01iphone风格界面骨架与状态夹具)。已有 Windows/浏览器验证和 Codex 截图自查，与本次外部代码/产品整改审计分别记录；已合入的 U02 首切片已接入无远端 Git、普通目录、空项目的隔离执行，复用既有 Controller/Gate/Verifier。需要已安装 Python/Git/Codex 0.150.1 与官方 ChatGPT 登录/Windows 沙箱，不要求 AO；当前仅离线协议/浏览器验证，真实模型 NOT_RUN，尚非发布兼容性验收。用法见[本地项目与来源确认](clao/README.md#本地项目与来源确认)，任意进程重连和 Q01 独立安装器未实现；U03 独立补丁包已审计合入；旧 AO 历史只读与显式兼容后端分别保留，不混作新本地任务。

已合入的 U02 完整旅程接通按需环境检查、本次配置确认与冻结、审批差异/拒绝/回答、取消、只读历史查询和结果位置检查。运行中查看另一任务不会替换当前执行，停止未知不能启动另一任务；仍沿用既有控制与验收路径。当前实现及离线浏览器证据见 [U02 台账](docs/V03_BACKLOG.md#v03-u02完整任务gui与数据接线)，代码与返修审计已通过；不等同负责人完整 GUI 体验验收。200% 证据为等效布局/CSS zoom，真实模型、全量、安装与发布验证尚未完成；U03 状态见当前指针。

U03 在既有任务详情提供固定结果的变更、差异和逐项验收，以及复制路径、打开目录和独立 ZIP 补丁包。包生成后可脱离原工作树使用；仅支持明确的文本/文件模式范围，历史缺版本或含不支持/禁止材料时不伪造完整导出。用法与限制见[结果中心说明](clao/README.md#结果中心与独立补丁包v03-u03)。已有证据为离线 Git/HTTP/浏览器验证；M3 COMPLETE 不表示完整 GUI 体验、真实模型、全量、安装或发布验收通过，v0.3 尚未发布。结果包不含完整基线/项目依赖，敏感检测仅为有限规则；“任务闭环运行视图”仍仅为候选。

## v0.3 开发方向

先修复授权、终局判断、Git路径和证据、本地API及停止边界；再提供任务导向、iPhone风格层级的简洁GUI、结果导出，以及按角色明确的GLM/Kimi语义模型配置。Worker供应商切换需独立能力验证，不能仅改模型名。

## 开发上下文

- [当前架构与事实](docs/PROJECT.md)
- [当前执行任务](PLANS.md)
- [v0.3规划设计](docs/V03_PLAN.md)
- [任务与验收台账](docs/V03_BACKLOG.md)
- [原审计报告](docs/reference/CLAO_v0.2_audit_20260905.pdf)
- [Codex实施规则](AGENTS.md)

当前唯一正式产品源码为 `clao/`；发布工具位于 `packaging/`，历史来源归档在 `legacy/`。内部 `loopcore` 包名保留；main 已包含 F01–F05 修复、R01 配置/诊断及 R02 指令/取消恢复/固定来源契约，已发布 v0.2 保持不变。

```text
closed-loop-agent-orchestrator/
├─ clao/          当前产品、测试、bootstrap
├─ packaging/     release builder 与 manifest
├─ legacy/        历史 v0.1、sidecar、demo 和开发资料
├─ docs/          当前事实、v0.3 规划与 reference
├─ AGENTS.md
├─ PLANS.md
├─ README.md
└─ .gitignore
```

开发验证：进入 `clao/`，运行 `bootstrap.ps1`，按 [产品自检说明](clao/README.md#本地自检) 运行 pytest 和 compileall。

发布彩排：在 clean committed branch HEAD 上运行 `packaging/build-release.ps1 -OutputDirectory <仓库外的新目录>`。builder 只读取 HEAD 中 manifest 指定的 tracked blobs，产品 ZIP 唯一顶层仍是 `clao/`；不包含 `legacy/`、治理文档、runtime 或 `.venv`。这是本地构建，不自动创建 GitHub Release。

[M0 迁移证据与边界](docs/V03_M0_EVIDENCE.md) 记录路径、内容 allowlist 和验证结果。

本仓库为统一的发布与评审主线。队友补丁须按范围评审、验证并保留归属；不以Sync fork或整目录覆盖替代集成。

P01/P02 已合入 BigModel 国内通用 `glm-4.7` 与 Kimi 国内通用 `kimi-k3` 的工程接入；Planner 分解/异常调用、Auditor、Mission Verifier 可分别选择 Codex/GLM/Kimi，共用现有模型页与传输，角色/凭据/外发许可按服务隔离。Worker 仍为 Codex，Observer/Gate 无模型；国际/Coding/中转服务未支持。工程审计、离线 HTTP/浏览器测试不等于真实供应商请求或角色准入通过；联合真实验证尚未启动，当前支持与配置边界见 [产品说明](clao/README.md#glm-语义角色配置p01-工程切片)。
