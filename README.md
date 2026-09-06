# CLAO

Closed-Loop Agent Orchestrator

CLAO 是构建在 Agent Orchestrator（AO）上的本地闭环软件开发控制层。默认单Worker执行任务，通过确定性Gate、集成和Mission终局复核保存可检查结果。

**已发布：v0.2（Windows本地比赛版）。下一阶段：v0.3规划审核中，先修Bug，再优化用户体验和GLM/Kimi模型切换。规划中的能力尚未实现。**

## 使用已发布产品

前往 [v0.2 Release](https://github.com/zhaoshiyi4246/agent-orchestrator-AI-worker/releases/tag/v0.2)，下载附件 `clao-v0.2-4d3e8e6b5e70.zip`，不要把自动生成的Source code ZIP当作净化产品包。解压后进入 `clao/`，按其中README操作。

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

当前产品源码仍位于 `交付/closed-loop-v2/`；这是开发路径，release通过映射生成干净 `clao/`。不要复制一份新的v0.3源码，也不把历史来源目录打进产品。

本仓库为统一的发布与评审主线。队友补丁须按范围评审、验证并保留归属；不以Sync fork或整目录覆盖替代集成。
