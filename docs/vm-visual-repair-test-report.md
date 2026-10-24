# 虚拟机视觉检查修复实测（2026-10-23）

项目513239a6d2d84e8f913d393064ee9965。

原因：桌面服务因覆盖心跳文件失败退出（HubDesktopAgent.ps1第26行，文件已存在）；exec连接仍正常。恢复后在交互桌面启动dist/calc.exe，原始stderr确认为 `egui_glow requires opengl 2.0+`，并非此前推断的3.0+。exec属于Session0，不能代替桌面启动。

修复：心跳及结果采用唯一临时文件+MoveFileEx原子替换/短暂锁重试；桌面任务失败重启，健康检查保留具体错误并恢复停掉的任务。新增desktop_launch(path相对exe,value可选参数)，在登录用户桌面启动、返回窗口/进程/会话/输出错误。exec脚本改独立子进程，exit不退出持久连接，保留退出码、UTF8输出，超时结束子进程树，不再把空结果判成功。请求按提交时间排序。

20项回归通过，含500次真实心跳替换，以及独立PowerShell的显式exit0/exit7/异常/UTF8/环境隔离/超时后继续执行。

客机已部署修复桌面服务，心跳持续刷新desktop.ready=true。在 `.hub-evidence/vm-visual-runtime` 建立独立测试副本，exe与原dist/calc.exe SHA256一致，仅测试目录加入Qt官方软件OpenGL；未改变系统图形驱动、注册表、发布dist或zip。下载归档opengl32sw-64-mesa_11_2_2-signed_sha256.7z的SHA256与官方清单一致：c61f801c1760aa24b02c7a8354323cddf368b86f8f5c34b50b3b224f7d728afd。来源https://download.qt.io/development_releases/prebuilt/llvmpipe/windows/ 。这只是测试环境依赖，不默认捆绑发布。

实际启动进程3852、Session1、窗口983070；取得1024x768真实截图。Hyper-V Win+Up最大化、F1快捷键弹窗真实成功，截图确认。未宣称完成产品全部按钮/业务逻辑验收。

可复测：project_vm(action="desktop_launch",path=".hub-evidence/vm-visual-runtime/calc.exe")，查询request_id完成后再windows/screenshot。不能用exec启动GUI，不能用queued宣称成功。

证据请求：诊断960125bb15ea4224a31597dd496a853e；恢复8833e8701f6a42a3b60a2ab653a12ba1；原始GL错误19ebb323af6249099817e04cc9f425c7；成功启动8620964a11db45faa8b00acebe75e869。截图位于项目.hub-evidence/vm-1a32551c960d47a095e95d60079e6b8b.png与vm-51207767878d41e7b2c4c00df131d774.png。

本轮未调用模型，未清除会话上下文。Hub桌面应用此前已关闭，诊断启动了专用管理员桥接。
