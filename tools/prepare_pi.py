"""Reproducible Pi bundle and verified, platform-specific Node runtime."""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT/'hub/builtin_adapters/pi-api/engine'
NODE_VERSION='22.19.0'

def prepare():
    npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
    if not npm:raise RuntimeError('Build requires npm')
    subprocess.run([npm,'ci','--ignore-scripts'],cwd=ENGINE,check=True,shell=False)
    subprocess.run([shutil.which('node'),str(ENGINE/'node_modules/esbuild/bin/esbuild'),'bridge.mjs','--bundle','--platform=node',
        '--format=esm','--target=node22','--banner:js=import { createRequire } from "node:module"; const require = createRequire(import.meta.url);',
        '--legal-comments=external','--outfile=bridge.bundle.mjs'],cwd=ENGINE,check=True)
    notices=[]
    for path in sorted((ENGINE/'node_modules').rglob('*')):
        if path.is_file() and path.name.lower() in ('license','license.txt','license.md','notice','notice.txt'):
            notices.append(str(path.relative_to(ENGINE/'node_modules'))+'\n'+path.read_text(encoding='utf-8',errors='replace'))
    # Pi npm packages omit their MIT license file; keep it with the build sources.
    notices.append((ENGINE/'PI-LICENSE.txt').read_text(encoding='utf-8'))
    (ENGINE/'DEPENDENCY-LICENSES.txt').write_text('\n\n'.join(notices),encoding='utf-8')
    system='win' if os.name=='nt' else 'darwin' if platform.system()=='Darwin' else 'linux'
    arch='arm64' if platform.machine().lower() in ('arm64','aarch64') else 'x64'
    stem=f'node-v{NODE_VERSION}-{system}-{arch}';filename=stem+('.zip' if system=='win' else '.tar.gz')
    base=f'https://nodejs.org/dist/v{NODE_VERSION}/'
    checks=urllib.request.urlopen(base+'SHASUMS256.txt',timeout=45).read().decode()
    expected=next(line.split()[0] for line in checks.splitlines() if line.split()[-1]==filename)
    cache=ROOT/'.release-work'/filename;cache.parent.mkdir(exist_ok=True)
    if not cache.exists() or hashlib.sha256(cache.read_bytes()).hexdigest()!=expected:
        with urllib.request.urlopen(base+filename,timeout=120) as response:raw=response.read()
        if hashlib.sha256(raw).hexdigest()!=expected:raise RuntimeError('Node archive checksum mismatch')
        cache.write_bytes(raw)
    if system=='win':
        with zipfile.ZipFile(cache) as archive:
            (ENGINE/'node.exe').write_bytes(archive.read(stem+'/node.exe'))
            (ENGINE/'NODE-LICENSE.txt').write_bytes(archive.read(stem+'/LICENSE'))
    else:
        with tarfile.open(cache) as archive:
            (ENGINE/'node').write_bytes(archive.extractfile(stem+'/bin/node').read())
            (ENGINE/'NODE-LICENSE.txt').write_bytes(archive.extractfile(stem+'/LICENSE').read())
        (ENGINE/'node').chmod(0o755)
    print('Prepared Pi 1.4.0 and Node',NODE_VERSION,system,arch)

if __name__=='__main__':prepare()
