"""Package only adapter sources and the prepared Pi bundle, never node_modules."""
import os

def collect(root):
    base=root/'hub/builtin_adapters'
    files=[p for p in base.iterdir() if p.is_file() and p.suffix=='.py']+[p for folder in base.iterdir() if folder.is_dir() for p in folder.iterdir() if p.is_file() and p.suffix in ('.json','.py')]
    engine=base/'pi-api/engine'
    for name in ('bridge.bundle.mjs','bridge.bundle.mjs.LEGAL.txt','DEPENDENCY-LICENSES.txt','NODE-LICENSE.txt','node.exe' if os.name=='nt' else 'node'):
        path=engine/name
        if not path.is_file():raise RuntimeError('Run tools/prepare_pi.py before packaging: missing '+name)
        files.append(path)
    return [(str(p),str(p.parent.relative_to(root))) for p in files]
