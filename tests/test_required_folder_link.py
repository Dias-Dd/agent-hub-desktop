import json,time,unittest
from pathlib import Path
from types import SimpleNamespace
import test_designs as base
from hub.core import HubError
from hub.automation import Automation
class RequiredFolder(unittest.TestCase):
 plan=base.DesignFlow.plan
 def setUp(self):
  base.DesignFlow.setUp(self);base.DesignFlow.start(self)
  self.workflow=self.w.snapshot('user')[0];self.workflow.pop('design_review',None);self.w.save(self.workflow)
  task=self.w.steps(self.workflow['id'])[0]['task'];self.job=self.d.submit('user','deepseek-4',self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone()[0],True,task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),self.job['id']))
  self.service=Automation(SimpleNamespace(hub=self.h,workflows=self.w))
 def tearDown(self):base.DesignFlow.tearDown(self)
 def complete(self):
  self.w.project_complete('deepseek-4',self.job['id'],'Ready',['verified'])
  return self.w.project_complete('deepseek-4',self.job['id'],'Ready',['verified'],confirmation={'comprehensive_tests':'verified','vm_ui_tests':'not applicable to fixture'})
 def share(self):return self.service.publish_artifact('deepseek-4',self.job['id'],'.',kind='folder',caption='交付目录')
 def test_missing_link_rejected_without_finishing_or_stopping(self):
  with self.assertRaisesRegex(HubError,'publish_artifact'):self.complete()
  self.assertEqual(self.w.snapshot('user')[0]['status'],'active')
  self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(self.job['id'],)).fetchone()[0],'running')
 def test_manager_link_allows_completion_without_user_click(self):
  link=self.share();self.assertTrue(self.complete()['completed'])
  w=self.w.snapshot('user')[0];self.assertEqual(w['completion']['folder_link'],link['id'])
  self.assertTrue(self.complete()['deduplicated'])
 def test_old_workflow_or_worker_link_does_not_count(self):
  link=self.share()
  for field,value in [('workflow_id','another-workflow'),('sender','deepseek-1')]:
   item=dict(link);item[field]=value
   with self.h.tx():self.h.db.execute('UPDATE shared_artifacts SET body=? WHERE id=?',(json.dumps(item),link['id']))
   with self.assertRaisesRegex(HubError,'publish_artifact'):self.complete()
 def test_removed_directory_link_does_not_count(self):
  link=self.share();link['path']=str(Path(self.t.name)/'missing-folder')
  with self.h.tx():self.h.db.execute('UPDATE shared_artifacts SET body=? WHERE id=?',(json.dumps(link),link['id']))
  with self.assertRaisesRegex(HubError,'publish_artifact'):self.complete()

 def test_demo_completion_does_not_require_folder_link(self):
  self.assertIsNone(self.w.completion_folder({'id':'demo','design_review':'review'}))

 def test_first_completion_only_asks_does_not_freeze_or_cancel(self):
  self.share();answer=self.w.project_complete('deepseek-4',self.job['id'],'Ready',['verified'])
  self.assertTrue(answer['confirmation_required']);self.assertFalse(answer['completed']);self.assertIn('哈希',answer['questions'][0]);self.assertIn('PID',answer['questions'][0]);self.assertIn('逐按钮',answer['questions'][1])
  self.assertEqual(self.w.snapshot('user')[0]['status'],'active')
  self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(self.job['id'],)).fetchone()[0],'running')
 def test_testing_confirmation_is_manager_judgment_not_automated_pass_gate(self):
  self.share();self.w.project_complete('deepseek-4',self.job['id'],'Ready',['verified'])
  report={'comprehensive_tests':'partial; known limitation disclosed','vm_ui_tests':'not run; user accepts CLI-only delivery'}
  self.assertTrue(self.w.project_complete('deepseek-4',self.job['id'],'Ready',['verified'],confirmation=report)['completed'])
  self.assertEqual(self.w.snapshot('user')[0]['completion']['testing_confirmation'],report)
