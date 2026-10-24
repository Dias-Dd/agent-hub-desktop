import json,re,subprocess,tempfile,threading,unittest
import test_nine_browser as base
CHECK=r"""
const card=document.querySelector('#agents [data-agent="deepseek-2"]');
if(!card.classList.contains('quota-exhausted')||!card.textContent.includes('额度耗尽'))throw Error('exhausted card not grey');
const mini=[...document.querySelectorAll('#agentMiniStates .agent-mini-row')].find(x=>x.textContent.includes('deepseek-2'));
if(!mini||!mini.classList.contains('quota-exhausted'))throw Error('mini not grey');
if(document.querySelector('#agents [data-agent="deepseek-1"]').classList.contains('quota-exhausted'))throw Error('healthy member greyed');
if(!document.getElementById('quotaDisasterBanner').hidden)throw Error('red quota banner still visible');
if(document.querySelectorAll('#timerList .timer-row').length!==1)throw Error('delivered timer retained');
if(!document.querySelector('#timerList [data-timer="pending-timer"]'))throw Error('active timer missing');
"""
class Fixture(base.Fixture):
 def respond(self,code,data,kind='application/json'):
  if self.path=='/api/state' and isinstance(data,dict):
   profiles=[{'id':a['id'],'name':a['id'],'model':a['model'],'enabled':True,'connection_id':'deepseek-default','role':'工程师','effort':'high','quota_status':{'exhausted':a['id']=='deepseek-2'}} for a in data['agents']]
   data['integrations']={'agents':profiles,'connections':[],'kinds':[]};data['agents']=[{**a,'profile':next(p for p in profiles if p['id']==a['id'])} for a in data['agents']]
   data['deepseek']['runs']=[{'id':'quota-run','agent':'deepseek-3','status':'waiting_quota'}]
   common={'project_id':'default','workflow_id':'w','creator':'deepseek-4','recipient':'deepseek-1','note':'test','condition':'time','due':9999999999,'created':1,'updated':1,'generation':1}
   data['timers']=[{**common,'id':'pending-timer','state':'scheduled'},{**common,'id':'old-timer','state':'finished'}]
  return super().respond(code,data,kind)
class QuotaUI(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_exhausted_cards_mini_no_red_popup_and_finished_timers_hidden(self):
  old=base.DRIVER;base.DRIVER=old.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   with tempfile.TemporaryDirectory() as folder:
    r=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--user-data-dir={folder}','--dump-dom','--virtual-time-budget=5000',f'http://127.0.0.1:{server.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1))
  finally:server.shutdown();server.server_close();thread.join();base.DRIVER=old
