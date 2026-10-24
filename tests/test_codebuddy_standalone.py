import unittest,os
from pathlib import Path
from unittest.mock import patch
from hub.integrations import locate
from hub.workbuddy_catalog import catalog
import test_integrations as base
class Migration(base.RegistryTests):
 def test_switch_preserves_agents_budget_and_previous_metadata(self):
  c=self.registry.get('integration_connections','workbuddy-local');c.pop('transport',None);c.update(executable='C:/WorkBuddy/codebuddy-lite-wb.mjs',models=[{'id':'old'}],client_models=[{'id':'client-only'}]);self.registry.put('integration_connections',c)
  before=self.registry.rows('agent_profiles');cfg=self.server.hub.db.execute("select value from settings where key='integration_runtime_workbuddy-local'").fetchone()
  self.registry.migrate_codebuddy();after=self.registry.get('integration_connections',c['id'])
  self.assertEqual(after['transport'],'codebuddy-standalone');self.assertEqual(after['executable'],'');self.assertEqual(after['models'],[]);self.assertEqual(after['previous_workbuddy_catalog']['models'],[{'id':'old'}]);self.assertEqual(before,self.registry.rows('agent_profiles'))
  self.assertEqual(cfg,self.server.hub.db.execute("select value from settings where key='integration_runtime_workbuddy-local'").fetchone())
  self.registry.migrate_codebuddy();self.assertEqual(after,self.registry.get('integration_connections',c['id']))
 def test_connection_save_preserves_migration_marker(self):
  c=self.registry.get('integration_connections','workbuddy-local');c['cwd']=self.temp.name;saved=self.registry.save_connection('user',c)
  self.assertEqual(saved['transport'],'codebuddy-standalone')
class Catalog(unittest.TestCase):
 def test_only_standalone_command_is_discovered(self):
  with patch('hub.integrations.shutil.which',side_effect=lambda x:'C:/npm/codebuddy.cmd' if x=='codebuddy.cmd' else None):self.assertEqual(locate('workbuddy'),'C:/npm/codebuddy.cmd')
 def test_acp_without_embedded_server_flags(self):
  with patch('hub.deepseek_harness.ACP') as acp,patch('hub.integrations.command',side_effect=lambda x:x):
   acp.return_value.request.side_effect=[{'protocolVersion':1},{'models':{'availableModels':[{'modelId':'space-bunny'}]}}]
   rows,detail=catalog('codebuddy','.',standalone=True)
   self.assertEqual(acp.call_args.args[0],['codebuddy','--acp']);self.assertEqual(rows[0]['id'],'space-bunny');self.assertIn('CodeBuddy',detail)
   self.assertNotIn('session/prompt',[call.args[0] for call in acp.return_value.request.call_args_list])
