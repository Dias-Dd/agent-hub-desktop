# Local arm64 .app build. Ad-hoc signing only; no release/notarization implied.
from pathlib import Path
import tomllib

root = Path(SPECPATH).parent
version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
import sys
sys.path.insert(0,str(root))
from desktop.adapter_assets import collect
adapter_data=collect(root)
# Enumerate sources explicitly: the spec executes before Analysis applies pathex,
# so collect_submodules('hub') can silently miss modules with this CLI layout.
hub_modules = ['hub'] + sorted('.'.join(p.relative_to(root).with_suffix('').parts)
                              for p in (root/'hub').rglob('*.py')
                              if p.name != '__init__.py')
a = Analysis([str(root / 'desktop/launch_desktop.py')], pathex=[str(root)],
    binaries=[], datas=adapter_data + [
        (str(root / 'hub/static'), 'hub/static'),
        (str(root / 'hub/adapter_examples'), 'hub/adapter_examples'),
        (str(root / 'hub/mcp.py'), 'hub'),
        *[(str(root / 'tools' / name), 'tools') for name in
          ('HubDesktopAgent.ps1','Configure-HubVmUnattended.ps1','Start-HubVmBridge.ps1')]],
    hiddenimports=hub_modules + ['desktop.macos_webview',
        'desktop.macos_notifications', 'desktop.macos_tray', 'desktop.first_run', 'desktop.tray_status', 'AppKit', 'WebKit',
        'UserNotifications', 'PyObjCTools.AppHelper'],
    excludes=['tests','tkinter','desktop.onboarding','desktop.native_webview',
              'PySide6','PyQt5','webview'], hookspath=[], runtime_hooks=[])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AgentHub',
          debug=False, strip=False, upx=False, console=False, target_arch='arm64')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AgentHub')
app = BUNDLE(coll, name='Agent Hub.app', bundle_identifier='com.agenthub.desktop',
    icon=str(root/'desktop/app.icns'),
    info_plist={'CFBundleName':'Agent Hub', 'CFBundleDisplayName':'Agent Hub',
                'CFBundleShortVersionString':version, 'CFBundleVersion':version,
                'NSHighResolutionCapable':True, 'LSMinimumSystemVersion':'14.0',
                'NSAppTransportSecurity': {'NSAllowsLocalNetworking':True}})
