import re,threading,unittest,tempfile
import test_nine_browser as base
class Fixture(base.Fixture):
 def do_GET(self):
  if self.path.startswith('/api/reply-stream'):return self.respond(200,'','text/event-stream')
  return super().do_GET()
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   body['planning']=[{'id':'discussion','project_id':'p','manager':'deepseek-4','state':'thinking','revision':3,'pending':'r3','history':[
    {'role':'user','text':'initial','created':1}, {'role':'deepseek-4','text':'long reply\n'*100,'run_id':'r1','created':2},
    {'role':'user','text':'same request','created':3}, {'role':'deepseek-4','text':'previous reply','run_id':'r2','created':4},
    {'role':'user','text':'same request','created':5}]}]
   body['messages']=[{'id':'m2','sender':'user','recipient':'deepseek-4','body':'same request','created':3,'status':'completed','result':'DUPLICATED RAW PLAN','discussion_session_id':'discussion','discussion_run_id':'r2'},
    {'id':'m3','sender':'user','recipient':'deepseek-4','body':'same request','created':5,'status':'acknowledged','discussion_session_id':'discussion','discussion_run_id':'r3'}]
   body['messages'] += [{'id':'receipt-r2','sender':'deepseek-4','recipient':'user','body':'DUPLICATE MANAGER RECEIPT','created':4.01,'status':'user_delivered','request_key':'execution:r2:user'}, {'id':'manual-reply','sender':'deepseek-4','recipient':'user','body':'separate intentional manager message','created':4.02,'status':'user_delivered'}]
   body['deepseek']['runs']=[{'id':'r3','agent':'deepseek-4','status':'running','created':5}]
   body['live_replies']=[{'run_id':'r3','revision':1,'status':'running','text':'streamed reply\n'*100}]
  return super().respond(status,body,kind)
CHECK=r"""
await new Promise(r=>setTimeout(r,150));
const rows=[...document.querySelectorAll('#discussionHistory .chat-message')];
if(rows.filter(r=>r.dataset.role==='user'&&r.querySelector('.chat-message-body').textContent==='same request').length!==2)throw Error('queue/history duplicate, or legitimate repeated message lost');
if(document.getElementById('discussionHistory').textContent.includes('DUPLICATE MANAGER RECEIPT'))throw Error('same manager run displayed twice');
if(!document.getElementById('discussionHistory').textContent.includes('separate intentional manager message'))throw Error('independent manager message lost');
if(document.getElementById('discussionHistory').textContent.includes('DUPLICATED RAW PLAN'))throw Error('manager result shown under user');
const reader=document.getElementById('managerReadingArea'),reply=document.getElementById('discussionReplyForm');
if(reader.scrollHeight<=reader.clientHeight)throw Error('long discussion has no scroll');
if(innerWidth<680)reply.scrollIntoView({block:'end'});
if(document.getElementById('discussionSend').getBoundingClientRect().bottom>innerHeight+1)throw Error('composer clipped');
reader.scrollTop=reader.scrollHeight;
if(document.getElementById('managerLiveReply').getBoundingClientRect().bottom>reader.getBoundingClientRect().bottom+1)throw Error('streamed output clipped');
reader.scrollTop=10;document.getElementById('discussionReply').value='keep draft';await H.store.refresh(true);
if(document.getElementById('discussionReply').value!=='keep draft'||Math.abs(reader.scrollTop-10)>2)throw Error('refresh moved reader or lost draft');
"""
class DiscussionChat(unittest.TestCase):
 def test_queue_history_stream_and_composer(self):
  old=base.DRIVER;base.DRIVER=old.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   for size in ['1993,1248','1440,900','1024,600','600,800']:
    with self.subTest(size=size):
     r=base.browser_run([str(base.m.EDGE),'--window-size='+size,f'http://127.0.0.1:{server.server_port}/'],timeout=30)
     match=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(match);self.assertTrue(match.group(1).startswith('PASS'),match.group(1))
  finally:server.shutdown();server.server_close();thread.join();base.DRIVER=old
