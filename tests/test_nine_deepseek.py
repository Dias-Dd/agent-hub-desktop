import json,tempfile,time,unittest
from pathlib import Path
from hub.core import Hub,HubError
from hub.identities import AGENTS
from hub.codex_runtime import CodexRuntime
from hub.antigravity import AntigravityRuntime
from hub.deepseek_runtime import DeepSeekRuntime
from hub.workflows import Workflows
from hub.planning import Planning
from hub.coordination import Coordination

class API:
 def __init__(self):self.answers=[];self.requests=[]
 def request(self,path,payload=None):
  self.requests.append((path,payload))
  if path=='/models':return {'data':[{'id':'deepseek-flash'}]}
  content=self.answers.pop(0) if self.answers else 'ok'
  return {'choices':[{'message':{'role':'assistant','content':content,'tool_calls':[]},'finish_reason':'stop'}],'usage':{'prompt_tokens':3,'completion_tokens':2}}

class NineDeepSeek(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.h=Hub(self.t.name);self.api=API()
  self.c=CodexRuntime(self.h);self.a=AntigravityRuntime(self.h);self.c.models={};self.a.models={}
  self.d=DeepSeekRuntime(self.h,self.api);self.d.validate('user')
  self.d.configure_api('user',self.t.name,'full',0,600,0,1,1,0,256,True,False,True)
  self.w=Workflows(self.h,[self.c,self.a,self.d]);self.co=Coordination(self.h,[self.c,self.a,self.d],self.w);self.p=Planning(self.h,self.d,self.w)
 def tearDown(self):self.h.db.close();self.t.cleanup()
 def running(self,ident):
  with self.h.tx():self.h.db.execute("update executions set status='running',started=? where id=?",(time.time(),ident))
  return dict(self.h.db.execute('select * from executions where id=?',(ident,)).fetchone())
 def test_nine_real_names_and_isolated_context(self):
  self.assertEqual({a[0] for a in AGENTS},{f'deepseek-{i}' for i in range(1,10)})
  for a in AGENTS:
   self.assertEqual(a[1],'DeepSeek Flash');self.assertIs(self.w.runtime(a[0]),self.d)
   run=self.d.submit('user',a[0],'hello',True,purpose='question',session_scope='hub-project:test')
   self.d.execute(self.running(run['id']))
   payload=self.api.requests[-1][1]
   self.assertIn(a[0],payload['messages'][0]['content']);self.assertIn('DeepSeek',payload['messages'][0]['content']);self.assertEqual(payload['tools'],[])
  self.assertEqual(self.h.db.execute('select count(*) from deepseek_context').fetchone()[0],9)
 def test_no_budget_sentinel_and_no_call_cap(self):
  for _ in range(12):self.d.submit('user','deepseek-1','new task',True)
  s=self.d.snapshot('user');self.assertIsNone(s['remaining_runs']);self.assertIsNone(s['remaining_cents']);self.assertTrue(s['unlimited'])
  self.assertIsNone(self.d.config()['budget_cents']);self.assertIsNone(self.d.config()['max_requests'])
 def test_discussion_does_not_execute_until_approval(self):
  opts=dict(cwd=self.t.name,agents=['deepseek-1','deepseek-3'],max_calls=3,expires_minutes=60,max_parallel=2,max_seconds=600,reviewer='deepseek-3',auto_wake=True,delegate_stop=False,max_hops=4,max_messages=12)
  s=self.p.message('user','make a plan',options=opts,confirmed=True,project_id=None)
  self.api.answers.append(json.dumps({'done':False,'report':'review this plan','tasks':[{'agent':'deepseek-1','instruction':'write a file'}]}))
  self.d.execute(self.running(s['pending']));self.p.patrol();s=self.p.get(s['id'])
  self.assertEqual(s['state'],'awaiting_approval');self.assertEqual(self.w.snapshot('user'),[]);self.assertEqual(self.api.requests[-1][1]['tools'],[])
  w=self.p.message('user','按计划执行',session_id=s['id'],revision=s['revision'])
  workflow=self.w.snapshot('user')[0];self.assertEqual(workflow['manager'],'deepseek-4');self.assertTrue(workflow['unlimited_calls'])
 def test_manager_tools_use_current_actor_and_bypass_project_call_budget(self):
  w=self.w.start('user','approved scope',['deepseek-1','deepseek-2','deepseek-3'],max_calls=3,confirmed=True,reviewer='deepseek-3',approved_proposal={'done':False,'report':'approved','tasks':[{'agent':'deepseek-1','instruction':'work'}]})
  task=self.w.add_step(w,'deepseek-4','plan','schedule work');self.d.submit('user','deepseek-4','schedule work',True,task_id=task)
  run=dict(self.h.db.execute('select * from executions where task_id=?',(task,)).fetchone());run=self.running(run['id'])
  tools=self.d.definitions(run);names={t['function']['name'] for t in tools}
  self.assertIn('project_assign',names);self.assertIn('project_complete',names)
  answer=self.d.tool(run,'project_assign',{'agent':'deepseek-2','instruction':'independent job','request_key':'one'},names)
  self.assertTrue(answer['task_id'])
  with self.assertRaises(HubError):self.w.project_assign('deepseek-1',run['id'],'deepseek-2','bad','bad')
 def test_tools_and_stop_latch(self):
  r=self.d.submit('user','deepseek-2','write',True);run=self.running(r['id'])
  self.d.tool(run,'write_file',{'path':'x.txt','content':'saved'},{'write_file'})
  self.assertEqual(Path(self.t.name,'x.txt').read_text(),'saved')
  self.co.halt('user','deepseek-2','test stop')
  with self.assertRaises(HubError):self.d.guard(run)

 def test_more_than_32_api_requests_in_one_authorized_turn(self):
  r=self.d.submit('user','deepseek-1','read repeatedly for test',True)
  run=self.running(r['id']);Path(self.t.name,'input.txt').write_text('fixture')
  counter=[0]
  def request(path,payload=None):
   counter[0]+=1
   if counter[0]<=35:
    message={'role':'assistant','content':None,'tool_calls':[{'id':'tool-'+str(counter[0]),'type':'function','function':{'name':'read_file','arguments':json.dumps({'path':'input.txt'})}}]}
   else:message={'role':'assistant','content':'done'}
   return {'choices':[{'message':message}]}
  self.d.api.request=request;self.d.execute(run)
  self.assertEqual(counter[0],36)
  self.assertEqual(self.h.db.execute('select status from executions where id=?',(run['id'],)).fetchone()[0],'completed')

if __name__=='__main__':unittest.main()
