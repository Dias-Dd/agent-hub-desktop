import json,unittest
from unittest.mock import patch
import test_integrations as base
from hub.quota_state import record_rejection,is_exhausted_error
from hub.quota_monitor import QuotaMonitor
from hub.prompt_identity import discussion_snapshot
class ModelQuotaVisibility(unittest.TestCase):
 setUp=base.RegistryTests.setUp
 tearDown=base.RegistryTests.tearDown
 connection=base.RegistryTests.connection
 agent=base.RegistryTests.agent
 def prepare(self):
  self.c=self.connection(enabled=True);self.a=self.agent(self.c,'MiniMax','opencode/minimax-m3.1-flash-free')
  self.run={'id':'rejected','agent':self.a['id'],'model':self.a['model'],'provider':'integration:'+self.c['id']}
  with self.server.hub.tx():record_rejection(self.server.hub,self.run,'Free usage limit reached. Subscribe to OpenCode Go to keep going')
  return QuotaMonitor(self.server.hub,self.server.workflows,self.server.codex,self.server.antigravity,self.server.deepseek)
 def test_free_usage_limit_is_exhausted_not_transient_rate_limit(self):
  self.assertTrue(is_exhausted_error('Free usage limit reached. Subscribe to OpenCode Go'))
  self.assertFalse(is_exhausted_error('429 Too Many Requests; retry after 30 seconds'))
 def test_new_discussion_and_runtime_capabilities_include_known_model_block(self):
  self.prepare();snapshot=discussion_snapshot(self.server.hub,'deepseek-4',[self.a['id']])
  member=snapshot['team'][0];self.assertFalse(member['ready']);self.assertTrue(member['quota_exhausted']);self.assertIn('Free usage limit reached',member['quota_detail']);self.assertIsNone(member['resets_at'])
  self.assertEqual(snapshot['quota']['blocked_agents'][0]['agent'],self.a['id'])
  capability=next(a for a in self.registry.capabilities() if a['agent']==self.a['id']);self.assertTrue(capability['quota_exhausted'])
 def test_non_numeric_rejection_notifies_once_preempts_and_can_realert_after_clear(self):
  monitor=self.prepare();h=self.server.hub;w={'id':'w','project_id':'project','manager':'deepseek-4','agents':[self.a['id']],'status':'active'};self.server.workflows.save(w)
  def samples():return [s for s in monitor.samples() if s['id'].startswith('model-rejection:')]
  with patch.object(self.server.coordination,'prioritize') as preempt:
   first=samples()[0];self.assertIsNone(first['remaining']);monitor.observe(first);monitor.observe(first);self.assertEqual(preempt.call_count,1)
   message=h.db.execute("SELECT body FROM messages WHERE sender='平台' AND recipient='deepseek-4' AND mode='immediate'").fetchone()[0];self.assertIn('剩余比例未知',message);self.assertIn('Free usage limit reached',message)
   with h.tx():h.db.execute('DELETE FROM model_quota_blocks WHERE agent=?',(self.a['id'],))
   recovered=samples()[0];self.assertFalse(recovered['exhausted']);monitor.observe(recovered);self.assertEqual(preempt.call_count,1)
   with h.tx():record_rejection(h,{**self.run,'id':'rejected-again'},'Free usage limit reached')
   monitor.observe(samples()[0]);self.assertEqual(preempt.call_count,2)
  self.assertFalse(h.db.execute("SELECT 1 FROM messages WHERE sender='deepseek-4' AND recipient='user' AND body LIKE '额度%'").fetchone())

 def test_queued_discussion_refreshes_quota_before_provider_start(self):
  self.c=self.connection(enabled=True);self.a=self.agent(self.c,'MiniMax','opencode/minimax-m3.1-flash-free');h=self.server.hub
  initial=discussion_snapshot(h,'deepseek-4',[self.a['id']]);self.assertTrue(initial['team'][0]['ready'])
  with h.tx():
   h.db.execute('CREATE TABLE discussion_prompt_context(run_id TEXT PRIMARY KEY,body TEXT)')
   h.db.execute('INSERT INTO discussion_prompt_context VALUES(?,?)',('stale',json.dumps(initial)))
   record_rejection(h,{'id':'later-rejection','agent':self.a['id'],'model':self.a['model'],'provider':'integration:'+self.c['id']},'Free usage limit reached')
  from hub.prompt_identity import discussion_system
  text=discussion_system(h,{'id':'stale','agent':'deepseek-4','purpose':'discussion','session_scope':'hub-project:p'})
  saved=json.loads(h.db.execute('SELECT body FROM discussion_prompt_context WHERE run_id=?',('stale',)).fetchone()[0])
  self.assertFalse(saved['team'][0]['ready']);self.assertTrue(saved['team'][0]['quota_exhausted']);self.assertIn('Free usage limit reached',text)
  self.assertEqual([a['agent'] for a in saved['team']],[self.a['id']])
