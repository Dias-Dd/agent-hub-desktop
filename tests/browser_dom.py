"""Real browser regression driver, including launchers that detach before CDP is ready."""
import base64,json,subprocess,tempfile,time,urllib.request
from pathlib import Path
from hub.browser_cdp import WebSocket
from hub.browser_render import spawn_browser

def run(argv,**kwargs):
 width,height=map(int,next((x.split('=',1)[1] for x in argv if x.startswith('--window-size=')),'1440,900').split(','))
 url=argv[-1];ws=None;browser=None
 with tempfile.TemporaryDirectory(prefix='hub-ui-regression-',ignore_cleanup_errors=True) as folder:
  args=[argv[0],'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--no-proxy-server','--remote-debugging-port=0','--user-data-dir='+folder,'about:blank']
  proc=spawn_browser(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:
   port_file=Path(folder)/'DevToolsActivePort';deadline=time.monotonic()+12
   while not port_file.exists() and time.monotonic()<deadline:time.sleep(.05)
   if not port_file.exists():raise RuntimeError('test browser did not open DevTools')
   lines=port_file.read_text().splitlines();port=lines[0]
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
   browser=WebSocket('ws://127.0.0.1:'+port+lines[1])
   targets=json.load(opener.open('http://127.0.0.1:'+port+'/json/list'))
   ws=WebSocket(next(t['webSocketDebuggerUrl'] for t in targets if t.get('type')=='page'))
   ws.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':False})
   ws.call('Page.navigate',{'url':url})
   deadline=time.monotonic()+kwargs.get('timeout',30)
   while time.monotonic()<deadline:
    value=ws.call('Runtime.evaluate',{'expression':"document.getElementById('result')?.textContent||''",'returnByValue':True}).get('result',{}).get('value','')
    if value.startswith(('PASS','FAIL')):break
    time.sleep(.05)
   if kwargs.get('after_checks'):kwargs['after_checks'](ws)
   if kwargs.get('screenshot'):Path(kwargs['screenshot']).write_bytes(base64.b64decode(ws.call('Page.captureScreenshot',{'format':'png'})['data']))
   dom=ws.call('Runtime.evaluate',{'expression':'document.documentElement.outerHTML','returnByValue':True})['result']['value']
   if kwargs.get('screenshot'):
    png=ws.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});Path(kwargs['screenshot']).write_bytes(base64.b64decode(png['data']))
   return subprocess.CompletedProcess(argv,0,dom,'')
  finally:
   if browser:
    try:browser.call('Browser.close')
    except Exception:pass
    browser.close()
   if ws:ws.close()
   if proc.poll() is None:proc.kill()
