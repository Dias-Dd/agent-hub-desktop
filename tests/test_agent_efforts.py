import json,unittest
from unittest.mock import patch
from test_nine_deepseek import NineDeepSeek
from hub.projects import Projects
from hub.core import HubError
class Efforts(unittest.TestCase):
 def setUp(self):
  NineDeepSeek.setUp(self);self.projects=Projects(self.h);self.project=self.projects.create('user','effort fixture')
 tearDown=NineDeepSeek.tearDown
 def workflow(self):return self.w.start('user','approved',['deepseek-1','deepseek-3'],confirmed=True,project_id=self.project['id'],approved_proposal={'done':False,'report':'ready','tasks':[{'agent':'deepseek-1','instruction':'work'}]})
 def test_defaults_and_idempotent_changes(self):
  self.assertEqual(set(self.d.efforts().values()),{'high'})
  self.d.set_effort('user','deepseek-1','low',self.project['id']);self.d.set_effort('user','deepseek-1','low',self.project['id'])
  self.assertEqual(self.h.db.execute('select count(*) from agent_effort_notices').fetchone()[0],1)
 def test_active_change_queues_one_manager_event(self):
  w=self.workflow();self.d.set_effort('user','deepseek-2','max',self.project['id'])
  e=json.loads(self.h.db.execute('select body from workflow_events where workflow=?',(w['id'],)).fetchone()[0]);self.assertEqual(e['type'],'effort_changed');self.assertNotIn('deepseek-1',e['body'])
 def test_inactive_changes_wait_for_next_wake_and_only_ack_after_completion(self):
  w=self.workflow();w['status']='paused';self.w.save(w)
  with patch.object(self.w,'enqueue') as enqueue:self.d.set_effort('user','deepseek-1','off',self.project['id']);enqueue.assert_not_called()
  run={'id':'next-manager-run','agent':'deepseek-4','session_scope':'hub-project:'+self.project['id']}
  notices=self.d.effort_notices(run);self.assertEqual(len(notices),1)
  self.assertEqual(self.d.effort_notices(run),notices)
  self.d.acknowledge_effort_notices(run,notices);self.assertEqual(self.d.effort_notices(run),[])
  self.assertEqual(self.w.snapshot('user')[0]['status'],'paused')
 def test_unselected_project_and_other_agent_cannot_consume_notice(self):
  self.d.set_effort('user','deepseek-1','low',self.project['id'])
  self.assertEqual(self.d.effort_notices({'agent':'deepseek-4','session_scope':'hub-project:other'}),[])
  self.assertEqual(self.d.effort_notices({'agent':'deepseek-1','session_scope':'hub-project:'+self.project['id']}),[])
 def test_only_user_can_set_official_efforts(self):
  with self.assertRaises(HubError):self.d.set_effort('deepseek-4','deepseek-1','low')
  with self.assertRaises(HubError):self.d.set_effort('user','deepseek-1','medium')
