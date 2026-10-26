"""Notification Center delivery for a bundled Cocoa app; permission is explicit."""
import threading
import uuid


def center():
    import Foundation as F
    if F.NSBundle.mainBundle().bundleIdentifier() != 'com.agenthub.desktop':
        raise RuntimeError('系统通知需要从 Agent Hub.app 启动；源码宿主无法申请应用通知权限')
    import UserNotifications as U
    return U.UNUserNotificationCenter.currentNotificationCenter()


def request_permission(callback):
    import UserNotifications as U
    center().requestAuthorizationWithOptions_completionHandler_(
        U.UNAuthorizationOptionAlert | U.UNAuthorizationOptionSound, callback)


def send(title, message, project=None):
    import UserNotifications as U
    target = center()
    ready = threading.Event()
    observed = {}
    def settings(value):
        observed['status'] = value.authorizationStatus()
        ready.set()
    target.getNotificationSettingsWithCompletionHandler_(settings)
    if not ready.wait(5):raise RuntimeError('读取通知权限超时')
    if observed['status'] not in (U.UNAuthorizationStatusAuthorized, U.UNAuthorizationStatusProvisional):
        raise RuntimeError('通知未授权；请在设置中点击“允许 macOS 通知”，或在系统设置的通知中允许 Agent Hub')
    content = U.UNMutableNotificationContent.alloc().init()
    content.setTitle_(title)
    content.setBody_(message)
    if project:content.setUserInfo_({'project':project})
    request = U.UNNotificationRequest.requestWithIdentifier_content_trigger_(str(uuid.uuid4()), content, None)
    ready.clear()
    def delivered(error):
        observed['error'] = str(error) if error else None
        ready.set()
    target.addNotificationRequest_withCompletionHandler_(request, delivered)
    if not ready.wait(5):raise RuntimeError('提交系统通知超时')
    if observed['error']:raise RuntimeError(observed['error'])
