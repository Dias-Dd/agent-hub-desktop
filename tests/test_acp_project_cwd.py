import json,time,unittest
from pathlib import Path
from unittest.mock import patch
from module_fixture import implementation
import test_integrations as base
import test_designs as design_base

class ACPProjectDirectory(unittest.TestCase):
 setUp=base.RegistryTests.setUp
 tearDown=base.RegistryTests.tearDown
 connection=base.RegistryTests.connection
 agent=base.RegistryTests.agent
 def running(self,rt,agent,scope='hub-project:p',purpose='task'):
  job=rt.submit('user',agent,'Implement the new task',True,session_scope=scope,purpose=purpose)
  h=self.server.hub
  with h.tx():h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
  return dict(h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
 def fake(self,expected_root,mode_options=True):
  test=self;calls=[]
  class FakeACP:
   def __init__(self,argv,cwd,env,update,permission):self.update=update;self.permission=permission;calls.append(('spawn',cwd))
   def request(self,method,params,guard=None,*args):
    if guard:guard()
    calls.append((method,params))
    if method=='initialize':return {'protocolVersion':1,'agentCapabilities':{'sessionCapabilities':{'additionalDirectories':{}}}}
    if method in ('session/load','session/new'):
     test.assertEqual(params['cwd'],str(expected_root))
     if method=='session/load':
      self.update({'update':{'sessionUpdate':'agent_message_chunk','content':{'text':'OLD REPLAY MUST NOT BECOME NEW RESULT'}}})
      self.update({'update':{'sessionUpdate':'tool_call','title':'Old write operation'}})
     return {'sessionId':'keep-session','configOptions':[{'id':'mode','category':'mode','currentValue':'plan'}] if mode_options else []}
    if method=='session/set_config_option':return {'configOptions':[{'id':params['configId'],'currentValue':params['value']}]}
    if method=='session/prompt':
     self.update({'update':{'sessionUpdate':'agent_message_chunk','content':{'text':'NEW RESULT'}}});return {'stopReason':'end_turn'}
    return {}
   def close(self):pass
  return FakeACP,calls
 def test_both_adapters_keep_context_when_project_directory_changes(self):
  for kind in ['opencode','ori']:
   with self.subTest(kind=kind):
    c=self.connection(kind,True);a=self.agent(c,model='vendor/model');rt=self.server.workflows.runtime(a['id']);h=self.server.hub
    old=Path(self.temp.name)/('draft-'+kind);old.mkdir();first=self.running(rt,a['id'])
    with h.tx():h.db.execute("UPDATE executions SET cwd=?,thread_id='keep-session',status='completed' WHERE id=?",(str(old),first['id']))
    first.update(cwd=str(old));rt.sessions.bind(first,'keep-session')
    run=self.running(rt,a['id']);fake,calls=self.fake(old)
    with patch.object(implementation(self.server.hub,kind),'ACP',fake),patch('hub.integrations.locate',return_value='fake.exe'),patch('hub.integrations.command',side_effect=lambda a:a):rt.execute(run)
    row=h.db.execute('SELECT status,result,actual_input FROM executions WHERE id=?',(run['id'],)).fetchone()
    self.assertEqual(row['status'],'completed');self.assertEqual(row['result'],'NEW RESULT')
    self.assertNotIn('OLD REPLAY',row['result']);self.assertIn(str(Path(run['cwd']).resolve()),row['actual_input']);self.assertIn('禁止误写旧目录',row['actual_input'])
    loads=[p for m,p in calls if m=='session/load'];self.assertEqual(loads[0]['sessionId'],'keep-session');self.assertEqual(loads[0]['additionalDirectories'],[str(Path(run['cwd']).resolve())])
    self.assertNotIn('session/new',[m for m,p in calls]);self.assertEqual([p['value'] for m,p in calls if m=='session/set_config_option' and p['configId']=='mode'],['build'])
    self.assertEqual(rt.sessions.get(run)['cwd'],str(old));self.assertEqual(rt.sessions.get(run)['session_id'],'keep-session')
 def test_legacy_root_is_recovered_from_first_execution(self):
  c=self.connection(enabled=True);a=self.agent(c);rt=self.server.workflows.runtime(a['id']);h=self.server.hub;old=Path(self.temp.name)/'legacy';old.mkdir()
  first=self.running(rt,a['id'])
  with h.tx():h.db.execute("UPDATE executions SET cwd=?,thread_id='legacy-session',status='completed' WHERE id=?",(str(old),first['id']))
  rt.sessions.bind(first,'legacy-session')
  with h.tx():h.db.execute('DELETE FROM provider_session_roots')
  run=self.running(rt,a['id']);self.assertEqual(rt.sessions.get(run)['cwd'],str(old))
 def test_peer_question_stays_plan_and_old_protocol_mode_fallback_works(self):
  c=self.connection(enabled=True);a=self.agent(c);rt=self.server.workflows.runtime(a['id']);run=self.running(rt,a['id'],purpose='question');fake,calls=self.fake(Path(run['cwd']),False)
  with patch.object(implementation(self.server.hub,'opencode'),'ACP',fake),patch('hub.integrations.locate',return_value='fake.exe'),patch('hub.integrations.command',side_effect=lambda a:a):rt.execute(run)
  self.assertEqual([p['modeId'] for m,p in calls if m=='session/set_mode'],['plan'])
  self.assertEqual(self.server.hub.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()[0],'completed')
 def test_different_projects_do_not_reuse_context(self):
  c=self.connection(enabled=True);a=self.agent(c);rt=self.server.workflows.runtime(a['id']);first=self.running(rt,a['id'],'hub-project:one');rt.sessions.bind(first,'one-session')
  second={**first,'session_scope':'hub-project:two'};self.assertIsNone(rt.sessions.get(second))

class MessageAuthority(unittest.TestCase):
 def setUp(self):
  self.f=design_base.DesignFlow();self.f.setUp();self.h=self.f.h;self.w=self.f.w;self.d=self.f.d
  self.project=self.w.start('user','Approved work',['deepseek-1','deepseek-2'],confirmed=True)
  manager_task=self.w.steps(self.project['id'])[0]['task'];self.manager=self.submit(manager_task)
 def tearDown(self):self.f.tearDown()
 def submit(self,task):
  t=self.h.db.execute('SELECT agent,title FROM tasks WHERE id=?',(task,)).fetchone();job=self.d.submit('user',t['agent'],t['title'],True,task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
  return dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
 def send(self,sender,source):
  ident=self.h.send(sender,'deepseek-2','Finish shell.html')[0]
  self.f.co.route(ident,project=self.project,source_run=source);self.w.advance(self.project)
  return self.h.db.execute('SELECT e.purpose,e.task_id FROM executions e JOIN wakeups a ON a.task=e.task_id WHERE a.message=?',(ident,)).fetchone()
 def test_manager_work_message_is_task_and_keeps_resource_ordering(self):
  row=self.send('deepseek-4',self.manager);self.assertEqual(row['purpose'],'task')
  self.assertEqual(self.h.db.execute('SELECT kind FROM workflow_resources WHERE task=?',(row['task_id'],)).fetchone()[0],'work')
 def test_peer_message_is_still_readonly_question(self):
  task=self.w.dispatch(self.project,'deepseek-1','Implement a.py','worker',write_paths=['a.py'])['task_id'];worker=self.submit(task)
  row=self.send('deepseek-1',worker);self.assertEqual(row['purpose'],'question')
