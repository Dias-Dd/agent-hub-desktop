# macOS 控件桥复用调查

调查日期：2026-10-26。已通过选定 Tart macOS 客体内的 Peekaboo 实际接入验证。

## 已核对的上游实现

- OpenClaw 的 macOS computer provider 提供 Peekaboo（默认）和 CUA，窗口/控件能力按 provider descriptor 声明。其应用配对、策略和 Gateway 生命周期并非 Deskfellows 的接口，不直接照搬。
  https://github.com/openclaw/openclaw/blob/main/docs/nodes/computer-use.md
- Hermes 的 computer_use 是 cua-driver 的 MCP 适配层，含驱动发现、版本契约、会话/权限和动作转换。复制 Hermes 包装层本身不会得到原生 AX 实现。
  https://github.com/NousResearch/hermes-agent/blob/main/tools/computer_use/cua_backend_driver.py
  https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/computer-use.md
- Peekaboo 导出 PeekabooAutomationKit 和 PeekabooBridge，依赖 AXorcist 0.2.2。根 Package.swift 声明 macOS 14+；AXorcist 提供 AX 元素树、原生动作和 value 属性写入。
  https://github.com/openclaw/Peekaboo/blob/main/Package.swift
  https://github.com/openclaw/AXorcist/blob/main/README.md
- OpenClaw、Hermes、Peekaboo、AXorcist 和 Cua 根许可均已核对为 MIT。直接复用需保留相应版权和许可；打包时还需核对选定组件及依赖的实际许可，不把根许可代替所有二进制授权。
  https://github.com/openclaw/openclaw/blob/main/LICENSE
  https://github.com/NousResearch/hermes-agent/blob/main/LICENSE
  https://github.com/openclaw/Peekaboo/blob/main/LICENSE
  https://github.com/openclaw/AXorcist/blob/main/LICENSE
  https://github.com/trycua/cua/blob/main/LICENSE.md

## 项目接入边界

优先验证 Peekaboo/AXorcist 的现成控件能力，而非立即独立重写完整 AX 驱动。当前客体实测 macOS 15.7.7 arm64，符合上述库声明的系统下限，但这不等于运行验证完成。需继续固定源码版本、核对发布二进制系统下限、实际运行与 TCC 责任身份。

驱动运行位置必须在选定 Tart 客体；宿主保留 project_vm、经理授权、只读轮次约束、取消和桌面租约。不得直接复用上游自动重试/权限提升策略，不得把宿主桌面当作客体的回退目标。使用公开许可组件不代表可绕过客体辅助功能授权；不修改宿主 TCC、安全策略或购买云端服务。

## 当前实现和验证

固定官方 Peekaboo 4.9.7 发布版（CLI commit 5639e7050），发布二进制实际要求 macOS 15+ ARM64，不能用根库的 macOS 14 声明替代。安装前校验固定 SHA-256 和签名 TeamIdentifier FWJYW4S8P8，CLI 与 GUI App 均只运行在所选访客中；原包 LICENSE 随安装保留。

`project_vm` 已接入 windows / ui_tree / ui_invoke / ui_set_value。每次调用明确指定访客 GUI Bridge socket；不回退到宿主、其他 daemon 或付费模型。主机端保留桌面租约、项目/Agent/VM/窗口归属、PID 代际校验、60 秒控件有效期；写操作前消费快照，失败也不重放。部分窗口清单和不可操作控件如实报告。

设置 → 虚拟机 → 启用控件操作，以及首次引导的 Tart 步骤，均可进入同一安装/权限面板。用户确认后自动下载并安装驱动；访客 TCC 权限必须手动授予。连接虚拟机时自动检查已有驱动权限，不自动安装或修改授权。

2026-10-26 在 agent-hub-macos-validation（macOS 15.7.7 ARM64）中验证：正式安装方法完成签名与版本检查；GUI Bridge 三项权限均已授权；真实 project_vm 枚举 TextEdit 窗口、读取 21 项控件、AXSetValue 写入多行中文并精确读回、AXPress 关闭目标窗口，旧快照再次写入被拒绝。8 项后端回归覆盖跨 Agent 隔离、进程代际变化、快照过期、不可操作树、缺权限和不确定失败禁止重放。

没有验证所有应用；自绘、像素窗口或不提供 AX 的控件仍可能无法操作。VNC 预览是独立通道，Peekaboo 的成功不代表 VNC 已就绪。当前实现只支持上述 ARM64 macOS 访客，不宣称 Intel 或 Linux 控件桥可用。

本轮界面验证：5 项设置/引导与必需阅读布局回归、2 项设计回归均通过；实际 WKWebView 独立弹窗、草稿、首次引导和托盘 smoke 通过。扩大浏览器套件初跑 61 项，有 21 条失败断言（含子尺寸）；其中 Tart 输入框 autocomplete 缺失的 3 条已修复并复核。独立 HEAD 副本复现配色恢复、产物卡 fixture 和群聊 composer clipped；其他扩大套件失败尚未逐项归因，不宣称全套通过。
