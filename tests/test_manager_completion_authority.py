import unittest,json,time
from unittest.mock import patch
from hub.core import HubError
import test_designs as base

class ManagerCompletionAuthority(unittest.TestCase):
 setUp=base.DesignFlow.setUp
 tearDown=base.DesignFlow.tearDown
 plan=base.DesignFlow.plan
 start=base.DesignFlow.start
 finish=base.DesignFlow.finish
 def test_only_running_member_blocks_then_manager_can_complete_despite_publish_warning(self):
  _,d=self.start()
  original=self.w.project_complete
  def submit(actor,run_id,summary,evidence):
   # Simulate a still-running member, stale check coverage and bad assets.
   w=next(w for w in self.w.snapshot('user') if w['id']==d['workflow_id'])
   self.member_task=self.w.dispatch(w,'deepseek-1','Read home.html only','late-check','check',read_paths=['home.html'])['task_id']
   title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(self.member_task,)).fetchone()[0]
   job=self.d.submit('user','deepseek-1',title,True,self.member_task)
   with self.h.tx():
    self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(job['id'],))
    self.h.db.execute("INSERT INTO workflow_events VALUES(?,?,?,?,'pending',NULL,?)",('late-event',d['workflow_id'],'test',json.dumps({'type':'test'}),time.time()))
   with patch.object(self.ds,'prepare_publish',side_effect=HubError('unpublishable demo')):
    return original(actor,run_id,summary,evidence)
  with patch.object(self.w,'project_complete',side_effect=submit):
   with self.assertRaisesRegex(HubError,'成员仍在执行'):self.finish(d)
  self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE task_id=?',(self.member_task,)).fetchone()[0],'running')
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='failed' WHERE task_id=?",(self.member_task,))
  manager=self.h.db.execute("SELECT e.id FROM executions e JOIN workflow_steps s ON s.task=e.task_id WHERE s.workflow=? AND s.kind='review' ORDER BY s.seq DESC LIMIT 1",(d['workflow_id'],)).fetchone()[0]
  with patch.object(self.ds,'prepare_publish',side_effect=HubError('unpublishable demo')):answer=original('deepseek-4',manager,'Manager confirms',['local evidence'])
  self.assertTrue(answer['completed']);self.assertFalse(answer['design_review_ready'])
  w=next(w for w in self.w.snapshot('user') if w['id']==d['workflow_id'])
  self.assertEqual(w['status'],'completed')
  self.assertIn('unpublishable demo',w['completion_warnings'])
  self.assertFalse(w['design_review_ready'])
  self.assertEqual(self.ds.get(d['id'])['state'],'publish_error')
  self.assertEqual(self.ds.get(d['id'])['publish_error'],'unpublishable demo')
  self.assertEqual(self.h.db.execute("SELECT status FROM executions WHERE task_id=?",(self.member_task,)).fetchone()[0],'failed')

  self.assertEqual(self.h.db.execute("SELECT status FROM workflow_events WHERE id='late-event'").fetchone()[0],'handled')
