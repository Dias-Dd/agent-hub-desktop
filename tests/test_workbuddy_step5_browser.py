import json
from unittest.mock import patch
import test_nine_browser as base
CONNECTION={'id':'workbuddy-local','name':'WorkBuddy','kind':'workbuddy','installed':True,'enabled':False,'permission':'full','models':[{'id':'step-5-preview','name':'Step-5 Preview','source':'user_confirmed_client_model','efforts':['default'],'inference_verified':False}],'probe_detail':'official catalog'}
class Fixture(base.Fixture):
 def respond(self,status,body,*args,**kwargs):
  if isinstance(body,dict) and 'agents' in body:body['integrations']={'connections':[CONNECTION],'agents':[]}
  return super().respond(status,body,*args,**kwargs)
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
  self.respond(200,{'result':CONNECTION if body.get('action')=='integration_probe' else {}})
class Browser(base.Browser):
 def test_nine(self):
  extra="document.getElementById('openIntegrations').click();document.getElementById('newIntegrationAgent').click();document.getElementById('wizardNext').click();await new Promise(r=>setTimeout(r,300));const select=document.getElementById('agentModel');if(![...select.options].some(o=>o.value==='step-5-preview'&&o.textContent.includes('Step-5 Preview')))throw Error('Step not visible in actual wizard');if(!document.getElementById('wizardModelHint').textContent.includes('客户端'))throw Error('client model source missing');if(document.getElementById('wizardEnableConnection').checked)throw Error('connection was silently enabled');"
  with patch.object(base,'Fixture',Fixture),patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS nine",extra+"out.textContent='PASS Step-5 visible in wizard; nine")):super().test_nine()
