import unittest
from unittest.mock import patch
import test_nine_browser as base

class DynamicParticipants(base.Browser):
 def test_nine(self):
  original=base.Fixture.respond
  def respond(handler,status,data,*args,**kwargs):
   if isinstance(data,dict) and 'all_deepseek' in data:
    data['selected_manager']='deepseek-2';data['workflows'][0]['manager']='deepseek-2'
   return original(handler,status,data,*args,**kwargs)
  driver=base.DRIVER.replace("manager!=='deepseek-4'","manager!=='deepseek-2'")
  driver=driver.replace('#workflowAgents input[value="deepseek-4"]','#workflowAgents input[value="deepseek-2"]')
  driver=driver.replace("if(!document.querySelector('#workflowAgents input[value=\"deepseek-1\"]'))", "if(!document.querySelector('#workflowAgents input[value=\"deepseek-4\"]'))")
  with patch.object(base.Fixture,'respond',respond),patch.object(base,'DRIVER',driver):super().test_nine()
