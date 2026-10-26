# macOS 本地移植记录

更新：2026-10-25。开发分支 `macos-port`，起点 `d041084`，Windows 基线
`333843055f0cefc9b6ca438aeca23800dbb9b77b`。这些是未提交的本地开发改动，
不是新的发布版本。Windows v0.2.1 发布和安装流程保持原样。

## 运行

目前只在 **Apple Silicon arm64、macOS 27.2** 验证。原生窗口实现使用
Cocoa / WKWebView，最低要求 macOS 14（使用按标识隔离的 WebKit 数据存储）；
Tart 自身要求 Apple Silicon 和 macOS 13+。未验证 Intel、其他系统版本或 Windows 回归。

```sh
brew install python@3.13
python3.13 -m venv .venv
.venv/bin/python -m pip install -r desktop/requirements-macos.txt
.venv/bin/python desktop/launch_desktop.py --data ./local-data/mac-dev
```

不需要虚拟机即可启动。不会自动打开外部浏览器充当桌面窗口。
首次打开当前数据目录时自动显示配置指引；也可用 `--setup`、应用菜单或菜单栏图标重新打开。
引导分为模型接入、Tart（可选）和完成，可明确跳过模型/虚拟机，不自动调用模型。
完成状态保存在 `macos-onboarding.completed.json`，不会覆盖 Windows 的引导记录。
Mac 使用工作台内的引导，不运行 Windows 的 Tkinter 安装引导 EXE。
同数据目录、同端口的正常再次启动会恢复原窗口；数据目录所有权锁仍有效。
`--connect-only` 保留其原有语义，不会停止未知服务。

省略 `--data` 时，Mac 默认数据在：
`~/Library/Application Support/AgentMessageHubDesktop/data`。
WebKit 缓存按数据目录派生的 UUID 隔离，不使用 Safari 的默认存储。
项目、权限、会话、长期记忆及其版本继续使用原来的 SQLite/模块接口。

关闭主窗口或 Cmd+W 会隐藏窗口并通过 Mac 菜单栏图标保留后台运行，草稿和独立窗口状态保留。
Dock 再次打开、菜单栏“打开工作台”或再次启动同版本可恢复。Cmd+Q / 菜单栏“退出应用”会先确认，
然后停止所拥有的 Hub 服务与运行时。虚拟机电源状态不会随应用退出自动改变。
配置弹窗复用原 DOM 节点、事件和状态；Cocoa 提供 Cmd+C/V/A 等编辑菜单。
目录选择使用 NSOpenPanel，打开项目/成果目录使用 Finder。

## Harness 与凭据

- 增加 Mac 应用包内 Codex CLI 的发现，不增加独立的 Claude Code 接入。
  本机通过官方 app-server 的初始化、账号存在性与模型目录探测，返回 7 个模型。
  **没有发真实推理请求，不能据此宣称真实问答、远端工具、付费续接和取消已验收。**
- 内置/用户模块继续使用同一个 SDK/JSONL 接口。实际本地 HTTP 模拟提供商验证了
  模型问答返回、工具往返和第二轮历史；不是付费提供商测试。
- DeepSeek API 的原有保存密钥入口在 Mac 使用当前用户 Keychain，按数据目录隔离。
  文件仅保存非秘密引用标记。用合成字符串验证了增、读、改、删。
  Windows 仍用 DPAPI；拷贝过来的 DPAPI 密钥不能在 Mac 解密，需要重新配置。
  OpenRouter/Gemini 等原有环境变量流程仍然适用；没有宣称所有适配器都有 Keychain 配置界面。
- POSIX 的受管 CLI 和工具命令建立独立会话，取消时清理进程组。
  实测父进程退出后仍能清理其子进程。该机制不等同于 Windows Job Object：
  **宿主被 SIGKILL 时不保证自动回收，脱离会话的子进程和远端请求也不保证取消。**

## Tart

本机已通过 Homebrew 安装 Tart 2.40.1、其 softnet 依赖和 Python 3.13.17。
未启用 softnet、修改 DHCP/主机安全策略，未购买软件。
安装参考 [Tart 官方指南](https://github.com/openai/tart/blob/main/docs/quick-start.md)。

`VmBridge` 在 Mac 下选择 `TartBridge`，Windows 保留原 Hyper-V 后端。
`project_vm` 对外工具名、宿主授权及请求归属检查保留。
控制面提供安装检测/指南、经用户点击的 Homebrew 安装入口、镜像下载/创建、列表、启动、
正常/强制停止、连接验证、断开及自动连接偏好。Homebrew 缺失时提供官方指南，不执行 sudo；
如果 Homebrew 要求额外的软件包信任确认，会如实报告失败，不自动放宽信任。
启动是异步操作，检查到真实 Running 才完成；Guest Agent 连接另行验证。
连接会验证命令和二进制文件往返，传输失败与桌面缺失分别显示。

每个数据目录的 `TART_HOME` 是 `<data>/vm-bridge/tart/machines`，
不会自动管理用户默认 `~/.tart` 下的已有虚拟机。可以按以下方式准备免费测试镜像：

```sh
export TART_HOME="$PWD/local-data/mac-dev/vm-bridge/tart/machines"
tart clone ghcr.io/cirruslabs/ubuntu:latest hub-ubuntu
```

也可直接在设置中选择 Ubuntu ARM / macOS Sequoia 模板并点击“下载镜像并创建”。
镜像下载会占用数 GB 至数十 GB 磁盘；应用不会在启动时自动下载，也不会覆盖同名 VM。
保存连接并启用自动连接后，启动应用或打开 Agent/设置面板会自动开机并验证 Guest Agent。
同一数据目录使用单次连接任务，避免重复开机；每个新宿主进程都需重新验证，不复用过期成功状态。
断开会关闭自动连接，保留 VM 与所选名称；可随时重新连接。Tart 自动缓存清理已禁用，避免意外删除镜像。
也可以在同一 TART_HOME 下手动使用官方 `tart create/clone` 管理镜像。
访客需要 Tart Guest Agent；文件传输额外需要 Python 3。

```json
{"action":"exec","shell":"posix","script":"uname -sm; pwd"}
```

Tart 必须显式指定 `shell: posix`，不会把原有 PowerShell `script` 静默改作 Shell。
Hyper-V 拒绝这个 POSIX 参数并继续使用 PowerShell。
`push/pull` 当前仅支持成员工作目录内的单个普通文件，最大 8 MiB。
工具返回 queued 只代表入队，必须按请求编号查到 completed；失败不自动重试。

**实测**：独立数据目录 `local-data/tart-validation` 中的 ARM Ubuntu VM
`hub-ubuntu-validation` 完成列表、启动、Guest Agent 连接、自检文件往返、命令、
34 字节二进制文件 push/pull 和正常停止。往返 SHA-256：
`0a1f115fb51c014497f2feba3f93afea3a70011001eb58758041cd753060415e`。
测试 VM 已关机，镜像保留在本地（约 10 GB）；没有把它加入普通开发数据目录。

**未支持**：截图、屏幕预览、窗口树、控件操作、键鼠和桌面租约。
已逐项确认这些调用明确返回不支持，不伪造成功。未验证 macOS 访客或强制停止。
VM 命令超时只终止本机等待，不保证访客任务终止；错误会明确提示先检查，不自动重试。

## 通知与本地打包

实现 UserNotifications 权限请求和完成事件提交，仅在用户点击应用菜单的
`Enable Notifications / 允许通知` 时请求授权。未授权会明确失败；不会冒充系统通知已送达。
源码 Python 宿主没有可靠的应用通知身份，应使用 .app。
**尚未人工授权并验证真实通知中心送达与点击跳转。** 点击跳转已接入项目选择，但尚未完成系统通知端到端验收。
Mac 菜单栏状态项复用 Windows 的只读 StatusCache：显示进行中的项目与进度、Agent 状态、
点击项目恢复/切换工作区，以及完成/演示事件提示。通知权限不足时仍在菜单栏保留待查看事件，
不伪造系统通知已送达。读取状态与菜单展开不触发提供商调用。

```sh
.venv/bin/python -m pip install pyinstaller
.venv/bin/python desktop/build_macos_icon.py
.venv/bin/python -m PyInstaller --noconfirm \
  --distpath desktop/macos-dist --workpath desktop/macos-build desktop/hub_macos.spec
.venv/bin/python desktop/build_macos_dmg.py --app "desktop/macos-dist/Agent Hub.app"
open "desktop/macos-installer-dist/AgentHub-macOS-arm64-dev.dmg"
```

产物为 arm64 本地开发 `.app`（约 25 MB 单个应用包），内含 Python、Cocoa 桥、服务、
前端与模块。DMG 位于 `desktop/macos-installer-dist/AgentHub-macOS-arm64-dev.dmg`，包含
应用、Applications 拖入快捷方式和中英文安装说明。当前新应用输出位于 `desktop/macos-next-dist/Agent Hub.app`。
构建只做本地 ad-hoc 签名；没有 Developer ID 签名、公证、自动更新或发布。安装前需先保存草稿并退出旧版，
新宿主发现旧版正在运行时会显示明确提示，不强制停止任务或静默恢复旧界面。
Windows 的 WebView2 DLL 和 Inno Setup 不参与 Mac 构建。

## 验证记录

在独立临时目录完成，未发送付费推理：

| 检查 | 结果 |
| --- | --- |
| 服务 `--smoke-test` | 认证、18 项资源、严格 CSP、同源会话交换通过 |
| 源码及打包 `.app` 的 `--window-smoke-test` | 真实 WKWebView、认证读状态、独立配置窗口、DOM 返回、草稿保留与关闭通过 |
| `test_long_term_memory.py` | 9 项通过：跨项目、版本冲突、锁定、回滚及经理授权 |
| `test_unified_modules.py` | 12 项通过，含真实本地模拟 HTTP 工具循环和历史 |
| `test_integrations.py` | 22 项通过 |
| `test_macos_port.py` | 4 项通过：进程组、请求归属、路径/脚本边界、失败结果、平台分派 |
| `test_manager_layout.py` | 1440×900、1024×600、600×800 的长回复/批准卡片/发送区通过 |
| `test_reading_browser.py` | 原回复、展开、节点和滚动位置保持通过 |
| `test_nine_browser.py` | 9 个卡片与草稿保持通过 |
| `test_long_term_memory_browser.py` | 1280×800、800×600 的保存/锁定/预览/回滚/冲突保留草稿通过 |
| `test_tart_browser.py` | 真实浏览器中隐藏 Windows 凭据、显示 Tart 列表、不把未验证文件传输显示为成功 |
| Keychain 合成条目 / Codex 官方只读探测 / Tart 实机 | 如上，范围有限 |

最终 `.app` 还实际检查了接入引导、独立设置窗、中英文切换及语言写入对应数据目录，
同端口再次启动恢复原窗口；Cmd+Q 后回环服务端口关闭。原生窗口烟测也覆盖了
Cocoa 关闭按钮返回原 DOM 和保留草稿的路径。本地 ad-hoc 包通过 `codesign --verify --deep --strict`。

浏览器测试使用本机 `/Applications/Microsoft Edge.app`，没有按 Windows 路径跳过。
修正了临时目录 `/var` 与 `/private/var` 的字符串比较误报、固定延迟等待、CDP 页面事件启用
和测试浏览器回收。诊断还发现服务默认仅五个待接受连接会导致并发脚本资源加载失败；
服务及快速启动壳的积压队列已扩大为 128，实际布局测试随后通过。

历史测试问题仍存在：本机 `test_antigravity.py` 为 14 项、1 失败/12 错误，
`test_codex_runtime.py` 为 7 项、6 错误，与交接记录的失败数量一致。
没有修整这些旧身份夹具，也没有宣称全套测试或 Windows 回归通过。

下一阶段：获得相应授权后完成真实 Harness 推理/续接/取消验收；实现并验证 Tart 桌面能力；
验证通知中心与点击跳转；完善自动更新和签名公证；在 Windows 与其他 Mac 上回归。

## 原生外观补齐（同日）

首次本地包遗漏了 ICNS 图标，也只启用了独立窗口标志；前端标题栏要求 Windows
`chrome.webview` 桥，因此 Mac 上没有标题栏工具、侧栏折叠和连续背景。这些遗漏已补齐：

- 从现有 `desktop/app.ico` 生成多尺寸 `app.icns`，由 Mac BUNDLE 明确指定；Windows 图标未改。
- 标题栏复用原布局和折叠逻辑，通过 WKWebView 的同源消息桥接入 Cocoa；Mac 使用原生交通灯，
  不显示 Windows 标题栏按钮，也不采用 Windows 拖动/边缘缩放消息。
- 主窗口采用透明标题栏及 full-size content view，以 NSVisualEffectView 的 Sidebar 材质
  连续覆盖标题栏和左侧导航；阅读/内容区域保留原本独立背景。遵守系统减少透明度设置。
- `test_macos_chrome_browser.py` 在 1440×900、1024×600、600×800 合并验证长回复、长批准卡片、
  发送区、阅读位置、草稿、折叠/展开及主题消息；`test_titlebar_browser.py` 的 Windows 桥分支通过。
  AGENTS.md 的三项强制浏览器测试重新通过，真实 WKWebView 烟测验证 native_chrome/sidebar_toggle。
- 在独立数据目录和独立 Review 应用身份中实际查看连续背景并点击折叠/展开；没有强制退出用户原窗口。

初期测试 VM 留在先前说明的隔离目录。本轮按用户要求另在默认应用数据目录创建了
`agent-hub-ubuntu`，开启自动连接，并实际验证开机、Guest Agent、文件往返以及新宿主进程自动重连；
未搬迁或覆盖测试 VM、项目、凭据和长期记忆。默认 VM 目前保留运行，供打开新面板时连接。
更新 `.app` 文件不会替换内存中正在运行的旧宿主；需保存草稿、退出旧进程后重新打开新包。

## 首次配置、菜单栏与安装包验收（同日）

- `test_macos_onboarding.py`：3 项通过，覆盖用户权限、无 Homebrew/Tart 情况、配置持久化、版本损坏、单次连接与文件传输失败的真实状态。
- `test_macos_onboarding_browser.py`：1280×800 / 800×600 下走完 Tart 跳过与完成，重新加载后不重复显示，保留草稿且完成按钮可达。
- `test_tart_browser.py`：2 项通过，包含打开面板自动连接、禁止重复连接、偏好关闭及未验证传输不显示成功。
- `test_desktop_notifications.py`：3 项通过，项目完成事件去重、只读状态和历史事件不重复提示。
- AGENTS.md 三项强制浏览器测试、Mac 标题栏三尺寸测试及长期记忆浏览器测试通过。
- 最终原生包首开烟测：first_run_shown、tray_hide_restore、18 个真实菜单项、标题栏、独立弹窗和草稿保护通过。
- 最终 DMG 只读挂载后实际复制应用到独立安装目录，严格签名校验通过；同一全新数据目录启动两次，首次自动显示配置指引，第二次不再显示。两次均通过真实 WKWebView 与菜单栏烟测，未发送模型推理。详细记录在 `desktop/macos-installer-dist/verification.json`。
- 原生界面人工检查确认：主窗口红色关闭按钮隐藏窗口后服务仍可用；Cmd+Q 显示退出确认，确认后应用与所属服务退出。首次指引的“稍后配置”按钮曾被旧样式隐藏，已修复，并加入可见性回归检查。
- 最终 DMG SHA-256：`268f26327ef1c9651ea83b68c4b80516be847a288d665011ee1daa3dff6b71a3`。原 `desktop/macos-dist/Agent Hub.app` 也已更新；旧包保存在 `desktop/macos-prior-dist/`，没有覆盖用户数据。

## Harness 检测与默认身份修正（同日后续）

- 修复 DeepSeek Harness 的 Mac 应用布局检测、显式应用/可执行文件路径、账号/目录配置传递与 frozen MCP 启动。实机官方 CLI `0.2.1-rc.3` 版本命令和 ACP initialize（protocolVersion 1 / deepseek-harness-acp）通过；未发 session/prompt，未验证真实推理。
- CLI 搜索增加 Finder 环境下的 Homebrew、用户 local/bun/npm/pnpm 与 nvm 路径；CLI 子环境补齐 PATH，不执行 shell 配置。Antigravity 桌面应用本身不作为 agy CLI 已安装的依据，缺少 CLI 时仍如实报告未找到。
- Mac 的终端登录使用仅用户可执行的参数转义 `.command` 文件并显式打开 Terminal；DeepSeek 登录打开官方应用。隔离测试验证脚本生成和转义，未冒充各厂商真实登录成功。
- Mac 桌面新数据目录不再播种旧九个 DS 身份或其 token。正常数据目录的 deepseek-1 至 deepseek-9 已经通过运行中服务的 archive 接口全部停用，保留历史；未改写项目记录。
- 扩大测试复现 Darwin 对未回收僵尸进程组 killpg 返回 EPERM：关闭进程组前先 poll 回收组长，仍终止存活后代。新增真实短命进程回归，原后代取消测试通过。
- 本轮测试：Mac Harness 5、代理 5、自定义 Harness 34、接入注册 22、统一模块 12、Mac 平台边界 4、长期记忆 9 项通过；AGENTS.md 三项布局/阅读浏览器测试通过。最终打包模块烟测及空工作区原生窗口烟测通过（菜单 10 项，无默认 Agent）。
- 本轮安装包为 `desktop/macos-installer-dist/AgentHub-macOS-arm64-harness-fix.dmg`；对应哈希和 `harness-fix.verification.json` 同目录。已通过签名、映像校验，尚未公证。用户当前运行的旧版应用未被强制退出或覆盖，需退出后替换安装。
- OpenCode、Ori、CodeBuddy CLI、agy 尚未在本机安装：修复及隔离测试不等于真实提供商的登录、模型调用、续接、取消已验收。未付费调用、安装这些 CLI、提交或发布。

## DeepSeek 添加向导旧连接拦截修正

截图中的“请先在配置中心完成 DeepSeek 接入”来自 `wizard_add` 的 legacy 分支：目录检测已通过，但启用仍要求旧全局配置。Mac 桌面现在创建与其他 Harness 同等的 `deepseek-harness-local` 模块连接，不再展示没有启用成员的旧默认连接。旧身份与会话保留。旧向导请求若明确确认启用且已有真实目录探测，转入模块连接；未探测时要求先读取官方目录，不能用旧预置列表启用。

新增三个回归用例验证禁用旧连接转入模块、无探测禁止启用、Mac 不展示闲置旧连接；接入测试 25 项及统一模块 12 项通过，三项规定布局/阅读测试通过。最终原生包空工作区烟测通过。安装包为 `desktop/macos-installer-dist/AgentHub-macOS-arm64-wizard-fix.dmg`，构建标识 `macos-harness-wizard-3`；仍是本地 ad-hoc 签名，未公证或发布，未进行真实模型推理。

## 演示审阅缩放裁切修正

用户明确反馈的是缩放变裁切，而非鼠标拖动。预览原先使用 CSS zoom 缩放含 iframe 的画布；现改为 transform 缩放完整渲染面，独立 spacer 维护缩放后的宽高与滚动范围，iframe 视口保持页面原始尺寸，批注层一同缩放。缩放中心、拖动画布、框选、反馈草稿及阅读位置仍沿用原交互。

新增 `test_design_webkit.py` 使用真实 WKWebView 和本地模拟演示，截图测量 iframe 内红色矩形：原始 200×100 在 50% / 100% / 200% 分别实测为 100×50 / 200×100 / 400×200，未用 DOM 存在性替代渲染验证。`test_design_browser.py` 三尺寸审阅、框选、反馈提交及重载恢复通过；修正旧测试固定 120ms 等待预览的竞态，并排除只读字段的自动填充误报。AGENTS.md 的三项强制布局/阅读测试通过。Windows 原生运行时未在本机验证。

修复版为 `desktop/macos-installer-dist/AgentHub-macOS-arm64-demo-zoom-fix.dmg`，构建标识 `macos-demo-surface-zoom-4`。本地 ad-hoc 签名，无公证；未调用模型、提交或发布。

## 合并 Windows main 修复（2026-10-25）

合入 `origin/main` 的 `050a81ba957712e6c9c107af2ae350211333d98b`：经理计划空字段恢复、原始回复/解析错误展示、Harness 账号与 API 凭据状态、实际模型目录、额度刷新、检查不隐式打开登录及 Windows 安装维护逻辑。唯一文本冲突位于 DeepSeek `probe_catalog`，采用 main 的配置与官方目录读取逻辑，同时保留 Mac 应用路径、CLI 环境和 frozen MCP 适配。修正引导单测只模拟宿主 locate、遗漏模块 locate 的环境依赖，未放宽真实登录检查。

合并后通过：计划响应 6、经理拥有计划 5、Harness 账号 7、接入注册 25、Mac Harness 5、长期记忆 9、统一模块 12、Mac 引导服务 3 项；可运行的旧引导服务测试 9 项通过、1 项平台跳过。AGENTS.md 三项浏览器测试、Mac 引导浏览器、Mac 标题栏浏览器、演示三尺寸/恢复测试、WKWebView 50%/100%/200% 像素测试通过。

未验证的旧 Tk 引导：本机缺少 `_tkinter`，两项 Tk 布局及一项 VM 向导测试无法运行，不计为通过。另将原始 main 提取到隔离目录对照：`test_planning.py` 两边均 18 项/17 错误，`test_workflows.py` 两边均 10 项/9 错误，均为旧 `sol-2` 身份夹具；`test_manager_owned_plan.py` 两边均 5 项通过。没有改写这些旧夹具，也没有声称全套测试通过。无真实付费推理；本次为源码合并，之前发布的安装包仍对应此前构建。

## 合入 main 后的 0.2.2 构建

Mac 打包版本号从 `pyproject.toml` 读取，避免主分支更新版本后 Mac 包仍显示 0.2.1；宿主构建标识更新为 `macos-main-sync-0.2.2-5`。本地 DMG 路径为 `desktop/macos-installer-dist/AgentHub-macOS-arm64-0.2.2.dmg`，验证摘要和 SHA-256 校验文件同目录。签名仍为本地 ad-hoc，未公证；不将已有 Release 安装包静默替换。
