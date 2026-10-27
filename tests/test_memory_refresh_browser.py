import unittest,subprocess,tempfile,re,threading
import test_nine_browser as base
EXTRA=r"""
let memory={revision:1,user:'first preference',memory:'first note',locked:false};let reads=0;
const oldPost=H.client.postAction.bind(H.client);
H.client.postAction=async(action,args)=>{
 if(action!=='memory')return oldPost(action,args);
 if(args.operation==='read'){reads++;return {...memory};}
 if(args.operation==='history')return {versions:[],total:0};
 throw Error('unexpected memory operation');
};
document.getElementById('memorySettings').classList.remove('settings-section-inactive');
window.dispatchEvent(new Event('hub-settings-section'));await new Promise(r=>setTimeout(r,40));
if(document.getElementById('memoryUser').value!=='first preference')throw Error('initial automatic load failed');
memory={...memory,revision:2,user:'updated preference'};
H.store.rawState.memory_revision=2;H.store._notify();await new Promise(r=>setTimeout(r,40));
if(document.getElementById('memoryUser').value!=='updated preference')throw Error('manager save did not refresh');
const editor=document.getElementById('memoryUser');editor.value='unsaved draft';editor.dispatchEvent(new Event('input'));
memory={...memory,revision:3,user:'another preference'};
H.store.rawState.memory_revision=3;H.store._notify();await new Promise(r=>setTimeout(r,40));
if(editor.value!=='unsaved draft')throw Error('automatic refresh overwrote user draft');
if(!document.getElementById('memoryStatus').textContent.includes('已有新版本'))throw Error('new version not reported while dirty');
const count=reads;H.store._notify();await new Promise(r=>setTimeout(r,40));
if(reads!==count)throw Error('unnecessary repeated reads');
"""
class MemoryRefresh(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_automatic_memory_refresh_preserves_drafts(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",EXTRA+"out.textContent='PASS")
  s=base.Server(('127.0.0.1',0),base.Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   with tempfile.TemporaryDirectory() as p:
    r=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=6000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print('PASS automatic memory refresh and preserved user drafts')
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
