# 导出卡住项目的诊断资料

请先导出，再重启或更新应用，以保留现场。

1. 把 `AgentHubDiagnostics.exe` 复制到运行 Deskfellows 的那台 Windows 电脑或虚拟机。
2. 双击运行。无需安装 Python，也无需退出 Deskfellows。
3. 成功提示会显示诊断包位置，默认是桌面的 `Deskfellows-diagnostics-日期-时间.zip`（旧版以 `AgentHub-diagnostics-` 开头）。
4. 将这个 ZIP 提供给排查人员，并说明卡住的项目名称、大致发生时间和最后一次操作。

安装版也可以从开始菜单的“Deskfellows 导出诊断包”运行。

诊断包包含项目、讨论、消息、执行、任务、调度和审计记录，以及部分连接状态；完整数据库快照通过 SQLite 在线备份接口读取，包括已提交到 WAL 的记录。不会停止执行、恢复任务或修改项目。对话内容和本地路径会保留，请在分享前自行检查。

不包含项目源码、API 密钥文件、DPAPI 文件或 Harness 登录文件。已识别的密钥字段和应用令牌会遮盖。不要额外发送 `credentials.json`、`.credentials.yaml` 或 `*.dpapi`。

自定义数据目录可以运行：

```text
AgentHubDiagnostics.exe --data "D:\AgentHubData" --output "D:\report.zip"
```

# DeepSeek Harness 账号与余额

Harness 模块优先通过官方 `deepseek-account` 服务复用 Harness 的登录状态，不复制登录令牌，也不需要另填 API Key。旧的 API Key 接入仍可用，和账号钱包分开标识。

模型目录、执行、登录状态及余额读取均属于 `adapters/builtin/deepseek-harness` 模块。应用仅通过统一模块接口调用并展示结果。充值钱包和赠送钱包分别显示；余额读取失败时保留上次观察，不将未知值显示为零。

本次验证覆盖模拟的已登录账号执行与钱包返回值、真实已安装 Harness 的未登录状态、打包后的模块和工具通道。尚未进行真实已登录账号的付费推理验证。
