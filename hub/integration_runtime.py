"""Adapters built on public App Server, ACP and documented print-mode CLIs."""
import hashlib,json,os,re,queue,shutil,subprocess,sys,threading,time,urllib.request,urllib.error
from pathlib import Path
from .core import HubError
from .deepseek_runtime import DeepSeekRuntime
from .codex_runtime import CodexRuntime
from .antigravity import AntigravityRuntime
from .deepseek_harness import ACP
from .process_job import ProcessJob
from .proxy_env import inherit_system_proxy

from importlib import import_module
_module_helpers=import_module('hub.builtin_adapters._shared.cli_api')
CompatibleAPI=_module_helpers.CompatibleAPI
cli_failure=_module_helpers.cli_failure
workbuddy_auth_failure=_module_helpers.workbuddy_auth_failure
workbuddy_session_failure=_module_helpers.workbuddy_session_failure
bridge=_module_helpers.bridge

class LinkedRuntime(DeepSeekRuntime):
 def __init__(self,registry,connection):
  self.registry=registry;self.connection_id=connection['id'];self.models={}
  self.provider='integration:'+self.connection_id;self.config_key='integration_runtime_'+self.connection_id
  super().__init__(registry.hub,CompatibleAPI(connection))
 def connection(self):return self.registry.get('integration_connections',self.connection_id)
 @property
 def title(self):return self.connection()['name']
 def config(self):
  cfg=CodexRuntime.config(self);cfg={**cfg,'unlimited':cfg.get('max_runs',0)==0,'input_rate':0,'output_rate':0};cfg['engine']='harness' if self.connection()['kind']=='deepseek-harness' else 'api'
  cfg['enabled']=bool(cfg.get('enabled') and self.connection().get('enabled'))
  return cfg
 def submit(self,*args,**kwargs):
  with self.hub.lock:
   cfg=self.config();limit=cfg.get('max_runs',0)
   used=self.hub.db.execute("SELECT count(*) FROM executions WHERE grant_id=? AND status!='cancelled'",(cfg['grant_id'],)).fetchone()[0]
   if limit and used>=limit:raise HubError('此连接的本地调用上限已用完，请在接入页调整')
   return super().submit(*args,**kwargs)
 def saved_validation(self):return {'supported':bool(self.connection().get('probed_at'))}
 def efforts(self):return {a:self.registry.effort(a) for a in self.models}
 def effort_summary(self):return '当前成员接入与档位：'+json.dumps(self.registry.capabilities(),ensure_ascii=False)
 def execute(self,run):
  stop=threading.Event()
  def renew():
   while not stop.wait(3):
    try:self.check_latch(run);self.hub.heartbeat(run['agent'],'busy')
    except Exception:return
  thread=threading.Thread(target=renew,daemon=True);thread.start()
  try:return self.execute_connected(run)
  finally:stop.set();thread.join(timeout=5)
 def execute_connected(self,run):
  kind=self.connection()['kind']
  if kind=='custom-harness':
   from .custom_harness import execute
   return execute(self,run)
  from .harness_adapters import execute_builtin
  return execute_builtin(self,run,kind)
 def reserve(self,run,payload):
  from .core import uid
  if len(json.dumps(payload,ensure_ascii=False).encode())>180000:raise HubError('上下文达到本地上限，保留会话，不自动丢弃历史')
  ident=uid()
  with self.hub.tx():
   limit=self.config().get('max_runs',0);used=self.hub.db.execute('SELECT count(*) FROM deepseek_spend WHERE grant_id=?',(run['grant_id'],)).fetchone()[0]
   if limit and used>=limit:raise HubError('此连接的 API 请求上限已用完，不发送新请求')
   self.hub.db.execute('INSERT INTO deepseek_spend VALUES(?,?,?,?,?,?,?)',(ident,run['grant_id'],run['id'],None,'reserved',None,time.time()))
  return ident
 def finalize(self,run,status,result,usage=None):
  status=self.quota_outcome(run,status,result)
  with self.hub.tx():
   if self.force_stopped(run):return
   self.hub.db.execute('UPDATE executions SET status=?,finished=?,result=?,usage=? WHERE id=?',(status,time.time(),result,json.dumps(usage),run['id']))
   self.hub.db.execute('UPDATE messages SET status=?,result=?,lease=NULL WHERE id=?',(status,result,run['message_id']))
   self.hub.db.execute("UPDATE agents SET status='idle',active=NULL,heartbeat=? WHERE id=? AND active=?",(time.time(),run['agent'],run['message_id']))
   self.hub.db.execute('UPDATE tasks SET status=?,progress=?,note=? WHERE id=?',('done' if status=='completed' else 'cancelled' if status=='cancelled' else 'blocked',100 if status=='completed' else 0,result,run['task_id']))
   self.hub.audit(run['agent'],'integration.'+status,{'run':run['id'],'connection':self.connection_id})
  self.deliver_result(run,status,result)
 def read_only(self,run):
  with self.hub.lock:s=self.hub.db.execute('SELECT kind FROM workflow_steps WHERE task=?',(run['task_id'],)).fetchone()
  return run.get('purpose') in ('discussion','question') or bool(s and s[0]=='check')


def make_runtime(registry,connection):
 kind=connection['kind']
 if kind in ('codex','antigravity'):
  base=CodexRuntime if kind=='codex' else AntigravityRuntime
  cls=type('Connected'+base.__name__,(base,),{'provider':'integration:'+connection['id'],'config_key':'integration_runtime_'+connection['id'],'models':{},'title':connection['name'],'configure':DeepSeekRuntime.configure})
  runtime=cls(registry.hub)
  runtime.effort=lambda agent:registry.effort(agent)
  from .integrations import locate
  runtime.connection_executable=lambda:locate(kind,registry.get('integration_connections',connection['id']).get('executable',''))
  if kind=='antigravity':
   from .antigravity import AntigravityProbe
   runtime.probe=AntigravityProbe(runtime.connection_executable)
  return runtime
 return LinkedRuntime(registry,connection)
