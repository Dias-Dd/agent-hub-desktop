# 多 Agent 接入管理

打开「Agent 面板」，点击左上角「管理 Agent」。管理窗口提供删除与添加；添加分为选择接入、选择模型与命名两步。只提供已列出的固定接入选项，不提供手动创建提供商或手填模型 ID 的表单。新接入若尚未启用，可在添加时明确确认启用，或先添加离线身份。

同一模型可重复创建，自动生成不同身份 ID；同名模型在不同平台属于不同连接。显示名称可修改，固定身份、历史和权限主体保留。停用不会删除历史。现有九个 DeepSeek 身份及凭证、会话原样迁移。项目经理固定身份 deepseek-4 可更换平台、模型和显示名称；这次不迁移任意经理身份 ID。正在执行或参与未结束项目的身份/连接不能静默改接入，档位可在执行期间调整、下一轮生效并通知经理。工作流最大并发可设为1–128；Agent 数量不再固定，超过9个显示可滚动的固定尺寸卡片，3/6个使用相应行数。

## 配置顺序

1. 「Agent 面板」→「管理 Agent」→「添加 Agent」。
2. 选择已有接入选项，点击「下一步」。需要时自动读取官方模型目录，不发起推理。
3. 选择模型，默认名称为模型名加序号，也可以自己命名。无需设置角色、连接名、目录、模型 ID 或提供商。
4. 点击「添加 Agent」。未启用的连接会提供明确的启用确认；不勾选也可先添加离线身份。
5. 在卡片上选择档位；任务、额度与停止操作在「详情」中。OpenCode/Ori会按需读取模型支持的档位。
6. 删除普通Agent时从面板移除，历史保留；执行中或仍属于未结束项目的身份不会被静默改路由。

## 接入说明

| 连接 | 实现 | 本轮验证与限制 |
|---|---|---|
| Codex | 原有官方 App Server、model/list、reasoning effort、OAuth登录 | 本机读取7个模型及官方档位；未发送推理。模型和档位在执行前再次核实。 |
| Antigravity | 原有官方 agy 流式CLI、持久 conversation、models及/usage | 复用原适配器，档位目前只开放已验证的medium；其它挡位不能凭空宣称支持。 |
| DeepSeek Harness | 原有官方 ACP、权限同步插件、各身份持续会话 | 原有26项Harness回归通过；目前已验证模型是deepseek-flash，不能任意填别的模型冒充成功。 |
| OpenCode | 官方 opencode acp，独立 session、新消息、取消、MCP | 本机2.0.32握手、模型设置确认、plan模式确认、模型档位读取成功；未发送推理。 |
| Ori | 官方 ori opencode启动OpenCode ACP，沿用Ori认证 | 已找到 ~/.local/bin/ori.exe；本机尚未登录OpenRouter，需用户执行ori login。不会读取或搬运OAuth文件。 |
| WorkBuddy | 安装包内官方codebuddy-lite-wb.mjs或用户指定的CodeBuddy CLI，print/stream-json/resume/MCP | 默认bin脚本缺失dist模块；轻量入口帮助命令验证成功。不假设桌面登录必然能用于CLI，未验证真实任务。 |
| Claude Code | 官方 -p/stream-json/--resume/--model/--effort/--mcp-config | 本机未安装，显示未安装；提供适配器，不自动安装、登录或转用其它模型。 |
| OpenRouter/Gemini/DeepSeek API | 官方OpenAI兼容接口及Hub工具循环 | 环境变量供密钥；保存配置、读/models与真实推理分别进行。此轮无API推理。会话由Hub持久化，不冒充提供商原生Harness。 |

API密钥只通过环境变量传入，页面不保存或回显密钥。默认变量 OPENROUTER_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY；设置后需重新打开服务进程。原DeepSeek的DPAPI密钥保留供现有Harness连接使用。Ori使用官方登录，不要求用户粘贴API Key。

额度：官方能读取时显示账号窗口和恢复时间；否则显示未知，允许手动录入，标注来源。上下文容量、已使用tokens、余额、订阅剩余额度不是同一概念，不互相推算。新连接的本地请求上限默认为1000，0表示用户明确选择不限；DeepSeek继续保持用户已授权的不限额策略。直接API同时限制请求数量，金额未知就记录未知，不能承诺精确费用上限。CLI计数指Hub执行轮次，不是其内部每次模型请求；直接API按请求计数。实际账户账单以提供商为准。

## 数据与接口

新增 SQLite integration_connections / agent_profiles。运行路由以connection ID隔离 provider/config/grant；会话key包含项目、连接、身份、模型，重名模型不会串会话。新身份生成独立Hub Token；修改名字保留ID；停用保留记录。新运行可在项目中派工、接收消息、汇报、停止，持续心跳更新租约；恢复后不重放不确定任务。接入管理API仅user可写。

新增 action：integration_wizard_add、integration_connection_save、integration_agent_save、integration_agent_archive、integration_probe、integration_model_options、integration_quota、integration_submit、integration_stop。状态增加 integrations / integration_runs；后者按当前项目过滤。完整参数见 frontend-actions.json。

## 官方参考

- https://developers.openai.com/codex/app-server/
- https://dev.opencode.ai/v2/docs/cli/acp/
- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/cli-reference
- https://www.codebuddy.ai/docs/cli/headless
- https://www.codebuddy.ai/docs/cli/release-notes/v2.143.0
- https://openrouter.ai/blog/announcements/ori-harness/
- https://openrouter.ai/docs/api/reference/overview
- https://ai.google.dev/gemini-api/docs/openai

使用的是公开CLI/协议；未抓Cookie、未调用桌面私有服务、未用浏览器绕过登录或额度。
