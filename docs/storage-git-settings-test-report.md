# 项目文件清理、设置两栏、实时 Git 树

- 修改前备份：outputs/agent-message-hub-before-storage-git-settings-app.zip（上一级 outputs）。
- 清理入口使用预览与用户确认；未移除项目仍允许清理，确认后停止项目与计时器并移除列表项。
- 覆盖主目录、登记和中断创建的项目独立工作区、冻结演示、展示附件；未提交文件也会删除。项目存储统计纳入关联目录，避免重复统计。
- 不操作实际用户项目，不执行任何真实模型调用。不自动重启 Hub。
- 共享目录/存储根目录不会递归删除；目录重定向不会越界跟随；文件占用会返回实际错误，不声称已清理。
- 设置左侧分类，右侧独立滚动；原表单节点、输入草稿、服务状态刷新保持。
- Git 图来自 git log --all --graph，包含分支/合并，最近80条；展开5秒刷新，后台/收起不请求，请求不重叠，切换项目丢弃旧响应，断网保留数据。

## 验证

- test_project_cleanup_git.py：6项通过（真实临时 Git 工作区、合并树、活动项目清理、未提交文件、演示与附件、确认失效、角色权限、共享目录保护、占用失败与重试、外部容量统计）。
- test_storage_git_browser.py：宽/窄屏真实 Edge 验证清理预览、取消不删除、确认执行、两栏布局、图加载/自动刷新、收起停止、断网保留与滚动保留。
- test_settings_refresh_browser.py：宽/窄屏设置、存储草稿、长设置滚动、文件夹入口、加载完成隐藏。
- test_manager_layout.py / test_reading_browser.py / test_nine_browser.py：通过。

实际项目未被删除；清理测试全部在临时目录中进行。

- test_git_workspaces.py：15项通过；test_storage_folder.py：3项通过。
- 打包 smoke：ok=true，16个静态入口、原生窗口与VM脚本齐全。原生启动 smoke：ok=true，Mica、透明WebView、圆角和原生标题栏命中测试通过。
- 宽/窄屏截图已检查：data/storage-git-settings-1440.png、data/storage-git-settings-600.png。
