import io,json,time,unittest
from unittest.mock import patch
from types import SimpleNamespace
from hub.print_turn import PrintTurn,completed_result
from hub.model_availability import retired,status,restore
import test_integrations as base

class Turns(unittest.TestCase):
 def test_old_history_and_empty_result_are_not_current_success(self):
  turn=PrintTurn('检查当前交付','new-request',time.time())
  self.assertEqual(json.loads(turn.payload())['message']['content'],'检查当前交付')
  old={'type':'assistant','uuid':'old','message':{'content':[{'type':'text','text':'上轮构建已完成'}]}}
  self.assertIsNone(turn.receive(old));self.assertEqual(turn.replayed,1)
  turn.receive({'type':'user','uuid':'new-request','message':{'content':'检查当前交付'},'isReplay':True})
  self.assertTrue(turn.accepted)
  self.assertIsNone(turn.receive({**old,'isReplay':True}))
  current={'type':'assistant','uuid':'new-output','message':{'content':[{'type':'text','text':'本轮核查发现问题'}]}}
  self.assertEqual(turn.receive(current),'本轮核查发现问题');self.assertIsNone(turn.receive(current))
  self.assertEqual(completed_result({'result':''})[0],'failed')
  self.assertEqual(completed_result({'result':''},json.dumps({'summary':'已通过 MCP 提交本轮结论'}))[0],'completed')
 def test_timestamped_history_after_ack_is_still_history(self):
  turn=PrintTurn('new','id',time.time());turn.receive({'type':'user','message':{'content':'new'}})
  self.assertIsNone(turn.receive({'type':'assistant','__timestamp':'2020-01-01T00:00:00Z','message':{'content':[{'type':'text','text':'old'}]}}))

class Availability(unittest.TestCase):
 setUp=base.RegistryTests.setUp
 tearDown=base.RegistryTests.tearDown
 connection=base.RegistryTests.connection
 agent=base.RegistryTests.agent
 def test_rejection_cancels_and_is_shared_only_for_same_model(self):
  c=self.connection('ori',True);a=self.agent(c,'Free 1','minimax/minimax-m3.1-flash:free');b=self.agent(c,'Free 2',a['model']);other=self.agent(c,'Different','different-model');h=self.server.hub;rt=self.server.workflows.runtime(a['id'])
  job=rt.submit('user',a['id'],'work',True);run=dict(h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
  raw='The :free variant has been retired; use a paid model instead.'
  self.assertEqual(rt.quota_outcome(run,'uncertain',raw),'cancelled')
  self.assertTrue(self.registry.model_status(b['id']));self.assertFalse(self.registry.model_status(other['id']))
  team=self.registry.discussion_team(other['id'],[a['id'],b['id']]);self.assertTrue(all(not x['ready'] for x in team['team']))
  with patch.object(rt,'execute') as execute:
   rt.start()
   try:
    for _ in range(80):
     if h.db.execute('SELECT status FROM executions WHERE id=?',(job['id'],)).fetchone()[0]=='cancelled':break
     time.sleep(.02)
   finally:rt.close()
  execute.assert_not_called();self.assertEqual(h.db.execute('SELECT status FROM executions WHERE id=?',(job['id'],)).fetchone()[0],'cancelled')
  self.assertEqual(self.registry.get('agent_profiles',a['id'])['model'],a['model'])
  rt.quota_outcome({**run,'session_scope':'connection-test:confirmed'},'completed','连接成功');self.assertIsNone(self.registry.model_status(a['id']))
 def test_assignment_returns_cancelled_without_calling_a_retired_model(self):
  c=self.connection('ori',True);a=self.agent(c,'Free','free-model');manager=self.agent(c,'Manager','healthy-model');w=self.server.workflows;h=self.server.hub
  project=w.start('user','approved',[a['id']],confirmed=True,manager=manager['id'],reviewer=manager['id']);rt=w.runtime(a['id']);first=rt.submit('user',a['id'],'old',True);run=dict(h.db.execute('SELECT * FROM executions WHERE id=?',(first['id'],)).fetchone())
  rt.finalize(run,'uncertain','Model variant has been retired.')
  state=next(x for x in w.agent_states(project) if x['agent']==a['id']);self.assertFalse(state['available']);self.assertEqual(state['state'],'model_unavailable')
  answer=w.dispatch(project,a['id'],'work','next',write_paths=['new.txt']);self.assertEqual(answer['reason'],'model_unavailable');self.assertFalse(answer['model_called'])
  ended=dict(h.db.execute('SELECT * FROM executions WHERE task_id=?',(answer['task_id'],)).fetchone());self.server.coordination.report(ended,ended['status'],ended['result']);note=h.db.execute('SELECT body FROM messages WHERE request_key=?',('report:'+ended['id'],)).fetchone()[0];self.assertIn('改派',note)
 def test_restore_does_not_reopen_old_work_or_notify(self):
  c=self.connection('ori',True);a=self.agent(c,'Free','old-model');rt=self.server.workflows.runtime(a['id']);h=self.server.hub;job=rt.submit('user',a['id'],'old',True)
  with h.tx():h.db.execute("UPDATE executions SET status='uncertain',result='model variant has been retired' WHERE id=?",(job['id'],))
  before=h.db.execute('SELECT count(*) FROM messages').fetchone()[0];restore(h)
  self.assertTrue(self.registry.model_status(a['id']));self.assertEqual(before,h.db.execute('SELECT count(*) FROM messages').fetchone()[0]);self.assertEqual(h.db.execute('SELECT status FROM executions WHERE id=?',(job['id'],)).fetchone()[0],'uncertain')
 def test_only_explicit_model_errors_are_classified(self):
  self.assertFalse(retired('HTTP 429 too many requests'));self.assertFalse(retired('file not found'));self.assertFalse(retired('Authentication required'))
  self.assertTrue(retired('model_not_found'));self.assertTrue(retired('The :free variant has been retired'))
class PrintAdapter(unittest.TestCase):
 setUp=base.RegistryTests.setUp
 tearDown=base.RegistryTests.tearDown
 connection=base.RegistryTests.connection
 agent=base.RegistryTests.agent
 def execute(self,empty=False):
  c=self.connection('workbuddy',True);a=self.agent(c,'CodeBuddy','hy3');rt=self.server.workflows.runtime(a['id']);h=self.server.hub
  job=rt.submit('user',a['id'],'检查新版本',True,session_scope='hub-project:keep');run=dict(h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
  with h.tx():h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],))
  rt.sessions.bind(run,'keep-session',cwd=run['cwd'])
  values=[{'type':'assistant','uuid':'old','message':{'content':[{'type':'text','text':'上轮交付'}]}},{'type':'user','uuid':run['id'],'message':{'content':run['prompt']}},{'type':'assistant','uuid':'new','message':{'content':[{'type':'text','text':'本轮核查'}]}},{'type':'result','session_id':'keep-session','result':'' if empty else '本轮结论','is_error':False}]
  class Input(io.StringIO):
   def close(self):pass
  proc=SimpleNamespace(pid=42,stdin=Input(),stdout=io.StringIO('\n'.join(json.dumps(x,ensure_ascii=False) for x in values)+'\n'),stderr=io.StringIO(''),wait=lambda **k:0,poll=lambda:0)
  with patch('hub.integrations.locate',return_value='codebuddy.cmd'),patch('hub.integrations.command',side_effect=lambda a:a),patch('hub.integration_runtime.subprocess.Popen',return_value=proc) as spawn,patch('hub.integration_runtime.ProcessJob',return_value=SimpleNamespace(close=lambda:None)),patch.object(rt,'track_client'):
   rt.execute(run)
  argv=spawn.call_args.args[0];self.assertIn('--replay-user-messages',argv);self.assertIn('--resume',argv)
  self.assertEqual(json.loads(proc.stdin.getvalue())['message']['content'],run['prompt']);self.assertEqual(rt.sessions.get(run)['session_id'],'keep-session')
  output=[json.loads(r[0])['text'] for r in h.db.execute("SELECT data FROM execution_events WHERE run_id=? AND kind='integration.output'",(run['id'],))];self.assertEqual(output,['本轮核查'])
  return dict(h.db.execute('SELECT status,result FROM executions WHERE id=?',(run['id'],)).fetchone())
 def test_input_is_framed_and_resumed_history_is_not_emitted(self):self.assertEqual(self.execute()['status'],'completed')
 def test_vendor_success_with_empty_result_is_failed_not_fake_completion(self):
  result=self.execute(empty=True);self.assertEqual(result['status'],'failed');self.assertIn('未返回',result['result'])
