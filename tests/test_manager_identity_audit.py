import json,time,unittest
from unittest.mock import patch
import test_integrations as base
from hub.planning import Planning
from hub.projects import Projects
from hub.manager_identity import resolve
from hub.core import HubError

class DynamicManager(base.RegistryTests):
 def prepare(self):
  h=self.server.hub;self.planning=Planning(h,self.server.deepseek,self.server.workflows);self.projects=Projects(h)
  c=self.connection();manager=self.agent(c,'Custom manager','vendor/manager');worker=self.agent(c,'Worker','vendor/worker')
  project=self.projects.create('user','Existing',options={'agents':[manager['id'],worker['id']],'reviewer':'deepseek-4'})
  self.registry.set_manager('user',project['id'],manager['id'])
  self.registry.archive_agent('user','deepseek-4')
  return manager,worker,project
 def test_new_project_settings_and_first_discussion_without_seed_manager(self):
  manager,worker,old=self.prepare();h=self.server.hub
  project=self.projects.create('user','New',options={'agents':[worker['id']],'reviewer':'deepseek-4'})
  self.assertEqual(resolve(h,project['id']),manager['id'])
  self.projects.update('user',project['id'],{'max_parallel':4})
  rt=self.server.workflows.runtime(manager['id'])
  with patch.object(rt,'submit',return_value={'id':'new-discussion'}) as submit:
   session=self.planning.message('user','Make a plan',project_id=project['id'])
  self.assertEqual(session['manager'],manager['id']);self.assertEqual(session['options']['reviewer'],worker['id'])
  self.assertEqual(session['options']['agents'],[worker['id']]);self.assertEqual(submit.call_args.args[1],manager['id'])
 def test_dispatch_and_member_messages_use_current_manager(self):
  manager,worker,project=self.prepare();w=self.server.workflows;h=self.server.hub
  item={'id':'dynamic','manager':manager['id'],'project_id':project['id'],'agents':[worker['id']],'status':'active','expires':time.time()+3600,'max_hops':8,'max_messages':100,'processed':0}
  w.save(item);task=w.add_step(item,worker['id'],'work','Implement')
  row=h.db.execute('SELECT assigned_by FROM tasks WHERE id=?',(task,)).fetchone();self.assertEqual(row[0],manager['id'])
  row=h.db.execute('SELECT sender FROM messages WHERE body LIKE ?',('[task:'+task+'] %',)).fetchone();self.assertEqual(row[0],manager['id'])
  message=h.send(worker['id'],manager['id'],'Ready for review')[0]
  with h.tx():h.db.execute('UPDATE messages SET project_id=? WHERE id=?',(project['id'],message))
  self.server.coordination.route(message,item,{'id':'worker-run','task_id':task})
  event=json.loads(h.db.execute('SELECT body FROM workflow_events WHERE workflow=?',(item['id'],)).fetchone()[0]);self.assertEqual(event['message_id'],message)
  self.assertTrue(w.manager_prompt(item,w.steps(item['id'])).startswith(worker['id']+'：['));self.assertIn('+08:00] Ready for review',w.manager_prompt(item,w.steps(item['id'])))
  self.assertNotIn('deepseek-4',w.manager_prompt(item,w.steps(item['id'])))
 def test_arbitrary_manager_claims_short_messages_without_losing_remainder(self):
  manager,worker,project=self.prepare();w=self.server.workflows;h=self.server.hub
  item={'id':'inbox','manager':manager['id'],'project_id':project['id'],'agents':[worker['id']],'status':'active'};w.save(item)
  for i in range(3):w.enqueue(item,'msg'+str(i),{'type':'message','from':worker['id'],'body':str(i)+'x'*250})
  task=w.prepare_manager(item,[],reason='Check next steps')
  claimed=h.db.execute("SELECT count(*) FROM workflow_events WHERE manager_task=? AND status='claimed'",(task,)).fetchone()[0]
  pending=h.db.execute("SELECT count(*) FROM workflow_events WHERE workflow=? AND status='pending'",(item['id'],)).fetchone()[0]
  self.assertGreater(claimed,0);self.assertGreaterEqual(claimed+pending,4)
  for i in range(3):self.assertTrue(h.db.execute("SELECT 1 FROM workflow_events WHERE workflow=? AND json_extract(body,'$.body')=?",(item['id'],str(i)+'x'*250)).fetchone())
  prompt=h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone()[0];self.assertNotIn('deepseek-4',prompt)
 def test_manager_authority_follows_project_choice_and_stop_delegation(self):
  manager,worker,project=self.prepare();h=self.server.hub;w=self.server.workflows
  item={'id':'delegation','manager':manager['id'],'project_id':project['id'],'agents':[worker['id']],'status':'active','delegate_stop':True};w.save(item)
  h.project(manager['id'],35,'Progress')
  with self.assertRaises(HubError):h.project('deepseek-4',40,'Old seed')
  self.server.coordination.halt(manager['id'],worker['id'],'Stop conflicting work')
  self.assertTrue(self.server.coordination.is_stopped(worker['id']))
 def test_legacy_missing_manager_resolves_own_project_not_global_default(self):
  manager,worker,project=self.prepare()
  self.assertEqual(self.server.workflows.manager({'project_id':project['id']}),manager['id'])
  self.assertEqual(self.planning.options({'cwd':project['cwd'],'agents':[worker['id']],'reviewer':'deepseek-4'})['reviewer'],worker['id'])

 def test_no_runtime_branch_restores_seed_manager(self):
  import ast
  from pathlib import Path
  for path in (Path(__file__).parents[1]/'hub').glob('*.py'):
   if path.name in ('identities.py','antigravity.py'):continue
   for node in ast.walk(ast.parse(path.read_text(encoding='utf8'))):
    if isinstance(node,ast.Constant):self.assertNotEqual(node.value,'deepseek-4',str(path)+':'+str(node.lineno))

 def test_switch_transfers_prepared_manager_turn_without_replaying_execution(self):
  h=self.server.hub;w=self.server.workflows;Planning(h,self.server.deepseek,w);projects=Projects(h)
  project=projects.create('user','Transfer',options={'agents':['deepseek-2'],'reviewer':'deepseek-4'})
  cfg=self.server.deepseek.config()
  item={'id':'transfer','project_id':project['id'],'manager':'deepseek-4','agents':['deepseek-2'],'status':'paused','grants':{'deepseek':cfg['grant_id']},'reviewer':'deepseek-4'};w.save(item)
  task=w.add_step(item,'deepseek-4','plan','Unprocessed message')
  with patch.object(self.server.deepseek,'config',return_value={**cfg,'enabled':True}):self.registry.set_manager('user',project['id'],'deepseek-2')
  step=w.steps(item['id'])[0];self.assertEqual(step['agent'],'deepseek-2');self.assertIsNone(step['run_id'])
  row=h.db.execute('SELECT recipient,status FROM messages WHERE body LIKE ?',('[task:'+task+'] %',)).fetchone();self.assertEqual(tuple(row),('deepseek-2','pending'))
  stored=json.loads(h.db.execute('SELECT body FROM workflows WHERE id=?',(item['id'],)).fetchone()[0]);self.assertNotIn('deepseek-2',stored['agents']);self.assertIsNone(stored['reviewer'])

 def test_archived_manager_setting_does_not_break_new_discussion(self):
  manager,worker,project=self.prepare();h=self.server.hub
  other=self.projects.create('user','Old completed project',options={'agents':[worker['id']]})
  with h.tx():h.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('project_manager:'+other['id'],'deepseek-4'))
  self.assertEqual(resolve(h,other['id']),manager['id'])
  rt=self.server.workflows.runtime(manager['id'])
  with patch.object(rt,'submit',return_value={'id':'retired-manager-discussion'}):session=self.planning.message('user','New discussion',project_id=other['id'])
  self.assertEqual(session['manager'],manager['id'])
