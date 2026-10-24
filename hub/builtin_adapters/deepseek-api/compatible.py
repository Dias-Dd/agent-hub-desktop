import hashlib,json,os,re,queue,shutil,subprocess,sys,threading,time,urllib.request,urllib.error
from pathlib import Path
from hub.core import HubError
from hub.process_job import ProcessJob
from hub.proxy_env import inherit_system_proxy
class CompatibleAPI:
 def __init__(self,connection):self.connection=connection
 def request(self,path,payload=None):
  from hub.integrations import BASES
  config=self.connection.get('api') or {}
  fallback=BASES.get(self.connection['kind'],('',''))
  base=config.get('base_url') or fallback[0];default_env=config.get('key_environment') or fallback[1]
  key_name=self.connection.get('key_env') or default_env
  key=os.environ.get(self.connection.get('module_environment',{}).get(key_name,key_name))
  if not base:raise HubError('模块未声明 API 地址')
  if not key:raise HubError('服务进程尚未读到密钥环境变量；设置后重新打开应用')
  body=None if payload is None else json.dumps({k:v for k,v in payload.items() if k!='thinking'}).encode()
  req=urllib.request.Request(base+path,data=body,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
  try:
   env=inherit_system_proxy(dict(os.environ));proxy=env.get('HTTPS_PROXY') or env.get('https_proxy')
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':proxy} if proxy else {}))
   with opener.open(req,timeout=60) as r:return json.load(r)
  except urllib.error.HTTPError as e:raise HubError('提供商 HTTP '+str(e.code)+'；不自动重试') from None
  except (OSError,ValueError):raise HubError('提供商连接或响应异常；不自动重试') from None

def cli_failure(final,exit_code,diagnostics,env=None):
 parts=[]
 if isinstance(final,dict):
  for field in ('error','errors','message','result'):
   value=final.get(field)
   if value:parts.append(json.dumps(value,ensure_ascii=False) if not isinstance(value,str) else value)
 if not parts:parts=[x.strip() for x in diagnostics if x.strip()][-12:]
 message='CLI 未确认成功结束（退出码 '+str(exit_code)+'）：'+('；'.join(parts) or '没有最终结果或错误详情')
 for key,value in (env or {}).items():
  if isinstance(value,str) and len(value)>5 and any(word in key.upper() for word in ('KEY','TOKEN','SECRET','PASSWORD')):message=message.replace(value,'[已隐藏]')
 message=re.sub(r'(?i)Bearer\s+[^\s\"\']+','Bearer [已隐藏]',message)
 return message[:2400]+'；不自动重试'

def workbuddy_auth_failure(pid,started,home=None):
 """Fallback for a vendor CLI that exits 0 without a result or stderr.
 Read only matching current-process diagnostic lines, never login stores.
 """
 from datetime import datetime
 root=(Path(home) if home else Path.home())/'.codebuddy/logs'/datetime.now().strftime('%Y-%m-%d')
 if not root.is_dir():return None
 for file in root.glob('*.log'):
  try:
   if file.stat().st_mtime<started:continue
   with file.open('rb') as handle:
    handle.seek(0,2);size=handle.tell();handle.seek(max(0,size-65536));tail=handle.read().decode('utf8',errors='replace')
   for line in tail.splitlines():
    if ('[pid='+str(pid)+']') in line and 'Authentication required. Please use /login' in line:
     return 'CodeBuddy 官方 CLI 要求登录（Authentication required /login）；客户端登录不代表此 CLI 通道已授权'
  except OSError:continue
 return None

def workbuddy_session_failure(session_id,started,home=None):
 """Read only this resumed session's explicit failure, including a detached CLI child."""
 if not session_id:return None
 from datetime import datetime
 root=(Path(home) if home else Path.home())/'.codebuddy/logs'/datetime.fromtimestamp(started).strftime('%Y-%m-%d')
 if not root.is_dir():return None
 for file in root.glob('*.log'):
  try:
   if file.stat().st_mtime<started:continue
   with file.open('rb') as handle:
    handle.seek(0,2);size=handle.tell();handle.seek(max(0,size-2_000_000));tail=handle.read().decode('utf8',errors='replace')
   for line in tail.splitlines():
    if session_id not in line or not any(x in line for x in ('SessionNotFoundError','not found in current project dir','No conversation found with session ID')):continue
    stamp=re.match(r'\[(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d+)\]',line)
    if stamp and datetime.strptime(stamp[1],'%Y/%m/%d %H:%M:%S.%f').timestamp()>=started-1:
     return 'CodeBuddy 无法在启动目录找到原会话（SessionNotFoundError）；原会话保留，须从会话原目录续接，不能清空或重放任务'
  except OSError:continue
 return None

def bridge(runtime,run,allowed):
 cfg=runtime.mcp_config();env=runtime.run_environment(run)
 env['HUB_TOOL_ALLOWLIST']=json.dumps(allowed)
 return {'name':'agent-message-hub','command':cfg['command'],'args':cfg['args'],'env':[{'name':k,'value':v} for k,v in env.items()]}

