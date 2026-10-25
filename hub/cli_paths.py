"""CLI lookup for Finder-launched apps; never source shell profiles."""
import os, shutil, sys
from pathlib import Path

def search_path(path=None):
    entries=(os.environ.get('PATH','') if path is None else path).split(os.pathsep)
    if sys.platform=='darwin':
        entries += [str(Path.home()/p) for p in ('.local/bin','.bun/bin','.npm-global/bin','Library/pnpm')]
        entries += ['/opt/homebrew/bin','/usr/local/bin','/usr/bin','/bin']
        for base in (Path.home()/'.nvm/versions/node',Path.home()/'.local/share/fnm/node-versions'):
            entries += [str(p) for p in sorted(base.glob('*/bin'),reverse=True) if p.is_dir()]
    return os.pathsep.join(dict.fromkeys(x for x in entries if x))

def which(name):
    return shutil.which(name,path=search_path())

def child_environment(env):
    result=dict(env)
    if sys.platform=='darwin': result['PATH']=search_path(result.get('PATH'))
    return result


def cli_environment(environment):
    from .proxy_env import inherit_system_proxy
    return inherit_system_proxy(child_environment(environment))
