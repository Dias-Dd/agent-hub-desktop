import re
import tempfile
import threading
import unittest
import test_nine_browser as base
from test_connection_tests_browser import Fixture

CHECK = r"""
document.getElementById('viewModeStatusRadio').checked=true;
await new Promise(r=>setTimeout(r,100));
const card=document.querySelector('#agents [data-agent="deepseek-1"]');
const actions=card.querySelector('.agent-card-test-actions');
if(!actions||actions.getBoundingClientRect().bottom>card.getBoundingClientRect().bottom+1)throw Error('test actions clipped');
const previous=H.store.rawState;
const message={id:'user-message',sender:'user',recipient:'deepseek-4',body:'same request',created:100,discussion_session_id:'p',discussion_run_id:'run'};
H.store.rawState={...previous,selected_manager:'deepseek-4',planning:[{id:'p',manager:'deepseek-4',pending:'run',created:100,history:[{role:'user',text:'same request',input_run_id:'run',message_id:'user-message'}]}],messages:[message],workflows:[{id:'w',manager:'deepseek-4',status:'active',requirement:'same request',created:100}]};
let stream=H.store.getManagerDiscussionStream();
if([...stream.history,...stream.userDirectMessages].filter(m=>m.isUser).length!==1)throw Error('pending user request duplicated');
H.store.rawState.messages.push({...message,id:'later',created:200,discussion_run_id:'run2'});
stream=H.store.getManagerDiscussionStream();
if(stream.userDirectMessages.length!==2)throw Error('legitimate repeated request lost');
H.store.rawState={...previous,projects:[],planning:[],workflows:[],messages:[]};
document.getElementById('viewModeChatRadio').checked=true;
H.store._notify();await new Promise(r=>setTimeout(r,100));
const welcome=document.getElementById('emptyWorkspace');
if(welcome.hidden||getComputedStyle(welcome).display==='none')throw Error('empty welcome missing');
if(getComputedStyle(document.getElementById('sidebarRight')).display!=='none'||getComputedStyle(document.getElementById('viewChatMode')).display!=='none')throw Error('stale workspace visible');
if(!document.getElementById('createFirstProject'))throw Error('create first project missing');
document.getElementById('viewModeStatusRadio').checked=true;
if(getComputedStyle(welcome).display!=='none')throw Error('welcome covers Agent panel');
H.store.rawState=previous;
document.getElementById('verifyIntegrationsHeader').click();
const confirm=document.getElementById('connectionTestDialog');
const nativeCSS=document.createElement('link');nativeCSS.rel='stylesheet';nativeCSS.href='/windows.css';await new Promise((resolve,reject)=>{nativeCSS.onload=resolve;nativeCSS.onerror=reject;document.head.append(nativeCSS);});
out.style.display='none';document.body.replaceChildren(confirm,out);document.body.className='hub-window-body';
document.body.style.height='310px';document.body.style.width='620px';confirm.dataset.detachedWindow='1';
await new Promise(r=>setTimeout(r,30));
const start=[...confirm.querySelectorAll('button')].find(b=>b.textContent==='开始真实测试');
if(start.getBoundingClientRect().bottom>310||confirm.scrollHeight>confirm.clientHeight+2)throw Error('compact native test dialog clips actions '+JSON.stringify({scroll:confirm.scrollHeight,client:confirm.clientHeight,bottom:start.getBoundingClientRect().bottom}));
"""


@unittest.skipUnless(base.m.EDGE.exists(), 'Edge unavailable')
class Browser(unittest.TestCase):
    def test_empty_workspace_duplicates_and_completed_test_geometry(self):
        original=base.DRIVER
        base.DRIVER=original.replace("out.textContent='PASS", CHECK+"out.textContent='PASS")
        server=base.Server(('127.0.0.1',0),Fixture)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            for size in ('1440,900','1024,600','600,800'):
                with self.subTest(size=size), tempfile.TemporaryDirectory() as folder:
                    result=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size='+size,'--user-data-dir='+folder,'--dump-dom','--virtual-time-budget=6000','http://127.0.0.1:'+str(server.server_port)+'/'],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
                    match=re.search(r'<pre id="result"[^>]*>(.*?)</pre>',result.stdout,re.S)
                    self.assertIsNotNone(match);self.assertTrue(match.group(1).startswith('PASS'),match.group(1))
        finally:
            server.shutdown();server.server_close();thread.join();base.DRIVER=original
