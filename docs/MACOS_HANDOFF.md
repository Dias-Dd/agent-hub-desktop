# macOS 开发交接

更新日期：2026-10-25。

## 状态与起点

- 仓库：<https://github.com/Dias-Dd/deskfellows>。
- Windows 最新发布：`v0.2.1`，源码提交 `333843055f0cefc9b6ca438aeca23800dbb9b77b`。
- 本次交接使用 `macos-port` 分支；创建时与上述提交相同。
- [Windows 0.2.1 Release](https://github.com/Dias-Dd/deskfellows/releases/tag/v0.2.1) 已发布安装包和 SHA-256 校验文件。
- **交接时 macOS 移植尚未开始**。本文件保留交接基线；后续本地实现、验证与剩余限制见 [MACOS_PORT.md](MACOS_PORT.md)，不代表新版本已发布。
- 用户已授权将交接文档提交并推送到远程 `macos-port` 分支。Mac 应检出这个分支；单独检出 `main` 不会得到这两份交接文件。此次授权仅用于交接分支，不延续到后续开发提交或发布。

本文件不包含聊天全文、账号凭据、应用运行数据或用户长期记忆。Deskfellows 的长期记忆属于产品本身，不是 Codex 开发聊天的同步机制。

## 项目是什么

Deskfellows 是本地优先的 AI Agent 协作桌面应用。用户在项目中选择经理、添加成员，先讨论并批准计划，再制作演示或直接实施。经理通过工具派工、检查、调度并交付成果。单个 Agent 也可以兼任经理独立完成工作。

保留 Python 服务、HTML/CSS/JavaScript 前端和现有适配器接口，先识别平台依赖，再增加 macOS 实现。不要因为更换桌面宿主就重写业务逻辑或重做全部界面。

## 0.2.1 已有内容

1. 模块化 Harness 接入：内置模块与用户模块使用同一套 SDK/协议。用户模块放在应用数据目录的 `adapters/custom`，内置模块位于 `adapters/builtin`。
2. `hub-module-v1` Python 模块与 `hub-jsonl-v1` 子进程桥接。登录、模型目录、额度查询、提供商会话和工具循环由适配器实现；项目管理策略、授权与停止锁由宿主维护。
3. 内置接入：DeepSeek Harness、Codex、Antigravity、OpenCode、ORI、CodeBuddy（代码标识 `workbuddy`）及 DeepSeek/OpenRouter/Gemini API。
4. DeepSeek Harness 的 Windows 账号通道优先复用 DSH 登录，不应笼统要求另填 API Key。不同平台的安装发现、登录与读取额度能力必须重新验证。
5. 项目对话、群聊、批准计划、演示审阅、成果卡片、项目工具、队列与定时提醒。
6. 简体中文/英文、浅色/深色独立配色、独立设置窗口和 Windows 原生桌面集成。
7. 完成事件接入 Windows 通知中心，失败时回退到托盘通知。
8. 跨项目长期记忆：经理主动保存偏好/经验，用户在设置中编辑、预览版本、回滚和锁定。详情见 [LONG_TERM_MEMORY.md](LONG_TERM_MEMORY.md)。

最近修复包括：页签选中时文字上浮、同时编辑两套配色、自定义 Harness 额度分组报错。不要把这些已修复问题当作新的待办；如有复现，先检查基线版本和实际运行程序。

## 先读哪些文件

| 路径 | 用途 |
| --- | --- |
| `AGENTS.md` | 界面修改必须遵守的阅读、滚动、草稿及布局回归要求 |
| `README.md` / `README.en.md` | 产品介绍、运行和 Windows 打包 |
| `docs/HARNESS_INTEGRATION.md` / `.en.md` | 用户模块接入协议与 SDK 使用 |
| `hub/server.py` / `hub/core.py` | HTTP 服务、认证、SQLite 数据与事务 |
| `hub/projects.py` / `hub/planning.py` / `hub/workflows.py` | 项目、讨论和任务流程 |
| `hub/module_sdk.py` / `hub/module_tools.py` / `hub/mcp.py` | 模块 SDK、工具授权、MCP |
| `hub/execution_policy.py` / `hub/prompt_identity.py` | 宿主维护的经理和项目指令 |
| `hub/builtin_adapters/` / `hub/harness_adapters.py` | 提供商模块和发现流程 |
| `hub/long_term_memory.py` / `hub/static/memory.js` | 长期记忆服务与设置界面 |
| `hub/static/index.html` / `style.css` / `modern.css` / `app.js` | 主要界面 |
| `desktop/launch_desktop.py` / `desktop/launch_installed.py` | 源码与打包启动入口 |
| `desktop/native_webview.py` / `desktop/tray.py` / `desktop/system_notifications.py` | Windows 窗口、托盘和系统通知 |
| `desktop/onboarding.py` / `desktop/onboarding_service.py` | 独立首次设置程序 |
| `hub/vm_bridge.py` / `tools/HubDesktopAgent.ps1` | 现有 Hyper-V 桥与虚拟机内工具 |

## 首先需要审查的平台依赖

- **桌面宿主**：目前是 Win32 + WebView2；Mac 需要自己的窗口/WebView 宿主。WKWebView/Cocoa 或使用其后端的包装库可以评估，但尚未选定或验证。
- **窗口行为**：标题栏聚焦色、缩放、快捷键、独立弹窗、关闭/最小化、菜单和浏览器权限需要按 Mac 行为实现；不能直接调用 `ctypes.windll`。
- **数据目录与凭据**：Windows 路径、注册表环境变量、DPAPI 存储需分别处理。Mac 需确定应用数据位置，并实现合适的凭据存储，例如 Keychain。不要把 Windows 的加密文件当作可移植凭据。
- **CLI 发现**：部分模块依赖 `%LOCALAPPDATA%`、`.exe`、Windows 安装目录、注册表或 PowerShell。Mac 上应检测真实可执行文件和官方登录状态，不要伪造可用模型/额度。
- **进程清理**：`hub/process_job.py` 的 Windows Job Object 在非 Windows 平台不建立进程树管理。需要落实 POSIX 进程组与取消行为，不能把“没有报错”当作已验证停止全部子进程。
- **通知与托盘**：`desktop/system_notifications.py` 使用 Windows 注册与 PowerShell/WinRT；Mac 应使用本机通知接口并处理授权。不能用网页内提示冒充系统通知中心通知。
- **虚拟机**：现有 Hyper-V / PowerShell Direct 无法直接移植；虚拟机可跳过，不应阻止普通项目使用。
- **打包**：Inno Setup、WebView2 DLL 和 Windows EXE 的 `.spec` 不适用于 Mac 发布；需在 Mac 构建和验证 `.app`，再确定 DMG/安装方式及签名、公证条件。
- **测试**：部分浏览器测试固定寻找 Windows Edge 路径，必须让 Mac 使用实际可用的测试浏览器。测试被跳过不能算验证通过。

这不是完整依赖清单，需继续检索源码。`hub/locking.py` 已有 POSIX 文件锁分支，`hub/module_tools.py` 已有 `/bin/sh` 分支；保留并检查，不要重复实现。

## 虚拟机方案：已选择 Tart

用户已明确选择 **Tart** 作为 macOS 版的虚拟机后端。按此选择推进，不再将 Tart、UTM、Parallels 作为待选方案反复询问。先核对真实 Mac 是否为 Apple Silicon、系统版本及 Tart 的实际兼容性；若环境不支持，报告具体阻塞，不自行替换提供商。选择 Tart 不代表已经安装、接通或验证了虚拟机。

建议保留经理调用的 `project_vm` 工具接口，在宿主下方增加不同虚拟机后端。命令执行、文件传输、截图、窗口/UI 操作和鼠标键盘应使用明确的能力声明；缺少能力时如实返回不可用，不能返回虚假成功。跨系统命令语义必须明确区分，不能把现有 PowerShell `script` 静默当作 POSIX Shell 执行。

优先让无虚拟机的 Mac 应用可用，再完成 Tart 后端。具体实施前检查真实 Mac 的架构、系统版本、可用工具和测试目标。实现 Tart 的安装检测与引导、虚拟机发现/启动/停止以及访客连接；命令、文件传输、截图和桌面控制需逐项核实。普通项目仍应能跳过虚拟机设置。不要把选定后端解释为允许任意改变主机安全策略或购买软件。

## 推荐开发顺序

1. 检查 Mac 环境、工作树、当前分支和已有工具；梳理启动链路的 Windows 依赖。
2. 让服务和前端能在独立测试数据目录中启动；浏览器访问可作中间验证，但最终交付需要真正的 Mac 桌面窗口。
3. 实现 Mac 窗口宿主、数据目录、单实例、进程退出和独立窗口，复用现有前端。
4. 验证至少一种真实可用的 Harness：发现、登录、模型选择、调用、工具、续接和取消。其余接入按实际支持情况显示能力。
5. 移植设置引导、凭据保存、通知、主题和其他桌面行为。
6. 接入已选定的 Tart 虚拟机后端；保持 Windows 的 Hyper-V 后端可用。
7. 在 Mac 构建应用包，验证首次启动、升级、权限和应用退出；Windows 端再做回归。

以上是实施建议，不代表每项都已获准改变主机配置。先处理可移植性和实际阻塞，避免一次性大规模重构。

## 验证基线

Windows 0.2.1 已通过：

- `tests/test_long_term_memory.py`：9 项；跨项目、持久化、版本冲突、锁定、回滚、授权和共享工具。
- `tests/test_long_term_memory_browser.py`：通过真实 HTTP 接口操作设置，包括保存/锁定/预览/回滚/冲突保留草稿，在 1280×800 和 800×600 下验证。
- `tests/test_unified_modules.py`：12 项；模块接入和本地模拟提供商的工具循环等。
- `tests/test_integrations.py`：22 项。
- `tests/test_manager_input.py`：9 项；`test_discussion_identity.py`：6 项；`test_manager_identity_audit.py`：29 项。
- `AGENTS.md` 要求的 `test_manager_layout.py`、`test_reading_browser.py`、`test_nine_browser.py`；以及 `test_memory_browser.py` 的内存/节点稳定性检查。
- 实际打包程序的 `--module-smoke-test`、`--smoke-test`：九个内置模块、用户 Python 模块和启动检查通过；没有发付费模型请求。

已知测试限制：`test_antigravity.py` 在基线中为 14 项、1 失败/12 错误；`test_codex_runtime.py` 为 7 项、6 错误，涉及过期身份/提供商样例。在未修改的 `157aab4` 基线上和长期记忆改动后检查结果相同。不要因此声称全套测试已通过，也不要把它们自动判定为 Mac 移植引起。需要按真实代码修整测试样例后再做有效验证。

在 Mac 可先尝试以下不应发送付费推理请求的测试，然后处理平台差异；真实结果以当地运行情况为准：

```sh
python3 -m unittest discover -s tests -p test_long_term_memory.py
python3 -m unittest discover -s tests -p test_unified_modules.py
python3 -m unittest discover -s tests -p test_integrations.py
```

这些测试**尚未在 Mac 运行**。界面修改仍必须满足 `AGENTS.md` 的布局和交互验证要求；如果测试工具不能在 Mac 使用，应先适配测试，明确记录无法验证的部分。

## 接班后的第一条回复

不要假称继承了 Windows 聊天历史。阅读本文件和实际源码后，简要说明：当前检出版本、Mac 环境、最先发现的阻塞与本轮处理范围，再继续实施。

不要从本文件推断已获得提交、推送、合并或发布授权。当前操作边界另见用户粘贴的提示词；新会话中的直接用户要求优先。
