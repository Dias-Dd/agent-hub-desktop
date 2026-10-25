"""MCP 2025-11-25 stdio transport, backed by the single HTTP authority.

No database is opened by this process. Give each client its own HUB_TOKEN.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

def schema(properties=None,required=None):
    return {'type':'object','properties':properties or {},'required':required or [],'additionalProperties':False}

S={'type':'string'}
N={'type':'number'}
TOOLS=[
    ('memory','当前项目经理跨项目长期记忆：read读取实时内容与revision；add追加、patch唯一原文替换、remove删除。写入必须带expected_revision，锁定或冲突会拒绝。target=user用户偏好或memory经验笔记。不保存密钥、临时状态或整段聊天。',schema({'operation':{'enum':['read','add','patch','remove']},'target':{'enum':['user','memory']},'content':S,'old_text':S,'expected_revision':{'type':'integer','minimum':0}},['operation'])),
    ('project_vm','虚拟机工具：status查连接/用request_id查异步结果；queued仅入队，exec/push/pull须查到completed，failed要读error，不能据queued宣称成功。exec在Session 0；GUI用desktop_launch(path相对exe路径,value可选参数)在登录桌面启动，再windows/screenshot验证；不得仅凭无窗口推断缺OpenGL。push/pull传cwd相对path。桌面优先windows→ui_tree→ui_invoke/ui_set_value；screenshot返回图片。key(key_codes虚拟键码组合)/mouse(x,y屏幕像素，button=0移动/1左键/2右键)仅作Hyper-V备用。操作后desktop_release释放120秒桌面租约；不要重复提交。',schema({'action':{'enum':['status','exec','push','pull','desktop_launch','desktop_status','desktop_release','screenshot','windows','ui_tree','ui_invoke','ui_set_value','key','mouse']},'request_id':S,'script':S,'path':S,'timeout_seconds':{'type':'integer','minimum':1,'maximum':3600},'window_handle':{'type':'integer'},'element_id':S,'value':S,'key_codes':{'type':'array','items':{'type':'integer'}},'x':{'type':'integer'},'y':{'type':'integer'},'button':{'type':'integer'}})),
    ('project_git','独立Git工作区：status查看成员分支；commit保存自己的修改；经理用integrate加agent合并成员提交。冲突保留现场，解决后commit，不自动覆盖。',schema({'action':{'enum':['status','commit','integrate']},'agent':S,'message':S})),
    ('browser_render','用独立浏览器渲染项目或已确认设计基线内的本地HTML，返回PNG图片及证据；只读检查也可用，不修改源码。不接受远程URL。',schema({'path':S,'width':{'type':'integer'},'height':{'type':'integer'}},['path'])),
    ('schedule_wake','设置持久定时提醒：自己或同项目成员，附言按队列投递。相同request_key更新原提醒；仅经理只剩关键成员时用wait_for_agent记录自动等待，项目仍active，quota_recovered检测该成员而非收件人；不绕过停止锁/人工暂停/项目授权。额度未知保持等待。',schema({'delay_seconds':N,'recipient':S,'note':S,'request_key':S,'interval_seconds':N,'condition':{'enum':['time','quota_recovered']},'wait_for_agent':S},['request_key'])),
    ('timer_list','查看本项目定时器、附言和暂缓原因。',schema()),
    ('timer_cancel','取消自己创建或当前经理管理的定时器。',schema({'timer_id':S},['timer_id'])),
    ('publish_artifact','给用户发送图片、静态网页或文件夹链接（kind=folder，用户点击在资源管理器打开）；path为本项目内路径。平台永久快照，网页禁脚本、外部服务和表单。',schema({'path':S,'kind':{'enum':['image','webpage','folder']},'caption':S},['path','kind'])),
    ('project_mailbox','读取当前项目的消息队列和发送者；项目经理 可查项目内所有对话，其他成员只查自己的。',schema({'before':N,'limit':{'type':'integer','minimum':1,'maximum':50}})),
    ('project_return_manager','当前代理经理申请在本轮结束后交回本项目原经理；平台核实额度、权限与单经理约束。',schema({'summary':S},['summary'])),
    ('project_set_role','当前项目经理调整项目内角色或指定检查者；不修改正在执行任务的范围。',schema({'agent':S,'role':S,'reviewer':{'type':'boolean'}},['agent','role'])),
    ('project_stop_task','当前项目经理停止本项目成员的单项任务；排队直接取消，运行中强停本地执行、撤销该轮工具权限并立即释放占位，可重新派工，无须成员确认。',schema({'task_id':S,'reason':S},['task_id','reason'])),
    ('project_cancel_task','当前项目经理取消当前项目中尚未启动的任务，保留审计。',schema({'task_id':S,'reason':S},['task_id','reason'])),
    ('project_schedule_wake','定时唤醒项目经理或安排后续倒计时唤醒；支持指定延迟秒数与原因。',schema({'delay_seconds':{'type':'integer','minimum':1,'maximum':86400},'reason':S},['delay_seconds'])),
    ('project_status','按需读取状态；view=context读取获批要求，events读取本轮完整消息，offset/limit分页，避免重复读取。',schema({'view':{'enum':['status','context','events']},'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':100,'maximum':4000}})),
    ('project_queue','经理管理本项目成员待执行队列：list查看内容，edit修改，reorder按item_ids排序（省略项顺延），delete取消并保留审计；interrupt直接打断当前轮次并优先处理instruction，需request_key。运行中输入不改写，使用interrupt。',schema({'agent':S,'operation':{'enum':['list','edit','reorder','delete','interrupt']},'item_id':S,'instruction':S,'item_ids':{'type':'array','items':S},'request_key':S,'reason':S},['agent'])),
    ('project_assign','当前项目经理给成员分派任务；request_key 用于防止重复安排。',schema({'agent':S,'instruction':S,'request_key':S,'kind':{'enum':['work','check']},'write_paths':{'type':'array','items':S},'read_paths':{'type':'array','items':S}},['agent','instruction','request_key'])),
    ('report_result','执行者主动提交简短结果；提供商结束确认后，队列发送并唤醒 项目经理。',schema({'summary':S,'risk':{'enum':['low','high','blocked','unknown']},'evidence':{'type':'array','items':S}},['summary','risk','evidence'])),
    ('project_complete','静态演示一次提交，无需confirmation。正式交付两步结案：首次返回测试核对问题；经理核对后再次调用并携带confirmation说明全面测试及虚拟机模拟输入的页面、全部按钮和逻辑验证结果或未测原因。由经理决定，平台不自动测试。演示无需文件夹链接；正式交付先publish_artifact(kind=folder)。其他成员在执行时不能结案。演示以design_review_ready为准。',schema({'summary':S,'evidence':{'type':'array','items':S},'confirmation':{'type':'object','properties':{'comprehensive_tests':S,'vm_ui_tests':S},'required':['comprehensive_tests','vm_ui_tests']}},['summary','evidence'])),
    ('agent_halt','紧急止损：仅已获用户项目委托的 argon/astra/deepseek 可停止同项目单个参与者。不能全局停止或恢复。',schema({'agent':S,'reason':S},['agent','reason'])),
    ('snapshot','读取 Agent 忙闲、任务、自己的消息和获准可见的额度。',schema()),
    ('send','私聊或群发；普通补充信息用queue。immediate会停止接收方当前轮次并优先投递，仅用于确需抢占；原任务不视为已完成。',schema({'recipient':S,'body':S,'mode':{'enum':['immediate','queue']},'request_key':S},['recipient','body'])),
    ('heartbeat','上报自己的 busy/idle 心跳，活跃任务完成后才可 idle。',schema({'status':{'enum':['idle','busy']}},['status'])),
    ('poll','领取下一条消息；先心跳 idle。单个身份只运行一个消费者。',schema()),
    ('ack','确认或完成自己领取的消息。',schema({'message_id':S,'complete':{'type':'boolean'},'result':S},['message_id'])),
    ('assign','仅项目经理/用户可分配任务并写入唤醒消息。',schema({'agent':S,'title':S},['agent','title'])),
    ('progress','仅任务执行者可上报任务进度。',schema({'task_id':S,'progress':{'type':'number','minimum':0,'maximum':100},'note':S,'status':{'enum':['working','blocked','done']}},['task_id','progress','note'])),
    ('project','当前项目经理上报总体进度与简短依据，更新用户面板；有实质变化时调用，不按调用次数估算。',schema({'progress':{'type':'number','minimum':0,'maximum':100},'note':S},['progress','note'])),
]

def call(name,args):
    base=os.environ.get('HUB_URL','http://127.0.0.1:8765')
    parsed=urllib.parse.urlsplit(base)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.path not in ('','/') or parsed.username or parsed.query or parsed.fragment:
        raise ValueError('HUB_URL must be a loopback HTTP origin')
    if name in ('memory','project_vm','project','schedule_wake','timer_list','timer_cancel','browser_render','publish_artifact','project_git','project_status','project_assign','report_result','project_complete','project_mailbox','project_set_role','project_cancel_task','project_stop_task','project_queue','project_return_manager','project_schedule_wake'):
        run_id=os.environ.get('HUB_RUN_ID')
        if not run_id:raise ValueError('tool requires a Hub-owned active execution')
        args={**args,'run_id':run_id}
    req=urllib.request.Request(base.rstrip('/')+'/api/action',data=json.dumps({'action':name,'args':args},allow_nan=False).encode(),headers={'Authorization':'Bearer '+os.environ.get('HUB_TOKEN',''),'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=45 if name=='browser_render' else 10) as response:return json.load(response)['result']
    except urllib.error.HTTPError as e:
        raise ValueError(json.load(e).get('error','hub request rejected')) from None

class Protocol:
    def __init__(self):self.initialized=False;self.ready=False
    def handle(self,msg):
        ident=msg.get('id');method=msg.get('method');params=msg.get('params',{})
        if method=='notifications/initialized':
            self.ready=self.initialized
            return None
        if ident is None:return None
        def result(value):return {'jsonrpc':'2.0','id':ident,'result':value}
        def error(code,message):return {'jsonrpc':'2.0','id':ident,'error':{'code':code,'message':message}}
        if msg.get('jsonrpc')!='2.0' or not isinstance(params,dict):return error(-32600,'invalid request')
        if method=='initialize':
            self.initialized=True
            return result({'protocolVersion':params.get('protocolVersion') if params.get('protocolVersion') in ('2024-11-05','2025-03-26','2025-06-18','2025-11-25') else '2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'agent-message-hub','version':'0.2.1'},'instructions':'身份由 HUB_TOKEN 确定，不能用参数冒充；真实模型审批不通过 MCP 开放。'})
        if method=='ping':return result({})
        if not self.ready:return error(-32000,'initialize and notifications/initialized required')
        allowed=json.loads(os.environ['HUB_TOOL_ALLOWLIST']) if os.environ.get('HUB_TOOL_ALLOWLIST') else None
        if method=='tools/list':return result({'tools':[{'name':n,'description':d,'inputSchema':s} for n,d,s in TOOLS if (allowed is None or n in allowed) and (allowed is not None or not os.environ.get('HUB_RUN_ID') or n in ({'memory','project_vm','schedule_wake','timer_list','timer_cancel','browser_render','publish_artifact','send','report_result','project_git','project_status','project_assign','project_complete','project','project_mailbox','project_set_role','project_cancel_task','project_stop_task','project_queue','project_schedule_wake','project_return_manager'} if os.environ.get('HUB_IS_MANAGER')=='1' else {'project_vm','send','project_git','report_result','project_status','project_mailbox','schedule_wake','timer_list','timer_cancel','browser_render','publish_artifact'}))]})
        if method=='tools/call':
            try:
                name=params.get('name');args=params.get('arguments',{})
                if allowed is not None and name not in allowed:raise ValueError('tool is not authorized for this turn')
                spec=next((s for n,_,s in TOOLS if n==name),None)
                if spec is None or not isinstance(args,dict):raise ValueError('unknown tool or invalid arguments')
                if set(args)-set(spec['properties']) or set(spec['required'])-set(args):raise ValueError('invalid arguments')
                value=call(name,args)
                image=value.pop('image_data',None) if name in ('browser_render','project_vm') and isinstance(value,dict) else None
                content=[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]
                if image:content.append({'type':'image','data':image,'mimeType':'image/png'})
                return result({'content':content,'isError':False})
            except Exception as e:return result({'content':[{'type':'text','text':str(e)[:500]}],'isError':True})
        return error(-32601,'method not found')

def main():
    if hasattr(sys.stdin,'reconfigure'):sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8')
    protocol=Protocol()
    for line in sys.stdin:
        try:
            if len(line)>65536:raise ValueError('request too large')
            msg=json.loads(line)
            if not isinstance(msg,dict):raise ValueError('object required')
            response=protocol.handle(msg)
        except Exception:response={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'parse error'}}
        if response is not None:print(json.dumps(response,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
