import json,re,threading,unittest
from pathlib import Path
from unittest.mock import patch
import test_nine_browser as base

CHECK=r"""
const pause=()=>new Promise(r=>setTimeout(r,150));
const $=id=>document.getElementById(id);
$('configModalToggle').checked=true;$('configModalToggle').dispatchEvent(new Event('change'));
document.querySelector('[aria-controls="vmSettings"]').click();await pause();
if($('tartSetupOptions').hidden)throw Error('Tart options hidden');
if($('vmSelection').getBoundingClientRect().top>$('vmThumbnail').parentElement.getBoundingClientRect().top)throw Error('selector not first');
if(!$('vmReconnectSaved').hidden||!$('vmConnectForm').querySelector('.vm-credentials-details').hidden||$('vmConnect').textContent!=='连接')throw Error('duplicate save controls');
if($('vmSettings').textContent.includes('root 已验证')||$('vmSettings').textContent.includes('默认保存在应用数据目录'))throw Error('removed copy still present');
if(!$('tartEnvironment').closest('.vm-status-surface').contains($('vmConnectionStatus')))throw Error('status not combined');
$('vmRefresh').click();await pause();
if($('vmSelect').value!=='mac-test')throw Error('VM selection missing');
$('tartReadResources').click();await pause();
if($('tartManageCpu').value!=='3'||$('tartManageMemory').value!=='4352')throw Error('actual resources missing');
const draft=$('discussionReply');draft.value='Tart settings preserve draft';
$('tartDelete').scrollIntoView({block:'center'});$('tartDelete').click();await pause();
const dialog=document.getElementById('tartConfirmDialog');
if(!dialog||!dialog.textContent.includes('永久删除 mac-test'))throw Error('targeted deletion confirmation missing');
const bounds=dialog.getBoundingClientRect();if(bounds.bottom>innerHeight+1||bounds.top<0)throw Error('confirmation clipped');
dialog.querySelector('.secondary-btn').click();
$('tartEditHome').click();await pause();if(!$('tartDirectoryDialog').open)throw Error('directory dialog absent');
$('tartHome').value='/tmp/new-mac-vms';$('tartHome').dispatchEvent(new Event('input'));
$('tartCreate').click();await pause();
if(!$('vmConnectionStatus').textContent.includes('尚未应用'))throw Error('unapplied directory was used');
$('tartSaveHome').click();await pause();
document.getElementById('tartConfirmDialog').querySelector('.primary-btn').click();await pause();await pause();
if($('vmSelect').value!=='mac-new-location'||!$('tartActiveHome').textContent.includes('/tmp/new-mac-vms'))throw Error('directory/list out of sync');
$('tartOpenAccessibility').click();await pause();if(!$('tartAccessibilityDialog').open)throw Error('accessibility dialog absent');
$('tartCheckAccessibility').click();await pause();if(!$('tartAccessibilityStatus').textContent.includes('控件通道已就绪'))throw Error('permission probe missing');
$('tartAccessibilityDialog').close();
$('tartOpenInstaller').click();await pause();if(!$('tartInstallDialog').open)throw Error('installer dialog absent');$('tartSourceType').value='tvm';$('tartSource').value='/tmp/manual.tvm';
$('tartCreate').scrollIntoView({block:'center'});
let rect=$('tartCreate').getBoundingClientRect();if(rect.top<0||rect.bottom>innerHeight)throw Error('create has no scroll path');
$('tartCreate').click();await pause();
const createDialog=document.getElementById('tartConfirmDialog');if(!createDialog)throw Error('install confirmation missing');
createDialog.querySelector('.primary-btn').click();await pause();await pause();
if(!$('vmConnectionStatus').textContent.includes('root 已验证'))throw Error('auto install/create/connect did not finish');
$('tartInstallDialog').close();$('configModalToggle').checked=false;$('configModalToggle').dispatchEvent(new Event('change'));
if(draft.value!=='Tart settings preserve draft')throw Error('draft lost');
window.HubI18n.set('en');await pause();
if($('tartCreate').textContent!=='Install Tart, create and connect a VM'||$('tartDelete').textContent!=='Delete selected VM')throw Error('Tart controls not translated');
window.HubI18n.set('zh-CN');await pause();
"""
class Fixture(base.Fixture):
 home="/tmp/AgentHub/TartVMs"
 def do_POST(self):
  payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))));args=payload.get('args',{});action=args.get('action');value={}
  if payload.get('action')=='vm_control':
   if action=='status':value={'backend':'tart','supported':True,'installed':True,'helper_alive':True,'connected':True,'vm':'mac-test','power_state':'Running','tart_home':Fixture.home,'max_cpu':8,'root_verified':True,'console_user':'admin','desktop':{'ready':False},'transfer_verified':True}
   elif action=='set_home':
    Fixture.home=args['tart_home'];value={'state':'completed','tart_home':Fixture.home}
   elif action=='list':value={'state':'completed','backend':'tart','vms':[{'name':'mac-new-location' if Fixture.home=='/tmp/new-mac-vms' else 'mac-test','state':'running'}]}
   elif action=='peekaboo_status':value={'state':'completed','accessibility':{'ready':True,'permissions':[{'name':'Accessibility','isGranted':True}]}}
   elif action=='details':value={'state':'completed','vm':'mac-test','details':{'CPU':3,'Memory':4352}}
   elif action=='create':
    if args['source_type']!='tvm' or args['source']!='/tmp/manual.tvm':raise AssertionError('manual source not passed')
    value={'state':'completed','vm':args['vm_name'],'created':True}
   elif action=='connect':value={'state':'completed','vm':args['vm_name'],'root_verified':True,'desktop_verified':True}
  self.respond(200,{'result':value})

@unittest.skipUnless(base.m.EDGE.exists(),'browser unavailable')
class Browser(unittest.TestCase):
 def test_tart_management_at_all_viewports(self):
  driver=base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  server=base.Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   with patch.object(base,'DRIVER',driver):
    for size in ('1440,900','1024,600','600,800'):
     with self.subTest(size=size):
      Fixture.home='/tmp/AgentHub/TartVMs'
      screenshot=Path('local-data/macos-validation')/('settings-'+size.replace(',','x')+'.png');screenshot.parent.mkdir(parents=True,exist_ok=True)
      result=base.browser_run([str(base.m.EDGE),'--window-size='+size,f'http://127.0.0.1:{server.server_port}/'],timeout=30,screenshot=str(screenshot),after_checks=lambda ws:ws.call('Runtime.evaluate',{'expression':"document.getElementById('configModalToggle').checked=true;document.getElementById('configModalToggle').dispatchEvent(new Event('change'));document.querySelector('[aria-controls=vmSettings]').click();document.getElementById('tartOpenInstaller').click();"}))
      matched=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
      self.assertTrue(matched and matched.group(1).startswith('PASS'),matched.group(1) if matched else 'no result')
  finally:server.shutdown();server.server_close();thread.join()
