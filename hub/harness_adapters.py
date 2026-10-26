"""Adapter layout and the built-in JSON/script execution boundary.

Discovery never executes scripts. Built-ins share existing transport code and
run inside the bundled Python runtime; custom JSONL scripts stay subprocesses.
"""
import hashlib
import json
import threading
import time
from pathlib import Path
from .core import HubError

PACKAGED = Path(__file__).with_name('builtin_adapters')
_lock = threading.RLock()


def custom_directory(directory):
    return Path(directory) / 'adapters' / 'custom'


def _relocate_commands(target, original):
    """Repair absolute launch paths while retaining the original manifest."""
    paths = target.glob('*/adapter.json') if target.is_dir() else []
    # A merged item is itself an adapter rather than the entire custom root.
    if (target / 'adapter.json').is_file(): paths = [target / 'adapter.json']
    for path in paths:
        try:
            before = path.read_bytes()
            data = json.loads(before.decode('utf-8-sig'))
            argv = data.get('command') if isinstance(data, dict) else None
            if not isinstance(argv, list): continue
            updated = []
            for arg in argv:
                value = arg
                if isinstance(arg, str):
                    for source, dest in [(str(original.resolve()), str(target.resolve())),
                                         (original.resolve().as_posix(), target.resolve().as_posix())]:
                        if arg == source or arg.startswith(source + '/') or arg.startswith(source + '\\'):
                            value = dest + arg[len(source):]
                            break
                updated.append(value)
            if updated != argv:
                backup = path.with_name('adapter.before-directory-migration.json')
                if not backup.exists(): backup.write_bytes(before)
                data['command'] = updated
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except (OSError, ValueError):
            # Discovery will report invalid manifests; never discard the file.
            continue


def builtin_catalog():
    result = {}
    for path in sorted(PACKAGED.glob('*/adapter.json')):
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if (data.get('version') != 1 or data.get('protocol') != 'hub-module-v1'
                or data.get('id') != path.parent.name or data.get('entrypoint') != 'adapter.py'
                or not data.get('name') or not data.get('efforts')):
            raise HubError('内置适配器配置无效：' + path.parent.name)
        from .module_config import schema
        schema(data)
        result[data['id']] = data
    if not result:
        raise HubError('内置适配器资源缺失，请重新安装应用')
    return result


def prepare_layout(directory, install_builtins=True):
    """Move the old custom directory without overwriting any user file."""
    with _lock:
        base = Path(directory)
        custom = custom_directory(base)
        custom.parent.mkdir(parents=True, exist_ok=True)
        readme = custom.parent / 'README.md'
        if not readme.exists():
            readme.write_text('# Agent Hub 接入目录\n\n'
                '- builtin：应用维护的内置接入，每项包含 adapter.json 与 adapter.py，实际用于执行。\n'
                '- custom：用户自定义接入，采用 hub-jsonl-v1；示例和完整协议说明在 custom/README.md。\n'
                '- 旧 harness-adapters 自动迁入 custom；账号、Agent 和会话仍在原应用数据中。\n'
                '- builtin 与 custom 均支持 hub-module-v1，可复制模块并修改 ID；Python 模块使用应用自带运行环境。\n', encoding='utf-8')
        if readme.exists():
            text=readme.read_text(encoding='utf-8')
            old='builtin 采用 hub-builtin-v1，使用内置 Python 和共享传输实现；不能原样搬入 custom。'
            if old in text:readme.write_text(text.replace(old,'builtin 与 custom 均支持 hub-module-v1，可整目录复制并修改；完整接口见 custom/MODULES.md。'),encoding='utf-8')
        legacy = base / 'harness-adapters'
        if legacy.is_dir() and not custom.exists():
            legacy.rename(custom)
            _relocate_commands(custom, legacy)
        else:
            custom.mkdir(parents=True, exist_ok=True)
            if legacy.is_dir():
                for source in legacy.iterdir():
                    target = custom / source.name
                    if target.exists():
                        # Retain both on collisions. Duplicate adapter IDs are
                        # reported by discovery rather than silently preferred.
                        suffix = 1
                        while target.exists():
                            target = custom / (source.name + '-migrated-' + str(suffix))
                            suffix += 1
                    source.rename(target)
                    if target.is_dir(): _relocate_commands(target, source)
                legacy.rmdir()
        if not install_builtins: return custom
        builtins = base / 'adapters' / 'builtin'
        builtins.mkdir(exist_ok=True)
        state_path = builtins / '.installed-hashes.json'
        try:
            previous = json.loads(state_path.read_text(encoding='utf-8'))
            if not isinstance(previous, dict): previous = {}
        except (OSError, ValueError):
            previous = {}
        updated = dict(previous)
        for source in sorted(PACKAGED.glob('*/*')):
            if not source.is_file() or source.suffix not in ('.json', '.py'): continue
            relative = source.relative_to(PACKAGED)
            key = relative.as_posix()
            target = builtins / relative
            target.parent.mkdir(exist_ok=True)
            incoming = source.read_bytes()
            digest = hashlib.sha256(incoming).hexdigest()
            if target.exists():
                current = hashlib.sha256(target.read_bytes()).hexdigest()
                if current == digest:
                    updated[key] = digest
                    continue
                if current != previous.get(key):
                    # Local edits are preserved. They cannot silently replace
                    # a bundled in-process adapter; use custom for extensions.
                    continue
            target.write_bytes(incoming)
            updated[key] = digest
        if updated != previous:
            state_path.write_text(json.dumps(updated, indent=2), encoding='utf-8')
        return custom


def load_builtin(directory, kind):
    """Compatibility name for the common loader; no built-in privilege branch."""
    from .module_loader import load
    folder = Path(directory) / 'adapters' / 'builtin' / kind
    if not folder.exists(): prepare_layout(directory)
    return load(folder)[0].execute


def execute_builtin(runtime, run, kind):
    from .module_loader import execute
    folder = Path(runtime.hub.directory) / 'adapters' / 'builtin' / kind
    if not folder.exists(): prepare_layout(runtime.hub.directory)
    return execute(runtime, run, folder)


def probe_module(registry, actor, connection_id):
    registry.hub.require(actor, {'user'})
    connection=registry.get('integration_connections',connection_id)
    if connection['kind']=='custom-harness':
        registry.scan_adapters(force=True)
        connection=registry.get('integration_connections',connection_id)
        if not connection.get('adapter_available'):raise HubError('模块配置不可用，请刷新接入目录')
        config=connection['adapter']
        folder=Path(config['directory'])
        python_module=config.get('protocol')=='hub-module-v1'
    else:
        folder=registry.hub.directory/'adapters'/'builtin'/connection['kind']
        python_module=True
    observations={}
    if python_module:
        from .module_loader import load
        module,manifest=load(folder)
        hook=getattr(module,'probe',None)
        if callable(hook):observations=hook(registry,dict(connection))
        else:observations={'models':manifest.get('models',[]),'verification':'模块声明的模型目录，未验证实际调用'}
    else:
        observations={'models':connection.get('models',[]),'verification':'用户声明的模型与能力，未验证实际调用','probe_detail':'目录发现不运行脚本，也不发送推理请求。'}
    if not isinstance(observations,dict) or not isinstance(observations.get('models'),list):raise HubError('模块 probe 必须返回包含 models 数组的对象')
    for model in observations['models']:
        if not isinstance(model,dict) or not isinstance(model.get('id'),str) or not model['id']:raise HubError('模块返回了无效模型目录')
    # Hooks return observations; they cannot replace stable identity or grants.
    allowed=('models','verification','probe_detail','official_windows','catalog_complete','catalog_status','candidate_models','client_models','quota_error','official_balance','balance_source','quota_observed_at')
    for key in allowed:
        if key in observations:connection[key]=observations[key]
    connection['probed_at']=time.time()
    with registry.hub.tx():
        registry.put('integration_connections',connection)
        registry.hub.audit(actor,'integration.probed',{'connection':connection_id,'models':len(connection['models']),'inference_sent':False})
    return connection


def _module_folder(registry,connection):
    if connection.get('adapter'):
        if connection['adapter'].get('protocol')!='hub-module-v1':raise HubError('此模块未实现对应的公开能力')
        return Path(connection['adapter']['directory'])
    return registry.hub.directory/'adapters'/'builtin'/connection['kind']


def quota_module(registry,actor,connection_id):
    registry.hub.require(actor,{'user'})
    from .module_loader import load
    connection=registry.get('integration_connections',connection_id)
    module,_=load(_module_folder(registry,connection))
    hook=getattr(module,'quota',None)
    if not callable(hook):raise HubError('此模块没有提供额度读取功能')
    observations=hook(registry,dict(connection))
    if not isinstance(observations,dict):raise HubError('模块 quota 返回值无效')
    for key in ('models','official_windows','official_balance','quota_observed_at','quota_error','probed_at','verification','balance_source'):
        if key in observations:connection[key]=observations[key]
    with registry.hub.tx():registry.put('integration_connections',connection)
    if 'models' in observations:return connection
    return {'readable':bool(connection.get('official_balance')),'observed_at':connection.get('quota_observed_at')}


def model_options_module(registry,actor,connection_id,model):
    registry.hub.require(actor,{'user'})
    from .core import text
    text(model,200)
    from .module_loader import load
    connection=registry.get('integration_connections',connection_id)
    module,_=load(_module_folder(registry,connection))
    hook=getattr(module,'probe_model',None)
    if not callable(hook):raise HubError('此模块未提供模型档位探测')
    result=hook(registry,dict(connection),model)
    if not isinstance(result,dict) or result.get('id')!=model or not isinstance(result.get('efforts'),list) or not result['efforts']:raise HubError('模块返回无效档位目录')
    connection['models']=[m for m in connection.get('models',[]) if m['id']!=model]+[result]
    with registry.hub.tx():registry.put('integration_connections',connection)
    return result
