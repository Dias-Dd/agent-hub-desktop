from hub.module_sdk import runtime_view
from .runtime import AntigravityRuntime, AntigravityStream, AntigravityProbe

def execute(host, run):
    runtime=runtime_view(host,AntigravityRuntime,provider='antigravity')
    if hasattr(runtime,'connection') and not hasattr(runtime,'connection_executable'):
        from hub.integrations import locate
        runtime.connection_executable=lambda:locate('antigravity',runtime.connection().get('executable',''))
    if not hasattr(runtime,'stream_factory') or getattr(runtime.stream_factory,'hub_transport',None)=='antigravity':runtime.stream_factory=AntigravityStream
    if not hasattr(runtime,'probe'):runtime.probe=AntigravityProbe(runtime.connection_executable if hasattr(runtime,'connection_executable') else None)
    return runtime._execute_native(run)


def probe(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{}),'kind':'antigravity'}
    if manifest.get('api'):current['api']=manifest['api']
    return import_module('hub.builtin_adapters._shared.catalog').probe(registry,current)


def quota(registry,connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{}),'kind':'antigravity'}
    if manifest.get('api'):current['api']=manifest['api']
    return import_module('hub.builtin_adapters._shared.quota').quota(registry,current)


def setup_status(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{})}
    return import_module('hub.builtin_adapters._shared.setup').status(registry,current,'antigravity',manifest.get('setup',{}))


def setup_login(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{})}
    return import_module('hub.builtin_adapters._shared.setup').login(registry,current,'antigravity',manifest.get('setup',{}))
