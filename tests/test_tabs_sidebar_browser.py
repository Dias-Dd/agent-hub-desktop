import re,threading,unittest
from pathlib import Path
from unittest.mock import patch
import test_nine_browser as base
CHECK=r"""
const titlebar=document.getElementById('nativeTitlebar');
window.dispatchEvent(new Event('blur'));if(!titlebar.classList.contains('is-inactive'))throw Error('title blur missing');
window.dispatchEvent(new Event('focus'));if(titlebar.classList.contains('is-inactive'))throw Error('title focus missing');
if(document.getElementById('nativeProjectTitle').textContent==='智能协作工作台')throw Error('fallback title remains');
const nav=document.querySelector('.chat-tabs-nav');
for(const id of ['tabGroupChat','tabProjectStatus','tabManagerChat','tabProjectStatus','tabGroupChat','tabManagerChat']){
 const tab=document.getElementById(id);tab.click();
 await new Promise(r=>setTimeout(r,60));
 const pill=nav.querySelector('.chat-tab-indicator');
 if(tab.getAttribute('aria-selected')!=='true'||!pill.getAnimations().length)throw Error('tab transition cancelled or absent: '+id);
 tab.click();await new Promise(r=>setTimeout(r,35));
 if(tab.classList.contains('is-loading'))throw Error('navigation uses request spinner');
 if(getComputedStyle(tab).boxShadow!=='none')throw Error('duplicate selection surface');
 await new Promise(r=>setTimeout(r,280));
 const a=pill.getBoundingClientRect(),b=tab.getBoundingClientRect();
 if(Math.abs(a.left-b.left)>1||Math.abs(a.width-b.width)>1)throw Error('tab surface misaligned: '+id+' '+JSON.stringify([a.left,a.width,b.left,b.width,nav.getBoundingClientRect().left,getComputedStyle(nav).position]));
}
if(document.querySelector('.context-menu-hint'))throw Error('internal context help visible');
document.getElementById('tabGroupChat').click();await new Promise(r=>setTimeout(r,300));
const composerToggle=document.getElementById('toggleGroupComposer'),form=document.getElementById('messageForm'),shell=document.querySelector('.group-composer-motion');
if(composerToggle.getAttribute('aria-expanded')==='true'){composerToggle.click();await new Promise(r=>setTimeout(r,300));}
const draft=document.getElementById('message');draft.value='preserved animation draft';
composerToggle.click();await new Promise(r=>setTimeout(r,60));
if(!shell.getAnimations().length||shell.getBoundingClientRect().height<=0)throw Error('composer opening motion absent');
composerToggle.click();await new Promise(r=>setTimeout(r,40));composerToggle.click();await new Promise(r=>setTimeout(r,300));
const feed=document.querySelector('#panelGroupChat .messages-feed-scroll'),toolbar=document.querySelector('.group-compose-toolbar');
if(feed.getBoundingClientRect().height<85||feed.getBoundingClientRect().bottom>toolbar.getBoundingClientRect().top+1)throw Error('expanded composer overlaps conversation');
if(form.hidden||form.inert||draft.value!=='preserved animation draft')throw Error('composer rapid reversal lost state');
composerToggle.click();await new Promise(r=>setTimeout(r,300));
if(!form.hidden||shell.getBoundingClientRect().height>1)throw Error('composer collapse left space');
const toggle=document.querySelector('#nativeTitlebar button[aria-label="显示／隐藏项目列表"]'),sidebar=document.getElementById('sidebarLeft');
if(innerWidth>680){
 const surface=document.querySelector('.workbench-content-surface'),start=sidebar.getBoundingClientRect().width,initial=surface.getBoundingClientRect().left;toggle.click();await new Promise(r=>setTimeout(r,50));const middle=surface.getBoundingClientRect().left;
 if(middle>=initial-1||middle<=initial-start+1||!surface.getAnimations().length)throw Error('compositor sidebar animation missing');
 await new Promise(r=>setTimeout(r,400));if(sidebar.getBoundingClientRect().width>1||!sidebar.inert)throw Error('sidebar did not finish collapse');
 toggle.click();await new Promise(r=>setTimeout(r,400));if(Math.abs(sidebar.getBoundingClientRect().width-start)>2||sidebar.inert)throw Error('sidebar failed to restore');
}else{toggle.click();await new Promise(r=>setTimeout(r,400));toggle.click();await new Promise(r=>setTimeout(r,400));}
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
     result=base.browser_run([str(base.m.EDGE),f'--window-size={width},{height}',f'http://127.0.0.1:{server.server_port}/'],timeout=30,screenshot=Path(__file__).parents[1]/'data'/('tabs-sidebar-'+str(width)+'.png'))
     found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(found);self.assertTrue(found.group(1).startswith('PASS'),found.group(1))
  finally:server.shutdown();server.server_close();thread.join()

