# 上下文保留与虚拟机传输诊断

修改前备份：上一级 outputs/agent-message-hub-before-context-vm-diagnosis-app.zip。

- 清理文件不再更新 project_reset_epoch，不移除 agent_sessions，也不清空讨论 history。项目会话 ID 和提供商会话 ID 继续保留。
- 旧任务/工作流/计时器仍归档，避免重放已经失效的工作；讨论回到 draft，旧计划和演示引用清除，历史对话保留。下次重建目录时只附一条必要的“文件已清理、旧证据失效”状态说明。
- 现场只读核查：当前真实数据库的 project_reset_epoch 记录数为0，未发生上一版本清理功能导致的模型上下文重置。
- 最近 deepseek-2 的 efcb9482...：max_seconds=1200，开始1792744874.249，结束1792746075.205，约1201秒，uncertain，错误“任务时间预算已到”。平台时限，不是提供商额度耗尽。发现 deepseek_runtime 的 authorized_max_seconds 也为1200，项目时限被 min 静默压低；修复为 Harness 在用户确认项目设置时使用该时限，保持 grant_id 与费用字段，不直接改动当前授权或在途执行。API 费用授权的时限上限逻辑不变。
- VM 请求2f47f792...、4631bad5...：目标目录已存在而拒绝传输；58e9a964...：VM未连接。queued不能当成功。
- 改 push 为逐文件按精确目标路径覆盖，completed前核对SHA256；已有目录可覆盖，不删除额外文件，不再复制成crates/crates。MCP描述和入队回执明确要求查询最终状态。
- GUI记录52f3906a...：session_of_exec=0、calc_session=0；后续读取GUI日志的请求失败“VM未连接”。没有已确认OpenGL3缺失的原始报错，因此未擅自装Mesa或改应用渲染后端。当前宿主Hub进程仍为AgentMessageHubDesktop-0779327a8300，在Session1，不应套用guest exec的Session0结论。

验证：test_single_project_reset.py（11项，包括清理后相同讨论与提供商会话继续）；test_vm_transfer_overlay.py（真实Windows PowerShell本机目录，远端调用替身：目录覆盖、文件覆盖、不嵌套、不删除其它文件、哈希不符报告失败）。不启动真实模型，不改实际项目文件，不重连正在运行的虚拟机。真实Hyper-V传输新路径未在本轮实测。

追加验证：test_vm_bridge.py 16项、test_project_scope_fix.py 13项，以及三项必跑UI回归和Git/清理浏览器回归通过；打包与原生窗口smoke均ok=true。
