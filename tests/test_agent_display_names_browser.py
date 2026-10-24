import unittest
from unittest.mock import patch
import test_nine_browser as base

class Names(base.Browser):
 def test_nine(self):
  original=base.Fixture.respond
  def respond(handler,status,data,*args,**kwargs):
   if isinstance(data,dict) and 'all_deepseek' in data:
    data['integrations']={'connections':[],'kinds':[],'agents':[{'id':'agent-a5e4a441b5','name':'Gemini Flash 1','enabled':True,'connection_id':'fixture','model':'gemini-flash','effort':'medium','role':'工程师'}],'test_results':{},'manager_projects':{}}
    data['deepseek']['runs']=[{'id':'name-run','agent':'agent-a5e4a441b5','status':'running','created':1,'purpose':'task'}]
   return original(handler,status,data,*args,**kwargs)
  check="""const label=document.getElementById('operation_name-run');if(!label||label.textContent!=='Gemini Flash 1 · 正在执行任务')throw Error('internal ID visible in live operation: '+label?.textContent);if(H.agentName('agent-a5e4a441b5')!=='Gemini Flash 1')throw Error('profile name missing');const chat=H.chatMessage('经理 agent-a5e4a441b5','body','completed',1);if(chat.querySelector('.chat-message-meta').textContent.includes('agent-a5e4a441b5'))throw Error('chat metadata exposes ID');"""
  driver=base.DRIVER.replace("H.store.stopPolling();out.textContent",check+"H.store.stopPolling();out.textContent")
  with patch.object(base.Fixture,'respond',respond),patch.object(base,'DRIVER',driver):super().test_nine()
