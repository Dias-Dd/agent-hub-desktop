from .manager_identity import independent_reviewer
from .manager_identity import resolve as project_manager
"""Durable bounded project authorization; models propose, controller dispatches."""
import json
from datetime import datetime,timezone,timedelta
import threading
import time
from .core import HubError, text, uid, number
from .manager_input import clip,POLICY,ROUTINE_TARGET

ACTIVE={'queued','running','interrupting','waiting_quota'}

def validate_plan_report(value):
    if not isinstance(value,str) or not value.strip():raise HubError('计划说明为空或不是文本')
    if len(value)>20000:raise HubError('计划说明为 '+str(len(value))+' 字符，超过 20000 字符上限')
    return value

def proposal(raw,allow_idle=False):
    value=raw.strip()
    if value.startswith('```'):
        value=value.split('\n',1)[1].rsplit('```',1)[0].strip()
    from .plan_response import decode
    try:data,_=decode(value)
    except (ValueError,TypeError):raise HubError('项目经理未返回有效 JSON；保留原始输出供检查，不自动重试') from None
    if not isinstance(data,dict):raise HubError('项目经理分工格式不正确')
    if not isinstance(data.get('done'),bool) or not isinstance(data.get('tasks'),list):raise HubError('缺少 done/tasks')
    data={k:data.get(k) for k in ('done','report','tasks')}
    data['tasks']=[{k:t.get(k) for k in ('agent','instruction')} if isinstance(t,dict) else t for t in data['tasks']]
    validate_plan_report(data.get('report'))
    if data['done'] and data['tasks']:raise HubError('验收完成不能同时安排新任务')
    if not allow_idle and not data['done'] and not data['tasks']:raise HubError('未完成但没有可执行分工，请检查阻塞')
    for index,task in enumerate(data['tasks'],1):
        if not isinstance(task,dict) or not {'agent','instruction'}<=set(task):raise HubError('子任务格式不正确')
        instruction=task.get('instruction')
        if not isinstance(instruction,str) or not instruction.strip():raise HubError('第 '+str(index)+' 项任务说明不能为空')
        if len(instruction)>6000:raise HubError('第 '+str(index)+' 项任务说明为 '+str(len(instruction))+' 字，超过 6000 字上限，请缩短该项任务')
    return data

class Workflows:
    def __init__(self,hub,runtimes):
        self.hub=hub;self.runtimes=runtimes;self.lock=threading.RLock();hub.workflows=self
        with hub.tx():
            for table in ('tasks','messages'):
                if 'project_id' not in {r[1] for r in hub.db.execute('PRAGMA table_info('+table+')')}:hub.db.execute('ALTER TABLE '+table+' ADD COLUMN project_id TEXT')
            hub.db.execute('CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY,body TEXT)')
            hub.db.execute("CREATE INDEX IF NOT EXISTS workflows_by_status ON workflows(json_extract(body,'$.status'))")
            hub.db.execute("CREATE INDEX IF NOT EXISTS workflows_by_project ON workflows(json_extract(body,'$.project_id'))")
            hub.db.execute('CREATE TABLE IF NOT EXISTS workflow_events(id TEXT PRIMARY KEY,workflow TEXT,source_run TEXT,body TEXT,status TEXT,manager_task TEXT,created REAL)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS project_dispatches(workflow TEXT,request_key TEXT,task TEXT,PRIMARY KEY(workflow,request_key))')
            hub.db.execute('CREATE TABLE IF NOT EXISTS workflow_resources(task TEXT PRIMARY KEY,kind TEXT,paths TEXT)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS workflow_resource_dependencies(task TEXT,depends_on TEXT,PRIMARY KEY(task,depends_on))')
            hub.db.execute('CREATE TABLE IF NOT EXISTS workflow_stop_requests(task TEXT PRIMARY KEY,workflow TEXT,run TEXT,actor TEXT,reason TEXT,created REAL)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS workflow_dependencies(task TEXT PRIMARY KEY,depends_on TEXT)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS model_reports(run TEXT PRIMARY KEY,body TEXT)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS workflow_steps(workflow TEXT,seq INTEGER,task TEXT UNIQUE,agent TEXT,kind TEXT,PRIMARY KEY(workflow,seq))')
            if not hub.db.execute("SELECT 1 FROM settings WHERE key='manager_patrol'").fetchone():
                hub.db.execute("INSERT INTO settings VALUES('manager_patrol',?)",(json.dumps({'enabled':True,'interval_minutes':10}),))
                for row in hub.db.execute('SELECT body FROM workflows').fetchall():
                    w=json.loads(row[0]);w['next_inspection']=time.time()+600
                    w['inspection_policy']={'manager_interval_seconds':600,'enabled':True}
                    hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))


        from .message_sources import repair_platform_sources
        repair_platform_sources(hub)
        from .git_workspaces import GitWorkspaces
        self.git=GitWorkspaces(self)
        # Upgrade existing queues before any provider worker starts. Earlier tasks
        # precede later tasks, preventing backfill cycles across legacy jobs.
        from .task_resources import register
        with hub.tx():
            for row in hub.db.execute('SELECT body FROM workflows').fetchall():
                w=json.loads(row[0])
                if w.get('status') not in ('active','paused','blocked','needs_attention'):continue
                reviewer=independent_reviewer(self.manager(w),w.get('agents',[]),w.get('reviewer'))
                if w.get('reviewer')!=reviewer:
                    w['reviewer']=reviewer;hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
                for step in self.steps(w['id']):
                    kind=step['kind']
                    if kind=='message' and hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='wakeups'").fetchone():
                        source=hub.db.execute('SELECT m.sender,m.mode,a.note FROM wakeups a JOIN messages m ON m.id=a.message WHERE a.task=?',(step['task'],)).fetchone()
                        if source and source['mode']=='immediate':
                            hub.db.execute('DELETE FROM workflow_resource_dependencies WHERE task=?',(step['task'],))
                            continue
                        if source and (source['sender']==self.manager(w) or source['note']=='定时器在现有授权内投递'):
                            kind='work'
                            hub.db.execute("UPDATE executions SET purpose='task' WHERE task_id=? AND purpose='question' AND status IN ('queued','waiting_quota')",(step['task'],))
                    if hub.db.execute('SELECT 1 FROM project_queue_positions WHERE item_id=?',(step['task'],)).fetchone():continue
                    if kind not in ('work','check') or step['status'] in ('completed','cancelled','failed','interrupted','uncertain'):continue
                    saved=hub.db.execute('SELECT kind,paths FROM workflow_resources WHERE task=?',(step['task'],)).fetchone()
                    if saved and step['status']!='queued':continue
                    title=hub.db.execute('SELECT title FROM tasks WHERE id=?',(step['task'],)).fetchone()
                    if title:
                        explicit=json.loads(saved['paths']) if saved and step['kind']!='message' else None
                        hub.db.execute('DELETE FROM workflow_resource_dependencies WHERE task=?',(step['task'],))
                        waiting=register(self,w,step['task'],step['agent'],kind,title[0],explicit)
                        if step['status']=='queued':hub.db.execute("UPDATE tasks SET note=? WHERE id=?",('等待相关文件的在途任务结束：'+', '.join(waiting) if waiting else '',step['task']))

    def manager(self,w):return project_manager(self.hub,record=w)

    def runtime(self,agent):
        for runtime in self.runtimes:
            if agent in runtime.models:return runtime
        raise HubError('该身份没有真实任务执行器：'+str(agent))

    def launch_options(self,options,manager=None):
        manager=manager or project_manager(self.hub)
        """Refresh an approved roster without adding identities or substituting models."""
        result=dict(options);available=[];removed=[]
        registry=getattr(self.hub,'integrations',None)
        profiles={a['id']:a for a in registry.rows('agent_profiles')} if registry else None
        for agent in options.get('agents',[]):
            if agent==manager:continue
            try:
                if profiles is not None and not profiles.get(agent,{}).get('enabled'):raise HubError('已停用')
                rt=self.runtime(agent)
                if not rt.config().get('enabled'):raise HubError('接入未启用')
            except HubError:removed.append(agent)
            else:available.append(agent)
        result['agents']=available
        reviewer=result.get('reviewer')
        if reviewer and reviewer!=manager and reviewer not in available:removed.append(reviewer)
        result['reviewer']=independent_reviewer(manager,available,reviewer)
        return result,list(dict.fromkeys(removed))

    def roster_instruction(self,removed,agents):
        return ('成员配置已变化：不可用身份 '+ '、'.join(removed)+'；当前获准成员 '+('、'.join(agents) or '仅你本人')+
                '。请用 project_status(view="context") 读取原批准计划和需求，保留全部任务、验收及设计基线，重新安排分工和检查者。'
                '不得继续派给不可用身份，不要求有相同模型，不得自动扩大接入或权限；能力确有缺口时说明具体缺口。')

    def save(self,w):
        with self.hub.tx():
            prior=self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(w['id'],)).fetchone()
            previous=json.loads(prior[0]).get('status') if prior else None
            if w.get('status') in ('blocked','needs_attention') and w.get('status')!=previous:
                from .desktop_notifications import enqueue
                enqueue(self.hub,'attention:'+w['id']+':'+uid(),'attention',w.get('project_id') or w['id'])
            self.hub.db.execute('INSERT OR REPLACE INTO workflows VALUES(?,?)',(w['id'],json.dumps(w,ensure_ascii=False)))
            if w.get('status')=='completed' and not w.get('design_review'):
                from .desktop_notifications import enqueue
                enqueue(self.hub,'project:'+w['id'],'project',w.get('project_id') or w['id'])

    def steps(self,ident):
        with self.hub.lock:
            rows=[dict(r) for r in self.hub.db.execute("SELECT s.*,e.id run_id,e.status,e.result,e.prompt,e.actual_input,d.depends_on,(SELECT group_concat(dep.depends_on) FROM workflow_resource_dependencies dep LEFT JOIN executions parent ON parent.task_id=dep.depends_on WHERE dep.task=s.task AND (parent.status IS NULL OR parent.status IN ('queued','waiting_quota','running','interrupting'))) resource_wait_for FROM workflow_steps s LEFT JOIN executions e ON s.task=e.task_id LEFT JOIN workflow_dependencies d ON d.task=s.task WHERE workflow=? ORDER BY seq",(ident,))]
            for row in rows:row['resource_wait_for']=(row['resource_wait_for'] or '').split(',') if row['resource_wait_for'] else []
            return rows

    def patrol_config(self,actor='user',enabled=None,interval_minutes=None):
        self.hub.require(actor,{'user'})
        with self.lock,self.hub.lock:
            row=self.hub.db.execute("SELECT value FROM settings WHERE key='manager_patrol'").fetchone()
            cfg=json.loads(row[0]) if row else {'enabled':True,'interval_minutes':10}
            if enabled is not None:cfg['enabled']=bool(enabled)
            if interval_minutes is not None:
                number(interval_minutes,1,1440);cfg['interval_minutes']=interval_minutes
            if enabled is not None or interval_minutes is not None:
                with self.hub.tx():
                    self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('manager_patrol',?)",(json.dumps(cfg),))
                    for row in self.hub.db.execute('SELECT body FROM workflows').fetchall():
                        w=json.loads(row[0]);w['next_inspection']=time.time()+cfg['interval_minutes']*60
                        w['inspection_policy']={'manager_interval_seconds':cfg['interval_minutes']*60,'enabled':cfg['enabled']}
                        self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
            return cfg

    def patrol_seconds(self):return self.patrol_config()['interval_minutes']*60

    def records(self,project_id=None,statuses=None):
        """Internal state queries must not inherit the UI's history page limit."""
        query="SELECT body FROM workflows WHERE coalesce(json_extract(body,'$.phase'),'')!='cleaned'"
        values=[]
        if project_id is not None:
            query+=" AND json_extract(body,'$.project_id')=?";values.append(project_id)
        if statuses is not None:
            if not statuses:return []
            query+=" AND json_extract(body,'$.status') IN ("+','.join('?' for _ in statuses)+')';values.extend(statuses)
        with self.hub.lock:return [json.loads(row[0]) for row in self.hub.db.execute(query+' ORDER BY rowid DESC',values)]

    def snapshot(self,actor):
        self.hub.require(actor,{'user'})
        with self.lock,self.hub.lock:
            items=[json.loads(r[0]) for r in self.hub.db.execute("SELECT body FROM workflows WHERE coalesce(json_extract(body,'$.phase'),'')!='cleaned' ORDER BY rowid DESC LIMIT 20")]
            for w in items:
                all_steps=self.steps(w['id']);w['calls_used']=len(all_steps);w['steps']=all_steps[-100:]
            return items

    def start(self,actor,requirement,agents,max_calls=6,expires_minutes=60,confirmed=False,auto_wake=True,reviewer=None,delegate_stop=False,max_hops=4,max_messages=12,max_parallel=1,approved_proposal=None,approval_key=None,project_id=None,manager_instruction=None,manager=None):
        self.hub.require(actor,{'user'})
        project=self.hub.projects.get(project_id) if project_id and getattr(self.hub,'projects',None) else None
        if confirmed is not True:raise HubError('请确认项目范围、参与者、调用次数、有效期及现有执行权限')
        manager=manager or project_manager(self.hub,project_id)
        self.runtime(manager)
        text(requirement,45000)
        if not isinstance(agents,list) or len(agents)!=len(set(agents)) or manager in agents:raise HubError('请选择不重复的工作 Agent')
        if type(expires_minutes)!=int or not 1<=expires_minutes<=43200:raise HubError('项目预算或有效期无效')
        if type(max_parallel)!=int or not 1<=max_parallel<=128:raise HubError('并发数必须在1到128之间')
        if type(auto_wake)!=bool or type(delegate_stop)!=bool:raise HubError('协作开关必须是布尔值')
        reviewer=independent_reviewer(manager,agents,reviewer)
        if type(max_hops)!=int or not 1<=max_hops<=32 or type(max_messages)!=int or not 1<=max_messages<=10000:raise HubError('消息链限制无效')
        manager_first=False
        if approved_proposal is not None:
            accepted=proposal(json.dumps(approved_proposal,ensure_ascii=False))
            if accepted['done'] or any(t['agent'] not in [manager]+agents for t in accepted['tasks']):raise HubError('批准计划包含未授权参与者或缺少初始任务')
            manager_first=any(t['agent']==manager for t in accepted['tasks'])
            if manager_first:
                manager_instruction=(manager_instruction+'\n' if manager_instruction else '')+'计划已获用户批准。先调用 project_status(view="context") 读取 approved_plan，再亲自完成分配给你的任务；给所选成员的任务通过 project_assign 派工。没有成员时独立执行，不向自己重复派工，不再请求同一份计划的批准。按原授权执行并验证，完成后用 project_complete 提交。'

        with self.lock:
            from .project_activity import require_available
            require_available(self.hub,project_id)
            if approval_key:
                with self.hub.lock:existing=self.hub.db.execute("SELECT body FROM workflows WHERE json_extract(body,'$.approval_key')=?",(approval_key,)).fetchone()
                if existing:return json.loads(existing[0])
            if getattr(self.hub,'coordination',None) and any(self.hub.coordination.is_stopped(a) for a in [manager]+agents):raise HubError('参与者存在紧急停止锁，先由用户解除')
            if self.hub.db.execute("SELECT 1 FROM workflows WHERE json_extract(body,'$.status') IN ('active','needs_attention') LIMIT 1").fetchone():raise HubError('请先结束当前项目')
            configs={}
            for agent in [manager]+agents:
                rt=self.runtime(agent);cfg=rt.config()
                if not cfg['enabled']:raise HubError(agent+' 的真实执行尚未启用')
                configs[rt.provider]=cfg
            if project:
                from .module_sdk import working_directory
                cwd=working_directory(project['cwd'],'项目工作目录')
            else:
                if len({c['cwd'] for c in configs.values()})!=1:raise HubError('参与者的工作目录必须相同')
                cwd=next(iter(configs.values()))['cwd']
            w={'project_id':project_id,'approval_key':approval_key,'initial_manager_instruction':manager_instruction,'manager':manager,'backup_manager':None,'approved_plan':approved_proposal,'max_parallel':max_parallel,'auto_wake':True,'reviewer':reviewer,'delegate_stop':delegate_stop,'max_hops':max_hops,'max_messages':max_messages,'id':uid(),'requirement':requirement,'agents':agents,'unlimited_calls':True,'max_calls':max_calls,'expires':time.time()+expires_minutes*60,'created':time.time(),'status':'active','phase':'planning','report':'已授权，等待项目经理分解需求','processed':0,'patrolled':None,'inspection_policy':{'supervisor_seconds':0.25,'manager_interval_seconds':self.patrol_seconds(),'model_checks':'消息驱动；定期忙闲巡检'},'grants':{k:v['grant_id'] for k,v in configs.items()},'cwd':next(iter(configs.values()))['cwd']}
            w['cwd']=cwd
            self.save(w)
            with self.hub.tx():self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('max_parallel',?)",(str(max_parallel),))
            with self.hub.tx():self.hub.audit('user','project.authorized',w)
            if approved_proposal is None or manager_first:self.add_step(w,manager,'plan',manager_instruction or self.manager_prompt(w,[]))
            else:
                w['phase']='working';w['report']='用户已批准此版本计划，开始执行'
                with self.hub.tx():
                    for seq,item in enumerate(approved_proposal['tasks'],1):
                        task=uid();message=uid()
                        self.hub.db.execute('INSERT INTO tasks(id,agent,title,assigned_by,created) VALUES(?,?,?,?,?)',(task,item['agent'],item['instruction'],manager,time.time()))
                        self.hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created) VALUES(?,?,?,?,'queue','pending',?)",(message,manager,item['agent'],'[task:'+task+'] '+item['instruction'],time.time()))
                        self.hub.db.execute('UPDATE tasks SET project_id=? WHERE id=?',(w.get('project_id') or w['id'],task))
                        self.hub.db.execute('UPDATE messages SET project_id=? WHERE id=?',(w.get('project_id') or w['id'],message))
                        self.hub.db.execute('INSERT INTO workflow_steps VALUES(?,?,?,?,?)',(w['id'],seq,task,item['agent'],'work'))
                        from .task_resources import register
                        register(self,w,task,item['agent'],'work',item['instruction'])
                    self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
            return w

    def manager_events(self,w,manager_task=None):
        """Claim only what is actually sent; a long original is never cut or rejected."""
        runtime=self.runtime(self.manager(w));cfg=runtime.config()
        synthetic={'id':'new','task_id':'new','session_scope':'project:'+w['id'],'provider':runtime.provider,'agent':self.manager(w),'model':runtime.models[self.manager(w)],**{k:cfg[k] for k in ('cwd','permission','grant_id')}}
        overhead=len(POLICY)+2 if runtime.sessions.policy_needed(synthetic,POLICY) else 0
        with self.hub.lock:
            if manager_task:
                rows=self.hub.db.execute("SELECT id,body,created FROM workflow_events WHERE workflow=? AND manager_task=? ORDER BY CASE WHEN json_extract(body,'$.message_id') IN (SELECT id FROM messages WHERE mode='immediate') THEN 0 ELSE 1 END,created",(w['id'],manager_task)).fetchall()
            else:
                rows=self.hub.db.execute("SELECT id,body,created FROM workflow_events WHERE workflow=? AND status='pending' ORDER BY CASE WHEN json_extract(body,'$.message_id') IN (SELECT id FROM messages WHERE mode='immediate') THEN 0 ELSE 1 END,created LIMIT 8",(w['id'],)).fetchall()
            result=[]
            for row in rows:
                event=json.loads(row['body'])
                original=self.hub.db.execute('SELECT sender,body FROM messages WHERE id=?',(event.get('message_id'),)).fetchone() if event.get('message_id') else None
                sender=original['sender'] if original else (event.get('from') or event.get('agent') or '平台')
                body=original['body'] if original else event.get('body') or event.get('summary') or event.get('type','状态变化')
                if event.get('type')=='result':
                    data=event
                    if original and original['body'].startswith('[主动汇报] '):
                        try:data=json.loads(original['body'][7:])
                        except ValueError:data={**event,'summary':body}
                    body=sender+' '+str(data.get('status',event.get('status','')))+'：'+str(data.get('summary',body))
                    risk=data.get('risk',event.get('risk'))
                    if risk in ('high','blocked'):body+='；风险：'+risk
                    if event.get('kind')=='check':body+=' {"kind": "check"}'
                if sender!='user':body='['+datetime.fromtimestamp(row['created'],timezone(timedelta(hours=8))).strftime('%m-%d %H:%M:%S')+' +08:00] '+str(body)
                candidate=result+[(row['id'],sender,str(body))]
                # Split the queue, not the message. Everything not selected stays pending.
                if not manager_task and result and len(self.manager_event_text(candidate))+overhead>ROUTINE_TARGET:break
                result=candidate
            return result

    @staticmethod
    def manager_event_text(events):
        if len(events)==1 and events[0][1]=='user':return events[0][2]
        def labeled(sender,body):
            if sender=='平台':return body if body.startswith('平台通知：') else '平台通知：'+body
            return body if body.startswith((sender+' ',sender+'：')) else sender+'：'+body
        return '\n\n'.join(labeled(sender,body) for _,sender,body in events)

    def manager_prompt(self,w,steps,periodic=False,manager_task=None):
        if periodic:
            return '成员忙闲：'+'；'.join(a['agent']+'='+a['state'] for a in self.agent_states(w))
        events=self.manager_events(w,manager_task)
        if events:return self.manager_event_text(events)
        return '成员忙闲：'+'；'.join(a['agent']+'='+a['state'] for a in self.agent_states(w))

    def peer_advice(self,w):
        if not getattr(self.hub,'coordination',None):return []
        with self.hub.lock:
            rows=self.hub.db.execute("SELECT m.sender,m.body FROM messages m JOIN wakeups a ON a.message=m.id WHERE a.workflow=? AND m.recipient=? AND m.body NOT LIKE '[主动汇报]%' ORDER BY m.created DESC LIMIT 6",(w['id'],self.manager(w))).fetchall()
        return [{'from':r['sender'],'advice':r['body'][:600]} for r in rows]

    def resources(self,w):
        result={}
        with self.hub.lock:
            rows=self.hub.db.execute('SELECT e.agent,e.usage FROM executions e JOIN workflow_steps s ON s.task=e.task_id WHERE s.workflow=? AND e.usage IS NOT NULL',(w['id'],)).fetchall()
        result['project_usage']=[{'agent':r['agent'],'usage':json.loads(r['usage'])} for r in rows[-12:]]
        if getattr(self.hub,'integrations',None):
            registry=self.hub.integrations
            result['members']=[a for a in registry.capabilities() if a['agent'] in [self.manager(w)]+w['agents']]
            result['connections']=[{'id':c['id'],'name':c['name'],'quota':c.get('quota'),'official_windows':c.get('official_windows',[])} for c in registry.rows('integration_connections')]
            result['note']='额度按账号或连接共享；未知不代表无限额度。'
        else:result['note']='DeepSeek 官方 API；官方余额与限流仍适用。'
        return result

    def result_briefs(self,steps):
        result=[]
        for s in steps[-12:]:
            if s['kind'] not in ('work','message','check'):continue
            report=None
            if getattr(self.hub,'coordination',None):
                with self.hub.lock:report=self.hub.db.execute('SELECT * FROM worker_reports WHERE run=?',(s['run_id'],)).fetchone()
            full_res=(s.get('result') or '')
            summary=report['summary'] if report else clip(full_res,600)
            result.append({'agent':s['agent'],'kind':s['kind'],'status':s['status'],'depends_on':s.get('depends_on'),'run_id':s.get('run_id'),'task_id':s.get('task'),'summary':summary,'risk':report['risk'] if report else 'unknown','evidence':report['evidence'] if report else '未结构化；原文通过 project_status(view="events") 按需读取'})
        return result

    def check_prompt(self,w,steps):
        checker=independent_reviewer(self.manager(w),w['agents'],w.get('reviewer'))
        if checker is None:return '没有独立检查成员；由经理按需选择可用成员，不以经理本人冒充独立检查。'
        rt=self.runtime(checker);cfg=rt.config()
        run={'id':'new','task_id':'new','session_scope':'project:'+w['id'],'agent':checker,'provider':rt.provider,'model':rt.models[checker],**{k:cfg[k] for k in ('cwd','permission','grant_id')}}
        changed=[s for s in steps if s['kind'] in ('work','message') and [s['run_id'],s['status']] not in w.get('check_coverage',[])]
        context={'project_id':w['id'],'changed_reports':self.result_briefs(changed)}
        if w.get('design_baseline'):context['design_verification']='按 '+w['design_baseline']['directory']+' 的manifest.json逐页核对成品布局、颜色、字体、间距、层级及视频镜头/文档版式；提供截图或渲染对照证据，明显偏差不能通过。'
        if not rt.sessions.get(run):context['requirement']=w['requirement']
        return '延续独立检查会话，核查最新完成产物、契约、测试和严重风险。只读检查并运行相关验证，不重复实现。通过 report_result 向 项目经理 简短汇报风险与证据，不能仅凭执行者自称成功认定通过。新变化：'+json.dumps(context,ensure_ascii=False)

    def add_step(self,w,agent,kind,instruction,source_message_id=None,wake_context=None):
        steps=self.steps(w['id'])
        task=uid();message=source_message_id or uid()
        with self.hub.tx():
            self.hub.db.execute('INSERT INTO tasks(id,agent,title,assigned_by,created) VALUES(?,?,?,?,?)',(task,agent,instruction,self.manager(w),time.time()))
            if not source_message_id:self.hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created) VALUES(?,?,?,?,'queue','pending',?)",(message,'user' if kind=='plan' else self.manager(w),agent,'[task:'+task+'] '+instruction,time.time()))
            if wake_context:self.hub.db.execute('INSERT INTO wakeups VALUES(?,?,?,?,?,?,?)',(message,w['id'],task,wake_context['root'],wake_context['depth'],'queued','已在原项目授权内唤醒接收方'))
            self.hub.db.execute('UPDATE tasks SET project_id=? WHERE id=?',(w.get('project_id') or w['id'],task))
            self.hub.db.execute('UPDATE messages SET project_id=? WHERE id=?',(w.get('project_id') or w['id'],message))
            self.hub.db.execute('INSERT INTO workflow_steps VALUES(?,?,?,?,?)',(w['id'],len(steps)+1,task,agent,kind))
            if source_message_id:
                rank=self.hub.db.execute('SELECT position FROM project_queue_positions WHERE item_id=?',(source_message_id,)).fetchone()
                if rank:self.hub.db.execute('INSERT OR REPLACE INTO project_queue_positions VALUES(?,?)',(task,rank[0]))
            if kind=='check':
                w['manager_assigned_review']=True
                w['check_coverage']=[[s['run_id'],s['status']] for s in steps if s['kind'] in ('work','message')]
                self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
            from .task_resources import register
            resource_kind=kind
            if kind=='message' and source_message_id:
                source=self.hub.db.execute('SELECT sender,mode FROM messages WHERE id=?',(source_message_id,)).fetchone()
                if source and source[0]==self.manager(w) and source[1]!='immediate':resource_kind='work'
            register(self,w,task,agent,resource_kind,instruction)
            self.hub.audit(self.manager(w),'project.step_prepared',{'project':w['id'],'agent':agent,'task':task,'kind':kind})
        return task

    def stop(self,actor,workflow_id):
        self.hub.require(actor,{'user'})
        with self.lock:
            with self.hub.lock:row=self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(workflow_id,)).fetchone()
            if not row:raise HubError('项目不存在')
            w=json.loads(row[0])
            with self.hub.lock:runs=[dict(r) for r in self.hub.db.execute("SELECT * FROM executions WHERE status IN ('queued','waiting_quota','running','interrupting') AND (task_id IN (SELECT task FROM workflow_steps WHERE workflow=?) OR session_scope=?)",(w['id'],'project:'+w['id']))]
            for run in runs:self.stop_run(actor,run)
            w.pop('steps',None);w['status']='stopped';w['report']='用户已停止项目，执行中的任务遵循提供商停止确认规则';self.save(w)
        return {'ok':True}

    def stop_run(self,actor,run):
        runtime=next((r for r in self.runtimes if r.provider==run['provider']),None)
        if runtime:
            try:return runtime.stop(actor,run['id'])
            except HubError:
                with self.hub.lock:current=self.hub.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()
                if current and current[0] in ACTIVE:raise
                return
        # A removed module cannot authorize further work or leave an eternal run.
        with self.hub.tx():
            current=self.hub.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()
            if not current or current[0] not in ACTIVE:return
            status='cancelled' if current[0] in ('queued','waiting_quota') else 'interrupted'
            note='执行接入已移除；本地授权已停止，远端执行结果未知，不自动重试。'
            self.hub.db.execute('INSERT OR IGNORE INTO execution_revocations VALUES(?,?,?,?)',(run['id'],actor,note,time.time()))
            self.hub.db.execute('UPDATE executions SET status=?,stop_requested=1,finished=?,result=? WHERE id=?',(status,time.time(),note,run['id']))
            self.hub.db.execute('UPDATE messages SET status=?,lease=NULL,result=? WHERE id=?',(status,note,run['message_id']))
            self.hub.db.execute("UPDATE tasks SET status='blocked',note=? WHERE id=?",(note,run['task_id']))
            self.hub.db.execute("UPDATE agents SET status='idle',active=NULL WHERE id=? AND active=?",(run['agent'],run['message_id']))
            self.hub.audit(actor,'execution.removed_module_stopped',{'run_id':run['id'],'remote_cancel_confirmed':False})

    def reconcile_manager_receipts(self):
        # Repair receipts only for provider-confirmed turns already consumed by the
        # coordinator. Never wake a model or infer successful project completion.
        with self.hub.tx():
            rows=self.hub.db.execute("SELECT v.id,json_extract(v.body,'$.message_id') message FROM workflow_events v JOIN workflow_steps s ON s.task=v.manager_task JOIN workflows w ON w.id=v.workflow WHERE v.status='claimed' AND s.seq<=json_extract(w.body,'$.processed') AND EXISTS(SELECT 1 FROM executions e WHERE e.task_id=s.task AND e.status='completed' AND e.id=(SELECT last.id FROM executions last WHERE last.task_id=s.task ORDER BY last.created DESC,last.id DESC LIMIT 1))").fetchall()
            for row in rows:
                self.hub.db.execute("UPDATE workflow_events SET status='handled' WHERE id=?",(row['id'],))
                if row['message']:
                    self.hub.db.execute("UPDATE messages SET status='completed',lease=NULL,result='经理本轮已结束，汇报已送达' WHERE id=? AND status IN ('pending','acknowledged','delivered')",(row['message'],))
                    self.hub.db.execute("UPDATE wakeups SET status='completed',note='经理本轮已结束，汇报已送达' WHERE message=?",(row['message'],))
            return len(rows)

    def patrol(self):
        with self.lock:
            self.reconcile_manager_receipts()
            with self.hub.lock:pending_stops=[json.loads(r[0]) for r in self.hub.db.execute("SELECT body FROM workflows WHERE id IN (SELECT r.workflow FROM workflow_stop_requests r JOIN executions e ON e.id=r.run WHERE e.stop_requested=1 AND e.status IN ('running','interrupting'))")]
            for item in pending_stops:self.reconcile_stops(item)
            for item in self.records(statuses=('active','needs_attention')):
                from .project_activity import owner
                active_project=owner(self.hub)
                if active_project and item.get('project_id') and active_project!=item['project_id']:continue
                w={k:v for k,v in item.items() if k!='steps'}
                try:
                    if w['status']=='needs_attention':
                        self.valid(w)
                        self.ingest(w,self.steps(w['id']))
                        if time.time()<w.get('next_recovery',0):continue
                        backlog=[step for step in self.steps(w['id']) if step['kind'] in ('plan','review') and step['run_id'] and step['status'] not in ACTIVE and step['seq']>w['processed']]
                        if backlog:
                            w.update(status='active',format_retries=0);self.save(w)
                            self.advance(w);continue
                        finished=[step['seq'] for step in self.steps(w['id']) if step['kind'] in ('plan','review') and step['run_id'] and step['status'] not in ACTIVE]
                        w.update(status='active',processed=max([w['processed']]+finished),manager_recoveries=0,format_retries=0)
                        self.save(w)
                        self.prepare_manager(w,self.steps(w['id']),'调度恢复检查：先核查现有产物和新消息，不重放旧执行。')
                    self.advance(w)
                except Exception as e:
                    # A coordinator/format failure must not cancel independent work.
                    # Invalid authorization and explicit stop still stop all affected runs.
                    safety_error=None
                    try:self.valid(w)
                    except HubError as invalid:safety_error=invalid
                    if safety_error:
                        for step in self.steps(w['id']):
                            if step['run_id'] and step['status'] in ACTIVE:
                                with self.hub.lock:run=self.hub.db.execute('SELECT * FROM executions WHERE id=?',(step['run_id'],)).fetchone()
                                if run:self.stop_run('user',dict(run))
                        w['status']='blocked';w['report']=str(safety_error)[:2000]
                    else:
                        w['status']='needs_attention';w['report']='调度待恢复（成员继续执行）：'+str(e)[:1800];w['next_recovery']=time.time()+180
                    self.save(w)
                    self.hub.send(self.manager(w),'user','[项目调度状态] '+w['report'])

    def valid(self,w):
        if w['status'] not in ('active','needs_attention'):raise HubError('项目未运行；停止锁不会自动解除')
        if time.time()>w['expires']:raise HubError('项目授权已到期')
        for provider,grant in w['grants'].items():
            rt=next((r for r in self.runtimes if r.provider==provider),None)
            if rt is None:raise HubError('项目接入已被移除：'+str(provider)+'；请重新选择可用接入并确认计划')
            if not rt.config()['enabled'] or rt.config()['grant_id']!=grant:raise HubError('执行权限或提供商预算已变化')
        if getattr(self.hub,'coordination',None) and self.hub.coordination.is_stopped(self.manager(w)):raise HubError('项目经理 紧急停止锁有效')

    def enqueue(self,w,event_id,body,source_run=None):
        with self.hub.tx():self.hub.db.execute("INSERT OR IGNORE INTO workflow_events VALUES(?,?,?,?,'pending',NULL,?)",(event_id,w['id'],source_run,json.dumps(body,ensure_ascii=False),time.time()))

    def ingest(self,w,steps):
        for step in steps:
            if not step['run_id'] or step['kind'] not in ('work','message','check') or step['status'] in ACTIVE:continue
            if getattr(self.hub,'coordination',None):
                with self.hub.lock:run=dict(self.hub.db.execute('SELECT * FROM executions WHERE id=?',(step['run_id'],)).fetchone())
                self.hub.coordination.report(run,step['status'],step['result'] or '')
            with self.hub.lock:message=self.hub.db.execute('SELECT id FROM messages WHERE recipient=? AND request_key=?',(self.manager(w),'report:'+step['run_id'])).fetchone()
            briefs=self.result_briefs([step]);body={'type':'result','run':step['run_id'],'task':step['task'],'message_id':message[0] if message else None,**briefs[0]}
            self.enqueue(w,'execution:'+step['run_id']+':'+str(step['status']),body,step['run_id'])

    def prepare_manager(self,w,steps,reason=None,periodic=False):
        if getattr(self.hub,'integrations',None):self.hub.integrations.flush_changes(w,force=True)
        steps=self.steps(w['id'])
        if reason:
            self.enqueue(w,'control:'+uid(),{'type':'control','body':reason})
        w['next_inspection']=time.time()+self.patrol_seconds()
        prepared=next((x for x in steps if x['kind'] in ('plan','review') and not x['run_id']),None)
        if prepared:return prepared['task']
        task=uid();message=uid();manager=self.manager(w)
        with self.hub.tx():
            selected=self.manager_events(w)
            for ident,_,_ in selected:self.hub.db.execute("UPDATE workflow_events SET status='claimed',manager_task=? WHERE id=? AND status='pending'",(task,ident))
            instruction=self.manager_prompt(w,steps,periodic=periodic and not selected,manager_task=task)
            self.hub.db.execute('INSERT INTO tasks(id,agent,title,assigned_by,created) VALUES(?,?,?,?,?)',(task,manager,instruction,manager,time.time()))
            self.hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created) VALUES(?,?,?,?,'queue','pending',?)",(message,'user' if len(selected)==1 and selected[0][1]=='user' else '平台',manager,'[task:'+task+'] '+instruction,time.time()))
            self.hub.db.execute('UPDATE tasks SET project_id=? WHERE id=?',(w.get('project_id') or w['id'],task))
            self.hub.db.execute('UPDATE messages SET project_id=? WHERE id=?',(w.get('project_id') or w['id'],message))
            self.hub.db.execute('INSERT INTO workflow_steps VALUES(?,?,?,?,?)',(w['id'],len(steps)+1,task,manager,'review'))
            self.hub.db.execute("UPDATE messages SET status='acknowledged',acked=?,attempts=attempts+1 WHERE id IN (SELECT json_extract(body,'$.message_id') FROM workflow_events WHERE manager_task=?) AND status='pending'",(time.time(),task))
            w['phase']='reviewing';w['report']=reason or '新消息已唤醒 项目经理，延续原会话调度';self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
        return task

    def dispatch(self,w,agent,instruction,key,kind='work',write_paths=None,read_paths=None):
        self.valid(w)
        if agent not in w['agents'] or agent==self.manager(w):raise HubError('未授权的执行者或正在担任经理：'+str(agent))
        text(instruction,6000)
        if kind not in ('work','check'):raise HubError('分工种类无效')
        if kind=='check':instruction='只读检查，不得修改文件或重放历史执行。'+instruction
        with self.hub.lock:old=self.hub.db.execute('SELECT task FROM project_dispatches WHERE workflow=? AND request_key=?',(w['id'],key)).fetchone()
        if old:
            with self.hub.lock:prior=self.hub.db.execute('SELECT agent,title FROM tasks WHERE id=?',(old[0],)).fetchone()
            if prior['agent']!=agent or prior['title']!=instruction:raise HubError('同一请求键不能改变任务内容')
            return {'task_id':old[0],'deduplicated':True}
        steps=self.steps(w['id'])
        previous=next((s for s in reversed(steps) if s['agent']==agent and s['kind'] in ('work','check') and (not s['run_id'] or s['status'] in ACTIVE)),None)
        reserve=2 if w.get('reviewer',self.manager(w))!=self.manager(w) else 1
        # Task preparation, idempotency key, and dispatch record survive a process restart together.
        task=uid();message=uid()
        with self.hub.tx():
            self.hub.db.execute('INSERT INTO tasks(id,agent,title,assigned_by,created) VALUES(?,?,?,?,?)',(task,agent,instruction,self.manager(w),time.time()))
            self.hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created) VALUES(?,?,?,?,'queue','pending',?)",(message,self.manager(w),agent,'[task:'+task+'] '+instruction,time.time()))
            self.hub.db.execute('UPDATE tasks SET project_id=? WHERE id=?',(w.get('project_id') or w['id'],task))
            self.hub.db.execute('UPDATE messages SET project_id=? WHERE id=?',(w.get('project_id') or w['id'],message))
            self.hub.db.execute('INSERT INTO workflow_steps VALUES(?,?,?,?,?)',(w['id'],len(steps)+1,task,agent,kind))
            if kind=='check':
                w['manager_assigned_review']=True
                w['check_coverage']=[[s['run_id'],s['status']] for s in steps if s['kind'] in ('work','message')]
                self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
            self.hub.db.execute('INSERT INTO project_dispatches VALUES(?,?,?)',(w['id'],key,task))
            from .task_resources import register
            resource_wait=register(self,w,task,agent,kind,instruction,read_paths if kind=='check' else write_paths)
            if resource_wait:self.hub.db.execute("UPDATE tasks SET note=? WHERE id=?",('等待相关文件的在途任务结束：'+', '.join(resource_wait),task))
            if previous:self.hub.db.execute('INSERT INTO workflow_dependencies VALUES(?,?)',(task,previous['task']))
            self.hub.audit(self.manager(w),'project.message_dispatch',{'project':w['id'],'agent':agent,'task':task})
        registry=getattr(self.hub,'integrations',None)
        quota=registry.quota_status(agent) if registry else None
        unavailable=registry.model_status(agent) if registry else None
        if unavailable:
            self._cancel_task(w,task,self.manager(w),'所选模型已下线或不可用，未调用模型；请经理改派')
            with self.hub.tx():
                row=dict(self.hub.db.execute('SELECT * FROM executions WHERE task_id=?',(task,)).fetchone())
                from .model_availability import reject
                reject(self.hub,row,unavailable['detail'])
                self.hub.db.execute("UPDATE tasks SET status='cancelled' WHERE id=?",(task,))
            return {'task_id':task,'status':'cancelled','reason':'model_unavailable','model_called':False,'detail':unavailable['detail']}
        if quota and quota['exhausted']:
            self._cancel_task(w,task,self.manager(w),'该模型额度耗尽，未调用模型；请改派或设置恢复提醒')
            with self.hub.tx():
                row=dict(self.hub.db.execute('SELECT * FROM executions WHERE task_id=?',(task,)).fetchone())
                from .quota_state import record_rejection
                record_rejection(self.hub,row,'官方或手动额度读数已耗尽，任务未启动。')
                self.hub.db.execute("UPDATE tasks SET status='cancelled' WHERE id=?",(task,))
            return {'task_id':task,'status':'cancelled','reason':'quota_exhausted','model_called':False,'resets_at':quota.get('resets_at')}
        return {'task_id':task,'status':'queued' if previous or resource_wait else 'prepared','after_task':previous['task'] if previous else None,'waiting_for_tasks':resource_wait,'file_scope':write_paths if kind=='work' else read_paths}

    def run_context(self,actor,run_id,manager=False,allow_completed=False):
        with self.hub.lock:
            row=self.hub.db.execute('SELECT e.*,s.workflow,s.kind step_kind FROM executions e JOIN workflow_steps s ON s.task=e.task_id WHERE e.id=?',(run_id,)).fetchone()
            wrow=self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(row['workflow'],)).fetchone() if row else None
        if not row and not manager:
            from .user_followup import direct,context
            with self.hub.lock:raw=self.hub.db.execute('SELECT * FROM executions WHERE id=?',(run_id,)).fetchone()
            candidate=dict(raw) if raw else {}
            if candidate.get('agent')==actor and candidate.get('status')=='running' and direct(self.hub,candidate):
                if candidate.get('stop_requested'):raise HubError('本轮已请求停止，工具权限已暂停')
                w=context(self.hub,candidate)
                if w.get('grants'):
                    rt=self.runtime(actor);rt.check_latch(candidate)
                    self.valid({**w,'status':'active'})
                    if candidate['grant_id']!=w['grants'].get(candidate['provider']):raise HubError('执行授权已变化')
                    return w,{**candidate,'step_kind':'message'}
        if row and row['stop_requested']:raise HubError('本轮已请求停止，工具权限已暂停')
        if row and self.hub.db.execute('SELECT 1 FROM execution_revocations WHERE run=?',(run_id,)).fetchone():raise HubError('此执行已由经理强制停止，工具权限已撤销')
        if not row or row['agent']!=actor or row['purpose'] not in ('task','question') or row['status'] not in (('running','completed') if allow_completed else ('running',)):raise HubError('工具仅供当前项目内的有效执行使用')
        w=json.loads(wrow[0]);self.valid(w)
        if manager and (actor!=self.manager(w) or row['purpose']!='task' or row['step_kind'] not in ('plan','review')):raise HubError('只有当前项目经理可以管理项目')
        if row['grant_id']!=w['grants'].get(row['provider']):raise HubError('执行授权已变化')
        return w,dict(row)

    def project_assign(self,actor,run_id,agent,instruction,request_key,kind='work',write_paths=None,read_paths=None):
        with self.lock:
            from .user_followup import dispatch as dispatch_followup
            followup=dispatch_followup(self,actor,run_id,agent,instruction,'mcp:'+run_id+':'+request_key,kind,write_paths,read_paths)
            if followup is not None:return followup
            w,run=self.run_context(actor,run_id,True);text(request_key,200)
            if w.get('return_manager'):raise HubError('已申请交接，请结束本轮后再由下一位经理派工')
            return self.dispatch(w,agent,instruction,'mcp:'+run_id+':'+request_key,kind,write_paths,read_paths)

    def project_queue(self,actor,run_id,agent,operation='list',item_id=None,instruction=None,item_ids=None,request_key=None,reason='经理调整待执行队列'):
        from .queue_control import operate
        return operate(self,actor,run_id,agent,operation,item_id,instruction,item_ids,request_key,reason)

    def project_progress(self,actor,run_id,progress,note):
        number(progress,0,100);text(note,5000)
        with self.lock:
            w,run=self.run_context(actor,run_id,True)
            report={'progress':progress,'note':note,'by':actor,'updated':time.time()}
            w['manager_progress']=report
            self.save(w)
            with self.hub.tx():self.hub.audit(actor,'project.progress',{'project':w.get('project_id') or w['id'],'workflow':w['id'],**report})
            return report

    def project_git(self,actor,run_id,action='status',agent=None,message=None):
        return self.git.tool(actor,run_id,action,agent,message)

    def report_result(self,actor,run_id,summary,risk='unknown',evidence=None):
        with self.lock:
            w,run=self.run_context(actor,run_id);text(summary,800)
            if risk not in ('low','high','blocked','unknown') or not isinstance(evidence or [],list):raise HubError('汇报风险或证据格式无效')
            body={'summary':summary,'risk':risk,'evidence':evidence or []}
            if len(json.dumps(body,ensure_ascii=False))>4000:raise HubError('汇报过长')
            with self.hub.tx():self.hub.db.execute('INSERT OR REPLACE INTO model_reports VALUES(?,?)',(run_id,json.dumps(body,ensure_ascii=False)))
            return {'saved':True,'delivery':'提供商确认本轮结束后，队列发送简短汇报给 项目经理 并唤醒；不把提前自报视为执行已结束'}

    def project_status(self,actor,run_id,view="status",offset=0,limit=2000):
        with self.lock:
            w,run=self.run_context(actor,run_id)
            if view not in ('status','context','events') or type(offset)!=int or offset<0 or type(limit)!=int or not 100<=limit<=4000:raise HubError('状态视图或分页参数无效')
            if view!='status':
                if actor!=self.manager(w):raise HubError('项目完整上下文与消息事件仅供当前经理读取')
                if view=='context':data={'git':self.git.status(w),'requirement':w['requirement'],'approved_plan':w.get('approved_plan'),'agents':w['agents'],'reviewer':w.get('reviewer'),'design':{k:w[k] for k in ('design_review','design_dir','design_brief','design_baseline') if k in w},'delivery_stage':w.get('delivery_stage') or ('implementation' if w.get('design_baseline') else 'demo' if w.get('design_review') else 'execution'),'acceptance_policy':'正式制作需验证真实功能和设计外观；演示复制、哈希一致不等于功能完成。检查任务由经理安排，不能将静态检查说成视觉验证。','capabilities':{a:self.runtime(a).models[a] for a in w['agents']}}
                else:
                    with self.hub.lock:rows=self.hub.db.execute("SELECT id,body FROM workflow_events WHERE workflow=? AND (status='pending' OR manager_task=?) ORDER BY created",(w['id'],run['task_id'])).fetchall()
                    data=[]
                    for row in rows:
                        event={'event_id':row['id'],**json.loads(row['body'])}
                        if event.get('message_id'):
                            with self.hub.lock:message=self.hub.db.execute('SELECT sender,recipient,body FROM messages WHERE id=?',(event['message_id'],)).fetchone()
                            if message:event['message']={'from':message['sender'],'to':message['recipient'],'body':message['body']}
                        data.append(event)
                value=json.dumps(data,ensure_ascii=False)
                return {'view':view,'text':value[offset:offset+limit],'total_chars':len(value),'next_offset':offset+limit if offset+limit<len(value) else None}
            try:self.completion_check(w,run['task_id']);blocker=None
            except HubError as error:blocker=str(error)
            return {'manager':self.manager(w),'agents':self.agent_states(w),'completion_blocker':blocker,'completion_authority':'manager','completion_blocking_tasks':self.completion_blocking_tasks(self.steps(w['id']),run['task_id']),'id':w['id'],'status':w['status'],'report':w['report'],'resource_wait':w.get('resource_wait'),'remaining_calls':None,'unlimited_calls':True,'steps':[{'task':s['task'],'agent':s['agent'],'kind':s['kind'],'status':s['status'],'depends_on':s.get('depends_on'),'waiting_for_tasks':s.get('resource_wait_for',[]),'summary':self.result_briefs([s])} for s in self.steps(w['id'])[-30:]],'git':self.git.status(w),'resources':self.resources(w),'design':{k:w[k] for k in ('design_review','design_dir','design_brief','design_baseline') if k in w},'delivery_stage':w.get('delivery_stage') or ('implementation' if w.get('design_baseline') else 'demo' if w.get('design_review') else 'execution'),'acceptance_policy':'正式制作需验证真实功能和设计外观；演示复制、哈希一致不等于功能完成。检查任务由经理安排，不能将静态检查说成视觉验证。'}

    def agent_states(self,w):
        states=[]
        with self.hub.lock:
            for agent in dict.fromkeys([self.manager(w)]+w['agents']):
                rows=self.hub.db.execute("SELECT status,task_id,retry_after FROM executions WHERE agent=? AND status IN ('queued','running','interrupting','waiting_quota')",(agent,)).fetchall()
                registry=getattr(self.hub,'integrations',None);quota=registry.quota_status(agent) if registry else {'exhausted':False}
                unavailable=registry.model_status(agent) if registry else None
                busy=any(r['status'] in ('running','interrupting') for r in rows)
                waiting_files=any(self.hub.db.execute("SELECT 1 FROM workflow_resource_dependencies dep LEFT JOIN executions prior ON prior.task_id=dep.depends_on WHERE dep.task=? AND (prior.status IS NULL OR prior.status IN ('queued','running','interrupting','waiting_quota'))",(r['task_id'],)).fetchone() for r in rows if r['status']=='queued')
                states.append({'agent':agent,'role':w.get('roles',{}).get(agent,self.hub.agent(agent)['role']),'quota_exhausted':quota['exhausted'],'model_unavailable':unavailable,'state':'busy' if busy else ('model_unavailable' if unavailable else 'quota_exhausted' if quota['exhausted'] else 'waiting_quota' if any(r['status']=='waiting_quota' for r in rows) else 'waiting_files' if waiting_files else 'idle'),'queued':sum(r['status']=='queued' for r in rows),'retry_at':max([r['retry_after'] or 0 for r in rows if r['status']=='waiting_quota'] or [0]) or None,'waiting_files':waiting_files,'available':not unavailable and not quota['exhausted'] and not waiting_files and not any(r['status']=='waiting_quota' for r in rows) and self.runtime(agent).config()['enabled'] and not (getattr(self.hub,'coordination',None) and self.hub.coordination.is_stopped(agent))})
        return states

    def project_mailbox(self,actor,run_id,before=None,limit=30):
        with self.lock:
            w,run=self.run_context(actor,run_id)
            if type(limit)!=int or not 1<=limit<=50:raise HubError('limit 必须在1到50之间')
            if before is not None and not isinstance(before,(int,float)):raise HubError('before 必须为时间戳')
            with self.hub.lock:
                if actor==self.manager(w):
                    rows=self.hub.db.execute("SELECT DISTINCT m.* FROM messages m LEFT JOIN executions e ON e.message_id=m.id LEFT JOIN workflow_steps s ON s.task=e.task_id LEFT JOIN wakeups a ON a.message=m.id WHERE (s.workflow=? OR a.workflow=?) AND m.created<? ORDER BY m.created DESC LIMIT ?",(w['id'],w['id'],before or time.time()+1,limit)).fetchall()
                else:
                    rows=self.hub.db.execute("SELECT DISTINCT m.* FROM messages m LEFT JOIN executions e ON e.message_id=m.id LEFT JOIN workflow_steps s ON s.task=e.task_id LEFT JOIN wakeups a ON a.message=m.id WHERE (s.workflow=? OR a.workflow=?) AND (m.sender=? OR m.recipient=?) AND m.created<? ORDER BY m.created DESC LIMIT ?",(w['id'],w['id'],actor,actor,before or time.time()+1,limit)).fetchall()
            return {'messages':[{'id':r['id'],'from':r['sender'],'to':r['recipient'],'mode':r['mode'],'status':r['status'],'body':r['body'][:2200],'created':r['created'],'authority':'manager' if r['sender']==self.manager(w) else ('user' if r['sender']=='user' else 'platform_notice' if r['sender']=='平台' else 'peer_question_or_reply')} for r in rows], 'next_before':rows[-1]['created'] if len(rows)==limit else None}

    def project_return_manager(self,actor,run_id,summary):
        with self.lock:
            w,run=self.run_context(actor,run_id,True);text(summary,500)
            target=w.get('previous_manager') or w.get('inherited_context',{}).get('previous_manager')
            if not target or target==actor:raise HubError('本项目没有已授权的原经理，请由用户选择项目经理')
            rt=self.runtime(target)
            if not rt.config().get('enabled') or rt.config().get('grant_id')!=w['grants'].get(rt.provider):raise HubError('原经理接入未获得本项目授权')
            if self.hub.coordination.is_stopped(target):raise HubError('原经理停止锁有效，不交回')
            w['return_manager']={'target':target,'requested_by':actor,'run_id':run_id,'summary':summary,'at':time.time()};self.save(w)
            with self.hub.tx():self.hub.audit(actor,'project.manager_return_requested',{'project':w['id'],'run_id':run_id})
            return {'saved':True,'handoff':'本轮提供商确认结束并由平台处理完成后交回；请不再派工，输出简短等待结论'}

    def project_set_role(self,actor,run_id,agent,role,reviewer=False):
        with self.lock:
            w,run=self.run_context(actor,run_id,True);text(role,200)
            if agent not in w['agents'] or agent==self.manager(w) or type(reviewer)!=bool:raise HubError('只能调整已授权参与者')
            w.setdefault('roles',{})[agent]=role
            if reviewer:w['reviewer']=agent
            self.save(w)
            with self.hub.tx():self.hub.audit(actor,'project.role_changed',{'project':w['id'],'agent':agent,'role':role,'reviewer':reviewer})
            return {'agent':agent,'role':role,'reviewer':w.get('reviewer'),'applies':'后续任务；不更改正在执行任务的范围'}

    def project_cancel_task(self,actor,run_id,task_id,reason):
        with self.lock:
            w,run=self.run_context(actor,run_id,True);text(reason,500)
            return self._cancel_task(w,task_id,actor,reason)

    def _cancel_task(self,w,task_id,actor,reason):
        step=next((s for s in self.steps(w['id']) if s['task']==task_id),None)
        if not step:raise HubError('任务不属于当前项目')
        if step['status'] in ('running','interrupting'):raise HubError('执行中任务不能用取消排队代替中断；先协调停止')
        if step['run_id'] and step['status'] not in ('queued','waiting_quota'):raise HubError('任务已结束，不重写历史状态')
        if step['run_id']:
            with self.hub.tx():
                changed=self.hub.db.execute("UPDATE executions SET status='cancelled',finished=?,result=? WHERE id=? AND status IN ('queued','waiting_quota')",(time.time(),'经理取消排队：'+reason,step['run_id'])).rowcount
                if not changed:raise HubError('任务已开始或结束，请刷新状态后使用 project_stop_task')
                self.hub.db.execute("UPDATE messages SET status='cancelled',lease=NULL WHERE id=(SELECT message_id FROM executions WHERE id=?)",(step['run_id'],))
                self.hub.db.execute("UPDATE tasks SET status='blocked',note=? WHERE id=?",('经理取消排队：'+reason,task_id))
        else:
            try:
                rt=self.runtime(step['agent']);cfg=rt.config();provider=rt.provider;model=rt.models[step['agent']]
            except HubError:
                cfg={'cwd':w.get('cwd',''),'permission':'none','max_seconds':0,'grant_id':''};provider='controller';model=self.hub.agent(step['agent'])['model']
            ident=uid()
            with self.hub.tx():
                title=self.hub.db.execute('SELECT title FROM tasks WHERE id=?',(task_id,)).fetchone()[0]
                message=self.hub.db.execute("SELECT id FROM messages WHERE body LIKE ?",('[task:'+task_id+'] %',)).fetchone()
                self.hub.db.execute("INSERT INTO executions(id,task_id,message_id,agent,model,prompt,actual_input,cwd,permission,max_seconds,grant_id,status,created,finished,result,provider) VALUES(?,?,?,?,?,?,?,?,?,?,?,'cancelled',?,?,?,?)",(ident,task_id,message[0] if message else None,step['agent'],model,title,title,cfg['cwd'],cfg['permission'],cfg['max_seconds'],cfg['grant_id'],time.time(),time.time(),'经理取消未启动任务：'+reason,provider))
                self.hub.db.execute("UPDATE messages SET status='cancelled' WHERE id=?",(message[0] if message else None,))
                self.hub.db.execute("UPDATE tasks SET status='blocked',note=? WHERE id=?",('经理取消排队：'+reason,task_id))
        w.setdefault('cancelled_tasks',{})[task_id]=reason;self.save(w)
        with self.hub.tx():self.hub.audit(actor,'project.queued_task_cancelled',{'project':w['id'],'task':task_id,'reason':reason})
        return {'cancelled':True,'task_id':task_id}

    def project_stop_task(self,actor,run_id,task_id,reason):
        with self.lock:
            w,run=self.run_context(actor,run_id,True);text(reason,500)
            return self._stop_task(w,task_id,actor,reason)

    def _stop_task(self,w,task_id,actor,reason):
        step=next((s for s in self.steps(w['id']) if s['task']==task_id),None)
        if not step or step['agent']==self.manager(w):raise HubError('只能停止本项目成员任务')
        if step['status'] and step['status'] not in ACTIVE:return {'stopped':True,'status':step['status'],'task_id':task_id}
        if not step['run_id'] or step['status'] in ('queued','waiting_quota'):
            try:return {**self._cancel_task(w,task_id,actor,reason),'stopped':True,'status':'cancelled','can_reassign':True}
            except HubError:
                step=next((s for s in self.steps(w['id']) if s['task']==task_id),None)
                if not step or not step['run_id']:raise
                if step['status'] not in ACTIVE:return {'stopped':True,'status':step['status'],'task_id':task_id,'can_reassign':True}
                if step['status'] not in ('running','interrupting'):raise
        with self.hub.tx():
            row=self.hub.db.execute('SELECT * FROM executions WHERE id=?',(step['run_id'],)).fetchone()
            if row['status'] not in ACTIVE:return {'stopped':True,'status':row['status'],'task_id':task_id,'can_reassign':True}
            # Permanent per-execution fence survives late worker responses.
            self.hub.db.execute('INSERT OR IGNORE INTO execution_revocations VALUES(?,?,?,?)',(row['id'],actor,reason,time.time()))
            self.hub.db.execute('UPDATE executions SET stop_requested=1 WHERE id=?',(row['id'],))
        rt=next((r for r in self.runtimes if r.provider==row['provider']),None)
        errors=[]
        client=getattr(rt,'clients',{}).get(row['id'])
        if client:
            for resource,method in ((getattr(client,'job',None),'close'),(getattr(client,'proc',None),'kill'),(client,'close')):
                if resource is None:continue
                try:
                    action=getattr(resource,method,None)
                    if callable(action):action()
                except Exception as error:errors.append(type(error).__name__)
            if rt.clients.get(row['id']) is client:rt.clients.pop(row['id'],None)
        note='经理强制停止此任务；可立即重新派工。已发送的远端请求仍可能计费。'
        with self.hub.tx():
            self.hub.db.execute("UPDATE executions SET status='interrupted',finished=?,result=? WHERE id=?",(time.time(),note,row['id']))
            self.hub.db.execute("UPDATE messages SET status='interrupted',lease=NULL,result=? WHERE id=?",(note,row['message_id']))
            self.hub.db.execute("UPDATE tasks SET status='blocked',note=? WHERE id=?",(note,task_id))
            self.hub.db.execute("UPDATE agents SET status='idle',active=NULL WHERE id=? AND active=?",(row['agent'],row['message_id']))
            self.hub.audit(actor,'project.member_force_stopped',{'project':w['id'],'task':task_id,'run_id':row['id'],'reason':reason,'cleanup_errors':errors})
        return {'task_id':task_id,'stopped':True,'status':'interrupted','can_reassign':True,'note':note}

    def reconcile_stops(self,w):
        with self.hub.lock:
            rows=self.hub.db.execute("SELECT r.*,e.agent,e.message_id,e.status FROM workflow_stop_requests r JOIN executions e ON e.id=r.run WHERE r.workflow=? AND e.stop_requested=1 AND e.status IN ('running','interrupting')",(w['id'],)).fetchall()
        for row in rows:
            rt=next((r for r in self.runtimes if r.provider==self.hub.db.execute('SELECT provider FROM executions WHERE id=?',(row['run'],)).fetchone()[0]),None)
            thread=getattr(rt,'run_threads',{}).get(row['run']);client=getattr(rt,'clients',{}).get(row['run'])
            if thread and thread.is_alive():
                if client and time.time()-row['created']>5:
                    # Close only this task's owned client; no global Agent stop latch.
                    try:client.close()
                    except Exception:pass
                continue
            if client:
                try:
                    close=getattr(client,'close',None)
                    if callable(close):close()
                    elif getattr(client,'job',None):client.job.close()
                except Exception:continue
                process=getattr(client,'proc',None)
                if process is None or process.poll() is None:continue
                if rt.clients.get(row['run']) is client:rt.clients.pop(row['run'],None)
            with self.hub.tx():
                note='经理请求停止；平台确认本地执行器已不存在。提供商远端取消状态未知，不能视为成功。'
                changed=self.hub.db.execute("UPDATE executions SET status='interrupted',finished=?,result=? WHERE id=? AND stop_requested=1 AND status IN ('running','interrupting')",(time.time(),note,row['run'])).rowcount
                if not changed:continue
                self.hub.db.execute("UPDATE messages SET status='interrupted',lease=NULL,result=? WHERE id=?",(note,row['message_id']))
                self.hub.db.execute("UPDATE tasks SET status='blocked',note=? WHERE id=?",(note,row['task']))
                self.hub.db.execute("UPDATE agents SET status='idle',active=NULL WHERE id=? AND active=?",(row['agent'],row['message_id']))
                self.hub.audit('supervisor','project.member_stop_reconciled',{'project':w['id'],'task':row['task'],'provider_cancel_confirmed':False})

    def project_schedule_wake(self,actor,run_id,delay_seconds,reason=None):
        w,_=self.run_context(actor,run_id)
        result=self.hub.automation.schedule_wake(actor,run_id,delay_seconds,recipient=self.manager(w),note=reason or '',request_key='manager-follow-up')
        w['next_inspection']=result['due'];self.save(w)
        return result

    @staticmethod
    def completion_blocking_tasks(steps,manager_task=None):
        return [{'task':s['task'],'agent':s['agent'],'kind':s['kind'],'run_id':s.get('run_id'),'status':s.get('status') or 'not_started','depends_on':s.get('depends_on')} for s in steps if s['task']!=manager_task and (not s.get('run_id') or s['status'] in ACTIVE)]

    def completion_check(self,w,manager_task=None):
        # The only automatic completion gate: another project member is
        # actually executing. Queued/quota-waiting/ended tasks do not veto it.
        steps=self.steps(w['id'])
        manager=w.get('manager') or self.manager(w)
        busy=[{'agent':s['agent'],'task':s['task'],'run_id':s.get('run_id'),'status':s['status']} for s in steps if s['agent']!=manager and s['task']!=manager_task and s['status'] in ('running','interrupting')]
        if busy:raise HubError('成员仍在执行，暂不能提交完成：'+json.dumps(busy,ensure_ascii=False)+'；等待其结束，或由经理先用 project_stop_task 强停。')
        return steps

    def completion_folder(self,w):
        if w.get('design_review'):return None # The published review is the demo delivery entry.
        with self.hub.lock:
            table=self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='shared_artifacts'").fetchone()
            rows=self.hub.db.execute("SELECT body FROM shared_artifacts WHERE json_extract(body,'$.workflow_id')=? AND json_extract(body,'$.kind')='folder' AND json_extract(body,'$.sender')=? ORDER BY rowid DESC",(w['id'],self.manager(w))).fetchall() if table else []
        from pathlib import Path
        for row in rows:
            item=json.loads(row[0]);target=Path(item.get('path','')).resolve()
            if target.is_dir() and any(target.is_relative_to(Path(root)) for root in item.get('folder_roots',[])):return item['id']
        raise HubError('完成前请先向用户发送本轮交付文件夹链接：调用 publish_artifact(kind="folder", path=".", caption="打开交付目录")，再重试 project_complete。可改为实际交付子目录；用户无需先点击链接。')

    def project_complete(self,actor,run_id,summary,evidence,confirmation=None):
        with self.lock:
            self.hub.agent(actor)
            with self.hub.lock:prior=self.hub.db.execute('SELECT w.body FROM workflows w JOIN workflow_steps s ON s.workflow=w.id JOIN executions e ON e.task_id=s.task WHERE e.id=? AND e.agent=?',(run_id,actor)).fetchone()
            old=json.loads(prior[0]) if prior else {}
            if old.get('status')=='completed' and old.get('completion',{}).get('run_id')==run_id:return {'completed':True,'project_id':old['id'],'deduplicated':True,'design_review_ready':old.get('design_review_ready'),'warnings':old.get('completion_warnings',[])}
            w,run=self.run_context(actor,run_id,True,True);text(summary,2000)
            if not isinstance(evidence,list) or not evidence or any(not isinstance(e,str) or not e.strip() or len(e)>1000 for e in evidence) or len(evidence)>20:raise HubError('需要简短、可核查的完成证据')
            self.completion_check(w,run['task_id'])
            pending=w.get('completion_review',{})
            if not w.get('design_review') and (pending.get('run_id')!=run_id or not isinstance(confirmation,dict) or not all(isinstance(confirmation.get(k),str) and confirmation[k].strip() for k in ('comprehensive_tests','vm_ui_tests'))):
                w['completion_review']={'run_id':run_id,'summary':summary,'evidence':evidence,'requested_at':time.time()};self.save(w)
                from .memory_notices import notify
                notifications=[]
                key='memory-review:completed:'+w['id']
                with self.hub.lock:already=self.hub.db.execute("SELECT 1 FROM messages WHERE sender='平台' AND recipient=? AND request_key=?",(actor,key)).fetchone()
                if not already:notifications.append(notify(self.hub,w,'completed',run_id=run_id))
                return {'completed':False,'confirmation_required':True,'notifications':notifications,'questions':['是否测试了本次交付构建？请给出交付文件哈希/版本、实际启动路径和PID，说明旧实例已终止、新构建冷启动结果及已测/未测范围。','是否在虚拟机交互桌面或真实浏览器中逐按钮、菜单、弹窗测试正反路径及状态变化？请给出操作清单与证据，HTTP测试、DOM桩及静态截图不能替代；说明失败项和未测原因。' if not w.get('design_review') else '本轮为静态演示，请说明全部页面、层次和版面的检查结果；不要求尚未实现的真实按钮逻辑。'],'next':'核对后再次调用project_complete，可更新summary/evidence说明测试限制，携带confirmation={comprehensive_tests:测试结果或未测原因,vm_ui_tests:虚拟机实测结果或未测原因}。由经理自行决定是否交付，平台不自动测试或判定测试通过。'}
            folder_link=self.completion_folder(w)
            self.ingest(w,self.steps(w['id']))
            # Serialize the check and queue retirement with worker startup.
            # A queued member cannot become running between these operations.
            settled=[]
            with self.hub.lock:
                self.completion_check(w,run['task_id'])
                for step in self.steps(w['id']):
                    if step['agent']!=self.manager(w) and (not step['run_id'] or step['status'] in ACTIVE):
                        settled.append(self._stop_task(w,step['task'],actor,'经理已确认项目完成，取消本轮剩余排队任务'))
            warnings=[];review_ready=None
            if w.get('design_baseline'):
                try:self.hub.designs.verify_baseline(w['design_baseline'])
                except HubError as error:warnings.append(str(error))
            with self.hub.tx():
                if w.get('design_review'):
                    try:
                        review=self.hub.designs.prepare_publish(w)
                        self.hub.db.execute('UPDATE design_reviews SET body=? WHERE id=?',(json.dumps(review,ensure_ascii=False),review['id']));review_ready=True
                    except HubError as error:
                        # Invalid assets are never published, but do not veto
                        # the manager's project completion decision.
                        warnings.append(str(error));review_ready=False
                        review=self.hub.designs.get(w['design_review'])
                        review.update(state='publish_error',publish_error=str(error))
                        self.hub.db.execute('UPDATE design_reviews SET body=? WHERE id=?',(json.dumps(review,ensure_ascii=False),review['id']))
                w['design_review_ready']=review_ready
                w['completion_stopped_tasks']=settled
                w['completion_warnings']=warnings
                w.update(status='completed',phase='done',report=summary,completion={'by':actor,'run_id':run_id,'evidence':evidence,'at':time.time(),'folder_link':folder_link,'testing_confirmation':confirmation})
                self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
                self.hub.db.execute("UPDATE messages SET status='completed',result='项目经理 已验收并完成项目' WHERE id IN (SELECT json_extract(body,'$.message_id') FROM workflow_events WHERE manager_task=?)",(run['task_id'],))
                self.hub.db.execute("UPDATE workflow_events SET status='handled' WHERE workflow=? AND manager_task=?",(w['id'],run['task_id']))
                self.hub.db.execute("UPDATE messages SET status='archived',lease=NULL,result='经理已结束本轮；未领取的回报归档，不代表已阅读' WHERE id IN (SELECT json_extract(body,'$.message_id') FROM workflow_events WHERE workflow=? AND status IN ('pending','claimed')) AND sender!='user' AND status IN ('pending','acknowledged','delivered','paused')",(w['id'],))
                self.hub.db.execute("UPDATE workflow_events SET status='archived' WHERE workflow=? AND status IN ('pending','claimed') AND (json_extract(body,'$.message_id') IS NULL OR json_extract(body,'$.message_id') NOT IN (SELECT id FROM messages WHERE sender='user' AND body NOT LIKE '[task:%'))",(w['id'],))
                self.hub.db.execute("UPDATE wakeups SET status='archived',note='本轮已结案；未领取回报归档' WHERE message IN (SELECT id FROM messages WHERE status='archived')")
                self.hub.db.execute("UPDATE wakeups SET status='completed',note='经理已处理' WHERE message IN (SELECT json_extract(body,'$.message_id') FROM workflow_events WHERE workflow=? AND status='handled')",(w['id'],))
                self.hub.db.execute("UPDATE wakeups SET status='held',note='用户新消息保留，等待独立处理' WHERE message IN (SELECT json_extract(body,'$.message_id') FROM workflow_events WHERE workflow=? AND status='pending')",(w['id'],))
                self.hub.db.execute("UPDATE settings SET value=? WHERE key='project'",(json.dumps({'progress':100,'note':summary,'by':actor,'updated':time.time()},ensure_ascii=False),))
                self.hub.audit(actor,'project.completed_mcp',{'project':w['id'],'run_id':run_id,'evidence':evidence})
                from .desktop_notifications import enqueue
                if not w.get('design_review'):enqueue(self.hub,'project:'+w['id'],'project',w.get('project_id') or w['id'])
                elif review_ready:enqueue(self.hub,'demo:'+review['id']+':'+str(review['version']),'demo',w.get('project_id'))
            return {'completed':True,'project_id':w['id'],'design_review_ready':review_ready,'warnings':warnings,'stopped_tasks':settled}

    def set_patrol(self,actor,workflow_id,enabled):
        self.hub.require(actor,{'user'})
        if type(enabled)!=bool:raise HubError('enabled 必须为布尔值')
        with self.lock:
            with self.hub.lock:row=self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(workflow_id,)).fetchone()
            if not row:raise HubError('项目不存在')
            w=json.loads(row[0]);w['patrol_enabled']=enabled;self.save(w)
            return {'workflow_id':workflow_id,'patrol_enabled':enabled}

    def resume(self,actor,workflow_id,message_id=None):
        self.hub.require(actor,{'user'})
        with self.lock:
            with self.hub.lock:row=self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(workflow_id,)).fetchone()
            if not row:raise HubError('项目不存在')
            w=json.loads(row[0])
            if w.get('superseded_by'):raise HubError('此轮已由新计划替代，不能恢复旧任务')
            if w['status'] not in ('paused','stopped'):raise HubError('仅能恢复已暂停或由用户停止的项目；停止锁须先由用户解除')
            from .project_activity import require_available
            require_available(self.hub,w.get('project_id'))
            self.valid({**w,'status':'active'})
            if message_id:
                with self.hub.lock:m=self.hub.db.execute('SELECT * FROM messages WHERE id=?',(message_id,)).fetchone()
                if not m or m['sender']!='user' or m['recipient']!=self.manager(w) or m['status']!='pending' or m['project_id']!=w.get('project_id'):raise HubError('请选择本项目待处理的用户消息')
            if w['status']=='stopped':
                steps=self.steps(w['id']);w['processed']=max([w.get('processed',0)]+[s['seq'] for s in steps if s['kind'] in ('plan','review') and s['status'] not in ACTIVE])
                w['manager_recoveries']=0;w['format_retries']=0
            w.update(status='active',pause_reason=None,phase='working',next_inspection=time.time()+self.patrol_seconds(),report='用户恢复项目；沿用原授权与会话')
            with self.hub.tx():
                self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
                if message_id:self.hub.db.execute("DELETE FROM wakeups WHERE message=? AND status='held'",(message_id,))
                self.hub.audit(actor,'project.resumed',{'project':workflow_id,'message':message_id})
            if message_id:self.hub.coordination.route(message_id)
            steps=self.steps(w['id'])
            if not any(s['agent']==self.manager(w) and (not s['run_id'] or s['status'] in ACTIVE) for s in steps):
                self.prepare_manager(w,steps,'用户已恢复项目。检查现场后继续，不重放历史执行。')
            return {'resumed':True,'project_id':workflow_id}

    def wake(self,actor,workflow_id,note=None):
        self.hub.require(actor,{'user'})
        with self.lock:
            with self.hub.lock:row=self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(workflow_id,)).fetchone()
            if not row:raise HubError('项目不存在')
            w=json.loads(row[0]);recovering=w['status'] in ('blocked','needs_attention')
            from .project_activity import require_available
            require_available(self.hub,w.get('project_id'))
            self.valid({**w,'status':'active'} if recovering else w);steps=self.steps(w['id'])
            if any((s['agent']==self.manager(w) and (not s['run_id'] or s['status'] in ACTIVE)) or s['status'] in ('running','interrupting','waiting_quota') for s in steps):return {'activated':False,'reason':'已有在途任务；没有重复唤醒'}
            if note is not None:text(note,2000)
            if recovering:
                # Explicit user recovery starts one inspection; never replays old executions.
                w['processed']=max([w['processed']]+[s['seq'] for s in steps if s['kind'] in ('plan','review') and s['status'] not in ACTIVE])
                w['manager_recoveries']=0;w['format_retries']=0
                with self.hub.tx():self.hub.db.execute("UPDATE workflow_events SET status='pending',manager_task=NULL WHERE workflow=? AND status='claimed'",(w['id'],))
            w['status']='active';w['idle_poked']=self.activity_key(steps);self.save(w)
            self.ingest(w,steps)
            task=self.prepare_manager(w,steps,(note+'\n' if note else '')+'请根据新消息安排后续；详细核查交给成员。')
            with self.hub.tx():self.hub.audit(actor,'project.manual_wake',{'project':w['id'],'task':task})
            return {'activated':True,'task_id':task}

    def switch_manager(self,actor,workflow_id=None,session_id=None,target_manager=None,inherit_context=True):
        self.hub.require(actor,{'user'})
        session=self.hub.planning.get(session_id) if session_id else None
        with self.lock:
            with self.hub.lock:row=self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(workflow_id or (session or {}).get('workflow_id'),)).fetchone()
            w=json.loads(row[0]) if row else None
            project=(w or session or {}).get('project_id')
            if project and getattr(self.hub,'integrations',None):
                return self.hub.integrations.set_manager(actor,project,target_manager)
            if session:return self.hub.planning.switch_manager(actor,session_id,target_manager,inherit_context)
            raise HubError('请选择要切换经理的项目')

    def pending_requires_wake(self,w):
        with self.hub.lock:
            types=[json.loads(r[0]).get('type') for r in self.hub.db.execute("SELECT body FROM workflow_events WHERE workflow=? AND status='pending'",(w['id'],))]
        if not types:return False
        if any(t not in ('agent_config_changed','quota_low','quota_recovered') for t in types):return True
        registry=getattr(self.hub,'integrations',None)
        return bool(registry and registry.project_is_running(w.get('project_id') or w['id']))

    def activity_key(self,steps):
        return json.dumps([[s['task'],s['status']] for s in steps if s['kind'] in ('work','message','check')])

    def notify_dependency_blocks(self,w,steps):
        by_task={step['task']:step for step in steps}
        for step in steps:
            parent=by_task.get(step.get('depends_on'))
            if not parent or step.get('status') not in (None,'queued','waiting_quota'):continue
            if parent.get('status') in (None,'completed',*ACTIVE):continue
            self.enqueue(w,'dependency-blocked:'+step['task']+':'+str(parent.get('run_id'))+':'+parent['status'],{'type':'dependency_blocked','body':'前置任务已结束但未成功，后续任务未启动，须经理核查后取消或重新分工；不得自动重放。','task_id':step['task'],'agent':step['agent'],'depends_on':parent['task'],'dependency_status':parent['status']})

    def advance(self,w):
        self.valid(w);w['patrolled']=time.time();self.save(w)
        steps=self.steps(w['id']);self.ingest(w,steps);steps=self.steps(w['id']);self.notify_dependency_blocks(w,steps)
        with self.hub.lock:current=json.loads(self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(w['id'],)).fetchone()[0])
        if current['status']!='active':return
        # Submit durable prepared work; never replay an existing execution.
        with self.hub.lock:
            urgent={r[0] for r in self.hub.db.execute("SELECT a.task FROM wakeups a JOIN messages m ON m.id=a.message WHERE a.workflow=? AND m.mode='immediate'",(w['id'],))} if getattr(self.hub,'coordination',None) else set()
        with self.hub.lock:queue_positions={r[0]:r[1] for r in self.hub.db.execute('SELECT p.item_id,p.position FROM project_queue_positions p JOIN workflow_steps s ON s.task=p.item_id WHERE s.workflow=?',(w['id'],))}
        for s in sorted(steps,key=lambda s:(s['task'] not in urgent,queue_positions.get(s['task'],1e12+s['seq']))):
            if not s['run_id']:
                with self.hub.lock:
                    title=self.hub.db.execute('SELECT title FROM tasks WHERE id=?',(s['task'],)).fetchone()[0]
                    source=self.hub.db.execute('SELECT message,note FROM wakeups WHERE task=?',(s['task'],)).fetchone() if getattr(self.hub,'coordination',None) else None
                purpose='task'
                if source:
                    with self.hub.lock:sender=self.hub.db.execute('SELECT sender FROM messages WHERE id=?',(source[0],)).fetchone()[0]
                    purpose='task' if source[1]=='定时器在现有授权内投递' or sender==self.manager(w) else 'question'
                self.runtime(s['agent']).submit('user',s['agent'],title,True,s['task'],source_message_id=source[0] if source else None,purpose=purpose);return
        managers=[s for s in steps if s['kind'] in ('plan','review') and s['seq']>w['processed']]
        if managers:
            manager=managers[0]
            if manager['status'] in ACTIVE:return
            if manager['status']!='completed':
                with self.hub.lock:
                    local_error=self.hub.db.execute("SELECT data FROM execution_events WHERE run_id=? AND kind='deepseek.harness.internal_error' ORDER BY seq DESC LIMIT 1",(manager['run_id'],)).fetchone()
                if local_error:
                    w.update(status='blocked',phase='adapter_error',report='本地执行器错误，已停止自动重复唤醒；修复后可恢复，原会话和消息保留。'+json.loads(local_error[0]).get('error',''),processed=manager['seq'])
                    self.save(w)
                    with self.hub.tx():self.hub.db.execute("UPDATE workflow_events SET status='pending',manager_task=NULL WHERE manager_task=?",(manager['task'],))
                    return
                with self.hub.lock:
                    preempted=self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='manager_preemptions'").fetchone() and self.hub.db.execute('SELECT 1 FROM manager_preemptions WHERE run_id=?',(manager['run_id'],)).fetchone()
                if preempted:
                    w['processed']=manager['seq']
                    with self.hub.tx():self.hub.db.execute("UPDATE workflow_events SET status='pending',manager_task=NULL WHERE manager_task=?",(manager['task'],))
                    self.save(w);self.prepare_manager(w,steps,'用户插入新消息，上一轮已结束。先查现场，优先处理新消息，不重放已派任务。');return
                if w.get('manager_recoveries',0)>=2:raise HubError('项目经理连续恢复失败，保留现场')
                w['manager_recoveries']=w.get('manager_recoveries',0)+1;w['processed']=manager['seq']
                with self.hub.tx():self.hub.db.execute("UPDATE workflow_events SET status='pending',manager_task=NULL WHERE manager_task=?",(manager['task'],))
                self.save(w);self.prepare_manager(w,steps,'上轮异常；请安排成员核查后继续，不重放旧任务。');return
            try:plan=proposal(manager['result'],allow_idle=True)
            except HubError as error:
                # Provider-confirmed natural language is a valid reply. It does not
                # imply task assignment or project completion, and needs no model retry.
                plan={'done':False,'tasks':[],'report':str(manager['result'] or '本轮未返回文字')}
                with self.hub.tx():self.hub.audit(self.manager(w),'project.manager_text_reply',{'project':w['id'],'run':manager['run_id'],'format_note':str(error)})
            if manager['kind']=='plan' and plan['done']:raise HubError('首次分工不能声称已完成')
            if plan['tasks']:
                reserve=2 if w.get('reviewer',self.manager(w))!=self.manager(w) else 1
                for index,t in enumerate(plan['tasks']):self.dispatch(w,t['agent'],t['instruction'],'json:'+manager['run_id']+':'+str(index))
            with self.hub.tx():
                self.hub.db.execute("UPDATE messages SET status='completed',result='项目经理 已处理此汇报' WHERE id IN (SELECT json_extract(body,'$.message_id') FROM workflow_events WHERE manager_task=?)",(manager['task'],))
                self.hub.db.execute("UPDATE workflow_events SET status='handled' WHERE manager_task=?",(manager['task'],))
                self.hub.db.execute("UPDATE wakeups SET status='completed',note='经理本轮已结束，汇报已送达' WHERE message IN (SELECT json_extract(body,'$.message_id') FROM workflow_events WHERE manager_task=?)",(manager['task'],))
                w.update(next_inspection=time.time()+self.patrol_seconds(),processed=manager['seq'],report=plan['report'],phase='waiting_resource' if w.get('resource_wait') else 'working',manager_recoveries=0)
                self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
            if plan['done']:
                try:
                    outcome=self.project_complete(self.manager(w),manager['run_id'],plan['report'],['经理核对执行与独立检查记录后提交验收'])
                    if outcome.get('confirmation_required'):self.prepare_manager(w,self.steps(w['id']),'完成尚未确认，请先核对测试情况，再通过project_complete两步提交；自然语言done不代替确认。')
                except HubError as error:
                    with self.hub.lock:incoming=self.hub.db.execute("SELECT 1 FROM workflow_events WHERE workflow=? AND status='pending'",(w['id'],)).fetchone()
                    if incoming:
                        # New mail is normal scheduling, not a failed acceptance retry.
                        w['acceptance_corrections']=0;self.save(w)
                        self.prepare_manager(w,self.steps(w['id']));return
                    if w.get('acceptance_corrections',0)>=2:raise
                    w['acceptance_corrections']=w.get('acceptance_corrections',0)+1;w['report']='已退回 项目经理：'+str(error);self.save(w)
                    self.prepare_manager(w,self.steps(w['id']),'已退回 项目经理：完成未被确认，'+str(error)+'。请处理新消息、安排核查或修复。')
                return
            # Drain already-finished manager turns before creating another invocation.
            if any(s['kind'] in ('plan','review') and s['seq']>w['processed'] for s in self.steps(w['id'])):return
            # Completion events arriving during this manager turn remain pending.
            steps=self.steps(w['id'])
        if any(s['kind'] in ('plan','review') and (not s['run_id'] or s['status'] in ACTIVE) for s in steps):return
        if w.get('return_manager'):
            target=w['return_manager'].get('target')
            registry=getattr(self.hub,'integrations',None)
            if target and registry and not registry.busy([self.manager(w),target]):
                registry.set_manager('user',w['project_id'],target)
            return
        live=[s for s in steps if not s['run_id'] or s['status'] in ACTIVE]
        blocked=[]
        for step in live:
            if step.get('depends_on'):
                prior=next((x for x in steps if x['task']==step['depends_on']),None)
                if prior and prior['status'] not in ACTIVE and prior['status']!='completed':
                    blocked.append(step)
                    self.enqueue(w,'dependency:'+step['task']+':'+str(prior['status']),{'type':'blocked_dependency','task':step['task'],'agent':step['agent'],'after_task':prior['task'],'prior_status':prior['status'],'action':'前置未成功，后续任务未启动；请经理核查、取消排队或安排安全替代任务'})
        work=[s for s in steps if s['kind'] in ('work','message')]
        coverage=[[s['run_id'],s['status']] for s in work]
        reviewer=w.get('reviewer',self.manager(w))
        uncertain=[s for s in work if s['status'] in ('uncertain','interrupted','cancelled')]
        # Only the manager creates check tasks. Notify it once per changed outcome.
        if not live and work and w.get('manager_review_notice')!=coverage:
            self.enqueue(w,'review-needed:'+str(len(steps)),{'type':'review_needed','body':'成员执行已结束。请核查新产物与风险，由你决定检查者及检查范围；平台不自动派发复核。异常执行不得直接视为成功。'})
            w['manager_review_notice']=coverage;self.save(w)
        with self.hub.lock:pending=self.hub.db.execute("SELECT 1 FROM workflow_events WHERE workflow=? AND status='pending'",(w['id'],)).fetchone()
        if pending and self.pending_requires_wake(w):
            self.prepare_manager(w,steps);return
        if blocked and len(blocked)==len(live):
            w['status']='needs_attention';w['report']='前置执行未成功，后续队列已保留；经理检查后仍未处理，可唤醒 项目经理 再检查';self.save(w);return
        # Durable timer: no catch-up bursts; message-driven scheduling above stays immediate.
        waiting=w.get('resource_wait')
        if waiting and getattr(self.hub,'automation',None):
            timer=next((t for t in self.hub.automation.timers(w.get('project_id') or w['id']) if t['id']==waiting['timer_id']),None)
            if timer and timer['state'] in ('scheduled','held'):return
        if not w.get('patrol_enabled',True) or not self.patrol_config()['enabled']:return
        due=w.get('next_inspection')
        if due is None:
            w['next_inspection']=time.time()+self.patrol_seconds();self.save(w);return
        if time.time()>=due:
            self.prepare_manager(w,steps,periodic=True)
