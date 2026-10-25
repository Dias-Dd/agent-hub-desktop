# Local arm64 .app build. Ad-hoc signing only; no release/notarization implied.
from pathlib import Path
import tomllib
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
adapter_data = [(str(p), str(p.parent.relative_to(root)))
                for p in (root / 'hub/builtin_adapters').rglob('*')
                if p.is_file() and p.suffix in ('.py', '.json')]
a = Analysis([str(root / 'desktop/launch_desktop.py')], pathex=[str(root)],
    binaries=[], datas=adapter_data + [
        (str(root / 'hub/static'), 'hub/static'),
        (str(root / 'hub/adapter_examples'), 'hub/adapter_examples'),
        (str(root / 'hub/mcp.py'), 'hub'),
        *[(str(root / 'tools' / name), 'tools') for name in
          ('HubDesktopAgent.ps1','Configure-HubVmUnattended.ps1','Start-HubVmBridge.ps1')]],
    hiddenimports=collect_submodules('hub') + ['desktop.macos_webview',
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
