# CLAO（v0.3 开发版；已发布版本仍为 v0.2）

Closed-Loop Agent Orchestrator

> 本目录保留旧产品及可复用核心。[AO 原生底座 + 单 Worker 验收闭环基础集成](../ao/CLAO.md) 已经 PR #46 返修外部代码审计 PASS 并合入（DONE）；整体迁移与 M4 仍 IN_PROGRESS，当前执行内容为 Planner/Auditor 决策与独立角色配置迁移（IN_REVIEW）。开发入口不启动本 Panel/Controller。以下旧产品功能与历史完成状态不等于已迁移；配置、凭据和 runtime 原样保留，新数据不写入旧数据库。正式默认入口未切换；空账户隔离启动命令与未迁移边界见上述说明，真实账户/模型及完整体验尚未验收。

CLAO 是本地闭环软件开发控制层。新本地任务通过 Codex App Server 执行，无需 AO。它把用户的
Mission 交给受控的 Codex Worker，在确定性观察、Gate 和最终验证后生成可审计结果。
当前架构见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 系统要求

- Windows；
- CPython 3.12.x；
- Git；
- Codex CLI **0.150.1**，已通过官方 `codex login` 使用 ChatGPT 登录；
- Codex Windows 沙箱已在官方 Codex 中设置就绪。版本/登录/沙箱不满足时明确拒绝启动，不自动升级或登录。

CLAO 不安装或启动 Git、AO Desktop、Codex CLI，也不读取 API Key 作为默认认证方式。

## 本地项目与来源确认

在“新建任务”中输入本机目录完整路径，选择“打开目录”或“创建空项目”。项目登记保存在
`runtime/projects.json`，重启后仍可选择；无需 origin、GitHub、AO 配置或 daemon。
Git 仓库须选择根目录，普通非 Git 目录和空目录均可使用。

启动前读取文件清单并确认：采用**当前磁盘内容**（包括未提交修改），不会只用旧 HEAD。
Git 项目遵循已跟踪文件及未被 ignore 的未跟踪文件；默认排除凭据文件、链接/junction、
运行缓存、`.git` / `.ao` / `.codex`、虚拟环境、node_modules、vendor、build、dist 等目录。
链接/junction 遇到时拒绝导入；不扫描项目外内容。`.env.example` 等模板、
`data.pyconfig`、`.coverage_policy.py` 正常保留。摘要可查看实际排除项。
单文件上限 10 MiB、总计 100 MiB / 10000 文件；超过时拒绝，不静默截断。这里是有限的
文件名/目录规则，不是万能密钥扫描器；用户仍应核对清单，移出其它含密钥材料。

确认后在 `runtime/<mission-id>/source` 建立私有 Git 快照，以冻结 commit 创建 detached
Worker 工作树；原项目的内容、index、分支和 ignore 配置不变。读取时发现内容变化要求
重新确认；不承诺正在被其它程序修改的文件系统具有跨文件原子快照。
默认配置、来源 revision、后端和协议版本随 Mission 冻结，恢复不能切换后端。
私有 Git 不运行来源附带的 hooks 或继承的内容过滤器；不会修改用户全局配置。
若当前进程设置了 `GIT_CONFIG_COUNT/PARAMETERS`，导入会明确拒绝，需在没有这类覆盖的环境中启动 CLAO。

旧 AO 任务仍可历史只读查看；显式 `execution_backend: "ao"` 的旧 CLI 执行路径保留
AO Desktop 0.12.9、注册 Git Project、origin/base 一致性要求。缺省后端的旧 Mission JSON
按 AO 兼容解释，不能将其静默恢复成本地任务。

## 安装与启动

最简单的方式是双击 `启动CLAO.bat`。启动器会在需要时调用 `bootstrap.ps1` 创建本
目录的 `.venv`、安装 `requirements.txt` 中锁定的依赖，然后在浏览器中打开 Panel：

```text
http://127.0.0.1:7100/
```

也可以手动 bootstrap：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

bootstrap 只管理本目录的 Python 环境，不连接 AO，也不调用模型。

## 使用 Panel

1. 双击 `启动CLAO.bat`；
2. 在概览点击“检查环境”：显示 Git、Codex 版本、已有登录及沙箱的真实检查结果；不调用模型。未就绪仍可编辑草稿、浏览历史；处理具体原因后可重新检查，启动时仍核对一次；
3. 选择“新建任务”，打开本地目录或创建空项目，查看当前内容与排除项；填写目标、验收条件、允许/禁止路径和多条 Gate 命令，空范围或空 Gate 不会自动补值；
4. 第四步核对实际项目/来源，直接调整本次 Worker/语义角色模型、任务/运行预算、修正次数及 Gate 超时/输出限制，然后确认启动；默认单 Worker，2 仅表示两个独立子任务；
5. 任务详情显示准备/执行、等待原因与处理入口；可查看已有文件差异、允许一次/拒绝、按真实问题回答或补充指令。失效请求不能继续提交，取消接收不等于已停止；
6. 查看 Mission 最终结论、Gate / Verifier 摘要与 `integration` 位置。Worker 回合完成本身不是成功；失败产物标明未验收，失效目录明确提示；
7. 在任务列表按目标搜索或项目/状态筛选，点击即可只读查看；运行 A 时查看 B 不影响 A。符合既有条件的非终态可“检查并恢复”；终态“重新执行”重新确认目标任务自己的来源并创建关联记录。

本地任务不读取 AO 项目或 runfile，不调用 AO REST/CLI；不能用未知停止事实继续交付。
“允许一次”不能覆盖任务禁止路径、工作区边界、Git 控制文件或危险操作限制。
回答写入与请求关闭不等于引擎已采纳；无法确认时显示“采纳未知”，不重复发送。
已关闭响应之后的执行和验收仍依据各自事实继续；未知 spawn/send/停止结果仍阻断依赖流程。
对历史任务“重新执行”会显示该任务自己的项目与后端，重新确认当前来源，再建立关联的新记录。
“设置”保存新任务默认参数；已打开的任务草稿保持其配置，确认页使用的快照随本次 Mission 冻结。
运行中修改默认值不会改变该任务；成功启动后再次新建才采用新默认值。原始事实位于高级详情。
刷新保留所查看的任务；断连保留最后记录，重连不自动重发启动、回答、审批或取消。
停止未知时保留诊断并阻断新任务，不能通过查看历史或重新执行绕过停止确认。

## 任务工作台（v0.3 U01）

U01 的 PR #39 已通过本轮外部代码与产品整改审计并 rebase 合入 main（DONE），尚未发布到 v0.2。
已有 Windows/浏览器验证与 Codex 截图自查沿用，不将其表述为外部逐张截图验收。
概览、任务、模型、设置四个入口共用桌面侧栏与窄屏底部导航。主题支持浅色、深色和
跟随系统，刷新后保留。新建任务为四步弹层，前进、返回、编辑与关闭后重开均保留草稿；
只有现有 API 确认成功才提示已启动。取消请求接收与 Worker 停止未知仍明确区分。
概览就绪检查复用后端启动检查；source 核对仍在启动边界进行，不把项目列表可读解释成全面就绪。

正常启动只读取真实任务；没有记录时显示空态。旧 `preview` 参数不改变数据来源，
正式服务不提供样例资源。主层使用少量中文状态，断连单独提示，Gate 读取失败在证据卡
中保留；原始状态和完整诊断可展开查看。“重新执行”会创建关联的新执行记录，不重跑旧终态。
U02 首切片已接入本地项目与真实 App Server 生产适配；[PR #40](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/40) 再次外部审计 PASS、已 rebase 合入（首切片 DONE）。“完整任务旅程与 GUI 数据接线”的 [PR #41](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/41) 代码与返修再次外部审计 PASS、已 rebase 合入；本切片及 U02 整卡 DONE；V03-U03 — 结果中心与独立导出的 [PR #42](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/42) 再次外部审计 PASS 并已 rebase 合入（DONE）。M0/M1/M2 保持 COMPLETE，M3 COMPLETE 表示阶段开发和代码审计完成；M4 IN_PROGRESS；P01 工程与离线验证切片的 [PR #43](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/43) 再次外部审计 PASS、已 rebase 合入（切片 DONE）；P02 工程接入与离线验证切片的 [PR #44](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/44) 工程审计 PASS、已 rebase 合入（DONE）；P01/P02 整卡及 M4 保持 IN_PROGRESS。两家联合真实服务/角色准入及质量、延迟、用量评测继续暂缓，仍需负责人另行确认权限、材料与预算；当前原生迁移下一指针见本文开头，不开始 P03。运行证据仍为协议替身/离线集成、Windows/浏览器定向验证及 Codex 截图自查；外部代码与返修审计不代表负责人已完成完整 GUI 体验验收。U02 的 200% 检查为等效布局/CSS zoom，非原生浏览器缩放验收。真实 Codex 模型任务、全量与安装/发布验证仍 NOT_RUN；任意进程重连、模型扩展与 Q01 安装/发布兼容性未完成；U03 结果中心/固定版本补丁包及历史下载已合入，文件类型支持不变；包不含完整基线/项目依赖，敏感检测仅为有限规则。M3 COMPLETE 不代表完整 GUI 体验或发布验收完成；闭环运行视图仍仅为未授权候选。

视觉参考：[Framework7 分组列表](https://framework7.io/docs/list-view)、
[Konsta iOS 列表](https://konstaui.com/react/list)；没有引入这些框架。
图标采用 [Lucide](https://lucide.dev/) 的 12 个本地 SVG 符号，固定上游提交
`3859eb20fabe7fd95652fcd4395843b6c0bcdd01`，完整 [ISC / Feather MIT 许可](panel/icons-LICENSE.txt)
随资源提供，来源见[官方许可](https://lucide.dev/license)。不使用 Emoji、远程字体或 Apple 素材。

## 使用 CLI

准备 Mission JSON（唯一 `mission_id`、objective、acceptance_criteria、allowed_paths、
forbidden_paths、gate_commands，格式可参考 `tasks/mission-quick.json`），先只读预览本地来源：

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
.\.venv\Scripts\python.exe .\run_mission.py .\my-mission.json --project-path "E:\Projects\我的项目"
```

检查输出的文件与排除项后，以该摘要的完整 revision 启动（会调用已登录 Codex 模型）：

```powershell
.\.venv\Scripts\python.exe .\run_mission.py .\my-mission.json `
  --project-path "E:\Projects\我的项目" --confirm-source "摘要中的完整revision"
```

`--project-path` 使用本地后端并替换模板的 project_id；首次预览不启动 Worker。
没有此参数、也没有显式本地后端的旧模板继续走 AO 兼容路径，此时
`REPLACE_WITH_AO_PROJECT_ID` 才需要真实 AO Project ID。新 Mission 必须使用新 identity。

仅查看确定性单任务计划可使用：

```powershell
.\.venv\Scripts\python.exe .\run_mission.py .\tasks\e2e-smoke.json --dry-run
```

当 `max_subtasks=1` 时，dry-run 不连接 AO、不调用 Codex 模型，也不创建 runtime。

## 新任务默认设置与本次配置（v0.3 R01 已合入）

Panel 的设置保存到本产品目录的 `config/default.yaml`，重启后仍在。CLI 与 Panel
使用同一解析入口：内置缺省值 < 此文件 < 新 Mission 的显式输入（CLI 轮询/cap
参数、Mission budgets）。保存整份校验后原子替换，失败不部分应用。秒数范围为
`0 < value <= 604800`，允许小数；计数必须是整数（上限 1000000），具体最小值和
消费者在页面配置详情中列出，`max_subtasks` 仅允许 1 或 2。

当前默认模型继续为 `gpt-5.6-sol`。Worker 使用 `worker.model`，Codex 语义角色使用
`roles.planner/auditor/verifier.model` 和各自 `timeout_seconds`；重复的旧
`roles.worker.model` 会迁移，同层值冲突则拒绝。没有消费者的旧选项会显示弃用/
未生效；不支持的键、取样参数、密钥或环境变量配置不会作为有效值保存。

新 Mission 在 StateStore 中固定有效值、来源和内容哈希 revision。修改默认值只影响
之后的新 Mission，续跑使用已有快照；历史缺快照可查看，但不能自动用最新默认值
猜测历史参数后执行。默认 CLI/Panel 轮询均为 5 秒、runner cap 均为 7200 秒；
cap 是 runner 的循环边界检查，不是抢占中断或确认所有 Worker 已停止。

`gate.timeout_seconds` 限制 Task/baseline/Final Gate 的每条命令；
`gate.output_limit_chars` 分别限制每条命令 stdout/stderr 的持久化和后续证据正文，
截断标记另计。原长度、SHA-256 和超时类别可查询；失败编号在截断前提取。
进程输出仍捕获在内存中，这不是进程内存上限。截断片段无法通过
F01 的完整证据校验，不能因此假装 Gate 或 Verifier 已通过。

页面显示准备、实际执行后端调用、观察/审批等待、语义角色、各 Gate、materialization/merge
和重试等真实阶段。独立模型请求记录开始/结束、attempt、耗时和错误类别；未调用、
历史 unknown、未知模型/用量/费用分开表达。Worker 的配置请求/传入值、AO Session 创建时
resolved model、conversation 后续 reroute 各自显示来源；缺字段不从配置猜测，也不把
Session 或 reroute 事实当成单次 provider 请求模型/精确耗时。本地 Worker 单列
`thread/start` 返回的 model（线程配置确认，非单次 provider 请求证据）；未知用量/费用仍为 unknown。SSE 断连保留最后状态，重连以顺序化
完整快照替换，不重放写请求。HTTP 处理耗时和状态快照耗时不等于模型调用耗时。

## 指令、取消与恢复（v0.3 R02 已审计 PASS 并合入）

指令发送成功表示 receipt 已持久接收；页面显示 received/applied/rejected/unknown，
以及实际消费者、时间与原因。Worker applied 仅表示相应执行后端确认接受消息；Planner 镜像单列，
不代表 Auditor/Verifier/Worker 主目标已消费。Observer/Gate 是确定性程序，不能接受
语义指令。Final Verifier 实际读取面向 verifier 的 notes；同 command 重试不重复发送。

“取消本次执行”先接收请求，再确认当前本地 Codex/Gate 子进程与对应后端 Worker 停止；
requested/cancelling 不等于 cancelled，unknown 表示需人工核对。未知停止不继续交付。
历史查看不连接 AO、也不修改原库；非终态“检查并恢复”必须验证原配置/source、当前
所需 Git/workspace/Session/operation/证据。缺材料不自动补造；终态只可创建有关联的新
attempt，具有独立 identity/config/source/历史，原记录不变。旧停止未知时也不能开替代 attempt。

旧 AO 后端的每次新 Mission 要求来源分支的 local/origin tracking/真实 remote commit 一致，
用只读查询冻结 exact source；需要访问已配置 origin。CLAO 不代为 fetch 或同步分支。
后续来源漂移会阻断新 Worker spawn，integration 保持原 source。缺少 Worker 创建基线
证据时交人工；AO 当前没有 exact-commit spawn 参数，source 检查与 AO 创建不是原子事务，
不匹配继续 fail closed，不宣称 exactly-once。最多两个独立子任务保持可用；本版明确拒绝
有 dependencies 的计划，避免下游 Worker 在没有上游代码的基线上执行。

本地后端使用 `turn/interrupt` 请求取消，以关联的回合结束通知且没有仍在进行的命令/文件
item 确认停止；interrupt 返回空对象不等于已停。spawn、send、审批 intent/ACK 留在原
StateStore；缺少唯一确认不盲重发。进程重启时活跃/等待审批/断连 Worker 保留 UNKNOWN，
不能自动重新发起回合；已结束回合的完整检查点按既有恢复规则检查。历史仍只读，
“重新执行”要求旧停止已确认，并重新确认当前目录内容。暂不实现 App Server 任意进程重连、
背景命令重接管、MCP/第三方工具授权或 API Key 登录管理，不承诺 exactly-once。

## 结果与 SCM 边界

每个 Mission 的状态和证据位于：

```text
runtime/<mission-id>/
```

`MISSION_DONE` 表示 integration 结果已经通过 Final Gate 和 Mission Verifier。结果保留
在 `runtime/<mission-id>/integration`，不会自动修改目标 repository 的 `main` 或
`master`，也不会自动 push `origin`。将结果交付到目标主分支始终需要用户显式操作。

### 结果中心与独立补丁包（v0.3 U03）

任务详情的“结果与验收”列出净变化、可展开差异、逐项 AC、各阶段 Gate 与最终 Verifier。
读取失败、缺少历史字段、未生成及未通过分别显示；不会从 Mission 成功反推 AC 或 Gate。
“复制结果路径”“打开结果目录”只定位所选任务；Windows 仅确认已接收打开请求，
剪贴板/打开失败会保留错误。运行 A 时查看、导出历史 B 不替换 A 的运行句柄。

点击“生成结果包”，保存成功后点击“下载结果包”。统一 ZIP 包含：

- `changes.patch`：冻结 `source_commit` 到已记录 `integration_head` 的完整净变化；
- `manifest.json`：基线/结果标识、变更类型、相对文件路径、大小、SHA-256 和 Git 模式；
- `evidence.json`：Mission、AC、Gate、Verifier 的必要摘要，排除原始 Prompt、对话、输出日志、配置和环境；
- `README.md`：验收状态、匹配基线和独立应用方法。

在**匹配 baseline_files 内容的独立目录副本**中，用 Git 应用解压后的补丁：

```powershell
git -c core.autocrlf=false apply --check ../result-package/changes.patch
git -c core.autocrlf=false apply --whitespace=nowarn ../result-package/changes.patch
```

应用后逐文件核对 `result_files` 的内容哈希、删除路径与所需验收。空补丁会明确标记
`no_changes=true`，跳过应用命令。普通目录不必初始化 Git，也不需要原仓库拥有 CLAO
私有 commit；非空基线的未修改源码须保留自己的副本，包不是完整源码或可执行应用。
完整命令与说明见包内 README 和 [Git 官方 apply 文档](https://git-scm.com/docs/git-apply)。

支持 UTF-8 普通文件、新增/修改/删除/重命名/复制、中文和空格路径，保留 100644/100755
模式；Windows 不把 Unix executable bit 等同本机执行权限。当前明确拒绝二进制、非 UTF-8、
Git LFS 指针变化、链接/子模块以及 Windows 不可表示的路径。沿用来源/artifact 规则；
若净变化含被排除材料，或完整旧/新内容（含删除行与上下文）、摘要中检出私钥、已知凭据形态、
授权头、具名凭据的非空引号字面值或明确的完整 Prompt 材料标记，则拒绝整个代码包，
不静默过滤或改写补丁。精确的 `${API_KEY}` 环境变量占位、凭据读取/函数调用与普通
`tool --prompt hello` 使用说明不会仅因变量或参数名被拒绝；引用中另含明确凭据仍会拦截。
此检查不是通用秘密扫描器，不把无特征的标识符或任意表达式猜测成已确定泄露的密钥。
限制为每文件 10 MiB、每版本 100 MiB/10000 文件；页面只显示前 24000 字节并说明截断，
下载补丁不截断。

包按固定内容与证据标识去重，原子保存后才在原 StateStore 记录；生成失败不覆盖既有有效包。
之后原目录或 Git 对象失效，已记录包仍可下载，匹配的包也可继续提供只读差异。
历史缺少 source/head 时不能用当前 HEAD 补建代码包；已有可确定成果即使失败、取消或停止
未知，也只读取固定对象并标明未通过验收，不提交/整理仍活动的 Worker。
新旧后端的结果读取无需 AO 或模型在线；不自动应用、commit、push 或改写用户原项目。

## 故障排查

- **本地后端准备失败**：按页面提示检查 Codex 0.150.1、ChatGPT 登录和 Windows 沙箱；不需要 AO。
- **AO unavailable（仅旧 AO 后端）**：启动 AO Desktop，确认默认 `~/.ao/running.json` 可用；若 `ao`
  不在 PATH，可为当前进程设置 `CLAO_AO_BIN`。
- **Codex login**：运行 `codex login status`，确认显示 ChatGPT 登录。
- **origin/default branch（仅旧 AO 后端）**：确认 Project 有 `origin`，运行
  `git rev-parse refs/remotes/origin/<branch>`；auto 模式还需确认
  `git symbolic-ref refs/remotes/origin/HEAD`。
- **spawn failure**：Panel/StateStore 会显示经过脱敏且有长度上限的根因摘要；凭据、
  prompt 和用户主目录不会写入该摘要。

## 本地自检

```powershell
$env:PATH = "$(Resolve-Path '.\.venv\Scripts');$env:PATH"
$env:PYTHONPATH = (Resolve-Path ".\src").Path
.\.venv\Scripts\python.exe -m pytest .\tests -q
.\.venv\Scripts\python.exe -m compileall -q .\src .\panel .\run_mission.py
```

U01 浏览器检查仅在源码仓库运行，开发预览和夹具位于发布映射之外的 `dev/panel/`。
定向检查使用本机 Edge 和开发环境的 Node/Playwright。设置 `U01_NODE`
为开发 Node 可执行文件、`NODE_PATH` 指向含 Playwright 的开发依赖目录，然后运行
`python -m pytest tests/test_u01_panel.py -q -s`。未提供开发 Node 时明确 SKIP；缺少
Playwright 时不能视作浏览器通过。`U01_SCREENSHOTS` 可指定截图输出目录，默认在隔离
测试临时目录。200% 检查使用临时隔离浏览器扩展设置真实 browser zoom，结束后清理，
不安装到用户浏览器；产品运行不依赖 Node、Playwright 或该测试扩展。

## GLM 语义角色配置（P01 工程切片）

Worker 仍使用本地 Codex App Server。Planner（分解和异常规划）、Auditor、Mission Verifier
各自选择 Codex CLI、BigModel 通用或 Kimi 国内通用 Chat Completions；Observer/Gate 不使用模型。
默认全为 Codex，不需要外部 Key。P01/P02 工程接入与离线验证切片均已审计合入（DONE）。两家真实服务/角色准入及切换质量、延迟、用量评测继续暂缓，等待负责人另行确认权限、材料与次数/时长/费用预算；P01/P02 整卡及 M4 保持 IN_PROGRESS。配置保存、离线验证和代码审计均不等于真实请求或全部角色准入通过。

1. 在“模型”页选择服务、添加连接，填写连接名称和凭据引用。工程目标仅支持
   BigModel `https://open.bigmodel.cn/api/paas/v4/chat/completions` / `glm-4.7`，
   Kimi 国内 `https://api.moonshot.cn/v1/chat/completions` / `kimi-k3`。
   不支持国际域、第三方中转、Coding 套餐或自定义域，不跨域试 Key。
2. 在“凭据”区选择对应服务并填写相同引用，保存/替换测试或已获授权的 Key。使用当前 Windows 用户的系统凭据存储，
   不回显 Key；不可用时明确失败，不写明文备用文件。同名引用按服务隔离，删除只影响该服务/引用。
   旧 GLM 存储位置不变、不自动迁移；编辑或删除连接配置不自动删除凭据。
3. 分别保存三个语义角色的默认连接；新任务确认页仍可单独选择。本次任务固定参数和引用；
   修改默认值只影响之后创建的任务。Key 值不进入快照；替换/删除同一引用会影响后续读取该凭据的调用。
4. 使用外部角色的任务启动前，确认页逐项列出角色与服务；一次确认覆盖列出的 BigModel / Kimi 组合。
   所选角色的目标、规划上下文、代码差异、Gate/验收证据可能外发并计费。
   新任务须重新确认；项目、外发角色或连接变化使旧确认失效，同一未提交草稿普通切页/关闭重开/SSE 保留。
   重新执行使用重新确认的默认快照和许可；恢复沿用原快照/许可，旧 GLM 许可不能授权 Kimi。
   保存/读取配置及凭据状态只进行本地检查，不发模型请求。当前没有额外真实连接测试按钮。

配置使用既有 `config/default.yaml`：`model_profiles` 是无密钥连接列表，
`roles.planner/auditor/verifier.profile` 引用连接名称，`codex` 为原 CLI。
原 `roles.<role>.model/timeout_seconds` 仅在该角色选择 Codex 时消费；GLM/Kimi 使用连接内的值。
省略新键的旧配置仍默认 Codex；v1 历史快照原样校验/保留，新任务用 v2 快照固定连接。
`roles.worker.model` 旧别名仍迁移到 `worker.model`，重复冲突仍明确拒绝。

| 连接键 | 当前边界与消费者 |
|---|---|
| `id` / `credential_ref` | 小写字母开头，后接小写字母/数字/下划线/连字符，总长 1–48；最多 12 个连接 |
| `service` / `endpoint` / `model` | `bigmodel_general` / GLM 固定地址 / `glm-4.7`；或 `moonshot_cn` / Kimi 固定地址 / `kimi-k3` |
| `timeout_seconds` | 每次 HTTP 调用 (0, 600] 秒，保留小数 |
| `max_attempts` | 一次角色调用含首次共 1–3 次；HTTP 与本地 JSON/Schema/关联校验共用预算 |
| `retry_delay_seconds` | 重试等待 [0, 30] 秒，支持小数、可取消 |
| `max_tokens`（GLM） | 整数 1–131072；达到输出上限记 TRUNCATED，不用片段作完整证据 |
| `temperature`（GLM） | [0, 1]，最多两位小数 |
| `thinking`（GLM） | `enabled` / `disabled`；不透传 Codex reasoning effort |
| `reasoning_effort`（Kimi） | `low` / `high` / `max`，页面初值 max；K3 始终思考，不支持 thinking 开关 |
| `max_completion_tokens`（Kimi） | 整数 1–1048576，包含思考与正文；页面初值 8192；不使用已弃用 max_tokens |

Kimi K3 的采样由服务固定（temperature=1.0、top_p=0.95、n=1、presence/frequency penalty=0），
请求省略这些参数，配置不提供伪可调入口；GLM 参数保持原值，不互相透传。
两家均非流式 `response_format: {"type":"json_object"}`，system 消息提供现有 JSON Schema，随后仍作完整本地校验。
保留原完整证据上限（角色 prompt 64000 字符、HTTP 回复 2 MiB）；超限明确拒绝/标 TRUNCATED，
较大的输出预算不表示取消本地完整性限制。

未知/多余字段、未保存的角色连接、非法数值和跨服务地址会整份拒绝，不部分生效。
只解析 `choices[0].message.content`；思考内容不作为结果，工具调用不执行。
继续执行原完整 Schema、ID、AC 和一致性校验；语义 FAIL 不重试，确定性失败不被模型 PASS 覆盖。
AUTH/能力错误/拒绝/截断不重试；429、网络/超时和结构化错误在上述总预算内重试，耗尽交人工。
取消停止本地等待和重试、丢弃迟到结果，不保证远端计算/计费停止；不影响 Worker UNKNOWN 保护。

诊断记录实际服务、请求/传入/响应 model、attempt、耗时、错误类别和返回的 token 用量；缺失模型/用量
和费用保持 unknown。连接页的“配置检查未发送模型请求/真实角色准入待验证”区分本地检查与工程准入状态；某一次任务的响应事实
只在该任务诊断中表示，不自动升级成全角色已准入。Key 不进入子进程环境/参数、SQLite、Prompt 日志或导出。

接口依据：[BigModel Chat Completions](https://docs.bigmodel.cn/api-reference/模型-api/对话补全)、
[JSON 输出](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output)、
[思考模式](https://docs.bigmodel.cn/cn/guide/capabilities/thinking)。这是公开协议与离线实现范围，非真实模型通过证据。

Kimi 工程契约核对日 2026-09-09：[模型列表](https://platform.kimi.com/docs/models)、
[K3 参数](https://platform.kimi.com/docs/guide/kimi-k3-quickstart)、
[Chat API](https://platform.kimi.com/docs/api/chat)、[JSON Mode](https://platform.kimi.com/docs/guide/response_format)。
仅选择明确支持的 kimi-k3，不承诺账户已获权限或其他 Kimi 型号兼容，不升级 Codex/GLM 默认值。

CLI 使用相同默认文件与角色绑定。Mission JSON 的 `external_service_consent` 为实际确认服务列表，
如 `["bigmodel_general", "moonshot_cn"]`；纯 Kimi 为 `["moonshot_cn"]`。
兼容旧字符串 `"bigmodel_general"`，但它只授权 GLM；缺少所选服务许可时，在产生 Worker/外发前拒绝。
纯 Codex 不需要。原有多子任务 planning dry-run 仍可能调用 Planner，不能把它当成不发模型的配置检查。
