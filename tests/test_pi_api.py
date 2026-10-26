import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from hub.core import HubError
from hub.harness_adapters import builtin_catalog
from hub.module_config import schema,validate

class Pi(unittest.TestCase):
    def setUp(self):
        from test_integrations import RegistryTests
        self.fixture=RegistryTests();self.fixture.setUp();self.registry=self.fixture.registry;self.h=self.fixture.server.hub
        self.runtime=importlib.import_module('hub.builtin_adapters.pi-api.runtime')
    def tearDown(self):self.fixture.tearDown()

    def turn(self,rt,agent,prompt='read the file'):
        job=rt.submit('user',agent['id'],prompt,True,purpose='task',session_scope='hub-project:pi-test')
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone());rt.execute(run)
        return dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())

    def test_old_api_history_migrates_without_replaying_tools(self):
        old=[{'role':'user','content':'hello'},{'role':'assistant','content':None,'tool_calls':[{'id':'x','function':{'name':'read_file','arguments':'{"path":"a"}'}}]},{'role':'tool','tool_call_id':'x','content':'old result'},{'role':'assistant','content':'done'}]
        result=self.runtime.convert_history(old,'model')
        self.assertEqual(result[1]['content'][0]['type'],'toolCall');self.assertEqual(result[2]['toolCallId'],'x');self.assertEqual(result[2]['toolName'],'read_file');self.assertEqual(result[-1]['content'][0]['text'],'done')

    def test_declarative_schema_rejects_undeclared_and_invalid_fields(self):
        spec=schema(builtin_catalog()['pi-api'])
        for value in ({'unexpected':'x'},{'protocol':'invalid'},{'max_tokens':False},{'base_url':'https://key@host.test'},{'models':'a'}):
            with self.subTest(value=value),self.assertRaises(HubError):validate(spec,value)

    def test_generic_custom_module_can_declare_and_read_configuration(self):
        folder=self.h.directory/'adapters/custom/fields';folder.mkdir(parents=True)
        manifest={'version':1,'id':'fields','name':'Fields','protocol':'hub-module-v1','entrypoint':'adapter.py','efforts':['default'],
            'configuration':{'version':1,'fields':[{'name':'endpoint','type':'url','label':'地址'},{'name':'token','type':'secret','label':'密钥'}]}}
        (folder/'adapter.json').write_text(json.dumps(manifest),encoding='utf-8')
        (folder/'adapter.py').write_text("def execute(ctx,run):return ctx.user_configuration()['endpoint']",encoding='utf-8')
        self.registry.adapters('user')
        value=self.registry.module_configure('user','custom-fields',{'endpoint':'https://example.test','token':'private-fixture-value'})
        self.assertEqual(value['config']['endpoint'],'https://example.test');self.assertTrue(value['secrets']['token'])
        self.assertNotIn('private-fixture-value',json.dumps(value));self.assertNotIn('private-fixture-value',str(self.registry.rows('integration_connections')))
        with self.assertRaises(HubError):self.registry.module_configure('deepseek-1','custom-fields',{})

    def test_discovery_and_form_configuration_never_start_node(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('no subprocess during discovery')):
            self.registry.module_configure('user','pi-api-local')
            self.registry.snapshot()

    def test_real_pi_stream_tools_resume_and_failure_without_retries(self):
        calls=[];mode={'fail':False,'stop':False};owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(payload)
                if mode['stop']:
                    with owner.h.tx():owner.h.db.execute("UPDATE executions SET stop_requested=1 WHERE status='running'")
                    time.sleep(.5);self.close_connection=True;return
                if mode['fail']:
                    self.send_response(500);self.end_headers();self.wfile.write(b'fixture failed');return
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
                if len(calls)==1:
                    chunks=[{'role':'assistant','tool_calls':[{'index':0,'id':'read-1','type':'function','function':{'name':'read_file','arguments':'{"path":"probe.txt"}'}}]}];finish='tool_calls'
                else:chunks=[{'role':'assistant','content':'PI STREAM OK'}];finish='stop'
                for delta in chunks:
                    self.wfile.write(('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture-model','choices':[{'index':0,'delta':delta,'finish_reason':None}]})+'\n\n').encode())
                self.wfile.write(('data: '+json.dumps({'id':'fixture','choices':[{'index':0,'delta':{},'finish_reason':finish}],'usage':{'prompt_tokens':5,'completion_tokens':3,'total_tokens':8}})+'\n\ndata: [DONE]\n\n').encode());self.wfile.flush()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.dict(os.environ,{'PI_FIXTURE_KEY':'not-a-real-key'}):
                self.registry.module_configure('user','pi-api-local',{'base_url':f'http://127.0.0.1:{server.server_port}/v1','key_env':'PI_FIXTURE_KEY','models':['fixture-model']})
                connection=self.registry.get('integration_connections','pi-api-local');connection['cwd']=str(self.h.directory);self.registry.put('integration_connections',connection)
                self.registry.probe('user','pi-api-local');agent=self.registry.wizard_add('user','pi-api-local','fixture-model',confirmed=True)
                rt=self.registry.instances['pi-api-local'];(Path(rt.config()['cwd'])/'probe.txt').write_text('HOST TOOL VALUE',encoding='utf-8')
                first=self.turn(rt,agent);self.assertEqual(first['status'],'completed',first['result']);self.assertEqual(first['result'],'PI STREAM OK')
                self.assertTrue(calls[0]['stream']);self.assertTrue(any(m['role']=='tool' and 'HOST TOOL VALUE' in m['content'] for m in calls[1]['messages']))
                second=self.turn(rt,agent,'second request');self.assertEqual(second['status'],'completed',second['result'])
                self.assertTrue(any(m.get('role')=='assistant' and 'PI STREAM OK' in str(m.get('content')) for m in calls[-1]['messages']))
                self.assertFalse(rt.clients)
                mode['fail']=True;before=len(calls);failed=self.turn(rt,agent,'failure')
                self.assertEqual(failed['status'],'uncertain',failed['result']);self.assertEqual(len(calls),before+1)
                mode['fail']=False;mode['stop']=True
                stopped=self.turn(rt,agent,'stop this request');self.assertEqual(stopped['status'],'interrupted',stopped['result']);self.assertFalse(rt.clients)
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
