2026-10-18 新增：执行者主动汇报、Flash-3/Astra 独立检查、项目消息受控唤醒、用户单个/全部紧急停止、可选模型止损委托（默认关闭）。详见 docs/COORDINATION_AND_STOP.md。

2026-10-18 最新：已加入 Argon 自动项目分工、巡检、验收与回报；真实三调用闭环通过。详见 docs/ARGON_PROJECTS.md（测试报告同目录时为 ARGON_PROJECTS.md）。

# v0.1 测试报告

## 代理修复更新（2026-10-18，当前）

**44 项自动测试通过（约 12.2 秒）**。定位 CLI 未继承 Windows 系统代理，修复子进程代理继承后，一次真实 Gemini Flash 测试成功返回 HUB_PROXY_OK，官方 SUCCESS、退出码 0。没有使用 API Key、切换账号或修改系统代理。此前地区错误是未继承代理路径的历史结果。Claude 额度零仍是独立限制。详见 PROXY_DIAGNOSIS.md 与 antigravity-proxy-test.json。以下 39/29/更早版本为历史阶段记录。

## Antigravity 更新（2026-10-18，当前）

**39 项自动测试通过**。已实际读取 agy 1.4.0 的模型列表和官方共享订阅额度。新增覆盖 Google 订阅队列、模型/权限 init、API 环境排除、额度等待与再次核实、Codex/Antigravity 全局单执行槽、两个 HTTP 入口隔离、地区错误不能冒充成功。

真实 Gemini Flash 验收只尝试一次：官方返回 `FAILED_PRECONDITION (code 400): User location is not supported for the API use.`，状态 failed，未生成测试产物。Claude 五小时额度为 0，因此未发起其推理验证。没有绕过地区限制、购买额度或切换 API。见 ANTIGRAVITY_EXECUTION.md、antigravity-live-test.json 和 antigravity-probe.json。下面 Codex 真实成功及更早基础版本数据为历史记录；当前自动测试总数以本段和 test-results.json 为准。

## Codex 真实执行版（当前）

新增官方执行器与 HTTP 集成验证，当前 **29 项自动测试通过**，另有 **1 项真实 Sol 工作回合成功**：实际创建三份文件并运行两项单元测试，两项均通过；开发侧独立复跑同样通过。权限为 danger-full-access + never，effort medium。真实执行约 40 秒，官方记录 70280 total tokens（包含缓存输入），不等于美元费用。详情见 CODEX_EXECUTION.md 与 codex-live-test.json。

新增覆盖：具体任务授权、次数预算占用/取消释放、模型权限参数、真实/模拟队列隔离、已有任务不可静默改写、官方完成与中断事件处理、命令/文件/用量记录、重启运行中任务不重放、API Key 登录拒绝。Windows CLI 进程 Job 与官方 OAuth/模型/额度已只读验证。

当前实例已启用完全访问；未追加真实生产任务。真实任务面板和权限摘要已在浏览器检查。仅 Sol 实际推理实测；Astra 模型目录可用，未消耗额度重复推理；真实取消未另做付费实验。DeepSeek 仍无实际调用。

## 基础版本历史记录

以下 22/17 项和“真实调用 0 次”均是此前基础版本的历史状态；当前结果以上段与机器可读摘要为准。

初始化向导更新：新增 5 项测试，当前 **22 / 22 通过**（约 9.1 秒）。新增覆盖环境密钥不泄露、配置持久化且不生成模型授权、非法配置/越权拒绝、预算不能覆盖既有保留费用、HTTP 向导路由与保存。浏览器已实际走通连接 → 项目 → 接口检查 → 零预算确认 → 保存 → 演示任务完成；未勾选确认时保存会被拦截。截图见 `setup.png`。下文 17 项为基础版本原始测试记录。

日期：2026-10-17，Asia/Shanghai。Windows 11 本机，Python 3.13.7。测试结果：**17 / 17 通过**，0 失败、0 错误，约 8.4 秒。机器可读摘要见 `test-results.json`。

## 已实际执行

| 层面 | 验证与结果 |
|---|---|
| 身份与 Prompt | 九个固定身份、角色与系统 Prompt 初始化成功 |
| 立即/排队 | 繁忙时排队等待；立即消息优先；旧消息暂停后继续；两条立即消息不反复互相抢占 |
| 确认与幂等 | delivered / acknowledged / completed 分离；完成确认可重复；群发九收件人；相同 key 去重与冲突拒绝 |
| 并发 | 30 次并发相同 key 只创建一条；12 次并发领取只有一个成功 |
| 权限 | 身份凭证鉴别；他人私聊不可读；任务分配、经理汇总、本人进度与额度读写隔离 |
| 任务与进度 | 分配与唤醒事务、仅本人汇报、done 须 100%、经理整体报告 |
| 心跳/租约 | 心跳续租，租约过期重投，离线显示 |
| SQLite 恢复 | 重开数据库保持凭证，未完成消息重新待领取，工作状态重新离线 |
| 模拟端到端 | 九个 Agent 无模型账号均可被唤醒、确认并完成消息、回复用户 |
| HTTP | 真正启动本地服务，界面资源可读，任务自动模拟完成至经理 100%；错误 Host/Origin/token 拒绝；错误路径不发生写入 |
| MCP | 启动真实 stdio 子进程，初始化、八工具发现、经 HTTP 读九身份；越权任务分配返回 isError |
| 费用门禁 | 真实开关缺失拒绝、非用户不能批准、明确确认要求、单次授权、防重复执行、过期拒绝 |
| 并发预算 | 两个同时批准争夺一份预算，仅一个获准；撤销释放未执行保留 |
| 网络/计费不确定 | 假连接器模拟网络失败，调用标 uncertain，占用预算，不能自动重试；运行中重启同样 uncertain |
| DeepSeek 请求 | mock 传输核验官方 URL、模型名、256 输出 tokens、关闭 thinking、没有 tools |
| Supervisor | 真正启动常驻父进程，发送待处理消息后终止服务子进程；自动创建新 PID，SQLite inbox 中原消息保持 pending |

首轮测试发现共享 SQLite 连接的未加锁读取存在并发问题，已将 Agent 查询纳入同一可重入锁；相关并发测试复验通过。

## 官方只读探测

- **OpenAI**：本机 `codex --version` 为 `0.163.0-alpha.10.2`；App Server stdio 初始化成功，`model/list` 实际返回 `gpt-6.1-sol`、`gpt-6-astra` 及 medium effort；`account/rateLimits/read` 返回实际共享额度窗口。只保留能力/窗口信息，过滤账户 ID 和可兑换额度重置信息。未启动 thread/turn，未消耗模型推理。
- **Antigravity**：`agy` 未安装；官方文档确认 headless/stream-json 接口存在，但指定模型、medium、自动启动推理、取消、账号额度接口均未本机验证。
- **DeepSeek**：当前进程没有 `DEEPSEEK_API_KEY`，probe 明确返回未设置、未发送请求。官方文档已核实 `deepseek-flash`、models 和 chat/completions；实际账号与推理连通尚待密钥及单次批准。

## 界面验收

通过本地浏览器输入随机 User token，看到九 Agent 卡片、空闲心跳和 Supervisor 健康状态；在页面实际分配任务，随后看到消息完成、模拟回复、任务 done/100% 与项目经理模拟汇总；实际群发到九个收件人，并读取官方额度。页面截图见 `dashboard.png`。未点击付费执行，未创建真实模型授权。

## 未执行与边界

- 真实模型推理调用 **0 次**；假连接器成功不是实际 DeepSeek API 成功。
- OpenAI / Antigravity 的真实任务执行与中断仅做适配器设计，尚未实现可调用执行器；不会因在同一台电脑已有 OAuth 而自动消费。
- Windows 登录启动脚本已提供但未注册，未测试关机/登录后的真实调度。Supervisor 已测试运行期间的子进程故障恢复；机器关闭、睡眠或自身停止时无法运行。
- MCP 使用 2025-11-25 stdio 兼容模式，并非全部协议版本/客户端认证套件；当前测试使用真实 stdin/stdout JSON-RPC 客户端，不声称通过官方认证。
- v0.1 为单机单项目原型：无跨机器部署、多用户 ACL、TLS、自动升级迁移、审计防篡改或历史分页。至少一次投递可能重复，消费者必须幂等。
- 预算为保守保留账本，依赖用户核实的单价与提供商 token 上限，不能替代提供商账户支出限制。

## 复现

在项目根目录运行 `python -m unittest discover -s tests -v`。所有测试使用临时数据库与随机端口，不调用真实模型，不修改交付实例的消息或预算；Supervisor 故障测试仅结束自己启动的临时进程。
