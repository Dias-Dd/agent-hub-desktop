import json
from unittest.mock import patch
import test_nine_browser as base
class Reports(base.Browser):
 def test_nine(self):
  respond=base.Fixture.respond
  def fixture(handler,status,data,*args,**kwargs):
   if isinstance(data,dict) and 'all_deepseek' in data:
    task='a'*32;data['tasks']=[{'id':task,'agent':'deepseek-4','title':'manager copy','prompt':'task original source'}]
    data['messages']=[{'id':'report','sender':'deepseek-1','recipient':'deepseek-4','body':'[主动汇报] '+json.dumps({'run':'worker-run','summary':'已完成三页','risk':'high','evidence':['layout verified']},ensure_ascii=False),'status':'completed','created':2,'request_key':'report:worker-run'},{'id':'copy','sender':'user','recipient':'deepseek-4','body':'[task:'+task+'] copied report','status':'completed','created':3}]
    data['coordination']={'reports':[{'run':'worker-run','summary':'已完成三页','risk':'high','created':2}],'wakeups':[{'message':'report','status':'batched','note':'已入队'}]}
   return respond(handler,status,data,*args,**kwargs)
  check="""const items=H.view.agentStream.timeline;if(items.length!==1||items[0].id!=='report')throw Error('report duplicated: '+JSON.stringify(items));if(!items[0].body.includes('已完成三页')||!items[0].body.includes('high')||items[0].body.includes('[主动汇报]'))throw Error('report not readable');if(!items[0].prompt.includes('worker-run'))throw Error('original report missing');const inspect=document.querySelector('#messages button[title="查看实际模型输入"]');if(!inspect)throw Error('source button missing');inspect.click();if(!document.getElementById('chatSourceDialog').open||!document.getElementById('chatSourceText').textContent.includes('worker-run'))throw Error('original report reader broken');document.getElementById('chatSourceDialog').close();document.querySelector('#tasks button[title="查看实际模型输入"]').click();if(!document.getElementById('chatSourceDialog').open||document.getElementById('chatSourceText').textContent!=='task original source')throw Error('task source reader broken');document.getElementById('chatSourceDialog').close();"""
  driver=base.DRIVER.replace("H.store.stopPolling();out.textContent",check+"H.store.stopPolling();out.textContent")
  with patch.object(base.Fixture,'respond',fixture),patch.object(base,'DRIVER',driver):super().test_nine()
