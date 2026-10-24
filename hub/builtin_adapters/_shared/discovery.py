import os,shutil
from pathlib import Path
from hub.core import HubError
def locate(kind,supplied=''):
 from hub.codex_runtime import codex_executable
 from hub.antigravity import executable as agy_executable
 if supplied:
  if kind=='workbuddy' and 'codebuddy-lite-wb' in supplied.lower():raise HubError('此接入已切换 CodeBuddy；请使用独立 codebuddy CLI，不再使用 WorkBuddy 内置精简入口')
  return str(Path(supplied)) if Path(supplied).is_file() else None
 if kind=='codex':return codex_executable()
 if kind=='antigravity':return agy_executable()
 if kind=='deepseek-harness':
  p=Path(os.environ.get('LOCALAPPDATA',''))/'Programs/DeepSeek Harness/DeepSeek Harness.exe'
  return str(p) if p.is_file() else None
 names={'opencode':['opencode.cmd','opencode'],'ori':['ori.exe','ori'],'workbuddy':['codebuddy.cmd','codebuddy','cbc']}.get(kind,[])
 for name in names:
  found=shutil.which(name)
  if found:return found
 for base in [Path.home()/'.local/bin',Path.home()/'.bun/bin',Path(os.environ.get('APPDATA',''))/'npm']:
  for name in names:
   if (base/name).is_file():return str(base/name)
 return None
