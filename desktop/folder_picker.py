"""Windows Explorer folder picker through the public IFileOpenDialog API."""
import ctypes as C
from contextlib import contextmanager
from pathlib import Path
import sys,uuid

class GUID(C.Structure):
    _fields_=[('a',C.c_uint32),('b',C.c_uint16),('c',C.c_uint16),('d',C.c_ubyte*8)]
    @classmethod
    def parse(cls,value):return cls.from_buffer_copy(uuid.UUID(value).bytes_le)

CLSID=GUID.parse('dc1c5a9c-e88a-4dde-a5a1-60f82a20aef7')
IID=GUID.parse('d57c7288-d4ad-4768-be02-9d969532d960')
SHELL_ITEM=GUID.parse('43826d1e-e718-42ee-bc55-a1e261c37bfe')
OPTIONS=0x20|0x40|0x800|0x8|0x02000000

def call(pointer,index,types=(),*args):
    address=C.cast(pointer,C.POINTER(C.POINTER(C.c_void_p))).contents[index]
    return C.WINFUNCTYPE(C.c_long,C.c_void_p,*types)(address)(pointer,*args)

def checked(hr):
    if hr<0:raise OSError('Windows folder dialog error 0x%08X'%(hr&0xffffffff))

@contextmanager
def explorer_dialog(initial=''):
    if sys.platform!='win32':raise OSError('此环境不支持 Windows 资源管理器目录窗口')
    ole=C.OleDLL('ole32');shell=C.WinDLL('shell32');ole.CoInitializeEx.argtypes=[C.c_void_p,C.c_uint32];ole.CoInitializeEx.restype=C.c_long
    checked(ole.CoInitializeEx(None,2));pointer=C.c_void_p()
    try:
        ole.CoCreateInstance.argtypes=[C.POINTER(GUID),C.c_void_p,C.c_uint32,C.POINTER(GUID),C.POINTER(C.c_void_p)];ole.CoCreateInstance.restype=C.c_long
        checked(ole.CoCreateInstance(C.byref(CLSID),None,1,C.byref(IID),C.byref(pointer)))
        checked(call(pointer,9,(C.c_uint32,),OPTIONS));checked(call(pointer,17,(C.c_wchar_p,),'选择项目工作目录'));checked(call(pointer,18,(C.c_wchar_p,),'选择此文件夹'))
        if initial and Path(initial).is_absolute() and Path(initial).is_dir():
            folder=C.c_void_p();shell.SHCreateItemFromParsingName.argtypes=[C.c_wchar_p,C.c_void_p,C.POINTER(GUID),C.POINTER(C.c_void_p)];shell.SHCreateItemFromParsingName.restype=C.c_long
            if shell.SHCreateItemFromParsingName(str(Path(initial).resolve()),None,C.byref(SHELL_ITEM),C.byref(folder))>=0:
                try:checked(call(pointer,12,(C.c_void_p,),folder))
                finally:call(folder,2)
        yield pointer,ole
    finally:
        if pointer:call(pointer,2)
        ole.CoUninitialize()

def pick_directory(initial=''):
    if sys.platform=='darwin':
        import threading
        from PyObjCTools import AppHelper
        import AppKit as A
        import Foundation as F
        ready=threading.Event();result={}
        def show():
            try:
                panel=A.NSOpenPanel.openPanel()
                panel.setCanChooseDirectories_(True);panel.setCanChooseFiles_(False)
                panel.setAllowsMultipleSelection_(False)
                if initial and Path(initial).is_dir():panel.setDirectoryURL_(F.NSURL.fileURLWithPath_(str(Path(initial).resolve())))
                if panel.runModal()==A.NSModalResponseOK:result['path']=str(panel.URL().path())
            except Exception as error:result['error']=str(error)
            finally:ready.set()
        if threading.current_thread() is threading.main_thread():show()
        else:
            if A.NSApp() is None:raise OSError('macOS folder picker requires the running Cocoa host')
            AppHelper.callAfter(show)
            ready.wait()
        if result.get('error'):raise OSError(result['error'])
        return result.get('path')
    with explorer_dialog(initial) as (dialog,ole):
        user=C.WinDLL('user32');user.GetForegroundWindow.restype=C.c_void_p
        hr=call(dialog,3,(C.c_void_p,),user.GetForegroundWindow())
        if (hr&0xffffffff)==0x800704c7:return None
        checked(hr);item=C.c_void_p();checked(call(dialog,20,(C.POINTER(C.c_void_p),),C.byref(item)))
        display=C.c_void_p()
        try:
            checked(call(item,5,(C.c_uint32,C.POINTER(C.c_void_p)),0x80058000,C.byref(display)))
            return C.wstring_at(display)
        finally:
            if display:
                ole.CoTaskMemFree.argtypes=[C.c_void_p];ole.CoTaskMemFree(display)
            call(item,2)
