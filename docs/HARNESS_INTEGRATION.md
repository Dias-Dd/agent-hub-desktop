# 手动接入 Harness

[返回项目首页](../README.md) · [English](HARNESS_INTEGRATION.en.md)

本指南适用于希望接入自己的 CLI、兼容 API 或 Agent 平台的用户。**“Harness”指实际调用模型、维护会话并执行工具的程序或服务；适配器负责把它的协议接到 Agent Hub。** 新增接入不需要修改主程序。

## 1. 先选择接入方式

| 方式 | 适用情况 | 运行环境 |
| --- | --- | --- |
| 完整复制内置模块 | 已有相近平台或兼容 API，希望复用工具循环、会话等实现 | 与内置模块相同 |
| `hub-module-v1` | 编写 Python 接入，需要 SDK 及登录、模型、额度钩子 | 安装版内置 Python；源码版使用启动应用的 Python |
| `hub-jsonl-v1` | 已有独立程序，或希望使用 Node.js、PowerShell、独立 Python 环境 | 自行安装对应运行时，或提供独立 EXE |

内置和自定义 Python 模块共用加载器、SDK 和回调。区别主要在安装位置与默认配置，不是“内置享有另一套协议”。

## 2. 放在哪里，如何添加

安装版默认数据目录是 `%LOCALAPPDATA%\AgentMessageHubDesktop\data`。使用 `--data .\local-data` 启动源码时，则使用仓库下的 `local-data`。

```text
<数据目录>/adapters/
├─ builtin/                  应用提供的模块
│  ├─ deepseek-harness/
│  ├─ openrouter-api/
│  └─ ...
└─ custom/
   └─ my-chat-api/
      ├─ adapter.json
      └─ adapter.py
```

1. 创建自己的子目录，写入 `adapter.json` 和入口文件。
2. 打开 **添加 Agent → 刷新自定义接入**；可用界面中的“打开自定义接入目录”确认实际路径。
3. 选择模块，按提示登录或配置凭据，读取或确认模型目录。
4. 选择模型和档位、命名并明确授权，然后添加 Agent。
5. 先做基础问答，再按实际能力测试续接和工具。真实调用可能计费。

普通目录扫描只读取 JSON，不运行用户脚本。显式登录检查、模型探测和执行会运行相应代码。模型目录能读不等于登录、费用和全部功能已验证。

`id` 必须唯一，格式为小写英文/数字/短横线，首位为英文或数字，最长 48 字符。发现重复自定义 ID 时，同 ID 接入会停用，不会任意选择一份。

## 3. 最省事：复用内置模块

例如，接入一个与 Chat Completions 兼容的服务：

1. 将 `builtin/openrouter-api` **整个目录**复制到 `custom/my-api`，不要只复制 `adapter.py`。
2. 修改 `adapter.json` 的 `id`、`name`、`api.base_url` 和 `api.key_environment`。不要把真实密钥写入 JSON。
3. 保留 `protocol`、`entrypoint` 及原有 `provider`。同步修改 `setup.website`、`setup.login_url`、`setup.key_env` 和说明，避免继续打开原提供商页面。
4. 如果服务支持 `/models`，可以复用目录探测；否则删除入口中的 `probe` 函数，并在 JSON 的 `models` 中声明实际模型与档位。
5. 原模块的 `quota` 实现使用 OpenRouter 接口。服务没有兼容额度接口时，应删除或替换它，不要将原提供商的余额当作新服务余额。
6. 配置密钥环境变量，完全退出并重新打开应用，再刷新自定义接入。

源码模板在 [内置模块目录](../hub/builtin_adapters/)。兼容不只是 URL 相同：应验证请求格式、模型名、工具返回、推理档位和流式事件。

## 4. 从头写 Python 模块：一个基础 API 示例

下面的适配器向你指定的 Chat Completions 兼容接口发起真实请求，使用标准库，并转发成功问答历史。它**只支持文本问答**，不实现工具、原生会话恢复或流式输出，不能据此宣称具备完整项目执行能力。

### adapter.json

把 `provider-model-id` 改成服务实际支持的模型标识。

```json
{
  "version": 1,
  "id": "my-chat-api",
  "name": "My Chat API",
  "protocol": "hub-module-v1",
  "entrypoint": "adapter.py",
  "models": [{"id": "provider-model-id", "efforts": ["default"]}],
  "capabilities": {"tools": false, "resume": false, "streaming": false},
  "environment": {
    "CHAT_API_URL": "MY_CHAT_API_URL",
    "CHAT_API_KEY": "MY_CHAT_API_KEY"
  }
}
```

### adapter.py

```python
import json
import urllib.error
import urllib.request


def execute(context, run):
    context.guard(run)
    request = context.request(run)
    messages = [{"role": "system", "content": request["system"]}]
    messages.extend(request["history"])
    messages.append({"role": "user", "content": request["prompt"]})
    payload = {"model": request["model"], "messages": messages, "stream": False}
    http_request = urllib.request.Request(
        context.environment["CHAT_API_URL"],
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + context.environment["CHAT_API_KEY"],
            "Content-Type": "application/json",
        },
    )
    try:
        timeout = min(request["timeout_seconds"], 60)
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            body = json.load(response)
        reply = body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Provider HTTP {error.code}; not retried") from None
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError("Provider connection or response failed; not retried") from None
    context.guard(run)
    return {"status": "completed", "text": reply}
```

在 Windows 中设置用户环境变量 `MY_CHAT_API_URL`（完整接口地址，例如服务提供的 `/v1/chat/completions` 地址）与 `MY_CHAT_API_KEY`，再重启应用。`environment` 的方向是 **模块变量名 → 宿主已有变量名**；Python 模块通过 `context.environment` 读取。不要提交真实密钥，也不要把令牌写到回复或错误中。

声明 `resume: false` 不代表“没有历史”：SDK 会保存成功问答，下一轮在 `history` 中提供。本例转发这份历史，但它不是提供商的原生会话，也不包含完整工具轨迹。

## 5. 完整能力分别由谁实现

| 能力 | Agent Hub | 适配器 |
| --- | --- | --- |
| 项目、身份、授权、队列、停止锁、结果投递 | 管理并持久化 | 使用当前请求，不扩大授权 |
| 模型调用、登录和凭据协议 | 提供引导入口 | 对接对应平台的真实接口 |
| 对话历史与会话映射 | 保存成功历史、隔离项目与 Agent | 转发历史或恢复正确的原生会话 |
| 工具调用 | 提供并校验本轮允许的工具 | 转换协议、执行多轮工具循环、回传工具结果 |
| 模型目录、档位、余额 | 保存、展示支持的观察结果 | 从提供商读取，不伪造支持或无限额度 |
| 取消 | 撤销平台授权；JSONL 进程可被终止 | 配合停止检查，并处理远端请求取消 |

平台不会仅靠 `tools: true` 为任意服务生成工具实现。也不会替未知平台自动完成登录或会话协议。复制相近内置模块可以复用已有实现。

### Python 模块的主要接口

- `execute(context, run)`：必需。基础模块返回非空字符串，或 `{"status":"completed","text":"真实回复"}`；有原生会话时可加 `session_id`。
- `context.request(run)`：含 `system`、`prompt`、`history`、`session_id`、`model`、`effort`、`cwd`、`permission`、`tools`、`timeout_seconds`。不要只转发 `prompt` 而忽略系统约束和历史。
- `context.guard(run)`：工具调用、后续请求前及等待期间检查停止、授权与时间预算。阻塞网络调用应设置超时并配合取消。
- `context.public_reply(run, text)`：发送流式文本；`context.record(run_id, kind, data)`：记录脱敏事件。
- `context.tool(run, name, arguments, allowed_names)`：调用平台工具，`allowed_names` 来自本轮 `tools` 中的函数名。
- `context.sessions.get/bind/state`：高级模块使用的会话接口。可参考内置实现和 [SDK 源码](../hub/module_sdk.py)。

工具循环应把本轮 `tools` 转成提供商格式，将模型的工具请求交给 `context.tool`，再把真实结果交回模型。直到明确完成才返回 `completed`。不得绕过平台直接伪造派工、交付或 VM 成功结果。

若原生会话恢复成功，不要再次重放同一份历史。恢复失败应明确报告，不能静默换 ID 丢弃上下文。修改工作目录时，原生会话目录与本轮授权目录可能不同，参考内置 Harness 的处理。

### 可选钩子

| 函数 | 返回与用途 |
| --- | --- |
| `probe(registry, connection)` | 包含 `models` 数组；模型项可含 `id`、`name`、`efforts`。只探测目录，不发送推理 |
| `probe_model(registry, connection, model)` | `{"id": model, "efforts": ["default"]}` 等实际档位 |
| `setup_status(registry, connection)` | `state` 为 `ready` / `login` / `missing` / `unknown`，并提供可读 `message` |
| `setup_login(registry, connection)` | 打开该平台真实的登录窗口、交互 CLI 或官方页面 |
| `quota(registry, connection)` | 官方余额/额度观察，如 `official_balance`、`official_windows`、`quota_observed_at` |

`quota` 示例字段为 `official_balance: [{"name":"账户余额","amount":"12.34","currency":"CNY"}]`；窗口观察可使用 `remaining`（剩余百分比）、`resets_at`（Unix 秒）和 `name`。读取失败应报告错误、保留旧观察，不返回虚假的零或无限。面板能否一键刷新，还取决于该接入对应的 UI 支持。

清单可加 `setup.website`、`setup.login_url`、`setup.note`，网站使用真实 HTTPS 地址；不要把占位地址当官网发布。没有可靠登录检测时，明确让用户手动确认，不能把“目录可读”当作“已通过真实推理”。

## 6. 独立程序：hub-jsonl-v1

JSONL 每个回合启动一个子进程，工作目录为本轮 `cwd`。示例清单：

```json
{
  "version": 1,
  "id": "my-cli",
  "name": "My CLI",
  "protocol": "hub-jsonl-v1",
  "command": ["${python}", "${adapter_dir}/bridge.py"],
  "models": [{"id": "provider-model-id", "efforts": ["default"]}],
  "capabilities": {"tools": false, "resume": false, "streaming": false},
  "environment": {}
}
```

`command` 是参数数组，不是 shell 命令串。`${adapter_dir}` 展开为适配器目录；`${python}` 使用本机 Python，**安装版的内置 Python 不等于可供 JSONL 启动的外部 Python 命令**。也可改用自己的 EXE 或其他运行时。

标准输入第一行是包含上述请求字段的 `run` 对象，`protocol` 为 `hub-jsonl-v1`，另有 `session_cwd`。标准输出使用 UTF-8，每行一个 JSON 对象；日志放 stderr，不混进协议输出。

```json
{"type":"text","text":"可选的增量正文"}
{"type":"result","status":"completed","text":"真实最终回复"}
```

`text` 事件用于流式输出；最终 `result` 的 `text` 可省略，此时合并增量。需要非空回复和明确完成，只有退出码 0 或 EOF 不算成功。错误使用 `{"type":"error","message":"可读错误"}`。

实现工具时声明 `tools: true`，按请求中的清单发出：

```json
{"type":"tool_call","id":"call-1","name":"project_status","arguments":{"view":"status"}}
```

然后从 stdin 读取匹配 ID 的 `tool_result`，其中包含 `result` 或 `error`，再继续模型循环。声明 `resume: true` 时必须返回 `session_id`，下一轮恢复该 ID，不能静默替换。

发出完成前应持久化必要的原生状态；平台随后回收本回合进程。进程被终止不保证远端付费请求也被取消。仅回显 prompt 的 [协议示例](../hub/adapter_examples/bridge.py.example)不是模型接入，不应作为真实调用测试通过的依据。

## 7. 验收与排错

按顺序验证：目录发现 → 登录/凭据 → 真实问答 → 第二轮上下文 → 工具往返（若支持）→ 只读权限 → 停止/超时 → 重启后续接。测试完整项目执行时，需要具备工具能力的模块；文本问答模块不够。

| 问题 | 检查方向 |
| --- | --- |
| 添加界面找不到模块 | 实际数据目录、子目录层级、`adapter.json` 名称、唯一 ID、JSON 格式及入口文件 |
| 声明了模型但不能调用 | 登录状态、提供商授权、真实模型 ID、档位和费用/额度 |
| 改了环境变量仍无效 | 完全退出应用及后台进程后重开；检查变量映射方向 |
| 只能聊天，不能派工/执行 | 工具能力是否真正实现；有没有使用本轮工具清单和实际工具结果 |
| 忘记上下文 | 是否转发 `history`；是否正确恢复 `session_id`，且没有重复重放 |
| JSONL 退出却失败 | 是否输出最终 `result`、非空文本，stdout 是否混入日志 |
| 停止后远端仍运行 | 为第三方 SDK/API 实现取消；本地停止不能保证远端请求取消 |

模块以当前用户身份运行，不是 OS 沙箱。不要在未授权时写文件、执行命令或把凭据交给模型。备份自己的模块；升级时不要假定修改过的内置文件会被自动覆盖。

进一步参考：[模块接口说明](harness-modules.md)、[JSONL 兼容协议](custom-harness.md)、[模块 SDK](../hub/module_sdk.py)、[内置实现](../hub/builtin_adapters/)、[自动化接入测试](../tests/test_unified_modules.py)。
