# 状态卡、滚动条、自动填充与演示缩放（2026-10-19）

- 右侧九个极简 Agent 卡片：按 busy/idle/offline 使用琥珀/绿色/灰色框与底色，带小圆形指示灯，只显示身份及状态。
- 工作台统一细滚动条，透明轨道、主题色滑块与圆角，保留进度卡48dvh上限和可滚动性。
- 所有静态表单、输入框、文本框设置autocomplete=off，SafeDOM动态输入同样默认关闭。原生桌面通过Microsoft公开ICoreWebView2Settings4关闭IsGeneralAutofillEnabled与IsPasswordAutosaveEnabled，并读回确认；不删除用户数据或修改外部Edge配置。
- 演示工具栏：缩小/放大、比例选择、适应窗口、1:1；25%~200%常用选项，适应模式可按空间进一步缩小。预览区滚轮直接缩放（无需Ctrl），不改变工作台字体；按住鼠标中键拖动画面。框选工具提供“清除框选”按钮及Delete快捷键，保留文字意见，正在文本框内编辑时Delete不会删除框选。放大后可横向及纵向滚动，框选使用画面归一化坐标。
- 每项目在sessionStorage保存演示页面、缩放比例、滚动位置及各页批注草稿；刷新后可恢复。仅保存本地草稿与查看状态，不保存凭证。切页的草稿相互独立，轮询不重置缩放或输入。

测试：真实Edge在正常/短/窄三种窗口检查1:1、125%、200%、适应与滚动路径；实际reload保留演示页面、200%比例、批注与滚动；框选反馈与确认流程回归通过。状态框/指示灯、滚动条和自动补全属性有浏览器回归。原生WebView2实测两项自动填充设置读回false，白屏恢复仍成功。经理布局、历史阅读与九身份基础回归通过。无付费模型调用。

公开原生接口来源：
https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2settings4
ABI按官方Microsoft WebView2 SDK头文件核对（Settings4 IID cb56846c-4168-4d53-b04f-03b6d6796ff2；password autosave get/put 25/26；general autofill get/put 27/28）。

追加验证：正常/短/窄三种尺寸下的普通滚轮缩放、中键拖动及释放、按钮清除选区、Delete清除与输入框编辑保护通过；清除同步保存到本页草稿。界面原有阅读、滚动、缩放及输入保留测试仍通过。
