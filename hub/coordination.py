"""Persistent emergency latches and bounded in-project agent message wakes."""
import json
import time
from .core import HubError,text,uid
from .identities import AGENTS

ACTIVE={'queued','waiting_quota','running','interrupting'}

class Coordination:
    def __init__(self,hub,runtimes,workflows):
        self.hub=hub;self.runtimes=runtimes;self.workflows=workflows
        with hub.tx():
            hub.db.execute('CREATE TABLE IF NOT EXISTS agent_stops(agent TEXT PRIMARY KEY,reason TEXT,actor TEXT,ts REAL)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS wakeups(message TEXT PRIMARY KEY,workflow TEXT,task TEXT,root TEXT,depth INTEGER,status TEXT,note TEXT)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS worker_reports(run TEXT PRIMARY KEY,summary TEXT,risk TEXT,evidence TEXT)')
        hub.coordination=self

    def snapshot(self,actor):
        from .manager_identity import managers
        self.hub.require(actor,{'user'}|managers(self.hub))
        with self.hub.lock:
            return {'stops':[dict(r) for r in self.hub.db.execute('SELECT * FROM agent_stops')],
                'wakeups':[dict(r) for r in self.hub.db.execute('SELECT * FROM wakeups ORDER BY rowid DESC LIMIT 60')],
                'reports':[dict(r) for r in self.hub.db.execute('SELECT r.*,e.finished created FROM worker_reports r LEFT JOIN executions e ON e.id=r.run ORDER BY e.finished DESC LIMIT 30')]}

    def is_stopped(self,agent):
        with self.hub.lock:return bool(self.hub.db.execute("SELECT 1 FROM agent_stops WHERE agent IN ('*',?)",(agent,)).fetchone())

    def halt(self,actor,agent='*',reason='用户紧急停止'):
        text(reason,1000)
        if agent!='*':self.hub.agent(agent)
        with self.workflows.lock:
            projects=self.workflows.records(statuses=('active','needs_attention'))
            if actor!='user':
                if not any(actor==self.workflows.manager(w) for w in projects):raise HubError('此身份没有紧急停止权限')
                owned=[w for w in projects if w.get('delegate_stop') and self.workflows.manager(w)==actor]
                if not owned or agent=='*':raise HubError('模型只能停止用户授权项目内的一个参与者；全局停止仅用户可用')
                if not any(agent in [self.workflows.manager(w)]+w['agents'] for w in owned):raise HubError('不能停止项目之外的 Agent')
            with self.hub.tx():
                self.hub.db.execute('INSERT OR REPLACE INTO agent_stops VALUES(?,?,?,?)',(agent,reason,actor,time.time()))
                self.hub.audit(actor,'emergency.halt',{'agent':agent,'reason':reason})
                for w in projects:
                    if agent=='*' or agent in [self.workflows.manager(w)]+w['agents']:
                        w.pop('steps',None);w['status']='stopped';w['report']='紧急止损：'+actor+' 停止 '+agent+'：'+reason
                        self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
                targets=[r[0] for r in self.hub.db.execute('SELECT id FROM agents')] if agent=='*' else [agent]
                # Halt affected projects too: another queued step must not revive the stopped work.
                project_ids=[w['id'] for w in projects if agent=='*' or agent in [self.workflows.manager(w)]+w['agents']]
                rows=[dict(r) for r in self.hub.db.execute("SELECT * FROM executions WHERE status IN ('queued','waiting_quota','running','interrupting')")]
                affected=[]
                for r in rows:
                    step=self.hub.db.execute('SELECT workflow FROM workflow_steps WHERE task=?',(r['task_id'],)).fetchone()
                    if r['agent'] in targets or (step and step[0] in project_ids and r['status'] in ('queued','waiting_quota')):affected.append(r)
                for r in affected:
                    if r['status'] in ('queued','waiting_quota'):
                        self.hub.db.execute("UPDATE executions SET status='cancelled',finished=?,result='紧急停止，未启动模型' WHERE id=?",(time.time(),r['id']))
                        self.hub.db.execute("UPDATE messages SET status='cancelled' WHERE id=?",(r['message_id'],))
                        self.hub.db.execute("UPDATE tasks SET status='blocked',note='紧急停止' WHERE id=?",(r['task_id'],))
                    else:self.hub.db.execute('UPDATE executions SET stop_requested=1 WHERE id=?',(r['id'],))
                if agent in ('*','deepseek-9'):
                    self.hub.db.execute("UPDATE calls SET status='cancelled' WHERE status IN ('pending','approved')")
                    self.hub.db.execute("UPDATE calls SET status='uncertain',result='紧急停止；已发送的官方 API 请求无法确认取消' WHERE status='running'")
                for target in targets:
                    active=self.hub.agent(target)['active']
                    if active and not any(r['message_id']==active for r in rows):
                        self.hub.db.execute("UPDATE messages SET status='paused',lease=NULL WHERE id=?",(active,))
                        self.hub.db.execute("UPDATE agents SET active=NULL,status='idle' WHERE id=?",(target,))
            for r in affected:
                if r['status'] in ('running','interrupting'):
                    rt=next((runtime for runtime in self.runtimes if runtime.provider==r['provider']),None)
                    if rt is None:
                        self.workflows.stop_run('user',r);continue
                    client=rt.clients.get(r['id']) or (rt.active_client if getattr(rt,'active_run',None)==r['id'] else None)
                    # Kill only Hub-owned local process trees. Never claim server-side cancellation.
                    if client:
                        if getattr(client,'job',None):client.job.close()
                        proc=getattr(client,'proc',None)
                        if proc and proc.poll() is None:
                            try:proc.terminate()
                            except OSError:pass
            return {'latched':True,'agent':agent,'local_stop_requested':True,'server_cancel_confirmed':False}

    def resume(self,actor,agent='*'):
        self.hub.require(actor,{'user'})
        with self.hub.tx():
            self.hub.db.execute('DELETE FROM agent_stops WHERE agent=?',(agent,))
            self.hub.audit(actor,'emergency.resume',{'agent':agent,'replay':False})
        return {'ok':True,'note':'仅解除启动锁；已停止项目和任务不会自动重放'}

    def prioritize(self,recipient,project_id,exclude=(),actor='平台',cause='高优先级通知',force=False):
        """Interrupt only the receiving project's current turn; preserve its queue."""
        with self.workflows.lock:
            with self.hub.tx():
                self.hub.db.execute('CREATE TABLE IF NOT EXISTS message_preemption_deliveries(message_id TEXT PRIMARY KEY)')
                if exclude and all(self.hub.db.execute('SELECT 1 FROM message_preemption_deliveries WHERE message_id=?',(ident,)).fetchone() for ident in exclude):return 0
                self.hub.db.execute('CREATE TABLE IF NOT EXISTS manager_preemptions(run_id TEXT PRIMARY KEY,project_id TEXT,created REAL)')
                rows=[dict(r) for r in self.hub.db.execute("SELECT e.* FROM executions e JOIN tasks t ON t.id=e.task_id WHERE e.agent=? AND (t.project_id=? OR EXISTS(SELECT 1 FROM workflow_steps s JOIN workflows w ON w.id=s.workflow WHERE s.task=e.task_id AND json_extract(w.body,'$.project_id')=?)) AND e.status IN ('running','interrupting')",(recipient,project_id,project_id)) if r['message_id'] not in exclude]
                self.hub.db.execute('CREATE TABLE IF NOT EXISTS message_preemptions(run_id TEXT PRIMARY KEY,actor TEXT,cause TEXT,message_id TEXT)')
                for row in rows:
                    self.hub.db.execute('INSERT OR IGNORE INTO manager_preemptions VALUES(?,?,?)',(row['id'],project_id,time.time()))
                    self.hub.db.execute('INSERT OR REPLACE INTO message_preemptions VALUES(?,?,?,?)',(row['id'],actor,cause,next(iter(exclude),None)))
                    self.hub.db.execute('UPDATE executions SET stop_requested=1 WHERE id=?',(row['id'],))
                    self.hub.audit(actor,row['provider']+'.stop_requested',{'run_id':row['id'],'cause':cause,'source':'message_preemption','recipient':recipient,'project_id':project_id})
                for ident in exclude:self.hub.db.execute('INSERT OR IGNORE INTO message_preemption_deliveries VALUES(?)',(ident,))
            if force:
                for row in rows:
                    context=self.hub.db.execute('SELECT w.body FROM workflows w JOIN workflow_steps s ON s.workflow=w.id WHERE s.task=?',(row['task_id'],)).fetchone()
                    if context:self.workflows._stop_task(json.loads(context[0]),row['task_id'],actor,cause)
                    else:
                        rt=next((r for r in self.runtimes if r.provider==row['provider']),None)
                        if rt:rt.stop('user',row['id'])
            return len(rows)

    def send(self,actor,recipient,body,mode='queue',request_key=None,project_id=None):
        if project_id and actor == 'user' and getattr(self.hub,'projects',None):
            self.hub.projects.get(project_id)
        if not project_id and getattr(self.hub,'workflows',None):
            w = None
            if actor == 'user':
                w = next(iter(self.workflows.records(statuses=('active','needs_attention','blocked','paused','executing'))), None)
            else:
                w, _ = self.context({'sender': actor, 'request_key': request_key})
                if not w:
                    w = next(iter(self.workflows.records(statuses=('active','needs_attention','blocked','paused','executing'))), None)
            if w:
                project_id = w.get('project_id') or w.get('id')
        if mode=='immediate' and actor!='user':
            owned,_=self.context({'sender':actor,'request_key':request_key})
            if not owned or actor!=self.workflows.manager(owned) or recipient not in owned['agents']:raise HubError('只有当前项目经理可中断本项目已授权成员')
            project_id=owned.get('project_id') or owned['id']
        with self.workflows.lock,self.hub.lock:
            ids=self.hub.send(actor,recipient,body,mode,request_key)
            if project_id:
                with self.hub.tx():
                    for ident in ids:self.hub.db.execute('UPDATE messages SET project_id=? WHERE id=?',(project_id,ident))
            if mode=='immediate' and project_id:self.prioritize(recipient,project_id,ids,actor=actor,cause='immediate 消息主动打断',force=actor!='user')
            for ident in ids:self.route(ident)
            return ids

    def context(self,message):
        key=message['request_key'] or ''
        with self.hub.lock:
            if key.startswith('execution:'):
                parts=key.split(':');run=self.hub.db.execute('SELECT * FROM executions WHERE id=?',(parts[1],)).fetchone()
            else:run=self.hub.db.execute("SELECT * FROM executions WHERE agent=? AND status IN ('running','interrupting') ORDER BY created DESC LIMIT 1",(message['sender'],)).fetchone()
            if message.get('project_id'):
                run=self.hub.db.execute("SELECT e.* FROM executions e JOIN workflow_steps s ON s.task=e.task_id JOIN workflows w ON w.id=s.workflow WHERE e.agent=? AND json_extract(w.body,'$.project_id')=? ORDER BY e.created DESC LIMIT 1",(message['sender'],message['project_id'])).fetchone()
            if not run or run['agent']!=message['sender']:return None,None
            step=self.hub.db.execute('SELECT workflow FROM workflow_steps WHERE task=?',(run['task_id'],)).fetchone()
            if not step:return None,None
            row=self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(step[0],)).fetchone()
            return (json.loads(row[0]) if row else None),dict(run)

    def route(self,ident,project=None,source_run=None):
        with self.workflows.lock:
            with self.hub.lock:
                prior=self.hub.db.execute('SELECT status,note FROM wakeups WHERE message=?',(ident,)).fetchone()
                row=self.hub.db.execute('SELECT * FROM messages WHERE id=?',(ident,)).fetchone()
            if not row or row['recipient']=='user' or row['status']!='pending':return
            # Manager discussion inputs have a single owner, including while a
            # reply is running. Generic wakeups must not execute them a second time.
            with self.hub.lock:
                owned=self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='manager_discussion_inputs'").fetchone()
                if owned and self.hub.db.execute('SELECT 1 FROM manager_discussion_inputs WHERE message_id=?',(ident,)).fetchone():return
            m=dict(row)
            if prior and prior['status']!='held':return
            if m['body'].startswith('[task:'):return
            w,run=(project,source_run) if project else self.context(m)
            if m['sender']=='user' and not w:
                w=next((x for x in self.workflows.records(project_id=m.get('project_id')) if (x['status'] in ('active','needs_attention','blocked','paused','stopped') or (x['status']=='completed' and m['recipient']==self.workflows.manager(x) and m.get('project_id')==x.get('project_id'))) and m['recipient'] in [self.workflows.manager(x)]+x['agents']),None)
                run={'task_id':None} if w else None
                # Completed projects remain available for dialogue. Keep their identity
                # and context without reopening implementation or replaying old work.
            if w:
                from .project_activity import owner
                active_project=owner(self.hub)
                if active_project and active_project!=w.get('project_id'):
                    with self.hub.tx():self.hub.db.execute('INSERT OR REPLACE INTO wakeups VALUES(?,?,?,?,?,?,?)',(ident,w['id'],None,ident,0,'held','另一项目正在执行；消息保留，稍后处理'))
                    return
                if w['status']=='needs_attention':w['status']='active';w['idle_poked']=self.workflows.activity_key(self.workflows.steps(w['id']));self.workflows.save(w)
            recover_manager=bool(w and w['status']=='blocked' and m['sender']=='user' and m['recipient']==self.workflows.manager(w))
            if recover_manager:
                try:
                    self.workflows.valid({**w,'status':'active'})
                    self.workflows.enqueue(w,'message:'+ident,{'type':'message','message_id':ident,'from':m['sender'],'body':m['body']})
                    recovered=self.workflows.wake('user',w['id'])
                    with self.hub.tx():self.hub.db.execute('INSERT OR REPLACE INTO wakeups VALUES(?,?,?,?,?,?,?)',(ident,w['id'],None,ident,0,'batched','用户新消息已请求经理处理；保持原授权，不重放旧执行'))
                    return
                except HubError:pass
            if w and run and m['recipient']==self.workflows.manager(w) and m['sender'] in w['agents'] and w['status'] in ('active','needs_attention','paused','blocked'):
                self.workflows.enqueue(w,'message:'+ident,{'type':'message','message_id':ident,'from':m['sender'],'body':m['body']},run.get('id'))
                with self.hub.tx():self.hub.db.execute('INSERT OR REPLACE INTO wakeups VALUES(?,?,?,?,?,?,?)',(ident,w['id'],None,ident,0,'batched','已进入经理收件箱；调度恢复或空闲后优先处理'))
                return
            status='held';note='没有有效的项目消息授权；消息保留，不启动模型';task=None;depth=0;root=ident
            if w and run:
                with self.hub.lock:parent=self.hub.db.execute('SELECT * FROM wakeups WHERE task=?',(run['task_id'],)).fetchone()
                if parent:depth=parent['depth']+1;root=parent['root']
                if run.get('purpose')=='question':
                    with self.hub.lock:origin=self.hub.db.execute('SELECT sender FROM messages WHERE id=?',(run['message_id'],)).fetchone()
                    if origin and m['recipient'] not in (self.workflows.manager(w),origin[0]):
                        with self.hub.tx():self.hub.db.execute('INSERT OR IGNORE INTO wakeups VALUES(?,?,?,?,?,?,?)',(ident,w['id'],None,root,depth,'held','质询只允许回复原提问者或上报 项目经理，不能扩展自行分工链'))
                        return
                if w['status']=='active' and time.time()<w['expires']:
                    members=[self.workflows.manager(w)]+w['agents']
                    if (m['sender'] in members or m['sender']=='user') and m['recipient'] in members and not self.is_stopped(m['recipient']):
                        if m['recipient'] in (self.workflows.manager(w),):
                            status='batched';note='进入 项目经理 收件箱；空闲领取，忙碌时累积'
                            if not (m['request_key'] or '').startswith(('execution:','report:')):
                                self.workflows.enqueue(w,'message:'+ident,{'type':'message','message_id':ident,'from':m['sender'],'body':m['body'][:2000]},run.get('id'))
                        else:
                            count=self.hub.db.execute('SELECT count(*) FROM wakeups WHERE workflow=?',(w['id'],)).fetchone()[0]
                            steps=self.workflows.steps(w['id']);reserve=2 if w.get('reviewer',self.workflows.manager(w))!=self.workflows.manager(w) else 1
                            if depth>=w.get('max_hops',4) or count>=w.get('max_messages',12):note='触发消息链/项目消息数上限，不再唤醒'
                            else:
                                task=self.workflows.add_step(w,m['recipient'],'message',m['body'],source_message_id=ident,wake_context={'root':root,'depth':depth})
                                status='queued';note='已在原项目授权内唤醒接收方'
            # Direct dialogue is independent of the project's implementation gate.
            # Never replay tasks, clear stop latches, or auto-reply to generated receipts.
            if status=='held' and not (m['request_key'] or '').startswith(('execution:','report:')):
                eligible=m['sender']=='user' or (w and w['status']=='active' and run and m['sender'] in [self.workflows.manager(w)]+w['agents'] and m['recipient'] in [self.workflows.manager(w)]+w['agents'] and time.time()<w['expires'] and depth<w.get('max_hops',4))
                if eligible:
                    try:
                        if self.is_stopped(m['recipient']):raise HubError('紧急停止锁有效；请先解除该Agent的停止锁')
                        if m['sender']!='user':
                            count=self.hub.db.execute('SELECT count(*) FROM wakeups WHERE workflow=?',(w['id'],)).fetchone()[0]
                            if count>=w.get('max_messages',12):raise HubError('项目消息数上限已达，保留消息')
                        rt=self.workflows.runtime(m['recipient'])
                        scope='project:'+w['id'] if w else ('chat:'+m['project_id'] if m.get('project_id') else 'chat:default')
                        from .module_sdk import working_directory
                        project_id=m.get('project_id') or (w or {}).get('project_id')
                        target=self.hub.projects.get(project_id)['cwd'] if project_id and getattr(self.hub,'projects',None) else (w or {}).get('cwd',rt.config()['cwd'])
                        target=working_directory(target,'项目工作目录')
                        # Fence worker pickup until this execution is bound to its
                        # project; shared runtime defaults may belong to another one.
                        with self.hub.lock:
                            job=rt.submit('user',m['recipient'],m['body'],True,source_message_id=ident,purpose='task' if m['sender']=='user' else 'question',session_scope=scope)
                            with self.hub.tx():self.hub.db.execute('UPDATE executions SET cwd=? WHERE id=?',(target,job['id']))
                        task=job['task_id'];status='queued';note='消息已唤醒；忙碌时排队。按本轮新请求处理，不自动恢复旧项目执行'
                    except HubError as error:note=str(error)
            if prior and status=='held' and prior['note']==note:return
            with self.hub.tx():
                self.hub.db.execute('INSERT OR REPLACE INTO wakeups VALUES(?,?,?,?,?,?,?)',(ident,w['id'] if w else None,task,root,depth,status,note))
                self.hub.audit('supervisor','message.wake_'+status,{'message':ident,'depth':depth,'note':note})

    def report(self,run,status,result):
        with self.hub.lock:
            if self.hub.db.execute('SELECT 1 FROM worker_reports WHERE run=?',(run['id'],)).fetchone():return
            step=self.hub.db.execute('SELECT * FROM workflow_steps WHERE task=?',(run['task_id'],)).fetchone()
            if not step or step['kind'] in ('plan','review'):return
            row=self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(step['workflow'],)).fetchone();w=json.loads(row[0])
        # Worker chooses its concise report. Full result remains in executions, never discarded.
        with self.hub.lock:own=self.hub.db.execute('SELECT body FROM model_reports WHERE run=?',(run['id'],)).fetchone()
        if own:result=own[0]
        with self.hub.lock:
            table=self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='message_preemptions'").fetchone()
            preempt=self.hub.db.execute('SELECT actor,cause FROM message_preemptions WHERE run_id=?',(run['id'],)).fetchone() if table else None
        if preempt and status!='completed':result=json.dumps({'summary':preempt['actor']+' 主动打断本轮以插入高优先级消息；不是平台随机故障。原工作未确认完成，需结合新消息续接或改派。','risk':'high','evidence':[preempt['cause'],str(result)[:1000]]},ensure_ascii=False)
        try:data=json.loads(result.strip().removeprefix('```json').removesuffix('```').strip())
        except (ValueError,TypeError):
            data={}
            # Some official runtimes prefix their final JSON with commentary.
            if isinstance(result,str):
                decoder=json.JSONDecoder()
                for i,c in enumerate(result):
                    if c!='{':continue
                    try:candidate,end=decoder.raw_decode(result[i:])
                    except ValueError:continue
                    if isinstance(candidate,dict) and isinstance(candidate.get('summary'),str) and not result[i+end:].strip().strip('`'):data=candidate;break
        structured=isinstance(data,dict) and isinstance(data.get('summary'),str)
        summary=data['summary'][:800] if structured else (str(result).strip()[:600] or '本轮未返回文字结果。')+'（平台未独立核实，待经理验收）'
        risk=data.get('risk','unknown') if structured else 'unknown'
        if risk not in ('low','high','blocked','unknown'):risk='unknown'
        if status!='completed':risk='high'
        evidence=data.get('evidence',[]) if structured else []
        if not isinstance(evidence,list):evidence=[]
        git=getattr(self.workflows,'git',None)
        change=git.finish(run,status) if git else None
        if change:
            evidence=['Git '+json.dumps(change,ensure_ascii=False)]+evidence
            if change['status'] in ('error','conflict'):risk='high'
        with self.hub.tx():self.hub.db.execute('INSERT OR IGNORE INTO worker_reports VALUES(?,?,?,?)',(run['id'],summary,risk,json.dumps(evidence,ensure_ascii=False)[:3000]))
        if w['status'] in ('active','paused','needs_attention','blocked') and step['kind'] in ('work','message','check'):
            report_id=self.hub.send(run['agent'],self.workflows.manager(w),'[主动汇报] '+json.dumps({'run':run['id'],'status':status,'summary':summary,'risk':risk,'evidence':evidence},ensure_ascii=False)[:5000],request_key='report:'+run['id'])[0]
            with self.hub.tx():
                self.hub.db.execute('UPDATE messages SET project_id=? WHERE id=?',(w.get('project_id') or w['id'],report_id))
                self.hub.db.execute('INSERT OR IGNORE INTO wakeups VALUES(?,?,?,?,?,?,?)',(report_id,w['id'],None,report_id,0,'batched','主动汇报已入队；项目经理 空闲即领取'))
        if structured and w['status']=='active' and step['kind'] in ('work','message','check'):
            messages=data.get('messages',[])
            if isinstance(messages,list):
                for i,item in enumerate(messages[:4]):
                    if not isinstance(item,dict) or item.get('recipient') not in [self.workflows.manager(w)]+w['agents']:continue
                    body=item.get('body')
                    if not isinstance(body,str) or not 0<len(body)<=2000:continue
                    ident=self.hub.send(run['agent'],self.workflows.manager(w) if step['kind']=='check' else item['recipient'],('检查建议给 '+item['recipient']+'：' if step['kind']=='check' else '')+body,request_key='worker:'+run['id']+':'+str(i))[0]
                    self.route(ident,w,run)
            if w.get('delegate_stop') and run['agent']==self.workflows.manager(w):
                for target in data.get('stop_agents',[])[:3] if isinstance(data.get('stop_agents'),list) else []:
                    if target in [self.workflows.manager(w)]+w['agents']:
                        self.halt(run['agent'],target,'模型报告严重问题：'+summary[:500]);break

    def patrol(self):
        from .message_receipts import reconcile
        if time.monotonic() >= getattr(self,'next_receipt_check',0):
            self.next_receipt_check=time.monotonic()+5
            reconcile(self.hub)

        with self.hub.lock:
            stranded=[dict(r) for r in self.hub.db.execute("SELECT m.id,a.workflow,w.body FROM messages m JOIN wakeups a ON a.message=m.id JOIN workflows w ON w.id=a.workflow WHERE m.sender='user' AND m.status='pending' AND a.status='batched' AND json_extract(w.body,'$.status')='blocked' ORDER BY m.created LIMIT 20")]
        for item in stranded:
            w=json.loads(item['body'])
            try:self.workflows.wake('user',w['id'])
            except HubError:pass
        with self.hub.lock:
            rows=[dict(r) for r in self.hub.db.execute("SELECT e.* FROM executions e JOIN workflow_steps s ON s.task=e.task_id WHERE s.kind IN ('work','message','check') AND e.status NOT IN ('queued','running','waiting_quota','interrupting') AND e.result IS NOT NULL AND e.id NOT IN (SELECT run FROM worker_reports) ORDER BY e.created LIMIT 30")]
        for run in rows:self.report(run,run['status'],run['result'])
        with self.hub.lock:pending=[r[0] for r in self.hub.db.execute("SELECT id FROM messages WHERE status='pending' AND recipient!='user' AND body NOT LIKE '[task:%' AND (id NOT IN (SELECT message FROM wakeups) OR (id IN (SELECT message FROM wakeups WHERE status='held'))) ORDER BY CASE mode WHEN 'immediate' THEN 0 ELSE 1 END,coalesce((SELECT position FROM project_queue_positions WHERE item_id=messages.id),created),created LIMIT 50")]
        for ident in pending:self.route(ident)
