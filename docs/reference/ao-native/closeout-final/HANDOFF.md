# V03-NATIVE-CLOSEOUT 候选交接

2026-09-22，PR #49，v0.3.0-rc.1。候选源码 `1325591e02cb3a091755189e20f4c80ca8fe992f`，状态 RELEASE_CANDIDATE；不代表 M4/M5、两套干净Windows或负责人体验完成。后续仅文档/开发证据提交，发布映射内产品blob另行核对。

## 安装与最短验收

交付目录名为 `CLAO-0.3-final-candidate-1325591`。其内只包含安装器、便携ZIP、SOURCE.json、SHA256SUMS.txt和中文安装说明。运行 `CLAO-Native-0.3.0-rc.1-Setup-1325591e02cb.exe`，安装后从 **CLAO Native** 快捷方式启动；便携包解压后运行 `clao/clao-native.exe`。完整说明见[Windows候选安装](../../../../packaging/WINDOWS-CANDIDATE.md)。

系统准备Git和所选编码工具及账户；应用自带Python核心、Node与桌面运行环境。打开一个小型本地项目→新建任务→启用CLAO闭环→确认来源与允许范围→填写可执行检查命令→选择已登录工具/模型→启动。查看原生Chat中的待处理审批、运行图及独立验收；完成后导出ZIP，在副本按说明应用并重跑检查。原项目不会自动写回。卸载保留独立任务数据。

## 已验证与限制

- 真实Kimi：官方CLI2.0.2、国内标准API kimi-k3，一个两文件合成任务完成Worker、范围审批、Gate、独立Verifier、DONE及独立导出Gate。三角色各正反质量对照通过。此为开发daemon与测试计量传输；OAuth/Coding Plan及其他CLI版本未验证。
- 同题独立CLI：文件修改及相同Gate通过，但达到预设4步上限退出，整体未完成。保留首轮协议/参数/步数失败，不追加真实试次追求通过。小样本不支持一般性能优劣结论。
- Windows完整首轮已运行并保留失败；新增/受影响消费者定向修复和独立审查通过。旧Panel/Controller深Git路径与上游Unix/macOS/工具环境等限制单列；不宣称全部测试全绿。
- 外部前提：GLM项目凭据引用未取得；现有Codex登录测试daemon被客户端自动审批拒绝；两套独立干净Windows未取得。不能用本机不同目录替代两台环境。外部阶段审计、负责人完整体验、正式合并/签名/tag/发布尚未完成。

真实费用台账最终19/40次HTTP、5/6次Worker admission；确认usage保守上界4.36718/20元，真实账单未知。原始最坏预留记录总和27.46946元保留，不是同时在途金额或实扣。全部真实试次确认测试进程停止，无Key落盘/日志检测命中。详见[有限对照](live-kimi-comparison.md)、[Windows回归](windows-regression.md)、[前端回归](frontend-regression.md)及[证据索引](README.md)。

只创建独立候选安装、测试项目/账户目录和隔离构建工具；官方AO安装与`.ao`、原仓库main及用户未提交配置保持。候选未签名、自动更新关闭。没有合并PR、创建tag或公开发布。
