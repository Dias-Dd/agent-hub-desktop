"""
Build and Packaging Utility for Agent Message Hub Standalone Desktop App.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parent
ROOT_DIR = DESKTOP_DIR.parent
SPEC_FILE = DESKTOP_DIR / "hub_desktop_fast.spec"


def build():
    print("=" * 60)
    print("Agent Message Hub - Desktop Packaging Script")
    print("=" * 60)

    # Check if pyinstaller is available
    pyinstaller_found = shutil.which("pyinstaller") or shutil.which("pyinstaller.exe")
    if not pyinstaller_found:
        try:
            import PyInstaller
            pyinstaller_found = "python -m PyInstaller"
        except ImportError:
            pass

    if not pyinstaller_found:
        print("[NOTICE] PyInstaller is not installed in the current Python environment.")
        print("To build a standalone .exe distribution package:")
        print("  1. Run: pip install pyinstaller")
        print("  2. Re-run: python desktop/build_package.py")
        print("\nNote: The desktop app can already run directly via:")
        print("  python desktop/launch_desktop.py")
        print("  desktop/launch_desktop.ps1")
        print("  desktop/launch_desktop.cmd")
        return 2

    print(f"[+] Using PyInstaller: {pyinstaller_found}")
    import uuid
    dist_dir = DESKTOP_DIR / ("package-"+uuid.uuid4().hex[:12])
    build_dir = DESKTOP_DIR / "build"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        f"--distpath={dist_dir}",
        f"--workpath={build_dir}",
        str(SPEC_FILE),
    ]

    print(f"[+] Running build command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT_DIR), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000) if os.name == 'nt' else 0)
    if result.returncode == 0:
        try:
            from .deploy_release import publish
        except ImportError:
            from deploy_release import publish
        folder=dist_dir / "AgentMessageHubDesktop"
        release=publish(folder if folder.is_dir() else dist_dir, DESKTOP_DIR / "dist")
        print(f"[SUCCESS] Immutable desktop release: {release}")
    else:
        print(f"[ERROR] PyInstaller build failed with exit code {result.returncode}")
    return result.returncode


if __name__ == "__main__":
    sys.exit(build())
