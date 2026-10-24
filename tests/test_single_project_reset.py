import json,time,unittest
from pathlib import Path
from unittest.mock import patch
import test_designs as base
from hub.projects import Projects
from hub.core import HubError
from hub.manager_inbox import ManagerInbox
from hub.project_activity import allows,busy,require_available

class SingleProjectReset(unittest.TestCase):
 def setUp(self):
  self.f=base.DesignFlow();self.f.setUp();self.h=self.f.h;self.w=self.f.w;self.planning=self.f.p;self.rt=self.f.d
  with patch.object(Projects,'tag'):self.projects=Projects(self.h)
  self.one=self.projects.create('user','One');self.two=self.projects.create('user','Two')
 def tearDown(self):self.f.tearDown()
 def discuss(self,project,body='Build fixture'):
  return self.planning.message('user',body,project_id=project['id'],options={'cwd':project['cwd'],'agents':['deepseek-1'],'preview_mode':'skip'})
 def start(self,project):
  return self.w.start('user','Build fixture',['deepseek-1'],confirmed=True,project_id=project['id'])
 def test_other_project_cannot_discuss_or_start_while_one_runs(self):
  one=self.start(self.one)
  with self.assertRaisesRegex(HubError,'One'):self.start(self.two)
  with self.assertRaisesRegex(HubError,'One'):self.discuss(self.two)
  self.w.stop('user',one['id']);self.assertEqual(self.start(self.two)['project_id'],self.two['id'])
 def test_two_queued_discussions_do_not_bypass_single_project(self):
  self.discuss(self.one)
  with self.assertRaises(HubError):self.discuss(self.two)
  other={'id':'new','task_id':None,'message_id':None,'session_scope':'hub-project:'+self.two['id']}
  self.assertFalse(allows(self.h,other));other['session_scope']='hub-project:'+self.one['id'];self.assertTrue(allows(self.h,other))
 def test_busy_cleanup_rejected_without_stopping_or_deleting(self):
  (Path(self.one['cwd'])/'keep.txt').write_text('keep');self.start(self.one)
  with self.assertRaisesRegex(HubError,'正在执行'):self.projects.cleanup('user',self.one['id'])
  self.assertTrue((Path(self.one['cwd'])/'keep.txt').exists());self.assertEqual(self.w.snapshot('user')[0]['status'],'active')
 def test_execution_created_after_preview_prevents_cleanup(self):
  plan=self.projects.cleanup('user',self.one['id']);self.discuss(self.one)
  with self.assertRaisesRegex(HubError,'正在执行'):self.projects.cleanup('user',self.one['id'],True,plan['inventory_key'])
  self.assertTrue(Path(self.one['cwd']).exists())
 def test_clean_keeps_project_history_and_next_manager_message_resumes_session(self):
  old=self.discuss(self.one);run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(old['pending'],)).fetchone());self.rt.sessions.bind(run,'old-provider-thread')
  self.assertIsNotNone(self.rt.sessions.get(run))
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',finished=? WHERE id=?",(time.time(),run['id']))
  old.update(pending=None,state='draft');self.planning.save(old)
  plan=self.projects.cleanup('user',self.one['id']);result=self.projects.cleanup('user',self.one['id'],True,plan['inventory_key'])
  self.assertTrue(result['ok'],result);self.assertFalse(result['project_removed']);self.assertFalse(Path(self.one['cwd']).exists())
  self.assertFalse(self.h.db.execute('SELECT 1 FROM settings WHERE key=?',('deleted_project:'+self.one['id'],)).fetchone())
  self.assertEqual(self.planning.snapshot('user')[0]['history'],old['history'])
  inbox=ManagerInbox(self.h,self.planning,self.w,self.f.co);answer=inbox.send('user',old['id'],'从头开始做一个计算器',project_id=self.one['id'])
  self.assertTrue(Path(self.one['cwd']).is_dir());new=self.planning.snapshot('user')[0];self.assertEqual(new['id'],old['id']);self.assertEqual(new['history'][-1]['text'],'从头开始做一个计算器')
  new_run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(new['pending'],)).fetchone());self.assertEqual(self.rt.sessions.get(new_run)['session_id'],'old-provider-thread');self.assertEqual(self.rt.sessions.key(run),self.rt.sessions.key(new_run));self.assertIn('项目文件已由用户清理',new_run['prompt'])
 def test_cleaning_flag_prevents_new_model_start(self):
  self.h.cleaning_projects={self.one['id']}
  with self.assertRaisesRegex(HubError,'清理'):self.discuss(self.one)

 def test_timer_for_another_project_is_held_until_active_project_finishes(self):
  from hub.automation import Automation
  from types import SimpleNamespace
  one=self.start(self.one)
  timer_workflow={'id':'other-w','project_id':self.two['id'],'manager':'deepseek-4','agents':['deepseek-1'],'status':'paused','pause_reason':'wait_time','expires':time.time()+3600,'grants':{},'cwd':self.two['cwd']}
  self.w.save(timer_workflow);service=Automation(SimpleNamespace(hub=self.h,workflows=self.w,coordination=self.f.co))
  timer={'id':'timer-other','workflow_id':'other-w','project_id':self.two['id'],'recipient':'deepseek-4','creator':'deepseek-4','state':'scheduled','due':time.time()-1,'condition':'time'}
  with self.h.tx():service.save(timer)
  service.fire(timer)
  self.assertEqual(timer['state'],'held');self.assertIn('另一项目',timer['reason']);self.assertEqual(self.w.snapshot('user')[0]['status'],'paused')

 def test_paused_project_releases_slot_and_can_clean_unstarted_tasks(self):
  one=self.start(self.one);step=self.w.steps(one['id'])[0]
  title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(step['task'],)).fetchone()[0]
  job=self.rt.submit('user',step['agent'],title,True,step['task'])
  one['status']='paused';self.w.save(one)
  self.assertFalse(busy(self.h,self.one['id']));self.start(self.two)
  plan=self.projects.cleanup('user',self.one['id']);self.assertTrue(self.projects.cleanup('user',self.one['id'],True,plan['inventory_key'])['ok'])
  self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(job['id'],)).fetchone()[0],'cancelled')

 def test_cleaned_workflow_no_longer_supplies_old_progress_or_execution_state(self):
  one=self.start(self.one);one.update(status='completed',manager_progress={'progress':100,'note':'old result'});self.w.save(one)
  plan=self.projects.cleanup('user',self.one['id']);self.assertTrue(self.projects.cleanup('user',self.one['id'],True,plan['inventory_key'])['ok'])
  self.assertEqual(self.w.snapshot('user'),[])

 def test_harness_confirmed_project_time_not_capped_by_old_twenty_minutes(self):
  cfg=self.rt.config();cfg.update(engine='harness',max_seconds=1200,authorized_max_seconds=1200)
  with self.h.tx():self.h.db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(cfg),self.rt.config_key))
  updated=self.rt.configure('user',self.one['cwd'],cfg['permission'],0,7200,True,True)
  self.assertEqual(updated['max_seconds'],7200);self.assertEqual(updated['grant_id'],cfg['grant_id']);self.assertEqual(updated.get('budget_cents'),cfg.get('budget_cents'))

 def test_api_explicit_time_ceiling_remains_separate(self):
  cfg=self.rt.config();cfg.update(engine='api',max_seconds=1200,authorized_max_seconds=1200)
  with self.h.tx():self.h.db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(cfg),self.rt.config_key))
  updated=self.rt.configure('user',self.one['cwd'],cfg['permission'],0,7200,True,True)
  self.assertEqual(updated['max_seconds'],1200);self.assertEqual(updated['grant_id'],cfg['grant_id'])
