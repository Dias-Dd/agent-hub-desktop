"""Version-aware native materials. No timers or software blur rendering."""
import ctypes as C
from ctypes import wintypes as W
import sys


class AccentPolicy(C.Structure):
    _fields_=[('state',C.c_int),('flags',C.c_int),('color',W.DWORD),('animation',C.c_int)]


class CompositionData(C.Structure):
    _fields_=[('attribute',C.c_int),('data',C.c_void_p),('size',C.c_size_t)]


class VersionInfo(C.Structure):
    _fields_=[('size',W.DWORD),('major',W.DWORD),('minor',W.DWORD),('build',W.DWORD),('platform',W.DWORD),('service_pack',W.WCHAR*128)]


def windows_build(ntdll=None):
    # Version helpers can report Windows 8 for a frozen EXE without OS metadata.
    try:
        version=VersionInfo();version.size=C.sizeof(version)
        getter=(ntdll or C.windll.ntdll).RtlGetVersion
        getter.argtypes=[C.POINTER(VersionInfo)];getter.restype=C.c_long
        if getter(C.byref(version))==0:return int(version.build)
    except (AttributeError,OSError):pass
    return sys.getwindowsversion().platform_version[2]


def transparency_allowed(user):
    class HighContrast(C.Structure):
        _fields_=[('size',W.UINT),('flags',W.DWORD),('scheme',W.LPWSTR)]
    contrast=HighContrast();contrast.size=C.sizeof(contrast)
    try:
        if user.SystemParametersInfoW(0x42,C.sizeof(contrast),C.byref(contrast),0) and contrast.flags&1:return False
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return bool(winreg.QueryValueEx(key,'EnableTransparency')[0])
    except (OSError,AttributeError):return True


def apply(hwnd,dark=False,*,build=None,user=None,dwm=None,allowed=None):
    user=user or C.windll.user32;dwm=dwm or C.windll.dwmapi
    build=windows_build() if build is None else build
    allowed=transparency_allowed(user) if allowed is None else allowed
    dwm.DwmSetWindowAttribute.argtypes=[W.HWND,W.DWORD,C.c_void_p,W.DWORD]
    if build>=22000:
        value=C.c_int(2 if allowed else 1)
        attribute=38 if build>=22621 else 1029
        if attribute==1029:value=C.c_int(1 if allowed else 0)
        if dwm.DwmSetWindowAttribute(hwnd,attribute,C.byref(value),C.sizeof(value))>=0:
            return 'mica' if allowed else None
    if build>=17763:
        try:
            setter=user.SetWindowCompositionAttribute
            setter.argtypes=[W.HWND,C.POINTER(CompositionData)];setter.restype=W.BOOL
            # ACCENT_ENABLE_ACRYLICBLURBEHIND; color is AABBGGRR.
            accent=AccentPolicy(4 if allowed else 0,2,0xD91E1F1C if dark else 0xD9F0F4F8,0)
            data=CompositionData(19,C.cast(C.pointer(accent),C.c_void_p),C.sizeof(accent))
            if setter(hwnd,C.byref(data)):return 'acrylic' if allowed else None
        except (AttributeError,OSError):pass
    return None
