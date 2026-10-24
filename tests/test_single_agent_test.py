import unittest
from unittest.mock import patch
from hub.core import HubError
import test_integrations as base
class Single(base.RegistryTests):
 def test_selected_identity_only_and_other_results_untouched(self):
  service=self.registry.connection_tests;agents=self.registry.rows('agent_profiles');chosen=agents[0];other=agents[1]
  service.save({'id':other['id'],'status':'passed','detail':'keep','connection_id':other['connection_id']})
  captured=[]
  with patch.object(service,'loop',side_effect=lambda rows:captured.extend(rows)):
   result=self.registry.test_all('user',True,chosen['id']);service.thread.join(timeout=2)
  self.assertEqual(result['count'],1);self.assertEqual([x['id'] for x in captured],[chosen['id']]);self.assertEqual(service.snapshot()[other['id']]['detail'],'keep')
 def test_invalid_identity_does_not_fall_back_to_all(self):
  with self.assertRaises(HubError):self.registry.test_all('user',True,'missing')
  self.assertIsNone(self.registry.connection_tests.thread)
 def test_single_still_requires_confirmation(self):
  with self.assertRaises(HubError):self.registry.test_all('user',False,'deepseek-1')
