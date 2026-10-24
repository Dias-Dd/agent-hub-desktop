# Antigravity 历史错误误报诊断

结论：最初一次空函数调用是真实错误；后续两轮正常完成，但CLI将历史错误继续放在终端result.status/error中，Hub按ERROR判断失败，经理恢复两次后项目blocked。

本地CLI版本1.4.2。只读检查官方导出的 transcript.jsonl，ERROR_MESSAGE只出现在步骤409；后续411–417和418–424均无新错误，最后PLANNER_RESPONSE为DONE且与对应result.response完全相同，进程退出0。官方问题库有同类报告：https://github.com/google-antigravity/antigravity-cli/issues/1048 。这不是因为本轮输入太长，也不需要清空会话。

修复仅在以下全部成立时识别历史误报：恢复同一UUID会话；退出0；无权限拒绝；本轮准确输入及时间对应唯一USER_INPUT；当前轮无ERROR_MESSAGE、模型流式ERROR或stderr AGY_ERROR，普通工具错误仅在后续已正常完成时单独保留证据；末条模型回复与result.response一致；同样的错误文本只在此前的系统错误步骤中出现。证据缺失、格式变化、进程非零、新错误、部分回复、无法匹配输入等一律不提升为成功。不会只因有回复而忽略ERROR。

证据来源为官方说明的导出日志，不访问或修改提供商私有数据库、不删历史、不改会话、不抓Cookie。原始CLI结果保留，单独记录判定依据。文档：https://www.antigravity.google/docs/hooks/ 。

真正的新空函数调用停止自动经理恢复，保留上下文和队列，不再启动两次同类重试。此次纠正两条已核实的历史误报前备份了Hub数据库，首条真实失败保留。只将因该误报而blocked的原项目恢复active，并重新核实原授权、有效期和停止锁，未扩预算、未重跑旧任务。

184项回归通过，覆盖新错误、历史误报、缺日志、错误退出码、权限拒绝、部分回复、不同错误、输入/时间不匹配、重复锚点及停止自动重试。原始duration_seconds、num_turns和usage为会话累计指标，不应据此将每个回合解释成数小时新执行。官方说明：https://www.antigravity.google/docs/cli/headless/ 。

边界：本次定位并修复了历史错误重复触发项目阻塞的原因。最初模型为何生成空函数调用，现有导出记录没有原始无效函数参数，不能凭这些记录确定其模型侧生成原因。

真实联调还修复了调度线程只在数据库写入started、未将时间传给执行器的问题。证据核验器此前因此保守拒绝一次已完成回合；已用完整工作线程而非手工执行器测试覆盖，原始结果再次经只读证据校验后纠正。原始日志和备份保留。

最终版另区分已由模型处理完的普通工具错误（例如读取不存在的文件）与致命模型/系统错误。普通错误步骤保留在证据中，不声称文件读取成功；未知步骤、未完成回复、非零退出或本轮AGY_ERROR仍拒绝提升。184项完整回归通过。

补充覆盖：导出日志中后台命令的GENERIC步骤可能停留RUNNING；只有对应实时tool DONE事件证明同一步结束时才接受，未知运行步骤仍拒绝。此问题的真实记录包含步骤498与511，现已交叉核对。

最终真实验证：在同一原会话发送一次禁止工具与派工的短文本验证，返回HUB_CONTEXT_OK，status正确记为completed；原始CLI status仍为ERROR，核验事件verified=true、无本轮系统错误。未换会话、未清空历史；随后通过原授权workflow_wake恢复项目。


## 2026-10-19: truncated long-plan exports

The official exported transcript truncates long content with `<truncated N bytes>`. Verification now checks the retained prefix/suffix and exact omitted UTF-8 byte count. Truncated final output additionally requires the complete matching live response and its DONE event for the same step. New system errors, incomplete streams, wrong step IDs, denied actions and nonzero exits still fail verification.

185 tests passed. Recorded discussion run 8e3424b57e144f11a5c755cf7a576854 was verified against current user step 556, final step 558, and historical error step 409. The original 9,447-character JSON response was recovered through plan_recover: revision 1, awaiting_approval, five proposed tasks, no workflow created and no new inference. Original provider error evidence and conversation remain preserved. This fixes the long-export verification path; it does not establish the cause of the original provider malformed call.
