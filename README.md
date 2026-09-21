# CLAO Native

CLAO 基于 AO v0.12.12 的原生桌面应用，为编码任务提供范围检查、可执行验收、独立复核、有限修复和独立结果导出。

当前开发版本为 **v0.3.0-rc.1 候选，收尾验收进行中**。本分支继续 [PR #49](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/49)，尚未获准合并或正式发布。安装包生成、真实模型、Windows环境与界面验收的实际结果见 [验收记录](docs/reference/ao-native/README.md)，不以源码构建代替安装验证。

## 安装与使用

候选交付包含 Windows x64 安装器和便携 ZIP。安装后启动 **CLAO Native**；便携版解压后运行 `clao/clao-native.exe`。Python 验收核心及依赖随包分发，使用者不需要源码、Go、Node、Vite 或 Python venv。

系统需有 Git，以及所选编码工具和其有效登录；项目自己的测试工具和依赖仍按项目要求准备。安装位置、数据目录和支持前提见 [Windows 安装说明](packaging/WINDOWS-CANDIDATE.md)。候选版具有独立应用身份和数据目录，自动更新关闭。

1. 打开或创建本地项目。普通目录、空项目、无远端仓库及未提交改动均可作为确认后的来源。
2. 新建任务，选择原生编码工具和模型，启用“CLAO 闭环验收”，填写目标、验收条件、允许范围和检查命令，确认本次来源。
3. 需要 GLM/Kimi 语义角色时，在设置的“模型连接与迁移”中新建标准 API 连接并保存系统凭据，然后在任务角色选择中使用它。角色和来源随任务冻结。
4. 在任务详情查看执行和需要处理的请求；在原生 Chat 审批或补充要求。中断后只有可确认阶段可继续，未知结果先确认停止。
5. 查看固定结果、改动和验收，导出独立结果包；在匹配基线的副本上按包内说明应用补丁。

默认一个 Worker；显式选择双任务时只执行两个独立、无范围重叠的子任务，再汇合验收。共享修复预算不重置。结果留在隔离工作区，原项目分支和未提交内容保留。

## 模型与交付边界

| 路径 | 上游保留 | CLAO 接入范围 | 当前真实证据 |
|---|---|---|---|
| 原生 Codex | App Server、账号、模型、Chat | Worker及独立只读语义角色；来源/验收/恢复 | 协议替身完整旅程通过；现有登录daemon启动被客户端自动审批阻止，真实Worker尚未验证 |
| 原生 OpenCode | ACP、账号、模型、Chat | Worker与有明确只读权限的语义角色 | 生产daemon/协议替身旅程已验证；没有据此宣称真实服务通过 |
| BigModel 标准 API | 独立CLAO连接，不冒充原生执行器 | GLM-5.3/GLM-4.7建议型号，Planner/Auditor/Verifier | GLM-5.3实际参数与混合角色离线通过；真实凭据引用待确认 |
| Kimi 国内标准 API | 独立CLAO连接，不冒充原生执行器 | kimi-k3，Planner/Auditor/Verifier | 三个角色各一组真实正反质量对照通过；真实Worker混合完整旅程尚待验证 |
| 其他上游编码工具 | 原生目录、安装和账号入口 | 仅按已具备的协议与确定性权限准入 | 未逐一真实验证，不代表全部可用于自动语义角色 |

自定义型号需兼容所选传输，并由服务确认权限。标准 API 按量计费；不能将其视为 Coding Plan 套餐。未知用量或账单保持未知，不会静默改用其他供应商。

结果包包含完整文本补丁、相对文件清单、验收摘要和说明，支持 UTF-8 普通文本及已声明文件模式；不包含完整基线、项目依赖或凭据。二进制、链接和子模块等不支持对象会明确拒绝整包。旧配置与历史仅从用户明确指定的文件导入，历史只读。

## 开发与来源

开发入口为 [ao/dev-clao.ps1](ao/dev-clao.ps1)，操作与诊断见 [ao/CLAO.md](ao/CLAO.md)。`ao/` 保存原生底座与CLAO增量；`clao/`保留复用验收核心、历史实现和测试。旧Panel/Controller退出候选运行入口。

[AO v0.12.12](https://github.com/Untrivial-ai/agent-orchestrator/tree/v0.12.12) 的上游来源、[Apache-2.0许可证](ao/LICENSE)和组件归属保留。候选包包含第三方许可与源码版本说明。已发布的 [v0.2](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/releases/tag/v0.2) 附件及校验值保持原样。

唯一发行入口是 `packaging/build-release.ps1`，由 `release-manifest.txt` 从干净提交构建到仓库外，不自动发布。

- [当前任务与下一步](PLANS.md)
- [开发事实与已知限制](docs/PROJECT.md)
- [设计与任务台账](docs/V03_PLAN.md) · [验收卡](docs/V03_BACKLOG.md)
- [实施规则](AGENTS.md)
