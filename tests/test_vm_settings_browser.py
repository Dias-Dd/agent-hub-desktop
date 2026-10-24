import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import test_nine_browser as base

CHECK="""
const toggle=document.getElementById('configModalToggle');toggle.checked=true;toggle.dispatchEvent(new Event('change'));
document.getElementById('vmRefresh').click();await new Promise(r=>setTimeout(r,200));
if(document.getElementById('vmSelect').value!=='Hub')throw Error('VM list missing');
document.getElementById('vmUsername').value='hub';document.getElementById('vmPassword').value='fixture-only';
document.getElementById('vmConnectForm').dispatchEvent(new Event('submit',{cancelable:true}));
await new Promise(r=>setTimeout(r,200));
if(document.getElementById('vmPassword').value)throw Error('password retained in input');
if(!document.getElementById('vmConnectionStatus').textContent.includes('文件传输测试通过'))throw Error('connection result absent');
if(!document.getElementById('vmConnectionStatus').textContent.includes('无人值守已配置'))throw Error('unattended result absent');
if(Object.values(sessionStorage).some(x=>String(x).includes('fixture-only')))throw Error('password persisted');
document.getElementById('vmDisconnect').click();await new Promise(r=>setTimeout(r,200));
if(!document.getElementById('vmConnectionStatus').textContent.includes('已断开'))throw Error('disconnect failed');
if(!document.getElementById('vmRemember').checked)throw Error('remember consent missing');
document.getElementById('vmReconnectSaved').click();await new Promise(r=>setTimeout(r,200));
if(!document.getElementById('vmConnectionStatus').textContent.includes('已连接 Hub'))throw Error('saved reconnect failed');
document.getElementById('vmForget').click();await new Promise(r=>setTimeout(r,200));
if(!document.getElementById('vmConnectionStatus').textContent.includes('已删除'))throw Error('forget failed');
document.getElementById('vmPowerForce').click();
if(!document.getElementById('vmForceDialog').open)throw Error('force shutdown confirmation missing');
document.getElementById('vmForceDialog').querySelector('.dialog-close').click();
if(document.getElementById('vmForceDialog').open)throw Error('force shutdown cancel broken');
toggle.checked=false;
"""


class Fixture(base.Fixture):
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
        result={}
        if body.get('action')=='vm_control':
            args=body['args'];action=args['action']
            if action=='connect' and args.get('unattended') is not True:raise AssertionError('unattended missing')
            if action in ('connect','connect_saved','list','disconnect','power_on','power_off','power_force'):result={'request_id':action}
            elif action=='status':result={'vm':'Hub','helper_alive':True,'power_state':'Running','connected':True}
            elif action=='result':
                result={'state':'completed','vms':[{'name':'Hub','state':'Running','generation':2}], 'vm':'Hub','account':'desktop\\hub','credential_saved':True,'unattended_configured':True,'unattended_enabled':True}
        self.respond(200,{'result':result})


@unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
class Browser(unittest.TestCase):
    def test_vm_setup_and_credential_clear(self):
        server=base.Server(('127.0.0.1',0),Fixture)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            driver=base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
            with patch.object(base,'DRIVER',driver),tempfile.TemporaryDirectory() as folder:
                result=base.browser_run([str(base.m.EDGE),'--window-size=1024,600',f'http://127.0.0.1:{server.server_port}/'],timeout=30)
                matched=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
                self.assertIsNotNone(matched)
                self.assertTrue(matched.group(1).startswith('PASS'),matched.group(1))
                print('PASS VM dropdown/connect/disconnect/credential clearing in real browser (mock Hyper-V)')
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
