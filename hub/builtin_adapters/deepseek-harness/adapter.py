from .runtime import execute


def probe(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{}),'kind':'deepseek-harness'}
    if manifest.get('api'):current['api']=manifest['api']
    result=import_module('hub.builtin_adapters._shared.catalog').probe(registry,current)
    from hub.core import HubError
    try:
        balances=quota(registry,current)
        result.update({k:balances[k] for k in ('official_balance','balance_source','quota_observed_at','quota_error') if k in balances})
    except HubError:result['quota_error']='余额读取失败，请检查登录或网络；模型目录仍可使用。'
    return result


def quota(registry,connection):
    from .account import quota as read
    return read(registry,connection)


def setup_status(registry,connection):
    from .account import inspect
    from hub.core import HubError
    result=inspect(registry.server.deepseek,config=connection)
    ready=result['status']=='credential-stored' or result.get('api_key_configured')
    if not ready:
        try:ready=bool(registry.server.deepseek.key())
        except HubError:pass
    return {'state':'ready' if ready else 'login','message':'已找到 Harness 账号或 API 凭据；将读取实际模型目录。' if ready else '请在 DeepSeek Harness 中登录账号或配置 API 凭据后重新检查。'}



def setup_login(registry, connection):
    import json
    from pathlib import Path
    from importlib import import_module
    manifest=json.loads(Path(__file__).with_name('adapter.json').read_text(encoding='utf-8-sig'))
    current={**connection,**manifest.get('settings',{})}
    return import_module('hub.builtin_adapters._shared.setup').login(registry,current,'deepseek-harness',manifest.get('setup',{}))
