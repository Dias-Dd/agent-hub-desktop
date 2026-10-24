import unittest,subprocess,tempfile,re,threading
import test_nine_browser as base
class Fixture(base.Fixture):
 def do_GET(self):
  if self.path.startswith('/api/reply-stream?'):return self.respond(503,{'error':'fixture has no provider stream'})
  super().do_GET()
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   for a in body['agents']:a.update(active='当前长任务'+('详细任务要求。'*1000),status='busy')
   body['deepseek']['runs']=[{'id':'run-'+a['id'],'agent':a['id'],'status':'running','prompt':'详细任务要求。'*1000,'actual_input':'实际输入。'*1000} for a in body['agents']]
  super().respond(status,body,kind)
CHECK=r"""
document.getElementById('viewModeStatusRadio').checked=true;
await new Promise(r=>setTimeout(r,20));
const cards=[...document.querySelectorAll('#agents .agent-box')];
for(const card of cards){
 if(Math.abs(card.getBoundingClientRect().height-cards[0].getBoundingClientRect().height)>1)throw Error('unequal card height');
 if(innerWidth>=680 && (card.getBoundingClientRect().bottom>document.getElementById('agentsGrid').getBoundingClientRect().bottom+1))throw Error('card below viewport');
 const d=card.querySelector('.agent-task-details');if(!d||d.open||d.querySelector('pre'))throw Error('task not lazy collapsed');
}
const grid=document.getElementById('agentsGrid');
if(innerWidth>=680 && grid.scrollHeight>grid.clientHeight+1)throw Error('grid still requires scrolling');
if(innerWidth>=1100 && cards.some(c=>c.scrollHeight>c.clientHeight+1))throw Error('collapsed card still needs scrolling '+JSON.stringify(cards.map(c=>({client:c.clientHeight,scroll:c.scrollHeight,children:[...c.children].map(e=>[e.className,e.getBoundingClientRect().height])}))));
const card=cards[0],originalHeight=card.getBoundingClientRect().height;
card.querySelector('button[aria-label^="查看"]').click();
if(!document.getElementById('agentDetailsDialog').open)throw Error('details dialog did not open');
const d=document.querySelector('#agentDetailsContent .agent-task-details');d.open=true;d.ensureContent();
await new Promise(r=>setTimeout(r,20));
if(!d.querySelector('pre').textContent.includes('详细任务要求。')||Math.abs(card.getBoundingClientRect().height-originalHeight)>1)throw Error('expand lost full text or changed card height');
if(!d.querySelector('pre').getClientRects().length)throw Error('expanded task unreachable in details dialog');
document.getElementById('closeAgentDetails').click();await new Promise(r=>setTimeout(r,20));
await H.store.refresh(true);
if(document.querySelector('#agents .agent-box')!==card||!d.open)throw Error('refresh lost expansion');
"""
class Cards(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_fixed_cards_and_lazy_tasks(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  s=base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   for size in ['1425,862','1140,690','1024,600','600,800']:
    with self.subTest(size=size),tempfile.TemporaryDirectory() as p:
     r=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--window-size={size}',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=6000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
     result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print('PASS fixed nine cards, collapsed full tasks, expand/refresh at '+size)
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
