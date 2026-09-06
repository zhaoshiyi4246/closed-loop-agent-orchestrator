# CLAO 当前项目事实

更新：2026-09-06（M0 基线与目录整理）。本文件只记录已实现事实与已知限制；v0.3的设计见 [V03_PLAN.md](V03_PLAN.md)，不能把设计直接写成已完成能力。

## 1. 版本与基线

| 项目 | 当前事实 |
|---|---|
| 产品 | CLAO / Closed-Loop Agent Orchestrator |
| 已发布版本 | v0.2，Windows本地比赛版 |
| 已发布源码 | 4d3e8e6b5e70bab868b2eef0d28c7742dea044ba |
| 开发目标 | v0.3：先修Bug，再优化GUI与模型切换；本稿阶段未实现 |
| 主仓库 | zhaoshiyi4246/closed-loop-agent-orchestrator |
| 产品源码路径 | `clao/`，当前唯一正式产品，内部 Python 包为 `src/loopcore/` |
| 发布工具 | `packaging/build-release.ps1` 与 `packaging/release-manifest.txt` |
| 历史／reference | `legacy/` 保存原历史内容；`docs/reference/` 保存冻结审计 PDF |
| 用户发布包 | clao/，由唯一映射manifest从clean Git tree构建 |

v0.2完成过支持环境下的干净ZIP bootstrap、438项测试、指定CLI和人工GUI Mission验收。该历史证据只证明对应样例，不表示所有Bug已修完、安全已认证或多模型已实现。

M0 只迁移仓库目录、修正当前引用和治理状态，不修 A01—A12、不改变 runtime 或已发布 v0.2；结构验收见 [M0 证据](V03_M0_EVIDENCE.md)。

## 2. 当前真实架构

```text
Panel / CLI → 同一runtime组装与preflight → MissionController
                                     ├ per-task ClosedLoop
                                     ├ Planner / Auditor / Verifier
                                     ├ deterministic Observer / Gate
                                     ├ AOAdapter / ActionExecutor → AO Worker
                                     └ StateStore
StateStore → StoreBusProjector / JSONL / Markdown / GUI
```

MissionController是控制编排权威，ClosedLoop负责子任务；StateStore保存逻辑状态、动作、计数和证据。AO提供Session／conversation／activity／workspace事实。AOAdapter主要读取，也包含approval resolve POST；ActionExecutor执行有限spawn/send/kill。Bus不是控制传输层。

语义角色当前使用共享headless Codex CLI；stdin传Prompt，保留ephemeral/read-only、schema输出、non-Git cwd支持。Worker是AO Codex harness。当前历史验收模型为gpt-5.6-sol，不把这个字符串作为永久模型支持清单。Observer/Gate不用模型。

## 3. 当前工作流与限制

默认单Worker时不调用decomposition Planner；证据充足的正常Task为WORKER_RUNNING → GATE_PENDING → DONE；新Task正常路径无Task Verifier。Mission随后materialization、integration、Final Gate、Mission Verifier，满足程序现有条件才到MISSION_DONE。异常可以进入Auditor → Planner以及受限LOCAL_FIX/REPLAN/HUMAN。历史VERIFIER_PENDING有兼容恢复。

当前L0是确定性程序消息，用户directive也能经受控路径发给Worker；不能写成所有消息都由Planner LLM生成。当前Stop是终态HUMAN，不是暂停；attach不启动runner但仍存在组装副作用，A08要求进一步只读化。现有SSE已存在，v0.3不是从零新增实时更新。

成果保留在runtime/<mission-id>/integration，不自动写回target main/master，不自动push。artifact-aware clean可以忽略正常cache，不等于原始git status为空。runtime linked worktree依赖Git common dir，不能当独立可搬运项目。

## 4. 已验证外部前提

Windows、CPython3.12、Git、AO Desktop0.12.9、Codex CLI0.150.1及ChatGPT登录是v0.2的已验证组合。bootstrap只管理本地Python venv，不安装Python/Git/AO/Codex。

AO executable通过CLAO_AO_BIN或PATH解析；runfile通过CLAO_AO_RUN_FILE或~/.ao/running.json解析。Project需要注册的Git-backed项目、identity、origin及有效remote-backed base；显式branch要求origin/<branch>，auto要求origin/HEAD。origin可以是本地bare repo。不自动修改Git/AO配置。该约束是当前验证过的产品支持范围，不宣称覆盖AO所有潜在能力。

## 5. 新审计已知缺口

依据 [原审计](reference/CLAO_v0.2_audit_20260905.pdf)；本次治理更新没有修复以下代码：

- A01：命令审批和路径包含性；A02：Schema/ID/AC/最终结论一致性；A03：rename/artifact/index取证。
- A04：Gate表专用查询与真实错误显示；A05：本地写API和安全渲染。
- A06—A10：指令生效、外部动作未知、kill确认、停止恢复、基线/依赖和有效配置。
- A11/A12：多模型、证据完整性、结果导出和普通用户使用体验。

状态与证据等级请查 [V03_BACKLOG.md](V03_BACKLOG.md)。不能因为历史R5 COMPLETE把这些问题写成RESOLVED。

队友在既有发布基线上提供了0.2.1-rc1的完整Schema等候选补丁。它是可评审输入，不是当前main已合入事实；按F01选择性移植并保留归属，不能整目录覆盖或继承未经本次验证的live结论。

## 6. v0.3目标与现状严格分栏

| 主题 | 当前v0.2 | v0.3设计（待实现） |
|---|---|---|
| GUI | 技术拓扑＋任务表单＋SSE | 四入口、iPhone风格层级、任务/结果中心 |
| 模型 | Codex CLI与AO Codex | GLM/Kimi语义profile，Worker单独准入 |
| 配置 | 有重复和未接线项 | 唯一effective config与Mission快照 |
| 结果 | integration路径与日志 | 可独立应用的patch导出与证据摘要 |
| 停止 | HUMAN与文案不一致 | 准确取消、崩溃恢复、关联attempt |

## 7. 文档职责与历史

AGENTS=规则；PROJECT=事实；PLANS=当前指针；V03_PLAN=目标设计；V03_BACKLOG=任务/证据。只有大写docs/PROJECT.md作为开发事实文件；runtime/project.md不属于项目治理。

原R0—R5历史文档未从Git历史删除，完整冻结内容见：

- [v0.2原PROJECT](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/blob/4d3e8e6b5e70bab868b2eef0d28c7742dea044ba/docs/PROJECT.md)
- [v0.2原PLANS](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/blob/4d3e8e6b5e70bab868b2eef0d28c7742dea044ba/PLANS.md)
- [v0.2Release](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/releases/tag/v0.2)

以后本文件仅按已合入代码与验收更新，不复制完整PR流水账；旧治理文件的目标性措辞不再凌驾于本文件和v0.3批准设计。
