"""Independent OpenCode providers, sharing the official ACP transport.

Preset data is adapted from CC Switch (MIT). See THIRD_PARTY_NOTICES.md.
This module never reads or modifies CC Switch or the user's OpenCode config.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from hub.core import HubError
from hub.cli_paths import cli_environment
from hub.module_sdk import runtime_view


from hub.module_credentials import identity, setting_key, secret_path, saved, keychain, key_present, store_key, get_key

def launcher(connection,manifest):
    if connection.get('kind')=='custom-harness':return manifest.get('settings',{}).get('executable','')
    return connection.get('executable','')


def resolve(connection,manifest,config):
    preset=manifest['settings']['opencode_preset'];variants=preset['variants']
    selected=config.get('variant') or variants[0]['id']
    variant=next((v for v in variants if v['id']==selected),None)
    if not variant:raise HubError('所选供应商地区或套餐不存在')
    base=config.get('base_url') or variant['config']['options'].get('baseURL','')
    if not isinstance(base,str) or len(base)>2000 or any(c.isspace() for c in base):raise HubError('供应商地址格式无效')
    try:parsed=urlsplit(base)
    except ValueError:raise HubError('供应商地址格式无效') from None
    if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise HubError('供应商地址须为有效的 HTTP(S) 地址，不能包含账号、查询参数或片段')
    namespace='hub-'+hashlib.sha256((connection['id']+'|'+selected+'|'+base).encode()).hexdigest()[:16]
    return variant,base,namespace


def model_rows(connection,manifest,config):
    variant,base,namespace=resolve(connection,manifest,config)
    models=variant['config'].get('models',{});chosen=config.get('models') or list(models)
    known={m['id']:m for m in connection.get('models',[]) if m.get('source')=='official_acp_config'}
    return [known.get(namespace+'/'+mid,{'id':namespace+'/'+mid,'name':models.get(mid,{}).get('name',mid),'efforts':['default'],
             'source':'cc_switch_preset','inference_verified':False}) for mid in chosen]


def configure(registry,connection,manifest,config=None):
    current=saved(registry,connection)
    if config is not None:
        if not isinstance(config,dict) or set(config)-{'variant','base_url','key_env','api_key','models'}:raise HubError('供应商配置字段无效')
        if not all(isinstance(config.get(k,''),str) for k in ('variant','base_url','key_env','api_key')):raise HubError('供应商配置须为文字')
        next_config={k:config.get(k,current.get(k,'')) for k in ('variant','base_url','key_env')}
        changed_variant='variant' in config and config['variant']!=current.get('variant')
        if changed_variant and 'base_url' not in config:next_config['base_url']=''
        env_name=next_config['key_env']
        if env_name and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',env_name):raise HubError('请输入密钥环境变量名，不是密钥内容')
        models=config.get('models',[] if changed_variant else current.get('models',[]))
        if not isinstance(models,list) or len(models)>100 or any(not isinstance(m,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,199}',m) for m in models):raise HubError('模型 ID 列表无效，最多 100 项')
        next_config['models']=list(dict.fromkeys(models));resolve(connection,manifest,next_config)
        key=config.get('api_key','')
        if key and env_name:raise HubError('API Key 与密钥环境变量请选择一种，避免使用错误的凭据')
        if key and (not 4<=len(key)<=4096 or any(c.isspace() for c in key)):raise HubError('API Key 格式无效')
        assigned=[a['id'] for a in registry.rows('agent_profiles') if a['connection_id']==connection['id']]
        with registry.lock,registry.server.workflows.lock:
            if registry.busy(assigned):raise HubError('此供应商仍有在途任务，请等待结束后修改')
            structural=any(next_config.get(k)!=current.get(k) for k in ('variant','base_url','models'))
            if structural:
                for w in registry.server.workflows.snapshot('user'):
                    if w.get('status') in ('active','paused','blocked','needs_attention') and set(assigned)&set([w.get('manager')]+w.get('agents',[])):raise HubError('此供应商仍被未结束项目使用，请先结束项目或新建独立连接')
            if key:store_key(registry,connection,key)
            with registry.hub.tx():
                registry.hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(setting_key(connection),json.dumps(next_config)))
                row=registry.get('integration_connections',connection['id']);row['models']=model_rows(connection,manifest,next_config)
                registry.put('integration_connections',row);registry.hub.audit('user','opencode.provider_configured',{'connection':connection['id'],'variant':next_config['variant'],'models':len(row['models'])})
        current=next_config
    variant,base,_=resolve(connection,manifest,current)
    return {'config':{**current,'variant':variant['id'],'base_url':base},'variants':[{'id':v['id'],'name':v['name'],'base_url':v['config']['options']['baseURL']} for v in manifest['settings']['opencode_preset']['variants']],
        'website':variant['website'],
        'key_saved':key_present(registry,connection),'key_env_present':bool(current.get('key_env') and os.environ.get(current['key_env'])),
        'models':model_rows(connection,manifest,current),'note':'预设不代表账号权限或真实调用已通过；模型与凭据仅用于此连接。'}


def environment(registry,connection,manifest,require_key=True):
    config=saved(registry,connection);variant,base,namespace=resolve(connection,manifest,config)
    key=get_key(registry,connection,config,variant) if require_key else ''
    # Unique provider IDs avoid matching credentials in a user's auth.json.
    # All known OpenCode environment overrides are replaced for this child only.
    env=cli_environment({k:v for k,v in os.environ.items() if not k.startswith(('OPENCODE_','HUB_'))})
    if os.environ.get('OPENCODE_GIT_BASH_PATH'):env['OPENCODE_GIT_BASH_PATH']=os.environ['OPENCODE_GIT_BASH_PATH']
    root=registry.hub.directory/'opencode-providers'/identity(connection)
    for kind in ('config','data','cache','state'):(root/kind).mkdir(parents=True,exist_ok=True)
    env.update({'XDG_CONFIG_HOME':str((root/'config').resolve()),'XDG_DATA_HOME':str((root/'data').resolve()),
        'XDG_CACHE_HOME':str((root/'cache').resolve()),'XDG_STATE_HOME':str((root/'state').resolve()),
        'OPENCODE_DB':str((root/'data/opencode.db').resolve()),'OPENCODE_CONFIG_DIR':str((root/'config/opencode').resolve()),
        'OPENCODE_DISABLE_PROJECT_CONFIG':'true','OPENCODE_DISABLE_DEFAULT_PLUGINS':'true','OPENCODE_PURE':'true',
        'OPENCODE_DISABLE_CLAUDE_CODE':'true','OPENCODE_DISABLE_EXTERNAL_SKILLS':'true','OPENCODE_DISABLE_AUTOUPDATE':'true',
        'HUB_PROVIDER_API_KEY':key})
    provider=copy.deepcopy(variant['config']);provider['options']['baseURL']=base
    provider['options']['apiKey']='{env:HUB_PROVIDER_API_KEY}'
    selected=config.get('models') or list(provider['models']);provider['models']={mid:provider['models'].get(mid,{'name':mid}) for mid in selected}
    env['OPENCODE_CONFIG_CONTENT']=json.dumps({'$schema':'https://opencode.ai/config.json','autoupdate':False,
        'enabled_providers':[namespace],'provider':{namespace:provider}},ensure_ascii=False)
    if len(env['OPENCODE_CONFIG_CONTENT'].encode('utf-16-le'))>=60000:raise HubError('供应商配置过大，请减少自定义模型；未截断或发送请求')
    return env


def status(registry,connection,manifest):
    from hub.integrations import locate
    if not locate('opencode',launcher(connection,manifest)):return {'state':'missing','message':'本机未安装 OpenCode，请通过官网安装后重新检测。'}
    try:get_key(registry,connection,saved(registry,connection),resolve(connection,manifest,saved(registry,connection))[0])
    except HubError as error:return {'state':'login','message':str(error)}
    return {'state':'ready','message':'已配置此供应商凭据；未调用模型，不代表账号授权已验证。'}


def setup_login(registry,connection,manifest):
    raise HubError('此接入使用独立 API 凭据，请在主程序“添加 Agent”界面配置；首次引导可先跳过，不会打开原版 OpenCode 登录')


def probe(registry,connection,manifest):
    from hub.integrations import locate
    if not locate('opencode',launcher(connection,manifest)):raise HubError('请先安装 OpenCode，再配置和读取本供应商模型')
    return {'models':model_rows(connection,manifest,saved(registry,connection)), 'catalog_complete':False,'catalog_status':'preset',
        'verification':'CC Switch 预设目录，未验证真实调用','probe_detail':'仅显示本供应商所选地区／套餐的模型。实际账号权限、价格和可用性需单独测试。'}


def probe_model(registry,connection,model,manifest):
    if model not in {m['id'] for m in model_rows(connection,manifest,saved(registry,connection))}:raise HubError('模型不属于此供应商配置')
    from hub.builtin_adapters._shared.model_options import probe_model as options
    return options(registry,{**connection,'kind':'opencode','executable':launcher(connection,manifest)},model,environment_override=environment(registry,connection,manifest))


def execute(host,run,manifest):
    from .runtime import execute as execute_acp
    view=runtime_view(host,provider='opencode');connection=host.connection()
    if run['model'] not in {m['id'] for m in model_rows(connection,manifest,saved(host.registry,connection))}:raise HubError('模型不属于此供应商或配置已变化，请重新选择模型；未发送推理')
    view.provider_environment=lambda:environment(host.registry,connection,manifest)
    return execute_acp(view,run)
