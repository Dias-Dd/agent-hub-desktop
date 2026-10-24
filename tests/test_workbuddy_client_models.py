import unittest
from unittest.mock import patch
from hub.core import HubError
import test_integrations as base
class ClientModels(base.RegistryTests):
 def test_user_confirmation_adds_persistent_model_without_inference(self):
  item=self.registry.add_client_model('user','workbuddy-local','step-5-preview','Step-5 Preview',True)
  self.assertEqual(item['source'],'user_confirmed_client_model');self.assertFalse(item['inference_verified'])
  c=self.registry.get('integration_connections','workbuddy-local');self.assertIn('step-5-preview',[m['id'] for m in c['models']])
  with patch('hub.integrations.locate',return_value='workbuddy'),patch('hub.integrations.subprocess.run') as run,patch('hub.workbuddy_catalog.catalog',return_value=([{'id':'auto','efforts':['default']}],'public catalog')):
   run.return_value.returncode=0;run.return_value.stdout='help'
   c=self.registry.probe('user','workbuddy-local')
  self.assertIn('step-5-preview',[m['id'] for m in c['models']]);self.assertEqual(len(c['client_models']),1)
 def test_only_user_can_register_client_confirmations(self):
  with self.assertRaises(HubError):self.registry.add_client_model('deepseek-4','workbuddy-local','step-5-preview',confirmed=True)
  with self.assertRaises(HubError):self.registry.add_client_model('user','workbuddy-local','step-5-preview')
 def test_connection_edit_preserves_supplement(self):
  self.registry.add_client_model('user','workbuddy-local','step-5-preview',confirmed=True)
  c=self.registry.get('integration_connections','workbuddy-local');c['cwd']=self.temp.name;updated=self.registry.save_connection('user',c)
  self.assertEqual(updated['client_models'][0]['id'],'step-5-preview')
