import os,shutil,sys
from hub.cli_paths import which
from pathlib import Path
from hub.core import HubError
def locate(kind,supplied=''):
 from hub.codex_runtime import codex_executable
 from hub.antigravity import executable as agy_executable
 if kind=='deepseek-harness':
  from hub.deepseek_harness import installation
  try:return str(installation({'harness_install':supplied} if supplied else None)[0])
  except HubError:return None
 if supplied:
  if kind=='workbuddy' and 'codebuddy-lite-wb' in supplied.lower():raise HubError('此接入已切换 CodeBuddy；请使用独立 codebuddy CLI，不再使用 WorkBuddy 内置精简入口')
  return str(Path(supplied)) if Path(supplied).is_file() else None
 if kind=='codex':return codex_executable()
 if kind=='antigravity':return agy_executable()
 names={'opencode':['opencode.cmd','opencode'],'ori':['ori.exe','ori'],'workbuddy':['codebuddy.cmd','codebuddy','cbc']}.get(kind,[])
 if sys.platform=='darwin':names=[n for n in names if not n.endswith(('.cmd','.exe'))]
 for name in names:
  found=which(name)
  if found:return found
 for base in [Path.home()/'.local/bin',Path.home()/'.bun/bin',Path(os.environ.get('APPDATA',''))/'npm']:
  for name in names:
   if (base/name).is_file():return str(base/name)
 return None
