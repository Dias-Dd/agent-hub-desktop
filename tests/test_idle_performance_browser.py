import time,threading,tempfile,subprocess,re,unittest
import test_nine_browser as base
class Fixture(base.Fixture):
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:body['time']=time.time()
  return super().respond(status,body,kind)
CHECK="""
let renders=0;H.render(()=>renders++);renders=0;
const start=performance.now();for(let i=0;i<120;i++)await H.store.refresh(true);H.store.stopPolling();
if(renders!==0)throw Error('idle clock triggered '+renders+' full renders');
if(document.getElementById('discussionReply').value!=='draft')throw Error('draft lost');
console.log('120 idle refreshes ms',performance.now()-start);
"""
class Browser(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_repeated_clock_changes_do_not_rebuild_panels(self):
  old=base.DRIVER;base.DRIVER=old.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  server=base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=server.serve_forever);t.start()
  try:
   with tempfile.TemporaryDirectory() as folder:
    p=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--user-data-dir='+folder,'--dump-dom','--virtual-time-budget=15000','http://127.0.0.1:'+str(server.server_port)+'/'],capture_output=True,encoding='utf8',errors='replace',timeout=40)
    result=re.search(r'<pre id="result">(.*?)</pre>',p.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1))
  finally:server.shutdown();server.server_close();t.join();base.DRIVER=old
