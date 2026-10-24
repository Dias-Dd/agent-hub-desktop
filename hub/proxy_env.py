"""Bridge the user's existing Windows system proxy to CLI child environments.

No system changes, PAC execution, credentials lookup, or TLS interception.
"""
import ipaddress
import os
from urllib.parse import urlsplit,urlunsplit

def windows_settings():
    if os.name!='nt':return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:
            def value(name,default=None):
                try:return winreg.QueryValueEx(key,name)[0]
                except OSError:return default
            return {'enabled':bool(value('ProxyEnable',0)),'server':value('ProxyServer',''),'bypass':value('ProxyOverride',''),'pac':bool(value('AutoConfigURL',''))}
    except OSError:return None

def proxy_url(value):
    value=value.strip()
    if not value:return None
    if '://' not in value:value='http://'+value
    try:
        url=urlsplit(value)
        if url.scheme not in ('http','https') or not url.hostname or url.path not in ('','/') or url.query or url.fragment:return None
        _=url.port
        return value
    except ValueError:return None

def bypass_values(raw):
    values=['localhost','127.0.0.1','::1']
    for value in raw.split(';'):
        value=value.strip()
        if not value or value=='<local>':continue
        if value.startswith('*') and len(value)>1:
            values.append('.'+value.lstrip('*.'));continue
        if '*' in value:
            parts=value.split('.')
            prefix=[]
            for part in parts:
                if part=='*':break
                if not part.isdigit() or not 0<=int(part)<=255:prefix=[];break
                prefix.append(part)
            if prefix and len(prefix)<4 and all(p=='*' for p in parts[len(prefix):]):
                values.append(str(ipaddress.ip_network('.'.join(prefix+['0']*(4-len(prefix)))+'/'+str(8*len(prefix)),strict=False)))
            continue
        values.append(value)
    return list(dict.fromkeys(values))

def inherit_system_proxy(environment,settings=None):
    env=dict(environment)
    # Explicit process configuration wins, including lower-case variants.
    if any(env.get(k) for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy')):return env
    info=windows_settings() if settings is None else settings
    if not info or not info.get('enabled'):return env
    raw=info.get('server','')
    if '=' in raw:
        for item in raw.split(';'):
            if '=' not in item:continue
            protocol,address=item.split('=',1);protocol=protocol.strip().lower();address=proxy_url(address)
            if protocol in ('http','https') and address:env[protocol.upper()+'_PROXY']=address
    else:
        address=proxy_url(raw)
        if address:env.update(HTTP_PROXY=address,HTTPS_PROXY=address)
    if ('HTTP_PROXY' in env or 'HTTPS_PROXY' in env) and not any(env.get(k) for k in ('NO_PROXY','no_proxy')):
        env['NO_PROXY']=','.join(bypass_values(info.get('bypass','')))
    return env

def describe(environment):
    safe={}
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        value=environment.get(key)
        if not value:continue
        try:
            url=urlsplit(value if '://' in value else 'http://'+value)
            host=url.hostname or 'unknown'
            if ':' in host:host='['+host+']'
            safe[key]=urlunsplit((url.scheme,host+(':'+str(url.port) if url.port else ''),'','',''))
        except ValueError:safe[key]='configured'
    return {'proxy_configured':bool(safe),'endpoints_without_credentials':safe}
