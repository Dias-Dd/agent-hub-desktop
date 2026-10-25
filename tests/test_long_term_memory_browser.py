import re
import tempfile
import threading
import unittest
from pathlib import Path
import test_nine_browser as base
from hub.core import Hub
from hub.server import Handler

CHECK = r"""
const waitMemory=async test=>{for(let i=0;i<100;i++){if(test())return;await new Promise(r=>setTimeout(r,20));}throw Error('memory UI timeout');};
document.getElementById('configModalToggle').checked=true;
document.querySelector('[aria-controls="memorySettings"]').click();
await waitMemory(()=>!document.getElementById('memoryUser').disabled);
const user=document.getElementById('memoryUser'),notes=document.getElementById('memoryNotes'),save=document.getElementById('memorySave');
user.value='User prefers Chinese.';user.dispatchEvent(new Event('input'));
notes.value=Array.from({length:100},(_,i)=>'Reusable lesson '+i).join('\n');notes.dispatchEvent(new Event('input'));
save.click();await waitMemory(()=>document.getElementById('memoryStatus').textContent.startsWith('v1')&&!notes.disabled);
if(notes.scrollHeight<=notes.clientHeight)throw Error('long memory must scroll');
user.value='unsaved draft';user.dispatchEvent(new Event('input'));document.getElementById('memoryLock').click();
await waitMemory(()=>document.getElementById('memoryStatus').textContent.startsWith('v2')&&!notes.disabled);
if(user.value!=='unsaved draft')throw Error('locking lost draft');
save.click();await waitMemory(()=>document.getElementById('memoryStatus').textContent.startsWith('v3')&&!notes.disabled);
const versions=document.getElementById('memoryVersions');versions.value='1';versions.dispatchEvent(new Event('change'));
await waitMemory(()=>!document.getElementById('memoryPreview').hidden&&!document.getElementById('memoryRollback').disabled);
if(document.getElementById('memoryPreviewUser').value!=='User prefers Chinese.')throw Error('preview wrong version');
document.getElementById('memoryRollback').click();await waitMemory(()=>document.getElementById('memoryStatus').textContent.startsWith('v4')&&!notes.disabled);
const memoryResult=await H.client.postAction('memory',{operation:'read'});
if(user.value!=='User prefers Chinese.'||!memoryResult.locked)throw Error('rollback changed lock or wrong content');
const newer=await H.client.postAction('memory',{operation:'save',expected_revision:4,user:'Concurrent update',memory:'keep this'});
notes.value='my draft';notes.dispatchEvent(new Event('input'));save.click();await waitMemory(()=>!notes.disabled);
if(notes.value!=='my draft'||(await H.client.postAction('memory',{operation:'read'})).revision!==newer.revision)throw Error('conflict lost draft or overwrote current memory');
if(document.getElementById('memorySave').getBoundingClientRect().width<=0)throw Error('save hidden');
"""


class Fixture(base.Fixture):
    do_POST = Handler.do_POST


class MemoryBrowser(unittest.TestCase):
    @unittest.skipUnless(base.m.EDGE.exists(), 'Edge unavailable')
    def test_memory_settings_edit_lock_preview_rollback_conflict(self):
        original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
        with tempfile.TemporaryDirectory() as folder:
            hub=Hub(Path(folder)/'data',recover=False);hub.tokens['user']='fixture'
            server=base.Server(('127.0.0.1',0),Fixture);server.hub=hub
            thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                for size in ('1280,800','800,600'):
                    # Each viewport exercises real authenticated HTTP memory operations.
                    hub.db.execute('DELETE FROM long_term_memory_versions');hub.db.execute("DELETE FROM sqlite_sequence WHERE name='long_term_memory_versions'")
                    with self.subTest(size=size),tempfile.TemporaryDirectory() as profile:
                        response=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--window-size={size}',f'--user-data-dir={profile}','--dump-dom','--virtual-time-budget=10000',f'http://127.0.0.1:{server.server_port}/'],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
                        result=re.search(r'<pre id="result">(.*?)</pre>',response.stdout,re.S)
                        self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1))
            finally:
                server.shutdown();server.server_close();thread.join();hub.db.close();base.DRIVER=original
