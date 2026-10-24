import unittest,subprocess,tempfile,re,threading
import test_nine_browser as base
class Fixture(base.Fixture):
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   body['projects']=[{'id':'older','name':'新项目'},{'id':'recent','name':'Recently opened'}]
   body['selected_project']=self.headers.get('X-Hub-Project') or 'older'
  super().respond(status,body,kind)
CHECK=r"""
if(document.querySelector('.tasks-board-card')||document.querySelector('.service-status-card'))throw Error('removed panels still exist');
for(const id of ['providerIntegrationBar','runtimeMode','openProviderGuide','openDeepSeekIntegration','reopenSetup'])if(document.getElementById(id).getClientRects().length)throw Error(id+' remains visible');
if(!document.getElementById('themeModeDark').closest('#configModal'))throw Error('theme not moved to settings');
if(sessionStorage.getItem('restore-stage')!=='1'){
 if(H.client.getSelectedProjectId()!=='recent')throw Error('saved selection ignored at startup');
 await H.chooseProject('older');if(localStorage.getItem('hub.lastOpenedProject')!=='older')throw Error('selection not saved');
 document.getElementById('discussionReply').value='unsent recovery draft';document.getElementById('discussionReply').dispatchEvent(new Event('input',{bubbles:true}));
 sessionStorage.setItem('restore-stage','1');location.reload();return;
}
if(H.client.getSelectedProjectId()!=='older')throw Error('reload did not restore last opened project');

"""
class CleanWorkspace(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_cleanup_and_reload_restoration(self):
  original=base.DRIVER;base.DRIVER="if(sessionStorage.getItem('restore-stage')!=='1')localStorage.setItem('hub.lastOpenedProject','recent');"+original.replace("const e=document.getElementById('discussionReply');","if(sessionStorage.getItem('restore-stage')==='1'&&document.getElementById('discussionReply').value!=='unsent recovery draft')throw Error('draft lost across UI reload');const e=document.getElementById('discussionReply');").replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  s=base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   with tempfile.TemporaryDirectory() as p:
    r=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=9000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print('PASS hidden removed panels, settings theme, selection persistence across actual page reload')
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
