# V03 M0 基线与目录整理证据

日期：2026-09-06。基线 main：`3a9ea27468915eb9571611bcca10962e7a732fb0`；发布源码：`4d3e8e6b5e70bab868b2eef0d28c7742dea044ba`。

范围：V03-DOC-00、仓库目录与当前引用、本机重复副本分类整理；不实施 V03-F01，不修 A01—A12。PR 审计前不合并 main，不修改 v0.2 tag／Release。

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

本轮 Windows canonical clone 验证：直接相关测试 `88 passed in 0.79s`；完整 pytest `438 passed in 105.61s`；compileall 与 diff-check 退出 0。环境与命令见 [PLANS](../PLANS.md#m0-开发验证环境)。builder 将在本次路径适配提交后的 clean HEAD 执行，artifact 验证尚待完成。

## 本机资料边界

完整路径、refs、untracked／ignored 文件清单、ZIP SHA-256 和 AO registry 结果只存本机任务证据，不进入 Git。可恢复的重复副本使用隔离目录整理；唯一历史分支、运行证据和 AO 引用不能当作垃圾永久删除。

## NOT_RUN

AO Worker、真实模型调用、Mission、CLAO GUI、Release publish。AO Project registry 仅通过公开 CLI 只读查询，不读取内部 DB 或凭据。

下一任务：**V03-F01 — 完整契约与终局一致性**，保持 TODO；本任务完成后停止。
