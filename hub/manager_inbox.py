from .manager_identity import resolve as project_manager
"""User manager input queue and explicit, scoped preemption without stop locks."""
import json,time
from .core import HubError,text

class ManagerInbox:
 def __init__(self,hub,planning,workflows,coordination):
  self.hub=hub;self.planning=planning;self.workflows=workflows;self.coordination=coordination
  with hub.tx():
   hub.db.execute('CREATE TABLE IF NOT EXISTS manager_discussion_inputs(message_id TEXT PRIMARY KEY,session_id TEXT,run_id TEXT)')
   hub.db.execute('CREATE TABLE IF NOT EXISTS manager_preemptions(run_id TEXT PRIMARY KEY,project_id TEXT,created REAL)')
 def context(self,session_id,project_id=None):
  s=self.planning.get(session_id)
  if project_id and s.get('project_id')!=project_id:raise HubError('讨论不属于当前项目')
  manager=project_manager(self.hub,record=s)
  with self.hub.lock:row=self.hub.db.execute("SELECT body FROM workflows WHERE json_extract(body,'$.project_id')=? ORDER BY rowid DESC LIMIT 1",(s.get('project_id'),)).fetchone()
  w=json.loads(row[0]) if row else None
  if w and s['state'] in ('executing','designing'):manager=self.workflows.manager(w)
  return s,manager
 def send(self,actor,session_id,body,revision=None,request_key=None,project_id=None):
  self.hub.require(actor,{'user'});text(body,20000)
  with self.planning.lock,self.workflows.lock:
   s,manager=self.context(session_id,project_id)
   if s['state'] in ('executing','designing'):
    ids=self.coordination.send(actor,manager,body,mode='queue',request_key=request_key,project_id=s.get('project_id'))
    return {'message_ids':ids,'queued':True}
   if not s.get('pending') and body.strip()=='按计划执行':
    result=self.planning.message(actor,body,session_id=s['id'],revision=revision,project_id=s.get('project_id'))
    return {'message_ids':[],'queued':False,'session_id':result.get('id') if isinstance(result,dict) else s['id']}
   was_busy=bool(s.get('pending'))
   ids=self.hub.send(actor,manager,body,mode='queue',request_key=request_key)
   with self.hub.tx():
    for ident in ids:
     self.hub.db.execute('UPDATE messages SET project_id=? WHERE id=?',(s.get('project_id'),ident))
     self.hub.db.execute('INSERT OR IGNORE INTO manager_discussion_inputs VALUES(?,?,NULL)',(ident,s['id']))
   # The supervisor drains this durable inbox; HTTP receipt must not wait for model startup.
   return {'message_ids':ids,'queued':was_busy}
 def interrupt(self,actor,session_id,message_ids,project_id=None):
  self.hub.require(actor,{'user'})
  if not isinstance(message_ids,list) or not message_ids or any(not isinstance(x,str) for x in message_ids):raise HubError('没有可插入的排队消息')
  with self.planning.lock,self.workflows.lock:
   s,manager=self.context(session_id,project_id);eligible=[];runs=[]
   with self.hub.tx():
    for ident in set(message_ids):
     row=self.hub.db.execute('SELECT * FROM messages WHERE id=?',(ident,)).fetchone()
     if not row or row['sender']!='user' or row['recipient']!=manager or row['project_id']!=s.get('project_id'):raise HubError('只能插入当前项目中你发给当前经理的消息')
     if row['status']=='pending' and not row['body'].startswith('[task:'):eligible.append(ident)
    if not eligible:return {'interrupt_requested':False,'note':'消息已被经理领取，不重复插入'}
    for row in self.hub.db.execute("SELECT * FROM executions WHERE agent=? AND status IN ('queued','waiting_quota','running','interrupting')",(manager,)).fetchall():
     run=dict(row)
     if run['message_id'] in eligible:continue
     if self.workflows.runtime(manager).sessions.scope(run)=='hub-project:'+(s.get('project_id') or 'default'):
      runs.append(run);self.hub.db.execute('INSERT OR IGNORE INTO manager_preemptions VALUES(?,?,?)',(run['id'],s.get('project_id'),time.time()))
    for ident in eligible:self.hub.db.execute("UPDATE messages SET mode='immediate' WHERE id=?",(ident,))
    self.hub.audit(actor,'manager.input_prioritized',{'project':s.get('project_id'),'messages':eligible,'runs':[r['id'] for r in runs]})
   for run in runs:
    try:self.workflows.runtime(manager).stop('user',run['id'])
    except HubError:
     with self.hub.lock:state=self.hub.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()
     if state and state[0] in ('queued','waiting_quota','running','interrupting'):raise
   return {'interrupt_requested':bool(runs),'message_ids':eligible,'note':'等待当前轮次确认中断，再领取插入消息' if runs else '经理已空闲，消息优先领取'}
 def patrol(self):
  with self.planning.lock:
   with self.hub.lock:rows=self.hub.db.execute("SELECT q.*,m.body,m.status FROM manager_discussion_inputs q JOIN messages m ON m.id=q.message_id WHERE q.run_id IS NULL AND m.status='pending' ORDER BY CASE m.mode WHEN 'immediate' THEN 0 ELSE 1 END,m.created").fetchall()
   for row in rows:
    s=self.planning.get(row['session_id'])
    if s.get('pending'):continue
    # Approval is never replayed against an unseen newer revision.
    if row['body'].strip()=='按计划执行':
     with self.hub.tx():self.hub.db.execute("UPDATE messages SET status='failed',result='请审阅最新计划后明确批准；排队审批口令不自动重放' WHERE id=?",(row['message_id'],))
     continue
    try:result=self.planning.message('user',row['body'],session_id=s['id'],project_id=s.get('project_id'))
    except HubError as error:
     with self.hub.tx():self.hub.db.execute("UPDATE messages SET result=? WHERE id=? AND (result IS NULL OR result!=?)",('等待处理：'+str(error),row['message_id'],'等待处理：'+str(error)))
     continue
    if isinstance(result,dict) and result.get('pending'):
     with self.hub.tx():
      self.hub.db.execute('UPDATE manager_discussion_inputs SET run_id=? WHERE message_id=?',(result['pending'],row['message_id']))
      self.hub.db.execute("UPDATE messages SET status='acknowledged',acked=?,attempts=attempts+1 WHERE id=?",(time.time(),row['message_id']))
   with self.hub.tx():
    done=self.hub.db.execute("SELECT q.message_id,e.status,e.result FROM manager_discussion_inputs q JOIN executions e ON e.id=q.run_id JOIN messages m ON m.id=q.message_id WHERE m.status='acknowledged' AND e.status NOT IN ('queued','running','interrupting','waiting_quota')").fetchall()
    for row in done:self.hub.db.execute("UPDATE messages SET status=?,result=? WHERE id=? AND status='acknowledged'",('completed' if row['status']=='completed' else 'failed',row['result'],row['message_id']))
