import unittest
import test_designs as base
from hub.manager_identity import independent_reviewer
class ReviewerDefaults(unittest.TestCase):
 def setUp(self):self.f=base.DesignFlow();self.f.setUp()
 def tearDown(self):self.f.tearDown()
 def test_discussion_defaults_and_legacy_manager_selection_use_member(self):
  for value in ({'agents':['deepseek-2','deepseek-3']},{'agents':['deepseek-2','deepseek-3'],'reviewer':'deepseek-4'}):
   self.assertEqual(self.f.p.options(value)['reviewer'],'deepseek-2')
 def test_valid_selected_member_is_preserved_and_empty_pool_is_unassigned(self):
  self.assertEqual(independent_reviewer('manager',['worker-a','worker-b'],'worker-b'),'worker-b')
  self.assertIsNone(self.f.p.options({'agents':[]})['reviewer'])
 def test_workflow_default_does_not_automatically_dispatch_review(self):
  w=self.f.w.start('user','project',['deepseek-2','deepseek-3'],confirmed=True)
  self.assertEqual(w['reviewer'],'deepseek-2')
  self.assertFalse(any(s['kind']=='check' for s in self.f.w.steps(w['id'])))
