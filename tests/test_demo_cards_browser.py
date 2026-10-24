import test_nine_browser as base
from unittest.mock import patch
class Fixture(base.Fixture):
 def do_GET(self):
  if self.path.startswith('/api/shared/'):return self.respond(200,'<p>Fixture artifact</p>','text/html')
  return super().do_GET()
 def respond(self,status,body,*args,**kwargs):
  if isinstance(body,dict) and 'agents' in body:
   body['workflows']=[{'id':'normal','manager':'deepseek-4','status':'paused','created':1},{'id':'demo','manager':'deepseek-4','status':'paused','created':3,'design_review':'review-id'}]
   body['shared_artifacts']=[{'id':c*64,'kind':kind,'sender':'deepseek-4','created':created,'caption':caption,'url':'/api/shared/'+c*64+'/index.html'} for c,kind,created,caption in [('a','webpage',2,'Normal webpage'),('b','webpage',4,'Demo page'),('c','image',4,'Normal image')]]
  return super().respond(status,body,*args,**kwargs)
class Browser(base.Browser):
 def test_nine(self):
  extra="const cards=document.getElementById('discussionHistory');if(cards.querySelectorAll('.shared-artifact').length!==2||cards.textContent.includes('Demo page')||!cards.textContent.includes('Normal webpage')||!cards.textContent.includes('Normal image'))throw Error('demo filtering lost normal artifacts');"
  with patch.object(base,'Fixture',Fixture),patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS nine",extra+"out.textContent='PASS unified demo cards; nine")):super().test_nine()
