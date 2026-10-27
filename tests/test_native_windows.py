import os,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from desktop.native_popups import popup_request,popup_style

class Request(unittest.TestCase):
 def test_origin_and_modality(self):
  base='http://127.0.0.1:8766/'
  self.assertIsNone(popup_request('https://example.com/popup.html#id=x&modal=1',base))
  self.assertIsNone(popup_request(base+'api/shared/x#id=x',base))
  self.assertIsNone(popup_request(base+'popup.html#modal=1',base))
  self.assertTrue(popup_request(base+'popup.html#id=confirm&modal=1',base)['modal'])
  self.assertFalse(popup_request(base+'popup.html#id=settings&modal=0',base)['modal'])
  self.assertEqual(popup_request(base+'popup.html#id=x&width=100000&height=bad',base)['width'],2400)

class CaptionControls(unittest.TestCase):
 def test_review_retains_minimize_and_maximize(self):
  self.assertEqual(popup_style({'id':'designReviewDialog'}) & 0x30000,0x30000)
 def test_other_dialogs_keep_existing_controls(self):
  for identity in ('configModal','connectionTestDialog','newProjectDialog'):
   self.assertEqual(popup_style({'id':identity}),0x00CC0000)

@unittest.skipUnless(os.environ.get('HUB_NATIVE_UI_TEST')=='1','explicit isolated visible-window test')
class Native(unittest.TestCase):
 def test_real_owned_windows_and_drafts(self):
  from hub.server import Server
  from test_nine_browser import Fixture
  from desktop.native_webview import run_native
  from desktop.native_popups import NativePopups
  class ZoomedPopups(NativePopups):
   def __init__(self,*args,**kwargs):
    super().__init__(*args,**kwargs);self.zoom=lambda:1.25
  server=Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
    def capture_frame(hwnd,user,state):
     import ctypes as C
     from ctypes import wintypes as W
     from PIL import ImageGrab
     bounds=W.RECT();user.GetClientRect(hwnd,C.byref(bounds));origin=W.POINT(0,0);user.ClientToScreen(hwnd,C.byref(origin))
     outer=W.RECT();user.GetWindowRect(hwnd,C.byref(outer))
     self.assertLessEqual(abs(origin.y-outer.top),2)
     close=state['caption'].close_rect;edge=W.POINT(bounds.right-2,max(2,(close[1]+close[3])//2));user.ClientToScreen(hwnd,C.byref(edge))
     self.assertEqual(int(user.SendMessageW(hwnd,0x84,0,(edge.x&0xffff)|((edge.y&0xffff)<<16))),20,'rightmost Close edge must remain clickable')
     # Hit testing alone missed invisible native glyphs in an earlier regression.
     # Verify the actual DWM hover reaches the visible right edge, without a painted patch.
     previous=W.POINT();user.GetCursorPos(C.byref(previous))
     center=W.POINT((close[0]+close[2])//2,(close[1]+close[3])//2);user.ClientToScreen(hwnd,C.byref(center))
     try:
      user.SetForegroundWindow(hwnd);user.SetCursorPos(center.x,center.y)
      user.SendMessageW(hwnd,0xA0,20,(center.x&0xffff)|((center.y&0xffff)<<16))
      C.windll.dwmapi.DwmFlush();__import__('time').sleep(.2)
      pixels=ImageGrab.grab(bbox=(edge.x,edge.y,edge.x+1,edge.y+1)).getpixel((0,0))
      self.assertTrue(pixels[0]>150 and pixels[1]<110 and pixels[2]<110,'native Close hover did not reach right edge: '+str(pixels))
     finally:user.SetCursorPos(previous.x,previous.y)
     folder=Path(__file__).resolve().parents[1]/'data';folder.mkdir(exist_ok=True)
     ImageGrab.grab(bbox=(outer.left,outer.top,outer.right,outer.top+300)).save(folder/'mica-titlebar-verified.png')
    with patch('desktop.native_popups.NativePopups',ZoomedPopups):
     result=run_native('http://127.0.0.1:'+str(server.server_port)+'/',Path(folder)/'profile',smoke=True,popup_test=True,frame_probe=capture_frame)
    self.assertTrue(result['mica']);self.assertTrue(result['webview_transparent'])
    self.assertLessEqual(result['caption_right_gap'],2)
    self.assertEqual(result['native_close_hit'],20)
    self.assertEqual(result['native_snap_hit'],9)
    self.assertEqual(result['rounded_corner_preference'],2)
    self.assertTrue(result['review_caption_verified']);self.assertTrue(result['custom_chrome']);self.assertTrue(result['popup_modal_verified']);self.assertTrue(result['popup_modeless_verified'])
    self.assertEqual(result['popup_counts'],{'created':6,'closed':6,'remaining':0})
    print('PASS round DWM corners, real HWNDs, modeless main enabled, modal owner disabled, native close, drafts, reopen, all controllers released',result['popup_counts'])
  finally:server.shutdown();server.server_close();thread.join()

 def test_snap_layout_real_hover(self):
  from hub.server import Server
  from test_nine_browser import Fixture
  from desktop.native_webview import run_native
  server=Server(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
    result=run_native('http://127.0.0.1:'+str(server.server_port)+'/',Path(folder)/'profile',smoke=True,snap_test=True)
   if result.get('snap_probe_interrupted'):self.skipTest('Pointer/focus moved outside the isolated test window during native hover')
   self.assertTrue(result['snap_flyout_visible'],'Windows Snap flyout did not appear on real hover')
   self.assertEqual(result['native_snap_hit'],9);self.assertEqual(result['rounded_corner_preference'],2)
   print('PASS real pointer hover opens native Windows Snap flyout; DWM round corners')
  finally:server.shutdown();server.server_close();thread.join()
