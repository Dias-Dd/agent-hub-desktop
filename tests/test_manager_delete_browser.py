from unittest.mock import patch
import test_nine_browser as base
class Fixture(base.Fixture):
 def respond(self,status,body,*args,**kwargs):
  if isinstance(body,dict) and 'agents' in body:
   body['selected_manager']='deepseek-1';body['workflows'][0]['status']='completed'
   body['integrations']={'connections':[],'agents':[{'id':'deepseek-'+str(i),'name':'DeepSeek '+str(i),'enabled':True,'model':'deepseek-flash','connection_id':'deepseek-default'} for i in range(1,10)],'manager_projects':{}}
  return super().respond(status,body,*args,**kwargs)
class Browser(base.Browser):
 def test_nine(self):
  extra="if(document.querySelector('[data-remove-agent=deepseek-4]').disabled)throw Error('former default manager remains locked');if(!document.querySelector('[data-remove-agent=deepseek-1]').disabled)throw Error('current manager unprotected');"
  driver=base.DRIVER.replace("H.view.managerStream.manager!=='deepseek-4'","H.view.managerStream.manager!=='deepseek-1'").replace("out.textContent='PASS nine",extra+"out.textContent='PASS dynamic deletion controls; nine")
  with patch.object(base,'Fixture',Fixture),patch.object(base,'DRIVER',driver):super().test_nine()
