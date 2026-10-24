import unittest,subprocess,tempfile,threading,re,json
import test_nine_browser as base

class Fixture(base.Fixture):
 count=12;requests=[];adapter_kind="opencode";adapter_errors=[]
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   ids=['deepseek-4']+['agent-test'+str(i) for i in range(self.count-1)]
   profiles=[{'id':a,'name':'Gemini '+str(i),'connection_id':'google','model':'google/gemini-test','effort':'default','role':'工程师','enabled':True} for i,a in enumerate(ids)]
   body['agents']=[{'id':a['id'],'model':a['model'],'role':a['role'],'status':'idle','profile':a} for a in profiles]
   body.update(real_agents=ids,integrations={'agents':profiles,'connections':[{'id':'google','name':'OpenCode Google' if self.adapter_kind=='opencode' else '自定义示例','kind':self.adapter_kind,'adapter':{'capabilities':{'tools':False,'resume':False,'streaming':True}},'enabled':True,'installed':True,'verification':'未验证真实调用','models':[{'id':'google/gemini-test','efforts':['default','high']}],'effort_options':['default','high'],'quota':{'remaining':None,'source':'unknown'}}],'kinds':[{'id':'opencode','name':'OpenCode','efforts':['default','high']} ]})
  return super().respond(status,body,kind)
 def do_POST(self):
  value=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));self.requests.append(value)
  if value['action']=='integration_adapters':return self.respond(200,{'result':{'directory':'C:/fixture/adapters/custom','errors':self.adapter_errors}})
  self.respond(200,{'result':{'id':'new'}})

DRIVER=r"""window.addEventListener('DOMContentLoaded',async()=>{
const out=document.createElement('pre');out.id='result';document.body.append(out);
try{
document.getElementById('token').value='fixture';document.getElementById('loginForm').dispatchEvent(new Event('submit',{cancelable:true}));
const wait=()=>new Promise(r=>setTimeout(r,150));await wait();await wait();await wait();
const H=window.HubDesktop,count=H.view.rawSnapshot.integrations.agents.length;
if(H.view.agents.length!==count||document.querySelectorAll('#agents .agent-box').length!==count)throw Error('dynamic cards lost');
if(document.querySelectorAll('#workflowAgents input').length!==count-1)throw Error('dispatch roster still fixed');
if(document.getElementById('recipient').options.length!==count+1)throw Error('message recipients still fixed');
const manage=document.getElementById('openIntegrations');if(!manage.closest('.status-grid-header')||manage.closest('#activityRail'))throw Error('manage button not on panel header');
document.getElementById('viewModeStatusRadio').checked=true;await wait();
const grid=document.getElementById('agentsGrid'),cards=document.getElementById('agents'),gr=grid.getBoundingClientRect(),cr=cards.getBoundingClientRect();
if(count===9&&innerWidth>=1400){const x=(cr.left-gr.left)/gr.width,y=(cr.top-gr.top)/gr.height;if(x<.15||x>.28||y<.14||y>.3)throw Error('nine cards need surrounding whitespace: '+JSON.stringify({x,y,grid:[gr.width,gr.height],cards:[cr.width,cr.height]}));}
if(count>20&&grid.scrollHeight<=grid.clientHeight)throw Error('many agents have no scroll path');
const card=document.querySelector('#agents .agent-box'),beforeHeight=card.getBoundingClientRect().height;
card.querySelector('.agent-details-toggle:not([data-test-agent])').click();await wait();const detail=document.getElementById('agentDetailsDialog');if(!detail.open||detail.getBoundingClientRect().bottom>innerHeight)throw Error('details dialog clipped '+JSON.stringify({open:detail.open,box:detail.getBoundingClientRect().toJSON(),viewport:innerHeight}));
if(card.getBoundingClientRect().height!==beforeHeight)throw Error('details expanded card');
document.getElementById('closeAgentDetails').click();await wait();
manage.click();const dialog=document.getElementById('integrationsDialog');if(dialog.hidden)throw Error('manager did not open');
if(document.querySelectorAll('#integrationAgentList .agent-manager-row').length!==count)throw Error('management list incomplete');
if(!document.querySelector('.agent-box[data-agent="deepseek-4"]').classList.contains('is-project-manager'))throw Error('manager highlight missing');
if(document.querySelector('#projectManagerSelect').options.length!==document.querySelectorAll("#agents .agent-box").length)throw Error('manager choices incomplete');
if(document.querySelector('[data-remove-agent="deepseek-4"]').disabled!==true)throw Error('manager can be accidentally removed');
if(document.getElementById('connectionKind')||document.getElementById('newIntegrationConnection'))throw Error('manual provider form remains');
document.querySelector('[data-remove-agent="agent-test0"]').click();await wait();
document.getElementById('newIntegrationAgent').click();if(document.getElementById('agentWizardProviderStep').hidden)throw Error('provider step missing');
document.getElementById('wizardNext').click();await wait();if(document.getElementById('agentWizardModelStep').hidden)throw Error('model step missing');
if(document.getElementById('agentModel').tagName!=='SELECT')throw Error('model must be a picker');
if(document.getElementById('agentName').value!=='gemini-test 1')throw Error('default numbered model name missing');
if(document.getElementById('wizardEnableConnection').checked)throw Error('permission preselected');
document.getElementById('agentName').value='My Gemini duplicate';document.getElementById('agentName').dispatchEvent(new Event('input'));
await H.store.refresh(true);if(document.getElementById('agentName').value!=='My Gemini duplicate')throw Error('poll overwrote name');
document.getElementById('wizardBack').click();document.getElementById('wizardNext').click();await wait();if(document.getElementById('agentName').value!=='My Gemini duplicate')throw Error('back/next lost name');
document.getElementById('saveIntegrationAgent').click();await wait();if(document.getElementById('agentManagerListStep').hidden)throw Error('add did not return to list');
if(dialog.getBoundingClientRect().bottom>innerHeight||getComputedStyle(document.querySelector('.agent-manager-content')).overflowY!=='auto')throw Error('manager lacks bounded scroll area');
document.getElementById('closeIntegrations').click();if(!dialog.hidden)throw Error('close failed');
H.store.stopPolling();out.textContent='PASS '+count+' compact cards, whitespace, details, deletion, two-step wizard, model naming and preserved draft';
}catch(e){out.textContent='FAIL '+e.stack;}});"""

@unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
class IntegrationsBrowser(unittest.TestCase):
 def test_custom_harness_appears_in_wizard(self):
  from unittest.mock import patch
  with patch.object(Fixture,'adapter_kind','custom-harness'):
   original=base.DRIVER;base.DRIVER=DRIVER;Fixture.count=3;Fixture.requests=[]
   server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
   try:
    with tempfile.TemporaryDirectory() as folder:
     result=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size=1024,700',f'--user-data-dir={folder}','--dump-dom','--virtual-time-budget=5000',f'http://127.0.0.1:{server.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
     found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(found);self.assertTrue(found.group(1).startswith('PASS'),found.group(1))
     self.assertEqual(len([r for r in Fixture.requests if r['action']=='integration_wizard_add']),1)
   finally:server.shutdown();server.server_close();thread.join();base.DRIVER=original

 def test_more_and_less_than_nine_and_editor_layout(self):
  original=base.DRIVER;base.DRIVER=DRIVER
  s=base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   for count,size in [(9,'1440,900'),(12,'1440,900'),(36,'1440,900'),(3,'1024,600'),(9,'1024,600'),(12,'600,800')]:
    Fixture.count=count;Fixture.requests=[]
    with self.subTest(count=count,size=size),tempfile.TemporaryDirectory() as p:
     r=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--window-size={size}',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=5000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
     result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1))
     saves=[x for x in Fixture.requests if x['action']=='integration_wizard_add'];self.assertEqual(len(saves),1);self.assertEqual(saves[0]['args']['model'],'google/gemini-test');self.assertEqual(saves[0]['args']['name'],'My Gemini duplicate');self.assertTrue(any(x['action']=='integration_agent_archive' for x in Fixture.requests));print(result.group(1))
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
 def test_wizard_draft_survives_reload_without_retaining_consent(self):
  driver=r"""window.addEventListener('DOMContentLoaded',async()=>{const out=document.createElement('pre');out.id='result';document.body.append(out);try{
  document.getElementById('token').value='fixture';document.getElementById('loginForm').dispatchEvent(new Event('submit',{cancelable:true}));const wait=()=>new Promise(r=>setTimeout(r,180));await wait();await wait();await wait();
  if(!sessionStorage.getItem('wizard-reloaded')){document.getElementById('openIntegrations').click();document.getElementById('newIntegrationAgent').click();document.getElementById('wizardNext').click();await wait();document.getElementById('agentName').value='KEEP CUSTOM NAME';document.getElementById('agentName').dispatchEvent(new Event('input'));document.getElementById('wizardEnableConnection').checked=true;sessionStorage.setItem('wizard-reloaded','yes');location.reload();return;}
  if(document.getElementById('integrationsDialog').hidden||document.getElementById('agentWizardModelStep').hidden)throw Error('wizard not restored');if(document.getElementById('agentName').value!=='KEEP CUSTOM NAME')throw Error('wizard draft lost');if(document.getElementById('wizardEnableConnection').checked)throw Error('consent restored without new confirmation');window.HubDesktop.store.stopPolling();out.textContent='PASS wizard step/model/name restored, consent remains unchecked';}catch(e){out.textContent='FAIL '+e.stack;}});"""
  original=base.DRIVER;base.DRIVER=driver;Fixture.count=9
  s=base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   with tempfile.TemporaryDirectory() as p:
    r=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size=1440,900',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=6000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print(result.group(1))
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original

 def test_adapter_directory_notice_severity(self):
  from browser_dom import run
  driver=r"""window.addEventListener('DOMContentLoaded',async()=>{const out=document.createElement('pre');out.id='result';document.body.append(out);try{
   document.getElementById('token').value='fixture';document.getElementById('loginForm').dispatchEvent(new Event('submit',{cancelable:true}));const wait=()=>new Promise(r=>setTimeout(r,180));await wait();await wait();await wait();
   document.getElementById('openIntegrations').click();document.getElementById('newIntegrationAgent').click();await wait();
   const notice=document.getElementById('notice');
   for(const id of ['openHarnessAdapters','refreshHarnessAdapters']){document.getElementById(id).click();await wait();await wait();if(notice.classList.contains('notice-error')!==EXPECTED_ERROR)throw Error('wrong notice severity '+id+' '+notice.outerHTML);if(notice.getAttribute('role')!==(EXPECTED_ERROR?'alert':'status'))throw Error('wrong accessibility severity');}
   window.HubDesktop.store.stopPolling();out.textContent='PASS directory and refresh notice severity';}catch(e){out.textContent='FAIL '+e.stack;}});"""
  original=base.DRIVER
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   for errors in [[],[{'file':'bad/adapter.json','error':'invalid configuration'}]]:
    Fixture.adapter_errors=errors;base.DRIVER=driver.replace('EXPECTED_ERROR','true' if errors else 'false')
    with tempfile.TemporaryDirectory() as profile:
     result=run([str(base.m.EDGE),'--window-size=1440,900',f'--user-data-dir={profile}',f'http://127.0.0.1:{server.server_port}/'],timeout=30)
     verdict=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(verdict);self.assertTrue(verdict.group(1).startswith('PASS'),verdict.group(1))
  finally:Fixture.adapter_errors=[];base.DRIVER=original;server.shutdown();server.server_close();thread.join()
