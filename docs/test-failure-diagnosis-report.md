# 本轮14个Agent接入测试失败排查

- 7个真实回复通过。
- 4个Antigravity失败：AntigravityStream构造函数错误地调用self.hub，流对象并不持有数据库。已把actual_input持久化移回运行时；新增直接实例化真实流类的回归测试，替身只在子进程边界，能够捕获原有错误。
- 1个OpenCode失败：官方ACP返回Rate limit exceeded。归类为“暂时限流”，没有证据认定是并发超限、账号无权限或模型不可用。
- 2个WorkBuddy失败：对应子进程CLI日志含刷新401和Authentication required /login。GUI登录不能证明CLI已获授权。本轮没有确认Step/Hy3推理权限，也没有改用私有客户端身份。

修复：CLI结构化最终错误和stderr不再丢弃；读stderr有界且去敏。WorkBuddy退出0但无最终结果时，只读取当前子进程PID匹配且本轮更新的日志中的固定登录错误指纹，返回固定提示，不采集登录文件、Token、Cookie或原日志内容。卡片区分限流、额度不足、登录授权和接入程序错误。原始执行记录保留，不自动重试、不新发模型调用。

新版本仍需要通过官方CLI完成WorkBuddy登录后由用户手动重测；Antigravity修复通过模拟子进程回归，尚未重新消耗真实账号额度验证。
