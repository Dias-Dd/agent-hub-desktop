"""Windows notification icon: hide UI without ending the owned service."""
import ctypes as C
from ctypes import wintypes as W
class Tray:
 MESSAGE=0x8012
 def __init__(self,window,icon,status=None,select_project=None):
  import queue
  self.status=status;self.select_project=select_project;self.notification_fallback=queue.SimpleQueue()
  from .ui_preferences import language
  self.language=language(status.directory) if status else 'zh-CN';self.notification_project=None
  self.window=window;self.user=C.windll.user32;self.shell=C.windll.shell32
  class Data(C.Structure):
   _fields_=[('cbSize',W.DWORD),('hWnd',W.HWND),('uID',W.UINT),('uFlags',W.UINT),('uCallbackMessage',W.UINT),('hIcon',W.HICON),('szTip',W.WCHAR*128),('dwState',W.DWORD),('dwStateMask',W.DWORD),('szInfo',W.WCHAR*256),('uTimeoutOrVersion',W.UINT),('szInfoTitle',W.WCHAR*64),('dwInfoFlags',W.DWORD),('guidItem',C.c_byte*16),('hBalloonIcon',W.HICON)]
  self.data=Data();self.data.cbSize=C.sizeof(Data);self.data.hWnd=window;self.data.uID=1;self.data.uFlags=7;self.data.uCallbackMessage=self.MESSAGE;self.data.hIcon=icon;self.data.szTip='Deskfellows · 后台运行，双击打开'
  self.shell.Shell_NotifyIconW.argtypes=[W.DWORD,C.POINTER(Data)]
  self.active=bool(self.shell.Shell_NotifyIconW(0,C.byref(self.data)))
  self.set_language(self.language)
 def set_language(self,value):
  self.language=value;self.data.szTip='Deskfellows · Running in background; double-click to open' if value=='en' else 'Deskfellows · 后台运行，双击打开'
  if self.active:
   self.data.uFlags=4;self.shell.Shell_NotifyIconW(1,C.byref(self.data));self.data.uFlags=7
 def close(self):
  if self.active:self.shell.Shell_NotifyIconW(2,C.byref(self.data));self.active=False
 def notify_pending(self):
  if not self.active or not self.status:return
  import queue
  fallback=False
  try:event=self.notification_fallback.get_nowait();fallback=True
  except queue.Empty:
   try:event=self.status.notifications.get_nowait()
   except queue.Empty:return
  from hub.notification_settings import allowed,wording
  import os
  self.user.GetForegroundWindow.restype=W.HWND
  self.user.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
  foreground_pid=W.DWORD();self.user.GetWindowThreadProcessId(self.user.GetForegroundWindow(),C.byref(foreground_pid))
  if not allowed(self.status.value.get('notification_settings',{}),event,foreground_pid.value==os.getpid()):return
  english=self.language=='en';demo=event['kind']=='demo'
  self.data.szInfoTitle=wording(event['kind'],english)
  description=('Open Deskfellows to review the demo.' if demo else 'Open Deskfellows to view the delivery.') if english else ('打开工作台审阅演示并确认设计。' if demo else '打开工作台查看交付结果。')
  if event['kind']=='attention':description='Open Deskfellows to inspect the project.' if english else '打开工作台查看需要处理的问题。'
  if event['kind']=='test':description='System notifications are working.' if english else '系统通知已成功送达。'
  message=(event.get('name','')+'\n'+description).strip()
  if not fallback:
   import threading
   title=self.data.szInfoTitle
   def deliver():
    try:
     from .system_notifications import send
     send(title,message)
     from hub.notification_settings import record_delivery
     record_delivery(self.status.directory,event,True,channel='windows')
    except Exception:self.notification_fallback.put(event)
   threading.Thread(target=deliver,daemon=True,name='hub-completion-notification').start()
   return
  self.data.szInfo=message[:255];self.data.dwInfoFlags=1;self.data.uFlags=0x10
  submitted=bool(self.shell.Shell_NotifyIconW(1,C.byref(self.data)));self.data.uFlags=7;self.notification_project=event.get('project')
  from hub.notification_settings import record_delivery
  record_delivery(self.status.directory,event,submitted,None if submitted else 'Windows 托盘通知提交失败',channel='windows-tray')
 def handle(self,event):
  if event==0x405:
   self.user.ShowWindow(self.window,9);self.user.SetForegroundWindow(self.window)
   if self.notification_project and self.select_project:self.select_project(self.notification_project)
   return
  if event in (0x202,0x203):self.user.ShowWindow(self.window,9);self.user.SetForegroundWindow(self.window)
  elif event==0x205:
   self.user.CreatePopupMenu.restype=W.HMENU;self.user.AppendMenuW.argtypes=[W.HMENU,W.UINT,W.WPARAM,W.LPCWSTR]
   menu=self.user.CreatePopupMenu();self.user.AppendMenuW(menu,0,1,'Open workspace' if self.language=='en' else '打开工作台');projects={}
   from .tray_status import menu_rows
   rows=menu_rows(self.status.value if self.status else {})
   for kind,label,project in rows:
    if self.language=='en':
     mapping={'进行中的项目':'Active projects','暂无进行中的项目':'No active projects','Agent 状态':'Agent status','正在加载 Agent 状态':'Loading Agent status','状态暂未更新，保留上次记录':'Status unavailable; showing last reading','进行中':'In progress','暂停':'Paused','等待处理':'Waiting','待核查':'Needs review','待经理汇报':'Awaiting manager report'}
     label=mapping.get(label,label)
     for source,target in mapping.items():
      if ' · '+source in label:label=label.replace(' · '+source,' · '+target)
    if kind=='header':self.user.AppendMenuW(menu,0x800,0,None)
    key=100+len(projects) if kind=='project' else 0
    if project:projects[key]=project
    self.user.AppendMenuW(menu,0 if project else 0x2,key,label.replace('&','&&'))
   self.user.AppendMenuW(menu,0x800,0,None);self.user.AppendMenuW(menu,0,2,'Quit application…' if self.language=='en' else '退出应用…')
   self.user.TrackPopupMenu.argtypes=[W.HMENU,W.UINT,C.c_int,C.c_int,C.c_int,W.HWND,C.c_void_p]
   point=W.POINT();self.user.GetCursorPos(C.byref(point));self.user.SetForegroundWindow(self.window)
   choice=self.user.TrackPopupMenu(menu,0x100|2,point.x,point.y,0,self.window,None)
   self.user.DestroyMenu.argtypes=[W.HMENU];self.user.DestroyMenu(menu)
   if choice==1:self.user.ShowWindow(self.window,9);self.user.SetForegroundWindow(self.window)
   if choice in projects:
    self.user.ShowWindow(self.window,9);self.user.SetForegroundWindow(self.window)
    if self.select_project:self.select_project(projects[choice])
   if choice==2:self.user.PostMessageW(self.window,0x8013,0,0)
