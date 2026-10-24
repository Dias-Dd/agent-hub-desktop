"""Manager-owned durable pending queue edits, without rewriting active/history turns."""
import json,time
from .core import HubError,text


def items(workflows,w,agent):
 h=workflows.hub;result=[];linked=set()
 for step in workflows.steps(w['id']):
  if step['agent']!=agent or (step['run_id'] and step['status'] not in ('queued','waiting_quota','running','interrupting')):continue
  task=h.db.execute('SELECT title,created FROM tasks WHERE id=?',(step['task'],)).fetchone()
  message=h.db.execute('SELECT m.* FROM messages m WHERE m.id=(SELECT message_id FROM executions WHERE task_id=?) OR m.id=(SELECT message FROM wakeups WHERE task=?) OR (m.recipient=? AND m.body LIKE ?) ORDER BY created LIMIT 1',(step['task'],step['task'],agent,'[task:'+step['task']+'] %')).fetchone()
  if message:linked.add(message['id'])
  rank=h.db.execute('SELECT position FROM project_queue_positions WHERE item_id=?',(step['task'],)).fetchone()
  result.append({'id':step['task'],'task_id':step['task'],'message_id':message['id'] if message else None,'run_id':step['run_id'],'status':step['status'] or 'prepared','kind':step['kind'],'instruction':task['title'],'created':task['created'],'position':rank[0] if rank else task['created'],'mode':message['mode'] if message else 'queue','editable':step['status'] not in ('running','interrupting')})
 for message in h.db.execute("SELECT * FROM messages WHERE project_id=? AND recipient=? AND status='pending' AND body NOT LIKE '[task:%' AND NOT EXISTS(SELECT 1 FROM executions e WHERE e.message_id=messages.id) ORDER BY created",(w.get('project_id') or w['id'],agent)).fetchall():
  if message['id'] in linked:continue
  rank=h.db.execute('SELECT position FROM project_queue_positions WHERE item_id=?',(message['id'],)).fetchone()
  result.append({'id':message['id'],'task_id':None,'message_id':message['id'],'run_id':None,'status':'pending','kind':'message','instruction':message['body'],'created':message['created'],'position':rank[0] if rank else message['created'],'mode':message['mode'],'editable':True})
 return sorted(result,key=lambda x:(x['mode']!='immediate',x['position'],x['created'],x['id']))


def operate(workflows,actor,run_id,agent,operation='list',item_id=None,instruction=None,item_ids=None,request_key=None,reason='经理调整待执行队列'):
 h=workflows.hub
 with workflows.lock,h.lock:
  w,_=workflows.run_context(actor,run_id,True)
  if agent not in w['agents'] or agent==workflows.manager(w):raise HubError('仅能管理当前项目已授权成员的队列')
  current=items(workflows,w,agent)
  if operation=='list':return {'agent':agent,'items':current,'note':'可编辑待执行项；执行中的轮次用interrupt直接打断并优先处理新内容。'}
  if operation=='interrupt':
   text(instruction,20000);text(request_key,128)
   interrupted=[x['run_id'] for x in current if x['status'] in ('running','interrupting')]
   ids=h.coordination.send(actor,agent,instruction,'immediate',request_key,w.get('project_id') or w['id'])
   return {'agent':agent,'message_ids':ids,'priority':'immediate','interrupted':bool(interrupted),'interrupted_runs':interrupted,'note':'原轮次已中断，新内容优先处理；原轮次不算成功，其它队列项保留。'}
  if operation=='reorder':
   pending=[x for x in current if x['editable']];by_id={x['id']:x for x in pending}
   if not isinstance(item_ids,list) or not item_ids or len(set(item_ids))!=len(item_ids) or any(i not in by_id for i in item_ids):raise HubError('请提供此成员待执行队列中的有效且不重复的 item_ids')
   ordered=[by_id[i] for i in item_ids]+[x for x in pending if x['id'] not in item_ids]
   tasks=[x['task_id'] for x in ordered if x['task_id']]
   with h.tx():
    for index,item in enumerate(ordered):
     for ident in (item['task_id'],item['message_id']):
      if ident:h.db.execute('INSERT OR REPLACE INTO project_queue_positions VALUES(?,?)',(ident,index))
     if item['message_id']:h.db.execute("UPDATE messages SET mode='queue' WHERE id=?",(item['message_id'],))
    # Drop only automatic serial/file ordering between this agent's pending jobs.
    # External prerequisites remain visible and respected; one active turn per agent remains.
    for task in tasks:
     for previous in tasks:
      h.db.execute('DELETE FROM workflow_dependencies WHERE task=? AND depends_on=?',(task,previous))
      h.db.execute('DELETE FROM workflow_resource_dependencies WHERE task=? AND depends_on=?',(task,previous))
    h.audit(actor,'project.queue_reordered',{'workflow':w['id'],'agent':agent,'items':[x['id'] for x in ordered]})
   return {'reordered':True,'items':items(workflows,w,agent),'note':'已持久化顺序；跨成员前置依赖仍有效。'}
  item=next((x for x in current if x['id']==item_id),None)
  if not item:raise HubError('此项不在当前成员队列中，请重新读取队列')
  if not item['editable']:raise HubError('此轮已执行，使用interrupt发送新内容；不修改执行中的输入')
  if operation=='delete':
   if item['task_id']:answer=workflows._cancel_task(w,item['task_id'],actor,reason)
   else:
    with h.tx():
     h.db.execute("UPDATE messages SET status='cancelled',result=?,lease=NULL WHERE id=? AND status='pending'",(reason,item['message_id']))
     h.db.execute("UPDATE wakeups SET status='cancelled',note=? WHERE message=?",(reason,item['message_id']))
    answer={'cancelled':True,'message_id':item['message_id']}
   # A removed serial queue entry is not a failed prerequisite that blocks all successors.
   if item['task_id']:
    with h.tx():
     h.db.execute('DELETE FROM workflow_dependencies WHERE depends_on=?',(item['task_id'],))
     h.db.execute('DELETE FROM workflow_resource_dependencies WHERE depends_on=?',(item['task_id'],))
  elif operation=='edit':
   text(instruction,6000)
   if item['kind']=='check' and not instruction.startswith('只读检查'):instruction='只读检查，不得修改文件或重放历史执行。'+instruction
   with h.tx():
    if item['task_id']:
     h.db.execute('UPDATE tasks SET title=? WHERE id=?',(instruction,item['task_id']))
     h.db.execute("UPDATE executions SET prompt=?,actual_input=? WHERE task_id=? AND status IN ('queued','waiting_quota')",(instruction,instruction,item['task_id']))
    if item['message_id']:
     old=h.db.execute('SELECT body FROM messages WHERE id=?',(item['message_id'],)).fetchone()[0]
     body=('[task:'+item['task_id']+'] ' if item['task_id'] and old.startswith('[task:') else '')+instruction
     h.db.execute('UPDATE messages SET body=? WHERE id=?',(body,item['message_id']))
    # A manager may change prose, but declared file scope stays intact. Reassign
    # separately if the new task needs a different worktree or file ownership.
   answer={'updated':True,'item_id':item['id'],'instruction':instruction,'note':'待执行输入已同步更新，原会话和已声明文件范围保留。'}
  else:raise HubError('未知队列操作')
  with h.tx():h.audit(actor,'project.queue_'+operation,{'workflow':w['id'],'agent':agent,'item_id':item['id'],'before':item['instruction'],'after':instruction if operation=='edit' else None,'reason':reason})
  return answer
