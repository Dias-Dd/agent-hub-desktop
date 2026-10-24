import unittest,subprocess,tempfile,re,threading,json
import test_nine_browser as base
class Fixture(base.Fixture):
 efforts={};requests=[]
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   body['projects']=[{'id':'p1','name':'First project'},{'id':'p2','name':'Second project'}]
   body['selected_project']=self.headers.get('X-Hub-Project') or 'p1'
   body['deepseek']['efforts']={f'deepseek-{i}':self.efforts.get(f'deepseek-{i}','high') for i in range(1,10)}
  super().respond(status,body,kind)
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));self.requests.append(body)
  if body.get('action')=='agent_set_effort':self.efforts[body['args']['agent']]=body['args']['effort']
  self.respond(200,{'result':{'ok':True}})
CHECK=r"""
const rail=document.getElementById('activityRail'),sidebar=document.getElementById('sidebarLeft');
if(rail.getBoundingClientRect().width>60||rail.getBoundingClientRect().right>sidebar.getBoundingClientRect().left+1)throw Error('rail not narrow or leftmost');
for(const id of ['btnViewChat','btnViewStatus','toggleQuotaQuick','btnOpenConfig'])if(!document.getElementById(id).closest('#activityRail'))throw Error('navigation outside rail');
if(document.getElementById('hubProjectSelect').getClientRects().length)throw Error('project dropdown still visible');
if(document.querySelectorAll('#projectList .project-list-item').length!==2)throw Error('project list missing');
document.querySelector('[data-project-id="p2"]').click();await new Promise(r=>setTimeout(r,200));
if(H.client.getSelectedProjectId()!=='p2'||document.querySelector('#projectList [aria-current="page"]').dataset.projectId!=='p2')throw Error('project row switch failed');
document.getElementById('toggleQuotaQuick').click();if(document.getElementById('quotaQuickPanel').hidden)throw Error('quota icon failed');
document.getElementById('closeQuotaQuick').click();document.getElementById('viewModeStatusRadio').checked=true;
const choices=[...document.querySelectorAll('#agents .agent-effort-row select')];if(choices.length!==9||choices.some(c=>c.options.length!==4))throw Error('nine effort selectors missing');
choices[0].value='max';choices[0].dispatchEvent(new Event('change',{bubbles:true}));await new Promise(r=>setTimeout(r,200));
if(document.querySelector('#agents .agent-effort-row select').value!=='max')throw Error('effort choice not persisted');
"""
class EffortRail(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_rail_project_list_and_nine_effort_selectors(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS");Fixture.efforts={};Fixture.requests=[]
  s=base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   with tempfile.TemporaryDirectory() as p:
    r=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size=1425,862',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=6000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));self.assertTrue(any(r.get('action')=='agent_set_effort' for r in Fixture.requests));print('PASS narrow icon rail, project row switching, quota popup and nine effort selectors')
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
