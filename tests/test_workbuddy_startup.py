import os,unittest
from unittest.mock import patch,MagicMock
from hub.workbuddy_catalog import environment,acp_arguments,catalog
class WorkBuddyStartup(unittest.TestCase):
 def test_does_not_inject_system_proxy_or_drop_explicit_proxy(self):
  self.assertEqual(environment({'PATH':'node'}),{'PATH':'node'})
  self.assertEqual(environment({'HTTPS_PROXY':'http://127.0.0.1:9999'})['HTTPS_PROXY'],'http://127.0.0.1:9999')
 def test_uses_actual_stdio_server_mode(self):
  args=acp_arguments('workbuddy');self.assertIn('--serve',args);self.assertEqual(args[args.index('--acp-transport')+1],'stdio');self.assertEqual(args[args.index('--host')+1],'127.0.0.1')
 def test_dynamic_catalog_does_not_include_installed_candidates(self):
  with patch('hub.deepseek_harness.ACP') as acp,patch('hub.workbuddy_catalog.product_models',return_value=[{'id':'hy3','source':'official_installed_catalog'}]):
   acp.return_value.request.side_effect=[{'protocolVersion':1},{'models':{'availableModels':[{'modelId':'auto'}]}}]
   models,detail=catalog('workbuddy','.')
   self.assertEqual({m['id'] for m in models},{'auto'})
   self.assertNotIn('session/prompt',[call.args[0] for call in acp.return_value.request.call_args_list]);acp.return_value.close.assert_called_once()
