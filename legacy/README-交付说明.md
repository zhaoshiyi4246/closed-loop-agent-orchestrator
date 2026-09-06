# 闭环多智能体系统 v0.2 — 交付说明

本目录用于组内讨论、验证和后续收敛。`closed-loop-v2/` 是当前 v0.2 主产品
候选；`clao-src/` 与 `ao-supervision-sidecar/` 是历史来源和参考实现，
不是并行的正式运行入口。

当前权威架构是仓库根目录的 `docs/PROJECT.md`；本目录的
`ARCHITECTURE-v0.2.md` 与其保持一致。

## 首次安装

当前 v2 面向 Windows 与 CPython 3.12.x。进入 `closed-loop-v2/` 后双击
`启动CLAO.bat`，会在缺少本地 Python 环境时自动执行 `bootstrap.ps1`；也可手动运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

bootstrap 只创建 `.venv` 并安装固定版本的 Python dependencies，不安装 Python、
Git、AO Desktop/CLI 或 Codex CLI。后三者及 Codex ChatGPT 登录在运行 Mission 时
仍是外部 prerequisite。

正常 Mission 启动通过 Panel/CLI 共用的 read-only preflight 检查这些 prerequisite、
AO Project Git worktree/identity 和生产模型配置；它不会调用 Codex 模型或安装工具。
最终 artifact 的唯一边界由 `release-manifest.txt` 定义，`build-release.ps1` 只从 clean
HEAD 的 tracked blobs 构建 repo 外 staging 与 zip。

## 当前产品边界

AO 负责 Project、Session、Conversation、Agent Runtime、worktree 和 PR/SCM。
本项目在 AO 之上提供唯一的 `MissionController` 控制平面、唯一的
`StateStore` 运行状态源、Observer、Auditor、Planner、Verifier、Integration
Gate、Worker 编排和 UI 时间线。

```text
Panel / run_mission
  → MissionController
    → Planner / Auditor / Verifier（headless Codex CLI）
    → Observer / Gate（确定性程序）
    → ActionExecutor / AOAdapter → AO Codex Worker
    ↔ StateStore
  → StoreBusProjector → JSONL / Markdown / UI Timeline
```

`LoopBus` 是 Store 后置事件投影和审计展示，不是控制总线，也不是唯一 AO
传输层。用户指令经 `Panel → DirectiveChannel → MissionController` 消费；
发给 Worker 的真实指令再由 `ActionExecutor → AO` 投递。

## 当前角色契约

| 角色或程序 | 当前形态 |
|---|---|
| Planner | 项目级唯一；headless Codex CLI；默认 `gpt-5.6-sol`；不直接编辑代码 |
| Auditor | 只读语义审计；headless Codex CLI；默认 `gpt-5.6-sol`；只向 Planner 提交结果 |
| Verifier | 独立只读复核；headless Codex CLI；默认 `gpt-5.6-sol`；新 Mission 正常路径只在 Mission 终局调用，历史 `VERIFIER_PENDING` Task 恢复仍可调用 |
| Worker | AO Chat-mode Codex Worker；harness=`codex`；model=`gpt-5.6-sol` |
| Observer | 确定性程序；无模型 |
| Integration Gate | 确定性程序；无模型 |

Auditor、Verifier 和 Observer 都不直接向 Worker 下发自动执行指令。新 Mission
默认 `max_subtasks=1` 并由 Controller 确定性生成唯一 S1，不调用 decomposition
Planner；Panel 只接受 1 或 2。显式选择 2 时 Planner 可以返回 1 或 2，且只应在
存在真实独立并行收益时启用第二 Worker。历史持久化计划即使已有更多 task 仍可
hydrate。VerifierProvider 仍是正式角色；高风险子任务的显式按需策略尚未实现。

当前正常路径为：

```text
Worker idle（确定性证据充分）
→ deterministic Task Gate
→ DONE

证据不足或异常
→ Completion Auditor
→ Planner

materialization
→ integration
→ Final Gate
→ Mission Verifier
→ MISSION_DONE / HUMAN
```

gate-first 只用于首次 `WORKER_RUNNING` 的明确
idle/waiting_input/needs_input/exited/terminated Worker：必须无
pending approval、无 actionable alert 或待处理 L0 fresh error，且非空 Gate、AO
workspace 与至少一个可审计的 non-artifact Git change 同时存在。空 Gate、无变更、
change set 未知或 workspace 不可解析继续走 Completion Auditor → Planner；Gate
FAIL 也继续由 Auditor → Planner 裁决。新 Task Gate PASS 不调用 Completion
Auditor、completion Planner 或 Task Verifier，也不写 task-level verification row；
历史 runtime 若已处于 `VERIFIER_PENDING`，仍按旧 task verifier 路径恢复。Mission
Verifier 是新 Mission 默认唯一的正常路径 Verifier 调用。

`MISSION_DONE` 表示 verified integration 已通过 Final Gate 与 Mission Verifier，
结果保留在 `runtime/<mission-id>/integration`。Competition runtime 不会自动修改
用户 `master`/`main`，也不会 push `origin`。如果未来需要交付到主分支，应设计为
用户显式 SCM 操作，而不是 Mission DONE 的隐式副作用；当前没有宣称已实现手动
SCM 按钮。

## 目录结构

```text
ARCHITECTURE-v0.2.md          v0.2 当前架构说明
PV-独立验证任务.md            历史独立产品验证任务书
AO_UPGRADE_CHECKLIST.md       AO 版本升级验收流程
ao-openapi-diff.py            OpenAPI 契约对比工具

closed-loop-v2/               当前主产品候选
  src/loopcore/               Mission、Store、AO 边界、Observer、Gate、Provider
  panel/                      server.py + index.html，本地 Web 面板（7100）
  prompts/                    Planner/Auditor/Verifier 角色契约
  config/default.yaml         当前运行配置
  schemas/                    JSON Schema
  tasks/mission-quick.json    当前 Codex dry-run 示例
  tasks/e2e-smoke.json        固定标准 E2E 输入（不自动执行）
  run_mission.py              CLI 与运行时组装入口
  启动CLAO.bat                 CLAO 面板启动入口
  tests/                      v0.2 自动化测试

clao-src/                     历史来源与参考实现
ao-supervision-sidecar/       历史来源与参考实现
closed-loop-demo/             演示目标仓库
closed-loop-demo-origin.git/  演示 bare origin
```

R2 Closure Audit 已确认当前 v2 不依赖历史来源目录。它们继续保留在 Git repo 作为
historical/reference source，但不应进入最终 competition release artifact；精确的
clean release 内容边界归 R5 审计。

## AO 运行时与用户交付边界

R2-0 已从当前生产主路径移除开发者绝对 AO 路径。AO Desktop 是外部依赖，不随
本源码目录打包、安装或自动启动：

- executable：`CLAO_AO_BIN` → PATH 中的 `ao`；
- runfile：`CLAO_AO_RUN_FILE` → `~/.ao/running.json`；
- 正常 Mission 启动/恢复必须能够解析 AO executable，否则 fail fast；
- Panel 只读查看已有 Mission 存档不要求 AO executable，也不连接 AO、调用
  Codex 或创建 Worker；
- Panel `GET /api/projects` 通过现有 `AOAdapter.get_projects()` 读取 AO 官方
  Project registry，只返回 `id/name/path/kind`。用户新建 Mission 时选择一个已注册
  Project，后端在创建 runtime/Worker 前重新查询并验证 ID 与本地目录 path；不读取
  `ao.db`、`AO_DATA_DIR` 或 AO worktree 根目录，也不伪造 demo Project。

上述结论只表示“运行时路径可移植”，不表示“任意用户零配置安装”。clean-machine
Python bootstrap、AO/Codex/Git Mission preflight 与 clean artifact builder 已提供；
clean-release rehearsal、AO 首次配置 UX 和真实 AO/Codex 彩排仍未完成。Panel 已能
选择 AO 中的已注册 Project，但 Project 创建、注册和修改仍由 AO 负责。

## 当前实现与阶段事项

当前已实现：

- Panel 发起 Mission；
- Panel 从 AO 官方 registry 发现并选择已注册 Project，后端启动前重验
  `project_id/path`，且不再默认绑定 `closed-loop-demo`；
- 单 Worker Mission 确定性规划；双 Worker 候选才调用 Planner 分解；
- Panel/CLI 的 AO Codex Worker 执行；
- Observer 确定性观察；
- 证据不足或异常时的 Auditor → Planner 闭环；
- deterministic Task Gate、Mission Final Gate 和 Mission Verifier；
- StateStore 恢复、stop/resume；
- UI 时间线与派生的 Markdown/JSONL。

阶段状态与后续：

- Verifier final-only 已完成，PR #11 后同题 E2E 为 `646.116s`；
- gate-first happy path 与 event-freshness 修复已完成；
- 默认 1 个 Worker、按需最多 2 个已完成；标准 smoke
  `MISSION-E2E-SMOKE-20260902-204459` 已到达 `MISSION_DONE`；
- Competition runtime 的自动 master/main merge 与 origin push 已移除；
- R2 duplicate / legacy convergence 已关闭，当前 v2 production authority 单一；
- 最后完成 clean delivery、installer/bootstrap、AO first-run 和 CI 收尾；
- fingerprint/source 与 thread revision 继续保持低优先级。

Project selector 已完成；Project 注册本身仍由 AO 负责，其他首次配置 UX 继续归
后续任务。R5-2 已提供 clean-machine Python bootstrap，R5-3 已实现 shared Mission
preflight、allowlist builder 与 release-safe sample。历史 Mission 查看/resume 保留已持久化的
`project_id`；CLI 仍通过
Mission JSON 显式提供 `project_id`。若未来需要主分支交付，用户显式 SCM 操作也应
作为独立设计处理。legacy `AO_DATA_DIR` parallel runtime 已在 R2 收敛；当前
runtime 只使用正式 portable AO boundary。

## 本地验证

已验证基线使用 Python 3.12、本地 `.venv`、独立安装并运行的 AO Desktop，
以及已通过 ChatGPT 登录的 Codex CLI。

真实 Mission 启动前必须先安装并运行 AO Desktop。若 PATH 已有 `ao`，无需设置
executable；否则在当前进程设置 `CLAO_AO_BIN`。非标准 daemon runfile 才需要
设置 `CLAO_AO_RUN_FILE`，默认读取 `~/.ao/running.json`。

```powershell
cd closed-loop-v2
$venvScripts = (Resolve-Path ".\.venv\Scripts").Path
$env:PATH = "$venvScripts;$env:PATH"
$env:PYTHONPATH = (Resolve-Path ".\src").Path

.\.venv\Scripts\python.exe -m pytest .\tests -q
.\.venv\Scripts\python.exe -m compileall -q .\src .\panel .\run_mission.py
.\.venv\Scripts\python.exe .\run_mission.py .\tasks\mission-quick.json --dry-run
```

`--dry-run` 不连接 AO，也不创建 Worker、StateStore 或 runtime；
`max_subtasks=1` 时输出确定性计划且不调用模型，值为 2 时才调用真实只读 Codex
Planner。真实运行还需要 AO daemon 在线，且目标 Project 已在 AO 注册。

测试数量以 CI 或当前真实命令输出为准，不在交付说明中冻结。

## 不作为源码交付的内容

- AO Desktop 安装目录与 AO 用户数据；
- 真实 Session、Conversation、凭据、Cookie 和日志；
- `.venv/`、`__pycache__/`、`.pytest_cache/`；
- `closed-loop-v2/runtime/` 及面板生成的任务存档；
- 历史 worktree、运行数据库和本机缓存。
