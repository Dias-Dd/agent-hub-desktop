"""Native Win32 host for the locally installed WebView2 Runtime (no browser app).
API reference: https://learn.microsoft.com/microsoft-edge/webview2/reference/win32/
Uses only ctypes and an existing Microsoft WebView2Loader.dll; downloads nothing.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys
import uuid
import time
from .ui_recovery import RecoveryPolicy


def find_loader():
    if sys.platform != 'win32':
        return None
    local = Path(os.environ.get('LOCALAPPDATA', ''))
    program = Path(os.environ.get('PROGRAMFILES', 'C:/Program Files'))
    candidates = [Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1])) / 'desktop/WebView2Loader.dll']
    candidates += list((local / 'Microsoft/OneDrive').glob('*/WebView2Loader.dll'))
    candidates += [program / 'Bambu Studio/WebView2Loader.dll']
    candidates += list((program / 'Autodesk/AdskIdentityManager').glob('*/WebView2Loader.dll'))
    for candidate in candidates:
        try:
            lib = C.WinDLL(str(candidate))
            getattr(lib, 'CreateCoreWebView2EnvironmentWithOptions')
            return str(candidate)
        except (OSError, AttributeError):
            continue
    return None



_ACTIVE_WINDOW = None
WM_DESKTOP_ZOOM = 0x8007
WM_DESKTOP_THEME = 0x8008
ZOOM_LEVELS = (90, 100, 110, 125, 150)


def set_immersive_dark_mode(hwnd, dark=True):
    """Set DWMWA_USE_IMMERSIVE_DARK_MODE (20 on Win10 2004+ / Win11, 19 on earlier Win10)."""
    try:
        dwmapi = C.windll.dwmapi
        value = C.c_int(1 if dark else 0)
        hr = dwmapi.DwmSetWindowAttribute(hwnd, 20, C.byref(value), C.sizeof(value))
        if hr != 0:
            dwmapi.DwmSetWindowAttribute(hwnd, 19, C.byref(value), C.sizeof(value))
        return True
    except Exception:
        return False


def is_system_dark_mode():
    """Detect Windows application dark mode preference from registry."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return val == 0
    except Exception:
        return False


def enable_native_frame(hwnd,dark=None):
    """Request DWM rounding/shadow while retaining our client-drawn title bar."""
    try:
        dwm=C.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes=[W.HWND,W.DWORD,C.c_void_p,W.DWORD]
        dwm.DwmExtendFrameIntoClientArea.argtypes=[W.HWND,C.c_void_p]
        policy=C.c_int(2)
        dwm.DwmSetWindowAttribute(hwnd,2,C.byref(policy),C.sizeof(policy))
        preference=C.c_int(2) # DWMWCP_ROUND; Windows keeps snapped/maximized edges square.
        dwm.DwmSetWindowAttribute(hwnd,33,C.byref(preference),C.sizeof(preference))
        class MARGINS(C.Structure):
            _fields_=[('left',C.c_int),('right',C.c_int),('top',C.c_int),('bottom',C.c_int)]
        from .native_backdrop import apply
        material=apply(hwnd,is_system_dark_mode() if dark is None else dark)
        margins=MARGINS(-1,-1,-1,-1) if material else MARGINS(1,1,1,1)
        dwm.DwmExtendFrameIntoClientArea(hwnd,C.byref(margins))
        return material
    except (AttributeError,OSError):
        pass


def set_native_dark_mode(dark=True):
    """Notify the active native window to update its titlebar theme."""
    if not _ACTIVE_WINDOW:
        return False
    user = C.windll.user32
    user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    return bool(user.PostMessageW(_ACTIVE_WINDOW, WM_DESKTOP_THEME, 1 if dark else 0, 0))


def enable_dpi_awareness(user=None, shcore=None):
    """Run before any HWND; manifests may have already selected Per-Monitor V2."""
    user = user or C.windll.user32
    try:
        setter = user.SetProcessDpiAwarenessContext
        setter.argtypes = [C.c_void_p]; setter.restype = W.BOOL
        if setter(C.c_void_p(-4)):
            return 'per-monitor-v2'
        current = user.GetThreadDpiAwarenessContext
        current.restype = C.c_void_p
        equal = user.AreDpiAwarenessContextsEqual
        equal.argtypes = [C.c_void_p,C.c_void_p];equal.restype = W.BOOL
        if equal(current(),C.c_void_p(-4)):
            return 'per-monitor-v2-existing'
    except (AttributeError,OSError):
        pass
    try:
        shcore = shcore or C.windll.shcore
        if shcore.SetProcessDpiAwareness(2) >= 0:
            return 'per-monitor'
    except (AttributeError,OSError):
        pass
    try:
        if user.SetProcessDPIAware():
            return 'system-aware'
    except (AttributeError,OSError):
        pass
    return 'already-configured'


def initial_geometry(dpi, work_area):
    """Logical 1440x900, capped inside the primary monitor's usable area."""
    left,top,right,bottom = work_area
    scale = max(1,int(dpi))/96
    available_w,available_h = max(1,right-left),max(1,bottom-top)
    width = max(1,min(round(1440*scale),int(available_w*.94)))
    height = max(1,min(round(900*scale),int(available_h*.92)))
    return left+(available_w-width)//2,top+(available_h-height)//2,width,height


def apply_dpi_bounds(user, hwnd, rect, resize):
    user.SetWindowPos(hwnd,None,rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top,0x0014)
    resize()


def request_native_zoom(percent):
    """HTTP bridge posts to the UI thread; never call COM from the server thread."""
    if type(percent) is not int or percent not in ZOOM_LEVELS or not _ACTIVE_WINDOW:
        return False
    user = C.windll.user32
    user.PostMessageW.argtypes = [W.HWND,W.UINT,W.WPARAM,W.LPARAM]
    return bool(user.PostMessageW(_ACTIVE_WINDOW,WM_DESKTOP_ZOOM,percent,0))


def run_native(url, profile, smoke=False, recovery_test=False, popup_test=False, data_directory=None, snap_test=False, frame_probe=None):
    """Own the native UI message loop; close controller before caller closes Hub."""
    global _ACTIVE_WINDOW
    dpi_awareness = enable_dpi_awareness()
    loader = find_loader()
    if not loader:
        raise RuntimeError('Native WebView2 loader unavailable; install WebView2 Runtime or select an explicit browser engine.')
    user, kernel, ole = C.windll.user32, C.windll.kernel32, C.windll.ole32
    HRESULT = C.c_long
    PTR = C.c_void_p
    CALLBACK = C.WINFUNCTYPE
    LRESULT = C.c_ssize_t
    user.DefWindowProcW.restype = LRESULT
    user.DefWindowProcW.argtypes = [W.HWND,W.UINT,W.WPARAM,W.LPARAM]
    user.CreateWindowExW.restype = W.HWND
    user.CreateWindowExW.argtypes = [W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,PTR]
    kernel.GetModuleHandleW.restype = W.HMODULE
    user.GetMessageW.argtypes = [C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT]
    user.PostMessageW.argtypes = [W.HWND,W.UINT,W.WPARAM,W.LPARAM]
    user.DestroyWindow.argtypes = [W.HWND]
    user.GetClientRect.argtypes = [W.HWND,C.POINTER(W.RECT)]
    user.ShowWindow.argtypes = [W.HWND,C.c_int]
    user.SetTimer.argtypes = [W.HWND,C.c_size_t,W.UINT,PTR]
    user.KillTimer.argtypes = [W.HWND,C.c_size_t]
    user.SetWindowPos.argtypes = [W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT]
    user.SystemParametersInfoW.argtypes = [W.UINT,W.UINT,C.c_void_p,W.UINT]
    user.GetWindowRect.argtypes = [W.HWND,C.POINTER(W.RECT)]
    user.ScreenToClient.argtypes=[W.HWND,C.POINTER(W.POINT)]
    user.ClientToScreen.argtypes=[W.HWND,C.POINTER(W.POINT)]
    user.ReleaseCapture.argtypes=[]
    user.IsZoomed.argtypes=[W.HWND];user.IsZoomed.restype=W.BOOL
    user.SendMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
    user.MonitorFromWindow.argtypes=[W.HWND,W.DWORD];user.MonitorFromWindow.restype=W.HANDLE
    ole.CoInitializeEx(None,2)
    profile = Path(profile); profile.mkdir(parents=True,exist_ok=True)
    recovery=RecoveryPolicy();ui_started_at=time.monotonic()
    keep = []
    state = {'controller':None,'core':None,'error':None,'smoke_pass':False,'checking':False,'dpi_awareness':dpi_awareness,'dpi_changes':0,'zoom_percent':100}

    def call(ptr, slot, result, args, *values):
        table = C.cast(ptr,C.POINTER(C.POINTER(PTR))).contents
        fn = CALLBACK(result,PTR,*args)(table[slot])
        return fn(ptr,*values)

    def check(hr):
        if hr < 0:
            raise RuntimeError('WebView2 HRESULT 0x%08x' % (hr & 0xffffffff))

    def handler(signature, invoke):
        qi_type = CALLBACK(HRESULT,PTR,PTR,C.POINTER(PTR))
        ref_type = CALLBACK(W.ULONG,PTR)
        invoke_type = CALLBACK(HRESULT,PTR,*signature)
        class Object(C.Structure):
            _fields_ = [('vtable',C.POINTER(PTR))]
        obj = Object()
        def query(_this, iid, out):
            # IUnknown is the only extra interface this STA callback implements.
            if C.string_at(iid,16) == uuid.UUID('00000000-0000-0000-c000-000000000046').bytes_le:
                out[0] = C.cast(C.pointer(obj),PTR); return 0
            out[0] = None; return -2147467262
        def safe(_this,*args):
            try:
                invoke(*args)
            except Exception as error:
                state['error'] = str(error); user.PostMessageW(hwnd,0x10,0,0)
            return 0
        functions = [qi_type(query),ref_type(lambda _:2),ref_type(lambda _:1),invoke_type(safe)]
        vtable = (PTR*4)(*[C.cast(fn,PTR).value for fn in functions])
        obj.vtable = vtable; keep.extend([obj,vtable,*functions])
        return C.cast(C.pointer(obj),PTR)

    def log_ui(event,**detail):
        try:
            dest=profile.parent/'data'/'desktop-ui.log'
            if dest.exists() and dest.stat().st_size>1000000:dest.replace(dest.with_suffix('.previous.log'))
            with dest.open('a',encoding='utf8') as stream:stream.write(json.dumps({'at':time.time(),'event':event,**detail},ensure_ascii=False)+'\n')
        except OSError:pass

    def recover_ui(recreate=False,manual=False,reason='page health'):
        if not recovery.allow(time.monotonic(),manual):
            user.SetWindowTextW(hwnd,'Agent Message Hub · 界面恢复已暂停，按 F5 重试')
            log_ui('recovery_throttled',reason=reason);return
        log_ui('recovery',recreate=recreate,reason=reason)
        state['ui_checking']=False;state['ui_grace']=time.monotonic()+(1 if recovery_test else 20)
        user.SetWindowTextW(hwnd,'Agent Message Hub · 正在恢复界面（后台任务继续）')
        if state.get('popups'):state['popups'].close_all()
        if recreate and state.get('environment'):
            if state['controller']:
                call(state['controller'],24,HRESULT,[]);call(state['controller'],2,W.ULONG,[]);state['controller']=None
            if state['core']:call(state['core'],2,W.ULONG,[]);state['core']=None
            check(call(state['environment'],3,HRESULT,[W.HWND,PTR],hwnd,state['controller_callback']))
        elif state['core']:
            hr=call(state['core'],5,HRESULT,[W.LPCWSTR],url)
            if hr<0:user.PostMessageW(hwnd,0x8009,1,0)

    def ui_health_result(hr,result):
        state['ui_checking']=False
        if hr<0:
            user.PostMessageW(hwnd,0x8009,1,0);return
        try:data=json.loads(result or 'null') or {}
        except ValueError:data={}
        if data.get('hasUI'):
            recovery.observe(True);user.SetWindowTextW(hwnd,'Agent Hub')
            if recovery_test:
                if not state.get('blank_injected'):
                    state['blank_injected']=True
                    check(call(state['core'],6,HRESULT,[W.LPCWSTR],'<html><body></body></html>'))
                    state['ui_grace']=time.monotonic()+1
                elif recovery.attempts:
                    state['recovery_pass']=True;user.PostMessageW(hwnd,0x10,0,0)
        elif time.monotonic()>state.get('ui_grace',0) and recovery.observe(False):
            log_ui('blank_document');user.PostMessageW(hwnd,0x8009,0,0)

    def process_failed(_sender,args):
        kind=C.c_int();call(args,3,HRESULT,[C.POINTER(C.c_int)],C.byref(kind))
        log_ui('process_failed',kind=kind.value)
        if kind.value in (0,1,2,3,6):user.PostMessageW(hwnd,0x8009,1 if kind.value==0 else 0,0)

    def resize():
        if state['controller']:
            rect = W.RECT();user.GetClientRect(hwnd,C.byref(rect))
            # WindowRect includes invisible resize borders; align the WebView to
            # DWM's visible frame so content and native Close share a right edge.
            visible=W.RECT();origin=W.POINT(0,0);user.ClientToScreen(hwnd,C.byref(origin))
            dwm=C.windll.dwmapi;dwm.DwmGetWindowAttribute.argtypes=[W.HWND,W.DWORD,C.c_void_p,W.DWORD]
            if dwm.DwmGetWindowAttribute(hwnd,9,C.byref(visible),C.sizeof(visible))>=0 and visible.right>visible.left:
                rect.left=max(0,visible.left-origin.x);rect.right=min(rect.right,visible.right-origin.x)
                rect.bottom=min(rect.bottom,visible.bottom-origin.y)
            state['webview_bounds']=[rect.left,rect.top,rect.right,rect.bottom]
            check(call(state['controller'],6,HRESULT,[W.RECT],rect))

    def script_result(hr, result):
        state['checking'] = False; check(hr)
        data = json.loads(result or 'null'); state['last_result']=data
        if popup_test and data:
            popups=state.get('popups');enabled=bool(user.IsWindowEnabled(hwnd))
            user.GetWindowLongW.argtypes=[W.HWND,C.c_int];user.GetWindowLongW.restype=C.c_long
            if popups and any(user.GetWindowLongW(child,-16)&0x30000 for child in popups.windows):raise RuntimeError('Popup has minimize/maximize buttons')
            if data.get('phase')=='modal' and not enabled and not state.get('popup_modal_verified'):
                state['popup_modal_verified']=True
                user.PostMessageW(next(iter(popups.windows)),0x10,0,0)
            if data.get('phase')=='modeless' and enabled and popups and popups.windows and not state.get('popup_modeless_verified'):
                state['popup_modeless_verified']=True
                user.PostMessageW(next(iter(popups.windows)),0x10,0,0)
            if data.get('error'):raise RuntimeError(data['error'])
            if data.get('ready'):
                if not state.get('popup_modal_verified') or not state.get('popup_modeless_verified') or not enabled:raise RuntimeError('Native popup modality verification failed')
                state['popup_counts']={'created':popups.created,'closed':popups.closed,'remaining':len(popups.windows)}
        if data and data.get('ready'):
            zoom=C.c_double();check(call(state['controller'],7,HRESULT,[C.POINTER(C.c_double)],C.byref(zoom)))
            state['actual_zoom_factor']=zoom.value
            if state.get('maximize_rect'):
                left,top,right,bottom=state['maximize_rect']
                center=W.POINT(round((left+right)/2),round((top+bottom)/2));user.ClientToScreen(hwnd,C.byref(center))
                hit=user.SendMessageW(hwnd,0x84,0,(center.x&0xffff)|((center.y&0xffff)<<16))
                state['native_snap_hit']=int(hit)
                if hit!=9:raise RuntimeError('Native maximize region did not return HTMAXBUTTON')
                close=state['caption'].close_rect
                point=W.POINT(round((close[0]+close[2])/2),round((close[1]+close[3])/2));user.ClientToScreen(hwnd,C.byref(point))
                state['native_close_hit']=int(user.SendMessageW(hwnd,0x84,0,(point.x&0xffff)|((point.y&0xffff)<<16)))
            else:raise RuntimeError('Native maximize geometry missing')
            if snap_test:
                # Exercise a real pointer hover, rather than merely sending WM_NCHITTEST.
                def visible_windows():
                    result={}
                    @CALLBACK(W.BOOL,W.HWND,W.LPARAM)
                    def collect(item,unused):
                        if user.IsWindowVisible(item):
                            label=C.create_unicode_buffer(256);user.GetClassNameW(item,label,256)
                            result[int(item)]=label.value
                        return True
                    @CALLBACK(W.BOOL,W.HWND,W.LPARAM)
                    def root_collect(item,unused):
                        collect(item,unused)
                        user.EnumChildWindows(item,collect,0)
                        return True
                    user.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
                    user.IsWindowVisible.argtypes=[W.HWND]
                    user.EnumWindows(root_collect,0)
                    return result
                if not state.get('snap_hover_started'):
                    state['snap_before']=visible_windows();state['snap_hover_started']=time.monotonic()
                    state['previous_cursor']=W.POINT();user.GetCursorPos(C.byref(state['previous_cursor']))
                    user.SetForegroundWindow(hwnd);user.SetCursorPos(center.x-150,center.y+100)
                    state['checking']=False
                    return
                if not state.get('snap_hover_entered'):
                    state['caption'].clip_webview()
                    user.SetForegroundWindow(hwnd);user.SetCursorPos(center.x,center.y)
                    state['snap_hover_entered']=True;state['snap_hover_started']=time.monotonic()
                    state['checking']=False;return
                candidates=[]
                for item,name in visible_windows().items():
                    if 'Xaml_WindowedPopupClass' not in name and 'Multitasking' not in name:continue
                    bounds=W.RECT();user.GetWindowRect(item,C.byref(bounds))
                    if bounds.left-20<=center.x<=bounds.right+20 and abs(bounds.top-center.y)<round(180*state['system_dpi']/96):candidates.append(name)
                user.WindowFromPoint.argtypes=[W.POINT];user.WindowFromPoint.restype=W.HWND
                user.GetAncestor.argtypes=[W.HWND,W.UINT];user.GetAncestor.restype=W.HWND
                probe=W.POINT(center.x,center.y+round(70*state['system_dpi']/96))
                hit=user.WindowFromPoint(probe);root=user.GetAncestor(hit,2)
                name=C.create_unicode_buffer(256);user.GetClassNameW(root,name,256)
                # Immersive shell popups may be absent from EnumWindows. Probe
                # below this window's native maximize button as well.
                if root!=hwnd and name.value=='Xaml_WindowedPopupClass':candidates.append(name.value)
                state['snap_hover_windows']=candidates
                state['snap_flyout_visible']=bool(candidates)
                pointer=W.POINT();user.GetCursorPos(C.byref(pointer))
                user.GetForegroundWindow.restype=W.HWND
                state['snap_probe_interrupted']=not candidates and ((pointer.x,pointer.y)!=(center.x,center.y) or user.GetForegroundWindow()!=hwnd)
                if not candidates and time.monotonic()-state['snap_hover_started']<3:
                    state['checking']=False;return
                previous=state['previous_cursor'];user.SetCursorPos(previous.x,previous.y)
            dwm=C.windll.dwmapi
            dwm.DwmGetWindowAttribute.argtypes=[W.HWND,W.DWORD,C.c_void_p,W.DWORD]
            preference=C.c_int()
            corner_hr=dwm.DwmGetWindowAttribute(hwnd,33,C.byref(preference),C.sizeof(preference))
            state['rounded_corner_preference']=preference.value if corner_hr>=0 else None
            if frame_probe and not state.get('frame_probed'):
                frame_probe(hwnd,user,state);state['frame_probed']=True
            suggested=W.RECT();user.GetWindowRect(hwnd,C.byref(suggested))
            suggested.right-=20;suggested.bottom-=20
            user.SendMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
            user.SendMessageW(hwnd,0x02E0,(state['system_dpi']<<16)|state['system_dpi'],C.addressof(suggested))
            actual=W.RECT();user.GetWindowRect(hwnd,C.byref(actual))
            state['synthetic_dpi_rect_applied']=(actual.left,actual.top,actual.right,actual.bottom)==(suggested.left,suggested.top,suggested.right,suggested.bottom)
            try:state['window_dpi']=int(user.GetDpiForWindow(hwnd))
            except AttributeError:state['window_dpi']=state['system_dpi']
            client=W.RECT();frame=W.RECT();user.GetClientRect(hwnd,C.byref(client));user.GetWindowRect(hwnd,C.byref(frame))
            user.GetWindowLongW.argtypes=[W.HWND,C.c_int];user.GetWindowLongW.restype=C.c_long
            origin=W.POINT(0,0);user.ClientToScreen(hwnd,C.byref(origin))
            state['custom_chrome']=abs(origin.y-frame.top)<=2
            if state.get('caption') and state['caption'].rect:
                state['caption_right_gap']=abs(state.get('webview_bounds',[0,0,client.right,client.bottom])[2]-state['caption'].rect[2])
            if popup_test and not state['custom_chrome']:raise RuntimeError('Native caption/frame mismatch: style='+hex(user.GetWindowLongW(hwnd,-16)&0xffffffff)+' outer='+str([frame.right-frame.left,frame.bottom-frame.top])+' client='+str([client.right,client.bottom]))
            state['smoke_pass'] = True; state['verification'] = data
            user.PostMessageW(hwnd,0x10,0,0)

    WNDPROC = CALLBACK(LRESULT,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
    def refresh_material(window,dark):
        state['backdrop']=enable_native_frame(window,dark)
        state['mica']=state['backdrop']=='mica'
        caption=state.get('caption')
        if caption:
            caption.backdrop=bool(state['backdrop'])
            if caption.last_geometry:caption.geometry(*caption.last_geometry)
        if state.get('core'):
            material=state.get('backdrop') if state.get('webview_transparent') else None
            call(state['core'],29,HRESULT,[W.LPCWSTR,PTR],'window.HubNativeBackdrop?.('+json.dumps(material)+');',None)

    def wndproc(window,msg,wp,lp):
        caption=state.get('caption')
        if msg != 0x83:
            dwm=C.windll.dwmapi
            dwm.DwmDefWindowProc.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM,C.POINTER(LRESULT)]
            native=LRESULT()
            if dwm.DwmDefWindowProc(window,msg,wp,lp,C.byref(native)):return native.value
        if msg==0x84 and state.get('maximize_rect'):
            point=W.POINT(C.c_short(lp&0xffff).value,C.c_short((lp>>16)&0xffff).value)
            user.ScreenToClient(window,C.byref(point))
            left,top,right,bottom=state['maximize_rect']
            if left<=point.x<right and top<=point.y<bottom:
                return 9 # HTMAXBUTTON: Windows 11's own Snap Layout hover menu.
        if msg==0x84 and not user.IsZoomed(window): # resize hit-testing without WS_CAPTION
            bounds=W.RECT();user.GetWindowRect(window,C.byref(bounds))
            px=C.c_short(lp&0xffff).value;py=C.c_short((lp>>16)&0xffff).value
            try:edge=max(4,round(6*user.GetDpiForWindow(window)/96))
            except AttributeError:edge=6
            left=px<bounds.left+edge;right=px>=bounds.right-edge
            top=py<bounds.top+edge;bottom=py>=bounds.bottom-edge
            if top:return 13 if left else 14 if right else 12
            if bottom:return 16 if left else 17 if right else 15
            if left:return 10
            if right:return 11
        if msg==0x83 and wp: # Preserve native resize borders; extend the client over the title only.
            proposed=C.cast(lp,C.POINTER(W.RECT)).contents
            full=W.RECT(proposed.left,proposed.top,proposed.right,proposed.bottom)
            dpi=user.GetDpiForWindow(window)
            inset=user.GetSystemMetricsForDpi(32,dpi)+user.GetSystemMetricsForDpi(92,dpi)
            C.cast(lp,C.POINTER(W.RECT))[0]=W.RECT(full.left+inset,full.top,full.right-inset,full.bottom-inset)
            if user.IsZoomed(window):
                class MONITORINFO(C.Structure):
                    _fields_=[('cbSize',W.DWORD),('rcMonitor',W.RECT),('rcWork',W.RECT),('dwFlags',W.DWORD)]
                info=MONITORINFO();info.cbSize=C.sizeof(info)
                user.GetMonitorInfoW.argtypes=[W.HANDLE,C.POINTER(MONITORINFO)]
                if user.GetMonitorInfoW(user.MonitorFromWindow(window,2),C.byref(info)):
                    C.cast(lp,C.POINTER(W.RECT))[0]=info.rcWork
            return 0
        if msg==0x8012 and state.get('tray'):
            state['tray'].handle(lp);return 0
        if msg==0x8013 or (msg==0x112 and (wp&0xfff0)==0x1f20):
            english=state.get('tray') and state['tray'].language=='en'
            prompt='Quitting stops background tasks. When reopened, the manager will check the current state before resuming. Quit Agent Hub?' if english else '退出将停止后台任务。再次打开后经理会核查现场续接。确定退出？'
            if user.MessageBoxW(window,prompt,'Quit Agent Hub' if english else '退出 Agent Hub',0x24|0x100)!=6:return 0
            state['explicit_exit']=True;user.PostMessageW(window,0x10,0,0);return 0
        if (msg in (0x100,0x104) and (wp==0x74 or (wp==ord('R') and user.GetKeyState(0x11)&0x8000))) or (msg==0x112 and (wp&0xfff0)==0x1f10):
            user.PostMessageW(window,0x8009,0,1);return 0
        if msg == 0x8009:
            try:recover_ui(recreate=bool(wp),manual=bool(lp))
            except Exception as error:log_ui('recovery_error',error=str(error));user.SetWindowTextW(window,'Agent Message Hub · 恢复失败，按 F5 重试')
            return 0
        if msg == 0x113 and not smoke:
            if state.get('tray'):state['tray'].notify_pending()
            now=time.monotonic()
            if recovery_test and now-ui_started_at>45:
                state['error']='Native recovery probe timed out';user.PostMessageW(window,0x10,0,0);return 0
            if state.get('ui_checking'):
                if now-state.get('ui_started',now)>35:
                    log_ui('page_unresponsive');user.PostMessageW(window,0x8009,1,0)
            elif state['core'] and now>state.get('ui_grace',0):
                state['ui_checking']=True;state['ui_started']=now
                expression="(()=>({hasUI:!!(document.body&&document.getElementById('workspace')&&window.HubDesktop)}))()"
                hr=call(state['core'],29,HRESULT,[W.LPCWSTR,PTR],expression,state['health_callback'])
                if hr<0:state['ui_checking']=False;user.PostMessageW(window,0x8009,1,0)
            return 0
        if msg == 6 and state['core']:
            call(state['core'],32,HRESULT,[W.LPCWSTR],json.dumps({'type':'hub-window-focus','active':bool(int(wp)&0xffff)}))
        if msg == 5:
            if state.get('caption'):state['caption'].invalidate()
            if state['core']:call(state['core'],32,HRESULT,[W.LPCWSTR],json.dumps({'type':'hub-window-state','maximized':bool(user.IsZoomed(window))}))
            try:
                resize()
                if state.get('caption') and state['caption'].last_geometry:
                    state['caption'].geometry(*state['caption'].last_geometry)
                    state['maximize_rect']=state['caption'].maximize_rect
            except Exception as e: state['error']=str(e)
            return 0
        if msg == 0x02E0:
            suggested = C.cast(lp,C.POINTER(W.RECT)).contents
            state['dpi_changes'] += 1
            apply_dpi_bounds(user,window,suggested,resize)
            return 0
        if msg == WM_DESKTOP_ZOOM and state['controller'] and wp in ZOOM_LEVELS:
            check(call(state['controller'],8,HRESULT,[C.c_double],wp/100.0))
            state['zoom_percent'] = int(wp)
            if state.get('popups'):
                for child in state['popups'].windows.values():
                    if child['controller']:call(child['controller'],8,HRESULT,[C.c_double],wp/100.0)
            return 0
        if msg == 0x001A:
            dark=state.get('dark_mode',is_system_dark_mode())
            set_immersive_dark_mode(window,dark)
            refresh_material(window,dark)
            return 0
        if msg == WM_DESKTOP_THEME:
            state['dark_mode']=bool(wp)
            set_immersive_dark_mode(window, bool(wp))
            refresh_material(window,bool(wp))
            if state.get('popups'):
                for child in state['popups'].windows:set_immersive_dark_mode(child,bool(wp))
            return 0
        if msg == 3 and state['controller']:
            call(state['controller'],23,HRESULT,[])
        if msg == 0x113 and smoke:
            state['ticks'] = state.get('ticks',0)+1
            if state['ticks'] > 25:
                state['error']='Native window startup timed out: '+str(state.get('last_result'));user.PostMessageW(window,0x10,0,0)
            elif state['core'] and not state['checking']:
                state['checking']=True
                expression="(()=>{const H=window.HubDesktop;const ready=!!(H?.client.hasToken()&&document.querySelectorAll('#agents .agent-box').length===9&&document.getElementById('setupWizard').hidden);if(ready&&!window.__hubZoomProbe){window.__hubZoomProbe='pending';H.setInterfaceZoom(125).then(()=>window.__hubZoomProbe='done').catch(()=>window.__hubZoomProbe='failed');}return {ready:ready&&window.__hubZoomProbe==='done',context_menu:!!document.getElementById('desktopContextMenu'),pixel_ratio:window.devicePixelRatio,viewport:[innerWidth,innerHeight],mode:document.getElementById('runtimeMode')?.textContent,wizard:document.getElementById('setupTitle')?.textContent,error:document.getElementById('loginError')?.textContent};})()"
                if snap_test:expression=expression.replace("&&document.getElementById('setupWizard').hidden",'')
                if popup_test:
                    from .native_popups import POPUP_PROBE
                    expression=POPUP_PROBE
                cb=handler([HRESULT,W.LPCWSTR],script_result)
                call(state['core'],29,HRESULT,[W.LPCWSTR,PTR],expression,cb)
            return 0
        if msg == 0x10:
            if state.get('previous_cursor'):
                saved=state.pop('previous_cursor');user.SetCursorPos(saved.x,saved.y)
            if not smoke and not recovery_test and not state.get('explicit_exit') and not state.get('error'):
                if state.get('tray') and state['tray'].active:
                    user.ShowWindow(window,0);return 0
                # If tray creation failed, keep a visible taskbar recovery path.
                user.ShowWindow(window,6);return 0
            user.KillTimer(window,1)
            if state.get('popups'):state['popups'].close_all()
            if state['controller']:
                call(state['controller'],24,HRESULT,[]);call(state['controller'],2,W.ULONG,[]);state['controller']=None
            if state['core']:call(state['core'],2,W.ULONG,[]);state['core']=None
            user.DestroyWindow(window);return 0
        if msg == 2:
            user.PostQuitMessage(0);return 0
        result=user.DefWindowProcW(window,msg,wp,lp)
        if caption and msg in (0xF,0x85):caption.clear_surface()
        return result
    proc = WNDPROC(wndproc);keep.append(proc)
    class WNDCLASS(C.Structure):
        _fields_=[('style',W.UINT),('lpfnWndProc',WNDPROC),('cbClsExtra',C.c_int),('cbWndExtra',C.c_int),('hInstance',W.HINSTANCE),('hIcon',W.HICON),('hCursor',W.HANDLE),('hbrBackground',W.HBRUSH),('lpszMenuName',W.LPCWSTR),('lpszClassName',W.LPCWSTR)]
    name='AgentMessageHubNative'+str(os.getpid())
    wc=WNDCLASS();wc.lpfnWndProc=proc;wc.hInstance=kernel.GetModuleHandleW(None);wc.lpszClassName=name
    user.LoadImageW.argtypes=[W.HINSTANCE,W.LPCWSTR,W.UINT,C.c_int,C.c_int,W.UINT];user.LoadImageW.restype=W.HANDLE
    icon_path=Path(__file__).parent/'app.ico'
    if icon_path.exists():wc.hIcon=user.LoadImageW(None,str(icon_path),1,32,32,0x10)
    if not user.RegisterClassW(C.byref(wc)):raise C.WinError()
    # Do not apply the DPI ratio to WebView zoom: WebView2 rasterization already
    # follows its PMv2-aware parent. User zoom is an independent setting.
    area=W.RECT()
    if not user.SystemParametersInfoW(0x0030,0,C.byref(area),0):
        raise C.WinError()
    try: dpi=int(user.GetDpiForSystem())
    except AttributeError: dpi=96
    x,y,width,height=initial_geometry(dpi,(area.left,area.top,area.right,area.bottom))
    hwnd=user.CreateWindowExW(0,name,'Agent Hub',0x00CF0000,x,y,width,height,None,None,wc.hInstance,None)
    if not hwnd:raise C.WinError()
    # Retain the standard caption capability for DWM/Snap, but use the entire
    # frame as client content. Force NCCALCSIZE now, before the first show.
    user.GetWindowLongW.argtypes=[W.HWND,C.c_int];user.GetWindowLongW.restype=C.c_long
    user.SetWindowLongW.argtypes=[W.HWND,C.c_int,C.c_long];user.SetWindowLongW.restype=C.c_long
    user.SetWindowLongW(hwnd,-16,user.GetWindowLongW(hwnd,-16)|0x00C00000)
    user.SetWindowPos(hwnd,None,0,0,0,0,0x0037)
    state['backdrop']=enable_native_frame(hwnd)
    state['mica']=state['backdrop']=='mica'
    from .native_caption import NativeCaption
    state['caption']=NativeCaption(user,hwnd,backdrop=bool(state.get('backdrop')))
    state['caption'].clear_surface()
    user.GetSystemMenu.argtypes=[W.HWND,W.BOOL];user.GetSystemMenu.restype=W.HMENU
    user.AppendMenuW.argtypes=[W.HMENU,W.UINT,W.WPARAM,W.LPCWSTR]
    user.AppendMenuW(user.GetSystemMenu(hwnd,False),0,0x1f10,'恢复工作台界面（F5）')
    user.AppendMenuW(user.GetSystemMenu(hwnd,False),0,0x1f20,'退出应用…')
    if not smoke and not recovery_test:
        from .tray import Tray
        from .tray_status import StatusCache
        state['tray_status']=StatusCache(data_directory) if data_directory else None
        def select_project(project):
            if state['core']:call(state['core'],29,HRESULT,[W.LPCWSTR,PTR],'window.HubDesktop?.chooseProject('+json.dumps(project)+')',None)
        state['tray']=Tray(hwnd,wc.hIcon,state['tray_status'],select_project)
    _ACTIVE_WINDOW=hwnd
    dark_mode_active = is_system_dark_mode()
    set_immersive_dark_mode(hwnd, dark_mode_active)
    state['initial_geometry']=[x,y,width,height]
    state['system_dpi']=dpi
    state['immersive_dark_mode']=dark_mode_active
    user.ShowWindow(hwnd,5)
    # The first call obeys STARTUPINFO (including a hidden launcher). The next
    # call explicitly presents this interactive app, independent of that flag.
    user.ShowWindow(hwnd,5)
    user.IsWindowVisible.argtypes=[W.HWND];user.IsWindowVisible.restype=W.BOOL
    state['window_visible_after_show']=bool(user.IsWindowVisible(hwnd))
    user.SetWindowTextW.argtypes=[W.HWND,W.LPCWSTR]

    def accelerated(_sender,args):
        event_kind=C.c_int();call(args,3,HRESULT,[C.POINTER(C.c_int)],C.byref(event_kind))
        if event_kind.value not in (0,2):return
        key=W.UINT();call(args,4,HRESULT,[C.POINTER(W.UINT)],C.byref(key))
        ctrl=user.GetKeyState(0x11)&0x8000
        if key.value==0x74 or (ctrl and key.value==ord('R')):
            call(args,8,HRESULT,[W.BOOL],True);user.PostMessageW(hwnd,0x8009,0,1);return
        if key.value==0x7b or (ctrl and key.value in (ord('L'),ord('I'),ord('J'),ord('U'))):
            call(args,8,HRESULT,[W.BOOL],True)

    def window_message(_sender,args):
        # Accept chrome commands only from this main same-origin document.
        from urllib.parse import urlsplit
        def string(slot):
            value=PTR();check(call(args,slot,HRESULT,[C.POINTER(PTR)],C.byref(value)))
            try:return C.wstring_at(value) if value else ''
            finally:ole.CoTaskMemFree(value)
        source=urlsplit(string(3));own=urlsplit(url)
        if (source.scheme,source.netloc,source.path)!=(own.scheme,own.netloc,own.path):return
        try:message=json.loads(string(4))
        except ValueError:return
        if not isinstance(message,dict) or message.get('type')!='hub-window':return
        command=message.get('command')
        if command=='caption-geometry':
            import math
            rect=message.get('rect');scale=message.get('scale')
            if isinstance(rect,list) and len(rect)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in rect) and type(scale) in (int,float) and math.isfinite(scale) and scale>0:
                state['caption'].geometry([round(v*scale) for v in rect],scale)
                state['maximize_rect']=state['caption'].maximize_rect
                if state['caption'].rect:
                    native_width=(state['caption'].rect[2]-state['caption'].rect[0])/scale
                    call(state['core'],32,HRESULT,[W.LPCWSTR],json.dumps({'type':'hub-native-caption','width':native_width}))
        elif command=='minimize':user.ShowWindow(hwnd,6)
        elif command=='maximize':user.ShowWindow(hwnd,9 if user.IsZoomed(hwnd) else 3)
        elif command=='close':user.PostMessageW(hwnd,0x10,0,0)
        elif command=='drag':user.ReleaseCapture();user.PostMessageW(hwnd,0xA1,2,0)
        elif command=='language' and message.get('language') in ('en','zh-CN') and data_directory:
            from .ui_preferences import save_language
            save_language(data_directory,message['language'])
            if state.get('tray'):state['tray'].set_language(message['language'])
        elif isinstance(command,str) and command.startswith('resize:'):
            side={'left':10,'right':11,'top':12,'topleft':13,'topright':14,'bottom':15,'bottomleft':16,'bottomright':17}.get(command[7:])
            if side and not user.IsZoomed(hwnd):user.ReleaseCapture();user.PostMessageW(hwnd,0xA1,side,0)

    def created_controller(hr,controller):
        check(hr);call(controller,1,W.ULONG,[]);state['controller']=controller
        from .native_backdrop import windows_build
        if windows_build()>=17763:
            # Controller2's transparent background exposes the host DWM material.
            iid=(C.c_ubyte*16).from_buffer_copy(uuid.UUID('c979903e-d4ca-4228-92eb-47ee3fa96eab').bytes_le)
            controller2=PTR()
            if call(controller,0,HRESULT,[PTR,C.POINTER(PTR)],C.byref(iid),C.byref(controller2))>=0:
                class COLOR(C.Structure):_fields_=[('A',C.c_ubyte),('R',C.c_ubyte),('G',C.c_ubyte),('B',C.c_ubyte)]
                try:
                    check(call(controller2,27,HRESULT,[COLOR],COLOR(0,0,0,0)))
                    color=COLOR();check(call(controller2,26,HRESULT,[C.POINTER(COLOR)],C.byref(color)))
                    state['webview_transparent']=color.A==0
                finally:call(controller2,2,W.ULONG,[])
        core=PTR();check(call(controller,25,HRESULT,[C.POINTER(PTR)],C.byref(core)));state['core']=core
        settings=PTR();check(call(core,3,HRESULT,[C.POINTER(PTR)],C.byref(settings)))
        # Native edit menus and browser page zoom remain available; the frontend
        # replaces non-editing menus with workbench actions.
        for slot in (10,12,16):check(call(settings,slot,HRESULT,[W.BOOL],False))
        for slot in (14,18):check(call(settings,slot,HRESULT,[W.BOOL],True))
        features={}
        for slot,label in [(9,'status_bar'),(11,'devtools'),(13,'context_menus'),(15,'host_objects'),(17,'zoom_ui')]:
            flag=W.BOOL();check(call(settings,slot,HRESULT,[C.POINTER(W.BOOL)],C.byref(flag)));features[label]=bool(flag.value)
        # Official ICoreWebView2Settings4: general form suggestions and
        # password-save prompts are separate controls. Never clear saved data.
        iid=(C.c_ubyte*16).from_buffer_copy(uuid.UUID('cb56846c-4168-4d53-b04f-03b6d6796ff2').bytes_le)
        settings4=PTR()
        if call(settings,0,HRESULT,[PTR,C.POINTER(PTR)],C.byref(iid),C.byref(settings4))>=0:
            try:
                for put_slot,get_slot,label in [(26,25,'password_autosave'),(28,27,'general_autofill')]:
                    check(call(settings4,put_slot,HRESULT,[W.BOOL],False))
                    flag=W.BOOL();check(call(settings4,get_slot,HRESULT,[C.POINTER(W.BOOL)],C.byref(flag)));features[label]=bool(flag.value)
            finally:call(settings4,2,W.ULONG,[])
        state['browser_features']=features
        call(settings,2,W.ULONG,[])
        token=C.c_longlong();accelerator=state['accelerator_callback']
        check(call(controller,19,HRESULT,[PTR,C.POINTER(C.c_longlong)],accelerator,C.byref(token)))
        failed_token=C.c_longlong();check(call(core,25,HRESULT,[PTR,C.POINTER(C.c_longlong)],state['failed_callback'],C.byref(failed_token)))
        if not state.get('popups'):
            from .native_popups import NativePopups
            state['popups']=NativePopups(user,kernel,ole,call,check,handler,state['environment'],hwnd,url,wc.hInstance,wc.hIcon,lambda w:set_immersive_dark_mode(w,state.get('dark_mode',is_system_dark_mode())),log_ui,lambda:state['zoom_percent']/100)
        state['popups'].bind(core)
        message_token=C.c_longlong();check(call(core,34,HRESULT,[PTR,C.POINTER(C.c_longlong)],state['window_message_callback'],C.byref(message_token)))
        # Install the desktop capability before any page script; browser-only
        # visits retain the existing HTML dialog fallback.
        script_ready=handler([HRESULT,W.LPCWSTR],lambda hr,_:check(call(core,5,HRESULT,[W.LPCWSTR],url)) if hr>=0 else check(hr))
        check(call(core,27,HRESULT,[W.LPCWSTR,PTR],'window.__HUB_NATIVE_WINDOWS__=true;window.__HUB_NATIVE_BACKDROP__='+json.dumps(state.get('backdrop') if state.get('webview_transparent') else None)+';window.__HUB_NATIVE_MICA__='+str(bool(state.get('mica') and state.get('webview_transparent'))).lower()+';',script_ready))
        state['ui_grace']=time.monotonic()+(1 if recovery_test else 20)
        resize();check(call(controller,4,HRESULT,[W.BOOL],True))

    def created_environment(hr,environment):
        check(hr);call(environment,1,W.ULONG,[]);state['environment']=environment
        check(call(environment,3,HRESULT,[W.HWND,PTR],hwnd,state['controller_callback']))

    state['window_message_callback']=handler([PTR,PTR],window_message)
    state['accelerator_callback']=handler([PTR,PTR],accelerated)
    state['controller_callback']=handler([HRESULT,PTR],created_controller)
    state['health_callback']=handler([HRESULT,W.LPCWSTR],ui_health_result)
    state['failed_callback']=handler([PTR,PTR],process_failed)
    lib=C.WinDLL(loader)
    create=lib.CreateCoreWebView2EnvironmentWithOptions
    create.restype=HRESULT;create.argtypes=[W.LPCWSTR,W.LPCWSTR,PTR,PTR]
    try:
        check(create(None,str(profile),None,handler([HRESULT,PTR],created_environment)))
        user.SetTimer(hwnd,1,1000 if smoke or recovery_test else 10000,None)
        msg=W.MSG()
        while user.GetMessageW(C.byref(msg),None,0,0)>0:
            user.TranslateMessage(C.byref(msg));user.DispatchMessageW(C.byref(msg))
        if state['error']:raise RuntimeError(state['error'])
        if recovery_test and not state.get('recovery_pass'):raise RuntimeError('Native recovery probe did not pass')
        if smoke and not state['smoke_pass']:raise RuntimeError('Native window closed before verification')
        return {'backdrop':state.get('backdrop'),'mica':bool(state.get('mica')),'webview_transparent':state.get('webview_transparent'),'caption_right_gap':state.get('caption_right_gap'),'snap_probe_interrupted':state.get('snap_probe_interrupted'),'snap_flyout_visible':state.get('snap_flyout_visible'),'native_close_hit':state.get('native_close_hit'),'native_snap_hit':state.get('native_snap_hit'),'rounded_corner_preference':state.get('rounded_corner_preference'),'custom_chrome':state.get('custom_chrome'),'popup_modal_verified':state.get('popup_modal_verified'),'popup_modeless_verified':state.get('popup_modeless_verified'),'popup_counts':state.get('popup_counts'),'recovery_pass':state.get('recovery_pass',False),'ui_recoveries':len(recovery.attempts),'engine':'win32-webview2','native_window':True,'window_visible_after_show':state['window_visible_after_show'],'window_class':name,'browser_features':state.get('browser_features'),'dpi_awareness':dpi_awareness,'system_dpi':state['system_dpi'],'initial_geometry':state['initial_geometry'],'dpi_changes':state['dpi_changes'],'zoom_percent':state['zoom_percent'],'actual_zoom_factor':state.get('actual_zoom_factor'),'synthetic_dpi_rect_applied':state.get('synthetic_dpi_rect_applied'),'window_dpi':state.get('window_dpi'),'immersive_dark_mode':state.get('immersive_dark_mode'),'smoke':state['smoke_pass'],'verification':state.get('verification')}
    finally:
        if state.get('popups'):state['popups'].dispose()
        if state.get('tray'):state['tray'].close()
        if state.get('tray_status'):state['tray_status'].close()
        _ACTIVE_WINDOW=None
        user.KillTimer(hwnd,1)
        if state.get('environment'):call(state['environment'],2,W.ULONG,[])
        if state['controller']:call(state['controller'],24,HRESULT,[])
        user.UnregisterClassW.argtypes=[W.LPCWSTR,W.HINSTANCE]
        user.UnregisterClassW(name,wc.hInstance)
        ole.CoUninitialize()
