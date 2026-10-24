# 自定义 Harness 接入 v1

自定义接入位于 `<应用数据目录>/adapters/custom/<名称>/adapter.json`。根目录里的 example 文件不执行。

目录结构：
```
adapters/
  builtin/                 内置接入，每项都有 adapter.json + adapter.py
    deepseek-harness/
    codex/
    antigravity/
    opencode/
    ori/
    workbuddy/              CodeBuddy CLI，保留原连接标识
    openrouter-api/
    gemini-api/
    deepseek-api/
  custom/                  用户接入，每项为 adapter.json + 自己的脚本/程序
```
首次启动自动把旧 `harness-adapters` 迁入 `adapters/custom`。原连接、Agent ID、授权和会话记录不变。配置中的旧绝对启动路径会随之迁移，并在同目录保留原配置备份；脚本内部硬编码的旧路径需自行调整，推荐用 `${adapter_dir}`。同名目录保留两份，重复 ID 会报错并停止接收新任务，不会覆盖文件或任选一份执行。

内置和自定义 Python 模块现在统一采用 `hub-module-v1`。提供商执行实现已经移入模块；两者使用同一加载器与 SDK，可完整复制内置目录到 custom 后修改使用。完整接口与复用 API 模块的方法见 MODULES.md（源码文档为 docs/harness-modules.md）。本文件下面继续说明兼容的 `hub-jsonl-v1` 子进程格式。

模型列表仍从各提供商原有探测接口读取，JSON 不会把订阅模型写死。目录发现只读配置，不登录、不发送推理。

1. 创建 `my-harness` 子目录，将 adapter.example.json 复制为 adapter.json，bridge.py.example 复制为 bridge.py。
2. 修改 name、id、command、models，并将 bridge.py 里的协议示例替换为真实 CLI/SDK/API 调用。
3. 在“添加 Agent → 刷新自定义接入”选择它。发现配置只读取 JSON，不会运行脚本。
4. 明确勾选允许执行后，平台才会启动脚本。脚本以当前 Windows 用户身份运行，没有 OS 沙箱；必须自己遵守请求中的只读/完全访问授权。

## 配置
version 固定 1，protocol 固定 hub-jsonl-v1；id 是稳定的小写英文/数字/短横线标识。
command 是参数数组，不是 shell 命令串。`${adapter_dir}` 展开为本适配器目录，`${python}` 展开为本机 Python。EXE、Node、Python、PowerShell 均可作为程序；相应运行时须自行安装。不要在配置里写密钥。
models 必须声明至少一个模型，可为各模型提供 efforts 字符串数组；名称只是声明，平台不会声称已验证调用。
environment 将子进程变量名映射到宿主已有的环境变量名，例 `{"API_KEY":"MY_API_KEY"}`。缺失时明确失败，不会回显值。
capabilities 是 tools/resume/streaming 布尔值；全部可为 false。仅基础回复的适配器不具备经理派工/虚拟机工具能力。
不支持同时放置重复 id。错误会在刷新时显示。移除或写坏配置后停止接受新任务，已有记录保留。

## 传输：UTF-8 JSON Lines
每个回合启动一个进程，在任务 cwd 运行。stdin 第一行是：
`{"type":"run","protocol":"hub-jsonl-v1","run_id":"...","agent":"...","model":"...","effort":"default","cwd":"...","permission":"read-only|full","prompt":"...","system":"...","history":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}],"session_id":null,"tools":[]}`
必须遵守 system 及 permission，不能只转发 prompt。标准输出每行一个 JSON，日志写 stderr。
历史按项目和 Agent 隔离，成功回合保存在平台；超过 4 MB 时停止并保留上下文，不自动截断。

输出事件：
- `{"type":"text","text":"增量正文"}`：可选流式输出。
- `{"type":"result","status":"completed","text":"最终正文","session_id":"原生会话ID"}`：必须明确完成。text 可省略，此时使用所有 text 增量。空回复、EOF、未知事件、超时或只有 exit 0 均不算成功。失败发 `{"type":"error","message":"错误说明"}`。
- resume=true 时必须返回有效 session_id。下一轮提供该 ID；原生恢复成功时不要重复投递 history。历史是 stateless 适配器的上下文，也可作为恢复失败后的只读参考；不要默默创建新会话丢弃上下文。
- tools=true 时 tools 列出本轮实际授权的函数。调用 `{"type":"tool_call","id":"唯一编号","name":"工具名","arguments":{}}`，从 stdin 读取 `{"type":"tool_result","id":"同编号","result":...}` 或 error。平台检查停止锁与工具权限；不要自行提升授权。可通过这些工具使用派工、汇报、文件和 VM 管道。

停止/超时时平台终止适配器进程及其子进程，不自动重试已发送的推理请求。适配器自己的远端请求可能仍计费，须处理断开与取消。
远端会话和远端任务取消并不能由杀本地进程保证；需要适配器自己处理。
工具过程由原生 Harness 自己保存；stateless 适配器收到的 history 是成功问答记录，不包含原始工具完整轨迹。
平台保留 stdin/out 的协议边界，不收集 stderr 登录日志；请勿把凭据放进正文、事件或错误消息。

可以使用桥接脚本包装任何 CLI、ACP、HTTP API 或远端 Agent 平台；平台不保证第三方服务的授权、模型质量或订阅支持。

发送 completed 前必须持久化原生会话和所需状态；发送完成后平台会回收该回合进程及其子进程。

Windows PowerShell 适配脚本需将 `[Console]::InputEncoding` 与 `[Console]::OutputEncoding` 设为 UTF-8，并使用压缩单行 JSON。Python 子进程已设置 UTF-8 输入输出环境变量。

恢复时还会提供 session_cwd（原生会话最初绑定的目录）。若 Harness 需要原目录才能恢复，请用于恢复入口；实际文件修改必须使用本轮 cwd。resume=true 时不可默默返回不同的 session_id，需保留原生会话身份。

v1 不自动读取第三方订阅额度，也不把未知额度当作无限；可以使用平台的手动额度记录。

run 请求还包含 timeout_seconds，可用于设置远端 SDK/API 超时，尽早取消远端请求。
