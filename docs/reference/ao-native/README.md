# AO 原生底座集成证据

2026-09-09 起，Windows。本页分节保留迁移各阶段的直接验证，不代表真实模型、负责人完整体验或发布验收。

## PR #46 启动失败局部返修

最终 Windows 定向：`test_ao_native.py -k 'failed_start or spawn_receipt_loss or opencode_pass or cancel or manual_accept or codex_uses_same'` **7 passed / 1 xfailed / 9 deselected，46.02s**；Codex xfailed 仍是账户安全阻塞，不算执行通过。原生 `NewTaskDialog` / `GlobalNewTaskDialog` **16 passed**；Go `./internal/service/claoloop` 通过。开发 daemon 构建、Electron/Forge/Vite 实际启动、`tsc --noEmit`、Python compileall、JS 语法、diff-check 与本地文档链接目标检查通过。

- 真实 SQLite 定向覆盖：接收后、intent 前中断；Session 未发布；原生 ACK / 本地关联回执丢失；owner 查询失败；同 ID 重放与新尝试；UNKNOWN 阻止启动和确认停止。没有把缺少回执当作未执行。
- 真实 daemon / Manager / Chat / Git / HTTP：ACP `session/new` 失败记 FAILED / CONFIRMED_FAILURE；解除故障后新尝试可通过真实 Gate/独立 Verifier。另一故障用隔离 SQLite trigger 拒绝 CONFIRMED_SUCCESS 回执写入：真实 Session 和初始回合已存在，UNKNOWN 按 owner 关联，不重复发指令，取消后确认停止。
- 实际 Electron `CLAO_TEST_START_FAILURE=1` 通过：原生模型菜单浏览/搜索/点击、失败记录刷新后可见、查看旧请求、新尝试草稿/模型/范围保留、关闭重开、HTTP POST 回执丢失仍只提交一次、UNKNOWN 阻断与取消。截图已由 Codex 逐张查看，不等同负责人体验验收。
- 直接发现并修复：AO 回滚删除 seed Session 后，其编号可能复用，但分支仍存在；新尝试改用 Mission ID 的 worker/verifier 分支，不删除旧分支。未改账户检查。
- 首轮正常场景在原有 30 秒测试轮询内尚未完成，串行复查原断言通过，未提高等待上限或放宽判断。协议报错实际属于异步 turn 失败；回执丢失改在 SQLite 写入处重现。浏览器夹具按保留下来的当前选择限定菜单作用域，负例断言保留。

本机完整开发启动命令见 [ao/CLAO.md](../../../ao/CLAO.md#启动)，已实际执行，使用已有 Node/npm/Python 与独立 `manual-profile` / `manual-data`，端口 7316。自动桌面检查另用临时目录和 7314，不写入官方 AO、旧 CLAO 或手动 profile。

- [无 Session 的失败请求](startup-failure-visible.png)：刷新后仍可进入，保留原因和新尝试入口。
- [新尝试验收通过](startup-new-attempt-pass.png)：新身份/原生 Session，不改旧请求。
- [已有关联的 UNKNOWN](startup-unknown-linked.png)：可请求停止，不提供替换 Worker 捷径。

返修浏览器复现（先运行开发入口，从仓库根执行）：

```powershell
$env:PATH = 'C:\Users\Lenovo\AppData\Local\Temp\clao-native-build-tools\go1.25.7\go\bin;' + $env:PATH
$env:GOWORK = 'off'
$env:GOTOOLCHAIN = 'go1.26.5'
$env:CLAO_CORE_PYTHON = 'E:\Projects\closed-loop-agent-orchestrator\clao\.venv\Scripts\python.exe'
$env:CLAO_TEST_START_FAILURE = '1'
& 'C:\Users\Lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' ao/frontend/scripts/test-clao-desktop.cjs
```

PR #46 交付时未接：Planner/Auditor 决策、独立角色配置、完整恢复、旧历史导入、独立导出、闭环运行图。后续实现见当前开发说明；当时 M4 IN_PROGRESS、切片 IN_REVIEW。NOT_RUN：全量、smoke、发行/安装器、真实账户/模型/套餐与负责人完整体验验收。

## 构建与运行

- AO v0.12.12 原样导入 `81d2ea9`：3365 文件逐个 Git blob 对照源 ZIP 一致，25 个可执行模式保留，无嵌套 `.git`。原生 registry、模型目录与两个模型选择组件没有翻译或替换。
- Go 1.26.5 开发 daemon 构建通过；原生 Electron 33.4.11 / Node 24.19.0 / Vite/Forge 实际构建并启动。`ao/dev-clao.ps1 -SkipBuild -Python <venv-python>` 开发入口也实际启动，数据与端口独立。
- 前端 `tsc --noEmit`、浏览器检查脚本 `node --check`、Python `compileall` 通过。

## 直接验证

1. `clao/tests/test_ao_native.py` 原生业务集成：**9 passed, 1 xfailed / 58.17s**。仅 OpenCode/Codex CLI 进程由 Go 协议替身替换，AO daemon、Manager、Chat、SQLite、工作区、Git、Gate/Verifier 校验均为真实代码。覆盖正常 PASS、Gate FAIL/只发一次修复、重复创建 receipt 不重生 Worker、取消与确认停止、原生审批一次/拒绝、危险 Git/禁止路径/`.git` 不能人工覆盖、空 Verifier 不通过。原项目 HEAD/分支/index 字节/内容保持不变。
2. 后续补充 Codex 完整权限事实检查：**5 passed / 0.30s**（同文件 `-k original_permission`），local、remote、额外权限和未知字段区分；不是实际 Codex 执行验收。
3. Go `go test ./internal/service/claoloop ./internal/httpd/apispec/specgen ./internal/sessionguard -count=1` 通过。恢复测试重新打开真实 SQLite，丢失确认后按原生 owner 找回 Session、UNKNOWN 不重发/阻止新任务；未创建 Worker 与确认 exited 不永久阻塞；receipt 写失败无停止副作用。
4. Go 定向 `TestCLAOApprovalRetainsAuthorizationContext`、`TestLoadDefaults`、`TestApprovalIsStoredPendingWithProviderDecisions` 与 `TestSpawn.*AutoReview.*` 通过；daemon 包完成编译（该名称筛选没有选中 daemon 测试，不计作测试通过数量）。
5. **实际 Electron 桌面**：打开原生 Agent/Model 菜单，浏览并搜索 `second`、点击选择，提交原生闭环；确认持久 requested model 为 `test/second`，PASS 与 Gate FAIL 两条任务分别可见，失败 repair_send 恰一条。新建项目使用隔离中文路径、无远端 Git；未替换整套 Controller。
6. **端口隔离**：测试 HTTP 进程占据另一个开发端口后，实际 Electron 启动不会探测/连接/关闭它（`FOREIGN_PORT_UNTOUCHED`）。开发版仅根据自己的 discovery 复用相符 daemon，移除按未知端口杀进程接管的上游兜底。

复现（先完成开发构建并运行 Vite 开发入口）：

```powershell
# 从仓库根执行；所有路径参数指向自己的开发构建/venv。
$env:CLAO_NATIVE_BINARY = "$PWD/ao/frontend/daemon/clao-ao.exe"
# clao-ao.exe 是同一开发构建的副本，保留旧测试对 ao.exe 的防真实调用限制。
$env:CLAO_CORE_PYTHON = "$PWD/clao/.venv/Scripts/python.exe"
$env:PYTHONPATH = "$PWD/clao/src"
& $env:CLAO_CORE_PYTHON -m pytest clao/tests/test_ao_native.py -q
node ao/frontend/scripts/test-clao-desktop.cjs
# 端口冲突隔离检查；不连接任何真实 AO。
$env:CLAO_TEST_FOREIGN_PORT = '1'
$env:CLAO_DESKTOP_TEST_PORT = '7318'
node ao/frontend/scripts/test-clao-desktop.cjs
```

桌面检查在系统临时目录创建独立 profile/source/data/协议进程；默认截图也在该临时目录，`CLAO_SCREENSHOTS` 可指定本页目录。替身不会调用真实模型，不使用用户 Key；新文件不进入产品运行资源。源码原封保留，用户已有配置未修改；不扫描官方安装或 `.ao`。

## 实际截图与自查

- [原生模型菜单](native-model-menu.png)：原 AO 下拉菜单展开、可浏览/搜索/点击；默认项仍表示不覆盖模型，测试目录只由外部进程替身提供。
- [闭环通过](closed-loop-pass.png)：Gate 命令、完整性、范围与独立 Verifier 分列，AC 与路径证据可展开。
- [Gate 失败](closed-loop-fail.png)：修复预算用尽仍未通过；未运行 Verifier 不猜成 PASS。

截图来自实际开发 Electron；已由 Codex 查看并收敛重复的恢复提示和大段默认展开证据。不是生成图，不代表负责人已经完成视觉/体验验收。

## 明确未通过/未运行

- **Codex 代表路径未准入**：AO v0.12.12 在隔离 Windows 账户目录报 `account_storage_unsafe` / `Codex account setup did not complete`。保留该场景并记为 xfailed，不 materialize；此次按 owner 事实区分未启动 FAILED 与 UNKNOWN，没有绕过账户 ACL 或借用用户登录。这不影响已经验证的 OpenCode ACP 代表路径，但不能据此称全部执行器兼容。
- 较早一次过宽的 `TestBuild` 名称筛选带入上游 `TestBuildSourceHandoffRequestUsesCurrentNativeSessionContext`，在 Windows 原路径与 JSON 转义路径比较失败。该测试与函数未修改，仍保留；不把本次定向通过表述为上游全量通过。
- 首次 HTTP 测试把派生构建命名 `ao.exe`，触发旧离线夹具的防真实 AO 保护，9 个 setup error；使用同一派生构建的 `clao-ao.exe` 副本完成隔离测试，未移除该保护。桌面脚本先后修正上游 BaseWindow API 与返回项目后新建任务的导航定位；最终实际交互通过。
- **NOT_RUN**：真实账户/登录/API Key/模型/套餐计费；全部执行器与角色组合；完整 GUI 体验；全量回归；smoke；安装器/发行打包/发布。旧功能迁移边界见 [开发说明](../../../ao/CLAO.md)，不由旧 M0–M3 历史完成状态推定。


## 运行恢复与指令回执（PR #48 已审计合入）

本切片实际 Electron 中关闭并重启独立 daemon，从原请求继续验收；同一 Mission/Session 没有重建 Worker。补充输入、原生 Chat、A/B 历史查看和延迟回执经过实际 UI。截图：[继续原任务](recovery/continue-original.png)、[继续后结果](recovery/continued-result.png)、[主目标与 Planner 镜像](recovery/directive-consumers.png)。已查看截图；不代替负责人体验验收。命令与恢复限制见 [开发入口](../../../ao/CLAO.md#运行恢复与用户指令回执)。测试曾修正重启后原生弹层的关闭步骤及 Lexical combobox 定位；没有用强制点击/假 Controller 制造通过。


## 原生迁移收官大阶段（2026-09-11，IN_REVIEW）

基线为 PR #48 rebase 合入后的 main，分支 `codex/ao-native-migration-closeout`。同一 AO 原生服务、Session、Chat、SQLite、Git 与工作区；仅外部执行器/服务及明确故障写入边界使用替身。详细能力、内部审查修正和逐项检查结果见 [当前台账](../../V03_BACKLOG.md#原生迁移收官大阶段2026-09-11-授权)。

- 来源/并行/独立包：Windows `test_ao_native_closeout.py` 七条先通过，后补子任务通过但父 Verifier FAIL 的导出负例通过。普通/空/未提交 Git 来源未回写；真实两 Worker、重启继续/取消/共享预算；下载补丁在匹配基线副本应用后逐文件核对及 Gate，并使临时工作区不可用后下载已存包。
- 连接：`test_ao_native_legacy_integration.py` 两条正式 HTTP 集成通过，旧历史/配置显式导入、内容版本、不同服务/凭据代际与外发确认，真实角色消费者到两个本地 HTTP 替身。`test_ao_legacy.py` 20 passed；源码/结果的 `test_ao_materials.py` 核心和原 U03 HTTP 兼容定向通过，详细分批证据在台账，不累计成全量。
- 恢复：四个可确认检查点通过；最新未发送修复、原生 Chat/镜像、Worker ACK 丢失恢复三条 **3 passed / 96.64s**。窗口消失不等于已停止；只有真实退出事实才能整理或重开。同一 intent 丢失后不再次发送。
- Go 受影响包与六个 SQLite 未发送修复故障子例、TypeScript、Python compileall、JS 语法和文档/差异检查通过。Go specgen 本次名称选集仅编译，未选中行为测试。前端最终相关选集 21 passed、29 passed，集合有重叠。
- 实际 Electron/Forge/Vite：`NATIVE_CLOSEOUT_DESKTOP_PASS`。首次无连接/无项目界面打开普通目录，展开原生模型菜单、搜索并点击，来源确认→真实闭环→差异/AC/Gate/Verifier→浏览器保存 ZIP→解压→独立应用补丁与内容/Gate 核对；显式导入旧配置；两真实 Worker 运行高亮→私有集成→最终验收。原目录未生成 `.git` 或成果文件。
- 最新源码另经稳定启动器完整 Go + Forge 开发构建并实际启动：`./ao/dev-clao.ps1 -IsolatedAccount -DataHome E:\Projects\clao-ao-native\.native-dev\closeout-manual-data -Port 7318`，未用 `-SkipBuild`；同一独立数据保留。
- 首轮 Electron 子进程初始化返回 `0xc0000142`，改用上游非交互 `process.CommandContext` 后同旅程通过。未增加 Gate 自动重试。截图最后仅重新读取同一完成历史校正轮询投影时点，未重跑任务。

实际截图（Coordinator 与 Implementer 均已查看，不等同负责人体验验收）：[确认来源](closeout/source-confirmation.png)、[原生模型菜单](closeout/native-model-selection.png)、[固定差异与验收](closeout/frozen-result-diff.png)、[已保存结果包](closeout/saved-independent-package.png)、[显式旧配置导入](closeout/explicit-legacy-import.png)、[两个真实 Worker 高亮](closeout/two-worker-process.png)、[集成后最终结论](closeout/integrated-acceptance.png)。

普通使用与空账户查看命令见 [稳定开发入口](../../../ao/CLAO.md#启动)。本次桌面验证从工作树根运行（先打开该开发入口，使 Vite 就绪）：

```powershell
Set-Location 'E:\Projects\clao-ao-native'
$env:PATH = 'C:\Users\Lenovo\go\pkg\mod\golang.org\toolchain@v0.0.1-go1.26.5.windows-amd64\bin;' + $env:PATH
$env:GOTOOLCHAIN = 'local'
$env:GOWORK = 'off'
$env:CLAO_CORE_PYTHON = 'E:\Projects\closed-loop-agent-orchestrator\clao\.venv\Scripts\python.exe'
$env:CLAO_NATIVE_BINARY = 'E:\Projects\clao-ao-native\.native-dev\ao-closeout-hidden.exe'
$env:CLAO_TEST_CLOSEOUT = '1'
$env:CLAO_DESKTOP_TEST_PORT = '7319'
$env:CLAO_SCREENSHOTS = 'E:\Projects\clao-ao-native\docs\reference\ao-native\closeout'
& 'C:\Users\Lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' ao/frontend/scripts/test-clao-desktop.cjs
```

此替身命令不同于普通使用；不导入真实账号。闭环路径由外部协议替身验证，不称真实模型验收。当前 `account_storage_unsafe` 的祖先 ACL 限制继续保留，未改检查或用户权限。NOT_RUN：真实账号/Key/登录/模型/套餐计费与质量评测；全部执行器组合；全量；smoke；发行/安装器；负责人完整体验。整体迁移/M4 IN_PROGRESS，正式入口和已发布 v0.2 不变。
