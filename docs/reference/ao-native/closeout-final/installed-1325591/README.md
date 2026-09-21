# 1325591 Windows 最终候选安装证据

2026-09-22，V03-NATIVE-CLOSEOUT / PR #49。候选版本 `0.3.0-rc.1`，来源提交 **`1325591e02cb3a091755189e20f4c80ca8fe992f`**。这些截图来自该提交实际 NSIS 安装后的 CLAO Native，与此前开发截图及 `installed-1002f8d` 中间版本分开保存。

唯一入口 `packaging/build-release.ps1` 从独立 clean HEAD 构建成功，manifest 纳入 2,847 个源文件。交付目录 `E:\Projects\CLAO-0.3-final-candidate-1325591` 仅包含安装器、顶层 `clao/` 便携 ZIP、原始 `SHA256SUMS.txt`、`SOURCE.json` 和中文 `WINDOWS-CANDIDATE.md`；全部按 builder 原清单复制并核对哈希。构建目录和日志独立保留，未发布或签名。

NSIS 实际安装至独立含空格测试目录。6,462 个已安装运行文件与候选运行清单逐项 SHA-256 一致；桌面、开始菜单快捷方式和卸载注册均属于 CLAO Native，官方 AO 文件及注册不变。首次辅助脚本的 45 秒等待不足；安装进程之后完成，重新获取前已退出，因此安装器退出码未采集，不能写成 exit 0。完整文件校验、真实启动和下列旅程均在安装完成后通过。

应用使用全新测试配置，PATH 只有 Windows、Git 和预先编译的离线执行器协议替身。Node/Playwright 仅驱动测试；应用未获得源码、开发 Python/Node/Go/Vite/venv 或 Codex 缓存。

- 单任务：GUI 打开普通目录 → Worker 替身 → 随包 Python Gate 导入同目录 `solution` → 独立 Verifier 替身 → DONE。GUI 下载 ZIP 后，在另一目录使用随包 Python 解压、Git 应用改动，同一 Gate 再次通过；原始目录文件及内容不变。
- 双 Worker：同一个整体图显示两个真实并发替身会话，两个节点均可选择并定位对应会话；模拟传输断连后清除活动声明，恢复后继续；两个子任务及父任务最终 DONE，集成 Gate、范围检查和独立最终 Verifier 通过。
- 显示：同一次已完成 Mission 在浅/深主题下分别检查 1440×900、960×900、1440×900 的 200% Electron 缩放，共六种；一个整体运行图，无横向溢出。保存测试模型连接但未调用真实服务。
- 卸载：NSIS 卸载退出 0，等待异步清理后应用目录、两个快捷方式及 CLAO 注册移除；163 个任务与验收证据文件哈希不变，官方 AO 文件及注册不变。

保留的三张最终截图均由实际 Electron `webContents.capturePage` 生成，未编辑：

- [双 Worker 执行与节点交互](installed-two-workers-active.png)
- [深色 200% 缩放](native-dark-1440-200pct.png)
- [浅色固定成果差异与导出](installed-result-diff.png)

本机完整脱敏证据在 `clao-closeout-evidence-20260921/installed-1325591/`，对应 `report.json`、六种显示截图及双 Worker 活动/断连/集成截图；同级保存 `installed-integrity-1325591.json`、`nsis-install-1325591.json`、`uninstall-report-1325591.json`、`delivery-1325591.json` 和构建日志。安装旅程全部为离线替身测试，不替代真实模型、两套干净 Windows 或负责人体验验收；本轮未重复此前无关负例。

| 产物 | 字节 | SHA-256 |
|---|---:|---|
| `CLAO-Native-0.3.0-rc.1-Setup-1325591e02cb.exe` | 137677784 | `7e5e309d96b4c75e6823ecb0c1394a1d2701976c62677648edca73d7b94e520c` |
| `clao-0.3.0-rc.1-windows-x64-1325591e02cb.zip` | 199483443 | `bb6f3fd5a151a526e9f2238cd60617aa6a9ee46f8b1faef3753b4cbda9228e4e` |
