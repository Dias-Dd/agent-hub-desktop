import unittest,subprocess,tempfile,re,threading
import test_nine_browser as base
EXTRA=r"""
const body=Array.from({length:180},(_,i)=>'第'+i+'行：用于验证刷新不打断阅读的长回复。').join('\n');
for(const id of ['discussionHistory','messages','tasks','audit','wakeLog','reportLog','planTaskPreview']) {
 H.list(id,[H.record('stable row',body,'completed')]);
 const root=document.getElementById(id),row=root.firstElementChild,d=row.querySelector('details');
 d.open=true;await new Promise(r=>setTimeout(r,20));
 const pre=d.querySelector('pre');pre.scrollTop=130;const top=pre.scrollTop;
 H.list(id,[H.record('stable row',body,'completed')]);
 if(root.firstElementChild!==row||!d.open||!pre.isConnected||pre.scrollTop!==top)throw Error(id+' lost reading state');
 H.list(id,[H.record('stable row',body,'completed'),H.record('new item','new','completed')]);
 if(root.firstElementChild!==row||!d.open||pre.scrollTop!==top)throw Error(id+' append disrupted reading');
}
const pre=document.querySelector('#discussionHistory pre');
if(parseFloat(getComputedStyle(pre).maxHeight)<300)throw Error('manager reader too small');
if(getComputedStyle(pre).resize!=='vertical')throw Error('reader cannot resize');
const d=document.querySelector('#discussionHistory details');
d.querySelector('pre').scrollTop=110;const changedTop=d.querySelector('pre').scrollTop;
H.list('discussionHistory',[H.record('stable row',body,'running')]);
const changed=document.querySelector('#discussionHistory details');
if(!changed.open||!changed.querySelector('pre')||changed.querySelector('pre').scrollTop!==changedTop)throw Error('changed row not synchronously expanded');
"""
class BrowserReading(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_polling_preserves_reading_across_all_lists(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",EXTRA+"out.textContent='PASS")
  s=base.Server(('127.0.0.1',0),base.Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   with tempfile.TemporaryDirectory() as p:
    r=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=6000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print('PASS stable nodes/expansion/nested scrolling/append across seven lists; enlarged resizable manager reader; changed rows hydrate before insertion')
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
