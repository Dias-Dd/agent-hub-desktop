import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_integrations as base
from hub.workbuddy_catalog import acp_models,product_models,catalog
class DiscussionQuota(base.RegistryTests):
 def test_shared_connection_once_and_unknown_explicit(self):
  result=self.registry.discussion_resources(['deepseek-4','deepseek-1'])
  self.assertEqual(len(result['accounts']),1);account=result['accounts'][0]
  self.assertEqual(set(account['agents']),{'deepseek-4','deepseek-1'});self.assertTrue(account['unknown'])
 def test_zero_percent_is_known_not_missing(self):
  c=self.registry.get('integration_connections','deepseek-default');c['official_windows']=[{'name':'weekly','remaining':0,'resets_at':123}];c['probed_at']=99;self.registry.put('integration_connections',c)
  account=self.registry.discussion_resources(['deepseek-4'])['accounts'][0]
  self.assertFalse(account['unknown']);self.assertEqual(account['windows'][0]['remaining'],0);self.assertEqual(account['windows'][0]['observed_at'],99)
 def test_discussion_prompt_contains_snapshot(self):
  from hub.planning import Planning
  from hub.projects import Projects
  h=self.server.hub;planning=Planning(h,self.server.deepseek,self.server.workflows);h.planning=planning;projects=Projects(h);project=projects.create('user','quota test')
  with patch.object(self.server.deepseek,'submit',return_value={'id':'probe-no-inference'}) as submit:
   planning.message('user','plan only',project_id=project['id'])
  prompt=submit.call_args.args[2];raw=h.db.execute('SELECT body FROM discussion_prompt_context WHERE run_id=?',('probe-no-inference',)).fetchone()[0];self.assertIn('"quota":',raw);self.assertIn('"unknown": true',raw)
class WorkBuddyCatalog(unittest.TestCase):
 def test_public_acp_forms(self):
  rows=acp_models({'models':{'availableModels':[{'modelId':'hy3','name':'Hy3'}]},'configOptions':[{'id':'model','options':[{'name':'Group','options':[{'value':'hy4-preview','name':'Hy4 preview'}]}]}]})
  self.assertEqual({m['id'] for m in rows},{'hy3','hy4-preview'})
 def test_official_product_fallback_and_no_inference(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'dist').mkdir();exe=root/'dist/cli.mjs';exe.write_text('')
   (root/'product.json').write_text(json.dumps({'models':[{'id':'hy3'},{'id':'hy4-preview'},{'id':'disabled','disabled':True},{'id':'image','tags':['text-to-image']}]}))
   with patch('hub.deepseek_harness.ACP') as client:
    client.return_value.request.side_effect=RuntimeError('offline')
    models,detail=catalog(str(exe),t)
   self.assertEqual(models,[]);self.assertIn('单独保存',detail);self.assertTrue(all(m['pricing']=='unknown' for m in models));self.assertNotIn('session/prompt',[call.args[0] for call in client.return_value.request.call_args_list]);client.return_value.close.assert_called_once()
