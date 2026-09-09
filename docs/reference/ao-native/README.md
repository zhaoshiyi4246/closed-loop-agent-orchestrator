# AO 原生底座集成证据

2026-09-09，Windows。本页记录当前迁移分支的直接验证，不代表真实模型、负责人完整体验或发布验收。

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

- **Codex 代表路径未准入**：AO v0.12.12 在隔离 Windows 账户目录报 `account_storage_unsafe` / `Codex account setup did not complete`。保留该场景并记为 xfailed，保持 UNKNOWN、不 materialize；没有绕过账户 ACL 或借用用户登录。这不影响已经验证的 OpenCode ACP 代表路径，但不能据此称全部执行器兼容。
- 较早一次过宽的 `TestBuild` 名称筛选带入上游 `TestBuildSourceHandoffRequestUsesCurrentNativeSessionContext`，在 Windows 原路径与 JSON 转义路径比较失败。该测试与函数未修改，仍保留；不把本次定向通过表述为上游全量通过。
- 首次 HTTP 测试把派生构建命名 `ao.exe`，触发旧离线夹具的防真实 AO 保护，9 个 setup error；使用同一派生构建的 `clao-ao.exe` 副本完成隔离测试，未移除该保护。桌面脚本先后修正上游 BaseWindow API 与返回项目后新建任务的导航定位；最终实际交互通过。
- **NOT_RUN**：真实账户/登录/API Key/模型/套餐计费；全部执行器与角色组合；完整 GUI 体验；全量回归；smoke；安装器/发行打包/发布。旧功能迁移边界见 [开发说明](../../../ao/CLAO.md)，不由旧 M0–M3 历史完成状态推定。
