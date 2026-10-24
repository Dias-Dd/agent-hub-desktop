import unittest,sys,socket,os
from desktop.launch_desktop import listener_pid
class WindowRestore(unittest.TestCase):
 @unittest.skipUnless(sys.platform=='win32','Windows TCP owner API')
 def test_listener_identity_is_scoped_to_actual_port_owner(self):
  with socket.socket() as first,socket.socket() as second:
   first.bind(('127.0.0.1',0));first.listen();second.bind(('127.0.0.1',0))
   self.assertEqual(listener_pid(first.getsockname()[1]),os.getpid())
   self.assertIsNone(listener_pid(second.getsockname()[1]))
