import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from hub.harness_adapters import builtin_catalog, custom_directory, prepare_layout, load_builtin
from hub.custom_harness import discover

class AdapterLayout(unittest.TestCase):
 def test_legacy_migration_repairs_launch_paths_and_preserves_all_files(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);old=base/'harness-adapters';folder=old/'demo';folder.mkdir(parents=True)
   script=folder/'bridge.py';script.write_text('raise RuntimeError("discovery must not execute")',encoding='utf-8')
   manifest={'version':1,'id':'demo','protocol':'hub-jsonl-v1','name':'Demo','command':[__import__('sys').executable,str(script)],'models':[{'id':'m'}]}
   raw=json.dumps(manifest).encode();(folder/'adapter.json').write_bytes(raw)
   (old/'notes.txt').write_text('keep',encoding='utf-8')
   result=prepare_layout(base);found,errors=discover(base)
   self.assertFalse(old.exists());self.assertEqual(result,custom_directory(base));self.assertFalse(errors)
   self.assertEqual(found[0]['id'],'custom-demo');self.assertEqual(found[0]['adapter']['command'][1],str(result/'demo/bridge.py'))
   self.assertEqual((result/'demo/adapter.before-directory-migration.json').read_bytes(),raw)
   self.assertEqual((result/'notes.txt').read_text(),'keep')
   first=(result/'demo/adapter.json').stat().st_mtime_ns;prepare_layout(base)
   self.assertEqual(first,(result/'demo/adapter.json').stat().st_mtime_ns)
 def test_collision_preserves_both_and_disables_ambiguous_ids(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);prepare_layout(base)
   for parent in [base/'harness-adapters',custom_directory(base)]:
    folder=parent/'demo';folder.mkdir(parents=True)
    (folder/'adapter.json').write_text(json.dumps({'version':1,'id':'demo','protocol':'hub-jsonl-v1','name':'Demo','command':[__import__('sys').executable], 'models':[{'id':'m'}]}),encoding='utf-8')
   found,errors=discover(base)
   self.assertEqual(found,[]);self.assertTrue(errors)
   self.assertEqual(len(list(custom_directory(base).glob('*/adapter.json'))),2)
 def test_every_builtin_uses_the_public_module_abi(self):
  with tempfile.TemporaryDirectory() as d:
   prepare_layout(d);catalog=builtin_catalog()
   self.assertEqual(len(catalog),9)
   for kind,metadata in catalog.items():
    self.assertEqual(metadata['protocol'],'hub-module-v1')
    self.assertTrue(callable(load_builtin(d,kind)))
    self.assertTrue((Path(d)/'adapters/builtin'/kind/'runtime.py').is_file())
 def test_edited_builtin_uses_the_same_loader_as_user_code(self):
  with tempfile.TemporaryDirectory() as d:
   prepare_layout(d);file=Path(d)/'adapters/builtin/codex/adapter.py'
   file.write_text("def execute(ctx,run): return 'edited module'",encoding='utf-8')
   prepare_layout(d)
   self.assertEqual(load_builtin(d,'codex')(None,{}),'edited module')
 def test_existing_custom_identity_and_session_survive_migration(self):
  from test_custom_harness import CustomHarness
  f=CustomHarness();f.setUp()
  try:
   f.connect();self.assertEqual(f.turn()['status'],'completed')
   agent=f.registry.get('agent_profiles',f.agent);key=f.h.db.execute('SELECT key FROM custom_harness_context').fetchone()[0]
   old=f.h.directory/'harness-adapters';old.mkdir();manifest=f.manifest
   manifest['command'][1]=str(old/'demo/bridge.py');(f.folder/'adapter.json').write_text(json.dumps(manifest),encoding='utf-8');f.folder.rename(old/'demo')
   f.registry.adapters('user')
   self.assertEqual(f.registry.get('agent_profiles',f.agent),agent)
   row=f.turn('after migration');self.assertEqual(row['status'],'completed',row['result'])
   self.assertEqual(json.loads(row['result'])['history'],2)
   self.assertEqual(json.loads(row['result'])['session'],'native-session')
   self.assertEqual(f.h.db.execute('SELECT key FROM custom_harness_context').fetchone()[0],key)
  finally:f.tearDown()
