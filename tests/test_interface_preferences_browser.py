import re,tempfile,threading,unittest,base64
import test_nine_browser as base

CHECK=r"""
const I=window.HubI18n,wait=()=>new Promise(r=>setTimeout(r,100));
if(!I)throw Error('language controller missing');
const original=H.node('p','项目状态','chat-message-body');document.body.append(original);
const projectName=H.node('button','项目状态','project-list-item');document.body.append(projectName);
I.set('en');await wait();
if(document.documentElement.lang!=='en')throw Error('lang not set');
if(!document.getElementById('tabManagerChat').textContent.includes('Chat with project manager'))throw Error('manager tab untranslated');
if(!document.getElementById('tabGroupChat').textContent.includes('Agent chat'))throw Error('group tab untranslated');
if(!document.getElementById('themeModeDark').textContent.includes('Dark'))throw Error('settings untranslated');
if(!document.getElementById('message').placeholder.includes('Broadcast'))throw Error('composer placeholder untranslated');
if(original.textContent!=='项目状态'||projectName.textContent!=='项目状态')throw Error('user content translated');
const later=H.node('button','保存');document.body.append(later);await wait();if(later.textContent!=='Save')throw Error('dynamic UI untranslated');
I.set('zh-CN');await wait();if(later.textContent!=='保存')throw Error('Chinese restoration failed');
const root=document.documentElement;root.dataset.theme='light';await wait();
const input=document.querySelector('#interfaceColors input[data-token="--bg-app"]');
if(!input)throw Error('color editor missing');input.value='#dce7e2';input.dispatchEvent(new Event('input',{bubbles:true}));await wait();
if(root.style.getPropertyValue('--bg-app')!=='#dce7e2')throw Error('light color not saved');
root.dataset.theme='dark';await wait();if(root.style.getPropertyValue('--bg-app')==='#dce7e2')throw Error('light colors leaked into dark mode');
input.value='#202b29';input.dispatchEvent(new Event('input',{bubbles:true}));await wait();
root.dataset.theme='light';await wait();if(root.style.getPropertyValue('--bg-app')!=='#dce7e2')throw Error('light palette not restored');
root.dataset.theme='dark';await wait();if(root.style.getPropertyValue('--bg-app')!=='#202b29')throw Error('dark palette not restored');
document.getElementById('resetInterfaceColors').click();root.dataset.theme='light';await wait();if(root.style.getPropertyValue('--bg-app')!=='#dce7e2')throw Error('reset erased other mode');
const item=H.artifactMessage({id:'a'.repeat(64),kind:'image',entry:'screenshot.png',caption:'浏览器实际渲染：ik-target.html',url:'/api/shared/'+'a'.repeat(64)+'/screenshot.png',created:1,sender:'deepseek-1'});
document.body.append(item);item.querySelector('.artifact-web-link').click();await wait();
const viewer=document.getElementById('artifactViewer'),bounds=viewer.getBoundingClientRect();
if(document.getElementById('artifactViewerTitle').textContent.includes('ik-target'))throw Error('rendered filename still shown');
if(Math.abs(bounds.width-innerWidth)>2||Math.abs(bounds.height-innerHeight)>2)throw Error('viewer not full window');
if(getComputedStyle(viewer.querySelector('h2')).display!=='none')throw Error('preview still has a heading strip');
document.getElementById('closeArtifactViewer').click();original.remove();projectName.remove();
"""

class Fixture(base.Fixture):
    def do_GET(self):
        if self.path.startswith('/api/shared/'):
            raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aB1kAAAAASUVORK5CYII=')
            self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
        super().do_GET()

class Browser(unittest.TestCase):
    @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
    def test_language_palettes_and_full_window_preview(self):
        old=base.DRIVER;base.DRIVER=old.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
        server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            for size in ('1440,900','1024,600','600,800'):
                with self.subTest(size=size),tempfile.TemporaryDirectory() as folder:
                    result=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size='+size,'--user-data-dir='+folder,'--dump-dom','--virtual-time-budget=6000','http://127.0.0.1:'+str(server.server_port)+'/'],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
                    match=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
                    self.assertIsNotNone(match);self.assertTrue(match.group(1).startswith('PASS'),match.group(1))
        finally:server.shutdown();server.server_close();thread.join();base.DRIVER=old
