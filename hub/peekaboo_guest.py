"""Pinned, signed Peekaboo installation and JSON transport INSIDE a Tart guest.

No host binary is run; no model/analysis commands or local-runtime fallbacks.
"""
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request
from .core import HubError

VERSION='4.9.7'
TEAM='FWJYW4S8P8'
ASSETS={
 'peekaboo-macos-arm64.tar.gz':'147a81a9b31c1b7b7bd5f720674ad7de71951698138d379679678a9ccfdd0a38',
 'Peekaboo-4.9.7.app.zip':'ad87379580bdc9a2d96a62f1d3db7545b18306f8fcd96d1b50b4eee033959ed0',
}
BASE='https://github.com/openclaw/Peekaboo/releases/download/v'+VERSION+'/'

class PeekabooGuest:
 def __init__(self,bridge,name):self.bridge=bridge;self.name=bridge.name(name)
 def python(self,code,input=None,timeout=45):
  return self.bridge.run('exec',*(['-i'] if input is not None else []),self.name,'python3','-c',code,input=input,timeout=timeout)
 def location(self):
  info=json.loads(self.python("import pathlib,platform,json; print(json.dumps({'home':str(pathlib.Path.home()),'os':platform.system(),'arch':platform.machine(),'version':platform.mac_ver()[0]}))"))
  if info['os']!='Darwin' or info['arch']!='arm64' or int(info['version'].split('.')[0])<15:
   raise HubError('Peekaboo 4.9.7 需要 macOS 15+ ARM64 访客')
  home=info['home'];return home+'/Library/Application Support/AgentHubPeekaboo/'+VERSION, home+'/Library/Application Support/Peekaboo/bridge.sock'
 def install(self):
  root,_=self.location();cache=self.bridge.root/'peekaboo-downloads'/VERSION;cache.mkdir(parents=True,exist_ok=True)
  for filename,digest in ASSETS.items():
   path=cache/filename
   if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
    partial=path.with_suffix('.partial')
    try:
     with urllib.request.urlopen(BASE+filename,timeout=30) as response,partial.open('wb') as stream:
      count=0
      while chunk:=response.read(1048576):
       count+=len(chunk)
       if count>80*1024*1024:raise HubError('Peekaboo 下载超出预期大小')
       stream.write(chunk)
     if hashlib.sha256(partial.read_bytes()).hexdigest()!=digest:raise HubError('Peekaboo 下载校验失败，未安装')
     partial.replace(path)
    finally:partial.unlink(missing_ok=True)
   request={'root':root,'filename':filename,'sha256':digest}
   # Binary stdin avoids subprocess argument limits and supports guest Python 3.9.
   code="import sys,pathlib,hashlib,json; q=json.loads(sys.stdin.buffer.readline()); p=pathlib.Path(q['root'])/q['filename']; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(sys.stdin.buffer.read()); assert hashlib.sha256(p.read_bytes()).hexdigest()==q['sha256']; print('verified')"
   self.python(code,json.dumps(request).encode()+b'\n'+path.read_bytes(),timeout=180)
  code=r'''
import pathlib,subprocess,tarfile,sys,json
q=json.loads(sys.stdin.buffer.read());r=pathlib.Path(q['root'])
with tarfile.open(r/'peekaboo-macos-arm64.tar.gz') as t:
 for m in t.getmembers():
  if pathlib.PurePosixPath(m.name).is_absolute() or '..' in pathlib.PurePosixPath(m.name).parts or m.issym() or m.islnk() or m.isdev():raise RuntimeError('Unsafe archive member')
 t.extractall(r/'cli')
subprocess.run(['/usr/bin/ditto','-xk',str(r/'Peekaboo-4.9.7.app.zip'),str(r/'app')],check=True)
exe=r/'cli/peekaboo-macos-arm64/peekaboo';app=r/'app/Peekaboo.app'
for p in (exe,app):
 subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(p)],check=True,capture_output=True)
 sig=subprocess.run(['/usr/bin/codesign','-dv','--verbose=4',str(p)],capture_output=True,text=True)
 if 'TeamIdentifier='+q['team'] not in sig.stderr:raise RuntimeError('Unexpected signing team')
v=subprocess.run([str(exe),'--version'],capture_output=True,text=True,check=True).stdout.strip()
if not v.startswith('Peekaboo '+q['version']+' '):raise RuntimeError('Unexpected Peekaboo version')
subprocess.run(['/usr/bin/open',str(app)],check=True)
print(json.dumps({'installed':True,'version':v,'root':str(r)}))
'''
  return json.loads(self.python(code,json.dumps({'root':root,'team':TEAM,'version':VERSION}).encode(),timeout=120))
 def run(self,args,timeout=45):
  root,socket=self.location()
  # Explicit standard GUI socket is authoritative; no daemon/caller fallback.
  code=r'''
import sys,json,pathlib,subprocess,os
q=json.loads(sys.stdin.buffer.read());exe=pathlib.Path(q['root'])/'cli/peekaboo-macos-arm64/peekaboo'
if not exe.is_file():print(json.dumps({'success':False,'error':{'code':'NOT_INSTALLED','message':'请先在虚拟机设置中安装 Peekaboo 控件驱动'}}));sys.exit(0)
p=subprocess.run([str(exe),*q['args'],'--bridge-socket',q['socket'],'--json'],capture_output=True,text=True,timeout=q['timeout'])
try:data=json.loads(p.stdout)
except ValueError:data={'success':False,'error':{'code':'INVALID_RESPONSE','message':(p.stderr or p.stdout)[-2000:]}}
if p.returncode and data.get('success') is not False:data={'success':False,'error':{'code':'PROCESS_FAILED','message':(p.stderr or p.stdout)[-2000:]}}
print(json.dumps(data))
'''
  response=json.loads(self.python(code,json.dumps({'root':root,'socket':socket,'args':args,'timeout':max(1,timeout-5)},ensure_ascii=False).encode(),timeout=timeout))
  if response.get('success') is not True:
   error=response.get('error',{});raise HubError('Peekaboo: '+str(error.get('code','FAILED'))+' · '+str(error.get('message','操作失败')))
  return response.get('data',{})
 def permissions(self):
  data=self.run(['permissions','status','--all-sources'])
  source=next((s for s in data.get('sources',[]) if s.get('isSelected')),None)
  if not source or source.get('source')!='bridge':raise HubError('Peekaboo 未选中访客 GUI Bridge，拒绝使用其他运行位置')
  permissions=source.get('permissions',[])
  required=[p for p in permissions if p.get('isRequired') is True]
  ready=bool(required) and all(p.get('isGranted') is True for p in required)
  return {'ready':ready,'provider':'peekaboo','version':VERSION,'permissions':permissions,'source':'guest-gui-bridge'}
 def open_permissions(self):
  root,_=self.location()
  code="import json,sys,subprocess,pathlib; r=pathlib.Path(json.loads(sys.stdin.buffer.read())['root']); app=r/'app/Peekaboo.app'; assert app.is_dir(); subprocess.run(['/usr/bin/open',str(app)],check=True); subprocess.run(['/usr/bin/open','x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'],check=True); print('opened')"
  self.python(code,json.dumps({'root':root}).encode());return {'opened':True}
