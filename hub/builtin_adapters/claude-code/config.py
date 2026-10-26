"""Read-only provider configuration; never copy or rewrite account credentials.

settings_path is adapted from CC Switch get_claude_settings_path (MIT).
See THIRD_PARTY_NOTICES.md for provenance. The full license travels with copied modules:

MIT License

Copyright (c) 2025 Jason Young

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import json
import os
import re
import subprocess
from pathlib import Path
from hub.cli_paths import which, cli_environment
from hub.core import HubError


def executable(supplied=''):
    if supplied:
        path=Path(supplied).expanduser()
        return str(path.resolve()) if path.is_file() else None
    for name in ('claude.exe','claude.cmd','claude') if os.name=='nt' else ('claude',):
        found=which(name)
        if found:return found
    bases=[Path.home()/'.local/bin',Path.home()/'.claude/local',Path.home()/'.npm-global/bin']
    if os.environ.get('APPDATA'):bases.append(Path(os.environ['APPDATA'])/'npm')
    for base in bases:
        for name in ('claude.exe','claude.cmd','claude') if os.name=='nt' else ('claude',):
            if (base/name).is_file():return str((base/name).resolve())
    return None


def settings_path():
    root=Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home()/'.claude').expanduser()
    current=root/'settings.json'
    if current.exists():return current
    legacy=root/'claude.json'
    return legacy if legacy.exists() else current


def settings():
    path=settings_path()
    if not path.exists():return {}
    try:
        if path.stat().st_size>2*1024*1024:raise ValueError('size')
        value=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value,dict):raise ValueError('object')
        return value
    except (OSError,ValueError):raise HubError('Claude Code 配置无法读取，请先在官方 CLI 检查配置；未修改文件') from None


def environment():
    # Inherit provider routes and credentials exactly; only replace Hub's own
    # identity later. Do not read OAuth files or execute apiKeyHelper ourselves.
    return cli_environment({k:v for k,v in os.environ.items() if not k.startswith('HUB_')})


def inspect(connection):
    from hub.integrations import command
    exe=executable(connection.get('executable',''))
    if not exe:return {'state':'missing','message':'本机未安装 Claude Code，请通过官网安装后重新检测。'}
    try:
        result=subprocess.run(command([exe,'auth','status']),cwd=connection.get('cwd'),env=environment(),
            stdin=subprocess.DEVNULL,capture_output=True,encoding='utf-8',errors='replace',timeout=20,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        value=json.loads(result.stdout)
    except (OSError,ValueError,subprocess.TimeoutExpired):
        return {'state':'unknown','message':'无法读取 Claude Code 登录状态，请更新 CLI 或在官方终端确认登录。检查不会启动交互界面或调用模型。'}
    if not isinstance(value,dict):return {'state':'unknown','message':'Claude Code 登录检查未返回有效对象；请在官方终端确认。'}
    if value.get('loggedIn') is True and result.returncode==0:
        return {'state':'ready','message':'Claude Code 已配置认证；实际模型权限以调用结果为准。'}
    if value.get('loggedIn') is False:
        return {'state':'login','message':'Claude Code 尚未登录，请打开官方登录界面。'}
    return {'state':'unknown','message':'此 CLI 版本没有明确登录证据，请在官方终端确认。'}


def catalog(connection):
    if not executable(connection.get('executable','')):raise HubError('尚未安装 Claude Code，请先通过官网安装；未调用模型')
    config=settings()
    models={name:{'id':name,'name':name,'efforts':['default'],'source':'official_alias','inference_verified':False}
            for name in ('sonnet','opus','haiku')}
    env={**(config.get('env') if isinstance(config.get('env'),dict) else {}),**os.environ}
    values=[config.get('model'),env.get('ANTHROPIC_MODEL')]
    values += [env.get('ANTHROPIC_DEFAULT_'+name+'_MODEL') for name in ('SONNET','OPUS','HAIKU','FABLE')]
    values += config.get('availableModels',[]) if isinstance(config.get('availableModels'),list) else []
    for model in values:
        if isinstance(model,str) and len(model)<=200 and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/\[\]-]*',model):
            models[model]={'id':model,'name':model,'efforts':['default'],'source':'official_user_config','inference_verified':False}
    return {'models':list(models.values()),'catalog_complete':False,'catalog_status':'partial',
        'verification':'CLI 别名与本机配置，未验证实际模型权限，未发送推理请求',
        'probe_detail':'沿用 Claude Code 已有账号和服务商；列表为官方别名及用户配置，不是账号可用模型或额度清单。档位沿用 CLI 默认设置。'}
