# 2026-10-20 额度与实时回复验证

专项回归共 82 项通过：live 10、manager_layout 1、reading_browser 1、nine_browser 1、integrations 21、harness 26、automation 22。浏览器覆盖 1440×900、1024×600、600×800；验证额度分组、公开回复增量、摘要、选中与草稿保留、项目切换、未结束不允许批准。HTTP 验证认证、跨项目拒绝与提供商结束前可见。模型均为模拟，无付费推理。

全量旧测试发现 344 项中 10 failures、132 errors，未宣称全部通过。大量旧夹具仍使用 flash-1/opus 等默认身份，与目前默认 DeepSeek 身份不兼容；也包含废弃 setup_save 等页面断言。另有旧浏览器夹具含正在运行的经理但没有配置 SSE 服务，触发夹具缺失 hub 属性。该结果保留为历史测试债务，没有为使旧断言通过而恢复已移除的产品行为。

桌面构建和启动烟雾测试结果见交付说明；本报告不代表已调用用户真实模型验证。

桌面构建通过；独立烟雾启动退出码 0，ok=true、assets=10、simulation=false、native_available=true。三个交付 EXE 已同步。
