# Kimi 真实有界对照

V03-NATIVE-CLOSEOUT / PR #49，2026-09-22 Windows。初轮运行层e5c87e6，最终协议修复288e64d、验收脚本6b84bb9。官方 `@moonshot-ai/kimi-code` 2.0.2，国内标准API `kimi-k3`。两个方法使用相同两文件加法缺陷、目标、范围与独立Python检查；任何未完成尝试不改写为通过。测试传输逐HTTP持久预留，工具仅可读两份合成文件、修改solution.py；该限制是小任务验证约束，不宣称通用系统沙箱。

| 尝试 | 实际请求 | 输入/输出token | 工作区与完成事实 | 时间 | 原费用预留 |
|---|---:|---:|---|---:|---:|
| CLAO native初试 | 2 | 8939 / 179 | 写入审批缺少前置rawInput，拒绝批准；文件未改，无最终Verifier/结果 | 17.234秒 | 3.0793元 |
| baseline初始启动 | 0 | 无 | 测试脚本错误组合CLI互斥参数，HTTP前exit1；原文件不变 | 0.828秒 | 0元 |
| baseline参数修正试次 | 3 | 12829 / 229 | 仅solution.py修正、相同外部Gate通过；CLI exit1，未正常完成，不算整体PASS | 15.844秒 | 4.51848元 |
| CLAO native最终 | 4（Worker3、Verifier1） | 16916 / 1038 | Worker完成→Gate PASS→独立Verifier PASS→DONE→ZIP独立应用后同一Gate PASS | 66.781秒 | 5.69558元 |
| baseline最终 | 4 | 17421 / 325 | 仅solution.py修正、相同Gate PASS；官方CLI记录loop.max_steps_exceeded（maxSteps=4），exit1，整体未完成 | 27.265秒 | 6.0773元 |

全部自有进程树确认停止，未检测到Key落盘或日志泄露；原来源均保持不变。基线参数修正使用新的试次ID，初始失败和Worker admission没有删除。以上含启动/验收开销，非严谨性能基准；人工操作为0，最终native另有1次自动范围内once审批。五个Worker admission中一个在请求前失败；为保守控制，仍计入6次上限。加上此前六个真实角色质量对照，最终为 **19/40次HTTP、5/6次Worker、保守确认费用上界4.36718/20元**；历史原预留总和27.46946元永久保留，它是逐次请求发送前的最坏预留之和，并非实扣或同时在途金额。账单实扣未知。

最终native与baseline的来源摘要均为 `68f296ab02736c88716ce53e874c972495d3eefd96226be5c6676d9c89a9f436`。native的保守费用上界1.11876元，baseline为1.07776元。两者最终产物都通过相同检查；只有native完成全部流程。baseline的3步和4步试次均由本地官方wire事件确认达到预设步数上限，不能由此推断不限步数的CLI无法完成，也不能声称CLAO普遍更快、更便宜或质量更高。两条最终试次后停止付费验证，不追加试次追求PASS。

本次是开发daemon+官方CLI+测试用计量传输的真实标准API验证；不代表真实安装应用、OAuth/Coding Plan、所有任务或完整取消/重启均已通过。脱敏最终报告见 [native](live-kimi-final/native-report.json)、[baseline](live-kimi-final/baseline-report.json)及[baseline失败事实](live-kimi-final/baseline-diagnostic.json)。

独立Reviewer只读核对SQLite、roleCall、scope/Gate、审批与导出提交后未发现报告的产品结论冲突。原baseline报告的environment字段误沿用daemon模板；实际为独立官方CLI，原报告保留，脚本模板已更正。source_sha256只标识合成任务输入，不是产品源码或daemon哈希。

实际协议暴露旧离线探测的顺序错误：完整参数chunk和分片Edit都是审批后才出现canonical rawInput，旧probe只看整段更新，误将其视作审批前事实。现已修正probe为明确检查审批时点；此前“官方CLI写入成功”只证明独立probe人为许可后的协议流程，不能作为CLAO审批前输入已就绪的证明。通用ACP绑定正负测试仍有效，真实native初试按安全边界拒绝是正确行为。

官方2.0.2源码明确将原始arguments分片累计编码到特定tool_call/update.content.text，canonical rawInput在权限回调后发布。288e64d已实现仅该精确AgentInfo版本启用的Kimi专属参数解码，严格绑定session/turn/tool ID、参数流形态和完整JSON，再通过原有权限和路径检查；不从标题/diff猜测路径，不给一般ACP文本授权。独立Reviewer复核与官方CLI离线实际Go/路径审批三链路通过；真实最终native试次通过。

服务型号、usage均已确认，尚无超时或未知HTTP；后续任何这类结果仍冻结该服务。依据[官方价格](https://platform.kimi.com/docs/pricing/chat)与[官方usage定义](https://platform.kimi.com/docs/api/chat)核对保守费用上界，原始预留和全部尝试永久保留，未提高20元/40HTTP/6Worker授权上限。脱敏明细见[live-ledger.json](live-ledger.json)。真实账单、Coding Plan扣款不作推断。

费用核算补充：原11条预留15.69658元保持不变；完整成功HTTP的合法原预留、精确型号、usage及token上限均核对后，以所有输入60元/百万（20输入+40最长缓存写入）、输出100元/百万核算保守上界2.17066元。所有错误或未知结果仍保留全预留并冻结服务。独立Node26/Python95离线测试通过；新试次预声明最多4次Worker HTTP，旧试次不可增额，三项总上限不变。
