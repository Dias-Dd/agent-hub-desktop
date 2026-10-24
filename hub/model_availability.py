"""Explicit provider model rejection; shared by identities using the same model.
A catalog refresh never silently enables a paid replacement or clears rejection.
"""
import json,re,time

def retired(detail):
 s=str(detail).lower()
 return 'model_not_found' in s or bool(re.search(r'(?:model|variant).{0,100}(?:retired|decommissioned|no longer available|has been removed)',s)) or '型号已下线' in s

def status(hub,provider,model):
 with hub.lock:
  exists=hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='unavailable_models'").fetchone()
  row=hub.db.execute('SELECT body FROM unavailable_models WHERE provider=? AND model=?',(provider,model)).fetchone() if exists else None
 return json.loads(row[0]) if row else None

def reject(hub,run,detail):
 hub.db.execute('CREATE TABLE IF NOT EXISTS unavailable_models(provider TEXT,model TEXT,body TEXT,PRIMARY KEY(provider,model))')
 hub.db.execute('CREATE TABLE IF NOT EXISTS model_reports(run TEXT PRIMARY KEY,body TEXT)')
 body={'reason':'model_unavailable','model':run['model'],'provider':run['provider'],'detail':str(detail)[:1800],'at':time.time()}
 hub.db.execute('INSERT OR REPLACE INTO unavailable_models VALUES(?,?,?)',(run['provider'],run['model'],json.dumps(body,ensure_ascii=False)))
 summary='提供商明确拒绝所选模型（已下线或不存在），本任务取消、未完成；请经理改派其它可用成员。不自动切换付费型号，不自动重试。'
 hub.db.execute('INSERT OR REPLACE INTO model_reports VALUES(?,?)',(run['id'],json.dumps({'summary':summary,'risk':'blocked','evidence':[str(detail)[:1800]]},ensure_ascii=False)))
 hub.audit('supervisor','execution.model_unavailable',{'run_id':run['id'],'agent':run['agent'],'model':run['model'],'provider':run['provider']})

def cancel_queued(hub,run,block):
 detail='所选模型已标记不可用，未启动推理。'+block['detail'];reject(hub,run,block['detail'])
 hub.db.execute("UPDATE executions SET status='cancelled',finished=?,result=? WHERE id=? AND status='queued'",(time.time(),detail,run['id']))
 hub.db.execute("UPDATE messages SET status='cancelled',lease=NULL,result=? WHERE id=?",(detail,run['message_id']))
 hub.db.execute("UPDATE tasks SET status='cancelled',note=? WHERE id=?",(detail,run['task_id']))


def restore(hub):
 # Restore explicit rejections for the currently selected models only; do not
 # rewrite old executions, send messages, or resurrect completed projects.
 with hub.tx():
  hub.db.execute('CREATE TABLE IF NOT EXISTS unavailable_models(provider TEXT,model TEXT,body TEXT,PRIMARY KEY(provider,model))')
  if not hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='agent_profiles'").fetchone():return
  for row in hub.db.execute('SELECT body FROM agent_profiles').fetchall():
   profile=json.loads(row[0]);provider='deepseek' if profile['connection_id']=='deepseek-default' else 'integration:'+profile['connection_id'];model=profile['model']
   latest=hub.db.execute("SELECT id,status,result,finished FROM executions WHERE provider=? AND model=? AND status NOT IN ('queued','running','interrupting','waiting_quota') ORDER BY created DESC LIMIT 1",(provider,model)).fetchone()
   if latest and latest['status']!='completed' and retired(latest['result']):
    body={'reason':'model_unavailable','model':model,'provider':provider,'detail':latest['result'][:1800],'at':latest['finished']}
    hub.db.execute('INSERT OR IGNORE INTO unavailable_models VALUES(?,?,?)',(provider,model,json.dumps(body,ensure_ascii=False)))
