# CLAO v0.3 规划设计报告

> 文档版本：0.3-plan-r1 · 2026-09-06
> 状态：已批准 / IN EFFECT；2026-09-06 完成 V03-DOC-00 基线核对，规划生效不代表功能已经实现。
> 产品目标：**先修 Bug，再优化用户体验；让任务、结果与模型选择都清楚可信。**
> 开发基线：`4d3e8e6b5e70bab868b2eef0d28c7742dea044ba`（已发布 v0.2）。
> 设计权威：本文件；当前实现事实：`PROJECT.md`；当前执行指针：根目录 `PLANS.md`；任务状态与证据：`V03_BACKLOG.md`。

## 0. 本轮决策与阅读方式

本规划采用已上传《CLAO v0.2 全面架构审计与 v0.3 产品规划》（2026-09-05，29 页）作为缺陷基线，保留 A01—A12 编号与证据等级。该报告中的“源码确认”“隔离复演”“待验证推断”不得统一改写成已在真实用户机器发生的故障。[S01]

规划起草过程不是新一轮全量代码审计，未运行 AO、真实模型、Windows 回归或 GUI；M0 整理后的离线验收另记于 V03_M0_EVIDENCE。规划起草时采用上述发布源码；规划文件已进入 main `3a9ea27468915eb9571611bcca10962e7a732fb0`，与发布源码的产品 blob 差异为 0。本稿中所有 v0.3 接口、状态、设计尺寸和验收目标均是**新设计**，需要实施与验证后才可写入产品说明。[S02]

**确定采用：**

1. 保留现有 MissionController／ClosedLoop、StateStore、AO、Gate、Provider、事件投影主干，不重新增加协调 Agent、第二个数据库或控制总线。
2. 先关闭 A01—A05 的安全／正确性缺口，并补齐 A07 的关键停止与未知外部动作边界；此后才允许把新版 GUI 和更多供应商向普通用户开放。
3. GUI 借鉴 iPhone 系统应用的层级、留白、分组列表和稳定导航；仍是 Windows 本地浏览器产品，不做仿 iPhone 外壳，不要求原生 iOS，不开局域网访问。
4. 将 **GLM 与 Kimi 的语义角色接入**列为 v0.3 目标，逐个验收，不同时大铺供应商。Worker 的模型／harness 单独准入，不能拿聊天 API 成功冒充编码 Worker 可替换。
5. Markdown 是持续查询与实施的唯一规划正文；Word 是此日期的阅读快照，不建立第二套手工维护的计划。
6. 本轮由规划审计助手写出方案、项目负责人确认；Codex 负责实施、测试、证据更新和经授权的 Git 操作，不自行改变产品范围。

### 发布策略

已发布 v0.2 tag、ZIP、checksum 和历史验收不变。优先将修复集集成到同一开发主线；需要提前提供补丁时，可从这组修复发布 v0.2.1，不再另造一套并行产品。v0.3 完整版在安全、GUI、GLM／Kimi 语义后端及发布验收同时满足后发布；任何范围缩减必须由负责人明确批准并记录。

“先修 Bug”不意味着等所有闲置符号、历史注释、云功能都做完才做 GUI。修复门槛通过后，GUI 可以在固定的 API 契约上推进；不能继续几十轮只读盘点而没有可用增量。

## 1. v0.2 保留什么，不能沿用哪些承诺

### 1.1 已有实现与验收基线

v0.2 已实现：Panel／CLI 共用 runtime 组装与 preflight；默认单 Worker 确定性计划；证据充分时 gate-first；异常进入 Auditor → Planner；Task Gate、materialization、integration、Final Gate、Mission Verifier；StateStore 与后置投影；干净 ZIP 和 bootstrap。正式 Windows 环境已有 438 项测试以及指定 CLI 和人工 GUI Mission 的成功记录。[S01，第 3—7 页]

默认正常路径保持：

```text
任务确认 → shared preflight → 固定任务／配置／代码基线
→ 确定性 S1 → AO Worker → Task Gate → Task DONE
→ 停止事实确认 → materialization → integration
→ Final Gate → Mission Verifier → 程序级终局校验 → Mission 完成
```

新增的“固定快照、停止事实确认、程序级终局校验”是本版强化目标，不声称 v0.2 已完整具备。

### 1.2 现状与设计的分界

- `Task DONE` 只说明子任务阶段通过，不等于 integration 已完成，更不等于用户主分支更新。
- 现有 `Stop` 将任务写入 HUMAN，不是真暂停；新版先修正文案与取消流程，不凭 UI 按钮制造“可随时暂停恢复”的能力。
- StateStore 是逻辑状态权威，但交付还依赖 Git 对象／linked worktree；复制一个 `state.db` 不是完整迁移。
- AOAdapter 还承担 approval resolve POST，不能把当前实现写成绝对纯只读。
- L0 与用户 override 是明确的程序路径例外；“每条自动消息都必须由 Planner LLM 撰写”不是现状，也不是本版目标。
- “Schema 合法”“分项结论一致”“证据足够”“真实通过”是四层检查，不能互相替代。[S01，第 4—5、10、13、26 页]

## 2. v0.3 的范围和非目标

### 2.1 必交付

| 工作面 | v0.3 结果 | 不可替代的验收 |
|---|---|---|
| 修复与安全 | A01—A05 闭环、停止确认与未知动作保护 | 负例先红后绿，正常任务不回退 |
| 使用可靠性 | 有效配置、真实回执、阶段耗时、准确取消／恢复 | UI 与 Store／AO 实际事实一致 |
| GUI | 概览、任务、模型、设置四个稳定入口；任务与结果优先 | 浏览器测试 + 非开发者首次使用 |
| 模型切换 | Codex 保留；GLM、Kimi 各一个经验证的语义模型 profile | 每家独立协议／错误／真实任务准入 |
| 结果交付 | 查看差异、复制路径、打开结果、导出独立补丁包 | 删除临时 linked worktree 后导出仍可用 |
| 发布 | clean ZIP、依赖／来源说明、回归与已知限制 | 从最终 ZIP 而非开发环境验收 |

### 2.2 有界处理与延期

双任务保持默认关闭的高级能力。独立双任务要验证共同基线；存在依赖且尚不能证明 S2 读取 S1 已验证结果时，**明确拒绝该计划**，不得假支持。依赖图调度能力扩展不阻塞本版 UX 主线。[依据 S01 A09；处理方式为本稿新设计]

本版不做：云多租户、公开远程 Panel、任意网关代理、无限 Worker、向量长期记忆、Agent 商店、完整 Electron／SwiftUI 重写、自动安装全部外部工具、默认自动 push、运行中静默换供应商。高风险按需 Task Verifier不是本版必须项；现有 final-only 保持。

## 3. 缺陷基线与修复设计

### 3.1 A01：授权必须先包含性检查，再匹配规则

路径先规范化、解析实际路径并确认位于 Worker 工作树内；处理符号链接、junction、UNC、大小写和不存在文件的已有父目录。解析不明为 UNKNOWN，进入人工处理，不返回原字符串继续 glob。允许 `**` 只扩大**工作树内**的相对范围。

命令授权必须检查原始输入，再按实际平台／AO 请求形态解析；拒绝换行、命令链、重定向、任意模块名、短前缀。精确区分用户预先授权 Gate 与 Worker 自提命令。默认不自动批准丢弃改动的 `restore`、`checkout --`、reset、clean、push。严格匹配 `python -m pytest` 不等于任意 `python -m pytest*`。[S01，第 9 页]

验收：报告中列出的六类谓词负例、外部路径与符号链接越界均拒绝；授权范围内正常 Edit 与已确认 Gate 通过。测试只执行安全隔离用例，不在重要项目上执行破坏性字符串。

### 3.2 A02：格式、关联、覆盖与语义四层统一

采用必需的完整 JSON Schema 校验，缺依赖明确报安装错误；不得回退为顶层字段检查。可以评审移植队友候选的 validator 缓存、有限数值校验、错误数组不清空等补丁；保留来源，补丁实测前仍视为未集成。[S01，第 10 页；已有候选来源见 S09]

在现有 contract／Verifier 边界提供共享的程序级校验：

- `verify_id` 必须等于本次请求；Mission／Task ID 的映射必须由调用方明确给出。
- 每个必需 AC 恰好出现一次；缺失、重复、未知 ID 都不是成功。
- 顶层 PASS 需要所有必需 AC 为 PASS，anti-gaming 无 FAIL；必需 AC 为 UNVERIFIABLE 时不得 PASS。
- 路径越界、repository integrity 失败、证据缺失不能由模型覆盖。
- 截断必须可见，保存原长度／摘要；不能把前 6000 字符假称完整证据。无法在有界请求内补齐关键证据时进入人工处理。
- 格式或关联错误归协议失败；真实 FAIL 归语义结论，分别计数，不能伪装成 HUMAN／FAIL 的模型结论。

全语义角色共享格式与关联边界，具体角色的业务校验仍保留各自契约。不得把错误模型输出“修成空数组”来通过。

### 3.3 A03：路径与证据必须覆盖实际改动

Git 读取使用 NUL 分隔或等价无歧义表示；rename 必须同时核查 old/new，copy／delete／untracked 也不得遗漏。artifact 按目录段或明确后缀匹配，不用任意子串。untracked diff 不修改真实 index；证据采集前后 index、工作区和 HEAD 不变。Final Gate 后再做 Mission 级确定性范围复核。[S01，第 11 页]

基线命令的执行与采证也需使用同一完整性规则。不要复活已删除的 Gate 模块；改造现有模块／helper，基线红测容忍只在可审计证据下生效。

### 3.4 A04：Gate 与错误必须真实可见

为 Gate 表建立专用读取，不再查询不存在的 `payload_json`。区分 `no_records`、`read_error`、`not_run`，数据库查询错误不能变成空数组成功。UI 统一展示 alert 的 summary／description／error，并显示 Mission reason 与 Panel runner error。[S01，第 12 页]

Gate 展示必须分开 command exit、integrity、scope 和整体验收；`exit=0` 但修改了仓库时应是失败，不得由前端自行推断为绿灯。Task、baseline、Final 的 scope 明确；旧记录没有完整字段时标“历史字段未提供”。

### 3.5 A05：本地 Panel 也要有输入和浏览器边界

保持 loopback。对写请求检查受支持 Host、Origin、JSON Content-Type 和会话级随机 nonce／CSRF 凭据；nonce 不放 URL、日志或持久任务数据。对 mission_id、文件名和结果动作做规范与目录包含性校验。页面使用 DOM／textContent 或上下文安全编码，禁把不可信字符串拼入属性。[S01，第 12 页]

HTTP 200 与 SSE 连接不证明 GUI 安全。新增跨源、非法 Host、路径穿越、引号、HTML 字符、长中文等负例。外部浏览器攻击可达性按本机隔离测试确认，不把原报告的静态推断说成已遭利用。

### 3.6 修复冻结门 G1

上述问题有可重复测试、修复和源码位置；安全反例不得假 PASS；Windows 正向任务仍可完成。G1 通过前可讨论线框，但不把新供应商、可写 GUI 功能对外发布。若发现同等级新缺陷进入 ledger，不因“原报告没写”而忽略，也不无限扩大重构。

## 4. 可靠性最小集：为用户体验提供真实语义

### 4.1 外部动作与停止（A07）

在同一个 StateStore 中记录 operation intent、稳定 operation_id、attempt 和结果，不增加第二状态库。复用已核实的 AO 幂等／查询能力；超时不等于外部未执行。先对账，无法唯一确认就标 UNKNOWN 并停止重发；不承诺跨进程严格 exactly-once。

materialization 前，Worker 终止必须有 AO 外部事实确认。kill 返回 false／timeout 时不提交一个仍可能写入的工作树。取消时先持久 cancel request，立即返回接收回执，再等待受控子进程／Worker 停止确认；UI 显示“取消中”，不能提前显示“已停止”。

### 4.2 指令与恢复（A06／A08）

为用户指令记录 received、applied、rejected（以及 unknown），绑定 command_id 和真实消费者。没有消费者的入口禁用并解释；最终 Verifier 的 notes 要进入真正 Mission final 输入。初始 Worker prompt 完整携带路径清单与用户指令。

本版区分三种操作：取消本次执行；恢复非终态崩溃检查点；由终态创建关联的新 attempt。不要提供尚未实现的暂停功能。旧 HUMAN 记录保持原义，新取消状态若需新增必须有 schema 迁移与兼容测试，不把历史 HUMAN 批量重写。

查看历史应走真正只读查询，不构造 Provider、不连接 AO、不初始化新的状态数据。恢复需先验证外部 Git／worktree 材料，缺材料明确报错；不得仅凭 state.db 宣称可恢复。

### 4.3 基线、配置与耗时（A09／A10）

Mission 开始固定 source commit、任务范围、有效配置 revision；Worker 与 integration 使用一致基线。本地 main 与 remote base 不一致时明确选择／拒绝，运行中主分支漂移不得混入交付。

读取配置只通过一个有效配置解析边界；保存后展示实际生效键、来源与消费者。移除重复／未接线的可调表象；Gate timeout/output limit 要真正接线。每次新 Mission 保存无密钥的配置快照。运行中修改默认值只影响新 Mission。

阶段计时分为 preflight、spawn、Worker、观察等待、各 Gate、merge、Verifier、retry；记录 requested model、实际可确认 model、transport、attempt、error category。不能拿一次 418.4 秒和另一次几秒比较后就宣称某模型更快。[S01，第 13—15、23 页]

## 5. GUI 信息架构：从拓扑图中心转为任务中心

### 5.1 四个顶层入口

| 入口 | 主要内容 | 主操作 |
|---|---|---|
| 概览 | 就绪状态、进行中任务、最近结果、需要处理的阻塞 | 新建任务 |
| 任务 | 运行、历史、筛选；任务详情含结果／证据／事件 | 打开详情或创建新 attempt |
| 模型 | 服务连接、已验证能力、角色分配、连接测试、密钥状态 | 添加连接／选择模型 |
| 设置 | 外部工具诊断、默认预算、主题、语言、数据保留与版本 | 保存明确的新默认值 |

项目选择属于新建任务和项目诊断，不再单独占一个底部 Tab；结果和历史属于任务，不另造两套导航。概览的新建按钮是动作，不放在 Tab 中充当页面。此处借鉴 Apple 关于 Tab 用于顶层导航、不要用作动作的原则；四入口划分是 CLAO 自己的设计。[S05]

### 5.2 屏幕与实际用户旅程

**概览。** 大标题“概览”，一张紧凑就绪卡而不是六个彩色 Agent。显示可工作／需要设置／服务不可达；“检查环境”不自动发收费模型请求。已有历史在 AO 未启动时仍可查看。对外依赖给具体操作，不偷偷安装或修改用户全局工具配置。

**独立项目入口（U02 首切片，2026-09-08 已授权实施）。** 目标是用户无需预先使用或配置 AO，能在 CLAO 内打开/创建项目并执行任务；普通本地项目不要求 GitHub/origin。先完成独立项目入口与本地执行，再完成任务旅程。本切片采用本机 Codex 0.150.1 官方 App Server 本地 stdio，仅替换新任务 Worker 的 AO 强制依赖，复用 MissionController/ClosedLoop/StateStore/Gate/Verifier；语义角色保留 Codex CLI。依赖自动准备/安装和发布兼容性仍在 Q01。

**新建任务。** 用四步渐进表单：选择项目 → 目标与验收 → 修改范围与 Gate → 模型／预算确认。选择项目必须显式确认，避免默认首项误操作。高级参数折叠；允许范围为空不得扩成全部。Gate 使用多行编辑或结构化 argv 输入，保留安全解析与原始展示。

最后确认卡明确：“将在项目 X 的提交 Y 创建隔离 Worker；仅可改 A；验收 B；Worker 模型 C、语义复核模型 D；成功不改 main、不 push。”默认一个 Worker；未支持的 Scratch／依赖计划给出不可选原因，而不是提交后才报模糊错误。

**运行详情。** 首屏回答目标、阶段、为什么等待、下一步。用准备／执行／验收／完成的阶段条，但只映射真实状态，不编造百分比或 ETA。分离“模型请求处理中”“网络重试”“等待人工审批”；显示阶段累计时长和取消按钮。技术拓扑移到“高级诊断”，未调用角色显示“未调用”。

**审批卡。** 不用短暂 toast 承载风险决策。显示谁请求、真实目标路径／argv、是否在范围内、一次授权的影响；显式允许一次／拒绝。禁止“全部同意”遮蔽不同请求。被安全规则判拒绝的操作不得经 GUI 普通按钮绕开。

**结果。** 明确分开 Task 完成、集成、Final Gate、Verifier 四级事实。显示 diff、AC 逐项结果、证据是否完整、Git commit 和实际结果位置；提供复制路径、打开目录、导出。失败保留最后有效成果并标“未通过最终验收”，不能标为已验证交付。

**历史。** 搜索和过滤按项目、日期、结果；继续查看旧版本记录。取消／人工处理可以创建关联新 attempt，不能改写旧终态。缺外部 worktree 时显示“原结果位置已失效”，导出包若已保存仍可获取。

**模型。** 先展示服务连接，再按角色分配；不把供应商、模型、登录方式混成一个文本框。明确“Worker 仍使用 Codex”这类混合配置，不能用一个 GLM 图标暗示全部调用已切换。

### 5.3 结果交付的边界

v0.3 必交付“查看／打开／导出”，**不把自动应用／自动 PR 当必须项**。打开目录 API 只接收已存在的 mission_id，经包含性校验后由服务器定位路径，不接受任意系统路径。

导出包包含完整可应用的 patch、基线／结果 commit 标识、文件清单和摘要证据；不得导出密钥、完整 Prompt、AO profile 或 .git。对二进制和新增文件提供明确支持／拒绝；无法生成完整补丁不伪称成功。用隔离 clone 验证补丁可应用、内容匹配、测试通过。linked worktree 不是可移动的独立源码包。[依据 S01 A12；以上是实现要求]

## 6. iPhone 风格的视觉与交互规范

目标是 iPhone 系统应用的**清楚、轻量、层级稳定**，不是 Apple 官网商品广告页。借鉴设计原则，不使用 Apple 标识、不复制系统截图、不捆绑 Apple 字体或图标资源。

### 6.1 本项目设计 token（建议值，不是 Apple 官方强制规范）

| 项目 | 方案 |
|---|---|
| 默认主题 | 跟随系统，浅色优先设计；深色同等验收 |
| 浅色层级 | 页面近白灰 `#F5F5F7`，内容卡白色，弱分隔；文字深灰；单一蓝色强调 |
| 深色层级 | 深背景 + 不同层级实色卡片；失败不能只靠红色 |
| 字体 | 系统字体栈：system-ui、Segoe UI、中文系统字体；不分发字体文件 |
| 字号 | 主标题约 28—32px、正文 15—16px、辅助 13px；不以缩小字号解决拥挤 |
| 间距 | 4／8／12／16／24／32px；卡片内边距 20—24px |
| 圆角 | 卡片约 16—20px、输入／按钮约 10—12px；全产品一致 |
| 触达 | 主要按钮建议至少 44×44 CSS px；这不是把 iOS point 与网页 px 当完全等价 |
| 材质 | 仅导航可用轻半透明；代码、证据、审批和错误用不透明高对比底 |
| 动效 | 约 120—200ms 的轻过渡；尊重 reduced-motion；不循环发光伪造工作 |
| 图标 | 文本标签伴随一致线性图标；使用允许分发的资源并记录来源 |

Apple 的基础指南强调主要内容无需水平滚动、触控目标、对比与清晰组织；本稿把这些原则转成适合 Windows 网页的自主尺寸，而不是移植 iOS 原生控件。[S04]

### 6.2 响应式

宽屏（建议 ≥1024px）：约 216—240px 侧栏 + 单主内容区；任务详情可附可折叠证据侧栏。中屏：导航收敛，表单保持一列或可读双列。窄屏（建议 <720px）：单列卡片、四项底部导航、详情全屏页；代码区域可局部横向滚动，页面本身不横向溢出。

必须验收 1440×900、1366×768、768px 和 390px 宽，以及浏览器 200% 缩放。390px 是响应式测试，不承诺手机能通过网络连接本地 Panel；v0.3 仍绑定 loopback，不增加远程手机控制。

### 6.3 可访问性与文案

键盘可完成新建／取消／查看／切换；焦点可见，弹层关闭后恢复原焦点；状态更新不抢焦点。正常文字对比度目标 4.5:1，图标／大字目标 3:1；作为本项目验收值逐项检测，不以“看起来像 iOS”替代。

日常工作台不提供宣传标语、重复的技术保证或用户状态演示入口。首层以待开始、进行中、需处理、取消中、已取消、已完成等少量状态，配具体原因与动作；断连单独提示，Gate read_error 保留在证据中，底层状态与权限不变。同一原因不在同一页面多处完整重复，协议术语、ID 和长诊断进入高级详情。

面向用户优先中文：“子任务已完成，正在验证整体结果”“取消请求已接收，正在确认 Worker 停止”“复核证据不足，需要处理”。原始状态码、task_id、trace_id 放进详情。永久错误需常驻区域，可复制脱敏诊断，不靠 2.6 秒 toast。

### 6.4 前端工程选择

本版默认沿用本地 HTML/CSS/JavaScript + 原后端，拆出清晰的视图／组件／API／样式文件；无需为美化引入 React、Vue、Electron 或构建服务。确实出现无法维护的组件复杂度时，先给替代方案和迁移测试，再申请设计变更。

浏览器自动化放开发测试环境，不进入产品 runtime 依赖。状态夹具仅用于开发检查，与产品共用组件；正式服务不提供、不加载夹具，开发预览及夹具不进入发布映射。正常空态不补样例。演示视频在产品完成后制作，不能替代真实 Store 数据与可操作页面。

## 7. 多模型接入：明确哪些角色真的切换

### 7.1 v0.3 目标支持矩阵

| 层 | Codex | GLM | Kimi |
|---|---|---|---|
| Planner／Auditor／Mission Verifier | 保留现有 CLI 路径并验收配置 | 目标：一个明确 endpoint／model 的 API profile | 目标：一个明确 endpoint／model 的 API profile |
| Worker | AO Codex 为稳定默认 | AO／harness 兼容性专项；未通过则显示不支持 | AO／harness 兼容性专项；未通过则显示不支持 |
| Observer／Gate | 无模型 | 不适用 | 不适用 |

这是“两个新供应商都在计划内、逐个准入”，不是只做一个空下拉。GLM 与 Kimi 的语义 profile 均应在正式 v0.3 交付前完成验证；若外部权限或协议阻塞，必须由负责人批准缩减并在版本说明里标明，Codex不得自动删掉此目标。

**Worker 非 Codex 选择是有条件扩展。**先核实固定 AO 版本的官方适配能力、独立凭据／进程配置和实际 Session model；不能全局改 AO/Codex 配置影响其它任务。无法证明隔离和工具能力，就不开放该项。不需要为满足一个下拉框自研新的 coding agent。

### 7.2 外部能力证据与不确定性

智谱官方文档展示 `response_format={"type":"json_object"}`、API Key、模型与 messages，并给出应用侧 Schema 校验示例；它不能替代本产品业务语义校验。[S06]

Kimi 官方快速开始目前说明 API Key、模型、base_url 与兼容 API 格式，并把 JSON Mode 列为能力。该信息说明存在接入路径，不证明任意 Kimi 模型、所有参数或 AO harness 都与 Codex 相同。[S07]

模型 ID、endpoint 地域、推理参数和版本可能变化。本稿不把当前营销名称写死为 v0.3 支持承诺。各 adapter 任务开始时核实官方文档，在受控 live 中记录**具体已通过**的 model／endpoint／认证方式。BigModel 国内服务与 Z.AI 不能自动视为同一密钥域；Kimi 各服务域同理。

### 7.3 传输与验证结构

```text
角色输入（既有 TaskSpec／EvidenceBundle／VerifierInput）
→ 无密钥的 EffectiveModelProfile
→ Codex CLI adapter 或供应商 HTTP adapter
→ 严格解析／Schema／ID／AC覆盖／语义一致性
→ 既有角色结果 → Controller
```

角色数量和含义不变。HTTP adapter 只发证据并返回数据，不执行模型返回的工具调用；工具调用请求在语义角色路径中应被拒绝或明确归能力错误。保留现有 Provider 接口，抽取有真实复用价值的请求／错误归一化 helper，不造大型网关框架。

Structured transport 必须区分 JSON_PARSE、SCHEMA、CORRELATION、COHERENCE、AUTH、RATE_LIMIT、NETWORK、TIMEOUT、REFUSAL、TRUNCATED、CAPABILITY、CANCELLED。401／缺权限不循环重试；同供应商暂态重试有总预算；结构化错误允许有限重试，不降低标准。任何跨供应商 fallback 必须有用户数据发送授权，不静默执行。

### 7.4 凭据、费用与数据

浏览器不得直接调用供应商 API。新增凭据通过受保护的本地写接口提交，只存 OS 安全凭据存储或本次内存；配置和 StateStore 只保留 secret reference。开发可使用环境变量引用。不能把 Key 放 localStorage、JSON 配置、日志、Prompt、导出包或 Git。

设置页允许新增／替换／删除凭据，但保存后的 API 不回传明文；只显示 configured/missing。Windows 首期使用一个经过检查的系统凭据 wrapper，不自制加密算法或新密钥服务。多供应商 Key 不传给 AO／Codex 子进程。

第一次选择供应商时说明将发送的代码／证据范围。默认保留 Codex ChatGPT 路径；新 API 服务不假定共用 ChatGPT 额度，价格未知显示 unknown，不编造费用。连接测试分为“不发模型的配置检查”和“用户明确触发的低成本真实请求”，展示发送对象与开销边界。

### 7.5 配置和运行中切换

一个 profile 明确记录 provider、endpoint identity、model、effort（可选）、timeout、重试、credential_ref、能力与验证时间。按角色选择 profile，Worker 配置单独展示。运行中的 Mission 固定配置摘要；编辑默认配置只对新 Mission 生效。

运行中改后端必须先结束或创建新 attempt，并重新确认数据发送；本版不做无提示热切换。回执显示 requested/effective/confirmed model；无法从服务端确认的值标 unknown，不伪装验证。

## 8. 实施里程碑与任务顺序

不在本稿承诺日历工期；以退出门而不是“做满若干天”判完成。预计约 10—14 个可独立评审的纵向 PR，按改动耦合调整，不为凑数量拆文案 PR。

| 里程碑 | 范围／任务组 | 退出门 |
|---|---|---|
| M0 基线与目录整理 | V03-DOC-00、V03-M0-LAYOUT；背景与目录、桌面副本 | DOC-00 产品 blob 不变；目录迁移完整离线／构建验证；OPEN PR |
| M1 修复冻结 | V03-F01—F05 | A01—A05、关键停止／未知动作负例通过；正常默认路径通过 |
| M2 使用契约 | V03-R01—R02 | 有效配置、指令回执、取消／历史、固定基线；API契约可供GUI使用 |
| M3 GUI 体验 | V03-U01—U03 | 四入口；独立项目入口与本地执行后完成任务旅程；结果导出、响应式／可访问性／浏览器测试 |
| M4 模型扩展 | V03-P01—P03 | Codex回归；GLM与Kimi语义profile；凭据、错误、质量、费用边界 |
| M5 发布候选 | V03-Q01 | 独立安装包、依赖准备与干净机器验收；负例／恢复／GUI／受控模型及有限对照评测；来源／校验与发布说明 |

M3 的无副作用布局原型可在 M1 后与 M2 并行，但与后端集成须等契约确认。M4 的官方能力调查可提前，真实模型接线须在 M1／配置快照后；先 GLM 再 Kimi复用薄接口。当前批准执行指针始终只有 PLANS.md 中的一个任务。

### 建议保留的 scope gate

G1：高风险已修；G2：API事实、配置、停止和回执一致；G3：GUI真实可用；G4：两家供应商准入；G5：最终包验收。未通过一项门，不得在 README 把该能力写成完成。

## 9. 验收矩阵与指标

保留 v0.2 438 项作为历史基线，不把测试数作为目标；适当增加、重构或退休测试需给出理由，不能删失败测试制造通过。[S01，第 22 页]

| 类别 | 必测场景 |
|---|---|
| 判定 | 全绿；Gate红；顶层PASS与AC/反作弊FAIL；缺失/重复/未知AC；错误ID；截断证据 |
| 授权 | 越界／符号链接／junction；rename old/new；伪产物源码；换行／短前缀／任意模块 |
| API／GUI | Host/Origin/nonce、Content-Type、穿越、引号、断连、DB错误、双击提交与回执 |
| 外部动作 | spawn可能成功但客户端超时；send后中断；kill未确认；重复request；恢复后不盲目重发 |
| 生命周期 | 取消Worker/审计/Gate；非终态崩溃恢复；终态只读；缺材料；关联新attempt |
| 模型 | 每家合法/非法JSON、Schema、拒绝、429、401、超时、截断；实际role配置与数据发送 |
| 结果 | 导出patch可独立应用；源main/origin不变；结果失效可解释；旧记录字段缺失不伪补 |
| 发布 | 独立安装包、依赖准备、自测、link/hash/hygiene；两套干净Windows环境；人工GUI；源码 ZIP 不等于独立产品 |

负例集中的假成功、越界自动批准、无回执副作用必须为 0。UI 控制请求本地 ACK 建议 p95 <1s、事件可见建议 p95 <2s；这不承诺外部 AO／模型终止同步完成。阶段耗时、失败率、配置和费用未知项需如实显示。

Q01 增加有限的同任务对照与角色消融，预先明确次数、时长和费用预算后执行。固定任务、base、Gate、范围与成功标准，比较完成质量、人工介入、耗时和用量；成功与失败耗时分开，未知用量保持 unknown，不以 Agent 数量证明优势。供应商速度改善属于待测结果，不预设结论。独立安装包、依赖准备、干净机器首次任务也是 Q01 退出门；现有源码 ZIP 不等于独立产品。

## 10. 项目背景文件：谁决定，哪里查询

### 10.1 单一事实分工

| 文件 | 只负责什么 | 谁可更新 |
|---|---|---|
| AGENTS.md | 长期实施规则、安全边界、验证／Git纪律 | 规划助手起草；负责人批准；Codex只能在获准任务中调整 |
| docs/PROJECT.md | 当前已实现架构、版本、已知缺口；不混写目标 | Codex按已合入实现和证据更新，经审核 |
| PLANS.md | 当前阶段、唯一任务指针、最近证据、下一步 | Codex据真实进度维护；负责人决定切阶段 |
| docs/V03_PLAN.md | 目标、设计、范围、退出门、决策记录 | 规划助手／负责人批准修订；Codex只能提案 |
| docs/V03_BACKLOG.md | 稳定任务ID、依赖、状态、验证证据 | Codex更新事实；改范围须批准 |
| 根 README.md | 稳定版下载、开发入口、v0.3正在开发的声明 | 随里程碑更新，不抢先承诺能力 |

`docs/PROJECT.md` 使用大写精确路径；不要新建第二份 `project.md`。`runtime/<id>/project.md` 是程序投影，绝不是开发项目背景文档。Word/PDF 快照只供阅读，未来查进度读取 GitHub Markdown，而不是依赖聊天记忆。[S03][S08]

### 10.2 历史保存

新的 PROJECT/PLANS 可以变短，不再附带全部 R0—R5 日志。原始完整文件继续由冻结 `v0.2` tag 和固定提交链接保存；新文件提供入口。不得重写旧证据为全问题清零。旧源码保留但不进入产品包；原规划入库没有整理旧仓库。负责人于 2026-09-06 追加授权 M0 目录迁移和本机副本整理，发布 tag 仍冻结。

### 10.3 责任与工作流

规划审计助手：制定目标、设计、优先级与验收，审查真实 diff 和证据；发现先前假设错误要修正规划。

项目负责人：确认需求／取舍、授权真实模型花费与高风险动作、批准范围变化和发布；可以亲自上传本次已写好的背景文件。

Codex：在授权任务范围内自主做代码细节、测试、诊断和文档事实更新；源码与测试证明规划不成立时先报告可选修正，不照着错误假设硬实现。不需要为普通低风险实现选择每一步请示。

这种分工不依赖谁点击上传。用户手动入库不意味着跳过分支／PR；Codex搬运文件也不等于让它重新决定架构。

### 10.4 Codex 下一步任务模板

```text
Goal: 关闭 V03-<ID>，只做该任务可验收的最小切片。
Context: 当前 main SHA；AGENTS、PROJECT、PLANS当前指针；V03_PLAN对应节；V03_BACKLOG该卡；原报告A编号。
Constraints: 允许/禁止文件与行为；不动v0.2；不换模型/框架除非该卡授权；本轮是否允许live及费用上限。
Done when: 原负例红/修复后绿；正向回归；需否Windows/浏览器/live；更新同一卡证据并开PR。
Stop when: 数据/权限风险；未知AO协议；范围矛盾；预算/网络重试上限；不能定位的外部结果。
Report: commit、changed files、测试命令/环境/结果、实际证据、剩余风险；不复述整篇计划。
```

OpenAI 建议把长期规则放 AGENTS.md，单次任务明确目标、上下文、约束和完成条件；本项目在此基础上加入停止条件与证据要求。不要每轮重新发送整个计划，也不要让 Agent 自动读全部历史日志。[S08]

## 11. 已批准基线与 M0 整理

V03-DOC-00 已核对 main `3a9ea27468915eb9571611bcca10962e7a732fb0` 的 7 项规划／治理文件与审计附件；产品 106 个 blob、manifest 和 builder 相对发布源码均未改变。`DOC00_BASELINE_PASS`；当前 Markdown 本地链接有效。规划由负责人明确批准，文档入库事实由 Git 历史证明，不虚构已合入的文档 PR。

当前目录语义为：`clao/` 唯一产品；`packaging/` 发布工具；`legacy/` 历史 snapshot；`docs/` 当前事实和规划，`docs/reference/` 冻结审计附件。内部 `loopcore` 包保持原名。

负责人追加授权同一 M0 中完成 repository layout consolidation 与本机历史副本整理，允许必要路径适配并要求完整离线测试和 clean HEAD release builder 验证；不改变 runtime、不改 v0.2 tag／Release。M0 结束后的下一任务仍是 **V03-F01 — 完整契约与终局一致性**，保持 TODO，须另行收到实施指令。

## 12. 决策记录与变更规则

| 决策ID | 本稿决策 | 依据 |
|---|---|---|
| D01 | 修复优先，保留架构 | 原报告总评、A01—A05；用户本轮确认方向 |
| D02 | 四入口、iPhone风格层级、桌面适配 | 用户偏好 + Apple导航原则；本稿具体化 |
| D03 | GLM和Kimi语义角色均为目标，逐个准入 | 用户需求；原报告分层方案扩展为两家顺序接入 |
| D04 | Worker切换独立且有条件，不伪支持 | 原报告第17—18页；AO能力仍需核实 |
| D05 | 查看／导出优先，默认不自动应用push | 原报告A12与SCM边界 |
| D06 | Markdown主文档，Word只作快照 | 动态查询与避免多份状态分叉 |
| D07 | 用户手动入库方案；Codex不自主改scope | 用户工作方式；可审计PR纪律 |
| D08 | 独立双任务有界；未验证依赖计划拒绝 | A09待验证风险；避免阻塞UX主线 |
| D09 | 2026-09-06：批准规划生效；M0 增补目录迁移与本机副本整理 | 负责人明确任务；仅结构与路径适配，完整离线测试／builder 验收，不实施 F01 |
| D10 | 2026-09-07：U01 收敛为日常工作台，开发夹具退出产品；U02 先独立项目/本地执行，再完整旅程；Q01 独立安装与有限对照/角色消融 | 负责人 PR #39 返修授权；2026-09-08 U02 首切片进一步授权采用本机 Codex 0.150.1 App Server stdio 执行 Worker，历史 AO 显式兼容；不要求普通本地项目具有 GitHub/origin；历史 M0/M1/M2 完成状态不变；首切片等待代码审计/真实运行后续验收，不等于 U02 整卡或独立安装完成 |

批准后改变以上决策时，追加日期、原因、影响、验收变化和负责人确认；不要静默删目标或把“规划”改成“已完成”。本稿签署状态由用户入库/批准决定，生成文件本身不构成批准记录。

## 13. 来源与可查询证据

以下外部资料只用于规划可行性与设计原则，不替代项目实测。检索日：2026-09-06。

- **S01 原审计（主要依据）**：[CLAO v0.2 全面架构审计与 v0.3 产品规划，2026-09-05](reference/CLAO_v0.2_audit_20260905.pdf)。缺陷第9—15页；GUI第16、19页；模型第17—18页；排期/测试第20—24页；证据等级第2、25—26页。原文件随文档包原样保留。
- **S02 发布与源码基线**：[v0.2 Release](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/releases/tag/v0.2)；[固定提交](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/commit/4d3e8e6b5e70bab868b2eef0d28c7742dea044ba)。本次只核对背景文件与main，不重新证明历史live。
- **S03 旧治理文件**：[原 AGENTS](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/blob/4d3e8e6b5e70bab868b2eef0d28c7742dea044ba/AGENTS.md)、[原 PROJECT](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/blob/4d3e8e6b5e70bab868b2eef0d28c7742dea044ba/docs/PROJECT.md)、[原 PLANS](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/blob/4d3e8e6b5e70bab868b2eef0d28c7742dea044ba/PLANS.md)。历史完整保存在此，不覆盖发布tag。
- **S04 Apple 基础设计原则**：[UI Design Dos and Don’ts](https://developer.apple.com/design/tips/)。清晰内容、对比和触达原则；本稿token和Web尺寸是自主设计。
- **S05 Apple 导航原则**：[标签页栏](https://developer.apple.com/cn/design/human-interface-guidelines/tab-bars)。Tab用于顶层导航，不承载执行动作。
- **S06 智谱官方结构化输出**：[结构化输出](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output)。JSON模式、参数及应用侧Schema校验；不是本产品兼容验收。
- **S07 Kimi 官方接入**：[快速开始](https://platform.kimi.com/docs/get-api-key)。原Moonshot入口重定向到该页；模型与参数需在实施日复核，不照抄“最新”模型为固定支持承诺。
- **S08 OpenAI Codex工作方式**：[Best practices](https://developers.openai.com/codex/learn/best-practices/)、[AGENTS.md](https://developers.openai.com/codex/guides/agents-md/)。本稿只借鉴持续上下文与任务结构，不改变产品runtime。
- **S09 队友候选补丁（待评审输入）**：[固定候选修改说明](https://github.com/liuxinyue743-wq/agent-orchestrator-AI-worker/blob/7b30184ff19922dd6af03c874ac2ba9c6c5dd77e/v0.2.1beta/docs/PATCH_NOTES_0.2.1-rc1.md)。来自上一轮仓库对比；本稿不声称它已合入主线或通过Windows live。
