from unittest.mock import patch
import test_nine_browser as base
class Fixture(base.Fixture):
 def respond(self,status,body,*args,**kwargs):
  if isinstance(body,dict) and 'agents' in body:
   body['agents'][0]['profile']={'id':'deepseek-1','name':'自定义测试工程师','model':'DeepSeek Flash','connection_id':'deepseek-default','enabled':True};body['integrations']={'connections':[],'agents':[]}
  return super().respond(status,body,*args,**kwargs)
class Browser(base.Browser):
 def test_nine(self):
  extra="const mini=document.getElementById('agentMiniStates');if(!mini.textContent.includes('自定义测试工程师'))throw Error('mini status lost display name');"
  with patch.object(base,'Fixture',Fixture),patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS nine",extra+"out.textContent='PASS mini display names; nine")):super().test_nine()
