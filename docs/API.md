> 前端改造请优先阅读 [当前交接指引](FRONTEND_HANDOFF.md) 和 [源码参数索引](frontend-actions.json)。本文保留早期接口记录，预算范围等可能已过期；以当前源码为准。

# HTTP 与 MCP

Antigravity（仅 user，不向 MCP 暴露）：antigravity_configure / antigravity_submit / antigravity_stop 与 Codex 操作参数同形，身份为 flash-1/flash-2/flash-3/argon/opus，仅支持明确授权的 full 权限；refresh_antigravity 只读查询官方模型与订阅额度。GET /api/state 的 antigravity 包含独立配置、任务、事件、官方窗口及交付验收结果。waiting_quota 代表尚未发起推理，预计恢复后重新读取，不按时间假设恢复。执行中断确认边界见 ANTIGRAVITY_EXECUTION.md。

Codex 真实执行（仅 user，不通过 MCP 暴露）：

- codex_configure：cwd、permission(full/workspace)、max_runs(0–100)、max_seconds(30–3600)、enabled、confirmed=true；保存执行权限与次数预算。
- codex_submit：agent(sol-1/sol-2/astra)、instruction、confirmed=true、可选 task_id；已有任务必须与原文本相同。
- codex_stop：run_id，取消排队或请求官方中断。
- GET /api/state 的 codex 字段包含 config、remaining_runs、runs、events；real_agents 列出已停止模拟并启用真实执行的身份。

完整执行与权限语义见 CODEX_EXECUTION.md。

初始化：`GET /setup` 打开向导（与主页使用相同页面）。认证后的 `setup_status` 返回配置及 CLI/环境布尔检测信息；`setup_save` 接收 project_name、route（simulation/deepseek/codex）、budget_cents、confirmed=true，仅 user 可用。保存预算与配置在同一事务中，不得低于已有保留费用；不会发起模型调用。两项操作均不通过 MCP 暴露。

HTTP origin：`http://127.0.0.1:8765`。除静态文件外，每个请求带 `Authorization: Bearer <identity token>`。

`GET /api/state`：九个身份、任务、可见消息（最新 300 条）、额度、总体进度；user 另有最新 100 条审计和调用。历史数据持续保存在 SQLite，v0.1 无 UI 历史分页。`GET /health`：进程调度心跳是否新鲜。

`POST /api/action`，`Content-Type: application/json`：

```json
{"action":"send","args":{"recipient":"argon","body":"请安排测试","mode":"queue","request_key":"client-unique-id"}}
```

返回 `{"result":...}`，失败 `{"error":"..."}`，HTTP 4xx/5xx。传输层重试 send 时必须复用 request_key，不可生成新 key。

| action | args | 权限 |
|---|---|---|
| snapshot | 空 | 全部身份 |
| send | recipient, body, mode?, request_key? | 私聊全部；群发 * 仅 user/argon |
| heartbeat | status: idle/busy | Agent 本人 |
| poll | 空 | Agent 本人；领取一个消息 |
| ack | message_id, complete?, result? | 收件者本人，且 active |
| assign | agent, title | user/argon，事务内唤醒 |
| progress | task_id, progress, note, status? | 执行者本人；done 须 100 |
| project | progress, note | argon |
| quota | agent, remaining?, resets_at? | user，手动百分比/Unix 时间戳，可 null |
| enable | agent, enabled: boolean | user，控制模拟身份消费开关 |
| refresh_openai | 空 | user，只读官方探测 |
| budget | cents: integer | user |
| prepare | prompt | user/deepseek，不调用模型 |
| approve | call_id, reserve_cents, input_cents_per_million, output_cents_per_million, confirmed: true | user |
| execute | call_id | user，有效批准 + 环境开关 + API key |
| cancel | call_id | user，只限 pending/approved |

MCP 只公开前八种 action。token 绑定调用者，不接收可伪造 sender/actor 参数。身份之间可看任务与状态，但不能读他人私聊。所有 Hub 数据（含消息和任务）以本地工作区为信任边界，不暴露给外网。

调用状态：pending → approved → running → completed / uncertain；pending/approved 可 cancelled。批准占用累计预算；completed 仍占用全部保留额。已过期批准不能执行，可撤销释放。uncertain 无自动退款或重试入口，人工确认后再调整后续总预算，原始记录保留。

示例 Agent 消费顺序：heartbeat(idle) → poll → ack → heartbeat(busy) 定期续租 → progress → ack(complete=true,result=...) → heartbeat(idle)。繁忙时继续 poll 仅会领取立即消息；应先保存业务检查点再接受中断。每个身份限一个消费者，不能将 token 复制到多个执行器。
