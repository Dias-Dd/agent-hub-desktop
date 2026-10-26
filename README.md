# Agent Hub Desktop

[简体中文](README.md) · [English](README.en.md)

**面向 Windows 的 AI Agent 协作工作台。** 将不同 Harness、CLI 和 API 接入同一个项目，由经理 Agent 组织讨论、安排任务、跟进进度并交付成果。

保留你已有的模型账号和执行工具，在一个桌面界面中管理协作。Agent Hub 不是模型服务，也不附带模型订阅或 API 额度。

## 功能概览

- **按项目协作**：经理对话、Agent 群聊、任务队列、进度与原始回复集中展示。
- **跨项目长期记忆**：经理主动保存偏好与经验；用户可在设置中编辑、预览历史、回滚和锁定。详见[长期记忆指南](docs/LONG_TERM_MEMORY.md)。
- **先讨论，再执行**：审阅计划后批准制作；可先生成产品演示，确认设计后进入正式实现，也可跳过演示。
- **单 Agent 或多 Agent**：一位 Agent 可以兼任经理并独立完成任务；多成员可以分工、汇报和集成。
- **模块化接入**：内置与自定义 Python 适配器共用接口，也支持 JSON Lines 子进程桥接。
- **项目工具**：按授权提供文件、命令、Git 工作区、浏览器渲染、成果发布与 Hyper-V 虚拟机工具。
- **执行控制**：停止锁、队列管理、持久提醒，以及接入支持时的额度与恢复状态。
- **桌面体验**：中英文界面、独立窗口、托盘通知、深浅主题及独立配色；Windows 10 亚克力、Windows 11 云母，效果受系统透明设置与图形环境影响。

## 内置接入

| 接入 | 使用方式 |
| --- | --- |
| DeepSeek Harness | 官方 ACP 通道，优先复用 DSH 登录账号；账号方式无需另填 API Key |
| Codex、Antigravity | 对接本机官方执行通道，按实际登录状态与能力工作 |
| OpenCode | 使用本机已配置、授权的提供商；第三方订阅/API 是否可用取决于 OpenCode 与提供商自身支持 |
| CodeBuddy、ORI | 对应的本机 CLI；CodeBuddy 源码模块保留 `workbuddy` 标识 |
| DeepSeek API、OpenRouter API、Gemini API | 对应的 API 配置和凭据 |

各接入的登录、工具、续接、模型目录和余额读取能力有所不同。能列出模型不代表账号拥有调用权限，额度未知也不代表无限。

## 快速上手

### macOS 本地开发版

`macos-port` 分支新增 Cocoa / WKWebView 原生窗口及可选 Tart 后端，目前仅在
Apple Silicon、macOS 27.2 上验证。源码宿主需要 macOS 14+、Python 3.11+ 与
`desktop/requirements-macos.txt`；提供本地 arm64 `.app` 和 DMG 开发安装包。
首次打开自动显示配置指引，可安装 Tart、自动创建 macOS VM 或指定镜像。默认 VM 目录在应用数据内的 `vm-bridge/tart/machines/`，保留已有目录，设置可切换。支持 root 并发命令、文件传输和实验性桌面截图/键鼠；关闭窗口后通过菜单栏恢复。
普通项目无需虚拟机。运行方法、实际验证范围及尚未支持的功能见
[macOS 移植记录](docs/MACOS_PORT.md)。这不是已签名公证的正式 Mac Release。

### 从源码运行

需要 **Windows 10 2004（build 19041）及以上 / Windows 11**、**Python 3.11+（含 Tkinter）** 和 **Microsoft WebView2 Runtime**。调用模型还需要安装、登录对应 Harness，或配置自己的 API 凭据。

```powershell
git clone https://github.com/Dias-Dd/agent-hub-desktop.git
cd agent-hub-desktop
python desktop/launch_desktop.py --data .\local-data
```

`local-data` 是独立的数据目录，不会混用已安装应用的默认数据。核心服务使用 Python 标准库，直接运行源码不需要 PyInstaller。源码入口直接打开工作台；独立首次配置程序面向打包后的安装版。

### 创建第一个项目

1. 打开 **Agent 面板 → 添加 Agent**，选择接入方式。
2. 安装并登录相应 Harness，或按提示配置 API 凭据，再读取模型目录。
3. 选择模型和档位，确认执行授权后添加 Agent。**实际接入测试会调用模型，可能消耗额度。**
4. 创建项目，指定工作目录、经理和参与成员。只添加一位 Agent 也可以使用。
5. 在经理对话里说明需求，审阅计划，再批准执行；先制作演示时，确认设计后再正式制作。
6. 在对话、项目状态和右侧信息区查看进度、输出与成果，需要时使用停止控制。

API 凭据按接入要求通过环境变量或已有凭据流程配置。设置用户环境变量后，请完全退出并重新打开应用。`.env.example` 是说明模板，应用**不会自动加载 `.env` 文件**。

## 手动接入自己的 Harness

**没有找到你的平台？可以添加适配器，不必修改主程序。** 在数据目录的 `adapters/custom/<你的模块>/` 中放入 `adapter.json` 和脚本，再在添加 Agent 界面刷新自定义接入。也可以完整复制一个相近的内置模块，修改标识与配置。

- 安装版默认目录：`%LOCALAPPDATA%\AgentMessageHubDesktop\data\adapters\custom`
- 使用上述源码命令时：`.\local-data\adapters\custom`
- 推荐 `hub-module-v1` Python 模块；独立 EXE、Node.js、PowerShell 等可使用 `hub-jsonl-v1`。

详见 **[手动接入 Harness 指南](docs/HARNESS_INTEGRATION.md)**：包含目录、基础示例、登录、会话续接、工具调用、额度读取与排错。

## 安装版与首次配置

从 [GitHub Releases](https://github.com/Dias-Dd/agent-hub-desktop/releases/latest) 下载 `AgentHub-Setup-0.2.1.exe` 并运行。仓库同时提供源码和构建脚本。

1. 运行安装程序，选择简体中文或 English。
2. 在独立引导中添加 Agent 并指定经理；也可跳过，稍后在工作台配置。
3. 可选连接 Hyper-V 虚拟机。引导会协助打开管理工具或 Windows 功能，不会自动完成系统安装或重启。
4. 完成后打开工作台，以后可从开始菜单重新打开配置引导。

缺少 WebView2 Runtime 时，安装程序会调用微软引导安装器联网安装。Hyper-V 及相应系统支持只在使用虚拟机工具时需要，不是运行工作台的前提。

## 构建安装程序

安装 Inno Setup，然后在仓库根目录执行，按实际安装位置修改编译器路径：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r desktop/requirements-build.txt
.\desktop\build_installer.ps1 -Python .\.venv\Scripts\python.exe -Compiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

输出：`desktop/installer-dist/AgentHub-Setup-0.2.1.exe`，包含主程序、独立配置程序、MCP 工具通道与诊断导出工具。脚本会检查 Inno Setup 编译器和微软 WebView2 引导安装器的数字签名。

## 数据、权限与排错

安装版数据默认位于 `%LOCALAPPDATA%\AgentMessageHubDesktop\data`；源码启动以 `--data` 为准。其中保存项目、消息、执行状态、会话与接入配置。卸载安装版会保留这些数据。

适配器以当前用户权限运行，**不是操作系统沙箱**。只运行可信模块，并确认目录、命令权限和提供商费用。Hyper-V 管理操作可能需要管理员权限。

项目似乎卡住时，先导出诊断资料，再重启或升级。安装版可使用开始菜单中的诊断工具；源码版可运行：

```powershell
python desktop/export_diagnostics.py --data .\local-data --output .\diagnostics.zip
```

诊断包包含对话与本地路径，分享前请检查。见 [诊断说明](docs/diagnostics.md)。不要将凭证文件、运行数据或真实密钥上传到仓库。

## 源码与测试

| 目录 | 内容 |
| --- | --- |
| `hub/` | 服务、调度、权限、会话与前端 |
| `hub/builtin_adapters/` | 内置 Harness / API 模块 |
| `hub/adapter_examples/` | 模块和 JSONL 示例 |
| `desktop/` | Windows 原生窗口、配置引导与打包 |
| `tools/` | 虚拟机桥接等辅助工具 |
| `tests/` | 自动化测试 |

```powershell
python -m unittest discover -s tests -p test_manager_owned_plan.py
python -m unittest discover -s tests -p test_native_backdrop.py
python -m unittest discover -s tests -p test_unified_modules.py
```

界面修改还应运行 `test_manager_layout.py`、`test_reading_browser.py` 和 `test_nine_browser.py`，这些浏览器测试需要 Microsoft Edge。`docs/` 保留了早期开发记录，部分身份名称和配置已过时；当前用法以本 README、[接入指南](docs/HARNESS_INTEGRATION.md)和源码为准。部分历史测试仍使用旧身份夹具。

## 许可证

[Apache License 2.0](LICENSE)。随仓库提供的微软 WebView2 二进制依赖适用各自的许可证。
