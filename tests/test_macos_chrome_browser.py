"""Rendered Mac titlebar plus the real long-reply/reading regression checks."""
import re
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import test_nine_browser as base
from test_manager_layout import CHECK as LAYOUT
from test_reading_browser import EXTRA as READING

SETUP="""window.__HUB_NATIVE_WINDOWS__=true;window.__HUB_NATIVE_MACOS__=true;
window.__HUB_NATIVE_BACKDROP__='sidebar';window.webkit={messageHandlers:{hubNative:{postMessage:m=>(window.__macMessages||=[]).push(m)}}};
"""
CHECK=r"""
const bar=document.getElementById('nativeTitlebar'),toggle=bar?.querySelector('.titlebar-tools button');
if(!toggle||!document.documentElement.classList.contains('native-macos'))throw Error('Mac toolbar absent');
if(toggle.getBoundingClientRect().left<80)throw Error('sidebar toggle overlaps traffic lights');
if(bar.getBoundingClientRect().height!==48||bar.getBoundingClientRect().right>innerWidth)throw Error('toolbar clipped');
if(toggle.querySelectorAll('svg rect').length!==1||!toggle.querySelector('svg path'))throw Error('Mac sidebar SVG missing');
if(document.querySelectorAll('#btnViewStatus svg rect').length!==9)throw Error('Mac grid is font dependent');
if(getComputedStyle(document.querySelector('.workbench-content-surface')).borderBottomRightRadius!=='12px')throw Error('Mac inset corner incorrect');
if(bar.querySelectorAll('.titlebar-system button').length)throw Error('Windows caption buttons on Mac');
if(!document.documentElement.classList.contains('native-backdrop'))throw Error('continuous material missing');
const draft=document.getElementById('discussionReply').value;
toggle.click();
const list=document.getElementById('sidebarLeft'),surface=document.querySelector('.workbench-content-surface');
if(!list.inert||getComputedStyle(list).visibility!=='hidden')throw Error('project list remains interactive');
if(surface.getBoundingClientRect().width<innerWidth/3)throw Error('collapsed content cannot expand');
toggle.click();
if(list.inert||getComputedStyle(list).visibility==='hidden')throw Error('project list not restored');
if(document.getElementById('discussionReply').value!==draft)throw Error('toggle lost draft');
document.documentElement.dataset.theme='dark';await new Promise(r=>setTimeout(r,20));
if(!window.__macMessages.some(m=>m.command==='appearance'&&m.dark===true))throw Error('native theme not synchronized');
document.documentElement.dataset.theme='light';
"""


class MacChrome(unittest.TestCase):
    @unittest.skipUnless(base.m.EDGE.exists(),'No real browser available')
    def test_mac_toolbar_long_replies_reading_and_sidebar(self):
        server=base.Server(('127.0.0.1',0),base.Fixture)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        folder=Path(__file__).parents[1]/'local-data/ui-validation';folder.mkdir(parents=True,exist_ok=True)
        try:
            driver=SETUP+base.DRIVER.replace("out.textContent='PASS",'{'+LAYOUT+'}{'+READING+'}{'+CHECK+"}out.textContent='PASS")
            with patch.object(base,'DRIVER',driver):
                for width,height in [(1440,900),(1024,600),(600,800)]:
                    with self.subTest(width=width,height=height):
                        result=base.browser_run([str(base.m.EDGE),f'--window-size={width},{height}',f'http://127.0.0.1:{server.server_port}/'],timeout=30,screenshot=folder/f'macos-chrome-{width}.png')
                        found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
                        self.assertTrue(found and found.group(1).startswith('PASS'),found.group(1) if found else 'No result')
        finally:server.shutdown();server.server_close();thread.join()
