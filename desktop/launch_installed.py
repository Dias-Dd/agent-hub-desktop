"""Two independent executables, one immutable bundled dependency directory."""
import sys,os
from pathlib import Path

if Path(sys.executable).stem.casefold().startswith('agenthubmcp'):
    from hub.mcp import main
elif Path(sys.executable).stem.casefold().startswith('agenthubsetup'):
    from desktop.onboarding import main
else:
    from desktop.launch_desktop import main

if __name__=='__main__':
    if getattr(sys,'frozen',False):
        if sys.stdout is None:sys.stdout=open(os.devnull,'w')
        if sys.stderr is None:sys.stderr=open(os.devnull,'w')
    sys.exit(main())
