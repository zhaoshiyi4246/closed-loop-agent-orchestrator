# CLAO

Closed-Loop Agent Orchestrator

CLAO 是构建在 Agent Orchestrator（AO）上的本地闭环软件开发控制层。默认单Worker执行任务，通过确定性Gate、集成和Mission终局复核保存可检查结果。

**已发布：v0.2（Windows本地比赛版）。v0.3 规划已批准，M0 COMPLETE，基线与目录整理人工审计 PASS；V03-F01 实现与 Windows 离线验证已完成，PR 交付因 GitHub 连接失败受阻（IN_PROGRESS；live 待授权）；后续先修Bug，再优化用户体验和GLM/Kimi模型切换。规划中的能力尚未实现。**

## 使用已发布产品

前往 [v0.2 Release](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/releases/tag/v0.2)，下载附件 `clao-v0.2-4d3e8e6b5e70.zip`，不要把自动生成的Source code ZIP当作净化产品包。解压后进入 `clao/`，按其中README操作。

当前验证环境为Windows、CPython3.12、Git、AO Desktop0.12.9和Codex CLI0.150.1/ChatGPT登录。bootstrap只管理Python venv，不替用户安装外部工具。Git-backed AO Project需要origin与有效remote-backed base；origin可为本地bare repo。

结果保留在 `runtime/<mission-id>/integration`，不自动写回main/master，不自动push。当前版本只按支持环境和指定路径验证；已知权限、结果一致性和GUI证据问题列入v0.3首批修复，重要项目应备份并保留人工监督。

## v0.3 开发方向

先修复授权、终局判断、Git路径和证据、本地API及停止边界；再提供任务导向、iPhone风格层级的简洁GUI、结果导出，以及按角色明确的GLM/Kimi语义模型配置。Worker供应商切换需独立能力验证，不能仅改模型名。

## 开发上下文

- [当前架构与事实](docs/PROJECT.md)
- [当前执行任务](PLANS.md)
- [v0.3规划设计](docs/V03_PLAN.md)
- [任务与验收台账](docs/V03_BACKLOG.md)
- [原审计报告](docs/reference/CLAO_v0.2_audit_20260905.pdf)
- [Codex实施规则](AGENTS.md)

当前唯一正式产品源码为 `clao/`；发布工具位于 `packaging/`，历史来源归档在 `legacy/`。内部 `loopcore` 包与已发布 v0.2 的运行行为保持不变。

```text
closed-loop-agent-orchestrator/
├─ clao/          当前产品、测试、bootstrap
├─ packaging/     release builder 与 manifest
├─ legacy/        历史 v0.1、sidecar、demo 和开发资料
├─ docs/          当前事实、v0.3 规划与 reference
├─ AGENTS.md
├─ PLANS.md
├─ README.md
└─ .gitignore
```

开发验证：进入 `clao/`，运行 `bootstrap.ps1`，按 [产品自检说明](clao/README.md#本地自检) 运行 pytest 和 compileall。

发布彩排：在 clean committed branch HEAD 上运行 `packaging/build-release.ps1 -OutputDirectory <仓库外的新目录>`。builder 只读取 HEAD 中 manifest 指定的 tracked blobs，产品 ZIP 唯一顶层仍是 `clao/`；不包含 `legacy/`、治理文档、runtime 或 `.venv`。这是本地构建，不自动创建 GitHub Release。

[M0 迁移证据与边界](docs/V03_M0_EVIDENCE.md) 记录路径、内容 allowlist 和验证结果。

本仓库为统一的发布与评审主线。队友补丁须按范围评审、验证并保留归属；不以Sync fork或整目录覆盖替代集成。
