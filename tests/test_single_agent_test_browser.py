import json
from unittest.mock import patch
import test_connection_tests_browser as fixtures
import test_nine_browser as base
class Fixture(fixtures.Fixture):
 requests=[]
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
  if data.get('action')=='integration_test_all':self.requests.append(data.get('args'));return self.respond(200,{'result':{'started':True,'count':1}})
  return self.respond(200,{'result':{}})
class Browser(base.Browser):
 def test_nine(self):
  extra="""const card=document.querySelector('[data-agent="deepseek-1"]');card.querySelector('[data-test-agent="deepseek-1"]').click();const dialog=document.getElementById('connectionTestDialog');if(!dialog.open||!dialog.querySelector('h2').textContent.includes('deepseek-1'))throw Error('single confirmation missing identity');if(!dialog.textContent.includes('1 个 Agent'))throw Error('wrong test count');[...dialog.querySelectorAll('button')].find(b=>b.textContent==='开始真实测试').click();await new Promise(r=>setTimeout(r,200));if(dialog.open)throw Error('single test failed to start');if(document.getElementById('verifyIntegrationsHeader').textContent!=='全部测试')throw Error('batch entry removed');"""
  Fixture.requests=[]
  with patch.object(base,'Fixture',Fixture),patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS nine",extra+"out.textContent='PASS single and all tests coexist; nine")):super().test_nine()
  self.assertEqual(Fixture.requests,[{'confirmed':True,'agent_id':'deepseek-1'}])
