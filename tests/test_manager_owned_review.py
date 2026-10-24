import unittest,time,json
from unittest.mock import patch
import test_designs as base
class ManagerOwnedReview(unittest.TestCase):
 def setUp(self):base.DesignFlow.setUp(self)
 def tearDown(self):base.DesignFlow.tearDown(self)
 def workflow(self,status='completed'):
  w={'id':'ownership','manager':'deepseek-4','project_id':'p','agents':['deepseek-1','deepseek-3'],'reviewer':'deepseek-3','status':'active','processed':0,'next_inspection':time.time()+180,'report':'test'}
  self.w.save(w)
  steps=[{'seq':1,'kind':'work','task':'t','agent':'deepseek-1','run_id':'r','status':status,'depends_on':None}]
  return w,steps
 def check_notice(self,status):
  w,steps=self.workflow(status)
  with patch.object(self.w,'valid'),patch.object(self.w,'steps',return_value=steps),patch.object(self.w,'ingest'),patch.object(self.w,'prepare_manager') as manager,patch.object(self.w,'pending_requires_wake',return_value=True),patch.object(self.w,'add_step',side_effect=AssertionError('platform must not dispatch reviewer')):
   self.w.advance(w);self.w.advance(w);self.assertTrue(manager.called)
  events=self.h.db.execute("SELECT body FROM workflow_events WHERE workflow='ownership'").fetchall();self.assertEqual(len(events),1);self.assertEqual(json.loads(events[0][0])['type'],'review_needed')
 def test_completed_work_notifies_manager_without_automatic_reviewer(self):self.check_notice('completed')
 def test_uncertain_work_also_goes_to_manager(self):self.check_notice('uncertain')
 def test_preset_reviewer_does_not_force_hidden_check_task(self):
  w,steps=self.workflow()
  with patch.object(self.w,'steps',return_value=steps):self.assertEqual(self.w.completion_check(w),steps)
 def test_manager_explicit_check_is_preserved(self):
  w,steps=self.workflow();w['manager_assigned_review']=True
  with patch.object(self.w,'steps',return_value=steps):
   self.assertEqual(self.w.completion_check(w),steps)
