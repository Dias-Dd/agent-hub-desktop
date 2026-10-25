from hub.module_sdk import host_resource
from hub.manager_identity import resolve as project_manager
"""Official installed DeepSeek Harness ACP adapter (no desktop-private APIs)."""
import hashlib,json,os,queue,shutil,subprocess,sys,tempfile,threading,time
from pathlib import Path
from hub.core import HubError
from hub.user_followup import direct as direct_followup
from hub.process_job import ProcessJob
from hub.cli_paths import cli_environment as inherit_system_proxy

DISABLED_ALWAYS=['otel','session-telemetry','deepseek-account','llm-deepseek-account','tool-plugin-manager','tool-subagent','tool-subagent-fork','tool-subagent-control','tool-subagent-list-agents','tool-workflow','workflow-ptc','goal-round-driver','tool-goal','tool-working-directory']
DIALOGUE_TOOLS=['tool-bash','tool-pwsh','tool-jobs','tool-fs','tool-fs-search','tool-skill','tool-web','tool-todo']

# Official Cordis extension seam: synchronize a resumed session through the
# public PermissionPresetService.set API, never edit native session logs.
PERMISSION_PLUGIN = r"""
const fs = require('node:fs');
const path = require('node:path');
exports.name = 'hub-permission-sync';
exports.inject = ['permissionPresets', 'sandboxPolicy', 'workingDirectory'];
exports.apply = (ctx, config) => {
  const modes = ['read-only', 'workspace-write', 'danger-full-access'];
  if (!modes.includes(config.mode)) throw new Error('Hub permission mode is invalid');
  const root = path.resolve(config.workspaceRoot);
  if (!path.isAbsolute(config.workspaceRoot) || !fs.statSync(root).isDirectory()) throw new Error('Hub workspace must be an existing absolute directory');
  const service = ctx.sandboxPolicy;
  const original = service.resolve;
  // This Hub-owned process hosts one agent/run. Bind its public request-time
  // policy to the approved workspace without mutating the immutable session header.
  service.resolve = function(request = {}) { return { ...original.call(this, request), mode: config.mode, workspaceRoot: root }; };
  const directory = ctx.workingDirectory;
  const originalGet = directory.get;
  directory.get = function() { return root; };
  ctx.effect(() => () => { service.resolve = original; directory.get = originalGet; });
  ctx.on('session/created', session => {
    ctx.permissionPresets.set(session, config.mode);
    const actual = ctx.sandboxPolicy.resolve({session});
    if (actual.mode !== config.mode) throw new Error('Hub permission sync was not applied');
    fs.writeFileSync(config.record, JSON.stringify({sessionId: session.id, mode: actual.mode, workspaceRoot: actual.workspaceRoot, workingDirectory: ctx.workingDirectory.get(session)}), 'utf8');
  });
};
"""


def installation(config=None):
    supplied=(config or {}).get('harness_install')
    if sys.platform=='darwin':
        candidates=[Path(supplied)] if supplied else [Path('/Applications/DeepSeek Harness.app'),Path.home()/'Applications/DeepSeek Harness.app']
        for root in candidates:
            if root.name=='DeepSeek Harness' and root.parent.name=='MacOS':root=root.parents[2]
            contents=root if root.name=='Contents' else root/'Contents'
            exe=contents/'MacOS/DeepSeek Harness'
            launcher=contents/'Resources/runtime/cli/bin/dsh'
            cli=contents/'Resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js'
            # Electron resolves the ASAR entry; it is not an ordinary filesystem path.
            if exe.is_file() and launcher.is_file() and os.access(exe,os.X_OK) and (contents/'Resources/app.asar').is_file():return exe,cli
        raise HubError('未找到官方 DeepSeek Harness.app；请安装到 Applications 或指定应用路径')
    root=Path(supplied) if supplied else Path(os.environ.get('LOCALAPPDATA',''))/'Programs'/'DeepSeek Harness'
    exe=root/'DeepSeek Harness.exe'
    cli=root/'resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js'
    if not exe.is_file() or not (root/'resources/runtime/cli/bin/dsh.cmd').is_file():raise HubError('未找到已安装的官方 DeepSeek Harness；不会回退到简化 API 执行器')
    return exe,cli

def patch_text(agent,role,dialogue=False,policy="",workspace_root=None,sandbox_mode="read-only",permission_plugin=None,permission_record=None,manager=None,model="deepseek-flash",provider="deepseek-official",credentials_path=None):
    from hub.module_sdk import persona_prefix
    persona=persona_prefix(agent,role,manager,model)
    rows=[{'id':'acp','config':{'provider':provider,'model':model}}, {'id':'system-prompt','config':{'personaPrefix':persona+'\n'+policy}}, {'id':'skill-filesystem','config':{'includeDefaultRoots':False}}]
    if sandbox_mode not in ('read-only','workspace-write','danger-full-access'):raise HubError('Harness 文件权限模式无效')
    sandbox={'mode':sandbox_mode}
    if workspace_root:sandbox['workspaceRoot']=workspace_root
    rows.append({'id':'sandbox-policy','config':sandbox})
    if permission_plugin:rows.append({'insert':[{'id':'hub-permission-sync','name':permission_plugin,'config':{'mode':sandbox_mode,'record':permission_record,'workspaceRoot':workspace_root}}]})
    rows += [{'id':ident,'disabled':True} for ident in DISABLED_ALWAYS+(DIALOGUE_TOOLS if dialogue else []) if provider!='deepseek-account' or ident not in ('deepseek-account','llm-deepseek-account')]
    if provider=='deepseek-account':
        from .account import account_rows
        rows+=account_rows(credentials_path)
    elif credentials_path:
        from .account import account_rows
        rows+=account_rows(credentials_path) # Resuming an account session needs its provider before switching models.
    # JSON flow values are valid YAML. No credentials are written into this patch.
    return '\n'.join('- '+json.dumps(row,ensure_ascii=False) for row in rows)+'\n'

class ACP:
    def __init__(self,argv,cwd,env,on_update=None,permission=False,factory=subprocess.Popen):
        self.on_update=on_update or (lambda _u:None);self.permission=permission;self.queue=queue.Queue();self.lock=threading.Lock();self.serial=0;self.responses={};self.errors=[];self.redactions=[env.get('DEEPSEEK_API_KEY',''),env.get('HUB_TOKEN','')]
        self.proc=factory(argv,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',start_new_session=os.name!='nt',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:self.job=ProcessJob(self.proc)
        except Exception:self.proc.kill();self.proc.wait();raise
        self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
        self.drainer=threading.Thread(target=self._stderr,daemon=True);self.drainer.start()
    def clean(self,text):
        for value in self.redactions:
            if value:text=text.replace(value,'[redacted]')
        return text
    def _read(self):
        try:
            noise=0
            for line in self.proc.stdout:
                if len(line)>4000000:self.queue.put({'transport_error':'Harness 协议帧过大'});break
                line=line.lstrip('\ufeff').strip()
                if not line:continue
                try:value=json.loads(line)
                except ValueError:
                    noise+=1
                    if '"jsonrpc"' in line or noise>32:
                        self.queue.put({'transport_error':'Harness ACP 协议损坏或非协议输出持续过多'});break
                    self.errors=(self.errors+['[stdout diagnostic] '+self.clean(line[:400])])[-12:]
                    continue
                if not isinstance(value,dict) or not ('id' in value or 'method' in value):
                    noise+=1
                    if noise>32:self.queue.put({'transport_error':'Harness ACP 持续输出无效帧'});break
                    continue
                noise=0
                self.queue.put(value)
        finally:self.queue.put({'eof':True})
    def _stderr(self):
        for line in self.proc.stderr:self.errors=(self.errors+[self.clean(line.strip())])[-12:]
    def write(self,message):
        with self.lock:
            self.proc.stdin.write(json.dumps(message,ensure_ascii=False)+'\n');self.proc.stdin.flush()
    def begin(self,method,params):
        self.serial+=1;ident=self.serial;self.write({'jsonrpc':'2.0','id':ident,'method':method,'params':params});return ident
    def notify(self,method,params):self.write({'jsonrpc':'2.0','method':method,'params':params})
    def dispatch(self,message):
        if message.get('transport_error'):raise HubError(message['transport_error'])
        if message.get('eof'):raise HubError('Harness ACP 进程退出；'+self.clean('\n'.join(self.errors))[-1200:])
        if message.get('method')=='session/update':self.on_update(message.get('params',{}));return
        if 'method' in message and 'id' in message:
            if message['method']=='session/request_permission':
                options=message.get('params',{}).get('options',[])
                chosen=next((x for x in options if x.get('kind')==('allow_once' if self.permission else 'reject_once')),None)
                outcome={'outcome':'selected','optionId':chosen['optionId']} if chosen else {'outcome':'cancelled'}
                self.write({'jsonrpc':'2.0','id':message['id'],'result':{'outcome':outcome}})
            else:self.write({'jsonrpc':'2.0','id':message['id'],'error':{'code':-32601,'message':'Unsupported client method'}})
        elif 'id' in message:self.responses[message['id']]=message
    def wait(self,ident,guard=None,timeout=60):
        deadline=time.monotonic()+timeout
        while ident not in self.responses:
            if guard:guard()
            if time.monotonic()>deadline:raise HubError('Harness ACP 操作超时；不自动重试')
            try:self.dispatch(self.queue.get(timeout=.2))
            except queue.Empty:pass
        response=self.responses.pop(ident)
        if 'error' in response:raise HubError('Harness ACP: '+self.clean(str(response['error'].get('message','请求失败')))[:1600])
        return response.get('result',{})
    def request(self,method,params,guard=None,timeout=60):return self.wait(self.begin(method,params),guard,timeout)
    def close(self):
        try:self.proc.stdin.close()
        except (OSError,ValueError):pass
        try:self.proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self.job.close()
            try:self.proc.kill()
            except OSError:pass
            self.proc.wait(timeout=4)
        self.job.close();self.reader.join(timeout=1);self.drainer.join(timeout=1)


def execute(runtime,run):
    run=dict(run);run['started']=time.time();status='failed';result='';client=None;session=None;prompt_id=None;parts=[];usage=None;renew_stop=threading.Event()
    def guard():runtime.guard(run)
    def renew():
        while not renew_stop.wait(3):
            with runtime.hub.tx():
                runtime.hub.db.execute('UPDATE agents SET heartbeat=? WHERE id=? AND active=?',(time.time(),run['agent'],run['message_id']))
                runtime.hub.db.execute("UPDATE messages SET lease=? WHERE id=? AND status='acknowledged'",(time.time()+30,run['message_id']))
    renewal=threading.Thread(target=renew,daemon=True);renewal.start()
    try:
        guard();cfg=runtime.config();exe,cli=installation(cfg)
        from .account import auth
        provider,credential_path,authentication=auth(runtime,cfg)
        with runtime.hub.lock:
            step=runtime.hub.db.execute('SELECT kind FROM workflow_steps WHERE task=?',(run['task_id'],)).fetchone()
            role=runtime.hub.agent(run['agent'])['role']
        dialogue=not step and run.get('purpose') in ('question','discussion')
        read_only=dialogue or bool(step and (step[0]=='check' or run.get('purpose')=='question'))
        mode='read-only' if read_only else ('danger-full-access' if run['permission']=='full' else 'workspace-write')
        project=runtime.hub.workflows.run_context(run['agent'],run['id'])[0] if step else None
        from hub.prompt_identity import identity
        person=identity(runtime.hub,run,project);role=person['role']
        from hub.module_sdk import instructions
        policy=instructions(runtime,run,style='tool_agent',project=project,read_only=read_only,dialogue=dialogue)
        key=runtime.sessions.key(run)
        with runtime.hub.lock:old=runtime.hub.db.execute('SELECT * FROM harness_sessions WHERE key=?',(key,)).fetchone()
        target_cwd=str(Path(run['cwd']).resolve())
        session_cwd=old['cwd'] if old else target_cwd
        moved=bool(old and Path(session_cwd).resolve()!=Path(target_cwd))
        if moved:
            from hub.module_sdk import workspace_notice
            policy+=workspace_notice(target_cwd)
        home=runtime.hub.directory/'harness'/run['agent'];home.mkdir(parents=True,exist_ok=True)
        permission_plugin=home/'permission-sync.cjs';permission_plugin.write_text(PERMISSION_PLUGIN,encoding='utf-8')
        permission_record=home/('permission-'+run['id']+'.json')
        patch=home/'hub.patch.yml';patch.write_text(patch_text(run['agent'],role,dialogue,policy,workspace_root=target_cwd,sandbox_mode=mode,permission_plugin=str(permission_plugin.resolve()),permission_record=str(permission_record.resolve()),manager=person['manager'],model=run['model'],provider=provider,credentials_path=credential_path),encoding='utf8')
        env=inherit_system_proxy(dict(os.environ));env.update(ELECTRON_RUN_AS_NODE='1',DSH_HOME=str(home.resolve()),DSH_PERMISSION_MODE=mode);env.pop('DEEPSEEK_API_KEY',None);env.update(authentication)
        # ACP mounts a fresh, run-bound MCP bridge on both new and resumed sessions.
        bridge={'name':'agent-message-hub','command':sys.executable,'args':[str(host_resource('mcp.py').resolve())],'env':[]}
        run['_read_only']=read_only
        allowed=[x['function']['name'] for x in runtime.definitions(run) if x['function']['name'] not in ('read_file','write_file','run_command')]
        if allowed and getattr(sys,'frozen',False) and sys.platform=='darwin':
            bridge['command']=sys.executable;bridge['args']=['--mcp-server']
        elif allowed and getattr(sys,'frozen',False):
            companion=Path(sys.executable).with_name(Path(sys.executable).name.replace('AgentMessageHubDesktop','AgentHubMcp'))
            if not companion.is_file():raise HubError('安装包缺少 AgentHubMcp.exe，请重新安装完整应用')
            bridge['command']=str(companion);bridge['args']=[]
        for name,value in {'HUB_URL':runtime.hub.url,'HUB_TOKEN':runtime.hub.tokens[run['agent']],'HUB_AGENT':run['agent'],'HUB_RUN_ID':run['id'],'HUB_TOOL_ALLOWLIST':json.dumps(allowed)}.items():bridge['env'].append({'name':name,'value':value})
        def update(params):
            nonlocal usage
            value=params.get('update',{});kind=value.get('sessionUpdate')
            if kind=='agent_message_chunk':
                content=value.get('content',{})
                if content.get('type')=='text':
                    parts.append(content.get('text',''));runtime.public_reply(run,client.clean(content.get('text','')) if client else content.get('text',''),phase='正在生成回复')
            elif kind in ('tool_call','tool_call_update'):
                if kind=='tool_call':
                    parts.clear();runtime.public_reply(run,'',replace=True,phase='正在使用工具：'+str(value.get('title') or value.get('kind') or '项目工具'))  # pre-tool narration is not the final response
                runtime.record(run['id'],'deepseek.harness.tool',{k:value.get(k) for k in ('toolCallId','title','kind','status') if value.get(k) is not None})
            elif kind=='usage_update':usage={'harness_context':value}
        client=ACP([str(exe),'--expose-internals',str(cli),'--profile','acp','--patch',str(patch.resolve())],session_cwd,env,update,mode=='danger-full-access');runtime.track_client(run,client);client.redactions.append(runtime.hub.tokens[run['agent']])
        init=client.request('initialize',{'protocolVersion':1,'clientCapabilities':{},'clientInfo':{'name':'agent-message-hub','version':'0.1'}},guard)
        if init.get('protocolVersion')!=1 or init.get('agentInfo',{}).get('name')!='deepseek-harness-acp':raise HubError('Harness 未返回受支持的 ACP 身份')
        params={'cwd':str(Path(session_cwd).resolve()),'mcpServers':[bridge] if allowed else []}
        if old:
            session=old['session_id'];view=client.request('session/resume',{**params,'sessionId':session},guard)
        else:
            view=client.request('session/new',params,guard);session=view.get('sessionId')
            if not isinstance(session,str) or not session:raise HubError('Harness 未返回持久会话 ID')
        try:permission_state=json.loads(permission_record.read_text(encoding='utf-8'))
        except (OSError,ValueError) as error:raise HubError('Harness 未确认当前会话文件权限；尚未发送模型请求') from error
        if permission_state.get('sessionId')!=session or permission_state.get('mode')!=mode:raise HubError('Harness 会话实际权限与当前授权不一致；尚未发送模型请求')
        if mode=='workspace-write' and Path(permission_state.get('workspaceRoot','')).resolve()!=Path(target_cwd):raise HubError('Harness 未确认当前项目的实际写入边界；未发送模型请求，会话保留')
        runtime.record(run['id'],'deepseek.harness.permission_verified',{**permission_state,'target_cwd':target_cwd,'workspace_matches_target':Path(permission_state.get('workspaceRoot',session_cwd)).resolve()==Path(target_cwd).resolve()})
        selected=next((x.get('currentValue') for x in view.get('configOptions',[]) if x.get('id')=='model'),None)
        expected=json.dumps([provider,run['model']],separators=(',',':'))
        if selected!=expected:
            view=client.request('session/set_config_option',{'sessionId':session,'configId':'model','value':expected},guard)
            selected=next((x.get('currentValue') for x in view.get('configOptions',[]) if x.get('id')=='model'),None)
            if selected!=expected:raise HubError('Harness 模型核验失败；禁止静默换模型')
        effort=runtime.efforts()[run['agent']]
        options=next((x for x in view.get('configOptions',[]) if x.get('id')=='reasoning_effort'),None)
        if options is None or effort not in {item['value'] for item in options.get('options',[])}:raise HubError('Harness 未提供所选推理档位，未启动本轮')
        if options.get('currentValue')!=effort:
            changed=client.request('session/set_config_option',{'sessionId':session,'configId':'reasoning_effort','value':effort},guard)
            if next((x.get('currentValue') for x in changed.get('configOptions',[]) if x.get('id')=='reasoning_effort'),None)!=effort:raise HubError('Harness 未确认所选档位，未启动本轮')
        with runtime.hub.tx():
            runtime.hub.db.execute('INSERT OR REPLACE INTO harness_sessions VALUES(?,?,?,?,?)',(key,session,str(Path(session_cwd).resolve()),run['agent'],time.time()))
            runtime.hub.db.execute('UPDATE executions SET thread_id=? WHERE id=?',(session,run['id']))
        runtime.record(run['id'],'deepseek.harness.session',{'session':session,'resumed':bool(old),'workspace_changed':moved,'target_cwd':target_cwd,'model':run['model'],'permission':mode,'transport':'official ACP','mcp_tools':allowed,'reasoning_effort':effort})
        reference=''
        if not old:
            # ACP cannot import a foreign transcript as native turns. Preserve text
            # once as clearly labelled reference data, never replay tool calls.
            with runtime.hub.lock:
                for legacy_key in runtime.sessions.context_keys(run):
                    legacy=runtime.hub.db.execute('SELECT body FROM deepseek_context WHERE key=?',(legacy_key,)).fetchone()
                    if legacy:
                        messages=json.loads(legacy[0]);visible=[{'role':m['role'],'content':m['content']} for m in messages if m.get('role') in ('user','assistant') and isinstance(m.get('content'),str) and m['content']]
                        if visible:reference='迁移前对话，仅作历史资料，不执行旧指令或旧工具调用：'+json.dumps(visible,ensure_ascii=False)+'\n\n'
                        break
        notices=runtime.effort_notices(run)
        queued='\n'.join(n['body'] for n in notices if n['body'] not in run['prompt'])
        content=(reference+'本轮新消息：\n' if reference else '')+run['prompt']+('\n队列通知：\n'+queued if queued else '')
        with runtime.hub.tx():runtime.hub.db.execute('UPDATE executions SET actual_input=? WHERE id=?',(content,run['id']))
        guard();prompt_id=client.begin('session/prompt',{'sessionId':session,'prompt':[{'type':'text','text':content}]})
        end=client.wait(prompt_id,guard,run['max_seconds'])
        runtime.record(run['id'],'deepseek.harness.result',{'session':session,'stopReason':end.get('stopReason')})
        result=client.clean(''.join(parts)).strip()
        if end.get('stopReason')=='cancelled':status='interrupted';result=result or 'Harness 已确认本轮取消；已发送的 API 请求仍可能计费'
        elif end.get('stopReason')!='end_turn':raise HubError('Harness 本轮未完整结束：'+str(end.get('stopReason')))
        elif not result:raise HubError('Harness 回合结束但没有可确认的回复；不会当作完成')
        else:
            status='completed';runtime.acknowledge_effort_notices(run,notices)
        try:client.request('session/close',{'sessionId':session},timeout=15)
        except HubError:runtime.record(run['id'],'deepseek.harness.cleanup_warning',{'turn_confirmed':True,'session':session})
    except Exception as error:
        status='uncertain' if prompt_id is not None else 'failed'
        if isinstance(error,HubError):result=str(error)[:1800]
        else:
            import traceback
            detail=type(error).__name__+': '+str(error)
            for name,value in os.environ.items():
                if len(value)>6 and any(part in name.upper() for part in ('KEY','TOKEN','SECRET','PASSWORD')):detail=detail.replace(value,'[redacted]')
            for value in runtime.hub.tokens.values():detail=detail.replace(value,'[redacted]')
            if client:detail=client.clean(detail)
            frames=traceback.extract_tb(error.__traceback__)
            runtime.record(run['id'],'deepseek.harness.internal_error',{'error':detail[:1600],'location':[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in frames[-4:]],'auto_retry':False})
            result='Harness 本地执行错误：'+detail[:1600]+'；会话保留，不自动重试'
        if client:result=client.clean(result)
        with runtime.hub.lock:state=runtime.hub.db.execute('SELECT stop_requested FROM executions WHERE id=?',(run['id'],)).fetchone()
        if client and session and state and (state[0] or runtime.stop_event.is_set()):
            try:
                client.notify('session/cancel',{'sessionId':session})
                end=client.wait(prompt_id,timeout=5) if prompt_id else {}
                if end.get('stopReason')=='cancelled':status='interrupted';result=result or 'Harness 已确认本轮取消；已发送的 API 请求仍可能计费';result='Harness 已确认本轮取消；已发送的 API 请求费用仍可能产生'
            except Exception:result+='；本地进程树已停止，提供商取消状态未知'
    finally:
        renew_stop.set();renewal.join(timeout=4)
        if client:client.close()
        runtime.clients.pop(run['id'],None)
        status=runtime.quota_outcome(run,status,result)
        with runtime.hub.tx():
            if runtime.force_stopped(run):return
            runtime.hub.db.execute('UPDATE executions SET status=?,finished=?,result=?,usage=? WHERE id=?',(status,time.time(),result,json.dumps(usage) if usage else None,run['id']))
            runtime.hub.db.execute('UPDATE messages SET status=?,result=?,lease=NULL WHERE id=?',(status,result,run['message_id']))
            runtime.hub.db.execute("UPDATE agents SET status='idle',active=NULL,heartbeat=? WHERE id=? AND active=?",(time.time(),run['agent'],run['message_id']))
            runtime.hub.db.execute('UPDATE tasks SET status=?,progress=?,note=? WHERE id=?',('done' if status=='completed' else 'cancelled' if status=='cancelled' else 'blocked',100 if status=='completed' else 0,result,run['task_id']))
            runtime.hub.audit(run['agent'],'deepseek.harness.'+status,{'run_id':run['id'],'session':session})
        runtime.deliver_result(run,status,result)


def catalog_entries(view,route="deepseek-official"):
    option=next((x for x in view.get('configOptions',[]) if x.get('id')=='model'),{})
    result={}
    def visit(items):
        for item in items:
            if 'options' in item:
                visit(item['options']);continue
            try:provider,model=json.loads(item.get('value',''))
            except (ValueError,TypeError):continue
            if provider==route and isinstance(model,str) and model:
                result[model]={'id':model,'name':item.get('name') or model,'source':'official_acp','efforts':[]}
    visit(option.get('options',[]))
    return list(result.values())


def probe_catalog(runtime,config=None):
    """Read official ACP choices without sending session/prompt or inference."""
    cfg=config or runtime.config()
    exe,cli=installation(cfg)
    from .account import auth,account_rows,credential_store
    provider,credential_path,authentication=auth(runtime,cfg)
    with tempfile.TemporaryDirectory(prefix='hub-harness-catalog-') as tmp:
        home=Path(tmp);patch=home/'catalog.patch.yml'
        plugin=home/'catalog.cjs'; output=home/'catalog.json'
        plugin.write_text("""const fs=require('node:fs');exports.name='hub-model-catalog';exports.inject=['llm','deepseekAccount','credentials'];exports.apply=async(ctx,c)=>{try{const models=await ctx.llm.listModels(c.provider);fs.writeFileSync(c.output,JSON.stringify({models:models.map(m=>({id:m.id,name:m.name||m.id}))}));}catch(e){fs.writeFileSync(c.output,JSON.stringify({error:'Official model catalog unavailable'}));}};""",encoding='utf-8')
        rows={'insert':[{'id':'hub-model-catalog','name':str(plugin),'config':{'provider':provider,'output':str(output)}}]}
        patch.write_text(patch_text('catalog','读取模型目录',True,provider=provider,credentials_path=credential_path)+''.join('- '+json.dumps(row)+'\n' for row in account_rows(credential_path or credential_store(cfg)))+'- '+json.dumps(rows)+'\n',encoding='utf-8')
        env=inherit_system_proxy(dict(os.environ));env.update(ELECTRON_RUN_AS_NODE='1',DSH_HOME=tmp);env.pop('DEEPSEEK_API_KEY',None);env.update(authentication)
        client=ACP([str(exe),'--expose-internals',str(cli),'--profile','acp','--patch',str(patch)],tmp,env)
        session=None
        try:
            init=client.request('initialize',{'protocolVersion':1,'clientCapabilities':{},'clientInfo':{'name':'agent-message-hub','version':'0.1'}},timeout=30)
            if init.get('agentInfo',{}).get('name')!='deepseek-harness-acp':raise HubError('Harness ACP 身份核验失败')
            view=client.request('session/new',{'cwd':tmp,'mcpServers':[]},timeout=30);session=view.get('sessionId')
            deadline=time.monotonic()+35
            while not output.exists() and time.monotonic()<deadline:time.sleep(.05)
            if not output.exists():raise HubError('Harness 官方模型目录读取超时')
            catalog=json.loads(output.read_text(encoding='utf-8'))
            models=[{'id':m['id'],'name':m.get('name') or m['id'],'source':'official_llm','efforts':[]} for m in catalog.get('models',[]) if isinstance(m.get('id'),str) and m['id']]
            if catalog.get('error'):raise HubError(catalog['error'])
            if not models:raise HubError('Harness 未返回官方模型目录，不使用固定列表冒充读取结果')
            for model in models:
                value=json.dumps([provider,model['id']],separators=(',',':'))
                state=client.request('session/set_config_option',{'sessionId':session,'configId':'model','value':value},timeout=30)
                option=next((x for x in state.get('configOptions',[]) if x.get('id')=='reasoning_effort'),{})
                model['efforts']=[x['value'] for x in option.get('options',[]) if x.get('value') in ('off','low','high','max')] or ['off']
            return models
        finally:
            if session:
                try:client.request('session/close',{'sessionId':session},timeout=5)
                except HubError:pass
            client.close()
