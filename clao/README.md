# CLAO v0.2

Closed-Loop Agent Orchestrator

CLAO 是构建在 Agent Orchestrator（AO）之上的本地闭环软件开发控制层。它把用户的
Mission 交给受控的 Codex Worker，在确定性观察、Gate 和最终验证后生成可审计结果。
当前架构见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 系统要求

- Windows；
- CPython 3.12.x；
- Git；
- AO Desktop 0.12.9（基准版本），daemon 已启动；
- Codex CLI，并已通过 `codex login` 使用 ChatGPT 登录。

CLAO 不安装或启动 Git、AO Desktop、Codex CLI，也不读取 API Key 作为默认认证方式。

## 准备 AO Project

先在 AO 中注册要使用的 Git repository。针对已验证的 AO Desktop 0.12.9，Project
必须具有名为 `origin` 的 remote 和可用的 remote-backed base ref：

- 显式 `defaultBranch=<branch>` 时，`refs/remotes/origin/<branch>` 必须存在；
- `defaultBranch=auto` 时，`refs/remotes/origin/HEAD` 必须指向一个可解析的
  remote branch；
- 没有 `origin` 的 local-only repository 当前不受支持。

`origin` 可以指向 GitHub/GitLab，也可以指向完全本地的 bare Git repository；这一
要求本身不需要互联网。CLAO 不会自动执行 `git fetch`、添加 remote、设置 remote
HEAD 或修改 AO Project config。Panel 与 CLI 先保存无密钥的有效配置快照，再通过共享的只读 preflight
报告缺失项；失败的准备阶段也可在 Panel 中查询，尚未创建 Worker。

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

1. 启动 AO Desktop；
2. 双击 `启动CLAO.bat`；
3. 在 Project selector 中选择已注册的 AO Git Project；
4. 填写目标、允许路径、验收条件和 Gate 命令；
5. 保持默认 `max_subtasks=1`，只有确有独立并行收益时才选择 2；
6. 启动 Mission，并在页面中查看 Task、Gate、Verifier 和 timeline。

Panel 不会构造 demo Project，也不会替用户注册或修改 AO Project。

## 使用 CLI

复制一个 sample，替换 `project_id` 和 `mission_id`，然后运行：

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
.\.venv\Scripts\python.exe .\run_mission.py .\tasks\mission-quick.json `
  --poll-seconds 5 --cap-seconds 1200
```

`tasks/mission-quick.json` 与 `tasks/e2e-smoke.json` 都是模板，其中
`REPLACE_WITH_AO_PROJECT_ID` 必须替换为真实 AO Project ID。每次新运行应使用唯一
`mission_id`。

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

当前默认模型继续为 `gpt-5.6-sol`。Worker 使用 `worker.model`，语义角色使用
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

页面显示准备、AO 调用、观察/审批等待、语义角色、各 Gate、materialization/merge
和重试等真实阶段。独立模型请求记录开始/结束、attempt、耗时和错误类别；未调用、
历史 unknown、未知模型/用量/费用分开表达。Worker 的配置请求/传入值、AO Session 创建时
resolved model、conversation 后续 reroute 各自显示来源；缺字段不从配置猜测，也不把
Session 或 reroute 事实当成单次 provider 请求模型/精确耗时。SSE 断连保留最后状态，重连以顺序化
完整快照替换，不重放写请求。HTTP 处理耗时和状态快照耗时不等于模型调用耗时。

## 指令、取消与恢复（v0.3 R02 本分支待审计）

指令发送成功表示 receipt 已持久接收；页面显示 received/applied/rejected/unknown，
以及实际消费者、时间与原因。Worker applied 仅表示 AO 接受消息；Planner 镜像单列，
不代表 Auditor/Verifier/Worker 主目标已消费。Observer/Gate 是确定性程序，不能接受
语义指令。Final Verifier 实际读取面向 verifier 的 notes；同 command 重试不重复发送。

“取消本次执行”先接收请求，再确认当前本地 Codex/Gate 子进程与 AO Worker 停止；
requested/cancelling 不等于 cancelled，unknown 表示需人工核对。未知停止不继续交付。
历史查看不连接 AO、也不修改原库；非终态“检查并恢复”必须验证原配置/source、当前
所需 Git/workspace/Session/operation/证据。缺材料不自动补造；终态只可创建有关联的新
attempt，具有独立 identity/config/source/历史，原记录不变。旧停止未知时也不能开替代 attempt。

每次新 Mission 要求 AO 来源分支的 local/origin tracking/真实 remote commit 一致，
用只读查询冻结 exact source；需要访问已配置 origin。CLAO 不代为 fetch 或同步分支。
后续来源漂移会阻断新 Worker spawn，integration 保持原 source。缺少 Worker 创建基线
证据时交人工；不承诺跨 AO/Git 的原子创建。最多两个独立子任务保持可用；本版明确拒绝
有 dependencies 的计划，避免下游 Worker 在没有上游代码的基线上执行。

## 结果与 SCM 边界

每个 Mission 的状态和证据位于：

```text
runtime/<mission-id>/
```

`MISSION_DONE` 表示 integration 结果已经通过 Final Gate 和 Mission Verifier。结果保留
在 `runtime/<mission-id>/integration`，不会自动修改目标 repository 的 `main` 或
`master`，也不会自动 push `origin`。将结果交付到目标主分支始终需要用户显式操作。

## 故障排查

- **AO unavailable**：启动 AO Desktop，确认默认 `~/.ao/running.json` 可用；若 `ao`
  不在 PATH，可为当前进程设置 `CLAO_AO_BIN`。
- **Codex login**：运行 `codex login status`，确认显示 ChatGPT 登录。
- **origin/default branch**：确认 Project 有 `origin`，运行
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
