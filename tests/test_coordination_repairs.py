import json,tempfile,threading,time,unittest,os
from pathlib import Path
from unittest.mock import patch,MagicMock
import test_designs as fixtures
from hub.core import HubError
from hub.integrations import command
from hub.codex_runtime import AppServer

class CoordinationRepairs(unittest.TestCase):
 def setUp(self):
  self.f=fixtures.DesignFlow();self.f.setUp();self.h=self.f.h;self.w=self.f.w;self.d=self.f.d;self.d.models=dict(self.d.models)
  self.project=self.w.start('user','Approved work',['deepseek-1','deepseek-2','deepseek-3'],confirmed=True)
 def tearDown(self):self.d.close();self.f.tearDown()
 def dispatch(self,agent,path,kind='work'):
  return self.w.dispatch(self.project,agent,'Modify '+path,str(time.time_ns()),kind,write_paths=[path] if kind=='work' else None,read_paths=[path] if kind=='check' else None)['task_id']
 def submit(self,task):
  row=self.h.db.execute('SELECT agent,title FROM tasks WHERE id=?',(task,)).fetchone()
  return self.d.submit('user',row['agent'],row['title'],True,task)
 def test_same_file_across_agents_waits_but_unrelated_file_can_run(self):
  first=self.dispatch('deepseek-1','state.html');second=self.dispatch('deepseek-2','state.html');other=self.dispatch('deepseek-3','other.html')
  for task in (first,second,other):self.submit(task)
  started=threading.Event();unrelated=threading.Event();release=threading.Event();second_started=threading.Event()
  def execute(run):
   if run['task_id']==first:started.set();release.wait(4)
   elif run['task_id']==second:second_started.set()
   else:unrelated.set()
   with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed' WHERE id=?",(run['id'],))
  with self.h.tx():self.h.db.execute("INSERT OR REPLACE INTO settings VALUES('max_parallel','3')")
  with patch.object(self.d,'execute',side_effect=execute):
   self.d.start()
   try:
    self.assertTrue(started.wait(2));self.assertTrue(unrelated.wait(2));self.assertFalse(second_started.is_set());release.set();self.assertTrue(second_started.wait(2))
   finally:release.set();self.d.close()
 def test_readonly_review_waits_for_relevant_writer(self):
  first=self.dispatch('deepseek-1','unfinished.html');check=self.dispatch('deepseek-2','unfinished.html','check')
  self.assertEqual(self.h.db.execute('SELECT depends_on FROM workflow_resource_dependencies WHERE task=?',(check,)).fetchone()[0],first)
 def test_scope_escape_is_rejected_atomically(self):
  before=len(self.w.steps(self.project['id']))
  with self.assertRaises(HubError):self.dispatch('deepseek-1','../outside.html')
  self.assertEqual(len(self.w.steps(self.project['id'])),before)
 def test_manager_stops_orphan_without_worker_confirmation(self):
  task=self.dispatch('deepseek-1','a.html');run=self.submit(task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],))
  with patch.object(self.w,'run_context',return_value=(self.project,{'task_id':'manager'})):
   answer=self.w.project_stop_task('deepseek-4','manager-run',task,'Duplicate task')
  self.assertTrue(answer['stopped']);self.assertEqual(answer['status'],'interrupted')
  self.assertNotIn(task,[s['task'] for s in self.w.completion_blocking_tasks(self.w.steps(self.project['id'])) if s['kind']=='work'])
  self.assertEqual(self.h.db.execute('SELECT count(*) FROM agent_stops').fetchone()[0],0)
 def test_manager_force_stop_releases_live_worker_immediately(self):
  task=self.dispatch('deepseek-1','a.html');run=self.submit(task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],))
  thread=MagicMock();thread.is_alive.return_value=True;self.d.run_threads[run['id']]=thread
  with patch.object(self.w,'run_context',return_value=(self.project,{'task_id':'manager'})):
   answer=self.w.project_stop_task('deepseek-4','manager-run',task,'Stop')
  self.assertTrue(answer['stopped']);self.assertEqual(answer['status'],'interrupted');self.d.run_threads.clear()
 def test_stop_rejects_foreign_task(self):
  with patch.object(self.w,'run_context',return_value=(self.project,{'task_id':'manager'})):
   with self.assertRaises(HubError):self.w.project_stop_task('deepseek-4','manager-run','foreign','Stop')

 def test_new_stop_tool_is_exposed_only_to_running_manager(self):
  task=self.w.steps(self.project['id'])[0]['task'];run=self.submit(task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],))
  self.assertIn('project_stop_task',[d['function']['name'] for d in self.d.definitions(dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(run['id'],)).fetchone()))])
  worker=self.submit(self.dispatch('deepseek-1','work.html'))
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(worker['id'],))
  self.assertNotIn('project_stop_task',[d['function']['name'] for d in self.d.definitions(dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(worker['id'],)).fetchone()))])
 def test_manager_can_cancel_prepared_task_after_its_agent_was_removed(self):
  task=self.dispatch('deepseek-1','a.html');self.d.models.pop('deepseek-1')
  with patch.object(self.w,'run_context',return_value=(self.project,{'task_id':'manager'})):
   answer=self.w.project_stop_task('deepseek-4','manager-run',task,'Retired executor')
  self.assertTrue(answer['cancelled']);self.assertEqual(self.w.steps(self.project['id'])[-1]['status'],'cancelled')
 def test_cancelled_writer_releases_resource_wait(self):
  task=self.dispatch('deepseek-1','a.html');run=self.submit(task);other=self.dispatch('deepseek-2','a.html')
  with patch.object(self.w,'run_context',return_value=(self.project,{'task_id':'manager'})):self.w.project_stop_task('deepseek-4','manager-run',task,'Cancel')
  # The resource dependency waits for local termination, not a success claim.
  pending=self.h.db.execute("SELECT 1 FROM workflow_resource_dependencies d LEFT JOIN executions e ON e.task_id=d.depends_on WHERE d.task=? AND (e.status IS NULL OR e.status IN ('running','queued','waiting_quota','interrupting'))",(other,)).fetchone()
  self.assertIsNone(pending)

 def test_restart_backfills_old_queues_without_cycles(self):
  a=self.dispatch('deepseek-1','a.html');b=self.dispatch('deepseek-2','a.html')
  with self.h.tx():self.h.db.execute('DELETE FROM workflow_resources');self.h.db.execute('DELETE FROM workflow_resource_dependencies')
  from hub.workflows import Workflows
  restored=Workflows(self.h,self.w.runtimes)
  rows=self.h.db.execute('SELECT task,depends_on FROM workflow_resource_dependencies').fetchall()
  self.assertEqual([tuple(r) for r in rows],[(b,a)])

 def test_dead_worker_client_is_closed_and_confirmed_before_ghost_release(self):
  task=self.dispatch('deepseek-1','a.html');run=self.submit(task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],))
  client=MagicMock();client.proc.poll.return_value=0;self.d.clients[run['id']]=client
  with patch.object(self.w,'run_context',return_value=(self.project,{'task_id':'manager'})):answer=self.w.project_stop_task('deepseek-4','manager-run',task,'Orphan')
  self.assertTrue(answer['stopped']);client.close.assert_called();self.assertNotIn(run['id'],self.d.clients)
 def test_owned_live_process_is_killed_without_waiting_for_member(self):
  task=self.dispatch('deepseek-1','a.html');run=self.submit(task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],))
  client=MagicMock();client.proc.poll.return_value=None;self.d.clients[run['id']]=client
  with patch.object(self.w,'run_context',return_value=(self.project,{'task_id':'manager'})):answer=self.w.project_stop_task('deepseek-4','manager-run',task,'Stop')
  self.assertTrue(answer['stopped']);client.job.close.assert_called();client.proc.kill.assert_called();self.d.clients.clear()

class AdapterRepairs(unittest.TestCase):
 def test_extensionless_npm_node_entry_handles_quoted_multiline_prompt(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);target=root/'node_modules/pkg/bin/codebuddy';target.parent.mkdir(parents=True);target.write_text('#!/usr/bin/env node\nconsole.log("ok")')
   launcher=root/'codebuddy.cmd';launcher.write_text('@echo off\n"%dp0%\\node_modules\\pkg\\bin\\codebuddy" %*')
   with patch('hub.integrations.os.name','nt'):argv=command([str(launcher),'-p','JSON {"report":"a"}\nnext'])
   self.assertEqual(argv[1],str(target.resolve()));self.assertEqual(argv[-1],'JSON {"report":"a"}\nnext');self.assertNotIn('cmd.exe',argv)
 def test_codex_mcp_approval_is_scoped_to_hub_server(self):
  import io
  proc=MagicMock();proc.stdout=io.StringIO()
  with patch('hub.codex_runtime.subprocess.Popen',return_value=proc) as launch,patch('hub.codex_runtime.ProcessJob'),patch.object(AppServer,'rpc',return_value={}):
   client=AppServer('.',{'command':'python','args':['bridge.py']},executable_path='codex')
   try:
    args=launch.call_args.args[0];self.assertIn('mcp_servers.agent_hub.default_tools_approval_mode="approve"',args)
    self.assertFalse(any(x.startswith('approval_policy=') for x in args))
   finally:client.close()
