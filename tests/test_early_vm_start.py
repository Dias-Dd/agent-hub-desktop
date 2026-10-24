import tempfile,threading,time,unittest,urllib.request
from pathlib import Path
from unittest.mock import patch
from desktop.fast_start import FastHub
from desktop.launch_desktop import OwnedHub
from hub.core import HubError

class EarlyVmStartup(unittest.TestCase):
 def exercise(self,error=None,startup_extras=True,saved=True):
  release=threading.Event();called=threading.Event();calls=[];owner=None
  def slow(*args,**kwargs):release.wait(5);return OwnedHub(*args,**kwargs)
  def control(_bridge,action,**kwargs):
   calls.append(action)
   if action=='connect_saved':
    called.set()
    if error:raise HubError(error)
    return {'request_id':'fixture'}
   return {'state':'completed'}
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder,patch('desktop.launch_desktop.OwnedHub',side_effect=slow),patch('hub.vm_bridge.VmBridge.saved_connections',return_value=[{'vm':'Hub'}] if saved else []),patch('hub.vm_bridge.VmBridge.control',autospec=True,side_effect=control),patch('desktop.dependencies.start_dependencies'):
   try:
    start=time.monotonic();owner=FastHub(Path(folder)/'data',0,startup_extras=startup_extras)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    self.assertIn('id="workspace"',opener.open(f'http://127.0.0.1:{owner.port}/').read().decode())
    self.assertLess(time.monotonic()-start,2)
    self.assertFalse(owner.server.ui_ready.is_set());self.assertFalse(owner.server.startup['backend_ready'])
    if startup_extras and saved:
     self.assertTrue(called.wait(2),'VM authorization waited for backend/UI')
     if owner.vm_initializer:owner.vm_initializer.join(2)
     self.assertEqual(owner.server.startup['stages']['vm']['state'],'failed' if error else 'ready')
    else:
     if owner.vm_initializer:owner.vm_initializer.join(2)
     self.assertEqual(calls,[])
    release.set();owner.initializer.join(10)
    self.assertTrue(owner.server.startup['backend_ready'])
    self.assertEqual(calls.count('connect_saved'),1 if startup_extras and saved else 0)
   finally:
    release.set()
    if owner:owner.close()
 def test_vm_authorization_starts_before_backend_and_ui_handshake(self):self.exercise()
 def test_cancelled_consent_not_requested_again_after_backend_loads(self):self.exercise(error='管理员授权被取消')
 def test_smoke_mode_never_requests_authorization(self):self.exercise(startup_extras=False)
 def test_no_saved_vm_never_requests_authorization(self):self.exercise(saved=False)
