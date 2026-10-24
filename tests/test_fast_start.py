import json
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch
from desktop.fast_start import FastHub
from desktop.launch_desktop import OwnedHub
from hub.browser_cdp import WebSocket
from hub.browser_render import spawn_browser
import test_nine_browser as base


@unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
class Startup(unittest.TestCase):
    def test_shell_is_interactive_before_backend_and_vm(self):
        release=threading.Event();vm_release=threading.Event()
        def slow(*args,**kwargs):
            release.wait(20);return OwnedHub(*args,**kwargs)
        def vm(owner):
            owner.stage('vm','loading','模拟慢速虚拟机启动（后台）')
            vm_release.wait(20);owner.stage('vm','ready','模拟虚拟机就绪')
        page=browser=None;hub=None
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder,patch('desktop.launch_desktop.OwnedHub',side_effect=slow),patch.object(FastHub,'virtual_machine',vm),patch('desktop.dependencies.start_dependencies'):
            try:
                data=Path(folder)/'data';data.mkdir();(data/'ui-preferences.json').write_text('{"language":"en"}',encoding='utf-8')
                start=time.monotonic();hub=FastHub(data,0,False)
                url=f'http://127.0.0.1:{hub.port}'
                self.assertIn('id="workspace"',opener.open(url).read().decode())
                self.assertIn('name="hub-interface-language" content="en"',opener.open(url).read().decode())
                self.assertEqual(json.load(opener.open(url+'/i18n.json'))['项目状态'],'Project status')
                self.assertLess(time.monotonic()-start,2)
                profile=Path(folder)/'profile';profile.mkdir()
                process=spawn_browser([str(base.m.EDGE),'--headless=new','--disable-gpu','--no-first-run','--no-proxy-server','--remote-debugging-port=0','--user-data-dir='+str(profile),'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                active=profile/'DevToolsActivePort';end=time.monotonic()+12
                while not active.exists() and time.monotonic()<end:time.sleep(.05)
                port,path=active.read_text().splitlines()[:2]
                browser=WebSocket('ws://127.0.0.1:'+port+path)
                targets=json.load(opener.open('http://127.0.0.1:'+port+'/json/list'))
                page=WebSocket(next(t['webSocketDebuggerUrl'] for t in targets if t['type']=='page'))
                def evaluate(code):
                    result=page.call('Runtime.evaluate',{'expression':code,'returnByValue':True})
                    self.assertNotIn('exceptionDetails',result,str(result))
                    return result.get('result',{}).get('value')
                page.call('Page.navigate',{'url':url})
                end=time.monotonic()+8
                while not evaluate('!!window.HubDesktop') and time.monotonic()<end:time.sleep(.05)
                time.sleep(.3)
                self.assertIn('Chat with project manager',evaluate("document.getElementById('tabManagerChat').textContent"))
                self.assertTrue(evaluate("document.getElementById('hubProjectCreateBtn').inert"))
                self.assertTrue(evaluate("document.getElementById('btnViewStatus').click();document.getElementById('viewModeStatusRadio').checked"))
                evaluate("document.getElementById('discussionReply').value='startup draft'")
                self.assertTrue(evaluate("!document.getElementById('login')&&!document.getElementById('modalLoginForm')"))
                evaluate("window.__authDenied=false;const originalFetch=window.fetch;window.fetch=async function(url,options){if(url==='/desktop-session'&&!window.__authDenied){options={...options,headers:{...options.headers,'X-Desktop-Session':'expired-session'}};const response=await originalFetch(url,options);if(response.status===403)window.__authDenied=true;return response;}return originalFetch(url,options);}")
                evaluate("const detached=document.createElement('section');const pending=document.createElement('button');detached.append(pending);window.__detachedButton=pending;window.HubWindows={entries:new Map([['fixture',{root:detached}]])};document.body.append(document.createElement('i'));")
                time.sleep(.1)
                self.assertTrue(evaluate("window.__detachedButton.inert"))
                release.set();end=time.monotonic()+20
                while not evaluate('!!window.HubDesktop?.view.rawSnapshot') and time.monotonic()<end:time.sleep(.1)
                self.assertTrue(evaluate('!!window.HubDesktop.view.rawSnapshot'))
                self.assertFalse(evaluate("document.getElementById('hubProjectCreateBtn').inert"))
                self.assertFalse(evaluate("window.__detachedButton.inert"))
                self.assertEqual(evaluate("document.getElementById('discussionReply').value"),'startup draft')
                self.assertEqual(hub.server.startup['stages']['vm']['state'],'loading')
                self.assertTrue(evaluate("window.__authDenied"))
                self.assertTrue(hub.server.startup['backend_ready'])
                time.sleep(1.1)
                self.assertNotIn('（',evaluate("document.getElementById('startupLabel').textContent"))
                vm_release.set();end=time.monotonic()+5;animated=False
                while time.monotonic()<end:
                    animated=animated or bool(evaluate("document.getElementById('startupProgress').getAnimations().length"))
                    if evaluate("document.getElementById('startupProgress').hidden"):break
                    time.sleep(.05)
                self.assertTrue(animated,'completed startup did not fade')
                self.assertTrue(evaluate("document.getElementById('startupProgress').hidden"))
                print('PASS immediate real shell; local tabs/draft during backend startup; backend unlocked while VM still loading')
            finally:
                release.set();vm_release.set()
                if browser:
                    try:browser.call('Browser.close')
                    except Exception:pass
                    browser.close()
                if page:page.close()
                if hub:hub.close()


if __name__=='__main__':unittest.main()
