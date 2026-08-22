"""Runtime guards and lightweight host telemetry for GPU training.

The M28B scientific recipe keeps ``num_workers=0``.  Runtime Repair 1 moves
feature encoding out of the training loop and deliberately caps the CPU
thread pools so that the host remains thermally stable while the GPU is fed.
"""

from __future__ import annotations

import ctypes
import glob
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

import torch


EXPECTED_CPU_THREADS = {"intra_op": 2, "inter_op": 1}
EXPECTED_THREAD_ENV = {
    "OMP_NUM_THREADS": "2",
    "MKL_NUM_THREADS": "2",
    "OPENBLAS_NUM_THREADS": "2",
    "NUMEXPR_NUM_THREADS": "2",
}


def validate_thread_environment(environ: Mapping[str, str] | None = None) -> None:
    """Reject a run unless every required BLAS/OpenMP cap is explicit."""

    values = os.environ if environ is None else environ
    mismatches = {
        name: (expected, values.get(name))
        for name, expected in EXPECTED_THREAD_ENV.items()
        if values.get(name) != expected
    }
    if mismatches:
        detail = ", ".join(
            f"{name}={actual!r} (expected {expected!r})"
            for name, (expected, actual) in sorted(mismatches.items())
        )
        raise RuntimeError(f"M28B Runtime Repair 1 requires explicit CPU thread caps: {detail}")


def configure_cpu_runtime() -> dict[str, Any]:
    """Apply and assert the fail-closed CPU runtime contract."""

    validate_thread_environment()
    torch.set_num_threads(EXPECTED_CPU_THREADS["intra_op"])
    try:
        torch.set_num_interop_threads(EXPECTED_CPU_THREADS["inter_op"])
    except RuntimeError as exc:
        raise RuntimeError(
            "M28B Runtime Repair 1 must set torch inter-op threads before parallel work"
        ) from exc
    actual = {
        "intra_op": torch.get_num_threads(),
        "inter_op": torch.get_num_interop_threads(),
        "environment": {name: os.environ[name] for name in EXPECTED_THREAD_ENV},
    }
    if actual["intra_op"] != EXPECTED_CPU_THREADS["intra_op"]:
        raise RuntimeError(f"unexpected torch intra-op thread count: {actual['intra_op']}")
    if actual["inter_op"] != EXPECTED_CPU_THREADS["inter_op"]:
        raise RuntimeError(f"unexpected torch inter-op thread count: {actual['inter_op']}")
    return actual


class NvmlCollector:
    """Lightweight direct NVML wrapper via ctypes without third-party dependencies."""

    def __init__(self):
        self._available = False
        self._handle = None
        self._nvml = None
        try:
            self._nvml = ctypes.CDLL("libnvidia-ml.so.1")
            if self._nvml.nvmlInit_v2() == 0:
                handle = ctypes.c_void_p()
                if self._nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) == 0:
                    self._handle = handle
                    self._available = True
        except Exception:
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    def sample_temperature(self) -> float | None:
        if not self._available or self._handle is None or self._nvml is None:
            return None
        try:
            temp = ctypes.c_uint()
            ret = self._nvml.nvmlDeviceGetTemperature(self._handle, 0, ctypes.byref(temp))
            if ret == 0:
                return float(temp.value)
            return None
        except Exception:
            return None

    def close(self):
        if self._available and self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._available = False
            self._handle = None
            self._nvml = None


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def cpu_temperatures_c() -> list[dict[str, Any]]:
    """Read available thermal-zone and hwmon temperatures with firmware trip points."""

    readings: list[dict[str, Any]] = []
    for raw_path in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")):
        path = Path(raw_path)
        value = _read_int(path)
        if value is None:
            continue
        tz_dir = path.parent
        type_path = tz_dir / "type"
        label = type_path.read_text(encoding="utf-8").strip() if type_path.exists() else tz_dir.name

        firmware_crit = None
        firmware_hot = None
        for trip_file in sorted(tz_dir.glob("trip_point_*_type")):
            try:
                trip_type = trip_file.read_text(encoding="utf-8").strip()
                prefix = trip_file.name[:-5]
                temp_file = tz_dir / f"{prefix}_temp"
                if temp_file.exists():
                    t_val = _read_int(temp_file)
                    if t_val is not None and t_val > 0:
                        c_val = t_val / 1000.0
                        if trip_type == "critical":
                            firmware_crit = min(firmware_crit, c_val) if firmware_crit else c_val
                        elif trip_type == "hot":
                            firmware_hot = min(firmware_hot, c_val) if firmware_hot else c_val
            except (OSError, ValueError):
                pass

        sensor_info: dict[str, Any] = {
            "source": str(path),
            "label": label,
            "celsius": value / 1000.0,
        }
        if firmware_crit is not None:
            sensor_info["firmware_crit"] = firmware_crit
        if firmware_hot is not None:
            sensor_info["firmware_hot"] = firmware_hot
        readings.append(sensor_info)

    for raw_path in sorted(glob.glob("/sys/class/hwmon/hwmon*/temp*_input")):
        path = Path(raw_path)
        value = _read_int(path)
        if value is None:
            continue
        name_path = path.parent / "name"
        label_path = path.with_name(path.name.replace("_input", "_label"))
        crit_path = path.with_name(path.name.replace("_input", "_crit"))
        max_path = path.with_name(path.name.replace("_input", "_max"))

        label = label_path.read_text(encoding="utf-8").strip() if label_path.exists() else path.stem
        if name_path.exists():
            label = f"{name_path.read_text(encoding='utf-8').strip()}:{label}"

        firmware_crit = None
        crit_val = _read_int(crit_path) if crit_path.exists() else None
        if crit_val is not None and 0 < crit_val < 200000:
            firmware_crit = crit_val / 1000.0

        firmware_hot = None
        max_val = _read_int(max_path) if max_path.exists() else None
        if max_val is not None and 0 < max_val < 200000:
            firmware_hot = max_val / 1000.0

        sensor_info = {
            "source": str(path),
            "label": label,
            "celsius": value / 1000.0,
        }
        if firmware_crit is not None:
            sensor_info["firmware_crit"] = firmware_crit
        if firmware_hot is not None:
            sensor_info["firmware_hot"] = firmware_hot
        readings.append(sensor_info)

    return readings


def gpu_temperatures_c() -> list[dict[str, Any]]:
    """Read NVIDIA GPU temperature via direct NVML."""
    collector = NvmlCollector()
    try:
        if not collector.is_available:
            return []
        temp = collector.sample_temperature()
        if temp is None:
            return []
        return [{"source": "nvml:gpu_0", "label": "NVIDIA GPU", "celsius": temp}]
    finally:
        collector.close()


def _proc_meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for line in lines:
        key, separator, value = line.partition(":")
        if not separator:
            continue
        number = value.strip().split()[0] if value.strip() else ""
        if number.isdigit():
            result[key] = int(number)
    return result


def _proc_cpu_counters() -> dict[str, int]:
    try:
        first = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return {}
    fields = first.split()
    if not fields or fields[0] != "cpu":
        return {}
    return {f"field_{index}": int(value) for index, value in enumerate(fields[1:]) if value.isdigit()}


def _nvidia_smi() -> dict[str, Any] | None:
    command = [
        "nvidia-smi",
        "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def runtime_snapshot(device: torch.device | None = None) -> dict[str, Any]:
    """Return current CPU/RAM/GPU/temperature telemetry for a local report."""

    snapshot: dict[str, Any] = {
        "cpu_threads": {
            "intra_op": torch.get_num_threads(),
            "inter_op": torch.get_num_interop_threads(),
        },
        "cpu_counters": _proc_cpu_counters(),
        "cpu_temperatures": cpu_temperatures_c(),
        "memory_kib": _proc_meminfo(),
        "nvidia_smi": _nvidia_smi(),
    }
    if device is not None and device.type == "cuda" and torch.cuda.is_available():
        snapshot["torch_cuda"] = {
            "device": str(device),
            "allocated_bytes": torch.cuda.memory_allocated(device),
            "reserved_bytes": torch.cuda.memory_reserved(device),
            "max_allocated_bytes": torch.cuda.max_memory_allocated(device),
            "max_reserved_bytes": torch.cuda.max_memory_reserved(device),
        }
    return snapshot


def cpu_utilization_percent(before: Mapping[str, int], after: Mapping[str, int]) -> float | None:
    """Estimate aggregate CPU utilization over two ``/proc/stat`` snapshots."""

    if not before or not after:
        return None
    keys = sorted(set(before) & set(after))
    deltas = {key: after[key] - before[key] for key in keys}
    total = sum(value for value in deltas.values())
    idle = deltas.get("field_3", 0) + deltas.get("field_4", 0)
    if total <= 0:
        return None
    return 100.0 * (total - idle) / total


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
