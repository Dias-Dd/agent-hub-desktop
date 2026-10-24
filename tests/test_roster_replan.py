import unittest,json
from unittest.mock import patch
import test_designs as base
class Replan(unittest.TestCase):
 def setUp(self):base.DesignFlow.setUp(self)
 def tearDown(self):base.DesignFlow.tearDown(self)
 def plan(self,mode='demo'):return base.DesignFlow.plan(self,mode)
 def workflow(self,ident):return json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(ident,)).fetchone()[0])
 def disable(self,agent):self.d.models=dict(self.d.models);self.d.models.pop(agent,None)
 def test_removed_worker_reassigns_through_manager_not_replacement(self):
  s=self.plan('skip');self.disable('deepseek-1')
  result=self.p.approve(s,s['revision'],None);w=self.workflow(result['workflow_id'])
  self.assertNotIn('deepseek-1',w['agents']);steps=self.w.steps(w['id']);self.assertEqual(len(steps),1);self.assertEqual(steps[0]['agent'],'deepseek-4')
  self.assertEqual(w['approved_plan']['tasks'][0]['agent'],'deepseek-1');self.assertIn('重新安排',w['initial_manager_instruction']);self.assertEqual(w['roster_replan']['unavailable'],['deepseek-1'])
 def test_removed_reviewer_also_requests_manager_reassignment(self):
  s=self.plan('skip');s['options']['reviewer']='deepseek-3';self.disable('deepseek-3');self.p.save(s)
  result=self.p.approve(s,s['revision'],None);w=self.workflow(result['workflow_id']);self.assertEqual(w['reviewer'],'deepseek-4');self.assertIn('deepseek-3',w['roster_replan']['unavailable']);self.assertEqual(self.w.steps(w['id'])[0]['kind'],'plan')
 def test_manager_can_start_when_all_former_workers_removed(self):
  s=self.plan('skip')
  for a in s['options']['agents']:self.disable(a)
  result=self.p.approve(s,s['revision'],None);w=self.workflow(result['workflow_id']);self.assertEqual(w['agents'],[]);self.assertEqual(self.w.steps(w['id'])[0]['agent'],'deepseek-4')
 def test_demo_uses_refreshed_members_and_preserves_original_plan(self):
  s=self.plan();self.disable('deepseek-1');result=self.p.approve(s,s['revision'],None);d=self.ds.get(result['design_id']);w=self.workflow(d['workflow_id'])
  self.assertNotIn('deepseek-1',w['agents']);self.assertEqual(w['approved_plan'],s['plan']);self.assertIn('不要求有相同模型',w['initial_manager_instruction']);self.assertEqual(self.w.steps(w['id'])[0]['agent'],'deepseek-4')
 def test_repeat_approval_does_not_duplicate_manager_work(self):
  s=self.plan('skip');self.disable('deepseek-1');result=self.p.approve(s,s['revision'],None);again=self.p.approve(self.p.get(s['id']),s['revision'],None);self.assertEqual(result['workflow_id'],again['workflow_id']);self.assertEqual(len(self.w.steps(result['workflow_id'])),1)
