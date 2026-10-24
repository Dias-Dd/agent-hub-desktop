import unittest,time,json
from unittest.mock import patch
import test_designs as base
class Settlement(unittest.TestCase):
 plan=base.DesignFlow.plan
 def setUp(self):base.DesignFlow.setUp(self)
 def tearDown(self):base.DesignFlow.tearDown(self)
 def workflow(self):
  base.DesignFlow.start(self)
  w=self.w.snapshot('user')[0];w.pop('design_review',None);w['next_inspection']=time.time()+1000;self.w.save(w)
  from hub.automation import Automation
  from types import SimpleNamespace
  Automation(SimpleNamespace(hub=self.h,workflows=self.w))
  item={'id':'f'*64,'workflow_id':w['id'],'project_id':w['project_id'],'sender':'deepseek-4','kind':'folder','path':self.t.name,'folder_roots':[self.t.name]}
  with self.h.tx():self.h.db.execute('INSERT INTO shared_artifacts VALUES(?,?)',(item['id'],json.dumps(item)))
  return w
 def end(self,w,text,task=None):
  task=task or self.w.steps(w['id'])[0]['task']
  job=self.d.submit('user','deepseek-4',self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone()[0],True,task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',finished=?,result=? WHERE id=?",(time.time(),text,job['id']))
  return job
 def notice(self,w,task,key='one'):
  msg=self.h.send('deepseek-1','deepseek-4','Finished '+key)[0]
  with self.h.tx():
   self.h.db.execute("INSERT INTO workflow_events VALUES(?,?,NULL,?,'claimed',?,?)",(key,w['id'],json.dumps({'type':'message','message_id':msg}),task,time.time()))
   self.h.db.execute("INSERT INTO wakeups VALUES(?,?,NULL,?,0,'batched','waiting')",(msg,w['id'],msg))
  return msg
 def test_natural_reply_settles_once_without_format_retry(self):
  w=self.workflow();job=self.end(w,'成员已派工，等待回报。');msg=self.notice(w,job['task_id'])
  with patch.object(self.w,'prepare_manager') as prepare:
   self.w.advance(w);self.w.advance(w);prepare.assert_not_called()
  self.assertEqual(w['processed'],1);self.assertEqual(w['status'],'active')
  self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(msg,)).fetchone()[0],'completed')
  self.assertEqual(self.h.db.execute('SELECT status FROM wakeups WHERE message=?',(msg,)).fetchone()[0],'completed')
  self.assertEqual(self.h.db.execute('SELECT status FROM workflow_events WHERE id=?',('one',)).fetchone()[0],'handled')
 def test_old_bad_format_cannot_block_new_valid_completion(self):
  w=self.workflow();first=self.end(w,'{"report":"自然说明，无调度字段"}');self.notice(w,first['task_id'])
  task=self.w.prepare_manager(w,self.w.steps(w['id']))
  self.end(w,json.dumps({'done':True,'report':'测试完成','tasks':[]}),task)
  w['status']='needs_attention';w['next_recovery']=0;self.w.save(w)
  with patch.object(self.w,'prepare_manager') as prepare:
   self.w.patrol();self.w.patrol();prepare.assert_not_called()
  stored=json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(w['id'],)).fetchone()[0]);self.assertEqual(stored['status'],'completed')
 def test_receipt_repair_is_idempotent_and_never_wakes(self):
  w=self.workflow();job=self.end(w,'收到，已核查');msg=self.notice(w,job['task_id']);w['processed']=1;self.w.save(w)
  self.assertEqual(self.w.reconcile_manager_receipts(),1);self.assertEqual(self.w.reconcile_manager_receipts(),0)
  self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(msg,)).fetchone()[0],'completed')
 def test_completion_archives_unread_report_without_claiming_it_was_read(self):
  w=self.workflow();first=self.end(w,'等待');w['processed']=1;self.w.save(w)
  task=self.w.prepare_manager(w,self.w.steps(w['id']));self.end(w,json.dumps({'done':True,'report':'已核查完成','tasks':[]}),task)
  msg=self.h.send('deepseek-1','deepseek-4','late report')[0]
  with self.h.tx():self.h.db.execute("INSERT INTO workflow_events VALUES(?,?,NULL,?,'pending',NULL,?)",('late',w['id'],json.dumps({'type':'result','message_id':msg}),time.time()))
  self.w.advance(w)
  row=self.h.db.execute('SELECT status,result FROM messages WHERE id=?',(msg,)).fetchone();self.assertEqual(row['status'],'archived');self.assertIn('不代表已阅读',row['result'])

 def test_codebuddy_check_allows_reporting_without_bypass_or_profile_changes(self):
  from module_fixture import implementation
  adapter_runtime=implementation(self.h,'workbuddy')
  from types import SimpleNamespace
  from unittest.mock import MagicMock
  import sys
  w=self.workflow();job=self.end(w,'placeholder');run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
  fake=SimpleNamespace(hub=self.h,clients={},guard=MagicMock(),connection=lambda:{'kind':'workbuddy'},read_only=lambda r:True,definitions=lambda r:[{'function':{'name':'report_result'}}],execution_instructions=lambda r:'Read only check',report_instructions=lambda r:'Report result',efforts=lambda:{run['agent']:'default'},sessions=SimpleNamespace(get=lambda r:None,state=MagicMock()),run_environment=lambda r:{},record=MagicMock(),finalize=MagicMock())
  bridge={'command':sys.executable,'args':[],'env':[]}
  with patch('hub.integrations.locate',return_value=sys.executable),patch('hub.integrations.command',side_effect=lambda a:a),patch.object(adapter_runtime,'bridge',return_value=bridge),patch('hub.integration_runtime.subprocess.Popen',side_effect=RuntimeError('TEST_STOP_NO_INFERENCE')) as launch:
   adapter_runtime.execute(fake,run)
  argv=launch.call_args.args[0]
  self.assertEqual(argv[argv.index('--permission-mode')+1],'plan')
  self.assertNotIn('-y',argv)
  self.assertEqual(argv[argv.index('--allowedTools')+1],'DeferExecuteTool,mcp__agent-message-hub__report_result')
  self.assertIn('--strict-mcp-config',argv)
  self.assertEqual(launch.call_args.kwargs['env'].get('USERPROFILE'),__import__('os').environ.get('USERPROFILE'))
 def test_failed_manager_turn_is_not_marked_as_handled(self):
  w=self.workflow();job=self.end(w,'placeholder');self.notice(w,job['task_id']);w['processed']=1;self.w.save(w)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='failed' WHERE id=?",(job['id'],))
  self.assertEqual(self.w.reconcile_manager_receipts(),0)
  self.assertEqual(self.h.db.execute("SELECT status FROM workflow_events WHERE id='one'").fetchone()[0],'claimed')

 def test_completion_keeps_new_human_message_for_followup(self):
  w=self.workflow();self.end(w,'等待');w['processed']=1;self.w.save(w)
  task=self.w.prepare_manager(w,self.w.steps(w['id']));self.end(w,json.dumps({'done':True,'report':'完成','tasks':[]}),task)
  msg=self.h.send('user','deepseek-4','还有一个新问题')[0]
  with self.h.tx():
   self.h.db.execute("INSERT INTO workflow_events VALUES(?,?,NULL,?,'pending',NULL,?)",('new-human',w['id'],json.dumps({'type':'message','from':'user','message_id':msg}),time.time()))
   self.h.db.execute("INSERT INTO wakeups VALUES(?,?,NULL,?,0,'batched','waiting')",(msg,w['id'],msg))
  self.w.advance(w)
  self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(msg,)).fetchone()[0],'pending')
  self.assertEqual(self.h.db.execute('SELECT status FROM wakeups WHERE message=?',(msg,)).fetchone()[0],'held')
