import json,time,unittest,threading
from unittest.mock import patch
from hub.core import HubError
from hub.workflows import Workflows
import test_manager_force_stop_patrol as base

class QueueControl(unittest.TestCase):
 setUp=base.ManagerControls.setUp
 tearDown=base.ManagerControls.tearDown
 member=base.ManagerControls.member
 running=base.ManagerControls.running
 def queue(self,operation='list',**kwargs):
  with patch.object(self.w,'run_context',return_value=(self.project,{'task_id':'manager'})):
   return self.w.project_queue('deepseek-4','manager-run','deepseek-1',operation,**kwargs)
 def test_edit_updates_queued_inputs_but_preserves_active_turn(self):
  active=self.running(self.member('Active original'))
  task=self.member('Pending original');job=self.d.submit('user','deepseek-1','Pending original',True,task)
  self.queue('edit',item_id=task,instruction='New pending instruction')
  row=self.h.db.execute('SELECT prompt,actual_input,message_id FROM executions WHERE id=?',(job['id'],)).fetchone()
  self.assertEqual(row['prompt'],'New pending instruction');self.assertEqual(row['actual_input'],'New pending instruction')
  self.assertIn('New pending instruction',self.h.db.execute('SELECT body FROM messages WHERE id=?',(row['message_id'],)).fetchone()[0])
  with self.assertRaises(HubError):self.queue('edit',item_id=active['task_id'],instruction='Do not rewrite')
  self.assertEqual(self.h.db.execute('SELECT prompt FROM executions WHERE id=?',(active['id'],)).fetchone()[0],'Active original')
 def test_reorder_persists_and_changes_actual_runtime_selection(self):
  first=self.member('first');second=self.member('second')
  for task,title in [(first,'first'),(second,'second')]:self.d.submit('user','deepseek-1',title,True,task)
  answer=self.queue('reorder',item_ids=[second,first])
  self.assertEqual([x['id'] for x in answer['items']],[second,first])
  self.assertIsNone(self.h.db.execute('SELECT 1 FROM workflow_dependencies WHERE task=?',(second,)).fetchone())
  picked=[]
  def execute(run):picked.append(run['task_id']);self.d.stop_event.set()
  with patch.object(self.d,'execute',side_effect=execute):
   thread=threading.Thread(target=self.d.loop);thread.start();thread.join(3)
   self.d.stop_event.set();thread.join(3)
  self.assertEqual(picked,[second])
  self.assertTrue(self.h.db.execute('SELECT 1 FROM project_queue_positions WHERE item_id=?',(first,)).fetchone())
 def test_delete_cancels_and_releases_successor_without_erasing_history(self):
  first=self.member('first');second=self.member('second')
  self.queue('delete',item_id=first)
  self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE task_id=?',(first,)).fetchone()[0],'cancelled')
  self.assertIsNone(self.h.db.execute('SELECT 1 FROM workflow_dependencies WHERE task=?',(second,)).fetchone())
  self.assertIsNotNone(self.h.db.execute('SELECT 1 FROM tasks WHERE id=?',(first,)).fetchone())
  self.assertEqual([x['id'] for x in self.queue()['items']],[second])
 def test_interrupt_revokes_active_and_prioritizes_new_content(self):
  active=self.running(self.member('old work'));queued=self.member('normal queued')
  with patch.object(self.f.co,'context',return_value=(self.project,{'task_id':'manager'})):
   answer=self.queue('interrupt',instruction='Process this new content now',request_key='priority-one')
  self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(active['id'],)).fetchone()[0],'interrupted')
  self.assertTrue(self.h.db.execute('SELECT 1 FROM execution_revocations WHERE run=?',(active['id'],)).fetchone())
  listing=self.queue()['items'];self.assertEqual(listing[0]['message_id'],answer['message_ids'][0]);self.assertEqual(listing[0]['instruction'],'Process this new content now')
  self.assertIn(queued,[x['id'] for x in listing])
  self.w.advance(self.project)
  new=self.h.db.execute('SELECT prompt,status FROM executions WHERE message_id=?',(answer['message_ids'][0],)).fetchone()
  self.assertIsNotNone(new);self.assertEqual(new['prompt'],'Process this new content now');self.assertEqual(new['status'],'queued')
 def test_nonmanager_and_cross_member_changes_rejected(self):
  run=self.running(self.member('worker'))
  with self.assertRaises(HubError):self.w.project_queue('deepseek-1',run['id'],'deepseek-2')
  with patch.object(self.w,'run_context',return_value=(self.project,{'task_id':'manager'})):
   with self.assertRaises(HubError):self.w.project_queue('deepseek-4','manager-run','unknown-agent')
 def test_raw_pending_message_can_be_edited_deleted_and_ordered(self):
  mid=self.h.send('user','deepseek-1','pending user note')[0]
  with self.h.tx():self.h.db.execute('UPDATE messages SET project_id=? WHERE id=?',(self.project.get('project_id') or self.project['id'],mid))
  self.queue('edit',item_id=mid,instruction='revised pending note')
  self.queue('reorder',item_ids=[mid]);self.assertEqual(self.queue()['items'][0]['id'],mid)
  self.queue('delete',item_id=mid);self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(mid,)).fetchone()[0],'cancelled')

 def test_reordered_queue_survives_workflow_reinitialization(self):
  first=self.member('first');second=self.member('second')
  self.queue('reorder',item_ids=[second,first])
  reopened=Workflows(self.h,[self.f.c,self.f.a,self.d])
  self.assertIsNone(self.h.db.execute('SELECT 1 FROM workflow_resource_dependencies WHERE task=? AND depends_on=?',(second,first)).fetchone())
  from hub.queue_control import items
  self.assertEqual([x['id'] for x in items(reopened,self.project,'deepseek-1')],[second,first])
 def test_queue_tool_in_manager_api_definitions_and_hidden_from_worker(self):
  manager_task=self.w.steps(self.project['id'])[0]['task'];manager=self.running(manager_task)
  names={x['function']['name'] for x in self.d.definitions(manager)}
  self.assertIn('project_queue',names)
  worker=self.running(self.member('worker'))
  self.assertNotIn('project_queue',{x['function']['name'] for x in self.d.definitions(worker)})

 def test_prepared_queue_dispatches_reordered_item_first(self):
  first=self.member('first');second=self.member('second')
  self.queue('reorder',item_ids=[second,first])
  self.w.advance(self.project)
  self.assertIsNotNone(self.h.db.execute('SELECT 1 FROM executions WHERE task_id=?',(second,)).fetchone())
  self.assertIsNone(self.h.db.execute('SELECT 1 FROM executions WHERE task_id=?',(first,)).fetchone())
 def test_raw_poll_respects_persistent_message_order(self):
  first=self.h.send('user','deepseek-1','first raw')[0];second=self.h.send('user','deepseek-1','second raw')[0]
  with self.h.tx():
   for ident in (first,second):self.h.db.execute('UPDATE messages SET project_id=? WHERE id=?',(self.project.get('project_id') or self.project['id'],ident))
  self.queue('reorder',item_ids=[second,first]);self.h.heartbeat('deepseek-1','idle')
  self.assertEqual(self.h.poll('deepseek-1')['id'],second)
