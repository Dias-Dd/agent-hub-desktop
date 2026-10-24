import json,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import test_designs as base
from hub.designs import Designs

class DemoCompletion(unittest.TestCase):
 setUp=base.DesignFlow.setUp
 tearDown=base.DesignFlow.tearDown
 plan=base.DesignFlow.plan
 start=base.DesignFlow.start
 finish=base.DesignFlow.finish
 write_manifest=base.DesignFlow.write_manifest
 def test_completion_allows_manager_running_and_cancels_queue_before_freezing(self):
  _,d=self.start();self.write_manifest(d);complete=self.w.project_complete;result={};tasks=[]
  def submit(actor,run_id,summary,evidence):
   w=next(w for w in self.w.snapshot('user') if w['id']==d['workflow_id'])
   for i,agent in enumerate(['deepseek-1','deepseek-2','deepseek-1']):
    task=self.w.dispatch(w,agent,'Inspect home.html','pending-'+str(i),'check',read_paths=['home.html'])['task_id'];tasks.append(task)
    if i<2:
     title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone()[0]
     job=self.d.submit('user',agent,title,True,task)

   result.update(complete(actor,run_id,summary,evidence));return result
  with patch.object(self.w,'project_complete',side_effect=submit):review=self.finish(d)
  self.assertTrue(result['completed']);self.assertTrue(result['design_review_ready']);self.assertEqual(len(result['stopped_tasks']),3)
  self.assertEqual([self.h.db.execute('SELECT status FROM executions WHERE task_id=?',(t,)).fetchone()[0] for t in tasks],['cancelled','cancelled','cancelled'])
  self.assertIn('home',self.ds.content('user',d['id'])['html']['home'])
 def test_architecture_rename_does_not_hide_v2(self):
  _,d=self.start();d['outline']=[{'id':'home'},{'id':'settings'},{'id':'arch','kind':'architecture'}];self.ds.save(d)
  self.write_manifest(d);first=self.finish(d)
  second=self.ds.feedback('user',d['id'],1,'Add editing controls','home',scope='page')
  (Path(second['working_directory'])/'home.html').write_text('<h1>v2 editing controls</h1>',encoding='utf-8')
  second=self.finish(second)
  self.assertEqual(second['state'],'review');self.assertEqual([v['version'] for v in second['versions']],[1,2])
  self.assertIn('v2 editing controls',self.ds.content('user',d['id'])['html']['home'])
  self.assertNotIn('v2 editing controls',self.ds.content('user',d['id'],1)['html']['home'])
 def test_restart_recovers_completed_unpublished_review_without_model_calls(self):
  _,d=self.start();self.write_manifest(d);d=self.finish(d);d.update(state='building',versions=[]);self.ds.save(d)
  count=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0]
  repaired=Designs(self.h,self.p,self.w);repaired.recover_publications()
  d=repaired.get(d['id']);self.assertEqual(d['state'],'review');self.assertEqual(len(d['versions']),1)
  self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],count)
 def test_recovery_does_not_publish_active_workflow(self):
  _,d=self.start();self.write_manifest(d);self.ds.recover_publications()
  self.assertEqual(self.ds.get(d['id'])['state'],'building');self.assertEqual(self.ds.get(d['id'])['versions'],[])

 def test_restart_retires_old_completed_workflow_queue_then_publishes(self):
  _,d=self.start();self.write_manifest(d);d=self.finish(d)
  w=next(w for w in self.w.snapshot('user') if w['id']==d['workflow_id']);w['status']='active';self.w.save(w)
  task=self.w.dispatch(w,'deepseek-1','Inspect home.html','legacy-queue','check',read_paths=['home.html'])['task_id']
  title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone()[0];self.d.submit('user','deepseek-1',title,True,task)
  w['status']='completed';self.w.save(w);d.update(state='building',versions=[]);self.ds.save(d)
  requests=len(self.api.requests);self.ds.recover_publications()
  self.assertEqual(self.ds.get(d['id'])['state'],'review')
  self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE task_id=?',(task,)).fetchone()[0],'cancelled')
  self.assertEqual(len(self.api.requests),requests)
