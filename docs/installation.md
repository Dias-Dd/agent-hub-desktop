# 安装与首次配置

运行 `Deskfellows-Setup-*.exe`（旧版名称为 `AgentHub-Setup-*.exe`）。默认安装到当前用户的应用目录，不要求管理员权限。安装结束可打开独立的 **Deskfellows 配置引导**。

搭班（Deskfellows）原名 Agent Hub。更名沿用原安装识别码与数据目录，覆盖升级继续使用原安装位置；现有项目、长期记忆、账号与适配器无需迁移。MCP 协议名称与程序内部标识保留兼容性。

主程序仍使用 WebView2。安装器检测 Microsoft WebView2 Runtime；缺失时运行随包附带的微软 Evergreen 引导安装器（此步骤需要联网），失败会提示并停止安装。配置引导本身使用原生 Tk 窗口，不依赖 WebView2。安装器不会替用户启用 Hyper-V，也不会强制重启。

安装程序可选择简体中文或 English，首次引导沿用安装语言，也可以在引导右上角切换。工作台设置中的“语言 / Language”可即时切换，输入草稿、项目名称和模型原始输出保持原文。语言选择保存在数据目录中的非敏感文件 `ui-preferences.json`。

工作台的深色、浅色模式分别保存配色；恢复默认仅影响当前模式。演示完成与项目完成后发送 Windows 托盘通知，点击可回到对应项目。启动时不会重复通知旧的完成记录；Windows 自身的通知设置仍然适用。

## Agent 与经理

1. 选择 Harness 或 API 接入。缺少本机 Harness 时，打开官方安装链接；安装后重新检测。
2. 检查登录。需要登录时会打开官方程序、CLI 或密钥管理网页；完成后返回重新检查。
3. 读取模型目录，选择模型，确认执行权限与提供商费用，添加 Agent。可重复添加多位成员。
4. 指定一位已启用的 Agent 作为默认经理。已有项目的经理不受此默认值影响。

整个 Agent 流程可以跳过。跳过不会把示例 DeepSeek 身份显示为已配置成员。读取目录不进行推理，也不把公开目录误认为已登录或拥有所有模型权限。

API 接入沿用用户环境变量。点击“配置 API 环境变量”设置相应变量，然后重新打开应用并检查。DeepSeek Harness 优先通过官方账号服务复用 DSH 登录，无需另外填写 API Key；旧 API 凭据方式与账号钱包分开。手动扩展见 [接入指南](HARNESS_INTEGRATION.md)。

有些 Harness 没有可靠的独立账号检测接口。这时引导会打开官方界面，并明确要求用户确认已登录，随后读取目录；不会声称完成了实际推理验证。

## Hyper-V 与账号

缺少管理工具时，引导可打开“Windows 功能”并提供微软安装指引。启用 Hyper-V 平台及管理工具后，按系统要求重启。Windows 家庭版不提供 Hyper-V，可跳过或按微软要求使用支持的系统版本。

打开 Hyper-V 管理器，创建并启动 Windows 来宾；返回后读取虚拟机列表，填写来宾账号与密码（不是 PIN）。可选择记住凭据以及配置无人值守登录、解锁和不休眠。凭据使用现有 Windows 当前用户 DPAPI 加密格式，不写入引导完成标记或日志。

首次读取列表或连接时，现有 Hyper-V 桥接组件可能触发管理员授权。引导不会在启动时自动提权。连接流程可跳过。连接成功后，独立引导进程以无界面、阻塞等待方式保留 VM 辅助进程的所有权，直到主程序退出，避免交接时重复提权；它不进行后台轮询。

## 再次配置与卸载

开始菜单的“Deskfellows”在配置完成后直接启动主程序；“Deskfellows 配置引导”始终重新打开引导。配置中断时不会写入完成标记。主程序运行时需先正常从托盘退出，再运行引导；引导不会中止项目或恢复在途任务。

卸载只删除安装文件和快捷方式，保留 `%LOCALAPPDATA%\AgentMessageHubDesktop\data` 中的项目、适配器、账号及配置。首次配置完成标记为该目录中的 `onboarding.completed.json`。

## 模块接入引导协议

内置与自定义模块均从各自的 `adapter.json` 读取可选 `setup` 字段：

```json
{
  "setup": {
    "website": "https://provider.example/download",
    "login_url": "https://provider.example/login",
    "note": "安装与登录说明"
  }
}
```

Python 模块可以在 `adapter.py` 导出：

```python
def setup_status(registry, connection):
    # 只检查账号，不调用模型。不能返回密钥或令牌。
    return {"state": "login", "message": "请登录"}

def setup_login(registry, connection):
    # 打开该平台真正的登录窗口或交互 CLI。
    # 使用参数数组，不拼接 shell 命令。
    ...
```

`state` 支持 `ready`、`login`、`missing`、`unknown`。没有检测钩子的自定义模块使用明确的人工登录确认，仍可通过原有 `probe` 返回模型目录。JSONL 适配器使用 `setup.website/login_url` 和清单中的模型目录。网站必须是 HTTPS；未知模块不会被伪造一个官网地址。

## 构建

`desktop/hub_installer_bundle.spec` 构建主程序、独立配置程序和控制台 MCP 工具通道，共享一个不可变依赖目录；入口 `desktop/launch_installed.py` 根据可执行文件名选择程序。`desktop/build_installer.ps1` 另行构建独立诊断导出工具，一并加入安装包。

构建后在同目录放置 `installation.json`：

```json
{"main": "AgentMessageHubDesktop.exe"}
```

使用 Inno Setup 编译 `desktop/agent_hub_setup.iss`，通过 `Payload` 指定上述目录。WebView2 引导安装器需放入 `desktop/installer-tools/MicrosoftEdgeWebview2Setup.exe`；构建前验证它的 Microsoft Authenticode 签名。编译器不进入产品安装包。

也可使用 `desktop/build_installer.ps1 -Python <含 PyInstaller 的 Python 路径> -Compiler <ISCC.exe 路径>`。脚本会先检查微软引导安装器与 Inno Setup 编译器的数字签名。
