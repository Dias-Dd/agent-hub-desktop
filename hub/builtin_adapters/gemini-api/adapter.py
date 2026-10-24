from hub.module_sdk import runtime_view
from .runtime import DeepSeekRuntime
from .compatible import CompatibleAPI

def execute(host, run):
    runtime=runtime_view(host,DeepSeekRuntime,provider='gemini-api')
    if hasattr(runtime,'connection'):runtime.api=CompatibleAPI(runtime.connection())
    return runtime._execute_native(run)


def probe(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{}),'kind':'gemini-api'}
    if manifest.get('api'):current['api']=manifest['api']
    return import_module('hub.builtin_adapters._shared.catalog').probe(registry,current)


def quota(registry,connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{}),'kind':'gemini-api'}
    if manifest.get('api'):current['api']=manifest['api']
    return import_module('hub.builtin_adapters._shared.quota').quota(registry,current)


def setup_status(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{})}
    return import_module('hub.builtin_adapters._shared.setup').status(registry,current,'gemini-api',manifest.get('setup',{}))


def setup_login(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{})}
    return import_module('hub.builtin_adapters._shared.setup').login(registry,current,'gemini-api',manifest.get('setup',{}))
