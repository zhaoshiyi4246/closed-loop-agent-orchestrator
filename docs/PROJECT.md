# CLAO 当前项目事实

更新：2026-09-09（F01–F05、R01/R02、U01/U02/U03 均 DONE；PR #43 / #44 工程审计 PASS 并已合入，P01/P02 工程切片 DONE、整卡 IN_PROGRESS；M0–M3 保持 COMPLETE，M4 IN_PROGRESS；当前唯一执行内容为 AO 原生底座 + CLAO 闭环迁移，IN_PROGRESS；联合真实评测暂缓）。本文件只记录已实现事实与已知限制；v0.3 的设计见 [V03_PLAN.md](V03_PLAN.md)。真实模型、完整 GUI 体验、全量、安装与发布验收尚未完成，已发布版本仍为 v0.2。

## 1. 版本与基线

| 项目 | 当前事实 |
|---|---|
| 产品 | CLAO / Closed-Loop Agent Orchestrator |
| 已发布版本 | v0.2，Windows本地比赛版 |
| 已发布源码 | 4d3e8e6b5e70bab868b2eef0d28c7742dea044ba |
| 开发目标 | v0.3：F01–F05、R01/R02、U01/U02/U03 已审计合入 main（DONE）；M0/M1/M2/M3 COMPLETE，M4 IN_PROGRESS；P01/P02 工程切片 DONE、整卡 IN_PROGRESS；当前唯一执行内容为 AO 原生底座 + CLAO 闭环迁移，IN_PROGRESS；联合真实评测暂缓 |
| 主仓库 | zhaoshiyi4246/closed-loop-agent-orchestrator |
| 产品源码路径 | `ao/` 为当前迁移开发入口；`clao/` 保留旧产品与可复用核心，正式默认入口未切换 |
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

## 2. 当前迁移架构

`ao/` 基于 v0.12.12，原样导入 `81d2ea9`；实际开发入口为 [dev-clao.ps1](../ao/dev-clao.ps1)。Electron 原生界面/模型菜单 → AO HTTP/Manager/Chat/driver/workspace/SQLite；可选 CLAO service 在同一 daemon 内保存 Mission/operation/验收并独占自动跟进。纯 Python 子进程复用 F02/F03/Gate/Verifier 校验，不运行旧 Controller 或 Panel。

已接线：原生项目与模型选项创建闭环、冻结干净单仓库 base、Worker 停止确认、确定性 Gate/范围、最多三次修复、固定结果及独立原生 Session 复核。原生详情展示 AC/分项验收/文件与结果位置；缺结果或读取失败不算 PASS。开发身份/数据/发现与官方 AO 分离，更新/云账户路径不接官方服务；旧 CLAO 配置、凭据、数据库不自动迁入。

当前边界与开发步骤见 [ao/CLAO.md](../ao/CLAO.md)。代表 OpenCode ACP 离线完整路径已验证，Codex 隔离 Windows 账户被上游安全检查阻止；真实账户/模型、全执行器闭环准入未通过。旧版脏/普通目录来源快照、独立导出中心、历史导入、完整恢复和 Planner/Auditor/独立角色配置尚待迁移。M4 IN_PROGRESS，PR #45 已被新路线替代；历史 M0–M3 完成状态不代表这些新路径完成。

### 保留的旧 clao 架构与历史实现

以下内容说明旧产品，不与新 daemon 同时运行，也不伪装成已迁移能力。

```text
Panel / CLI → 同一runtime组装与preflight → MissionController
                                     ├ per-task ClosedLoop
                                     ├ Planner / Auditor / Verifier
                                     ├ deterministic Observer / Gate
                                     ├ ActionExecutor → Codex App Server Worker / 旧 AOAdapter
                                     └ StateStore
StateStore → StoreBusProjector / JSONL / Markdown / GUI
```

MissionController是控制编排权威，ClosedLoop负责子任务；StateStore保存逻辑状态、动作、计数和证据。新本地任务由 Codex App Server stdio 提供 thread/turn/item/approval 外部事实；旧 AO 后端提供 Session／conversation／activity／workspace 事实。AOAdapter主要读取，也包含approval resolve POST；ActionExecutor执行有限spawn/send/kill。Bus不是控制传输层。

语义角色默认使用共享headless Codex CLI，P01 可按角色选用 BigModel 通用 HTTP 传输，P02 已合入 Kimi 国内通用服务（两家工程已审计、真实准入均待验证）；stdin传Prompt，保留ephemeral/read-only、schema输出、non-Git cwd支持。新本地 Worker 使用 Codex 0.150.1 App Server；旧 AO 任务保留 Codex harness 兼容。当前历史验收模型为gpt-5.6-sol，不把这个字符串作为永久模型支持清单。Observer/Gate不用模型。

### U02 首切片：本地项目与 Codex Worker

首切片 DONE；[PR #40](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/40) 再次外部审计 PASS，2026-09-08 已 rebase 合入 main `3d0a33ebd69b6184f9e47dffca87895aba2d960a`。已合入的完整旅程复用这些执行契约，U02 整卡 DONE；M3 当前收尾状态见下文 U03。

- 本地项目登记沿用 runtime 下的原子 JSON 文件；Panel 支持打开/创建/再次选择，CLI 用 `--project-path` / `--confirm-source`。本地 Git 无需 remote，普通目录/空项目无需 Git 初始化；不访问 AO REST/CLI/项目/runfile。
- 来源预览显示当前磁盘文件清单、hash/revision 和排除项，含未提交内容；确认后私有 source Git 与 detached Worker worktree 固定该内容。Git 项目只读取 tracked 与未忽略文件；拒绝链接/junction、特殊文件和超限输入，跳过凭据名/运行缓存/依赖目录。10 MiB 单文件、100 MiB/10000 文件上限；清单检查不是万能密钥扫描。原目录、index、分支、ignore 与全局配置不变。
- 私有 Git 禁用 hooks/fsmonitor 及继承的内容过滤器，避免来源 `.gitattributes` 在 checkout 时执行用户全局配置中的处理程序；来源 Git 只读查询也禁用 fsmonitor。存在可覆盖这些设置的 `GIT_CONFIG_COUNT/PARAMETERS` 环境配置时明确拒绝导入，不修改该环境。
- 采用本机 `codex-cli 0.150.1` 的稳定生成协议；公开源码 tag `rust-v0.150.1` / `0eb410ad0dd161ea323b05452f978de01cd63430`。JSONL UTF-8 stdio，initialize/initialized，thread/start、turn/start/steer/interrupt，item 与 turn 通知；模型初始配置和 model/rerouted 的来源分列。只读 account/read、windowsSandbox/readiness 核对已有 ChatGPT 登录与沙箱，不登录、不读取引擎私库。config/read 只用于在此次线程禁用继承 MCP，不保存原配置；进程级覆盖关闭插件/附加 Agent 等工具，不修改全局文件。
- Mission 原 StateStore 冻结 execution_backend/config/source/version；Adapter 使用原生 thread/turn/item 事实，不伪造 AO Session DTO。文件/命令审批复用 F02 范围与精确 Gate 策略；完整 fileChange item/started 路径（含 move 来源/目标）才能自动允许一次，额外授权/未知工具不支持通过普通人工审批放行。Panel 的 Host/Origin/nonce/JSON/文本渲染边界继续有效。
- 生产 MissionController/ClosedLoop 继续 gate-first 和终局 Verifier；单次 turn completed 不覆盖执行失败、scope 或 Gate 失败。materialization 必须关联回合已结束且无在途命令/文件 item；新结果仍在 integration，不写回原项目、不自动 push。Planner/Auditor/Verifier 保留现有 Codex CLI，不增加模型轮次。
- 原 operation intent/claim/ACK/UNKNOWN 用于 spawn/send/kill 与单次审批。ACK 持久后本地中断可复用；无 ACK 不重新创建线程或重发回合/输入。interrupt ACK 不算已停，只有关联 ended 事实可继续。人工审批提交期间与 Controller 对账互斥，进程消失后的不确定结果仍 UNKNOWN。
- PR #40 审计返修：官方 0.150.1 保留的 `environmentId=local` 与已绑定 thread/turn/item/cwd 共同核对；未知/远程环境不支持授权。item 是展示命令，审批参数保留原始 shell argv，只接受现有解析器确认的等价形式。后端单次 accept 再读 Task 范围；禁止路径、`.git`、越根、危险 Git、额外权限不能经人工按钮绕过。精确 Gate/已有查看操作自动允许，受限 `git ls-files` 摘要可人工确认；不支持任意 shell 授权。
- 审批回执分别记录响应写入、请求关闭、关联 item 结果与采纳状态；`serverRequest/resolved` 本身不证明采纳。无响应即关闭为 EXPIRED，提交期间取消为 INVALIDATED/UNKNOWN；同一 item 的执行/拒绝事实可确认相应结果。0.150.1 没有公开回答采纳回执，因此正常回答的 adoption 仍 UNKNOWN（HTTP 202），不伪造成功；仅已写入且已关闭的响应允许继续观察独立执行/Gate 事实，UNKNOWN operation 原样保留、绝不重发或计作成功。此例外不适用于 spawn/send/kill，也不放松停止前置条件；历史 API 仍可查看持久回执。
- 历史“重新执行”通过现有来源读取边界按目标 Mission ID 读取其项目和后端，确认框展示目标路径；提交再次绑定父任务、project_id、backend、source revision。当前已加载的另一任务不参与这次来源选择，即使两个项目内容哈希相同也不能混用。
- 老 AO 记录缺 backend 按 AO 解释，历史只读；本地恢复不能换后端/版本/配置。活跃、等待请求或断连 Worker 重启后不猜测停止，只能查看并人工核对；完整已结束检查点继续原 R02 校验，已结束 Mission 必须新 attempt 并重新确认来源。两独立子任务预算仍保留，依赖计划继续明确拒绝；本切片主验证为单 Worker。
- 官方协议参考：[App Server](https://developers.openai.com/codex/app-server/)、[固定版本源码](https://github.com/openai/codex/tree/rust-v0.150.1/codex-rs/app-server)、[Windows 沙箱](https://developers.openai.com/codex/windows/)。本轮验证是 Windows 隔离 Git/SQLite/HTTP + 受控 stdio 进程和浏览器；真实 Codex 模型任务 NOT_RUN，不视为最终发布兼容性通过。Q01 仍负责安装、依赖准备和干净机器验收。

### U02 完整任务旅程与 GUI 数据接线（DONE）

[PR #41](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/41) 代码与三项返修再次外部审计 PASS，2026-09-08 已 rebase 合入 main `e78738d0c11774b8163feb344256355a32ae5fb2`，tree 与已审计 head `73b5a8055094bc09b4c6ee119034f09a4ff93903` 完全相同；U02 两个切片与整卡 DONE。

- 概览的按需环境检查与本地启动共用 `local_preflight`，检查 Git、Codex 0.150.1、已有登录和沙箱；显示未检查/检查中/可运行/需要处理及检查时间，SSE 不重复触发进程。检查不创建 Mission/Worker、不调用模型，启动仍重新核对真实条件。
- 四步表单以同一有效配置解析器确认本次模型、预算、Gate 超时/输出限制；确认快照直接交给启动边界并冻结。草稿保留打开时的默认设置，修改默认值不改变运行任务；成功启动后的新草稿才采用最新默认值。空范围/空 Gate 明确拒绝，禁止路径与 `.git/**` 一起持久化；来源变化要求重新确认，不补演示路径。
- 准备中即有状态，失败保留原因与草稿；任务首层区分真实角色执行、审批/回答、验收、整理结果与取消/停止未知。待处理项链接到所属任务；文件差异使用已收到的 item facts，展示截断明确标识。后端禁止批准的命令/文件仍能按现有能力拒绝，回答选项来自原请求；UNKNOWN 回执不伪称采纳，也不覆盖后续独立执行结果。
- `GET /api/mission?mission_id=...` 和限定 Markdown 文件读取只投影对应历史记录，不替换正在运行的 runtime。任务目标搜索与项目/状态筛选、刷新后的任务路由、每个任务的输入草稿及延迟响应检查防止串数据；生产写请求携带任务 ID，后端核对当前消费者。SSE 仍按 epoch/sequence 接收完整快照，不重放动作。当前 Worker 停止未知时后端也阻止另一任务启动。
- 结果摘要分别展示 Mission 结论、关联终局 Verifier、各 Gate 分项与实际 integration 位置；目录存在不代表验收成功，失效或无法读取明确显示。历史详情只读，恢复仍通过原检查点/配置/source/停止校验，重新执行仍绑定目标存档自己的项目与后端。
- PR #41 审计返修：Panel 启动边界与界面共用现有存档查询的停止限制，覆盖持久 worker_stop / local_execution / cancellation UNKNOWN；重启和只读历史句柄不能解除，读取失败保留原因并阻止新启动。明确停止和未产生 Worker 的正常失败记录不因终态或缺字段永久阻塞。草稿先恢复本任务 Worker 选项再恢复接收对象；失效 Worker 保留选中提示，不回退 Planner。延迟指令回执按任务与编辑版本更新，审批仅渲染任务归属的持久回执，不直接覆盖共享区域。

验证为 Windows 隔离 Git/SQLite/HTTP、原 Controller/Gate/Verifier 路径与外部协议/Provider 替身，含实际 Edge 浏览器；命令、截图自查和 NOT_RUN 见 [U02 台账](V03_BACKLOG.md#v03-u02完整任务gui与数据接线)。U02 收尾时真实模型、任意进程重连、独立导出、安装/发布兼容性未验收或未实现；后续独立导出事实见下文 U03。未改变协议引擎主体，也未增加并发或写回原项目。已有 Windows/浏览器证据与 Codex 截图自查继续沿用；代码与返修审计 PASS 不等同负责人完整 GUI 体验验收。200% 为等效布局/CSS zoom 检查，未声明原生浏览器缩放验收；全量、安装与发布验证尚未完成，收尾未重跑测试或构建。

### U03 结果中心与独立导出（DONE）

[PR #42](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/42) 再次外部审计 PASS，2026-09-08 已 rebase 合入 main `b755c1abe3c69167ddb62bc3489d513d97ea918d`；导出误拦截返修已闭环。M3 COMPLETE 表示 U01—U03 开发和代码审计完成，不代表完整 GUI 体验、真实模型或 v0.3 发布验收完成。本次仅文档和差异检查，沿用以下既有验证。

- Panel 新增目标 Mission 的结果只读查询、完整差异和 AC/Gate/Verifier 分项展示；来源/提交 ID 留在详情。StateStore 同一读事务读取已有 Mission、Gate、最终 Verifier 和导出元数据，不从终态补造缺失 AC。
- `results.py` 只读已记录 source commit/integration head 的 Git 对象，NUL 路径解析；不使用模型 `git_diff_text`，不读当前工作内容代替已验收结果。local source 或 integration 提供对象；旧 AO 历史有明确 source/head 时可查询，无 AO/model 请求。原项目/index/分支不变。
- POST 生成/打开仅接收 mission_id，沿用 Host/Origin/JSON/nonce；GET 下载只接受所属 Mission 已记录包标识，路径从固定 runtime/exports 推导，拒绝穿越和 junction。打开目录确认的是 Windows Shell 已接收请求，不声称已观察到资源管理器窗口。
- 一个 ZIP 格式：完整 Git patch、两版文件哈希/模式及变更清单、白名单摘要、独立使用说明。原 StateStore 的 `result_exports` 表仅记录已完成包，不更新历史 Mission/验收事实。原子临时文件替换后登记；相同固定内容/证据复用同一个包，读包校验大小与 SHA-256。
- 原工作树或 Git 对象失效时，已有包继续下载并提供匹配版本的差异；未知停止不触发 materialization。失败/取消的冻结成果明确为未通过最终验收；目录存在与已验收分开。非空基线需保留匹配内容副本，不要求 checkout 私有 commit，包不含未修改源码或项目依赖。
- 当前支持 UTF-8 普通文件及 100644/100755 模式；新增/修改/删除/rename/copy、中文/空格路径。二进制、其他编码、LFS 指针变化、链接/子模块、不安全/Windows 不可表示路径明确拒绝完整代码包。复用 local_projects 的来源排除与 F03 artifact 规则；完整旧/新变化内容、补丁及必要摘要检查明确凭据/Prompt 标记，命中拒绝而不改写代码。具名凭据仅检查非空引号字面值（精确环境变量占位除外），不单凭变量名/表达式长度或 `--prompt` 参数拒绝正常源码；私钥、已知凭据形态、授权头与明确 Prompt 材料标记仍检查全部内容，调用/引用不豁免其中的真实凭据形态。有限规则不宣称通用秘密扫描；摘要去掉本机路径、限制长字段并标识，页面差异 24000 字节可见截断，下载不截断。
- 定向证据与实际截图见 [U03 台账](V03_BACKLOG.md#v03-u03结果中心与独立导出)。未执行真实 AO/模型、全量、安装、smoke 或 CLAO 发行打包；本任务结果包的生成/下载/解压/应用及内容与 Gate 核对已纳入定向验证。负责人体验审计仍待完成，闭环运行视图仍未授权。

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
| `worker.model` | 本地 Codex thread/start/resume；旧 AO spawn `--model`；含初始与 replan，保持默认 gpt-5.6-sol |
| `worker.spawn_max_attempts` / `spawn_backoff_seconds` | F05 已证明未执行时的有界初始 spawn 重试；次数 / 秒 |
| `worker.spawn/send/kill_timeout_seconds` | 本地 stdio 对应操作或旧 AO CLI 请求的等待秒数；timeout 不证明外部失败，不绕过 UNKNOWN |
| `roles.planner/auditor/verifier.model` / `timeout_seconds` | 角色选择 Codex 时实际传入模型与每次调用秒数；GLM 使用连接参数 |
| `ao.base_url` / `request_timeout_seconds` | 仅旧 AOAdapter 的 loopback REST fallback / 秒；本地任务不消费；有效 AO runfile 端口优先，外部发现事实不伪装成模型确认 |
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
未运行全量、安装、打包、smoke、真实 AO/模型或完整 GUI 视觉验收；R01 / R02 DONE，M2 COMPLETE；U01 已合入实现见下节，U02 首切片及 U03 的当前实施事实见前文。

### U01 工作台骨架（DONE，已审计合入）

[PR #39](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/39) 本轮代码与产品收敛整改外部审计通过，2026-09-07 已 rebase merge；产品实现保持已审计 head 不变。

沿用 Python Panel 与原生 HTML/CSS/JavaScript，四入口为概览、任务、模型、设置。
桌面侧栏、窄屏底部导航共用同一页面；浅/深/跟随系统主题只保存浏览器外观偏好。
任务首层显示中文状态、真实原因、当前阶段和下一步；原始 ID、配置快照、模型来源、
拓扑与事件留在高级详情。正常 SSE 仍消费现有有序快照，断连保留记录；更新不清空
表单或默认设置草稿，正在操作的列表区域延后更新且只采用最新事实。

四步新建表单保留项目、目标/验收、路径/Gate、模型/预算确认输入。项目必须明确选择；
U01 合入时仅提供既有创建接口和项目选择；已合入的 U02 首切片新增本地登记与来源确认接线，未新增模型/供应商选项，见前文。
历史摘要加载、恢复、新 attempt、取消、指令、默认设置与有限文件查看入口继续保留，
停止未知时不提供可用的新 attempt 按钮，实际权限仍由原有后端判定。

正常页面不提供状态预览，旧 `preview` 参数仍读取真实数据；正式静态 allowlist 不含夹具。
主层归并为待开始/进行中/需处理/取消中/已取消/已完成；断连为连接提示，Gate 读取失败为证据错误。
停止 UNKNOWN 属于需处理，取消接收不代表取消完成；子任务 DONE 不改变 Mission 状态。
“重新执行”继续调用原 `/api/new-attempt`，生成关联新记录，不重新运行旧终态。

开发资源移至仓库 `dev/panel/`（现有 manifest 不覆盖）；独立只读预览服务读取原产品 shell/assets，
用开发传输夹具调用同一渲染组件，不实例化 Controller/PanelState/AO，不提供写 API。
[启动与检查方法](V03_BACKLOG.md#v03-u01iphone风格界面骨架与状态夹具)；夹具取消状态为 `cancelled`，
停止事实与历史子任务状态分别保留，取消完成不显示 Worker 正在执行。
产品静态资源为四个固定路径；原 Host / Origin / JSON / nonce、memory.md/project.md 文件范围与
CSP 脚本 nonce 要求不变。12 个本地 Lucide 符号及完整 ISC/Feather MIT 许可保留；没有新框架、
构建服务、CDN 或模型探测请求。U01 合入时依赖 AO 注册项目及 origin；已合入的 U02 首切片提供无需 AO 的本地项目与执行入口，旧 AO 路径显式兼容。

定向 Windows/Edge 证据及截图索引见 [U01 卡](V03_BACKLOG.md#v03-u01iphone风格界面骨架与状态夹具)。
已有 Windows/浏览器验证与实际截图沿用，截图由 Codex 自查；本次外部代码与产品整改审计通过，不宣称外部逐张截图验收。合并收尾未重新运行测试或模型，仅做文档与差异检查。
M0/M1/M2/M3 COMPLETE；U01/U02/U03 均 DONE，U02 两个切片保持 DONE；M4 IN_PROGRESS，P01/P02 工程切片 DONE、整卡 IN_PROGRESS；当前唯一执行内容为 AO 原生底座 + CLAO 闭环迁移，IN_PROGRESS；联合真实评测暂缓。

## 4. 已验证外部前提

Windows、CPython3.12、Git、AO Desktop0.12.9、Codex CLI0.150.1及ChatGPT登录是v0.2的已验证组合。bootstrap只管理本地Python venv，不安装Python/Git/AO/Codex。

以下约束仅适用于已发布 v0.2 与显式 AO 兼容后端。AO executable通过CLAO_AO_BIN或PATH解析；runfile通过CLAO_AO_RUN_FILE或~/.ao/running.json解析。Project需要注册的Git-backed项目、identity、origin及有效remote-backed base；显式branch要求origin/<branch>，auto要求origin/HEAD。origin可以是本地bare repo。不自动修改Git/AO配置。该约束不适用于新本地 Codex 任务，也不宣称覆盖 AO 所有潜在能力。

新本地任务无需 AO 项目、daemon 或 origin，仍需已安装 Python/Git/Codex 0.150.1、已有 ChatGPT 登录和受支持且就绪的 Windows 沙箱。当前为离线协议/集成及浏览器证据，真实模型 NOT_RUN；不沿用 v0.2 live 结果宣称新后端已完成真实模型或发布验收。任意进程重连与安装器仍未实现；U03 独立补丁包已再次外部审计 PASS 并合入，支持范围与剩余验收边界见前文。

## 5. 审计缺口与修复状态

依据 [原审计](reference/CLAO_v0.2_audit_20260905.pdf)；F01 已补齐 A02 的完整契约与终局一致性及 A11 相关证据边界，F02 已修复 A01 的审批命令与路径包含性，F03 已修复 A03 的路径、artifact 和只读取证，支持边界见上文。其他卡继续保留：

- A04/A05：F04 已实现 Gate 表专用只读 DTO 与 command/integrity/scope/overall 记录、历史 unknown/read_error 区分及常驻错误；本地写 API 校验 Host/Origin/JSON/会话 nonce，路径包含性与安全 DOM/pending 去重已补齐。外部审计 PASS、已合入 main（DONE），已发布 v0.2 不变；验证和支持边界见 F04 卡。
- A07：F05 使用精确持久随机标记对账 spawn；普通 send 无唯一公开回执则保持 UNKNOWN、不重发；kill 需同一 Session 的 isTerminated=true / status=terminated。逻辑终止依赖 AO 公共契约，不承诺 OS 级证明或 exactly-once；再次外部审计 PASS、已合入 main（DONE）。
- A10：R01 已接通有效配置与阶段诊断，再次外部审计 PASS 并合入（DONE）；A06 / A08 / A09 的 R02 指令、取消恢复与 source/依赖已外部审计 PASS 并合入（DONE）；AO/Git 非原子边界保持，不宣称 exactly-once。
- A11/A12：U03 结果中心/独立导出已审计合入；多模型、完整用户体验及发布验收尚未完成，不因 M3 COMPLETE 宣称所有模型或发布路径已验收。

状态与证据等级请查 [V03_BACKLOG.md](V03_BACKLOG.md)。不能因为历史R5 COMPLETE把这些问题写成RESOLVED。

队友在既有发布基线上提供的 0.2.1-rc1 候选说明已作为 F01 评审输入；本次独立实现，未移植队友源码或继承其 live 结论，来源记录在 F01 卡。

## 6. v0.3目标与现状严格分栏

| 主题 | 当前实现 | v0.3设计（待实现） |
|---|---|---|
| GUI | U01 / U02 / U03 DONE：四入口、完整旅程、结果中心与独立导出；开发夹具独立 | 完整 GUI 体验及原生浏览器 200% 缩放验收 |
| 模型 | 本地 Worker 为 Codex App Server；语义角色默认 Codex CLI，可选 BigModel GLM；P02 已合入 Kimi（未实测准入）；AO 显式兼容 | 两家真实准入/切换质量、延迟、用量评测；Worker单独准入 |
| 配置 | R01 已合入；R02 恢复先验证冻结材料 | 新 GUI 的配置旅程 |
| 结果 | U03 DONE：固定版本差异、独立文本补丁包及摘要、历史下载 | 完整体验/发布验收；更广文件类型支持不宣称完成 |
| 停止 | F05 已合入；R02 明确取消状态、只读历史/恢复检查、关联新 attempt（DONE，已合入） | 新 GUI 的操作与错误体验 |

## 7. 文档职责与历史

AGENTS=规则；PROJECT=事实；PLANS=当前指针；V03_PLAN=目标设计；V03_BACKLOG=任务/证据。只有大写docs/PROJECT.md作为开发事实文件；runtime/project.md不属于项目治理。

原R0—R5历史文档未从Git历史删除，完整冻结内容见：

- [v0.2原PROJECT](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/blob/4d3e8e6b5e70bab868b2eef0d28c7742dea044ba/docs/PROJECT.md)
- [v0.2原PLANS](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/blob/4d3e8e6b5e70bab868b2eef0d28c7742dea044ba/PLANS.md)
- [v0.2Release](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/releases/tag/v0.2)

以后本文件仅按已合入代码或明确标注待审计的分支实现与验收更新，不复制完整PR流水账；旧治理文件的目标性措辞不再凌驾于本文件和v0.3批准设计。

## P01 工程切片：连接、凭据与语义 HTTP

工程实现与离线验证切片 DONE；[PR #43](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/43) 再次外部审计 PASS，2026-09-09 已 rebase 合入。整卡 IN_PROGRESS，剩余为真实 GLM 服务与角色准入，无继续代码返修阻塞项。P02 工程接入与离线验证切片也已完成：[PR #44](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/44) 工程审计 PASS，2026-09-09 rebase 合入 `c112e25d332a284e857c9b2b0d3bd1ad32856485`。P01/P02 整卡及 M4 仍 IN_PROGRESS。

现有角色 Provider 复用同一提示词、输入与完整本地校验；P01 新增 BigModel 通用服务，P02 已合入实现复用同一传输增加 Kimi。
Planner 的分解/异常调用、Auditor 和 Mission Verifier 分别消费冻结的 `roles.<role>.profile`。
Worker/Observer/Gate 边界不变。连接限定 `open.bigmodel.cn` / `glm-4.7` 或 `api.moonshot.cn/v1/chat/completions` / `kimi-k3`，
不共用 Z.AI/Coding 域或凭据，不静默 fallback。详细参数、来源/优先级兼容见
[现有产品 README](../clao/README.md#glm-语义角色配置p01-工程切片)。

新快照 v2 包含无密钥 `model_profiles` 与绑定；历史 v1 原样校验保留，缺新键仍走 Codex。
受保护凭据 POST 只使用 Windows Credential Manager 的 CLAO 命名空间；Key 不写配置/Store，
GET 只返回配置和凭据状态，无系统存储则失败。任务启动前验证冻结的外发确认与所选凭据存在性。
默认设置、连接检查不调用模型；任务运行中的响应模型/用量与工程准入状态分别展示。

P02 已合入实现复用原传输、角色与模型页，仅按两个明确契约生成参数：GLM 沿用 thinking/temperature/max_tokens；Kimi K3 使用 reasoning_effort/max_completion_tokens 与 JSON object，不支持自定义采样或关闭思考。
Windows 凭据按 `CLAO/BigModel`（旧位置）与 `CLAO/MoonshotCN` 隔离，同名引用不会跨服务读写/删除，无用户凭据迁移。
新许可记录实际服务列表；旧 BigModel 字符串许可仅覆盖 GLM。确认页列出每个角色/服务，连续任务重新确认；项目/角色/连接变化失效，同一草稿切页、重开、SSE 不丢确认。
连接变更不改已冻结快照；缺失该服务凭据明确失败，不选择其他服务。配置/连接状态读取不发供应商请求，不提供虚假的真实连接测试结果。

非流式 HTTP 每次超时明确、只接收完整 formal content，思考/工具/截断不制造 PASS。
HTTP 与结构化错误共用每个角色调用 1–3 次总预算，Controller 不叠加重试 ProtocolError。
取消接入既有 ExecutionControl，停止等待/重试并丢弃迟到结果；不声称远端计算或计费被取消。
配置已保存、离线验证及工程审计通过均不等于真实 GLM/Kimi 请求、全部角色准入或质量评测通过。两家工程均已完成；唯一下一执行内容为联合真实服务与角色准入及质量、延迟、用量评测，TODO，等待服务/型号权限、允许外发材料及次数/时长/费用预算确认。工程收尾只做文档与差异检查，未调用供应商或读取真实 Key，不开始 P03。完整 GUI 体验、全量/安装/发行包测试仍未运行。
