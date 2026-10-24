import json,re,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import test_nine_browser as base
from test_vm_settings_browser import Fixture as VMFixture
CHECK=r"""
await new Promise(r=>setTimeout(r,5500));
if(document.getElementById('vmThumbnail').hidden)throw Error('startup thumbnail not prefetched before opening settings');
const toggle=document.getElementById('configModalToggle');toggle.checked=true;toggle.dispatchEvent(new Event('change'));await new Promise(r=>setTimeout(r,200));
const title=document.getElementById('configModalTitle');if(title.getBoundingClientRect().height>2||document.querySelector('#configModal .eyebrow'))throw Error('duplicate settings heading still visible');
if(document.querySelector('.storage-directory-details summary,.vm-credentials-details summary'))throw Error('fixed sections still collapsible');
const button=document.getElementById('storageRefresh');if(button.getBoundingClientRect().height>36)throw Error('settings action remains oversized');
document.querySelector('[aria-controls=storageSettings]').click();await new Promise(r=>setTimeout(r,150));
if(document.querySelectorAll('.storage-project-group').length!==2||!document.querySelector('.storage-project-badge.is-retained')||!document.querySelector('.storage-project-badge.is-removed'))throw Error('storage removal groups indistinguishable');
document.querySelector('.storage-project-actions button:last-child').click();await new Promise(r=>setTimeout(r,120));
const cleanup=document.getElementById('projectCleanupDialog'),confirm=cleanup.querySelector('.danger-btn');confirm.click();await new Promise(r=>setTimeout(r,80));
if(window.cleanupWrites||!cleanup.open||!confirm.textContent.includes('确认清理'))throw Error('retained project missing extra confirmation');
confirm.click();await new Promise(r=>setTimeout(r,150));if(window.cleanupWrites!==1)throw Error('cleanup not submitted once after confirmation');
document.querySelector('[aria-controls=colorSettings]').click();
const colorInput=document.querySelector('#interfaceColors input[data-token="--accent"]');if(!colorInput)throw Error('color menu absent');
colorInput.value='#735599';colorInput.dispatchEvent(new Event('input',{bubbles:true}));if(document.documentElement.style.getPropertyValue('--accent')!=='#735599')throw Error('color preview not applied');
document.querySelector('#interfaceColors .interface-color-button').click();
const picker=document.getElementById('interfaceColorPicker');if(!picker.matches(':popover-open')||document.querySelector('#interfaceColors input[type=color]'))throw Error('custom picker not used');
const hex=picker.querySelector('.color-hex');hex.value='#315577';hex.dispatchEvent(new Event('input',{bubbles:true}));if(document.documentElement.style.getPropertyValue('--bg-app')!=='#315577')throw Error('custom hex edit failed');
picker.hidePopover();
document.getElementById('resetInterfaceColors').click();if(document.documentElement.style.getPropertyValue('--accent'))throw Error('color reset failed');
document.querySelector('[aria-controls=vmSettings]').click();await new Promise(r=>setTimeout(r,350));
const canvas=document.getElementById('vmThumbnail');if(canvas.hidden)throw Error('thumbnail not rendered');
const pixels=canvas.getContext('2d').getImageData(0,0,2,1).data;if(pixels[0]!==255||pixels[1]!==0||pixels[4]!==0||pixels[5]!==255)throw Error('RGB565 colors incorrect');
const calls=window.thumbnailCalls||0;document.querySelector('[aria-controls=storageSettings]').click();document.getElementById('vmThumbnailRefresh').click();await new Promise(r=>setTimeout(r,40));if(window.thumbnailCalls!==calls)throw Error('thumbnail polled while hidden');
document.getElementById('vmOpenManager').click();await new Promise(r=>setTimeout(r,80));if(!window.managerOpened)throw Error('official manager entry not called');
const surface=document.querySelector('.workbench-content-surface');if(!surface.contains(document.getElementById('workbenchCenter'))||!surface.contains(document.getElementById('sidebarRight'))||parseFloat(getComputedStyle(surface).borderRadius)<10)throw Error('shared content surface missing');
document.querySelector('[aria-controls=vmSettings]').click();
"""
class Fixture(VMFixture):
 def do_GET(self):
  if self.path=='/':return self.respond(200,(Path(__file__).parents[1]/'hub/static/index.html').read_text(encoding='utf-8').replace('<head>','<head><script src="/driver.js" defer></script>'),'text/html')
  super().do_GET()
 def do_POST(self):
  size=int(self.headers.get('Content-Length',0));body=self.rfile.read(size);data=json.loads(body or '{}');action=data.get('action');args=data.get('args',{})
  if action=='vm_control' and args.get('action')=='thumbnail':return self.respond(200,{'result':{'request_id':'thumb'}})
  if action=='vm_control' and args.get('action')=='open_manager':return self.respond(200,{'result':{'state':'completed','opened':True}})
  if action=='vm_control' and args.get('action')=='result' and args.get('request_id')=='thumb':return self.respond(200,{'result':{'state':'completed','available':True,'vm':'Hub','format':'rgb565le','width':2,'height':1,'image_data':'APjgBw=='}})
  if action=='project_cleanup':return self.respond(200,{'result':{'ok':True} if args.get('confirmed') else {'project_id':'p','removed':False,'inventory_key':'fixture','paths':[{'kind':'项目目录','path':r'C:\HubProjects\weather','exists':True}]}})
  if action=='project_storage':return self.respond(200,{'result':{'root':args.get('path',r'C:\HubProjects'),'disk_free':20000000000,'disk_total':100000000000,'projects':[{'id':'p','name':'天气应用','cwd':r'C:\HubProjects\weather','bytes':12345678,'files':42,'exists':True},{'id':'removed','name':'已移除示例','cwd':r'C:\HubProjects\old','bytes':0,'files':0,'exists':False,'removed':True}]}})
  if action=='artifact_open_folder':return self.respond(200,{'result':{'opened':True}})
  self.rfile=__import__('io').BytesIO(body);super().do_POST()
@unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
class Browser(unittest.TestCase):
 def test_settings_links_and_completed_startup(self):
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   driver=base.DRIVER.replace("out.textContent='PASS","const oldPost=H.client.postAction.bind(H.client);H.client.postAction=async(a,b)=>{if(a==='vm_control'&&b.action==='thumbnail')window.thumbnailCalls=(window.thumbnailCalls||0)+1;if(a==='project_cleanup'&&b.confirmed)window.cleanupWrites=(window.cleanupWrites||0)+1;if(a==='vm_control'&&b.action==='open_manager')window.managerOpened=true;return oldPost(a,b);};"+CHECK+"out.textContent='PASS")
   # Observe only our test action, retaining normal client behavior.
   driver=driver.replace('const toggle=',"const origPost=H.client.postAction.bind(H.client);H.client.postAction=async(a,b)=>{const r=await origPost(a,b);if(a==='artifact_open_folder')window.folderOpened=true;return r;};const toggle=")
   with patch.object(base,'DRIVER',driver):
    for width,height in [(1440,900),(600,800)]:
     result=base.browser_run([str(base.m.EDGE),f'--window-size={width},{height}',f'http://127.0.0.1:{server.server_port}/'],timeout=30,screenshot=Path(__file__).parents[1]/'data'/('settings-preview-'+str(width)+'.png'))
     found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(found);self.assertTrue(found.group(1).startswith('PASS'),found.group(1));print('PASS settings, storage draft, folder action, review button and completed startup',width,height)
  finally:server.shutdown();server.server_close();thread.join()
