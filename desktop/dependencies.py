"""Restore enabled provider hosts and the configured local proxy, never inference."""
import csv,ctypes,json,os,socket,sqlite3,subprocess,time
from pathlib import Path
from contextlib import closing
from urllib.parse import urlsplit
HOSTS={
 'deepseek-harness':('DeepSeek Harness','DeepSeek Harness/DeepSeek Harness.exe'),
 'antigravity':('Antigravity','Antigravity/Antigravity.exe'),
}
PROXIES={'clash-verge.exe','clash for windows.exe','flclash.exe','v2rayn.exe','mihomo-party.exe','clash-nyanpasu.exe'}

def running_names():
 try:
  r=subprocess.run(['tasklist.exe','/FO','CSV','/NH'],capture_output=True,text=True,errors='replace',timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  return {row[0].lower() for row in csv.reader(r.stdout.splitlines()) if row}
 except (OSError,subprocess.TimeoutExpired):return set()

def spawn_host(path):
 # GUI hosts must not inherit Electron's console mode or frozen DLL overrides.
 env={k:v for k,v in os.environ.items() if not k.startswith(('_PYI','_MEIPASS')) and k not in ('ELECTRON_RUN_AS_NODE','PYTHONHOME','PYTHONPATH')}
 env['PYINSTALLER_RESET_ENVIRONMENT']='1'
 startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
 kernel=ctypes.WinDLL('kernel32',use_last_error=True);buffer=ctypes.create_unicode_buffer(32768);kernel.GetDllDirectoryW(len(buffer),buffer);old=buffer.value
 kernel.SetDllDirectoryW(None)
 try:return subprocess.Popen([str(path)],cwd=str(path.parent),env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,startupinfo=startup,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
 finally:kernel.SetDllDirectoryW(old or None)

def proxy_candidate():
 # Only known GUI proxy clients registered by Windows or installed in known roots.
 import winreg
 for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
  try:
   with winreg.OpenKey(hive,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
    for index in range(winreg.QueryInfoKey(key)[1]):
     _,command,_=winreg.EnumValue(key,index)
     if not isinstance(command,str):continue
     command=os.path.expandvars(command.strip());value=command.split('"',2)[1] if command.startswith('"') else command.split(' ',1)[0]
     path=Path(value)
     if path.name.lower() in PROXIES and path.is_absolute() and path.is_file():return path
  except OSError:pass
 for base in [Path(os.environ.get('LOCALAPPDATA',''))/'Programs',Path(os.environ.get('PROGRAMFILES',''))]:
  for folder,file in [('Clash Verge','clash-verge.exe'),('FlClash','FlClash.exe'),('mihomo-party','mihomo-party.exe'),('Clash Nyanpasu','clash-nyanpasu.exe')]:
   path=base/folder/file
   if path.is_file():return path
 return None

def port_ready(host,port):
 try:
  with socket.create_connection((host,port),timeout=.3):return True
 except OSError:return False

def enabled_connections(data):
 db=Path(data)/'hub.sqlite3'
 if not db.is_file():return []
 with closing(sqlite3.connect('file:'+db.as_posix()+'?mode=ro',uri=True,timeout=2)) as connection:
  tables={r[0] for r in connection.execute("select name from sqlite_master where type='table'")}
  if not {'integration_connections','agent_profiles'}<=tables:return []
  used={a['connection_id'] for row in connection.execute('select body from agent_profiles') if (a:=json.loads(row[0])).get('enabled')}
  rows=[json.loads(row[0]) for row in connection.execute('select body from integration_connections')]
  setting=connection.execute("select value from settings where key='deepseek_runtime'").fetchone() if 'settings' in tables else None
  for item in rows:
   if item.get('legacy') and setting:item['enabled']=json.loads(setting[0]).get('enabled',False)
  return [item for item in rows if item['id'] in used and item.get('enabled')]

def start_dependencies(data):
 if os.name!='nt':return []
 try:connections=enabled_connections(data)
 except (OSError,sqlite3.Error,ValueError):return []
 result=[];running=running_names()
 if connections:
  from hub.proxy_env import inherit_system_proxy
  proxy=inherit_system_proxy({})
  urls={v for k,v in proxy.items() if k in ('HTTP_PROXY','HTTPS_PROXY')}
  unavailable=[]
  for value in urls:
   url=urlsplit(value)
   if url.hostname not in ('localhost','127.0.0.1','::1'):continue
   port=url.port or (443 if url.scheme=='https' else 80)
   if not port_ready(url.hostname,port):unavailable.append((url.hostname,port))
  if unavailable:
   path=proxy_candidate()
   if path:
    try:
     if path.name.lower() not in running:spawn_host(path)
     result.append({'name':'系统代理','status':'starting','hint':'等待本地代理端口就绪'})
    except OSError:result.append({'name':'系统代理','status':'failed'})
   else:result.append({'name':'系统代理','status':'unavailable','hint':'本地端口未启动，未找到已安装代理客户端；请手动打开原代理程序'})
  elif urls:result.append({'name':'系统代理','status':'ready'})
 for item in connections:
  if item['kind'] not in HOSTS:continue
  name,relative=HOSTS[item['kind']];path=Path(os.environ.get('LOCALAPPDATA',''))/'Programs'/relative
  if not path.is_file():result.append({'name':name,'status':'not_installed'});continue
  if path.name.lower() in running:result.append({'name':name,'status':'running'});continue
  try:
   spawn_host(path);running.add(path.name.lower());result.append({'name':name,'status':'starting'})
  except OSError:result.append({'name':name,'status':'failed'})
 try:
  folder=Path(data);folder.mkdir(parents=True,exist_ok=True)
  (folder/'startup-dependencies.json').write_text(json.dumps({'at':time.time(),'items':result},ensure_ascii=False),encoding='utf8')
 except OSError:pass
 return result
