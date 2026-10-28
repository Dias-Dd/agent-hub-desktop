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

class SocketTransport(unittest.TestCase):
 def test_handshake_eof_is_reported_and_socket_closed(self):
  from unittest.mock import MagicMock
  from hub.browser_cdp import WebSocket
  from hub.core import HubError
  sock=MagicMock();sock.recv.return_value=b''
  with patch('hub.browser_cdp.socket.create_connection',return_value=sock):
   with self.assertRaisesRegex(HubError,'握手'):WebSocket('ws://127.0.0.1:1234/devtools')
  self.assertEqual(sock.recv.call_count,1);sock.close.assert_called_once()
 def test_pong_does_not_corrupt_text_message(self):
  from unittest.mock import MagicMock
  from hub.browser_cdp import WebSocket
  ws=WebSocket.__new__(WebSocket);ws.read=MagicMock(side_effect=[bytes([0x8a,1]),b'x',bytes([0x81,2]),b'{}'])
  self.assertEqual(ws.receive(),{})
