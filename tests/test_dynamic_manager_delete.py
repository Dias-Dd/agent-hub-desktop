import json,time
from hub.core import HubError
import test_integrations as base
class DynamicManagerDelete(base.RegistryTests):
 def test_former_default_manager_can_be_removed(self):
  result=self.registry.archive_agent('user','deepseek-4');self.assertFalse(result['enabled'])
 def test_any_active_manager_is_protected_with_project_reason(self):
  w={'id':'w','project_id':'other-project','manager':'deepseek-1','status':'blocked','agents':[]}
  self.server.workflows.save(w)
  with self.assertRaisesRegex(HubError,'other-pr'):self.registry.archive_agent('user','deepseek-1')
  self.assertTrue(self.registry.get('agent_profiles','deepseek-1')['enabled'])
 def test_completed_history_does_not_protect_former_manager(self):
  self.server.workflows.save({'id':'w','manager':'deepseek-4','status':'completed','agents':[]})
  self.assertFalse(self.registry.archive_agent('user','deepseek-4')['enabled'])

 def test_archive_unsupported_old_effort_keeps_history(self):
  c=self.connection();a=self.agent(c)
  a['effort']='obsolete-tier';self.registry.put('agent_profiles',a)
  self.server.hub.send('user',a['id'],'keep history')
  result=self.registry.archive_agent('user',a['id'])
  self.assertFalse(result['enabled']);self.assertEqual(result['effort'],'obsolete-tier')
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM messages').fetchone()[0],1)
 def test_archive_catalog_changed_but_new_configuration_still_validated(self):
  c=self.connection();a=self.agent(c)
  c['models']=[{'id':a['model'],'efforts':['high']}];self.registry.put('integration_connections',c)
  with self.assertRaisesRegex(HubError,'不支持所选档位'):self.registry.save_agent('user',a)
  self.assertFalse(self.registry.archive_agent('user',a['id'])['enabled'])
