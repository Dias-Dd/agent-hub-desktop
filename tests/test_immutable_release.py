import tempfile,unittest
from pathlib import Path
from desktop.deploy_release import publish
class ImmutableRelease(unittest.TestCase):
 def test_publishing_preserves_existing_executable_and_runtime(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/'source';target=root/'target';source.mkdir();target.mkdir()
   canonical=target/'AgentMessageHubDesktop.exe';canonical.write_bytes(b'running old exe')
   (source/'AgentMessageHubDesktop.exe').write_bytes(b'new exe')
   runtime=source/'_runtime-new';runtime.mkdir();(runtime/'lib').write_bytes(b'new runtime')
   release=publish(source,target)
   self.assertEqual(canonical.read_bytes(),b'running old exe')
   self.assertEqual(release.read_bytes(),b'new exe')
   self.assertEqual(publish(source,target),release)
 def test_different_runtime_contents_cannot_overwrite_existing(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/'source';source.mkdir();target=root/'target'
   (source/'AgentMessageHubDesktop.exe').write_bytes(b'exe');runtime=source/'_runtime-x';runtime.mkdir();(runtime/'lib').write_bytes(b'old')
   publish(source,target);(runtime/'lib').write_bytes(b'new')
   with self.assertRaisesRegex(RuntimeError,'different contents'):publish(source,target)
   self.assertEqual((target/'_runtime-x/lib').read_bytes(),b'old')
