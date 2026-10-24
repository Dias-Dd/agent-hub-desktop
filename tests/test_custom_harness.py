import json,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from hub.custom_harness import discover
from hub.codex_runtime import CodexRuntime
from test_integrations import RegistryTests

class CustomHarness(unittest.TestCase):
 def setUp(self):
  self.f=RegistryTests();self.f.setUp();self.registry=self.f.registry;self.h=self.f.server.hub
  self.folder=Path(self.f.temp.name)/'adapters/custom/demo';self.folder.mkdir(parents=True)
  self.manifest={'version':1,'id':'demo','name':'Local demo adapter','protocol':'hub-jsonl-v1','command':[sys.executable,str(self.folder/'bridge.py')],'models':[{'id':'example/model','efforts':['default']}],'capabilities':{'resume':True,'tools':False,'streaming':True}}
  self.script("print(json.dumps({'type':'result','status':'completed','session_id':'native-session','text':json.dumps({'history':len(r['history']),'session':r['session_id'],'cwd':r['cwd']})}),flush=True)")
 def tearDown(self):self.f.tearDown()
 def script(self,body):
  (self.folder/'bridge.py').write_text('import sys,json,time\nr=json.loads(sys.stdin.readline())\n'+body+'\n',encoding='utf-8')
  (self.folder/'adapter.json').write_text(json.dumps(self.manifest),encoding='utf-8')
 def connect(self):
  self.registry.adapters('user');c=self.registry.get('integration_connections','custom-demo')
  self.assertFalse(c['enabled']);self.assertEqual(c['kind'],'custom-harness')
  a=self.registry.wizard_add('user',c['id'],'example/model',confirmed=True)
  self.rt=self.registry.instances[c['id']];self.agent=a['id'];return a
 def turn(self,prompt='hello',seconds=30,purpose='question'):
  result=self.rt.submit('user',self.agent,prompt,True,purpose=purpose,session_scope='hub-project:demo')
  with self.h.tx():
   self.h.db.execute("UPDATE executions SET status='running',started=?,max_seconds=? WHERE id=?",(time.time(),seconds,result['id']))
   row=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(result['id'],)).fetchone())
   self.h.db.execute("UPDATE agents SET active=?,status='busy' WHERE id=?",(row['message_id'],self.agent))
  self.rt.execute(row)
  return dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(result['id'],)).fetchone())
 def test_discovery_never_launches_and_real_process_preserves_context(self):
  self.connect();one=self.turn();self.assertEqual(one['status'],'completed',one['result'])
  first=json.loads(one['result']);self.assertEqual(first['history'],0);self.assertIsNone(first['session'])
  two=self.turn('new input');self.assertEqual(two['status'],'completed',two['result']);last=json.loads(two['result']);self.assertEqual(last['history'],2);self.assertEqual(last['session'],'native-session')
  self.assertEqual(last['cwd'],str((self.h.directory/'adapter-workspaces/custom-demo').resolve()))
 def test_unknown_tool_is_rejected_and_reply_can_continue(self):
  self.manifest['capabilities']['tools']=True
  self.script("print(json.dumps({'type':'tool_call','id':'call-1','name':'not_authorized','arguments':{}}),flush=True)\nreply=json.loads(sys.stdin.readline())\nprint(json.dumps({'type':'result','status':'completed','session_id':'native-session','text':'denied' if 'error' in reply else 'BAD'}),flush=True)")
  self.connect();result=self.turn();self.assertEqual(result['status'],'completed',result['result']);self.assertEqual(result['result'],'denied')
 def test_authorized_tool_round_trip(self):
  self.manifest['capabilities']['tools']=True
  self.script("print(json.dumps({'type':'tool_call','id':'read-1','name':'read_file','arguments':{'path':'probe.txt'}}),flush=True)\nreply=json.loads(sys.stdin.readline())\nprint(json.dumps({'type':'result','status':'completed','session_id':'native-session','text':reply.get('result',str(reply))}),flush=True)")
  self.connect();(Path(self.rt.config()['cwd'])/'probe.txt').write_text('authorized tool evidence',encoding='utf-8')
  result=self.turn(purpose='task');self.assertEqual(result['status'],'completed',result['result']);self.assertEqual(result['result'],'authorized tool evidence')
 def test_stop_request_terminates_script(self):
  self.connect();(self.folder/'bridge.py').write_text('import time;time.sleep(20)',encoding='utf-8')
  def stop():
   with self.h.tx():self.h.db.execute("UPDATE executions SET stop_requested=1 WHERE agent=? AND status='running'",(self.agent,))
  timer=threading.Timer(.3,stop);timer.start()
  try:
   started=time.monotonic();result=self.turn(seconds=15);self.assertLess(time.monotonic()-started,5);self.assertEqual(result['status'],'interrupted')
  finally:timer.cancel();timer.join()
 def test_exit_zero_without_result_is_failure(self):
  self.script("print(json.dumps({'type':'text','text':'partial'}),flush=True)")
  self.connect();result=self.turn();self.assertEqual(result['status'],'failed');self.assertIn('result',result['result'])
 def test_empty_result_is_failure(self):
  self.script("print(json.dumps({'type':'result','status':'completed','text':''}),flush=True)")
  self.connect();self.assertEqual(self.turn()['status'],'failed')
 def test_timeout_kills_process_and_keeps_prior_context(self):
  self.connect();self.assertEqual(self.turn()['status'],'completed');self.script('time.sleep(20)')
  started=time.monotonic();result=self.turn(seconds=1);self.assertLess(time.monotonic()-started,7);self.assertEqual(result['status'],'failed');self.assertIn('超时',result['result'])
  self.assertEqual(len(json.loads(self.h.db.execute('SELECT body FROM custom_harness_context').fetchone()[0])),2)
 def test_not_reading_stdin_does_not_block_cancellation(self):
  self.connect();(self.folder/'bridge.py').write_text('import time;time.sleep(20)',encoding='utf-8')
  started=time.monotonic();result=self.turn(prompt='x'*55000,seconds=1);self.assertLess(time.monotonic()-started,7);self.assertEqual(result['status'],'failed')
 def test_broken_manifest_is_reported_not_executed(self):
  (self.folder/'adapter.json').write_text('{ broken',encoding='utf-8');found,errors=discover(self.h.directory);self.assertEqual(found,[]);self.assertEqual(len(errors),1)
 def test_json_array_manifest_is_an_error_not_a_host_crash(self):
  (self.folder/'adapter.json').write_text('[]',encoding='utf-8');found,errors=discover(self.h.directory);self.assertEqual(found,[]);self.assertTrue(errors)

 def test_changed_manifest_refuses_stale_execution(self):
  self.connect();(self.folder/'adapter.json').unlink();result=self.turn();self.assertEqual(result['status'],'failed');self.assertIn('未运行脚本',result['result'])
 def test_refresh_unchanged_manifest_does_not_write_db(self):
  self.registry.adapters('user');before=self.h.db.total_changes;self.registry.scan_adapters(force=True);self.assertEqual(self.h.db.total_changes,before)

class RuntimePolling(unittest.TestCase):
 def test_start_is_idempotent(self):
  runtime=CodexRuntime.__new__(CodexRuntime);runtime.hub=SimpleNamespace(lock=threading.RLock());runtime.stop_event=threading.Event();runtime.thread=None;runtime.loop=lambda:runtime.stop_event.wait(5)
  try:
   runtime.start();first=runtime.thread;runtime.start();runtime.start();self.assertIs(runtime.thread,first)
  finally:runtime.stop_event.set();runtime.thread.join(timeout=2)
