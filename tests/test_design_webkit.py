"""Real WKWebView raster check: an iframe marker must scale, not be cropped."""
import json
import sys
import threading
import time
import unittest

@unittest.skipUnless(sys.platform=='darwin','WKWebView is macOS only')
class DesignWebKit(unittest.TestCase):
 def test_iframe_pixels_scale_with_canvas(self):
  import AppKit as A
  import Foundation as F
  import WebKit as W
  import test_design_browser as fixture
  base=fixture.base;original=base.DRIVER
  script=r'''
  document.getElementById('openDesignReview').click();
  const until=Date.now()+10000;
  while((!document.getElementById('designFrame').contentDocument?.getElementById('far')||parseFloat(getComputedStyle(document.getElementById('designCanvas')).width)<1750)&&Date.now()<until)await new Promise(r=>setTimeout(r,50));
  if(document.getElementById('designReviewDialog').hidden)throw Error(document.getElementById('notice').textContent);
  const doc=document.getElementById('designFrame').contentDocument;
  const marker=doc.createElement('div');marker.setAttribute('style','position:absolute;left:40px;top:40px;width:200px;height:100px;background:rgb(255,0,0)');doc.body.append(marker);
  '''
  base.DRIVER=original.replace("out.textContent='PASS",script+"out.textContent='PASS")
  server=base.Server(('127.0.0.1',0),fixture.Fixture);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  app=A.NSApplication.sharedApplication()
  config=W.WKWebViewConfiguration.alloc().init()
  config.setWebsiteDataStore_(W.WKWebsiteDataStore.nonPersistentDataStore())
  view=W.WKWebView.alloc().initWithFrame_configuration_(A.NSMakeRect(0,0,1440,900),config)
  window=A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(A.NSMakeRect(0,0,1440,900),A.NSWindowStyleMaskTitled,A.NSBackingStoreBuffered,False)
  window.setReleasedWhenClosed_(False);window.setContentView_(view);window.orderFront_(None)
  def wait(result,seconds=20):
   end=time.monotonic()+seconds
   while not result and time.monotonic()<end:
    F.NSRunLoop.currentRunLoop().runUntilDate_(F.NSDate.dateWithTimeIntervalSinceNow_(.02))
   self.assertTrue(result,'WKWebView callback timeout')
  def evaluate(code):
   result=[]
   view.evaluateJavaScript_completionHandler_(code,lambda value,error:result.append((value,error)))
   wait(result);self.assertIsNone(result[0][1]);return result[0][0]
  try:
   view.loadRequest_(F.NSURLRequest.requestWithURL_(F.NSURL.URLWithString_(f'http://127.0.0.1:{server.server_port}/')))
   end=time.monotonic()+20
   while time.monotonic()<end:
    value=evaluate("document.getElementById('result')?.textContent||''")
    if str(value).startswith(('PASS','FAIL')):break
    F.NSRunLoop.currentRunLoop().runUntilDate_(F.NSDate.dateWithTimeIntervalSinceNow_(.05))
   self.assertTrue(str(value).startswith('PASS'),str(value))
   for zoom in (50,100,200):
    rect=json.loads(evaluate(f"""(()=>{{const z=document.getElementById('designZoomLevel');z.value='{zoom}';z.dispatchEvent(new Event('change'));const s=document.getElementById('designStage');s.scrollLeft=0;s.scrollTop=0;const r=s.getBoundingClientRect();return JSON.stringify([r.x,r.y,Math.min(r.width,600),Math.min(r.height,300)]);}})()"""))
    F.NSRunLoop.currentRunLoop().runUntilDate_(F.NSDate.dateWithTimeIntervalSinceNow_(.15))
    snapshot=W.WKSnapshotConfiguration.alloc().init();snapshot.setRect_(A.NSMakeRect(*rect));images=[]
    view.takeSnapshotWithConfiguration_completionHandler_(snapshot,lambda image,error:images.append((image,error)))
    wait(images);self.assertIsNone(images[0][1]);rep=A.NSBitmapImageRep.imageRepWithData_(images[0][0].TIFFRepresentation())
    width,height=rep.pixelsWide(),rep.pixelsHigh();channels=rep.samplesPerPixel();stride=rep.bytesPerRow()
    self.assertEqual(rep.bitsPerSample(),8);self.assertFalse(rep.isPlanar());self.assertGreaterEqual(channels,3)
    pixels=bytes(rep.bitmapData());xs=[];ys=[]
    for y in range(height):
     for x in range(width):
      offset=y*stride+x*channels
      if pixels[offset]>245 and pixels[offset+1]<10 and pixels[offset+2]<10:xs.append(x);ys.append(y)
    self.assertTrue(xs,'red iframe marker missing')
    ratio=width/rect[2];actual=((max(xs)-min(xs)+1)/ratio,(max(ys)-min(ys)+1)/ratio)
    self.assertAlmostEqual(actual[0],200*zoom/100,delta=3);self.assertAlmostEqual(actual[1],100*zoom/100,delta=3)
    print('PASS WKWebView iframe raster',zoom,actual)
  finally:
   window.orderOut_(None);view.stopLoading();window.close();server.shutdown();server.server_close();thread.join();base.DRIVER=original

if __name__=='__main__':unittest.main()
