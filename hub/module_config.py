"""Declarative module forms. Secrets never travel back to the browser."""
import json
import re
from urllib.parse import urlsplit
from .core import HubError

TYPES={'text','secret','url','select','string_list','integer','boolean'}

def schema(manifest):
    value=manifest.get('configuration')
    if not isinstance(value,dict):return None
    fields=value.get('fields',[])
    if value.get('version')!=1 or not isinstance(fields,list) or len(fields)>40:raise HubError('模块配置表单声明无效')
    names=set()
    for f in fields:
        if not isinstance(f,dict):raise HubError('模块字段必须是对象')
        name=f.get('name','')
        if not isinstance(name,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',name) or name in names or f.get('type') not in TYPES:raise HubError('模块配置字段声明无效')
        if not isinstance(f.get('label',name),str) or not isinstance(f.get('max_length',4096),int) or not 1<=f.get('max_length',4096)<=100000:raise HubError('模块字段标签或长度声明无效')
        if f['type']=='select':
            options=f.get('options',[])
            if not isinstance(options,list) or not options or len(options)>500 or any(not isinstance(o,dict) or not isinstance(o.get('value'),str) or not isinstance(o.get('label'),str) for o in options):raise HubError('模块下拉选项声明无效')
        names.add(name)
    return value

def validate(spec,values):
    if not isinstance(values,dict):raise HubError('模块配置必须是对象')
    fields={f['name']:f for f in spec['fields']}
    if set(values)-set(fields):raise HubError('包含模块未声明的字段')
    for name,value in values.items():
        f=fields[name];kind=f['type'];label=f.get('label',name)
        if kind=='boolean':valid=isinstance(value,bool)
        elif kind=='integer':valid=isinstance(value,int) and not isinstance(value,bool) and f.get('min',-2147483648)<=value<=f.get('max',2147483647)
        elif kind=='string_list':valid=isinstance(value,list) and len(value)<=100 and all(isinstance(x,str) and len(x)<=200 for x in value)
        else:valid=isinstance(value,str) and len(value)<=f.get('max_length',4096)
        if not valid:raise HubError(label+'：值或长度无效')
        if f.get('required') and not value and kind not in ('secret','integer','boolean'):raise HubError(label+'：不能为空')
        if kind=='select' and value not in [o['value'] for o in f.get('options',[])]:raise HubError(label+'：选项无效')
        if kind=='url' and value:
            try:p=urlsplit(value)
            except ValueError:raise HubError(label+'：地址无效') from None
            if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment or any(c.isspace() for c in value):raise HubError(label+'：地址无效')
    return values

def configure(registry,connection,manifest,hook,values=None):
    spec=schema(manifest)
    if values is not None and spec:validate(spec,values)
    if hook:
        result=hook(registry,connection,values)
    else:
        result=generic(registry,connection,manifest,values)
    if spec:result['schema']=spec
    return result

def generic(registry,connection,manifest,values=None):
    # Use the same secure per-connection vault as every provider module.
    from .module_credentials import saved,setting_key,identity,store_key,key_present
    spec=schema(manifest)
    if not spec:raise HubError('模块未声明配置字段')
    current=saved(registry,connection)
    if values is not None:
        proposed={f['name']:current.get(f['name'],f.get('default',False if f['type']=='boolean' else [] if f['type']=='string_list' else '')) for f in spec['fields'] if f['type']!='secret'}
        proposed.update({k:v for k,v in values.items() if next(f for f in spec['fields'] if f['name']==k)['type']!='secret'})
        validate(spec,proposed)
        for f in spec['fields']:
            if f['type']=='secret' and f.get('required') and not values.get(f['name']) and not key_present(registry,{**connection,'id':connection['id']+':'+f['name']}):raise HubError(f.get('label',f['name'])+'：不能为空')
        assigned=[a['id'] for a in registry.rows('agent_profiles') if a['connection_id']==connection['id']]
        with registry.lock,registry.server.workflows.lock:
            if registry.busy(assigned):raise HubError('此接入仍有任务运行，请结束后修改')
            if any(w.get('status') in ('active','paused','blocked','needs_attention') and set(assigned)&set([w.get('manager')]+w.get('agents',[])) for w in registry.server.workflows.snapshot('user')):raise HubError('此接入仍被未结束项目使用，请结束项目或新建独立连接')
            for f in spec['fields']:
                name=f['name']
                if name not in values:continue
                if f['type']=='secret':
                    if values[name]:store_key(registry,{**connection,'id':connection['id']+':'+name},values[name])
                else:current[name]=values[name]
            with registry.hub.tx():registry.hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(setting_key(connection),json.dumps(current)))
    defaults={f['name']:f.get('default',False if f['type']=='boolean' else [] if f['type']=='string_list' else '') for f in spec['fields'] if f['type']!='secret'}
    return {'config':{**defaults,**current},'secrets':{f['name']:key_present(registry,{**connection,'id':connection['id']+':'+f['name']}) for f in spec['fields'] if f['type']=='secret'}}

def resolved(registry,connection,manifest):
    """Module-only view, including secrets; never use in an HTTP response."""
    from .module_credentials import get_key
    value=generic(registry,connection,manifest)['config']
    for f in schema(manifest)['fields']:
        if f['type']=='secret':
            try:value[f['name']]=get_key(registry,{**connection,'id':connection['id']+':'+f['name']},{},{'config':{'options':{}}})
            except HubError:value[f['name']]=''
    return value
