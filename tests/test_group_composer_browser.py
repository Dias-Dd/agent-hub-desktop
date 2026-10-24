import re,threading,unittest
from pathlib import Path
from unittest.mock import patch
import test_nine_browser as base
CHECK=r"""
document.getElementById('chatTabGroupRadio').checked=true;
const form=document.getElementById('messageForm'),toggle=document.getElementById('toggleGroupComposer');
if(!form.hidden||toggle.getAttribute('aria-expanded')!=='false')throw Error('composer not collapsed by default');
toggle.click();await new Promise(r=>setTimeout(r,10));if(form.hidden||toggle.getAttribute('aria-expanded')!=='true')throw Error('composer did not expand');
const input=document.getElementById('message');input.value='keep this draft';input.dispatchEvent(new Event('input',{bubbles:true}));
toggle.click();await new Promise(r=>setTimeout(r,10));await H.store.refresh(true);if(!form.hidden||input.value!=='keep this draft')throw Error('collapse lost draft or polling reopened form');
toggle.click();await new Promise(r=>setTimeout(r,10));if(input.value!=='keep this draft')throw Error('reopen lost draft');
const box=form.getBoundingClientRect();if(box.bottom>innerHeight+2||box.width<100)throw Error('composer clipped');
const titles=[...document.querySelectorAll('#nativeTitlebar button')].map(b=>b.title);
if(titles.some(t=>['上一个项目','下一个项目','打开项目目录','额度速览','配置'].includes(t)))throw Error('removed titlebar icon remains');
if(!titles.includes('最大化')||!titles.includes('关闭至托盘'))throw Error('system controls lost');
"""
class Fixture(base.Fixture):
 def do_GET(self):
  if self.path=='/driver.js':return self.respond(200,"window.__HUB_NATIVE_WINDOWS__=true;window.chrome=window.chrome||{};window.chrome.webview={postMessage(){},addEventListener(){}};"+base.DRIVER,'text/javascript')
  super().do_GET()
@unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
class Browser(unittest.TestCase):
 def test_collapsible_composer_drafts_and_titlebar(self):
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   driver=base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
   with patch.object(base,'DRIVER',driver):
    for width,height in [(1440,900),(1024,600),(600,800)]:
     result=base.browser_run([str(base.m.EDGE),f'--window-size={width},{height}',f'http://127.0.0.1:{server.server_port}/'],timeout=30,screenshot=Path(__file__).parents[1]/'data'/('group-composer-'+str(width)+'.png'))
     found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(found);self.assertTrue(found.group(1).startswith('PASS'),found.group(1))
  finally:server.shutdown();server.server_close();thread.join()
