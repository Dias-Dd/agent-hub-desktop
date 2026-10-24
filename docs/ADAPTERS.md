当前代理修复：Antigravity Gemini Flash 真实请求已成功；此前地区错误来自 CLI 未继承 Windows 既有系统代理。当前核验以 PROXY_DIAGNOSIS.md 为准。

<!-- 适配器历史设计与当前核验并列；Antigravity 当前状态以 ANTIGRAVITY_EXECUTION.md 为准。 -->
# 官方适配器验证与执行边界

最新更新：OpenAI 官方真实执行器已实现并成功进行一次 Sol 代码任务验收。具体权限、队列、停止与预算见 [CODEX_EXECUTION.md](CODEX_EXECUTION.md)。Antigravity 已接通官方 CLI 与订阅额度，真实 Gemini 请求被地区限制拒绝，Claude 额度为零；当前实测见 ANTIGRAVITY_EXECUTION.md。

核验日期：2026-10-17（Asia/Shanghai）。网页支持某接口不等于本机已安装、账号已获权或指定模型可用。固定业务身份和提供商实际 model slug 分开保存，不静默替换。

| 能力 | OpenAI OAuth / Codex | Antigravity CLI | DeepSeek |
|---|---|---|---|
| 官方自动化入口 | `codex app-server --stdio`，本机 0.163.0-alpha.10.2 已只读验证 | 文档有 `agy -p` / stream-json；本机无 agy | HTTPS 官方 API，源码已实现 |
| 指定模型 | 本机 model/list 返回 gpt-6.1-sol / gpt-6-astra | Gemini 3.8 Flash / Gemini 4 Argon Medium / Claude Opus 5.5 Medium 均未本机验证 | 文档列出 deepseek-flash；当前无 key，账号列表未验证 |
| 推理 medium | 本机模型目录含 medium | 未验证；不能将显示名 Medium 当模型 slug | 本版本关闭 thinking，只做短文本连通执行 |
| 启动推理 | 已实现 thread/start + turn/start，真实 Sol 文件写入和测试通过 | 设计使用官方无界面输入；v0.1 禁用 | 已实现，环境开关 + 预算 + 每次用户确认 |
| 中断 | 已实现 turn/interrupt 并等待最终事件；取消由协议模拟测试，未额外做真实取消实验 | 未验证；杀进程不保证服务端取消和停止计费 | 不支持取消已发出的请求；超时结果标不确定 |
| 额度 | 官方 account/rateLimits/read，本机成功，只读手动刷新 | 文档有 /usage，但没有本机机器接口实测 | 余额不是模型配额，v0.1 保持未知/手动 |

## 适配器契约（OpenAI 已实现；Antigravity 后续依据）

统一操作：`probe → capabilities → submit(approval, checkpoint) → events → checkpoint → finish`；`interrupt(turn_id)` 必须返回 requested / confirmed / unsupported，只有 provider 最终事件可以确认取消；`quota()` 返回 source、scope、observed_at、windows 与 resets_at，读不到为 unknown。

能力列表分别记录 installed、authenticated、models、reasoning_efforts、headless、interrupt、quota。失败不得将 unknown 当 true。真实执行只能经审批账本，审批需扩展为绑定 provider/model/effort/prompt/工具权限/费用上界/有效期，不能复用本版本仅针对 DeepSeek 的批准。

OpenAI 由官方 CLI 自身管理 OAuth，不读取/导出其 token；`initialize → initialized → model/list` 分页完整读取，再核实目标模型与 effort。真实执行前建立符合用户所选权限的 thread（可为完全访问），收到明确 threadId/turnId 后才记录 active。App Server 的权限请求须转交用户，不能一律批准。中断后等待 turn/completed(interrupted) 再确认 Hub 消息；断连时标 uncertain 并人工核对，不能直接重发。额度窗口按 bucket 展示，不操作赠送重置或购买额度。

Antigravity 先核对官方安装来源，再由用户登录，运行无推理的模型目录/权限检查。官方无界面使用 `agy -p ... --output-format stream-json --model <verified-slug>`，连续模式文档给出 `--input-format stream-json` 和 user 事件。必须按官方事件解析结果、usage、error，并将 hub Prompt 通过官方支持的配置注入。当前未验证模型与取消/工具审批传输，不构造猜测性实时执行器。CLI 的 /usage 命令是否能稳定无推理、机器读取、按账号权限运行需实测；不抓 UI、Cookie、内部网络。

## 官方来源

- [OpenAI Codex App Server](https://learn.chatgpt.com/docs/app-server)：stdio、模型发现、turn 中断、账号额度协议。本机 probe 仅发初始化和两个只读方法。
- [Antigravity Headless](https://www.antigravity.google/docs/cli/headless/)：官方无界面参数及输入/输出事件。
- [Antigravity CLI reference](https://www.antigravity.google/docs/cli/reference/)：CLI 能力目录；模型访问需本机验证。
- [DeepSeek models](https://api-docs.deepseek.com/api/list-models/) 与 [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)：Bearer 模型目录及文本请求。
- [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/)：执行前重新核实单价，项目不硬编码可变价格。
- [MCP 2025-11-25 stdio](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)：本项目有意选择兼容版本，不声称实现所有更新协议。
