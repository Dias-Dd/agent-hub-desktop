from hub.manager_identity import resolve as project_manager
"""Official DeepSeek tool loop, durable sessions, prepaid local request bounds."""
import base64
import ctypes
import json
import math
import itertools
import os
import sys
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from hub.codex_runtime import CodexRuntime
from hub.core import HubError, uid
from hub.mcp import TOOLS
from hub.process_job import ProcessJob
from hub.proxy_env import inherit_system_proxy


def protect(raw, decrypt=False):
    if os.name != 'nt':raise HubError('持久密钥存储需要 Windows DPAPI；其它系统请使用环境变量')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(raw);source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));out=Blob()
    api=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not api(ctypes.byref(source),None,None,None,None,1,ctypes.byref(out)):raise HubError('Windows 密钥加解密失败')
    try:return ctypes.string_at(out.data,out.size)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes=[ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(out.data)


class OfficialAPI:
    def __init__(self,key):self.key=key
    def request(self,path,payload=None):
        req=urllib.request.Request('https://api.deepseek.com'+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Authorization':'Bearer '+self.key(),'Content-Type':'application/json'})
        try:
            # Use the configured system proxy, never a custom API endpoint.
            env=inherit_system_proxy(dict(os.environ));proxy=env.get('HTTPS_PROXY') or env.get('https_proxy')
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':proxy} if proxy else {}))
            with opener.open(req,timeout=45) as response:return json.load(response)
        except urllib.error.HTTPError as error:raise HubError('DeepSeek HTTP '+str(error.code)+'；未自动重试') from None
        except (OSError,ValueError):raise HubError('DeepSeek 网络或响应错误；费用可能未知，不自动重试') from None


class DeepSeekRuntime(CodexRuntime):
    provider='deepseek';models={f'deepseek-{i}':'deepseek-flash' for i in range(1,10)};config_key='deepseek_runtime';title='DeepSeek API'
    def __init__(self,hub,api=None):
        self._api_injected=api is not None
        super().__init__(hub);self.api=api or OfficialAPI(self.key)
        with hub.tx():
            hub.db.execute('CREATE TABLE IF NOT EXISTS agent_effort_notices(message_id TEXT PRIMARY KEY,project_id TEXT,recipient TEXT,body TEXT,delivered REAL,run_id TEXT)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS harness_sessions(key TEXT PRIMARY KEY,session_id TEXT,cwd TEXT,agent TEXT,updated REAL)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS deepseek_context(key TEXT PRIMARY KEY,body TEXT)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS deepseek_spend(id TEXT PRIMARY KEY,grant_id TEXT,run_id TEXT,reserved_cents INTEGER,status TEXT,usage TEXT,created REAL)')

    @property
    def title(self):return 'DeepSeek Harness' if self.config().get('engine')=='harness' else 'DeepSeek API'

    def config(self):
        cfg=super().config()
        return {**cfg,'engine':cfg.get('engine','api' if self._api_injected else 'harness'),'unlimited':True,'max_runs':0,'budget_cents':None,'max_requests':None}

    def efforts(self):
        with self.hub.lock:row=self.hub.db.execute("SELECT value FROM settings WHERE key='agent_efforts'").fetchone()
        saved=json.loads(row[0]) if row else {}
        return {agent:saved.get(agent,'high') for agent in self.models}

    def effort_summary(self):
        if getattr(self.hub,'integrations',None):return '当前成员接入与档位：'+json.dumps(self.hub.integrations.capabilities(),ensure_ascii=False)
        return '各 Agent 当前推理档位：'+'；'.join(agent+'='+effort for agent,effort in self.efforts().items())+'。'

    def set_effort(self,actor,agent,effort,project_id=None):
        self.hub.require(actor,{'user'})
        if agent not in self.models or effort not in ('off','low','high','max'):raise HubError('未知身份或不支持的档位')
        if project_id and getattr(self.hub,'projects',None):self.hub.projects.get(project_id)
        with self.hub.tx():
            values=self.efforts();previous=values[agent]
            if previous==effort:return {'agent':agent,'effort':effort,'changed':False}
            values[agent]=effort
            self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('agent_efforts',?)",(json.dumps(values),))
            workflows=[json.loads(row[0]) for row in self.hub.db.execute('SELECT body FROM workflows ORDER BY rowid DESC')] if getattr(self.hub,'workflows',None) else []
            targets={}
            for w in reversed(workflows):
                if w['status'] in ('active','needs_attention','paused','blocked') or w.get('project_id')==project_id:targets[w.get('project_id') or w['id']]=w
            if project_id and project_id not in targets:targets[project_id]=None
            for project,w in targets.items():
                manager=project_manager(self.hub,record=w) if w else project_manager(self.hub)
                body=f'档位变更：{agent} {previous} → {effort}。下一轮执行生效，当前执行不打断。'
                message=uid()
                self.hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created,project_id) VALUES(?,'平台',?,?,'queue','queued',?,?)",(message,manager,body,time.time(),project))
                self.hub.db.execute('INSERT INTO agent_effort_notices VALUES(?,?,?,?,NULL,NULL)',(message,project,manager,body))
                if w and w['status'] in ('active','needs_attention'):
                    event={'type':'effort_changed','from':'平台','message_id':message,'body':body}
                    self.hub.db.execute("INSERT INTO workflow_events VALUES(?,?,NULL,?,'pending',NULL,?)",('effort:'+message,w['id'],json.dumps(event,ensure_ascii=False),time.time()))
            self.hub.audit(actor,'agent.effort_changed',{'agent':agent,'previous':previous,'effort':effort,'applies':'next_turn'})
        return {'agent':agent,'effort':effort,'changed':True,'applies':'next_turn'}

    def effort_notices(self,run):
        scope=self.sessions.scope(run)
        if not scope.startswith('hub-project:'):return []
        with self.hub.lock:return [dict(r) for r in self.hub.db.execute('SELECT * FROM agent_effort_notices WHERE project_id=? AND recipient=? AND delivered IS NULL ORDER BY rowid',(scope[12:],run['agent']))]

    def acknowledge_effort_notices(self,run,notices):
        with self.hub.tx():
            for notice in notices:
                self.hub.db.execute('UPDATE agent_effort_notices SET delivered=?,run_id=? WHERE message_id=? AND delivered IS NULL',(time.time(),run['id'],notice['message_id']))
                self.hub.db.execute("UPDATE messages SET status='completed',result='经理本轮已收到档位变化' WHERE id=?",(notice['message_id'],))

    def key(self):
        if sys.platform=='darwin':
            from hub.macos_keychain import Keychain
            value=Keychain(self.hub.directory).get()
            if value:return value
        path=self.hub.directory/'deepseek-key.dpapi'
        if path.exists():return protect(base64.b64decode(path.read_bytes()),True).decode()
        value=os.environ.get('DEEPSEEK_API_KEY')
        if not value:raise HubError('请先在 DeepSeek 配置页填写 API 密钥')
        return value

    def status(self,actor):
        self.hub.require(actor,{'user'});cfg=self.config()
        with self.hub.lock:spent=self.hub.db.execute('SELECT COALESCE(SUM(reserved_cents),0) FROM deepseek_spend WHERE grant_id=?',(cfg['grant_id'],)).fetchone()[0]
        return {'config':cfg,'key_present':bool((self.hub.directory/('deepseek-key.keychain' if sys.platform=='darwin' else 'deepseek-key.dpapi')).exists() or os.environ.get('DEEPSEEK_API_KEY')),'reserved_cents':spent,'remaining_cents':None,'unlimited':True,'validation':self.saved_validation(),'efforts':self.efforts(),'effort_options':['off','low','high','max']}

    def snapshot(self,actor):
        res=super().snapshot(actor)
        res['remaining_runs']=None;res['unlimited']=True
        res['remaining_cents']=None
        return res

    def saved_validation(self):
        with self.hub.lock:r=self.hub.db.execute("SELECT value FROM settings WHERE key='deepseek_validation'").fetchone()
        return json.loads(r[0]) if r else None

    def save_key(self,actor,api_key):
        self.hub.require(actor,{'user'})
        with self.hub.lock:
            if self.hub.db.execute("SELECT 1 FROM executions WHERE provider='deepseek' AND status IN ('queued','running','interrupting','waiting_quota')").fetchone():raise HubError('DeepSeek 有在途任务，请先等待或停止再更换密钥')
        if not isinstance(api_key,str) or not 10<=len(api_key.strip())<=500:raise HubError('API 密钥格式无效')
        if any(c.isspace() for c in api_key.strip()):raise HubError('密钥不能含空白字符')
        if sys.platform=='darwin':
            from hub.macos_keychain import save
            save(self.hub.directory,api_key.strip())
        else:
            path=self.hub.directory/'deepseek-key.dpapi';temp=path.with_suffix('.tmp')
            temp.write_bytes(base64.b64encode(protect(api_key.strip().encode())));temp.replace(path)
        with self.hub.tx():
            self.hub.db.execute("DELETE FROM settings WHERE key='deepseek_validation'")
            self.hub.audit(actor,'deepseek.key_saved',{'storage':'macOS Keychain' if sys.platform=='darwin' else 'Windows DPAPI','key': '[redacted]'})
        return {'saved':True,'storage':('macOS Keychain' if sys.platform=='darwin' else 'Windows 当前用户加密')+'；不回显密钥'}

    def validate(self,actor):
        self.hub.require(actor,{'user'})
        data=self.api.request('/models');models=[m['id'] for m in data.get('data',[]) if isinstance(m.get('id'),str)]
        result={'at':time.time(),'models':models,'supported':'deepseek-flash' in models,'inference_sent':False}
        with self.hub.tx():self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('deepseek_validation',?)",(json.dumps(result),))
        return result

    def configure_api(self,actor,cwd,permission,max_runs,max_seconds,budget_cents,input_rate,output_rate,max_requests=8,max_output=2048,enabled=True,takeover=False,confirmed=False):
        self.hub.require(actor,{'user'})
        if confirmed is not True:raise HubError('请确认费用预算、工具权限及接管选项')
        budget_cents = 0 if not isinstance(budget_cents, int) or budget_cents < 0 else budget_cents
        input_rate = float(input_rate) if isinstance(input_rate, (int, float)) and math.isfinite(input_rate) and input_rate >= 0 else 0.0
        output_rate = float(output_rate) if isinstance(output_rate, (int, float)) and math.isfinite(output_rate) and output_rate >= 0 else 0.0
        max_requests = 0 if not isinstance(max_requests, int) or max_requests < 0 else max_requests
        max_output = 0 if not isinstance(max_output, int) or max_output < 0 else max_output
        takeover = bool(takeover)
        validation=self.saved_validation()
        if enabled and (not validation or not validation['supported']):raise HubError('请先验证官方模型列表中包含 deepseek-flash')
        runs_val = max_runs if (isinstance(max_runs, int) and 0 <= max_runs <= 10000) else 10000
        engine=self.config().get('engine','harness');install=self.config().get('harness_install')
        cfg=super().configure(actor,cwd,permission,runs_val,max_seconds,enabled,confirmed)
        cfg.update(engine=engine,harness_install=install)
        cfg.update(authorized_cwd=cfg['cwd'],authorized_max_seconds=cfg['max_seconds'],unlimited=True,budget_cents=None,input_rate=input_rate,output_rate=output_rate,max_requests=None,max_output=max_output,takeover=takeover)
        with self.hub.tx():self.hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(self.config_key,json.dumps(cfg)))
        return cfg

    def configure(self,actor,cwd,permission,max_runs,max_seconds,enabled=True,confirmed=False):
        # Global project bounds do not renew this provider's independent money/call grant.
        self.hub.require(actor,{'user'})
        if confirmed is not True:raise HubError('需要用户确认')
        old=self.config()
        if not old.get('enabled'):raise HubError('请先完成 DeepSeek API 与费用授权')
        if permission!=old['permission']:raise HubError('DeepSeek 访问权限与已确认授权不同，请先在配置页调整')
        if type(max_runs)!=int or max_runs < 0 or type(max_seconds)!=int or not 30<=max_seconds<=86400:raise HubError('项目调用次数或时限无效')
        root=Path(old.get('authorized_cwd',old['cwd'])).resolve();target=Path(cwd)
        if not target.is_absolute() or not target.is_dir():raise HubError('项目目录必须是已存在的绝对目录')
        target=target.resolve()
        # User-confirmed project selection authorizes this exact new workspace.
        # Keep the provider grant, permission level and independent call/fee limits.
        rebound=permission!='full' and not target.is_relative_to(root)
        if rebound:root=target
        cfg={**old,'authorized_cwd':str(root),'authorized_max_seconds':old.get('authorized_max_seconds',old['max_seconds']),'cwd':str(target)}
        # Harness task duration is explicitly selected in the confirmed project
        # settings; a stale API-era ceiling must not silently reduce that value.
        if cfg.get('engine')=='harness':
            cfg['max_seconds']=max_seconds
            cfg['authorized_max_seconds']=max(cfg['authorized_max_seconds'],max_seconds)
        else:cfg['max_seconds']=min(max_seconds,cfg['authorized_max_seconds'])
        with self.hub.tx():
            if str(target)!=str(Path(old['cwd']).resolve()) and self.hub.db.execute("SELECT 1 FROM executions WHERE provider=? AND status IN ('queued','running','interrupting','waiting_quota')",(self.provider,)).fetchone():raise HubError('该接入仍在执行旧目录任务，完成后可继续切换项目；原任务与会话保留')
            self.hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(self.config_key,json.dumps(cfg)))
            self.hub.audit(actor,'deepseek.project_scope_bound',{'cwd':cfg['cwd'],'max_runs':cfg['max_runs'],'max_seconds':cfg['max_seconds'],'budget_renewed':False,'grant_changed':False,'workspace_reauthorized':rebound})
        return cfg

    def submit(self,actor,agent,instruction,confirmed=False,task_id=None,source_message_id=None,purpose="task",session_scope=None):
        self.hub.require(actor,{'user'})
        if confirmed is not True:raise HubError('请确认启动真实任务')
        if agent not in self.models:raise HubError('该身份不属于 '+self.title+' 真实执行器')
        from hub.core import text
        text(instruction,60000)
        if purpose not in ('task','discussion','question'):raise HubError('任务目的无效')
        with self.hub.tx():
            if getattr(self.hub,'coordination',None) and self.hub.coordination.is_stopped(agent):raise HubError('Agent 已被紧急停止，只能由用户解除启动锁')
            cfg=self.config()
            if not cfg['enabled']:raise HubError('请先配置并启用 '+self.title+' 真实执行')
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
                if not message:raise HubError('未找到待执行任务消息')
                message_id=message['id']
            else:
                task_id=uid();message_id=uid()
                self.hub.db.execute('INSERT INTO tasks(id,agent,title,assigned_by,created) VALUES(?,?,?,?,?)',(task_id,agent,instruction,actor,time.time()))
                self.hub.db.execute("INSERT INTO messages(id,sender,recipient,mode,body,status,created) VALUES(?,?,?,'queue',?,'pending',?)",(message_id,actor,agent,'[task:'+task_id+'] '+instruction,time.time()))
            if self.hub.db.execute('SELECT 1 FROM executions WHERE task_id=?',(task_id,)).fetchone():raise HubError('该任务已有真实执行记录，不自动重试；请检查后创建新任务')
            design_work=self.hub.db.execute('SELECT w.body FROM workflows w JOIN workflow_steps s ON s.workflow=w.id WHERE s.task=?',(task_id,)).fetchone()
            if design_work:
                workflow=json.loads(design_work[0])
                if workflow.get('design_dir'):cfg={**cfg,'cwd':workflow['design_dir']}
            run_id=uid()
            self.hub.db.execute("INSERT INTO executions(id,task_id,message_id,agent,model,prompt,actual_input,cwd,permission,max_seconds,grant_id,status,created,provider) VALUES(?,?,?,?,?,?,?,?,?,?,?,'queued',?,?)",(run_id,task_id,message_id,agent,self.models[agent],instruction,instruction,cfg['cwd'],cfg['permission'],cfg['max_seconds'],cfg['grant_id'],time.time(),self.provider))
            self.hub.db.execute('UPDATE executions SET purpose=?,session_scope=? WHERE id=?',(purpose,session_scope,run_id))
            self.hub.audit(actor,self.provider+'.authorized',{'run_id':run_id,'task_id':task_id,'model':self.models[agent],'permission':cfg['permission']})
        return {'id':run_id,'task_id':task_id,'status':'queued'}

    def guard(self,run):
        from hub.module_tools import guard
        return guard(self,run)

    def reserve(self,run,payload):
        cfg=self.config();size=len(json.dumps(payload,ensure_ascii=False).encode())
        if size>180000:raise HubError('上下文已达本地上限，请整理会话；不丢弃历史后自动执行')
        # UTF-8 bytes + framing bound, cache hits charged at the higher input price.
        out_tokens = cfg.get('max_output', 0)
        out_tokens = out_tokens if out_tokens > 0 else 8192
        amount=max(1,math.ceil(((size+4096)*cfg['input_rate']+out_tokens*cfg['output_rate'])/1000000))
        ident=uid()
        with self.hub.tx():
            self.hub.db.execute('INSERT INTO deepseek_spend VALUES(?,?,?,?,?,?,?)',(ident,run['grant_id'],run['id'],amount,'reserved',None,time.time()))
        return ident

    def definitions(self,run):
        from hub.module_tools import definitions
        return definitions(self,run)

    def tool(self,run,name,args,allowed):
        from hub.module_tools import tool
        return tool(self,run,name,args,allowed)

    def execute(self,run):
        from hub.harness_adapters import execute_builtin
        kind='deepseek-harness' if self.config().get('engine')=='harness' else 'deepseek-api'
        return execute_builtin(self,run,kind)

    def _execute_native(self,run):
        if self.config().get('engine')=='harness':
            from hub.deepseek_harness import execute
            return execute(self,run)
        run=dict(run);run['started']=time.time();status='failed';result='';submitted=False;key=self.sessions.key(run)
        try:
            self.guard(run)
            validation=self.saved_validation()
            if not validation or not validation.get('supported'):raise HubError('密钥或模型尚未验证；未发送付费请求')
            with self.hub.lock:
                row=None
                for context_key in self.sessions.context_keys(run):
                    row=self.hub.db.execute('SELECT body FROM deepseek_context WHERE key=?',(context_key,)).fetchone()
                    if row:break
                step=self.hub.db.execute('SELECT kind FROM workflow_steps WHERE task=?',(run['task_id'],)).fetchone()
            run['_read_only']=bool(step and step[0]=='check')
            if run.get('purpose')=='discussion':run['_read_only']=True
            history=json.loads(row[0]) if row else []
            w=self.hub.workflows.run_context(run['agent'],run['id'])[0] if step else None
            manager=bool(w and project_manager(self.hub,record=w)==run['agent'] and step[0] in ('plan','review'))
            from hub.module_sdk import instructions
            policy=instructions(self,run,style='tool_api',project=w,manager=manager)
            with self.hub.tx():self.hub.db.execute('UPDATE executions SET actual_input=? WHERE id=?',(run['prompt'],run['id']))
            history.append({'role':'user','content':run['prompt']})
            defs=self.definitions(run);allowed={t['function']['name'] for t in defs};cfg=self.config()
            out_tokens = cfg.get('max_output', 0)
            if out_tokens <= 0: out_tokens = 8192
            for _ in itertools.count():
                self.guard(run)
                if (run.get('session_scope') or '').startswith('connection-test:'):out_tokens=32
                payload={'model':run['model'],'messages':[{'role':'system','content':policy}]+history,'tools':defs,'max_tokens':out_tokens,'thinking':{'type':'disabled'},'stream':False}
                reservation=self.reserve(run,payload);submitted=True
                response=self.api.request('/chat/completions',payload)
                with self.hub.tx():self.hub.db.execute("UPDATE deepseek_spend SET status='returned',usage=? WHERE id=?",(json.dumps(response.get('usage')),reservation))
                self.check_latch(run)
                message=(response.get('choices') or [{}])[0].get('message')
                if not isinstance(message,dict):raise HubError('DeepSeek 未返回有效消息')
                history.append({k:v for k,v in message.items() if k in ('role','content','tool_calls','reasoning_content')})
                tools=message.get('tool_calls') or [];answered=set()
                if tools and (run.get('session_scope') or '').startswith('connection-test:'):raise HubError('测试回复包含工具调用，已拒绝；不重试或继续请求')
                for item in tools:
                    self.guard(run);name=item.get('function',{}).get('name');args=json.loads(item.get('function',{}).get('arguments','{}'))
                    self.record(run['id'],'deepseek.tool',{'name':name})
                    try:answer=self.tool(run,name,args,allowed)
                    except (HubError,OSError,TypeError,ValueError):answer={'error':'工具被拒绝或未完成，请查询项目状态；不得声称成功'}
                    self.record(run['id'],'deepseek.tool_result',{'name':name,'path':args.get('path'),'result':answer if name!='read_file' else '文件读取完成'})
                    history.append({'role':'tool','tool_call_id':item['id'],'content':json.dumps(answer,ensure_ascii=False)[:14000]});answered.add(item['id'])
                    if name=='project_complete' and isinstance(answer,dict) and answer.get('completed'):break
                    if name=='project_return_manager' and isinstance(answer,dict) and answer.get('saved'):
                        run['_return_requested']=True;break
                if run.get('_return_requested'):
                    for item in tools:
                        if item['id'] not in answered:history.append({'role':'tool','tool_call_id':item['id'],'content':'交接已申请，此工具未执行。'})
                with self.hub.lock:current=json.loads(self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(w['id'],)).fetchone()[0]) if w else {}
                if current.get('status')=='completed' and current.get('completion',{}).get('run_id')==run['id']:
                    result=json.dumps({'done':True,'report':current['report'],'tasks':[]},ensure_ascii=False);status='completed';break
                with self.hub.tx():
                    self.check_latch(run)
                    self.hub.db.execute('INSERT OR REPLACE INTO deepseek_context VALUES(?,?)',(key,json.dumps(history,ensure_ascii=False)))
                if run.get('_return_requested'):
                    result=json.dumps({'done':False,'report':'交回经理申请已保存，本轮结束后由平台交接','tasks':[]},ensure_ascii=False);status='completed';break
                if not tools:
                    result=message.get('content') or '';status='completed';break
            else:
                result=(message.get('content') if 'message' in locals() and message else '') or 'DeepSeek 执行完成';status='completed'
        except Exception as error:
            status='uncertain' if submitted else 'failed';result=str(error)[:1000] if isinstance(error,HubError) else 'DeepSeek 执行异常；保留现场，不自动重试'
        finally:
            status=self.quota_outcome(run,status,result)
            with self.hub.tx():
                if self.force_stopped(run):return
                self.hub.db.execute('UPDATE executions SET status=?,finished=?,result=? WHERE id=?',(status,time.time(),result,run['id']))
                self.hub.db.execute('UPDATE messages SET status=?,result=?,lease=NULL WHERE id=?',(status,result,run['message_id']))
                self.hub.db.execute("UPDATE agents SET status='idle',active=NULL,heartbeat=? WHERE id=? AND active=?",(time.time(),run['agent'],run['message_id']))
                self.hub.db.execute('UPDATE tasks SET status=?,progress=?,note=? WHERE id=?',('done' if status=='completed' else 'cancelled' if status=='cancelled' else 'blocked',100 if status=='completed' else 0,result,run['task_id']))
                self.hub.audit(run['agent'],'deepseek.'+status,{'run_id':run['id']})
            self.deliver_result(run,status,result)
