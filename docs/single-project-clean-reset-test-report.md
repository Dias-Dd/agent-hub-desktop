# 单项目执行、清理后重启与界面调整

修改前备份：上一级 outputs/agent-message-hub-before-single-project-clean-reset-app.zip。

## 行为

- 正在执行的项目不能清理，不会自动停止任务以便删除。确认清单后若新任务启动，再次拒绝清理。
- 暂停/结束且没有真实运行进程后可清理。未移除项目保留名称/设置；成功后旧工作流、讨论、未启动执行与消息归档，旧计时器清除。
- 发新消息即重建空目录并开始新讨论；项目的模型会话键加入清理代际，历史提供商 ID、API 上下文均不复用。正常未清理项目仍持续会话。
- 项目全局执行槽覆盖工作流启动/恢复、讨论、通用执行器调度、消息路由、巡检、计时器与额度恢复。暂停项目的未启动执行不占据执行槽，尚在运行/中断中的进程仍占据。
- 群聊输入默认只有展开图标，可收起；草稿/刷新/发送方式保持。
- 标题栏删除前进、后退、目录、额度、设置的重复按钮。保留侧栏切换和 Windows 原生系统按钮。
- 原生 Close 背景与命中区域延伸至最右侧，修复看得见的边框空隙；DWM 原生图标、Mica、圆角、最大化和 Snap 保留。

## 验证

- test_single_project_reset.py：9项通过，包含活动清理拒绝、确认期间新执行、单项目启动/讨论、清理后旧进度/工作流不再展示、发经理消息、会话重新创建、暂停释放槽、旧执行取消、计时器暂缓。
- test_project_cleanup_git.py：6项通过。
- test_automation.py：26项通过；test_designs.py：13项通过；test_git_workspaces.py：15项通过。
- test_group_composer_browser.py：1440×900、1024×600、600×800，默认收起、展开/收起、轮询草稿、可见发送区、标题栏图标检查通过。
- test_manager_layout.py、test_reading_browser.py、test_nine_browser.py 通过。
- test_storage_git_browser.py：宽/窄屏清理确认、取消、Git自动刷新、滚动保持通过。
- HUB_NATIVE_UI_TEST=1 test_native_windows.py：3项通过；6次原生弹窗开关、模态/非模态、原生 Close、最右端关闭命中、真实鼠标悬停 Windows Snap、圆角通过。原生窗口截图已检查。
- test_sessions_inbox.py：旧固定 sol/argon 身份夹具导致16项报错，2项通过；使用修改前完整源码备份在临时目录复跑，同为18项中16项报错。非本次新增回归，未声称此旧套件通过；日志 data/sessions-inbox-prechange-baseline.log。

未删除真实项目，未调用真实模型，未自动重启用户工作台。

打包验证：package smoke 与 native window smoke 均 ok=true；16静态入口、VM脚本、Mica、透明WebView、圆角、原生Close/Snap命中测试正常。
