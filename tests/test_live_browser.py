import json,re,subprocess,tempfile,threading,unittest
import test_nine_browser as base

class Fixture(base.Fixture):
 revision=2
 @classmethod
 def draft(cls):return '{"done":false,"report":"开头 '+('公开回复内容 '*180)+(' 后续流式' if cls.revision>=3 else '')
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   project=self.headers.get('X-Hub-Project') or 'p';body['selected_project']=project;body['projects']=[{'id':project,'name':'stream fixture'}]
   body['quota_overview']=[{'id':'deepseek','name':'DeepSeek','windows':[],'balances':[{'account':'API','name':'余额','amount':'25.50','currency':'CNY'}],'unreadable':['Harness'],'refreshable':[]},{'id':'openai','name':'OpenAI / Codex','windows':[{'account':'account','name':'5小时','remaining':65,'resets_at':1800000000,'source':'official'}],'balances':[],'unreadable':[],'refreshable':[]}]
   body['planning']=[{'id':'plan','project_id':'p','manager':'deepseek-4','state':'thinking','pending':'live','revision':1,'history':[{'role':'user','text':'plan please','created':1}],'options':{}}] if project=='p' else []
   body['workflows']=[];body['deepseek']['runs']=[{'id':'live','agent':'deepseek-4','status':'running','created':2,'purpose':'discussion'}] if project=='p' else []
   body['live_replies']=[{'run_id':'live','revision':self.revision,'status':'running','text':self.draft(),'summary':'公开思考摘要：先核对页面要求。','phase':'正在生成回复'}] if project=='p' else []
  return super().respond(status,body,kind)
 def do_GET(self):
  if self.path.startswith('/api/reply-stream?'):
   values=[{'run_id':'live','revision':1,'status':'running','text':'{"done":false,"report":"开头','summary':'公开思考摘要','phase':'正在生成回复'},{'run_id':'live','revision':2,'status':'running','text':self.draft(),'summary':'公开思考摘要：先核对页面要求。','phase':'正在生成回复'}]
   return self.respond(200,''.join('data: '+json.dumps(v,ensure_ascii=False)+'\n\n' for v in values),'text/event-stream')
  return super().do_GET()
 def do_POST(self):
  if self.path=='/fixture-append':Fixture.revision=3
  return self.respond(200,{'result':{}})

CHECK="""
const wait=()=>new Promise(r=>setTimeout(r,100));for(let i=0;i<10&&!document.getElementById('managerLiveText').textContent;i++)await wait();
const live=document.getElementById('managerLiveReply'),text=document.getElementById('managerLiveText'),area=document.getElementById('managerReadingArea');
if(live.hidden||!text.textContent.startsWith('开头')||text.textContent.includes('"done"'))throw Error('public draft extraction failed');
if(H.view.managerStream.planning.canApprove||!document.getElementById('approvePlan').hidden)throw Error('unfinished draft approved');
if(!document.getElementById('managerLiveSummaryText').textContent.includes('公开思考摘要'))throw Error('summary not displayed');
document.getElementById('toggleQuotaQuick').click();if(document.querySelectorAll('#providerQuotaList .provider-quota').length!==2)throw Error('providers not grouped');
const quota=document.getElementById('providerQuotaList').textContent;if(!quota.includes('25.50 CNY')||!quota.includes('65%')||quota.includes('DeepSeek 工程组'))throw Error('quota overview incorrect');document.getElementById('closeQuotaQuick').click();
document.getElementById('discussionReply').value='preserve draft';const old=text.querySelector('p').firstChild;const range=document.createRange();range.setStart(old,0);range.setEnd(old,2);getSelection().removeAllRanges();getSelection().addRange(range);area.scrollTop=30;const top=area.scrollTop;
await fetch('/fixture-append',{method:'POST'});await H.store.refresh(true);
if(!old.isConnected||text.querySelector('p').firstChild!==old||getSelection().toString()!=='开头'||!text.textContent.includes('后续流式')||Math.abs(area.scrollTop-top)>2)throw Error('stream update lost reading/selection '+JSON.stringify({same:old.isConnected,selection:getSelection().toString(),appended:text.textContent.includes('后续流式'),top,now:area.scrollTop}));
const button=document.getElementById('discussionSend');if(innerWidth>=680&&button.getBoundingClientRect().bottom>innerHeight+2)throw Error('composer pushed away');
await H.chooseProject('q');if(!live.hidden)throw Error('old project stream leaked: '+H.client.getSelectedProjectId()+' / '+H.store.rawState?.selected_project+' / '+H.store.lastError);
"""
class Browser(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_live_draft_quota_selection_and_project_isolation(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  s=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=s.serve_forever);thread.start()
  try:
   for size in ['1440,900','1024,600','600,800']:
    Fixture.revision=2
    with self.subTest(size=size),tempfile.TemporaryDirectory() as folder:
     r=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size='+size,'--user-data-dir='+folder,'--dump-dom','--virtual-time-budget=6000','http://127.0.0.1:'+str(s.server_port)+'/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
     result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print('PASS quota grouping, live draft, no early approval, selection and project isolation at '+size)
  finally:s.shutdown();s.server_close();thread.join();base.DRIVER=original
