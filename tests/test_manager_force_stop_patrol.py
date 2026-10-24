import json,threading,time,unittest
from unittest.mock import patch,MagicMock
from pathlib import Path
import test_designs as base
from hub.core import HubError
from hub.integration_runtime import LinkedRuntime

class ManagerControls(unittest.TestCase):
 def setUp(self):
  self.f=base.DesignFlow();self.f.setUp();self.h=self.f.h;self.w=self.f.w;self.d=self.f.d
  self.project=self.w.start('user','Approved work',['deepseek-1','deepseek-2'],confirmed=True)
 def tearDown(self):self.d.close();self.f.tearDown()
 def running(self,task):
  t=self.h.db.execute('SELECT agent,title FROM tasks WHERE id=?',(task,)).fetchone()
  result=self.d.submit('user',t['agent'],t['title'],True,task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),result['id']))
  return dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(result['id'],)).fetchone())
 def member(self,instruction='Write a.txt'):
  return self.w.dispatch(self.project,'deepseek-1',instruction,str(time.time_ns()),write_paths=['a.txt'])['task_id']
 def stop(self,task):
  with patch.object(self.w,'run_context',return_value=(self.project,{'task_id':'manager'})):
   return self.w.project_stop_task('deepseek-4','manager-run',task,'Replace task')
 def test_force_stop_allows_reassignment_and_fences_late_api_response(self):
  task=self.member();run=self.running(task);entered=threading.Event();release=threading.Event()
  answer={'choices':[{'message':{'role':'assistant','content':'old result','tool_calls':[]}}],'usage':{}}
  def request(*args):entered.set();release.wait(5);return answer
  with patch.object(self.d.api,'request',side_effect=request):
   worker=threading.Thread(target=self.d.execute,args=(run,));worker.start()
   try:
    self.assertTrue(entered.wait(2));self.assertTrue(self.stop(task)['can_reassign'])
    new_task=self.member('Replacement write a.txt');new=self.running(new_task)
    with self.h.tx():self.h.db.execute("UPDATE agents SET status='busy',active=? WHERE id=?",(new['message_id'],new['agent']))
    release.set();worker.join(3);self.assertFalse(worker.is_alive())
    self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()[0],'interrupted')
    self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(run['message_id'],)).fetchone()[0],'interrupted')
    self.assertEqual(self.h.db.execute('SELECT active FROM agents WHERE id=?',(new['agent'],)).fetchone()[0],new['message_id'])
    self.assertIsNone(self.h.db.execute('SELECT 1 FROM workflow_dependencies WHERE task=?',(new_task,)).fetchone())
    self.assertIsNone(self.h.db.execute('SELECT 1 FROM deepseek_context WHERE key=?',(self.d.sessions.key(run),)).fetchone())
   finally:release.set();worker.join(5)
 def test_revoked_run_cannot_write_files_or_change_session(self):
  run=self.running(self.member());self.d.sessions.bind(run,'original');self.stop(run['task_id'])
  self.d.sessions.bind(run,'stale');self.d.sessions.state(run,'inflight')
  self.assertEqual(self.d.sessions.get(run)['session_id'],'original')
  with self.assertRaises(HubError):self.d.tool(run,'write_file',{'path':'a.txt','content':'late'}, {'write_file'})
  self.assertFalse((Path(run['cwd'])/'a.txt').exists())
 def test_late_integration_finalizer_cannot_overwrite_forced_stop(self):
  run=self.running(self.member());self.stop(run['task_id'])
  LinkedRuntime.finalize(self.d,run,'completed','stale success')
  self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()[0],'interrupted')
 def test_client_registered_after_force_stop_is_killed(self):
  run=self.running(self.member());self.stop(run['task_id']);client=MagicMock()
  with self.assertRaises(HubError):self.d.track_client(run,client)
  client.job.close.assert_called();client.close.assert_called();self.assertNotIn(run['id'],self.d.clients)
 def test_patrol_toggle_changes_only_one_field_no_messages_or_agents(self):
  with self.h.lock:
   before={t:[tuple(r) for r in self.h.db.execute('SELECT * FROM '+t)] for t in ['executions','messages','agents','workflow_events','audit']}
   original=json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(self.project['id'],)).fetchone()[0])
  self.w.set_patrol('user',self.project['id'],False)
  saved=json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(self.project['id'],)).fetchone()[0])
  self.assertEqual(saved,{**original,'patrol_enabled':False})
  for t,rows in before.items():self.assertEqual(rows,[tuple(r) for r in self.h.db.execute('SELECT * FROM '+t)])
  self.w.set_patrol('user',self.project['id'],True)
  self.assertEqual(json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(self.project['id'],)).fetchone()[0]),{**original,'patrol_enabled':True})
 def test_disabled_patrol_skips_periodic_wake_but_pending_messages_wake(self):
  w={**self.project,'patrol_enabled':False,'next_inspection':0}
  with patch.object(self.w,'steps',return_value=[]),patch.object(self.w,'ingest'),patch.object(self.w,'notify_dependency_blocks'),patch.object(self.w,'prepare_manager') as wake:
   self.w.advance(w);wake.assert_not_called()
   w['patrol_enabled']=True;self.w.advance(w);wake.assert_called_once()
   wake.reset_mock();w['patrol_enabled']=False
   with self.h.tx():self.h.db.execute("INSERT INTO workflow_events VALUES(?,?,NULL,?,'pending',NULL,?)",('new',w['id'],json.dumps({'type':'message'}),time.time()))
   with patch.object(self.w,'pending_requires_wake',return_value=True):self.w.advance(w)
   wake.assert_called_once()
 def test_only_user_controls_patrol(self):
  with self.assertRaises(HubError):self.w.set_patrol('deepseek-4',self.project['id'],False)
  with self.assertRaises(HubError):self.w.set_patrol('user',self.project['id'],'false')


 def test_native_codex_late_result_does_not_revive_stopped_execution(self):
  from test_codex_runtime import FakeAppServer
  entered=threading.Event();release=threading.Event()
  class Held(FakeAppServer):
   def event(self,timeout=.5):entered.set();release.wait(5);return super().event(timeout)
  runtime=self.f.c;runtime.models={'deepseek-1':'gpt-6.1-sol'};runtime.factory=Held
  runtime.configure('user',self.f.t.name,'full',0,60,True,True)
  self.project['grants'][runtime.provider]=runtime.config()['grant_id'];self.w.save(self.project)
  task=self.member();title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone()[0]
  job=runtime.submit('user','deepseek-1',title,True,task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
  run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
  worker=threading.Thread(target=runtime.execute,args=(run,));worker.start()
  try:
   self.assertTrue(entered.wait(2));self.assertTrue(self.stop(task)['stopped']);release.set();worker.join(3)
   self.assertFalse(worker.is_alive());self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(job['id'],)).fetchone()[0],'interrupted')
  finally:release.set();worker.join(5)
 def test_native_antigravity_late_result_does_not_revive_stopped_execution(self):
  from test_antigravity import FakeProbe,FakeStream
  entered=threading.Event();release=threading.Event()
  class Held(FakeStream):
   def event(self):entered.set();release.wait(5);return super().event()
  runtime=self.f.a;runtime.models={'deepseek-1':'gemini-3.8-flash-medium'};runtime.stream_factory=Held
  runtime.configure('user',self.f.t.name,'full',0,60,True,True)
  self.project['grants'][runtime.provider]=runtime.config()['grant_id'];self.w.save(self.project)
  task=self.member();title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone()[0]
  with patch.object(runtime,'refresh',return_value=FakeProbe().run()):
   job=runtime.submit('user','deepseek-1',title,True,task)
   with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
   run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
   worker=threading.Thread(target=runtime.execute,args=(run,));worker.start()
   try:
    self.assertTrue(entered.wait(2));self.assertTrue(self.stop(task)['stopped']);release.set();worker.join(3)
    self.assertFalse(worker.is_alive());self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(job['id'],)).fetchone()[0],'interrupted')
   finally:release.set();worker.join(5)

 def test_force_stop_terminates_owned_process_before_returning(self):
  import subprocess,sys
  from hub.process_job import ProcessJob
  from types import SimpleNamespace
  run=self.running(self.member());marker=Path(self.f.t.name)/'should-not-be-written.txt'
  proc=subprocess.Popen([sys.executable,'-c',"import time,pathlib;time.sleep(10);pathlib.Path("+repr(str(marker))+").write_text('late')"],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  job=ProcessJob(proc);self.d.clients[run['id']]=SimpleNamespace(proc=proc,job=job)
  try:
   self.assertTrue(self.stop(run['task_id'])['stopped']);proc.wait(timeout=3);self.assertFalse(marker.exists())
  finally:
   job.close()
   if proc.poll() is None:proc.kill()
   proc.wait()

 def test_immediate_message_has_no_file_wait_and_preempts_only_recipient(self):
  task=self.member();run=self.running(task)
  # An older queued job must not hold an urgent control message behind file locks.
  queued=self.w.dispatch(self.project,'deepseek-2','Write a.txt','queued',write_paths=['a.txt'])['task_id']
  co=self.f.co
  with patch.object(co,'context',return_value=(self.project,{'id':'manager-run','task_id':'manager'})):
   mid=co.send('deepseek-4','deepseek-1','Please stop editing and report progress',mode='immediate',project_id=self.project.get('project_id') or self.project['id'])[0]
  wake=self.h.db.execute('SELECT task FROM wakeups WHERE message=?',(mid,)).fetchone()
  self.assertIsNotNone(wake)
  self.assertIsNone(self.h.db.execute('SELECT 1 FROM workflow_resource_dependencies WHERE task=?',(wake[0],)).fetchone())
  self.assertEqual(self.h.db.execute('SELECT stop_requested FROM executions WHERE id=?',(run['id'],)).fetchone()[0],1)
  self.assertIsNotNone(self.h.db.execute('SELECT 1 FROM tasks WHERE id=?',(queued,)).fetchone())

 def test_immediate_retry_does_not_interrupt_another_turn(self):
  run=self.running(self.member());co=self.f.co
  with patch.object(co,'context',return_value=(self.project,{'id':'manager-run','task_id':'manager'})):
   first=co.send('deepseek-4','deepseek-1','Urgent',mode='immediate',request_key='once')
   with self.h.tx():self.h.db.execute('UPDATE executions SET stop_requested=0 WHERE id=?',(run['id'],))
   self.assertEqual(co.send('deepseek-4','deepseek-1','Urgent',mode='immediate',request_key='once'),first)
   self.assertEqual(self.h.db.execute('SELECT stop_requested FROM executions WHERE id=?',(run['id'],)).fetchone()[0],0)
