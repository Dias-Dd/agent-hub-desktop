# CodeBuddy 独立 CLI 接入

- 本机发现 `%APPDATA%/npm/codebuddy.cmd`，官方版本2.171.0。
- 实测使用公开 `--acp` 完成 initialize / session/new，返回20项模型，包含hy3、step-5-preview、space-bunny；没有调用session/prompt。
- 原WorkBuddy连接切换为独立CodeBuddy。保留连接ID（内部兼容键workbuddy-local）、原2个Agent身份/名称/模型/档位、权限、授权grant与预算。公开界面显示CodeBuddy CLI。
- 不再发现或启动WorkBuddy客户端自带codebuddy-lite-wb.mjs，也不再自动拉起WorkBuddy GUI。缺少独立CLI时显示未安装，不回退精简入口。
- 原安装包候选及人工确认目录归档；默认目录由独立CLI公开菜单产生，不把旧客户端权限带入CodeBuddy。用户配置仅读取官方.codebuddy/models.json的模型元数据。
- 旧接入测试保留并标记旧配置。用户在全部测试确认后才会产生真实推理。
- 模型目录读取成功不证明免费资格或全部模型推理权限。没有读取登录存储、Cookie或私有客户端接口。

## 验证
独立可执行文件发现、ACP启动参数、连接迁移幂等、身份/预算不变、旧目录归档、保存配置不丢迁移标志、无需WorkBuddy GUI测试通过。长回复/短窗口/窄窗口、阅读位置、Agent面板回归通过；打包启动验证通过。
