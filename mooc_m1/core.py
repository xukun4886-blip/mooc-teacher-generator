from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone


class Failure(Exception):
    def __init__(self, code, message, source=None, remedy=None):
        super().__init__(message)
        self.code, self.source, self.remedy = code, source, remedy

    def record(self):
        return {"code": self.code, "message": str(self), "source": self.source,
                "remedy": self.remedy}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def owned_windows_job(process):
    """Kill native descendants if the owner crashes, releasing the serial GPU.

    The handle is non-inheritable: closing it or terminating this process kills
    its assigned process tree. No unrelated process is inspected or terminated.
    """
    import ctypes
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_ = [('ProcessTime', ctypes.c_int64), ('JobTime', ctypes.c_int64), ('LimitFlags', wintypes.DWORD),
                    ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t),
                    ('ActiveProcessLimit', wintypes.DWORD), ('Affinity', ctypes.c_size_t),
                    ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ['ReadOperations', 'WriteOperations', 'OtherOperations', 'ReadBytes', 'WriteBytes', 'OtherBytes']]
    class Extended(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO), ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    operation = 'CreateJobObjectW'
    ok = bool(handle)
    if ok:
        operation = 'SetInformationJobObject'
        ok = bool(kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)))
    if ok:
        operation = 'AssignProcessToJobObject'
        ok = bool(kernel.AssignProcessToJobObject(handle, int(process._handle)))
    if not ok:
        error = ctypes.get_last_error()
        if handle:
            kernel.CloseHandle(handle)
        process.kill()
        process.communicate()
        raise Failure('PROCESS_OWNERSHIP_FAILED', f'Cannot fence native process: {operation}, Windows error {error}')
    return lambda: kernel.CloseHandle(handle)


def resume_windows_process(process):
    """Resume the sole primary thread after assigning the suspended child to a job.

    Popen closes the primary thread handle, so recover it using documented
    Toolhelp APIs. The child cannot exit or spawn descendants before fencing.
    """
    import ctypes
    from ctypes import wintypes
    class ThreadEntry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ThreadID', wintypes.DWORD), ('th32OwnerProcessID', wintypes.DWORD),
                    ('tpBasePri', wintypes.LONG), ('tpDeltaPri', wintypes.LONG), ('dwFlags', wintypes.DWORD)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Thread32First.argtypes = kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenThread.restype = wintypes.HANDLE
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise Failure('PROCESS_OWNERSHIP_FAILED', f'Thread snapshot failed, Windows error {ctypes.get_last_error()}')
    try:
        entry = ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == process.pid:
                handle = kernel.OpenThread(2, False, entry.th32ThreadID)  # THREAD_SUSPEND_RESUME
                if not handle:
                    break
                try:
                    if kernel.ResumeThread(handle) != 0xFFFFFFFF:
                        return
                finally:
                    kernel.CloseHandle(handle)
                break
            found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        raise Failure('PROCESS_OWNERSHIP_FAILED', f'Primary thread resume failed, Windows error {ctypes.get_last_error()}')
    finally:
        kernel.CloseHandle(snapshot)


def run(args, timeout=60, cwd=None, env=None, log_path=None):
    """No shell; on Windows terminate the owned child process tree on timeout."""
    started = time.perf_counter()
    env = dict(os.environ if env is None else env)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    stream = None
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        stream = Path(log_path).open("wb")
    try:
        p = subprocess.Popen([str(a) for a in args], cwd=cwd, env=env,
                             stdout=stream or subprocess.PIPE,
                             stderr=subprocess.STDOUT if stream else subprocess.PIPE,
                             creationflags=(subprocess.CREATE_NO_WINDOW | 4) if os.name == "nt" else 0)
    except (OSError, ValueError) as exc:
        if stream:
            stream.close()
        raise Failure("SERVICE_CONFIG_MISSING", "Cannot start configured executable", str(args[0])) from exc
    timed_out = False
    close_job = lambda: None
    try:
        if os.name == 'nt':
            close_job = owned_windows_job(p)
            resume_windows_process(p)
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            close_job()
            close_job = lambda: None
        else:
            p.kill()
        out, err = p.communicate()
        timed_out = True
    except BaseException:
        close_job()
        close_job = lambda: None
        if p.poll() is None:
            p.kill()
        p.communicate()
        raise
    finally:
        close_job()
        if stream:
            stream.close()
    if stream:
        out, err = Path(log_path).read_bytes(), b""
    out, err = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    if timed_out:
        raise Failure("TIMEOUT", "Operation exceeded configured timeout", str(args[0]))
    if p.returncode:
        code = "RESOURCE_INSUFFICIENT" if "out of memory" in err.lower() + out.lower() else "RUN_FAILED"
        # Raw model logs may contain teaching text; only store them in controlled storage.
        raise Failure(code, f"Process exited with code {p.returncode}", str(args[0]))
    return {"stdout": out, "stderr": err, "elapsed_seconds": time.perf_counter() - started}
