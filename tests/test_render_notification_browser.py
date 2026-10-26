import json,re,tempfile,threading,unittest
import test_nine_browser as base

CHECK=r"""
const waitUI=async predicate=>{const until=Date.now()+4000;while(!predicate()&&Date.now()<until)await new Promise(r=>setTimeout(r,20));if(!predicate())throw Error('settings did not update');};
document.getElementById('configModalToggle').checked=true;
document.querySelector('[aria-controls="renderSettings"]').click();
await waitUI(()=>document.querySelectorAll('#renderBrowserChoice option').length>=3);
const browserSelect=document.getElementById('renderBrowserChoice');
if(![...browserSelect.options].some(o=>o.textContent==='Installed Edge'))throw Error('installed browser missing');
browserSelect.value='custom';browserSelect.dispatchEvent(new Event('change'));
if(document.getElementById('renderCustomPath').hidden)throw Error('custom executable path unavailable');
document.getElementById('renderBrowserPath').value='C:/custom/chrome.exe';
document.getElementById('renderBrowserForm').dispatchEvent(new Event('submit',{cancelable:true}));
await waitUI(()=>document.getElementById('renderCurrent').textContent.includes('C:/custom/chrome.exe'));
await new Promise(r=>setTimeout(r,50));
document.getElementById('renderDownload').click();
await waitUI(()=>document.getElementById('renderDownloadStatus').textContent.includes('已安装'));
await new Promise(r=>setTimeout(r,50));
if(![...browserSelect.options].some(o=>o.value==='managed'))throw Error('managed browser unavailable after install');
document.querySelector('[aria-controls="notificationSettings"]').click();
await waitUI(()=>document.getElementById('notificationWhen').value==='background');
document.getElementById('notificationsEnabled').checked=false;document.getElementById('notifyAttention').checked=true;
document.getElementById('notificationForm').dispatchEvent(new Event('submit',{cancelable:true}));
await waitUI(()=>document.getElementById('notificationSaveStatus').textContent.includes('已保存'));
await new Promise(r=>setTimeout(r,50));document.getElementById('notificationTest').click();
await waitUI(()=>document.getElementById('notificationSaveStatus').textContent.includes('已提交'));
await waitUI(()=>document.getElementById('notificationSaveStatus').textContent.includes('fixture permission denied'));
if(document.getElementById('notificationSaveStatus').textContent.includes('系统已接受'))throw Error('denied notification reported as accepted');
if(document.querySelectorAll('.settings-navigation [aria-controls="notificationSettings"]').length!==1)throw Error('duplicate notification page');
"""

class Fixture(base.Fixture):
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));action=data.get('action');args=data.get('args',{})
        if action=='render_settings':
            if args.get('operation')=='save':self.server.browser_config={'mode':args['mode'],'path':args['path']}
            if args.get('operation')=='download':self.server.installed=True
            if args.get('operation')=='browse':return self.respond(200,{'result':{'path':'C:/picked/chrome.exe'}})
            value={'config':self.server.browser_config,'current':self.server.browser_config['path'] or 'C:/edge.exe','browsers':[{'name':'Installed Edge','path':'C:/edge.exe'}],
                   'managed':{'revision':'123','path':'C:/owned/chrome.exe'} if self.server.installed else None,'download':{'state':'completed' if self.server.installed else 'idle','received':100,'total':100}}
        elif action=='notification_settings':
            if args.get('operation')=='save':self.server.notification_config=args['config']
            if args.get('operation')=='test':value={'queued':True,'event_id':'test:fixture'}
            elif args.get('operation')=='delivery_status':value={'delivery':{'event':'test:fixture','submitted':False,'error':'fixture permission denied'}}
            else:value=self.server.notification_config
        else:value={}
        self.respond(200,{'result':value})

class SettingsBrowser(unittest.TestCase):
    @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
    def test_browser_choices_download_and_notification_controls(self):
        original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
        server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            for size in ['1440,900','1024,600','600,800']:
                server.browser_config={'mode':'auto','path':''};server.installed=False
                server.notification_config={'enabled':True,'when':'background','demo':True,'project':True,'attention':False}
                with self.subTest(size=size),tempfile.TemporaryDirectory() as folder:
                    result=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size='+size,'--user-data-dir='+folder,'--dump-dom','--virtual-time-budget=6000',f'http://127.0.0.1:{server.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
                    match=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertIsNotNone(match)
                    self.assertTrue(match.group(1).startswith('PASS'),match.group(1))
                    self.assertFalse(server.notification_config['enabled']);self.assertTrue(server.notification_config['attention'])
        finally:server.shutdown();server.server_close();thread.join();base.DRIVER=original
