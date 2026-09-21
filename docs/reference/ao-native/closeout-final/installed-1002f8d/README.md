# 1002f8d Windows 实际安装候选证据

2026-09-22，V03-NATIVE-CLOSEOUT / PR #49。来源提交为 `1002f8d59a2b9686be130625b19c937008681835`，版本为 `0.3.0-rc.1`。这是该提交真实安装后的证据；后续 ACL、恢复和协议修复尚未包含，不能冒充最终修复版本的验收。

唯一入口 `packaging/build-release.ps1` 从独立 clean HEAD 构建成功，生成 NSIS 安装器和顶层 `clao/` 便携 ZIP。NSIS 安装与卸载退出均为 0，安装器未签名。6,462 个已安装运行文件的 SHA-256 与候选清单一致，桌面和开始菜单快捷方式均指向独立 CLAO 可执行文件。

实际安装程序使用全新测试配置；PATH 只有 Windows、外部 Git 和预先编译的执行器协议替身。Playwright/Node 仅作为测试驱动，应用未获得源码、开发 Python/Node/Go/Vite/venv 或 Codex 缓存。真实普通目录 → Worker 替身 → 随包 Python Gate（`import solution`）→ 独立 Verifier 替身 → DONE → GUI 下载 ZIP → 另一目录 `git apply` 和同一 Gate 全链通过，原目录文件及内容不变。不是实际模型服务验收。

- [浅色 1440×900 / 100%](native-light-1440-100pct.png)：一个整体运行图及完整确定性/语义验收结论。
- [深色 1440×900 / 200%](native-dark-1440-200pct.png)：真实 Electron zoom，内容纵向滚动，无横向溢出。
- [已安装程序的固定成果差异](installed-result-diff.png)：真实产物与导出入口。

同一次 DONE Mission 还完成浅/深色 960×900 / 100%、1440×900 / 100% 与 200% 共六种显示检查，使用实际 `webContents.capturePage`。保存模型连接但未调用供应商。当前这组仅证明单 Worker 布局；最终安装版本仍需补双 Worker 分支与节点交互证据。

另一个独立安装副本注入旧 `python312._pth` 后，真实 Gate 因 `ModuleNotFoundError: No module named 'solution'` 停在 HUMAN（修复预算为 0），未生成固定结果、未运行最终 Verifier；原安装与交付候选未改。缺 Git/缺 coding tool 的安装 UI 分支均明确展示所需依赖，未点击安装依赖。

卸载等待 NSIS 异步清理完成后，应用目录、快捷方式及 CLAO 卸载注册均移除；46 个测试任务/结果文件哈希不变，官方 AO 可执行文件及卸载注册不变。两套干净 Windows、真实模型/账户和负责人体验验收仍不能由本机隔离测试替代。

本机外置证据目录：`clao-closeout-evidence-20260921/installed-1002f8d/`、`installed-pythonpath-negative-1002f8d/`、`installed-prerequisites-1002f8d/`，以及 `installed-integrity.json`、`uninstall-report.json`。先前构建失败、初次辅助脚本入口/终态预期错误均保留，未并入通过计数。

| 候选 | SHA-256 |
|---|---|
| `CLAO-Native-0.3.0-rc.1-Setup-1002f8d59a2b.exe` | `5e5e7679d6019be84facad7ed118c7946118b37c8f6a75f345be6c8eaf0ee0e9` |
| `clao-0.3.0-rc.1-windows-x64-1002f8d59a2b.zip` | `3d63928d77a5e9cbaf3a6b86aad0b23b162f7e97f4c0fde0f6aa1fb1c69366ba` |
