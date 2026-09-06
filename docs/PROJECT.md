# CLAO 当前项目事实

更新：2026-09-06（F01 审计 PASS 并合入 main）。本文件只记录已实现事实与已知限制；v0.3的设计见 [V03_PLAN.md](V03_PLAN.md)，不能把设计直接写成已完成能力。

## 1. 版本与基线

| 项目 | 当前事实 |
|---|---|
| 产品 | CLAO / Closed-Loop Agent Orchestrator |
| 已发布版本 | v0.2，Windows本地比赛版 |
| 已发布源码 | 4d3e8e6b5e70bab868b2eef0d28c7742dea044ba |
| 开发目标 | v0.3：F01 已合入 main；下一任务 F02 TODO；GUI与模型切换等后续目标待实现 |
| 主仓库 | zhaoshiyi4246/closed-loop-agent-orchestrator |
| 产品源码路径 | `clao/`，当前唯一正式产品，内部 Python 包为 `src/loopcore/` |
| 发布工具 | `packaging/build-release.ps1` 与 `packaging/release-manifest.txt` |
| 历史／reference | `legacy/` 保存原历史内容；`docs/reference/` 保存冻结审计 PDF |
| 用户发布包 | clao/，由唯一映射manifest从clean Git tree构建 |

v0.2完成过支持环境下的干净ZIP bootstrap、438项测试、指定CLI和人工GUI Mission验收。该历史证据只证明对应样例，不表示所有Bug已修完、安全已认证或多模型已实现。

M0 只迁移仓库目录、修正当前引用和治理状态，不修 A01—A12、不改变 runtime 或已发布 v0.2；结构验收见 [M0 证据](V03_M0_EVIDENCE.md)。

F01 已通过外部审计 PASS，[PR #32](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/32) rebase 合入 main `144c599a022659f6264762e47a54ca296622f751`，状态 DONE；已发布 v0.2 未变。已有 Windows 定向 76 项、开发全量 514 项与干净包全量 514 项通过，bootstrap、compileall 与本地构建证据有效；负责人确认本阶段无需额外 live smoke，未将离线结果视作真实模型/AO验收。详细证据见 F01 卡。

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

F01 在语义角色与 Controller 实际路径共用必需的完整 JSON Schema、有限数值和请求 ID 关联校验，依赖 `jsonschema==4.25.1`；无弱 fallback。终局要求必需 AC 恰好覆盖、PASS 与 AC/anti-gaming 一致，已有确定性 Gate/范围/integrity 失败不能被模型 PASS 覆盖。协议错误与合法语义 FAIL 分开处理，后者原样保留且不为改写结论重试。

实际角色输入带证据原长度、SHA-256、缺失/截断标识；关键证据不完整时阻断通过。Task 历史与 Mission final 结果重放校验相同契约及保存的输入摘要；缺失/损坏或输入变化进入人工处理，不伪补成功、不批量改写历史终态。长证据与 Gate 输出变化可能保守触发人工处理；默认单 Worker、gate-first、Mission final-only 保持不变。

当前L0是确定性程序消息，用户directive也能经受控路径发给Worker；不能写成所有消息都由Planner LLM生成。当前Stop是终态HUMAN，不是暂停；attach不启动runner但仍存在组装副作用，A08要求进一步只读化。现有SSE已存在，v0.3不是从零新增实时更新。

成果保留在runtime/<mission-id>/integration，不自动写回target main/master，不自动push。artifact-aware clean可以忽略正常cache，不等于原始git status为空。runtime linked worktree依赖Git common dir，不能当独立可搬运项目。

## 4. 已验证外部前提

Windows、CPython3.12、Git、AO Desktop0.12.9、Codex CLI0.150.1及ChatGPT登录是v0.2的已验证组合。bootstrap只管理本地Python venv，不安装Python/Git/AO/Codex。

AO executable通过CLAO_AO_BIN或PATH解析；runfile通过CLAO_AO_RUN_FILE或~/.ao/running.json解析。Project需要注册的Git-backed项目、identity、origin及有效remote-backed base；显式branch要求origin/<branch>，auto要求origin/HEAD。origin可以是本地bare repo。不自动修改Git/AO配置。该约束是当前验证过的产品支持范围，不宣称覆盖AO所有潜在能力。

## 5. 审计缺口与修复状态

依据 [原审计](reference/CLAO_v0.2_audit_20260905.pdf)；F01 已补齐 A02 的完整契约与终局一致性及 A11 相关证据边界。其他卡继续保留：

- A01：命令审批和路径包含性（下一任务 F02，TODO）；A03：rename/artifact/index取证。
- A04：Gate表专用查询与真实错误显示；A05：本地写API和安全渲染。
- A06—A10：指令生效、外部动作未知、kill确认、停止恢复、基线/依赖和有效配置。
- A11/A12 其余范围：多模型、后续 Git 取证边界、结果导出和普通用户使用体验；不因 F01 完成宣称所有证据路径或模型真实性已验收。

状态与证据等级请查 [V03_BACKLOG.md](V03_BACKLOG.md)。不能因为历史R5 COMPLETE把这些问题写成RESOLVED。

队友在既有发布基线上提供的 0.2.1-rc1 候选说明已作为 F01 评审输入；本次独立实现，未移植队友源码或继承其 live 结论，来源记录在 F01 卡。

## 6. v0.3目标与现状严格分栏

| 主题 | 当前实现 | v0.3设计（待实现） |
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
