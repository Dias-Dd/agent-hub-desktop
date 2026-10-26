"""One source-only Python loader for built-in and user-owned harness modules."""
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import sys
import threading
import types
from pathlib import Path
from .core import HubError

_lock=threading.RLock()
_roots={}
_cache={}

class _Source(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        return compile(Path(self.path).read_bytes(), self.path, 'exec')

class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        prefix=fullname.split('.')[0]
        root=_roots.get(prefix)
        if not root or fullname==prefix:return None
        relative=fullname[len(prefix)+1:].split('.')
        folder=root.joinpath(*relative)
        source=folder.with_suffix('.py')
        if source.is_file():return importlib.util.spec_from_loader(fullname,_Source(fullname,str(source)))
        if folder.is_dir():
            init=folder/'__init__.py'
            if init.is_file():return importlib.util.spec_from_file_location(fullname,init,loader=_Source(fullname,str(init)),submodule_search_locations=[str(folder)])
            spec=importlib.machinery.ModuleSpec(fullname,None,is_package=True);spec.submodule_search_locations=[str(folder)];return spec
        return None

_finder=_Finder()
sys.meta_path.insert(0,_finder)


def load(folder):
    folder=Path(folder).resolve()
    manifest=json.loads((folder/'adapter.json').read_text(encoding='utf-8-sig'))
    if manifest.get('version')!=1 or manifest.get('protocol')!='hub-module-v1':raise HubError('模块协议必须为 hub-module-v1')
    entry=manifest.get('entrypoint','adapter.py')
    if not isinstance(entry,str) or Path(entry).name!=entry or not entry.endswith('.py'):raise HubError('entrypoint 必须是模块目录内的 Python 文件名')
    if not (folder/entry).is_file():raise HubError('模块入口不存在')
    digest=hashlib.sha256(str(folder).encode())
    for path in sorted(folder.rglob('*.py')):
        if '__pycache__' in path.parts:continue
        digest.update(path.relative_to(folder).as_posix().encode());digest.update(path.read_bytes())
    digest.update((folder/'adapter.json').read_bytes())
    key=digest.hexdigest()
    with _lock:
        if key in _cache:return _cache[key],manifest
        name='hub_module_'+key
        package=types.ModuleType(name);package.__path__=[str(folder)];package.__package__=name
        sys.modules[name]=package;_roots[name]=folder
        fullname=name+'.'+Path(entry).stem
        spec=importlib.util.spec_from_loader(fullname,_Source(fullname,str(folder/entry)))
        module=importlib.util.module_from_spec(spec);sys.modules[fullname]=module
        try:
            spec.loader.exec_module(module)
            if not callable(getattr(module,'execute',None)):raise HubError('模块缺少 execute(context, run)')
        except BaseException:
            for item in list(sys.modules):
                if item==name or item.startswith(name+'.'):sys.modules.pop(item,None)
            _roots.pop(name,None)
            raise
        _cache[key]=module
        return module,manifest


def execute(host,run,folder):
    from .module_sdk import runtime_view,request,finish,finalize
    try:
        host.check_latch(run)
        from .memory_notices import attach
        run=attach(host.hub,run)
        module,manifest=load(folder)
        context=runtime_view(host);context._module_manifest=manifest;context.module_directory=str(Path(folder).resolve())
        from . import module_tools
        if not hasattr(context,'read_only'):
            context.read_only=lambda r:r.get('purpose') in ('discussion','question')
        for name in ('guard','definitions','tool'):
            if not hasattr(context,name):
                setattr(context,name,lambda *args,_name=name:getattr(module_tools,_name)(context,*args))
        context.request=lambda current=run:request(context,current)
        result=module.execute(context,dict(run))
        with host.hub.lock:row=host.hub.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()
        if row and row[0] not in ('running','interrupting','queued'):return result
        if result is None:raise HubError('模块退出但未确认结果，不视为完成')
        return finish(context,run,result)
    except Exception as error:
        with host.hub.lock:row=host.hub.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()
        if row and row[0] not in ('running','interrupting','queued'):return
        status='interrupted' if host.stop_event.is_set() or '停止' in str(error) or '取消' in str(error) else 'failed'
        host.sessions.state(run,status)
        finalize(host,run,status,'模块执行未完成：'+str(error))
