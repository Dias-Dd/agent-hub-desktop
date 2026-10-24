from hub.module_sdk import runtime_view
from .runtime import execute as execute_protocol

def execute(host,run):
    return execute_protocol(runtime_view(host,provider='ori'),run)


def probe(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{}),'kind':'ori'}
    if manifest.get('api'):current['api']=manifest['api']
    return import_module('hub.builtin_adapters._shared.catalog').probe(registry,current)


def quota(registry,connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{}),'kind':'ori'}
    if manifest.get('api'):current['api']=manifest['api']
    return import_module('hub.builtin_adapters._shared.quota').quota(registry,current)


def probe_model(registry,connection,model):
    from importlib import import_module
    return import_module('hub.builtin_adapters._shared.model_options').probe_model(registry,{**connection,'kind':'ori'},model)


def setup_status(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{})}
    return import_module('hub.builtin_adapters._shared.setup').status(registry,current,'ori',manifest.get('setup',{}))


def setup_login(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{})}
    return import_module('hub.builtin_adapters._shared.setup').login(registry,current,'ori',manifest.get('setup',{}))
