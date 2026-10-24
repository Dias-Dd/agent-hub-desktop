"""One executing project, shared by user entry points and provider dispatch."""
import json
from .core import HubError

LIVE = ('queued', 'running', 'interrupting', 'waiting_quota')

def has(hub, table):
 return bool(hub.db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone())

def run_project(hub, run):
 scope=run.get('session_scope') or ''
 if scope.startswith('connection-test:'):return None
 for prefix in ('hub-project:', 'chat:'):
  if scope.startswith(prefix):return scope[len(prefix):]
 if has(hub,'workflow_steps'):
  row=hub.db.execute('SELECT w.body FROM workflows w JOIN workflow_steps s ON s.workflow=w.id WHERE s.task=?',(run['task_id'],)).fetchone()
  if row:return json.loads(row[0]).get('project_id')
 for table,ident in (('tasks',run.get('task_id')),('messages',run.get('message_id'))):
  if 'project_id' in {r[1] for r in hub.db.execute('PRAGMA table_info('+table+')')}:
   row=hub.db.execute('SELECT project_id FROM '+table+' WHERE id=?',(ident,)).fetchone()
   if row and row[0]:return row[0]
 return None

def runnable(hub,run):
 if has(hub,'workflow_steps'):
  row=hub.db.execute('SELECT w.body FROM workflows w JOIN workflow_steps s ON s.workflow=w.id WHERE s.task=?',(run['task_id'],)).fetchone()
  if row:return json.loads(row[0]).get('status') in ('active','needs_attention')
 return True

def busy(hub,project):
 with hub.lock:
  if has(hub,'executions'):
   for row in hub.db.execute("SELECT id,task_id,message_id,session_scope,status,started,created FROM executions WHERE status IN ('queued','running','interrupting','waiting_quota')"):
    if run_project(hub,dict(row))==project and (row['status'] in ('running','interrupting') or runnable(hub,dict(row))):return True
  if has(hub,'workflows'):
   for row in hub.db.execute("SELECT body FROM workflows WHERE json_extract(body,'$.project_id')=? AND json_extract(body,'$.status') IN ('active','needs_attention')",(project,)):
    w=json.loads(row[0])
    if w.get('project_id')==project and w.get('status') in ('active','needs_attention'):return True
 return False

def owner(hub):
 with hub.lock:
  if has(hub,'executions'):
   for row in hub.db.execute("SELECT id,task_id,message_id,session_scope,status,started,created FROM executions WHERE status IN ('running','interrupting') ORDER BY started,created,id"):
    project=run_project(hub,dict(row))
    if project:return project
  if has(hub,'workflows'):
   for row in hub.db.execute("SELECT body FROM workflows WHERE json_extract(body,'$.project_id') IS NOT NULL AND json_extract(body,'$.status') IN ('active','needs_attention') ORDER BY rowid LIMIT 1"):
    w=json.loads(row[0])
    if w.get('project_id') and w.get('status') in ('active','needs_attention'):return w['project_id']
  if has(hub,'executions'):
   for row in hub.db.execute("SELECT id,task_id,message_id,session_scope,status,started,created FROM executions WHERE status IN ('queued','waiting_quota') ORDER BY created,id"):
    if not runnable(hub,dict(row)):continue
    project=run_project(hub,dict(row))
    if project:return project
 return None

def require_available(hub,project):
 if not project:return
 if project in getattr(hub,'cleaning_projects',set()):raise HubError('此项目正在清理文件，请稍后再发送消息')
 other=owner(hub)
 if other and other!=project:
  name=other
  if has(hub,'hub_projects'):
   row=hub.db.execute('SELECT name FROM hub_projects WHERE id=?',(other,)).fetchone()
   if row:name=row[0]
  raise HubError('项目“'+name+'”正在执行；请先暂停或结束它，再启动其它项目')

def allows(hub,run):
 project=run_project(hub,run)
 return not project or owner(hub) in (None,project)
