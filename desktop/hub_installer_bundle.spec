# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys,uuid
from PyInstaller.utils.hooks import collect_submodules
root=Path(SPECPATH).parent
sys.path.insert(0,str(root))
from desktop.native_webview import find_loader
loader=find_loader()
if not loader:raise RuntimeError('WebView2Loader.dll missing')
from desktop.adapter_assets import collect
modules=collect(root)
assets=modules+[(str(root/'hub/adapter_examples'),'hub/adapter_examples'),(str(root/'hub/static'),'hub/static'),(str(root/'hub/mcp.py'),'hub'),(str(root/'desktop/app.ico'),'desktop')]
assets += [(str(root/'tools'/name),'tools') for name in ('HubDesktopAgent.ps1','Configure-HubVmUnattended.ps1','Start-HubVmBridge.ps1')]
a=Analysis([str(root/'desktop/launch_installed.py')],pathex=[str(root)],binaries=[(loader,'desktop')],datas=assets,hiddenimports=collect_submodules('hub')+collect_submodules('desktop'),excludes=['tests','PySide6','PyQt5','webview'])
pyz=PYZ(a.pure)
folder='_runtime-setup-'+uuid.uuid4().hex[:12]
options=dict(exclude_binaries=True,contents_directory=folder,debug=False,strip=False,upx=False,console=False,manifest=str(root/'desktop/hub_desktop.manifest'),icon=str(root/'desktop/app.ico'))
main=EXE(pyz,a.scripts,[],name='AgentMessageHubDesktop',**options)
wizard=EXE(pyz,a.scripts,[],name='AgentHubSetup',**options)
mcp=EXE(pyz,a.scripts,[],name='AgentHubMcp',**{**options,'console':True})
coll=COLLECT(main,wizard,mcp,a.binaries,a.datas,strip=False,upx=False,name='AgentHub')
