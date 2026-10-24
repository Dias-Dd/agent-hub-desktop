import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

class SupervisorTests(unittest.TestCase):
    def test_force_kill_child_restarts_and_preserves_inbox(self):
        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            proc=subprocess.Popen([sys.executable,'-m','hub.supervisor','--data',directory,'--port',str(port),'--no-sim'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            path=Path(directory);base=f'http://127.0.0.1:{port}';child_pid=None
            def wait_for(fn,seconds=15):
                deadline=time.monotonic()+seconds
                while time.monotonic()<deadline:
                    try:
                        value=fn()
                        if value:return value
                    except (OSError,ValueError,KeyError):pass
                    time.sleep(.1)
                raise AssertionError('timeout waiting for supervisor')
            def request(action=None,args=None):
                token=json.loads((path/'credentials.json').read_text())['user']
                req=urllib.request.Request(base+('/api/action' if action else '/api/state'),data=json.dumps({'action':action,'args':args or {}}).encode() if action else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=2) as response:return json.load(response)
            try:
                wait_for(lambda:request())
                child_pid=int((path/'service.pid').read_text())
                ident=request('send',{'recipient':'opus','body':'survive child crash'})['result'][0]
                os.kill(child_pid,signal.SIGTERM)
                wait_for(lambda:(path/'service.pid').exists() and int((path/'service.pid').read_text())!=child_pid)
                state=wait_for(lambda:request())
                self.assertEqual(next(m for m in state['messages'] if m['id']==ident)['status'],'pending')
                self.assertTrue((path/'supervisor.jsonl').exists())
            finally:
                # Stop supervisor first, then its latest child. No process is left behind.
                proc.terminate();proc.wait(timeout=5)
                if (path/'service.pid').exists():
                    try:os.kill(int((path/'service.pid').read_text()),signal.SIGTERM)
                    except OSError:pass
                time.sleep(.3)

if __name__=='__main__':unittest.main()
