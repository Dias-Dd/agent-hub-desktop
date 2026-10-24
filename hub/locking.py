from pathlib import Path
import sys

def acquire(directory,name):
    Path(directory).mkdir(parents=True,exist_ok=True)
    handle=open(Path(directory)/name,'a+b')
    handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0)
    try:
        if sys.platform=='win32':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError('another process owns this data directory: '+name) from None
    return handle
