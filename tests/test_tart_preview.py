"""Decode real PNG bytes through production CSP and the actual preview renderer."""
import base64,json,re,sys,threading,time,unittest
from unittest.mock import patch
import test_nine_browser as base
from hub.tart_rfb import Console

frame=Console.__new__(Console);frame.width=2;frame.height=2;frame.frame=bytearray([17,153,221]*4)
PNG=base64.b64encode(frame.png()).decode()
CHECK=r"""
const $=id=>document.getElementById(id);
$('configModalToggle').checked=true;$('configModalToggle').dispatchEvent(new Event('change'));
$('vmSettings').closest('#configModal').querySelector('[aria-controls="vmSettings"]').click();
await window.HubDesktop.connectSavedVm();$('vmThumbnailRefresh').click();
const until=Date.now()+5000;
while($('vmThumbnail').hidden&&Date.now()<until){await new Promise(r=>setTimeout(r,50));}
if($('vmThumbnail').hidden)throw Error('PNG preview failed: '+$('vmThumbnailStatus').textContent);
const canvas=$('vmThumbnail'),pixel=[...canvas.getContext('2d').getImageData(0,0,1,1).data];
if(canvas.width!==2||canvas.height!==2||pixel.join(',')!=='17,153,221,255')throw Error('preview pixels incorrect: '+pixel);
if($('discussionReply').value!=='draft')throw Error('preview lost draft');
"""

class Fixture(base.Fixture):
 def do_POST(self):
  payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))));args=payload.get('args',{});value={}
  if payload.get('action')=='vm_control':
   if args.get('action')=='status':value={'backend':'tart','supported':True,'installed':True,'helper_alive':True,'connected':True,'vm':'mac-test','power_state':'Running','tart_home':'/tmp/test-only','max_cpu':8,'desktop':{'ready':True}}
   elif args.get('action')=='thumbnail':value={'state':'completed','available':True,'format':'png','width':2,'height':2,'image_data':PNG}
  self.respond(200,{'result':value})

class Preview(unittest.TestCase):
 def fixture(self):
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join()))
  return f'http://127.0.0.1:{server.server_port}/'

 @unittest.skipUnless(base.m.EDGE.exists(),'real browser unavailable')
 def test_chromium_preview_under_production_csp(self):
  url=self.fixture()
  with patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS").replace("'FAIL '+e.stack", "'FAIL '+e.message+' '+e.stack")):
   result=base.browser_run([str(base.m.EDGE),url],timeout=15)
   found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
   self.assertTrue(found and found.group(1).startswith('PASS'),found.group(1) if found else 'no result')

 @unittest.skipUnless(sys.platform=='darwin','WKWebView requires macOS')
 def test_webkit_preview_under_production_csp(self):
  import AppKit as A
  import Foundation as F
  import WebKit as W
  url=self.fixture()
  app=A.NSApplication.sharedApplication();app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
  config=W.WKWebViewConfiguration.alloc().init();config.setWebsiteDataStore_(W.WKWebsiteDataStore.nonPersistentDataStore())
  view=W.WKWebView.alloc().initWithFrame_configuration_(A.NSMakeRect(0,0,1080,820),config)
  window=A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(A.NSMakeRect(0,0,1080,820),A.NSWindowStyleMaskTitled,A.NSBackingStoreBuffered,False)
  window.setReleasedWhenClosed_(False);window.setContentView_(view);window.makeKeyAndOrderFront_(None);app.activateIgnoringOtherApps_(True)
  try:
   # An unbundled test host may be classified as background by WebKit.
   # This test isolates CSP/PNG rendering, not app visibility transitions.
   native_driver=base.DRIVER.replace("out.textContent='PASS", "Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});"+CHECK+"out.textContent='PASS").replace("'FAIL '+e.stack", "'FAIL '+e.message+' '+e.stack")
   with patch.object(base,'DRIVER',native_driver):
    view.loadRequest_(F.NSURLRequest.requestWithURL_(F.NSURL.URLWithString_(url)))
    end=time.monotonic()+18;value=''
    while time.monotonic()<end:
     result=[]
     view.evaluateJavaScript_completionHandler_("document.getElementById('result')?.textContent||''",lambda v,e:result.append((v,e)))
     while not result and time.monotonic()<end:F.NSRunLoop.currentRunLoop().runUntilDate_(F.NSDate.dateWithTimeIntervalSinceNow_(.02))
     self.assertTrue(result,'WK callback timeout');self.assertIsNone(result[0][1]);value=result[0][0] or ''
     if value.startswith(('PASS','FAIL')):break
     F.NSRunLoop.currentRunLoop().runUntilDate_(F.NSDate.dateWithTimeIntervalSinceNow_(.05))
    self.assertTrue(value.startswith('PASS'),value)
  finally:view.stopLoading();window.orderOut_(None);window.close()
