import json,re,subprocess,tempfile,threading,unittest
import test_nine_browser as base

CHECK=r"""
H.store.stopPolling();
const button=document.getElementById('workflowPatrolBtn');
if(button.hidden||button.textContent!=='允许项目静置')throw Error('patrol toggle missing');
button.click();await new Promise(r=>setTimeout(r,150));
if(button.textContent!=='恢复定期巡检'||button.getAttribute('aria-pressed')!=='true')throw Error('patrol not disabled');
button.click();await new Promise(r=>setTimeout(r,150));
if(button.textContent!=='允许项目静置'||button.getAttribute('aria-pressed')!=='false')throw Error('patrol not reenabled');
const enabled=document.getElementById('managerPatrolEnabled'),minutes=document.getElementById('managerPatrolMinutes');
if(!enabled.checked||minutes.value!=='10')throw Error('wrong default patrol config');
enabled.checked=false;minutes.value='15';document.getElementById('managerPatrolForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
await new Promise(r=>setTimeout(r,150));await H.store.refresh(true);
if(enabled.checked||minutes.value!=='15')throw Error('patrol settings lost on refresh');
"""
class Fixture(base.Fixture):
 enabled=True
 actions=[]
 def respond(self,code,data,kind='application/json'):
  if self.path=='/api/state' and isinstance(data,dict):
   data['workflows'][0]['patrol_enabled']=type(self).enabled;data['manager_patrol']=getattr(type(self),'config',{'enabled':True,'interval_minutes':10})
  return super().respond(code,data,kind)
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
  type(self).actions.append(data)
  if data['action']=='workflow_set_patrol':type(self).enabled=data['args']['enabled']
  if data['action']=='manager_patrol_config':type(self).config=data['args']
  self.respond(200,{'result':{}})
class PatrolBrowser(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_toggle_changes_only_periodic_patrol(self):
  old=base.DRIVER;base.DRIVER=old.replace("out.textContent='PASS",CHECK+"out.textContent='PASS");Fixture.actions=[];Fixture.enabled=True
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   with tempfile.TemporaryDirectory() as folder:
    r=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--user-data-dir={folder}','--dump-dom','--virtual-time-budget=5000',f'http://127.0.0.1:{server.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1))
    self.assertEqual([a['action'] for a in Fixture.actions],['workflow_set_patrol','workflow_set_patrol','manager_patrol_config'])
    self.assertEqual([a['args']['enabled'] for a in Fixture.actions],[False,True,False])
  finally:server.shutdown();server.server_close();thread.join();base.DRIVER=old
