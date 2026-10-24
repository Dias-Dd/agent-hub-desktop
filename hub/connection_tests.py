"""User-confirmed, one-turn connection tests using the existing budgeted runtimes."""
import threading,time,os,json
from concurrent.futures import ThreadPoolExecutor,wait
MAX_PARALLEL=8
from .core import HubError,uid
ACTIVE={'queued','running','waiting_quota','interrupting'}
PROMPT='接入测试：只回复“连接成功”。不要调用工具、读取或修改文件、执行命令、联系其他 Agent。'
def failure_kind(detail):
 text=detail.lower()
 from .model_availability import retired
 if retired(detail):return 'model_unavailable'
 if any(x in text for x in ('insufficient_quota','insufficient balance','quota exhausted','额度耗尽','余额不足')):return 'quota_exhausted'
 if any(x in text for x in ('rate limit','rate_limit','too many requests','http 429')):return 'rate_limited'
 if any(x in text for x in ('authentication required','unauthorized','http 401','status code 401','invalid api key')):return 'auth_required'
 if 'conflicts with --effort' in text or 'invalid model selection' in text:return 'configuration_error'
 if any(x in text for x in ('has no attribute','attributeerror','typeerror','nameerror')):return 'adapter_error'
 return None

class ConnectionTests:
 def __init__(self,registry):
  self.registry=registry;self.hub=registry.hub;self.lock=threading.RLock();self.stop=threading.Event();self.thread=None;self.threads=[];self.inflight=set();self.pool=ThreadPoolExecutor(max_workers=MAX_PARALLEL,thread_name_prefix="hub-connection-test")
  with self.hub.tx():
   self.hub.db.execute('CREATE TABLE IF NOT EXISTS integration_test_results(id TEXT PRIMARY KEY,body TEXT)')
   for item in registry.rows('integration_test_results'):
    if item['status'] in ('pending','testing'):
     if item.get('run_id'):
      self.hub.db.execute("UPDATE executions SET stop_requested=1,status=CASE WHEN status IN ('queued','waiting_quota') THEN 'cancelled' ELSE status END WHERE id=?",(item['run_id'],))
     if item.get('run_id'):
      self.hub.db.execute("UPDATE messages SET status='cancelled',lease=NULL WHERE id IN (SELECT message_id FROM executions WHERE id=? AND status='cancelled')",(item['run_id'],))
      self.hub.db.execute("UPDATE tasks SET status='blocked',note='接入测试重启中断，不自动重试' WHERE id IN (SELECT task_id FROM executions WHERE id=? AND status='cancelled')",(item['run_id'],))
     item.update(status='interrupted',detail='服务重启，测试未确认结束；不自动重试',finished=time.time());registry.put('integration_test_results',item)
 def snapshot(self):
  with self.hub.lock:
   results={}
   for x in self.registry.rows('integration_test_results'):
    if x.get('run_id') and '缺少官方模型/权限 init 验证' in x.get('detail',''):
     row=self.hub.db.execute("SELECT data FROM execution_events WHERE run_id=? AND kind='antigravity.final_payload' ORDER BY seq DESC LIMIT 1",(x['run_id'],)).fetchone()
     if row:
      error=json.loads(row[0]).get('error')
      if error:x={**x,'original_detail':x['detail'],'detail':self.redact(str(error))[:2000]}
    kind=failure_kind(x.get('detail','')) if x['status']=='failed' else None
    if kind:x={**x,'status':kind}
    c=self.registry.get('integration_connections',x['connection_id'])
    if c.get('transport') and x.get('transport')!=c['transport']:x={**x,'stale_configuration':True}
    results[x['id']]=x
   return results
 def save(self,item):
  with self.hub.tx():self.registry.put('integration_test_results',item)
 def start(self,actor,confirmed=False,agent_id=None):
  self.hub.require(actor,{'user'})
  if confirmed is not True:raise HubError('请确认真实接入测试将使用账号额度或 API 余额；每个 Agent 最多提交一轮，不自动重试')
  with self.lock:
   if self.stop.is_set():raise HubError('服务正在关闭，未启动测试')
   profiles=[a for a in self.registry.rows('agent_profiles') if a.get('enabled')]
   if agent_id is not None:
    if not isinstance(agent_id,str) or not any(a['id']==agent_id for a in profiles):raise HubError('请选择现有且启用的 Agent')
    profiles=[a for a in profiles if a['id']==agent_id]
   skipped=[a['id'] for a in profiles if a['id'] in self.inflight];profiles=[a for a in profiles if a['id'] not in self.inflight]
   if not profiles:return {'started':False,'status':'testing','detail':'所选 Agent 已在测试中，不重复提交','skipped':skipped}
   batch=uid();items=[]
   for a in profiles:
    item={'id':a['id'],'batch':batch,'name':a['name'],'connection_id':a['connection_id'],'transport':self.registry.get('integration_connections',a['connection_id']).get('transport'),'model':a['model'],'effort':a['effort'],'status':'pending','created':time.time(),'detail':'等待测试'};self.save(item);items.append(item);self.inflight.add(a['id'])
   with self.hub.tx():self.hub.audit(actor,'integration.test_batch_authorized',{'batch':batch,'count':len(items),'max_turns_per_agent':1})
   self.threads=[t for t in self.threads if t.is_alive()];self.thread=threading.Thread(target=self.loop,args=(items,),daemon=True);self.threads.append(self.thread);self.thread.start()
   return {'started':True,'count':len(items),'batch':batch,'parallel':MAX_PARALLEL,'skipped':skipped}
 def loop(self,items):
  futures=[]
  for item in items:
   try:futures.append(self.pool.submit(self.run_item,item))
   except RuntimeError:
    item.update(status='interrupted',detail='服务关闭，未开始测试',finished=time.time());self.save(item)
    with self.lock:self.inflight.discard(item['id'])
  wait(futures)
 def run_item(self,item):
  try:
   if self.stop.is_set():item.update(status='interrupted',detail='服务关闭，未开始测试',finished=time.time());self.save(item)
   else:self.test_one(item)
  finally:
   with self.lock:self.inflight.discard(item['id'])
 def test_one(self,item):
  rt=None;run_id=None;started=time.monotonic()
  try:
   # Hold the same lock used by runtime workers until isolation is written.
   with self.hub.lock:
    a=self.registry.get('agent_profiles',item['id'])
    if not a.get('enabled') or any(a.get(k)!=item.get(k) for k in ('connection_id','model','effort')):raise HubError('测试前配置已变化，请重新测试')
    if self.registry.busy([a['id']]):raise HubError('正在执行或已有排队任务，本轮跳过，不插队')
    rt=self.registry.server.workflows.runtime(a['id'])
    if not rt.config()['enabled']:raise HubError('接入未启用，未发送推理请求')
    cwd=self.hub.directory/'connection-tests'/item['batch']/a['id'];cwd.mkdir(parents=True,exist_ok=True)
    job=rt.submit('user',a['id'],PROMPT,True,purpose='question',session_scope='connection-test:'+item['batch'])
    run_id=job['id']
    with self.hub.tx():self.hub.db.execute("UPDATE executions SET cwd=?,max_seconds=? WHERE id=?",(str(cwd.resolve()),min(90,rt.config()['max_seconds']),run_id))
    item.update(status='testing',detail='正在等待真实回复',run_id=run_id,started=time.time());self.save(item)
   while not self.stop.wait(.2):
    with self.hub.lock:run=self.hub.db.execute('SELECT status,result,started FROM executions WHERE id=?',(run_id,)).fetchone()
    if not run:raise HubError('测试执行记录不存在')
    if run['status'] not in ACTIVE:
     reply=(run['result'] or '').strip();success=run['status']=='completed' and reply.strip('。.!！ \n\r\t\"“”')=='连接成功'
     item.update(status='passed' if success else 'failed',reply=self.redact(reply)[:2000],detail='真实回复验证通过' if success else ('已返回内容，但未匹配测试回复' if run['status']=='completed' else self.redact(reply)[:500] or '执行结束，未获得有效回复'),execution_status=run['status']);break
    if run['status']=='waiting_quota':
     rt.stop('user',run_id);item.update(status='quota_exhausted',detail='额度不足；本次测试不等待恢复或自动重试');break
    if time.monotonic()-started>100:
     rt.stop('user',run_id);item.update(status='timeout',detail='测试超时，已请求停止；可能已计费，不自动重试');break
   else:
    if run_id:rt.stop('user',run_id)
    item.update(status='interrupted',detail='服务关闭，已请求停止，不自动重试')
  except Exception as error:
   item.update(status='failed' if run_id else 'skipped',detail=self.redact(str(error))[:500])
  finally:
   if item.get('status') in ('failed','skipped'):
    kind=failure_kind(item.get('detail',''))
    if kind:item['status']=kind
   item.update(finished=time.time(),elapsed_ms=round((time.monotonic()-started)*1000));self.save(item)
 def redact(self,text):
  secrets=[v for k,v in os.environ.items() if any(w in k.upper() for w in ('API_KEY','TOKEN','SECRET','PASSWORD')) and len(v)>5]+list(getattr(self.hub,'tokens',{}).values())
  for value in secrets:
   if isinstance(value,str) and value:text=text.replace(value,'[已隐藏]')
  return text
 def close(self):
  self.stop.set()
  deadline=time.monotonic()+4
  for thread in list(self.threads):thread.join(timeout=max(0,deadline-time.monotonic()))
  self.pool.shutdown(wait=False)
