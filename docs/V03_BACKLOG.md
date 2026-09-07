# CLAO v0.3 任务与验收台账

版本：0.3-plan-r1 · 2026-09-06。状态：已批准 / IN EFFECT。DOC-00、F01–F05 已完成（DONE），M1 修复冻结为 `COMPLETE`；当前任务 R01 为 `IN_REVIEW`，M2 `IN_PROGRESS`；其余功能卡状态见下表，原报告的发现不等于已复现或已修复。

设计以 [V03_PLAN.md](V03_PLAN.md) 为准。当前唯一任务由根目录 [PLANS.md](../PLANS.md) 指定。本文件保存每张卡的详细状态和证据，PLANS 不重复整张台账。

## 状态与记录格式

`TODO → IN_PROGRESS → IN_REVIEW → DONE`；外部前提阻塞为 `BLOCKED`。DONE 需要代码／测试／范围审计符合该卡完成定义；仅生成 PR 不等于 DONE。需要 live 的卡可先写 `IN_REVIEW，offline PASS / live PENDING`，不能先写全部通过。

每卡更新只追加：日期、执行基线、分支、commit/PR、测试环境与命令、red/green结果、live/GUI证据等级、风险、下一步。不得复制大日志、用户Prompt、凭据或真实机器路径。调整范围／依赖由负责人批准，在 V03_PLAN 决策记录说明。

## A01—A12 映射

| 原编号 | 原报告性质 | 本版落点 |
|---|---|---|
| A01 审批／包含性 | 源码＋隔离负例 | F02；安全规则不能被GUI绕开 |
| A02 终局一致性 | 源码＋判定条件复演 | F01；P01/P02沿用 |
| A03 Git路径／取证 | 源码＋临时Git复演 | F03 |
| A04 Gate查询／错误显示 | 源码＋SQLite复演 | F04；U02 |
| A05 本地API／HTML | 源码＋字符串复演，浏览器可达性待测 | F04 |
| A06 指令消费 | 源码／异常窗口 | R02 |
| A07 外部动作／kill | 源码推断，需故障注入验证 | F05 |
| A08 Stop/Resume | 源码语义不一致 | R02；U02 |
| A09 双任务／基线 | 静态调用顺序风险，需验证 | R02；不能支持的依赖计划明确拒绝 |
| A10 配置／性能 | 源码消费者差异 | R01 |
| A11 多模型／证据 | 现状差距与设计任务 | F01；P01/P02/P03 |
| A12 交付／维护 | 现状差距与设计任务 | U03；Q01 |

## 总表

| ID | 阶段 | 标题 | 依赖 | 状态 |
|---|---|---|---|---|
| V03-DOC-00 | M0 | 规划入库与基线核对 | 负责人批准 | DONE |
| V03-M0-LAYOUT | M0 | Repository layout consolidation 与本机副本整理 | DOC-00 | DONE |
| V03-F01 | M1 | 完整契约与终局一致性 | DOC-00 | DONE（PR #32 审计 PASS / merged） |
| V03-F02 | M1 | 审批命令与路径包含性 | DOC-00 | DONE（PR #33 审计 PASS / merged） |
| V03-F03 | M1 | Git路径、产物规则与只读取证 | DOC-00 | DONE（PR #34 审计 PASS / merged） |
| V03-F04 | M1 | Gate查询、本地API与安全渲染 | F01的结果字段约定 | DONE（PR #35 审计 PASS / merged） |
| V03-F05 | M1 | 停止确认与未知外部动作保护 | DOC-00 | DONE（PR #36 再次审计 PASS / merged） |
| V03-R01 | M2 | 有效配置与阶段诊断 | F01/F04 | IN_REVIEW |
| V03-R02 | M2 | 指令回执、取消恢复、固定基线 | F03/F05/R01 | TODO |
| V03-U01 | M3 | iPhone风格界面骨架与状态夹具 | G1；R01/R02字段设计 | TODO |
| V03-U02 | M3 | 完整任务GUI与数据接线 | U01/R02/F04 | TODO |
| V03-U03 | M3 | 结果中心与独立导出 | U02/F03 | TODO |
| V03-P01 | M4 | 模型配置／凭据与GLM语义后端 | F01/R01/F04 | TODO |
| V03-P02 | M4 | Kimi语义后端与切换评测 | P01 | TODO |
| V03-P03 | M4 | 第二Worker能力准入决策 | P01/P02；AO官方契约 | TODO |
| V03-Q01 | M5 | 新Windows产品验收与发布候选 | G1—G4 | TODO |

G1=F01—F05；G2=R01—R02；G3=U01—U03；G4=P01—P02及P03有记录的支持/拒绝决策；G5=Q01。

## V03-DOC-00｜规划入库与基线核对

- 目标：把负责人批准的规划变成唯一可查询上下文，先不实施产品。
- 范围：AGENTS、PROJECT、PLANS、V03_PLAN、V03_BACKLOG、根README、原审计PDF引用。不得改产品、manifest或builder。
- 检查：main最新SHA；已发布tag不变；7个预期文件；链接有效；不存在另一份开发project.md；旧治理历史可由固定提交访问。
- 完成：负责人批准的 7 项规划／治理文件及附件已进入 main，产品 blob 变更=0；功能下一任务为 F01。本次入库由用户直接提交，Git 历史为依据，不声称存在文档合并 PR。
- 状态：DONE；2026-09-06，`DOC00_BASELINE_PASS`。
- 证据：main `3a9ea27468915eb9571611bcca10962e7a732fb0` 相对发布源码 `4d3e8e6b5e70bab868b2eef0d28c7742dea044ba` 的差异恰为预期 7 项；106 个产品 blob、builder／manifest 均一致；12 个当前 Markdown 中 17 个本地链接有效。
- 源码核对：Panel／CLI 共用 build_runtime；Controller／ClosedLoop、Store、AO、投影边界与 PROJECT 一致；Stop、attach、弱 Schema 与 best-effort kill 缺口仍存在，不将规划要求写成已实现。
- 规则核对：根规则的安全和模型条款属于实施约束；PROJECT 记录当前缺口。历史 nested AGENTS 只适用历史目录；本次 M0 追加授权见 V03_PLAN D09，不启动 F01。

## V03-M0-LAYOUT｜Repository layout consolidation

- 状态：DONE；2026-09-06；分支 `task/v03-m0-repository-layout`；[PR #31](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/31) 人工审计 PASS；M0 COMPLETE。
- 范围：Git rename、必要路径／名称适配、当前文档与 canonical URL、本机重复副本分类整理。
- 验收：完整 pytest、compileall、当前 Markdown 本地链接、diff-check、clean committed HEAD builder、artifact file set／hash／hygiene；唯一 canonical development clone；独立 PR 与人工审计 PASS。
- 边界：不修 A01—A12，不改 runtime／依赖／loopcore 包名，不改变已发布 v0.2；F01 保持 TODO。
- 证据：`9344bff` 关闭 DOC-00；`68bf256` 迁移 308 文件且零内容增删；`667ce95` 适配 manifest／注释／治理路径。定向 88 passed；全量 438 passed in 105.61s；compileall、diff-check 通过；收尾复核 13 个当前 Markdown 的 23 个本地链接全部有效。
- 构建：clean HEAD `667ce95deb2b4baae2a22fcfa394c4c2b5e55d4d` builder exit 0；92 个产品文件 + checksum，唯一顶层 clao/；逐文件 SHA-256、HEAD blob、hygiene、secret/path scan PASS；产品文件集变化 0。已验证的后续文档提交 `06bfb67` 构建结果记录于 PR 与本机证据；本次最终收尾仅修正文档状态，产品与发布工具 blob 不变，沿用原验证结论。
- 整理：唯一指定开发 clone 已建立；旧源码 ZIP 全部 25 个 blob 与 legacy 相同；发布包与设计快照归档，旧测试 worktree 用 Git move 保留；历史 refs 和 runtime 完整保存。AO 仍引用的 v0.1 clone 原地保留，原工作区空目录因占用／清理审查拒绝保留，不虚报桌面完全清空。详见 [M0 证据](V03_M0_EVIDENCE.md)。

## V03-F01｜完整契约与终局一致性

- 状态：DONE；2026-09-06 负责人确认外部审计 PASS、无代码修改问题；[PR #32](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/32) 已 rebase merge 到 main，合入提交 `144c599a022659f6264762e47a54ca296622f751`。实际 base `26b02e9d3e1d72cde3b29143d96ed4e096391249`；原代码提交 `bf4601bb3d4bcc119349e20e99a2689ddb7778aa`（rebase 后 `fae3e5c`）；分支 `task/v03-f01-contract-consistency`。

- 对应：A02、A11。落点：mission_contracts.py、verifier.py、mission.py、必要Provider/schema/requirements/bootstrap与直接测试；以实际调用链为准。
- 工作：先复现顶层PASS但AC FAIL等负例；移植或重做必要的完整validator，评审队友补丁，不整目录覆盖。取消弱fallback；强制关联、覆盖、有限数值、结果一致性和证据截断语义。
- 必测：错误verify/task/mission ID；AC缺失/重复/未知/UNVERIFIABLE；anti-gaming FAIL；畸形列表；NaN/Infinity；证据缺口。正常合法PASS仍可到MISSION_DONE。
- 完成：负例全部不能成功；本地protocol failure与语义FAIL区分；同一规范供新供应商复用；Windows离线和受控Codex角色smoke按变更影响执行。
- 不做：更换默认模型、动态高风险Verifier、放宽Gate。
- 红证据：改产品前，Windows 原始 base 上 `python -m pytest tests/test_f01_contract_boundary.py -q --tb=line` 得到 **17 failed / 65.25s**，多类非法结果实际进入 MISSION_DONE；随后从同一 base 的 Git archive 在仓库外重跑扩展产品集（含离线进程拦截），**33 failed、1 passed / 284.50s**，覆盖终局、历史重放、语义 FAIL 重试与协议耗尽。均使用本仓库 CPython 3.12 venv；非 Linux、非 live。
- 实现：必需 `jsonschema==4.25.1`；启动检查本地 Schema；共享 JSON/Schema/有限数值/关联边界；拒绝错误输出而不补 ID、改列表或改结论。Mission final 显式以 Mission ID 填充现有 VerifierResult.task_id；MissionPlan 维持既有 mission_id 关联字段，不另造协议。
- 终局：Controller 再查完整 AC 恰好一次、PASS 与分项/anti-gaming 一致性；复用现有 scope checker，Gate/范围/integrity 失败先阻断。Task 历史和 Mission final 重放都校验 Schema、关联、覆盖和保存的输入摘要；损坏/缺字段/缺验证上下文进入人工处理，不改写历史终态或伪补成功。
- 证据：Git diff 的角色调用取消上游裁剪，Gate 保留完整 stdout/stderr；实际模型输入按部分携带 content、original_length、sha256、truncated/missing、omitted_chars。Verifier 的 diff/Gate 各限 6000 字符，整体 CLI Prompt 限 64000；关键缺口进入明确处理。Auditor 可对带缺口标识的材料作非 PASS 诊断，不能据此通过。
- 错误边界：纯协议输出最多 2 次，耗尽由 Controller 记录 PROTOCOL_FAILURE 并 HUMAN；合法语义 FAIL 原样记录、不重试。纯传输按原 Controller 最多 3 个连续失败 tick；混合协议/传输最多 6 次调用（decomposition 更早停止）。成功重试也保留先前错误类别与响应摘要，不保存完整 Prompt；不新增跨供应商 fallback。
- 测试维护：保留原用例意图并修正静态错误 ID、空 evidence 等非法夹具；旧“强制降级 PASS、空列表纠正、刷新合法 FAIL、Provider 伪造 HUMAN”预期替换为显式协议拒绝和合法 FAIL 原样留存；状态及 SQLite 证据由 `test_f01_contract_boundary.py`、`test_f01_schema.py` 与原回归共同覆盖。离线 conftest 拦截真实 AO/Codex 进程启动。
- Windows 实测：CPython 3.12.7；pytest 9.1.1；jsonschema 4.25.1。最终定向 **76 passed / 100.95s**；完整 `tests` **514 passed / 177.68s**；均 0 failed、0 skipped；加严原语义 FAIL 状态断言的 4 项回归另跑通过。compileall、diff-check 通过；7 个当前治理 Markdown 的 22 个本地链接有效。干净包同版本 venv 全量 **514 passed / 183.21s**（0 failed、0 skipped），包内 compileall 通过；上述为既有 Windows 离线证据，合并收尾未重跑。
- 命令：从 `clao/` 将 `.venv\Scripts` 前置 PATH、`src` 设为 PYTHONPATH，用 `.venv\Scripts\python.exe -m pytest tests/test_f01_contract_boundary.py tests/test_f01_schema.py -q`、`-m pytest tests -q`、`-m compileall -q src panel run_mission.py`；仓库根 `git diff --check`。
- 安装/打包：从 clean committed `bf4601b` 用原 `packaging/build-release.ps1 -OutputDirectory <仓库外新目录>` 构建，exit 0；96 个产品文件 + SHA256SUMS，顶层 clao/。96/96 checksum 与独立 HEAD archive export 逐字节一致；原始 blob 比对为 2 个完全相同、94 个仅 Git `core.autocrlf=true` 导出的 CRLF 差异，未把换行差异虚报为 raw blob 相同。manifest 前缀已覆盖新 helper/测试；无 .venv、runtime、日志或密钥，链接/敏感内容扫描通过，未改 builder/manifest。
- 干净安装：新目录解压上述 ZIP，运行包内 `bootstrap.ps1`，exit 0；创建新 CPython 3.12.7 venv，安装并验证 PyYAML 6.0.3、pytest 9.1.1、jsonschema 4.25.1 及本地 Schema，然后按同一 PATH/PYTHONPATH 方法执行包内全量与 compileall。代码包 ZIP SHA-256：`54866c30de5fe3eaa2e0cb04b61b34d43b8919f60bc5577265e3e20e5aa12522`。本地构建彩排，不创建 tag/Release；后续仅治理文档变更以产品 blob/包文件等价核对。
- NOT_RUN：真实角色 smoke、AO Worker、真实 Mission、GLM/Kimi、GUI live，未执行。2026-09-06 负责人明确本阶段不要求额外 live smoke，确认既有 Windows 离线、干净包与构建证据有效，并授权审计 PASS、合并后将 F01 标为 DONE；不将未运行项写成 live PASS。
- 残余边界：F02/F03/F05/R02 的底层审批、Git 路径解析/取证、外部动作停止与生命周期问题仍在原卡范围；本修复只阻断已有确定性失败。证据过长保守进入人工处理；重放要求输入摘要相同（Gate 输出变化亦会阻断），不声称模型真实性已验收。
- 来源：阅读 S09 固定 `7b30184ff19922dd6af03c874ac2ba9c6c5dd77e` 候选说明作为评审输入；本次独立实现，未移植队友源码、命名、发布工具或历史验收结论。

- 历史交付阻塞（已解除）：2026-09-06，提交 `65e9922` 后 push 共 **20 轮**，含首次；轮间等待 10 秒。均为连接重置或 TCP443 无法连接；每次写入失败后通过 GitHub API 核对，当时任务分支仍不存在、PR 未创建。达到授权上限后停止网络操作并以 `205eb3b` 记录，保留本地分支与包。
- 历史恢复交付：同日用户确认 TCP443 恢复并授权新一轮最多 20 次推送；第 **1** 次推送成功并创建 PR #32；文档追加提交在该轮第 **8** 次推送成功，最终远端 head 为 `ff47fc90d8298a2034764f7ab7fee1272597947c`，当时状态 IN_REVIEW。该次只更新 PLANS、BACKLOG、根 README，产品及发布工具与已验收 `bf4601b` 的 blob 相同；治理链接及 diff-check 通过，未重跑 pytest/live；当时未合并或标 DONE。
- 合并收尾：2026-09-06 按负责人授权完成 rebase merge，合入 tree 与已审计 PR head 完全相同；本地 main 正常 fast-forward 到合入提交。仅更新 PLANS、BACKLOG、根 README 与 PROJECT 的状态及当前实现事实；产品/发布工具 blob 未变，沿用既有验证，不重跑 514 项测试或构建。F01 DONE；下一任务 F02 TODO，未开始实现；未创建 tag 或 Release，已发布 v0.2 不变。

## V03-F02｜审批命令与路径包含性

- 状态：DONE；2026-09-06 负责人确认外部审计 PASS、无需返修；[PR #33](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/33) 已 rebase merge 到 main，合入提交 `62f5851a72490074a6cb6030803275a9846d9f45`。base `409127d598d678dc98a2f6e6cb3087d9d950cd16`，原实现提交 `6717c453e6aad8730b180295ae87241749110201`（rebase 后 `1dc392f`），分支 `codex/v03-f02-approval-boundaries`；F01 保持 DONE。
- 对应：A01。落点：ClosedLoop生产审批路径、approvals和相关测试。
- 工作：先查真实AO请求结构，再规范原始输入与路径；解析不明不授权；exact module/argv、不用双向前缀和先折叠换行。
- 必测：报告所有predicate负例；允许**仍不能越根；symlink/junction；中文空格路径；不存在文件；restore/checkout等危险动作不自动允许。
- 完成：隔离产品级负例与正常 Edit/精确 Gate 回归成立；拒绝原因和人工审批均可追踪。按本轮授权，检查集中在实现结束时，不要求先红后绿报告；完整回归/安装/打包与整体运行验收留到 v0.3 收尾，本轮不执行 smoke、真实模型或 AO Mission。
- 不做：执行危险命令验证“是否真的删除”；自造沙箱框架；用户重要仓库测试。
- AO 依据：只读核对官方 v0.12.9 固定源码 `4cbb4b6ced1ad93f79641a2347d2342f1ffd218a` 的 [Codex 审批转换](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/adapters/chatdriver/codexappserver/conversation.go)、[ACP 工具审批](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/adapters/chatdriver/acp/client.go) 及 conversation DTO/Controller；使用 requestId、原始 rawCommand/cwd、subjectKind/toolKind/input 和实际 offered allow_once ID，不硬编码所有供应商都返回 allow；未启动 Worker/模型获取样例。
- 实现：ClosedLoop 和保留的 AutoApprover 共用同一策略，删除旧前缀/多命令/通用 pytest 与 Git 写操作白名单。文件先按 AO Worker workspace 与请求 cwd 严格解析已有父目录、链接/junction，再检查词法及实际相对路径；forbidden 优先，空 allow 不授权，解析失败不回退 glob。命令检查原始控制字符，完整 argv 与 cwd 匹配 Gate；保留有限 shell 包装/已确认 cd 前缀及参数受限的查看操作。
- 记录：沿用 counters 和 processed_events，按 task/session/request 去重；记录目标路径、请求/命令摘要、原因、所选单次选项和是否需人工。原请求通过 AO conversation ID 对应，不复制文件正文或命令密钥；拒绝项留 pending，正常任务不因此立即失败。resolve 未确认不自动重发；未新增审批表/控制层或配置。
- Windows 定向：CPython 3.12.7；在 `clao/` 将 `.venv/Scripts` 前置 PATH、`src` 设为 PYTHONPATH，使用本目录 venv Python 执行 `-m pytest tests/test_approvals.py tests/test_approvals_bridge.py tests/test_approval_block.py tests/test_gate_first_completion.py tests/sidecar_port/test_budgets.py tests/test_ao_runtime_portability.py -q -rs --tb=short`，最终 **200 passed、1 skipped / 19.42s**；变更的 approvals/closed_loop/ao_adapter 三个源码 compileall 通过，diff-check 与治理链接通过。真实 Windows junction 越根/禁止目标及 ClosedLoop 回归通过；危险命令只作为字符串判断，未执行。
- NOT_RUN / 边界：原生 symlink 创建测试因 Windows 权限不足 skipped，未修改系统设置；本轮未跑完整回归、干净安装、打包、smoke、真实模型/AO Mission。AO v0.12.9 的 Codex fileChange 审批不暴露完整文件目标，明确留人工；未知工具/格式、复杂 shell、Git 写操作留人工。路径校验发生在审批时，不承诺跨 AO 执行的原子文件系统保证；F03/F05 等后续卡范围未扩展。
- 合并收尾：合入 tree 与已审计 PR head `89be6f7e15e053ef0407afddc491dbefd083ef6a` 完全相同，本地 main 正常 fast-forward 同步。仅更新 PLANS、BACKLOG、根 README 与 PROJECT；产品及发布工具 blob 未变，沿用上述 200 passed / 1 skipped 证据，不重跑测试、构建或 live。下一任务 F03 TODO，未开始实现；未创建 tag/Release，已发布 v0.2 不变。

## V03-F03｜Git路径、产物规则与只读取证

- 状态：DONE；2026-09-07 负责人确认再次外部审计 PASS，已提交 artifact 交付缺口闭环、无其他返修项；[PR #34](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/34) 已 rebase merge 到 main，合入提交 `35a67d07ae196368434fbd83a95693b288c6bc6e`。base `3af98d46e3495aa0154f8701152a11274b42a7c2`，已审计 head `451daef6aff7a1039f0b5d5ec1b73e988d5ea9c9`，原实现提交 `95b09b6dd308b84f18f7aa1c44e395fc7ac98c47`，分支 `codex/v03-f03-git-evidence`；F01/F02 保持 DONE。
- 对应：A03，关联A09/A12。落点：worktree、mission_gate、mission及调用者。
- 工作：无歧义路径解析；rename old/new；精确artifact规则；不改index取untracked diff；统一baseline采证完整性；Final确定性scope。
- 必测：rename/copy/delete/untracked/staged；空格中文控制字符；data.pyconfig/.coverage_policy.py不能误过滤；cache允许；采证异常也不得破坏index。
- 完成：Git before/after内容和index校验；非允许路径不能被模型PASS覆盖；正向materialization不加入cache。
- 不做：改变用户ignore、强制add、自动reset/checkout、重写Git历史。
- Git 依据：本机 Git 2.55.0.windows.3 随附 git-diff / diff-format、git-ls-files、git-commit 文档及隔离仓库实测；不根据面向人的 quoting 推断路径。
- 改动事实：严格 NUL name-status / index 解析；committed（冻结 base 与 HEAD 两端点）、staged、unstaged / untracked 分层取并集，rename/copy 同时保留来源与目标，删除保留原路径。JSON 路径列表补充 diff 展示；空 allow 不授权。Final scope 与 Verifier 使用同一完整路径集合，ClosedLoop 沿用同一 helper。
- 只读与 artifact：临时 index / objects 均位于仓库外，保留原 index 的 staged 事实；add -N 只作用于临时 index，异常不 reset/restore 真实仓库。禁用自动 index refresh、fsmonitor、取证 hook、外部 diff/textconv 与 clean/process 程序；不修改 ignore/exclude。artifact 只按目录段、明确后缀或 coverage 数据文件格式匹配；复制到 cache 不把未变来源算作修改，移入 cache 的源码删除仍可见。
- baseline / materialization：基线复用 IntegrationGate 的 require_clean、before/after 完整性和既有 Gate 记录；旧/损坏/不匹配的基线不提供红测豁免，采证完整性失败进入 HUMAN。main HEAD 无法确认时不回退 Worker HEAD。materialization 仅 add 实际可暂存用户路径，commit --only 精确提交用户净改动；已暂存 cache 保留在 index，但不随提交进入交付，不重写既有 Worker 历史。
- 审计返修：Mission 使用 dispatch 时已有 frozen base，把 artifact 条目精确恢复为基线的 blob/mode、保留 Worker HEAD 的全部非 artifact 条目；通过仓库外临时 index 形成追加的交付 commit 对象，并 fetch/merge 该明确 SHA。已被 Worker commit 的新 cache 不进入最终 integration 树；基线 cache 的修改/删除还原为基线内容。原 Worker 提交仍为祖先，历史中的 artifact blob 不清除；该过滤步骤不移动 Worker ref、不改其 index/cache 或 ignore/exclude。基线缺失/损坏、构造失败或基线 cache 与普通文件的目录冲突进入 HUMAN，不回退 merge 原始 HEAD。
- 返修验证：同一 Windows 产品 venv，`-m pytest tests/test_f03_git_evidence.py tests/sidecar_port/test_worktree_multi.py tests/sidecar_port/test_mission.py tests/test_final_gate_baseline.py tests/test_mission_gate.py -q -rs --tb=short` 最终 **145 passed / 210.22s**，0 failed / 0 skipped。新增 17 个场景含实际 Mission materialization/integration、Worker 先 commit 源码和 cache、基线 cache 未改/修改/删除的精确 blob/mode、pending 源码和 staged/untracked cache、缺失/损坏基线及构造异常、文件/目录冲突、中文/Tab/换行树路径。首次集中检查的两个控制字符用例暴露 Windows Git 静默跳过路径，已修复并保留断言；仅在不检出文件的临时 index 中设置 protectNTFS=false，真实仓库设置与 checkout/merge 保护不变。`-m compileall -q src/loopcore/worktree.py src/loopcore/mission.py tests/test_f03_git_evidence.py tests/sidecar_port/test_mission.py`、diff-check、2 个变更文档的 8 个本地链接通过。沿用下述历史 F03 证据；本轮 NOT_RUN 同卡末边界。
- Windows 检查：CPython 3.12.7；产品 .venv/Scripts 前置 PATH、src 为 PYTHONPATH，均在 clao/ 使用 .venv/Scripts/python.exe。主集合 `-m pytest tests/test_f03_git_evidence.py tests/sidecar_port/test_worktree_multi.py tests/test_mission_gate.py tests/test_final_gate_baseline.py tests/test_cluster7_audit.py tests/sidecar_port/test_mission.py tests/test_gate_first_completion.py tests/test_f01_contract_boundary.py -q -rs --tb=short`：**188 passed / 323.88s**。
- 最终加固复查：隐藏 index 标志加固后，前述前 4 模块同参数 **110 passed / 162.69s**；统一 Git 环境隔离后，`-m pytest tests/test_f03_git_evidence.py::test_git_environment_cannot_redirect_reads_or_materialization tests/sidecar_port/test_worktree_multi.py -q -rs --tb=short` **21 passed / 23.22s**。均 0 failed / 0 skipped，集合有重叠不累计；`-m compileall -q src/loopcore/worktree.py src/loopcore/mission.py` 通过。
- 证据边界：隔离临时 Git 仓库验证真实 HEAD、index 字节、staged 条目、用户文件内容，异常还比对 .git 文件集/内容；覆盖 split index、取证 hook/filter 不执行。Windows 禁止检出的控制字符文件名用真实 Git tree/commit 对象验证，未冒充本机可检出路径。Git copy 相似度用于端点事实，不宣称追踪任意历史复制意图；隐藏 index 标志、未合并条目、当前 submodule index、无法解析/读取的状态返回未知。多次 Git 采样不承诺跨并发 Worker 写入的原子快照；F05 停止确认、R02 生命周期仍在原卡范围。
- NOT_RUN：完整全量回归、干净安装、打包、smoke、真实 AO Mission / 模型、GUI，按授权留到 v0.3 收尾；本次合并收尾也未重跑 145 项定向测试或 compileall。未创建 tag/Release，未开始 F04。
- 合并收尾：合入 tree 与上述已审计 head 完全相同，本地 main 正常 fast-forward 同步；仅更新 PLANS、BACKLOG、根 README 与 PROJECT 的状态和当前事实，产品及发布工具 blob 未变，沿用既有验证。文档 diff-check、4 个变更文档的 20 个本地链接及产品 blob 核对通过。下一任务为 F04 TODO，本轮未实施 F04/F05/R01/R02，已发布 v0.2 不变。

## V03-F04｜Gate查询、本地API与安全渲染

- 状态：DONE；2026-09-07 负责人确认外部审计 PASS、无需返修；[PR #35](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/35) 已 rebase merge 到 main `c51ccd155f7ab6c226454846c9e1f1fff146956d`。已审计 head `fddf87a3237dbde1cc493dbc08963ee4b3b9bdca`；原 base `9a55a6c20f8828246723d66e18c91dbc4a23e122`，分支 `codex/v03-f04-panel-boundaries`，原产品提交 `3d1e693b5f9bef6eea926c4bbb9ef12383762302`；F01/F02/F03 保持 DONE，F05 TODO。
- 对应：A04、A05。落点：StateStore查询、Panel server/index及新直接测试。
- 工作：专用Gate DTO；command/integrity/scope/overall分别表达；数据库异常保留read_error；完整错误字段。Host/Origin/JSON/nonce；id与文件路径包含性；安全DOM渲染。
- 必测：真实SQLite Gate row到/api/state到页面；exit0+integrity失败显示失败；无记录与读失败不同；跨源请求、非法Host、缺token、穿越、引号、双击写请求。
- 完成：离线API/浏览器合同全绿；loopback不变；不会因错误toast消失而丢失根因。
- 不做：美化大重构、公网访问、让客户端自行裁决PASS。
- Gate：复用 `gate_runs`，仅新增可空 `assessment_json`；IntegrationGate 记录 command/integrity，Controller 将实际 scope 结论写回同批记录 ID，标识 task/baseline/final。专用只读查询保留旧表兼容；历史缺字段为 unknown，SQLite/损坏记录为 read_error，不伪装为空记录或 PASS。无加载任务为 not_run，已加载库无记录为 no_records；命令尚未执行单独为 command not_run。exit=0 不能覆盖 integrity/scope failure。
- Panel：常驻显示 Mission reason、runner/read error、alert summary/description/error/reason 及 Gate 原因/完整输出；动态内容用 DOM/textContent、受限状态 class 和安全属性赋值，保留中文、引号与长错误。写动作在单页面内 pending 去重，任务启动/续跑/查看共用锁；不自动重试写请求。
- API：仅监听 127.0.0.1；Host 限实际端口的 127.0.0.1/localhost，POST 必须精确同源 Origin、UTF-8 JSON、每次 Panel HTTP 服务启动随机生成的内存 nonce（页面/script nonce 和请求头，不进 URL/日志/任务数据）。严格 JSON/framing 与大小限制；Windows 分段到达的被拒请求有界排空请求体，保留明确错误响应，不先执行动作。页面附 CSP/no-store 等响应头。
- 路径：HTTP mission_id 限 1–128 位 ASCII 字母/数字/下划线/连字符并排除 Windows 保留设备名；校验 runtime/tasks、存档 mission_id 一致性及解析后的文件包含性，拒绝穿越、绝对路径、异常编码和越界 junction。`/api/file` 仍仅允许 memory.md/project.md。
- Windows 定向：从 `clao/` 前置 `.venv\Scripts` 到 PATH、`src` 到 PYTHONPATH，以本目录 CPython 3.12.7 venv 执行 `python -m pytest tests/test_f04_panel_boundaries.py tests/test_panel_worker_contract.py tests/test_mission_gate.py tests/test_gate_first_completion.py tests/test_final_gate_baseline.py tests/sidecar_port/test_mission.py tests/test_ao_runtime_portability.py tests/test_f03_git_evidence.py::test_closed_loop_real_gate_blocks_scope tests/test_f03_git_evidence.py::test_final_scope_copy_source_blocks_passing_verifier -q -rs --tb=short`：**224 passed / 160.98s**，0 failed / 0 skipped。
- 浏览器证据：真实本机 Edge headless 消费隔离 SQLite 的 HTTP/SSE 页面，断言不可信文本未形成 DOM/属性注入、command pass 与 overall fail 分离、错误不随 toast 消失、六类写按钮快速双击各执行一次，并用另一 localhost 端口页面验证跨源 POST 无副作用。外部动作使用替身，测试 SSE 发送真实快照后关闭以结束虚拟时钟；不等于真实 AO Mission 或视觉重设计验收。未新增浏览器依赖或框架。
- 追加验证：最终复查补齐历史 Task Verifier 已计算的 scope 记录（仅记录，不改决策/恢复），以同一 Windows venv 运行 `python -m pytest tests/test_f04_panel_boundaries.py::test_historical_task_verifier_records_its_known_scope tests/sidecar_port/test_verifier.py tests/test_f01_contract_boundary.py -q -rs --tb=short`：**49 passed / 316.91s**，0 failed / 0 skipped；与前述选择分开报告，不累计数量。改动 Python 文件 compileall、`git diff --check` 和 4 份变更 Markdown 的 20 个本地链接检查均通过。
- 残余边界：历史缺失事实不回填猜测；Gate 原始命令失败仍显示失败，既有 Mission 对已识别 baseline 失败的容忍规则不变。nonce 是本地浏览器 CSRF 边界，不是 OS 客户端认证；pending 仅处理同页在途重复提交；路径解析不承诺抵御有本机写权限者并发替换目录。attach/停止/有效配置的生命周期语义仍由 F05/R01/R02 处理。
- NOT_RUN：全量回归、clean install、打包、smoke、真实 AO Mission/模型、GUI 视觉重设计验收；本次合并收尾也未重跑已有 224 / 49 项定向测试或 compileall。未创建 tag/Release，未开始 F05 或其他功能卡。
- 合并收尾：合入 tree 与已审计 head 完全相同，本地 main 正常 fast-forward 同步；仅更新 PLANS、BACKLOG、根 README 与 PROJECT 的状态和当前事实，产品及发布工具 blob 未变，沿用既有验证。文档 diff-check、4 个变更文档的 20 个本地链接及产品 blob 核对通过。下一任务为 F05 TODO，M1 继续 IN_PROGRESS；已发布 v0.2 不变。

## V03-F05｜停止确认与未知外部动作保护

- 状态：DONE；base `fe1d12c42f780e6bbf6af272d0aca38ddb50026a`，分支 `codex/v03-f05-external-operations`；[PR #36](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/36) 再次外部审计 PASS，已审计 head `9620adced463f479a693f67667e90397a9521ef7`；2026-09-07 已 rebase merge 到 main `1e1401f7b55ff71617c0e3ef4ab277490b916cff`。F01–F05 DONE，M1 COMPLETE；下一任务 R01 TODO，未开始实现。

- 对应：A07。落点：Executor、Mission、Store，必要AO官方只读查询。
- 工作：同Store intent/operation_id/result；spawn/send超时先对账；无法确认则UNKNOWN+人工处理。materialization须已停止事实；不忽略kill失败继续提交。
- 必测：spawn成功但客户端ack丢失；send后进程中断；kill false/timeout；多次重试同操作；不唯一外部结果不得造第二Worker。
- 完成：在支持的AO契约下防盲重发，未知状态可解释；副作用数量受控；一次受控故障恢复验收。报告at-most-once/对账边界，不承诺分布式exactly-once。
- 不做：改AO内部DB；新增队列服务；提升预算隐藏未知。
- 实现：现有 `state.db` 的 `external_operations` 保存稳定 identity、输入摘要、attempt、结果与对账证据。`NOT_STARTED` 尚未调用（或已证明 CLI 未创建）、`IN_FLIGHT` 已持久抢占但确认未落盘、`SUCCEEDED` 已确认操作结果、`FAILED` 已确认本地未执行且有界尝试耗尽、`UNKNOWN` 无法确认；UNKNOWN 不当成功或失败。结果与成功预算计数同事务保存，多 Store 争用也只有一个调用者；超时/transport/nonzero 不再按错误文案自动重发。提示词/消息只存 hash，CLI 诊断脱敏限长。
- 对账依据：固定 AO v0.12.9 源码 `4cbb4b6ced1ad93f79641a2347d2342f1ffd218a`。核对 [spawn CLI](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/cli/spawn.go)、[send CLI](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/cli/send.go)、[公开 Session 控制器](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/httpd/controllers/sessions.go) 与 [终止实现](https://github.com/Untrivial-ai/agent-orchestrator/blob/4cbb4b6ced1ad93f79641a2347d2342f1ffd218a/backend/internal/session_manager/manager.go)。未访问 AO 内部 DB，也未启动真实 Worker/模型。
- Spawn：调用前冻结随机 120-bit、完整 20 字符 displayName 标记；ACK 丢失后只接受公开列表中唯一精确标记，且单 Session 的 ID/project/harness/kind/mode 全部吻合；无匹配、多匹配、改名、缺字段、读取失败均 UNKNOWN。该标记是关联证据，不是 AO 幂等键；不按人名/时间猜测，不证明初始 prompt 已被 Worker 消费或工作树已就绪。成功结果供初始 dispatch/replan 重入采用，未绑定的迟到 Worker 也纳入终止清理。
- Send：覆盖 Planner local-fix、L0 和实际 Worker directive 发送。普通 CLI send 没有传 caller clientMessageId，conversation 内容相同或缺失都不能证明某次消息交付；未知时只做只读诊断并进入 HUMAN，不再发送。成功只代表 AO 接受，不代表 Worker 已应用。未实现 R02 完整 directive 回执。
- Kill / Stop / 交付：ACK、exit=0、false、timeout 都需查同一 Session 的严格布尔 `isTerminated=true` 且 `status=terminated`；idle/exited、404、畸形/重复 JSON 字段均不当已停。未知状态只读再对账；旧停止结果遇到外部 restore/live 事实失效，但不盲目重新 kill。Mission 及 ClosedLoop 在后续工作前检查未决 operation；旧 Worker 未确认停止不 spawn replacement、不 commit/materialize/merge。Stop receipt 先落库，`worker_stop` 单独记录 CONFIRMED/UNKNOWN；终态保留原始 reason 与停止未知原因，不声称 HUMAN 等于所有 Worker 已停止。Panel 仅同步接收顺序与写失败错误，未新增取消中/恢复 UI。
- Windows 检查：产品 CPython 3.12.7 / `.venv`，Scripts 前置 PATH，src 为 PYTHONPATH。在 `clao/` 执行 `python -m pytest tests/test_f05_external_operations.py tests/test_spawn_and_boundary.py tests/test_crash_resume.py tests/test_terminal_cleanup_and_total_replans.py tests/test_directive_channel.py tests/test_shellish_guard.py tests/test_ao_runtime_portability.py tests/test_f03_git_evidence.py tests/sidecar_port/test_mission.py tests/sidecar_port/test_budgets.py tests/sidecar_port/test_phase2.py tests/test_f04_panel_boundaries.py::test_unauthorized_http_writes_never_reach_actions tests/test_f04_panel_boundaries.py::test_same_origin_page_nonce_allows_normal_write -q -rs --tb=short`：**286 passed / 1 failed / 211.64s**。唯一失败是告警预算夹具依赖旧 send 异常留下的中间态，已改为合法 CONTINUE 观察路径，保留并增强相同告警阻断断言；所有故障场景、正常发送、预算、F03 artifact/index 与交付断言均保留。
- 定向复核：`python -m pytest tests/sidecar_port/test_budgets.py::test_max_same_alerts_forces_human tests/test_f05_external_operations.py::test_mission_resume_unknown_send_parks_before_any_materialization tests/test_f05_external_operations.py::test_stop_during_spawn_adopts_late_ack_only_for_cleanup -q --tb=short`：**3 passed / 3.31s**（含修正夹具与新增两个完整恢复窗口）。此前其余 286 项已通过，集合分开报告，不将中途失败隐藏为一次全绿运行。
- 最终 operation/预算检查：`python -m pytest tests/test_f05_external_operations.py tests/sidecar_port/test_budgets.py tests/test_terminal_cleanup_and_total_replans.py tests/test_spawn_and_boundary.py tests/test_crash_resume.py tests/sidecar_port/test_phase2.py -q -rs --tb=short`：**114 passed / 79.75s**，0 failed / 0 skipped；包括已证明 CLI 未创建的 send/replan 重启重试、耗尽后 FAILED、恢复成功仅计一次，及迟到弱对账不覆盖已确认成功或产生误报。最后为 pending 重试补齐 ClosedLoop 不消费新事件/另起 action 的入口断言：`python -m pytest tests/test_f05_external_operations.py::test_closed_loop_unstarted_resume_keeps_one_pending_action tests/test_crash_resume.py -q -rs --tb=short`：**9 passed / 29.08s**，0 failed / 0 skipped。集合存在重叠，不累计为全量回归计数。变更 Python 文件 compileall、diff-check 和 4 份 Markdown 的 20 个本地链接检查通过。
- 故障注入覆盖：真实隔离 SQLite 关闭/重开、临时 Git、按官方响应形状实现的 loopback HTTP fake；spawn 成功丢 ACK/timeout/crash 后精确采用、多/零候选 UNKNOWN、send 外部生效但保存前/后 crash、kill false/timeout/transport/crash 的存活与终止分支、late ACK 遇 Stop、停止事实先于真实 materialization、成功预算只计一次、进程未创建的有界重试及真实缺失 executable。运行次数断言保证不重复 spawn/send/kill。
- 残余 AO 边界：displayName 可被外部改名/复制，不能代替官方唯一键；普通 send 缺少可唯一关联的公开回执，未知结果可能长期需人工。Session terminated 是 AO 公开的逻辑终止事实；AO chat stop 内部有 best-effort 清理，不能据此承诺独立 OS 进程级证明、不可被外部 restore 或分布式 exactly-once。现有终态不自动恢复为 running，完整取消/新 attempt/只读 attach 留给 R02。
- PR #36 审计返修：其余 F05 实现外部审计 PASS，唯一 blocker 为 `/api/stop` 吞掉 receipt 持久化失败后仍返回成功。本轮基于 `0542fc932c0fd9ad733152f88cfbc8d863632e5f`，仅修改 Panel 接收结果传递：无法确认持久 receipt 时 HTTP 503 / ok=false，保留错误且不设置 stop flag；无加载任务时 HTTP 409。正常返回明确的 ok=true / stop_requested=true；若后续清理抛错，先查同一 StateStore 的既有 receipt，已持久接收不因停止 UNKNOWN 被误报为未接收。路由返回该实际结果，沿用前端 writeAction 错误处理，不修改 index.html、写安全边界或已审计的 operation/spawn/send/kill 逻辑。该返修已通过再次外部审计 PASS，无其他需要返修的问题。
- 返修验证：同一 Windows 产品 venv、Scripts 前置 PATH / src 为 PYTHONPATH，在 `clao/` 执行 `python -m pytest tests/test_f05_external_operations.py tests/test_f04_panel_boundaries.py::test_unauthorized_http_writes_never_reach_actions tests/test_f04_panel_boundaries.py::test_same_origin_page_nonce_allows_normal_write tests/test_f04_panel_boundaries.py::test_invalid_json_never_writes tests/test_f04_panel_boundaries.py::test_duplicate_host_and_missing_host_cannot_write tests/test_f04_panel_boundaries.py::test_rejected_split_request_receives_error_without_writing tests/test_f04_panel_boundaries.py::test_real_browser_text_rendering_nonce_and_pending_writes -q -rs --tb=short`：**122 passed / 44.87s**，0 failed / 0 skipped。新增真实 Panel HTTP + MissionController + 隔离 SQLite/fake AO 回归：receipt 写失败无 stop_request、两层 stop flag 或 kill；receipt 成功但 kill false/timeout 时 200 接收且 worker_stop=UNKNOWN；receipt 后清理抛错仍按持久接收事实响应。既有真实浏览器夹具追加 Stop 失败错误提示与无假成功断言，保留双击去重、nonce、渲染断言。`python -m compileall -q panel/server.py tests/test_f05_external_operations.py tests/test_f04_panel_boundaries.py`、diff-check 通过；NOT_RUN 边界沿用下述内容。
- NOT_RUN：全量回归、clean install、打包、smoke、真实 AO Mission/收费模型、GUI 视觉验收；本次合并收尾也未重跑既有 F05 定向测试或 compileall。未创建 tag/Release，未实施 R01/R02/U01/U02 或模型切换。
- 合并收尾：合入 tree 与已审计 head 完全相同，本地 main 正常 fast-forward 同步；仅更新 PLANS、BACKLOG、根 README 与 PROJECT 的状态和当前事实，产品及发布工具 blob 未变。文档 diff-check、本地链接及产品 blob 核对通过，沿用既有验证；F05 DONE、M1 COMPLETE，下一任务 R01 TODO，已发布 v0.2 不变。

## V03-R01｜有效配置与阶段诊断

- 状态：IN_REVIEW；base `d59dd8fd630fab573ea4dd80b005106cf7fde207`，分支 `codex/v03-r01-effective-config`；M0/M1 COMPLETE，M2 IN_PROGRESS，R02 TODO。
- 对应：A10，支持A06/A11。落点：runtime/config、Gate、Adapter、Provider、Panel。
- 工作：唯一effective config解析；model重复键迁移；Gate时间/输出真正接线；配置来源与revision；phase/attempt/error metrics；敏感项不落库。
- 必测：保存值等于消费者值；非法范围拒绝；旧配置迁移/提示；运行中默认值改变不改当前Mission；unknown费用不填0；角色请求与实际确认模型分开。
- 完成：Panel可解释在等什么；已有SSE沿用，稳定cursor/序列与断连状态；本地ACK和事件延迟可测，不假承诺模型速度。
- 不做：新监控平台、全部配置热更新、同一事实复制多处。
- 实现事实：CLI/Panel 同一严格解析入口；整份验证并原子保存现有 YAML；配置来源与 revision 随 Mission 冻结，续跑复用旧快照，历史缺快照不伪补。模型/角色 timeout、AO timeout、runner 等待、watchdog 小数时间与三阶段 Gate 参数已接线；迁移键、弃用项及消费者表见 PROJECT，未新增依赖。
- Gate：timeout 真实作用于每条命令；每流持久证据正文有长度/hash/截断标记，失败编号在截断前提取，尾部新失败仍阻断 Final，片段不能绕过 F01 完整证据。诊断：执行开始先落现有 StateStore，语义传输 attempt/错误类别、Worker AO 观察与模型请求/传入/确认分开；UNKNOWN 不影响 F05 对账行为。
- Panel：默认设置与本次冻结配置分开显示；真实 preflight/慢模型/AO 读取在途可见，缺失和 read_error 不混淆；HTTP 处理、浏览器往返、状态记录到快照及请求耗时分别展示。SSE epoch+sequence 完整替换，断连保留最后状态并冻结计时，重连不重发写动作，沿用 F04 写边界与安全 DOM。
- Windows 定向（产品 venv、src 前置 PYTHONPATH）：`pytest tests/test_r01_effective_config.py tests/test_panel_worker_contract.py tests/test_f04_panel_boundaries.py tests/test_mission_preflight.py tests/test_codex_cli.py tests/test_codex_planner.py tests/test_codex_auditor.py tests/test_codex_verifier.py tests/test_f01_contract_boundary.py tests/sidecar_port/test_budgets.py -q -rs --tb=short`：**311 passed / 213.30s**；含真实 Edge 的配置交互、安全文本、在途/未知诊断、SSE 断连重连检查。新增 AO 只读边界和最后消费者检查另见下条，不将重叠集合相加。
- 补充命令：`pytest tests/test_r01_effective_config.py tests/test_f05_external_operations.py tests/test_ao_runtime_portability.py tests/test_mission_gate.py tests/test_final_gate_baseline.py tests/test_approval_block.py tests/test_approvals_bridge.py -q -rs --tb=short`：**182 passed、1 failed / 99.48s**；唯一失败是旧 AO Runtime 替身缺 diagnostics 字段，补齐该替身后单独复查 `pytest tests/test_ao_runtime_portability.py -q -rs --tb=short`：**18 passed / 0.27s**。其余 F05/Gate/审批/R01 场景无失败；集合重叠不累计。含在途 AO 只读请求、小数 watchdog 持久化和恢复诊断读取失败的最终负例。
- 检查中的修正：首次收集发现诊断 import 位于 decorator 与 class 之间，已修正；浏览器探针误读自身 script 文本已修正。旧 preflight/恢复夹具改为真实 SQLite、持久配置事实与无 Worker 副作用断言；停止前先模拟 Worker 存活，停止后才 terminated。检查保留失败/拒绝断言，未删除负例；最后一次上述集合无失败。
- 最后边界复查：增加超大整数和带控制字符 URL 的拒绝用例后，`pytest tests/test_r01_effective_config.py -q -rs --tb=short`：**37 passed / 22.43s**；compileall（src/panel/run_mission.py 与直接变更测试）、diff-check、5 个变更 Markdown 的 21 个本地链接 PASS。新增源码/测试已由既有 manifest 前缀覆盖，依赖、builder、manifest、AGENTS 与设计主文档不变。
- NOT_RUN：全量、clean install、打包、smoke、真实 AO Mission/模型、GUI 视觉重设计验收；未新增 tag/Release，未实施 R02 或模型供应商。
- 剩余边界：当前语义 CLI 无可确认的实际模型/用量/费用字段，均 unknown；AO conversation.modelReroute 只确认 conversation 级替换，复用既有读取不额外请求。Gate 上限限制证据正文，仍使用既有内存捕获；runner cap 仅循环边界。历史无快照只读查看、attach 组装副作用与完整恢复留 R02；阶段记录只诊断，不是新的状态权威。

## V03-R02｜指令回执、取消恢复、固定基线

- 对应：A06、A08、A09。落点：directives、Controller、Store、Panel和Git基线。
- 工作：received/applied/rejected/unknown回执；final verifier notes真实消费；Worker prompt范围完整；取消中与已取消区分；崩溃恢复只读检查材料；终态新attempt关联；Mission固定source commit。
- 必测：指令无消费者；入队与落盘失败；取消发生在Worker/语义角色/Gate；旧HUMAN不重新变running；旧记录字段缺失；source main/remote分歧；S2缺依赖代码。
- 完成：取消/恢复文案与实现一致；不支持的dependent plan preflight明确拒绝，或有真实dependency commit交付测试；独立双任务保留有界支持。
- 不做：新建完整暂停调度器；未经验证扩大并发。
- 证据：待填。

## V03-U01｜iPhone风格界面骨架与状态夹具

- 对应：GUI新设计，A12。依赖：G1已通过；G2字段约定确定。
- 工作：四入口、浅/深主题、响应式、分组卡片、渐进表单、键盘焦点；拓扑降为高级诊断。先用状态夹具展示完整/失败/取消/断连/审批/空记录。
- 完成：负责人审核1440/1366/768/390宽截图与键盘流程；不把mock原型写成真实功能；无字体/图标许可遗漏。
- 不做：iPhone外框、网页远程手机接入、大面积模糊/发光、换框架。
- 证据：待填。

## V03-U02｜完整任务GUI与数据接线

- 对应：A04/A05/A06/A08。依赖：U01+G2。
- 工作：真实就绪卡；显式Project与base确认；目标/范围/Gate/模型摘要；运行阶段、审批、取消、历史与重试；大错误常驻；真实角色调用与证据scope。
- 必测：从新建到结果；断连重连不双发；停止请求不假完成；Gate read_error；引用/中文/超长文本；200%缩放；旧Mission只读。
- 完成：Playwright或等价浏览器测试在开发环境通过；用户实际GUI确认；不把API200当视觉PASS。
- 不做：未经授权后台创建Mission验证界面；浏览器依赖打入产品。
- 证据：待填。

## V03-U03｜结果中心与独立导出

- 对应：A12、A03。工作：AC/Gate/Verifier/diff/commit；open/copy/export；完整patch和manifest；无效linked worktree的可读说明。
- 必测：新增/删除/rename/二进制（支持或明确拒绝）；隔离clone应用；export后临时worktree不可用仍能读取；无密钥/Prompt/.git导出。
- 完成：用户能在60秒内找到结果并知道main未改（建议体验目标）；补丁应用后内容/验收匹配；动作API不接受任意外部路径。
- 不做：自动主分支写回、自动GitHub PR或push；这些可后续单独设计。
- 证据：待填。

## V03-P01｜模型配置／凭据与GLM语义后端

- 对应：A11/A10。工作：profile/角色绑定/credential_ref；一种安全凭据存储；Codex保留；GLM明确服务域、认证、model/effort、JSON协议。语义角色无工具执行。
- 必测：密钥不进入响应/log/Store/export；跨域发送须授权；非法/截断/拒绝/401/429/timeout；Schema+ID+coherence；运行中不热切；有模型调用与无模型检查分开。
- 完成：一个已验证GLM profile覆盖所声明Planner/Auditor/Verifier角色；UI显示真实范围、价格unknown等；正向与真实失败反馈受控live。
- 不做：改全局~/.codex或AO daemon环境；仅换model字符串；静默跨供应商fallback。
- 证据：待填。

## V03-P02｜Kimi语义后端与切换评测

- 对应：A11。依赖：P01的薄transport/本地校验契约。
- 工作：核对官方Kimi当前API和具体model；实现供应商参数差异，不复制整套角色/Controller；设置页明确数据发送、凭据和支持角色。
- 必测：与P01相同的协议/错误/安全矩阵；固定任务profile切换；Codex/GLM/Kimi回归；不支持参数保存前拒绝；requested/confirmed模型区分。
- 完成：一个已验证Kimi profile；与GLM均不是只列在UI；完成批准预算下的质量/延迟评测，已知负例假PASS=0。
- 不做：猜测ChatGPT订阅覆盖API；以一次OK响应宣称全角色可用。
- 证据：待填。

## V03-P03｜第二Worker能力准入决策

- 性质：有条件扩展；决策记录为必须，非Codex Worker上线不是无条件承诺。
- 工作：查固定AO版本官方harness、tool/edit/approval/kill/model设置与隔离；选GLM或Kimi的一个可行组合做专项。
- 两种完成结果：SUPPORTED（完整Worker E2E与隔离通过）或DEFERRED（明确限制，UI禁用且说明；负责人批准）。均不能写“全部模型完全切换”。
- 必测（选择上线时）：两个配置互不污染、实际工具编辑、审批、取消、重启、Session实际model、同任务Gate/交付；禁止继承未验证全局别名。
- 不做：为支持下拉框patch AO、自造coding agent、把API JSON调用称为Worker。
- 证据：待填。

## V03-Q01｜新Windows产品验收与发布候选

- 依赖：G1—G4；无未处置高等级正确性／权限缺陷。
- 工作：单一manifest包；依赖锁定、来源许可、代码/脚本边界；从新ZIP开始bootstrap；两套干净Windows环境；普通用户首次任务；真实CLI/GUI与失败恢复；各已支持模型profile live。
- 完成：固定source SHA、最终artifact hash、任务/Gate/Verifier/SCM证据、浏览器记录、明确模型支持矩阵、已知限制和回滚说明。所有查询/字段错误不能被空成功吞掉。
- 发布纪律：旧v0.2不可覆盖；产品文件若变，重新验证受影响路径；仅开发文档变可用manifest blob等价性，不重跑昂贵live。
- 证据：待填。

## 通用证据模板

```text
任务ID / 状态：
日期 / 源码基线 / 分支 / PR：
设计依据：V03_PLAN节号；原报告A编号/页码
修改范围：
原负例：命令、环境、失败输出（有界脱敏）
修复后：相关测试、全量/编译、API/浏览器/live实际结果
未执行：明确NOT_RUN；原因
产品行为/配置/Schema变化：
Windows/AO/model/SDK实际版本：
残余风险 / 停止条件触发：
下一步：由PLANS唯一指针决定
```
