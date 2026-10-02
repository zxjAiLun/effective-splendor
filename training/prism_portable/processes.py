"""Owned Windows Job Objects / Linux systemd cgroups with bounded supervision."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .common import component, read, write


def directory_bytes(root):
    total = 0
    for p in Path(root).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except FileNotFoundError:
            pass
    return total


def systemctl(*args, check=True):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                          check=check, timeout=15)


def unit_properties(unit):
    result = systemctl("show", unit, "--property=ControlGroup,ActiveState,SubState,"
                      "CPUUsageNSec,MemoryPeak,ExecMainStatus", check=False)
    if result.returncode:
        return {}
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def cgroup_accounting(unit):
    props = unit_properties(unit)
    cg = props.get("ControlGroup", "")
    result = {"cpu_seconds": 0.0, "user_cpu_seconds": 0.0, "kernel_cpu_seconds": 0.0,
              "active_processes": 0, "peak_memory_bytes": None,
              "accounting_scope": "owned systemd cgroup including descendants"}
    if cg:
        root = Path("/sys/fs/cgroup") / cg.lstrip("/")
        try:
            counters = dict(line.split() for line in (root / "cpu.stat").read_text().splitlines())
            result.update(cpu_seconds=int(counters["usage_usec"]) / 1e6,
                          user_cpu_seconds=int(counters["user_usec"]) / 1e6,
                          kernel_cpu_seconds=int(counters["system_usec"]) / 1e6,
                          active_processes=len((root / "cgroup.procs").read_text().splitlines()),
                          peak_memory_bytes=int((root / "memory.peak").read_text()))
            return result
        except (FileNotFoundError, KeyError, ValueError):
            pass
    usage = props.get("CPUUsageNSec", "")
    if usage.isdecimal():
        result["cpu_seconds"] = int(usage) / 1e9
        # Do not invent a split after a cgroup has disappeared.
        result["user_cpu_seconds"] = result["kernel_cpu_seconds"] = None
    peak = props.get("MemoryPeak", "")
    if peak.isdecimal():
        result["peak_memory_bytes"] = int(peak)
    return result


class LinuxProcess:
    def __init__(self, tree, pid):
        self.tree, self.pid = tree, pid

    def poll(self):
        if self.tree.record.exists():
            row = read(self.tree.record)
            if row["status"] == "FINISHED":
                return row["returncode"]
        if unit_properties(self.tree.unit).get("ActiveState") in ("failed", "inactive"):
            return -9
        return None

    def wait(self, timeout=10):
        deadline = time.monotonic() + timeout
        while self.poll() is None:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.tree.unit, timeout)
            time.sleep(0.05)
        return self.poll()


class ProcessTree:
    def __init__(self, *, cpu_seconds, memory_bytes, max_processes=6):
        if cpu_seconds <= 0 or memory_bytes <= 0:
            raise ValueError("positive process budget required")
        self.cpu_seconds, self.memory_bytes = cpu_seconds, memory_bytes
        self.max_processes = max_processes
        self.process = None
        self.last = None
        self.closed = False
        self.windows = None
        if os.name == "nt":
            from .engine.ppo.processes import ProcessTree as WindowsTree
            self.windows = WindowsTree(cpu_seconds=cpu_seconds, memory_bytes=memory_bytes,
                                       max_processes=max_processes)
        elif sys.platform != "linux":
            raise ValueError("portable execution supports Windows/Linux only")

    def start(self, argv, *, cwd, stdout, stderr):
        if self.process is not None:
            raise ValueError("owned tree is single-use")
        if self.windows:
            self.process = self.windows.start(argv, cwd=cwd, stdout=stdout, stderr=stderr)
            return self.process
        token = uuid.uuid4().hex
        self.unit = "prism-ppo-tree-" + token + ".service"
        control = Path(os.environ.get("PRISM_PPO_CONTROL_DIR", cwd)) / "trees"
        control.mkdir(parents=True, exist_ok=True)
        self.record, self.release = control / (token + ".json"), control / (token + ".release.json")
        out = str(Path(stdout.name).resolve()) if stdout is not None else str(control / (token + ".stdout.log"))
        err = str(Path(stderr.name).resolve()) if stderr is not None else str(control / (token + ".stderr.log"))
        command = ["systemd-run", "--user", "--quiet", "--unit=" + self.unit,
                   "--property=Type=exec", "--property=KillMode=control-group",
                   "--property=CPUAccounting=yes", "--property=MemoryAccounting=yes",
                   "--property=MemoryMax=" + str(self.memory_bytes),
                   "--property=TasksMax=" + str(max(32, self.max_processes * 16)),
                   "--property=RuntimeMaxSec=" + str(max(60, self.cpu_seconds * 2)),
                   "--working-directory=" + str(Path(cwd).resolve())]
        slice_name = os.environ.get("PRISM_PPO_SLICE")
        if slice_name:
            component(slice_name.removesuffix(".slice"))
            if not slice_name.startswith("prism-ppo-"):
                raise ValueError("unowned systemd slice")
            command.append("--slice=" + slice_name)
        for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "PRISM_PPO_CONTROL_DIR",
                    "PRISM_PPO_SLICE", "PRISM_PPO_CANCEL_FIXTURE", "PRISM_PPO_HOST_ID", "PRISM_PPO_OWNER_NONCE"):
            if key in os.environ:
                command.append("--setenv=" + key + "=" + os.environ[key])
        command += [sys.executable, "-B", "-m", "training.prism_portable.cgroup_entry",
                    "--record", str(self.record), "--release", str(self.release),
                    "--stdout", out, "--stderr", err, "--", *map(str, argv)]
        write(control / (token + ".owner.json"), {"unit": self.unit, "argv": list(map(str, argv)),
                                                "cpu_seconds": self.cpu_seconds, "owner_nonce": os.environ.get("PRISM_PPO_OWNER_NONCE")})
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
        deadline = time.monotonic() + 15
        while not self.record.exists():
            if time.monotonic() > deadline or unit_properties(self.unit).get("ActiveState") == "failed":
                self.terminate()
                raise RuntimeError("owned systemd command did not start")
            time.sleep(0.05)
        self.process = LinuxProcess(self, read(self.record)["pid"])
        return self.process

    def accounting(self):
        if self.closed:
            return self.last
        if self.windows:
            result = self.windows.accounting()
            from .engine.ppo.processes import _Extended
            value = _Extended()
            if self.windows.api.QueryInformationJobObject(self.windows.handle, 9, ctypes.byref(value),
                                                          ctypes.sizeof(value), None):
                result["peak_memory_bytes"] = value.PeakJobMemoryUsed
            else:
                result["peak_memory_bytes"] = None
            result["cpu_seconds"] = result["user_cpu_seconds"] + result["kernel_cpu_seconds"]
            result["accounting_scope"] = "owned Windows Job Object including descendants"
        else:
            result = cgroup_accounting(self.unit)
        self.last = result
        return result

    def terminate(self):
        if self.windows:
            if self.windows.handle:
                self.windows.api.TerminateJobObject(self.windows.handle, 124)
        elif hasattr(self, "unit"):
            systemctl("kill", "--kill-whom=all", "--signal=SIGKILL", self.unit, check=False)
            systemctl("stop", self.unit, check=False)

    def wait(self, *, wall_seconds, storage_root=None, max_storage_bytes=None,
             stop_checker=None, snapshot=None, accounting=None, storage_interval=5.0):
        started = time.monotonic()
        reason = None
        next_storage = next_snapshot = 0.0
        while self.process.poll() is None:
            now = time.monotonic()
            counters = accounting() if accounting else self.accounting()
            if snapshot and now >= next_snapshot:
                snapshot(counters)
                next_snapshot = now + 1.0
            if now - started >= wall_seconds:
                reason = "wall_deadline"
            elif counters["cpu_seconds"] >= self.cpu_seconds:
                reason = "cpu_deadline"
            elif stop_checker:
                reason = stop_checker()
            if storage_root is not None and now >= next_storage:
                next_storage = now + storage_interval
                if directory_bytes(storage_root) > max_storage_bytes:
                    reason = "storage_deadline"
            if reason:
                self.terminate()
                break
            time.sleep(0.1)
        code = self.process.wait(timeout=15)
        counters = accounting() if accounting else self.accounting()
        if storage_root is not None and directory_bytes(storage_root) > max_storage_bytes:
            reason = "storage_deadline"
        return counters | {"returncode": code, "stop_reason": reason,
                           "wall_seconds": time.monotonic() - started,
                           "storage_scan_interval_seconds": storage_interval}

    def close(self):
        if not self.closed:
            if self.process is not None:
                self.accounting()
                if self.windows:
                    self.windows.close()
                else:
                    write(self.release, {"release": True})
                    # Also kills any child left behind by an exited executable.
                    self.terminate()
            elif self.windows:
                self.windows.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
