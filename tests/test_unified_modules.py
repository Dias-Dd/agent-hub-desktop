import ast,importlib,json,os,shutil,tempfile,threading,time,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from hub.harness_adapters import prepare_layout
from hub.module_loader import load

class UnifiedModules(unittest.TestCase):
 def setUp(self):
  from test_integrations import RegistryTests
  self.f=RegistryTests();self.f.setUp();self.registry=self.f.registry;self.h=self.f.server.hub
 def tearDown(self):self.f.tearDown()
 def module(self,name,script,models=None):
  folder=self.h.directory/'adapters/custom'/name;folder.mkdir(parents=True)
  data={'version':1,'id':name,'name':name,'protocol':'hub-module-v1','entrypoint':'adapter.py','models':models or [{'id':'local-model','efforts':['default']}],'capabilities':{'tools':True,'resume':True,'streaming':True}}
  (folder/'adapter.json').write_text(json.dumps(data),encoding='utf-8');(folder/'adapter.py').write_text(script,encoding='utf-8');self.registry.adapters('user');return folder
 def connect(self,name):
  self.registry.probe('user','custom-'+name)
  a=self.registry.wizard_add('user','custom-'+name,'local-model',confirmed=True)
  return a,self.registry.instances['custom-'+name]
 def turn(self,rt,agent,text='hello',purpose='task'):
  job=rt.submit('user',agent['id'],text,True,purpose=purpose,session_scope='hub-project:module-test')
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
  run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone());rt.execute(run)
  return dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
 def test_discovery_does_not_import_python_and_sdk_preserves_history_session(self):
  folder=self.module('python-demo',"def execute(ctx,run):\n r=ctx.request(run)\n return {'status':'completed','text':str(len(r['history'])),'session_id':r['session_id'] or 'python-session'}\n")
  marker=folder/'import-marker';s=(folder/'adapter.py').read_text(encoding='utf-8');(folder/'adapter.py').write_text("from pathlib import Path\nPath(__file__).with_name('import-marker').write_text('executed')\n"+s)
  self.registry.adapters('user');self.assertFalse(marker.exists())
  agent,rt=self.connect('python-demo');self.assertTrue(marker.exists()) # explicit probe may import the module
  first=self.turn(rt,agent);self.assertEqual(first['status'],'completed',first['result']);self.assertEqual(first['result'],'0')
  second=self.turn(rt,agent);self.assertEqual(second['result'],'2');self.assertEqual(rt.sessions.get(second)['session_id'],'python-session')
 def test_none_without_terminal_result_is_failed(self):
  self.module('empty','def execute(ctx,run): pass');a,rt=self.connect('empty');row=self.turn(rt,a);self.assertEqual(row['status'],'failed');self.assertIn('未确认结果',row['result'])
 def test_relative_import_and_reload_do_not_use_stale_bytecode(self):
  folder=self.module('imports','from .helper import value\ndef execute(ctx,run): return value')
  (folder/'helper.py').write_text("value='A'",encoding='utf-8');a,rt=self.connect('imports');self.assertEqual(self.turn(rt,a)['result'],'A')
  (folder/'helper.py').write_text("value='B'",encoding='utf-8');self.assertEqual(self.turn(rt,a)['result'],'B')
 def test_builtin_copy_runs_real_api_loop_tool_and_history_without_host_executor(self):
  calls=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def send(self,data):
    payload=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
   def do_GET(self):self.send({'data':[{'id':'local-model'}]})
   def do_POST(self):
    payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(payload)
    if len(calls)==1:message={'role':'assistant','content':None,'tool_calls':[{'id':'read-1','type':'function','function':{'name':'read_file','arguments':json.dumps({'path':'probe.txt'})}}]}
    else:message={'role':'assistant','content':'LOCAL MODULE OK'}
    self.send({'choices':[{'message':message}],'usage':{'total_tokens':1}})
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   source=self.h.directory/'adapters/builtin/openrouter-api';folder=self.h.directory/'adapters/custom/copied-api';shutil.copytree(source,folder)
   manifest=json.loads((folder/'adapter.json').read_text(encoding='utf-8'));manifest.update(id='copied-api',name='Copied API',models=[{'id':'local-model','efforts':['default']}]);manifest['api']={'base_url':'http://127.0.0.1:'+str(server.server_port),'key_environment':'HUB_MODULE_FIXTURE_KEY'};(folder/'adapter.json').write_text(json.dumps(manifest),encoding='utf-8')
   self.registry.adapters('user')
   with patch.dict(os.environ,{'HUB_MODULE_FIXTURE_KEY':'not-a-real-key'}):
    a,rt=self.connect('copied-api');(Path(rt.config()['cwd'])/'probe.txt').write_text('TOOL RESULT FROM HOST',encoding='utf-8')
    one=self.turn(rt,a);self.assertEqual(one['status'],'completed',one['result']);self.assertEqual(one['result'],'LOCAL MODULE OK')
    self.assertTrue(any(m.get('role')=='tool' and 'TOOL RESULT FROM HOST' in m.get('content','') for m in calls[1]['messages']))
    two=self.turn(rt,a,'second request');self.assertEqual(two['status'],'completed',two['result'])
    self.assertTrue(any(m.get('content')=='LOCAL MODULE OK' for m in calls[-1]['messages']))
    self.assertEqual(calls[-1]['messages'][-1]['content'],'second request')
   self.assertTrue(load(folder)[0].__file__.startswith(str(folder)))
  finally:server.shutdown();server.server_close();thread.join()
 def test_old_application_files_have_no_provider_implementation(self):
  root=Path(__file__).parents[1]
  for name in ['codex_runtime','deepseek_runtime','deepseek_harness','antigravity','workbuddy_catalog','antigravity_evidence','print_turn']:
   tree=ast.parse((root/'hub'/(name+'.py')).read_text(encoding='utf-8'));self.assertFalse(any(isinstance(n,(ast.ClassDef,ast.FunctionDef)) for n in tree.body),name)

 def test_native_codex_module_keeps_session_and_authorized_model(self):
  from test_codex_runtime import FakeAppServer
  c=self.f.connection('codex',True)
  a=self.registry.save_agent('user',{'name':'Module Codex','connection_id':c['id'],'model':'gpt-test','effort':'medium','role':'工程师','enabled':True})
  rt=self.registry.instances[c['id']];rt.factory=FakeAppServer;FakeAppServer.instances=[]
  first=self.turn(rt,a,purpose='question');self.assertEqual(first['status'],'completed',first['result'])
  second=self.turn(rt,a,'next',purpose='question');self.assertEqual(second['status'],'completed',second['result'])
  methods=[name for client in FakeAppServer.instances for name,params in client.calls]
  self.assertIn('thread/start',methods);self.assertIn('thread/resume',methods)
 def test_native_antigravity_module_keeps_stream_and_quota_checks(self):
  from test_antigravity import FakeStream,FakeProbe
  c=self.f.connection('antigravity',True)
  a=self.registry.save_agent('user',{'name':'Module Google','connection_id':c['id'],'model':'gemini-3.8-flash-medium','effort':'medium','role':'工程师','enabled':True})
  rt=self.registry.instances[c['id']];rt.stream_factory=FakeStream;rt.probe=FakeProbe()
  row=self.turn(rt,a,purpose='task');self.assertEqual(row['status'],'completed',row['result']);self.assertIn('Created files',row['result'])
 def test_python_module_cooperates_with_stop(self):
  self.module('stop','import time\ndef execute(ctx,run):\n while True:\n  ctx.guard(run)\n  time.sleep(.02)')
  a,rt=self.connect('stop')
  def stop():
   with self.h.tx():self.h.db.execute("UPDATE executions SET stop_requested=1 WHERE agent=?",(a['id'],))
  timer=threading.Timer(.15,stop);timer.start()
  try:row=self.turn(rt,a);self.assertEqual(row['status'],'interrupted',row['result'])
  finally:timer.cancel();timer.join()
 def test_shared_sdk_rejects_readonly_write(self):
  self.module('readonly',"def execute(ctx,run): return str(ctx.tool(run,'write_file',{'path':'must-not-exist','content':'bad'},{'write_file'}))")
  a,rt=self.connect('readonly');row=self.turn(rt,a,purpose='question');self.assertEqual(row['status'],'failed');self.assertFalse((Path(rt.config()['cwd'])/'must-not-exist').exists())

 def test_probed_models_survive_metadata_only_refresh(self):
  self.module('catalog',"def execute(ctx,run): return 'unused'\ndef probe(registry,connection): return {'models':[{'id':'server-model','efforts':['default']}]}" )
  self.registry.probe('user','custom-catalog');self.registry.adapters('user')
  self.assertEqual(self.registry.get('integration_connections','custom-catalog')['models'][0]['id'],'server-model')

 def test_business_instructions_are_host_owned(self):
  root=Path(__file__).parents[1]
  phrases=['你是当前项目经理','project_assign 派工并给','用 Hub MCP report_result 向经理','WAIT_POLICY','DELEGATION_POLICY']
  for file in (root/'hub/builtin_adapters').rglob('*.py'):
   source=file.read_text(encoding='utf-8')
   for phrase in phrases:self.assertNotIn(phrase,source,str(file))
  source=(root/'hub/execution_policy.py').read_text(encoding='utf-8')
  for phrase in phrases:self.assertIn(phrase,source)
