import re,threading,unittest
from pathlib import Path
from unittest.mock import patch
import test_nine_browser as base
SETUP="window.__HUB_NATIVE_WINDOWS__=true;window.chrome.webview={postMessage:m=>(window.__windowCommands||=[]).push(m.command),addEventListener:()=>{}};"
CHECK=r"""
const bar=document.getElementById('nativeTitlebar');if(!bar||bar.getBoundingClientRect().height!==40)throw Error('titlebar absent');
const find=label=>bar.querySelector('button[aria-label="'+label+'"]');find('最小化').click();find('最大化').click();
if(!window.__windowCommands.includes('minimize')||!window.__windowCommands.includes('maximize'))throw Error('window controls not wired');
find('显示／隐藏项目列表').click();if(getComputedStyle(document.getElementById('sidebarLeft')).display!=='none')throw Error('sidebar toggle failed');
find('显示／隐藏项目列表').click();if(getComputedStyle(document.getElementById('sidebarLeft')).display==='none')throw Error('sidebar restore failed');
const reader=document.getElementById('managerReadingArea'),reply=document.getElementById('discussionReply');if(reader.getBoundingClientRect().bottom>innerHeight+1)throw Error('reader clipped by title bar');
if(bar.getBoundingClientRect().right>innerWidth+1)throw Error('titlebar horizontal overflow');
"""
class Browser(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_titlebar_and_sidebar(self):
  server=base.Server(('127.0.0.1',0),base.Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   driver=SETUP+base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
   with patch.object(base,'DRIVER',driver):
    for width,height in [(1440,900),(600,800)]:
     result=base.browser_run([str(base.m.EDGE),f'--window-size={width},{height}',f'http://127.0.0.1:{server.server_port}/'],timeout=30,screenshot=Path(__file__).parents[1]/'data'/('titlebar-'+str(width)+'.png'))
     found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertTrue(found and found.group(1).startswith('PASS'),found.group(1) if found else 'no result');print('PASS titlebar commands, sidebar toggle and bounded viewport',width,height)
  finally:server.shutdown();server.server_close();thread.join()
