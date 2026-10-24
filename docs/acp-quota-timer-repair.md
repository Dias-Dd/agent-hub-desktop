# ACP 会话、额度和计时器修复

2026-10-21

## 现场与原因

- 两个失败身份 agent-719905cf37 / agent-842e6451a7：provider session ses_ea202c703ffeUFKXSxo2Y547mA / ses_ea2023a48ffeZUqvmsw39oy6VY 在 draft-1 创建，正式实施时 Hub 改传产品根目录，session/load 拒绝 cwd 不一致。既有会话仍存在，已用两个本机官方 CLI 无推理读取验证可按原目录恢复。
- Plan 写入失败那轮是 purpose=question、kind=message，来源是经理工作沟通。旧调度统一把非定时器消息归为只读质询。修复只改变已批准项目内经理发给成员的工作消息；成员质询保持只读，原文件资源排队继续适用。
- session/load 会重放历史；旧适配器把这些历史消息混入本轮回复。现在只收集 session/prompt 开始后的新输出。
- Claude 实际记录：18:24:50、18:27:17、18:29:40 三个完成的 task，以及一次完成连接测试；19:29:48 提供商返回 Individual quota reached。官方 Claude and GPT models 周窗口读数为 0%。这批 GPT 后续执行走 integration:codex-local，不计入 Antigravity 窗口。现有数据不足以逐次还原提供商扣额，不据此编造精确消耗原因。

## 改动

- provider_session_roots 持久化原始 cwd；旧库从该 session 第一条执行恢复目录。保持项目会话 key；未换项目不创建替代上下文。OpenCode/Ori 公开支持 additionalDirectories 时添加当前目标目录；新输入明确绝对路径和目录切换，避免写回演示草稿。
- 现代 ACP 配置项 mode 明确确认 Build/Plan；旧协议回退 session/set_mode。MCP 按新执行身份重新挂载。
- cached quota 按连接和模型适用窗口判断；派工和 worker 启动前两处取消耗尽任务，执行记录/任务为 cancelled，经理收到带额度原因的汇报。提供商运行时拒绝也规范化为 cancelled，不自动重跑。仅手动或官方正额度新观测解除对应灰显；限流/并发 429 不冒充耗尽。
- Agent 卡片与极简状态灰显，操作仍可配置；移除全局红色额度面板。原阈值、耗尽与恢复通知保留，适用模型按窗口分组。
- 一次性计时器投递事务内移出 hub_timers，历史最多 500 条；公开 timer_list 与面板只显示活动项。循环定时器保留下一次，重启不重复投递。

## 验证

- acp_project_cwd 6、quota_cancellation 8、quota_ui_browser 1；mandatory manager_layout / reading_browser / nine_browser 各 1，通过。
- automation 22、harness 29、integrations 22、project_controls 14、manager_force_stop_patrol 10、demo_publication_completion 5、coordination_repairs 14、manager_identity_audit 29、connection_tests 26，通过。
- 两款本机 CLI 实际 initialize / session/new / session/load + additionalDirectories / session/set_config_option(mode=build) 都成功；专用临时会话删除；没有发送 session/prompt，没有模型推理调用。data/acp-directory-official-proof.json 保存无密钥验证结果。
- 历史 test_sessions_inbox 18 项中 16 项仍引用已删除 sol/flash/argon 身份而初始化失败；未计为通过。项目上下文和角色分流由新身份回归覆盖。
- 未改动当前项目产物、未重派已失败任务、未向经理发送额外消息，未重启当前活动服务。

参考：OpenCode 官方 ACP https://dev.opencode.ai/v2/docs/cli/acp/；ACP session setup https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/session-setup.mdx 。
