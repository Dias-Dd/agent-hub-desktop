import re,threading,unittest
from unittest.mock import patch
import test_nine_browser as base
class Fixture(base.Fixture):
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'all_deepseek' in body:
   body['integrations']={'connections':[{'id':'deepseek-default','name':'DeepSeek Harness','kind':'deepseek-harness','legacy':True,'models':[]}],'manager_projects':{},'agents':[{'id':f'deepseek-{i}','name':f'DeepSeek {i}','enabled':True,'connection_id':'deepseek-default','model':'deepseek-flash','role':'工程师','effort':'high',**({'model_status':{'detail':'model variant has been retired'}} if i==1 else {})} for i in range(1,10)]}
  return super().respond(status,body,kind)
class UI(unittest.TestCase):
 def test_unavailable_model_is_distinct_from_quota_and_healthy_agents(self):
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   check="""const retired=H.view.agents.find(a=>a.id==='deepseek-1');if(!retired.modelUnavailable||retired.quotaExhausted)throw Error('model state confused with quota');if(H.view.agents.find(a=>a.id==='deepseek-2').modelUnavailable)throw Error('healthy model disabled');const card=document.querySelector('.agent-box[data-agent="deepseek-1"]');if(!card.classList.contains('model-unavailable')||!card.textContent.includes('模型不可用'))throw Error('model card missing state');const mini=[...document.querySelectorAll('#agentMiniStates .agent-mini-row')].find(x=>x.title.includes('模型不可用'));if(!mini?.classList.contains('offline'))throw Error('mini state not offline');"""
   with patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS",check+"out.textContent='PASS")):
    result=base.browser_run([str(base.m.EDGE),'--window-size=1440,900',f'http://127.0.0.1:{server.server_port}/'],timeout=30)
   found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertTrue(found and found.group(1).startswith('PASS'),found.group(1) if found else 'no result')
  finally:server.shutdown();server.server_close();thread.join()
