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
const button=document.getElementById('discussionSend'),input=document.getElementById('discussionReply');
const type=t=>{input.value=t;input.dispatchEvent(new Event('input',{bubbles:true}));};
const post=H.client.postAction;let finish;H.client.postAction=async(a,b)=>a==='manager_message'?new Promise(resolve=>finish=resolve):post(a,b);
const refresh=H.store.refresh;H.store.refresh=()=>new Promise(()=>{});
type('hello');button.click();
if(input.value||button.getAttribute('aria-busy')!=='true'||!button.disabled)throw Error('no immediate sending feedback');
type('next draft');finish({queued:true,message_ids:['new']});await new Promise(r=>setTimeout(r,20));
if(button.disabled||button.getAttribute('aria-busy')!=='false'||input.value!=='next draft')throw Error('send waits for full state refresh or lost next draft');
H.view.rawSnapshot.deepseek.runs=[{agent:'deepseek-4',status:'running'}];type('');
H.client.postAction=async(a,b)=>a==='manager_interrupt'?new Promise(resolve=>finish=resolve):post(a,b);
button.click();if(button.getAttribute('aria-busy')!=='true')throw Error('no immediate insert feedback');
finish({note:'accepted'});await new Promise(r=>setTimeout(r,20));if(button.getAttribute('aria-busy')!=='false')throw Error('insert waits for full refresh');
H.client.postAction=async()=>{throw Error('fixture unavailable');};type('failed draft');button.click();type('new typing');await new Promise(r=>setTimeout(r,20));if(!input.value.includes('failed draft')||!input.value.includes('new typing'))throw Error('failed send lost draft');
if(H.statusLabel('user_delivered').includes('无需领取'))throw Error('internal delivery annotation exposed');
H.client.postAction=post;H.store.refresh=refresh;
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
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
