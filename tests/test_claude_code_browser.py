import json
import re
import tempfile
import threading
import unittest
import test_nine_browser as base

CHECK=r"""
await H.action('enable_claude_fixture',{});await H.store.refresh(true);
document.getElementById('openIntegrations').click();document.getElementById('newIntegrationAgent').click();
const select=document.getElementById('agentConnection');
if(![...select.options].some(o=>o.value==='claude-local'))throw Error('Claude Code missing from add-agent selection');
select.value='claude-local';select.dispatchEvent(new Event('change'));
const actions=document.getElementById('claudeConnectionActions');if(actions.hidden)throw Error('Claude setup actions hidden');
const waitUI=async predicate=>{const end=Date.now()+3000;while(!predicate()&&Date.now()<end)await new Promise(r=>setTimeout(r,20));if(!predicate())throw Error('Claude setup did not update');};
document.getElementById('claudeCheckLogin').click();await waitUI(()=>document.getElementById('claudeConnectionStatus').textContent.includes('fixture login ready'));
document.getElementById('claudeInstallHelp').click();document.getElementById('claudeOpenLogin').click();
document.getElementById('wizardNext').click();await waitUI(()=>!document.getElementById('agentWizardModelStep').hidden);
if(![...document.getElementById('agentModel').options].some(o=>o.value==='sonnet'))throw Error('Claude aliases missing');
const next=document.getElementById('saveIntegrationAgent').getBoundingClientRect();
if(next.width<=0||next.height<=0||next.bottom>innerHeight||next.top<0)throw Error('Claude add button clipped');
"""


class Fixture(base.Fixture):
    def respond(self,status,body,kind='application/json'):
        if self.path=='/api/state' and self.server.claude_enabled:
            body={**body,'integrations':{'connections':[{'id':'claude-local','kind':'claude-code','name':'Claude Code','installed':True,'enabled':False,'permission':'full','models':[]}],'agents':[]}}
        return super().respond(status,body,kind)

    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        action=data.get('action');args=data.get('args',{})
        if action=='enable_claude_fixture':self.server.claude_enabled=True
        if action=='integration_setup':self.server.operations.append(args['operation'])
        value={'state':'ready','message':'fixture login ready'} if action=='integration_setup' else {'models':[{'id':'sonnet','efforts':['default']}]} if action=='integration_probe' else {}
        self.respond(200,{'result':value})


@unittest.skipUnless(base.m.EDGE.exists(),'Browser unavailable')
class Browser(unittest.TestCase):
    def test_claude_setup_and_model_selection_at_three_sizes(self):
        original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
        server=base.Server(('127.0.0.1',0),Fixture);server.claude_enabled=False;server.operations=[]
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            for size in ('1440,900','1024,600','600,800'):
                server.claude_enabled=False;server.operations=[]
                with self.subTest(size=size),tempfile.TemporaryDirectory() as profile:
                    result=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size='+size,'--user-data-dir='+profile,'--dump-dom','--virtual-time-budget=7000',f'http://127.0.0.1:{server.server_port}/'],capture_output=True,encoding='utf-8',errors='replace',timeout=35)
                    match=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
                    self.assertIsNotNone(match);self.assertTrue(match.group(1).startswith('PASS'),match.group(1))
                    self.assertCountEqual(server.operations,['status','website','login'])
        finally:
            server.shutdown();server.server_close();thread.join();base.DRIVER=original
