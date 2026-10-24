import hashlib,json,os,re,queue,shutil,subprocess,sys,threading,time,urllib.request,urllib.error
from pathlib import Path
from hub.core import HubError
from hub.process_job import ProcessJob
from hub.proxy_env import inherit_system_proxy
from hub.deepseek_harness import ACP
from hub.integration_runtime import cli_failure,workbuddy_auth_failure,workbuddy_session_failure,bridge
def execute(self,run):
 from hub.integrations import locate,command
 run=dict(run);run['started']=time.time();proc=None;job=None;submitted=False;status='failed';result='';lines=queue.Queue();session=None;diagnostics=[];drainer=None;stage='准备执行器'
 try:
  self.guard(run);c=self.connection();exe=locate(c['kind'],c.get('executable',''))
  if not exe:raise HubError('尚未安装或未找到所选 CLI；未调用模型')
  readonly=self.read_only(run);run['_read_only']=readonly
  if not readonly and run['permission']!='full':raise HubError('此 CLI 尚未验证工作区沙箱；需要用户显式授权完全访问')
  allowed=[t['function']['name'] for t in self.definitions(run) if t['function']['name'] not in ('read_file','write_file','run_command')] if run.get('purpose') not in ('discussion','question') else []
  stage='配置消息工具'
  mcp=bridge(self,run,allowed);mcp_cfg={'mcpServers':{'agent-message-hub':{'command':mcp['command'],'args':mcp['args'],'env':{v['name']:v['value'] for v in mcp['env']}}}}
  home=self.hub.directory/'integrations'/run['id'];home.mkdir(parents=True,exist_ok=True)
  # This temporary bridge contains the run token, never account/API credentials.
  mcp_path=home/'mcp.json';mcp_path.write_text(json.dumps(mcp_cfg),encoding='utf-8')
  stage='构建启动参数'
  argv=[exe,'-p','--output-format','stream-json','--verbose','--model',run['model'],'--permission-mode','plan' if readonly else 'bypassPermissions','--append-system-prompt',self.execution_instructions(run)+self.report_instructions(run)]
  argv+=['--disallowedTools','Agent,Task']
  if c['kind']=='workbuddy':argv+=['--input-format','stream-json','--replay-user-messages']
  if c['kind']=='workbuddy' and not readonly:argv+=['-y']
  if c['kind']=='workbuddy' and readonly and 'report_result' in allowed:
   argv+=['--allowedTools','DeferExecuteTool,mcp__agent-message-hub__report_result']
   argv+=['--strict-mcp-config']
  if allowed:argv+=['--mcp-config',str(mcp_path)]
  effort=self.efforts()[run['agent']]
  if effort!='default':argv+=['--effort',effort]
  old=self.sessions.get(run)
  target_cwd=str(Path(run['cwd']).resolve())
  session_cwd=str(Path(old['cwd']).resolve()) if old and c['kind']=='workbuddy' else target_cwd
  moved=Path(session_cwd)!=Path(target_cwd)
  if old:argv+=['--resume',old['session_id']]
  if moved:argv+=['--add-dir',target_cwd]
  prompt=run['prompt']
  if moved:
   from hub.module_sdk import workspace_notice
   prompt=workspace_notice(target_cwd,session_cwd)+prompt
  with self.hub.tx():self.hub.db.execute('UPDATE executions SET actual_input=? WHERE id=?',(prompt,run['id']))
  env=inherit_system_proxy(dict(os.environ))
  if c['kind']=='workbuddy':
   from hub.workbuddy_catalog import environment as workbuddy_environment
   env=workbuddy_environment()
  env.update(self.run_environment(run))
  stage='启动 CLI 进程'
  proc=subprocess.Popen(command(argv),cwd=session_cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));job=ProcessJob(proc);self.track_client(run,type('Command',(),{'proc':proc,'job':job})())
  stage='读取 CLI 输出'
  def drain_errors():
   for line in proc.stderr:
    diagnostics.append(line[-1200:]);del diagnostics[:-20]
  drainer=threading.Thread(target=drain_errors,daemon=True);drainer.start()
  def reader():
   for line in proc.stdout:lines.put(line)
   lines.put(None)
  from hub.print_turn import PrintTurn,completed_result
  turn=PrintTurn(prompt,run['id'],run['started'])
  threading.Thread(target=reader,daemon=True).start();proc.stdin.write(turn.payload() if c['kind']=='workbuddy' else prompt);proc.stdin.flush();proc.stdin.close();submitted=True
  self.record(run['id'],'integration.session_launch',{'session':old['session_id'] if old else None,'resumed':bool(old),'session_cwd':session_cwd,'target_cwd':target_cwd,'directory_changed':moved})
  final=None
  while True:
   self.guard(run)
   try:line=lines.get(timeout=.25)
   except queue.Empty:continue
   if line is None:break
   try:value=json.loads(line)
   except ValueError:
    diagnostics.append(line[-1200:]);del diagnostics[:-20];continue
   if not isinstance(value,dict):continue
   if value.get('session_id'):
    session=value['session_id'];self.sessions.bind(run,session,cwd=session_cwd)
   if value.get('type')=='result':final=value
   elif c['kind']=='workbuddy':
    text=turn.receive(value)
    if text:self.record(run['id'],'integration.output',{'text':text[:4000],'message_id':value.get('uuid'),'current_turn':True})
   elif value.get('type')=='assistant':
    message=value.get('message') or {}
    blocks=message.get('content') or [] if isinstance(message,dict) else []
    self.record(run['id'],'integration.output',{'text':'\n'.join(str(block.get('text') or '') for block in blocks if isinstance(block,dict) and block.get('type')=='text')[:4000]})
  exit_code=proc.wait(timeout=5)
  if drainer:drainer.join(timeout=1)
  if exit_code!=0 or not final or final.get('is_error'):
   if c['kind']=='workbuddy' and not final:
    auth=workbuddy_auth_failure(proc.pid,run['started'])
    if auth:diagnostics.append(auth)
    missing=workbuddy_session_failure(old['session_id'] if old else None,run['started'])
    if missing:diagnostics.append(missing)
   detail=cli_failure(final,exit_code,diagnostics,env);self.record(run['id'],'integration.failure',{'error':detail,'exit_code':exit_code});raise HubError(detail)
  with self.hub.lock:own=self.hub.db.execute('SELECT body FROM model_reports WHERE run=?',(run['id'],)).fetchone()
  status,result=completed_result(final,own[0] if own else None)
  self.record(run['id'],'integration.turn_end',{'status':status,'input_acknowledged':turn.accepted,'historical_messages_skipped':turn.replayed,'has_result':bool(final.get('result'))})
 except Exception as e:
  status='uncertain' if submitted else 'failed'
  result=str(e) if isinstance(e,HubError) else cli_failure(None,None,[stage+'：'+type(e).__name__+': '+str(e)],locals().get('env',{}))
  self.record(run['id'],'integration.failure',{'stage':stage,'error':result,'exception':type(e).__name__})
 finally:
  if job:job.close()
  if proc and proc.poll() is None:proc.kill();proc.wait(timeout=5)
  if drainer:drainer.join(timeout=1)
  if proc and proc.stderr:proc.stderr.close()
  if 'mcp_path' in locals():mcp_path.unlink(missing_ok=True)
  self.clients.pop(run['id'],None);self.sessions.state(run,status);self.finalize(run,status,result)
