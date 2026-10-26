"""Connection-scoped settings and OS-protected secrets for all modules."""
import hashlib
import json
import os
import sys
from hub.core import HubError

def identity(connection):return hashlib.sha256(connection['id'].encode()).hexdigest()[:24]
def setting_key(connection):return 'opencode_provider:'+identity(connection)
def secret_path(registry,connection):return registry.hub.directory/'provider-secrets'/(identity(connection)+'.dpapi')


def saved(registry,connection):
    with registry.hub.lock:row=registry.hub.db.execute('SELECT value FROM settings WHERE key=?',(setting_key(connection),)).fetchone()
    return json.loads(row[0]) if row else {}


def keychain(registry,connection):
    from hub.macos_keychain import Keychain
    return Keychain(registry.hub.directory,account='opencode-'+identity(connection))


def key_present(registry,connection):
    if sys.platform=='darwin':
        chain=keychain(registry,connection);value,item=chain.find(False)
        if item:chain.cf.CFRelease(item)
        return bool(value)
    return secret_path(registry,connection).is_file()


def store_key(registry,connection,value):
    if sys.platform=='darwin':return keychain(registry,connection).set(value)
    if os.name!='nt':raise HubError('此系统请使用密钥环境变量；不降级为明文存储')
    from hub.deepseek_runtime import protect
    path=secret_path(registry,connection);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.new');tmp.write_bytes(protect(value.encode()));tmp.replace(path)


def get_key(registry,connection,config,variant):
    env_name=config.get('key_env','')
    if env_name:
        value=os.environ.get(env_name,'')
        if not value:raise HubError('未找到供应商密钥环境变量：'+env_name)
        return value
    if sys.platform=='darwin':
        value=keychain(registry,connection).get()
        if value:return value
    elif secret_path(registry,connection).is_file():
        from hub.deepseek_runtime import protect
        return protect(secret_path(registry,connection).read_bytes(),True).decode()
    if variant['config']['options'].get('apiKey') in ('ollama','no-key','dummy'):
        return variant['config']['options']['apiKey']
    raise HubError('请先为此接入配置 API Key 或密钥环境变量')

