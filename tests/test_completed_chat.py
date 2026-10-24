import json
from unittest.mock import patch
from hub.message_receipts import reconcile
from test_designs import DesignFlow

class CompletedChat(DesignFlow):
 def completed(self, demo=False):
  self.start()
  w=self.w.snapshot('user')[0]
  w['status']='completed'
  if demo:w['design_review']={'version':1}
  self.w.save(w)
  return w
 def test_receipts_preserve_user_chat_but_archive_worker_backlog(self):
  self.completed()
  user=self.h.send('user','deepseek-4','再问一下')[0]
  worker=self.h.send('deepseek-1','deepseek-4','old report')[0]
  with self.h.tx():
   self.h.db.execute('UPDATE messages SET project_id=? WHERE id IN (?,?)',('p',user,worker))
  reconcile(self.h)
  self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(user,)).fetchone()[0],'pending')
  self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(worker,)).fetchone()[0],'archived')
 def check_dialogue(self,demo):
  w=self.completed(demo)
  with patch.object(self.d,'submit',return_value={'task_id':'chat-task'}) as submit:
   ident=self.co.send('user','deepseek-4','五个字问题',project_id='p')[0]
   self.co.patrol()
   self.assertEqual(submit.call_count,1)
   self.assertEqual(submit.call_args.args[2],'五个字问题')
   self.assertEqual(submit.call_args.kwargs['purpose'],'task')
   self.assertEqual(submit.call_args.kwargs['session_scope'],'project:'+w['id'])
  stored=json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(w['id'],)).fetchone()[0])
  self.assertEqual(stored['status'],'completed')
  self.assertEqual(self.h.db.execute('SELECT status FROM wakeups WHERE message=?',(ident,)).fetchone()[0],'queued')
 def test_finished_product_chat_wakes_once_without_reopening(self):self.check_dialogue(False)
 def test_published_demo_chat_keeps_context_and_baseline(self):self.check_dialogue(True)

 def test_new_human_request_has_vm_tool_and_executable_policy(self):
  self.completed()
  ident=self.co.send('user','deepseek-4','测试虚拟机',project_id='p')[0]
  run=dict(self.h.db.execute('SELECT * FROM executions WHERE message_id=?',(ident,)).fetchone())
  from hub.user_followup import direct
  self.assertTrue(direct(self.h,run))
  self.assertIn('project_vm',{x['function']['name'] for x in self.d.definitions(run)})
  self.assertIn('publish_artifact',{x['function']['name'] for x in self.d.definitions(run)})
  self.assertIn('project_assign',{x['function']['name'] for x in self.d.definitions(run)})
  self.assertIn('用户直接发送的新请求',self.d.execution_instructions(run))
  from hub.automation import Automation
  from types import SimpleNamespace
  automation=Automation(SimpleNamespace(hub=self.h,workflows=self.w))
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],))
  with patch.object(self.d,'guard'),patch.object(self.d,'check_latch'),patch('hub.vm_bridge.VmBridge.call',return_value={'connected':True}) as call:
   self.assertTrue(automation.project_vm('deepseek-4',run['id'],action='status')['connected'])
   self.assertEqual(call.call_args.args[0],'p')
  self.assertEqual(self.w.snapshot('user')[0]['status'],'completed')
 def test_colleague_question_stays_read_only(self):
  self.completed()
  ident=self.h.send('deepseek-1','deepseek-4','question')[0]
  run={'purpose':'question','session_scope':'project:x','message_id':ident,'task_id':'none'}
  from hub.user_followup import direct
  self.assertFalse(direct(self.h,run))
  self.assertEqual(self.d.definitions(run),[])

 def test_followup_dispatch_is_separate_and_idempotent(self):
  old=self.completed()
  ident=self.co.send('user','deepseek-4','请让成员测试虚拟机',project_id='p')[0]
  run=dict(self.h.db.execute('SELECT * FROM executions WHERE message_id=?',(ident,)).fetchone())
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],))
  with patch.object(self.d,'guard'),patch.object(self.d,'check_latch'):
   self.assertEqual(self.w.run_context('deepseek-4',run['id'])[0]['status'],'completed')
   result=self.w.project_assign('deepseek-4',run['id'],'deepseek-1','Test VM status only','probe')
   again=self.w.project_assign('deepseek-4',run['id'],'deepseek-1','Test VM status only','probe')
  self.assertEqual(result['task_id'],again['task_id'])
  child=next(w for w in self.w.snapshot('user') if w['id']!=old['id'])
  self.assertEqual(child['parent_workflow'],old['id'])
  self.assertEqual(child['requirement'],'请让成员测试虚拟机')
  self.assertNotIn('design_review',child)
  self.assertEqual(len(self.w.steps(child['id'])),2)
  self.assertEqual(json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(old['id'],)).fetchone()[0])['status'],'completed')

  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result='已派工，等待成员汇报' WHERE id=?",(run['id'],))
  self.w.advance(child)
  worker=self.h.db.execute('SELECT * FROM executions WHERE task_id=?',(result['task_id'],)).fetchone()
  self.assertIsNotNone(worker)
  self.assertEqual(worker['status'],'queued')
  self.assertEqual(json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(child['id'],)).fetchone()[0])['status'],'active')
