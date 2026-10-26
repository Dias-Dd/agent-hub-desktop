"""Cocoa/WKWebView host. All AppKit operations stay on the main thread.

Child WKWebViews use WebKit's supplied configuration so window.opener and the
existing DOM-preserving popup protocol continue to share one application state.
"""
import json
import time
from urllib.parse import urlsplit

_host = None


def request_native_zoom(value):
    if type(value) is not int or value not in (90, 100, 110, 125, 150) or _host is None:
        return False
    from PyObjCTools import AppHelper
    AppHelper.callAfter(_host.zoom, value / 100)
    return True


def set_native_dark_mode(dark):
    if _host is not None:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(_host.theme, dark)


def run_native(url, profile, smoke=False, data_directory=None,notification_probe=False,browser_probe=False):
    import platform
    if int(platform.mac_ver()[0].split('.')[0]) < 14:
        raise RuntimeError('The isolated WKWebView host requires macOS 14 or newer')
    import objc
    import AppKit as A
    import Foundation as F
    import WebKit as W
    import UserNotifications
    from PyObjCTools import AppHelper
    from pathlib import Path

    global _host
    origin = urlsplit(url)
    result = {'engine': 'WKWebView', 'loaded': False, 'authenticated': False}

    class Host(F.NSObject, protocols=[objc.protocolNamed('UNUserNotificationCenterDelegate')]):
        def init(self):
            self = objc.super(Host, self).init()
            if self is None:
                return None
            self.windows = []
            self.views = []
            self.finished = False
            self.tray=None;self.hidden_windows=[]
            self.deadline = time.monotonic() + 40
            return self

        @objc.python_method
        def make_window(self, config, target=None, width=1366, height=860):
            view = W.WKWebView.alloc().initWithFrame_configuration_(A.NSMakeRect(0, 0, width, height), config)
            view.setUIDelegate_(self)
            view.setNavigationDelegate_(self)
            mask = (A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable |
                    A.NSWindowStyleMaskMiniaturizable | A.NSWindowStyleMaskResizable)
            main=not self.windows
            if main:mask |= A.NSWindowStyleMaskFullSizeContentView
            window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                A.NSMakeRect(0, 0, width, height), mask, A.NSBackingStoreBuffered, False)
            window.setReleasedWhenClosed_(False)
            window.setTitle_('Agent Hub')
            window.setMinSize_(A.NSMakeSize(520, 400))
            if main:
                window.setTitlebarAppearsTransparent_(True)
                window.setTitleVisibility_(A.NSWindowTitleHidden)
                effect=A.NSVisualEffectView.alloc().initWithFrame_(view.frame())
                effect.setMaterial_(A.NSVisualEffectMaterialSidebar)
                effect.setBlendingMode_(A.NSVisualEffectBlendingModeBehindWindow)
                effect.setState_(A.NSVisualEffectStateFollowsWindowActiveState)
                view.setAutoresizingMask_(A.NSViewWidthSizable|A.NSViewHeightSizable)
                view.setValue_forKey_(False,'drawsBackground')
                effect.addSubview_(view)
                window.setContentView_(effect)
                window.setOpaque_(False)
                window.setBackgroundColor_(A.NSColor.clearColor())
            else:window.setContentView_(view)
            window.setDelegate_(self)
            if main:self.layout_main_chrome(window,view)
            window.center()
            self.windows.append(window)
            self.views.append(view)
            window.makeKeyAndOrderFront_(None)
            if target:
                view.loadRequest_(F.NSURLRequest.requestWithURL_(F.NSURL.URLWithString_(target)))
            return view

        @objc.python_method
        def layout_main_chrome(self,window,view):
            # Public standard buttons remain native, including hover/full-screen behavior.
            if window.styleMask() & A.NSWindowStyleMaskFullScreen:return
            content=window.contentView();height=content.bounds().size.height
            zoom=float(view.pageZoom())
            close=window.standardWindowButton_(A.NSWindowCloseButton)
            close_rect=close.superview().convertRect_toView_(close.frame(),content)
            horizontal=18-close_rect.origin.x
            for kind in (A.NSWindowCloseButton,A.NSWindowMiniaturizeButton,A.NSWindowZoomButton):
                button=window.standardWindowButton_(kind)
                if button is None or button.superview() is None:continue
                current=button.superview().convertRect_toView_(button.frame(),content)
                center=A.NSMakePoint(current.origin.x+horizontal+current.size.width/2,height-24*zoom)
                point=button.superview().convertPoint_fromView_(center,content)
                frame=button.frame()
                button.setFrameOrigin_(A.NSMakePoint(point.x-frame.size.width/2,point.y-frame.size.height/2))

        def windowDidResize_(self,notification):
            if self.windows and notification.object()==self.windows[0]:
                self.layout_main_chrome(self.windows[0],self.views[0])

        def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(self, view, config, action, features):
            target = action.request().URL()
            parsed = urlsplit(str(target.absoluteString())) if target else None
            if parsed and (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                if parsed.scheme == 'https':
                    A.NSWorkspace.sharedWorkspace().openURL_(target)
                return None
            return self.make_window(config,width=max(520,int(features.width() or 900)),height=max(400,int(features.height() or 700)))

        def webView_decidePolicyForNavigationAction_decisionHandler_(self, view, action, decide):
            target = action.request().URL()
            parsed = urlsplit(str(target.absoluteString())) if target else None
            local = parsed and (parsed.scheme, parsed.netloc) == (origin.scheme, origin.netloc)
            if local or (parsed and parsed.scheme == 'about'):
                decide(W.WKNavigationActionPolicyAllow)
            else:
                decide(W.WKNavigationActionPolicyCancel)
                if parsed and parsed.scheme == 'https' and action.navigationType() == W.WKNavigationTypeLinkActivated:
                    A.NSWorkspace.sharedWorkspace().openURL_(target)

        def webViewDidClose_(self, view):
            for window in self.windows:
                if window.contentView() == view:
                    window.close()
                    break

        @objc.python_method
        def stop(self):
            app.stop_(None)
            event = A.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                A.NSEventTypeApplicationDefined, (0, 0), 0, 0, 0, None, 0, 0, 0)
            app.postEvent_atStart_(event, True)

        def windowWillClose_(self, notification):
            window = notification.object()
            if self.windows and window == self.windows[0]:
                for child in self.windows[1:]:
                    child.close()
                self.stop()

        def windowShouldClose_(self, window):
            if not self.windows:return True
            if window==self.windows[0]:
                if self.tray and not smoke:
                    self.hidden_windows=[w for w in self.windows if w.isVisible()]
                    for child in self.hidden_windows:child.orderOut_(None)
                    return False
                return True
            # A native red close button must return the original DOM to its
            # owner before hiding the child, just like the in-page close button.
            def returned(value,error):
                if error:
                    alert=A.NSAlert.alloc().init()
                    alert.setMessageText_('无法返回设置内容；请使用窗口内的关闭按钮。 / Unable to return settings. Use the in-page close button.')
                    alert.runModal()
                else:window.close()
            window.contentView().evaluateJavaScript_completionHandler_(
                'if(window.HubPopupClose)window.HubPopupClose();else window.close();',returned)
            return False

        def applicationShouldTerminate_(self, app):
            if not smoke:
                from desktop.ui_preferences import language
                english=data_directory and language(data_directory)=='en'
                alert=A.NSAlert.alloc().init()
                alert.setMessageText_('Quit Agent Hub?' if english else '退出 Agent Hub？')
                alert.setInformativeText_('Quitting stops background tasks. Reopen to check and resume.' if english else '退出将停止后台任务。再次打开后经理会核查现场续接。')
                alert.addButtonWithTitle_('Cancel' if english else '取消')
                alert.addButtonWithTitle_('Quit' if english else '退出')
                if alert.runModal()!=A.NSAlertSecondButtonReturn:return A.NSTerminateCancel
            self.stop()
            return A.NSTerminateCancel

        def restore_(self, notification):
            self.windows[0].deminiaturize_(None)
            self.windows[0].makeKeyAndOrderFront_(None)
            for window in self.hidden_windows:window.makeKeyAndOrderFront_(None)
            self.hidden_windows=[]
            app.activateIgnoringOtherApps_(True)

        def applicationShouldHandleReopen_hasVisibleWindows_(self,app,visible):
            self.restore_(None);return True

        @objc.python_method
        def open_project(self,project):
            self.restore_(None)
            self.views[0].evaluateJavaScript_completionHandler_(
                'window.HubDesktop?.chooseProject('+json.dumps(str(project))+')',None)

        def showSetup_(self, sender):
            self.views[0].evaluateJavaScript_completionHandler_("window.HubDesktop?.openFirstRunGuide?.()",None)

        def userContentController_didReceiveScriptMessage_(self, controller, message):
            if not message.frameInfo().isMainFrame():return
            parsed=urlsplit(str(message.webView().URL().absoluteString()))
            if (parsed.scheme,parsed.netloc)!=(origin.scheme,origin.netloc):return
            body=message.body()
            if hasattr(body,'get') and body.get('type')=='hub-window' and message.webView()==self.views[0]:
                command=body.get('command')
                if command=='appearance' and isinstance(body.get('dark'),bool):self.theme(body['dark'])
                elif command=='maximize':self.windows[0].zoom_(None)
                elif command=='drag':
                    event=app.currentEvent()
                    if event and event.type() in (A.NSEventTypeLeftMouseDown,A.NSEventTypeLeftMouseDragged):
                        self.windows[0].performWindowDragWithEvent_(event)
            if smoke and hasattr(body,'get') and body.get('smoke_close_popup') and len(self.windows)>1:
                self.windows[-1].performClose_(None)
            if smoke and hasattr(body,'get') and body.get('smoke_tray'):
                self.hidden_windows=[self.windows[0]];self.windows[0].orderOut_(None)
                hidden=not self.windows[0].isVisible();self.restore_(None)
                result['tray_hide_restore']=bool(self.tray and hidden and self.windows[0].isVisible())
                if self.tray:
                    self.tray.menuNeedsUpdate_(self.tray.menu)
                    result['tray_menu_items']=self.tray.menu.numberOfItems()
            if hasattr(body,'get') and body.get('language') in ('en','zh-CN') and data_directory:
                from desktop.ui_preferences import save_language
                save_language(data_directory,body['language'])
            if hasattr(body,'get') and body.get('request_notifications') is True:
                self.requestNotifications_(None)

        def requestNotifications_(self, sender):
            from desktop.macos_notifications import request_permission
            def completed(granted, error):
                result['notification_permission'] = bool(granted)
                if error:result['notification_error'] = str(error)
            try:request_permission(completed)
            except RuntimeError as error:
                alert=A.NSAlert.alloc().init()
                alert.setMessageText_(str(error));alert.runModal()

        def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(self,center,response,done):
            project=response.notification().request().content().userInfo().get('project')
            if project:AppHelper.callAfter(self.open_project,project)
            done()

        def userNotificationCenter_willPresentNotification_withCompletionHandler_(self,center,notification,done):
            # The delivery policy was checked before enqueueing this OS request.
            done(UserNotifications.UNNotificationPresentationOptionBanner |
                 UserNotifications.UNNotificationPresentationOptionList |
                 UserNotifications.UNNotificationPresentationOptionSound)

        @objc.python_method
        def notifications(self):
            if self.finished or not self.cache:return
            import queue
            try:
                event=self.cache.notifications.get_nowait()
            except queue.Empty:event=None
            if event:
                from hub.notification_settings import allowed
                if not allowed(self.cache.value.get('notification_settings',{}),event,bool(A.NSApp().isActive())):event=None
            if event:
                if self.tray:self.tray.observe(event)
                def deliver():
                    from desktop.macos_notifications import send
                    from desktop.ui_preferences import language
                    english=language(data_directory)=='en'
                    from hub.notification_settings import wording
                    title=wording(event.get('kind'),english)
                    try:
                        send(title,event.get('name') or title,event.get('project'))
                        observation={'submitted':True, 'event':event['id']}
                    except Exception as error:
                        observation={'submitted':False, 'error':str(error), 'event':event['id']}
                    if data_directory:
                        from hub.notification_settings import record_delivery
                        record_delivery(data_directory,event,observation['submitted'],observation.get('error'),channel='macos')
                import threading
                threading.Thread(target=deliver,daemon=True).start()
            AppHelper.callLater(1,self.notifications)

        @objc.python_method
        def zoom(self, factor):
            for view in self.views:
                view.setPageZoom_(factor)
            if self.windows:self.layout_main_chrome(self.windows[0],self.views[0])

        @objc.python_method
        def theme(self, dark):
            appearance = A.NSAppearance.appearanceNamed_(A.NSAppearanceNameDarkAqua if dark else A.NSAppearanceNameAqua)
            for window in self.windows:
                window.setAppearance_(appearance)

        @objc.python_method
        def check(self):
            if self.finished:
                return
            if time.monotonic() > self.deadline:
                result['error'] = 'WKWebView UI/authentication readiness timed out'
                self.finished = True
                self.stop()
                return
            script = """(async()=>{const H=window.HubDesktop;
              if(!H?.client.hasToken())return '{}';
              if(!H.firstRunChecked)return '{}';
              const state=await H.client.getState();
              const paletteValues=[...document.getElementById('interfaceColors').querySelectorAll('input[data-token]')].map(f=>({mode:f.dataset.mode,value:f.value}));
              for(const mode of ['light','dark']){
                const values=paletteValues.filter(f=>f.mode===mode).map(f=>f.value);
                if(values.length!==7||new Set(values).size<4)throw Error('Default palette collapsed: '+mode+' '+JSON.stringify(values));
              }
              H.store.stopPolling();
              const firstRun=document.getElementById('setupWizard');
              let firstRunShown=!firstRun.hidden;
              if(firstRunShown){
                const attached=Date.now()+5000;
                while(firstRun.ownerDocument===document&&Date.now()<attached)await new Promise(r=>setTimeout(r,25));
                const skip=document.getElementById('setupClose');
                if(skip.ownerDocument.defaultView.getComputedStyle(skip).display==='none'||skip.getBoundingClientRect().height<1)
                  throw Error('First-run skip button hidden in native panel');
                document.getElementById('setupClose').click();
                const finish=Date.now()+5000;
                while(!firstRun.hidden&&Date.now()<finish)await new Promise(r=>setTimeout(r,25));
                if(!firstRun.hidden)throw Error('First-run completion did not persist');
              }
              window.webkit.messageHandlers.hubNative.postMessage({smoke_tray:true});
              const bar=document.getElementById('nativeTitlebar');
              const toggle=bar?.querySelector('button[aria-label="显示／隐藏项目列表"]');
              if(!toggle||!document.documentElement.classList.contains('native-macos'))throw Error('Mac titlebar missing');
              toggle.click();if(!document.documentElement.classList.contains('sidebar-collapsed'))throw Error('Sidebar did not collapse');
              toggle.click();if(document.documentElement.classList.contains('sidebar-collapsed'))throw Error('Sidebar did not expand');
              const editor=document.getElementById('discussionReply'),draft='WKWebView draft verification';
              const previous=editor.value;editor.value=draft;
              const root=document.getElementById('configModal');
              document.getElementById('configModalToggle').checked=true;
              const end=Date.now()+5000;
              while(root.ownerDocument===document&&Date.now()<end)await new Promise(r=>setTimeout(r,25));
              const popup=root.ownerDocument!==document;
              root.querySelector('[aria-controls="vmSettings"]')?.click();
              for(const [openId,dialogId] of [['tartEditHome','tartDirectoryDialog'],['tartOpenInstaller','tartInstallDialog'],['tartOpenAccessibility','tartAccessibilityDialog']]){
                document.getElementById(openId).click();
                const panel=document.getElementById(dialogId),until=Date.now()+5000;
                while(panel.ownerDocument===document&&Date.now()<until)await new Promise(r=>setTimeout(r,25));
                if(!panel.open||panel.ownerDocument===document||panel.ownerDocument===root.ownerDocument)
                  throw Error('Tart independent dialog failed: '+dialogId);
                const close=panel.querySelector('footer [data-close-tart]');
                if(close.getBoundingClientRect().height<1)throw Error('Tart dialog close hidden');
                close.click();
                const returned=Date.now()+5000;
                while(panel.ownerDocument!==document&&Date.now()<returned)await new Promise(r=>setTimeout(r,25));
                if(panel.open||panel.ownerDocument!==document)throw Error('Tart dialog did not return');
              }
              let browserRendering=null;
              if(BROWSER_PROBE){
                root.querySelector('[aria-controls="renderSettings"]').click();
                const until=Date.now()+5000;
                while(document.getElementById('renderBrowserChoice').options.length<2&&Date.now()<until)await new Promise(r=>setTimeout(r,25));
                const settings=await H.client.postAction('render_settings',{operation:'read'});
                if(!settings.current)throw Error(settings.error||'No rendering browser');
                const path=settings.current.split('/Contents/MacOS/')[0];
                const saved=await H.client.postAction('render_settings',{operation:'save',mode:'custom',path});
                if(saved.current!==settings.current)throw Error('App bundle browser selection mismatch');
                browserRendering=await H.client.postAction('render_settings',{operation:'test'});
                if(!browserRendering.ok)throw Error('Configured browser rendering failed');
                root.querySelector('[aria-controls="notificationSettings"]').click();
                if(document.getElementById('notificationPermission').hidden)throw Error('Mac notification permission action missing');
              }
              window.webkit.messageHandlers.hubNative.postMessage({smoke_close_popup:true});
              const closeEnd=Date.now()+5000;
              while(root.ownerDocument!==document&&Date.now()<closeEnd)await new Promise(r=>setTimeout(r,25));
              if(!popup||document.getElementById('configModal')!==root||editor.value!==draft)
                throw Error('Independent window or draft preservation failed');
              editor.value=previous;
              let notificationDelivery=null;
              if(NOTIFICATION_PROBE){
                const request=await H.client.postAction('notification_settings',{operation:'test'});
                const until=Date.now()+15000;
                while(Date.now()<until){
                  await new Promise(r=>setTimeout(r,250));
                  const value=await H.client.postAction('notification_settings',{operation:'delivery_status'});
                  if(value.delivery?.event===request.event_id){notificationDelivery=value.delivery;break;}
                }
                if(!notificationDelivery)throw Error('Notification delivery result timed out');
              }
              return JSON.stringify({popup:true,tart_dialogs:true,draft_preserved:true,native_chrome:true,sidebar_toggle:true,first_run_shown:firstRunShown,
              notification_delivery:notificationDelivery,
              palette_values:paletteValues,browser_rendering:browserRendering,toolbar_center:bar.getBoundingClientRect().height/2,
              loaded:!!H, authenticated:!!state,
              ready:!!window.HubDesktop?.view, title:document.title,
              width:innerWidth,height:innerHeight});})()"""
            script=script.replace('NOTIFICATION_PROBE',json.dumps(bool(notification_probe)))
            script=script.replace('BROWSER_PROBE',json.dumps(bool(browser_probe)))
            # callAsyncJavaScript awaits the promise, unlike evaluateJavaScript.
            self.views[0].callAsyncJavaScript_arguments_inFrame_inContentWorld_completionHandler_(
                'return await ' + script, {}, None, W.WKContentWorld.pageWorld(), self.checked)

        @objc.python_method
        def checked(self, value, error):
            if error:
                result['last_error'] = str(error)
            if not error and isinstance(value, str):
                state = json.loads(value)
                if state.get('loaded') and state.get('authenticated') and state.get('ready'):
                    content=self.windows[0].contentView();centers=[];lefts=[]
                    for kind in (A.NSWindowCloseButton,A.NSWindowMiniaturizeButton,A.NSWindowZoomButton):
                        button=self.windows[0].standardWindowButton_(kind)
                        rect=button.superview().convertRect_toView_(button.frame(),content)
                        centers.append(content.bounds().size.height-rect.origin.y-rect.size.height/2);lefts.append(rect.origin.x)
                    result['traffic_light_centers']=centers
                    result['traffic_light_lefts']=lefts
                    expected=state['toolbar_center']*float(self.views[0].pageZoom())
                    if any(abs(center-expected)>1 for center in centers) or abs(lefts[0]-18)>1:
                        result['error']='Native traffic lights and toolbar center differ'
                        self.finished=True;self.stop();return
                    result.update(state)
                    self.finished = True
                    self.stop()
                    return
            AppHelper.callLater(.5, self.check)

    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
    host = Host.alloc().init()
    _host = host
    app.setDelegate_(host)
    menu = A.NSMenu.alloc().init()
    app_item = A.NSMenuItem.alloc().init()
    menu.addItem_(app_item)
    app_menu = A.NSMenu.alloc().init()
    app_menu.addItemWithTitle_action_keyEquivalent_('Quit Agent Hub', 'terminate:', 'q')
    app_menu.addItemWithTitle_action_keyEquivalent_('Enable Notifications / 允许通知', 'requestNotifications:', '')
    app_menu.addItemWithTitle_action_keyEquivalent_('Configure Harness / 配置接入', 'showSetup:', ',')
    app_item.setSubmenu_(app_menu)
    window_item=A.NSMenuItem.alloc().init();menu.addItem_(window_item)
    window_menu=A.NSMenu.alloc().initWithTitle_('Window')
    window_menu.addItemWithTitle_action_keyEquivalent_('Close Window / 关闭窗口','performClose:','w')
    window_menu.addItemWithTitle_action_keyEquivalent_('Minimize / 最小化','performMiniaturize:','m')
    window_item.setSubmenu_(window_menu);app.setWindowsMenu_(window_menu)
    edit_item = A.NSMenuItem.alloc().init()
    menu.addItem_(edit_item)
    edit_menu = A.NSMenu.alloc().initWithTitle_('Edit')
    for title, action, key in [('Undo','undo:','z'), ('Cut','cut:','x'), ('Copy','copy:','c'),
                               ('Paste','paste:','v'), ('Select All','selectAll:','a')]:
        edit_menu.addItemWithTitle_action_keyEquivalent_(title, action, key)
    edit_item.setSubmenu_(edit_menu)
    app.setMainMenu_(menu)
    config = W.WKWebViewConfiguration.alloc().init()
    # Keep cache/cookies separate for each data directory. Never touch Safari data.
    import uuid
    identity = uuid.uuid5(uuid.NAMESPACE_URL, str(Path(data_directory or profile).resolve()))
    identifier = F.NSUUID.alloc().initWithUUIDString_(str(identity))
    config.setWebsiteDataStore_(W.WKWebsiteDataStore.dataStoreForIdentifier_(identifier))
    config.preferences().setJavaScriptCanOpenWindowsAutomatically_(True)
    config.userContentController().addScriptMessageHandler_name_(host,'hubNative')
    config.userContentController().addUserScript_(W.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        'window.__HUB_NATIVE_WINDOWS__=true;window.__HUB_NATIVE_MACOS__=true;window.__HUB_NATIVE_BACKDROP__='+json.dumps(None if A.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceTransparency() else 'sidebar')+';', W.WKUserScriptInjectionTimeAtDocumentStart, True))
    host.make_window(config, url)
    import os
    notifications=F.NSDistributedNotificationCenter.defaultCenter()
    notifications.addObserver_selector_name_object_(host,'restore:','AgentHubActivate',str(os.getpid()))
    app.activateIgnoringOtherApps_(True)
    from desktop.tray_status import StatusCache
    host.cache=StatusCache(data_directory) if data_directory else None
    if host.cache:
        from desktop.macos_tray import MacTray
        host.tray=MacTray.alloc().initWithOwner_status_(host,host.cache)
    try:
        from desktop.macos_notifications import center
        notification_center=center();notification_center.setDelegate_(host)
    except RuntimeError:notification_center=None
    if host.cache:AppHelper.callLater(1,host.notifications)
    if smoke:
        AppHelper.callLater(.5, host.check)
    try:
        AppHelper.runEventLoop(installInterrupt=True)
    finally:
        host.finished = True
        notifications.removeObserver_(host)
        if host.cache:host.cache.close()
        if host.tray:host.tray.close()
        if notification_center:notification_center.setDelegate_(None)
        for view in host.views:
            view.setUIDelegate_(None)
            view.setNavigationDelegate_(None)
            view.stopLoading()
        config.userContentController().removeScriptMessageHandlerForName_('hubNative')
        for window in host.windows:
            window.setDelegate_(None)
            window.close()
        _host = None
    if smoke and not result.get('authenticated'):
        raise RuntimeError(result.get('error', 'WKWebView smoke failed')+' '+result.get('last_error',''))
    return result
