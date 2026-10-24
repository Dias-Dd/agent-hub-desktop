import json
from pathlib import Path
import re
import sys

_catalog=None

def translate(source,language):
    global _catalog
    if language!='en' or not isinstance(source,str):return source
    if _catalog is None:
        root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
        _catalog=json.loads((root/'hub/static/i18n.json').read_text(encoding='utf-8'))
    if source in _catalog:return _catalog[source]
    patterns=[(r'^(\d+) / 6  ·  Agent 接入  →  经理  →  虚拟机$',r'\1 / 6  ·  Agents  →  Manager  →  Virtual machine'),
              (r'^已读取 (\d+) 个模型。目录可读不代表账号一定拥有全部模型权限。$',r'Read \1 models. Catalog access does not guarantee access to every model.'),
              (r'^已接入：(.*)$',r'Connected: \1'),(r'^项目经理：(.*)$',r'Project manager: \1')]
    for pattern,replacement in patterns:
        if re.match(pattern,source):return re.sub(pattern,replacement,source)
    if '\n' in source:return '\n'.join(translate(line,language) for line in source.split('\n'))
    if source.startswith('执行权限：'):
        permission,_,directory=source[len('执行权限：'):].partition(' · 工作目录：')
        return 'Execution permissions: '+translate(permission,language)+' · Working directory: '+directory
    for prefix in ('虚拟机命令连接已建立。桌面状态：','请在官方界面登录，并按接入要求设置 '):
        if source.startswith(prefix):return _catalog[prefix]+source[len(prefix):]
    return source
