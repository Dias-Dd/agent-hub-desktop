"""Owned CLI lifetime: Windows Job Object or an isolated POSIX process group.

POSIX groups cover cooperative cancellation/normal host shutdown, not SIGKILL
of the host. Callers must spawn with start_new_session=True on POSIX.
"""
import os
import signal
import threading

class ProcessJob:
    def __init__(self,proc):
        self.handle=None;self.close_lock=threading.Lock()
        self.proc=proc
        self.pgid=None
        if os.name!='nt':
            try:
                if os.getpgid(proc.pid)!=proc.pid:
                    raise RuntimeError('CLI must be started in its own POSIX session')
                self.pgid=proc.pid
            except ProcessLookupError:
                pass  # Already exited; never signal the Hub's process group.
            return
        import ctypes
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_=[('per_process',ctypes.c_longlong),('per_job',ctypes.c_longlong),('flags',w.DWORD),('min_working',ctypes.c_size_t),('max_working',ctypes.c_size_t),('active_limit',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];kernel.CreateJobObjectW.restype=w.HANDLE
        kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD];kernel.SetInformationJobObject.restype=w.BOOL
        kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
        kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];kernel.AssignProcessToJobObject.restype=w.BOOL
        kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
        handle=kernel.CreateJobObjectW(None,None)
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        self.kernel=kernel;self.handle=handle
        limits=Extended();limits.basic.flags=0x2000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        process=kernel.OpenProcess(0x0100|0x0001,False,proc.pid)
        try:
            if not kernel.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)) or not process or not kernel.AssignProcessToJobObject(handle,process):raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            self.close();raise
        finally:
            if process:kernel.CloseHandle(process)

    def close(self):
        with self.close_lock:
            if self.pgid:
                # Reap a finished group leader first: Darwin returns EPERM for
                # a group containing only its unreaped zombie. Descendants still
                # receive SIGKILL after the leader has been reaped.
                self.proc.poll()
                try:os.killpg(self.pgid,signal.SIGKILL)
                except ProcessLookupError:pass
                self.pgid=None
            if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None
