import re
import tempfile
import threading
import unittest
import test_nine_browser as base

CHECK = r"""
const receipt=document.querySelector('#discussionHistory .memory-update');
if(!receipt)throw Error('missing saved-memory receipt in timeline');
if(!receipt.textContent.includes('长期记忆已更新')||!receipt.textContent.includes('平台'))throw Error('missing platform label');
if(receipt.querySelector('pre,textarea,details,iframe')||receipt.textContent.includes('PRIVATE_MEMORY_BODY'))throw Error('full memory leaked into receipt');
const managerText='Manager ordinary reply remains visible';
const replies=[...document.querySelectorAll('#discussionHistory .chat-message-body')].filter(n=>n.textContent.includes(managerText));
if(replies.length!==1)throw Error('normal manager reply missing or duplicated: '+replies.length);
for(const theme of ['light','dark']){
 document.documentElement.dataset.theme=theme;
 const rect=receipt.getBoundingClientRect();
 if(rect.width>342||rect.height>100||rect.width<100)throw Error('receipt not compact: '+JSON.stringify(rect.toJSON()));
}
await H.store.refresh(true);
if(document.querySelectorAll('#discussionHistory .memory-update').length!==1)throw Error('receipt duplicated on refresh');
"""

class Fixture(base.Fixture):
    def respond(self,status,body,content_type='application/json'):
        if isinstance(body,dict) and 'all_deepseek' in body:
            body={**body,'memory_updates':[{'revision':3,'actor':'deepseek-4','reason':'add','created':1,'content':'PRIVATE_MEMORY_BODY'}],
                  'integration_runs':[{'id':'saved-memory-run','agent':'deepseek-4','message_id':'question','status':'completed','created':1,'finished':3}],
                  'messages':[{'id':'question','sender':'user','recipient':'deepseek-4','body':'Try saving memory','result':'Manager ordinary reply remains visible','status':'completed','created':1},
                              {'id':'reply','sender':'deepseek-4','recipient':'user','body':'Manager ordinary reply remains visible','request_key':'execution:saved-memory-run:user','status':'user_delivered','created':3}]}
        return super().respond(status,body,content_type)

class MemoryReceipt(unittest.TestCase):
    @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
    def test_compact_metadata_receipt_and_normal_manager_reply(self):
        original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
        server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            for size in ['1440,900','600,800']:
                with self.subTest(size=size),tempfile.TemporaryDirectory() as folder:
                    result=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size='+size,'--user-data-dir='+folder,'--dump-dom','--virtual-time-budget=6000',f'http://127.0.0.1:{server.server_port}/'],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
                    match=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
                    self.assertIsNotNone(match);self.assertTrue(match.group(1).startswith('PASS'),match.group(1))
        finally:
            server.shutdown();server.server_close();thread.join();base.DRIVER=original
