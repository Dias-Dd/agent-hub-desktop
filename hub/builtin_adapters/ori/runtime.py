import hashlib,json,os,re,queue,shutil,subprocess,sys,threading,time,urllib.request,urllib.error
from pathlib import Path
from hub.core import HubError
from hub.process_job import ProcessJob
from hub.proxy_env import inherit_system_proxy
from hub.deepseek_harness import ACP
from hub.integration_runtime import cli_failure,workbuddy_auth_failure,workbuddy_session_failure,bridge
def execute(self,run):
 from hub.integrations import locate,command
 run=dict(run);run['started']=time.time();client=None;session=None;submitted=False;parts=[];status='failed';result='';usage=None;live=False
 try:
  self.guard(run);c=self.connection();exe=locate(c['kind'],c.get('executable',''))
  if not exe:raise HubError('找不到已配置的官方 CLI')
  readonly=self.read_only(run);run['_read_only']=readonly
  if not readonly and run['permission']!='full':raise HubError('OpenCode/Ori 不提供与 Hub 等价的工作区沙箱；请显式授权完全访问，或改用支持工作区隔离的连接')
  allowed=[t['function']['name'] for t in self.definitions(run) if t['function']['name'] not in ('read_file','write_file','run_command')]
  mcp=bridge(self,run,allowed)
  model=run['model'];effort=self.efforts()[run['agent']]
  argv=[exe,'acp'] if c['kind']=='opencode' else [exe,'opencode','--model',model]+(['--reasoning-effort',effort] if effort!='default' else [])+['--','acp']
  if c['kind']=='ori' and not model.startswith('openrouter/'):model='openrouter/'+model
  old=self.sessions.get(run);target_cwd=str(Path(run['cwd']).resolve());session_cwd=old['cwd'] if old else target_cwd
  moved=os.path.normcase(str(Path(session_cwd).resolve()))!=os.path.normcase(target_cwd)
  def update(params):
   if not live:return  # session/load replays history; it is not this turn's output.
   value=params.get('update',{});kind=value.get('sessionUpdate')
   if kind=='agent_message_chunk':
    chunk=value.get('content',{}).get('text','');parts.append(chunk);self.public_reply(run,chunk,phase='正在生成回复')
   elif kind in ('tool_call','tool_call_update'):
    if kind=='tool_call':
     parts.clear();self.public_reply(run,'',replace=True,phase='正在使用工具：'+str(value.get('title') or '项目工具'))
    self.record(run['id'],'integration.tool',{k:value[k] for k in ('toolCallId','title','status') if k in value})
  env=inherit_system_proxy(dict(os.environ));env.update(self.run_environment(run))
  client=ACP(command(argv),session_cwd,env,update,not readonly);self.track_client(run,client)
  self_guard=lambda:self.guard(run)
  info=client.request('initialize',{'protocolVersion':1,'clientCapabilities':{},'clientInfo':{'name':'agent-message-hub','version':'0.3'}},self_guard)
  if info.get('protocolVersion')!=1:raise HubError('CLI 未返回支持的 ACP 版本')
  params={'cwd':session_cwd,'mcpServers':[mcp] if allowed else []}
  caps=info.get('agentCapabilities',{}).get('sessionCapabilities',{})
  if 'additionalDirectories' in caps:params['additionalDirectories']=[target_cwd] if moved else []
  if old:params['sessionId']=old['session_id']
  view=client.request('session/load' if old else 'session/new',params,self_guard);session=old['session_id'] if old else view.get('sessionId')
  mode_option=next((o for o in view.get('configOptions',[]) if o.get('category')=='mode' or o.get('id')=='mode'),None)
  if not session:raise HubError('未返回独立会话 ID')
  # Model selection is always acknowledged before inference; no silent fallback.
  view=client.request('session/set_config_option',{'sessionId':session,'configId':'model','value':model},self_guard)
  selected=next((o.get('currentValue') for o in view.get('configOptions',[]) if o.get('id')=='model'),None)
  if selected!=model:raise HubError('CLI 未确认所选模型；未启动推理')
  if effort!='default':
   changed=client.request('session/set_config_option',{'sessionId':session,'configId':'effort','value':effort},self_guard)
   if next((o.get('currentValue') for o in changed.get('configOptions',[]) if o.get('id')=='effort'),None)!=effort:raise HubError('CLI 未确认所选档位；未启动推理')
  mode='plan' if readonly else 'build'
  if mode_option:
   changed=client.request('session/set_config_option',{'sessionId':session,'configId':mode_option['id'],'value':mode},self_guard)
   selected_mode=next((o.get('currentValue') for o in changed.get('configOptions',[]) if o.get('id')==mode_option['id']),None)
   if selected_mode!=mode:raise HubError('CLI 未确认当前 '+mode+' 模式；未发送任务，原会话保留')
  else:client.request('session/set_mode',{'sessionId':session,'modeId':mode},self_guard)
  self.sessions.bind(run,session,cwd=session_cwd);self.sessions.state(run,'inflight')
  self.record(run['id'],'integration.session_ready',{'session':session,'resumed':bool(old),'session_cwd':session_cwd,'target_cwd':target_cwd,'directory_changed':moved,'mode':mode,'mode_verified':bool(mode_option)})
  prompt=self.execution_instructions(run)+self.report_instructions(run)+'\n'+run['prompt']
  if moved:
   from hub.module_sdk import workspace_notice
   prompt=workspace_notice(target_cwd,session_cwd)+prompt
  with self.hub.tx():self.hub.db.execute('UPDATE executions SET thread_id=?,actual_input=? WHERE id=?',(session,prompt,run['id']))
  parts.clear();live=True;submitted=True;answer=client.request('session/prompt',{'sessionId':session,'prompt':[{'type':'text','text':prompt}]},self_guard,run['max_seconds'])
  usage=answer.get('usage');status='completed' if answer.get('stopReason')=='end_turn' else 'interrupted';result=''.join(parts)
 except Exception as e:
  status='uncertain' if submitted else 'failed';result=str(e) if isinstance(e,HubError) else 'CLI 执行异常，保留会话和记录，不自动重试'
  if client and session:
   try:client.notify('session/cancel',{'sessionId':session})
   except Exception:pass
 finally:
  if client:client.close()
  self.clients.pop(run['id'],None);self.sessions.state(run,status);self.finalize(run,status,result,usage)
