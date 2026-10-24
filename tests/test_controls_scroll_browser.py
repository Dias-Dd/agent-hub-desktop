import re,threading,time,unittest
from unittest.mock import patch
from pathlib import Path
import test_nine_browser as base
from test_project_status_browser import Fixture as StatusFixture

class Fixture(StatusFixture):
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:body['timers']=[];body['pending_notifications']=[]
  # StatusFixture injects timers; bypass its injection for this empty-card regression.
  from test_storage_git_browser import Fixture as Storage
  return Storage.respond(self,status,body,kind)

class Scroll(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_native_wheel_chains_from_empty_card_and_controls_are_not_text(self):
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  def native_wheel(ws):
   evaluate=lambda script:ws.call('Runtime.evaluate',{'expression':script,'returnByValue':True})['result']['value']
   info=evaluate("""(()=>{const panel=document.getElementById('panelProjectStatus'),card=document.getElementById('automationStatusCard');panel.scrollTop+=card.getBoundingClientRect().top-panel.getBoundingClientRect().top-40;const r=card.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+180,before:panel.scrollTop,empty:card.scrollHeight<=card.clientHeight+1};})()""")
   self.assertTrue(info['empty'],'fixture must have no inner scrollbar')
   ws.call('Input.dispatchMouseEvent',{'type':'mouseWheel','x':info['x'],'y':info['y'],'deltaY':-180,'deltaX':0})
   time.sleep(.3)
   self.assertLess(evaluate("document.getElementById('panelProjectStatus').scrollTop"),info['before']-30)
  check=r"""
document.getElementById('tabProjectStatus').click();
for(const id of ['btnOpenConfig','tabProjectStatus','refreshProjectGit'])if(getComputedStyle(document.getElementById(id)).userSelect!=='none')throw Error('control text remains selectable');
const text=document.querySelector('#projectNote');if(getComputedStyle(text).userSelect==='none')throw Error('report text cannot be copied');
if(getComputedStyle(document.getElementById('automationStatusCard')).overscrollBehaviorY!=='auto')throw Error('scroll chain blocked');
"""
  try:
   with patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS",check+"out.textContent='PASS")):
    result=base.browser_run([str(base.m.EDGE),'--window-size=1640,1000',f'http://127.0.0.1:{server.server_port}/'],timeout=30,after_checks=native_wheel,screenshot=Path(__file__).parents[1]/'data/controls-scroll.png')
   found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(found);self.assertTrue(found.group(1).startswith('PASS'),found.group(1))
  finally:server.shutdown();server.server_close();thread.join()
