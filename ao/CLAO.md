# CLAO Native 开发入口

本目录基于 [AO v0.12.12](https://github.com/Untrivial-ai/agent-orchestrator/tree/v0.12.12)，上游 commit `84fb37ce5aa947ceb9b19b0c2435b242ac92ce26`。`81d2ea9` 是 3365 个文件原样导入的独立提交（包括 25 个可执行文件模式），不包含上游 `.git`。之后的提交才是 CLAO 修改，审计可分别比较。

保留 [Apache-2.0 LICENSE](LICENSE) 及各目录原有归属/许可；AO 原 README、作者与组件来源不改成 CLAO 原创。CLAO 修改范围为独立应用身份、原生 Session 的可选闭环所有权、SQLite 验收记录、验收入口/结果以及原 Python 纯逻辑桥接。云服务、官方更新与发布目标不用于此开发版。

“AO 原生底座 + 单 Worker 验收闭环基础集成” **DONE**：[PR #46](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/46) 启动失败返修通过外部代码审计，2026-09-10 已 rebase 合入 main。整体迁移与 M4 仍 IN_PROGRESS；角色决策切片 **DONE**（[PR #47](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/47) 再次外部代码审计 PASS，2026-09-10 已 rebase 合入）；唯一下一开发内容为 **运行恢复与用户指令回执迁移，TODO**，本轮不开始。迁移工作树、依赖及独立开发数据保留。

## 启动

需要 Windows、Git、Node（此次构建 24.19.0）、Go（此次构建 1.26.5）、Python 3.12 与原 `clao` 的依赖。Frontend 依赖/锁文件及 Vite/Forge 构建结构沿用上游；未自动安装编码工具、登录或调用模型。

首次准备依赖：在本目录运行 `npm ci`，在 `packages/product-ui` 和 `frontend` 分别运行 `npm ci`。原 Python venv 可通过 `-Python` 明确传入。开发入口不自动安装缺少的依赖。

```powershell
# 从仓库根目录执行；Python 应指向已经具备 clao 依赖的 venv。
./ao/dev-clao.ps1 -Python ./clao/.venv/Scripts/python.exe
```

本机已验证的完整命令（本 PR 的开发 daemon 已构建，故使用 `-SkipBuild`）。在一个新的 PowerShell 窗口执行；下列环境只作用于该窗口及开发子进程。启动器直接使用现有 Forge start 入口，不要求另装 npm；需要已保留的前端依赖。此命令使用独立、空账户 profile，不读取官方 AO 或旧 CLAO 配置：

```powershell
Set-Location 'E:\Projects\clao-ao-native'
$env:PATH = 'C:\Users\Lenovo\go\pkg\mod\golang.org\toolchain@v0.0.1-go1.26.5.windows-amd64\bin;' + $env:PATH
$profileDir = 'E:\Projects\clao-ao-native\.native-dev\roles-manual-profile'
$env:USERPROFILE = $profileDir
$env:HOME = $profileDir
$env:APPDATA = Join-Path $profileDir 'appdata'
$env:LOCALAPPDATA = Join-Path $profileDir 'local'
$env:XDG_CONFIG_HOME = Join-Path $profileDir 'config'
$env:XDG_DATA_HOME = Join-Path $profileDir 'share'
$env:CODEX_HOME = Join-Path $profileDir '.codex'
./ao/dev-clao.ps1 -SkipBuild `
  -Node 'C:\Users\Lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' `
  -Python 'E:\Projects\closed-loop-agent-orchestrator\clao\.venv\Scripts\python.exe' `
  -DataHome 'E:\Projects\clao-ao-native\.native-dev\roles-manual-data' -Port 7317
```

打开的是原生 Electron 窗口；数据位于所列 `roles-manual-data`，不是其他工作树的 Panel。该隔离 profile 没有导入用户登录；Codex 的 `account_storage_unsafe` 仍如实阻止启动，需后续处理上游支持的账户存储条件，不能跳过检查。自动验证仅使用协议进程替身，不表示该 profile 已能调用真实模型。

可用 `-Node`、`-Go`、`-Python` 指定可执行文件；`-SkipBuild` 使用已经构建的 `ao/frontend/daemon/ao.exe`。这是实际 Electron + Vite + Go 开发入口，不是旧 Panel，也不构建发行安装包。默认名称 **CLAO Native**、应用 ID `dev.clao.native.desktop`、数据根 `~/.clao-ao`、端口 7312，可用 `-DataHome` / `-Port` 指定另外的开发目录/端口。拒绝把数据根设为官方 `~/.ao` 或其子目录；不会发现官方的 running.json、接管其 daemon 或使用官方更新目标。

原生项目、27 个 registry 入口、模型目录/搜索/默认选择、认证、普通 Session、Chat/终端与文件查看由 AO 源码提供。没有复制一张工具映射表替代执行器，也没有把 Python Panel 嵌入窗口。普通工具仍按上游表达安装、登录、Chat 或 TUI 能力；未验证的执行器不计为 CLAO 闭环准入。

## 创建闭环任务

在原生项目选择 **New task**，使用原生 **Agent / Model** 菜单，勾选 **CLAO 闭环验收**，填写目标、AC、允许/禁止范围和 Gate。当前闭环要求干净的单仓库 Git 项目（不要求 remote/origin），明确拒绝脏目录、scratch、多仓库、TUI 降级、跳过审批及附件。普通 AO 项目操作原样保留。

原生 AO 创建固定 base 的 Worker/worktree。回合结束后，程序先确认 Controller 已终止，再执行范围、仓库完整性与 Gate。需要诊断的失败进入下述 Auditor/Planner 决策，最多修复/替换合计 0–3 次；范围/取证失败不靠模型覆盖。通过后固定结果，在另一原生只读复核 Session 中使用原 Verifier schema/关联/AC/一致性约束，重新核对最终 Gate，全部通过才标“验收通过”。空回复、普通完成事件、已有结果 commit 都不等于通过。

提交被持久接收后即可在对话框查看原请求，不必等到 Session 创建成功。项目页的“闭环任务”也保留所有请求（包括启动失败、没有 Session 的记录），点击目标打开验收详情；有 Session 时可选“打开原生 Session”。AC、分项验收、修改路径和结果位置在同一面板，长证据在详情中。结果仅在隔离工作区，不自动写回用户 HEAD/分支/index、merge 或 push；本轮未接入旧版独立补丁导出。

失败/取消/通过的原请求可选择“创建新的尝试（保留草稿）”，重新确认后才提交新 ID；原请求不修改。关闭/重开保留目标、执行器/模型与验收草稿。POST 回执丢失时只查询原 ID，重复提交同一请求不重复创建 Worker。新尝试使用 Mission ID 区分工作分支，避免原生 seed Session 编号回收后撞上仍保留的旧分支，不删除旧分支。

人工审批仍通过原生 Chat。闭环只允许当前请求的 `allow_once`；再用已有 F02 路径/命令策略校验，禁止路径、越根、Git 控制文件、危险 Git、额外/未知权限不能经按钮绕过。信息不完整时可以拒绝或取消，不能猜测目标。Auditor/Planner/Verifier 均不获得工具审批。普通非闭环请求不受新增策略影响。

## 控制权与恢复边界

- AO Manager/Chat/driver 负责真实进程、Session、conversation 与 workspace；闭环服务是这一任务唯一自动调度者。持久 `clao_mission_id` 在启动进程前绑定，普通 AO 自动 nudge/CI/review/follow-up 对这些 Session 被隔离；普通 Session 不变。
- 同一个 AO SQLite 增加 `clao_missions` 和 CAS revision，保存范围/模型/base、operation intent、停止/验收事实。没有第二数据库、API 服务或 Python Controller。Python 子进程只复用 `TaskSpec`、F02、F03、`IntegrationGate`、Verifier 的纯校验/证据准备；不接模型、不保存凭据。
- spawn/resume/send/stop 前先持久 intent。spawn 失败立即读取不可变 owner：原生创建只在初始指令未交付的 seed 阶段删除记录，没有发布 Session 且没有既有执行证据时记录 CONFIRMED_FAILURE / FAILED；保留原始错误并允许另建尝试。已发布 Session 但关联回执未完成时保存已有关联、保留 UNKNOWN，不猜测初始执行成功、不重复 spawn。读取失败不能证明未启动；重启同样不重放。
- UNKNOWN 请求仍显示在项目页并阻止新闭环；可通过“取消闭环”请求停止，已接收但未确认时可“重新确认停止”。取消先持久 receipt；必须同时有 AO `exited` 和无 live Controller 才能结束取消或继续固定产物，不提供强制忽略 UNKNOWN。
- 原生 Chat 允许受控人工补充输入；自动跟进、重新启动、重试、变更运行模型/权限必须经过闭环 owner。终态 Session 不允许直接恢复成另一次任务。完整用户 directive 回执、跨进程继续执行与旧 Mission 导入尚未迁移。

每个 Worker/语义角色回合等待上限 30 分钟，Gate 每条 1–600 秒、输出上限 20000 字符；超限/截断保留原证据规则，过大的 Verifier 输入明确失败，不以片段当完整证据。单 Worker 是当前迁移范围；本轮四角色原生选择/决策接线见下节，旧 HTTP 连接/凭据导入未实施。

当前已接：**原生项目/模型入口、单 Worker 的 Session/工作区接线、Gate/范围/完整性、有界修复、独立 Verifier、启动请求可见/失败处理及验收面板**。下述单 Worker 角色决策切片已审计合入（DONE）。未接：**多子任务分解/并行、完整恢复与用户指令回执、旧历史/连接导入、普通目录/未提交来源支持、独立导出与结果中心、闭环运行图及正式发布入口**；旧底座完成记录不替代这些迁移验收。

## 数据与验证

旧 `clao/config`、系统凭据、runtime 和官方 AO 数据不读取/迁移到新数据库，也不删除。新页面为空不代表旧连接丢失；将来如需迁移须有明确导入。用户实际调用原生工具时仍使用该工具官方认证；本轮自动验证全部用临时 HOME/APPDATA、测试进程，不使用用户账号或 Key。

验证与实际截图见 [原生集成证据](../docs/reference/ao-native/README.md)。沿用既有 Windows/离线集成、开发构建、Electron 操作及 Codex 截图自查；PR #46 外部代码审计 PASS 不代表负责人已完成完整体验；本角色切片也已再次外部代码审计 PASS 并合入；两次源码审计均不等于负责人完整体验。OpenCode ACP 路径经过实际 AO 服务，外部进程/模型使用替身；Codex 隔离环境的 `account_storage_unsafe` 仍待解决，xfailed 不是执行通过。真实账户/模型、套餐计费、全部执行器/角色兼容、全量、安装与发布验收尚未完成。PR #46 收尾未重跑测试或构建；本轮角色迁移有下述直接证据。正式默认入口和发布 manifest 未切换。


## 角色决策与配置切片

状态 **DONE**：[PR #47](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/47) 再次外部代码审计 PASS，2026-09-10 已 rebase 合入；基础集成 DONE，整体迁移/M4 IN_PROGRESS。完成范围限于单 Worker 异常诊断、五类动作、独立只读语义会话、四角色配置、冻结选择贯通实际启动/恢复与原生决策展示，不等于全部 Planner 或完整恢复。

创建时展开“角色与决策预算”，为 Auditor、Planner、Verifier 选择“沿用 Worker”，或使用原生 Agent / Model 菜单单独搜索、点击型号。继承只复制当次配置，每次角色调用都有独立 Session/工作区/上下文。模型留空仍表示原生默认，不强填型号；实际选择、AO 配置解析值和执行器明确报告值分别显示。ACP 仅设置成功但没有回传当前型号时显示 unknown，不能从请求值推断；Codex 记录 thread/start resolved 事实，不冒充每一次 provider 请求型号。角色开始/结束计时来自真实调用边界，不是 Mission 总耗时，用量/费用未提供时为 unknown。

默认值贯通到实际 Chat：创建表单已展示并确认的项目模型作为具体型号提交；主动清空模型表示执行器默认/不覆盖。角色“沿用 Worker”复制该次已确认选择，换执行器后的空模型不会继承项目 Worker 的型号。Manager 的预检、Session 记录和 Chat 启动共用这一配置规则，局部修复的 Chat 恢复使用 Session 已保存的模型/权限；后续角色及替代 Worker 使用 Mission 冻结选择，不再合并当前项目默认。只能由执行器解析的空型号继续保持不覆盖，确认事实不足时显示 unknown。普通非闭环 AO 的项目/角色默认继承与恢复行为保持原样，历史记录不因本次修复重写。

原生 Codex 有可读 active account 引用时保存引用并在调用前核对，账号变化停止继续；AO v0.12.12 没有 per-spawn 独立账号参数，故不提供假的逐角色换账号功能。其他执行器沿用其原生认证，未提供账号事实不猜测。配置与角色冻结保存在现有 `clao_missions` 文档，之后改项目默认值不改变当前角色或 Worker 恢复参数。历史缺角色字段保持历史缺失，不写入新的角色/模型事实；旧 HTTP 连接、系统凭据仍未自动导入。

当前语义通道以 `read-only` 能力准入：Codex 原生 read-only sandbox/never approval，逐线程禁用继承 MCP、子 Agent、shell 与 web 工具；OpenCode 原生临时命名 agent 的全部工具/权限 deny，并在 ACP 客户端拒绝提权。权限覆盖仅本次调用，不改全局配置。结束后还需确认 Session 已停止且语义工作区相对其固定 base 无改动。其他上游 Chat/TUI 工具的普通能力原样保留，缺少这项明确只读映射时不能承载自动语义角色；不能将未安装与缺少只读能力混为一谈。当前验证代表为 OpenCode 语义角色，另有 Kimi Worker + OpenCode 角色混用；不宣称全部执行器/真实账号准入。

正常路径仍只有 Worker、确定性验收和独立 Verifier。Gate 命令失败或已停止执行的异常使用完整 TaskSpec/AC/范围、失败输出、Git 差异、Worker 状态和历史生成旧 Auditor 输入；审核结果及剩余预算进入旧 Planner Prompt/Schema。输出只取已完成回合的正式 assistant 内容，做原有关联、AC、目标及一致性校验。证据超限明确交人工，不截取后假称完整。合法 FAIL/HUMAN 不按协议错误重试；本原生切片协议错误直接进入 HUMAN，未增加新的模型重试层。

| Planner 动作 | 当前单 Worker 的程序行为 |
|---|---|
| CONTINUE | 当前 Worker 已停止，仅观察并复查一次确定性证据；仍失败则 HUMAN，不再发消息/重启 |
| SEND_LOCAL_FIX | 不改原目标/AC/Gate/范围，恢复当前 Worker 并提交一次有持久身份的修复 |
| REPLAN_SPAWN | 先确认旧 Worker 停止，按配置的替换预算从原 frozen base 建新 Worker；`replacement_task_spec.objective` 只作为原约束下执行方案，保留旧工作区和证据 |
| CANDIDATE_DONE | 只请求确定性验收；通过后仍需固定产物和 Verifier，不能直接 DONE |
| HUMAN | 合法结束自动处理，保留诊断与原因，可查看原请求/角色 Session 或确认新的尝试 |

局部修复和替换共用最多 0–3 次动作预算，替换默认 0、不得高于总预算。同一文件证据重复失败停止诊断循环；额外诊断上限为动作预算 + 2。未确认停止、范围/完整性违规不会进入模型放行。每次 incident、角色调用和动作有稳定标识及持久记录，轮询/查询不触发调用。取消遍历所有不可变 owner 的 Session，无法确认则保留 UNKNOWN；新增角色回执丢失可关联已有 Session，不重发、不重新 spawn。完整跨进程继续执行仍未迁移。

在原请求的“角色与决策”中查看本次选择、未调用/调用中/诊断/决策/程序动作和回执，点击对应角色会话查看原生记录；Gate/AC/结果仍在同一验收面板。需要账户/收费模型的手动执行尚未授权，空账户开发入口仅供打开页面；不要把隔离 fixture 名称当真实型号。

### 直接验证与截图

2026-09-10：Windows AO/Git/SQLite/HTTP 产品入口 **27 passed、1 xfailed**；纯角色契约 **15 passed**；原生创建对话框 **16 passed**，另补预算输入与历史角色字段兼容各 **1 passed**。新增无进展与恢复/模型事实定向检查单独记录在台账，不累计为全量。Go 修改相关包定向检查、Go daemon 开发构建、TypeScript 和实际 Electron 开发启动完成。Electron 实际展开/搜索/点击原生模型菜单，完成正常独立复核、Gate 失败 → Auditor/Planner → 修复、合法 HUMAN，并核对冻结记录、真实角色 Session 与原项目未变化。

截图：[角色模型菜单](../docs/reference/ao-native/roles/roles-native-model-menu.png)、[独立 Verifier](../docs/reference/ao-native/roles/roles-independent-verifier.png)、[审核与修复](../docs/reference/ao-native/roles/roles-audit-planner-repair.png)、[HUMAN](../docs/reference/ao-native/roles/roles-human-decision.png)。已由 Codex 自查；外部代码审计已通过，负责人完整体验仍待完成。默认模型返修仅做相关后端/协议检查，未重测浏览器；本次合并收尾未重跑测试或开发构建。

可重复的离线入口（在上述开发入口已经启动、Vite 正常服务后，于另一 PowerShell 窗口执行）：

```powershell
Set-Location 'E:\Projects\clao-ao-native\ao\frontend'
$env:PATH = 'C:\Users\Lenovo\go\pkg\mod\golang.org\toolchain@v0.0.1-go1.26.5.windows-amd64\bin;' + $env:PATH
$env:GOTOOLCHAIN = 'local'
$env:GOWORK = 'off'
$env:CLAO_CORE_PYTHON = 'E:\Projects\closed-loop-agent-orchestrator\clao\.venv\Scripts\python.exe'
$env:CLAO_TEST_ROLES = '1'
$env:CLAO_DESKTOP_TEST_PORT = '7318'
& 'C:\Users\Lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts/test-clao-desktop.cjs
```

该脚本另建临时数据/profile/Git 与协议进程替身，未替换 AO Manager/Chat/Store/Gate；不会使用真实账户、Key 或模型。保留 Codex `account_storage_unsafe` / xfailed 边界。NOT_RUN：真实模型/账户/套餐、完整体验、全执行器兼容、全量、smoke、发行安装包和发布；没有导入旧数据或切换正式入口。
