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
adapter_data=[(str(p),str(p.parent.relative_to(root))) for p in (root/'hub/builtin_adapters').rglob('*') if p.is_file() and p.suffix in ('.py','.json')]
a = Analysis([str(root / 'desktop' / 'launch_desktop.py')], pathex=[str(root)],
             binaries=[(loader, 'desktop')],
             datas=adapter_data + [(str(root / 'hub' / 'adapter_examples'), 'hub/adapter_examples'), (str(root / 'tools' / 'HubDesktopAgent.ps1'), 'tools'), (str(root / 'tools' / 'Configure-HubVmUnattended.ps1'), 'tools'), (str(root / 'tools' / 'Start-HubVmBridge.ps1'), 'tools'), (str(root / 'desktop' / 'app.ico'), 'desktop'), (str(root / 'hub' / 'static'), 'hub/static'), (str(root / 'hub' / 'mcp.py'), 'hub')],
             hiddenimports=collect_submodules('hub') + collect_submodules('desktop'), hookspath=[], runtime_hooks=[],
             excludes=['tests', 'PySide6', 'PyQt5', 'webview'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='AgentMessageHubDesktop',
          debug=False, strip=False, upx=False, console=False,
          manifest=str(root / 'desktop/hub_desktop.manifest'),icon=str(root / 'desktop/app.ico'))
