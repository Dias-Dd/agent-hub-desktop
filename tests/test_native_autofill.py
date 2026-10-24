import unittest,sys,tempfile
from pathlib import Path
from desktop.native_webview import run_native,find_loader
from desktop.launch_desktop import OwnedHub
class NativeAutofill(unittest.TestCase):
 @unittest.skipUnless(sys.platform=='win32' and find_loader(),'Windows WebView2 required')
 def test_native_autofill_settings_readback_and_recovery(self):
  with tempfile.TemporaryDirectory(prefix='hub_autofill_',ignore_cleanup_errors=True) as tmp:
   root=Path(tmp);owned=OwnedHub(root/'data',0,simulate=False)
   try:
    result=run_native(f'http://127.0.0.1:{owned.port}/',root/'profile',recovery_test=True)
    self.assertFalse(result['browser_features']['general_autofill']);self.assertFalse(result['browser_features']['password_autosave']);self.assertTrue(result['recovery_pass'])
   finally:owned.close()
