"""Real layout/interaction with synthetic Tart observations; never boots a VM."""
import json
import re
import threading
import unittest
from unittest.mock import patch
import test_nine_browser as base

CHECK = r"""
const waitTart=async test=>{const end=Date.now()+5000;while(!test()&&Date.now()<end)await new Promise(r=>setTimeout(r,25));if(!test())throw Error('Tart UI timeout');};
document.getElementById('configModalToggle').checked=true;
document.getElementById('configModalToggle').dispatchEvent(new Event('change'));
await waitTart(()=>document.getElementById('vmUsername').disabled);
if(!document.getElementById('vmUsername').closest('.vm-account-grid').hidden)throw Error('Windows credentials visible');
if(!document.getElementById('vmUnattended').closest('label').hidden)throw Error('Windows unattended settings visible');
if(!document.getElementById('vmOpenManager').textContent.includes('Tart'))throw Error('wrong VM guide');
document.getElementById('vmRefresh').click();
await waitTart(()=>document.getElementById('vmSelect').options.length===1&&document.getElementById('vmSelect').value==='fixture-vm');
if(document.getElementById('vmSelect').options[0].textContent.includes('undefined'))throw Error('Hyper-V generation leaked');
await waitTart(()=>!document.getElementById('vmConnect').disabled);
document.getElementById('vmConnect').click();
await waitTart(()=>document.getElementById('vmConnectionStatus').textContent.includes('文件传输未验证'));
if(document.getElementById('vmConnectionStatus').textContent.includes('文件传输测试通过'))throw Error('unverified transfer claimed success');
document.getElementById('configModalToggle').checked=false;
"""


class Fixture(base.Fixture):
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        args=payload.get('args',{})
        action=args.get('action')
        if payload.get('action')!='vm_control':return self.respond(200,{'result':{}})
        if action=='status':value={'backend':'tart','installed':True,'supported':True,'helper_alive':True,'connected':getattr(self.server,'vm_connected',False),'power_state':'Running' if getattr(self.server,'vm_connected',False) else 'Off','saved_connections':[{'vm':'fixture-vm'}] if getattr(self.server,'saved_vm',False) else [],'auto_connect':getattr(self.server,'auto_enabled',True),'desktop':{'ready':False},'install_command':'brew install openai/tools/tart'}
        elif action=='save_preferences':
            self.server.auto_enabled=args['auto_connect'];value={'state':'completed'}
        elif action=='auto_connect':
            self.server.auto_count=getattr(self.server,'auto_count',0)+1
            value={'state':'queued','request_id':'auto_connect'}
        elif action=='result':
            if args['request_id']=='auto_connect':self.server.vm_connected=True
            value={'state':'completed','backend':'tart','vms':[{'name':'fixture-vm','state':'stopped'}]} if args['request_id']=='list' else {'state':'completed','vm':'fixture-vm','account':'Tart Guest Agent','transfer_verified':False}
        else:value={'state':'queued','request_id':action}
        self.respond(200,{'result':value})


class TartBrowser(unittest.TestCase):
    @unittest.skipUnless(base.m.EDGE.exists(),'No real test browser')
    def test_opening_panel_auto_connects_once_and_preference_can_disable_it(self):
        check=r"""
const waitVm=async test=>{const end=Date.now()+6000;while(!test()&&Date.now()<end)await new Promise(r=>setTimeout(r,25));if(!test())throw Error('auto-connect UI timeout');};
const toggle=document.getElementById('configModalToggle');toggle.checked=true;toggle.dispatchEvent(new Event('change'));
await waitVm(()=>document.getElementById('vmSettingsBadge').textContent==='命令已连接');
await H.connectSavedVm();
const auto=document.getElementById('tartAutoConnect');auto.checked=false;auto.dispatchEvent(new Event('change'));
await waitVm(()=>document.getElementById('vmConnectionStatus').textContent.includes('已关闭自动连接'));
if((await H.client.postAction('vm_control',{action:'status'})).auto_connect!==false)throw Error('auto-connect preference not persisted');
toggle.checked=false;
"""
        server=base.Server(('127.0.0.1',0),Fixture);server.saved_vm=True
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            with patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS",check+"out.textContent='PASS")):
                result=base.browser_run([str(base.m.EDGE),'--window-size=800,600',f'http://127.0.0.1:{server.server_port}/'],timeout=30)
                found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
                self.assertTrue(found and found.group(1).startswith('PASS'),found.group(1) if found else 'No result')
                self.assertEqual(server.auto_count,1)
        finally:server.shutdown();server.server_close();thread.join()

    @unittest.skipUnless(base.m.EDGE.exists(),'No real test browser')
    def test_tart_setup_has_no_windows_credentials_or_unverified_success(self):
        server=base.Server(('127.0.0.1',0),Fixture)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            with patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")):
                result=base.browser_run([str(base.m.EDGE),'--window-size=800,600',f'http://127.0.0.1:{server.server_port}/'],timeout=30)
                found=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
                self.assertTrue(found and found.group(1).startswith('PASS'),found.group(1) if found else 'No result')
        finally:server.shutdown();server.server_close();thread.join()
