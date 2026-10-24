import unittest
from unittest.mock import patch
from hub.workflows import Workflows
from hub.core import HubError
class CompletionBlockers(unittest.TestCase):
 def test_older_queued_steps_remain_visible(self):
  steps=[{'task':str(i),'agent':'deepseek-1','kind':'work','run_id':'r'+str(i),'status':'completed'} for i in range(60)]
  steps[0]['status']='queued';steps[-1]['kind']='review';steps[-1]['status']='running'
  blockers=Workflows.completion_blocking_tasks(steps,'59')
  self.assertEqual([b['task'] for b in blockers],['0'])
  with patch.object(Workflows,'steps',return_value=steps):
   self.assertEqual(Workflows.completion_check(Workflows.__new__(Workflows),{'id':'w','manager':'deepseek-4'},'59'),steps)
 def test_ended_tasks_are_not_in_flight(self):
  steps=[{'task':s,'agent':'deepseek-1','kind':'work','run_id':'r','status':s} for s in ['completed','cancelled','interrupted','failed','uncertain']]
  self.assertEqual(Workflows.completion_blocking_tasks(steps),[])
 def test_unstarted_and_waiting_tasks_still_block(self):
  steps=[{'task':'a','agent':'deepseek-1','kind':'work','run_id':None,'status':None},{'task':'b','agent':'deepseek-2','kind':'work','run_id':'r','status':'waiting_quota'}]
  self.assertEqual(len(Workflows.completion_blocking_tasks(steps)),2)

 def test_only_other_actually_running_members_block(self):
  for status in ['running','interrupting']:
   steps=[{'task':'worker','agent':'worker','kind':'work','run_id':'r','status':status}]
   with patch.object(Workflows,'steps',return_value=steps):
    with self.assertRaisesRegex(HubError,'成员仍在执行'):Workflows.completion_check(Workflows.__new__(Workflows),{'id':'w','manager':'manager'})
 def test_manager_own_execution_and_nonrunning_states_are_allowed(self):
  steps=[{'task':'manager','agent':'manager','kind':'review','run_id':'m','status':'running'}]+[{'task':s,'agent':'worker','kind':'work','run_id':None if s is None else 'r'+s,'status':s} for s in [None,'queued','waiting_quota','completed','failed','cancelled','interrupted','uncertain']]
  with patch.object(Workflows,'steps',return_value=steps):self.assertEqual(Workflows.completion_check(Workflows.__new__(Workflows),{'id':'w','manager':'manager'}),steps)
