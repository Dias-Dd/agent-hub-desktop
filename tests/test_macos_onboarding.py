import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from desktop.first_run import action
from hub.core import Hub,HubError
from hub.tart_bridge import TartBridge


class FirstRun(unittest.TestCase):
    def test_missing_tart_requires_install_action_and_does_not_claim_homebrew_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=TartBridge(directory)
            with patch.object(bridge,'executable',return_value=None),patch.object(bridge,'brew',return_value=None),patch('hub.tart_bridge.subprocess.run') as command:
                self.assertFalse(bridge.status()['installed'])
                self.assertFalse(bridge.status()['homebrew_installed'])
                with self.assertRaises(HubError):bridge.control('install')
                with self.assertRaisesRegex(HubError,'Homebrew'):bridge.control('install',confirmed=True)
                with self.assertRaises(HubError):bridge.control('create',vm_name='vm',confirmed=False)
                command.assert_not_called()

    def test_skip_persists_but_unverified_vm_cannot_complete_and_agents_cannot_write(self):
        with tempfile.TemporaryDirectory() as directory:
            hub=Hub(directory,recover=False)
            try:
                self.assertTrue(action(hub,'user')['needed'])
                with patch('hub.vm_bridge.VmBridge') as bridge:
                    bridge.return_value.status.return_value={'connected':False}
                    with self.assertRaises(HubError):action(hub,'user','complete',False)
                self.assertTrue(action(hub,'user')['needed'])
                with self.assertRaises(HubError):action(hub,'deepseek-1','complete',True)
                action(hub,'user','complete',True)
                self.assertFalse(action(hub,'user')['needed'])
                (Path(directory)/'macos-onboarding.completed.json').write_text('invalid')
                self.assertTrue(action(hub,'user')['needed'])
            finally:hub.db.close()

    def test_tart_preferences_and_single_flight_connect(self):
        import threading,time
        with tempfile.TemporaryDirectory() as directory:
            bridge=TartBridge(directory);gate=threading.Event()
            def probe(*args,**kwargs):
                if args[0]=='exec':gate.wait(2);return str(args[-1]).split()[-1].encode() if args[-2]=='-c' else b''
                return b''
            with patch.object(bridge,'inventory',return_value=[{'name':'vm','state':'running'}]),patch.object(bridge,'run',side_effect=probe),patch.object(bridge,'guest_write'),patch.object(bridge,'guest_read',side_effect=HubError('Python missing')):
                one=bridge.control('connect',vm_name='vm',auto_connect=True)
                two=bridge.control('auto_connect') if bridge.selected().get('remember') else bridge.connect('vm',True)
                self.assertEqual(one['request_id'],two['request_id'])
                gate.set();deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    value=bridge.control('result',request_id=one['request_id'])
                    if value['state'] not in ('queued','running'):break
                    time.sleep(.01)
                self.assertEqual(value['state'],'completed',value)
                self.assertFalse(value['transfer_verified'])
                self.assertTrue(TartBridge(directory).preferences()['auto_connect'])
                bridge.control('disconnect')
                self.assertFalse(TartBridge(directory).preferences()['auto_connect'])
                self.assertTrue(bridge.control('auto_connect')['skipped'])
