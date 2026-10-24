"""Isolated frozen-runtime module check; no provider process or model call."""
import json
import shutil
import tempfile
from pathlib import Path
from .harness_adapters import prepare_layout,builtin_catalog
from .module_loader import load


def check():
    with tempfile.TemporaryDirectory(prefix='hub-module-self-test-') as directory:
        base=Path(directory);prepare_layout(base)
        loaded=[]
        for kind in builtin_catalog():
            module,manifest=load(base/'adapters'/'builtin'/kind)
            if not callable(module.execute):raise RuntimeError('module entry missing: '+kind)
            loaded.append(kind)
        source=base/'adapters/builtin/openrouter-api';copy=base/'adapters/custom/copied-api';shutil.copytree(source,copy)
        manifest=json.loads((copy/'adapter.json').read_text(encoding='utf-8'));manifest.update(id='copied-api',name='Copied module')
        (copy/'adapter.json').write_text(json.dumps(manifest),encoding='utf-8')
        copied,_=load(copy)
        sample=base/'adapters/custom/local-python';sample.mkdir()
        (sample/'adapter.json').write_text(json.dumps({'version':1,'id':'local-python','protocol':'hub-module-v1','entrypoint':'adapter.py'}),encoding='utf-8')
        (sample/'helper.py').write_text("value='FROZEN MODULE OK'",encoding='utf-8')
        (sample/'adapter.py').write_text('from .helper import value\ndef execute(context,run): return value\n',encoding='utf-8')
        user,_=load(sample);reply=user.execute(None,{})
        if reply!='FROZEN MODULE OK':raise RuntimeError('user module failed')
        return {'ok':True,'protocol':'hub-module-v1','builtin_modules':loaded,'copied_api_loads':callable(copied.execute),'user_python_executes':True,'external_python_required':False,'inference_sent':False}
