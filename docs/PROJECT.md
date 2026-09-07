# CLAO 当前项目事实

更新：2026-09-07（R02 外部审计 PASS 并合入 main，状态 DONE；F01–F05、R01 DONE；M0 / M1 / M2 COMPLETE；M3 TODO，唯一下一任务 U01 TODO，尚未开始实现）。本文件只记录已实现事实与已知限制；v0.3的设计见 [V03_PLAN.md](V03_PLAN.md)，不能把设计直接写成已完成能力。

## 1. 版本与基线

| 项目 | 当前事实 |
|---|---|
| 产品 | CLAO / Closed-Loop Agent Orchestrator |
| 已发布版本 | v0.2，Windows本地比赛版 |
| 已发布源码 | 4d3e8e6b5e70bab868b2eef0d28c7742dea044ba |
| 开发目标 | v0.3：F01–F05、R01 / R02 已合入 main（DONE）；M0 / M1 / M2 COMPLETE，M3 TODO；下一任务 U01 TODO；GUI与模型切换等后续目标待实现 |
| 主仓库 | zhaoshiyi4246/closed-loop-agent-orchestrator |
| 产品源码路径 | `clao/`，当前唯一正式产品，内部 Python 包为 `src/loopcore/` |
| 发布工具 | `packaging/build-release.ps1` 与 `packaging/release-manifest.txt` |
| 历史／reference | `legacy/` 保存原历史内容；`docs/reference/` 保存冻结审计 PDF |
| 用户发布包 | clao/，由唯一映射manifest从clean Git tree构建 |

v0.2完成过支持环境下的干净ZIP bootstrap、438项测试、指定CLI和人工GUI Mission验收。该历史证据只证明对应样例，不表示所有Bug已修完、安全已认证或多模型已实现。

M0 只迁移仓库目录、修正当前引用和治理状态，不修 A01—A12、不改变 runtime 或已发布 v0.2；结构验收见 [M0 证据](V03_M0_EVIDENCE.md)。

F01 已通过外部审计 PASS，[PR #32](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/32) rebase 合入 main `144c599a022659f6264762e47a54ca296622f751`，状态 DONE；已发布 v0.2 未变。已有 Windows 定向 76 项、开发全量 514 项与干净包全量 514 项通过，bootstrap、compileall 与本地构建证据有效；负责人确认本阶段无需额外 live smoke，未将离线结果视作真实模型/AO验收。详细证据见 F01 卡。

F02 已通过外部审计 PASS、无需返修，[PR #33](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/33) rebase 合入 main `62f5851a72490074a6cb6030803275a9846d9f45`，状态 DONE。沿用既有 Windows 定向 200 passed / 1 skipped、compileall 证据；原生 symlink 用例因权限不足跳过，真实 junction 用例通过。合并收尾无新增产品修改，未重跑测试、打包或 live；详细证据及未运行项见 F02 卡。

F03 已通过再次外部审计 PASS，[PR #34](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/34) rebase 合入 main `35a67d07ae196368434fbd83a95693b288c6bc6e`，状态 DONE；Worker 已提交 artifact 的交付缺口已闭环。沿用既有 Windows 定向 145 passed / 0 skipped 及此前 F03 证据；合并收尾无新增产品修改、未重跑测试或发布验证，详细边界见 F03 卡。

F04 已通过外部审计 PASS、无需返修，[PR #35](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/35) rebase 合入 main `c51ccd155f7ab6c226454846c9e1f1fff146956d`，状态 DONE。沿用既有 Windows 定向 224 passed、追加 49 passed（分开报告，均 0 skipped）及浏览器/compileall 证据；合并收尾无新增产品修改、未重跑测试或发布验证，详细边界见 F04 卡。

F05 已通过再次外部审计 PASS，[PR #36](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/36) rebase 合入 main `1e1401f7b55ff71617c0e3ef4ab277490b916cff`，状态 DONE。同一 StateStore 持久 operation intent 与结果，ACK 丢失后对账或 UNKNOWN；Stop 请求与 Worker 停止事实分开记录，HTTP 成功回执以持久 receipt 为准。沿用既有定向故障恢复与返修验证，合并收尾无新增产品修改、未重跑测试或发布验证；AO v0.12.9 契约边界见 F05 卡。M1 / M2 COMPLETE；R01 / R02 已审计 PASS 并合入，实现见下文。

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

F02 让 ClosedLoop 生产审批与 AutoApprover 共用范围策略：文件按实际 AO Worker workspace / cwd 解析，先验证根包含性及链接目标，再匹配允许/禁止路径；forbidden 优先，空 allow 不授权。命令保留原始控制字符检查，完整 argv 与 cwd 匹配 Gate；通用查看操作限定参数和目标，Git 写操作不在通用白名单中。

审批使用 AO requestId 和实际提供的单次允许选项，原因与人工处理标记沿用既有记录；未获批请求保留人工入口，不因此立即判整任务失败。未知/畸形请求、复杂 shell 及 AO v0.12.9 未暴露完整目标的 Codex fileChange 审批留人工；路径检查只保证审批时的解析结果，不承诺跨 AO 执行的原子文件系统保证。

当前L0是确定性程序消息，用户directive也能经受控路径发给Worker；不能写成所有消息都由Planner LLM生成。R02 将取消请求、停止确认与取消终态分开；历史 attach 不再组装 runtime。旧 HUMAN 保持原义，不解释成暂停或已取消。现有SSE已存在，v0.3不是从零新增实时更新。

成果保留在runtime/<mission-id>/integration，不自动写回target main/master，不自动push。artifact-aware clean可以忽略正常cache，不等于原始git status为空。runtime linked worktree依赖Git common dir，不能当独立可搬运项目。

F03 共用严格 NUL 路径事实，覆盖 frozen base 之后 committed、staged、unstaged/untracked 的改动，rename/copy 保留双端点、删除保留原路径；无法可靠取证时不当 clean。artifact 按目录段与明确文件规则过滤；untracked diff 使用仓库外临时 index/objects，不修改真实 index。baseline 复用 Gate 完整性检查，Final scope 的确定性违规不能被模型 PASS 覆盖。

materialization 保留正常用户净改动及原有暂存 cache；新交付树将 artifact 精确恢复为 frozen base 的 blob/mode，Mission 合并返回的明确 SHA，使 Worker 已提交的新 cache 不进入最终 integration 树。原 Worker 历史及基线内容保留，不改 ignore/exclude；构造失败进入 HUMAN。该过滤步骤不移动 Worker ref 或修改真实 index，多次 Git 采样仍不承诺并发写入下的原子快照；F05 已将 AO Session 明确终止事实设为 materialization 前置条件，未知停止进入 HUMAN；R02 增加明确取消/恢复契约，见下文。

### R01 有效配置与阶段诊断（DONE）

[PR #37](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/37) 再次外部审计 PASS，2026-09-07 已 rebase merge 到 main `551f7f49198e033b1331ec341ff0d352553bacb1`。合入 tree 与已审计 head 相同，沿用已有 184 / 311 项定向验证，收尾仅同步背景文档，未追加产品修改或重跑测试。

CLI / Panel 共用 `loopcore.effective_config`，优先级为内置缺省值 < `config/default.yaml`
< 新 Mission 的显式参数。CLI `--poll-seconds` / `--cap-seconds` 与 Mission 的 budgets
在冻结前覆盖；来源逐键保留，revision 为规范化有效值 JSON 的 SHA-256。Panel 默认设置
原子替换现有 YAML，整份验证后才提交，不修改当前 runtime。原 Panel 的 300 秒 idle/L0
覆盖和取整移除，统一使用 YAML（默认均 120 秒）；CLI/Panel runner cap 统一为 7200 秒。

新 Mission 在现有 missions payload 中冻结无密钥快照，再做只读 preflight；准备失败仍
有可查记录。已有快照恢复时严格校验并复用，缺失字段不借用新默认值；历史无快照只显示
缺失并拒绝执行续跑。R01 未处理的 attach 组装副作用由 R02 只读入口替代，缺快照仍不可恢复。

| 配置组 / 键 | 当前实际消费者与单位 |
|---|---|
| `runner.poll_seconds` / `cap_seconds` | CLI 和 Panel 共用 run_loop；轮询等待与循环边界 cap，秒 |
| `worker.model` | AO spawn `--model`；含初始与 replan，保持默认 gpt-5.6-sol |
| `worker.spawn_max_attempts` / `spawn_backoff_seconds` | F05 已证明未执行时的有界初始 spawn 重试；次数 / 秒 |
| `worker.spawn/send/kill_timeout_seconds` | 相应 AO CLI 请求的等待秒数；timeout 不证明外部失败，不绕过 UNKNOWN |
| `roles.planner/auditor/verifier.model` / `timeout_seconds` | 各 Codex CLI Provider 实际传入模型与每次调用秒数；未新增取样/供应商参数 |
| `ao.base_url` / `request_timeout_seconds` | AOAdapter 的 loopback REST fallback / 秒；有效 AO runfile 端口优先，外部发现事实不伪装成模型确认 |
| `gate.timeout_seconds` / `output_limit_chars` | Task、baseline、Final 的每条命令秒数 / 每个 stdout、stderr 的证据正文字符上限 |
| `observer.*_seconds` / `turn_diff_counts_as_progress` | ClosedLoop 的 L0/idle/audit/审批等待；保留小数时间戳；EventNormalizer 的 diff 进展开关 |
| `thresholds.repeated_error.*` / `no_progress.*` | Observer 的窗口/冷却（秒）、次数和 weak/strong 进展规则 |
| `fingerprint.*` | Fingerprinter 的规范化开关与 max_length 整数字符数 |
| `budgets.*` / `budgets.subtask_budgets.*` | Mission / ClosedLoop / ActionExecutor 的分解、重规划、局部修复、重复告警和运行预算 |
| `bus.*` | 原 LoopBus 投影约束；明确不等于 Controller 权限或 Mission 预算 |

时间参数为有限数且 `0 < value <= 604800` 秒，不取整、不钳制；计数为整数且不超过
1000000，最小值随语义为 0 或 1，max_subtasks 为 1–2；布尔不当数字。模型为 1–128
字符的明确 ID；AO URL 仅 loopback HTTP、合法端口，无凭据/query/fragment。页面列出
逐键范围、来源和消费者，配置不接收密钥、Prompt 或环境变量映射。

旧 `roles.worker.model` 迁移到 `worker.model`，相同层同时出现且不同则拒绝；相同值也
提示迁移。旧 Panel 顶层四个时间字段迁移到 runner/observer。以下旧无消费者配置从
有效值中移除，并在读取旧文件时明确标为 deprecated / NOT effective，设置 API 拒绝
保存这些键：observer.interval/stall_threshold/failure_threshold/early_warning、
activity_kinds/progress_kinds、auditor.audit_interval、ao.poll_interval/sse_idle_timeout、
roles.max_parallel_workers、Worker transient 重试配置。其他未知键及 YAML 重复键拒绝。

Gate 保留原始 exit/integrity/scope 与 overall。输出上限作用于持久化/后续证据正文，
每个流额外保留原长度、SHA-256、截断标记；失败 ID 在截断前提取，因此 baseline/Final
不会漏掉尾部新失败。现有子进程捕获仍在内存中，此参数不是进程内存限制。截断会触发
F01 的证据不完整边界，必要时进入人工处理，不将片段当完整验证输入。

阶段诊断写入同一 StateStore 的 execution_phases，开始事实先于慢调用，结束事实记录
耗时、attempt、结果及错误类别；不保存完整 Prompt/异常 argv，不触发额外动作。重入后
未完成的旧阶段为 unknown，不伪补结束时间。角色传输计时不取 Mission 总耗时；未调用
角色和历史缺字段分开。Worker 状态复用现有 AO 读取：公开
[SessionView.model](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/httpd/controllers/dto.go)
经 sessions controller 的 `sessionView()` 返回 spawn 时 resolved model，诊断记录为
`spawn_resolved_model` / `spawn_model_evidence`；配置仍是 requested / passed，不能代填缺失外部事实。
[conversation.modelReroute](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/httpd/controllers/conversations.go)
单列为 `model_reroute`（from/to/source），不会覆盖 Session 的创建时模型。外部模型值需是非空、
无控制字符、无首尾空白且不超过 AO 256 字符上限的字符串；缺失/非法为 unknown。
页面兼容旧记录时，仅将有明确 reroute 来源的旧 confirmed_model 显示为历史 reroute，
不回填 spawn 事实。两种事实均不是某次 provider 请求模型或精确计时的证据。
Codex CLI 没有被当前输出契约确认的模型字段，保持 unknown；未报告用量/费用也为 unknown。

Panel 沿用 F04 的 Host/Origin/JSON/nonce 与 textContent 安全渲染；显示默认设置与冻结
配置、在途阶段、独立请求耗时和持久错误。SSE 每次服务实例 epoch + 单调 sequence，
携带 mission_id，重连发送完整快照替换；旧/重复顺序不再应用，不累计事件或重提交动作。
HTTP 接收/响应、浏览器往返、状态快照查询耗时分别展示，不用这些数据宣称模型更快。

### R02 指令、取消恢复与来源（DONE）

[PR #38](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/38) 外部审计 PASS、无需返修，2026-09-07 已 rebase merge 到 main `2377dd03c172461c63d26835e23abe7171e883a9`。合入 tree 与已审计 head `7d91443cd10b95d8238b5febdee4dfa59026e28e` 完全相同；沿用已有定向证据，收尾仅同步背景文件，未追加产品修改或重跑测试。

StateStore 的 `directive_receipts` 是指令回执权威；稳定 `command_id` 重试复用原记录，
冲突拒绝，落盘失败不产生待消费队列。`received` 只表示持久接收；`applied` 对应实际
Planner/Auditor/Mission Final Verifier 输入调用，Worker 则对应 F05 的 AO send 接受，
不代表 Worker 已执行。每个消费者保留主目标/Planner 镜像、时间和原因；未确定输入
完成或 send 结果为 `unknown`，不盲重发。Observer/Gate 没有语义消费者，API 拒绝、页面禁用。
Final Verifier 输入与回执冻结同一组 notes，构造输入期间后来到达的指令不误记已消费。

取消 API 先保存 `stop_request` 和 `cancellation.status=requested`，立即确认请求接收；
Controller 再推进 `cancelling`。当前 Codex CLI/各 Gate 的受控本地子进程可被终止，
取消后返回的结果不能继续推进 Mission。只有本地执行与 AO Worker 停止都已确认，才
记录 `cancelled` / `CANCELLED`；否则是 `unknown` / `HUMAN`。后者不是取消成功。
旧 HUMAN 不迁移；F05 未知动作不重发、未确认停止不 materialize。既有 Git 操作不会
被当成通用可抢占进程；取消后在下一检查点停止，已发生的 Git 事实保留供核对。

CLI/Panel 对既有非终态先打开只读 Store：校验冻结配置/source、当前需要的 Worker
Session/workspace/base、integration commit/clean、未决 operation 和保存的验证关联。
检查没有模型/spawn/send/kill 或 Store 写入，成功后才组装 runtime。UNKNOWN send、
中断的本地过程/语义输入、缺失或关联不符的证据仍拒绝恢复。已合入 integration 的
Worker 不要求保留无用的旧 workspace；integration 本身及 Worker 停止事实仍须成立。

历史 attach 不连接 AO、不构造 Provider、不迁移 schema/补写快照或阶段，仅查询原库；
字段缺失显示 historical unknown/unavailable。无 WAL 内容的历史库以 immutable 只读
方式打开，不产生 WAL/SHM；活跃 WAL 缺必要共享内存材料时明确不可读取，不改库修复。
终态 `MISSION_DONE` / `FAILED` / `HUMAN` / `CANCELLED` 禁止 resume；
`/api/new-attempt` 创建新 identity 与 `previous_attempt`，保留原任务输入、使用自己的
新配置/source/执行历史，旧记录只读。旧 Worker 或本地执行停止仍未知时拒绝新 attempt。

Mission preflight 比较 AO 项目的本地来源分支、origin tracking ref 和 `ls-remote`，
不一致时拒绝，保存 project/ref/policy/exact commit。每个新 spawn 前复查漂移；创建后
根据 Worker HEAD reflog 的创建基线确认，缺失不猜测。integration 直接从冻结 commit
创建，F03 的 Worker/integration frozen diff base 必须与它一致。AO 当前没有 exact-commit spawn 参数，source 检查与 AO 创建不是原子事务；
发生竞态导致创建基线不符时继续 fail closed，不宣称 exactly-once，
不自动重写 branch 或 Git 历史。当前明确拒绝 dependencies 非空的 MissionPlan；
两个独立子任务的有界支持保留。

Worker 初始/replan prompt 包含实际 objective、AC、allowed/forbidden paths、Gate 与
原 user instruction。固定 AO 的 [spawn Prompt 上限](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/httpd/controllers/sessions.go)
为 4096 UTF-8 bytes；完整内容超限直接拒绝，不静默裁掉范围。模型/用量/费用 unknown
和 R01 冻结配置规则不变。Windows 定向 Git/SQLite/fake AO/HTTP 与 Edge 证据见 R02 卡，
未运行全量、安装、打包、smoke、真实 AO/模型或完整 GUI 视觉验收；R01 / R02 DONE，M2 COMPLETE；M3 / U01 仍为 TODO。

## 4. 已验证外部前提

Windows、CPython3.12、Git、AO Desktop0.12.9、Codex CLI0.150.1及ChatGPT登录是v0.2的已验证组合。bootstrap只管理本地Python venv，不安装Python/Git/AO/Codex。

AO executable通过CLAO_AO_BIN或PATH解析；runfile通过CLAO_AO_RUN_FILE或~/.ao/running.json解析。Project需要注册的Git-backed项目、identity、origin及有效remote-backed base；显式branch要求origin/<branch>，auto要求origin/HEAD。origin可以是本地bare repo。不自动修改Git/AO配置。该约束是当前验证过的产品支持范围，不宣称覆盖AO所有潜在能力。

## 5. 审计缺口与修复状态

依据 [原审计](reference/CLAO_v0.2_audit_20260905.pdf)；F01 已补齐 A02 的完整契约与终局一致性及 A11 相关证据边界，F02 已修复 A01 的审批命令与路径包含性，F03 已修复 A03 的路径、artifact 和只读取证，支持边界见上文。其他卡继续保留：

- A04/A05：F04 已实现 Gate 表专用只读 DTO 与 command/integrity/scope/overall 记录、历史 unknown/read_error 区分及常驻错误；本地写 API 校验 Host/Origin/JSON/会话 nonce，路径包含性与安全 DOM/pending 去重已补齐。外部审计 PASS、已合入 main（DONE），已发布 v0.2 不变；验证和支持边界见 F04 卡。
- A07：F05 使用精确持久随机标记对账 spawn；普通 send 无唯一公开回执则保持 UNKNOWN、不重发；kill 需同一 Session 的 isTerminated=true / status=terminated。逻辑终止依赖 AO 公共契约，不承诺 OS 级证明或 exactly-once；再次外部审计 PASS、已合入 main（DONE）。
- A10：R01 已接通有效配置与阶段诊断，再次外部审计 PASS 并合入（DONE）；A06 / A08 / A09 的 R02 指令、取消恢复与 source/依赖已外部审计 PASS 并合入（DONE）；AO/Git 非原子边界保持，不宣称 exactly-once。
- A11/A12 其余范围：多模型、后续 Git 取证边界、结果导出和普通用户使用体验；不因 F01 完成宣称所有证据路径或模型真实性已验收。

状态与证据等级请查 [V03_BACKLOG.md](V03_BACKLOG.md)。不能因为历史R5 COMPLETE把这些问题写成RESOLVED。

队友在既有发布基线上提供的 0.2.1-rc1 候选说明已作为 F01 评审输入；本次独立实现，未移植队友源码或继承其 live 结论，来源记录在 F01 卡。

## 6. v0.3目标与现状严格分栏

| 主题 | 当前实现 | v0.3设计（待实现） |
|---|---|---|
| GUI | 技术拓扑＋任务表单＋SSE | 四入口、iPhone风格层级、任务/结果中心 |
| 模型 | Codex CLI与AO Codex | GLM/Kimi语义profile，Worker单独准入 |
| 配置 | R01 已合入；R02 恢复先验证冻结材料 | 新 GUI 的配置旅程 |
| 结果 | integration路径与日志 | 可独立应用的patch导出与证据摘要 |
| 停止 | F05 已合入；R02 明确取消状态、只读历史/恢复检查、关联新 attempt（DONE，已合入） | 新 GUI 的操作与错误体验 |

## 7. 文档职责与历史

AGENTS=规则；PROJECT=事实；PLANS=当前指针；V03_PLAN=目标设计；V03_BACKLOG=任务/证据。只有大写docs/PROJECT.md作为开发事实文件；runtime/project.md不属于项目治理。

原R0—R5历史文档未从Git历史删除，完整冻结内容见：

- [v0.2原PROJECT](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/blob/4d3e8e6b5e70bab868b2eef0d28c7742dea044ba/docs/PROJECT.md)
- [v0.2原PLANS](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/blob/4d3e8e6b5e70bab868b2eef0d28c7742dea044ba/PLANS.md)
- [v0.2Release](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/releases/tag/v0.2)

以后本文件仅按已合入代码或明确标注待审计的分支实现与验收更新，不复制完整PR流水账；旧治理文件的目标性措辞不再凌驾于本文件和v0.3批准设计。
