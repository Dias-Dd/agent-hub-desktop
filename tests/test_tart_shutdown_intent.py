import tempfile,unittest
from unittest.mock import patch
from hub.tart_bridge import TartBridge
from hub.core import HubError
class Shutdown(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.b=TartBridge(self.tmp.name)
  self.b.write(self.b.root/'connection.json',{'vm':'fixture','remember':True})
 def test_shutdown_disables_auto_connect_before_stop_is_queued(self):
  for action in ('power_off','power_force'):
   with self.subTest(action=action),patch.object(self.b,'queue',return_value={'state':'queued'}) as queue:
    self.b.save_preferences(auto_connect=True);self.b.control(action,vm_name='fixture')
    self.assertFalse(TartBridge(self.tmp.name).preferences()['auto_connect'])
    with patch.object(self.b,'connect') as connect:
     self.assertTrue(self.b.control('auto_connect')['skipped']);connect.assert_not_called()
 def test_external_shutdown_does_not_repeat_automatic_start(self):
  with patch.object(self.b,'connect',return_value={'state':'completed'}) as connect:
   self.b.control('auto_connect');self.assertTrue(self.b.control('auto_connect')['skipped']);self.assertEqual(connect.call_count,1)
   self.b.control('save_preferences',auto_connect=True);self.b.control('auto_connect');self.assertEqual(connect.call_count,2)

 def test_pending_auto_power_on_is_cancelled_after_user_shutdown(self):
  with patch.object(self.b,'queue',return_value={'state':'queued'}) as queue:
   self.b.control('power_on',vm_name='fixture',automatic=True);work=queue.call_args.args[1]
  self.b.save_preferences(auto_connect=False)
  with patch('hub.tart_bridge.subprocess.Popen') as spawn,self.assertRaisesRegex(HubError,'未启动'):
   work()
  spawn.assert_not_called()
