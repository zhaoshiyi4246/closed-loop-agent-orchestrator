# CLAO Native 0.3 Windows 候选版安装说明

适用 Windows 10/11 x64。运行 `CLAO-Native-…-Setup-….exe`，选择仅为当前用户安装；随后从桌面或开始菜单的 **CLAO Native** 启动。也可解压便携 ZIP，打开 `clao/clao-native.exe`。本候选未签名，Windows 可能显示发布者提示。

应用自带运行环境，无需源码、Go、外部 Node/Python、venv、Vite 或 Codex 开发缓存。请另行安装 **Git for Windows** 和实际使用的编码工具（例如 Codex CLI），并完成该工具支持的账户登录。缺依赖时界面会明确提示；CLAO 不会静默安装工具或改写用户全局账户配置。打开本地项目后，新建任务、确认当前内容快照、填写验收条件和检查命令，再选择已就绪的工具与模型开始执行。

随包 Python 可直接运行 `python check.py` 并导入同目录模块。项目自己的其他依赖、编译器和测试工具仍须准备。验收通过后可查看固定差异并导出 ZIP，在独立目录应用；不自动写回原项目或推送远端。

数据默认位于 `%USERPROFILE%\.clao-ao`，与官方 AO 的 `.ao` 分开；安装身份、快捷方式及卸载入口均独立，候选版不接入官方 AO 更新。卸载移除应用、保留任务数据。回退前先退出 CLAO，备份完整数据目录、相关 Git 工作区和证据，再安装已验证的旧版；只备份数据库不足以恢复全部材料，不要直接用旧版打开不兼容的新数据。

候选目录中的 `SOURCE.json` 记录源码提交，`SHA256SUMS.txt` 提供安装器、ZIP 和说明的校验值。许可证保留在 `resources/third-party` 及各随包组件目录。构建成功不等于最终验收通过；真实模型/账户、两套干净 Windows 和负责人体验仍需分别记录，不以本机隔离测试替代。

开发者构建仍只使用 clean HEAD 的 `packaging/build-release.ps1 -OutputDirectory <仓库外新目录>`；`-Node/-Go/-Python` 仅指定构建工具。`build-root` 和构建日志是诊断材料，不属于交付文件；此工具不会自动发布。
