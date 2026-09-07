# CLAO 当前执行计划

> 规划版本：0.3-plan-r1，2026-09-06。已批准 / IN EFFECT；规划入库与基线核对已完成。
> 已发布基线：v0.2，4d3e8e6b5e70bab868b2eef0d28c7742dea044ba。
> 目标：先修Bug，再完成简洁GUI与GLM/Kimi语义模型切换。

## 当前唯一执行指针

- 当前阶段：**M1 IN_PROGRESS**；M0 COMPLETE。
- 当前唯一任务：**V03-F04 — Gate查询、本地API与安全渲染**，IN_REVIEW；[PR #35](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/35) 已提交、等待外部审计；base `9a55a6c20f8828246723d66e18c91dbc4a23e122`，分支 `codex/v03-f04-panel-boundaries`，产品提交 `3d1e693b5f9bef6eea926c4bbb9ef12383762302`。
- 最近完成：**V03-F03 — Git路径、产物规则与只读取证**，DONE；[PR #34](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/34) 再次外部审计 PASS，已提交 artifact 的交付缺口闭环、无其他返修项；2026-09-07 已 rebase merge 到 main `35a67d07ae196368434fbd83a95693b288c6bc6e`。
- F01 / F02 保持 DONE；[PR #32](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/32) / [PR #33](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/33) 均已审计 PASS 并合入，历史证据仍有效，详见对应卡。
- 本轮范围：Gate 查询/结果记录、Panel 错误显示、同源写 API、路径包含性、安全文本渲染及直接重复提交保护；沿用 StateStore / Controller，不新增控制面或框架。
- F04 验证：Windows 定向 **224 passed / 160.98s**，0 failed / 0 skipped；包含真实 SQLite、隔离 Git、临时 runtime/HTTP 与真实 Edge 安全交互；历史 Task Verifier scope 记录的追加检查见 F04 卡，重叠集合不累计计数。
- NOT_RUN：全量回归、clean install、打包、smoke、真实 AO/模型、GUI 视觉重设计验收；不将浏览器中的外部动作替身视作真实 Mission 验收。不实施 F05/R01/R02/U01/U02，不合并、不创建 tag/Release，不改已发布 v0.2。
- 下一步：停止，等待 PR #35 外部审计；F05 保持 TODO，不开始实现。

## 快速查询

- [设计主文档](docs/V03_PLAN.md)：范围、架构、GUI和模型设计、退出门。
- [任务/验收台账](docs/V03_BACKLOG.md)：对应卡、依赖、状态和证据。
- [当前架构事实](docs/PROJECT.md)：只记录已实现行为。
- [原审计PDF](docs/reference/CLAO_v0.2_audit_20260905.pdf)：A01—A12与证据等级。

## 阶段看板

| 阶段 | 状态 | 退出条件 |
|---|---|---|
| M0 基线与目录整理 | COMPLETE（DOC-00 / LAYOUT DONE） | 规划已批准入库；纯路径迁移验证；副本分类整理含保留项；人工审计 PASS |
| M1 修复冻结 | IN_PROGRESS（F01 / F02 / F03 DONE；F04 IN_REVIEW） | F01—F05负例与正常路径通过 |
| M2 使用契约 | TODO | 配置、回执、取消恢复、基线可追溯 |
| M3 GUI与交付体验 | TODO | 四入口＋任务旅程＋结果导出＋浏览器验收 |
| M4 模型扩展 | TODO | GLM与Kimi语义profile；Worker明确支持/拒绝决策 |
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
