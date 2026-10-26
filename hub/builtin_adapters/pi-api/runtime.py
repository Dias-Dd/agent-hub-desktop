"""Lazy Pi subprocess: no process during discovery, refresh or idle."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from hub.core import HubError
from hub.process_job import ProcessJob
from hub import module_config

ROOT=Path(__file__).parent

def manifest():return json.loads((ROOT/'adapter.json').read_text(encoding='utf-8'))

def node():
    from hub.module_sdk import host_resource
    bundled=host_resource('builtin_adapters/pi-api/engine')/('node.exe' if os.name=='nt' else 'node')
    if bundled.is_file():return str(bundled)
    if getattr(sys,'frozen',False):raise HubError('内置 Node.js 资源缺失，请重新安装应用')
    from hub.cli_paths import which
    found=which('node')
    if not found:raise HubError('源码运行需要 Node.js 22.19 或更新版本')
    return found

def configuration(registry,connection,module_manifest=None):
    if connection['kind'] in ('deepseek-api','openrouter-api','gemini-api') or module_manifest and module_manifest.get('api'):
        from hub.integrations import BASES
        kind=connection['kind'];base,env=BASES.get(kind,('',''))
        api=(module_manifest or {}).get('api') or {}
        base=api.get('base_url',base);env=connection.get('key_env') or api.get('key_environment',env)
        env=(module_manifest or {}).get('environment',{}).get(env,env)
        if not base or not os.environ.get(env):raise HubError('旧 API 接入缺少地址或密钥环境变量，请配置后重新打开应用')
        return {'protocol':'openai-completions','base_url':base,'api_key':os.environ[env],
            'models':[m['id'] for m in connection.get('models',[])],'context_window':128000,'max_tokens':8192}
    value=module_config.resolved(registry,connection,manifest())
    name=value.get('key_env','')
    if name:
        import re
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name):raise HubError('密钥环境变量名无效')
        value['api_key']=os.environ.get(name,'')
    if not value.get('api_key'):raise HubError('请填写 API Key 或有效的密钥环境变量')
    return value

def configure(registry,connection,config=None):
    if config is not None:
        if config.get('api_key') and config.get('key_env'):raise HubError('API Key 与环境变量请选择一种')
        if config.get('max_tokens',8192)>config.get('context_window',128000):raise HubError('最大输出不能超过上下文窗口')
    value=module_config.generic(registry,connection,manifest(),config)
    if config is not None:
        with registry.hub.tx():
            row=registry.get('integration_connections',connection['id']);row['models']=[];row.pop('probed_at',None);registry.put('integration_connections',row)
    value['note']='Pi 只在 API 任务执行时启动。目录读取不发送推理请求；预设模型不代表账号权限。'
    return value

def probe(registry,connection):
    cfg=configuration(registry,connection);models=cfg.get('models') or []
    if not models:
        base=cfg['base_url'].rstrip('/');headers={}
        if cfg['protocol']=='google-generative-ai':headers['x-goog-api-key']=cfg['api_key']
        elif cfg['protocol']=='anthropic-messages':headers.update({'x-api-key':cfg['api_key'],'anthropic-version':'2023-06-01'})
        else:headers['Authorization']='Bearer '+cfg['api_key']
        try:
            with urllib.request.urlopen(urllib.request.Request(base+'/models',headers=headers),timeout=20) as response:
                raw=response.read(2000001)
                if len(raw)>2000000:raise ValueError()
                body=json.loads(raw)
            models=[m.get('id') or m.get('name','').removeprefix('models/') for m in body.get('data',body.get('models',[]))]
        except Exception:raise HubError('模型目录读取失败；可手动填写模型 ID，不自动发送推理测试') from None
    if not models or len(models)>1000 or any(not isinstance(x,str) or not x or len(x)>200 for x in models):raise HubError('模型目录无效，请手动填写模型 ID')
    return {'models':[{'id':m,'name':m,'efforts':['default'],'source':'api_catalog'} for m in dict.fromkeys(models)],'verification':'API 模型目录，实际调用权限需接入测试确认'}

class Bridge:
    def __init__(self,cwd,environment=None):
        from hub.module_sdk import host_resource
        engine=host_resource('builtin_adapters/pi-api/engine')
        bundle=engine/'bridge.bundle.mjs';entry=bundle if bundle.is_file() else engine/'bridge.mjs'
        self.events=queue.Queue();self.errors=[]
        self.proc=subprocess.Popen([node(),str(entry)],cwd=cwd,env=environment,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
        self.job=ProcessJob(self.proc)
        def reader():
            try:
                while True:
                    line=self.proc.stdout.readline(8000001)
                    if not line:break
                    if len(line)>8000000:raise ValueError('Pi 事件过大')
                    self.events.put(json.loads(line))
            except Exception:self.events.put({'type':'error','message':'Pi 通信异常'})
            finally:self.events.put({'type':'eof'})
        def errors():
            while self.proc.stderr.read(4096):pass # Never expose credentials in SDK diagnostic output.
        self.threads=[threading.Thread(target=f,daemon=True) for f in (reader,errors)]
        for thread in self.threads:thread.start()
    def send(self,value):self.proc.stdin.write(json.dumps(value,ensure_ascii=False)+'\n');self.proc.stdin.flush()
    def close(self):
        self.job.close()
        try:self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
        for thread in self.threads:thread.join(timeout=2)
        for stream in (self.proc.stdin,self.proc.stdout,self.proc.stderr):
            try:stream.close()
            except OSError:pass

def execute(host,run):
    run={**run,'started':time.time()}
    bridge=None;reservation=None;submitted=False;status='failed';result='';usage=None;terminal=None
    try:
        host.guard(run);cfg=configuration(host.registry,host.connection(),getattr(host,'_module_manifest',None));key=host.sessions.key(run)
        run['_read_only']=host.read_only(run)
        with host.hub.lock:row=host.hub.db.execute('SELECT body FROM deepseek_context WHERE key=?',('pi:'+key,)).fetchone()
        history=json.loads(row[0]) if row else []
        if not row:
            with host.hub.lock:
                for old_key in host.sessions.context_keys(run):
                    old=host.hub.db.execute('SELECT body FROM deepseek_context WHERE key=?',(old_key,)).fetchone()
                    if old:
                        history=convert_history(json.loads(old[0]),run['model']);break
        # A previous uncertain turn cannot silently become a fresh conversation.
        if history and history[-1].get('role') in ('assistant','toolResult') and history[-1].get('stopReason')=='toolUse':raise HubError('上轮工具结果未确认，请核实项目状态后恢复，未重放工具')
        with host.hub.lock:step=host.hub.db.execute('SELECT kind FROM workflow_steps WHERE task=?',(run['task_id'],)).fetchone()
        w=host.hub.workflows.run_context(run['agent'],run['id'])[0] if step else None
        from hub.module_sdk import instructions
        from hub.manager_identity import resolve
        policy=instructions(host,run,style='tool_api',project=w,manager=bool(w and resolve(host.hub,record=w)==run['agent'] and step[0] in ('plan','review')))
        defs=host.definitions(run);allowed={t['function']['name'] for t in defs}
        model={'id':run['model'],'name':run['model'],'api':cfg['protocol'],'provider':'hub-api','baseUrl':cfg['base_url'],'reasoning':False,
            'input':['text'],'contextWindow':cfg['context_window'],'maxTokens':cfg['max_tokens'],'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0}}
        from hub.proxy_env import inherit_system_proxy
        env=inherit_system_proxy({k:v for k,v in os.environ.items() if k not in ('NODE_OPTIONS','NODE_PATH') and not k.startswith('PI_')})
        env['PI_TELEMETRY_DISABLED']='1'
        bridge=Bridge(run['cwd'],env);host.track_client(run,bridge)
        with host.hub.tx():host.hub.db.execute('UPDATE executions SET actual_input=? WHERE id=?',(run['prompt'],run['id']))
        bridge.send({'type':'run','model':model,'api_key':cfg['api_key'],'system':policy,'tools':defs,'history':history,'prompt':run['prompt'],
            'max_tokens':32 if (run.get('session_scope') or '').startswith('connection-test:') else cfg['max_tokens']})
        deadline=time.monotonic()+run['max_seconds']
        while True:
            host.guard(run)
            if time.monotonic()>deadline:raise HubError('Pi 执行超时；保留现场，不自动重试')
            try:event=bridge.events.get(timeout=.25)
            except queue.Empty:continue
            kind=event.get('type')
            if kind=='reserve':
                if terminal:raise HubError('项目已完成，不允许继续请求')
                reservation=host.reserve(run,event['payload']);submitted=True;bridge.send({'type':'reply','id':event['id']})
            elif kind=='delta':host.public_reply(run,event['text'],phase='正在生成回复')
            elif kind=='checkpoint':
                body=json.dumps(event['history'],ensure_ascii=False)
                if len(body.encode())>4000000:raise HubError('Pi 会话超过存储上限，未截断历史')
                with host.hub.tx():
                    host.hub.db.execute('INSERT OR REPLACE INTO deepseek_context VALUES(?,?)',('pi:'+key,body))
                    if reservation and event['history'] and event['history'][-1].get('role')=='assistant':host.hub.db.execute("UPDATE deepseek_spend SET status='returned',usage=? WHERE id=?",(json.dumps(event['history'][-1].get('usage')),reservation))
                bridge.send({'type':'reply','id':event['id']})
            elif kind=='tool':
                if terminal:
                    bridge.send({'type':'reply','id':event['id'],'value':{'error':'本轮已结束，此工具未执行'},'is_error':True,'terminate':True});continue
                if (run.get('session_scope') or '').startswith('connection-test:'):raise HubError('接入测试不允许调用工具')
                host.record(run['id'],'pi.tool',{'name':event['name']})
                try:answer=host.tool(run,event['name'],event['args'],allowed)
                except Exception as error:answer={'error':str(error) if isinstance(error,HubError) else '工具未完成；请核实状态，不得声称成功'}
                if event['name']=='project_complete' and isinstance(answer,dict) and answer.get('completed'):
                    with host.hub.lock:current=json.loads(host.hub.db.execute('SELECT body FROM workflows WHERE id=?',(w['id'],)).fetchone()[0]) if w else {}
                    terminal=json.dumps({'done':True,'report':current.get('report','项目已完成'),'tasks':[]},ensure_ascii=False)
                if event['name']=='project_return_manager' and isinstance(answer,dict) and answer.get('saved'):terminal=json.dumps({'done':False,'report':'交回经理申请已保存，本轮结束后由平台交接','tasks':[]},ensure_ascii=False)
                bridge.send({'type':'reply','id':event['id'],'value':answer,'is_error':isinstance(answer,dict) and bool(answer.get('error')),'terminate':bool(terminal)})
            elif kind=='result':
                result=terminal or event.get('text','');usage=event.get('usage')
                if not result.strip():raise HubError('Pi 未返回文字结果，不能确认完成')
                status='completed';break
            elif kind in ('error','eof'):
                if terminal:result=terminal;status='completed';break
                message=event.get('message','Pi 提前退出，未确认执行结果').replace(cfg['api_key'],'[redacted]')
                raise HubError(message[:1000])
    except Exception as error:
        with host.hub.lock:state=host.hub.db.execute('SELECT stop_requested FROM executions WHERE id=?',(run['id'],)).fetchone()
        status='interrupted' if host.stop_event.is_set() or state and state[0] else 'uncertain' if submitted else 'failed'
        result=(str(error) if isinstance(error,HubError) else 'Pi 执行异常，保留现场，不自动重试')
    finally:
        if bridge:bridge.close()
        host.clients.pop(run['id'],None);host.sessions.state(run,status);host.finalize(run,status,result,usage)

def convert_history(history,model):
    """Preserve legacy tool/result pairs; never re-execute them during migration."""
    result=[];names={}
    for item in history:
        role=item.get('role');message={'role':role,'timestamp':int(time.time()*1000)}
        if role in ('user','system'):message['content']=item.get('content') or ''
        elif role=='assistant':
            content=[{'type':'text','text':item['content']}] if item.get('content') else []
            for tool in item.get('tool_calls') or []:
                f=tool['function'];names[tool['id']]=f['name'];content.append({'type':'toolCall','id':tool['id'],'name':f['name'],'arguments':json.loads(f['arguments'])})
            message.update(content=content,api='openai-completions',provider='hub-api',model=model,stopReason='toolUse' if item.get('tool_calls') else 'stop',
                usage={'input':0,'output':0,'cacheRead':0,'cacheWrite':0,'totalTokens':0,'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0,'total':0}})
        elif role=='tool':message.update(role='toolResult',toolCallId=item['tool_call_id'],toolName=names.get(item['tool_call_id'],'unknown'),content=[{'type':'text','text':item.get('content') or ''}],isError=False)
        else:raise HubError('旧 API 历史格式无法转换，已保留原会话')
        result.append(message)
    return result
