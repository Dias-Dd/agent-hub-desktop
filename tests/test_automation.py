import json,tempfile,time,unittest,base64
from pathlib import Path
from unittest.mock import patch
import test_integrations
from hub.automation import Automation
from hub.core import Hub,HubError
from hub.projects import Projects
from hub.planning import Planning

class AutomationTests(unittest.TestCase):
 def setUp(self):
  test_integrations.RegistryTests.setUp(self)
  h=self.server.hub;h.planning=Planning(h,self.server.deepseek,self.server.workflows);Projects(h)
  self.project=h.projects.create('user','automation test')
  self.server.integrations=self.registry
  self.service=Automation(self.server);h.automation=self.service
  self.w={'id':'workflow','project_id':self.project['id'],'manager':'deepseek-4','agents':['deepseek-1','deepseek-2'],'status':'active','expires':time.time()+3600,'grants':{},'cwd':self.temp.name}
  self.server.workflows.save(self.w)
  self.context=patch.object(self.server.workflows,'run_context',return_value=(self.w,{'cwd':self.temp.name}));self.context.start()
  self.valid=patch.object(self.server.workflows,'valid');self.valid.start()
 def tearDown(self):
  self.context.stop();self.valid.stop();test_integrations.RegistryTests.tearDown(self)
 def schedule(self,**args):return self.service.schedule_wake('deepseek-1','run',1,**args)
 def due(self):
  with self.server.hub.tx():
   for item in self.service.timers():
    item['due']=time.time()-100;self.service.save(item)
  self.service.next_poll=0
 # This fixture exercises the Windows file queue; Tart has separate live/boundary tests.
 @patch('hub.vm_bridge.VmBridge.__new__',new=staticmethod(lambda cls,directory:object.__new__(cls)))
 def test_vm_tool_uses_active_run_cwd_and_preserves_read_only(self):
  from hub.vm_bridge import VmBridge
  bridge=VmBridge(self.server.hub.directory)
  (bridge.root/'status.json').write_text(json.dumps({'updated':time.time(),'vm':'Hub'}))
  result=self.service.project_vm('deepseek-1','run',action='exec',script='whoami')
  job=json.loads((bridge.requests/(result['request_id']+'.json')).read_text())
  self.assertEqual(job['project'],self.project['id']);self.assertEqual(job['agent'],'deepseek-1')
  with patch.object(self.server.workflows,'run_context',return_value=(self.w,{'cwd':self.temp.name,'step_kind':'check'})):
   with self.assertRaises(HubError):self.service.project_vm('deepseek-1','run',action='exec',script='whoami')
  self.assertTrue(self.service.project_vm('deepseek-1','run',action='status')['connected'])

 def test_demo_webpages_use_design_review_without_individual_cards(self):
  page=Path(self.temp.name)/'demo.html';page.write_text('<h1>Demo</h1>')
  self.w['design_review']='review-id'
  result=self.service.publish_artifact('deepseek-1','run',str(page),'webpage','Demo page')
  self.assertEqual(result['presentation'],'design_review');self.assertFalse(result['published']);self.assertTrue(page.exists());self.assertEqual(self.service.artifacts(self.project['id']),[])

 def test_idle_project_timers_wake_worker_and_are_not_replayed(self):
  self.schedule(recipient='deepseek-2',note='check build');self.due();self.service.patrol();self.service.next_poll=0;self.service.patrol()
  item=self.service.timers()[0];self.assertEqual(item['state'],'finished');self.assertEqual(item['fires'],1)
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM workflow_steps').fetchone()[0],1)
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM executions').fetchone()[0],0)
  reopened=Automation(self.server);reopened.patrol();self.assertEqual(reopened.timers()[0]['fires'],1)
 def test_timer_delivery_executes_with_existing_project_scope(self):
  self.schedule(recipient='deepseek-2',note='continue assigned check');self.due();self.service.patrol()
  with patch.object(self.server.deepseek,'submit',return_value={'id':'queued'}) as submit:
   self.server.workflows.advance(self.w)
  self.assertEqual(submit.call_args.kwargs['purpose'],'task')
  self.assertIn('continue assigned check',submit.call_args.args[2])

 def test_timer_real_queue_creation_needs_no_model_process(self):
  cfg=self.server.deepseek.config();cfg['enabled']=True
  with self.server.hub.tx():self.server.hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(self.server.deepseek.config_key,json.dumps(cfg)))
  self.schedule(recipient='deepseek-2',note='continue existing assignment');self.due();self.service.patrol()
  self.server.workflows.advance(self.w)
  run=self.server.hub.db.execute('SELECT agent,status,purpose FROM executions').fetchone()
  self.assertEqual(tuple(run),('deepseek-2','queued','task'))

 def test_global_stop_retains_notifications_and_release_delivers_once(self):
  self.schedule(recipient='deepseek-4',note='manager reminder');self.due()
  with self.server.hub.tx():self.server.hub.db.execute("INSERT INTO agent_stops VALUES('*','test','user',?)",(time.time(),))
  self.service.patrol();self.assertEqual(self.service.timers()[0]['state'],'held');self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM workflow_events').fetchone()[0],0)
  self.server.coordination.resume('user','*');self.service.next_poll=0;self.service.patrol()
  self.assertEqual(self.service.timers()[0]['state'],'finished');self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM workflow_events').fetchone()[0],1)
 def test_manual_pause_held_but_time_wait_can_resume(self):
  self.schedule(note='continue');self.due();self.w['status']='paused';self.server.workflows.save(self.w);self.service.patrol()
  self.assertEqual(self.service.timers()[0]['state'],'held')
  self.w['pause_reason']='wait_time';self.server.workflows.save(self.w);self.service.next_poll=0;self.service.patrol()
  self.assertEqual(self.service.timers()[0]['state'],'finished')
  self.assertEqual(json.loads(self.server.hub.db.execute('SELECT body FROM workflows').fetchone()[0])['status'],'active')
 def test_dedup_batch_periodic_sleep_and_no_pending_storm(self):
  first=self.schedule(recipient='deepseek-4',note='old',request_key='a',interval_seconds=5)
  updated=self.schedule(recipient='deepseek-4',note='new',request_key='a',interval_seconds=5);self.assertEqual(first['timer_id'],updated['timer_id'])
  self.schedule(recipient='deepseek-4',note='other',request_key='b');self.due();self.service.patrol()
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM workflow_events').fetchone()[0],1)
  body=self.server.hub.db.execute('SELECT body FROM messages').fetchone()[0];self.assertIn('new',body);self.assertIn('other',body);self.assertNotIn('old',body)
  self.due();self.service.patrol();self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM workflow_events').fetchone()[0],1)

 def test_later_due_notices_merge_without_altering_claimed_input(self):
  h=self.server.hub
  self.schedule(recipient='deepseek-4',note='first due',request_key='first')
  self.due();self.service.patrol()
  first=self.service.timers()[0]['last_message']
  self.schedule(recipient='deepseek-4',note='later due',request_key='later')
  self.due();self.service.patrol()
  with h.tx():
   from hub.notice_batch import queue
   self.assertEqual(queue(h,self.w,'deepseek-4','settings changed','agent_config_changed'),first)
   self.assertEqual(queue(h,self.w,'deepseek-4','quota recovered','quota_recovered'),first)
  self.assertEqual(h.db.execute("SELECT count(*) FROM workflow_events WHERE status='pending'").fetchone()[0],1)
  body=h.db.execute('SELECT body FROM messages WHERE id=?',(first,)).fetchone()[0]
  for text in ('first due','later due','settings changed','quota recovered'):self.assertIn(text,body)
  self.assertTrue(all(t['state']=='finished' for t in self.service.timers()))
  self.assertEqual(len(self.server.workflows.manager_events(self.w)),1)
  with h.tx():
   h.db.execute("UPDATE workflow_events SET status='claimed',manager_task='active-manager' WHERE json_extract(body,'$.message_id')=?",(first,))
   h.db.execute("UPDATE messages SET status='acknowledged' WHERE id=?",(first,))
   second=queue(h,self.w,'deepseek-4','after delivery','timer')
  self.assertNotEqual(first,second)
  self.assertEqual(h.db.execute('SELECT body FROM messages WHERE id=?',(first,)).fetchone()[0],body)
  self.assertEqual(h.db.execute('SELECT count(*) FROM executions').fetchone()[0],0)

 def test_notice_batch_repeats_are_compact_and_projects_isolated(self):
  from hub.notice_batch import queue
  h=self.server.hub
  with h.tx():
   first=queue(h,self.w,'deepseek-4','same reminder','timer')
   for _ in range(20):self.assertEqual(queue(h,self.w,'deepseek-4','same reminder','timer'),first)
   other=queue(h,{**self.w,'id':'other-workflow','project_id':'other-project'},'deepseek-4','other project','timer')
  self.assertNotEqual(first,other)
  row=h.db.execute('SELECT body FROM workflow_events WHERE workflow=?',(self.w['id'],)).fetchone()
  event=json.loads(row[0]);self.assertEqual(len(event['notice_parts']),1)
  self.assertEqual(event['notice_parts'][0]['occurrences'],21)
  self.assertEqual(event['body'].count('same reminder'),1)

 def test_periodic_timer_is_not_replayed_after_merging_into_config_notice(self):
  from hub.notice_batch import queue
  h=self.server.hub
  with h.tx():first=queue(h,self.w,'deepseek-4','config first','agent_config_changed')
  self.schedule(recipient='deepseek-4',note='periodic',request_key='periodic',interval_seconds=5)
  self.due();self.service.patrol()
  self.assertEqual(self.service.timers()[0]['last_message'],first)
  self.due();self.service.patrol()
  self.assertEqual(self.service.timers()[0]['fires'],1)
  self.assertEqual(h.db.execute('SELECT count(*) FROM workflow_events').fetchone()[0],1)
 def test_quota_unknown_waits_and_manual_restoration_resumes(self):
  self.schedule(condition='quota_recovered');self.due();self.service.patrol();self.assertEqual(self.service.timers()[0]['state'],'held')
  self.registry.quota('user','deepseek-default',remaining=50);self.due();self.service.patrol();self.assertEqual(self.service.timers()[0]['state'],'finished')
 def test_cancel_and_membership_and_completed_project(self):
  with self.assertRaises(HubError):self.schedule(recipient='deepseek-3')
  timer=self.schedule();self.service.timer_cancel('user',timer['timer_id']);self.due();self.service.patrol();self.assertEqual(self.service.timers()[0]['state'],'cancelled')
  self.schedule(request_key='second');self.w['status']='completed';self.server.workflows.save(self.w);self.due();self.service.patrol()
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM workflow_steps').fetchone()[0],0)
 def test_artifact_snapshot_survives_source_removal_and_reopen(self):
  root=Path(self.temp.name)/'demo';root.mkdir();page=root/'index.html';page.write_text('<html><link rel="stylesheet" href="a.css"><h1>saved</h1></html>');(root/'a.css').write_text('body{color:red}')
  item=self.service.publish_artifact('deepseek-1','run',str(page),'webpage','preview')
  page.unlink();body,kind=Automation(self.server).asset(item['id'],'index.html');self.assertIn(b'saved',body);self.assertEqual(kind,'text/html');self.assertEqual(Automation(self.server).asset(item['id'],'index.html')[0],body);self.assertEqual(len(self.service.artifacts(self.project['id'])),1)
  self.assertEqual(self.service.asset(item['id'],'a.css')[0],b'body{color:red}')
  with self.assertRaises(HubError):self.service.asset(item['id'],'../../credentials.json')
  with self.assertRaises(HubError):self.service.publish_artifact('deepseek-1','run','credentials.json','image')
 def test_mcp_tools_visible_to_workers_and_new_manager(self):
  import os
  from hub.mcp import Protocol
  p=Protocol();p.handle({'jsonrpc':'2.0','id':1,'method':'initialize'});p.handle({'method':'notifications/initialized'})
  with patch.dict(os.environ,{'HUB_RUN_ID':'run','HUB_AGENT':'deepseek-1','HUB_IS_MANAGER':'0'},clear=True):
   tools=p.handle({'jsonrpc':'2.0','id':2,'method':'tools/list'})['result']['tools'];names={t['name'] for t in tools}
   self.assertTrue({'schedule_wake','timer_cancel','timer_list','publish_artifact'}<=names);self.assertNotIn('project_assign',names)
  with patch.dict(os.environ,{'HUB_RUN_ID':'run','HUB_AGENT':'agent-new','HUB_IS_MANAGER':'1'},clear=True):
   self.assertIn('project_assign',{t['name'] for t in p.handle({'jsonrpc':'2.0','id':3,'method':'tools/list'})['result']['tools']})

 def test_global_stop_cancels_new_dynamic_agent_too(self):
  a=self.registry.save_agent('user',{'name':'extra agent','connection_id':'deepseek-default','model':'deepseek-flash','role':'worker','effort':'high','enabled':True})
  with self.server.hub.tx():
   self.server.hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created) VALUES('dynamic-message','user',?,'test','queue','pending',?)",(a['id'],time.time()))
   self.server.hub.db.execute("INSERT INTO executions(id,task_id,message_id,agent,provider,status) VALUES('dynamic-run','dynamic-task','dynamic-message',?,'deepseek','queued')",(a['id'],))
  self.server.coordination.halt('user','*')
  self.assertEqual(self.server.hub.db.execute("SELECT status FROM executions WHERE id='dynamic-run'").fetchone()[0],'cancelled')
  self.assertTrue(self.server.coordination.is_stopped(a['id']))

 def test_manager_paused_text_does_not_pause_platform(self):
  self.w['processed']=0;self.server.workflows.save(self.w)
  result=json.dumps({'done':False,'report':'paused: waiting for quota','status':'paused','tasks':[]})
  with self.server.hub.tx():
   self.server.hub.db.execute("INSERT INTO tasks(id,agent,title,assigned_by,created,project_id) VALUES('manager-task','deepseek-4','review','user',?,?)",(time.time(),self.project['id']))
   self.server.hub.db.execute("INSERT INTO executions(id,task_id,agent,provider,status,result,purpose) VALUES('manager-run','manager-task','deepseek-4','deepseek','completed',?,'task')",(result,))
   self.server.hub.db.execute("INSERT INTO workflow_steps VALUES('workflow',1,'manager-task','deepseek-4','review')")
  self.server.workflows.advance(self.w)
  self.assertEqual(json.loads(self.server.hub.db.execute('SELECT body FROM workflows').fetchone()[0])['status'],'active')
 def test_quota_wait_is_actionable_but_passive_notices_are_not(self):
  self.server.workflows.enqueue(self.w,'passive',{'type':'agent_config_changed','body':'changed'})
  self.assertFalse(self.server.workflows.pending_requires_wake(self.w))
  self.server.workflows.enqueue(self.w,'completed',{'type':'result','agent':'deepseek-2','body':'completed'})
  self.assertTrue(self.server.workflows.pending_requires_wake(self.w))
 def test_quota_wait_reminder_preserves_original_execution_and_other_members(self):
  retry=time.time()+3600;h=self.server.hub
  with h.tx():
   h.db.execute("INSERT INTO tasks(id,agent,title,assigned_by,created,project_id) VALUES('quota-task','deepseek-1','existing task','deepseek-4',?,?)",(time.time(),self.project['id']))
   h.db.execute("INSERT INTO executions(id,task_id,agent,provider,status,retry_after,prompt,purpose) VALUES('quota-run','quota-task','deepseek-1','deepseek','waiting_quota',?,'existing task','task')",(retry,))
   h.db.execute("INSERT INTO workflow_steps VALUES('workflow',1,'quota-task','deepseek-1','work')")
  self.service.quota_waiting({'id':'quota-run','agent':'deepseek-1'})
  self.assertTrue(self.server.workflows.pending_requires_wake(self.w))
  states={a['agent']:a for a in self.server.workflows.agent_states(self.w)}
  self.assertFalse(states['deepseek-1']['available']);self.assertEqual(states['deepseek-1']['retry_at'],retry)
  self.assertEqual(json.loads(h.db.execute('SELECT body FROM workflows').fetchone()[0])['status'],'active')
  self.schedule(recipient='deepseek-1',note='continue when ready');self.due();self.service.patrol()
  self.assertEqual(h.db.execute('SELECT count(*) FROM executions').fetchone()[0],1)
  self.assertEqual(h.db.execute('SELECT count(*) FROM workflow_steps').fetchone()[0],1)
  run=h.db.execute('SELECT prompt,retry_after FROM executions').fetchone();self.assertIn('continue when ready',run['prompt']);self.assertEqual(run['retry_after'],retry)
 def test_discussion_is_not_a_reason_to_push_configuration(self):
  h=self.server.hub
  with h.tx():
   h.db.execute("INSERT INTO tasks(id,agent,title,assigned_by,created,project_id) VALUES('discussion-task','deepseek-4','discuss','user',?,?)",(time.time(),self.project['id']))
   h.db.execute("INSERT INTO executions(id,task_id,agent,provider,status,purpose) VALUES('discussion-run','discussion-task','deepseek-4','deepseek','running','discussion')")
  self.assertFalse(self.registry.project_is_running(self.project['id']))
  with h.tx():h.db.execute("UPDATE executions SET purpose='task'")
  self.assertTrue(self.registry.project_is_running(self.project['id']))

 def test_critical_wait_stays_active_and_suppresses_empty_inspections(self):
  self.w['processed']=0
  result=self.service.schedule_wake('deepseek-4','run',3600,recipient='deepseek-4',note='critical model recovery',wait_for_agent='deepseek-1')
  workflow=json.loads(self.server.hub.db.execute('SELECT body FROM workflows').fetchone()[0])
  self.assertEqual(workflow['status'],'active');self.assertEqual(workflow['resource_wait']['agent'],'deepseek-1')
  workflow['next_inspection']=time.time()-1;self.server.workflows.save(workflow)
  with patch.object(self.server.workflows,'prepare_manager') as wake:self.server.workflows.advance(workflow);wake.assert_not_called()
  self.due();self.service.patrol()
  workflow=json.loads(self.server.hub.db.execute('SELECT body FROM workflows').fetchone()[0]);self.assertNotIn('resource_wait',workflow)
  with patch.object(self.server.workflows,'prepare_manager') as wake:self.server.workflows.advance(workflow);wake.assert_called_once()
 def test_quota_dependency_checks_critical_agent_not_recipient(self):
  self.service.schedule_wake('deepseek-4','run',1,recipient='deepseek-4',condition='quota_recovered',wait_for_agent='deepseek-1')
  self.due()
  with patch.object(self.service,'quota_delay',return_value=(time.time()+600,'waiting')) as check,patch.object(self.service,'quota_unknown',return_value=False):self.service.patrol();check.assert_called_once_with('deepseek-1')
  workflow=json.loads(self.server.hub.db.execute('SELECT body FROM workflows').fetchone()[0]);self.assertEqual(workflow['resource_wait']['until'],self.service.timers()[0]['due'])
 def test_cancel_critical_wait_clears_marker_and_workers_cannot_set_it(self):
  with self.assertRaises(HubError):self.schedule(wait_for_agent='deepseek-2')
  timer=self.service.schedule_wake('deepseek-4','run',60,wait_for_agent='deepseek-1')
  self.service.timer_cancel('user',timer['timer_id'])
  workflow=json.loads(self.server.hub.db.execute('SELECT body FROM workflows').fetchone()[0]);self.assertNotIn('resource_wait',workflow)
 def test_user_notification_view_is_read_only_and_project_scoped(self):
  project=self.project['id'];self.registry.set_effort('user','deepseek-1','low',project)
  self.server.workflows.enqueue(self.w,'pending-info',{'type':'quota_wait','body':'quota waiting'})
  messages=self.server.hub.db.execute('SELECT count(*) FROM messages').fetchone()[0]
  items=self.service.notifications(project);self.assertEqual(len(items),2)
  self.assertTrue(all(n['state']=='pending' for n in items));self.assertIn('high → low',str(items))
  self.assertEqual(self.service.notifications('other-project'),[])
  self.assertEqual(len(self.registry.changes(project)),1)
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM messages').fetchone()[0],messages)
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM executions').fetchone()[0],0)

 def test_unknown_critical_quota_wakes_manager_to_check_instead_of_waiting_forever(self):
  self.service.schedule_wake('deepseek-4','run',1,recipient='deepseek-4',condition='quota_recovered',wait_for_agent='deepseek-1')
  self.due();self.service.patrol()
  self.assertEqual(self.service.timers()[0]['state'],'finished')
  event=json.loads(self.server.hub.db.execute('SELECT body FROM workflow_events').fetchone()[0])
  self.assertIn('不代表已恢复',event['body']);self.assertEqual(event['type'],'timer')

 def test_stopped_project_stays_stopped_after_unlock(self):
  self.schedule();self.w['status']='stopped';self.server.workflows.save(self.w);self.due();self.service.patrol()
  self.assertEqual(self.service.timers()[0]['state'],'held');self.assertIn('用户已停止',self.service.timers()[0]['reason'])

if __name__=='__main__':unittest.main()
