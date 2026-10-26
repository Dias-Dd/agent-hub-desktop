# 模块声明配置字段 / Declarative module configuration

在 `adapter.json` 添加 `configuration`，主程序“添加 Agent”界面会自动生成表单。内置模块与 `adapters/custom` 的 Python 模块使用相同协议；无需修改主程序或编写网页。

Add `configuration` to `adapter.json`. The Add Agent screen renders the fields automatically for both bundled and custom Python modules.

```json
{
  "configuration": {
    "version": 1,
    "title": "服务配置",
    "fields": [
      {"name": "endpoint", "type": "url", "label": "服务地址", "required": true, "default": "https://example.com/v1"},
      {"name": "token", "type": "secret", "label": "API Key", "placeholder": "留空保留已保存密钥"},
      {"name": "models", "type": "string_list", "label": "模型 ID", "default": []},
      {"name": "mode", "type": "select", "label": "模式", "default": "standard", "options": [
        {"value": "standard", "label": "标准", "defaults": {"endpoint": "https://example.com/v1"}},
        {"value": "local", "label": "本机", "defaults": {"endpoint": "http://127.0.0.1:8080/v1"}}
      ]},
      {"name": "limit", "type": "integer", "label": "上限", "default": 8192, "min": 32, "max": 65536},
      {"name": "enabled_feature", "type": "boolean", "label": "启用可选功能", "default": false}
    ]
  }
}
```

支持 `text`、`secret`、`url`、`select`、`string_list`、`integer`、`boolean`。可选属性包括 `label`、`help`、`placeholder`、`default`、`required`、`max_length`；数字支持 `min/max`。下拉选项的 `defaults` 在切换时填入其它字段。建议为 `select` 和 `integer` 显式提供有效 `default`。字段名称必须唯一，使用小写字母、数字及下划线，以字母开头。服务端拒绝未声明字段，并校验类型、长度、URL 与选项。

Supported types are `text`, `secret`, `url`, `select`, `string_list`, `integer`, and `boolean`. Server-side validation rejects undeclared fields and invalid values. Option `defaults` populate related fields when selected.

## 在脚本中读取 / Read values in a script

没有 `configure` 回调时，平台自动保存普通字段，并将每个密钥字段分别保存在 Windows DPAPI / macOS Keychain。Linux 使用环境变量，不降级为明文密钥文件。表单不会读回密钥；留空保留原值。配置不能在在途任务或未结束项目使用该连接时更改。

```python
def execute(context, run):
    config = context.user_configuration()
    endpoint = config['endpoint']
    token = config['token']  # Only available inside the module; never returned to the UI.
    # Use endpoint/token with your own harness here.
    return {'status': 'completed', 'text': 'Actual harness reply'}
```

Without a `configure` hook, Hub persists ordinary values and protects each secret separately. `context.user_configuration()` resolves these values inside the module. Do not print or return credentials.

高级模块可以提供 `configure(registry, connection, config=None)`：`None` 表示读取，其它值表示保存；返回至少包含 `config` 对象，不能返回密钥明文。平台先校验声明字段，再调用回调，并自动为返回结果附加 `schema`。这种回调自行负责存储和执行时读取；OpenCode 供应商模块保留原有隔离配置、加密凭据和模型筛选逻辑，只有表单改为声明生成。

Advanced modules may implement `configure(registry, connection, config=None)`. Hub validates submitted fields before invoking the hook and attaches the form schema to the response. Such modules own their persistence and runtime resolution. Existing OpenCode provider settings and encrypted keys remain compatible.

## API 与 Pi / API and Pi

新 API 接入统一选择“自定义 API 与内置执行器（Pi）”。支持 OpenAI Chat Completions、Responses、Anthropic Messages、Google Gemini 协议；预设地址和模型可修改。模型留空会尝试读取 `/models`，失败可手动填写；预设或目录不证明真实账号权限。旧 API Agent 保留原连接、凭据环境变量和历史，但推理改由 Pi 执行。新增 Pi 接入当前未提供额度读取钩子；不把未知余额显示成无限额度。

Pi 仅用于 API 任务。发现接入、编辑配置、空闲和其它 CLI Harness 不启动 Pi；任务执行时启动独立 Node 子进程，结束或停止后回收。Pi 负责模型与工具循环，Hub 保留工具授权、停止锁、项目调度和长期记忆。使用 Pi agent-core，不启用 Pi CLI 的自动资源发现或扩展。完整工具历史持久保存；达到平台上下文上限时明确报错，不静默丢弃历史。请求失败不自动重试。

Pi runs only for API tasks. Other harnesses keep their original execution paths. The agent-core integration preserves Hub authorization and tool dispatch; it does not load Pi CLI extensions or project resources. History is durable; context overflow fails explicitly rather than silently discarding history. The new Pi integration currently has no balance-reading hook.

## 源码构建 / Source builds

运行 `python tools/prepare_pi.py`：按 lockfile 安装 Pi 1.4.0，构建执行桥，下载与构建机器匹配的 Node.js 22.19.0，并校验官网 SHA-256。安装包自带 Node，最终用户无需安装 npm 或 Node。Windows 安装包脚本自动执行此步骤；其它 PyInstaller 构建前先手动执行。构建资源缺失时打包立即失败。macOS 修改了打包配置，需在 Mac 上实际构建测试。

Run `python tools/prepare_pi.py` before source or macOS packaging. Windows installer builds run it automatically. It prepares the pinned Pi bundle and verifies the platform-specific Node archive against the official SHA-256 list. Installed users do not need npm or Node.
