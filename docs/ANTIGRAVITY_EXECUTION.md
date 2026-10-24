# Antigravity Google 订阅执行器

## 代理排查更新（当前）

Gemini 已真实连通：之前的地区错误源于 CLI 没有继承用户的 Windows 系统代理。仅为 CLI 子进程补齐现有 127.0.0.1:7890 后，Gemini Flash 返回 SUCCESS / HUB_PROXY_OK，退出码 0。接入器已自动继承用户既有代理，不修改系统设置。详见 PROXY_DIAGNOSIS.md 和 antigravity-proxy-test.json。Claude 额度为零仍需等待；下面地区失败段落为修复前历史记录，不应作为当前结论。

更新日期：2026-10-18，Asia/Shanghai。适配器已实现并接入 Hub，但**当前本机 Gemini 实际请求被官方地区限制拒绝，Claude 五小时额度为 0，不能声称两者已成功执行任务**。

## 本机核验

- 官方 Windows 默认位置 `AppData/Local/agy/bin/agy.exe`，版本 1.4.0。旧进程 PATH 未刷新；Hub 已支持官方默认位置发现，不修改系统 PATH。
- 官方 `agy models` 实际返回 `gemini-3.8-flash-medium`、`gemini-4-argon-medium`、`claude-opus-5-5-medium`，也列出 Sonnet 5.5 等其它选择；九个固定身份保持不变，本版使用 Flash×3、Argon×1、Opus×1。
- 官方 `agy -p /usage` 实际返回共享额度窗口：Gemini 五小时/周均 100%，Argon 独立周窗口 95%；Claude/GPT 共享组周额度 48%，五小时 0%。这是 Antigravity 分组，不是 OpenAI 账号额度。
- Claude 五小时预计恢复：**2026-10-18 01:57:36（北京时间）**，实际是否恢复以再次查询为准。Gemini 的可用额度不表示其地区访问已经通过。
- 仅发起一次真实 Gemini Flash 验收尝试，官方 init 返回指定模型和 always-proceed 权限，随后最终 ERROR：`FAILED_PRECONDITION (code 400): User location is not supported for the API use.`。没有实际生成测试产物，未称为成功。见 `antigravity-live-test.json`。
- Claude 未发起推理，避免在已知额度为零时试调用。未操作升级、购买或额度重置，未使用代理绕过地区限制。

官方资料列出 Google AI Pro 非试用订阅可使用 Argon 和 Claude 5.5，但安装 CLI、列出模型不等于所有请求必然通过账号/地区/额度检查。Hub 不读取 Cookie、OAuth 凭证或私有 API。

## 使用方法

连接仪表盘，在 **Antigravity 真实任务执行** 面板：

1. 点击“读取订阅模型与额度”，查看当前官方结果。
2. 展开配置，选择已存在的工作目录、完全访问、任务次数和时间预算，确认保存。当前实例已沿用用户的完全访问偏好，授权预算为 3 项、每项 900 秒；下载包的新数据目录默认关闭。
3. 选择 flash-1/2/3、argon 或 opus，填写具体任务并批准。该批准绑定任务文本、身份、实际模型、工作目录与权限。
4. 查看官方 CLI 流式工具步骤、最终回复及用量。额度耗尽时状态为 waiting_quota，可取消；到了预计时间再核实额度，未恢复就继续等待，不会仅凭时间启动。

当前地区限制应由官方支持的账号/地区条件解决或向提供商查询；本项目没有也不会添加绕过机制。不要把地区失败当作模型离线或伪造成功回复。

## 实现边界

只使用官方 `models`、`-p /usage` 与 `--input-format stream-json --output-format stream-json`。每次调用固定 `--model` 和 `--effort medium`，用 `--mode auto --dangerously-skip-permissions` 实现用户已经授权的完全访问。不会修改用户全局权限设置。角色指引通过官方 CLI 输入文本传入，不假称存在 CLI 未提供的 system-prompt 参数。

启动前清除子进程的 API Key、ADC 与端点覆盖环境；拒绝明确配置为 API/企业认证的用户设置；要求官方共享订阅额度可读取。不接触密钥值或登录数据库，不自动回退到 API 计费。官方 CLI 使用其自身缓存的个人 Google 登录；未额外独立验证 Google One 账单或订阅付费状态。

Codex 和 Antigravity 共用一个持久化执行队列与全局执行槽，避免同时改写同一项目，但权限配置、次数预算、日志和额度分别保存。SQLite provider/retry_after 字段会从旧版本自动添加。启用真实身份后，它们停止模拟消费。

Antigravity 此版本没有已验证的流式服务端取消请求。停止或超时会终止本地受管 CLI 进程树，任务标 uncertain；不会伪称服务端已停止计费或撤销文件修改。只有最终 SUCCESS 且退出码 0，并验证官方 init 的模型/权限，才标完成。运行中重启不自动重放；只有尚未启动推理的 waiting_quota 任务允许重新核实额度后启动。

调用次数预算不是美元或 token 硬上限。额度等待保留批准，取消等待释放未执行预算。提供商错误、地区错误和不确定的已启动任务不会自动重试。

## 验证与来源

39 项自动测试全部通过，含两个提供商的 HTTP 路由、预算与权限、队列隔离、共享额度解析、额度等待/恢复唤醒、官方地区错误不冒充成功、模型 init 不一致拒绝。真实 Gemini 请求失败与 Claude 未验证情况见上文，测试通过不等于提供商限制已解除。

[官方无界面 CLI](https://www.antigravity.google/docs/cli/headless/) · [官方模型与订阅说明](https://www.antigravity.google/docs/models) · [官方认证说明](https://www.antigravity.google/docs/install?tab=cli)
