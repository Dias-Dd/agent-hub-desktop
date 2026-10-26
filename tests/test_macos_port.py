import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from hub.core import HubError
from hub.process_job import ProcessJob
from hub.tart_bridge import TartBridge


class PortBoundaries(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX only')
    def test_cancel_kills_child_after_parent_exits_without_touching_host(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file=Path(directory)/'child.pid'
            code=('import subprocess,sys; from pathlib import Path; '
                  'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                  'Path(sys.argv[1]).write_text(str(p.pid))')
            parent=subprocess.Popen([sys.executable,'-c',code,str(pid_file)],start_new_session=True)
            job=ProcessJob(parent)
            try:
                parent.wait(timeout=10)
                child=int(pid_file.read_text())
                os.kill(child,0)
                job.close()
                # A killed orphan may briefly remain a zombie before launchd reaps it.
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    result=subprocess.run(['ps','-o','stat=','-p',str(child)],capture_output=True,text=True)
                    if result.returncode or result.stdout.strip().startswith('Z'):break
                    time.sleep(.05)
                else:self.fail('Descendant survived process group cancellation')
            finally:job.close()

    def test_tart_rejects_cross_agent_result_and_ambiguous_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=TartBridge(directory)
            request=bridge.queue({'project':'p','agent':'one'},lambda:{'output':'done'})
            with self.assertRaises(HubError):bridge.call('p','two',directory,request_id=request['request_id'])
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                if bridge.call('p','one',directory,request_id=request['request_id'])['state']=='completed':break
                time.sleep(.01)
            with patch.object(bridge,'status',return_value={'connected':True,'vm':'test'}):
                with self.assertRaisesRegex(HubError,'shell='):bridge.call('p','one',directory,action='exec',script='Get-ChildItem')
                with self.assertRaises(HubError):bridge.call('p','one',directory,action='unknown_action')
                with self.assertRaises(HubError):bridge.call('p','one',directory,action='pull',path='../outside')

    def test_tart_queued_failure_is_never_reported_as_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=TartBridge(directory)
            def fail():raise HubError('Guest Agent unavailable')
            request=bridge.queue({'control':True},fail)
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                result=bridge.control('result',request_id=request['request_id'])
                if result['state'] not in ('queued','running'):break
                time.sleep(.01)
            self.assertEqual(result['state'],'failed')
            self.assertIn('Guest Agent',result['error'])

    def test_platform_selection_preserves_windows_bridge(self):
        from hub.vm_bridge import VmBridge
        with tempfile.TemporaryDirectory() as directory:
            with patch('hub.vm_bridge.sys.platform','win32'):
                self.assertIs(type(VmBridge(directory)),VmBridge)
            with patch('hub.vm_bridge.sys.platform','darwin'):
                self.assertIsInstance(VmBridge(directory),TartBridge)


if __name__=='__main__':unittest.main()
