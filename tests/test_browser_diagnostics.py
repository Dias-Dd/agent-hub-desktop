import unittest,subprocess
from pathlib import Path
from unittest.mock import patch
from hub.browser_render import failure_detail,launch_browser
class Diagnostics(unittest.TestCase):
 def test_empty_error_includes_exit_and_missing_file(self):
  detail=failure_detail(subprocess.CompletedProcess([],1,b'',b''),Path('missing-screenshot.png'))
  self.assertIn('exit=1',detail);self.assertIn('PNG=False',detail);self.assertIn('stderr=(empty)',detail)
 def test_external_browser_environment_is_clean(self):
  with patch.dict('os.environ',{'WEBVIEW2_BROWSER_EXECUTABLE_FOLDER':'old','PYTHONHOME':'old'}),patch('hub.browser_render.subprocess.Popen') as popen:
   popen.return_value.communicate.return_value=(b'',b'');popen.return_value.returncode=0
   launch_browser(['browser'])
   env=popen.call_args.kwargs['env'];self.assertNotIn('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER',env);self.assertNotIn('PYTHONHOME',env)
