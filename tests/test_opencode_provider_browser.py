import json
import re
import tempfile
import threading
import unittest
import test_nine_browser as base
from hub.harness_adapters import builtin_catalog

CHECK=r"""
await H.action('enable_provider_fixture',{});await H.store.refresh(true);
document.getElementById('openIntegrations').click();document.getElementById('newIntegrationAgent').click();
const select=document.getElementById('agentConnection');
if([...select.options].filter(o=>o.textContent.startsWith('OpenCode【')).length!==84)throw Error('not all 84 provider groups are selectable');
const waitUI=async fn=>{const end=Date.now()+4000;while(!fn()&&Date.now()<end)await new Promise(r=>setTimeout(r,20));if(!fn())throw Error('provider UI did not update');};
select.value='opencode-minimax-local';select.dispatchEvent(new Event('change'));
await waitUI(()=>document.getElementById('moduleField-variant')?.options.length===2);
const variant=document.getElementById('moduleField-variant');variant.value='v2';variant.dispatchEvent(new Event('change'));
document.getElementById('moduleField-api_key').value='browser-fixture-secret';document.getElementById('moduleField-api_key').dispatchEvent(new Event('input'));
document.getElementById('moduleField-models').value='mini-only';document.getElementById('moduleField-models').dispatchEvent(new Event('input'));
const next=document.getElementById('wizardNext');next.scrollIntoView({block:'nearest'});
if(next.getBoundingClientRect().bottom>innerHeight||next.getBoundingClientRect().top<0)throw Error('provider footer cannot be reached');
next.click();await waitUI(()=>!document.getElementById('agentWizardModelStep').hidden);
if(document.getElementById('moduleField-api_key').value!=='')throw Error('key remained visible after save');
const model=document.getElementById('agentModel');if(model.options.length!==1||!model.value.endsWith('/mini-only'))throw Error('models not scoped to provider selection');
document.getElementById('wizardBack').click();select.value='opencode-deepseek-local';select.dispatchEvent(new Event('change'));
await waitUI(()=>document.getElementById('moduleField-variant')?.options.length===1);
if(document.getElementById('moduleField-api_key').value!=='')throw Error('provider password leaked into another provider');
document.getElementById('wizardNext').scrollIntoView({block:'nearest'});document.getElementById('wizardNext').click();
await waitUI(()=>!document.getElementById('agentWizardModelStep').hidden);
if([...document.getElementById('agentModel').options].some(o=>o.value.includes('mini-only')))throw Error('models from previous provider leaked');

document.getElementById('wizardBack').click();select.value='pi-api-local';select.dispatchEvent(new Event('change'));
await waitUI(()=>document.getElementById('moduleField-preset'));
const preset=document.getElementById('moduleField-preset');preset.value='deepseek';preset.dispatchEvent(new Event('change'));
if(document.getElementById('moduleField-protocol').value!=='openai-completions'||document.getElementById('moduleField-base_url').value!=='https://api.deepseek.com/v1')throw Error('declarative option defaults failed');
for(const [name,value] of [['api_key','api-fixture-secret'],['models','my-model']]){const el=document.getElementById('moduleField-'+name);el.value=value;el.dispatchEvent(new Event('input'));}
document.getElementById('wizardNext').scrollIntoView({block:'nearest'});document.getElementById('wizardNext').click();
await waitUI(()=>!document.getElementById('agentWizardModelStep').hidden);
if(document.getElementById('moduleField-api_key').value!=='')throw Error('API password remained after save');
if(!document.getElementById('agentModel').value.endsWith('/my-model'))throw Error('API custom model not selectable');

"""


class Fixture(base.Fixture):
    def respond(self,status,body,kind='application/json'):
        if self.path=='/api/state' and self.server.enabled:
            connections=[]
            for spec in builtin_catalog().values():
                if spec.get('configuration',{}).get('id')!='opencode-provider-v1':continue
                ident=spec['id']+'-local'
                connections.append({'id':ident,'kind':spec['id'],'name':spec['name'],'installed':True,'enabled':False,'permission':'full','module_configuration':spec['configuration'],'models':self.server.models.get(ident,[])})
            spec=builtin_catalog()['pi-api'];connections.append({'id':'pi-api-local','kind':'pi-api','name':spec['name'],'installed':True,'enabled':False,'module_configuration':spec['configuration'],'models':self.server.models.get('pi-api-local',[])})
            body={**body,'integrations':{'connections':connections,'agents':[]}}
        return super().respond(status,body,kind)

    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));action=data.get('action');args=data.get('args',{})
        if action=='enable_provider_fixture':self.server.enabled=True
        value={}
        if action=='integration_module_config':
            ident=args['connection_id'];mini='minimax' in ident
            config=self.server.configs.get(ident,{'variant':'v1','base_url':'https://fixture.test/v1','key_env':'','models':[]})
            if 'config' in args:
                incoming=dict(args['config']);key=incoming.pop('api_key','');self.server.saved_keys[ident]=key
                config=incoming;self.server.configs[ident]=config
            rows=[{'id':ident+'/'+mid,'efforts':['default']} for mid in config.get('models') or (['mini-a','mini-b'] if mini else ['deepseek-only'])]
            self.server.models[ident]=rows
            value={'config':config,'variants':[{'id':'v1','name':'China','base_url':'https://cn.fixture.test/v1'}]+([{'id':'v2','name':'Global','base_url':'https://global.fixture.test/v1'}] if mini else []),'key_saved':ident in self.server.saved_keys,'key_env_present':False,'models':rows,'schema':builtin_catalog()[ident.removesuffix('-local')]['configuration'],'note':'fixture scoped configuration'}
        elif action=='integration_probe':value={'models':self.server.models.get(args['connection_id'],[])}
        elif action=='integration_model_options':value={'id':args['model'],'efforts':['default'],'source':'official_acp_config'}
        self.respond(200,{'result':value})


@unittest.skipUnless(base.m.EDGE.exists(),'Browser unavailable')
class Browser(unittest.TestCase):
    def test_provider_variant_credentials_and_model_filter_at_three_sizes(self):
        original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
        server=base.Server(('127.0.0.1',0),Fixture);server.enabled=False;server.models={};server.configs={};server.saved_keys={}
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            for size in ('1440,900','1024,600','600,800'):
                server.enabled=False;server.models={};server.configs={};server.saved_keys={}
                with self.subTest(size=size),tempfile.TemporaryDirectory() as profile:
                    result=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size='+size,'--user-data-dir='+profile,'--dump-dom','--virtual-time-budget=10000',f'http://127.0.0.1:{server.server_port}/'],capture_output=True,encoding='utf-8',errors='replace',timeout=40)
                    match=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(match)
                    self.assertTrue(match.group(1).startswith('PASS'),match.group(1));self.assertEqual(server.saved_keys['opencode-minimax-local'],'browser-fixture-secret')
        finally:server.shutdown();server.server_close();thread.join();base.DRIVER=original
