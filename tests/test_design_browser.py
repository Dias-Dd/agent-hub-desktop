import unittest,subprocess,tempfile,re,threading,json
import test_nine_browser as base
class Fixture(base.Fixture):
 requests=[]
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   body.update(projects=[{'id':'p','name':'Demo project'}],selected_project='p',planning=[{'id':'discussion','project_id':'p','state':'designing','revision':1,'history':[],'design_id':'design'}],designs=[{'id':'design','state':'review','version':1,'versions':[{'version':1}],'feedback':[]}])
  super().respond(status,body,kind)
 def do_GET(self):
  if self.path=='/fixture-preview':
   raw=b'<!doctype html><style>*{margin:0}html,body{margin:0;height:100%;overflow:hidden}body{background:#dff2ff;font:32px sans-serif}.stage{display:flex;justify-content:center}.canvas{width:1760px;height:1080px;position:relative;flex:0 0 auto}#far{position:absolute;right:0;bottom:0}</style><section class="stage"><div class="canvas"><h1>Product design</h1><p id="far">Arrow annotation</p></div></section><script>window.previewScriptRan=true</script>'
   self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(raw)));self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; sandbox allow-same-origin");self.end_headers();self.wfile.write(raw);return
  super().do_GET()
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));self.requests.append(data)
  if data['action']=='design_content':
   pages=[{'id':'home','title':'Home','parent':None,'kind':'screen','note':'→ Main navigation'}, {'id':'settings','title':'Settings','parent':'home','kind':'screen','note':'→ Settings explanation'}, {'id':'architecture','title':'Architecture','parent':None,'kind':'architecture','note':'Backend and data flow'}]
   return self.respond(200,{'result':{'title':'Demo','version':1,'digest':'frozen','pages':pages,'urls':{p['id']:'/fixture-preview' for p in pages}}})
  return self.respond(200,{'result':{}})
CHECK=r"""
const wait=()=>new Promise(r=>setTimeout(r,120));
document.getElementById('openDesignReview').click();await wait();
const dialog=document.getElementById('designReviewDialog'),frame=document.getElementById('designFrame');
if(dialog.hidden)throw Error('review did not open');
if(Math.abs(frame.contentDocument.documentElement.scrollWidth-1760)>3||Math.abs(frame.contentDocument.documentElement.scrollHeight-1080)>3)throw Error('fixture is not large '+JSON.stringify([frame.contentDocument.documentElement.scrollWidth,frame.contentDocument.documentElement.scrollHeight,getComputedStyle(document.getElementById('designCanvas')).width,getComputedStyle(document.getElementById('designCanvas')).height]));
if(Math.abs(parseFloat(getComputedStyle(document.getElementById('designCanvas')).width)-1760)>3)throw Error('real page width was clipped');
if(frame.contentDocument.querySelector('.canvas').getBoundingClientRect().left < -1)throw Error('centred page left edge clipped');
if(frame.contentWindow.previewScriptRan)throw Error('untrusted preview script ran');
const far=frame.contentDocument.getElementById('far');if(!far||far.getBoundingClientRect().bottom>1081)throw Error('bottom annotation missing');
const pages=[...document.querySelectorAll('#designPageList button')];
if(pages.length!==3||!pages.at(-1).textContent.includes('Architecture'))throw Error('incomplete page inventory');
if(!pages[1].parentElement.parentElement.parentElement.querySelector('button').textContent.includes('Home'))throw Error('hierarchy lost');
pages[1].click();await wait();if(!document.getElementById('designPageNote').textContent.includes('Settings'))throw Error('page note missing');
document.getElementById('designZoomActual').click();if(document.getElementById('designCanvas').dataset.zoom!=='100')throw Error('1:1 zoom failed');
document.getElementById('designZoomIn').click();if(Number(document.getElementById('designCanvas').dataset.zoom)<=100)throw Error('zoom in failed');
const zoomSelect=document.getElementById('designZoomLevel');zoomSelect.value='200';zoomSelect.dispatchEvent(new Event('change'));
const zoomStage=document.querySelector('.design-stage');if(document.getElementById('designCanvas').getBoundingClientRect().width<2500||zoomStage.scrollWidth<=zoomStage.clientWidth)throw Error('enlarged demo is clipped without scrolling');
const zoomBefore=Number(document.getElementById('designCanvas').dataset.zoom);
zoomStage.dispatchEvent(new WheelEvent('wheel',{deltaY:1,bubbles:true,cancelable:true}));
const fineZoom=Number(document.getElementById('designCanvas').dataset.zoom);if(!(fineZoom<zoomBefore&&fineZoom>zoomBefore-1))throw Error('zoom still snaps to steps');
zoomStage.dispatchEvent(new WheelEvent('wheel',{deltaY:100,clientX:zoomStage.getBoundingClientRect().left+100,clientY:zoomStage.getBoundingClientRect().top+100,bubbles:true,cancelable:true}));
if(Number(document.getElementById('designCanvas').dataset.zoom)>=zoomBefore)throw Error('plain wheel did not zoom');
document.getElementById('designZoomActual').click();zoomStage.scrollLeft=120;zoomStage.scrollTop=150;zoomStage.setPointerCapture=()=>{};
const leftBefore=zoomStage.scrollLeft,topBefore=zoomStage.scrollTop;
for(const [type,x,y] of [['pointerdown',200,200],['pointermove',150,140],['pointerup',150,140]])zoomStage.dispatchEvent(new PointerEvent(type,{button:1,buttons:type==='pointerup'?0:4,pointerId:22,clientX:x,clientY:y,bubbles:true,cancelable:true}));
if(zoomStage.scrollLeft<=leftBefore||zoomStage.scrollTop<=topBefore||zoomStage.classList.contains('panning'))throw Error('middle mouse pan failed or got stuck');
zoomStage.scrollLeft=120;zoomStage.scrollTop=150;
for(const [type,x,y] of [['pointerdown',200,200],['pointermove',150,140],['pointerup',150,140]])zoomStage.dispatchEvent(new PointerEvent(type,{button:0,buttons:type==='pointerup'?0:1,pointerId:23,clientX:x,clientY:y,bubbles:true,cancelable:true}));
if(zoomStage.scrollLeft<=120||zoomStage.scrollTop<=150||zoomStage.classList.contains('panning'))throw Error('left mouse pan failed outside selection mode');
document.getElementById('designZoomFit').click();await wait();if(document.getElementById('designCanvas').getBoundingClientRect().width>zoomStage.clientWidth)throw Error('fit zoom does not fit');
if([...document.querySelectorAll('input,textarea,form')].some(el=>el.autocomplete!=='off'&&el.form?.autocomplete!=='off'&&!['checkbox','radio','hidden','submit','button'].includes(el.type)))throw Error('form autofill still enabled '+[...document.querySelectorAll('input,textarea,form')].filter(el=>el.autocomplete!=='off'&&el.form?.autocomplete!=='off'&&!['checkbox','radio','hidden','submit','button'].includes(el.type)).map(el=>el.id+':'+el.type).join(','));
if(!frame.hasAttribute('sandbox')||frame.getAttribute('sandbox')!=='allow-same-origin')throw Error('unsafe frame');
const footer=document.getElementById('acceptDesign').getBoundingClientRect();
if(footer.top<0||footer.bottom>innerHeight+1)throw Error('approval button clipped');
const stage=document.querySelector('.design-stage');
if(stage.clientHeight<100||getComputedStyle(stage).overflowY!=='auto')throw Error('preview has no scroll path');
document.getElementById('designSelectRegion').click();const overlay=document.getElementById('designOverlay'),r=overlay.getBoundingClientRect();overlay.setPointerCapture=()=>{};
for(const [type,x,y] of [['pointerdown',.1,.2],['pointermove',.5,.6],['pointerup',.5,.6]])overlay.dispatchEvent(new PointerEvent(type,{clientX:r.left+x*r.width,clientY:r.top+y*r.height,pointerId:1,bubbles:true}));
if(Number(document.getElementById('designSelection').getAttribute('width'))<399)throw Error('region selection failed');
const feedback=document.getElementById('designFeedbackText');feedback.value='Keep this text';
document.getElementById('designClearRegion').click();if(Number(document.getElementById('designSelection').getAttribute('width'))!==0||feedback.value!=='Keep this text')throw Error('clear region removed feedback or kept box');
const drawAgain=()=>{for(const [type,x,y] of [['pointerdown',.1,.2],['pointermove',.5,.6],['pointerup',.5,.6]])overlay.dispatchEvent(new PointerEvent(type,{button:0,clientX:r.left+x*r.width,clientY:r.top+y*r.height,pointerId:1,bubbles:true}));};
drawAgain();feedback.focus();feedback.dispatchEvent(new KeyboardEvent('keydown',{key:'Delete',bubbles:true,cancelable:true}));if(Number(document.getElementById('designSelection').getAttribute('width'))<399)throw Error('text editing Delete cleared selection');
zoomStage.focus();zoomStage.dispatchEvent(new KeyboardEvent('keydown',{key:'Delete',bubbles:true,cancelable:true}));if(Number(document.getElementById('designSelection').getAttribute('width'))!==0||!document.getElementById('designClearRegion').disabled)throw Error('Delete did not clear selection');
drawAgain();
document.getElementById('designFeedbackText').value='Make selected area blue';
await H.store.refresh(true);if(document.getElementById('designFeedbackText').value!=='Make selected area blue')throw Error('feedback draft lost');
pages[0].click();await wait();feedback.value='Home changes';feedback.dispatchEvent(new Event('input',{bubbles:true}));
document.getElementById('designOverallFeedback').value='Overall style changes';
pages[1].click();await wait();if(feedback.value!=='Make selected area blue')throw Error('page draft lost on switch');
// Simulate a server restart or expired ticket while preserving every draft and selection.
const beforeText=feedback.value,beforeBox=document.getElementById('designSelection').getAttribute('width'),realFetch=window.fetch;
let expiredOnce=true,renewed=false;
window.fetch=async function(input,options){const url=String(input);if(expiredOnce&&url.includes('/fixture-preview')){expiredOnce=false;return new Response('expired',{status:404});}if(options?.body?.includes('design_content'))renewed=true;return realFetch.call(this,input,options);};
window.dispatchEvent(new Event('focus'));await wait();await wait();window.fetch=realFetch;
if(!renewed)throw Error('expired preview was not renewed');
if(feedback.value!==beforeText||document.getElementById('designOverallFeedback').value!=='Overall style changes'||document.getElementById('designSelection').getAttribute('width')!==beforeBox)throw Error('preview recovery lost feedback or selection');
// Simulate hours spent asleep: renew proactively without waiting for an error.
const realNow=Date.now;Date.now=()=>realNow()+2*60*60*1000;renewed=false;
window.fetch=async function(input,options){if(options?.body?.includes('design_content'))renewed=true;return realFetch.call(this,input,options);};
window.dispatchEvent(new Event('focus'));await wait();await wait();Date.now=realNow;window.fetch=realFetch;
if(!renewed)throw Error('sleep recovery did not refresh stale preview');
document.getElementById('submitDesignFeedback').click();await wait();
document.getElementById('acceptDesign').click();await wait();if(!dialog.hidden)throw Error('accept did not finish');
"""
class DesignBrowser(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_review_selection_redesign_and_approval_across_viewports(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  s=base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   for size in ['1440,900','1024,600','600,800']:
    Fixture.requests=[]
    with self.subTest(size=size),tempfile.TemporaryDirectory() as p:
     r=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--window-size={size}',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=7000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
     result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1))
     feedback=[x['args'] for x in Fixture.requests if x['action']=='design_feedback'];self.assertEqual(len(feedback),1);self.assertEqual(len(feedback[0]['entries']),2);self.assertEqual(feedback[0]['overall'],'Overall style changes');self.assertEqual(next(e for e in feedback[0]['entries'] if e['page_id']=='settings')['page_id'],'settings');self.assertAlmostEqual(next(e for e in feedback[0]['entries'] if e['page_id']=='settings')['region']['x'],.1,places=2)
     self.assertTrue(any(x['action']=='design_accept' and x['args']['digest']=='frozen' for x in Fixture.requests));print('PASS demo hierarchy, sandbox, region/page/all feedback, version approval, bounded layout '+size)
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original

RELOAD_CHECK=r"""
const wait=()=>new Promise(r=>setTimeout(r,200));
if(!sessionStorage.getItem('fixture-review-reloaded')){
 document.getElementById('openDesignReview').click();await wait();
 document.querySelector('#designPageList [data-page="settings"]').click();
 const z=document.getElementById('designZoomLevel');z.value='200';z.dispatchEvent(new Event('change'));
 document.getElementById('designOverallFeedback').value='KEEP OVERALL';
 const draft=document.getElementById('designFeedbackText');draft.value='KEEP MY DESIGN FEEDBACK';draft.dispatchEvent(new Event('input',{bubbles:true}));
 const stage=document.querySelector('.design-stage');stage.scrollLeft=100;stage.scrollTop=80;await wait();
 sessionStorage.setItem('fixture-review-reloaded','yes');location.reload();return;
}
await wait();
if(document.getElementById('designReviewDialog').hidden)throw Error('review not restored after reload');
if(document.querySelector('#designPageList [aria-current="page"]').dataset.page!=='settings')throw Error('selected demo page lost');
if(document.getElementById('designFeedbackText').value!=='KEEP MY DESIGN FEEDBACK')throw Error('design feedback draft lost');
if(document.getElementById('designOverallFeedback').value!=='KEEP OVERALL')throw Error('overall draft lost');
if(document.getElementById('designCanvas').dataset.zoom!=='200')throw Error('zoom level lost');
if(document.querySelector('.design-stage').scrollLeft<90)throw Error('enlarged preview scroll lost');
"""
class DesignReload(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_design_page_zoom_feedback_and_scroll_survive_reload(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",RELOAD_CHECK+"out.textContent='PASS")
  s=base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   with tempfile.TemporaryDirectory() as p:
    r=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size=1440,900',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=9000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print('PASS actual reload preserves open demo, selected page, 200% zoom, feedback draft and preview scroll')
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
