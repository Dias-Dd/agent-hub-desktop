from hub.module_sdk import host_resource
from hub.manager_identity import resolve as project_manager
"""Official Codex App Server execution; OAuth only, durable per-task grants.

One model turn per authorized job; never automatically replay uncertain jobs.
"""
import json
import os
from pathlib import Path
import queue
import shutil
from hub.cli_paths import which
import sys
import subprocess
import threading
import time
from hub.core import HubError, number, text, uid
from hub.process_job import ProcessJob
from hub.sessions import Sessions

class QuotaWait(HubError):
    def __init__(self,resets):
        super().__init__('官方额度耗尽，等待实际恢复后重新核实，不启动推理');self.resets=resets

MODELS={'deepseek-6':'gpt-6.1-sol','deepseek-7':'gpt-6.1-sol','deepseek-8':'gpt-6-astra'}

def codex_executable():
    found=which('codex')
    if found:return found
    if sys.platform=='darwin':
        for base in (Path('/Applications'),Path.home()/'Applications'):
            for app in ('Codex.app','ChatGPT.app'):
                candidate=base/app/'Contents/Resources/codex-cli/bin/codex'
                if candidate.is_file():return str(candidate)
    local=os.environ.get('LOCALAPPDATA')
    root=Path(local)/'OpenAI/Codex/bin' if local else None
    candidates=list(root.glob('*/codex.exe')) if root and root.is_dir() else []
    return str(max(candidates,key=lambda p:p.stat().st_mtime)) if candidates else None

class AppServer:
    hub_transport="codex"
    def __init__(self,cwd,mcp=None,run_env=None,executable_path=None):
        exe=executable_path or codex_executable()
        if not exe:raise HubError('未安装官方 Codex CLI')
        env={k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','DEEPSEEK_API_KEY','HUB_TOKEN')}
        from hub.cli_paths import child_environment
        env=child_environment(env)
        env.update(run_env or {})
        args=[exe,'app-server','--stdio']
        if mcp:
            for key,value in {**mcp,'default_tools_approval_mode':'approve'}.items():args+=['-c','mcp_servers.agent_hub.'+key+'='+json.dumps(value)]
        self.proc=subprocess.Popen(args,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1,start_new_session=os.name!='nt',creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000) if os.name == 'nt' else 0)
        try:self.job=ProcessJob(self.proc)
        except Exception:
            self.proc.terminate();self.proc.wait(timeout=5)
            self.proc.stdin.close();self.proc.stdout.close()
            raise HubError('无法建立 CLI 进程守护；未启动模型') from None
        self.inbox=queue.Queue();self.pending=[];self.counter=0;self.closed=False
        def read():
            try:
                for line in self.proc.stdout:
                    try:self.inbox.put(json.loads(line))
                    except ValueError:pass
            finally:self.inbox.put({'_eof':True})
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        try:
            self.rpc('initialize',{'clientInfo':{'name':'agent_message_hub_runtime','version':'0.2.0'}})
            self.write({'method':'initialized','params':{}})
        except Exception:
            self.close()
            raise

    def write(self,value):
        self.proc.stdin.write(json.dumps(value,ensure_ascii=False)+'\n');self.proc.stdin.flush()

    def rpc(self,method,params,timeout=25):
        self.counter+=1;ident=self.counter;self.write({'id':ident,'method':method,'params':params});deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:item=self.inbox.get(timeout=max(.01,deadline-time.monotonic()))
            except queue.Empty:break
            if item.get('_eof'):raise HubError('Codex 官方进程已断开；不自动重试')
            if item.get('id')==ident and 'method' not in item:
                if 'error' in item:raise HubError('Codex 拒绝请求：'+str(item['error'].get('message','unknown'))[:2000])
                return item.get('result',{})
            self.pending.append(item)
        raise HubError('Codex 接口超时；不自动重试')

    def event(self,timeout=.5):
        if self.pending:return self.pending.pop(0)
        try:return self.inbox.get(timeout=timeout)
        except queue.Empty:return None

    def verify(self,model,effort='medium'):
        account=self.rpc('account/read',{'refreshToken':False}).get('account') or {}
        if account.get('type')!='chatgpt':raise HubError('真实执行仅接受官方 ChatGPT 登录；请先 codex login。不自动使用 API Key 计费。')
        cursor=None;models=[]
        for _ in range(20):
            page=self.rpc('model/list',{'limit':100,**({'cursor':cursor} if cursor else {})});models.extend(page.get('data',[]));cursor=page.get('nextCursor')
            if not cursor:break
        found=next((m for m in models if m.get('model',m.get('id'))==model),None)
        if not found or effort not in {e['reasoningEffort'] for e in found.get('supportedReasoningEfforts',[])}:raise HubError('当前账号未返回指定模型及 medium effort；未启动推理')
        limits=self.rpc('account/rateLimits/read',{});self.verified_limits=limits
        buckets=limits.get('rateLimitsByLimitId') or {'default':limits.get('rateLimits') or {}}
        windows=[b.get(k) for b in buckets.values() for k in ('primary','secondary') if b.get(k)]
        if not windows:raise HubError('无法核实官方额度；未启动推理')
        if any(w.get('usedPercent',100)>=100 for w in windows):raise QuotaWait(max(float(w.get('resetsAt') or time.time()+60) for w in windows if w.get('usedPercent',100)>=100))

    def close(self):
        if self.closed:return
        self.closed=True
        self.job.close()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
        self.reader.join(timeout=1)
        self.proc.stdin.close();self.proc.stdout.close()

class CodexRuntime:
    provider="codex"
    models=MODELS
    config_key="codex_runtime"
    title="Codex"
    def __init__(self,hub,factory=AppServer):
        self.hub=hub;self.sessions=Sessions(hub);self.factory=factory;self.stop_event=threading.Event();self.thread=None;self.active_client=None;self.clients={};self.workers=[];self.run_threads={}
        with hub.tx():
            hub.db.execute('CREATE TABLE IF NOT EXISTS workflow_resource_dependencies(task TEXT,depends_on TEXT,PRIMARY KEY(task,depends_on))')
            hub.db.execute('CREATE TABLE IF NOT EXISTS git_runs(run TEXT PRIMARY KEY,project TEXT,agent TEXT,cwd TEXT,branch TEXT,base TEXT,head TEXT,result TEXT)')
            hub.db.execute('''CREATE TABLE IF NOT EXISTS executions(id TEXT PRIMARY KEY,task_id TEXT UNIQUE, message_id TEXT,agent TEXT,model TEXT,prompt TEXT,actual_input TEXT,cwd TEXT,permission TEXT,max_seconds INTEGER,grant_id TEXT,status TEXT,created REAL,started REAL,finished REAL,thread_id TEXT,turn_id TEXT,result TEXT,stop_requested INTEGER DEFAULT 0,usage TEXT)''')
            hub.db.execute('CREATE TABLE IF NOT EXISTS workflow_dependencies(task TEXT PRIMARY KEY,depends_on TEXT)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS execution_revocations(run TEXT PRIMARY KEY,actor TEXT,reason TEXT,created REAL)')
            hub.db.execute('CREATE INDEX IF NOT EXISTS execution_finished ON executions(finished)')
            hub.db.execute('CREATE INDEX IF NOT EXISTS execution_state ON executions(status,agent)')
            hub.db.execute('CREATE INDEX IF NOT EXISTS execution_grant ON executions(grant_id,status)')
            hub.db.execute('''CREATE TABLE IF NOT EXISTS execution_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT,ts REAL,kind TEXT,data TEXT)''')
            if 'actual_input' not in {r[1] for r in hub.db.execute('PRAGMA table_info(executions)')}:
                hub.db.execute('ALTER TABLE executions ADD COLUMN actual_input TEXT')
            if 'provider' not in {r[1] for r in hub.db.execute('PRAGMA table_info(executions)')}:
                hub.db.execute("ALTER TABLE executions ADD COLUMN provider TEXT NOT NULL DEFAULT 'codex'")
            if 'retry_after' not in {r[1] for r in hub.db.execute('PRAGMA table_info(executions)')}:
                hub.db.execute('ALTER TABLE executions ADD COLUMN retry_after REAL')
            if 'purpose' not in {r[1] for r in hub.db.execute('PRAGMA table_info(executions)')}:hub.db.execute("ALTER TABLE executions ADD COLUMN purpose TEXT NOT NULL DEFAULT 'task'")
            if 'session_scope' not in {r[1] for r in hub.db.execute('PRAGMA table_info(executions)')}:hub.db.execute('ALTER TABLE executions ADD COLUMN session_scope TEXT')
            for row in hub.db.execute("SELECT * FROM executions WHERE provider=? AND status IN ('running','interrupting')",(self.provider,)).fetchall():
                hub.db.execute("UPDATE executions SET status='uncertain',result='服务重启；任务可能已修改文件，不自动重放',finished=? WHERE id=?",(time.time(),row['id']))
                hub.db.execute("UPDATE messages SET status='uncertain',lease=NULL WHERE id=?",(row['message_id'],))
                hub.db.execute("UPDATE tasks SET status='blocked',note='真实执行结果不确定，请检查产物与日志；不自动重试' WHERE id=?",(row['task_id'],))
                hub.audit('supervisor','codex.recovered_uncertain',{'run_id':row['id']})

    def config(self):
        with self.hub.lock:
            row=self.hub.db.execute("SELECT value FROM settings WHERE key=?",(self.config_key,)).fetchone()
        return json.loads(row[0]) if row else {'enabled':False,'cwd':str((self.hub.directory/'projects').resolve()),'permission':'full','max_runs':3,'max_seconds':600,'grant_id':None}

    def real_agents(self):return set(self.models) if self.config()['enabled'] else set()

    def configure(self,actor,cwd,permission,max_runs,max_seconds,enabled=True,confirmed=False):
        self.hub.require(actor,{'user'})
        if confirmed is not True:raise HubError('请确认工作目录、权限和调用次数预算')
        if not isinstance(enabled,bool) or permission not in ('full','workspace'):raise HubError('invalid execution settings')
        text(cwd,2000);path=Path(cwd)
        if not path.is_absolute() or not path.is_dir():raise HubError('工作目录必须是已存在的绝对目录')
        for value,low,high in ((max_runs,0,10000),(max_seconds,30,86400)):
            if not isinstance(value,int) or isinstance(value,bool):raise HubError('integer budget required')
            number(value,low,high)
        with self.hub.tx():
            if self.hub.db.execute("SELECT 1 FROM executions WHERE status IN ('queued','waiting_quota','running','interrupting')").fetchone():raise HubError('请先等待或停止已有真实任务，再修改执行配置')
            cfg={'enabled':enabled,'cwd':str(path.resolve()),'permission':permission,'max_runs':max_runs,'max_seconds':max_seconds,'grant_id':uid(),'confirmed_at':time.time()}
            self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",(self.config_key,json.dumps(cfg,ensure_ascii=False)))
            self.hub.audit(actor,self.provider+'.configured',cfg)
        return cfg

    def submit(self,actor,agent,instruction,confirmed=False,task_id=None,source_message_id=None,purpose="task",session_scope=None):
        self.hub.require(actor,{'user'})
        if confirmed is not True:raise HubError('请确认启动真实任务，将消耗订阅账号额度')
        if agent not in self.models:raise HubError('该身份不属于 '+self.title+' 真实执行器')
        text(instruction,60000)
        if purpose not in ('task','discussion','question'):raise HubError('讨论仅支持 项目经理')
        with self.hub.tx():
            from hub.project_activity import require_available,run_project
            require_available(self.hub,run_project(self.hub,{'session_scope':session_scope,'task_id':task_id,'message_id':source_message_id}))
            if getattr(self.hub,'coordination',None) and self.hub.coordination.is_stopped(agent):raise HubError('Agent 已被紧急停止，只能由用户解除启动锁')
            cfg=self.config()
            if not cfg['enabled']:raise HubError('请先配置并启用 '+self.title+' 真实执行')
            used=self.hub.db.execute("SELECT COUNT(*) FROM executions WHERE grant_id=? AND status!='cancelled'",(cfg['grant_id'],)).fetchone()[0]
            if cfg['max_runs']>0 and used>=cfg['max_runs']:raise HubError('本次授权的调用次数预算已用完，请重新设置预算')
            if source_message_id:
                existing_task=self.hub.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone() if task_id else None
                if task_id and (not existing_task or existing_task['agent']!=agent or existing_task['title']!=instruction):raise HubError('消息与任务不匹配')
                source=self.hub.db.execute('SELECT * FROM messages WHERE id=?',(source_message_id,)).fetchone()
                if not source or source['recipient']!=agent or source['status']!='pending' or source['body']!=instruction:raise HubError('消息已变化或不适合执行，请刷新')
                if self.hub.db.execute('SELECT 1 FROM executions WHERE message_id=?',(source_message_id,)).fetchone():raise HubError('消息已有执行记录')
                if instruction.startswith('[task:'):raise HubError('请从任务列表授权该任务')
                message_id=source_message_id
                if not task_id:
                    task_id=uid()
                    self.hub.db.execute('INSERT INTO tasks(id,agent,title,assigned_by,created) VALUES(?,?,?,?,?)',(task_id,agent,instruction,actor,time.time()))
            elif task_id:
                task=self.hub.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
                if not task or task['agent']!=agent or task['status']=='done':raise HubError('任务不适合真实执行')
                if instruction!=task['title']:raise HubError('任务文本已变化，请刷新后重新确认')
                message=self.hub.db.execute("SELECT * FROM messages WHERE recipient=? AND body LIKE ? AND status IN ('pending','paused')",(agent,'[task:'+task_id+'] %')).fetchone()
                if not message:raise HubError('任务没有待处理消息')
                message_id=message['id']
            else:
                task_id=uid();message_id=uid()
                self.hub.db.execute('INSERT INTO tasks(id,agent,title,assigned_by,created) VALUES(?,?,?,?,?)',(task_id,agent,instruction,actor,time.time()))
                self.hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created) VALUES(?,?,?,?,'queue','pending',?)",(message_id,actor,agent,'[task:'+task_id+'] '+instruction,time.time()))
            if self.hub.db.execute('SELECT 1 FROM executions WHERE task_id=?',(task_id,)).fetchone():raise HubError('该任务已有真实执行记录，不自动重试；请检查后创建新任务')
            run_id=uid()
            self.hub.db.execute("INSERT INTO executions(id,task_id,message_id,agent,model,prompt,actual_input,cwd,permission,max_seconds,grant_id,status,created,provider) VALUES(?,?,?,?,?,?,?,?,?,?,?,'queued',?,?)",(run_id,task_id,message_id,agent,self.models[agent],instruction,instruction,cfg['cwd'],cfg['permission'],cfg['max_seconds'],cfg['grant_id'],time.time(),self.provider))
            self.hub.db.execute('UPDATE executions SET purpose=?,session_scope=? WHERE id=?',(purpose,session_scope,run_id))
            self.hub.audit(actor,self.provider+'.authorized',{'run_id':run_id,'task_id':task_id,'model':self.models[agent],'permission':cfg['permission']})
        return {'id':run_id,'task_id':task_id,'status':'queued'}

    def snapshot(self,actor):
        self.hub.require(actor,{'user'})
        with self.hub.lock:
            runs=[dict(r) for r in self.hub.db.execute('SELECT * FROM executions WHERE provider=? ORDER BY created DESC LIMIT 30',(self.provider,))]
            events=[dict(r) for r in self.hub.db.execute('SELECT ev.* FROM execution_events ev JOIN executions ex ON ev.run_id=ex.id WHERE ex.provider=? ORDER BY ev.seq DESC LIMIT 150',(self.provider,))]
            cfg=self.config();used=self.hub.db.execute("SELECT count(*) FROM executions WHERE grant_id=? AND status!='cancelled'",(cfg['grant_id'],)).fetchone()[0]
        return {'config':cfg,'runs':runs,'events':events,'remaining_runs':max(0,cfg['max_runs']-used),'default_cwd':str((self.hub.directory/'projects').resolve())}

    def stop(self,actor,run_id):
        self.hub.require(actor,{'user'})
        with self.hub.tx():
            run=self.hub.db.execute('SELECT * FROM executions WHERE id=? AND provider=?',(run_id,self.provider)).fetchone()
            if not run or run['status'] not in ('queued','waiting_quota','running','interrupting'):raise HubError('任务已结束或不存在')
            if run['status'] in ('queued','waiting_quota'):
                self.hub.db.execute("UPDATE executions SET status='cancelled',finished=? WHERE id=?",(time.time(),run_id))
                self.hub.db.execute("UPDATE messages SET status='cancelled' WHERE id=?",(run['message_id'],))
                self.hub.db.execute("UPDATE tasks SET status='blocked',note='用户取消未执行任务' WHERE id=?",(run['task_id'],))
            else:self.hub.db.execute('UPDATE executions SET stop_requested=1 WHERE id=?',(run_id,))
            self.hub.audit(actor,self.provider+'.stop_requested',{'run_id':run_id})
        return {'ok':True}

    def public_reply(self,run,text='',replace=False,summary=None,phase=None):
        if self.force_stopped(run):return
        service=getattr(self.hub,'live',None)
        if service:service.update(run['id'],text,replace,summary,phase)

    def record(self,run_id,kind,data):
        # Store only execution artefacts, never account/auth or raw reasoning events.
        with self.hub.tx():self.hub.db.execute('INSERT INTO execution_events(run_id,ts,kind,data) VALUES(?,?,?,?)',(run_id,time.time(),kind,json.dumps(data,ensure_ascii=False)[:40000]))

    def start(self):
        with self.hub.lock:
            if self.stop_event.is_set() or (self.thread and self.thread.is_alive()):return
            self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()

    def loop(self):
        while not self.stop_event.is_set():
            try:
                run=None
                with self.hub.tx():
                    if getattr(self.hub,'automation',None):
                        due=self.hub.db.execute("SELECT e.id,e.agent,e.retry_after,w.id workflow,w.body FROM executions e JOIN workflow_steps s ON s.task=e.task_id JOIN workflows w ON w.id=s.workflow WHERE e.provider=? AND e.status='waiting_quota' AND e.retry_after<=?",(self.provider,time.time())).fetchall()
                        for resumed in due:
                            workflow=json.loads(resumed['body'])
                            if workflow['status']=='active' and not self.hub.coordination.is_stopped(resumed['agent']):
                                key='quota-attempt:'+resumed['id']+':'+str(resumed['retry_after'])
                                event={'type':'quota_resume','from':'平台','body':resumed['agent']+' 的预计额度恢复时间已到，平台将尝试继续等待额度的原执行；提供商尚未确认恢复，请勿重复派工。'}
                                self.hub.db.execute("INSERT OR IGNORE INTO workflow_events VALUES(?,?,NULL,?,'pending',NULL,?)",(key,resumed['workflow'],json.dumps(event,ensure_ascii=False),time.time()))
                    self.hub.db.execute("UPDATE executions SET status='queued' WHERE provider=? AND status='waiting_quota' AND retry_after<=?",(self.provider,time.time()))
                    setting=self.hub.db.execute("SELECT value FROM settings WHERE key='max_parallel'").fetchone()
                    limit=int(setting[0]) if setting else 1
                    from hub.connection_tests import MAX_PARALLEL
                    count=self.hub.db.execute("SELECT count(*) FROM executions WHERE status IN ('running','interrupting') AND coalesce(session_scope,'') NOT LIKE 'connection-test:%'").fetchone()[0]
                    test_count=self.hub.db.execute("SELECT count(*) FROM executions WHERE status IN ('running','interrupting') AND session_scope LIKE 'connection-test:%'").fetchone()[0]
                    candidates=[] if count>=limit and test_count>=MAX_PARALLEL else self.hub.db.execute("SELECT e.* FROM executions e WHERE e.provider=? AND e.status='queued' AND ((coalesce(e.session_scope,'') LIKE 'connection-test:%' AND ?) OR (coalesce(e.session_scope,'') NOT LIKE 'connection-test:%' AND ?)) AND NOT EXISTS(SELECT 1 FROM executions busy WHERE busy.agent=e.agent AND busy.status IN ('running','interrupting')) AND NOT EXISTS(SELECT 1 FROM git_runs pending_git WHERE pending_git.agent=e.agent AND pending_git.run!=e.id AND pending_git.result IS NULL) AND NOT EXISTS(SELECT 1 FROM workflow_dependencies dep LEFT JOIN executions prior ON prior.task_id=dep.depends_on WHERE dep.task=e.task_id AND (prior.status IS NULL OR prior.status!='completed')) AND NOT EXISTS(SELECT 1 FROM workflow_resource_dependencies dep LEFT JOIN executions prior ON prior.task_id=dep.depends_on WHERE dep.task=e.task_id AND (prior.status IS NULL OR prior.status IN ('queued','waiting_quota','running','interrupting'))) ORDER BY CASE WHEN e.message_id IN (SELECT id FROM messages WHERE mode='immediate') THEN 0 ELSE 1 END,coalesce((SELECT position FROM project_queue_positions WHERE item_id=e.task_id),(SELECT position FROM project_queue_positions WHERE item_id=e.message_id),e.created),CASE WHEN e.purpose='question' THEN 1 ELSE 0 END,e.created,e.id LIMIT 64",(self.provider,test_count<MAX_PARALLEL,count<limit)).fetchall()
                    from hub.project_activity import owner,run_project
                    active_project=owner(self.hub)
                    row=next((r for r in candidates if not active_project or run_project(self.hub,dict(r)) in (None,active_project)),None)
                    if row and getattr(self.hub,'coordination',None) and self.hub.coordination.is_stopped(row['agent']):row=None
                    if row and not (row['session_scope'] or '').startswith('connection-test:'):
                        from hub.model_availability import status as model_status,cancel_queued as cancel_model
                        block=model_status(self.hub,row['provider'],row['model'])
                        if block:cancel_model(self.hub,dict(row),block);row=None
                    if row:
                        from hub.quota_state import status as quota_status,cancel_queued
                        quota=quota_status(self.hub,row['agent'])
                        if quota['exhausted']:cancel_queued(self.hub,dict(row),quota);row=None
                    if row and self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_steps'").fetchone():
                        project=self.hub.db.execute('SELECT w.body FROM workflows w JOIN workflow_steps s ON s.workflow=w.id WHERE s.task=?',(row['task_id'],)).fetchone()
                        if project:
                            grant=json.loads(project[0])
                            if grant['status']!='active' or time.time()>grant['expires'] or self.config()['grant_id']!=grant['grants'].get(self.provider):
                                self.hub.db.execute("UPDATE executions SET status='cancelled',finished=?,result='项目授权已失效，未启动模型' WHERE id=?",(time.time(),row['id']))
                                self.hub.db.execute("UPDATE messages SET status='cancelled' WHERE id=?",(row['message_id'],))
                                self.hub.db.execute("UPDATE tasks SET status='blocked',note='项目授权已失效' WHERE id=?",(row['task_id'],))
                                row=None
                    if row:
                        run=dict(row)
                        self.hub.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),run['id']))
                        self.hub.db.execute("UPDATE agents SET status='busy',active=?,heartbeat=? WHERE id=?",(run['message_id'],time.time(),run['agent']))
                        self.hub.db.execute("UPDATE messages SET status='acknowledged',acked=?,lease=?,attempts=attempts+1 WHERE id=?",(time.time(),time.time()+30,run['message_id']))
                        self.hub.db.execute("UPDATE tasks SET status='working',note=? WHERE id=?",(self.title+' 官方执行器正在启动',run['task_id']))
                if run:
                    self.workers=[t for t in self.workers if t.is_alive()]
                    self.run_threads={key:t for key,t in self.run_threads.items() if t.is_alive()}
                    worker=threading.Thread(target=self.execute_job,args=(run,),daemon=True);self.run_threads[run['id']]=worker;self.workers.append(worker);worker.start()
            except Exception as e:
                with self.hub.tx():self.hub.audit('supervisor','codex.worker_error',{'type':type(e).__name__})
            self.stop_event.wait(.25 if run else 1)

    def execute_job(self,run):
        try:
            self.check_latch(run)
            workspaces=getattr(getattr(self.hub,'workflows',None),'git',None)
            if workspaces:run=workspaces.prepare(run)
        except Exception as error:
            with self.hub.tx():
                if self.force_stopped(run):return
                detail='工作目录准备失败，未调用模型：'+str(error)
                self.hub.db.execute("UPDATE executions SET status='failed',finished=?,result=? WHERE id=?",(time.time(),detail,run['id']))
                self.hub.db.execute("UPDATE messages SET status='failed',result=? WHERE id=?",(detail,run['message_id']))
                self.hub.db.execute("UPDATE tasks SET status='blocked',note=? WHERE id=?",(detail,run['task_id']))
                self.hub.db.execute("UPDATE agents SET status='idle',active=NULL WHERE id=? AND active=?",(run['agent'],run['message_id']))
            return
        self.execute(run)

    def execute(self,run):
        from hub.harness_adapters import execute_builtin
        return execute_builtin(self,run,'codex')

    def _execute_native(self,run):
        client=None;status='failed';result='';final=[];interrupted=False;interrupt_at=None;started=time.monotonic();usage=None;submitted=False
        renew_stop=threading.Event()
        def renew():
            while not renew_stop.wait(3):
                try:self.check_latch(run);self.hub.heartbeat(run['agent'],'busy')
                except Exception:return
        renewal=threading.Thread(target=renew,daemon=True);renewal.start()
        try:
            self.check_latch(run)
            client=AppServer(run['cwd'],self.mcp_config(),self.run_environment(run),self.connection_executable() if hasattr(self,'connection_executable') else None) if self.factory is AppServer else self.factory(run['cwd']);self.track_client(run,client)
            if isinstance(client,AppServer):client.verify(run['model'],self.effort(run['agent']) if hasattr(self,'effort') else 'medium')
            else:client.verify(run['model'])
            if getattr(client,'verified_limits',None):
                with self.hub.tx():self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('openai_limits',?)",(json.dumps({'observed_at':time.time(),'rate_limits':client.verified_limits,'source':'official_app_server'}),))
            self.check_latch(run)
            instructions=self.execution_instructions(run)
            instructions+=self.report_instructions(run)
            with self.hub.lock:check=self.hub.db.execute('SELECT kind FROM workflow_steps WHERE task=?',(run['task_id'],)).fetchone() if self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_steps'").fetchone() else None
            readonly=run.get('purpose') in ('discussion','question') or bool(check and check[0]=='check')
            sandbox='read-only' if readonly else ('danger-full-access' if run['permission']=='full' else 'workspace-write')
            session=self.sessions.get(run)
            params={'model':run['model'],'modelProvider':'openai','cwd':run['cwd'],'approvalPolicy':'never','sandbox':sandbox,'developerInstructions':instructions,'config':{'features.multi_agent':False}}
            if session:params.update(threadId=session['session_id'],excludeTurns=True)
            opened=client.rpc('thread/resume' if session else 'thread/start',params)
            if session and opened['thread']['id']!=session['session_id']:raise HubError('恢复的会话 ID 不匹配；未启动推理')
            thread_id=opened['thread']['id'];self.sessions.bind(run,thread_id)
            effective=opened.get('sandbox')
            expected='readOnly' if readonly else ('dangerFullAccess' if run['permission']=='full' else 'workspaceWrite')
            if not isinstance(effective,dict) or effective.get('type')!=expected or opened.get('approvalPolicy')!='never' or opened.get('model')!=run['model'] or opened.get('modelProvider')!='openai':raise HubError('官方返回的权限/模型与授权不一致；未启动推理')
            with self.hub.tx():self.hub.db.execute('UPDATE executions SET thread_id=? WHERE id=?',(thread_id,run['id']))
            policy={'type':'readOnly'} if readonly else ({'type':'dangerFullAccess'} if run['permission']=='full' else {'type':'workspaceWrite','writableRoots':[run['cwd']],'networkAccess':True})
            self.sessions.state(run,'inflight');submitted=True
            input_text=run.get('_manager_content') or run['prompt']
            with self.hub.tx():self.hub.db.execute('UPDATE executions SET actual_input=? WHERE id=?',(input_text,run['id']))
            turn=client.rpc('turn/start',{'threadId':thread_id,'input':[{'type':'text','text':input_text}],'model':run['model'],'effort':self.effort(run['agent']) if hasattr(self,'effort') else 'medium','approvalPolicy':'never','sandboxPolicy':policy})['turn']
            turn_id=turn['id']
            with self.hub.tx():self.hub.db.execute('UPDATE executions SET turn_id=? WHERE id=?',(turn_id,run['id']))
            self.record(run['id'],'started',{'thread_id':thread_id,'turn_id':turn_id,'permission':sandbox,'cwd':run['cwd']})
            while True:
                self.check_latch(run)
                self.hub.heartbeat(run['agent'],'busy')
                with self.hub.lock:
                    stop=self.hub.db.execute('SELECT stop_requested FROM executions WHERE id=?',(run['id'],)).fetchone()[0]
                if not interrupted and (stop or self.stop_event.is_set() or time.monotonic()-started>run['max_seconds']):
                    interrupted=True;interrupt_at=time.monotonic()
                    with self.hub.tx():self.hub.db.execute("UPDATE executions SET status='interrupting' WHERE id=? AND NOT EXISTS(SELECT 1 FROM execution_revocations WHERE run=executions.id)",(run['id'],))
                    client.rpc('turn/interrupt',{'threadId':thread_id,'turnId':turn_id},timeout=10)
                    self.record(run['id'],'interrupt_requested',{'reason':'用户/立即消息/时间预算/关闭'})
                if interrupt_at and time.monotonic()-interrupt_at>15:raise HubError('中断未收到完成确认；结果不确定，文件可能已变化')
                event=client.event()
                if not event:continue
                if event.get('_eof'):raise HubError('官方执行连接断开；文件可能已变化，不自动重试')
                method=event.get('method','');params=event.get('params',{})
                if 'id' in event and method:
                    client.write({'id':event['id'],'error':{'code':-32601,'message':'Hub does not grant additional interactive permissions'}})
                    raise HubError('提供商请求额外审批/工具交互；当前任务暂停失败，未自动批准')
                if params.get('threadId') not in (None,thread_id):continue
                if method=='item/agentMessage/delta':self.public_reply(run,params.get('delta',''),phase='正在生成回复')
                elif method=='item/reasoning/summaryTextDelta':self.public_reply(run,summary=params.get('delta',''),phase='提供商返回公开思考摘要')
                elif method=='item/completed':
                    item=params.get('item',{});kind=item.get('type')
                    if kind in ('agentMessage','commandExecution','fileChange','plan'):
                        self.record(run['id'],kind,item)
                        if kind=='agentMessage' and item.get('text'):
                            final.append(item['text']);self.public_reply(run,'\n\n'.join(final),replace=True,phase='回复生成中')
                        if kind=='commandExecution' and item.get('exitCode') not in (None,0):self.record(run['id'],'command_nonzero',{'exitCode':item.get('exitCode')})
                elif method in ('turn/plan/updated','turn/diff/updated'):
                    self.record(run['id'],method,params)
                elif method=='thread/tokenUsage/updated':usage=params.get('tokenUsage')
                elif method=='turn/completed' and params.get('turn',{}).get('id')==turn_id:
                    ended=params['turn'];status={'completed':'completed','interrupted':'interrupted','failed':'failed'}.get(ended.get('status'),'uncertain')
                    result='\n\n'.join(final) or json.dumps(ended.get('error') or {'status':status},ensure_ascii=False)
                    if len(result)>262144:raise HubError('提供商结果超过262144字符，未截断为有效计划')
                    break
        except QuotaWait as e:
            status='failed';result='官方额度耗尽，本任务已取消；预计恢复时间 '+str(e.resets)+'。请经理改派或设置恢复提醒。'
        except Exception as e:
            status='uncertain' if submitted else 'failed'
            result=str(e)[:5000]
        finally:
            renew_stop.set();renewal.join(timeout=5)
            if client:client.close()
            status=self.quota_outcome(run,status,result)
            self.sessions.state(run,status)
            self.clients.pop(run['id'],None)
            with self.hub.tx():
                if self.force_stopped(run):return
                self.hub.db.execute('UPDATE executions SET status=?,finished=?,result=?,usage=? WHERE id=?',(status,time.time(),result,json.dumps(usage),run['id']))
                self.hub.db.execute('UPDATE messages SET status=?,result=?,lease=NULL WHERE id=?',(status,result,run['message_id']))
                self.hub.db.execute("UPDATE agents SET status='idle',active=NULL,heartbeat=? WHERE id=? AND active=?",(time.time(),run['agent'],run['message_id']))
                self.hub.db.execute('UPDATE tasks SET status=?,progress=?,note=? WHERE id=?',('done' if status=='completed' else 'cancelled' if status=='cancelled' else 'blocked',100 if status=='completed' else 0,result,run['task_id']))
                self.hub.audit(run['agent'],'codex.'+status,{'run_id':run['id'],'task_id':run['task_id']})
            if status=='waiting_quota' and getattr(self.hub,'automation',None):self.hub.automation.quota_waiting(run)
            if status!='waiting_quota':self.deliver_result(run,status,result)

    def quota_outcome(self,run,status,result):
        from hub.quota_state import is_exhausted_error,record_rejection
        from hub.model_availability import retired,reject
        if status not in ('completed','cancelled') and retired(result):
            with self.hub.tx():
                if not self.force_stopped(run):reject(self.hub,run,result)
            return 'cancelled'
        if status=='completed' and result and (run.get('session_scope') or '').startswith('connection-test:'):
            with self.hub.tx():
                if self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='unavailable_models'").fetchone():self.hub.db.execute('DELETE FROM unavailable_models WHERE provider=? AND model=?',(run['provider'],run['model']))
        if status not in ('completed','cancelled') and is_exhausted_error(result):
            with self.hub.tx():
                if not self.force_stopped(run):record_rejection(self.hub,run,result)
            return 'cancelled'
        return status

    def force_stopped(self,run):
        with self.hub.lock:
            return bool(self.hub.db.execute('SELECT 1 FROM execution_revocations WHERE run=?',(run['id'],)).fetchone())

    def track_client(self,run,client):
        with self.hub.lock:
            if self.force_stopped(run):
                job=getattr(client,'job',None)
                if job:job.close()
                proc=getattr(client,'proc',None)
                if proc and proc.poll() is None:proc.kill()
                close=getattr(client,'close',None)
                if callable(close):close()
                raise HubError('经理已强制停止此任务')
            self.clients[run['id']]=client

    def check_latch(self,run):
        if self.force_stopped(run):raise HubError('经理已强制停止此任务')
        if getattr(self.hub,'coordination',None) and self.hub.coordination.is_stopped(run['agent']):raise HubError('Agent 紧急停止锁已生效，未启动新推理')

    def mcp_config(self):
        if getattr(sys, 'frozen', False):
            bridge = Path(self.hub.directory) / 'mcp_bridge.py'
            try:
                src_mcp = host_resource('mcp.py')
                if src_mcp.is_file():
                    bridge.write_bytes(src_mcp.read_bytes())
            except OSError:
                pass
            py_exe = shutil.which('python')
            if py_exe and bridge.is_file():
                return {'command':py_exe,'args':[str(bridge.resolve())],'env_vars':['HUB_TOKEN','HUB_URL','HUB_RUN_ID','HUB_AGENT','HUB_IS_MANAGER','HUB_TOOL_ALLOWLIST'],'required':True}
            return {'command':sys.executable,'args':['--mcp-server'],'env_vars':['HUB_TOKEN','HUB_URL','HUB_RUN_ID','HUB_AGENT','HUB_IS_MANAGER','HUB_TOOL_ALLOWLIST'],'required':True}
        return {'command':sys.executable,'args':[str(host_resource('mcp.py').resolve())],'env_vars':['HUB_TOKEN','HUB_URL','HUB_RUN_ID','HUB_AGENT','HUB_IS_MANAGER','HUB_TOOL_ALLOWLIST'],'required':True}

    def run_environment(self,run):
        # Passed through environment, never CLI arguments or persisted provider config.
        with self.hub.lock:
            row=self.hub.db.execute('SELECT w.body FROM workflows w JOIN workflow_steps s ON s.workflow=w.id WHERE s.task=?',(run['task_id'],)).fetchone() if self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='workflows'").fetchone() else None
        manager=bool(row and project_manager(self.hub,record=json.loads(row[0]))==run['agent'])
        if not manager:
            from hub.user_followup import manager as followup_manager
            manager=followup_manager(self.hub,run)
        from hub.long_term_memory import is_manager
        manager=manager or is_manager(self.hub,run)
        tools={}
        if run.get('purpose') in ('discussion','question'):
            tools['HUB_TOOL_ALLOWLIST']=json.dumps(['memory'] if is_manager(self.hub,run) else [])
        return {**tools,'HUB_IS_MANAGER':'1' if manager else '0','HUB_TOKEN':self.hub.tokens[run['agent']],'HUB_URL':getattr(self.hub,'url','http://127.0.0.1:8765'),'HUB_RUN_ID':run['id'],'HUB_AGENT':run['agent']}

    def compact_manager_input(self,run):
        from hub.execution_policy import compact_manager_input
        return compact_manager_input(self,run)

    def execution_instructions(self,run):
        from hub.execution_policy import execution_instructions
        return execution_instructions(self,run)

    def report_instructions(self,run):
        from hub.execution_policy import report_instructions
        return report_instructions(self,run)

    def deliver_result(self,run,status,result):
        if self.force_stopped(run):return
        if (run.get('session_scope') or '').startswith('connection-test:'):return
        # Project workers report through Coordination; raw provider output stays local.
        with self.hub.lock:
            exists=self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_steps'").fetchone()
            step=self.hub.db.execute('SELECT kind FROM workflow_steps WHERE task=?',(run['task_id'],)).fetchone() if exists else None
        if step and step['kind'] in ('work','message','check'):return
        body='[真实 '+self.title+' · '+status+'] '+result[:19000]
        ids=self.hub.send(run['agent'],'user',body,request_key='execution:'+run['id']+':user')
        with self.hub.tx():
            source=self.hub.db.execute('SELECT project_id FROM messages WHERE id=?',(run['message_id'],)).fetchone()
            if source and source['project_id']:
                for ident in ids:self.hub.db.execute('UPDATE messages SET project_id=? WHERE id=? AND project_id IS NULL',(source['project_id'],ident))
                self.hub.db.execute('UPDATE tasks SET project_id=? WHERE id=? AND project_id IS NULL',(source['project_id'],run['task_id']))
        with self.hub.lock:
            original=self.hub.db.execute('SELECT sender,request_key FROM messages WHERE id=?',(run['message_id'],)).fetchone()
        if original and not (original['request_key'] or '').startswith(('execution:','report:')) and original['sender'] not in ('user','平台',run['agent']):
            self.hub.send(run['agent'],original['sender'],body,request_key='execution:'+run['id']+':reply')

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)
        deadline=time.monotonic()+20
        for worker in list(self.workers):worker.join(timeout=max(0,deadline-time.monotonic()))
        for client in list(self.clients.values()):client.close()
        for worker in list(self.workers):worker.join(timeout=5)
