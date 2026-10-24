import json,unittest,shutil,time
from pathlib import Path
from unittest.mock import patch
import test_designs as base
from hub.projects import Projects
from hub.git_workspaces import GitWorkspaces
from hub.core import HubError

@unittest.skipUnless(shutil.which('git'),'Git unavailable')
class GitWorkflow(unittest.TestCase):
 def setUp(self):
  self.f=base.DesignFlow();self.f.setUp();self.h=self.f.h;self.w=self.f.w;self.d=self.f.d
  (Path(self.f.t.name)/'product').mkdir()
  self.projects=Projects(self.h);self.project=self.projects.create('user','Git project',str(Path(self.f.t.name)/'product'))
  self.root=Path(self.project['cwd']);(self.root/'shared.txt').write_text('baseline\n',encoding='utf8')
  self.flow=self.w.start('user','Build product',['deepseek-1','deepseek-2','deepseek-3'],confirmed=True)
  self.flow.update(project_id=self.project['id'],cwd=str(self.root));self.w.save(self.flow);self.g=self.w.git
 def tearDown(self):self.f.tearDown()
 def job(self,agent,text='Modify shared.txt',kind='work'):
  task=self.w.dispatch(self.flow,agent,text,str(time.time_ns()),kind,write_paths=['shared.txt'] if kind=='work' else None)['task_id']
  row=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone();job=self.d.submit('user',agent,row['title'],True,task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(job['id'],))
  run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone());return self.g.prepare(run)
 def done(self,run,status='completed'):
  with self.h.tx():self.h.db.execute('UPDATE executions SET status=?,finished=? WHERE id=?',(status,time.time(),run['id']))
  return self.g.finish(run,status)
 def integrate(self,agent):
  with patch.object(self.w,'run_context',return_value=(self.flow,{'cwd':str(self.root)})):return self.g.tool('deepseek-4','manager',action='integrate',agent=agent)
 def test_same_file_parallel_work_is_isolated_committed_and_conflict_is_preserved(self):
  a=self.job('deepseek-1');b=self.job('deepseek-2')
  self.assertNotEqual(a['cwd'],b['cwd']);self.assertEqual((self.root/'shared.txt').read_text(),'baseline\n')
  (Path(a['cwd'])/'shared.txt').write_text('version A\n');(Path(b['cwd'])/'shared.txt').write_text('version B\n')
  ra=self.done(a);rb=self.done(b);self.assertEqual(ra['status'],'committed');self.assertEqual(rb['status'],'committed')
  self.assertEqual(self.integrate(a['agent'])['status'],'integrated')
  result=self.integrate(b['agent']);self.assertEqual(result['status'],'conflict');self.assertEqual(result['files'],['shared.txt'])
  self.assertIn('<<<<<<<',(self.root/'shared.txt').read_text());self.assertEqual((Path(b['cwd'])/'shared.txt').read_text(),'version B\n')
  (self.root/'shared.txt').write_text('combined A + B\n');self.g.git(self.root,'add','shared.txt')
  with patch.object(self.w,'run_context',return_value=(self.flow,{'cwd':str(self.root)})):answer=self.g.tool('deepseek-4','manager',action='commit',message='Resolve integration')
  self.assertIn('commit',answer);self.assertTrue(all(x['integrated'] for x in self.g.status(self.flow)['workspaces']))
 def test_automatic_report_contains_commit_and_does_not_merge_it(self):
  a=self.job('deepseek-1');(Path(a['cwd'])/'new.txt').write_text('done')
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(json.dumps({'summary':'done','risk':'low','evidence':[]}),a['id']))
  self.f.co.report(a,'completed',json.dumps({'summary':'done','risk':'low','evidence':[]}))
  report=self.h.db.execute('SELECT evidence FROM worker_reports WHERE run=?',(a['id'],)).fetchone()[0]
  self.assertIn('Git',report);self.assertIn('commit',report);self.assertFalse((self.root/'new.txt').exists())
  head=self.g.git(a['cwd'],'rev-parse','HEAD').stdout;self.g.finish(a,'completed');self.assertEqual(head,self.g.git(a['cwd'],'rev-parse','HEAD').stdout)
 def test_next_task_reuses_worktree_and_fast_forwards_integrated_changes(self):
  a=self.job('deepseek-1');(Path(a['cwd'])/'a.txt').write_text('a');self.done(a);self.integrate(a['agent'])
  (self.root/'manager.txt').write_text('latest');self.g.checkpoint(self.root,'Manager update')
  second=self.job('deepseek-1');self.assertEqual(second['cwd'],a['cwd']);self.assertTrue((Path(second['cwd'])/'manager.txt').exists())
  self.assertEqual(self.g.prepare(second)['prompt'],second['prompt']);self.assertIn('版本更新',second['prompt']);self.assertIn('manager.txt',second['prompt']);self.assertIn('HEAD',second['prompt'])
 def test_failed_work_is_preserved_without_auto_commit(self):
  a=self.job('deepseek-1');(Path(a['cwd'])/'partial.txt').write_text('unfinished');before=self.g.git(a['cwd'],'rev-parse','HEAD').stdout
  result=self.done(a,'uncertain');self.assertEqual(result['status'],'preserved');self.assertTrue((Path(a['cwd'])/'partial.txt').exists());self.assertEqual(before,self.g.git(a['cwd'],'rev-parse','HEAD').stdout)
 def test_generated_outputs_and_secrets_are_not_added(self):
  (self.root/'.env').write_text('SECRET');(self.root/'credentials.json').write_text('SECRET');(self.root/'key.pfx').write_bytes(b'private');(self.root/'bin').mkdir();(self.root/'bin/app.exe').write_bytes(b'build')
  a=self.job('deepseek-1');tracked=self.g.git(a['cwd'],'ls-files').stdout
  for name in ['.env','credentials.json','key.pfx','app.exe']:self.assertNotIn(name,tracked)
  self.assertTrue((self.root/'.env').exists());self.assertIn('shared.txt',tracked)
 def test_restart_reuses_existing_branch_and_no_cross_project_directory(self):
  a=self.job('deepseek-1');self.done(a);self.w.git=GitWorkspaces(self.w);self.g=self.w.git
  b=self.job('deepseek-1');self.assertEqual(a['cwd'],b['cwd']);self.done(b)
  (Path(self.f.t.name)/'other').mkdir()
  other=self.projects.create('user','Second',str(Path(self.f.t.name)/'other'));self.flow.update(project_id=other['id'],cwd=other['cwd']);self.w.save(self.flow)
  c=self.job('deepseek-1');self.assertNotEqual(a['cwd'],c['cwd']);self.assertNotEqual(self.h.db.execute('SELECT branch FROM git_runs WHERE run=?',(a['id'],)).fetchone()[0],self.h.db.execute('SELECT branch FROM git_runs WHERE run=?',(c['id'],)).fetchone()[0])
 def test_file_lock_dependencies_are_absent_for_isolated_project(self):
  a=self.job('deepseek-1');b=self.job('deepseek-2')
  self.assertFalse(self.h.db.execute('SELECT 1 FROM workflow_resource_dependencies WHERE task IN (?,?)',(a['task_id'],b['task_id'])).fetchone())
 def test_original_absolute_paths_are_redirected_to_worktree(self):
  a=self.job('deepseek-1','Modify '+str(self.root/'shared.txt'));self.assertNotIn(str(self.root/'shared.txt'),a['prompt']);self.assertIn(str(Path(a['cwd'])/'shared.txt'),a['prompt'])
 def test_demo_stays_in_original_directory(self):
  self.flow['design_review']='demo';self.w.save(self.flow)
  a=self.job('deepseek-1');self.assertEqual(a['cwd'],self.d.config()['cwd']);self.assertFalse((self.root/'.git').exists())
 def test_worker_cannot_integrate_using_manager_tool(self):
  a=self.job('deepseek-1')
  with self.assertRaises(HubError):self.g.tool(a['agent'],a['id'],action='integrate',agent='deepseek-2')

 def test_dirty_manager_files_are_not_overwritten_by_integration(self):
  a=self.job('deepseek-1');(Path(a['cwd'])/'shared.txt').write_text('worker edit\n');self.done(a)
  (self.root/'shared.txt').write_text('manager unsaved\n');result=self.integrate(a['agent'])
  self.assertEqual(result['status'],'needs_attention');self.assertEqual((self.root/'shared.txt').read_text(),'manager unsaved\n')
 def test_readonly_checker_does_not_auto_commit_generated_files(self):
  a=self.job('deepseek-3',kind='check');(Path(a['cwd'])/'test-output.txt').write_text('evidence')
  result=self.done(a);self.assertEqual(result['status'],'inspected')
  with patch.object(self.w,'run_context',return_value=(self.flow,{**a,'purpose':'question'})):
   self.assertEqual(self.g.tool(a['agent'],a['id'],action='commit')['status'],'read_only')
  self.assertNotIn('test-output.txt',self.g.git(a['cwd'],'ls-files').stdout)
 def test_worker_loop_uses_worktree_and_commit_is_in_real_report(self):
  import threading
  task=self.w.dispatch(self.flow,'deepseek-1','Write loop.txt','loop',write_paths=['loop.txt'])['task_id']
  title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone()[0];job=self.d.submit('user','deepseek-1',title,True,task);finished=threading.Event();observed=[]
  def execute(run):
   observed.append(run);(Path(run['cwd'])/'loop.txt').write_text('actual worker')
   with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',finished=?,result=? WHERE id=?",(time.time(),json.dumps({'summary':'done','risk':'low','evidence':[]}),run['id']))
   finished.set()
  with patch.object(self.d,'execute',side_effect=execute):
   self.d.start()
   try:self.assertTrue(finished.wait(5))
   finally:self.d.close()
  self.assertNotEqual(observed[0]['cwd'],str(self.root));self.assertFalse((self.root/'loop.txt').exists())
  self.f.co.report(observed[0],'completed',json.dumps({'summary':'done','risk':'low','evidence':[]}))
  self.assertIsNotNone(self.h.db.execute('SELECT result FROM git_runs WHERE run=?',(job['id'],)).fetchone()[0]);self.assertEqual(self.integrate('deepseek-1')['status'],'integrated');self.assertEqual((self.root/'loop.txt').read_text(),'actual worker')
 def test_http_mcp_action_exposes_git_status_and_integration(self):
  from hub.server import Server,Handler
  from urllib.request import Request,urlopen
  import threading
  a=self.job('deepseek-1');(Path(a['cwd'])/'http.txt').write_text('http result');self.done(a)
  server=Server(('127.0.0.1',0),Handler);server.hub=self.h;server.workflows=self.w;thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   with patch.object(self.w,'run_context',return_value=(self.flow,{'cwd':str(self.root)})):
    payload=json.dumps({'action':'project_git','args':{'run_id':'manager','action':'integrate','agent':'deepseek-1'}}).encode()
    request=Request('http://127.0.0.1:'+str(server.server_port)+'/api/action',payload,{'Content-Type':'application/json','Authorization':'Bearer '+self.h.tokens['deepseek-4']})
    with urlopen(request) as response:answer=json.load(response)['result']
    self.assertEqual(answer['status'],'integrated');self.assertTrue((self.root/'http.txt').exists())
  finally:server.shutdown();server.server_close();thread.join()

 def test_dirty_worktree_keeps_files_and_explains_its_different_version(self):
  a=self.job('deepseek-1');self.done(a)
  (Path(a['cwd'])/'partial.txt').write_text('unfinished')
  (self.root/'manager.txt').write_text('new API');self.g.checkpoint(self.root,'Manager API changed')
  second=self.job('deepseek-1');self.assertEqual((Path(second['cwd'])/'partial.txt').read_text(),'unfinished');self.assertIn('尚未自动同步',second['prompt']);self.assertIn('主目录HEAD=',second['prompt'])
