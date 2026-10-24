# 多 Agent 接入验证报告 · 2026-10-20

## 自动化验证

通过77项测试：接入注册与真实HTTP/浏览器15项，Harness26项，档位11项，九身份基础6项，演示流程/浏览器15项，以及经理布局、阅读状态、九宫格、窄栏档位浏览器各1项。

新增覆盖：12/3个Agent的卡片、派工名单和私聊收件人；重复模型和跨平台相同模型的独立ID；停用低于9个、保留历史；模型/连接/项目维度会话隔离；ACP模拟端到端两轮、第二轮恢复同一会话；模型确认；活跃任务不改路由；旧Harness档位从编辑器同步实际设置；项目绑定目录时保留连接授权上限；权限不预选；轮询不覆盖编辑草稿。1440×900、1024×600、600×800检查通过。

## 本机只读接口验证

- Codex：官方App Server model/list读取7个模型；档位集合包含low/medium/high/xhigh/max/ultra。目录不是访问授权证明。
- OpenCode2.0.32：ACP initialize、session/new成功；设置google/gemini-3.8-flash获得模型确认；读取该模型low/medium/high/default档位；plan模式请求成功。没有发送session/prompt。
- Ori：发现用户目录.local/bin/ori.exe。ori opencode ACP启动前返回未登录OpenRouter（ORI_CLI_OPENROUTER_CREDENTIAL_MISSING），提示ori login；未尝试搬运凭证或自动换渠道。
- WorkBuddy：自带bin/codebuddy启动因缺少../dist/codebuddy失败；改为官方安装包codebuddy-lite-wb.mjs入口，--help成功，确认print、stream-json、model、resume、mcp-config参数。没有启动推理或读取桌面私有认证接口。
- Claude Code：本机未安装。实现公开print模式适配器，真实登录与任务未验证。
- Antigravity/DeepSeek Harness：复用已有适配器；Harness回归通过。此轮不额外启动真实推理。
- 直接API：实现官方兼容接口工具循环及不同模型路由；未发起真实付费请求，不能把本报告视为所有模型的真实推理验收。

## 限制

新连接默认未启用。原有DeepSeek保持已授权不限额；其它连接默认本地1000次、可由用户设为0不限并明确确认。CLI的计数是Hub轮次，不是其内部的每次模型请求；直接API限制请求数量。未知费用和额度保持未知。工作区隔离未经验证的CLI必须由用户明确选择完全访问，不能伪称提供OS沙箱。

没有运行全量旧版测试集合：test_workflows等旧夹具仍引用已移除的sol-2身份，之前已确认在实际执行前失败。本轮运行的是现有DeepSeek架构与本次接入的有效回归集合。

## 打包验证

新桌面EXE在独立临时数据目录执行--smoke-test，退出码0；已认证健康检查、静态资源、严格CSP与桌面凭证交换通过，关闭正常。没有创建模拟消费者，也没有模型推理。

## 备份与部署

代码备份：outputs/before-multi-agent-20261020-091840.zip；修改前桌面SQLite一致性备份：work/before-multi-agent.sqlite3。发行文件与源码包一起更新，不中断当前窗口、不修改现有生产接入授权；重新打开新版后自动迁移注册表并显示新入口。
