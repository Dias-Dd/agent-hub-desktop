import unittest,json
from unittest.mock import patch
import test_manager_owned_review as base
class ManagerProgress(base.ManagerOwnedReview):
 def test_report_persists_in_own_workflow(self):
  w,_=self.workflow();other={**w,'id':'other'};self.w.save(other)
  with patch.object(self.w,'run_context',return_value=(w,{'task_id':'manager-task'})) as context:
   report=self.w.project_progress('deepseek-2','r',37,'已完成核心功能，尚待边界测试')
  context.assert_called_once_with('deepseek-2','r',True)
  stored=json.loads(self.h.db.execute('select body from workflows where id=?',(w['id'],)).fetchone()[0]);self.assertEqual(stored['manager_progress']['progress'],37);self.assertEqual(report['by'],'deepseek-2')
  self.assertNotIn('manager_progress',json.loads(self.h.db.execute('select body from workflows where id="other"').fetchone()[0]))
 def test_progress_can_be_revised_after_new_findings(self):
  w,_=self.workflow()
  with patch.object(self.w,'run_context',return_value=(w,{'task_id':'manager-task'})):
   self.w.project_progress('deepseek-4','r',70,'初步完成');self.w.project_progress('deepseek-4','r',60,'复核发现缺口，修订估计')
  self.assertEqual(w['manager_progress']['progress'],60)

 def test_dynamic_manager_receives_progress_tool_only(self):
  w,_=self.workflow();w['manager']='deepseek-2'
  self.h.db.execute('insert into workflow_steps values(?,?,?,?,?)',(w['id'],1,'manager-progress-tool','deepseek-2','review'))
  run={'id':'run','agent':'deepseek-2','task_id':'manager-progress-tool','purpose':'task','permission':'full'}
  with patch.object(self.w,'run_context',return_value=(w,{'step_kind':'review'})):
   self.assertIn('project',[item['function']['name'] for item in self.d.definitions(run)])
  with patch.object(self.w,'run_context',return_value=(w,{'step_kind':'work'})):
   self.assertNotIn('project',[item['function']['name'] for item in self.d.definitions({**run,'agent':'deepseek-1'})])
