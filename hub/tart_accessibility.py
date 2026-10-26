"""Project-scoped adapter for Peekaboo's generation-bound AX snapshots."""
import hashlib
import json
import re
import time
import uuid
from .core import HubError
from .peekaboo_guest import PeekabooGuest

class TartAccessibility:
 def ax_identity(self,name):
  return hashlib.sha256((self.environment()['TART_HOME']+'\0'+name).encode()).hexdigest()
 def ax_directory(self):
  path=self.root/'peekaboo-receipts';path.mkdir(exist_ok=True);return path
 def ax_state(self,name):
  try:
   data=json.loads((self.root/'peekaboo-status.json').read_text())
   if data.get('vm_identity')==self.ax_identity(name):return data
  except (OSError,ValueError):pass
  return {'ready':False,'provider':'peekaboo','note':'请在虚拟机设置中安装并授权 Peekaboo 控件驱动'}
 def ax_probe(self,name):
  try:data=PeekabooGuest(self,name).permissions()
  except Exception as error:data={'ready':False,'provider':'peekaboo','error':str(error)}
  data={**data,'vm_identity':self.ax_identity(name),'checked_at':time.time()}
  self.write(self.root/'peekaboo-status.json',data);return data
 def ax_control(self,action,vm_name='',confirmed=False):
  name=self.name(vm_name or self.selected().get('vm',''))
  if action=='peekaboo_install':
   if confirmed is not True:raise HubError('请确认在所选访客内安装官方 Peekaboo（约 60 MB）')
   def work():
    result=PeekabooGuest(self,name).install();return {**result,'accessibility':self.ax_probe(name)}
  elif action=='peekaboo_status':work=lambda:{'accessibility':self.ax_probe(name)}
  elif action=='peekaboo_permissions':work=lambda:PeekabooGuest(self,name).open_permissions()
  else:raise HubError('未知控件驱动操作')
  return self.queue({'control':True,'action':action,'vm':name},work)
 def ax_windows_path(self,project,agent):
  return self.ax_directory()/('windows-'+hashlib.sha256((project+'\0'+agent).encode()).hexdigest()+'.json')
 def ax_window(self,project,agent,name,handle):
  if type(handle) is not int or handle<=0:raise HubError('请提供 windows 返回的 window_handle')
  try:record=json.loads(self.ax_windows_path(project,agent).read_text())
  except (OSError,ValueError):raise HubError('请先读取本 Agent 的 windows') from None
  if record['vm_identity']!=self.ax_identity(name) or time.time()-record['created']>120:raise HubError('窗口清单已过期，请重新读取 windows')
  window=record['windows'].get(str(handle))
  if not window:raise HubError('窗口不属于本 Agent 最近读取的清单')
  return window
 def ax_work(self,project,agent,name,action,args):
  with self._desktop_lock:
   self.desktop_lease(project,agent,name)
   provider=PeekabooGuest(self,name)
   if not self.ax_probe(name).get('ready'):raise HubError('访客 Peekaboo 控件通道未就绪，请在设置中检查辅助功能与屏幕录制权限')
   if action=='windows':
    apps=provider.run(['app','list']);rows=[];records={};warnings=[]
    for app in apps.get('apps',[])[:64]:
     pid=app.get('pid');generation=app.get('process_start_identity_decimal')
     if type(pid) is not int or not generation:continue
     try:listing=provider.run(['window','list','--pid',str(pid)])
     except HubError as error:warnings.append({'app':app.get('name'),'error':str(error)});continue
     if listing.get('inventory_completeness')=='partial' or listing.get('inventory_warnings'):
      warnings.append({'app':app.get('name'),'inventory_completeness':listing.get('inventory_completeness'),'warnings':listing.get('inventory_warnings',[])})
     for window in listing.get('windows',[]):
      handle=window.get('window_id')
      if type(handle) is not int or handle<=0:continue
      records[str(handle)]={'pid':pid,'generation':generation,'window':window}
      rows.append({**window,'window_handle':handle,'app':app.get('name'),'pid':pid})
      if len(rows)>=200:break
     if len(rows)>=200:break
    self.write(self.ax_windows_path(project,agent),{'created':time.time(),'vm_identity':self.ax_identity(name),'windows':records})
    return {'windows':rows,'warnings':warnings,'truncated':len(rows)>=200 or len(apps.get('apps',[]))>64,'provider':'peekaboo'}
   handle=args.get('window_handle');window=self.ax_window(project,agent,name,handle)
   if action=='ui_tree':
    # A new observation must not silently adopt a recycled PID/window identity.
    apps=provider.run(['app','list']).get('apps',[])
    if not any(a.get('pid')==window['pid'] and a.get('process_start_identity_decimal')==window['generation'] for a in apps):
     raise HubError('窗口所属进程已变化，请重新读取 windows')
    data=provider.run(['see','--pid',str(window['pid']),'--window-id',str(handle),'--tree','--no-screenshot','--fresh','--max-elements','200','--max-children','50','--depth','12'])
    snapshot=data.get('snapshot_id');elements=data.get('ui_elements',[])
    usable=bool(isinstance(snapshot,str) and re.fullmatch(r'ps1_[a-f0-9]{32}',snapshot) and data.get('snapshot_reusable') is True and data.get('mutation_targeting_available') is True)
    token=uuid.uuid4().hex;controls=[];native={}
    for index,row in enumerate(elements[:200]):
     ident=f'tartax_{token}_{index}'
     native[str(index)]={'id':row.get('id'),'actionable':row.get('is_actionable') is True,'settable':row.get('is_value_settable') is True}
     controls.append({**row,'element_id':ident,'is_actionable':usable and native[str(index)]['actionable'],'is_value_settable':usable and native[str(index)]['settable']})
    self.write(self.ax_directory()/(token+'.json'),{'project':project,'agent':agent,'vm_identity':self.ax_identity(name),'window_handle':handle,'created':time.time(),'snapshot':snapshot,'usable':usable,'elements':native,'consumed':False})
    return {'controls':controls,'window_handle':handle,'provider':'peekaboo','truncated':len(elements)>200 or data.get('truncated',False),'mutation_targeting_available':usable,'semantic_scope':data.get('semantic_scope'),'coordinate_note':'控件 bounds 为访客 macOS 逻辑坐标；优先使用 element_id，不作为 VNC 像素坐标'}
   match=re.fullmatch(r'tartax_([a-f0-9]{32})_([0-9]{1,3})',str(args.get('element_id','')))
   if not match:raise HubError('请使用 ui_tree 返回的 element_id')
   path=self.ax_directory()/(match[1]+'.json')
   try:record=json.loads(path.read_text())
   except (OSError,ValueError):raise HubError('控件快照不存在，请重新读取 ui_tree') from None
   if record['project']!=project or record['agent']!=agent or record['vm_identity']!=self.ax_identity(name) or record['window_handle']!=handle:
    raise HubError('控件快照不属于当前 Agent、项目或虚拟机窗口')
   if record.get('consumed') or not record.get('usable') or time.time()-record['created']>60:
    raise HubError('控件快照已过期或已使用，请重新读取 ui_tree；不会重试输入')
   element=record['elements'].get(match[2])
   if not element or not isinstance(element.get('id'),str):raise HubError('快照中没有此控件')
   if action=='ui_set_value':
    value=args.get('value')
    if not isinstance(value,str) or len(value)>16384:raise HubError('控件文本需要字符串，最多 16384 字符')
    if not element['settable']:raise HubError('此控件未声明可设置 value')
    command=['set-value','--value='+value,'--on',element['id'],'--snapshot',record['snapshot']]
   elif action=='ui_invoke':
    if not element['actionable']:raise HubError('此控件未声明可操作')
    command=['action','AXPress','--on',element['id'],'--snapshot',record['snapshot'],'--foreground','--input-strategy','actionOnly']
   else:raise HubError('未知控件动作')
   # Consume BEFORE dispatch, including uncertain failures. Never replay mutations.
   self.write(path,{**record,'consumed':True})
   outcome=provider.run(command)
   return {'provider':'peekaboo','element_id':args['element_id'],'result':outcome,'requires_fresh_observation':True,'note':'操作结果以 Peekaboo 的 effect/readback 为准；请重新读取控件树核对，不自动重放。'}
