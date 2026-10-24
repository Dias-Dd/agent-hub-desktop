import unittest,json,time
from unittest.mock import patch
import test_integrations as base
from hub.projects import Projects
from hub.planning import Planning
from hub.message_receipts import reconcile
class Receipts(unittest.TestCase):
 def setUp(self):
  base.RegistryTests.setUp(self);self.h=self.server.hub;Planning(self.h,self.server.deepseek,self.server.workflows);Projects(self.h);self.p=self.h.projects.create('user','receipts')['id']
 def tearDown(self):base.RegistryTests.tearDown(self)
 def message(self,recipient='deepseek-1'):
  ident=self.h.send('deepseek-4',recipient,'old message')[0]
  self.h.db.execute('UPDATE messages SET project_id=? WHERE id=?',(self.p,ident));return ident
 def status(self,ident):return self.h.db.execute('SELECT status FROM messages WHERE id=?',(ident,)).fetchone()[0]
 def workflow(self,status='completed',ident='old'):
  self.server.workflows.save({'id':ident,'project_id':self.p,'status':status})
 def test_user_reply_needs_no_claim(self):
  ident=self.message('user');self.assertEqual(self.status(ident),'user_delivered')
  self.h.db.execute("UPDATE messages SET status='pending' WHERE id=?",(ident,));reconcile(self.h);self.assertEqual(self.status(ident),'user_delivered')
 def test_terminal_queue_archived_without_execution_or_wake(self):
  self.workflow();ident=self.message()
  with patch.object(self.server.workflows,'wake',side_effect=AssertionError('must not wake')):
   result=reconcile(self.h);self.assertEqual(result['archived'],1);self.assertEqual(reconcile(self.h)['archived'],0)
  self.assertEqual(self.status(ident),'archived');self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],0)
 def test_new_active_workflow_keeps_messages(self):
  self.workflow();self.workflow('active','new');ident=self.message();reconcile(self.h);self.assertEqual(self.status(ident),'pending')
 def test_running_execution_keeps_messages(self):
  self.workflow();ident=self.message();self.h.db.execute("INSERT INTO tasks(id,agent,title,created,project_id) VALUES('task','deepseek-1','test',?,?)",(time.time(),self.p));self.h.db.execute("INSERT INTO executions(id,task_id,agent,status,created) VALUES('run','task','deepseek-1','running',?)",(time.time(),));reconcile(self.h);self.assertEqual(self.status(ident),'pending')
 def test_legacy_false_does_not_block_send(self):
  w={'id':'active','project_id':self.p,'status':'active','manager':'deepseek-4','agents':['deepseek-1'],'auto_wake':False,'expires':time.time()+60,'max_hops':4,'max_messages':100,'auto':True}
  ident=self.message();run={'task_id':'origin','id':'origin','purpose':'task'}
  with patch.object(self.server.workflows,'add_step',return_value='newtask') as add:
   self.server.coordination.route(ident,project=w,source_run=run);add.assert_called_once()

 def test_completed_workflow_does_not_wake_on_agent_message(self):
  w={'id':'done','project_id':self.p,'status':'completed','manager':'deepseek-4','agents':['deepseek-1'],'auto_wake':False,'expires':time.time()+60}
  ident=self.message();run={'task_id':'origin','id':'origin','purpose':'task'}
  with patch.object(self.server.workflows,'runtime',side_effect=AssertionError('must not launch')):
   self.server.coordination.route(ident,project=w,source_run=run)
  self.assertEqual(self.h.db.execute('SELECT status FROM wakeups WHERE message=?',(ident,)).fetchone()[0],'held')
