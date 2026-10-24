import time,json
from unittest.mock import patch
import test_nine_browser as base
class Fixture(base.Fixture):
 actions=[]
 def respond(self,status,body,*args,**kwargs):
  if isinstance(body,dict) and 'agents' in body:
   for i,a in enumerate(body['agents']):a['profile']={'name':'Very long model name that must stay in one line and scroll automatically '+str(i),'connection_id':'deepseek-default','model':'DeepSeek Flash','enabled':True}
   body['timers']=[{'id':'timer-fixture','creator':'deepseek-1','recipient':'deepseek-2','note':'检查额度恢复并继续工作','due':time.time()+3660,'state':'scheduled','generation':1,'created':1}]
  return super().respond(status,body,*args,**kwargs)
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
  if data.get('action')=='timer_cancel':self.actions.append(data['args'])
  self.respond(200,{'result':{}})
class Browser(base.Browser):
 def test_nine(self):
  extra="""await new Promise(r=>setTimeout(r,150));const list=document.getElementById('agentMiniStates'),name=list.querySelector('.agent-mini-name');if(getComputedStyle(list).maxHeight!=='none'||getComputedStyle(list).overflowY!=='visible')throw Error('mini states still have inner scroll');if(!name.classList.contains('is-overflowing'))throw Error('long name not detected');const span=name.firstElementChild;if(getComputedStyle(span).whiteSpace!=='nowrap'||getComputedStyle(span).animationName==='none')throw Error('name animation missing');const row=document.querySelector('[data-timer="timer-fixture"]');if(!row||!/^01:0[01]:[0-5][0-9]$/.test(row.querySelector('.timer-countdown').textContent))throw Error('HH:MM:SS countdown absent');if(!row.querySelector('.timer-note').textContent.includes('额度恢复')||!row.querySelector('.timer-route').textContent.includes('→'))throw Error('timer note/route missing');if(getComputedStyle(row).borderRadius!=='20px')throw Error('timer card style missing');row.querySelector('.timer-dismiss').click();await new Promise(r=>setTimeout(r,150));if(document.querySelector('[data-timer="timer-fixture"]'))throw Error('cancelled timer card not dismissed');"""
  Fixture.actions=[]
  run=base.subprocess.run
  def visible(args,**kwargs):return run([args[0],'--window-size=1440,900',*args[1:]],**kwargs)
  with patch.object(base.subprocess,'run',side_effect=visible),patch.object(base,'Fixture',Fixture),patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS nine",extra+"out.textContent='PASS growing mini states, marquee, timer card and cancel; nine")):super().test_nine()
  self.assertEqual(Fixture.actions,[{'timer_id':'timer-fixture'}])


