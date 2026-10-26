import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from hub.core import HubError
from hub.harness_adapters import builtin_catalog
from hub.module_loader import load
from hub.builtin_adapters.opencode import provider

FAKE=r'''
import hashlib,json,os,sys,time,uuid
from pathlib import Path
sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8')
config=json.loads(os.environ.get('OPENCODE_CONFIG_CONTENT','{}'))
providers=config.get('enabled_providers') or ['original']
namespace=providers[0]
def emit(value):print(json.dumps(value),flush=True)
if 'models' in sys.argv:
 for mid in config.get('provider',{}).get(namespace,{}).get('models',{'original-model':{}}):print(namespace+'/'+mid)
 sys.exit(0)
db=Path(os.environ['OPENCODE_DB']) if os.environ.get('OPENCODE_DB') else Path(os.environ['TEST_OC_ROOT'])/'original.db'
sessions=db.with_suffix('.sessions.json');saved=json.loads(sessions.read_text()) if sessions.exists() else []
session=None;model=None;mode=None
for line in sys.stdin:
 r=json.loads(line);method=r.get('method');p=r.get('params',{});value={}
 if method=='initialize':value={'protocolVersion':1,'agentCapabilities':{'loadSession':True}}
 elif method=='session/new':
  session=str(uuid.uuid4());saved.append(session);sessions.parent.mkdir(parents=True,exist_ok=True);sessions.write_text(json.dumps(saved));value={'sessionId':session}
 elif method=='session/load':
  session=p['sessionId']
  if session not in saved:emit({'jsonrpc':'2.0','id':r['id'],'error':{'message':'SESSION NOT IN THIS DATABASE'}});continue
  value={'sessionId':session}
 elif method=='session/set_config_option':
  if p['configId']=='model':model=p['value']
  value={'configOptions':[{'id':p['configId'],'currentValue':p['value']}]}
 elif method=='session/set_mode':mode=p['modeId']
 elif method=='session/prompt':
  start=time.time();time.sleep(.6)
  secret=os.environ.get('HUB_PROVIDER_API_KEY','')
  if os.environ.get('TEST_OC_ERROR')=='1':emit({'jsonrpc':'2.0','id':r['id'],'error':{'message':'API rejected '+secret}});continue
  text=json.dumps({'provider':namespace,'key_hash':hashlib.sha256(secret.encode()).hexdigest(),'db':str(db),'session':session,'mode':mode,'model':model,'config':config,'start':start,'end':time.time()})
  emit({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':session,'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':text}}}})
  value={'stopReason':'end_turn'}
 elif method=='session/cancel':continue
 if 'id' in r:emit({'jsonrpc':'2.0','id':r['id'],'result':value})
'''


class Providers(unittest.TestCase):
    def setUp(self):
        from test_integrations import RegistryTests
        self.f=RegistryTests();self.f.setUp();self.registry=self.f.registry;self.h=self.f.server.hub
        self.root=Path(self.f.temp.name);self.script=self.root/'fake-opencode.py';self.script.write_text(FAKE,encoding='utf-8')
        self.environ=patch.dict(os.environ,{'TEST_OC_ROOT':str(self.root),'TEST_MINIMAX_KEY':'minimax-private-key','TEST_DEEPSEEK_KEY':'deepseek-private-key','OPENCODE_CONFIG_CONTENT':'{"original":true}'})
        self.environ.start();self.command=patch('hub.integrations.command',side_effect=lambda args:[sys.executable,str(self.script),*args[1:]]);self.command.start()

    def tearDown(self):self.command.stop();self.environ.stop();self.f.tearDown()

    def connection(self,kind):
        c=self.registry.save_connection('user',{'kind':kind,'name':kind,'cwd':str(self.root),'executable':sys.executable,'permission':'full','enabled':False})
        return c

    def configure(self,c,env='TEST_MINIMAX_KEY',**extra):
        return self.registry.module_configure('user',c['id'],{'key_env':env,**extra})

    def connect(self,kind,env):
        c=self.connection(kind)
        if kind!='opencode':self.configure(c,env)
        c=self.registry.probe('user',c['id'])
        model=c['models'][0]['id'] if c['models'] else 'original/original-model'
        a=self.registry.wizard_add('user',c['id'],model,confirmed=True)
        return c,a,self.registry.instances[c['id']]

    def turn(self,a,rt):
        job=rt.submit('user',a['id'],'test',True,purpose='task',session_scope='hub-project:concurrent-test')
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
        with self.h.lock:run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
        rt.execute(run)
        with self.h.lock:return dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())

    def test_87_groups_generate_84_real_modules_and_all_variants_are_valid(self):
        report=json.loads((Path(__file__).parents[1]/'docs/OPENCODE_PROVIDERS.json').read_text(encoding='utf-8'))
        self.assertEqual(report['total'],87);self.assertEqual(report['generated'],84)
        supported=[x for x in builtin_catalog().values() if x.get('configuration',{}).get('id')=='opencode-provider-v1'];self.assertEqual(len(supported),84)
        variants=0
        for spec in supported:
            c=next(c for c in self.registry.rows('integration_connections') if c['kind']==spec['id'])
            module,_=load(self.h.directory/'adapters/builtin'/spec['id']);self.assertTrue(callable(module.execute))
            for v in spec['settings']['opencode_preset']['variants']:
                variants+=1;rows=provider.model_rows(c,spec,{'variant':v['id']})
                self.assertTrue(rows);self.assertTrue(all('/' in row['id'] for row in rows));self.assertEqual(len(rows),len(v['config']['models']))
        self.assertEqual(variants,104)

    def test_independent_presets_and_original_execute_concurrently_and_resume(self):
        values=[self.connect('opencode-minimax','TEST_MINIMAX_KEY'),self.connect('opencode-deepseek','TEST_DEEPSEEK_KEY'),self.connect('opencode','')]
        results=[None]*3
        threads=[threading.Thread(target=lambda i=i:results.__setitem__(i,self.turn(values[i][1],values[i][2]))) for i in range(3)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=15);self.assertFalse(thread.is_alive())
        for row in results:self.assertEqual(row['status'],'completed',row['result'])
        data=[json.loads(r['result']) for r in results]
        self.assertLess(max(d['start'] for d in data),min(d['end'] for d in data))
        self.assertEqual(len({d['db'] for d in data}),3);self.assertEqual(len({d['session'] for d in data}),3)
        self.assertEqual(data[0]['key_hash'],hashlib.sha256(b'minimax-private-key').hexdigest())
        self.assertEqual(data[1]['key_hash'],hashlib.sha256(b'deepseek-private-key').hexdigest())
        self.assertEqual(data[2]['config'],{'original':True});self.assertEqual(os.environ['OPENCODE_CONFIG_CONTENT'],'{"original":true}')
        self.assertEqual(len(data[0]['config']['provider']),1);self.assertEqual(len(data[1]['config']['provider']),1)
        second=self.turn(values[0][1],values[0][2]);self.assertEqual(second['status'],'completed',second['result']);self.assertEqual(second['thread_id'],results[0]['thread_id'])

    def test_only_selected_variant_models_are_visible_and_env_is_scoped(self):
        c=self.connection('opencode-minimax');before=dict(os.environ)
        result=self.configure(c,variant='v2',models=['my-private-model'])
        self.assertEqual(len(result['models']),1);self.assertTrue(result['models'][0]['id'].endswith('/my-private-model'))
        module,manifest=load(self.h.directory/'adapters/builtin/opencode-minimax')
        env=provider.environment(self.registry,c,manifest);config=json.loads(env['OPENCODE_CONFIG_CONTENT'])
        self.assertEqual(len(config['provider']),1);self.assertEqual(env['OPENCODE_DISABLE_PROJECT_CONFIG'],'true')
        self.assertNotIn('minimax-private-key',env['OPENCODE_CONFIG_CONTENT']);self.assertEqual(dict(os.environ),before)
        opts=next(iter(config['provider'].values()))['options'];self.assertEqual(opts['baseURL'],result['config']['base_url'])

    @unittest.skipUnless(os.name=='nt','Windows DPAPI test')
    def test_saved_keys_are_encrypted_and_not_returned_or_stored_in_database(self):
        c=self.connection('opencode-minimax');secret='private-dpapi-secret-123456'
        result=self.configure(c,env='',api_key=secret);self.assertTrue(result['key_saved']);self.assertNotIn(secret,json.dumps(result))
        self.assertNotIn(secret,provider.secret_path(self.registry,c).read_bytes().decode('latin1'))
        module,spec=load(self.h.directory/'adapters/builtin/opencode-minimax');self.assertEqual(provider.environment(self.registry,c,spec)['HUB_PROVIDER_API_KEY'],secret)
        self.assertNotIn(secret,'\n'.join(self.h.db.iterdump()))

    def test_missing_keys_and_bad_models_fail_before_inference(self):
        c=self.connection('opencode-deepseek');self.configure(c,env='MISSING_OPENCODE_TEST_KEY')
        module,spec=load(self.h.directory/'adapters/builtin/opencode-deepseek')
        with self.assertRaises(HubError):provider.environment(self.registry,c,spec)
        self.assertEqual(module.setup_status(self.registry,c)['state'],'login')
        with self.assertRaises(HubError):self.registry.module_configure('deepseek-1',c['id'])
        with self.assertRaises(HubError):self.configure(c,models=['../invalid?'])
        with self.assertRaises(HubError):self.configure(c,base_url='https://user:password@example.com')
        self.assertFalse(self.h.db.execute('SELECT 1 FROM executions').fetchone())

    def test_provider_key_is_redacted_from_acp_errors(self):
        c,a,rt=self.connect('opencode-minimax','TEST_MINIMAX_KEY')
        with patch.dict(os.environ,{'TEST_OC_ERROR':'1'}):row=self.turn(a,rt)
        self.assertNotEqual(row['status'],'completed');self.assertNotIn('minimax-private-key',row['result']);self.assertIn('API rejected',row['result'])

    def test_snapshot_resolves_shared_launcher_once_not_84_times(self):
        with patch('hub.integrations.locate',return_value=sys.executable) as locate:
            snapshot=self.registry.snapshot()
            calls=[c for c in locate.call_args_list if c.args[0]=='opencode' or c.args[0].startswith('opencode-')]
            self.assertEqual(len(calls),1)
            self.assertEqual(sum((c.get('module_configuration') or {}).get('id')=='opencode-provider-v1' for c in snapshot['connections']),84)

    def test_copied_custom_module_uses_same_configuration_and_execution(self):
        source=self.h.directory/'adapters/builtin/opencode-minimax';target=self.h.directory/'adapters/custom/my-minimax'
        shutil.copytree(source,target)
        path=target/'adapter.json';manifest=json.loads(path.read_text(encoding='utf-8'));manifest['id']='my-minimax';manifest['name']='My MiniMax';manifest['settings']['executable']=sys.executable
        path.write_text(json.dumps(manifest),encoding='utf-8');self.registry.adapters('user')
        c=self.registry.get('integration_connections','custom-my-minimax');self.configure(c)
        c=self.registry.probe('user',c['id']);a=self.registry.wizard_add('user',c['id'],c['models'][0]['id'],confirmed=True)
        row=self.turn(a,self.registry.instances[c['id']]);self.assertEqual(row['status'],'completed',row['result'])
