# v2 发布与完成收尾修复

2026-10-21

现场核查：工作流 21e100ffc35542379961bfe3b5787446 在 19:12:39 提交，Gemini 只读检查在 19:14:19 才结束。运行服务启动于 19:04:30，仍使用旧版页面覆盖门槛：outline 为 arch、实际架构页为 architecture，因而 completed=true 但设计仍 building、version=2、仅保存 v1。

恢复：备份 SQLite 后从 draft-2 冻结 v2，保留 v1。当前在线服务 design_content(version=2) 实测返回 version=2、29 pages、29 preview URLs。没有重做页面，没有调用模型。

改动：
- 提交完成先直接结束本轮剩余成员执行/队列，再冻结页面；旧线程的晚到回写继续受逐轮撤销保护。已经确认的经理完成决定仍有效，不重新引入在途/检查/未读消息门槛。
- 完成返回值明确区分 completed 与 design_review_ready，附带 warnings 和 stopped_tasks；重复提交返回已保存状态。
- 发布失败保留具体 publish_error 并显示错误，不冒充已发布/已确认，不一直显示制作中。
- 初始化恢复已完成工作流中尚未发布的设计；旧队列先取消，完整有效页面自动冻结，版本不重复。活动项目不会自动发布。
- 取消与启动并发时复核执行状态，避免将刚启动任务只改成 cancelled 却漏停本地执行器。

验证：demo_publication_completion 5、manager_completion_authority 1、designs 13、manager_force_stop_patrol 10、coordination_repairs 14、manager_input 8、harness 29、manager_layout/reading_browser/nine_browser 各 1，共 83 项通过。涉及外部模型的测试使用模拟提供商；现有服务只做审阅读取验证。

部署：新版 EXE 和源码压缩包已更新；当前运行的旧后端需从托盘退出后重开才能加载。v2 数据恢复已立即生效。
