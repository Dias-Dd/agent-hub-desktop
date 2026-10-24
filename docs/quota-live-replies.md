# 额度与实时回复

额度速览只包含现有启用 Agent 的接入提供商。同一接入的共享窗口不因多个 Agent 重复展示；不同连接保留账户标识，不推测是否同一账户。官方窗口、手动记录、API 余额分别标注。无法读取的订阅额度显示未知。点击刷新才查询官方接口，普通页面轮询不重复调用余额服务。

DeepSeek API 余额只使用用户显式配置的 API 凭证，与 Harness 订阅不混为同一账户。OpenRouter 展示当前密钥剩余额度；管理密钥才能读取账户余额。官方依据：https://api-docs.deepseek.com/zh-cn/api/get-user-balance/ 、https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key 、https://openrouter.ai/docs/api/api-reference/credits/get-credits 。

经理回复在独立阅读区域实时更新，保留草稿输入、选中内容及非底部阅读位置。Harness、Codex、Antigravity 和 ACP 接入转发提供商公开回复片段；不提供流式输出的适配器继续显示等待状态，结束后展示完整结果，不模拟打字。Codex 事件名经本机官方 app-server JSON schema 核验。仅展示提供商公开摘要或工具进度；不采集 ACP agent_thought_chunk、Codex reasoning/textDelta 等内部思考内容。提供商未公开摘要时明确提示。

实时草稿不代表讨论完成，不会绕过计划批准。连接使用用户认证请求头和项目隔离，切换项目关闭旧流。断开后使用持久快照恢复；页面关闭不取消模型任务。新增测试全部使用模拟输出，不消耗模型推理额度。
