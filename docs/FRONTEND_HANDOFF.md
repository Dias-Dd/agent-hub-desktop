# Hub 前端改造：给 Argon 和执行者的交接指引

这是对**当前实际实现**的说明，不是要求立刻修改后端，也不是模型调用授权。先讨论方案，用户确认“按计划执行”后实施。接口变更后重新核对源码，不能把本文当作永远正确的协议。

## 1. 目标与实施位置

将现有 Deskfellows 改成漂亮、清楚、易操作的本地工作台，保留真实功能和状态，不做只能演示的假面板。

当前 Hub 源码根目录：

```text
C:\Users\ASUS\Documents\Codex\2026-10-17\referenced-chatgpt-conversation-this-is-an\outputs\agent-message-hub
```

先核对实际任务的工作目录。新建“项目”按钮会自动创建空的项目目录，**它不是 Hub 源码**。如果用新项目分组来组织这次改造，要在执行设置中明确选择 Hub 的开发副本目录。优先在隔离源码副本里开发，复制时排除 data、密钥、运行日志、缓存和已有项目产物。验收后交付差异及部署说明，部署前让用户检查，不在自己的任务执行中停止承载任务的 Hub。

## 2. 先读什么，不要把整个仓库塞进每个 Prompt

| 文件 | 解决什么问题 |
|---|---|
| 本文 | 产品流程、接口用途、容易混淆的语义与验收要求 |
| `docs/frontend-actions.json` | 当前 action 的真实参数、必填项、默认值和源码位置 |
| `hub/server.py` | 真正存在的 HTTP 路由、认证、项目筛选、静态文件白名单与 CSP |
| `hub/static/app.js` | 当前请求包装、轮询、状态渲染与通用操作 |
| `hub/static/workflow.js` | 计划讨论、明确批准、项目切换、停止与恢复交互 |
| `hub/static/deepseek.js` | 密钥向导、费用授权、接管、额度通知 |
| `hub/projects.py` | project_id 的分组与状态过滤 |
| `hub/planning.py` | 计划版本、讨论与执行授权的边界 |
| `hub/workflows.py` | 项目工作流、当前经理、完成验收与交接 |
| `hub/quota_monitor.py` | 低额度、耗尽、恢复、双通知与交回规则 |

当前计划讨论模式禁止使用工具，Argon在讨论阶段不能直接读这些文件。请先把任务说明中的简短接口概况提供给它；用户批准后，由执行者先读本文相关部分及自己负责的文件；消息仅写目标、接口名、文件范围、验收与依赖。完整手册留在文件里按需读。较早的 `docs/API.md` 含旧预算等历史信息；出现冲突以当前源码验证为准。

更新机器参考：在源码根目录运行 `python tools/export_frontend_contract.py`。它只解析源码，不启动服务、不读账号、不调用模型。JSON 是方法签名索引，不代替类型、权限和前置条件验证。

## 3. HTTP 到底是什么

前端通过 HTTP 向本地 Hub 读取状态、提交操作；后端才负责数据库、模型调用、权限、队列与调度。前端不用直接连接模型提供商，也不用启动 MCP 客户端。

只有这些核心入口，**不要杜撰** `/api/agents`、`/api/tasks`、`/api/projects/:id`、WebSocket 或 SSE：

| 请求 | 用途 | 返回 |
|---|---|---|
| `GET /api/state` | 读取工作台快照；用户身份返回完整的可见工作台数据 | 直接返回状态对象，不包 `result` |
| `GET /health` | HTTP/调度心跳；不是模型在线或项目成功的证明 | `{ok, supervisor, simulation}`；不健康可503 |
| `POST /api/action` | 所有动作都使用同一个入口，靠 `action` 区分 | 成功 `{result: ...}`；错误 `{error: "..."}` |
| `GET /`、`GET /setup` | 当前主页、初始化页面 | 当前二者提供同一 HTML，不能假设已有前端路由系统 |

每个受保护请求带 `Authorization: Bearer <本地用户凭证>`。这不是 DeepSeek API Key，更不是 Agent 的身份令牌。保留用户凭证在当前页面内存；不要塞 URL、日志、localStorage 或构建产物。

POST 必须 `Content-Type: application/json`，请求体为 `{action, args}`。后端限制体积不超过262144字节。需求与后续讨论各支持20,000字符，输入框有字数计数。参数名必须匹配真实方法，额外参数也可能被拒绝。先检查 HTTP 状态再读取 `error`，不要只按200时的形状解包。

### 项目筛选和四种不同的 ID

| ID | 哪里读 | 哪里用 |
|---|---|---|
| 项目分组 ID | `state.projects[].id`、`selected_project` | `X-Hub-Project` 请求头；`project_id`；切换历史分组 |
| 工作流 ID | `state.workflows[].id` | `workflow_stop/resume/wake`、`backup_authorize` 的 `workflow_id` |
| 讨论 ID | `state.planning[].id` | `plan_chat.session_id`；必须同时使用该讨论当前 `revision` 批准计划 |
| 执行 ID | 各 provider 的 `runs[].id` | `codex_stop/antigravity_stop/deepseek_stop.run_id` |

另有 `tasks[].id` 任务 ID、`messages[].id` 消息 ID。**不能相互替代**，也不能假设项目分组和工作流恰好同 ID。

选择项目后对状态读取和动作统一携带 `X-Hub-Project: <分组ID>`。服务器只对用户的 `send/plan_chat/workflow_start/prepare` 自动补该项目 ID；其它操作仍必须显式传正确 ID，不是所有动作都被这个头隐式限定。

## 4. 状态快照：字段用于什么

| 顶层字段 | 用途及注意事项 |
|---|---|
| `agents[]` | 9个身份、显示模型、角色、status/active/heartbeat、手动或官方额度。角色可被项目覆盖，不把 Flash-3 永久锁定为测试角色 |
| `real_agents[]` | 已启用真实执行的身份；与“忙碌”“有额度”“已授权此项目”分别判断 |
| `projects[]`、`selected_project` | 项目分组选择；缺省可能是全部记录，不是自动选择最新项目 |
| `planning[]` | 讨论 history、state、revision、plan、pending、workflow_id、options、error |
| `workflows[]` | 项目 status/phase/report/progress、manager、参与者、调用上限、截止时间、steps、经理交接信息；旧记录无 manager 时默认 argon |
| `project` | 后端汇报的总体进度和说明；没有逐项等权计算成功的含义 |
| `tasks[]` | 任务台账、agent、title、status、progress、note；记录任务不等于已启动真实模型 |
| `messages[]` | sender、recipient、body、mode、status、attempts、时间和result。sender 必须可见，消息可能在暂停/额度/授权处等待 |
| `codex`、`antigravity` | config、remaining_runs、runs、events；运行记录供状态与高级调试使用 |
| `deepseek` | 同样有 config/runs/events/remaining_runs，另有 key_present、validation、reserved_cents、remaining_cents；绝不返回密钥 |
| `coordination` | stops 停止锁、wakeups 消息唤醒结果、reports 简报。held 的 note 应作为等待原因展示 |
| `quota_alerts[]` | 按窗口去重的当前额度状态；`body` 是 JSON字符串，`level` 0可用/1低于10%/2耗尽。恢复事件也会出现在消息和审计中，不能仅显示level>0 |
| `audit[]` | 审计轨迹，detail 通常是JSON字符串；默认折叠，不铺满首页 |
| `calls[]`、`budget_cents` | **旧版单次文本调用**，不是新的 DeepSeek 项目执行器预算；不要混为一个授权表单 |
| `simulation`、`time` | 模拟消费者是否开启、服务器时间；不要因此把真实模型显示成模拟 |

快照是有限窗口，不是完整历史分页接口：常见消息最多300条；provider通常最近30次执行/150个事件，选定项目时可能变为100条；审计和工作流也有限制。显示“最近记录”，不要伪造“已加载全部历史”或调用不存在的翻页接口。

### 不能混淆的状态

| 对象 | 常见状态 | 前端该怎么理解 |
|---|---|---|
| Agent | busy/idle/offline | 心跳与当前消费者状态；离线不等于额度耗尽 |
| Message | pending/delivered/acknowledged/completed、paused/failed/uncertain/cancelled等 | pending=尚待处理；acknowledged=已确认领取，**不是任务完成**；wakeups另有held/batched/queued/notice |
| Execution | queued/running/interrupting/waiting_quota/completed/failed/uncertain/interrupted/cancelled | uncertain=可能已经产生改动，不能显示“安全重试”或自动重发 |
| Workflow | active/paused/needs_attention/blocked/completed/stopped | paused要给恢复入口；停止锁与暂停不同；completed仍允许用户发验收后反馈 |
| Planning | draft/thinking/awaiting_approval/executing/error | awaiting_approval要显示版本与计划；只有用户明确确认最新版本才执行 |
| Report.risk | low/high/blocked/unknown | 执行者风险自评，**不等于成功状态或最终验收** |

未知状态保留原值和说明，不按成功处理。时间戳一般是Unix秒，显示时乘1000；费用是美元美分；remaining_runs是Hub授权回合数，不是token或订阅余额。CLI token统计可能是累计值，不能把每轮数字直接相加宣称总消耗。

## 5. 页面按钮与真实 action 对照

以下 POST 都发给 `/api/action`。完整参数见 `frontend-actions.json`，边界见对应源码。

| 用户界面 | action | 用途与关键参数 |
|---|---|---|
| 新建项目 | `project_create` | `{name}`；只创建分组/目录，不调用模型 |
| 私聊/群发 | `send` | `{recipient,body,mode:"queue"或"immediate",request_key}`；群发recipient为`*`；保存消息不等于授予任意执行权限 |
| 与Argon讨论 | `plan_chat` | `{body,options,confirmed:true}`，后续加`session_id`；**可能调用Argon，需讨论授权** |
| 重读已完成但解析失败的计划 | `plan_recover` | `{session_id}`；只重新校验保存的结果，不调用模型、不授权执行；失败的提供商调用不能用此操作重试 |
| 批准最新计划 | `plan_chat` | `{session_id,revision,body:"按计划执行"}`；由用户实际点击/输入确认，不能由模型文字触发 |
| 恢复暂停项目 | `workflow_resume` | `{workflow_id,message_id?}`；message_id只能是本项目待处理用户消息；不适用于stopped |
| 手动唤醒当前经理 | `workflow_wake` | `{workflow_id,note?}`；会消耗已授权模型额度；不是刷新按钮 |
| 停止项目 | `workflow_stop` | `{workflow_id}`；取消或请求停止未完成工作，不回滚文件 |
| 停单个/全部 | `agent_halt` | `{agent:"sol-1"或"*",reason}`；紧急停止锁；立即提供可用入口 |
| 解除停止锁 | `agent_resume` | `{agent}`；仅解除锁，不自动恢复原项目、重放旧任务 |
| 记录任务 | `assign` | `{agent,title}`；旧台账入口，**不能包装成“一键真实执行”** |
| 手动额度 | `quota` | `{agent,remaining:null或百分比,resets_at:null或Unix秒}`；明确标注手动输入 |
| 官方额度刷新 | `refresh_openai`、`refresh_antigravity` | 无参数；读取官方接口，不推理；不要每次状态轮询都再探测CLI |
| GPT/Google授权 | `codex_configure`、`antigravity_configure` | `{cwd,permission,max_runs,max_seconds,enabled,confirmed}`；会更新授权，禁止自动保存或默认勾选同意 |
| 单项开发任务 | `codex_submit`、`antigravity_submit` | `{agent,instruction,confirmed,task_id?,source_message_id?}`；沿用授权但需确认；消息必须属于该执行者且原文一致 |
| 停单项执行 | `codex_stop`、`antigravity_stop`、`deepseek_stop` | `{run_id}`；按实际provider分流，**不能把DeepSeek发给Antigravity** |
| DeepSeek填写密钥 | `deepseek_save_key` | `{api_key}`；本机加密保存，清空输入，不回显，不记录请求体 |
| DeepSeek连接验证 | `deepseek_validate` | 无参数；只读官方模型列表，不推理；模型不匹配时不能假装成功 |
| DeepSeek费用/工具授权 | `deepseek_configure_api` | 见下一节；独立于旧版单次文本调用 |
| 已有项目追加备用经理 | `backup_authorize` | `{workflow_id,confirmed:true}`；用户明确批准把DeepSeek加入项目及耗尽接管，暂停不因此解除 |

### 计划的 options 必须完整

`plan_chat.options` 目前要求这些键全部存在且不接受多余键：

```json
{
  "cwd": "<已存在的开发副本绝对路径>",
  "agents": ["sol-1", "sol-2", "flash-2", "flash-3"],
  "max_calls": 100,
  "expires_minutes": 1440,
  "max_parallel": 3,
  "max_seconds": 600,
  "reviewer": "flash-3",
  "auto_wake": true,
  "delegate_stop": false,
  "max_hops": 8,
  "max_messages": 100
}
```

这是接口形状示例，**不是建议前端自动替用户授权这些数字**。确认计划时传最新 revision；如果 options 或权限变了，要先更新计划，不能直接批准旧版本。当前初始讨论固定由Argon完成，不能仅改文字就声称已支持DeepSeek代替Argon讨论。

### DeepSeek执行授权参数

`deepseek_configure_api`：`cwd, permission, max_runs, max_seconds, budget_cents, input_rate, output_rate, max_requests, max_output, enabled, takeover, confirmed`；部分默认值见JSON索引。permission为workspace（文件工具，无命令）或full（允许本机命令，不是沙箱）。单价单位是**美元美分/百万tokens**。验证和费用确认分别展示；启用前必须官方模型验证通过。不得替用户填写真实密钥、勾选同意、提高预算或打开接管。

DeepSeek已加入并授权时，Argon可直接派普通任务，不必等待耗尽。它不是只能在接管时出现的“紧急按钮”。Argon不足时是否接管由后端判定，不能在前端根据百分比自行修改manager。

## 6. 哪些是Agent内部工具，不是用户面板按钮

`project_status/project_assign/project_complete/project_mailbox/project_set_role/project_cancel_task/project_return_manager/report_result` 需要当前有效执行的 `run_id` 和对应Agent身份。用户凭证不能冒充经理；前端不能找一个run_id就直接调用它们代替模型完成验收或交接。

`heartbeat/poll/ack/progress/project` 也属于Agent消费者/汇报流程，不要为了动画效果自动调用。面板显示应读取快照，不要替Agent领取消息、改进度或确认任务完成。

`workflow_start` 是已有的直接执行入口，但本次主流程继续使用“先讨论、后批准”的 `plan_chat`，不要绕开计划门。

## 7. 最小可用请求示例

只示范读取状态和准备发送消息。不要在页面载入时自动调用写动作：

```js
let userToken = ''; // 用户输入后仅保留在内存
let selectedProjectId = '';

async function hubRequest(path, body) {
  const headers = { Authorization: `Bearer ${userToken}` };
  if (selectedProjectId) headers['X-Hub-Project'] = selectedProjectId;
  if (body) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    method: body ? 'POST' : 'GET', headers,
    ...(body ? { body: JSON.stringify(body) } : {})
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

const snapshot = await hubRequest('/api/state'); // 状态对象本身

// 仅在用户点击发送后执行。若需重试同一条消息，复用相同request_key及原文。
async function sendUserMessage(recipient, body, requestKey) {
  const response = await hubRequest('/api/action', {
    action: 'send', args: { recipient, body, mode: 'queue', request_key: requestKey }
  });
  return response.result;
}
```

读取轮询可保留目前约1.5秒，避免请求重叠；后台页面可降低频率。GET失败保留最后一次状态并显示“连接中断/数据过期”，不能清空成“全部空闲”。POST超时不要自动重试执行、预算、计划批准或停止之外的其它动作；先核对快照和错误原因，用户操作防重复提交。

## 8. 前端运行环境的真实限制

- 当前静态路由是明确白名单，并非自动托管整个static目录。新增`/assets/*.js`、字体、图标或前端路由时必须规划真实托管方式；不能只生成文件就假设能访问。
- CSP为`default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'`。外部字体/CDN、内联脚本/事件/样式等可能被拒绝；不要为省事放宽CSP或移除认证。需要图片等资源时核对并明确最小改动。
- 保持同源优先。另开Vite端口直接请求8765会受Origin检查限制；开发服务器代理也要核对Origin/Host，不能通过允许任意Origin解决。
- 前端显示Agent文本用`textContent`或安全渲染。消息和Markdown是未信任内容，不能直接塞`innerHTML`。
- 优先用当前原生JS/CSS完成设计；如选择框架，先在计划中说明构建产物、静态路由与CSP如何兼容。运行成品不应依赖外网CDN。

## 9. 产品布局与视觉要求

目标是日常使用的项目控制台，既漂亮也能快速回答“谁在做什么、为什么等、下一步怎么办”。建议：

1. 顶部：项目切换、当前项目状态、当前经理、连接状态、紧急停止。经理来自workflow.manager，不写死Argon。
2. 主区域：左侧讨论/计划/当前经理消息，右侧任务看板与关键进展；预算、历史和原始执行日志进二级页或抽屉。
3. Agent区：紧凑卡片或列表，主显示当前任务短标题、busy/idle/等待原因；完整Prompt不直接放卡片。
4. 额度区：按提供商共享窗口展示余额/恢复时间/新鲜度，再标注受影响身份；不要给Sol-1和Sol-2复制成两份独立额度。Hub回合数、订阅额度、API费用分别显示。
5. 消息区：发送者、对象、状态、时间可见；默认短简报，完整历史/日志按需展开，避免同一结果重复占据屏幕。
6. 配置区：DeepSeek四步向导、权限和费用摘要清楚；默认不展示密钥。授权控件必须明确与保存普通偏好区分。

视觉可选沉稳深色或明亮中性色，先给一套连贯方案：明确字体层级、统一间距与圆角、克制强调色、正常/警告/错误对比明确。不要大面积渐变发光、几十个同权重卡片和满屏原始JSON。关注桌面主视图，也覆盖窄屏、键盘操作、焦点、对比度和长中文换行。

额度通知规则：低于10%、耗尽、恢复均通知，重复周期重新提醒。Argon已知适用额度至少20%通常只通知Argon；低、未知或当前经理DeepSeek时通知两方；仅当前经理处理合并事件。恢复充足后鼓励代理经理申请交回，后端等本轮结束后安全交接。前端只是显示，不抢做调度。**DeepSeek助理模式目前只是讨论过的方案，尚未实现，不要把它作为已存在的功能画成可用开关。**

## 10. 分工与共享契约

Argon先给页面结构、交互流程、API映射、文件归属、验收与分阶段计划，用户批准后执行。下面仅是建议，不固定角色：

| 工作 | 建议身份 | 文件/契约边界 |
|---|---|---|
| 视觉系统、布局、组件样式 | flash-2 | CSS、约定组件结构；不与客户端实现者同时改同一入口 |
| 请求客户端、状态归一化、核心交互 | sol-1 | 唯一请求适配层；明确哪些数据不做推断 |
| 对照真实后端、静态托管、契约/故障验证 | sol-2 | API差异说明、测试夹具；最少后端兼容改动单独提案 |
| 针对性浏览器验收 | flash-3 | 不重做实现；正常/异常状态、授权、窄屏与长文本 |
| 文档、状态文案、轻量复核 | DeepSeek（已授权时） | 不重复读取整仓库；不自行扩大API费用 |

入口HTML/组件结构由一个人负责，其他人通过约定接口集成；不要多个Agent同时改同一个大JS文件。可先约定`api client → store → view`与样式token，再并行做模块。不要让前端设计者猜后端，接口不符要报告差异并查询源码，不能靠假数据掩盖。

## 11. 验收与交付

在独立测试数据目录/端口（例如8766）验证，不复用正式data，不启动真实模型。模型、额度与工具响应用fixture，密钥测试用明确的测试字符串。浏览器测试不是只跑语法检查，也不是只看一张漂亮截图。

最低覆盖：

- 登录、项目切换、空项目；切换中没有串项目消息或过期请求覆盖新项目。
- 讨论中/计划待批准/计划报错；批准必须当前revision与明确用户动作；“继续”不能被前端擅自改写成“按计划执行”。
- busy、queued、waiting_quota、paused、stopped、blocked、uncertain、completed；每种状态有正确文案及下一步，暂停能恢复、停止锁不能自动解除。
- completed项目收到新反馈后能继续；同一消息不重复发送；当前经理为DeepSeek时页面仍正确。
- 密钥未填/验证失败/模型不匹配/保存授权/预算不足/恢复通知/双通知/经理交接等待。未授权时无付费请求。
- 断网、401/403、400、500、长任务名、长消息、大量近期记录、键盘与窄屏；无控制台错误、404静态资源或CSP阻断。
- 所有页面必须连接真实契约。fixture只用于测试，交付页面不得依赖伪造的在线状态、进度或额度。

交付包括：源码差异、启动/构建方式、页面截图、测试结果、未完成项、所需后端兼容改动与部署步骤。小改动只做相关检查与必要回归，避免每轮整仓扫描或完整验收。

最终由Argon给用户看实际页面和验证证据，再说明如何部署。检查者不能只凭“exit code 0”宣称视觉效果优秀或全部完成。
