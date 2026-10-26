# Harness 模块接口 v1

所有内置与自定义 Python 接入均采用 `hub-module-v1`：同一 JSON 格式、同一加载器、同一个 SDK、同样的回调和执行权限边界。安装位置只影响分组和默认配置，不决定可用功能。内置文件可以修改，也可以整目录复制到 custom。

```
adapters/
  builtin/    随应用提供的模块，每项包含 adapter.json、adapter.py 和实现文件
  custom/     用户模块，接口完全相同
```

平台保留：任务队列、授权与停止状态、项目与 Agent 身份、数据库/会话存储、工具校验和实际执行、模块加载，以及统一的经理调度、交付、验收和身份提示词。提示词由宿主生成，通过 SDK 的 instructions/request 等接口提供给模块；模块只负责按提供商协议传递，不内嵌平台业务规则。
模块负责：凭据/登录对接、提供商请求与协议、原生会话恢复、工具请求/返回格式转换、API 多轮工具循环、提供商模型和额度读取。原应用文件只留旧导入路径的兼容别名，不再保存这些提供商实现。

## 最省事的兼容 API 接入

普通 API 无需编写脚本：在主程序“添加 Agent”中选择“自定义 API 与内置执行器（Pi）”，设置协议、地址、密钥和模型。安装版自带 Node；仅执行 API 任务时启动 Pi。旧 API Agent 保留历史与原连接，但执行已经切换为 Pi。

需要独立名称和预设时，将 builtin/pi-api 整目录复制到 custom/my-api，修改 id、name 与 configuration 中的默认值。保留配套 Python 文件，共用应用提供的 Pi 桥与运行时，不必复制 node_modules 或 Node 二进制。其它 CLI 模块也可以完整复制并修改，仍使用相同的加载器与 SDK。

## 声明字段，自动生成表单

在 adapter.json 添加 `configuration: {"version":1,"fields":[...]}`。支持 text、secret、url、select、string_list、integer、boolean；每个字段声明 name、type、label 及可选默认值、约束。主程序“添加 Agent”自动生成表单；服务端拒绝未声明字段及无效输入。字段名必须以小写字母开头，仅含小写字母、数字和下划线。

没有 configure 回调时，平台保存普通字段，并将密钥保存到 Windows DPAPI / macOS Keychain；密钥不回显，留空保留原值。Python 模块用 `context.user_configuration()` 读取配置。高级模块可以提供 `configure(registry, connection, config=None)` 自行管理配置；这时也应自行在执行中读取，不能将密钥明文返回界面。84 个 OpenCode 供应商已采用声明表单，原有隔离配置和会话保持兼容。

## 从头编写模块

复制 module.example.json 为 `<custom>/<名称>/adapter.json`，adapter.py.example 为 adapter.py。入口文件只能是模块目录内的 Python 文件名；相关 .py 文件放在同一目录，支持相对导入。使用应用自带的 Python，不需要另装 Python。当前只保证标准库与应用提供的 SDK，额外第三方库应自行随模块提供或用子进程调用自己的环境。

`version: 1`，`protocol: hub-module-v1`，`entrypoint: adapter.py`。`models` 可声明模型或由 probe 返回。`settings` 为模块配置；平台的授权、工作目录、预算和启用状态优先，模块配置不能扩大这些授权。`environment` 为目标变量名到现有宿主变量名的映射，`context.environment` 提供本轮解析后的副本，不修改整个应用的进程环境。密钥不要直接写进 JSON。

### 必需：execute(context, run)

- `context.request(run)`：得到 system、prompt、history、session_id、model、effort、tools、cwd、permission、timeout_seconds。
- `context.guard(run)`：检查当前授权、停止状态与时间预算；工具或下一次请求前、等待期间定期检查。
- `context.tool(run, name, arguments, allowed_names)`：通过平台校验并执行工具；`allowed_names` 应来自本轮 tools 清单。
- `context.public_reply(run, text)`：流式文本；`context.record(run_id, kind, data)`：记录脱敏后的事件。
- `context.sessions.get/bind/state`：按原项目、Agent、连接和模型保存原生会话 ID。
- 返回 `{'status':'completed','text':'实际回复','session_id':'可选的原生会话ID'}`，平台保存成功历史并完成投递。基础问答可以只返回非空字符串。
- 高级模块可自行维护完整协议历史与完成状态（内置 API/CLI 模块即如此）；此时返回 None 前必须已经确认执行终态。空返回、异常或空回复不会被视为完成。

历史由平台存储；模块必须实际把它传给目标平台，或用正确的原生会话 ID 恢复。原生 ID 不应悄悄改变。SDK 不能凭空替未知平台实现登录或协议，但用户可复制已有模块，复用它们的完整实现。

### 可选回调

- `probe(registry, connection)` → 包含 models 数组的对象；还可返回 verification、probe_detail、official_windows。刷新时调用，目录扫描不会导入 Python 或执行此函数。
- `quota(registry, connection)` → 官方额度/余额观察结果；没有实现时显示不支持，不能伪造无限额度。
- `probe_model(registry, connection, model)` → `{'id':model,'efforts':[...]}`。

这些回调的注册、读取和结果持久化对 builtin 与 custom 一样。内置模块的共享实现位于 builtin/_shared；任何模块都能使用相同 SDK 和公开的模块代码。兼容 API 的 transport/工具循环实现也随模块文件提供。

## 执行与兼容

Python 模块以当前应用用户身份执行，没有额外的操作系统沙箱，builtin 和 custom 一样。提供商的工作区限制、平台工具权限和本机 Python 的权限是不同层级。模块必须合作处理停止与时间预算；阻塞的第三方调用不能保证立即中断。需要独立进程和进程树终止时，可使用下面的 JSONL 传输。

旧 `hub-jsonl-v1` 接入继续支持，格式与独立进程传输不变；它是兼容传输方式，不是内置模块专属或低权限 SDK。旧 harness-adapters 自动迁移到 adapters/custom，连接、Agent、授权与会话不改 ID。同名文件保留，重复模块 ID 报错；配置中旧绝对启动路径会迁移并保留原配置备份，脚本内部硬编码旧路径需自行调整。

升级只更新未被用户修改的内置文件，用户编辑过的内容会保留；请留意新旧接口版本的兼容性。目录扫描不会运行脚本，不代表实际登录、模型或费用已验证。


完整格式、示例和源码构建步骤见 [模块配置说明](https://github.com/Dias-Dd/agent-hub-desktop/blob/main/docs/MODULE_CONFIGURATION.md)。
