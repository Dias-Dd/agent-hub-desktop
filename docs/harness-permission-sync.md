# 持续会话权限同步修复（2026-10-19）

问题：ACP 会话第一次用于讨论时，官方 permission-presets 会持久记录 read-only。后续恢复该会话即使启动环境和默认 sandbox 配置已改为 workspace-write，已记录的权限仍优先，原生文件工具继续拒绝写入。Hub 对 workspace 授权本来就拒绝额外提权，所以模型只能报告阻塞。

修复：每轮通过官方 --patch/Cordis 插件入口挂载 Hub 自有 permission-sync 扩展，在公开 session/created 生命周期中调用公开 PermissionPresetService.set(session, mode)，由官方规范写入 sandbox/approval 事件；再通过 SandboxPolicyService.resolve 核对生效值。只同步当前 Hub 已授权模式，讨论/质询/独立检查保持 read-only，普通实施采用 workspace-write 或已有 full 对应 danger-full-access；不批准额外的 workspace 外提权，不篡改原生会话日志、不新建替代会话。

模型请求前必须拿到该会话权限确认记录；缺失或不匹配会停止，不能再把预期权限当成实际权限。系统事件 deepseek.harness.permission_verified 记录真实模式与会话号。

验证：26项 Harness 测试、11项演示流程测试通过；另外用真实官方 Harness/API 执行两轮（本轮有小额真实模型调用）：先只读讨论，再恢复同一个会话写 permission-probe.txt 并读回 WORKSPACE_WRITE_OK。保持同一会话 ID、文件实际存在、无需提权。最初仅改默认配置的测试未通过，因此没有将那个不完整修复部署。

官方来源：
- https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/interaction/permission-presets/src/index.ts （公开 set 与持久权限语义）
- https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/session.md （公开 session/created）
- https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/reference/README.md （官方 --patch 扩展入口）
