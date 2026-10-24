import unittest,os,sys,socket,tempfile,subprocess,time,ctypes as C
from pathlib import Path
from desktop.launch_desktop import check_health,get_user_token,listener_pid,restore_existing_window
@unittest.skipUnless(os.name=='nt','Windows only')
class Background(unittest.TestCase):
 def test_close_keeps_service_and_reopen_restores(self):
  with tempfile.TemporaryDirectory(prefix='hub-close-test-',ignore_cleanup_errors=True) as temp:
   data=Path(temp)/'data'
   with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
   command=[os.environ['HUB_TEST_EXE']] if os.environ.get('HUB_TEST_EXE') else [sys.executable,'desktop/launch_desktop.py']
   process=subprocess.Popen(command+['--port',str(port),'--data',str(data)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
   u=C.WinDLL('user32');u.FindWindowW.argtypes=[C.c_wchar_p,C.c_wchar_p];u.FindWindowW.restype=C.c_void_p;u.PostMessageW.argtypes=[C.c_void_p,C.c_uint,C.c_size_t,C.c_ssize_t];u.IsWindowVisible.argtypes=[C.c_void_p];u.IsWindowVisible.restype=C.c_bool
   try:
    hwnd=None
    for _ in range(100):
     pid=listener_pid(port)
     if pid:hwnd=u.FindWindowW('AgentMessageHubNative'+str(pid),None)
     if hwnd and u.IsWindowVisible(hwnd) and check_health(port,get_user_token(data)):break
     time.sleep(.1)
    self.assertTrue(hwnd,'native window missing');time.sleep(1)
    u.PostMessageW(hwnd,0x10,0,0)
    for _ in range(30):
     if not u.IsWindowVisible(hwnd):break
     time.sleep(.1)
    self.assertFalse(u.IsWindowVisible(hwnd),'close did not hide to tray')
    self.assertIsNone(process.poll());self.assertTrue(check_health(port,get_user_token(data)))
    self.assertTrue(restore_existing_window(port))
    for _ in range(30):
     if u.IsWindowVisible(hwnd):break
     time.sleep(.1)
    self.assertTrue(u.IsWindowVisible(hwnd))
   finally:process.terminate();process.wait(timeout=10)
