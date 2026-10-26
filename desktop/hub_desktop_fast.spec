# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
root = Path(SPECPATH).parent
import sys
sys.path.insert(0, str(root))
from desktop.native_webview import find_loader
loader = find_loader()
if not loader:
    raise RuntimeError('A local WebView2Loader.dll is required for the native desktop build')
from desktop.adapter_assets import collect
adapter_data=collect(root)
a = Analysis([str(root / 'desktop' / 'launch_desktop.py')], pathex=[str(root)],
             binaries=[(loader, 'desktop')],
             datas=adapter_data + [(str(root / 'hub' / 'adapter_examples'), 'hub/adapter_examples'), (str(root / 'tools' / 'HubDesktopAgent.ps1'), 'tools'), (str(root / 'tools' / 'Configure-HubVmUnattended.ps1'), 'tools'), (str(root / 'tools' / 'Start-HubVmBridge.ps1'), 'tools'), (str(root / 'desktop' / 'app.ico'), 'desktop'), (str(root / 'hub' / 'static'), 'hub/static'), (str(root / 'hub' / 'mcp.py'), 'hub')],
             hiddenimports=collect_submodules('hub') + collect_submodules('desktop'), hookspath=[], runtime_hooks=[],
             excludes=['tests', 'PySide6', 'PyQt5', 'webview'])
import hashlib
runtime_hash=hashlib.sha256()
for source in sorted([*root.glob('hub/**/*.py'),*root.glob('hub/static/*'),*root.glob('desktop/*.py'),*root.glob('tools/*.ps1')]):
    if source.is_file():runtime_hash.update(source.read_bytes())
# Each build is immutable, even when the source tree is unchanged.
import uuid
runtime_folder='_runtime-'+runtime_hash.hexdigest()[:12]+'-'+uuid.uuid4().hex[:8]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, contents_directory=runtime_folder, name='AgentMessageHubDesktop',
          debug=False, strip=False, upx=False, console=False,
          manifest=str(root / 'desktop/hub_desktop.manifest'),icon=str(root / 'desktop/app.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AgentMessageHubDesktop')
