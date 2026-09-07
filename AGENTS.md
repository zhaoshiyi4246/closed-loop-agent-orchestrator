# CLAO 项目实施规则

适用整个仓库。长期规则在本文件；当前任务在 PLANS.md；目标设计在 docs/V03_PLAN.md。更深层 AGENTS 只能补充局部规则，不得放松项目安全边界。`legacy/**` 中的 nested AGENTS 仅属于历史 snapshot，不是当前 `clao/` 或 `packaging/` 的实施规则。

## 开始任务

1. 阅读 docs/PROJECT.md（当前事实）、PLANS.md（唯一任务指针）、V03_BACKLOG 中对应卡以及 V03_PLAN 的相关节；无需每次读全部历史。
2. 检查 git status --short --branch、当前HEAD、工作区、任务允许范围和停止条件。
3. 再读当前调用路径与直接测试；不得仅按文件名或旧聊天结论判断现状。
4. 计划、源码与实测冲突时，报告证据和最小修订建议；不得把错误规划硬实现。

## 责任与修改权限

- 负责人决定产品范围、优先级、费用授权与发布；规划审计助手提供设计和评审。
- Codex负责授权卡内的实现选择、测试、诊断、PR和事实更新，不自行删除目标或变更架构决策。
- 常规低风险实现不需要逐行请示；范围变化、外部协议未知、凭据／破坏性操作和数据风险才停止。
- docs/V03_PLAN.md 的范围与决策变更需负责人批准；PLANS、BACKLOG、PROJECT可依据已验证事实最小更新。

## 固定架构与安全边界

以下是实施约束，包含 v0.3 待补齐的安全要求；当前实现和已知差距以 docs/PROJECT.md 为准，不以规则文字宣称功能已实现。

- 保留 MissionController + per-task ClosedLoop；StateStore 为逻辑运行状态权威；AO公开接口是Session/Worker/workspace外部事实源。
- AO 是当前执行后端，不是未来产品的强制用户前置依赖；独立项目/执行适配按后续授权卡实施，保留上述控制职责、状态权威及安全边界。
- Bus、Markdown、JSONL、前端缓存是投影，不变成第二控制面。恢复材料含Git和相关证据，不宣称state.db单文件足够。
- 默认单Worker；Observer和Gate是确定性程序。正常路径gate-first、Mission终局Verifier；Auditor/Verifier不直接控制Worker。
- Planner结果、确定性L0和用户override都通过受控程序执行，不要求每条消息调用Planner LLM。
- Schema之外必须校验关联、AC覆盖、结果一致性与确定性权限；模型PASS不能覆盖程序发现的失败。
- 未知外部动作结果先对账；无法确认不盲目重发。未确认Worker停止不materialize。
- 不自动push、写回用户main/master、reset、clean、restore或丢弃用户改动；批准命令前必须原始输入检查与精确授权。
- 路径先验证root containment，再glob；解析不明不授权。不在用户重要仓库执行破坏性测试。
- 本地Panel保持loopback；写接口、文件动作、HTML显示都需要各自安全边界。

## 模型与配置

- Codex是已有稳定默认，不是永久唯一供应商。本次v0.3规划包含GLM/Kimi语义adapter，范围批准后按任务卡顺序实施与验收。
- 不恢复旧全局llm_env、alias默认映射或改用户全局Codex/AO配置；Worker/harness单独准入。
- 一个有效配置入口；新Mission冻结无密钥快照。没有真实消费者的选项不能显示已生效。
- 不静默跨供应商fallback。真实API调用、费用和向新服务发送代码须有明确授权。
- Key只存OS安全存储/受控内存/环境变量引用；不得进入Git、localStorage、SQLite、Prompt日志、报告或发布包。

## 源码、发布与依赖

- 正式仓库：`zhaoshiyi4246/closed-loop-agent-orchestrator`。`clao/` 是唯一正式产品源码；不另复制一份 v0.3 源码。产品包顶层仍为 `clao/`。
- `packaging/build-release.ps1` 与 `packaging/release-manifest.txt` 是唯一发布工具和映射入口，从 clean HEAD tracked blobs 构建，输出目录必须在仓库外。
- `legacy/` 保存 v0.1、sidecar、demo 和旧开发资料，不进入产品；内部 `clao/src/loopcore/` 包不改名。`docs/` 保存当前事实与规划，`docs/reference/` 审计附件冻结。
- 发布边界唯一来源为 manifest；新 runtime 资源／依赖必须相应纳入、验证；开发工具不能混入 runtime。
- 已发布v0.2 tag、附件和checksum不可覆盖。不得自动Sync fork／覆盖队友整目录。
- 允许引入有明确必要性的jsonschema、HTTP或凭据薄依赖；禁止为方便建设新Agent、数据库、队列、网关或框架。
- UI默认沿用现有Web栈；Apple风格是层级与留白，不分发Apple字体/素材，不开公网。

## 测试与证据

- 执行节奏：实现→PR→外部审计→必要返修→合并并同步；阶段中不额外插入 smoke，全面测试与发布验证集中到收尾。合并仍须负责人授权，产品功能与安全边界不变。
- Bug任务保留产品级可重复负例和正向回归；阶段实现结束时集中做直接相关检查，不要求先红后绿报告或逐步重复全量测试。
- 代码任务：本阶段定向 Windows 回归、compileall、diff-check；完整回归、干净安装、打包及整体运行验收集中到 v0.3 收尾，未运行项如实注明。
- 纯治理文档：链接、路径、diff-check、产品blob未变；不跑pytest/live。
- UI/API任务：合同测试与浏览器状态/视觉测试；HTTP200不等于GUI通过。
- 真实模型/AO测试有次数/时长/费用上限，失败保留脱敏证据，禁止反复制造PASS。
- 不能将Linux测试、mock、源码推断、旧release live混称本次Windows产品验收。
- 438仅为v0.2历史测试计数；以后报告实际命令结果，禁止凑数量、删失败用例或弱化断言。

Windows已验证基线：从仓库根进入 `clao/` 产品目录，将 .venv\Scripts 前置PATH、src设为PYTHONPATH，再用本目录venv Python运行pytest/compileall。不得用无pytest的系统Python替代后改测试迁就。

## Git纪律

- 每个可验收切片一个分支/PR；不直接向main提交产品代码。
- 未明确授权不合并、不tag、不发布、不删除仓库。用户可在审计通过后明确授权Codex执行merge/pull。
- 网络步骤有界重试：最多20轮，每轮等待10秒；写失败先读远端状态判断是否已成功。认证失败、哈希冲突、dirty/divergence立即停止，不当网络重试。
- 不force push、reset --hard、git clean或强制覆盖同名tag/asset；特殊需求另行授权。
- 不修改用户已有未提交内容；从GitHub手动入库后先同步最新main再开实现分支。

## 输出与上下文

最终报告只需：任务ID、scope、commit/PR、测试分类/结果、NOT_RUN、残余风险、文档更新和下一步。不要重复整篇规划，不输出密钥/完整Prompt/隐私路径。

精确文件名：docs/PROJECT.md 是开发事实；runtime/.../project.md 是运行投影。不要创建第二份开发 project.md。Word/PDF是日期快照，持续进度只维护GitHub Markdown。
