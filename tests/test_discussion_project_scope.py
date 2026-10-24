import json,unittest
from unittest.mock import patch
import test_integrations as base
from hub.planning import Planning
from hub.projects import Projects
from hub.prompt_identity import identity,discussion_system
from hub.deepseek_harness import patch_text
class Scope(base.RegistryTests):
 def prepare(self):
  self.planning=Planning(self.server.hub,self.server.deepseek,self.server.workflows);self.projects=Projects(self.server.hub)
  c=self.connection();worker=self.agent(c,name='Allowed model',model='allowed/model');outsider=self.agent(c,name='Secret outsider',model='outside/model')
  project=self.projects.create('user','scope',options={'agents':[worker['id']]})
  with self.server.hub.tx():self.server.hub.db.execute('insert or replace into settings values(?,?)',('project_manager:'+project['id'],'deepseek-1'))
  return worker,outsider,project
 def test_first_discussion_system_snapshot_is_project_scoped(self):
  worker,outsider,project=self.prepare()
  with patch.object(self.server.deepseek,'submit',return_value={'id':'fixture-discussion'}) as submit:s=self.planning.message('user','只做计划',project_id=project['id'])
  self.assertEqual(s['options']['agents'],[worker['id']]);self.assertEqual(s['options']['reviewer'],'deepseek-1')
  body=submit.call_args.args[2];raw=self.server.hub.db.execute('select body from discussion_prompt_context where run_id=?',('fixture-discussion',)).fetchone()[0];snapshot=json.loads(raw)
  self.assertEqual(snapshot['manager']['agent'],'deepseek-1');self.assertEqual(snapshot['manager']['role'],'项目经理');self.assertEqual([a['agent'] for a in snapshot['team']],[worker['id']]);self.assertNotIn(outsider['id'],raw)
  members={a for bucket in snapshot['quota']['accounts'] for a in bucket['agents']};self.assertEqual(members,{'deepseek-1',worker['id']})
  run={'id':'fixture-discussion','agent':'deepseek-1','model':'deepseek-flash','purpose':'discussion','prompt':body}
  instructions=self.server.deepseek.execution_instructions(run);self.assertIn('allowed/model',instructions);self.assertNotIn('outside/model',instructions);self.assertNotIn('后端工程师',instructions)
  self.assertIn('project_vm',instructions);self.assertIn('管理员权限',instructions);self.assertEqual(instructions.count('allowed/model'),1);self.assertNotIn('allowed/model',body)
  self.assertEqual(self.server.hub.agent('deepseek-1')['role'],'后端工程师')
 def test_role_and_manager_resolve_per_project_without_global_role_change(self):
  run={'agent':'deepseek-1','purpose':'task'}
  person=identity(self.server.hub,run,{'manager':'deepseek-1','roles':{'deepseek-1':'old role'}});self.assertEqual(person['role'],'项目经理')
  text=patch_text('deepseek-1',person['role'],manager=person['manager']);self.assertIn('本项目经理是 deepseek-1',text);self.assertNotIn('项目经理是 deepseek-4',text)
  worker=identity(self.server.hub,run,{'manager':'deepseek-2','roles':{'deepseek-1':'测试工程师'}});self.assertEqual(worker['role'],'测试工程师')
 def test_unknown_scope_never_falls_back_to_global_team(self):
  self.prepare();text=discussion_system(self.server.hub,{'id':'missing','agent':'deepseek-1','purpose':'discussion','prompt':'plain'})
  self.assertIn('未附项目成员快照',text);self.assertNotIn('outside/model',text)

 def test_new_discussion_after_manager_switch_normalizes_legacy_options(self):
  worker,outsider,project=self.prepare()
  with self.server.hub.tx():self.server.hub.db.execute('update project_options set body=? where project_id=?',(json.dumps({'cwd':project['cwd'],'agents':['deepseek-1',worker['id']],'reviewer':'deepseek-4'}),project['id']))
  with patch.object(self.server.deepseek,'submit',return_value={'id':'after-switch'}):s=self.planning.message('user','继续讨论',project_id=project['id'])
  self.assertEqual(s['options']['agents'],[worker['id']]);self.assertEqual(s['options']['reviewer'],'deepseek-1')
