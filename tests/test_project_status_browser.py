import re,threading,unittest
from pathlib import Path
from unittest.mock import patch
import test_nine_browser as base
from test_storage_git_browser import Fixture as StorageFixture

CHECK=r'''
H.client.setSelectedProjectId('p');await H.store.refresh(true);
document.getElementById('discussionReply').value='讨论草稿';document.getElementById('message').value='群聊草稿';
document.getElementById('tabProjectStatus').click();await new Promise(r=>setTimeout(r,160));
const panel=document.getElementById('panelProjectStatus');
if(!panel.getClientRects().length||document.getElementById('panelManagerChat').getClientRects().length||document.getElementById('panelGroupChat').getClientRects().length)throw Error('status tab did not switch');
if(document.getElementById('tabProjectStatus').getAttribute('aria-selected')!=='true')throw Error('status tab accessibility stale');
for(const id of ['projectNote','projectBar','projectGitDrawer','automationStatusCard','auditDrawer'])if(!panel.contains(document.getElementById(id)))throw Error('status content outside page: '+id);
if(document.getElementById('overall').textContent!=='67%'||document.getElementById('sidebarRight').textContent.includes('完整进度说明'))throw Error('sidebar still contains detailed report');
if(document.getElementById('overallBar').value!==67||document.getElementById('projectBar').value!==67)throw Error('progress bars not synchronized');
const cards=[...panel.querySelectorAll('.status-dashboard-card')].map(x=>x.getBoundingClientRect());
if(innerWidth>1100){if(Math.abs(cards[0].height-cards[1].height)>1||Math.abs(cards[2].height-cards[3].height)>1||Math.abs(cards[2].top-cards[0].bottom-16)>1)throw Error('uneven cards or large empty grid gaps');}
const heightBefore=cards[0].height;if(document.getElementById('projectNote').clientHeight<140||document.getElementById('projectGitGraph').clientHeight<180)throw Error('status text reading areas too short');if(parseFloat(getComputedStyle(document.getElementById('statusProjectProgress')).fontSize)>28)throw Error('progress number oversized');
if(!document.getElementById('projectNote').textContent.includes('完整进度说明末尾')||!document.querySelector('#projectNote strong'))throw Error('detailed report missing');
if(!document.getElementById('projectGitGraph').textContent.includes('worker implementation'))throw Error('status Git graph did not load');
if(panel.querySelector('#projectGitDrawer>summary,#auditDrawer>summary,#timersDrawer>summary,#noticesDrawer>summary'))throw Error('status sections still folded');
if([...panel.querySelectorAll('button')].some(b=>b.textContent.includes('暂停')))throw Error('unrequested pause button');
if(!document.getElementById('timerList').textContent.includes('状态页提醒')||!document.getElementById('pendingNotices').textContent.includes('状态页通知'))throw Error('automation missing');
panel.scrollTop=120;const position=panel.scrollTop;await H.store.refresh(true);if(Math.abs(panel.scrollTop-position)>2)throw Error('status reading position reset');if(Math.abs(panel.querySelector('.status-overview-card').getBoundingClientRect().height-heightBefore)>1)throw Error('card size changed during refresh');
document.getElementById('tabGroupChat').click();
const toggle=document.getElementById('toggleGroupComposer');
for(const expanded of [false,true]){
 if(expanded)toggle.click();
 const icon=toggle.querySelector('[data-compose-icon]:not([hidden]) svg'),a=toggle.getBoundingClientRect(),b=icon.getBoundingClientRect();
 if(Math.abs((a.left+a.right-b.left-b.right)/2)>.75||Math.abs((a.top+a.bottom-b.top-b.bottom)/2)>.75)throw Error('composer icon not centered '+JSON.stringify({a:a.toJSON(),b:b.toJSON(),display:getComputedStyle(toggle).display}));
}
if(document.getElementById('message').value!=='群聊草稿')throw Error('group draft lost');
document.getElementById('tabManagerChat').click();if(document.getElementById('discussionReply').value!=='讨论草稿')throw Error('manager draft lost');
document.getElementById('tabProjectStatus').click();
if(panel.getBoundingClientRect().right>innerWidth+2||panel.clientHeight<100||panel.scrollHeight<=panel.clientHeight)throw Error('status layout clipped or cannot scroll');
'''

class Fixture(StorageFixture):
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   body['projects']=[{'id':'p','name':'状态页面测试'}];body['selected_project']='p'
   body['project']={'progress':67,'note':'**完整进度说明**\n\n'+('实现、测试与交付的实际进展。\n'*45)+'完整进度说明末尾','updated':1792749511}
   body['timers']=[{'id':'status-timer','creator':'deepseek-1','recipient':'deepseek-4','state':'scheduled','due':1900000000,'note':'状态页提醒'}]
   body['pending_notifications']=[{'id':'status-notice','source':'平台','recipient':'deepseek-4','category':'timer','body':'状态页通知','state':'pending','created':1}]
   body['audit']=[{'action':'status-fixture','created':1,'details':'审计条目'}]
  return super().respond(status,body,kind)

@unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
class Status(unittest.TestCase):
 def test_status_layout_icons_drafts_and_project_git(self):
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   driver=base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
   with patch.object(base,'DRIVER',driver):
    for width,height in [(1640,1000),(1024,600),(600,800)]:
     with self.subTest(viewport=(width,height)):
      result=base.browser_run([str(base.m.EDGE),f'--window-size={width},{height}',f'http://127.0.0.1:{server.server_port}/'],timeout=30,screenshot=Path(__file__).parents[1]/'data'/f'project-status-{width}.png')
      found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(found);self.assertTrue(found.group(1).startswith('PASS'),found.group(1))
  finally:server.shutdown();server.server_close();thread.join()
