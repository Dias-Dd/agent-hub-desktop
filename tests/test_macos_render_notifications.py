"""macOS app bundle selection and honest OS notification acknowledgements."""
import json,plistlib,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from hub.core import Hub,HubError
from hub import render_settings,notification_settings
from hub.chromium_download import target
from desktop import macos_notifications

class MacSettings(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.h=Hub(self.tmp.name,recover=False);self.addCleanup(self.h.db.close)
 def app(self,name='Chromium'):
  app=Path(self.tmp.name)/(name+'.app');binary=app/'Contents/MacOS'/name
  binary.parent.mkdir(parents=True);binary.write_text('#!/bin/sh\nexit 0\n');binary.chmod(0o755)
  (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':name}));return app,binary
 def test_app_bundle_selection_resolves_executable_and_persists(self):
  app,binary=self.app()
  with patch('hub.render_settings.sys.platform','darwin'):
   value=render_settings.action(self.h,'user','save',mode='custom',path=str(app))
   self.assertEqual(value['config']['path'],str(binary.resolve()));self.assertEqual(render_settings.resolve(self.h),str(binary.resolve()))
 def test_bundle_cannot_point_outside_itself(self):
  app,binary=self.app();(app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'../../../outside'}))
  with patch('hub.render_settings.sys.platform','darwin'),self.assertRaises(HubError):render_settings.validate(str(app))
 def test_missing_bundle_executable_does_not_fallback(self):
  app,binary=self.app();binary.unlink()
  with patch('hub.render_settings.sys.platform','darwin'),self.assertRaises(HubError):render_settings.validate(str(app))
 def test_mac_snapshot_architecture_matches_machine(self):
  with patch('hub.chromium_download.sys.platform','darwin'):
   for machine,group in [('arm64','Mac_Arm'),('x86_64','Mac')]:
    with self.subTest(machine=machine),patch('hub.chromium_download.platform.machine',return_value=machine):
     self.assertEqual(target(),(group,'chrome-mac.zip','chrome-mac/Chromium.app/Contents/MacOS/Chromium'))
 def test_test_event_is_queued_then_reports_real_result(self):
  request=notification_settings.action(self.h,'user','test');self.assertTrue(request['queued'])
  self.assertIsNone(notification_settings.action(self.h,'user','delivery_status')['delivery'])
  event={'id':request['event_id'],'kind':'test'}
  notification_settings.record_delivery(self.h.directory,event,False,'Notifications denied','macos')
  # Ordinary events must not overwrite the explicit test's acknowledgement.
  notification_settings.record_delivery(self.h.directory,{'id':'other','kind':'demo'},True,channel='macos')
  state=notification_settings.action(self.h,'user','delivery_status')['delivery']
  self.assertEqual(state['event'],request['event_id']);self.assertFalse(state['submitted']);self.assertEqual(state['error'],'Notifications denied')
  with self.assertRaises(HubError):notification_settings.action(self.h,'deepseek-1','delivery_status')

class MacDelivery(unittest.TestCase):
 def test_diagnostics_write_failure_does_not_replay_notification(self):
  with patch('hub.notification_settings.Path.write_text',side_effect=OSError('disk full')),patch('hub.notification_settings.Path.unlink',side_effect=OSError('read only')):
   notification_settings.record_delivery('/temporary',{'id':'test:accepted','kind':'test'},True,channel='macos')
 def test_denied_does_not_claim_accepted_or_request_permission(self):
  center=SimpleNamespace(getNotificationSettingsWithCompletionHandler_=lambda cb:cb(SimpleNamespace(authorizationStatus=lambda:0)))
  module=SimpleNamespace(UNAuthorizationStatusAuthorized=2,UNAuthorizationStatusProvisional=3)
  with patch('desktop.macos_notifications.center',return_value=center),patch.dict('sys.modules',{'UserNotifications':module}):
   with self.assertRaisesRegex(RuntimeError,'未授权'):macos_notifications.send('test','body')
 def test_os_error_is_propagated_after_authorized_submission(self):
  class Content:
   def setTitle_(self,value):pass
   def setBody_(self,value):pass
  center=SimpleNamespace(getNotificationSettingsWithCompletionHandler_=lambda cb:cb(SimpleNamespace(authorizationStatus=lambda:2)),addNotificationRequest_withCompletionHandler_=lambda request,cb:cb('OS rejected request'))
  module=SimpleNamespace(UNAuthorizationStatusAuthorized=2,UNAuthorizationStatusProvisional=3,UNMutableNotificationContent=SimpleNamespace(alloc=lambda:SimpleNamespace(init=Content)),UNNotificationRequest=SimpleNamespace(requestWithIdentifier_content_trigger_=lambda *args:args))
  with patch('desktop.macos_notifications.center',return_value=center),patch.dict('sys.modules',{'UserNotifications':module}):
   with self.assertRaisesRegex(RuntimeError,'OS rejected'):macos_notifications.send('test','body')
