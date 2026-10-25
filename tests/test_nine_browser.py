import importlib.util,json,subprocess,tempfile,threading,re,unittest
from pathlib import Path
from hub.server import Server,Handler
import os,types
from browser_dom import run as browser_run
from hub.browser_render import executable
from hub.core import HubError
try: m=types.SimpleNamespace(EDGE=Path(executable()))
except HubError: m=types.SimpleNamespace(EDGE=Path('/nonexistent/hub-test-browser'))
DRIVER="""window.addEventListener('DOMContentLoaded',async()=>{const out=document.createElement('pre');out.id='result';document.body.append(out);try{const deadline=Date.now()+10000;while(!window.HubDesktop&&Date.now()<deadline)await new Promise(r=>setTimeout(r,25));if(!window.HubDesktop)throw Error('HubDesktop initialization timed out');document.getElementById('token').value='fixture';document.getElementById('loginForm').dispatchEvent(new Event('submit',{cancelable:true}));const H=window.HubDesktop;const readyDeadline=Date.now()+10000;while((H.view.agents.length!==9||!document.querySelector('#workflowAgents input[value=\"deepseek-1\"]'))&&Date.now()<readyDeadline)await new Promise(r=>setTimeout(r,25));if(H.view.agents.length!==9)throw Error('missing identities');if(!H.view.agents.every(a=>a.id.startsWith('deepseek-')&&a.provider==='deepseek'&&a.model==='DeepSeek Flash'))throw Error('wrong model route');if(H.view.managerStream.manager!=='deepseek-4')throw Error('wrong manager');if(document.querySelector('#workflowAgents input[value="deepseek-4"]'))throw Error('manager selectable as participant');if(!document.querySelector('#workflowAgents input[value="deepseek-1"]'))throw Error('former fixed manager filter still active');if(document.querySelectorAll('#agents .agent-box').length!==9)throw Error('missing cards');if(document.getElementById('codexPanel').hidden!==true)throw Error('legacy provider visible');if(document.getElementById('switchManagerDeepseekBtn').hidden!==true)throw Error('obsolete handoff visible');if(!document.getElementById('setupWizard').hidden)throw Error('unexpected guide');const e=document.getElementById('discussionReply');e.value='draft';await H.store.refresh(true);if(e.value!=='draft')throw Error('draft lost');H.store.stopPolling();out.textContent='PASS nine DeepSeek cards, routing, manager, no stale provider controls, draft retained';}catch(e){out.textContent='FAIL '+e.stack;}});"""
class Fixture(Handler):
 def do_GET(self):
  if self.path=='/driver.js':return self.respond(200,DRIVER,'text/javascript')
  if self.path=='/':return self.respond(200,(Path(__file__).parents[1]/'hub/static/index.html').read_text(encoding='utf8').replace('<head>','<head><script src="/driver.js" defer></script>'),'text/html')
  if self.path=='/api/state':return self.respond(200,{'all_deepseek':True,'agents':[{'id':f'deepseek-{i}','model':'DeepSeek Flash','status':'idle'} for i in range(1,10)],'real_agents':[f'deepseek-{i}' for i in range(1,10)],'tasks':[],'messages':[],'planning':[],'workflows':[{'id':'w','manager':'deepseek-4','status':'paused','report':'fixture'}],'project':{},'coordination':{},'codex':{'config':{'enabled':False}},'antigravity':{'config':{'enabled':False}},'deepseek':{'config':{'enabled':True,'engine':'harness'},'unlimited':True,'remaining_runs':None,'remaining_cents':None}})
  if self.path=='/health':return self.respond(200,{'ok':True})
  super().do_GET()
 def do_POST(self):self.respond(200,{'result':{}})
@unittest.skipUnless(m.EDGE.exists(),'Edge unavailable')
class Browser(unittest.TestCase):
 def test_nine(self):
  s=Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   with tempfile.TemporaryDirectory() as p:
    r=browser_run([str(m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=3000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print(result.group(1))
  finally:s.shutdown();s.server_close();t.join()
