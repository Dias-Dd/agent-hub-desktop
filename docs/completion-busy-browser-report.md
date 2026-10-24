# 唯一完成门槛与截图诊断

2026-10-21。本次按用户最新指示覆盖上一版“提交时自动强停仍运行成员”的行为。

完成条件：本项目非经理 Agent 的任务仍为 running/interrupting 时，project_complete 返回明确忙碌清单，工作流保持 active，成员不被自动停止。经理可等待或显式使用既有 project_stop_task；经理自己的执行不拦截。queued/waiting_quota/未启动、失败、取消、检查风险/覆盖和未读消息不作为额外提交门槛。检查与剩余队列取消和 worker 启动共用同一个锁，防止检查后队列突然启动。project_status 会返回这个唯一 blocker。

演示：沿用冻结、版本保存、发布错误显示与旧版完成记录恢复。规划 arch / 产物 architecture 不再拦截；v1、v2 保留。截图服务不是演示发布的前置条件。

browser_render：此前 HTTP 500 被 Handler 的通用错误包装，未保留当时原始异常，不能据此断言沙箱限制或推断确切根因。现新增 Automation 级异常诊断，返回实际异常类型、脱敏信息和诊断编号，audit 保存对应堆栈位置；不输出密钥和 Token。

验证：
- completion_blockers 5：仅 running/interrupting 的非经理成员拦截，经理自身与所有其它状态通过。
- manager_completion_authority 1 / demo_publication_completion 5：运行成员不被自动强停；结束后即使异常结果也可由经理确认；取消排队并发布审阅，v2 和历史版本可读。
- manager_force_stop_patrol 10、manager_owned_review 4、browser_routes 46、browser_diagnostics 2、automation 22、manager_input 8、browser_render 6 均通过，合计 109 项。
- 源码与冻结 EXE 的 --browser-smoke-test 除 DevTools 基础截图外，现在实际调用独立临时服务的 HTTP browser_render -> Automation -> 渲染 -> 产物保存全流程；返回 900×600 PNG，artifact_saved=true。临时测试不连接模型、不改生产项目授权或执行状态。
- 当前真实 draft-2/panel-roll.html 在新渲染流程成功返回 1440×900 图像，SHA256 7af3dbb17b8a70ae7efc26594c73acac5344b8ce0b749125efb95a67d3682624。没有把截图失败当作页面问题，也没有声称已目视验收图像。

新版 EXE 和源码包更新后，从系统托盘退出并重开加载新后端；本次不主动重启或唤醒项目经理。
