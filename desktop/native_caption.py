"""Hybrid DWM title bar: native caption buttons, WebView toolbar content."""
import ctypes as C
from ctypes import wintypes as W

class NativeCaption:
    def __init__(self,user,hwnd,backdrop=False):
        self.user=user;self.hwnd=hwnd;self.backdrop=backdrop;self.rect=None;self.maximize_rect=None;self.close_rect=None;self.last_geometry=None;self.frame_margins=None
        self.gdi=C.windll.gdi32;self.dwm=C.windll.dwmapi
        user.EnumChildWindows.argtypes=[W.HWND,C.c_void_p,W.LPARAM]
        user.GetParent.argtypes=[W.HWND];user.GetParent.restype=W.HWND
        user.InvalidateRect.argtypes=[W.HWND,C.POINTER(W.RECT),W.BOOL]
        user.SetWindowRgn.argtypes=[W.HWND,W.HANDLE,W.BOOL]
        self.dwm.DwmGetWindowAttribute.argtypes=[W.HWND,W.DWORD,C.c_void_p,W.DWORD]
        self.dwm.DwmExtendFrameIntoClientArea.argtypes=[W.HWND,C.c_void_p]
        self.gdi.CreateRectRgn.argtypes=[C.c_int]*4;self.gdi.CreateRectRgn.restype=W.HANDLE
        self.gdi.CombineRgn.argtypes=[W.HANDLE,W.HANDLE,W.HANDLE,C.c_int]
        self.gdi.DeleteObject.argtypes=[W.HANDLE]
    def invalidate(self):
        if self.rect:self.user.InvalidateRect(self.hwnd,C.byref(W.RECT(*self.rect)),False)
    def geometry(self,rect,scale,colors=None):
        self.last_geometry=(list(rect),scale)
        bounds=W.RECT()
        if self.dwm.DwmGetWindowAttribute(self.hwnd,5,C.byref(bounds),C.sizeof(bounds))<0:return
        if bounds.right<=bounds.left:return
        outer=W.RECT();self.user.GetWindowRect(self.hwnd,C.byref(outer))
        origin=W.POINT(0,0);self.user.ClientToScreen(self.hwnd,C.byref(origin))
        dx=outer.left-origin.x;dy=outer.top-origin.y
        left,top,right,bottom=bounds.left+dx,bounds.top+dy,bounds.right+dx,bounds.bottom+dy
        width=right-left
        self.maximize_rect=[round(left+width/3),top,round(right-width/3),bottom]
        self.close_rect=[round(right-width/3),top,right,bottom]
        # DWM owns the entire button cluster; use its measured bounds unchanged.
        self.rect=[left,top,right,bottom]
        class MARGINS(C.Structure):_fields_=[('left',C.c_int),('right',C.c_int),('top',C.c_int),('bottom',C.c_int)]
        backdrop=C.c_int();mica=self.dwm.DwmGetWindowAttribute(self.hwnd,38,C.byref(backdrop),C.sizeof(backdrop))>=0 and backdrop.value==2
        margins=MARGINS(-1,-1,-1,-1) if (mica or self.backdrop) else MARGINS(1,1,max(bounds.bottom,rect[3]),1)
        value=(margins.left,margins.right,margins.top,margins.bottom)
        if value!=self.frame_margins:
            self.dwm.DwmExtendFrameIntoClientArea(self.hwnd,C.byref(margins));self.frame_margins=value
        self.clip_webview();self.invalidate();self.clear_surface()
    def clear_surface(self):
        # DWM draws the real caption underneath the client surface. Glass needs
        # zero alpha here; do not paint glyphs, hover colors or a fake edge.
        theme=C.windll.uxtheme
        theme.BufferedPaintInit()
        self.user.GetDC.argtypes=[W.HWND];self.user.GetDC.restype=W.HDC
        self.user.ReleaseDC.argtypes=[W.HWND,W.HDC]
        theme.BeginBufferedPaint.argtypes=[W.HDC,C.POINTER(W.RECT),C.c_int,C.c_void_p,C.POINTER(W.HDC)];theme.BeginBufferedPaint.restype=W.HANDLE
        theme.BufferedPaintClear.argtypes=[W.HANDLE,C.c_void_p]
        theme.EndBufferedPaint.argtypes=[W.HANDLE,W.BOOL]
        dc=self.user.GetDC(self.hwnd);memory=W.HDC();rect=W.RECT();self.user.GetClientRect(self.hwnd,C.byref(rect))
        buffer=theme.BeginBufferedPaint(dc,C.byref(rect),2,None,C.byref(memory))
        try:
            if buffer:
                theme.BufferedPaintClear(buffer,None)
                theme.EndBufferedPaint(buffer,True)
        finally:self.user.ReleaseDC(self.hwnd,dc);theme.BufferedPaintUnInit()
    def clip_webview(self):
        if not self.rect:return
        @C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        def visit(child,unused):
            if self.user.GetParent(child)!=self.hwnd:return True
            bounds=W.RECT();self.user.GetWindowRect(child,C.byref(bounds))
            origin=W.POINT(0,0);self.user.ClientToScreen(self.hwnd,C.byref(origin))
            left,top,right,bottom=self.rect
            dx=origin.x-bounds.left;dy=origin.y-bounds.top
            region=self.gdi.CreateRectRgn(0,0,bounds.right-bounds.left,bounds.bottom-bounds.top)
            hole=self.gdi.CreateRectRgn(left+dx,top+dy,right+dx,bottom+dy)
            self.gdi.CombineRgn(region,region,hole,4);self.gdi.DeleteObject(hole)
            if not self.user.SetWindowRgn(child,region,True):self.gdi.DeleteObject(region)
            return True
        self.user.EnumChildWindows(self.hwnd,visit,0)
