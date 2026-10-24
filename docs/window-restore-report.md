# 可见窗口与重复启动修复（2026-10-21）

现场后台宿主152172存在真实AgentMessageHubNative窗口，但IsWindowVisible=false。原因是维护启动用了隐藏启动标志；Win32第一次ShowWindow会遵循STARTUPINFO，忽略应用传入的显示参数。已恢复原窗口到前台，没有停止服务或任务。

修复：原生窗口再次显式ShowWindow，使交互式窗口不被隐藏启动标志吞掉。启动器在认证现有服务、确认运行模式后（恢复已有原生窗口先于新旧界面版本比较），经Windows公开TCP所有者表定位准确服务PID，恢复该PID对应原生窗口后退出，不创建第二个WebView/后台实例。

验证：TCP端口所有者测试通过；真正以-WindowStyle Hidden运行隔离桌面窗口自检通过，window_visible_after_show=true、native_window=true。再次以隐藏启动打开新版EXE，进程正常退出0，原生产服务PID仍152172，原窗口可见；无任务中断。源码备份work/before-visible-window-fix.zip。
