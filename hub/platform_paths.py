"""Small OS boundaries shared by desktop workflows."""
import os
import subprocess
import sys
from pathlib import Path


def open_directory(path):
    target = Path(path).resolve()
    if not target.is_dir():
        raise OSError('Directory does not exist')
    if os.name == 'nt':
        os.startfile(str(target))
    else:
        subprocess.run(['/usr/bin/open' if sys.platform == 'darwin' else 'xdg-open', str(target)],
                       check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
