# CLAO v0.3 任务与验收台账

版本：0.3-plan-r1 · 2026-09-06。状态：已批准 / IN EFFECT。DOC-00、F01–F05、R01 / R02 已完成（DONE），M0 / M1 / M2 为 `COMPLETE`；U01 / U02 / U03 均已审计合入（`DONE`），U02 两个切片保持 `DONE`；M3 `COMPLETE` 表示本阶段开发与代码审计完成，完整体验与发布验收尚未完成；M4 `IN_PROGRESS`，P01/P02 工程切片均已审计合入（`DONE`），两张整卡保持 `IN_PROGRESS`；原生底座基础集成已完成，整体迁移仍 IN_PROGRESS；角色决策切片 DONE；当前唯一切片为 原生迁移收官大阶段（IN_REVIEW）；PR #48 恢复/指令回执 DONE，外部代码审计 PASS 并已合入，联合真实评测暂缓；其余功能卡状态见下表，原报告的发现不等于已复现或已修复。

设计以 [V03_PLAN.md](V03_PLAN.md) 为准。当前唯一任务由根目录 [PLANS.md](../PLANS.md) 指定。本文件保存每张卡的详细状态和证据，PLANS 不重复整张台账。

## 状态与记录格式

`TODO → IN_PROGRESS → IN_REVIEW → DONE`；外部前提阻塞为 `BLOCKED`。DONE 需要代码／测试／范围审计符合该卡完成定义；仅生成 PR 不等于 DONE。需要 live 的卡可先写 `IN_REVIEW，offline PASS / live PENDING`，不能先写全部通过。

每卡更新只追加：日期、执行基线、分支、commit/PR、测试环境与命令、red/green结果、live/GUI证据等级、风险、下一步。不得复制大日志、用户Prompt、凭据或真实机器路径。调整范围／依赖由负责人批准，在 V03_PLAN 决策记录说明。

## A01—A12 映射

### M4 当前迁移：AO 原生底座 + CLAO 闭环

- 2026-09-09 负责人更新路线；PR #45 被替代、不合并，原分支及证据保留。不再向旧 Panel 逐项翻译执行器/模型页。
- 基础切片“AO 原生底座 + 单 Worker 验收闭环基础集成”：**DONE**；[PR #46](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/46) 启动失败返修已通过外部代码审计，2026-09-10 已 rebase 合入 main。迁移工作树与 `codex/ao-native-closed-loop` 分支保留。**整体迁移 / M4 IN_PROGRESS**；M0–M3 COMPLETE 与 P01/P02 工程 DONE 仅为旧底座历史。
- AO v0.12.12 / `84fb37ce5aa947ceb9b19b0c2435b242ac92ce26` 原样导入在独立提交 `81d2ea9`；后续增量可单独审计。原生模型/账号/Session/终端能力保留，交付不再以登记 27 个入口为指标。
- 实际入口、控制权、当前支持及未迁移能力见 [ao/CLAO.md](../ao/CLAO.md)，直接验证与截图见 [原生证据](reference/ao-native/README.md)。真实模型/账户/套餐未运行；Codex 隔离账户安全阻塞单列，不假称全执行器兼容。
- PR #46 局部返修：项目页直接查询持久 Mission，启动失败无 Session 也可查看原因和原请求；原生 owner 关联回执丢失保持 UNKNOWN/停止入口，已确认未启动记 FAILED 并允许新尝试。新提交身份与分支不复用旧请求，保留草稿；不放宽 `account_storage_unsafe`。本次定向故障/桌面证据及准确启动命令见上述入口。
- 已接：原生项目/模型入口、单 Worker 的 Session/工作区接线、Gate/范围/完整性、有界修复、独立 Verifier、启动请求可见/失败处理及验收面板。
- 当前唯一切片：**原生迁移收官大阶段，IN_REVIEW**；PR #48 恢复/指令回执已审计 PASS 并合入（DONE）。角色决策切片已审计合入（DONE）。上述来源、结果、导入与运行图纳入本阶段；任意在途执行恢复、真实准入及正式发行入口仍未完成。P01/P02 联合真实评测继续暂缓，P03 不开始。
- PR #46 收尾仅检查文档链接与差异，不重跑既有验证。沿用 Windows/离线集成与 Electron 检查、Codex 截图自查；本次为外部代码审计 PASS，负责人完整体验、真实账户/模型及发布验收尚未完成。`account_storage_unsafe` 保持待解决，xfailed 不是执行通过；保留空账户隔离开发入口，不切换正式发行入口。

### 原生迁移收官大阶段（2026-09-11 授权）

- 状态 IN_REVIEW；唯一当前阶段，已完成内部实施、交叉复核与集成检查，提交一个阶段 PR 等待外部审计；不逐个内部子任务另设外部审计关卡。
- 范围：普通/空/无远端/未提交来源的隔离快照；有价值且无依赖的最多两个子任务与最终集成；固定结果/独立补丁包；显式、幂等、只读的旧历史导入及实际连接消费者；只读运行图；统一原生旅程与稳定开发入口。
- 本轮不使用真实账户/Key/收费模型，不修改主目录 default.yaml、官方 AO/.ao 或旧数据；整体迁移/M4 不提前完成。沿用 PR #46/#47/#48 证据，合并收尾不重跑测试/构建。

- 实现与接线：AO 管理本地目录入口；确认磁盘 revision 后调用原来源过滤/快照，私有 Git 基线承载源内容，无需 origin/先提交。原目录/index/分支不写回。最多两个无依赖、范围与 AC 可分离的 Planner 子任务，嵌入同一 Mission 持久记录/调度 owner，共享修复预算；子任务 Gate 通过后集成精确净交付 commit，再运行 Mission 全部 Gate/独立 Verifier。
- 结果：原生文件差异组件读取固定 base/result；独立 ZIP 为完整补丁、清单、必要摘要、说明，包不含完整基线/依赖。沿用文本及敏感规则，二进制/链接/子模块不扩范围；子任务仅看差异和 Gate，不能独立导出为 Mission 验收通过。原目录失效后已保存包按记录校验下载。
- 旧记录：用户明确选择旧文件/runtime，只读投影保存到当前 AO SQLite；历史不变成可恢复原生任务。配置按内容版本幂等导入，连接身份不覆盖。GLM/Kimi 旧标准 API 可用于 Planner 两类调用、Auditor、Verifier，模型/参数/计费/服务冻结；不替代原生模型目录。重新连接保存独立 OS 引用版本，不覆盖旧 Key；旧外发同意失效，旧任务不静默换账号。原重试参数仅保留兼容说明，本原生语义通道单次调用、不盲重发。
- 内部审查与修正：子任务最终验收误标；运行图父 Worker/集成 Gate/等待字段；配置修正重导入死路；连接更换 Key 的确认与冻结版本；Session 恢复丢私有仓库路径；AO 后台恢复在闭环 owner 前重建/移动工作区。相应消费者与负例一并修正，不削弱未知动作、停止、范围和角色权限。
- Windows 正式 API/Git/SQLite 阶段旅程：`test_ao_native_closeout.py` 初批 **7 passed / 167.52s**，含普通/未提交/空来源、原项目不变、ZIP 下载解压与独立补丁应用、两个真实 Session、实际 daemon 重启/双继续、取消和共享一次修复预算。新增子任务成功但 Mission 最终 FAIL 的导出负例通过。仅替换外部引擎，非整套假 Controller。
- 旧连接正式 HTTP：`test_ao_native_legacy_integration.py` **2 passed / 36.01s**，真实 AO/角色/SQLite/Git/Gate→GLM Auditor/Kimi Planner/GLM Verifier 本地 HTTP 边界，缺服务同意零外发，配置版本、系统凭据 generation 与旧引用保留。只创建随机隔离测试凭据，finally 精确清理；未读取用户 Key。
- 验证中发现并保留的首轮失败：nil exports 读取、固定结果目录被 Session 关联覆盖、空基线测试 archive 解析、重新连接引用超出 48 字符、原生后台恢复错误 repo 移动测试 worktree、空首页缺本地项目入口。已针对原因修正；后续最终检查与原生截图见本卡下方及 [原生证据](reference/ao-native/README.md)。
- 最后恢复复查：真实 daemon 重启的 Gate 前、已保存决策、固定成果、已完成 Verifier 四个检查点通过；发送 intent 写入失败后的未发送修复、原生 Chat/语义镜像消费者、Worker 交付 ACK 丢失恢复 **3 passed / 96.64s**。发送未发生时在原进程确认停止，真正丢失进程事实仍 UNKNOWN；六个 SQLite 故障子例与实际消费者经独立交叉复核。
- 开发/界面：Go 开发 daemon 构建、相关 claoloop/process/SessionManager/worktree 定向、TypeScript、Python compileall、JS 语法和文档/差异检查通过；specgen 本次按名称过滤未选中测试，仅编译，不计行为测试。前端创建/来源/结果/连接确认最终选集分别 21 passed、29 passed（有重叠，不累计）。实际 Electron 完成原生模型菜单搜索点击、普通目录完整任务/差异/AC/结果包下载解压及独立 git apply/Gate、旧配置显式导入、真实双 Worker 运行高亮与父 Mission 最终验收。七张当前截图已自查，非负责人体验验收。
- 集成中 Electron 的并发验收进程曾返回 Windows 0xc0000142；非交互 Git/Python 改为复用上游 process.CommandContext 隐藏进程启动后，同一完整旅程通过。另一次最终回归入口遗漏 Go PATH，只有 fixture setup 失败，补齐既有工具路径后重跑原断言通过。无新增 Gate 自动重试、无安全条件放宽。
- 内部交付审查：Coordinator 集成并检查实际代码/截图；Implementer 交叉审阅非本人模块，独立 Reviewer 发现的问题修正后再次复核。覆盖父/子结果、scope/共享预算、冻结连接、持久来源恢复、异步界面归属及未发送修复停止，不以子智能体完成报告代替最终验证。没有未处置的内部代码 blocker。
- NOT_RUN：真实账户/模型/套餐与质量/用量准入、全量、安装器/发行打包、smoke、负责人完整体验。Codex account_storage_unsafe 的上游祖先 ACL 条件仍阻塞本机空账户路径；未更改 ACL、官方 AO 或账户，不将 xfailed 计为运行通过。正式入口未切换，整体迁移/M4 IN_PROGRESS。

### 原生运行恢复与用户指令回执切片（2026-09-10）

- 状态 **DONE**（2026-09-11 外部代码审计 PASS，已 rebase 合入 `5ea76ab8`）；[PR #48](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/48)，实现提交 `7a44cf8`；基线 main `157093b`，分支 `codex/ao-native-recovery-directives`。复用当前 AO Mission/Session/SQLite，迁移可确认阶段继续与 Worker/语义角色指令回执；不重放未知副作用，不回写终态。PR #46/#47 DONE，整体迁移/M4 IN_PROGRESS。
- 产品接线：Mission 保存 checkpoint/输入摘要、正式角色响应、原生消息/回合身份和指令消费者；显式继续复用原阶段/Session/base/模型/预算。Gate/固定产物在途结果丢失或输入变化不重跑；原生未知动作不重发。角色输入冻结，Planner 镜像单列；原生 Chat 与新增表单共用接收边界，终态新尝试保存 parentId。详细阶段/限制与完整本机入口见 [ao/CLAO.md](../ao/CLAO.md#运行恢复与用户指令回执)。
- Windows HTTP/Git/SQLite：`pytest clao/tests/test_ao_native_recovery.py` 的 **15 个直接回归**，连同两个兼容复核最终 **17 passed / 329.32s**。覆盖真实 daemon 终止/重启、Worker 完成/Gate 前、角色输入与已存决策、已恢复但尚未发送动作、固定产物/Verifier 已完成、发送与替换 ACK 丢失、停止/取消、输入变更拒绝和接收持久失败。引擎边界用协议替身，AO Manager/Chat/Store/Git 和 Python Gate 未替换。
- 兼容选集：审批/禁止路径、取消语义角色、五动作、混用 Worker、冻结默认和普通 AO Chat。首轮 19 项中 17 passed、2 failed；发现零替换预算应保持 HUMAN（已修正），另一次普通 Session kill HTTP 连接重置而 daemon 记录 200；保留断言复核两项通过，不把首轮失败隐去或累计成全量。
- Go：claoloop 包定向通过（含取消在恢复检查失败时仍有 owner、主消费与镜像/后续 UNKNOWN 分离）；Chat 的 Send/Steer/Queue 与 HTTP 受影响定向通过。API schema 生成及 TypeScript 检查通过；Python compileall、差异与文档链接检查通过。新增前端回执 + 原生创建测试 **17 passed**，包含 A/B 同文/异文草稿、原 Worker 目标与后续同文编辑保护。
- 实际 Electron：开发构建、原生菜单展开/搜索/点击、同一数据 daemon 重启后继续原任务、专用输入与原生 Chat 交付、Planner 镜像及 A/B 历史切换/延迟响应通过；[继续原任务](reference/ao-native/recovery/continue-original.png)、[验收结果](reference/ao-native/recovery/continued-result.png)、[消费回执](reference/ao-native/recovery/directive-consumers.png) 已由 Codex 自查。脚本修正了重启后的原生弹层关闭和 Lexical combobox 定位；不是生成图或整套假 Controller。
- 故障检查也修正了存储错误误落 HUMAN、动作恢复重复扣预算风险、恢复/取消 owner 交接和 Worker 新消息与停止的竞争窗口。角色 fixture 只从实际输入对象解析，支持追加指令后仍校验原 Schema；没有删失败用例或放松安全断言。
- NOT_RUN：真实账号/Key/登录/模型/套餐、全量、smoke、发行构建/安装、完整体验/全执行器兼容。`account_storage_unsafe` 原样保留，xfailed 不算执行通过。PR #48 交付时这些来源/导入/结果/运行图尚未迁移；现已审计合入，新增能力见当前收官阶段。历史缺 checkpoint 只读，任意未确认执行与正式发布边界仍保留。

### 原生 Planner/Auditor 与角色配置切片（2026-09-10）

- 状态 **DONE**；[PR #47](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/47) 再次外部代码审计 PASS、无返修阻塞，2026-09-10 已 rebase 合入 main `e1a6cbfb889d403de26ba01f349f56fd43852a0a`。实现提交 `1378c51`，默认模型返修 `752f617`；原分支 `codex/ao-native-role-decisions` 保留。基础切片 DONE；整体迁移/M4 IN_PROGRESS；旧 M0–M3 与 P01/P02 工程历史保留，联合真实评测暂缓。
- 复用旧 Auditor/Planner Prompt、Schema、ID/目标/AC/一致性及完整证据限制，通过原生 Chat 独立只读 Session 执行。正常路径不加 Auditor/Planner；失败记录关联审核、决策、一次动作及 Gate/Verifier。角色配置冻结，缺字段历史不伪造新角色记录。
- 五动作：CONTINUE 仅观察/一次确定性复查；SEND_LOCAL_FIX 只发当前 Worker 一条修复；REPLAN_SPAWN 停止后从原 base 替换、原目标/AC/范围/Gate 不变；CANDIDATE_DONE 只触发验收；HUMAN 合法结束自动处理并允许新尝试。有限预算/同一文件证据无进展阻止重复链。没有多任务分解、并行 Worker 或新的状态权威。
- 只读权限与不可变 owner 扩展至全部角色；操作回执丢失按精确 owner 关联，保留 UNKNOWN、不重发。取消覆盖所有关联 Session，迟到结果不触发动作。Codex 只读 sandbox、禁用继承 MCP/子 Agent/联网工具；OpenCode 原生临时 agent 禁用所有工具、ACP 不批准提权；不改用户原生配置。
- 直接 Windows 验证：真实 AO HTTP/SQLite/Session/Git + 外部协议替身 **27 passed / 1 xfailed**；独立 Kimi Worker + OpenCode 角色、不同模型、五动作、回执和取消均覆盖。Python 角色负例 **15 passed**；原生创建对话框 **16 passed**（另补预算输入与历史角色字段兼容各 **1 passed**）；Go 定向、类型/开发构建、Electron 原生菜单与正常/修复/HUMAN 旅程见 [开发说明](../ao/CLAO.md#角色决策与配置切片)。不是真实模型或全执行器兼容证明。
- 首轮检查修正了空集合字段、Verifier 错误归属及“设置 ACK 不能冒充模型回传”；Go 相关测试改用 Windows 临时绝对目录。首轮一项 HTTP 连接重置，保留相同断言复查通过。首轮 Electron Git 子进程 `0xc0000142` 未启动 Mission，界面保留真实错误；独立复查正常完成，未放宽账户/权限检查。
- 补充定向：同文件证据无进展 **1 passed**、明确模型回传与冻结选择分离 **1 passed**；Go 新增恢复/模型来源校验通过（构造夹具补齐原生 capability map），不改业务断言。
- PR #47 默认模型返修：修正实际 `launchChatController` 和 Chat 恢复重新合并项目模型的缺口；预检、Session 权限记录和执行入口复用同一选择规则。闭环空型号明确为执行器不覆盖、继承为当次 Worker 选择；项目已选型号作为确认值冻结。普通 AO 的默认继承不变，不改历史记录。新增正式 HTTP → SessionManager → Chat → ACP 协议回归，在 Worker 等待时改项目默认，覆盖跨执行器默认、明确型号、继承、后续三角色、局部恢复及替代 Worker；另有普通 AO 继承/显式覆盖正例。仅外部引擎替身，真实 Git/SQLite/Controller 保留。
- 返修 Windows 定向：`test_ao_native.py` 的默认模型/普通 AO/显式角色共 **6 个用例分批通过**（4 个默认变化场景、1 个普通 AO、1 个已有显式角色回归）；首次新用例因空 `roleCalls` / `roles` 被 API 省略而读取失败，改按现有省略契约读取，完整执行/型号断言保留。SessionManager 首次 Chat/恢复参数与既有配置/权限检查通过（含 7 个新增表格场景）；Go daemon 开发构建、Python compileall、diff-check 通过。未改前端/API 结构，未重跑浏览器/全量/smoke/发行/真实账户或模型；`account_storage_unsafe` 边界不变。返修提交时 IN_REVIEW；现已再次审计 PASS 并合入（DONE），整体迁移/M4 IN_PROGRESS。
- 截图：[原生角色模型菜单](reference/ao-native/roles/roles-native-model-menu.png)、[正常独立复核](reference/ao-native/roles/roles-independent-verifier.png)、[审核/规划/修复](reference/ao-native/roles/roles-audit-planner-repair.png)、[交人工](reference/ao-native/roles/roles-human-decision.png)。实际 Electron 截图已由 Codex 自查，不等同负责人完整体验验收。
- 合并收尾：完成范围限于单 Worker 的异常诊断、五类 Planner 动作、独立只读语义 Session、四角色执行器/模型配置与冻结选择贯通实际启动/恢复、原生角色/决策展示。不等于全部 Planner、全执行器或逐角色独立账号准入。下一项为 **运行恢复与用户指令回执迁移，TODO**；多子任务分解/并行、普通目录/未提交来源、旧历史/连接/凭据导入、结果中心/独立导出、闭环运行图与正式入口仍待迁移。本轮只做文档链接与差异检查，不重跑已有 Windows/Go/契约/Electron 证据；源码审计不等于负责人完整体验。主目录用户配置、开发工作树/依赖/独立数据及 PR #45 历史分支保留。
- NOT_RUN：真实账户/模型/套餐、全量、smoke、发行安装包与完整体验。Codex 隔离 `account_storage_unsafe` 仍待解决，xfailed 不计执行通过。后续恢复/指令回执、旧连接和历史导入、普通目录来源、导出/结果中心与运行图均未实施。

### 原发现映射（历史）

| 原编号 | 原报告性质 | 本版落点 |
|---|---|---|
| A01 审批／包含性 | 源码＋隔离负例 | F02；安全规则不能被GUI绕开 |
| A02 终局一致性 | 源码＋判定条件复演 | F01；P01/P02沿用 |
| A03 Git路径／取证 | 源码＋临时Git复演 | F03 |
| A04 Gate查询／错误显示 | 源码＋SQLite复演 | F04；U02 |
| A05 本地API／HTML | 源码＋字符串复演，浏览器可达性待测 | F04 |
| A06 指令消费 | 源码／异常窗口 | R02 |
| A07 外部动作／kill | 源码推断，需故障注入验证 | F05 |
| A08 Stop/Resume | 源码语义不一致 | R02；U02 |
| A09 双任务／基线 | 静态调用顺序风险，需验证 | R02；不能支持的依赖计划明确拒绝 |
| A10 配置／性能 | 源码消费者差异 | R01 |
| A11 多模型／证据 | 现状差距与设计任务 | F01；P01/P02/P03 |
| A12 交付／维护 | 现状差距与设计任务 | U03；Q01 |

## 总表

| ID | 阶段 | 标题 | 依赖 | 状态 |
|---|---|---|---|---|
| V03-DOC-00 | M0 | 规划入库与基线核对 | 负责人批准 | DONE |
| V03-M0-LAYOUT | M0 | Repository layout consolidation 与本机副本整理 | DOC-00 | DONE |
| V03-F01 | M1 | 完整契约与终局一致性 | DOC-00 | DONE（PR #32 审计 PASS / merged） |
| V03-F02 | M1 | 审批命令与路径包含性 | DOC-00 | DONE（PR #33 审计 PASS / merged） |
| V03-F03 | M1 | Git路径、产物规则与只读取证 | DOC-00 | DONE（PR #34 审计 PASS / merged） |
| V03-F04 | M1 | Gate查询、本地API与安全渲染 | F01的结果字段约定 | DONE（PR #35 审计 PASS / merged） |
| V03-F05 | M1 | 停止确认与未知外部动作保护 | DOC-00 | DONE（PR #36 再次审计 PASS / merged） |
| V03-R01 | M2 | 有效配置与阶段诊断 | F01/F04 | DONE（PR #37 再次审计 PASS / merged） |
| V03-R02 | M2 | 指令回执、取消恢复、固定基线 | F03/F05/R01 | DONE（PR #38 审计 PASS / merged） |
| V03-U01 | M3 | iPhone风格界面骨架与状态夹具 | G1；R01/R02字段设计 | DONE（PR #39 代码/产品整改审计 PASS / merged） |
| V03-U02 | M3 | 完整任务GUI与数据接线 | U01/R02/F04 | DONE（首切片 PR #40、完整旅程 PR #41 均再次审计 PASS / merged） |
| V03-U03 | M3 | 结果中心与独立导出 | U02/F03 | DONE（PR #42 再次外部审计 PASS / merged） |
| V03-P01 | M4 | 模型配置／凭据与GLM语义后端 | F01/R01/F04 | IN_PROGRESS（工程切片 DONE；真实准入待集中验证） |
| V03-P02 | M4 | Kimi语义后端与切换评测 | P01 | IN_PROGRESS（工程切片 DONE；真实准入/评测待验证） |
| V03-P03 | M4 | 第二Worker能力准入决策 | P01/P02；AO官方契约 | TODO |
| V03-Q01 | M5 | 新Windows产品验收与发布候选 | G1—G4 | TODO |

G1=F01—F05；G2=R01—R02；G3=U01—U03；G4=P01—P02及P03有记录的支持/拒绝决策；G5=Q01。

## V03-DOC-00｜规划入库与基线核对

- 目标：把负责人批准的规划变成唯一可查询上下文，先不实施产品。
- 范围：AGENTS、PROJECT、PLANS、V03_PLAN、V03_BACKLOG、根README、原审计PDF引用。不得改产品、manifest或builder。
- 检查：main最新SHA；已发布tag不变；7个预期文件；链接有效；不存在另一份开发project.md；旧治理历史可由固定提交访问。
- 完成：负责人批准的 7 项规划／治理文件及附件已进入 main，产品 blob 变更=0；功能下一任务为 F01。本次入库由用户直接提交，Git 历史为依据，不声称存在文档合并 PR。
- 状态：DONE；2026-09-06，`DOC00_BASELINE_PASS`。
- 证据：main `3a9ea27468915eb9571611bcca10962e7a732fb0` 相对发布源码 `4d3e8e6b5e70bab868b2eef0d28c7742dea044ba` 的差异恰为预期 7 项；106 个产品 blob、builder／manifest 均一致；12 个当前 Markdown 中 17 个本地链接有效。
- 源码核对：Panel／CLI 共用 build_runtime；Controller／ClosedLoop、Store、AO、投影边界与 PROJECT 一致；Stop、attach、弱 Schema 与 best-effort kill 缺口仍存在，不将规划要求写成已实现。
- 规则核对：根规则的安全和模型条款属于实施约束；PROJECT 记录当前缺口。历史 nested AGENTS 只适用历史目录；本次 M0 追加授权见 V03_PLAN D09，不启动 F01。

## V03-M0-LAYOUT｜Repository layout consolidation

- 状态：DONE；2026-09-06；分支 `task/v03-m0-repository-layout`；[PR #31](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/31) 人工审计 PASS；M0 COMPLETE。
- 范围：Git rename、必要路径／名称适配、当前文档与 canonical URL、本机重复副本分类整理。
- 验收：完整 pytest、compileall、当前 Markdown 本地链接、diff-check、clean committed HEAD builder、artifact file set／hash／hygiene；唯一 canonical development clone；独立 PR 与人工审计 PASS。
- 边界：不修 A01—A12，不改 runtime／依赖／loopcore 包名，不改变已发布 v0.2；F01 保持 TODO。
- 证据：`9344bff` 关闭 DOC-00；`68bf256` 迁移 308 文件且零内容增删；`667ce95` 适配 manifest／注释／治理路径。定向 88 passed；全量 438 passed in 105.61s；compileall、diff-check 通过；收尾复核 13 个当前 Markdown 的 23 个本地链接全部有效。
- 构建：clean HEAD `667ce95deb2b4baae2a22fcfa394c4c2b5e55d4d` builder exit 0；92 个产品文件 + checksum，唯一顶层 clao/；逐文件 SHA-256、HEAD blob、hygiene、secret/path scan PASS；产品文件集变化 0。已验证的后续文档提交 `06bfb67` 构建结果记录于 PR 与本机证据；本次最终收尾仅修正文档状态，产品与发布工具 blob 不变，沿用原验证结论。
- 整理：唯一指定开发 clone 已建立；旧源码 ZIP 全部 25 个 blob 与 legacy 相同；发布包与设计快照归档，旧测试 worktree 用 Git move 保留；历史 refs 和 runtime 完整保存。AO 仍引用的 v0.1 clone 原地保留，原工作区空目录因占用／清理审查拒绝保留，不虚报桌面完全清空。详见 [M0 证据](V03_M0_EVIDENCE.md)。

## V03-F01｜完整契约与终局一致性

- 状态：DONE；2026-09-06 负责人确认外部审计 PASS、无代码修改问题；[PR #32](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/32) 已 rebase merge 到 main，合入提交 `144c599a022659f6264762e47a54ca296622f751`。实际 base `26b02e9d3e1d72cde3b29143d96ed4e096391249`；原代码提交 `bf4601bb3d4bcc119349e20e99a2689ddb7778aa`（rebase 后 `fae3e5c`）；分支 `task/v03-f01-contract-consistency`。

- 对应：A02、A11。落点：mission_contracts.py、verifier.py、mission.py、必要Provider/schema/requirements/bootstrap与直接测试；以实际调用链为准。
- 工作：先复现顶层PASS但AC FAIL等负例；移植或重做必要的完整validator，评审队友补丁，不整目录覆盖。取消弱fallback；强制关联、覆盖、有限数值、结果一致性和证据截断语义。
- 必测：错误verify/task/mission ID；AC缺失/重复/未知/UNVERIFIABLE；anti-gaming FAIL；畸形列表；NaN/Infinity；证据缺口。正常合法PASS仍可到MISSION_DONE。
- 完成：负例全部不能成功；本地protocol failure与语义FAIL区分；同一规范供新供应商复用；Windows离线和受控Codex角色smoke按变更影响执行。
- 不做：更换默认模型、动态高风险Verifier、放宽Gate。
- 红证据：改产品前，Windows 原始 base 上 `python -m pytest tests/test_f01_contract_boundary.py -q --tb=line` 得到 **17 failed / 65.25s**，多类非法结果实际进入 MISSION_DONE；随后从同一 base 的 Git archive 在仓库外重跑扩展产品集（含离线进程拦截），**33 failed、1 passed / 284.50s**，覆盖终局、历史重放、语义 FAIL 重试与协议耗尽。均使用本仓库 CPython 3.12 venv；非 Linux、非 live。
- 实现：必需 `jsonschema==4.25.1`；启动检查本地 Schema；共享 JSON/Schema/有限数值/关联边界；拒绝错误输出而不补 ID、改列表或改结论。Mission final 显式以 Mission ID 填充现有 VerifierResult.task_id；MissionPlan 维持既有 mission_id 关联字段，不另造协议。
- 终局：Controller 再查完整 AC 恰好一次、PASS 与分项/anti-gaming 一致性；复用现有 scope checker，Gate/范围/integrity 失败先阻断。Task 历史和 Mission final 重放都校验 Schema、关联、覆盖和保存的输入摘要；损坏/缺字段/缺验证上下文进入人工处理，不改写历史终态或伪补成功。
- 证据：Git diff 的角色调用取消上游裁剪，Gate 保留完整 stdout/stderr；实际模型输入按部分携带 content、original_length、sha256、truncated/missing、omitted_chars。Verifier 的 diff/Gate 各限 6000 字符，整体 CLI Prompt 限 64000；关键缺口进入明确处理。Auditor 可对带缺口标识的材料作非 PASS 诊断，不能据此通过。
- 错误边界：纯协议输出最多 2 次，耗尽由 Controller 记录 PROTOCOL_FAILURE 并 HUMAN；合法语义 FAIL 原样记录、不重试。纯传输按原 Controller 最多 3 个连续失败 tick；混合协议/传输最多 6 次调用（decomposition 更早停止）。成功重试也保留先前错误类别与响应摘要，不保存完整 Prompt；不新增跨供应商 fallback。
- 测试维护：保留原用例意图并修正静态错误 ID、空 evidence 等非法夹具；旧“强制降级 PASS、空列表纠正、刷新合法 FAIL、Provider 伪造 HUMAN”预期替换为显式协议拒绝和合法 FAIL 原样留存；状态及 SQLite 证据由 `test_f01_contract_boundary.py`、`test_f01_schema.py` 与原回归共同覆盖。离线 conftest 拦截真实 AO/Codex 进程启动。
- Windows 实测：CPython 3.12.7；pytest 9.1.1；jsonschema 4.25.1。最终定向 **76 passed / 100.95s**；完整 `tests` **514 passed / 177.68s**；均 0 failed、0 skipped；加严原语义 FAIL 状态断言的 4 项回归另跑通过。compileall、diff-check 通过；7 个当前治理 Markdown 的 22 个本地链接有效。干净包同版本 venv 全量 **514 passed / 183.21s**（0 failed、0 skipped），包内 compileall 通过；上述为既有 Windows 离线证据，合并收尾未重跑。
- 命令：从 `clao/` 将 `.venv\Scripts` 前置 PATH、`src` 设为 PYTHONPATH，用 `.venv\Scripts\python.exe -m pytest tests/test_f01_contract_boundary.py tests/test_f01_schema.py -q`、`-m pytest tests -q`、`-m compileall -q src panel run_mission.py`；仓库根 `git diff --check`。
- 安装/打包：从 clean committed `bf4601b` 用原 `packaging/build-release.ps1 -OutputDirectory <仓库外新目录>` 构建，exit 0；96 个产品文件 + SHA256SUMS，顶层 clao/。96/96 checksum 与独立 HEAD archive export 逐字节一致；原始 blob 比对为 2 个完全相同、94 个仅 Git `core.autocrlf=true` 导出的 CRLF 差异，未把换行差异虚报为 raw blob 相同。manifest 前缀已覆盖新 helper/测试；无 .venv、runtime、日志或密钥，链接/敏感内容扫描通过，未改 builder/manifest。
- 干净安装：新目录解压上述 ZIP，运行包内 `bootstrap.ps1`，exit 0；创建新 CPython 3.12.7 venv，安装并验证 PyYAML 6.0.3、pytest 9.1.1、jsonschema 4.25.1 及本地 Schema，然后按同一 PATH/PYTHONPATH 方法执行包内全量与 compileall。代码包 ZIP SHA-256：`54866c30de5fe3eaa2e0cb04b61b34d43b8919f60bc5577265e3e20e5aa12522`。本地构建彩排，不创建 tag/Release；后续仅治理文档变更以产品 blob/包文件等价核对。
- NOT_RUN：真实角色 smoke、AO Worker、真实 Mission、GLM/Kimi、GUI live，未执行。2026-09-06 负责人明确本阶段不要求额外 live smoke，确认既有 Windows 离线、干净包与构建证据有效，并授权审计 PASS、合并后将 F01 标为 DONE；不将未运行项写成 live PASS。
- 残余边界：F02/F03/F05/R02 的底层审批、Git 路径解析/取证、外部动作停止与生命周期问题仍在原卡范围；本修复只阻断已有确定性失败。证据过长保守进入人工处理；重放要求输入摘要相同（Gate 输出变化亦会阻断），不声称模型真实性已验收。
- 来源：阅读 S09 固定 `7b30184ff19922dd6af03c874ac2ba9c6c5dd77e` 候选说明作为评审输入；本次独立实现，未移植队友源码、命名、发布工具或历史验收结论。

- 历史交付阻塞（已解除）：2026-09-06，提交 `65e9922` 后 push 共 **20 轮**，含首次；轮间等待 10 秒。均为连接重置或 TCP443 无法连接；每次写入失败后通过 GitHub API 核对，当时任务分支仍不存在、PR 未创建。达到授权上限后停止网络操作并以 `205eb3b` 记录，保留本地分支与包。
- 历史恢复交付：同日用户确认 TCP443 恢复并授权新一轮最多 20 次推送；第 **1** 次推送成功并创建 PR #32；文档追加提交在该轮第 **8** 次推送成功，最终远端 head 为 `ff47fc90d8298a2034764f7ab7fee1272597947c`，当时状态 IN_REVIEW。该次只更新 PLANS、BACKLOG、根 README，产品及发布工具与已验收 `bf4601b` 的 blob 相同；治理链接及 diff-check 通过，未重跑 pytest/live；当时未合并或标 DONE。
- 合并收尾：2026-09-06 按负责人授权完成 rebase merge，合入 tree 与已审计 PR head 完全相同；本地 main 正常 fast-forward 到合入提交。仅更新 PLANS、BACKLOG、根 README 与 PROJECT 的状态及当前实现事实；产品/发布工具 blob 未变，沿用既有验证，不重跑 514 项测试或构建。F01 DONE；下一任务 F02 TODO，未开始实现；未创建 tag 或 Release，已发布 v0.2 不变。

## V03-F02｜审批命令与路径包含性

- 状态：DONE；2026-09-06 负责人确认外部审计 PASS、无需返修；[PR #33](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/33) 已 rebase merge 到 main，合入提交 `62f5851a72490074a6cb6030803275a9846d9f45`。base `409127d598d678dc98a2f6e6cb3087d9d950cd16`，原实现提交 `6717c453e6aad8730b180295ae87241749110201`（rebase 后 `1dc392f`），分支 `codex/v03-f02-approval-boundaries`；F01 保持 DONE。
- 对应：A01。落点：ClosedLoop生产审批路径、approvals和相关测试。
- 工作：先查真实AO请求结构，再规范原始输入与路径；解析不明不授权；exact module/argv、不用双向前缀和先折叠换行。
- 必测：报告所有predicate负例；允许**仍不能越根；symlink/junction；中文空格路径；不存在文件；restore/checkout等危险动作不自动允许。
- 完成：隔离产品级负例与正常 Edit/精确 Gate 回归成立；拒绝原因和人工审批均可追踪。按本轮授权，检查集中在实现结束时，不要求先红后绿报告；完整回归/安装/打包与整体运行验收留到 v0.3 收尾，本轮不执行 smoke、真实模型或 AO Mission。
- 不做：执行危险命令验证“是否真的删除”；自造沙箱框架；用户重要仓库测试。
- AO 依据：只读核对官方 v0.12.9 固定源码 `4cbb4b6ced1ad93f79641a2347d2342f1ffd218a` 的 [Codex 审批转换](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/adapters/chatdriver/codexappserver/conversation.go)、[ACP 工具审批](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/adapters/chatdriver/acp/client.go) 及 conversation DTO/Controller；使用 requestId、原始 rawCommand/cwd、subjectKind/toolKind/input 和实际 offered allow_once ID，不硬编码所有供应商都返回 allow；未启动 Worker/模型获取样例。
- 实现：ClosedLoop 和保留的 AutoApprover 共用同一策略，删除旧前缀/多命令/通用 pytest 与 Git 写操作白名单。文件先按 AO Worker workspace 与请求 cwd 严格解析已有父目录、链接/junction，再检查词法及实际相对路径；forbidden 优先，空 allow 不授权，解析失败不回退 glob。命令检查原始控制字符，完整 argv 与 cwd 匹配 Gate；保留有限 shell 包装/已确认 cd 前缀及参数受限的查看操作。
- 记录：沿用 counters 和 processed_events，按 task/session/request 去重；记录目标路径、请求/命令摘要、原因、所选单次选项和是否需人工。原请求通过 AO conversation ID 对应，不复制文件正文或命令密钥；拒绝项留 pending，正常任务不因此立即失败。resolve 未确认不自动重发；未新增审批表/控制层或配置。
- Windows 定向：CPython 3.12.7；在 `clao/` 将 `.venv/Scripts` 前置 PATH、`src` 设为 PYTHONPATH，使用本目录 venv Python 执行 `-m pytest tests/test_approvals.py tests/test_approvals_bridge.py tests/test_approval_block.py tests/test_gate_first_completion.py tests/sidecar_port/test_budgets.py tests/test_ao_runtime_portability.py -q -rs --tb=short`，最终 **200 passed、1 skipped / 19.42s**；变更的 approvals/closed_loop/ao_adapter 三个源码 compileall 通过，diff-check 与治理链接通过。真实 Windows junction 越根/禁止目标及 ClosedLoop 回归通过；危险命令只作为字符串判断，未执行。
- NOT_RUN / 边界：原生 symlink 创建测试因 Windows 权限不足 skipped，未修改系统设置；本轮未跑完整回归、干净安装、打包、smoke、真实模型/AO Mission。AO v0.12.9 的 Codex fileChange 审批不暴露完整文件目标，明确留人工；未知工具/格式、复杂 shell、Git 写操作留人工。路径校验发生在审批时，不承诺跨 AO 执行的原子文件系统保证；F03/F05 等后续卡范围未扩展。
- 合并收尾：合入 tree 与已审计 PR head `89be6f7e15e053ef0407afddc491dbefd083ef6a` 完全相同，本地 main 正常 fast-forward 同步。仅更新 PLANS、BACKLOG、根 README 与 PROJECT；产品及发布工具 blob 未变，沿用上述 200 passed / 1 skipped 证据，不重跑测试、构建或 live。下一任务 F03 TODO，未开始实现；未创建 tag/Release，已发布 v0.2 不变。

## V03-F03｜Git路径、产物规则与只读取证

- 状态：DONE；2026-09-07 负责人确认再次外部审计 PASS，已提交 artifact 交付缺口闭环、无其他返修项；[PR #34](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/34) 已 rebase merge 到 main，合入提交 `35a67d07ae196368434fbd83a95693b288c6bc6e`。base `3af98d46e3495aa0154f8701152a11274b42a7c2`，已审计 head `451daef6aff7a1039f0b5d5ec1b73e988d5ea9c9`，原实现提交 `95b09b6dd308b84f18f7aa1c44e395fc7ac98c47`，分支 `codex/v03-f03-git-evidence`；F01/F02 保持 DONE。
- 对应：A03，关联A09/A12。落点：worktree、mission_gate、mission及调用者。
- 工作：无歧义路径解析；rename old/new；精确artifact规则；不改index取untracked diff；统一baseline采证完整性；Final确定性scope。
- 必测：rename/copy/delete/untracked/staged；空格中文控制字符；data.pyconfig/.coverage_policy.py不能误过滤；cache允许；采证异常也不得破坏index。
- 完成：Git before/after内容和index校验；非允许路径不能被模型PASS覆盖；正向materialization不加入cache。
- 不做：改变用户ignore、强制add、自动reset/checkout、重写Git历史。
- Git 依据：本机 Git 2.55.0.windows.3 随附 git-diff / diff-format、git-ls-files、git-commit 文档及隔离仓库实测；不根据面向人的 quoting 推断路径。
- 改动事实：严格 NUL name-status / index 解析；committed（冻结 base 与 HEAD 两端点）、staged、unstaged / untracked 分层取并集，rename/copy 同时保留来源与目标，删除保留原路径。JSON 路径列表补充 diff 展示；空 allow 不授权。Final scope 与 Verifier 使用同一完整路径集合，ClosedLoop 沿用同一 helper。
- 只读与 artifact：临时 index / objects 均位于仓库外，保留原 index 的 staged 事实；add -N 只作用于临时 index，异常不 reset/restore 真实仓库。禁用自动 index refresh、fsmonitor、取证 hook、外部 diff/textconv 与 clean/process 程序；不修改 ignore/exclude。artifact 只按目录段、明确后缀或 coverage 数据文件格式匹配；复制到 cache 不把未变来源算作修改，移入 cache 的源码删除仍可见。
- baseline / materialization：基线复用 IntegrationGate 的 require_clean、before/after 完整性和既有 Gate 记录；旧/损坏/不匹配的基线不提供红测豁免，采证完整性失败进入 HUMAN。main HEAD 无法确认时不回退 Worker HEAD。materialization 仅 add 实际可暂存用户路径，commit --only 精确提交用户净改动；已暂存 cache 保留在 index，但不随提交进入交付，不重写既有 Worker 历史。
- 审计返修：Mission 使用 dispatch 时已有 frozen base，把 artifact 条目精确恢复为基线的 blob/mode、保留 Worker HEAD 的全部非 artifact 条目；通过仓库外临时 index 形成追加的交付 commit 对象，并 fetch/merge 该明确 SHA。已被 Worker commit 的新 cache 不进入最终 integration 树；基线 cache 的修改/删除还原为基线内容。原 Worker 提交仍为祖先，历史中的 artifact blob 不清除；该过滤步骤不移动 Worker ref、不改其 index/cache 或 ignore/exclude。基线缺失/损坏、构造失败或基线 cache 与普通文件的目录冲突进入 HUMAN，不回退 merge 原始 HEAD。
- 返修验证：同一 Windows 产品 venv，`-m pytest tests/test_f03_git_evidence.py tests/sidecar_port/test_worktree_multi.py tests/sidecar_port/test_mission.py tests/test_final_gate_baseline.py tests/test_mission_gate.py -q -rs --tb=short` 最终 **145 passed / 210.22s**，0 failed / 0 skipped。新增 17 个场景含实际 Mission materialization/integration、Worker 先 commit 源码和 cache、基线 cache 未改/修改/删除的精确 blob/mode、pending 源码和 staged/untracked cache、缺失/损坏基线及构造异常、文件/目录冲突、中文/Tab/换行树路径。首次集中检查的两个控制字符用例暴露 Windows Git 静默跳过路径，已修复并保留断言；仅在不检出文件的临时 index 中设置 protectNTFS=false，真实仓库设置与 checkout/merge 保护不变。`-m compileall -q src/loopcore/worktree.py src/loopcore/mission.py tests/test_f03_git_evidence.py tests/sidecar_port/test_mission.py`、diff-check、2 个变更文档的 8 个本地链接通过。沿用下述历史 F03 证据；本轮 NOT_RUN 同卡末边界。
- Windows 检查：CPython 3.12.7；产品 .venv/Scripts 前置 PATH、src 为 PYTHONPATH，均在 clao/ 使用 .venv/Scripts/python.exe。主集合 `-m pytest tests/test_f03_git_evidence.py tests/sidecar_port/test_worktree_multi.py tests/test_mission_gate.py tests/test_final_gate_baseline.py tests/test_cluster7_audit.py tests/sidecar_port/test_mission.py tests/test_gate_first_completion.py tests/test_f01_contract_boundary.py -q -rs --tb=short`：**188 passed / 323.88s**。
- 最终加固复查：隐藏 index 标志加固后，前述前 4 模块同参数 **110 passed / 162.69s**；统一 Git 环境隔离后，`-m pytest tests/test_f03_git_evidence.py::test_git_environment_cannot_redirect_reads_or_materialization tests/sidecar_port/test_worktree_multi.py -q -rs --tb=short` **21 passed / 23.22s**。均 0 failed / 0 skipped，集合有重叠不累计；`-m compileall -q src/loopcore/worktree.py src/loopcore/mission.py` 通过。
- 证据边界：隔离临时 Git 仓库验证真实 HEAD、index 字节、staged 条目、用户文件内容，异常还比对 .git 文件集/内容；覆盖 split index、取证 hook/filter 不执行。Windows 禁止检出的控制字符文件名用真实 Git tree/commit 对象验证，未冒充本机可检出路径。Git copy 相似度用于端点事实，不宣称追踪任意历史复制意图；隐藏 index 标志、未合并条目、当前 submodule index、无法解析/读取的状态返回未知。多次 Git 采样不承诺跨并发 Worker 写入的原子快照；F05 停止确认、R02 生命周期仍在原卡范围。
- NOT_RUN：完整全量回归、干净安装、打包、smoke、真实 AO Mission / 模型、GUI，按授权留到 v0.3 收尾；本次合并收尾也未重跑 145 项定向测试或 compileall。未创建 tag/Release，未开始 F04。
- 合并收尾：合入 tree 与上述已审计 head 完全相同，本地 main 正常 fast-forward 同步；仅更新 PLANS、BACKLOG、根 README 与 PROJECT 的状态和当前事实，产品及发布工具 blob 未变，沿用既有验证。文档 diff-check、4 个变更文档的 20 个本地链接及产品 blob 核对通过。下一任务为 F04 TODO，本轮未实施 F04/F05/R01/R02，已发布 v0.2 不变。

## V03-F04｜Gate查询、本地API与安全渲染

- 状态：DONE；2026-09-07 负责人确认外部审计 PASS、无需返修；[PR #35](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/35) 已 rebase merge 到 main `c51ccd155f7ab6c226454846c9e1f1fff146956d`。已审计 head `fddf87a3237dbde1cc493dbc08963ee4b3b9bdca`；原 base `9a55a6c20f8828246723d66e18c91dbc4a23e122`，分支 `codex/v03-f04-panel-boundaries`，原产品提交 `3d1e693b5f9bef6eea926c4bbb9ef12383762302`；F01/F02/F03 保持 DONE，F05 TODO。
- 对应：A04、A05。落点：StateStore查询、Panel server/index及新直接测试。
- 工作：专用Gate DTO；command/integrity/scope/overall分别表达；数据库异常保留read_error；完整错误字段。Host/Origin/JSON/nonce；id与文件路径包含性；安全DOM渲染。
- 必测：真实SQLite Gate row到/api/state到页面；exit0+integrity失败显示失败；无记录与读失败不同；跨源请求、非法Host、缺token、穿越、引号、双击写请求。
- 完成：离线API/浏览器合同全绿；loopback不变；不会因错误toast消失而丢失根因。
- 不做：美化大重构、公网访问、让客户端自行裁决PASS。
- Gate：复用 `gate_runs`，仅新增可空 `assessment_json`；IntegrationGate 记录 command/integrity，Controller 将实际 scope 结论写回同批记录 ID，标识 task/baseline/final。专用只读查询保留旧表兼容；历史缺字段为 unknown，SQLite/损坏记录为 read_error，不伪装为空记录或 PASS。无加载任务为 not_run，已加载库无记录为 no_records；命令尚未执行单独为 command not_run。exit=0 不能覆盖 integrity/scope failure。
- Panel：常驻显示 Mission reason、runner/read error、alert summary/description/error/reason 及 Gate 原因/完整输出；动态内容用 DOM/textContent、受限状态 class 和安全属性赋值，保留中文、引号与长错误。写动作在单页面内 pending 去重，任务启动/续跑/查看共用锁；不自动重试写请求。
- API：仅监听 127.0.0.1；Host 限实际端口的 127.0.0.1/localhost，POST 必须精确同源 Origin、UTF-8 JSON、每次 Panel HTTP 服务启动随机生成的内存 nonce（页面/script nonce 和请求头，不进 URL/日志/任务数据）。严格 JSON/framing 与大小限制；Windows 分段到达的被拒请求有界排空请求体，保留明确错误响应，不先执行动作。页面附 CSP/no-store 等响应头。
- 路径：HTTP mission_id 限 1–128 位 ASCII 字母/数字/下划线/连字符并排除 Windows 保留设备名；校验 runtime/tasks、存档 mission_id 一致性及解析后的文件包含性，拒绝穿越、绝对路径、异常编码和越界 junction。`/api/file` 仍仅允许 memory.md/project.md。
- Windows 定向：从 `clao/` 前置 `.venv\Scripts` 到 PATH、`src` 到 PYTHONPATH，以本目录 CPython 3.12.7 venv 执行 `python -m pytest tests/test_f04_panel_boundaries.py tests/test_panel_worker_contract.py tests/test_mission_gate.py tests/test_gate_first_completion.py tests/test_final_gate_baseline.py tests/sidecar_port/test_mission.py tests/test_ao_runtime_portability.py tests/test_f03_git_evidence.py::test_closed_loop_real_gate_blocks_scope tests/test_f03_git_evidence.py::test_final_scope_copy_source_blocks_passing_verifier -q -rs --tb=short`：**224 passed / 160.98s**，0 failed / 0 skipped。
- 浏览器证据：真实本机 Edge headless 消费隔离 SQLite 的 HTTP/SSE 页面，断言不可信文本未形成 DOM/属性注入、command pass 与 overall fail 分离、错误不随 toast 消失、六类写按钮快速双击各执行一次，并用另一 localhost 端口页面验证跨源 POST 无副作用。外部动作使用替身，测试 SSE 发送真实快照后关闭以结束虚拟时钟；不等于真实 AO Mission 或视觉重设计验收。未新增浏览器依赖或框架。
- 追加验证：最终复查补齐历史 Task Verifier 已计算的 scope 记录（仅记录，不改决策/恢复），以同一 Windows venv 运行 `python -m pytest tests/test_f04_panel_boundaries.py::test_historical_task_verifier_records_its_known_scope tests/sidecar_port/test_verifier.py tests/test_f01_contract_boundary.py -q -rs --tb=short`：**49 passed / 316.91s**，0 failed / 0 skipped；与前述选择分开报告，不累计数量。改动 Python 文件 compileall、`git diff --check` 和 4 份变更 Markdown 的 20 个本地链接检查均通过。
- 残余边界：历史缺失事实不回填猜测；Gate 原始命令失败仍显示失败，既有 Mission 对已识别 baseline 失败的容忍规则不变。nonce 是本地浏览器 CSRF 边界，不是 OS 客户端认证；pending 仅处理同页在途重复提交；路径解析不承诺抵御有本机写权限者并发替换目录。attach/停止/有效配置的生命周期语义仍由 F05/R01/R02 处理。
- NOT_RUN：全量回归、clean install、打包、smoke、真实 AO Mission/模型、GUI 视觉重设计验收；本次合并收尾也未重跑已有 224 / 49 项定向测试或 compileall。未创建 tag/Release，未开始 F05 或其他功能卡。
- 合并收尾：合入 tree 与已审计 head 完全相同，本地 main 正常 fast-forward 同步；仅更新 PLANS、BACKLOG、根 README 与 PROJECT 的状态和当前事实，产品及发布工具 blob 未变，沿用既有验证。文档 diff-check、4 个变更文档的 20 个本地链接及产品 blob 核对通过。下一任务为 F05 TODO，M1 继续 IN_PROGRESS；已发布 v0.2 不变。

## V03-F05｜停止确认与未知外部动作保护

- 状态：DONE；base `fe1d12c42f780e6bbf6af272d0aca38ddb50026a`，分支 `codex/v03-f05-external-operations`；[PR #36](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/36) 再次外部审计 PASS，已审计 head `9620adced463f479a693f67667e90397a9521ef7`；2026-09-07 已 rebase merge 到 main `1e1401f7b55ff71617c0e3ef4ab277490b916cff`。F01–F05 DONE，M1 COMPLETE；下一任务 R01 TODO，未开始实现。

- 对应：A07。落点：Executor、Mission、Store，必要AO官方只读查询。
- 工作：同Store intent/operation_id/result；spawn/send超时先对账；无法确认则UNKNOWN+人工处理。materialization须已停止事实；不忽略kill失败继续提交。
- 必测：spawn成功但客户端ack丢失；send后进程中断；kill false/timeout；多次重试同操作；不唯一外部结果不得造第二Worker。
- 完成：在支持的AO契约下防盲重发，未知状态可解释；副作用数量受控；一次受控故障恢复验收。报告at-most-once/对账边界，不承诺分布式exactly-once。
- 不做：改AO内部DB；新增队列服务；提升预算隐藏未知。
- 实现：现有 `state.db` 的 `external_operations` 保存稳定 identity、输入摘要、attempt、结果与对账证据。`NOT_STARTED` 尚未调用（或已证明 CLI 未创建）、`IN_FLIGHT` 已持久抢占但确认未落盘、`SUCCEEDED` 已确认操作结果、`FAILED` 已确认本地未执行且有界尝试耗尽、`UNKNOWN` 无法确认；UNKNOWN 不当成功或失败。结果与成功预算计数同事务保存，多 Store 争用也只有一个调用者；超时/transport/nonzero 不再按错误文案自动重发。提示词/消息只存 hash，CLI 诊断脱敏限长。
- 对账依据：固定 AO v0.12.9 源码 `4cbb4b6ced1ad93f79641a2347d2342f1ffd218a`。核对 [spawn CLI](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/cli/spawn.go)、[send CLI](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/cli/send.go)、[公开 Session 控制器](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/httpd/controllers/sessions.go) 与 [终止实现](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/session_manager/manager.go)。未访问 AO 内部 DB，也未启动真实 Worker/模型。
- Spawn：调用前冻结随机 120-bit、完整 20 字符 displayName 标记；ACK 丢失后只接受公开列表中唯一精确标记，且单 Session 的 ID/project/harness/kind/mode 全部吻合；无匹配、多匹配、改名、缺字段、读取失败均 UNKNOWN。该标记是关联证据，不是 AO 幂等键；不按人名/时间猜测，不证明初始 prompt 已被 Worker 消费或工作树已就绪。成功结果供初始 dispatch/replan 重入采用，未绑定的迟到 Worker 也纳入终止清理。
- Send：覆盖 Planner local-fix、L0 和实际 Worker directive 发送。普通 CLI send 没有传 caller clientMessageId，conversation 内容相同或缺失都不能证明某次消息交付；未知时只做只读诊断并进入 HUMAN，不再发送。成功只代表 AO 接受，不代表 Worker 已应用。未实现 R02 完整 directive 回执。
- Kill / Stop / 交付：ACK、exit=0、false、timeout 都需查同一 Session 的严格布尔 `isTerminated=true` 且 `status=terminated`；idle/exited、404、畸形/重复 JSON 字段均不当已停。未知状态只读再对账；旧停止结果遇到外部 restore/live 事实失效，但不盲目重新 kill。Mission 及 ClosedLoop 在后续工作前检查未决 operation；旧 Worker 未确认停止不 spawn replacement、不 commit/materialize/merge。Stop receipt 先落库，`worker_stop` 单独记录 CONFIRMED/UNKNOWN；终态保留原始 reason 与停止未知原因，不声称 HUMAN 等于所有 Worker 已停止。Panel 仅同步接收顺序与写失败错误，未新增取消中/恢复 UI。
- Windows 检查：产品 CPython 3.12.7 / `.venv`，Scripts 前置 PATH，src 为 PYTHONPATH。在 `clao/` 执行 `python -m pytest tests/test_f05_external_operations.py tests/test_spawn_and_boundary.py tests/test_crash_resume.py tests/test_terminal_cleanup_and_total_replans.py tests/test_directive_channel.py tests/test_shellish_guard.py tests/test_ao_runtime_portability.py tests/test_f03_git_evidence.py tests/sidecar_port/test_mission.py tests/sidecar_port/test_budgets.py tests/sidecar_port/test_phase2.py tests/test_f04_panel_boundaries.py::test_unauthorized_http_writes_never_reach_actions tests/test_f04_panel_boundaries.py::test_same_origin_page_nonce_allows_normal_write -q -rs --tb=short`：**286 passed / 1 failed / 211.64s**。唯一失败是告警预算夹具依赖旧 send 异常留下的中间态，已改为合法 CONTINUE 观察路径，保留并增强相同告警阻断断言；所有故障场景、正常发送、预算、F03 artifact/index 与交付断言均保留。
- 定向复核：`python -m pytest tests/sidecar_port/test_budgets.py::test_max_same_alerts_forces_human tests/test_f05_external_operations.py::test_mission_resume_unknown_send_parks_before_any_materialization tests/test_f05_external_operations.py::test_stop_during_spawn_adopts_late_ack_only_for_cleanup -q --tb=short`：**3 passed / 3.31s**（含修正夹具与新增两个完整恢复窗口）。此前其余 286 项已通过，集合分开报告，不将中途失败隐藏为一次全绿运行。
- 最终 operation/预算检查：`python -m pytest tests/test_f05_external_operations.py tests/sidecar_port/test_budgets.py tests/test_terminal_cleanup_and_total_replans.py tests/test_spawn_and_boundary.py tests/test_crash_resume.py tests/sidecar_port/test_phase2.py -q -rs --tb=short`：**114 passed / 79.75s**，0 failed / 0 skipped；包括已证明 CLI 未创建的 send/replan 重启重试、耗尽后 FAILED、恢复成功仅计一次，及迟到弱对账不覆盖已确认成功或产生误报。最后为 pending 重试补齐 ClosedLoop 不消费新事件/另起 action 的入口断言：`python -m pytest tests/test_f05_external_operations.py::test_closed_loop_unstarted_resume_keeps_one_pending_action tests/test_crash_resume.py -q -rs --tb=short`：**9 passed / 29.08s**，0 failed / 0 skipped。集合存在重叠，不累计为全量回归计数。变更 Python 文件 compileall、diff-check 和 4 份 Markdown 的 20 个本地链接检查通过。
- 故障注入覆盖：真实隔离 SQLite 关闭/重开、临时 Git、按官方响应形状实现的 loopback HTTP fake；spawn 成功丢 ACK/timeout/crash 后精确采用、多/零候选 UNKNOWN、send 外部生效但保存前/后 crash、kill false/timeout/transport/crash 的存活与终止分支、late ACK 遇 Stop、停止事实先于真实 materialization、成功预算只计一次、进程未创建的有界重试及真实缺失 executable。运行次数断言保证不重复 spawn/send/kill。
- 残余 AO 边界：displayName 可被外部改名/复制，不能代替官方唯一键；普通 send 缺少可唯一关联的公开回执，未知结果可能长期需人工。Session terminated 是 AO 公开的逻辑终止事实；AO chat stop 内部有 best-effort 清理，不能据此承诺独立 OS 进程级证明、不可被外部 restore 或分布式 exactly-once。现有终态不自动恢复为 running，完整取消/新 attempt/只读 attach 留给 R02。
- PR #36 审计返修：其余 F05 实现外部审计 PASS，唯一 blocker 为 `/api/stop` 吞掉 receipt 持久化失败后仍返回成功。本轮基于 `0542fc932c0fd9ad733152f88cfbc8d863632e5f`，仅修改 Panel 接收结果传递：无法确认持久 receipt 时 HTTP 503 / ok=false，保留错误且不设置 stop flag；无加载任务时 HTTP 409。正常返回明确的 ok=true / stop_requested=true；若后续清理抛错，先查同一 StateStore 的既有 receipt，已持久接收不因停止 UNKNOWN 被误报为未接收。路由返回该实际结果，沿用前端 writeAction 错误处理，不修改 index.html、写安全边界或已审计的 operation/spawn/send/kill 逻辑。该返修已通过再次外部审计 PASS，无其他需要返修的问题。
- 返修验证：同一 Windows 产品 venv、Scripts 前置 PATH / src 为 PYTHONPATH，在 `clao/` 执行 `python -m pytest tests/test_f05_external_operations.py tests/test_f04_panel_boundaries.py::test_unauthorized_http_writes_never_reach_actions tests/test_f04_panel_boundaries.py::test_same_origin_page_nonce_allows_normal_write tests/test_f04_panel_boundaries.py::test_invalid_json_never_writes tests/test_f04_panel_boundaries.py::test_duplicate_host_and_missing_host_cannot_write tests/test_f04_panel_boundaries.py::test_rejected_split_request_receives_error_without_writing tests/test_f04_panel_boundaries.py::test_real_browser_text_rendering_nonce_and_pending_writes -q -rs --tb=short`：**122 passed / 44.87s**，0 failed / 0 skipped。新增真实 Panel HTTP + MissionController + 隔离 SQLite/fake AO 回归：receipt 写失败无 stop_request、两层 stop flag 或 kill；receipt 成功但 kill false/timeout 时 200 接收且 worker_stop=UNKNOWN；receipt 后清理抛错仍按持久接收事实响应。既有真实浏览器夹具追加 Stop 失败错误提示与无假成功断言，保留双击去重、nonce、渲染断言。`python -m compileall -q panel/server.py tests/test_f05_external_operations.py tests/test_f04_panel_boundaries.py`、diff-check 通过；NOT_RUN 边界沿用下述内容。
- NOT_RUN：全量回归、clean install、打包、smoke、真实 AO Mission/收费模型、GUI 视觉验收；本次合并收尾也未重跑既有 F05 定向测试或 compileall。未创建 tag/Release，未实施 R01/R02/U01/U02 或模型切换。
- 合并收尾：合入 tree 与已审计 head 完全相同，本地 main 正常 fast-forward 同步；仅更新 PLANS、BACKLOG、根 README 与 PROJECT 的状态和当前事实，产品及发布工具 blob 未变。文档 diff-check、本地链接及产品 blob 核对通过，沿用既有验证；F05 DONE、M1 COMPLETE，下一任务 R01 TODO，已发布 v0.2 不变。

## V03-R01｜有效配置与阶段诊断

- 状态：DONE；base `d59dd8fd630fab573ea4dd80b005106cf7fde207`，分支 `codex/v03-r01-effective-config`；[PR #37](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/37)，实现提交 `38d474c`、返修后已审计 head `e88c698a211ee5cd179709701ada1a7aa3079d3a`；再次外部审计 PASS、无其他返修，2026-09-07 已 rebase merge 到 main `551f7f49198e033b1331ec341ff0d352553bacb1`；M0/M1 COMPLETE，M2 IN_PROGRESS，R02 TODO。
- 对应：A10，支持A06/A11。落点：runtime/config、Gate、Adapter、Provider、Panel。
- 工作：唯一effective config解析；model重复键迁移；Gate时间/输出真正接线；配置来源与revision；phase/attempt/error metrics；敏感项不落库。
- 必测：保存值等于消费者值；非法范围拒绝；旧配置迁移/提示；运行中默认值改变不改当前Mission；unknown费用不填0；角色请求与实际确认模型分开。
- 完成：Panel可解释在等什么；已有SSE沿用，稳定cursor/序列与断连状态；本地ACK和事件延迟可测，不假承诺模型速度。
- 不做：新监控平台、全部配置热更新、同一事实复制多处。
- 实现事实：CLI/Panel 同一严格解析入口；整份验证并原子保存现有 YAML；配置来源与 revision 随 Mission 冻结，续跑复用旧快照，历史缺快照不伪补。模型/角色 timeout、AO timeout、runner 等待、watchdog 小数时间与三阶段 Gate 参数已接线；迁移键、弃用项及消费者表见 PROJECT，未新增依赖。
- Gate：timeout 真实作用于每条命令；每流持久证据正文有长度/hash/截断标记，失败编号在截断前提取，尾部新失败仍阻断 Final，片段不能绕过 F01 完整证据。诊断：执行开始先落现有 StateStore，语义传输 attempt/错误类别、Worker AO 观察与模型请求/传入/确认分开；UNKNOWN 不影响 F05 对账行为。
- Panel：默认设置与本次冻结配置分开显示；真实 preflight/慢模型/AO 读取在途可见，缺失和 read_error 不混淆；HTTP 处理、浏览器往返、状态记录到快照及请求耗时分别展示。SSE epoch+sequence 完整替换，断连保留最后状态并冻结计时，重连不重发写动作，沿用 F04 写边界与安全 DOM。
- Windows 定向（产品 venv、src 前置 PYTHONPATH）：`pytest tests/test_r01_effective_config.py tests/test_panel_worker_contract.py tests/test_f04_panel_boundaries.py tests/test_mission_preflight.py tests/test_codex_cli.py tests/test_codex_planner.py tests/test_codex_auditor.py tests/test_codex_verifier.py tests/test_f01_contract_boundary.py tests/sidecar_port/test_budgets.py -q -rs --tb=short`：**311 passed / 213.30s**；含真实 Edge 的配置交互、安全文本、在途/未知诊断、SSE 断连重连检查。新增 AO 只读边界和最后消费者检查另见下条，不将重叠集合相加。
- 补充命令：`pytest tests/test_r01_effective_config.py tests/test_f05_external_operations.py tests/test_ao_runtime_portability.py tests/test_mission_gate.py tests/test_final_gate_baseline.py tests/test_approval_block.py tests/test_approvals_bridge.py -q -rs --tb=short`：**182 passed、1 failed / 99.48s**；唯一失败是旧 AO Runtime 替身缺 diagnostics 字段，补齐该替身后单独复查 `pytest tests/test_ao_runtime_portability.py -q -rs --tb=short`：**18 passed / 0.27s**。其余 F05/Gate/审批/R01 场景无失败；集合重叠不累计。含在途 AO 只读请求、小数 watchdog 持久化和恢复诊断读取失败的最终负例。
- 检查中的修正：首次收集发现诊断 import 位于 decorator 与 class 之间，已修正；浏览器探针误读自身 script 文本已修正。旧 preflight/恢复夹具改为真实 SQLite、持久配置事实与无 Worker 副作用断言；停止前先模拟 Worker 存活，停止后才 terminated。检查保留失败/拒绝断言，未删除负例；最后一次上述集合无失败。
- 最后边界复查：增加超大整数和带控制字符 URL 的拒绝用例后，`pytest tests/test_r01_effective_config.py -q -rs --tb=short`：**37 passed / 22.43s**；compileall（src/panel/run_mission.py 与直接变更测试）、diff-check、5 个变更 Markdown 的 21 个本地链接 PASS。新增源码/测试已由既有 manifest 前缀覆盖，依赖、builder、manifest、AGENTS 与设计主文档不变。
- NOT_RUN：全量、clean install、打包、smoke、真实 AO Mission/模型、GUI 视觉重设计验收；未新增 tag/Release，未实施 R02 或模型供应商。
- 剩余边界：当前语义 CLI 无可确认的实际模型/用量/费用字段，均 unknown；Worker 的 AO SessionView.model 可确认 spawn 时 resolved model，conversation.modelReroute 单列 conversation 级替换，复用既有读取不额外请求。Gate 上限限制证据正文，仍使用既有内存捕获；runner cap 仅循环边界。历史无快照只读查看、attach 组装副作用与完整恢复留 R02；阶段记录只诊断，不是新的状态权威。
- 审计返修（2026-09-07）：外部审计指出正常 Session 无 reroute 时仍显示 confirmed unknown；核对固定 AO `4cbb4b6ced1ad93f79641a2347d2342f1ffd218a` 的公开 `dto.go SessionView.model` 与 `sessions.go sessionView()`，确认前次只看 domain Session 遗漏了公开映射。Mission 正常轮询及既有 Session 详情读取得到独立 `spawn_resolved_model` / 来源；conversation 记录 `model_reroute` 的 from/to/source，不互相覆盖；缺失/非法字段为 unknown，不从 requested/passed 推导，不增加 AO 请求。沿用 StateStore JSON 记录，无表迁移，配置和 F05 控制逻辑不变。
- 返修验证：Windows 产品 venv，`pytest tests/test_r01_effective_config.py tests/test_ao_runtime_portability.py tests/test_f04_panel_boundaries.py -q -rs --tb=short`：**184 passed / 37.84s**。覆盖真实 Mission 轮询→StateStore→Panel HTTP、合法/缺失/非法 Session model、两种事实先后合并、错误 Session 关联、请求数量不增加、未知 usage/cost 与配置快照；真实 Edge 检查 resolved/reroute 的来源、旧 reroute 兼容、安全文本及 SSE 重连。compileall（src/panel/run_mission.py 与直接测试）、diff-check、4 个相关文档的 13 个本地链接 PASS。
- 返修阶段 NOT_RUN：此前 311 项大集合、全量、clean install、打包、smoke、真实 AO/模型、GUI 视觉重设计验收。当时 R01 保持 IN_REVIEW，M2 IN_PROGRESS；未新建 PR、未合并、未实施 R02，未创建 tag/Release。
- 合并收尾（2026-09-07）：合入 tree 与已审计 head 完全相同，本地 main 正常 fast-forward 同步；仅更新 PLANS、BACKLOG、PROJECT、根 README 与 clao/README 的状态和当前事实，产品代码、配置、测试及发布工具未变。文档本地链接、路径与 diff-check 通过；沿用已有 184 / 311 项定向证据，未重跑测试、安装、打包、smoke 或真实 AO/模型。R01 DONE，M2 IN_PROGRESS；下一任务 R02 TODO，未开始实现；无 tag/Release。

## V03-R02｜指令回执、取消恢复、固定基线

- 状态：DONE；[PR #38](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/38) 外部审计 PASS、无需返修，2026-09-07 已 rebase merge 到 main `2377dd03c172461c63d26835e23abe7171e883a9`；已审计 head `7d91443cd10b95d8238b5febdee4dfa59026e28e`。原 base `b748363b0173b725bc20fc65caeffe2180449df1`，分支 `codex/v03-r02-lifecycle-contract`；R01 / R02 DONE，M2 COMPLETE，下一任务 U01 TODO，未开始实现。
- 对应：A06、A08、A09。落点：directives、Controller、Store、Panel和Git基线。
- 工作：received/applied/rejected/unknown回执；final verifier notes真实消费；Worker prompt范围完整；取消中与已取消区分；崩溃恢复只读检查材料；终态新attempt关联；Mission固定source commit。
- 必测：指令无消费者；入队与落盘失败；取消发生在Worker/语义角色/Gate；旧HUMAN不重新变running；旧记录字段缺失；source main/remote分歧；S2缺依赖代码。
- 完成：取消/恢复文案与实现一致；不支持的dependent plan preflight明确拒绝，或有真实dependency commit交付测试；独立双任务保留有界支持。
- 不做：新建完整暂停调度器；未经验证扩大并发。
- 实现：同一 StateStore 的 directive_receipts 保存 command identity、received/applied/rejected/unknown 和分消费者时间/原因；同 identity 同内容复用、冲突拒绝。Planner 镜像不代表主目标消费；Worker applied 仅表示 F05 send 接受。Observer/Gate 明确拒绝。Final Verifier 的 user_notes 与消费回执使用同一组输入；晚到指令不假 applied。初始/replan prompt 包含 Task objective、AC、允许/禁止路径、Gate、原始 user instruction；超过 AO 4096 UTF-8 byte 限制明确拒绝，不截断范围。
- 取消/恢复：receipt 先落盘、HTTP 及时返回；Controller 推进 requested/cancelling/cancelled/unknown，仅确认本地受控子进程和 AO Worker 已停止才 CANCELLED。实际 Codex CLI/Gate 子进程可取消，未知本地 PID 不猜测终止；旧 HUMAN 不迁移。非终态先只读验证配置/source/workspace/operation/Gate/verification；未通过不组装 runtime、不补建材料。历史 attach 使用只读 Store，无 AO/Provider/迁移。终态只能创建关联新 identity/快照；未知旧停止事实阻断新 attempt。
- source/计划：只读比较 local branch、origin tracking 与 ls-remote，保存 exact source；后续 spawn 前再次核对，创建后用 Worker HEAD reflog 确认基线，integration 明确从冻结 commit 创建。AO 无 exact-commit spawn 参数时漂移前阻断；missing reflog/关联不明交人工。dependent plan 在 dispatch 前明确拒绝；两独立任务仍可运行。F03 artifact/只读 index、F05 UNKNOWN 和 R01 配置冻结保持。
- Windows 验证（CPython 3.12.7、产品 venv；隔离 Git/SQLite/fake AO/本地 HTTP）：`pytest tests/test_r02_lifecycle.py tests/test_directive_channel.py tests/test_f03_git_evidence.py tests/test_final_gate_baseline.py` 加 F05 unknown-send 恢复、R01 真正消费者/旧快照、F04 浏览器节点的最终组合：**125 passed / 221.17s**。此前 Panel/恢复及修正节点组合 **148 passed / 60.02s**；F05 文件 **59 passed / 35.92s**。集合重叠不累计，不是全量回归。
- 最后边界验证：实际 Planner/Auditor/Final Verifier 输入、晚到指令、旧本地进程 UNKNOWN 阻断新 attempt、durable channel 与 Edge 组合 **9 passed / 16.39s**；真实 HTTP 新 attempt→runtime→新 source/config（原记录不变）和 materialization 中取消阻断 integration **2 passed / 5.58s**。Edge 检查取消四状态、回执/历史 unknown、安全文本、禁用确定性目标、新 attempt 快速重复点击；沿用 F04 SSE/nonce/错误边界回归。
- 静态/页面收尾：真实 Edge 历史 receipt unknown 展示复查 **1 passed / 12.03s**；compileall（src/panel/run_mission.py 与直接变更测试）、diff-check、5 个 Markdown 的 21 个本地链接 PASS；3 个新增薄 helper/测试文件由现有 manifest 前缀覆盖。依赖、发布映射、AGENTS 与设计主文档不变。
- 夹具同步：旧内存 queue/drain 改为可重启 Store 收据断言；旧 Stop 立即 HUMAN 改为 receipt→Controller 停止事实；旧依赖计划成功夹具替换为明确拒绝负例，并保留独立双任务正例。未删除失败用例或绕开产品 schema 校验。
- NOT_RUN：全量、clean install、打包、smoke、真实 AO Mission/模型、完整 GUI 视觉验收；无 tag/Release，未开始 U01/供应商/导出。实施阶段未运行项保持不变，沿用既有定向证据。
- 剩余边界：恢复检查为只读时点事实，不是跨 AO/Git 的原子事务；AO 当前没有 exact-commit spawn 参数，source 检查与 AO 创建间仍可能外部竞态；创建基线不符继续 fail closed，不宣称 exactly-once。已中断本地进程/语义输入或不完整 Git/SQLite 材料保守交人工；无自动 UNKNOWN 解除或通用进程恢复。历史活跃 WAL 缺少必要共享内存材料时只读查看返回 unavailable，不写回修复。
- 合并收尾（2026-09-07）：合入 tree 与已审计 head 完全相同；本地 main 正常 fast-forward 同步。仅最小更新 PLANS、BACKLOG、PROJECT、根 README 与 clao/README；文档链接/路径、diff-check、产品实现 blob 未变检查通过。未重跑定向测试、全量、安装、打包、smoke、真实 AO/模型或完整 GUI 验收；无 tag/Release。M0 / M1 / M2 COMPLETE，M3 TODO；唯一下一任务 U01 TODO，未实施。

## V03-U01｜iPhone风格界面骨架与状态夹具

- 状态：DONE；M3 IN_PROGRESS，base `89f1e1e475ea46246f9a6f9307d50ccb71b4995f`，分支 `codex/v03-u01-workbench-shell`；U02/U03 TODO。
- 合并收尾（2026-09-08）：[PR #39](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/39) 本轮代码与产品收敛整改外部审计 PASS，无继续返修问题；已 rebase merge 到 main `014e9123a842e8ecd1f42f4ca3845b929835ca2b`，已审计 head `01dfd935c7f55d0800edd526a707387744933423`；合入 tree 与该 head 完全相同。
- 对应：GUI新设计，A12。依赖：G1已通过；G2字段约定确定。
- 工作：四入口、浅/深主题、响应式、分组卡片、渐进表单、键盘焦点；拓扑降为高级诊断。先用状态夹具展示完整/失败/取消/断连/审批/空记录。
- 完成：负责人审核1440/1366/768/390宽截图与键盘流程；不把mock原型写成真实功能；无字体/图标许可遗漏。
- 不做：iPhone外框、网页远程手机接入、大面积模糊/发光、换框架。
- 实现：同一页面四入口、12 个本地 Lucide 符号、浅/深/系统主题、响应式分组卡片；四步新建表单保留输入，原始状态/拓扑移至高级详情。真实接口/状态权威不变，默认设置仅影响新任务；现有历史/指令/取消/恢复入口保留，UNKNOWN 不画为成功。
- 产品收敛返修（2026-09-07，PR #39）：去除标语、重复说明、产品预览入口；主层归并六类生命周期状态，断连/证据读取错误分开呈现；Gate 分项失败保留，技术字段折叠。“重新执行”仍创建关联新 attempt，权限与 Controller 不变。
- 开发隔离：`dev/panel/` 位于现有 manifest 全部映射之外；产品不加载/提供 fixtures.js，旧 `?preview=` 仍读真实状态。开发服务只服务原产品 shell/assets 与夹具，CSP 禁止网络连接，传输替身拒绝写操作，HTTP 也拒绝全部 POST；没有第二套 UI 或假 Controller。取消夹具使用实际 `cancelled`，Worker 停止与原子任务历史状态分开显示。
- 开发预览（仅源码仓库）：从仓库根运行 `clao/.venv/Scripts/python.exe dev/panel/preview.py --port 8768`，打开 `http://127.0.0.1:8768/?state=running`；开发页明确标识样例，可选择原 10 种状态。正式入口仍为 `clao/panel/server.py`，不能用 URL 参数启用夹具。
- 以下为首轮历史验证（head `d6cef4bc56a23696ada8c9dff63f4d0d722919ce`），不代表返修后的当前画面：
- Windows 定向命令（产品 venv、src/PATH 环境）：`python -m pytest tests/test_u01_panel.py tests/test_f04_panel_boundaries.py tests/test_panel_worker_contract.py tests/test_r01_effective_config.py::test_browser_config_phases_and_sse_reconnect_are_safe tests/test_r01_effective_config.py::test_http_defaults_restart_fractional_atomic_failure tests/test_r02_lifecycle.py::test_real_edge_r02_status_receipts_and_new_attempt_pending -q` → **166 passed / 29.07s**。保留原负例/副作用计数，更新测试以操作新详情/渐进表单；增加 UNKNOWN 禁止新 attempt 的 UI 负例。
- 最终窄屏修正后：`python -m pytest tests/test_u01_panel.py::test_edge_workbench_preview_keyboard_themes_and_actual_200_percent_zoom -q -s` → **1 passed / 8.68s，实际 Edge 184 项断言**；图标精确子集/完整许可复查 **1 passed / 1.15s**。与上列集合重叠，不累计为额外产品用例。
- 浏览器覆盖：1440×900、1366×768、768×1024、390×844 浅/深主题与四入口；实际 browser zoom=200%（临时隔离 profile/测试扩展，非 CSS zoom）；语义文本对比度 ≥4.5:1、主要操作高度 ≥44px；键盘弹层/焦点恢复、字段错误/草稿保留、长文本/XSS、断连保留/SSE 去重、预览零 API 请求。正常 `panel/server.py --no-browser` 启动方式已打开四入口预览，未创建真实任务。
- 静态检查：compileall、Node JS 语法、diff-check、本地文档路径及既有 `panel/` manifest 前缀覆盖检查通过；Python 仅增加五个固定静态资源路径，不扩大文件访问或 CSP 脚本权限。
- 首轮历史截图：以下 **19 张实际 Edge 截图**由实现直接产生，已逐张自查并修正空图标与模型页窄屏挤压；首轮当时待审计。截图属于 Codex 自查，不把自动化或截图生成写成外部视觉验收。

<details>
<summary>首轮历史截图（返修前，仅留作对照）</summary>

| 主界面尺寸 | 浅色 | 深色 |
|---|---|---|
| 1440×900 | [查看](assets/u01/overview-1440-light.png) | [查看](assets/u01/overview-1440-dark.png) |
| 1366×768 | [查看](assets/u01/overview-1366-light.png) | [查看](assets/u01/overview-1366-dark.png) |
| 768×1024 | [查看](assets/u01/overview-768-light.png) | [查看](assets/u01/overview-768-dark.png) |
| 390×844 | [查看](assets/u01/overview-390-light.png) | [查看](assets/u01/overview-390-dark.png) |

代表性页面：[任务](assets/u01/tasks-light.png)、[模型](assets/u01/models-light.png)、[设置](assets/u01/settings-light.png)、[审批等待](assets/u01/overview-approval-light.png)、[范围失败](assets/u01/detail-failure-light.png)、[停止未知](assets/u01/detail-stop_unknown-light.png)、[Gate read_error](assets/u01/detail-gate_read_error-light.png)、[确认表单/特殊字符](assets/u01/form-confirm-light.png)、[200% 缩放操作可达](assets/u01/form-200-percent-light.png)、[390 深色模型页](assets/u01/models-390-dark.png)、[390 深色表单](assets/u01/form-390-dark.png)。

</details>

- 本轮截图（正式 Panel、隔离 SQLite/HTTP 的执行事实；没有真实 Worker 或模型调用）：[正常概览](assets/u01/revision-overview-light.png)、[任务详情](assets/u01/revision-detail-light.png)、[设置](assets/u01/revision-settings-light.png)、[窄屏深色概览](assets/u01/revision-overview-390-dark.png)、[窄屏深色详情](assets/u01/revision-detail-390-dark.png)。返修仅更新这五张，由 Codex 自行查看；外部代码与产品整改审计已通过，不追加外部逐张截图验收声明。
- 本轮 Windows 定向：首次 U01/F04/Worker contract/R01/R02 集合 **171 passed / 1 failed / 33.18s**；修正开发传输的异步等待、详情返回顺序与夹具运行事实后，`pytest tests/test_u01_panel.py tests/test_f04_panel_boundaries.py::test_real_browser_text_rendering_nonce_and_pending_writes tests/test_r01_effective_config.py::test_browser_config_phases_and_sse_reconnect_are_safe tests/test_r02_lifecycle.py::test_real_edge_r02_status_receipts_and_new_attempt_pending -q` → **28 passed / 13.98s**。过程中保留并修正状态/焦点负例，不删断言。
- 最后补齐表单错误的单处展示/关闭后保留：F04/R01/R02 三个浏览器回归通过；U01 最终浏览器 **1 passed / 8.73s**，含原四宽度/浅深主题/200% 缩放、10 状态、键盘草稿、开发 HTTP POST 拒绝、旧 preview URL 真实数据、子任务失败/完成、仅阶段变更的列表更新；这些集合重叠不累计。compileall、JS 语法、diff-check、51 个本地文档路径、开发资源不在发布映射检查通过。
- 实施阶段 NOT_RUN：全量回归、clean install、打包、smoke、真实 AO Mission/收费模型、完整 U02 任务旅程；截图自查与本次外部代码/产品整改审计分别记录，不将后者等同逐张截图验收。没有 GLM/Kimi 接入、结果导出、Controller/Store 重构、tag 或 Release。
- 本次收尾沿用以上 Windows/浏览器证据，仅更新既有背景文档并检查链接/路径、diff 与产品 blob 一致性；不重跑测试、构建、smoke、真实 AO/模型。
- U01 合入时的下一步（历史）：唯一指针 U02 TODO，首个切片“独立项目入口与本地执行”，完成后再推进完整任务旅程；尚未开始。M0/M1/M2 COMPLETE，M3 IN_PROGRESS；U03/模型扩展仍 TODO，当时 D10 独立产品目标尚未实现；后续实施事实见 U02 卡。

## V03-U02｜完整任务GUI与数据接线

- 状态：U02 DONE；首个切片“独立项目入口与本地执行” DONE；[PR #40](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/40) 四项返修再次外部审计 PASS，2026-09-08 已 rebase merge 到 main `3d0a33ebd69b6184f9e47dffca87895aba2d960a`，tree 与已审计 head `4dc536cfa493d1b4ea8a8c36b8c78f5c7e9e7b43` 相同。采用 Codex 0.150.1 App Server 本地 stdio，新本地任务不依赖 AO 项目/daemon；完整旅程与整卡已通过 PR #41 代码与返修审计并合入（DONE），合入证据见下文。
- 对应：A04/A05/A06/A08。依赖：U01+G2。
- 顺序（D10，2026-09-08 首切片授权）：先本地项目与 Codex App Server stdio 执行，再完整任务旅程。新本地任务不要求 AO/GitHub/origin；本轮采用本机 0.150.1，不迁移语义角色 CLI，不升级用户环境。
- 工作：真实就绪卡；显式Project与base确认；目标/范围/Gate/模型摘要；运行阶段、审批、取消、历史与重试；大错误常驻；真实角色调用与证据scope。
- 必测：未预先使用/配置 AO 的本地项目入口与执行；无 GitHub/origin 的普通本地项目；从新建到结果；断连重连不双发；停止请求不假完成；Gate read_error；引用/中文/超长文本；200%缩放；旧Mission只读。
- 完成：Playwright或等价浏览器测试在开发环境通过；用户实际GUI确认；不把API200当视觉PASS。
- 不做：未经授权后台创建Mission验证界面；浏览器依赖打入产品。
- 首切片范围：`codex/v03-u02-local-codex-execution`，base `0feca5de502ef97de33cf025166318ab8f748bfa`。新增薄的本地项目/stdio 边界，原 Controller/Store/Gate/Verifier、审批、UNKNOWN、配置/source 冻结继续使用；未开始后续旅程或 U03。
- 实现事实与公开协议版本见 [PROJECT](PROJECT.md#u02-首切片本地项目与-codex-worker)，用户流程/来源规则见 [产品说明](../clao/README.md#本地项目与来源确认)。真实模型/发布兼容性尚未验收；原目录不写入，linked worktree 不是独立导出包。
- 首轮主集合（审计返修前）：`pytest tests/test_u02_local_execution.py tests/test_panel_worker_contract.py -q` → **57 passed / 114.89s**（产品 venv CPython 3.12.7，真实 Git/SQLite/HTTP 与 UTF-8 stdio 替身）。覆盖正式 CLI、无远端 Git/普通目录/空目录、原始 dirty 内容与 index 不变、来源漂移/过滤/junction、真实闭环与红 Gate、审批/输入、UNKNOWN/重入/停止/replan、重新确认来源的新 attempt、新旧配置冻结、模型事实，以及实际 Edge 新建至成果流程。此前 54 passed / 100.57s 是追加最后三个用例前的集合，重叠不累计。
- 兼容复查：`pytest tests/test_u02_local_execution.py tests/test_f04_panel_boundaries.py tests/test_u01_panel.py tests/test_r02_lifecycle.py tests/test_f05_external_operations.py tests/test_approvals.py tests/test_approvals_bridge.py tests/test_approval_block.py tests/test_mission_preflight.py -q` 初次 **431 passed / 3 failed / 1 skipped / 217.13s**。三处为旧浏览器缺新来源确认、开发夹具缺该只读响应、旧 fake adapter 缺显式 backend；修正接线/兼容表达并保留断言。后续 F04/U01 浏览器与 R02 崩溃回执节点均通过；新增 replan 测试的错误导入已修正，包含在上述最终 54 passed 中。唯一 skip 为 Windows 原生 symlink 权限；真实 junction 回归通过。
- 追加正式 CLI/source 与 F04/U01/R02 浏览器检查 6 passed / 1 failed / 19.70s；失败揭示旧 AO model 标签过度泛化，已恢复明确的 AO spawn-resolved 标签，并与本地 thread/start/model-rerouted 事实分开；随后 `pytest tests/test_u02_local_execution.py::test_native_model_facts_do_not_become_provider_timing tests/test_r01_effective_config.py -q` → **48 passed / 37.24s**（含实际 Edge 配置/SSE/模型来源安全渲染）。集合重叠，不累计成一次全量结果。
- 检查中的真实故障也已覆盖：Windows 协议替身修正为协议规定的 UTF-8；HTTP 回答提交期间与 Controller 恢复对账互斥，回执丢失/重启仍 UNKNOWN；真实 CLI/Panel/Controller/Git/Gate 不被成功 stub 替换，语义模型才使用 fake Provider。截图临时目录准备失败的一轮未进入产品测试，修正目录后完成上述最终集合。
- 最后负例发现继承的 Git smudge driver 可在隔离 checkout 时执行；私有仓库局部禁用 content filters/hooks/fsmonitor，保持原目录及全局配置不变，回归已纳入最终 57 项。用本机 `codex app-server generate-json-schema` 生成的 0.150.1 稳定 schema 校验 7 个客户端请求/通知和 12 个服务端消息；校正 readiness 的 null 参数及夹具完整字段后通过。此检查不启动模型，不将协议替身等同真实 Codex 任务。
- 截图由实际产品页面和隔离协议进程生成并已 Codex 自查：[桌面任务结果](assets/u02-local-execution/normal/normal-task.png)、[390px 深色](assets/u02-local-execution/normal/normal-390-dark.png)、[回答后验收](assets/u02-local-execution/question/question-task.png)。浏览器脚本在发布外 `dev/panel/u02-browser.cjs`，由测试启动临时 HTTP；可通过 U02 文件的 `-k actual_browser` 复现，不调用真实模型。不是生成图、产品演示模式或外部视觉审计 PASS。
- 静态检查：Python compileall、产品/开发脚本 JS 语法、diff-check、本地文档链接与 runtime 发布前缀检查通过。
- NOT_RUN：全量、clean install、打包、smoke、真实 AO/收费模型、独立安装与最终发布兼容性。

PR #40 审计返修证据（再次外部审计 PASS，已合入）：

- 修复 environmentId、人工硬边界、响应关闭/采纳和历史重试项目关联。固定协议的 `local` 是保留的本地环境 ID，结合绑定的 thread/turn/item/cwd 检查；普通 raw shell argv 与 item 展示字符串可能不同，保留原始输入检查。依据：[固定版本环境实现](https://github.com/openai/codex/blob/rust-v0.150.1/codex-rs/exec-server/src/environment.rs)、[事件/审批适配](https://github.com/openai/codex/blob/rust-v0.150.1/codex-rs/app-server/src/bespoke_event_handling.rs)、[请求关闭实现](https://github.com/openai/codex/blob/rust-v0.150.1/codex-rs/app-server/src/outgoing_message.rs)。没有升级环境、远程环境支持或新控制层。
- 后端实际 accept 按同一 Task 策略分为 AUTO / REVIEW / PROHIBITED_OR_UNSUPPORTED；正常 Gate/文件仍自动处理，受限查看请求支持人工确认/拒绝，危险 Git 不再作为人工正例。普通按钮不能覆盖 `.git`、禁止路径、越根或额外授权。
- 关闭请求不再计为采纳成功；正常确认需对应 item 事实，失效/取消/未知分别保留。回答没有公开唯一采纳证据时 HTTP 202、adoption 与 operation 均 UNKNOWN；仅已写入且已关闭的响应允许继续观察独立事实，不重发、不计成功，不放宽 UNKNOWN spawn/send/kill 或停止屏障。历史查询显示持久回执。重新执行确认和提交均按目标存档绑定项目/后端/父任务，覆盖不同内容、相同内容与新旧后端混合。
- Windows U02 定向：`pytest tests/test_u02_local_execution.py -k 'audit or approval or actual_http_question or new_attempt or actual_browser or formal_runtime_real or interrupt_ack or red_real_gate' -q` → **46 passed / 16 deselected / 119.32s**。随后补齐真实 raw/display 命令形态，`-k 'audit_native or audit_hard or audit_response or actual_panel_mission'` → **27 passed / 35 deselected / 42.80s**。含实际 Edge 项目 B 的确认/双击，以及真实 Git/Controller/Gate/HTTP；外部引擎/模型仍为隔离替身。
- 原审批文件 + F05 claim/未知 spawn/send/停止 + R02 历史/新 attempt 定向节点：117 passed / 1 failed / 1 skipped / 11.29s；失败为旧浏览器只预期 mission_id，补齐并断言新的项目/后端绑定字段后该节点 **1 passed / 8.12s**。skip 为原 Windows symlink 权限限制。新增测试初轮的 Controller 派发顺序、只读历史句柄清理和方法名错误已修正，未删除负例或弱化断言；集合重叠不累计。
- 最后历史回答回执 + 两个 U02 实际 Edge 流程 + R02 历史只读节点 **4 passed / 27.71s**；正常回答仍到真实 Gate/Verifier 结果，历史 HTTP 中采纳仍为 UNKNOWN。Python compileall、JS 语法、diff-check、本地文档链接检查通过；本轮没有重跑首轮大集合、全量、打包、smoke 或真实模型。
- 0.150.1 本机生成 schema 复查：7 个客户端请求/通知、12 个服务端消息通过，含 `environmentId=local` 与不同 raw/display 命令。真实模型仍 NOT_RUN，不将替身或 schema 验证写成真实任务验收。首切片收尾时 U02 首切片 DONE、U02/M3 IN_PROGRESS（历史）；整卡收尾见下文。
- 收尾仅检查文档链接、路径、差异与产品 blob；沿用上述验证，不重跑测试、构建、smoke 或真实模型。仍需已安装 Python/Git/Codex、已有登录及受支持的 Windows 沙箱；任意进程重连、独立导出与安装器未实现。旧 AO 历史只读与显式 AO 兼容后端独立保留，不将协议替身/浏览器验证写成真实模型或发布验收。
- U02 收尾时的下一任务（历史）：V03-U03 — 结果中心与独立导出，TODO，当时尚未开始；U02 两个切片与整卡、U01 均 DONE，M0/M1/M2 COMPLETE，M3 IN_PROGRESS；模型扩展/发布任务未推进。

完整任务旅程切片（2026-09-08）：

- [PR #41](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/41)，初始实现 `cdfd8cd654647a2f977b1efa6265d9d2cc4f89c6`，最终已审计 head `73b5a8055094bc09b4c6ee119034f09a4ff93903`；代码与返修再次外部审计 PASS，2026-09-08 已 rebase merge 到 main `e78738d0c11774b8163feb344256355a32ae5fb2`，tree 与已审计 head 完全相同。本切片与 U02 整卡 DONE。
- base `752ef0fbef10c638629bbbf2f1ef3f01e7d4ba72`，分支 `codex/v03-u02-task-journey`。同一启动 preflight 提供按需环境检查；四步表单确认项目/source、允许/禁止范围、多 Gate 与无密钥配置快照；移除空范围/空 Gate 的演示默认值。默认设置变化不改当前任务或已确认草稿，下个新任务才读取新默认值。
- 运行准备、真实角色阶段、审批/回答、取消与停止未知分别显示。审批可查看引擎已有 diff，截断明确标识；禁止批准仍可按后端能力拒绝，结构化问题显示真实选项。保留 F04 写保护、F05/R02 回执与 UNKNOWN，不重写协议/控制器。
- 历史详情采用只读 GET 查询，不 attach 到运行时；运行 A 时查看 B 不替换/停止 A。目标搜索/项目/状态筛选、任务归属写入检查、独立草稿及过期异步响应保护避免串数据。刷新保留任务视图，SSE 断连保留记录、重连不重放写操作。恢复检查仍由现有后端决定；结果目录可用性与 Mission 验收独立表达，失效位置和未通过产物不显示为成功交付。
- Windows 产品 venv / CPython 3.12.7，Scripts 前置 PATH，`src` 与产品目录为 PYTHONPATH。最终 `pytest tests/test_u02_journey.py tests/test_u02_local_execution.py::test_actual_browser_local_project_to_result tests/test_f04_panel_boundaries.py::test_real_browser_text_rendering_nonce_and_pending_writes -k 'not actual_journey_browser' -q --tb=short`：**27 passed / 4 deselected / 63.57s**；其中 23 项新 HTTP/配置/真实闭环检查和 4 项既有浏览器兼容检查。
- `pytest tests/test_u02_journey.py -k actual_journey_browser -q --tb=short` 对应的 4 条实际 Edge 旅程通过（最终命令含上述另 4 个指定节点，被筛选后 **4 passed / 27 deselected / 39.32s**）：环境未登录、正常任务至 Gate/Verifier、禁止文件差异/拒绝及运行中查看历史、取消停止未知。覆盖 1440/1366/768/390 四种宽度的浅深主题、键盘/草稿、安全文本、双击去重、历史刷新与延迟读取错误；200% 采用等效布局 viewport + CSS zoom 操作可达性检查，不冒称浏览器原生缩放已人工验收。
- 兼容定向：F04 Panel 文件 **119 passed / 56.77s**；U02 `-k 'actual_browser or actual_panel_mission or actual_http_question or audit_history or audit_http_history or audit_http_cancel or new_attempt or green_worker or interrupt_ack'` **17 passed / 46 deselected / 65.37s**。均非全量，各轮集合重叠不累计。
- 检查中保留过的失败：两次 Final Gate 读到同秒/同长度的旧 Python pyc，而实际交付源码正确；隔离测试改为直接执行源码，保留 `x == 2` 断言，产品仍正确阻断失败。停止轮询空值修正后揭示快照两次读取间的状态变化，已让启动限制与展示使用同一持久 stop fact，并验证 UNKNOWN 不能创建第二 Worker。最终上述用例均通过，未删负例或弱化断言。
- 截图自查后的停止阶段文字复查：`pytest tests/test_u02_journey.py -k 'actual_journey_browser and kill_live' -q --tb=short` → **1 passed / 26 deselected / 10.80s**。修改的 Python compileall、3 个产品/开发 JS 语法及 diff-check 通过；文档本地链接存在性检查通过，未改发布映射或新增运行资源。
- 实际截图（隔离协议进程，非真实模型）：[环境未就绪](assets/u02-task-journey/environment-unready.png)、[任务结果](assets/u02-task-journey/task-result.png)、[运行 A 时查看历史 B](assets/u02-task-journey/history-during-execution.png)、[禁止文件差异与拒绝](assets/u02-task-journey/approval-review.png)、[窄屏深色停止未知](assets/u02-task-journey/stop-unknown-dark.png)。Codex 已逐张自查，不等同负责人体验/视觉审计 PASS。
- 本地查看：正常启动 `clao/启动CLAO.bat`；打开概览点击“检查环境”，不创建 Worker/模型调用。离线复现上面四条旅程：设开发 Node 可执行路径为 `U01_NODE`、Playwright 所在 node_modules 为 `NODE_PATH`，在 `clao/` 按上述环境运行 `pytest tests/test_u02_journey.py -k actual_journey_browser -q -s`；可用 `U02_JOURNEY_SCREENSHOTS` 指定截图输出目录。测试使用临时 HTTP/Git/SQLite 与原 Controller，仅外部引擎/语义 Provider 替身；脚本在发布外 `dev/panel/u02-journey.cjs`，正式产品不提供演示资源或参数入口。
- NOT_RUN：全量、安装/clean install、打包、smoke、真实 AO/收费模型、最终发布兼容性及负责人完整体验审计。仍需已安装工具、现有登录与受支持的 Windows 沙箱；不支持任意进程重连、不增加并发，U03 独立导出、模型扩展、安装器未实施。实施交付时停止等待审计，未自行合并或创建 tag/Release；本次经负责人授权合并，收尾见下文。


PR #41 审计返修（2026-09-08，再次外部审计 PASS，已合入）：

- 返修基线 `78c1272fd67072e8bb2e87da6dcb6f91e644c62b`，原分支/PR 不变。停止限制复用已有 runtime 存档只读查询；Panel 重建、加载其它历史及正常 GET 使用同一持久 UNKNOWN，启动边界在产生 Worker 前再次核对。明确停止、正常完成或未产生 Worker 的失败不因缺字段误拦截；存档读取失败明确阻断，不当作没有限制。没有新数据库或强制忽略入口。
- 草稿在本任务 Worker 选项安装之后恢复接收目标，目标失效明确提示、保持原选择；文本、目标和编辑版本仍只存在原前端草稿 Map 中。指令成功只更新提交所属任务；同文 B 草稿及 A 提交后继续编辑的草稿不会被清空。审批/回答成功不再直接写共享回执区域，采用已有持久投影，返回原任务可查看；接收/采纳语义、失效保护与在途去重不变。
- Windows 产品 venv（CPython 3.12.7，Scripts 前置 PATH、`src`/产品目录为 PYTHONPATH，开发 `U01_NODE`/`NODE_PATH` 与前轮相同）：`pytest tests/test_u02_journey.py -k 'audit or stop_unknown_cannot' -q --tb=short` → **12 passed / 26 deselected / 48.79s**。含真实停止未知后重建 Panel、正式 API 阻断、另一只读句柄/历史查询、正常/未启动 Worker/已对账正例，以及 3 条实际 Edge A→B→A、相同/不同草稿、延迟真实 HTTP 成功响应与审批回执归属。Controller/Git/SQLite 使用生产路径，只替换引擎/模型边界；缺失 Worker 的展示另用隔离浏览器投影验证。
- 兼容定向：`pytest tests/test_u02_journey.py tests/test_f04_panel_boundaries.py::test_same_origin_page_nonce_allows_normal_write tests/test_f04_panel_boundaries.py::test_real_browser_text_rendering_nonce_and_pending_writes -k 'readiness or confirmed_config or history_b_while or actual_journey_browser or failed_start or same_origin or real_browser' -q --tb=short` → **16 passed / 24 deselected / 66.11s**。覆盖环境、配置冻结、历史只读、正常执行/审批/取消和安全文本/写保护，非全量；前轮大集合未重跑。
- 修改的 Python compileall、产品/开发 JS 语法、diff-check 与 3 个文档的 49 个本地链接路径检查通过；未新增文件、运行资源或依赖。
- NOT_RUN：全量、安装、打包、smoke、真实 AO/收费模型、完整 GUI/发布验收。保留现有任意进程重连未实现的边界；本轮不新增恢复平台或清除 UNKNOWN 的用户动作。返修提交时本切片与整卡 IN_REVIEW；现经再次审计与授权合并，U02 DONE、M3 IN_PROGRESS、U03 TODO。

收尾（2026-09-08）：沿用以上 Windows/浏览器定向证据与 Codex 截图自查；外部代码与返修审计 PASS 不代表负责人已完成完整 GUI 体验验收。200% 仍仅为等效布局/CSS zoom 检查；真实模型、全量、安装与发布验证尚未完成。本轮只更新现有背景文档及检查链接/路径、差异与产品 blob，不追加产品实现或重跑测试/构建。“任务闭环运行视图”仅在 [既有设计](V03_PLAN.md#52-屏幕与实际用户旅程) 记为未授权候选，下一任务仍为 U03。

## V03-U03｜结果中心与独立导出

- 状态：DONE；[PR #42](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/42) 再次外部审计 PASS、无继续返修阻塞项，2026-09-08 已 rebase merge 到 main `b755c1abe3c69167ddb62bc3489d513d97ea918d`；已审计 head `6ccaa5673052e30f3a77bf947b6be6812ec8b728`，合入内容一致。原实现提交 `13fae1ebefc66d62b165b968119460a17637d444`；2026-09-08 授权实施，base `f251535e209e14f6e9c698e290cce67aff8a2c16`，分支 `codex/v03-u03-results-export`。沿用现有结果/StateStore/Git/Panel，不实施闭环运行视图或模型扩展。
- 对应：A12、A03。工作：AC/Gate/Verifier/diff/commit；open/copy/export；完整patch和manifest；无效linked worktree的可读说明。
- 必测：新增/删除/rename/二进制（支持或明确拒绝）；隔离clone应用；export后临时worktree不可用仍能读取；无密钥/Prompt/.git导出。
- 完成：用户能在60秒内找到结果并知道main未改（建议体验目标）；补丁应用后内容/验收匹配；动作API不接受任意外部路径。
- 不做：自动主分支写回、自动GitHub PR或push；这些可后续单独设计。
- 已实现：沿用任务详情的结果中心，读取持久 Mission/AC/Gate/Verifier；版本固定为已记录 source commit/integration head，不读取当前内容替代，不调用模型/Worker。POST 导出/打开仅收 mission_id 并保留写保护；下载以该 Mission 的持久包标识定位，历史 B 不 attach 到运行 A。
- ZIP 仅含完整 `changes.patch`、`manifest.json`、`evidence.json` 与使用说明；StateStore 内 `result_exports` 仅记已保存的包。去重、原子保存、大小/SHA-256 校验；目录/Git 对象失效后仍下载已保存包及读取其匹配版本差异。无代码净变化明确标记；失败/取消的已有固定成果标未通过验收，UNKNOWN 不触发 commit/materialization。
- 支持/拒绝与独立使用方法见[产品结果说明](../clao/README.md#结果中心与独立补丁包v03-u03)。普通目录/空目录/无 origin 仓库不需要 checkout CLAO 私有 commit；准备匹配文件清单的独立基线副本，应用包后按内容哈希和验收核对。支持 UTF-8 普通文件、rename/copy/delete 与 Git 模式；二进制/其他编码/LFS 指针变化/链接/子模块/不安全 Windows 路径明确拒绝。来源排除规则和完整旧/新变化内容、补丁上下文及摘要凭据/Prompt 标记检查命中则拒绝整包，不静默删减；不是通用秘密扫描。
- Windows 产品 venv CPython 3.12.7，Scripts 前置 PATH、`src`/产品目录为 PYTHONPATH：`pytest tests/test_u03_results.py -q --tb=short` 最终 **39 passed / 84.44s**。真实 Git/SQLite/HTTP、正式 Mission/Controller/Gate/Verifier 路径只替换引擎/语义 Provider；覆盖正常结果、普通/无远端 Git/空基线、未提交原内容/index 不变、验收后新 commit 不混入、源码逐字节与 SHA-256 比对、独立真实 Gate、copy/rename/删除/模式、长差异完整补丁、限制材料/类型、失效工作区后下载/解压/应用、原子失败、并发重复、历史兼容和安全 API。
- 兼容定向：`pytest tests/test_u02_journey.py tests/test_f04_panel_boundaries.py::test_real_browser_text_rendering_nonce_and_pending_writes tests/test_f04_panel_boundaries.py::test_same_origin_page_nonce_allows_normal_write tests/test_f03_git_evidence.py -k 'actual_journey_browser or audit or real_browser or same_origin or committed or materializ or evidence_does_not_execute or git_environment' -q --tb=short` 初轮 **30 passed / 3 failed / 89 deselected / 116.88s**。失败揭示旧结果刷新覆盖新复核摘要、缺 head 的旧 merged 历史误显示未产出；已修正，不改原断言。之后 `pytest tests/test_u02_journey.py -k actual_journey_browser -q --tb=short` **4 passed / 34 deselected / 35.25s**；关闭浏览器时有 Windows 10053 连接关闭诊断，未造成用例失败。集合重叠不累计成全量。
- 首轮 U03 **26 passed / 3 failed / 66.15s**，三处均为隔离夹具删除 Windows 只读 Git 对象失败；改为只移动明确在临时目录内的测试仓库，使原路径不可用，保留下载/应用/内容检查。随后补齐限制/故障节点并复查（中间 34 passed），最终结果以上述 39 项为准，未删失败场景。
- 补充基线 artifact 语义：`pytest tests/test_u03_results.py -k preexisting_artifact -q --tb=short` → **1 passed / 39 deselected / 2.34s**；已存在的二进制 cache 不进入补丁，也不被应用过程删除。初轮夹具未按包内说明传入 `core.autocrlf=false`，新文件受全局 CRLF 设置影响导致内容哈希断言失败；按包内实际命令修正后通过，保留逐文件哈希断言。
- 实际 Edge 截图：[结果中心](assets/u03-results/result-center.png)、[差异与验收](assets/u03-results/file-diff-and-acceptance.png)、[390px 深色导出与剪贴板错误](assets/u03-results/export-390-dark.png)。同产品页面 + 隔离 Git/SQLite/HTTP，含下载 SHA 核对、A/B 延迟成功归属、剪贴板成功/失败、正常打开请求、键盘和四宽度；Codex 已自查，非真实模型或负责人完整体验验收。
- 本地查看：正常运行 `clao/启动CLAO.bat`，在任务列表打开有集成结果的任务，查看“结果与验收”。离线重现：配置开发 `U01_NODE`、`NODE_PATH`，执行 `pytest tests/test_u03_results.py -k actual_browser -q -s`；`U03_SCREENSHOTS` 可指定截图目录。脚本为发布外 `dev/panel/u03-results.cjs`，正式页面无夹具入口。
- 最后直接复查：目录 junction 不开放外部访问但仍可下载已有包、损坏包元数据 read_error、实际浏览器 → **3 passed / 38 deselected / 14.20s**；旧 AO 只读 DTO/缺失与畸形记录 → **4 passed / 37 deselected / 6.44s**，额外验证结果 API 不带出 `_validation` 原始输入。与主集合重叠，不累计。修改 Python compileall、产品/开发 JS 语法、diff-check、70 个本地文档链接（14 个标题锚点）及现有发布映射前缀检查通过；没有新增运行依赖或发布映射。
- NOT_RUN：全量、clean install、CLAO 发行打包、smoke、真实 AO/收费模型、负责人完整体验/发布验收。已做本任务结果包验证；没有自动写回/应用/push、模型扩展、安装器或闭环动态图。真实 Explorer 窗口出现未做自动验收；API 明确只表示 Windows 接收打开请求。


PR #42 导出误拦截返修（2026-09-08，再次外部审计 PASS，已合入）：

- 返修 base `18163a5305c8cafa96d6809702ead7ae44b2d7fd`，原分支/PR 不变。移除按敏感变量 RHS 长度与任意 `--prompt` 参数猜测泄密的规则；保留私钥、已知凭据形态、Bearer/Basic 认证头、明确 Prompt 材料标记，具名凭据检查非空引号字面值，精确 `${NAME}` 占位除外。没有整行/函数调用白名单：引用或调用中另含明确凭据仍拒绝。全部旧/新 blob、补丁与白名单摘要仍共用检查，不改写补丁、不改导出架构或类型支持。
- 新增真实 Git/SQLite/正式结果 API 回归：10 种安全引用/说明分别位于旧版本、新版本、未修改上下文与补丁之外，并出现在 Mission/AC/Gate/Verifier 摘要；实际下载补丁与 Git 原生补丁逐字节一致，在独立基线副本应用后逐文件/hash 与目标一致。12 个负例覆盖私钥、凭据字面值/形态、认证头、完整 Prompt、禁止文件和混入凭据的引用；明确拒绝且错误不带敏感值，同任务已有包仍原样下载，index/原项目不变。
- Windows 产品 venv / CPython 3.12.7，Scripts 前置 PATH、`src`/产品目录为 PYTHONPATH：`pytest tests/test_u03_results.py -k 'audit_export or restricted_old or http_export_applies or lookalikes_full or probe_failure or result_operations_are_bound' -q --tb=short` → **29 passed / 1 failed / 27 deselected / 77.70s**。唯一失败为新夹具错误假设远处源码不会出现在 Git hunk heading；加入独立段落标题使安全引用确实在补丁之外，保留原“补丁无该行”及逐字节/独立应用断言，不改产品或弱化断言。之后 `pytest tests/test_u03_results.py -k 'outside_hunk or actual_browser' -q --tb=short` → **2 passed / 55 deselected / 13.10s**，含实际 Edge 结果/下载/历史任务归属与既有交互复查。已通过的定向未重复跑大集合。
- Python compileall、diff-check 与修改文档的本地链接检查通过；本轮未修改 JS、结果页布局或协议，不另生成一套截图。NOT_RUN：全量、clean install、CLAO 发行打包、smoke、真实 AO/模型与负责人完整体验验收；结果包生成/下载/解压/独立应用已做。有限形态/字面值规则不宣称通用秘密扫描；返修提交时 U03 IN_REVIEW、M3 IN_PROGRESS（历史），收尾状态见下文。

收尾（2026-09-08）：按负责人授权完成 rebase merge 与背景同步；U03 DONE，U01/U02 保持 DONE，M0/M1/M2 保持 COMPLETE，M3 COMPLETE 仅表示本阶段开发和代码审计完成。沿用既有 Windows/Git/HTTP/浏览器证据与 Codex 截图自查，不等同负责人完整 GUI 体验或发布验收；本轮只检查文档链接与差异，未重跑测试、构建、smoke、结果包应用或真实模型。文件类型支持不变，结果包不含完整基线/项目依赖，敏感检测为有限规则。真实模型、完整 GUI 体验、全量、安装与发布验收尚未完成；M4 TODO，唯一下一任务 P01 TODO，尚未开始。无额外产品修改、tag 或 Release；闭环运行视图仍仅为候选。

## V03-P01｜模型配置／凭据与GLM语义后端

- 状态：整卡 **IN_PROGRESS**；工程实现与离线验证切片 **DONE**。[PR #43](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/43) 再次外部审计 PASS，外发确认归属问题已解决、无继续返修阻塞项；2026-09-09 已 rebase 合入 main `d1738b5337aecdfbc063fd284fb1e7bfa6fe7fcc`，合入 tree 与已审计 head `c629890d6fa3e740ffaa48a3117961f59dbe4988` 一致。P02 工程也已审计合入；剩余为两家真实服务与角色准入，以及已规划的质量、延迟、用量评测，非代码返修。联合执行内容为 TODO，等待负责人确认服务/型号权限、外发材料与次数/时长/费用预算，不取消测试要求。

- 对应：A11/A10。工作：profile/角色绑定/credential_ref；一种安全凭据存储；Codex保留；GLM明确服务域、认证、model/effort、JSON协议。语义角色无工具执行。
- 必测：密钥不进入响应/log/Store/export；跨域发送须授权；非法/截断/拒绝/401/429/timeout；Schema+ID+coherence；运行中不热切；有模型调用与无模型检查分开。
- 完成：一个已验证GLM profile覆盖所声明Planner/Auditor/Verifier角色；UI显示真实范围、价格unknown等；正向与真实失败反馈受控live。
- 不做：改全局~/.codex或AO daemon环境；仅换model字符串；静默跨供应商fallback。
- 工程实现：BigModel 通用 `https://open.bigmodel.cn/api/paas/v4/chat/completions`、`glm-4.7`，Bearer Key、非流式 JSON object、thinking enabled/disabled；明确拒绝 Z.AI/Coding/其他模型/未支持参数。三个角色共用原输入/提示词/Schema/ID/AC/coherence，Planner 分解与异常均接通；正常 gate-first/Worker/停止保护不变。
- 配置与凭据：旧 Codex 配置兼容，v1 快照原样校验保留，v2 冻结连接及绑定；默认原子保存不热切当前任务。Windows Credential Manager 存当前用户 CLAO 引用，无明文 fallback，无新增依赖；受保护 API 可保存/替换/删除，配置/查询/任务/子进程/导出不带 Key。每次新 Mission/attempt 明确确认外发，恢复保持旧配置/许可。
- 错误与取消：HTTP/结构化校验共享每次角色调用 1–3 次总尝试，Controller 不再叠加此类 ProtocolError 重试；semantic FAIL 不刷新成 PASS。正式 content 与 reasoning/tool/refusal/截断分开；只记有限错误摘要。既有 ExecutionControl 中止等待/重试，丢弃迟到响应，不声称取消服务端计算/费用。模型响应、实际 token 用量与 unknown 费用由当前 StateStore 阶段记录展示；连接页的本地检查不宣称真实准入。

Windows / CPython 3.12.7 / 产品 venv（Scripts 前置 PATH，`src` 与产品目录为 PYTHONPATH）证据：

- 最终 `pytest tests/test_p01_bigmodel.py tests/test_p01_panel.py tests/test_u03_results.py::test_audit_export_safe_references_apply_without_rewriting -q --tb=short` → **54 passed / 61.67s**。真实本地 HTTP（仅 HTTPS socket 目标替身）、原角色/Controller/Git/Gate 与隔离 App Server 进程；包含 Planner 两入口、Auditor、Mission Verifier PASS/FAIL、全部错误类/共享预算、取消在途与等待/迟到、旧 v1 实际恢复、CLI/Panel 混合消费者/冻结、正式结果导出中无 Key、安全引用旧/新/上下文及独立补丁应用。
- Windows 系统凭据验证在上述集合内实际调用 CredWrite/CredRead/CredDelete（非存储 mock）：独立随机 `CLAO-P01-Isolated-Test` 命名空间、仅假 Key，保存/替换/重新构造 wrapper 读取/删除；包括真实浏览器→HTTP→系统存储。每个测试 finally 清理并核对不存在；未读取用户凭据或全局 Codex/AO 配置。存储失败测试单独注入错误，不记作系统成功证据。
- 兼容复查 `pytest tests/test_codex_planner.py::test_build_runtime_uses_codex_planner_and_config_model tests/test_panel_worker_contract.py tests/test_f04_panel_boundaries.py::test_real_browser_text_rendering_nonce_and_pending_writes tests/test_u02_journey.py::test_audit_browser_mission_drafts_and_delayed_success -q --tb=short` → **31 passed / 20.71s**。保留三个 A/B 草稿、接收目标及延迟回执归属场景。
- 先前 R01/Codex/Verifier coherence 集合 **83 passed / 2 failed**；新浏览器脚本的隐藏概览按钮导航/终态等待已修正，原 runtime 夹具缺 frozen source/get_project 事实已用隔离 Git 与公开适配事实补齐，未改产品边界或弱化原断言；该 runtime 节点已在上述 31 项通过。P01 初轮 **47 passed / 1 failed**（浏览器导航）；随后 P01 + U02 四旅程 **53 passed / 1 failed**（同一旧 runtime 夹具），P01 浏览器与 U02 环境未就绪/正常/审批/停止未知四旅程均通过；最终 P01 结果以上述 54 项为准，集合重叠不累计。
- 实际 Edge：[模型配置](assets/p01-models/models-light.png)、[任务外发确认](assets/p01-models/task-consent.png)、[390px 深色](assets/p01-models/models-dark-390.png)。Codex 已自查；安全文本、无明文 Key/localStorage、角色选择、刷新后默认持久、在途去重、确认配置与实际冻结一致、原 Controller/Gate + HTTP Verifier 均有断言。不是负责人完整 GUI 体验或真实服务验收。
- 本地正常查看：`clao/启动CLAO.bat` → 模型。离线复现：配置既有开发 `U01_NODE` / `NODE_PATH` 后执行 `pytest tests/test_p01_panel.py -k browser -q -s`；`P01_SCREENSHOTS` 指定截图位置。只复用正式页面，`dev/panel/p01-models.cjs` 不进入运行资源。
- 最后确认页补充冻结 GLM 参数详情后，P01 实际浏览器单项 **1 passed / 14.85s**；截图已更新、自查。compileall、产品/开发 JS 语法、diff-check、6 个文档的 76 个本地链接/16 个锚点及既有发布映射前缀检查通过；没有发行构建。
- PR #43 外发确认归属返修：新建草稿的确认绑定项目及所选外发角色/连接（服务、endpoint、模型、credential_ref）；提交前再与确认配置核对，成功提交及下一草稿初始化清除。切换项目/外发角色/连接须重新确认；同一未提交草稿关闭重开、切页、SSE 和普通目标/预算编辑保留确认与输入。新默认值不热改草稿或已冻结任务；纯 Codex 无需外发确认，历史重新执行仍独立确认。未修改 Provider、凭据库、Controller 或 HTTP 重试。
- 返修定向：`pytest tests/test_p01_panel.py::test_audit_browser_consent_scope_and_new_missions tests/test_u02_local_execution.py::test_audit_history_retry_b_while_a_loaded -q --tb=short` → **5 passed / 50.13s**。实际 Edge/正式 Panel 与 Controller/Git/Gate，外部引擎、HTTP 模型及凭据读取使用隔离替身；新增浏览器用例完成 A/B、纯 Codex、历史重新执行共 4 个隔离 Mission，核对确认页/提交/持久配置值与 revision、跨草稿范围和在途去重、原项目不写回。历史 4 例覆盖不同/相同内容及新旧后端；替身补齐现有 `config_snapshot` 参数，并新增配置断言。正式 HTTP `test_actual_controller_git_gate_http_verifier_and_result_export` 的 PASS/FAIL **2 例通过**，无确认请求仍在 Worker 前拒绝。
- 返修首轮上述 7 项中 5 failed / 2 passed：新浏览器断言误要求 runtime 合并后的全部预算来源标注不变，旧历史替身未接收 P01 已有快照参数；修正测试契约后 5 项全部通过，保留配置值/revision/外发来源及原历史断言，未放宽产品规则。产品/开发 JS 语法、相关 Python compileall 与 diff-check 通过。仅返修定向验证，未重跑此前 54/31 项集合；返修提交时工程切片为 IN_REVIEW，之后已再次审计 PASS 并合入，真实 GLM 准入仍待验证，P02 未开始。
- **真实服务准入：NOT_RUN / 联合执行 TODO**（两家工程已完成，真实服务/角色准入及质量、延迟、用量评测尚未开始）。真实验证前仍需负责人确认 BigModel 通用服务类型、可用模型权限、参与角色及次数/单次与总时长/费用上限、允许外发的测试材料；本轮不读取或使用用户真实 Key。Key 由用户在本机凭据页保存，不发到聊天。配置保存、工程离线验证、代码审计通过均不等于真实请求或全部角色准入通过，P01 整卡及 M4 不标 DONE。
- P01 实施阶段 NOT_RUN（历史）：真实 GLM/Codex/AO 模型、全量、干净安装、CLAO 发行打包、smoke、负责人完整 GUI 体验与发布验收；当时未实施 P02/Kimi。P02 工程现已完成，P03 Worker 扩展、安装器/闭环视图仍未实施；M0–M3 COMPLETE，M4 IN_PROGRESS。


P01 工程收尾（2026-09-09，历史）：仅完成 PR #43 rebase merge、背景文档与本地 main 同步，保持已审计产品实现不变。沿用既有 Windows/浏览器/离线证据，本轮只检查文档链接与差异；未重跑测试、构建、smoke 或真实模型，未读取真实 Key、未创建 tag/Release。M0–M3 COMPLETE，M4 IN_PROGRESS；下一实施任务 P02 TODO，本轮停止，不开始 Kimi。

## V03-P02｜Kimi语义后端与切换评测

- 状态：整卡 **IN_PROGRESS**，工程接入与离线验证切片 **DONE**；[PR #44](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/44) 外部工程审计 PASS，无返修阻塞项，2026-09-09 已 rebase 合入 main `c112e25d332a284e857c9b2b0d3bd1ad32856485`，与已审计 head `d140e5d14e152ad1a64a4643bcbb1b775bac4a38` 的 tree 一致。base `6aefa5f5d2c0aeebcc99b115cf282a181efb73b5`，分支 `codex/v03-p02-kimi-semantic`。本轮国内通用服务工程接入、GLM/Codex 兼容及离线验证；两家真实 API、角色准入与切换质量/延迟评测待集中验证，测试要求与费用/外发授权不变。
- 对应：A11。依赖：P01的薄transport/本地校验契约。
- 工作：核对官方Kimi当前API和具体model；实现供应商参数差异，不复制整套角色/Controller；设置页明确数据发送、凭据和支持角色。
- 必测：与P01相同的协议/错误/安全矩阵；固定任务profile切换；Codex/GLM/Kimi回归；不支持参数保存前拒绝；requested/confirmed模型区分。
- 完成：一个已验证Kimi profile；与GLM均不是只列在UI；完成批准预算下的质量/延迟评测，已知负例假PASS=0。
- 本轮工程目标：`moonshot_cn`、固定 `https://api.moonshot.cn/v1/chat/completions`、`kimi-k3`；2026-09-09 核对官方 [模型](https://platform.kimi.com/docs/models)、[K3 参数](https://platform.kimi.com/docs/guide/kimi-k3-quickstart)、[JSON Mode](https://platform.kimi.com/docs/guide/response_format)。Bearer、非流式 JSON object + 原完整本地校验；reasoning_effort low/high/max，max_completion_tokens 含思考；不传 GLM thinking/temperature/max_tokens，不开放国际/Coding/中转。具体范围与参数见 [产品说明](../clao/README.md#glm-语义角色配置p01-工程切片)，不视为账户已获权限。
- 共用原 BigModelTransport 的完整回复、超时、取消及单层预算，不复制角色/Controller；Planner 两类调用、Auditor、Mission Verifier 可独立混用 Codex/GLM/Kimi，Worker 仍 Codex。旧配置/v1/v2 快照、glm-4.7 与 Codex 默认保持兼容；连接在当前 Mission 固定，默认删除/修改不热切换；缺凭据明确失败。
- 凭据按原 GLM `CLAO/BigModel` 与新 Kimi `CLAO/MoonshotCN` 隔离，同名引用可分别读写/替换/删除，不枚举或迁移用户凭据。正式 HTTP 使用 service，缺字段的旧请求仍仅 GLM。实际 Windows CredWrite/Read/Delete 在随机测试命名空间验证，两家假 Key，finally 清理并核对不存在；不读用户真实 Key。
- 外发许可列出实际服务组合，旧 BigModel 单项许可不能授权 Kimi；前后端在 Worker/外发前检查。模型页共用服务/参数/凭据/角色编辑，确认生命周期沿用 P01；保存连接后复用已有有序 HTTP 快照更新默认值，避免首个 SSE 前新草稿仍读旧连接，不改变已有草稿。新草稿清除上一任务准备提示。
- 最终 Windows 定向：`pytest tests/test_p02_kimi.py tests/test_p01_panel.py::test_browser_profiles_credentials_consent_and_real_pipeline tests/test_p01_panel.py::test_audit_browser_consent_scope_and_new_missions tests/test_f04_panel_boundaries.py::test_real_browser_text_rendering_nonce_and_pending_writes -q --tb=short`：**65 passed / 133.90s**。两个独立本地 HTTP 替身验证地址/Key/模型/参数/材料归属；实际语义 Provider 与 Controller/Git/SQLite/HTTP 路径，替身仅在外部边界；覆盖混合/纯服务、正式 CLI、冻结/历史、合法 FAIL、错误 ID/AC/JSON、拒绝/截断、401/429/超时/取消、缺确认无外发、包下载无 Key/原目录不写回。浏览器四任务旅程覆盖同草稿、跨项目/角色/服务、新默认、Codex、历史重新执行、诊断及写保护，配置与持久快照核对一致。
- Codex/停止兼容：`pytest tests/test_codex_planner.py tests/test_codex_auditor.py tests/test_codex_verifier.py tests/test_u02_local_execution.py::test_failed_or_unknown_worker_cannot_become_mission_success tests/test_u02_local_execution.py::test_interrupt_ack_is_not_stop_fact tests/test_u02_local_execution.py::test_green_worker_with_red_real_gate_is_not_done -q --tb=short`：**41 passed / 24.17s**。P01 原 HTTP/凭据/Panel 文件在本轮首轮与复查中通过，集合重叠不累计为全量。
- 首轮 P02/P01 集合 95 passed / 9 failed：新 HTTP 夹具重复 model 参数、AC 类别断言及 300ms 测试进程启动时限已修正（语义路由测试明确使用 3s 启动/1s send/kill）；浏览器暴露保存连接到新草稿的快照接线问题已修复。其后 68 passed / 1 failed 为新浏览器角色大小写/文案断言，确认文案统一角色名称并通过上述最终集合。保留失败用例及边界断言，未用重试掩盖 Worker UNKNOWN。
- 实际 Edge 截图（Codex 自查，非负责人体验验收）：[连接与凭据](assets/p02-models/p02-models-light.png)、[混合服务确认](assets/p02-models/p02-mixed-confirmation.png)、[任务模型诊断](assets/p02-models/p02-model-diagnostics.png)。正常查看：`clao/启动CLAO.bat` → 模型/新建任务；离线复现配置既有 U01_NODE / NODE_PATH 后 `pytest tests/test_p02_kimi.py -k browser -q -s`，可用 P02_SCREENSHOTS 指定截图位置。开发脚本复用 `dev/panel/p01-consent.cjs`，不成为产品预览或运行资源。
- 静态检查：产品与相关测试 compileall、产品/开发 JS 语法、diff-check 通过；6 个现有文档的 81 个本地链接与 18 个锚点有效。现有 manifest 的 panel/src/tests 前缀覆盖本轮修改，未新增 runtime 依赖或执行发行构建。
- NOT_RUN：真实 GLM/Kimi/Codex/AO 请求、实际角色准入与质量/延迟/费用评测、全量、干净安装、发行打包、smoke、负责人完整 GUI 体验及发布验收。两家工程均已审计合入；剩余为真实服务/角色准入及质量、延迟、用量评测，当时拟进行的联合执行现暂缓，改以 AO 原生底座迁移为唯一指针；真实评测仍须负责人确认服务/型号权限、允许外发材料与费用/次数/时长预算；本轮不读取或使用真实 Key。P01/P02 工程 DONE、整卡 IN_PROGRESS；M4 IN_PROGRESS，M0–M3 COMPLETE；P03/闭环视图/安装器未开始。
- 不做：猜测ChatGPT订阅覆盖API；以一次OK响应宣称全角色可用。
- 证据：工程与离线验证见上述记录；联合真实服务/角色准入及质量、延迟、用量评测暂缓，待后续授权。
- 工程收尾（2026-09-09）：PR #44 已合并，仅同步现有背景文件并检查链接/差异及产品 blob 不变；未重跑测试、构建、smoke 或模型。工程审计不等于真实供应商请求、角色准入、质量或完整 GUI/发布验收通过。联合实测未启动，不开始 P03、不创建 tag/Release，已发布 v0.2 不变。

## V03-P03｜第二Worker能力准入决策

- 性质：有条件扩展；决策记录为必须，非Codex Worker上线不是无条件承诺。
- 工作：查固定AO版本官方harness、tool/edit/approval/kill/model设置与隔离；选GLM或Kimi的一个可行组合做专项。
- 两种完成结果：SUPPORTED（完整Worker E2E与隔离通过）或DEFERRED（明确限制，UI禁用且说明；负责人批准）。均不能写“全部模型完全切换”。
- 必测（选择上线时）：两个配置互不污染、实际工具编辑、审批、取消、重启、Session实际model、同任务Gate/交付；禁止继承未验证全局别名。
- 不做：为支持下拉框patch AO、自造coding agent、把API JSON调用称为Worker。
- 证据：待填。

## V03-Q01｜新Windows产品验收与发布候选

- 依赖：G1—G4；无未处置高等级正确性／权限缺陷。
- 工作：独立安装包、依赖准备、干净机器首次任务验收；现有源码 ZIP 不等于独立产品。继续单一 manifest 映射；依赖锁定、来源许可、代码/脚本边界；从新ZIP开始bootstrap；两套干净Windows环境；普通用户首次任务；真实CLI/GUI与失败恢复；各已支持模型profile live。
- 评测：预先批准有限次数/时长/费用预算，固定同任务/source/Gate/成功标准做对照与角色消融；评估完成质量、人工介入、耗时和用量，未知用量不伪补，不以 Agent 数量证明优势。演示视频在产品完成后制作，开发夹具不作为用户功能。
- 完成：固定source SHA、最终artifact hash、任务/Gate/Verifier/SCM证据、浏览器记录、明确模型支持矩阵、已知限制和回滚说明。所有查询/字段错误不能被空成功吞掉。
- 发布纪律：旧v0.2不可覆盖；产品文件若变，重新验证受影响路径；仅开发文档变可用manifest blob等价性，不重跑昂贵live。
- 证据：待填。

## 通用证据模板

```text
任务ID / 状态：
日期 / 源码基线 / 分支 / PR：
设计依据：V03_PLAN节号；原报告A编号/页码
修改范围：
原负例：命令、环境、失败输出（有界脱敏）
修复后：相关测试、全量/编译、API/浏览器/live实际结果
未执行：明确NOT_RUN；原因
产品行为/配置/Schema变化：
Windows/AO/model/SDK实际版本：
残余风险 / 停止条件触发：
下一步：由PLANS唯一指针决定
```
