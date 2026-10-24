# 设置与内容层、Hyper-V缩略图

设置继续使用独立原生窗口，保留系统标题栏和关闭按钮；仅隐藏内容顶部重复的SETTINGS/工作台设置，保留屏幕阅读器标题。左侧分类和操作按钮紧凑化，表单与草稿节点复用。项目目录与占用、账号与连接设置默认展开。

主工作区中间和右侧放入同一圆角背景层，与项目栏及标题栏区分，随窄屏和隐藏项目栏适配；聊天输入、日志滚动、右侧进度保留。

虚拟机设置新增预览卡与固定系统Hyper-V管理器入口（virtmgmt.msc）。预览通过管理员桥接调用root\virtualization\v2的Msvm_VirtualSystemManagementService.GetVirtualSystemThumbnailImage，目标为当前Msvm_SettingsDefineState关联的设置，320×180原始RGB565；前端Canvas解码，不依赖客机GUI截图、不登录模型、不采用私有接口。仅在VM设置可见时单路每15秒读取；错误显示原因，未更新时标记保留旧帧；结果消费后删除请求及帧文件，避免长期积累。缩略图不改变电源覆盖状态，不妨碍正在执行命令。旧桥接不支持时明确提示退出旧版并打开新版。

验证：强制三项UI回归、设置/存储/VM表单、缩略图RGB565颜色与可见性、主内容层、宽/窄屏通过。20项桥接/缩略图/桌面原子处理测试通过。真实原生窗口3项通过，6个弹窗关闭/重开、草稿、模态与原生标题栏正常。实际普通用户Get-VM探测返回权限不足，未提升本轮权限或重启现有桥接，因此不把模拟帧当成真实Hyper-V缩略图验证；新版管理员桥接启用后才可读真实图像。

官方接口文档：https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/getvirtualsystemthumbnailimage-msvm-virtualsystemmanagementservice
