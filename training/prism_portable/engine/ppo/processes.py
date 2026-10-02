"""Windows process-tree supervision; only processes created here are managed.

Start suspended, assign to a Job Object, then resume: descendants cannot escape
between spawn and assignment. Kill-on-close also handles supervisor crashes.
"""
import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import time


class _IO(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _Basic(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong),
                ('PerJobUserTimeLimit', ctypes.c_longlong), ('LimitFlags', W.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', W.DWORD), ('Affinity', ctypes.c_size_t),
                ('PriorityClass', W.DWORD), ('SchedulingClass', W.DWORD)]


class _Extended(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _Basic), ('IoInfo', _IO),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [('TotalUserTime', ctypes.c_longlong), ('TotalKernelTime', ctypes.c_longlong),
                ('ThisPeriodTotalUserTime', ctypes.c_longlong), ('ThisPeriodTotalKernelTime', ctypes.c_longlong),
                ('TotalPageFaultCount', W.DWORD), ('TotalProcesses', W.DWORD),
                ('ActiveProcesses', W.DWORD), ('TotalTerminatedProcesses', W.DWORD)]


def directory_bytes(root):
    total = 0
    if Path(root).exists():
        for p in Path(root).rglob('*'):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except FileNotFoundError:
                pass  # atomic publication can replace temporary names
    return total


class ProcessTree:
    def __init__(self, *, cpu_seconds, memory_bytes, max_processes=6):
        if os.name != 'nt':
            raise ValueError('live launcher currently requires Windows Job Objects')
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [W.LPVOID, W.LPCWSTR]
        self.api.CreateJobObjectW.restype = W.HANDLE
        self.api.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD]
        self.api.SetInformationJobObject.restype = W.BOOL
        self.api.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
        self.api.AssignProcessToJobObject.restype = W.BOOL
        self.api.QueryInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD, W.LPVOID]
        self.api.QueryInformationJobObject.restype = W.BOOL
        self.api.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
        self.api.TerminateJobObject.restype = W.BOOL
        self.api.CloseHandle.argtypes = [W.HANDLE]
        self.api.CloseHandle.restype = W.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _Extended()
        # JOB_TIME | ACTIVE_PROCESS | JOB_MEMORY | KILL_ON_JOB_CLOSE
        limits.BasicLimitInformation.LimitFlags = 0x4 | 0x8 | 0x200 | 0x2000
        limits.BasicLimitInformation.PerJobUserTimeLimit = int(cpu_seconds * 10_000_000)
        limits.BasicLimitInformation.ActiveProcessLimit = max_processes
        limits.JobMemoryLimit = memory_bytes
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        self.process = None

    def start(self, argv, *, cwd, stdout, stderr):
        if self.process is not None:
            raise ValueError('process tree is single-use')
        p = subprocess.Popen(argv, cwd=cwd, stdout=stdout, stderr=stderr,
                             stdin=subprocess.DEVNULL, creationflags=0x4)  # CREATE_SUSPENDED
        self.process = p
        try:
            if not self.api.AssignProcessToJobObject(self.handle, W.HANDLE(int(p._handle))):
                raise ctypes.WinError(ctypes.get_last_error())
            resume = ctypes.WinDLL('ntdll').NtResumeProcess
            resume.argtypes = [W.HANDLE]
            resume.restype = ctypes.c_long
            if resume(W.HANDLE(int(p._handle))) != 0:
                raise RuntimeError('could not resume owned process')
        except BaseException:
            p.kill(); p.wait()
            self.close()
            raise
        return p

    def accounting(self):
        value = _Accounting()
        if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return {'user_cpu_seconds': value.TotalUserTime / 10_000_000,
                'kernel_cpu_seconds': value.TotalKernelTime / 10_000_000,
                'total_processes': value.TotalProcesses, 'active_processes': value.ActiveProcesses}

    def wait(self, *, wall_seconds, storage_root=None, max_storage_bytes=None):
        started = time.monotonic()
        reason = None
        while self.process.poll() is None:
            if time.monotonic() - started >= wall_seconds:
                reason = 'wall_deadline'
            elif storage_root is not None and directory_bytes(storage_root) > max_storage_bytes:
                reason = 'storage_deadline'
            if reason:
                self.api.TerminateJobObject(self.handle, 124)
                break
            time.sleep(0.1)
        code = self.process.wait(timeout=10)
        result = self.accounting() | {'returncode': code, 'stop_reason': reason,
                                      'wall_seconds': time.monotonic() - started}
        return result

    def close(self):
        if getattr(self, 'handle', None):
            self.api.CloseHandle(self.handle)  # also kills remaining descendants
            self.handle = None
        if getattr(self, 'process', None) is not None and self.process.poll() is None:
            self.process.wait(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
