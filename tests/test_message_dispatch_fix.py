import json,time
from unittest.mock import patch
from hub.projects import Projects
from hub.message_receipts import reconcile
import test_designs as base
class MessageDispatch(base.DesignFlow):
 def test_prepared_manager_task_stays_in_own_project_and_is_not_archived(self):
  s,d=self.start();w=self.ds.workflows.snapshot('user')[0];projects=Projects(self.h)
  task=self.w.prepare_manager(w,self.w.steps(w['id']),'Platform recovery notice')
  msg=self.h.db.execute('SELECT * FROM messages WHERE body LIKE ?',('[task:'+task+'] %',)).fetchone();self.assertEqual(msg['project_id'],'p')
  old={**w,'id':'old','project_id':'old-project','status':'completed','created':0};self.w.save(old)
  with self.h.tx():self.h.db.execute('UPDATE messages SET project_id=NULL WHERE id=?',(msg['id'],))
  projects.tag();reconcile(self.h);msg=self.h.db.execute('SELECT * FROM messages WHERE id=?',(msg['id'],)).fetchone();self.assertEqual(msg['project_id'],'p');self.assertEqual(msg['status'],'pending')
  self.d.submit('user','deepseek-4',self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone()[0],True,task)
 def test_manager_recovery_reuses_prepared_step(self):
  s,d=self.start();w=self.w.snapshot('user')[0]
  a=self.w.prepare_manager(w,self.w.steps(w['id']),'one');b=self.w.prepare_manager(w,self.w.steps(w['id']),'two');self.assertEqual(a,b)
 def test_member_message_reaches_attention_manager_after_sender_finishes(self):
  s,d=self.start();w=self.w.snapshot('user')[0];task=self.w.add_step(w,'deepseek-3','work','Checklist');self.w.advance(w)
  worker=self.d.submit('user','deepseek-3','Checklist',True,task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result='A concise ordinary report' WHERE id=?",(worker['id'],))
  w['status']='needs_attention';self.w.save(w)
  ids=self.co.send('deepseek-3','deepseek-4','Need a decision',project_id='p',request_key='question')
  wake=self.h.db.execute('SELECT * FROM wakeups WHERE message=?',(ids[0],)).fetchone();self.assertEqual(wake['status'],'batched');self.assertIsNotNone(self.h.db.execute('SELECT 1 FROM workflow_events WHERE id=?',('message:'+ids[0],)).fetchone())
 def test_manager_is_not_reported_as_worker_and_plain_worker_report_is_preserved(self):
  s,d=self.start();w=self.w.snapshot('user')[0];self.w.advance(w);run=dict(self.h.db.execute('SELECT * FROM executions ORDER BY created DESC LIMIT 1').fetchone());self.co.report(run,'completed','{"done":false,"report":"Assigned work","tasks":[]}');self.assertIsNone(self.h.db.execute('SELECT 1 FROM worker_reports WHERE run=?',(run['id'],)).fetchone())
  task=self.w.add_step(w,'deepseek-3','work','Work');job=self.d.submit('user','deepseek-3','Work',True,task);run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone());self.co.report(run,'completed','Checklist written; 39 pages verified.');self.assertIn('Checklist written',self.h.db.execute('SELECT summary FROM worker_reports WHERE run=?',(run['id'],)).fetchone()[0])

 def test_manager_mcp_assignment_plus_empty_tasks_is_accepted(self):
  s,d=self.start();w=self.w.snapshot('user')[0];self.w.advance(w)
  run=self.h.db.execute('SELECT id,task_id FROM executions ORDER BY created DESC LIMIT 1').fetchone()
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],))
  task=self.w.project_assign('deepseek-4',run['id'],'deepseek-1','Create skeleton','assigned-once')
  worker=self.w.steps(w['id'])[-1];job=self.d.submit('user','deepseek-1','Create skeleton',True,worker['task'])
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(json.dumps({'done':False,'report':'Assigned through MCP; waiting for skeleton','tasks':[]}),run['id']))
  self.w.advance(w)
  stored=json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(w['id'],)).fetchone()[0]);self.assertEqual(stored['phase'],'working');self.assertEqual(stored.get('format_retries',0),0)
