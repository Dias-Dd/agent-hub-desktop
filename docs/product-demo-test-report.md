# 产品演示流程测试报告（2026-10-19）

## 备份
编码前完整复制 Hub 约6.09GB源码、项目产物和运行数据，并保存桌面运行数据、EXE与原源码ZIP。位置：`outputs/hub-full-backup-20261019-220846`。两个运行数据库另用 SQLite backup 生成一致性副本。仅运行中的 service.lock/supervisor.lock 三个临时锁文件未复制；详情见该目录 backup-manifest.json。备份含本机凭证，不用于发布。

## 已通过

- test_designs.py：11项，覆盖讨论→演示→经理提交→用户确认→原产品计划、版本隔离、旧版审批、显式跳过、页面清单/层级/路径/架构页、基线篡改、跨项目、重启持久化、长反馈、HTTP预览与鉴权、讨论到期续期、普通聊天不得重开已发布演示。
- test_design_browser.py：真实 Edge 在1440×900、1024×600、600×800检查层级导航、静态sandbox预览、框选坐标、局部/整页/整体反馈、确认版本、确认按钮可达与滚动路径；均通过。
- test_nine_deepseek.py：6项通过；test_harness.py：22项通过。
- test_logical_recovery.py：13项通过；test_agent_efforts.py：11项通过。
- 必须的 UI 回归 test_manager_layout.py（三种尺寸）、test_reading_browser.py、test_nine_browser.py 通过；聊天顺序/底部跟随 test_chat_chronology.py 通过。
- JavaScript语法检查、Python编译检查、桌面程序打包通过。
- 工作台8765与桌面8766实际健康检查通过；设计API已加载，原项目保留，未自动重启历史任务。

## 验证范围
流程测试用模拟提供商返回结果及本地真实 HTTP/浏览器，不产生付费模型调用。本轮没有让真实模型另做一个完整产品，也没有自动证明任意需求的页面清单完全穷尽或最终成品像素一致。平台已把设计冻结版本、用户确认、逐页视觉核对和独立检查接入实际制作流程；最终成品仍需实际渲染证据。

预览展示时真实脚本、网络、表单及业务按钮不执行，产品逻辑意见作为批注交给经理安排下一版；视频/文档演示分别为故事板及章节版式，而非已生成最终视频或全文。
