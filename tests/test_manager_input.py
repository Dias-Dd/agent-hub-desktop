import json,time,unittest
import test_designs as fixtures
from hub.projects import Projects
from hub.manager_inbox import ManagerInbox
from hub.core import HubError

class ManagerInput(unittest.TestCase):
 def setUp(self):
  self.f=fixtures.DesignFlow();self.f.setUp()
  for name in ('h','d','w','p','co'):setattr(self,name,getattr(self.f,name))
  Projects(self.h)
  with self.h.tx():self.h.db.execute('INSERT INTO hub_projects VALUES(?,?,?,?)',('p','Test project',self.f.t.name,time.time()))
  self.box=ManagerInbox(self.h,self.p,self.w,self.co)
 def tearDown(self):self.f.tearDown()
 def pending_discussion(self):
  s=self.f.plan('skip');return self.p.message('user','Continue discussing',session_id=s['id'],project_id='p')
 def test_busy_discussion_queue_persists_and_delivers_once(self):
  s=self.pending_discussion();first=s['pending']
  a=self.box.send('user',s['id'],'five words',request_key='same',project_id='p');b=self.box.send('user',s['id'],'five words',request_key='same',project_id='p')
  self.assertEqual(a,b);self.assertEqual(self.p.get(s['id'])['pending'],first)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(json.dumps({'done':False,'report':'answer','tasks':[]}),first))
  self.p.patrol();self.box=ManagerInbox(self.h,self.p,self.w,self.co);self.box.patrol();new=self.p.get(s['id'])
  self.assertNotEqual(new['pending'],first);prompt=self.h.db.execute('SELECT prompt FROM executions WHERE id=?',(new['pending'],)).fetchone()[0];self.assertEqual(prompt.count('five words'),1)
  count=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0];self.box.patrol();self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],count)
 def test_interrupt_discussion_inserts_pending_message_without_stop_lock(self):
  s=self.pending_discussion();old=s['pending'];a=self.box.send('user',s['id'],'important update',project_id='p')
  result=self.box.interrupt('user',s['id'],a['message_ids'],project_id='p');self.assertTrue(result['interrupt_requested'])
  self.assertEqual(self.h.db.execute('SELECT count(*) FROM agent_stops').fetchone()[0],0)
  self.p.patrol();self.box.patrol();updated=self.p.get(s['id']);self.assertNotEqual(updated['pending'],old);self.assertEqual(updated['state'],'thinking')
 def test_idle_discussion_retry_is_idempotent(self):
  s=self.f.plan('skip');a=self.box.send('user',s['id'],'new details',request_key='retry',project_id='p');count=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0]
  b=self.box.send('user',s['id'],'new details',request_key='retry',project_id='p');self.assertEqual(a['message_ids'],b['message_ids']);self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],count)
 def test_receipt_does_not_wait_for_dispatch(self):
  from unittest.mock import patch
  s=self.f.plan('skip')
  with patch.object(self.box,'patrol',side_effect=AssertionError('dispatch on HTTP thread')):
   result=self.box.send('user',s['id'],'durable fast receipt',project_id='p')
  ident=result['message_ids'][0]
  self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(ident,)).fetchone()[0],'pending')
  self.box.patrol()
  self.assertIsNotNone(self.p.get(s['id'])['pending'])
 def test_cross_project_and_other_sender_cannot_be_interrupted(self):
  s=self.pending_discussion();ids=self.box.send('user',s['id'],'update',project_id='p')['message_ids']
  with self.assertRaises(HubError):self.box.interrupt('user',s['id'],ids,project_id='other')
  with self.assertRaises(HubError):self.box.interrupt('deepseek-1',s['id'],ids,project_id='p')
 def test_queue_approval_is_never_replayed_against_new_revision(self):
  s=self.pending_discussion();ids=self.box.send('user',s['id'],'按计划执行',project_id='p')['message_ids']
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(json.dumps({'done':False,'report':'new plan','tasks':[{'agent':'deepseek-1','instruction':'work'}]}),s['pending']))
  self.p.patrol();self.box.patrol();self.assertEqual(self.w.snapshot('user'),[]);self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(ids[0],)).fetchone()[0],'failed')
 def test_workflow_preemption_is_not_failure_and_does_not_stop_worker(self):
  s=self.f.plan('skip');s=self.p.approve(s,s['revision'],None);w=self.w.snapshot('user')[0]
  worker=self.w.steps(w['id'])[0];instruction=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(worker['task'],)).fetchone()[0];job=self.d.submit('user',worker['agent'],instruction,True,worker['task'])
  task=self.w.prepare_manager(w,self.w.steps(w['id']));title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone()[0];manager=self.d.submit('user','deepseek-4',title,True,task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id in (?,?)",(time.time(),job['id'],manager['id']))
  ids=self.box.send('user',s['id'],'urgent user request',project_id='p')['message_ids'];self.box.interrupt('user',s['id'],ids,project_id='p')
  self.assertEqual(self.h.db.execute('SELECT stop_requested FROM executions WHERE id=?',(job['id'],)).fetchone()[0],0)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='interrupted',finished=?,result='cancel confirmed' WHERE id=?",(time.time(),manager['id']))
  self.w.advance(w);saved=next(x for x in self.w.snapshot('user') if x['id']==w['id']);self.assertEqual(saved['status'],'active');self.assertEqual(saved.get('manager_recoveries',0),0)
  next_task=self.w.steps(w['id'])[-1];body=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(next_task['task'],)).fetchone()[0];self.assertIn('urgent user request',body)

 def test_paused_project_interrupt_keeps_inserted_question_job(self):
  s=self.f.plan('skip');s=self.p.approve(s,s['revision'],None);w=self.w.snapshot('user')[0];w['status']='paused';self.w.save(w)
  old=self.d.submit('user','deepseek-4','old question',True,purpose='question',session_scope='hub-project:p')
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),old['id']))
  ids=self.box.send('user',s['id'],'new question',project_id='p')['message_ids'];self.box.interrupt('user',s['id'],ids,project_id='p')
  job=self.h.db.execute('SELECT status,stop_requested FROM executions WHERE message_id=?',(ids[0],)).fetchone();self.assertEqual(job['status'],'queued');self.assertEqual(job['stop_requested'],0)
  self.assertEqual(self.h.db.execute('SELECT stop_requested FROM executions WHERE id=?',(old['id'],)).fetchone()[0],1)
  self.assertEqual(next(x for x in self.w.snapshot('user') if x['id']==w['id'])['status'],'paused')
 def test_stop_lock_keeps_discussion_queue_without_crashing_patrol(self):
  s=self.pending_discussion();ids=self.box.send('user',s['id'],'keep my message',project_id='p')['message_ids']
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='cancelled' WHERE id=?",(s['pending'],))
  self.p.patrol()
  self.co.halt('user','deepseek-4','locked')
  self.box.patrol();self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(ids[0],)).fetchone()[0],'pending')
