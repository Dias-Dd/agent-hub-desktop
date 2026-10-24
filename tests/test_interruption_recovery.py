import io,json,queue,time,unittest
from unittest.mock import patch
from test_nine_deepseek import NineDeepSeek
from hub.deepseek_harness import ACP
from hub.core import HubError
class Interruptions(unittest.TestCase):
 setUp=NineDeepSeek.setUp
 tearDown=NineDeepSeek.tearDown
 def workflow(self):return self.w.start('user','approved scope',['deepseek-1','deepseek-3'],confirmed=True,reviewer='deepseek-3',approved_proposal={'done':False,'report':'ready','tasks':[{'agent':'deepseek-1','instruction':'work'}]})
 def reader(self,content):
  c=ACP.__new__(ACP);c.proc=type('P',(),{'stdout':io.StringIO(content)})();c.queue=queue.Queue();c.errors=[];c.redactions=['secret'];c._read();items=[]
  while not c.queue.empty():items.append(c.queue.get())
  return items,c
 def test_stdout_diagnostic_does_not_interrupt_protocol(self):
  rows,c=self.reader('\ufeff\n[info] secret log\n'+json.dumps({'jsonrpc':'2.0','id':1,'result':{}})+'\n')
  self.assertTrue(any(r.get('id')==1 for r in rows));self.assertFalse(any('transport_error' in r for r in rows));self.assertNotIn('secret',''.join(c.errors))
 def test_broken_protocol_and_unbounded_noise_still_fail(self):
  self.assertTrue(any('transport_error' in r for r in self.reader('{"jsonrpc": invalid\n')[0]))
  self.assertTrue(any('transport_error' in r for r in self.reader('noise\n'*40)[0]))
 def test_manager_error_does_not_stop_live_members(self):
  w=self.workflow()
  with patch.object(self.w,'advance',side_effect=HubError('manager temporarily unavailable')),patch.object(self.d,'stop') as stop:
   self.w.patrol();stop.assert_not_called()
  w=self.w.snapshot('user')[0];self.assertEqual(w['status'],'needs_attention');self.assertGreater(w['next_recovery'],time.time())
 def test_expired_authorization_still_stops_live_execution(self):
  w=self.workflow();w['expires']=time.time()-1;self.w.save(w)
  with patch.object(self.w,'advance',side_effect=HubError('expired')),patch.object(self.w,'steps',return_value=[{'run_id':'live','status':'running','agent':'deepseek-1'}]),patch.object(self.d,'stop') as stop:
   self.w.patrol();stop.assert_called_once_with('user','live')
  self.assertEqual(self.w.snapshot('user')[0]['status'],'blocked')
 def test_long_history_produces_short_reference_not_full_trace(self):
  w=self.workflow();steps=[{'agent':'deepseek-1','kind':'work','status':'completed','run_id':'r','task':'t','result':'x'*100000}]
  p=self.w.check_prompt(w,steps)
  self.assertLess(len(p),2000);self.assertNotIn('full_result',p);self.assertIn('run_id',p)
 def test_recovery_timer_prevents_tight_retry_loop(self):
  w=self.workflow();w.update(status='needs_attention',next_recovery=time.time()+180);self.w.save(w)
  with patch.object(self.w,'advance') as advance:
   self.w.patrol();advance.assert_not_called()
