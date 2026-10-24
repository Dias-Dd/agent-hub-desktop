from hub.module_sdk import runtime_view
from .runtime import CodexRuntime, AppServer

def execute(host, run):
    runtime=runtime_view(host,CodexRuntime,provider='codex')
    if hasattr(runtime,'connection') and not hasattr(runtime,'connection_executable'):
        from hub.integrations import locate
        runtime.connection_executable=lambda:locate('codex',runtime.connection().get('executable',''))
    if getattr(runtime.factory,'hub_transport',None)=='codex':runtime.factory=AppServer
    return runtime._execute_native(run)


def probe(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{}),'kind':'codex'}
    if manifest.get('api'):current['api']=manifest['api']
    return import_module('hub.builtin_adapters._shared.catalog').probe(registry,current)


def quota(registry,connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{}),'kind':'codex'}
    if manifest.get('api'):current['api']=manifest['api']
    return import_module('hub.builtin_adapters._shared.quota').quota(registry,current)


def setup_status(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{})}
    return import_module('hub.builtin_adapters._shared.setup').status(registry,current,'codex',manifest.get('setup',{}))


def setup_login(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{})}
    return import_module('hub.builtin_adapters._shared.setup').login(registry,current,'codex',manifest.get('setup',{}))
