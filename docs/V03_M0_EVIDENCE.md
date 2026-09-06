# V03 M0 基线与目录整理证据

状态：M0 COMPLETE（含下列安全保留项）；[PR #31](https://github.com/zhaoshiyi4246/closed-loop-agent-orchestrator/pull/31) 人工审计 PASS；V03-DOC-00 / V03-M0-LAYOUT = DONE。

日期：2026-09-06。基线 main：`3a9ea27468915eb9571611bcca10962e7a732fb0`；发布源码：`4d3e8e6b5e70bab868b2eef0d28c7742dea044ba`。

范围：V03-DOC-00、仓库目录与当前引用、本机重复副本分类整理；不实施 V03-F01，不修 A01—A12。人工审计已通过；本次最终收尾仅修正文档状态，不修改 v0.2 tag／Release。

## DOC-00 与规则核对

`DOC00_BASELINE_PASS`：规划 main 相对发布源码的 diff 恰为 7 项治理／规划文件及审计 PDF；106 个产品 blob、builder 和 manifest 完全一致。12 个当前 Markdown 中 17 个本地链接有效；PDF 为原 29 页附件。

已核对 Panel／CLI → `build_runtime()` → `MissionRuntime` → `MissionController`／`ClosedLoop`；StateStore 是逻辑运行状态源，AO 提供外部事实，Bus／Markdown／JSONL 只投影。当前 Stop 是 HUMAN；attach 仍组装 runtime；Schema fallback、kill best-effort 和终局语义缺口继续由现有 backlog 描述。

根 AGENTS 中的未来安全要求属于实施约束，不是已实现声明。原 v0.2 完整治理历史通过固定提交保留。唯一 nested AGENTS 在 `legacy/clao-src/clao-v0.1.0/AGENTS.md`，保持原 blob；它不约束 `clao/`。`clao/` 和 `packaging/` 内无 nested AGENTS。

## 引用盘点与调用关系

迁移前对所有 tracked 文本搜索交付目录、旧产品目录名称、正反斜杠写法、旧 canonical 仓库名与 URL，共 43 个命中行，逐行分类：

| 分类 | 命中行 | 处理 |
|---|---:|---|
| CURRENT_DOC | 12 | 当前规则、README、PROJECT、PLANS、V03_PLAN 路径及 canonical URL 更新 |
| CURRENT_OPERATIONAL | 18 | 14 条 manifest SOURCE、3 条产品目录注释更新；builder 拒绝历史目录的名单保留 |
| HISTORICAL_SNAPSHOT | 12 | 原历史材料移入 legacy，字节不改 |
| EXTERNAL_TEAMMATE_REFERENCE | 1 | `liuxinyue743-wq/agent-orchestrator-AI-worker` 保持真实外部名称 |
| GENERATED/IGNORED | 不纳入 tracked 计数 | 本机缓存、runtime 和私有核对日志不进入提交／产品 |

运行入口与测试通过 `__file__`、`Path.parent` 或 `PRODUCT_ROOT` 定位产品内部文件。`bootstrap.ps1` 使用 `$PSScriptRoot`；batch 使用 `%~dp0`；manifest 和 builder 在同一层级，因此移动后无需改脚本执行逻辑。

已检查 Python import、sys.path、入口和测试中的历史目录引用：产品不导入 v0.1／sidecar，不读取 demo 或历史 bare repo。保留的 ported-from、旧设计出处与 mock project/session ID 是来源或测试夹具，不是 runtime 目录依赖。旧设计中的相对出处文字作为历史说明保留。

## Git 迁移与内容 allowlist

用 `git mv` 迁移 308 个 tracked 文件：产品 106 个进入 `clao/`，builder／manifest 2 个进入 `packaging/`，其余历史 200 个进入 `legacy/`。单独纯 rename commit 零内容增删；后续 commit 才适配当前引用。Git 对完全相同的历史／产品 blob 可能显示交叉配对，以逐路径 blob 映射作为来源证明。

所有历史文件与冻结审计 PDF 保持原 blob。`.gitignore` 的递归 `.venv`、cache、runtime 规则已覆盖新路径，无需改动。

产品内仅以下文件有内容编辑：

| 文件 | 为什么需要编辑 | 行为影响 | 覆盖 |
|---|---|---|---|
| `clao/config/default.yaml` | 首行注释使用当前产品名称 | YAML 数据不变 | 配置解析比较、完整 pytest |
| `clao/src/loopcore/mission_contracts.py` | docstring 与 ROOT 注释中的目录名称更新 | 仅描述文字；可执行语句不变 | AST 比较、schema／contract 与完整 pytest |

`packaging/release-manifest.txt` 只更改 SOURCE 前缀，DESTINATION 不变。builder 内容与发布基线完全一致：从 clean HEAD `git archive` 构建，拒绝仓库内输出和已有输出目录，校验文件集、hygiene、本地链接、secret/path scan 和 SHA256SUMS。它仍使用 v0.2 artifact 命名，因为本次不改变产品版本或发布结构。

## 本轮验证

本轮 Windows canonical clone 验证：直接相关测试 `88 passed in 0.79s`；完整 pytest `438 passed in 105.61s`；compileall 与 diff-check 退出 0。环境与命令见 [PLANS](../PLANS.md#m0-开发验证环境)。

| 检查 | 本轮结果 |
|---|---|
| 定向命令（在 clao 内） | `.venv\Scripts\python.exe -m pytest tests/test_ao_runtime_portability.py tests/test_panel_worker_contract.py tests/test_mission_preflight.py tests/test_codex_cli.py tests/sidecar_port/test_contracts.py -q` |
| Git 映射 | 308 个原路径全部映射；除 2 个产品注释文件及 manifest 外 blob 全部相同；历史 200 文件与 PDF 原样 |
| 配置／Python | YAML 数据一致；修正目录文字后 AST 一致；原有源码逻辑无改动 |
| builder source | clean committed HEAD `667ce95deb2b4baae2a22fcfa394c4c2b5e55d4d`，exit 0 |
| ZIP | 92 个 manifest 产品文件 + `SHA256SUMS.txt`；唯一顶层 `clao/` |
| artifact 校验 | 逐文件 SHA-256、Git HEAD blob、hygiene、secret/path scan 全部 PASS |
| runtime file set | `RUNTIME_PRODUCT_FILESET_CHANGED=0`；仅 2 项内容 allowlist 和派生 checksum 更新 |
| 初次 ZIP SHA-256 | `83c9854eb9f14ae8a6e74e6880a9fb7e3a1359866655270aa472e40bcbc5e3d6` |

Windows 既有 `core.autocrlf=true` 使 Git archive 输出 CRLF。额外核对脚本首次直接比较 LF blob 与导出字节时失败，已定位为验证方法问题；后用 Git 自身 `hash-object --path --stdin` 转换再与 HEAD blob ID 比对通过，未修改 Git 配置、builder 或产品换行。发布前后 ZIP 的相同文件也逐字节比较通过，仅上述 allowlist 不同。

治理状态／证据提交 `06bfb67fbb614da06de9cbdad3b5c4789a141573` 已运行 builder，SOURCE_COMMIT、ZIP hash 和链接检查数量记录在 PR 正文与本机报告中。本次最终收尾复核 13 个当前 Markdown 的 23 个本地链接全部有效，diff-check PASS；相对该已审计提交，产品、发布工具与历史目录 blob 均不变，原 438 项测试、compileall 和 builder 验证结论仍成立，不重复运行产品验证。

## 本机资料边界

完整路径、refs、untracked／ignored 文件清单、ZIP SHA-256 和 AO registry 结果只存本机任务证据，不进入 Git。指定 canonical clone 的 origin 为本仓库，任务分支与远端一致、工作区 clean，main 与 origin/main 无分歧。

本机范围为桌面 5 个相关目录、3 个设计／规划文件，以及旧 clone 内 1 个源码 ZIP；未扫描用户全盘。处理结果：

- 旧 v0.2 工作区的 31 个本地分支、全部用户 refs 与 ignored runtime 归档保留；用 Git bundle 再保留一份全部 refs，归档后 HEAD 和 clean 状态验证通过。
- v0.1 的 35 个历史本地分支也已保存 Git bundle；独立旧 M4-2 测试 worktree 用 `git worktree move` 移到 archive，common-dir 关系由 Git 更新。
- 干净的官方 AO 源码参考 clone 移到 archive/reference；它不是 AO 安装或配置目录。
- v0.2 正式 ZIP、外部 checksum 与原 release notes 归档到 releases/v0.2；ZIP hash 与 GitHub Release 一致。重复解压目录移到 quarantine。
- v0.1 源码 ZIP 的 25 个文件全部匹配 canonical legacy blob，移到 quarantine；原 v0.3 规划 ZIP、15 页评委 PDF 和 8 页早期设计 PDF 含历史或唯一资料，移到 design-snapshots 保存。
- **保留桌面 v0.1 clone**：AO Project registry 仍引用它，且一个旧 AO orchestrator linked worktree 的 Git common dir 在其中。未删除／重建 AO Project，未修改内部 DB 或会话。
- **保留原工作区空壳**：当前 app 占用目录句柄，全部文件已归档，原位置仅剩空 `.git` 目录。删除空目录的命令被自动审批审查拒绝（仅返回 blocked by policy），没有执行后续删除。

公开 AO CLI 还发现两个历史 Project 指向已不存在的 demo／R5 路径，原样报告并保留 registry；这不是本次整理删除的目录。归档工作区／runtime 用于保存历史材料，不承诺移动后旧 Mission 可直接恢复；linked worktree 恢复仍需原 Git 材料和路径核对。没有永久删除任何源码、历史分支或用户交付文件。

## NOT_RUN

AO Worker、真实模型调用、Mission、CLAO GUI、Release publish。AO Project registry 仅通过公开 CLI 只读查询，不读取内部 DB 或凭据。

下一任务：**V03-F01 — 完整契约与终局一致性**，保持 TODO；本任务完成后停止。
