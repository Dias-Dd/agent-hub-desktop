from .runtime import execute


def probe(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{}),'kind':'deepseek-harness'}
    if manifest.get('api'):current['api']=manifest['api']
    return import_module('hub.builtin_adapters._shared.catalog').probe(registry,current)


def quota(registry,connection):
    from .account import quota as read
    return read(registry,connection)


def setup_status(registry,connection):
    from .account import inspect
    result=inspect(registry.server.deepseek,config=connection)
    return {'state':'ready' if result['status']=='credential-stored' else 'login','message':'账号已登录。' if result['status']=='credential-stored' else '请在 DeepSeek Harness 中登录后重新检查。'}


def setup_login(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{})}
    return import_module('hub.builtin_adapters._shared.setup').login(registry,current,'deepseek-harness',manifest.get('setup',{}))
