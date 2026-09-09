# CLAO Native 开发入口

本目录基于 [AO v0.12.12](https://github.com/Untrivial-ai/agent-orchestrator/tree/v0.12.12)，上游 commit `84fb37ce5aa947ceb9b19b0c2435b242ac92ce26`。`81d2ea9` 是 3365 个文件原样导入的独立提交（包括 25 个可执行文件模式），不包含上游 `.git`。之后的提交才是 CLAO 修改，审计可分别比较。

保留 [Apache-2.0 LICENSE](LICENSE) 及各目录原有归属/许可；AO 原 README、作者与组件来源不改成 CLAO 原创。CLAO 修改范围为独立应用身份、原生 Session 的可选闭环所有权、SQLite 验收记录、验收入口/结果以及原 Python 纯逻辑桥接。云服务、官方更新与发布目标不用于此开发版。

## 启动

需要 Windows、Git、Node（此次构建 24.19.0）、Go（此次构建 1.26.5）、Python 3.12 与原 `clao` 的依赖。Frontend 依赖/锁文件及 Vite/Forge 构建结构沿用上游；未自动安装编码工具、登录或调用模型。

首次准备依赖：在本目录运行 `npm ci`，在 `packages/product-ui` 和 `frontend` 分别运行 `npm ci`。原 Python venv 可通过 `-Python` 明确传入。开发入口不自动安装缺少的依赖。

```powershell
# 从仓库根目录执行；Python 应指向已经具备 clao 依赖的 venv。
./ao/dev-clao.ps1 -Python ./clao/.venv/Scripts/python.exe
```

可用 `-Node`、`-Go`、`-Python` 指定可执行文件；`-SkipBuild` 使用已经构建的 `ao/frontend/daemon/ao.exe`。这是实际 Electron + Vite + Go 开发入口，不是旧 Panel，也不构建发行安装包。默认名称 **CLAO Native**、应用 ID `dev.clao.native.desktop`、数据根 `~/.clao-ao`、端口 7312，可用 `-DataHome` / `-Port` 指定另外的开发目录/端口。拒绝把数据根设为官方 `~/.ao` 或其子目录；不会发现官方的 running.json、接管其 daemon 或使用官方更新目标。

原生项目、27 个 registry 入口、模型目录/搜索/默认选择、认证、普通 Session、Chat/终端与文件查看由 AO 源码提供。没有复制一张工具映射表替代执行器，也没有把 Python Panel 嵌入窗口。普通工具仍按上游表达安装、登录、Chat 或 TUI 能力；未验证的执行器不计为 CLAO 闭环准入。

## 创建闭环任务

在原生项目选择 **New task**，使用原生 **Agent / Model** 菜单，勾选 **CLAO 闭环验收**，填写目标、AC、允许/禁止范围和 Gate。当前闭环要求干净的单仓库 Git 项目（不要求 remote/origin），明确拒绝脏目录、scratch、多仓库、TUI 降级、跳过审批及附件。普通 AO 项目操作原样保留。

原生 AO 创建固定 base 的 Worker/worktree。回合结束后，程序先确认 Controller 已终止，再执行范围、仓库完整性与 Gate。失败最多修复 0–3 次，每次只向同一 Session 发送一条修复指令；范围/取证失败不靠模型覆盖。通过后固定结果，在另一原生只读复核 Session 中使用原 Verifier schema/关联/AC/一致性约束，重新核对最终 Gate，全部通过才标“验收通过”。空回复、普通完成事件、已有结果 commit 都不等于通过。

Session 详情内显示任务结论、AC、分项验收、修改路径和结果位置，长证据在详情中。结果仅在隔离工作区，不自动写回用户 HEAD/分支/index、merge 或 push；本轮未接入旧版独立补丁导出。

人工审批仍通过原生 Chat。闭环只允许当前请求的 `allow_once`；再用已有 F02 路径/命令策略校验，禁止路径、越根、Git 控制文件、危险 Git、额外/未知权限不能经按钮绕过。信息不完整时可以拒绝或取消，不能猜测目标。Verifier 不获得工具审批。普通非闭环请求不受新增策略影响。

## 控制权与恢复边界

- AO Manager/Chat/driver 负责真实进程、Session、conversation 与 workspace；闭环服务是这一任务唯一自动调度者。持久 `clao_mission_id` 在启动进程前绑定，普通 AO 自动 nudge/CI/review/follow-up 对这些 Session 被隔离；普通 Session 不变。
- 同一个 AO SQLite 增加 `clao_missions` 和 CAS revision，保存范围/模型/base、operation intent、停止/验收事实。没有第二数据库、API 服务或 Python Controller。Python 子进程只复用 `TaskSpec`、F02、F03、`IntegrationGate`、Verifier 的纯校验/证据准备；不接模型、不保存凭据。
- spawn/resume/send/stop 前先持久 intent。未知结果不重放；重启根据不可变 owner 找到已有 Session，保持 UNKNOWN，阻止新闭环。确认未创建 Worker 的记录不永久阻塞。取消先持久 receipt；必须同时有 AO `exited` 和无 live Controller 才能继续固定产物。
- 原生 Chat 允许受控人工补充输入；自动跟进、重新启动、重试、变更运行模型/权限必须经过闭环 owner。终态 Session 不允许直接恢复成另一次任务。完整用户 directive 回执、跨进程继续执行与旧 Mission 导入尚未迁移。

每个 Worker/Verifier 回合等待上限 30 分钟，Gate 每条 1–600 秒、输出上限 20000 字符；超限/截断保留原证据规则，过大的 Verifier 输入明确失败，不以片段当完整证据。单 Worker 闭环是当前准入范围，使用同一原生执行器/解析模型做独立复核；Planner/Auditor 异常规划、不同角色连接/参数快照和旧多角色 UI 尚待迁移。

## 数据与验证

旧 `clao/config`、系统凭据、runtime 和官方 AO 数据不读取/迁移到新数据库，也不删除。新页面为空不代表旧连接丢失；将来如需迁移须有明确导入。用户实际调用原生工具时仍使用该工具官方认证；本轮自动验证全部用临时 HOME/APPDATA、测试进程，不使用用户账号或 Key。

验证与实际截图见 [原生集成证据](../docs/reference/ao-native/README.md)。OpenCode ACP 路径经过实际 AO 服务；Codex 在隔离 Windows 账户目录遇到上游 `account_storage_unsafe`，保持失败边界，没有将其算作闭环通过。真实模型、套餐计费、全部执行器/角色兼容、完整体验、全量、安装与发布验收均未完成。正式默认入口和发布 manifest 未切换。
