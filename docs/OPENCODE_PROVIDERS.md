# OpenCode 供应商模块

按 CC Switch 的 87 个供应商分组生成，其中 84 个模块可配置使用，覆盖 104 个地区／套餐变体。原始预设共 107 项；分组口径与 CC Switch 面板一致，没有把地区和套餐误算为独立供应商。

这是一组 **配置和执行适配模块**，不是 84 家服务商全部通过真实推理验收的承诺。调用仍需本机安装支持 ACP 的 OpenCode，以及自己的合法凭据与模型权限。

## 上手

1. 打开“添加 Agent”，选择 `OpenCode【供应商】`。
2. 在该供应商配置中选择地区／套餐，确认服务地址。
3. 填 API Key（Windows DPAPI 加密保存，macOS 保存到 Keychain），或填写已有密钥环境变量的名称。两种方式二选一；界面不回显已保存的密钥。其他系统使用环境变量。
4. 可填写逗号分隔的模型 ID 白名单；留空只展示当前套餐的预设模型。本地 Ollama、llama.cpp、vLLM 应按本机服务地址和已加载模型调整，预设不负责下载安装模型。
5. 保存后进入模型选择并添加 Agent。添加本身不调用模型；卡片上的真实测试会消耗额度，失败不会自动重复请求。

密钥变更前须结束在途任务；正在进行的项目不允许悄悄更换其连接的地区、地址和模型列表。首次安装引导可先跳过 Agent 配置，进入主程序后填写这些独立供应商的凭据。

## 并发与隔离

84 项共用 `hub/builtin_adapters/opencode/runtime.py` 和 `provider.py`，每项由自己的 `adapter.json` 与薄入口脚本声明预设。可以与原版 OpenCode 同时运行。

每个连接单独设置供应商命名空间、`OPENCODE_CONFIG_CONTENT`、配置／数据／缓存／状态目录和 `OPENCODE_DB`；密钥只传给本连接启动的子进程。限定 `enabled_providers` 并关闭项目配置、外部插件及额外技能加载，避免用户全局配置或项目配置覆盖路由。保留 Windows 自定义 Git Bash 路径。未修改 OpenCode 原有配置、登录或数据库，也不读取 CC Switch 的凭据数据库。

默认原版 **OpenCode** 仍沿用用户现有配置和认证。通过独立连接和 Agent 身份保存项目会话；供应商地区或地址变更会更换模型命名空间，不将旧模型悄悄映射到新地址。

每项预设先显示默认档位；本机 OpenCode 成功确认所选模型后，才使用 ACP 返回的可用档位。模型目录、档位确认和凭据存在都不代表付费请求一定可用。此组模块不提供未验证的余额读取。

## 跳过的三项

- **AWS Bedrock**：需要额外验证 AWS 身份、区域和请求签名，不伪装成普通 API Key 接入。
- **Oh My OpenCode**、**Oh My OpenCode Slim**：是插件／工作流配置，不是独立模型供应商。独立供应商模块有意关闭外部插件。

## 验证范围

自动化检查覆盖全部 84 项和 104 个变体的目录生成；模拟 ACP 子进程验证两个不同供应商与原版三路并发、独立密钥／数据库／会话、续接、错误脱敏和加密保存；浏览器检查覆盖三种窗口尺寸的配置、套餐选择、模型过滤、密钥清理与可滚动操作区。

本机 **OpenCode 2.0.32** 已实测 DeepSeek、MiniMax、Ollama 的独立模型目录，以及 ACP 无推理模型／档位确认。模型目录测试使用独立服务，ACP 本身也启动独立服务。**未向这些供应商发送真实推理请求，未完成 Mac 实机和全部服务商的账号验收。** 老版本 OpenCode 应升级后再验证配置隔离，不回退到共享全局配置。

## 来源与重新生成

预设来源固定在 CC Switch 提交 `88c878ac9da1d89ec1b512f87b52f3641dd30e3c` 的 `src/config/opencodeProviderPresets.ts`，按 MIT 使用，见[第三方声明](../THIRD_PARTY_NOTICES.md)。公共配置快照位于 `tools/vendor/cc-switch-opencode-presets.json`；网址已去除推广查询参数，不含用户密钥。此数据快照不是执行脚本，也不会自动联网更新。

运行 `python tools/generate_opencode_providers.py` 可从仓库内快照重新生成模块。不要直接在生成的内置文件中维护自己的修改；需要扩展时复制整个模块到 `adapters/custom`，修改模块 ID，仍使用同一套执行与配置接口。

完整机器可读清单：[OPENCODE_PROVIDERS.json](OPENCODE_PROVIDERS.json)。

## 87 项对照

| 供应商分组 | 地区／套餐数 | 结果 |
| --- | ---: | --- |
| Kimi | 4 | 已生成 |
| PackyCode | 1 | 已生成 |
| APINebula | 1 | 已生成 |
| AICodeMirror | 1 | 已生成 |
| hao.ai | 1 | 已生成 |
| FennoAI | 1 | 已生成 |
| RunAPI | 1 | 已生成 |
| OpenModel | 1 | 已生成 |
| GrooRoute Pro | 1 | 已生成 |
| DIT.ai | 1 | 已生成 |
| BuyToken | 1 | 已生成 |
| V-API | 1 | 已生成 |
| TokenFactory | 1 | 已生成 |
| FluxA Token Plan | 1 | 已生成 |
| AIGoCode | 1 | 已生成 |
| Qiniu | 1 | 已生成 |
| AICoding | 1 | 已生成 |
| SubRouter | 1 | 已生成 |
| Shengsuanyun | 1 | 已生成 |
| 88API | 1 | 已生成 |
| APIKEY.FUN | 1 | 已生成 |
| 9527CODE | 1 | 已生成 |
| Code0 | 1 | 已生成 |
| TeamoRouter | 1 | 已生成 |
| PPIO | 1 | 已生成 |
| ClaudeCN | 1 | 已生成 |
| 火山引擎 | 3 | 已生成 |
| BytePlus | 1 | 已生成 |
| A6API | 1 | 已生成 |
| CCSub | 1 | 已生成 |
| SSSAiCode | 1 | 已生成 |
| SoleAPI | 1 | 已生成 |
| Micu | 1 | 已生成 |
| RightCode | 1 | 已生成 |
| Cubence | 1 | 已生成 |
| CrazyRouter | 1 | 已生成 |
| DMXAPI | 1 | 已生成 |
| SudoCode | 2 | 已生成 |
| XycAi | 1 | 已生成 |
| Modelflare | 1 | 已生成 |
| AllTokens | 1 | 已生成 |
| AllTokens SI | 1 | 已生成 |
| Tu-zi | 1 | 已生成 |
| Amux | 1 | 已生成 |
| AtlasCloud | 1 | 已生成 |
| Soshow | 1 | 已生成 |
| DeepSeek | 1 | 已生成 |
| 智谱 GLM | 2 | 已生成 |
| 腾讯云 | 6 | 已生成 |
| Baidu Qianfan Token Plan | 1 | 已生成 |
| 千问AI平台 | 2 | 已生成 |
| QwenCloud | 3 | 已生成 |
| StepFun | 2 | 已生成 |
| StepFun Step Plan | 1 | 已生成 |
| ModelScope | 1 | 已生成 |
| StreamLake | 2 | 已生成 |
| Longcat | 1 | 已生成 |
| MiniMax | 2 | 已生成 |
| BaiLing | 1 | 已生成 |
| Xiaomi MiMo | 2 | 已生成 |
| OpenCode Go | 1 | 已生成 |
| SiliconFlow | 2 | 已生成 |
| AiHubMix | 1 | 已生成 |
| CherryIN | 1 | 已生成 |
| OpenRouter | 1 | 已生成 |
| TheRouter | 1 | 已生成 |
| Novita AI | 1 | 已生成 |
| Nvidia | 1 | 已生成 |
| PIPELLM | 1 | 已生成 |
| E-FlowCode | 1 | 已生成 |
| AWS Bedrock | 1 | 跳过：AWS 云身份、区域和签名认证需单独验证 |
| Ollama | 1 | 已生成 |
| llama.cpp | 1 | 已生成 |
| vLLM | 1 | 已生成 |
| Oh My OpenCode | 1 | 跳过：插件预设，不是独立模型供应商 |
| Oh My OpenCode Slim | 1 | 跳过：插件预设，不是独立模型供应商 |
| JieKou AI | 1 | 已生成 |
| AICodeWith | 1 | 已生成 |
| 模力方舟 | 1 | 已生成 |
| SoruxGPT | 1 | 已生成 |
| IKunCode | 1 | 已生成 |
| RunToken | 1 | 已生成 |
| BotCF | 1 | 已生成 |
| YYLX | 1 | 已生成 |
| TokenFlux | 1 | 已生成 |
| NekoCode | 1 | 已生成 |
| AIComing | 1 | 已生成 |


配置表单已迁移到模块声明字段，完整格式和脚本读取方式见 [MODULE_CONFIGURATION.md](https://github.com/Dias-Dd/agent-hub-desktop/blob/main/docs/MODULE_CONFIGURATION.md)。
