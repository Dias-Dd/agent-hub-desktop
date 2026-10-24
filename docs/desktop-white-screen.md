# 桌面白屏检查与恢复（2026-10-19）

现场：原生窗口与WebView2进程仍在，窗口中页面文档为空；8766的health、HTML、JS、CSS和state均200，state约1.46MB、响应约0.1秒，数据库21.35MB，检查时无在途任务。Windows存在WebView2 RADAR_PRE_LEAK_64预警，但未取得当前白屏的具体崩溃堆栈，不能据此断言某个Hub内存泄漏就是直接原因。

明确缺陷：旧原生宿主未订阅ProcessFailed，也没有页面存活检测；还拦截F5/Ctrl+R，页面故障后无法自行恢复。

修复：
- 使用官方ProcessFailed接口处理浏览器/渲染器退出、无响应及GPU故障，只重建/导航WebView，不动后台任务和模型会话。
- 每10秒用复用的ExecuteScript回调探测页面结构；连续两次空文档、超过35秒无回调才触发恢复。恢复后给20秒加载宽限。
- 自动恢复15秒冷却、5分钟最多3次；失败不会无限刷新，窗口标题提示F5重试，保留诊断日志。手动F5/Ctrl+R放行，原生窗口菜单也提供恢复入口。
- 回调对象复用，避免每次健康探测累积COM回调引用。
- 窗口不可见时页面轮询降到15秒，回到前台立即刷新；后台Supervisor继续运行。
- 未发送的需求、经理回复与群聊输入按项目临时保存于sessionStorage，页面重载后恢复；凭证和API密钥不在其中。

验证：4项恢复策略测试通过，包括10万次状态推进后的有限历史；真实Win32/WebView2隔离测试用NavigateToString制造空白文档，随后自动恢复真实工作台，1次恢复通过；实测生产窗口F5可恢复并留有desktop-ui.log记录；真实Edge实际reload确认最近项目和未发送草稿保留。经理布局、卡片、阅读位置、聊天跟随回归通过。测试未调用付费模型。

生产恢复前已备份SQLite，确认0在途任务后关闭旧白屏窗口，打开新版；现场确认重新显示项目9个ds、已有完成记录与输入框。未对完成项目重放执行。此次未做数小时耐久测试，仍需观察长期运行。

官方参考：
https://learn.microsoft.com/microsoft-edge/webview2/concepts/process-related-events
ICoreWebView2 ABI按Microsoft官方NuGet SDK 1.0.2903.40 WebView2.h核对（ProcessFailed=25，ExecuteScript=29，Navigate=5），没有远程调试或私有接口。
