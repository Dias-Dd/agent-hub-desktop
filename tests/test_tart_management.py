import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from hub.core import HubError
from hub.tart_bridge import TartBridge
from hub.tart_rfb import Console


def completed(bridge, request):
    end=time.monotonic()+5
    while time.monotonic()<end:
        _,result=bridge.record(request['request_id'])
        if result['state'] not in ('queued','running'):return result
        time.sleep(.01)
    raise AssertionError('job timed out')


class TartManagementTests(unittest.TestCase):
    def test_storage_preserves_existing_inventory_and_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=TartBridge(folder)
            self.assertEqual(bridge.default_home(),bridge.root/'machines')
            legacy=bridge.root/'machines';legacy.mkdir();(legacy/'old-vm').mkdir()
            self.assertEqual(bridge.environment()['TART_HOME'],str(legacy.resolve()))
            with patch.object(bridge,'inventory',return_value=[]):
                target=Path(folder)/'new-vms'
                bridge.control('set_home',tart_home=str(target),confirmed=True)
                bridge.control('save_preferences',auto_connect=False)
                self.assertEqual(bridge.environment()['TART_HOME'],str(target.resolve()))
                self.assertTrue((legacy/'old-vm').is_dir())
                bridge.control('disconnect')
                self.assertEqual(bridge.environment()['TART_HOME'],str(target.resolve()))
                with self.assertRaises(HubError):bridge.control('set_home',tart_home='/tmp/Foo.app/VM',confirmed=True)

    def test_delete_requires_confirmation_and_stopped_vm(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=TartBridge(folder)
            with self.assertRaises(HubError):bridge.control('delete',vm_name='myvm')
            with patch.object(bridge,'inventory',return_value=[{'name':'myvm','state':'running'}]),patch.object(bridge,'run') as run:
                result=completed(bridge,bridge.control('delete',vm_name='myvm',confirmed=True))
                self.assertEqual(result['state'],'failed');run.assert_not_called()

    def test_image_delete_cannot_target_vm_or_unlisted_path(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=TartBridge(folder)
            with patch.object(bridge,'run',return_value=b'[{"Name":"ghcr.io/test/image:latest"}]') as run:
                with self.assertRaises(HubError):bridge.control('delete_image',source='myvm',confirmed=True)
                self.assertEqual(run.call_count,1)
            with self.assertRaises(HubError):bridge.control('create',vm_name='myvm',source_type='tvm',source='../x.tvm',confirmed=True)

    def test_desktop_lease_is_shared_by_bridge_instances(self):
        with tempfile.TemporaryDirectory() as folder:
            one=TartBridge(folder);two=TartBridge(folder)
            one.desktop_lease('p','alice','myvm')
            with self.assertRaises(HubError):two.desktop_lease('p','bob','myvm')
            with self.assertRaises(HubError):two.desktop_lease('p','bob','myvm',release=True)
            one.desktop_lease('p','alice','myvm',release=True)
            two.desktop_lease('p','bob','myvm')
            self.assertTrue(two.desktop_lease('p','bob','myvm',inspect=True)['owned'])

    def test_rfb_validates_complete_text_and_chords_before_sending(self):
        console=Console.__new__(Console)
        with patch.object(console,'key') as key:
            with self.assertRaises(HubError):console.text('ascii中文')
            key.assert_not_called()
            with self.assertRaises(HubError):console.chord(['cmd','unknown-key'])
            key.assert_not_called()
        with patch.object(console,'chord') as chord:
            console.text('A!')
            self.assertEqual(chord.call_args_list[0].args[0],['shift','a'])
            self.assertEqual(chord.call_args_list[1].args[0],['shift','1'])

    def test_parallel_commands_are_distinct_jobs_with_root_and_agent_cwd(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge=TartBridge(folder)
            with patch.object(bridge,'status',return_value={'connected':True,'vm':'myvm','root_verified':True}),patch.object(bridge,'run',return_value=b'0\n') as run:
                jobs=[bridge.call('p',a,folder,action='exec',shell='posix',script='id -u') for a in ('alice','bob')]
                for job in jobs:self.assertEqual(completed(bridge,job)['state'],'completed')
                self.assertNotEqual(jobs[0]['request_id'],jobs[1]['request_id'])
                for call,agent in zip(run.call_args_list,('alice','bob')):
                    self.assertEqual(call.args[:5],('exec','myvm','sudo','-n','/bin/sh'))
                    self.assertIn('/p/'+agent,call.args[-1])
