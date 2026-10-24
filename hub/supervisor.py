"""Resident non-model watchdog: restart crashed/unhealthy HTTP+worker child."""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--data',default='data');p.add_argument('--port',type=int,default=8765);p.add_argument('--no-sim',action='store_true')
    a=p.parse_args();directory=Path(a.data).resolve();directory.mkdir(parents=True,exist_ok=True)
    # OS process lock releases automatically on crash. Windows byte-range / POSIX flock.
    lock=open(directory/'supervisor.lock','a+b')
    lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
    try:
        if sys.platform=='win32':
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:raise SystemExit('Supervisor already running for this data directory')
    (directory/'supervisor.pid').write_text(str(os.getpid()))
    stopped=False;child=None
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    command=[sys.executable,'-m','hub.server','--data',str(directory),'--port',str(a.port)]+(['--no-sim'] if a.no_sim else [])
    failures=0
    try:
        while not stopped:
            child=subprocess.Popen(command,creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000) if os.name == 'nt' else 0)
            (directory/'service.pid').write_text(str(child.pid))
            started=time.monotonic();bad=0
            while not stopped and child.poll() is None:
                time.sleep(1)
                if time.monotonic()-started<5:continue
                try:
                    token=json.loads((directory/'credentials.json').read_text())['user']
                    req=urllib.request.Request(f'http://127.0.0.1:{a.port}/health',headers={'Authorization':'Bearer '+token})
                    with urllib.request.urlopen(req,timeout=2) as r:healthy=json.load(r)['ok']
                    if not healthy:raise ValueError()
                    bad=0
                except Exception:bad+=1
                if bad>=3:child.terminate();break
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait()
            if stopped:break
            failures=0 if time.monotonic()-started>30 else failures+1
            delay=min(30,2**min(failures,5))
            with open(directory/'supervisor.jsonl','a',encoding='utf-8') as log:log.write(json.dumps({'ts':time.time(),'event':'child.restart','exit_code':child.returncode,'delay':delay})+'\n')
            deadline=time.monotonic()+delay
            while not stopped and time.monotonic()<deadline:time.sleep(.25)
    finally:
        if child and child.poll() is None:child.terminate();child.wait(timeout=5)
        lock.close()

if __name__=='__main__':main()
