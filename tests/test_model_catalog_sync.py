import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from hub.workbuddy_catalog import configured_models
import test_integrations as base
class ConfigCatalog(unittest.TestCase):
 def test_metadata_only_and_no_disabled_models(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'.workbuddy';p.mkdir();(p/'models.json').write_text(json.dumps([{'id':'new-model','name':'New','apiKey':'SECRET'},{'id':'hidden','disabled':True}]))
   rows=configured_models(t);self.assertEqual([m['id'] for m in rows],['new-model']);self.assertNotIn('SECRET',json.dumps(rows))
class Sync(base.RegistryTests):
 def test_refresh_separates_candidates_and_preserves_confirmed_models(self):
  self.registry.add_client_model('user','workbuddy-local','step-5-preview',confirmed=True)
  with patch('hub.integrations.locate',return_value='workbuddy'),patch('hub.integrations.subprocess.run') as run,patch('hub.workbuddy_catalog.catalog',return_value=([{'id':'auto','source':'official_acp_catalog'}],'partial')),patch('hub.workbuddy_catalog.product_models',return_value=[{'id':'candidate','source':'official_installed_catalog'}]),patch('hub.workbuddy_catalog.configured_models',return_value=[{'id':'configured','source':'official_user_config'}]):
   run.return_value.returncode=0;run.return_value.stdout='help';c=self.registry.probe('user','workbuddy-local')
  self.assertEqual({m['id'] for m in c['models']},{'auto','configured','step-5-preview'});self.assertEqual(c['candidate_models'],[]);self.assertFalse(c['catalog_complete'])
 def test_failed_catalog_keeps_previous_public_menu_stale(self):
  c=self.registry.get('integration_connections','workbuddy-local');c['models']=[{'id':'auto','source':'official_acp_catalog'},{'id':'old-candidate','source':'official_installed_catalog'}];self.registry.put('integration_connections',c)
  with patch('hub.integrations.locate',return_value='workbuddy'),patch('hub.integrations.subprocess.run') as run,patch('hub.workbuddy_catalog.catalog',return_value=([],'unavailable')),patch('hub.workbuddy_catalog.product_models',return_value=[]),patch('hub.workbuddy_catalog.configured_models',return_value=[]):
   run.return_value.returncode=0;run.return_value.stdout='help';c=self.registry.probe('user','workbuddy-local')
  self.assertEqual([m['id'] for m in c['models']],['auto']);self.assertTrue(c['models'][0]['stale']);self.assertEqual(c['catalog_status'],'unavailable')
