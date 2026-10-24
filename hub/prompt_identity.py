"""Resolve the manager for this project/turn without rewriting persistent roles."""
import json
from .manager_identity import resolve as project_manager

GIT_OVERVIEW='获批正式制作采用成员独立Git worktree：成员提交，经理用project_git查看并集成后测试；冲突保留处理，失败文件保留。虚拟机成果须pull回自己的工作区再提交，不自动同步。本轮仅讨论，不执行上述操作。'

PRODUCT_POLICY='区分产品界面与演示说明层：成品保留获批布局和真实功能，去掉演示编号、批注、说明栏、画布尺寸及演示专用禁用态；产品自身的图示、编号和危险操作确认保留，不机械复制演示CSS。适配高分屏，按逻辑尺寸和系统DPI布局；验证100%/125%/150%/200%缩放及小窗口，字体清晰、按钮可达、不裁切，桌面程序跨屏后重新核对。向成员传达这些要求。验收必须列出全部可操作按钮、菜单、弹窗及关键状态，逐项用真实点击/键盘验证正反路径；HTTP测试、DOM桩和静态截图不能替代逐按钮测试。先终止被测产品旧实例，核对本次交付文件哈希/版本、desktop_launch返回的executable/sha256/pid及existing_instances，再冷启动该构建测试，不能用旧进程或仅凭同名路径代验；启动失败应修复并复测，未完成项如实报告。报告实际已测与未测，复测结论同步到交付文档。'

FOLDER_POLICY='可用publish_artifact(kind="folder",path="项目内相对目录",caption="说明")向用户发送点击后在资源管理器打开的文件夹链接，不用file://链接。静态演示一次调用project_complete即可发布审阅入口，无需二次确认或文件夹链接；正式制作结案前必须先发送本轮交付目录链接，再调用project_complete；不用等待用户点击。仅正式交付的project_complete首次返回测试核对问题，再次携带confirmation说明全面测试和虚拟机模拟输入验证结果或未测原因，由经理确认完成，平台不自动测试。'
VM_POLICY=PRODUCT_POLICY+FOLDER_POLICY+'若你是当前经理，可用project_queue查看并编辑成员待执行队列、调整顺序或删除；interrupt直接中断当前轮次并优先处理新内容，原轮次不算成功。'+'可用 project_vm 使用已连接的Hyper-V虚拟机，已配置管理员命令通道；缺少开发环境、SDK或依赖时可自行在虚拟机内安装并验证，实际权限以返回结果为准：status查连接及command_elevated，exec运行PowerShell（异步编号用status查询），push/pull传文件。宿主与虚拟机目录分开；可在虚拟机安装依赖、编译和测试，管理员权限以command_elevated/结果elevated为准，无需重复runas；未知先实测，不能将普通宿主命令误当虚拟机命令。重连中勿反复exec，继续其它工作或设定时提醒后结束本轮；断线时结果未知的命令先核查现场，不盲目重放。exec在服务会话运行，不用于GUI、剪贴板或截图；GUI用desktop_launch(path=相对exe路径)在交互桌面启动，再用windows/ui_tree/screenshot；启动失败须读stderr，不能仅凭无窗口推断缺图形支持，鼠标坐标采用最新截图物理像素，分辨率或会话变化后重新截图，不盲用旧UIA边界。不搬运模型凭据。Hub的project_vm走Hyper-V PowerShell Direct；项目产物自己的VM服务必须查其源码，不能混称本机通道或凭空要求另填凭据。'

def vm_context(hub):
 from .vm_bridge import VmBridge
 try:
  state=VmBridge(hub.directory).status()
  label='已连接' if state.get('connected') else '未连接'
  elevated=state.get('command_elevated')
  return VM_POLICY+'当前虚拟机：'+label+'；命令管理员权限：'+('已确认' if elevated is True else '未提升' if elevated is False else '待核实')+'。'
 except (AttributeError,OSError,ValueError):return VM_POLICY

def identity(hub,run,project=None):
 role=hub.agent(run['agent'])['role']
 if run.get('purpose')=='discussion':return {'manager':run['agent'],'role':'项目经理'}
 project=project or {};manager=project.get('manager')
 scope=run.get('session_scope') or ''
 if not manager and scope.startswith('hub-project:'):
  ident=scope[len('hub-project:'):]
  with hub.lock:
   row=hub.db.execute('SELECT value FROM settings WHERE key=?',('project_manager:'+ident,)).fetchone()
   if row:manager=row[0]
   elif hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='workflows'").fetchone():
    row=hub.db.execute("SELECT body FROM workflows WHERE json_extract(body,'$.project_id')=? ORDER BY rowid DESC LIMIT 1",(ident,)).fetchone()
    if row:project=json.loads(row[0]);manager=project.get('manager')
 if not manager and project:manager=project_manager(hub,record=project)
 if manager==run['agent']:role='项目经理'
 else:role=project.get('roles',{}).get(run['agent'],role)
 return {'manager':manager,'role':role}


def discussion_snapshot(hub,manager,agents,project_id=None):
 registry=getattr(hub,'integrations',None)
 allowed=[a for a in dict.fromkeys(agents) if a!=manager]
 if registry:
  snapshot=registry.discussion_team(manager,allowed,project_id)
  snapshot['quota']=registry.discussion_resources([manager]+allowed)
  return snapshot
 rows=[]
 for agent in [manager]+allowed:
  runtime=hub.workflows.runtime(agent);record=hub.agent(agent)
  efforts=runtime.efforts() if hasattr(runtime,'efforts') else {}
  rows.append({'agent':agent,'name':agent,'model':runtime.models[agent],'platform':runtime.title,'effort':efforts.get(agent,'default'),'role':'项目经理' if agent==manager else record['role'],'ready':runtime.config()['enabled']})
 return {'manager':rows[0],'team':rows[1:],'quota':{'accounts':[],'unknown':True}}

def discussion_system(hub,run):
 if run.get('purpose')!='discussion':return ''
 snapshot=None
 with hub.lock:
  if hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='discussion_prompt_context'").fetchone():
   row=hub.db.execute('SELECT body FROM discussion_prompt_context WHERE run_id=?',(run['id'],)).fetchone()
   if row:snapshot=json.loads(row[0])
 if snapshot is None:
  # A queued discussion created by an older version may still contain its scope.
  try:
   legacy=json.JSONDecoder().raw_decode(run['prompt'].split('上下文：',1)[1])[0]
   snapshot=discussion_snapshot(hub,run['agent'],legacy['settings']['agents'])
   if legacy.get('quota'):snapshot['quota']=legacy['quota']
  except (KeyError,IndexError,ValueError):return GIT_OVERVIEW+vm_context(hub)+'本轮未附项目成员快照，不据全局名单推断派工权限。'
 registry=getattr(hub,'integrations',None)
 if registry and snapshot is not None:
  # Keep this turn's allowed roster, but don't send stale quota availability
  # merely because a discussion waited in the queue before provider startup.
  scope=run.get('session_scope') or ''
  project_id=scope.removeprefix('hub-project:') if scope.startswith('hub-project:') else None
  snapshot=discussion_snapshot(hub,run['agent'],[a['agent'] for a in snapshot.get('team',[])],project_id)
  with hub.tx():
   if hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='discussion_prompt_context'").fetchone():hub.db.execute('UPDATE discussion_prompt_context SET body=? WHERE run_id=?',(json.dumps(snapshot,ensure_ascii=False),run['id']))
 return GIT_OVERVIEW+vm_context(hub)+'本项目成员及额度（仅team可派工，ready=false当前不可用，quota_exhausted=true额度耗尽须避开，恢复时间未知不能自行假定恢复，unknown不代表无限）：'+json.dumps(snapshot,ensure_ascii=False)
