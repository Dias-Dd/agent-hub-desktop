"""Small non-secret UI preferences shared with the standalone setup program."""
import json
from pathlib import Path
import threading

_lock=threading.RLock()

def language(directory,default='zh-CN'):
    try:value=json.loads((Path(directory)/'ui-preferences.json').read_text(encoding='utf-8')).get('language')
    except (OSError,ValueError,AttributeError):return default
    return value if value in ('en','zh-CN') else default

def save_language(directory,value):
    if value not in ('en','zh-CN'):raise ValueError('Unsupported interface language')
    with _lock:
        path=Path(directory)/'ui-preferences.json';path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps({'language':value}),encoding='utf-8');temp.replace(path)
