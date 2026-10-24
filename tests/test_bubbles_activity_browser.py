import unittest,threading,tempfile,subprocess,re
import test_live_browser as live
class Fixture(live.Fixture):
 def respond(self,status,body,kind='application/json'):
  if isinstance(body,dict) and 'agents' in body:body['deepseek']['events']=[{'seq':1,'run_id':'live','kind':'deepseek.harness.tool','data':'{"toolCallId":"tool","title":"读取项目文件","status":"in_progress"}'}]
  return super().respond(status,body,kind)
CHECK="""
const wait=()=>new Promise(r=>setTimeout(r,120));await wait();
const message=H.chatMessage('用户 (你)','请把界面做得清爽一些。','completed',1800000000);H.list('discussionHistory',[message]);await wait();
const row=document.querySelector('#discussionHistory .chat-message'),bubble=row.querySelector('.chat-message-body');
if(row.dataset.role!=='user'||getComputedStyle(bubble).backgroundColor==='rgba(0, 0, 0, 0)'||parseFloat(getComputedStyle(bubble).borderTopRightRadius)<10)throw Error('user bubble missing');
if(Math.abs(bubble.getBoundingClientRect().right-row.getBoundingClientRect().right)>2)throw Error('bubble not on right');
const body=document.getElementById('managerLiveText'),operations=document.getElementById('managerOperations');
if(operations.hidden||!(body.compareDocumentPosition(operations)&Node.DOCUMENT_POSITION_FOLLOWING))throw Error('operations not below streaming body');
if(!operations.textContent.includes('deepseek-4')||!operations.textContent.includes('读取项目文件'))throw Error('operation agent absent');
const dot=operations.querySelector('i');if(!matchMedia('(prefers-reduced-motion: reduce)').matches&&getComputedStyle(dot).animationName!=='operation-pulse')throw Error('activity animation absent');
if(document.getElementById('discussionStatus').classList.contains('is-loading')||document.getElementById('discussionStatus').textContent.includes(' · v'))throw Error('header still showing live action/old version');
const stage=(state,workflow,design,extra={})=>H.chatStageLabel({managerStream:{planning:{sessionId:'p',state},workflow},rawSnapshot:{planning:[{id:'p',workflow_id:'w',...extra}],workflows:workflow?[{id:'w',...workflow}]:[],designs:design?[design]:[]}});
if(stage('executing',{status:'completed',delivery_stage:'implementation'})!=='正式制作 · 已完成')throw Error('completed still executing');
if(stage('designing',{status:'completed',design_review:'d'},{id:'d',state:'review'})!=='演示待确认')throw Error('demo acceptance status wrong');
if(stage('executing',{status:'paused',delivery_stage:'implementation'})!=='正式制作 · 已暂停')throw Error('paused still executing');
if(stage('awaiting_approval',{status:'completed',design_review:'d'},null,{design_approved:{id:'d'}})!=='正式制作 · 待启动')throw Error('old demo completion leaked to production');
const snapshot=H.store.rawState;snapshot.deepseek.runs=[{id:'worker','agent':'deepseek-1','status':'running',created:2}];snapshot.planning[0].pending=null;snapshot.planning[0].state='executing';snapshot.live_replies=[];H.store._notify();
if(document.getElementById('managerLiveReply').hidden||!body.hidden||!operations.textContent.includes('deepseek-1'))throw Error('worker-only operation disappears');
snapshot.deepseek.runs[0].status='completed';H.store._notify();if(!operations.hidden||!document.getElementById('managerLiveReply').hidden)throw Error('finished work still animating');
"""
class Browser(unittest.TestCase):
 @unittest.skipUnless(live.base.m.EDGE.exists(),'Edge unavailable')
 def test_bubble_activity_tail_and_accurate_phase(self):
  original=live.base.DRIVER;live.base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  s=live.base.Server(('127.0.0.1',0),Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   for size in ['1440,900','1024,600','600,800']:
    with self.subTest(size=size),tempfile.TemporaryDirectory() as folder:
     r=subprocess.run([str(live.base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size='+size,'--user-data-dir='+folder,'--dump-dom','--virtual-time-budget=8000','http://127.0.0.1:'+str(s.server_port)+'/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
     match=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(match);self.assertTrue(match.group(1).startswith('PASS'),match.group(1));print('PASS right bubble, operation animation below stream, idle/finished and stage labels at '+size)
  finally:s.shutdown();s.server_close();t.join();live.base.DRIVER=original
