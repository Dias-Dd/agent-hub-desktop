# 经理强停与巡检开关验证

2026-10-21

- project_stop_task：当前经理仅可停止本工作流的成员任务。运行项直接撤销执行、终止本地进程并释放占位；排队项直接取消，不设置 Agent 全局停止锁。
- SQLite execution_revocations 保存逐轮撤销，所有提供商结束回写及共享会话状态写入均检查撤销，API 文件写入与强停串行，CLI 启动后注册和输入发送检查撤销。
- Windows 实际子进程终止测试通过；使用模拟提供商验证阻塞 API、Codex、Antigravity 的晚到结果不会复活旧任务，经理能在旧线程返回前重新派工。未发起真实推理。
- 允许项目静置：仅持久化 patrol_enabled=false，三分钟 periodic 分支跳过；消息和显式定时器不受影响。测试逐表比较确认按钮不改变 executions/messages/agents/workflow_events/audit，也不改变工作流其它字段。
- 浏览器实际点击开关两次，仅发出两次 workflow_set_patrol，无 stop/send/wake 请求。
- 10 项专项测试通过；必需的 manager_layout / reading_browser / nine_browser 均通过。Harness 29、九身份 API 6、接入 22、经理身份审计 29、定时器 22、协调修复 14、Antigravity 证据 11、错误诊断 7、经理输入 8、项目控制 14 测试通过。
- 旧 test_codex_runtime / test_antigravity 仍使用 sol/flash/argon 等已删除固定身份，其旧身份初始化/额度分组断言失败；未将这些旧夹具结果计为通过。新增专项使用现有身份覆盖原生执行器停止回写。
- EXE 需退出托盘后重开才能加载新后端；本次不停止正在运行的 Hub，不唤醒经理。
