import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from module_fixture import implementation
from hub.core import HubError
from hub.harness_adapters import builtin_catalog

FAKE = r'''
import json,os,sys,time,subprocess
from pathlib import Path
a=sys.argv[1:]
mode=os.environ.get('TEST_CLAUDE_MODE','ok')
if a==['auth','status']:
 print(json.dumps({'loggedIn':mode!='login','authMethod':'claude.ai'}));sys.exit(1 if mode=='login' else 0)
def arg(key):return a[a.index(key)+1]
cfg=json.loads(Path(arg('--mcp-config')).read_text())
entry=cfg.get('mcpServers',{}).get('agent-message-hub')
names=json.loads(entry['env']['HUB_TOOL_ALLOWLIST']) if entry else []
session=arg('--resume') if '--resume' in a else arg('--session-id')
if mode=='wrong_session':session='00000000-0000-0000-0000-000000000000'
def emit(value):print(json.dumps(value),flush=True)
prompt=sys.stdin.read()
if mode=='hang':time.sleep(60)
if mode=='bad_json':print('NOT JSON');sys.exit(0)
if mode=='rejected':emit({'type':'result','subtype':'error_during_execution','is_error':True,'result':'Authentication failed '+os.environ.get('ANTHROPIC_API_KEY',''),'session_id':session});sys.exit(1)
tools=['mcp__agent-message-hub__'+n for n in names]
if mode=='missing_tools':tools=[]
init={'type':'system','subtype':'init','session_id':session,'cwd':os.getcwd(),'permissionMode':arg('--permission-mode'),'model':'claude-sonnet-test','tools':tools}
if mode=='wrong_permission':init['permissionMode']='bypassPermissions' if arg('--permission-mode')!='bypassPermissions' else 'default'
emit(init)
if mode=='no_result':sys.exit(0)
if mode=='mcp':
 env={**os.environ,**entry['env']}
 requests=[{'jsonrpc':'2.0','id':0,'method':'initialize'},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':1,'method':'tools/list'}]
 p=subprocess.run([entry['command'],*entry['args']],input=''.join(json.dumps(r)+'\n' for r in requests),capture_output=True,text=True,encoding='utf-8',env=env,timeout=10)
 answer=json.loads(p.stdout.strip().splitlines()[-1]);actual=[t['name'] for t in answer['result']['tools']]
 assert sorted(actual)==sorted(names),(actual,names,p.stderr)
emit({'type':'assistant','session_id':session,'isReplay':True,'message':{'id':'old','content':[{'type':'text','text':'OLD HISTORY'}]}})
emit({'type':'stream_event','session_id':session,'event':{'type':'content_block_delta','delta':{'type':'text_delta','text':'hello'}}})
emit({'type':'assistant','session_id':session,'message':{'id':'new','content':[{'type':'text','text':'hello'}]}})
text=json.dumps({'resumed':'--resume' in a,'session':session,'cwd':os.getcwd(),'args':a,'prompt':prompt,'tools':names})
emit({'type':'result','subtype':'success','is_error':False,'session_id':session,'result':'' if mode=='empty' else text,'usage':{'input_tokens':3}})
'''


class ClaudeModule(unittest.TestCase):
    def setUp(self):
        from test_integrations import RegistryTests
        self.f=RegistryTests();self.f.setUp();self.h=self.f.server.hub;self.registry=self.f.registry
        self.runtime=implementation(self.h,'claude-code')
        self.config=importlib.import_module(self.runtime.__package__+'.config')
        self.folder=Path(self.f.temp.name);self.script=self.folder/'fake-claude.py';self.script.write_text(FAKE,encoding='utf-8')
        self.config_dir=self.folder/'claude-settings';self.config_dir.mkdir()
        self.env=patch.dict(os.environ,{'CLAUDE_CONFIG_DIR':str(self.config_dir),'TEST_CLAUDE_MODE':'ok'},clear=False);self.env.start()
        self.command=patch('hub.integrations.command',side_effect=lambda argv:[sys.executable,str(self.script),*argv[1:]]);self.command.start()
        c=self.registry.save_connection('user',{'kind':'claude-code','name':'Claude test','cwd':str(self.folder),'permission':'full','executable':sys.executable,'enabled':False})
        self.connection=c;self.registry.probe('user',c['id'])
        self.agent=self.registry.wizard_add('user',c['id'],'sonnet',confirmed=True)
        self.rt=self.registry.instances[c['id']]

    def tearDown(self):
        self.command.stop();self.env.stop();self.f.tearDown()

    def turn(self,mode='ok',scope='hub-project:claude-test',purpose='task',max_seconds=None):
        os.environ['TEST_CLAUDE_MODE']=mode
        job=self.rt.submit('user',self.agent['id'],'test prompt',True,purpose=purpose,session_scope=scope)
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
        if max_seconds is not None:run['max_seconds']=max_seconds
        self.rt.execute(run)
        return dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())

    def test_builtin_discovery_and_login_checks_do_not_run_inference(self):
        self.assertIn('claude-code',builtin_catalog())
        self.assertEqual(self.config.inspect(self.connection)['state'],'ready')
        os.environ['TEST_CLAUDE_MODE']='login';self.assertEqual(self.config.inspect(self.connection)['state'],'login')
        self.assertFalse(self.h.db.execute('SELECT 1 FROM executions').fetchone())
        with patch.object(self.config,'executable',return_value=None):
            self.assertEqual(self.config.inspect(self.connection)['state'],'missing')
            with self.assertRaises(HubError):self.config.catalog(self.connection)

    def test_ccswitch_config_fallback_preserves_provider_and_secrets(self):
        legacy=self.config_dir/'claude.json';legacy.write_text(json.dumps({'model':'custom-model','env':{'ANTHROPIC_AUTH_TOKEN':'secret-test','ANTHROPIC_DEFAULT_SONNET_MODEL':'gateway-model'}}))
        before=legacy.read_bytes();result=self.config.catalog(self.connection)
        self.assertTrue({'sonnet','opus','haiku','custom-model','gateway-model'}.issubset({m['id'] for m in result['models']}))
        self.assertNotIn('secret-test',json.dumps(result));self.assertEqual(legacy.read_bytes(),before)
        current=self.config_dir/'settings.json';current.write_text('{"model":"preferred"}')
        self.assertEqual(self.config.settings_path(),current)
        current.write_text('INVALID')
        with self.assertRaises(HubError):self.config.catalog(self.connection)

    def test_execute_resume_project_isolation_and_transient_mcp_cleanup(self):
        first=self.turn('mcp');self.assertEqual(first['status'],'completed',first['result'])
        value=json.loads(first['result']);self.assertFalse(value['resumed']);self.assertIn('project_status',value['tools'])
        self.assertNotIn('OLD HISTORY',first['result'])
        self.assertFalse(list(self.folder.rglob('claude-mcp.json')))
        second=self.turn();self.assertEqual(second['status'],'completed',second['result'])
        self.assertTrue(json.loads(second['result'])['resumed']);self.assertEqual(second['thread_id'],first['thread_id'])
        third=self.turn(scope='hub-project:different');self.assertNotEqual(third['thread_id'],first['thread_id'])

    def test_discussion_removes_native_tools_and_does_not_bypass_permissions(self):
        row=self.turn(purpose='discussion');self.assertEqual(row['status'],'completed',row['result'])
        value=json.loads(row['result']);args=value['args']
        self.assertEqual(args[args.index('--tools')+1],'');self.assertEqual(args[args.index('--permission-mode')+1],'dontAsk')
        self.assertNotIn('project_assign',value['tools'])

    def test_rejected_or_missing_result_never_claims_success_and_preserves_session(self):
        self.turn()
        for mode in ('no_result','empty','wrong_session','wrong_permission','missing_tools','bad_json'):
            with self.subTest(mode=mode):
                row=self.turn(mode);self.assertNotEqual(row['status'],'completed',row['result'])
                self.assertTrue(self.rt.sessions.get(row))
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'secret-api-test-123'}):
            row=self.turn('rejected');self.assertEqual(row['status'],'failed');self.assertNotIn('secret-api-test-123',row['result'])

    def test_timeout_terminates_owned_process_without_retry(self):
        start=time.monotonic();row=self.turn('hang',max_seconds=.5)
        self.assertLess(time.monotonic()-start,8);self.assertNotEqual(row['status'],'completed')
        self.assertFalse(list(self.folder.rglob('claude-mcp.json')))
        self.assertTrue(self.rt.sessions.get(row))

    def test_setup_actions_use_module_hooks_and_require_user(self):
        self.assertEqual(self.registry.connection_setup('user',self.connection['id'])['state'],'ready')
        with patch('webbrowser.open') as opened:
            self.registry.connection_setup('user',self.connection['id'],'website')
            opened.assert_called_once_with('https://code.claude.com/docs/en/setup')
        with patch('hub.builtin_adapters._shared.setup.subprocess.Popen') as launched:
            self.registry.connection_setup('user',self.connection['id'],'login')
            self.assertEqual(launched.call_args.args[0][-2:],['auth','login'])
        with self.assertRaises(HubError):self.registry.connection_setup(self.agent['id'],self.connection['id'],'login')
        with self.assertRaises(HubError):self.registry.connection_setup('user',self.connection['id'],'other')

    def test_resume_uses_original_directory_after_workspace_move(self):
        first=self.turn();self.assertEqual(first['status'],'completed',first['result'])
        moved=self.folder/'new-workspace';moved.mkdir()
        with patch.object(self.rt,'submit',wraps=self.rt.submit):
            job=self.rt.submit('user',self.agent['id'],'next',True,purpose='task',session_scope='hub-project:claude-test')
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',cwd=?,started=? WHERE id=?",(str(moved),time.time(),job['id']))
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone());self.rt.execute(run)
        row=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
        self.assertEqual(row['status'],'completed',row['result']);value=json.loads(row['result'])
        self.assertEqual(Path(value['cwd']),self.folder);self.assertIn(str(moved.resolve()),value['args'])

    def test_user_stop_interrupts_owned_cli(self):
        result=[]
        thread=threading.Thread(target=lambda:result.append(self.turn('hang')));thread.start()
        deadline=time.monotonic()+5
        while not self.rt.clients and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue(self.rt.clients)
        run_id,client=next(iter(self.rt.clients.items()))
        with self.h.tx():self.h.db.execute('UPDATE executions SET stop_requested=1 WHERE id=?',(run_id,))
        thread.join(timeout=8);self.assertFalse(thread.is_alive())
        self.assertEqual(result[0]['status'],'interrupted');self.assertIsNotNone(client.proc.poll())
