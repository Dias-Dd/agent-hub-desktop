import json
from unittest.mock import patch
import test_nine_browser as base
class Fixture(base.Fixture):
 def respond(self,status,body,*args,**kwargs):
  if isinstance(body,dict) and 'agents' in body:
   body['integrations']={'connections':[],'agents':[{'id':'deepseek-1','name':'Test Agent','model':'fixture','effort':'default','connection_id':'fixture','enabled':True}],'test_results':{'deepseek-1':{'status':'passed','detail':'真实回复验证通过','reply':'连接成功','model':'fixture','effort':'default','created':1,'elapsed_ms':1200}}}
  return super().respond(status,body,*args,**kwargs)
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
  if data.get('action')=='integration_test_all':
   if data.get('args',{}).get('confirmed') is not True:return self.respond(400,{'error':'confirmation missing'})
   return self.respond(200,{'result':{'started':True,'count':1}})
  return self.respond(200,{'result':{}})
class Browser(base.Browser):
 def test_nine(self):
  extra="""const card=document.querySelector('[data-agent="deepseek-1"]');if(!card.querySelector('.agent-test-status')?.textContent.includes('测试通过'))throw Error('per-agent result absent');if(!card.querySelector('.agent-test-result')?.textContent.includes('连接成功'))throw Error('details missing reply');document.getElementById('verifyIntegrationsHeader').click();const dialog=document.getElementById('connectionTestDialog');if(!dialog.open||!dialog.textContent.includes('API 余额'))throw Error('inference confirmation missing');[...dialog.querySelectorAll('button')].find(b=>b.textContent==='开始真实测试').click();await new Promise(r=>setTimeout(r,200));if(dialog.open)throw Error('batch did not start');"""
  with patch.object(base,'Fixture',Fixture),patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS nine",extra+"out.textContent='PASS batch test confirmation/results; nine")):super().test_nine()
