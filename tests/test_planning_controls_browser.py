import re,tempfile,threading,unittest
import test_nine_browser as base

CHECK=r"""
const top=document.getElementById('newDiscussion'),inline=document.getElementById('newDiscussionInline'),editor=document.getElementById('discussionReply');
let calls=0,complete;
H.store.sendPlanChat=()=>{calls++;return new Promise(resolve=>{complete=resolve;});};
editor.value='requirements for this plan';
top.click();inline.click();await new Promise(r=>setTimeout(r,40));
if(calls!==1)throw Error('planning submitted twice through the shared controls');
editor.value='new unsent draft';editor.dispatchEvent(new Event('input'));
complete({});await new Promise(r=>setTimeout(r,40));
if(editor.value!=='new unsent draft')throw Error('planning reply cleared a newer draft');
"""
class Fixture(base.Fixture):
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   body.update(projects=[{'id':'p','name':'Project'}],selected_project='p',planning=[{'id':'s','project_id':'p','mode':'alignment','state':'chatting','revision':1,'history':[],'pending':None,'options':{'agents':[]}}])
  super().respond(status,body,kind)
class PlanningControls(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_shared_button_serialization_and_new_draft_preservation(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   with tempfile.TemporaryDirectory() as folder:
    result=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size=1440,900','--user-data-dir='+folder,'--dump-dom','--virtual-time-budget=6000','http://127.0.0.1:'+str(server.server_port)+'/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
    self.assertIsNotNone(found);self.assertTrue(found.group(1).startswith('PASS'),found.group(1))
  finally:server.shutdown();server.server_close();thread.join();base.DRIVER=original
