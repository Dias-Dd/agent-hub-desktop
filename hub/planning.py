from .manager_identity import independent_reviewer
from .manager_identity import resolve as project_manager
"""User-only discussion gate. Plans are versioned; text confirmation is never read from model output."""
import hashlib
import json
import threading
import time
from .core import HubError,text,uid
from .workflows import proposal,validate_plan_report

class Planning:
    def __init__(self,hub,runtime,workflows):
        self.hub=hub;hub.planning=self;self.runtime=runtime;self.workflows=workflows;self.lock=threading.RLock()
        with hub.tx():
            hub.db.execute('CREATE TABLE IF NOT EXISTS planning_sessions(id TEXT PRIMARY KEY,body TEXT)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS discussion_prompt_context(run_id TEXT PRIMARY KEY,body TEXT)')

    def save(self,s):
        with self.hub.tx():self.hub.db.execute('INSERT OR REPLACE INTO planning_sessions VALUES(?,?)',(s['id'],json.dumps(s,ensure_ascii=False)))

    def get(self,ident):
        with self.hub.lock:row=self.hub.db.execute('SELECT body FROM planning_sessions WHERE id=?',(ident,)).fetchone()
        if not row:raise HubError('讨论不存在')
        return json.loads(row[0])

    def snapshot(self,actor):
        self.hub.require(actor,{'user'})
        with self.lock,self.hub.lock:return [json.loads(r[0]) for r in self.hub.db.execute("SELECT body FROM planning_sessions WHERE coalesce(json_extract(body,'$.state'),'')!='archived' ORDER BY rowid DESC LIMIT 10")]

    def options(self,value,manager=None):
        manager=manager or project_manager(self.hub)
        required={'preview_mode','cwd','agents','max_calls','expires_minutes','max_parallel','max_seconds','reviewer','auto_wake','delegate_stop','max_hops','max_messages'}
        if not isinstance(value,dict):raise HubError('讨论设置必须是对象')
        defaults={'preview_mode':'demo','cwd':self.workflows.runtime(manager).config()['cwd'],'agents':[r[0] for r in self.hub.db.execute("SELECT id FROM agents WHERE enabled=1 AND id!=?",(manager,))],'max_calls':0,'expires_minutes':4320,'max_parallel':8,'max_seconds':7200,'reviewer':None,'auto_wake':True,'delegate_stop':False,'max_hops':4,'max_messages':1000}
        value={k:value.get(k,defaults[k]) for k in required}
        value['auto_wake']=True  # Legacy field accepted, no longer a user-controlled gate.
        if value['preview_mode'] not in ('demo','skip'):raise HubError('演示模式无效')
        from pathlib import Path
        if not isinstance(value['cwd'],str) or not Path(value['cwd']).is_absolute() or not Path(value['cwd']).is_dir():raise HubError('项目目录必须已存在且为绝对路径')
        agents=value['agents']
        if isinstance(agents,list):agents=[a for a in agents if a!=manager];value['agents']=agents
        if not isinstance(agents,list) or len(set(agents))!=len(agents) or any(a not in self.workflows.runtime(a).models or a==manager for a in agents):raise HubError('参与者无效')
        for k,lo,hi in [('expires_minutes',1,43200),('max_parallel',1,128),('max_seconds',30,86400),('max_hops',1,32),('max_messages',1,10000)]:
            if type(value[k])!=int or not lo<=value[k]<=hi:raise HubError('运行设置无效：'+k)
        value['reviewer']=independent_reviewer(manager,agents,value.get('reviewer'))
        if any(type(value[k])!=bool for k in ('auto_wake','delegate_stop')):raise HubError('协作开关无效')
        return dict(value)

    def message(self,actor,body,options=None,session_id=None,revision=None,confirmed=False,project_id=None):
        self.hub.require(actor,{'user'});text(body,20000)
        with self.lock:
            s=self.get(session_id) if session_id else None
            if s and s.get('state')=='archived':
                project_id=project_id or s.get('project_id');s=None
            from .project_activity import require_available
            require_available(self.hub,project_id or (s or {}).get('project_id'))
            files_recreated=False
            if project_id and getattr(self.hub,'projects',None):files_recreated=self.hub.projects.ensure_ready(project_id)
            if s and project_id and s.get('project_id')!=project_id:raise HubError('讨论不属于当前项目')
            if body.strip()=='按计划执行' and not (s and s.get('design_id') and s['state']=='designing'):
                if not s:raise HubError('请先与项目经理讨论并等待计划')
                return self.approve(s,revision,options)
            if s and s.get('design_id') and s['state']=='designing':
                d=self.hub.designs.get(s['design_id'])
                if d['state']=='building':return self.hub.coordination.send(actor,project_manager(self.hub,record=s),body,mode='queue',project_id=s.get('project_id'))
                raise HubError('请在产品演示中选择修改范围并提交反馈，或确认设计后制作')
            if s and s['state']=='executing':
                return self.hub.coordination.send(actor,project_manager(self.hub,record=s),body,mode='queue',project_id=s.get('project_id'))
            if s and s.get('pending'):
                self.patrol();s=self.get(s['id'])
                if s.get('pending'):raise HubError('经理仍在回复，本轮完成后可以继续；消息未发送')
            if s and time.time()>s['expires']:
                s['expires']=time.time()+86400
                with self.hub.tx():self.hub.audit(actor,'plan.discussion_renewed',{'session':s['id'],'execution_authorized':False})
            if not s:
                manager_row=self.hub.db.execute('SELECT value FROM settings WHERE key=?',('project_manager:'+str(project_id),)).fetchone()
                manager=project_manager(self.hub,project_id)
                project_options=self.hub.projects.get(project_id)['options'] if project_id and getattr(self.hub,'projects',None) else {}
                s={'manager':manager,'id':uid(),'project_id':project_id,'created':time.time(),'expires':time.time()+86400,'state':'draft','revision':0,'turns':0,'history':[],'plan':None,'pending':None,'workflow_id':None,'options':self.options({**project_options,**(options or {})},manager)}
            elif options is not None:s['options']=self.options(options,project_manager(self.hub,record=s))
            mgr=project_manager(self.hub,record=s)
            s['options']['agents']=[a for a in s['options']['agents'] if a!=mgr]
            s['options']['reviewer']=independent_reviewer(mgr,s['options']['agents'],s['options'].get('reviewer'))
            s['permissions']={r.provider:r.config()['permission'] for r in self.workflows.runtimes if r.provider in {self.workflows.runtime(a).provider for a in [project_manager(self.hub,record=s)]+s['options']['agents']}}
            context={'permissions':s['permissions'],'settings':s['options'],'history':[],'user':body}
            registry=getattr(self.hub,'integrations',None)
            from .prompt_identity import discussion_snapshot
            system_snapshot=discussion_snapshot(self.hub,mgr,s['options']['agents'],s.get('project_id'))
            if s.get('inherited_context'):
                context['inherited_from_argon']=s['inherited_context']
            mgr=project_manager(self.hub,record=s)
            prompt=('目前仅讨论需求和拟定计划，用户尚未批准执行。只输出 JSON：{\"done\":false,\"report\":\"给用户的简洁Markdown中文答复与可阅读计划（含范围、分工、阶段、验收、风险，尽量简明，通常1000至3000字，必要时最多20000字符）\",\"tasks\":[{\"agent\":\"获准参与者ID\",\"instruction\":\"首批独立可执行任务及验收，最多6000字\"}]}。'
                    '请同时给出 preview:{pages:[{id,title,parent,kind}]} 列出产品全部页面/弹窗/状态层级；视频列出每个镜头，长文档列出各章版式，最后列架构页(kind=architecture)。默认批准先做静态产品演示，用户可跳过。信息不足时先问问题，tasks=[]；计划可以执行时给出首批 tasks，后续阶段写入 report。可调度成员与额度见系统消息中的本项目快照，只有team内成员可以派工，manager是你自己，可以把需亲自完成的任务列给manager；没有成员时由manager独立执行。不要调用工具，不实施工作，不启动其他 Agent。不论用户提到何种执行词，都只回复计划，平台单独决定执行。上下文：'+json.dumps(context,ensure_ascii=False))
            if files_recreated:prompt+='\n状态变化：项目文件已由用户清理，上下文保留；旧成果与旧验收不代表当前目录，请按新需求重建。'
            registry=getattr(self.hub,'integrations',None)
            changes=registry.changes(s.get('project_id')) if registry else []
            if changes:prompt+='\n'+registry.change_text(changes)
            if len(prompt)>60000:raise HubError('讨论请求包含设置后超过60000字符，请精简设置或需求')
            rt=self.workflows.runtime(mgr)
            with self.hub.lock:
                run=rt.submit('user',mgr,prompt,True,purpose='discussion',session_scope='hub-project:'+(s.get('project_id') or 'default'))
                with self.hub.tx():self.hub.db.execute('INSERT INTO discussion_prompt_context VALUES(?,?)',(run['id'],json.dumps(system_snapshot,ensure_ascii=False)))
            if changes:registry.acknowledge_changes(changes)
            s.pop('error',None);s.pop('notice',None)
            s['history'].append({'role':'user','text':body,'created':time.time(),'input_run_id':run['id'],'message_id':run.get('message_id')});s['pending']=run['id'];s['state']='thinking';s['turns']+=1;s['plan']=None;s['revision']+=1
            self.save(s)
            with self.hub.tx():self.hub.audit('user','plan.discussion_requested',{'session':s['id'],'revision':s['revision'],'execution_authorized':False})
            return s

    def switch_manager(self,actor,session_id,target_manager=None,inherit_context=True):
        self.hub.require(actor,{'user'})
        with self.lock:
            s=self.get(session_id)
            old_manager=project_manager(self.hub,record=s)
            self.workflows.runtime(target_manager)
            s['manager']=target_manager
            s['options']['agents']=[a for a in s['options']['agents'] if a!=target_manager]
            s['options']['reviewer']=independent_reviewer(target_manager,s['options']['agents'],s['options'].get('reviewer'))
            if s.get('project_id'):
                with self.hub.tx():self.hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('project_manager:'+s['project_id'],target_manager))
            if inherit_context:
                handover_package={
                    'previous_manager':old_manager,
                    'target_manager':target_manager,
                    'switched_at':time.time(),
                    'session_id':s['id'],
                    'project_id':s.get('project_id'),
                    'history':s.get('history',[]),
                    'plan':s.get('plan'),
                    'options':s.get('options')
                }
                s['inherited_context']=handover_package
            self.save(s)
            with self.hub.tx():
                self.hub.audit(actor,'plan.manager_switched',{'session':s['id'],'from':old_manager,'to':target_manager,'inherited_context':bool(inherit_context)})
            return {'switched':True,'session_id':s['id'],'manager':target_manager,'previous_manager':old_manager,'inherited_context':s.get('inherited_context')}

    def patrol(self):
        with self.lock:
            for s in self.snapshot('user'):
                if not s.get('pending'):continue
                with self.hub.lock:r=self.hub.db.execute('SELECT * FROM executions WHERE id=?',(s['pending'],)).fetchone()
                if not r or r['status'] in ('queued','running','interrupting','waiting_quota'):continue
                s['last_run']=r['id'];s['pending']=None;s.pop('error',None)
                mgr=project_manager(self.hub,record=s)
                try:
                    with self.hub.lock:
                        preempted=self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='manager_preemptions'").fetchone() and self.hub.db.execute('SELECT 1 FROM manager_preemptions WHERE run_id=?',(r['id'],)).fetchone()
                    if preempted and r['status']!='completed':
                        s.update(state='draft',notice='本轮已按用户请求中断，等待处理插入消息');self.save(s);continue
                    if r['status']!='completed':raise HubError(mgr+' 讨论未完成：'+str(r['result'])[:1200])
                    raw=(r['result'] or '').strip()
                    if raw.startswith('```'):raw=raw.split('\n',1)[1].rsplit('```',1)[0].strip()
                    try:
                        data=proposal(raw,allow_idle=True)
                        try:
                            outline=json.loads(raw).get('preview',{}).get('pages',[])
                            s['design_outline']=outline if isinstance(outline,list) else []
                        except (ValueError,AttributeError):s['design_outline']=[]
                        if data['done'] is not False:raise HubError('讨论不能直接声称已验收完成')
                    except (HubError,ValueError,TypeError):
                        # Preserve a readable answer; no structured plan means no execution.
                        if not raw:raise HubError('经理没有返回可显示内容')
                        s['plan']=None;s['state']='draft'
                        s['history'].append({'role':mgr,'text':raw,'revision':s['revision'],'run_id':r['id'],'created':r['finished'] or r['created']})
                        s['notice']='已保留经理答复；尚无可审批的结构化计划，可继续讨论。'
                        self.save(s);continue
                    if not any(m.get('run_id')==r['id'] for m in s['history']):
                        s['history'].append({'role':mgr,'text':data['report'],'revision':s['revision'],'run_id':r['id'],'created':r['finished'] or r['created']})
                    if data['tasks']:
                        if any(t['agent'] not in [mgr]+s['options']['agents'] for t in data['tasks']):raise HubError('计划包含未选择的 Agent')
                        s['plan']=data;s['digest']=hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest();s['state']='awaiting_approval'
                    else:s['state']='draft'
                except Exception as e:s['state']='error';s['error']=str(e)[:2000]
                self.save(s)

    def recover_result(self,actor,session_id):
        self.hub.require(actor,{'user'})
        with self.lock:
            s=self.get(session_id)
            if s['state']!='error' or s.get('pending') or not s.get('last_run'):raise HubError('仅可重读已结束但解析失败的讨论结果')
            with self.hub.lock:r=self.hub.db.execute('SELECT * FROM executions WHERE id=?',(s['last_run'],)).fetchone()
            if not r or r['status']!='completed' or r['agent']!=project_manager(self.hub,record=s) or r['purpose']!='discussion' or r['session_scope'] not in ('discussion:'+s['id'],'hub-project:'+(s.get('project_id') or 'default')):raise HubError('没有属于本讨论的已完成结果；不会启动模型重试')
            s.update(pending=r['id'],state='thinking');s.pop('error',None);self.save(s)
            self.patrol()
            with self.hub.tx():self.hub.audit(actor,'plan.result_reparsed',{'session':s['id'],'run_id':r['id'],'execution_authorized':False,'inference_started':False})
            return self.get(s['id'])

    def approve(self,s,revision,options):
        if s['state']=='executing':return s
        if s['pending'] or s['state']!='awaiting_approval' or not s['plan']:raise HubError('请等待 项目经理 提供可执行计划')
        if time.time()>s['expires']:raise HubError('计划讨论授权已到期，请重新讨论')
        if type(revision)!=int or revision!=s['revision']:raise HubError('计划版本已变化，请阅读最新版本再确认')
        manager=project_manager(self.hub,record=s)
        current_options,removed=self.workflows.launch_options(s['options'],manager)
        if options is not None:
            submitted,_=self.workflows.launch_options(options,manager)
            if self.options(submitted,manager)!=self.options(current_options,manager):raise HubError('运行设置已变化，请先发送给 项目经理 更新计划')
        invalid_tasks=[t['agent'] for t in s['plan'].get('tasks',[]) if t['agent'] not in [manager]+current_options['agents']]
        removed=list(dict.fromkeys(removed+invalid_tasks))
        s['options']=current_options
        if removed:s['roster_replan']={'unavailable':removed,'available':current_options['agents']};self.save(s)

        if any(r.config()['permission']!=s.get('permissions',{}).get(r.provider) for r in self.workflows.runtimes if r.provider in s.get('permissions',{})):raise HubError('访问权限已变化，请先让 项目经理 更新计划')
        if getattr(self.hub,'designs',None) and s['options'].get('preview_mode','demo')!='skip' and not s.get('design_approved'):
            return self.hub.designs.start('user',s['id'],revision,s.get('project_id'))
        if s.get('design_approved'):self.hub.designs.verify_baseline(s['design_approved'])
        key='plan:'+s['id']+':'+str(revision)+':'+s['digest']
        with self.hub.lock:old=self.hub.db.execute("SELECT body FROM workflows WHERE json_extract(body,'$.approval_key')=?",(key,)).fetchone()
        if old:w=json.loads(old[0])
        else:
            opts=dict(s['options']);opts.pop('preview_mode',None);seconds=opts.pop('max_seconds');cwd=opts.pop('cwd')
            providers={self.workflows.runtime(a).provider for a in [project_manager(self.hub,record=s)]+opts['agents']}
            for rt in self.workflows.runtimes:
                if rt.provider in providers:
                    cfg=rt.config()
                    if cfg['cwd']!=cwd or cfg['max_seconds']!=min(seconds,cfg.get('authorized_max_seconds',seconds)):
                        rt.configure('user',cwd,cfg['permission'],opts['max_calls'],seconds,True,True)
            requirement=s['history'][0]['text']+'\n用户已批准计划 v'+str(revision)+'：\n'+s['plan']['report']
            accepted_plan=json.loads(json.dumps(s['plan']))
            if s.get('design_approved'):
                from .prompt_identity import PRODUCT_POLICY
                baseline=s['design_approved'];reference='严格复现用户确认的设计 v'+str(baseline['version'])+'，基线目录 '+baseline['directory']+'；逐页核对布局、字体、颜色、间距与层级，视频/文档核对镜头与版式。禁止擅自重设计，差异须告知用户并先获确认。'+PRODUCT_POLICY
                requirement+='\n'+reference
                for task in accepted_plan['tasks']:
                    if len(task['instruction'])+len(reference)+1<=6000:task['instruction']+='\n'+reference
                # Reviewer selection and final checks belong to the manager.
            opts['agents']=[a for a in opts['agents'] if a!=project_manager(self.hub,record=s)]
            production=bool(s.get('design_approved'))
            if production:
                requirement+='\n正式产品实施阶段：演示设计已获确认。原计划中的静态演示步骤已完成，以下旧计划仅供需求参考，不是本轮交付终点。必须实现原需求中的真实功能、交互、计算/数据与必要后端，保留确认的外观。复制演示、校验哈希或仅交付静态页面不能作为整体完成。'
            replan=s.get('roster_replan')
            instruction=self.workflows.roster_instruction(replan['unavailable'],opts['agents']) if replan else None
            if production:
                instruction=('用户已确认最终设计，现开始真实产品开发。先读取 project_status(view="context")，原计划中的演示阶段已完成；按完整需求拟定实现任务并派工，完成真实交互、业务逻辑、必要后端与测试，严格保留设计。不能以复制演示或哈希一致认定完成。由你安排独立验收与浏览器验证，不由平台自动指定检查者。产品界面与演示说明层须分离，成品去掉演示编号与批注并适配系统DPI缩放；按本轮工作目录实施，不沿用演示目录。浏览器端到端用服务地址而非file://；exec服务会话不能替代desktop_launch桌面通道。复测后同步验收文档，移除已失效的环境限制结论。'+('\n'+instruction if instruction else ''))
            w=self.workflows.start('user',requirement,confirmed=True,manager=manager,approved_proposal=None if (replan or production) else accepted_plan,manager_instruction=instruction,approval_key=key,project_id=s.get('project_id'),**opts)
            if replan or production:
                w.update(approved_plan=accepted_plan,roster_replan=replan,delivery_stage='implementation' if production else 'execution')
                self.workflows.save(w)

        if s.get('design_approved'):
            w['design_baseline']=s['design_approved'];self.workflows.save(w)
        s['state']='executing';s['workflow_id']=w['id'];s['history'].append({'role':'user','text':'按计划执行','revision':revision,'created':time.time()});self.save(s)
        with self.hub.tx():self.hub.audit('user','plan.approved',{'session':s['id'],'revision':revision,'digest':s['digest'],'workflow':w['id']})
        return s
