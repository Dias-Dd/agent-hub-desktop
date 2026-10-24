import json,time,unittest
from unittest.mock import patch
import test_integrations as base
import test_automation as automation_base
from hub.quota_state import status,is_exhausted_error

class QuotaCancellation(unittest.TestCase):
 setUp=base.RegistryTests.setUp
 tearDown=base.RegistryTests.tearDown
 connection=base.RegistryTests.connection
 agent=base.RegistryTests.agent
 def prepare(self):
  c=self.connection('antigravity',True);c['official_windows']=[{'group':'Claude and GPT models','window':'Weekly Limit Remaining','remaining':0,'resets_at':time.time()+3600},{'group':'Gemini Models','window':'Weekly Limit Remaining','remaining':70,'resets_at':time.time()+3600}];c['probed_at']=time.time()
  with self.server.hub.tx():self.registry.put('integration_connections',c)
  claude=self.agent(c,'Claude','claude-opus-5-5-low');gemini=self.agent(c,'Gemini','gemini-3.8-flash-medium')
  return c,claude,gemini
 def test_model_specific_windows_do_not_grey_healthy_gemini(self):
  c,claude,gemini=self.prepare();h=self.server.hub
  self.assertTrue(status(h,claude['id'])['exhausted']);self.assertFalse(status(h,gemini['id'])['exhausted'])
  profiles=self.registry.snapshot()['agents'];self.assertTrue(next(a for a in profiles if a['id']==claude['id'])['quota_status']['exhausted'])
 def test_quota_alerts_only_target_the_corresponding_model_pool(self):
  from hub.quota_monitor import QuotaMonitor
  c,claude,gemini=self.prepare();monitor=QuotaMonitor(self.server.hub,self.server.workflows,self.server.codex,self.server.antigravity,self.server.deepseek)
  samples=monitor.samples();empty=next(x for x in samples if x['remaining']==0)
  self.assertIn(claude['id'],empty['agents']);self.assertNotIn(gemini['id'],empty['agents'])
 def test_assign_exhausted_model_cancels_without_executor_and_reports_manager(self):
  c,claude,gemini=self.prepare();w=self.server.workflows;h=self.server.hub;project=w.start('user','approved task',[claude['id']],confirmed=True,manager=gemini['id'],reviewer=gemini['id'])
  rt=w.runtime(claude['id'])
  with patch.object(rt,'execute') as execute:
   answer=w.dispatch(project,claude['id'],'Implement foo.py','quota-task',write_paths=['foo.py'])
  self.assertEqual(answer['status'],'cancelled');self.assertFalse(answer['model_called']);execute.assert_not_called()
  self.assertEqual(h.db.execute('SELECT status FROM tasks WHERE id=?',(answer['task_id'],)).fetchone()[0],'cancelled')
  row=dict(h.db.execute('SELECT * FROM executions WHERE task_id=?',(answer['task_id'],)).fetchone());self.assertEqual(row['status'],'cancelled')
  self.server.coordination.report(row,row['status'],row['result'])
  message=h.db.execute("SELECT body FROM messages WHERE recipient=? AND request_key=?",(w.manager(project),'report:'+row['id'])).fetchone()
  self.assertIsNotNone(message);self.assertIn('额度耗尽',message[0]);self.assertIn('取消',message[0]);self.assertNotIn('waiting_quota',row['status'])
 def test_worker_rechecks_quota_before_launch(self):
  c,claude,gemini=self.prepare();h=self.server.hub;rt=self.server.workflows.runtime(claude['id']);job=rt.submit('user',claude['id'],'one task',True)
  with patch.object(rt,'execute') as execute:
   rt.start()
   try:
    for _ in range(80):
     if h.db.execute('SELECT status FROM executions WHERE id=?',(job['id'],)).fetchone()[0]=='cancelled':break
     time.sleep(.02)
   finally:rt.close()
  execute.assert_not_called();self.assertEqual(h.db.execute('SELECT status FROM executions WHERE id=?',(job['id'],)).fetchone()[0],'cancelled')
 def test_provider_rejection_becomes_cancelled_and_new_positive_quota_clears_grey(self):
  c,claude,gemini=self.prepare();h=self.server.hub;c['official_windows'][0]['remaining']=5
  with h.tx():self.registry.put('integration_connections',c)
  rt=self.server.workflows.runtime(claude['id']);job=rt.submit('user',claude['id'],'task',True);run=dict(h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
  self.assertEqual(rt.quota_outcome(run,'failed','Individual quota reached. Resets in 1h2m3s.'),'cancelled');self.assertTrue(status(h,claude['id'])['exhausted'])
  c['probed_at']=time.time()+1
  with h.tx():self.registry.put('integration_connections',c)
  self.assertFalse(status(h,claude['id'])['exhausted'])
 def test_concurrency_rate_limit_is_not_treated_as_exhaustion(self):
  self.assertFalse(is_exhausted_error('HTTP 429 Too many concurrent requests'))
  self.assertFalse(is_exhausted_error('Rate limit exceeded'))

class TimerRemoval(unittest.TestCase):
 setUp=automation_base.AutomationTests.setUp
 tearDown=automation_base.AutomationTests.tearDown
 schedule=automation_base.AutomationTests.schedule
 due=automation_base.AutomationTests.due
 def test_delivered_timer_removed_from_active_table_and_api(self):
  timer=self.schedule();self.due();self.service.patrol();h=self.server.hub
  self.assertIsNone(h.db.execute('SELECT 1 FROM hub_timers WHERE id=?',(timer['timer_id'],)).fetchone())
  self.assertIsNotNone(h.db.execute('SELECT 1 FROM hub_timer_history WHERE id=?',(timer['timer_id'],)).fetchone())
  self.assertEqual(self.service.timer_list('deepseek-1','run'),[])
  before=h.db.execute('SELECT count(*) FROM messages').fetchone()[0];self.service.patrol();self.assertEqual(h.db.execute('SELECT count(*) FROM messages').fetchone()[0],before)
 def test_repeating_timer_keeps_only_its_next_occurrence(self):
  timer=self.schedule(interval_seconds=60);self.due();self.service.patrol();rows=self.service.timer_list('deepseek-1','run')
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['state'],'scheduled');self.assertGreater(rows[0]['due'],time.time())
