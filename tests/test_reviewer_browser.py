import re,subprocess,tempfile,threading,unittest
import test_nine_browser as base
CHECK=r"""
const reviewer=document.getElementById('workflowReviewer');
if([...reviewer.options].some(o=>o.value===H.view.managerStream.manager))throw Error('manager appears as independent reviewer');
const second=document.querySelector('#workflowAgents input[value="deepseek-2"]');second.checked=true;second.dispatchEvent(new Event('change',{bubbles:true}));
if(reviewer.value!=='deepseek-2')throw Error('reviewer is not selected participant');
const third=document.querySelector('#workflowAgents input[value="deepseek-3"]');third.checked=true;third.dispatchEvent(new Event('change',{bubbles:true}));
second.checked=false;second.dispatchEvent(new Event('change',{bubbles:true}));
if(reviewer.value!=='deepseek-3'||[...reviewer.options].some(o=>o.value==='deepseek-2'))throw Error('removed participant still default reviewer');
third.checked=false;third.dispatchEvent(new Event('change',{bubbles:true}));
if(reviewer.value!=='')throw Error('empty roster must not select manager');
"""
class ReviewerBrowser(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_reviewer_tracks_participant_selection(self):
  old=base.DRIVER;base.DRIVER=old.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  server=base.Server(('127.0.0.1',0),base.Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   with tempfile.TemporaryDirectory() as folder:
    result=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--user-data-dir={folder}','--dump-dom','--virtual-time-budget=5000',f'http://127.0.0.1:{server.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    match=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(match);self.assertTrue(match.group(1).startswith('PASS'),match.group(1))
  finally:server.shutdown();server.server_close();thread.join();base.DRIVER=old
