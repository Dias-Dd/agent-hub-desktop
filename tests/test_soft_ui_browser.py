import json,re,threading,unittest
from pathlib import Path
from unittest.mock import patch
import test_nine_browser as base
CHECK=r"""
document.documentElement.dataset.theme='light';document.getElementById('toggleQuotaQuick').click();
await new Promise(r=>setTimeout(r,150));
const quota=document.getElementById('quotaQuickPanel');if(quota.hidden||quota.ownerDocument!==document)throw Error('quota detached');
if(quota.querySelectorAll('.quota-ring').length!==3)throw Error('quota rings missing');
const rect=quota.getBoundingClientRect();if(rect.right>innerWidth||rect.bottom>innerHeight)throw Error('quota clipped');
const input=document.getElementById('discussionReply');if(getComputedStyle(input).borderTopColor!=='rgba(0, 0, 0, 0)')throw Error('outlined input');
const card=H.chatMessage('产品演示','设计 v2 已确认，正式制作须遵循此基线。','设计',Date.now()/1000);card.classList.add('design-delivery');const button=H.node('button','审阅产品演示','design-review-launch');card.querySelector('.chat-message-body').append(button);document.getElementById('discussionHistory').append(card);
if(getComputedStyle(button).minHeight!=='44px')throw Error('review target too small');
const body=card.querySelector('.chat-message-body');if(getComputedStyle(body).flexDirection!=='column')throw Error('review invitation still inline');
if(button.getBoundingClientRect().width>body.clientWidth)throw Error('review action clipped');
"""
class Fixture(base.Fixture):
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'all_deepseek' in body:
   body['quota_overview']=[{'name':'Gemini Models','windows':[{'name':'Weekly Limit Remaining','account':'Google','remaining':47,'resets_at':1792800000},{'name':'Five Hour Limit Remaining','account':'Google','remaining':59,'resets_at':1792600000}],'balances':[],'unreadable':[],'refreshable':[]},{'name':'Claude and GPT models','windows':[{'name':'Weekly Limit Remaining','account':'Google','remaining':0,'resets_at':1792800000}],'balances':[],'unreadable':[],'refreshable':[]}]
  return super().respond(status,body,kind)
@unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
class Browser(unittest.TestCase):
 def test_quota_and_soft_surfaces(self):
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   driver=base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
   with patch.object(base,'DRIVER',driver):
    for width,height in [(1440,900),(600,800)]:
     result=base.browser_run([str(base.m.EDGE),f'--window-size={width},{height}',f'http://127.0.0.1:{server.server_port}/'],timeout=30,screenshot=Path(__file__).parents[1]/'data'/('soft-ui-'+str(width)+'.png'))
     found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(found);self.assertTrue(found.group(1).startswith('PASS'),found.group(1));print('PASS quota popover, real quotas/rings, borderless inputs and review invitation',width,height)
   dark=base.DRIVER.replace("out.textContent='PASS",CHECK+"quota.hidden=true;document.documentElement.dataset.theme='dark';out.textContent='PASS")
   with patch.object(base,'DRIVER',dark):
    result=base.browser_run([str(base.m.EDGE),'--window-size=1440,900',f'http://127.0.0.1:{server.server_port}/'],timeout=30,screenshot=Path(__file__).parents[1]/'data/soft-ui-review-dark.png')
    found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertTrue(found and found.group(1).startswith('PASS'),result.stdout[-1000:])
  finally:server.shutdown();server.server_close();thread.join()
