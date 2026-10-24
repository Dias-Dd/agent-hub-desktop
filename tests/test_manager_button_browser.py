import unittest,subprocess,tempfile,re,threading,json
import test_nine_browser as base
class Fixture(base.Fixture):
 busy=False;messages=[];requests=[]
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   body['projects']=[{'id':'p','name':'Current project'}];body['selected_project']='p';body['project']={'progress':20,'note':'Long project progress description. '*2000}
   body['planning']=[{'id':'p-session','project_id':'p','state':'executing','revision':1,'history':[],'workflow_id':'w'}]
   body['messages']=self.messages
   body['deepseek']['runs']=[{'id':'r','agent':'deepseek-4','status':'running'}] if self.busy else []
  super().respond(status,body,kind)
 def do_POST(self):
  d=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));self.requests.append(d)
  if d['action']=='manager_message':
   ident='message-'+str(len(self.messages));self.messages.append({'id':ident,'sender':'user','recipient':'deepseek-4','body':d['args']['body'],'status':'pending','mode':'queue','project_id':'p','created':1});return self.respond(200,{'result':{'message_ids':[ident],'queued':True}})
  if d['action']=='manager_interrupt':return self.respond(200,{'result':{'interrupt_requested':True,'note':'Waiting for cancellation'}})
  if d['action']=='fixture_busy':Fixture.busy=d['args']['value']
  self.respond(200,{'result':{}})
CHECK=r"""
const wait=()=>new Promise(r=>setTimeout(r,120));
const button=document.getElementById('discussionSend'),input=document.getElementById('discussionReply');
const type=t=>{input.value=t;input.dispatchEvent(new Event('input',{bubbles:true}));};
type('');if(!button.disabled||button.dataset.mode!=='send'||button.textContent.trim())throw Error('idle empty send is not disabled icon-only');
type('hello');if(button.disabled||button.dataset.mode!=='send')throw Error('idle typed input did not enable send');
await H.client.postAction('fixture_busy',{value:true});await H.store.refresh(true);
if(button.dataset.mode!=='queue'||!button.title.includes('排队'))throw Error('busy button not queue');
button.click();await wait();if(input.value||button.disabled||button.dataset.mode!=='interrupt'||!button.title.includes('中断'))throw Error('queued empty input did not arm interrupt');
type('second message');if(button.dataset.mode!=='queue')throw Error('more text should queue');button.click();await wait();
button.click();await wait();
if(document.querySelectorAll('#agentMiniStates .agent-mini-row').length!==9)throw Error('mini statuses missing');
for(const row of document.querySelectorAll('#agentMiniStates .agent-mini-row')){if(!row.querySelector('.agent-mini-lamp')||getComputedStyle(row).borderTopStyle==='none'||getComputedStyle(row).borderRadius==='0px')throw Error('missing colored box or status lamp');}
for(const row of document.querySelectorAll('#agentMiniStates .agent-mini-row'))if(!/deepseek-\d+(busy|idle|offline)$/.test(row.textContent))throw Error('mini status contains extra detail');
const summary=document.querySelector('.project-global-card');if(getComputedStyle(summary,'::-webkit-scrollbar').width!=='6px'||getComputedStyle(summary,'::-webkit-scrollbar-button').display!=='none')throw Error('summary scrollbar still uses browser default');if(summary.clientHeight>innerHeight*.51||summary.scrollHeight<=summary.clientHeight||getComputedStyle(summary).overflowY!=='auto')throw Error('summary is not capped and scrollable');
summary.scrollTop=summary.scrollHeight;if(!summary.scrollTop)throw Error('summary scrolling failed');
await H.client.postAction('fixture_busy',{value:false});await H.store.refresh(true);type('');if(!button.disabled||button.dataset.mode!=='send')throw Error('idle empty must return gray send');
"""
class ManagerButton(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_icons_queue_interrupt_and_compact_sidebar(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  Fixture.busy=False;Fixture.messages=[];Fixture.requests=[]
  s=base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   with tempfile.TemporaryDirectory() as p:
    r=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size=1440,900',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=6500',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1))
    sent=[x for x in Fixture.requests if x['action']=='manager_message'];self.assertEqual([x['args']['body'] for x in sent],['hello','second message'])
    interrupted=[x for x in Fixture.requests if x['action']=='manager_interrupt'];self.assertEqual(len(interrupted),1);self.assertEqual(len(interrupted[0]['args']['message_ids']),2)
    print('PASS icon states, queue twice, empty interrupt, hover labels, half-window progress scroll, nine minimal states')
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
