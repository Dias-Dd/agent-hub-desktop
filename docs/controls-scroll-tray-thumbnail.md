# 控件、滚动、托盘、缩略图与动画

控件标题/图标不可作为文本被拖选；聊天、报告、代码、输入框仍可选复制，选区色使用主题强调色。标签改为紧凑的单色SVG分段按钮，保留清晰激活差异与键盘焦点。

状态卡片内滚动区域允许滚动链传递，空计时器卡片及已到滚动边界时可带动外层项目状态页。Git分支列表最小90px、最大154px，Git所在行510px，提交树仍有独立空间，卡片间距保留。

托盘读取数据库快照时复用hub.quota_state.status，与前端依赖的后端额度判断一致，支持官方共享窗口、模型适用窗口、手动额度与明确拒绝记录；耗尽/模型不可用优先于busy并显示offline，不发额度查询或推理请求。

缩略图：CIM OctetString在115200字节像素外可带4字节网络序长度头。按声明长度验证后移除，兼容长度计入/不计入长度头两种表示与裸RGB565，不任意截断未知格式。回归覆盖115204有效帧、坏头拒绝、裸帧和颜色不偏移。

动画：移除每帧grid布局插值，切换时布局一次，再通过Web Animations API的transform/opacity做240ms非线性FLIP过渡；支持连续点击取消续接及减少动态效果，不永久保留will-change图层。实际桌面帧率仍受WebView/GPU和负载影响，未宣称所有机器零掉帧。

打包说明：主程序已由PyInstaller编译打包为exe；Hyper-V管理员桥接仍为PowerShell脚本，因此UAC显示PowerShell。重新打包不会把该组件变成原生程序。本次未冒充已完成原生管理员组件替换，也未重启正在使用的虚拟机连接。

验证包含真实CDP鼠标滚轮事件验证空卡片滚动链、控件user-select、额度托盘优先级及恢复、CIM带头/裸图像、动画中间帧与三项强制UI回归。未使用真实模型额度。

接口依据：https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/getvirtualsystemthumbnailimage-msvm-virtualsystemmanagementservice
OctetString格式：https://www.dmtf.org/sites/default/files/standards/documents/DSP0004_2.5.pdf （F.1）。

最终20项回归通过，打包与原生窗口冒烟通过。
