import json,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import test_integrations as registry
from hub.core import HubError
from hub.live_replies import LiveReplies
from hub.projects import Projects
from hub.planning import Planning

class LiveTests(unittest.TestCase):
 def setUp(self):
  registry.RegistryTests.setUp(self);h=self.server.hub;h.planning=Planning(h,self.server.deepseek,self.server.workflows);Projects(h)
  self.project=h.projects.create('user','live');self.live=LiveReplies(h);h.live=self.live
  with h.tx():
   h.db.execute("INSERT INTO tasks(id,agent,title,assigned_by,created,project_id) VALUES('task','deepseek-4','discussion','user',?,?)",(time.time(),self.project['id']))
   h.db.execute("INSERT INTO executions(id,task_id,agent,status,purpose,provider,created,session_scope) VALUES('run','task','deepseek-4','running','discussion','deepseek',?,?)",(time.time(),'hub-project:'+self.project['id']))
 def tearDown(self):registry.RegistryTests.tearDown(self)
 def test_checkpoints_append_resume_and_do_not_approve(self):
  self.live.update('run','first');self.live.flush();self.live.update('run',' second',summary='public summary')
  draft=self.live.read('run',self.project['id']);self.assertEqual(draft['text'],'first second');self.assertEqual(draft['summary'],'public summary')
  self.live.next_flush=0;self.live.flush();self.assertEqual(LiveReplies(self.server.hub).read('run',self.project['id'])['text'],'first second')
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM planning_sessions').fetchone()[0],0)
  with self.assertRaises(HubError):self.live.read('run','other')
 def test_tool_reset_replaces_narration_not_final_answer(self):
  self.live.update('run','pre-tool');self.live.update('run','',replace=True,phase='tool started');self.live.update('run','final')
  self.assertEqual(self.live.read('run',self.project['id'])['text'],'final')
 def test_concurrent_checkpoint_does_not_lose_delta(self):
  def writer():
   for _ in range(150):self.live.update('run','x');time.sleep(.0003)
  thread=threading.Thread(target=writer);thread.start()
  while thread.is_alive():self.live.next_flush=0;self.live.flush();time.sleep(.001)
  thread.join();self.assertEqual(self.live.read('run',self.project['id'])['text'],'x'*150)
 def test_quota_groups_follow_actual_roster_not_nine_roles(self):
  groups=self.registry.quota_overview();self.assertEqual(len(groups),1);self.assertEqual(groups[0]['name'],'DeepSeek');self.assertEqual(len(groups[0]['unreadable']),1)
  c=self.registry.save_connection('user',{'kind':'codex','name':'OpenAI account','cwd':self.temp.name})
  for i in range(3):self.registry.save_agent('user',{'name':'GPT '+str(i),'model':'gpt-example','connection_id':c['id'],'effort':'medium','role':'worker'})
  c['official_windows']=[{'name':'primary','remaining':42,'resets_at':1800000000}]
  with self.server.hub.tx():self.registry.put('integration_connections',c)
  groups=self.registry.quota_overview();self.assertEqual(len(groups),2)
  self.assertEqual(len(next(g for g in groups if g['id']=='openai')['windows']),1)
 def test_deepseek_balance_only_reads_official_get_endpoint(self):
  c=self.registry.save_connection('user',{'kind':'deepseek-api','name':'DeepSeek API','cwd':self.temp.name})
  with patch('hub.integration_runtime.CompatibleAPI.request',return_value={'balance_infos':[{'currency':'CNY','total_balance':'21.50'}]}) as get:self.registry.refresh_quota('user',c['id']);get.assert_called_once_with('/user/balance')
  self.assertEqual(self.registry.get('integration_connections',c['id'])['official_balance'][0]['amount'],'21.50')
 def test_openrouter_key_limit_and_management_credit_are_separate(self):
  c=self.registry.save_connection('user',{'kind':'openrouter-api','name':'OpenRouter','cwd':self.temp.name})
  def get(path):return {'data':{'limit_remaining':9,'is_management_key':True}} if path=='/key' else {'data':{'total_credits':100.5,'total_usage':20.25}}
  with patch('hub.integration_runtime.CompatibleAPI.request',side_effect=get):self.registry.refresh_quota('user',c['id'])
  balances=self.registry.get('integration_connections',c['id'])['official_balance'];self.assertEqual([b['amount'] for b in balances],['9','80.25'])
  with patch('hub.integration_runtime.CompatibleAPI.request',side_effect=HubError('HTTP unavailable')):
   with self.assertRaises(HubError):self.registry.refresh_quota('user',c['id'])
  self.assertEqual(self.registry.get('integration_connections',c['id'])['official_balance'],balances)

class HarnessPrivacy(unittest.TestCase):
 def test_public_deltas_arrive_before_provider_end_without_private_thought(self):
  import test_harness as harness
  fixture=harness.HarnessTests();fixture.setUp();fixture.h.url='http://127.0.0.1:8765';projects=Projects(fixture.h);project=projects.create('user','fixture');fixture.h.live=LiveReplies(fixture.h)
  observed=[]
  class Stream(harness.FakeACP):
   def wait(self,ident,guard=None,timeout=60):
    if guard:guard()
    self.update({'update':{'sessionUpdate':'agent_thought_chunk','content':{'type':'text','text':'PRIVATE_THOUGHT_SENTINEL'}}})
    self.update({'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'public reply'}}})
    ident=fixture.h.db.execute('SELECT id FROM executions').fetchone()[0]
    observed.append(fixture.h.live.read(ident,project['id'])['text'])
    return {'stopReason':'end_turn'}
  try:
   run=fixture.d.submit('user','deepseek-1','new input only',True,purpose='question',session_scope='hub-project:'+project['id'])
   with patch.object(fixture.adapter_module,'ACP',Stream),patch.object(fixture.adapter_module,'installation',return_value=('fixture.exe','cli.js')):fixture.d.execute(fixture.f.running(run['id']))
   self.assertEqual(observed,['public reply'],dict(fixture.h.db.execute('SELECT status,result FROM executions').fetchone()));draft=fixture.h.live.read(run['id'],project['id']);self.assertNotIn('PRIVATE_THOUGHT_SENTINEL',str(draft))
  finally:fixture.tearDown()
