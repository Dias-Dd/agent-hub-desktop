import json,re,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import test_nine_browser as base
from test_vm_settings_browser import Fixture as VMFixture
CHECK=r"""
const toggle=document.getElementById('configModalToggle');toggle.checked=true;toggle.dispatchEvent(new Event('change'));
await new Promise(r=>setTimeout(r,250));
if(!document.getElementById('storageRoot').value.includes('HubProjects'))throw Error('storage root absent');
if(!document.querySelector('#storageProjects .storage-project-row'))throw Error('project storage absent');
document.getElementById('storageRoot').value='C:\MyNewProjects';document.getElementById('storageRoot').dispatchEvent(new Event('input'));
await H.store.refresh(true);if(document.getElementById('storageRoot').value!=='C:\MyNewProjects')throw Error('storage draft overwritten');
document.getElementById('storageForm').dispatchEvent(new Event('submit',{cancelable:true}));await new Promise(r=>setTimeout(r,200));
if(!document.getElementById('storageStatus').textContent.includes('已保存'))throw Error('storage save failed');
document.querySelector('[aria-controls=vmSettings]').click();document.querySelector('.vm-credentials-details').open=true;document.getElementById('vmSettings').scrollIntoView({block:'center'});
const modal=document.querySelector('.config-modal-dialog'),area=document.querySelector('.settings-content');
if(modal.getBoundingClientRect().width>innerWidth||area.scrollWidth>area.clientWidth+2)throw Error('settings horizontal clipping');
const longContent=document.createElement('p');longContent.textContent=('长设置说明\n').repeat(300);longContent.style.whiteSpace='pre-wrap';document.getElementById('vmSettings').append(longContent);if(area.scrollHeight<=area.clientHeight)throw Error('settings scroll unavailable');longContent.remove();
const button=document.getElementById('openDesignReview');button.hidden=false;button.disabled=false;
const old=document.getElementById('designStatusCard').hidden;document.getElementById('designStatusCard').hidden=false;
if(parseFloat(getComputedStyle(button).minHeight)<44)throw Error('review target too small');document.getElementById('designStatusCard').hidden=old;
const item={id:'a'.repeat(64),kind:'folder',caption:'交付文件夹',path:'C:\HubProjects\demo\dist',url:'/api/folder/'+'a'.repeat(64),sender:'deepseek-4',created:1};
const card=H.artifactMessage(item);document.body.append(card);card.querySelector('a').click();await new Promise(r=>setTimeout(r,150));
if(!window.folderOpened)throw Error('folder link did not open through action');card.remove();
// Run the desktop-only progress controller against a completed startup fixture.
const originalFetch=window.fetch;window.fetch=(url,options)=>String(url)==='/startup-status'?Promise.resolve(new Response(JSON.stringify({stages:{server:{state:'ready',label:'服务'},agents:{state:'ready',label:'模型'},vm:{state:'ready',label:'虚拟机'}}}),{status:200,headers:{'Content-Type':'application/json'}})):originalFetch(url,options);
const meta=document.createElement('meta');meta.name='hub-desktop-session';meta.content='fixture';document.head.append(meta);
const script=document.createElement('script');script.src='/startup.js';document.head.append(script);await new Promise(r=>setTimeout(r,200));
if(!document.getElementById('startupProgress').hidden)throw Error('completed loading bar remains visible');
"""
class Fixture(VMFixture):
 def do_GET(self):
  if self.path=='/':return self.respond(200,(Path(__file__).parents[1]/'hub/static/index.html').read_text(encoding='utf-8').replace('<head>','<head><script src="/driver.js" defer></script>'),'text/html')
  super().do_GET()
 def do_POST(self):
  size=int(self.headers.get('Content-Length',0));body=self.rfile.read(size);data=json.loads(body or '{}');action=data.get('action');args=data.get('args',{})
  if action=='project_storage':return self.respond(200,{'result':{'root':args.get('path',r'C:\HubProjects'),'disk_free':20000000000,'disk_total':100000000000,'projects':[{'id':'p','name':'天气应用','cwd':r'C:\HubProjects\weather','bytes':12345678,'files':42,'exists':True}]}})
  if action=='artifact_open_folder':return self.respond(200,{'result':{'opened':True}})
  self.rfile=__import__('io').BytesIO(body);super().do_POST()
@unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
class Browser(unittest.TestCase):
 def test_settings_links_and_completed_startup(self):
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   driver=base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
   # Observe only our test action, retaining normal client behavior.
   driver=driver.replace('const toggle=',"const origPost=H.client.postAction.bind(H.client);H.client.postAction=async(a,b)=>{const r=await origPost(a,b);if(a==='artifact_open_folder')window.folderOpened=true;return r;};const toggle=")
   with patch.object(base,'DRIVER',driver):
    for width,height in [(1440,900),(600,800)]:
     result=base.browser_run([str(base.m.EDGE),f'--window-size={width},{height}',f'http://127.0.0.1:{server.server_port}/'],timeout=30,screenshot=Path(__file__).parents[1]/'data'/('settings-preview-'+str(width)+'.png'))
     found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(found);self.assertTrue(found.group(1).startswith('PASS'),found.group(1));print('PASS settings, storage draft, folder action, review button and completed startup',width,height)
  finally:server.shutdown();server.server_close();thread.join()
