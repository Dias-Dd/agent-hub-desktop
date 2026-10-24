# Harness持续会话写入边界修复（2026-10-21）

## 根因与实现

已安装Harness的SandboxPolicyService.resolve默认优先读取不可变session.header.cwd，deployment workspaceRoot仅作无会话后备。恢复旧会话时更改部署目录不会改变实际沙箱边界；另有旧权限投影恢复时序导致新preset可能被旧状态覆盖。

Hub专用Cordis插件在当前独立运行进程中装饰公开sandboxPolicy.resolve与workingDirectory.get方法，将每轮有效权限和工作目录绑定到Hub已授权参数；原方法用于取得其它策略字段，插件销毁时恢复。继续通过permissionPresets.set同步预设。没有修改Harness安装文件、不可变会话头、原会话日志或模型账号。所有检查保持原权限级别，workspace模式没有升级full。

模型请求前验证实际sessionId、权限模式及workspace-write目录一致；不一致时保留会话并停止发送模型请求。只读讨论仍只读，完全访问仅按原授权使用。

## 真实写入验证

运行tools/probe_harness_workspace.py，直接使用本机官方Harness ACP新建/关闭/恢复同一隔离会话，调用实际沙箱文件系统writeText，不调用session/prompt、不发模型请求：
- workspace-write原目录：目录内成功，目录外FS_SANDBOX_DENIED。
- 同一个sessionId恢复到新目录：新目录成功，目录外拒绝；workingDirectory与workspaceRoot均为新目录。
- 同会话read-only：内外均拒绝。
- 同会话danger-full-access：内外均成功。
共4组实际文件读写验证通过，测试文件由隔离临时目录清理。Harness回归27项、项目目录13项及消息链路18项通过。桌面打包与启动自检通过。

## 现场启用

用户明确选择“现在启用，让经理核查续接”。先备份生产库到work/before-write-fix-activation.sqlite3，临时暂停派工，向在途执行发送停止请求；全部执行结束后才退出旧宿主、替换程序并重开。未启动任务保留取消记录交经理重新核对，已完成任务没有重放。原文件和原会话保留。

生产经理检查轮486da0…已running，仍使用原sessionId 51e4edb9-5eae-4e7c-a0c1-faa69cf8a369；permission_verified实际mode=workspace-write，workspaceRoot、workingDirectory和target_cwd均为当前draft-1，workspace_matches_target=true。经理已收到先核查现场和中断/未启动任务，再决定续做或派工的通知。

源码备份：work/before-harness-write-fix.zip。
