# DeepSeek Harness 接入与验证

当前九个 DeepSeek Agent 全部由官方 DeepSeek Harness 执行，项目经理仍是 deepseek-4；模型别名为 deepseek-flash。Hub 不设置金额、回合、请求次数预算。官方账户余额与限流仍适用。

## 使用

打开 outputs/AgentMessageHubDesktop.exe，或使用 Open-Desktop.cmd。现有密钥与执行授权继续使用，配置状态显示 Harness / ACP。与经理讨论需求，批准计划后执行；未批准、暂停或停止的旧项目不会因为更换执行器自动重放。

安装检测到的 Harness 版本为 0.2.1-rc.2，路径 C:/Users/ASUS/AppData/Local/Programs/DeepSeek Harness。使用安装包自带的官方 CLI 入口和 ACP 协议，不依赖 Harness 桌面窗口开启，不访问桌面私有服务、Cookie 或登录数据。密钥经环境变量传给子进程，不写入配置补丁。

## 能力与上下文

Harness 负责原生文件、命令行、搜索和上下文压缩；Hub 负责九个固定身份、消息唤醒、项目派工、审批、心跳和停止。原生子 Agent 与另一套自动工作流被关闭，避免绕过 Hub 派工。

每个身份的 Harness 数据位于 Hub 数据目录下 harness/deepseek-N，持续会话按项目隔离。首次切换时旧 API 的可见文本作为历史参考带入，不重放旧工具调用；此后通过 session/resume 继续原会话。不会清除或修改个人 Harness Desktop 配置，个人桌面插件不会自动导入。

完整权限对应 danger-full-access，工作区权限对应 workspace-write；讨论、质询和只读检查限制工具与权限。任务时限、停止锁、项目审批和消息循环保护仍有效。停止先发官方 session/cancel，再在必要时终止本轮所属进程树。未获提供商结束确认不会冒充完成。

执行器异常不会静默退回旧 API 循环，不会清空失效的会话并自动重做。桌面版 MCP 使用系统已安装的控制台 Python 启动随包附带的桥接源码；缺少 Python 时明确报错。

## 验证报告（2026-10-19）

- 17 项 Harness/九身份自动化测试通过；1 项真实 Edge 前端测试通过，共18项定向测试。未宣称旧版混合模型全部测试通过。
- 真实 Harness 文件工具写入标记，PowerShell 读取验证成功。
- 重启执行进程后恢复同一会话，正确记住此前标记，无文件读取。
- 真实经理通过 MCP project_assign 创建成员任务，数据库台账验证成功。
- 官方取消接口返回 cancelled。
- 更新后的桌面 EXE 实测：deepseek-1 通过 MCP 向 user 发回 HARNESS_MCP_FROZEN_OK，数据库有实际回执，本轮 completed；不是仅检查模型自述。
- 8765 与8766均确认九个真实身份、engine=harness。现有项目未自动恢复或重放。

官方接口说明：
https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.md
https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/acp/acp/README.md
