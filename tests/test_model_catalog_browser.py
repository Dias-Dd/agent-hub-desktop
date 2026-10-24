from unittest.mock import patch
import test_workbuddy_step5_browser as wb
import test_nine_browser as base
class Fixture(wb.Fixture):
 def respond(self,status,body,*args,**kwargs):
  if isinstance(body,dict) and ('agents' in body or 'result' in body):
   wb.CONNECTION['candidate_models']=[{'id':'hidden-candidate','source':'official_installed_catalog'}]
   wb.CONNECTION['probe_detail']='CLI 目录可能少于客户端'
  return super().respond(status,body,*args,**kwargs)
class Browser(base.Browser):
 def test_nine(self):
  extra="""document.getElementById('openIntegrations').click();document.getElementById('newIntegrationAgent').click();document.getElementById('wizardNext').click();await new Promise(r=>setTimeout(r,300));const sel=document.getElementById('agentModel');if([...sel.options].some(o=>o.value==='hidden-candidate'))throw Error('candidate leaked into default menu');const toggle=document.getElementById('showCandidateModels');toggle.checked=true;toggle.dispatchEvent(new Event('change'));if(![...sel.options].some(o=>o.value==='hidden-candidate'&&o.textContent.includes('未验证')))throw Error('candidate source missing');toggle.checked=false;toggle.dispatchEvent(new Event('change'));if([...sel.options].some(o=>o.value==='hidden-candidate'))throw Error('candidate did not disappear');if(document.getElementById('wizardEnableConnection').checked)throw Error('silently enabled');"""
  with patch.object(base,'Fixture',Fixture),patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS nine",extra+"out.textContent='PASS separated catalogs; nine")):super().test_nine()
