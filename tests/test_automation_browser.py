import base64,json,re,subprocess,tempfile,threading,unittest
import test_nine_browser as base
from test_manager_layout import CHECK

class Fixture(base.Fixture):
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:
   body['shared_artifacts']=[{'id':'a'*64,'sender':'deepseek-4','kind':'webpage','caption':'网页演示','created':1,'url':'/api/shared/'+('a'*64)+'/index.html'},{'id':'b'*64,'sender':'deepseek-1','kind':'image','caption':'图片结果','created':2,'url':'/api/shared/'+('b'*64)+'/image.png'}]
   body['pending_notifications']=[{'id':'config:project','source':'平台','recipient':'deepseek-4','body':'累计通知：模型及档位变更','state':'pending','category':'agent_config_changed','created':2}]
   body['timers']=[{'id':'timer','creator':'deepseek-1','recipient':'deepseek-4','state':'held','condition':'time','due':1,'note':'检查项目','reason':'紧急停止锁；提醒已保留'}]
  return super().respond(status,body,kind)
 def do_GET(self):
  if self.path.startswith('/api/shared/'):
   if self.path.endswith('.png'):
    raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1kAAAAASUVORK5CYII=');self.send_response(200);self.send_header('Content-Type','image/png');self.end_headers();self.write_body(raw);return
   raw='<meta charset="utf-8"><style>body{margin:0;padding:32px;background:#f7f7f4;color:#243c33;font:16px/1.7 sans-serif}h1{font-size:24px;font-weight:500}</style><h1>静态成果</h1><p>网页内容预览</p>'.encode('utf8')
   self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'; sandbox");self.end_headers();self.write_body(raw);return
  return super().do_GET()

class Browser(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_media_timer_render_and_scroll_preservation(self):
  extra=CHECK+"""
const artifacts=document.getElementById('sharedArtifacts');artifacts.replaceChildren(...H.artifactItems(H.view.rawSnapshot).map(H.artifactMessage));const link=artifacts.querySelector('.artifact-web-link');if(!link||artifacts.querySelector('iframe'))throw Error('web attachment must remain a compact link');
document.querySelector('#sharedArtifacts .artifact-web-link').click();const viewer=document.getElementById('artifactViewer');if(!viewer.open||!viewer.querySelector('iframe')||viewer.querySelector('iframe').getAttribute('sandbox')!=='')throw Error('internal viewer missing');if(viewer.getBoundingClientRect().bottom>innerHeight+1||document.getElementById('closeArtifactViewer').getBoundingClientRect().bottom>innerHeight||viewer.querySelector('iframe').getBoundingClientRect().height<100)throw Error('viewer clipped');document.getElementById('closeArtifactViewer').click();await Promise.resolve();
document.querySelector('#sharedArtifacts .artifact-web-link').click();if(!viewer.open||!viewer.querySelector('iframe'))throw Error('second opening failed');await new Promise(r=>setTimeout(r,40));if(!viewer.querySelector('iframe'))throw Error('old close event wiped reopened preview');document.getElementById('closeArtifactViewer').click();
if(!document.getElementById('pendingNotices').textContent.includes('累计通知')||!document.getElementById('automationSummary').textContent.includes('1 条待交付通知')||document.getElementById('noticesDrawer').tagName==='DETAILS')throw Error('pending notifications hidden');
if(!H.view.agentStream.timeline.some(x=>x.category==='notification'&&x.body.includes('累计通知')))throw Error('platform notice missing from group timeline');
if(!document.querySelector('#sharedArtifacts img')||!document.querySelector('#timerList').textContent.includes('紧急停止锁'))throw Error('media/timer state missing');
const draft=document.getElementById('discussionReply');draft.value='keep draft';area.scrollTop=40;const position=area.scrollTop;
await H.store.refresh(true);if(document.querySelector('#sharedArtifacts .artifact-web-link')!==link)throw Error('attachment remounted by polling');
document.querySelector('#sharedArtifacts .artifact-web-link').click();if(!viewer.open||!viewer.querySelector('iframe'))throw Error('reopen after refresh failed');document.getElementById('closeArtifactViewer').click();
if(Math.abs(area.scrollTop-position)>2||draft.value!=='keep draft')throw Error('reading position or draft lost');
"""
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",extra+"out.textContent='PASS")
  s=base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   for size in ['1440,900','1024,600','600,800']:
    with self.subTest(size=size),tempfile.TemporaryDirectory() as folder:
     r=subprocess.run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size='+size,'--user-data-dir='+folder,'--dump-dom','--virtual-time-budget=6000','http://127.0.0.1:'+str(s.server_port)+'/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
     result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print('PASS media, timer, sandbox, stable reading and composer at '+size)
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
