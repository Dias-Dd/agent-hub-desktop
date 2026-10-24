import unittest,subprocess,tempfile,re,threading
import test_nine_browser as base
class Fixture(base.Fixture):
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   body['messages']=[{'id':'late','sender':'deepseek-1','recipient':'user','body':'newest message','created':200,'status':'completed'},{'id':'early','sender':'deepseek-2','recipient':'user','body':'oldest message','created':100,'status':'completed'}]
   body['deepseek']['runs']=[{'id':'manager-run','agent':'deepseek-4','status':'completed','created':150,'finished':200}]
   body['planning']=[{'id':'plan','created':100,'state':'draft','revision':1,'history':[{'role':'user','text':'old plan message','created':100},{'role':'deepseek-4','text':'new plan answer','run_id':'manager-run'}]}]
  super().respond(status,body,kind)
CHECK=r"""
const group=[...document.querySelectorAll('#messages article')];
if(!group[0].textContent.includes('oldest message')||!group.at(-1).textContent.includes('newest message'))throw Error('group order reversed');
if(!group.every(row=>row.querySelector('time[datetime]')))throw Error('group timestamp missing');
if(![...document.querySelectorAll('#discussionHistory article')].every(row=>row.querySelector('time[datetime]')))throw Error('manager timestamp missing');
const wait=()=>new Promise(r=>setTimeout(r,100));
for(const id of ['discussionHistory','messages']) {
 document.getElementById(id==='messages'?'chatTabGroupRadio':'chatTabManagerRadio').checked=true;
 const scroller=document.getElementById(id==='messages'?'messages':'managerReadingArea');
 const rows=Array.from({length:28},(_,i)=>H.record('row '+i,'content '.repeat(35),'completed'));
 H.list(id,rows);await wait();
 if(id==='messages') {
  scroller.scrollTop=100;await wait();
  document.getElementById('tabManagerChat').click();await wait();
  document.getElementById('tabGroupChat').click();await wait();
  if(scroller.scrollHeight-scroller.clientHeight-scroller.scrollTop>24)throw Error('enter group did not open latest messages');
 }
 scroller.scrollTop=scroller.scrollHeight;await wait();
 H.list(id,[...rows,H.record('last','new message '.repeat(30),'completed')]);await wait();
 if(scroller.scrollHeight-scroller.clientHeight-scroller.scrollTop>24)throw Error(id+' failed bottom following');
 scroller.scrollTop=100;await wait();const top=scroller.scrollTop;
 H.list(id,[...rows,H.record('last2','new message '.repeat(30),'completed'),H.record('last3','more '.repeat(30),'completed')]);await wait();
 if(Math.abs(scroller.scrollTop-top)>2)throw Error(id+' moved reader away from historical position');
}
"""
class ChatChronology(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_order_timestamps_and_scroll_follow(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  s=base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   with tempfile.TemporaryDirectory() as p:
    r=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size=1440,900',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=9000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print('PASS timestamp/order/bottom-follow/scrolled-up position for both chats')
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
