# Windows 回归事实 · 2026-09-21–22

任务 V03-NATIVE-CLOSEOUT / PR #49；当前 Windows 主机开发工作树。以下集合含重叠，不相加为新的“全量通过数”；真实模型及安装产物验收另记。

## Python 核心与原生集成

使用仓库原 `clao/.venv/Scripts/python.exe`（3.12.7），工作目录 `clao`，venv Scripts 前置 PATH、`PYTHONPATH=src`。完整首轮 `python -m pytest -q --tb=short`：**1282 PASS、44 FAIL、59 ERROR、1原有SKIP，3424.42秒**，保留 `python-full.log`。

59 ERROR 是测试进程没有 Go PATH，外部协议替身无法编译；不是59个产品断言失败。补正Go和隔离临时目录后运行四个原生测试模块：**55 PASS、9 FAIL，1296.35秒**，`python-native-final.log`。9项逐项定位：

- 来源快照使用确认后的磁盘字节和私有提交；原Git可能按core.autocrlf规范化，测试不再错误比较旧commit或tree，改查Source.base及逐文件原字节。
- 重启时账号/目录探测不代表Worker或模型重发；仅排除精确账号home及daemon数据根中的空policy事件，保留所有任务工作区、Session创建、prompt、选择与审批事件。
- completed turn不能证明进程停止。恢复正例经正式exit-agent和conversation确认后再真实重启；新增未确认停止的强杀负例，必须UNKNOWN、continue409、无固定结果或重复prompt。
- 空Verifier已记录FAILED却可通过continue接受循环，属于产品缺陷：恢复检查在来源快捷路径之前拒绝确认失败/协议错误角色，仍保留未确认回执和持久故障的恢复路径。新增Go直接正负回归，并由独立Reviewer复核。

定向复核 `python-native-fixes.log` 首轮 **4 PASS、6 FAIL**；余6项调整及产品修复后 `python-native-role-final.log` **6 PASS、55 deselected，180.47秒**。原9项失败均已在直接复核通过，另有1项新增停止负例；未重跑整个64项集合。命令使用三个native模块及精确 `-k`：`opencode_pass_and_frozen_result or empty_review or two_workers_restart or shared_budget_exhaustion or completed_turn_without_confirmed_stop`。新recovery代码的Go claoloop整包通过1.764秒。

44个Python原始FAIL另行重跑：**14 PASS、30 FAIL，437.45秒**。随后只读历史attach1项、R02 HTTP2项、真实Edge1项各自复核通过。剩余26项属于旧Panel/Controller路径：24项Git深嵌套worktree产生`$GIT_DIR too big`，2项旧Panel浏览器等待超时；未删除/skip或宣称通过。新的原生daemon调用链不执行旧MissionController的integration-worktree方法。另修复可复用核心的Windows超长侧车路径I/O，保留旧文件名、冻结base及缺证据拒绝语义；2项真实Git长路径回归通过，独立审查通过。

## Go 原生后端

官方Go1.26.5，`GOTOOLCHAIN=local GOWORK=off`，完整首轮 `go test -mod=mod -p 2 ./...`，`GOMAXPROCS=2`：**128包PASS、43包FAIL、14包无测试**。原始 `go-full-bounded2.log` 保留；包含当时并行源码迁移造成的service/agent构建失败和网络初始化失败，不将分类后的定向结果改写成完整全绿。

已完成定向修复/验证：

- Managed Codex的Windows真实DACL/owner/祖先检查共享；工厂握手、验证、保存后重读、弱权限及junction负例。codexappserver整包19.384秒、独立security3.563秒，service/agent定向12.175秒；独立Reviewer再跑直接消费者通过。
- Git项目导入保护CLAO/自定义StateDir、祖先及真实Windows junction，importer整包13.994秒；独立junction负例复核1.036秒。processenv排序、daemon工作目录测试清理顺序、gitworktree真实转义错误断言、migration ledger均定向通过。
- systemexec、supervisor、usage、project：16个顶层测试通过；使用真实Windows子进程/TLS脚本/文件handle与原子替换，不模拟“成功”退出。`go-windows-regression-final.jsonl`。
- systemcheck、systeminstall、session_manager：15个顶层测试通过。ConPTY前提、真实测试子进程、PATH验证、失败禁止callback、并发幂等及平台路径合同保持；`go-install-session-focused.jsonl`与`go-systemcheck-focused-final.jsonl`保留首次编译失败及修复结果。
- 手工switch-agent交接文件原仅Chmod不能保护Windows隐私；新增目录以私有DACL原子创建、现有对象只验证、读写handle验证。真实开放父目录/已存在开放对象/发布后改ACL/junction正负例和直接切换消费者：33顶层PASS、0FAIL、2原有symlink权限SKIP，1.165秒；新增junction实际通过。Unix实现保留，本机未运行Unix。
- domain测试缺testify锁定间接模块的go.mod校验记录。通过官方sum.golang.org和proxy.golang.org取得精确版本记录与缓存，未关闭校验或更新版本。`-mod=readonly GOPROXY=off`最终PASS0.404秒。

剩余上游失败保留：部分27工具的Unix shell、HOME/路径、POSIX权限和本机工具缺失；macOS executable symlink；tmux/persistenthost的Unix前提；mobilebridge/telemetry平台权限合同；pricing/reviewgateway的POSIX模式断言；未逐一宣称Windows可用。CLAO原生语义角色只按确定性权限准入，不能将上游目录存在等同全执行器验收。涉及Kimi实际协议及凭据路径的进一步检查仍进行中。

## 证据与限制

日志只保存在外部测试证据目录，不将可能包含环境/本机路径的完整上游失败输出放入Git。测试均在专用临时项目和账号目录执行，主目录负责人配置未改。前端完整结果与剩余平台/landing失败见 [前端记录](frontend-regression.md)。安装、卸载和真实请求按各自证据等级报告；两套独立干净Windows仍未取得，不能用同机换目录替代。
