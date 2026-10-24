# 模型目录同步与验证入口

## 修复
- WorkBuddy 每次进入添加向导、点击刷新模型或验证接入时读取官方 ACP 菜单；读取官方 ~/.workbuddy/models.json 与 ~/.codebuddy/models.json 的模型元数据，不返回密钥。
- 默认列表包括 ACP 菜单、官方用户配置和既有用户确认项，逐项标注来源；安装包全部候选项独立保存，默认隐藏，用户勾选后才显示。
- 公共 ACP 不保证返回客户端云端完整目录；catalog_complete=false，明确提示不完整。没有宣称目录模型已获账号权限或免费资格。
- 刷新失败时保留过期的上次公共菜单；不把候选目录自动晋升成可用列表，不删除 Agent 或重置会话。
- Agent 面板的旧 DeepSeek 专属按钮改为“验证接入”，打开管理列表，每个 Agent 都有验证按钮，按其实际接入检查，显示命令/目录结果，不发送推理请求。
- 没有逐个硬编码新增模型名称，没有冒充官方 Web UI，也没有抓取 Cookie 或私有接口。

## 实测与限制
本机官方 ACP 握手与 session/new 成功，返回9个菜单项；未发送 session/prompt。客户端完整云端目录在当前安装版本中无法通过普通 ACP 获得，Web UI 专属刷新明确返回 web-ui-only 门禁；Hub 不绕过。space-bunny 未由该接口返回，无法如实标成已发现或已验证。

官方资料：https://www.codebuddy.cn/docs/cli/acp 、https://www.codebuddy.cn/docs/cli/http-api 、https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Model

## 验证
目录来源、候选分离、刷新失败缓存与用户配置去敏测试通过；真实 Edge 测试验证候选默认隐藏、手动展开带来源、关闭后移除、不默认授权。经理长内容布局三种尺寸、阅读位置和 Agent 面板回归通过。
