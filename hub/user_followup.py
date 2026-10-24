"""Explicit human follow-ups are executable requests, independent of old workflows."""
import json
POLICY='本轮是用户直接发送的新请求。可以在现有目录、权限和费用授权内使用工具完成该请求；普通问题直接回答。沿用上下文，但不重放旧任务、不自动恢复旧计划。你若是当前经理，可用project_assign在本项目现有参与者和授权内为新请求派工；平台会单独跟踪这轮追加工作，成员汇报后继续调度并用project_complete结案，不创建额外模型进程。请求测试虚拟机时用project_vm实测，不能把旧错误当作当前结果。自然语言汇报实际结果和不足。'
def direct(hub,run):
 if run.get('purpose')!='task' or not (run.get('session_scope') or '').startswith(('project:','chat:')):return False
 with hub.lock:
  source=hub.db.execute('SELECT sender,body FROM messages WHERE id=?',(run.get('message_id'),)).fetchone()
  step=hub.db.execute('SELECT 1 FROM workflow_steps WHERE task=?',(run.get('task_id'),)).fetchone()
 return bool(source and source['sender']=='user' and not source['body'].startswith('[task:') and not step)
def context(hub,run):
 scope=run.get('session_scope') or ''
 if scope.startswith('project:'):
  with hub.lock:row=hub.db.execute('SELECT body FROM workflows WHERE id=?',(scope[8:],)).fetchone()
  if row:return json.loads(row[0])
 return {'id':scope.removeprefix('chat:'),'project_id':scope.removeprefix('chat:')}

def manager(hub,run):
 from .manager_identity import resolve
 w=context(hub,run)
 return direct(hub,run) and bool(w.get('grants')) and resolve(hub,w.get('project_id'))==run['agent']

def dispatch(workflows,actor,run_id,agent,instruction,key,kind,write_paths,read_paths):
 from .core import HubError,uid,text
 import time
 hub=workflows.hub
 with hub.lock:row=hub.db.execute('SELECT * FROM executions WHERE id=?',(run_id,)).fetchone()
 run=dict(row) if row else {}
 if not row or run['agent']!=actor or run['status']!='running' or not manager(hub,run):return None
 rt=workflows.runtime(actor);rt.check_latch(run)
 if hasattr(rt,'guard'):rt.guard(run)
 old=context(hub,run)
 workflows.valid({**old,'status':'active'})
 if run['grant_id']!=old['grants'].get(run['provider']):raise HubError('执行授权已变化')
 if agent not in old['agents'] or agent==actor:raise HubError('未授权的执行者：'+str(agent))
 text(instruction,6000);text(key,200)
 if kind not in ('work','check'):raise HubError('分工种类无效')
 with hub.lock:source=hub.db.execute('SELECT body FROM messages WHERE id=?',(run['message_id'],)).fetchone()[0]
 # Copy configuration only, never historical completion/events/tasks or demo publication state.
 keep=('project_id','agents','grants','cwd','expires','max_parallel','max_calls','unlimited_calls','auto_wake','reviewer','delegate_stop','max_hops','max_messages','inspection_policy','roles','design_baseline')
 w={k:old[k] for k in keep if k in old}
 w.update(id=uid(),manager=actor,parent_workflow=old['id'],followup_run=run_id,requirement=source,created=time.time(),status='active',phase='working',processed=1,patrolled=None,report='经理正在安排用户追加请求',next_inspection=time.time()+180)
 with hub.tx():
  hub.db.execute('INSERT INTO workflows VALUES(?,?)',(w['id'],json.dumps(w,ensure_ascii=False)))
  hub.db.execute('INSERT INTO workflow_steps VALUES(?,?,?,?,?)',(w['id'],1,run['task_id'],actor,'review'))
 try:
  result=workflows.dispatch(w,agent,instruction,key,kind,write_paths,read_paths)
 except Exception:
  with hub.tx():
   if not hub.db.execute('SELECT 1 FROM workflow_steps WHERE workflow=? AND seq>1',(w['id'],)).fetchone():
    hub.db.execute('DELETE FROM workflow_steps WHERE workflow=?',(w['id'],))
    hub.db.execute('DELETE FROM workflows WHERE id=?',(w['id'],))
  raise
 with hub.tx():
  hub.audit(actor,'project.followup_started',{'workflow':w['id'],'parent':old['id'],'message':run['message_id']})
 return result
