# Antigravity 代理问题排查与修复

日期：2026-10-18，Asia/Shanghai。

**结论：Hub 启动的 CLI 未继承 Windows 系统代理。补齐相同代理后，Gemini Flash 的真实请求成功。之前把官方地区错误直接归因为当前账号不可用，判断不充分。**

## 本机证据

| 检查 | 实际结果 |
|---|---|
| Windows 用户系统代理 | 开启，127.0.0.1:7890 |
| 代理监听 | FlClashCore 正在本地 7890 端口监听 |
| WinHTTP 设置 | 直连；未修改 |
| Hub/CLI 原进程环境 | 没有 HTTP_PROXY、HTTPS_PROXY、ALL_PROXY |
| CLI 原路径真实尝试 | 官方返回 FAILED_PRECONDITION，地区不支持 |
| 仅补子进程代理后 | 同一官方 CLI、同一 Gemini Flash medium，SUCCESS，退出码 0，回复 HUB_PROXY_OK |

对照请求使用本机 CLI 已缓存的 Google 登录；子进程继续排除 API Key/ADC 计费路线，未切换账号或访问私有接口。请求只要求回复一个标记，不使用文件或命令工具。约 12.35 秒完成（官方模型步骤约 3.27 秒），官方用量 11851 total tokens。原始证据见 `antigravity-proxy-test.json`。

用户环境中另有 GEMINI_API_KEY，本次仅检查是否设置，未读取或输出其值。接入器始终从订阅执行子进程中移除此变量；修复改变的是代理继承，不是 API 计费通道。

## 已实现的修复

`hub/proxy_env.py` 只读 Windows 当前用户的 Internet Settings，在 CLI 子进程没有显式 HTTP/HTTPS/ALL_PROXY 时，将已经启用的手动系统代理转换为标准代理环境变量；现有显式环境配置优先。支持通用代理地址及 http=/https= 分协议地址，保留已有 NO_PROXY，补充本地回环绕行规则。用于 Antigravity 的模型探测、额度读取和真实执行。

不修改系统代理、注册表、WinHTTP、Clash 节点或账号；不执行 PAC，不关闭 TLS 校验、不安装证书、不拦截认证流量。代理诊断信息会移除 URL 中的用户名/密码。完整运行仍通过官方 CLI，平台没有直接调用其内部端点。

面板已显示实际子进程代理信息和修复后成功记录，旧的地区失败日志保留为历史。Claude 五小时额度为 0 是另一项限制；代理修复不会增加额度。等待任务仍须在预计恢复后重新读取官方额度。

## 验证

44 项自动测试通过，新增检查包括系统代理到子进程的转换、显式配置优先、分协议解析、绕行规则、凭证脱敏和输入环境不被修改。另有上述一次真实 Gemini 连通成功；它验证了模型调用，不声称额外完成了文件修改任务。
