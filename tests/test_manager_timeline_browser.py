import test_nine_browser as base
from test_demo_cards_browser import Fixture as Artifacts
from unittest.mock import patch
class Fixture(Artifacts):
 def respond(self,status,body,*args,**kwargs):
  if isinstance(body,dict) and 'agents' in body:
   body['designs']=[{'id':'design-1','state':'approved','version':1,'created':1,'approved_at':1.5,'versions':[{'created':1.2}]}]
   body['manager_messages']=[{'id':'direct','sender':'deepseek-4','recipient':'user','created':5,'status':'user_delivered','body':'DIRECT MANAGER MESSAGE'}]
  result=super().respond(status,body,*args,**kwargs)
  return result
EXTRA=r"""
const taskId='a'.repeat(32),store=H.store,saved=store.rawState;store.rawState={...saved,tasks:[...(saved.tasks||[]),{id:taskId}],messages:[...(saved.messages||[]),{id:'generated-task',sender:'user',recipient:'deepseek-4',body:'[task:'+taskId+'] auto inspection',created:99}],manager_messages:[]};if(store.getManagerDiscussionStream().userDirectMessages.some(m=>m.id==='generated-task'))throw Error('platform task impersonates user');const generated=store.getAgentActivityStream().timeline.find(m=>m.id==='generated-task');if(generated)throw Error('routine scheduler envelope exposed in activity');if(store.isTaskEnvelope({body:'[task:'+'b'.repeat(32)+'] quoted text'}))throw Error('ordinary user text misclassified');store.rawState=saved;

const noticeTask='c'.repeat(32),activeManager=store.getManagerDiscussionStream().manager;
store.rawState={...saved,tasks:[...(saved.tasks||[]),{id:noticeTask}],messages:[{id:'source-platform',sender:'平台',recipient:activeManager,body:'[task:'+noticeTask+'] 平台通知：成员执行已结束。请核查',created:100}],manager_messages:[]};
const notice=store.getAgentActivityStream().timeline.find(m=>m.id==='source-platform');
if(!notice||notice.title!=='平台 → '+activeManager||notice.body.includes('[task:'))throw Error('platform notice source not explicit');
if(store.getManagerDiscussionStream().userDirectMessages.some(m=>m.id==='source-platform'))throw Error('platform notice displayed as human');
store.rawState=saved;

const screenshot=H.artifactMessage({id:'s',kind:'image',entry:'screenshot.png',caption:'网页测试截图',url:'/api/shared/'+'d'.repeat(64)+'/screenshot.png',created:6,sender:'deepseek-4'});if(screenshot.querySelector('img')||screenshot.querySelector('iframe')||!screenshot.querySelector('a'))throw Error('web screenshot still auto previews');
const history=document.getElementById('discussionHistory');
const design=history.querySelector('[data-design]'),web=history.querySelector('[data-artifact="'+ 'a'.repeat(64)+'"]'),direct=history.querySelector('[data-message-id="direct"]');
if(!design||!web||!direct)throw Error('missing design, artifact or direct manager message');
const rows=[...history.children];if(!(rows.indexOf(design)<rows.indexOf(web)&&rows.indexOf(web)<rows.indexOf(direct)))throw Error('mixed timeline is not chronological');
if(web.querySelector('iframe')||!web.querySelector('a'))throw Error('web preview still present');
if(document.getElementById('managerReadingArea').contains(document.getElementById('designStatusCard')))throw Error('duplicate pinned design card');
const attachment=web.querySelector('.artifact-web-link');
if(getComputedStyle(attachment).borderTopStyle!=='solid'||parseFloat(getComputedStyle(attachment).borderTopWidth)!==1)throw Error('attachment outline missing');
if(innerWidth>900&&web.getBoundingClientRect().width>=history.getBoundingClientRect().width-40)throw Error('attachment is not compact');
if(attachment.querySelector('.artifact-file-icon')&&getComputedStyle(attachment.querySelector('.artifact-file-icon')).position!=='static')throw Error('attachment icon escaped card');
const first=direct;await H.store.refresh(true);if(document.querySelector('[data-message-id="direct"]')!==first)throw Error('timeline refresh replaced stable message');
"""
class Browser(base.Browser):
 def test_nine(self):
  with patch.object(base,'Fixture',Fixture),patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS nine",EXTRA+"out.textContent='PASS mixed chronological timeline; nine")):super().test_nine()
