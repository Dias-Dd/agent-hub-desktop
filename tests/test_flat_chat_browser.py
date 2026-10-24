import re,threading,tempfile,subprocess,unittest
import test_live_browser as base
CHECK="""
const wait=()=>new Promise(r=>setTimeout(r,180));await wait();
const message=H.chatMessage('经理 deepseek-4 · done','完整回复开始 '+('内容 '.repeat(800))+' 完整回复结束','completed',1800000000);
H.list('discussionHistory',[message]);await wait();
const row=document.querySelector('#discussionHistory .chat-message'),body=row.querySelector('.chat-message-body'),meta=row.querySelector('.chat-message-meta');
if(row.querySelector('details')||!body.textContent.endsWith('完整回复结束'))throw Error('reply collapsed/truncated');
if(getComputedStyle(row).borderRadius!=='0px'||getComputedStyle(row).backgroundColor!=='rgba(0, 0, 0, 0)')throw Error('card boxes remain');
if(row.lastElementChild!==meta||!meta.querySelector('time[datetime]')||parseFloat(getComputedStyle(meta).fontSize)>12)throw Error('metadata not quiet footer');
if(getComputedStyle(meta).opacity!=='0')throw Error('metadata visible before hover');
row.querySelector('button').focus();await wait();if(getComputedStyle(meta).opacity!=='1')throw Error('keyboard focus did not show actions '+getComputedStyle(meta).opacity+' active='+document.activeElement.outerHTML.slice(0,100)+' connected='+row.isConnected);
let copied='';Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{copied=text;}},configurable:true});row.querySelector('button').click();await wait();if(copied!==body.textContent)throw Error('copy not full reply');
const natural=H.chatMessage('manager','[真实 DeepSeek · completed] '+JSON.stringify({done:false,report:'自然语言正文',tasks:[]}),'completed',1800000000);if(natural.querySelector('.chat-message-body').textContent!=='自然语言正文')throw Error('raw protocol JSON shown');
const live=document.getElementById('managerLiveReply');if(live.parentElement.lastElementChild!==live)throw Error('stream is not at reading bottom');
if(!live.querySelector('.chat-message-meta'))throw Error('stream footer absent');
const area=document.getElementById('managerReadingArea');area.scrollTop=80;await wait();const top=area.scrollTop;const old=row;H.list('discussionHistory',[H.chatMessage('经理 deepseek-4 · done',body.textContent,'completed',1800000000)]);await wait();if(document.querySelector('#discussionHistory .chat-message')!==old||Math.abs(area.scrollTop-top)>2)throw Error('poll moved/rebuilt reader');
const send=document.getElementById('discussionSend');if(innerWidth>=680&&send.getBoundingClientRect().bottom>innerHeight+2)throw Error('composer clipped');
"""
class Browser(unittest.TestCase):
 @unittest.skipUnless(base.base.m.EDGE.exists(),'Edge unavailable')
 def test_expanded_flat_chat_footer_copy_and_live_tail(self):
  old=base.base.DRIVER;base.base.DRIVER=old.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  server=base.base.Server(('127.0.0.1',0),base.Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   for size in ['1440,900','1024,600','600,800']:
    with self.subTest(size=size),tempfile.TemporaryDirectory() as folder:
     r=subprocess.run([str(base.base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size='+size,'--user-data-dir='+folder,'--dump-dom','--virtual-time-budget=8000','http://127.0.0.1:'+str(server.server_port)+'/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
     match=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(match);self.assertTrue(match.group(1).startswith('PASS'),match.group(1));print('PASS expanded prose, flat separators, footer focus/copy and live tail at '+size)
  finally:server.shutdown();server.server_close();thread.join();base.base.DRIVER=old
