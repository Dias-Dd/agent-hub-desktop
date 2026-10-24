import io,json,re,threading,unittest
from pathlib import Path
from unittest.mock import patch
import test_nine_browser as base
from test_settings_refresh_browser import Fixture as SettingsFixture
CHECK=r"""
H.client.setSelectedProjectId('p');
const originalPost=H.client.postAction.bind(H.client);let graphCalls=0,cleanCalls=0,failGraph=false;
H.client.postAction=async(a,b)=>{if(a==='project_git_tree'){graphCalls++;if(failGraph)throw Error('fixture offline');}if(a==='project_cleanup'&&b.confirmed)cleanCalls++;return originalPost(a,b);};
const toggle=document.getElementById('configModalToggle');toggle.checked=true;toggle.dispatchEvent(new Event('change'));await new Promise(r=>setTimeout(r,250));
document.querySelector('[aria-controls=storageSettings]').click();
const nav=document.querySelector('.settings-navigation').getBoundingClientRect(),content=document.querySelector('.settings-content').getBoundingClientRect();
if(nav.right>content.left+2||content.width<200)throw Error('settings columns overlap');
const clean=[...document.querySelectorAll('#storageProjects button')].find(b=>b.textContent==='清理文件');if(!clean)throw Error('cleanup button missing');clean.click();await new Promise(r=>setTimeout(r,150));
const dialog=document.getElementById('projectCleanupDialog');if(!dialog.open||!dialog.textContent.includes('项目会保留')||!dialog.textContent.includes('git-worktrees'))throw Error('cleanup preview absent');if(cleanCalls)throw Error('deleted before confirmation');
[...dialog.querySelectorAll('button')].find(b=>b.textContent==='取消').click();if(cleanCalls)throw Error('cancel deleted files');
clean.click();await new Promise(r=>setTimeout(r,100));[...dialog.querySelectorAll('button')].find(b=>b.textContent==='清理全部文件').click();await new Promise(r=>setTimeout(r,180));if(cleanCalls!==1||dialog.open)throw Error('confirmation failed');
toggle.checked=false;toggle.dispatchEvent(new Event('change'));
const drawer=document.getElementById('projectGitDrawer');document.getElementById('tabProjectStatus').click();await new Promise(r=>setTimeout(r,150));
if(!document.getElementById('projectGitGraph').textContent.includes('worker implementation'))throw Error('graph missing');
const graph=document.getElementById('projectGitGraph');graph.scrollLeft=20;const scrollBefore=graph.scrollLeft;document.getElementById('refreshProjectGit').click();await new Promise(r=>setTimeout(r,100));if(graph.scrollLeft!==scrollBefore)throw Error('unchanged graph scroll reset');
failGraph=true;document.getElementById('refreshProjectGit').click();await new Promise(r=>setTimeout(r,100));if(!graph.textContent.includes('worker implementation')||!document.getElementById('projectGitStatus').textContent.includes('保留'))throw Error('offline cleared graph');failGraph=false;
const before=graphCalls;await new Promise(r=>setTimeout(r,5100));if(graphCalls<=before)throw Error('automatic refresh missing');document.getElementById('tabManagerChat').click();await new Promise(r=>setTimeout(r,100));const closed=graphCalls;await new Promise(r=>setTimeout(r,5100));if(graphCalls!==closed)throw Error('closed graph still polling');
toggle.checked=true;toggle.dispatchEvent(new Event('change'));document.querySelector('[aria-controls=storageSettings]').click();
"""
class Fixture(SettingsFixture):
 def do_POST(self):
  size=int(self.headers.get('Content-Length',0));body=self.rfile.read(size);data=json.loads(body or '{}');action=data.get('action');args=data.get('args',{})
  if action=='project_cleanup':return self.respond(200,{'result':{'ok':True,'project_id':'p','name':'Fixture','removed':False,'inventory_key':'key','paths':[{'kind':'独立工作区','path':'C:/Hub/git-worktrees/p/a','exists':True}],'errors':[]} })
  if action=='project_git_tree':return self.respond(200,{'result':{'project_id':args['project_id'],'graph':'*   abc (main) integrate worker\n|\\\n| * def (worker) worker implementation '+'x'*100+'\n|/\n* baseline','workspaces':[{'agent':'deepseek-1','branch':'hub/worker'}],'updated':1}})
  self.rfile=io.BytesIO(body);super().do_POST()
@unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
class Browser(unittest.TestCase):
 def test_columns_cleanup_confirm_and_live_git(self):
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   driver=base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
   with patch.object(base,'DRIVER',driver):
    for width,height in [(1440,900),(600,800)]:
     result=base.browser_run([str(base.m.EDGE),f'--window-size={width},{height}',f'http://127.0.0.1:{server.server_port}/'],timeout=30,screenshot=Path(__file__).parents[1]/'data'/('storage-git-settings-'+str(width)+'.png'))
     found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(found);self.assertTrue(found.group(1).startswith('PASS'),found.group(1))
  finally:server.shutdown();server.server_close();thread.join()
