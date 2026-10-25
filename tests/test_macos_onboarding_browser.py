import json,re,tempfile,threading,unittest
from unittest.mock import patch
import test_nine_browser as base
from desktop.first_run import action
from hub.core import Hub,HubError

DRIVER=r"""window.__HUB_NATIVE_MACOS__=true;document.documentElement.classList.add('native-macos');document.body.classList.add('hub-window-body');
addEventListener('DOMContentLoaded',async()=>{
 const out=document.createElement('pre');out.id='result';document.body.append(out);
 const wait=async fn=>{const end=Date.now()+8000;while(!fn()&&Date.now()<end)await new Promise(r=>setTimeout(r,25));if(!fn())throw Error('first-run timeout');};
 try{
  await wait(()=>window.HubDesktop);const H=window.HubDesktop;
  document.getElementById('token').value='fixture';document.getElementById('loginForm').dispatchEvent(new Event('submit',{cancelable:true}));
  await wait(()=>H.firstRunChecked);
  if(sessionStorage.getItem('guide-completed')){
   if(!document.getElementById('setupWizard').hidden)throw Error('completed guide reopened');
   out.textContent='PASS first run persisted and does not reopen';return;
  }
  const root=document.getElementById('setupWizard');if(root.hidden)throw Error('first run not shown');
  const later=document.getElementById('setupClose');if(getComputedStyle(later).display==='none'||later.getBoundingClientRect().height<1)throw Error('native skip action hidden');
  const editor=document.getElementById('discussionReply');editor.value='keep draft';
  document.getElementById('setupNext').click();await wait(()=>document.getElementById('setupSkipVm')&&!document.getElementById('setupNext').disabled);
  if(!document.getElementById('setupBody').textContent.includes('Tart'))throw Error('wrong VM provider');
  document.getElementById('setupNext').click();await wait(()=>document.getElementById('setupError').textContent.includes('Tart')&&!document.getElementById('setupNext').disabled);
  const skip=document.getElementById('setupSkipVm');skip.checked=true;skip.dispatchEvent(new Event('change'));
  document.getElementById('setupNext').click();await wait(()=>document.getElementById('setupNext').textContent==='完成配置'&&!document.getElementById('setupNext').disabled);
  const next=document.getElementById('setupNext');next.scrollIntoView({block:'nearest'});
  if(next.getBoundingClientRect().bottom>innerHeight+1)throw Error('finish button clipped');
  next.click();await wait(()=>root.hidden);
  if(editor.value!=='keep draft')throw Error('guide lost draft');
  if((await H.client.postAction('desktop_onboarding',{operation:'status'})).needed)throw Error('completion not saved');
  sessionStorage.setItem('guide-completed','1');location.reload();
 }catch(e){out.textContent='FAIL '+e.stack;}
});"""


class Fixture(base.Fixture):
    def do_POST(self):
        try:
            payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            if payload.get('action')=='desktop_onboarding':
                value=action(self.server.hub,self.actor(),**payload.get('args',{}))
            elif payload.get('action')=='vm_control':value={'backend':'tart','connected':False,'installed':False,'supported':True,'homebrew_installed':True}
            else:value={}
            self.respond(200,{'result':value})
        except HubError as error:self.respond(400,{'error':str(error)})


class OnboardingBrowser(unittest.TestCase):
    @unittest.skipUnless(base.m.EDGE.exists(),'Real browser unavailable')
    def test_first_run_skip_reload_and_visible_finish(self):
        for size in ('1280,800','800,600'):
            with self.subTest(size=size),tempfile.TemporaryDirectory() as directory:
                hub=Hub(directory,recover=False);hub.tokens['user']='fixture'
                server=base.Server(('127.0.0.1',0),Fixture);server.hub=hub
                thread=threading.Thread(target=server.serve_forever);thread.start()
                try:
                    with patch.object(base,'DRIVER',DRIVER):
                        response=base.browser_run([str(base.m.EDGE),'--window-size='+size,f'http://127.0.0.1:{server.server_port}/'],timeout=30)
                        result=re.search(r'<pre id="result">(.*?)</pre>',response.stdout,re.S)
                        self.assertTrue(result and result.group(1).startswith('PASS'),result.group(1) if result else 'no result')
                finally:server.shutdown();server.server_close();thread.join();hub.db.close()
