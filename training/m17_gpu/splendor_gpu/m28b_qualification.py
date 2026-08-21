"""Read-only M28B Runtime Qualification 2B natural-path runner.

This module evaluates host runtime qualification by executing a single natural-path
shadow epoch (185 train batches + 62 validation batches + 1 in-memory CPU state copy)
for both control and candidate models without profiler hooks, per-batch CUDA
synchronization barriers, or checkpoint persistence.

Continuous high-frequency (250ms) background telemetry captures process/thread CPU,
memory, thermal sensors, core frequencies, and GPU metrics to diagnose host envelope
and execution characteristics safely and reproducibly.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import torch
from torch import nn

try:
    from .encoded_cache import EncodedCache, PackedEncodedDataset
    from .interaction_train import (
        EXPECTED_CATALOG_HASH,
        EXPECTED_MODELS,
        _loader,
        build_fresh_model,
        policy_loss,
        training_config_hash,
        validate_config,
    )
    from .model import build_model
    from .runtime import (
        EXPECTED_CPU_THREADS,
        EXPECTED_THREAD_ENV,
        configure_cpu_runtime,
        cpu_temperatures_c,
        runtime_snapshot,
        write_json,
    )
    from .self_play_train import evaluate
    from .train import file_sha256, resolve_device, seed_everything
except ImportError:
    from splendor_gpu.encoded_cache import EncodedCache, PackedEncodedDataset
    from splendor_gpu.interaction_train import (
        EXPECTED_CATALOG_HASH,
        EXPECTED_MODELS,
        _loader,
        build_fresh_model,
        policy_loss,
        training_config_hash,
        validate_config,
    )
    from splendor_gpu.model import build_model
    from splendor_gpu.runtime import (
        EXPECTED_CPU_THREADS,
        EXPECTED_THREAD_ENV,
        configure_cpu_runtime,
        cpu_temperatures_c,
        runtime_snapshot,
        write_json,
    )
    from splendor_gpu.self_play_train import evaluate
    from splendor_gpu.train import file_sha256, resolve_device, seed_everything


QUALIFICATION_FORMAT = "effective-splendor-m28b-qualification-2b"
QUALIFICATION_VERSION = 1
PREFLIGHT_MAX_C = 65.0
WARNING_TEMP_C = 82.0
HARD_ABORT_LIMIT_C = 88.0
TELEMETRY_INTERVAL_SECONDS = 0.250

SHADOW_TRAIN_BATCHES = 185
SHADOW_VAL_BATCHES = 62


class ThermalSafetyAbort(RuntimeError):
    """Raised when any thermal sensor reaches the hard abort limit."""

    def __init__(self, stage: str, readings: Sequence[Mapping[str, Any]], limit_c: float):
        maximum = max((float(item["celsius"]) for item in readings if "celsius" in item), default=None)
        self.stage = stage
        self.readings = [dict(item) for item in readings]
        self.maximum_c = maximum
        self.limit_c = limit_c
        super().__init__(
            f"host thermal safety abort at {stage}: max={maximum!r}°C, limit={limit_c}°C"
        )


class ThermalTelemetryUnavailable(RuntimeError):
    """Raised when no thermal sensor is available for a fail-closed run."""


def maximum_temperature_c(readings: Sequence[Mapping[str, Any]]) -> float | None:
    values = [float(item["celsius"]) for item in readings if "celsius" in item]
    return max(values) if values else None


def thermal_sample() -> dict[str, Any]:
    readings = cpu_temperatures_c()
    return {"readings": readings, "max_celsius": maximum_temperature_c(readings)}


def require_thermal_headroom(stage: str, limit_c: float = HARD_ABORT_LIMIT_C) -> dict[str, Any]:
    sample = thermal_sample()
    maximum = sample["max_celsius"]
    if maximum is None:
        raise ThermalTelemetryUnavailable(f"no thermal reading available at {stage}")
    if maximum >= limit_c:
        raise ThermalSafetyAbort(stage, sample["readings"], limit_c)
    return sample


class NvmlCollector:
    """Lightweight direct NVML wrapper via ctypes without extra third-party dependencies."""

    def __init__(self):
        self._available = False
        self._handle = None
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

    def sample(self) -> dict[str, Any] | None:
        if not self._available or self._handle is None:
            return None

        class nvmlUtilization_t(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        try:
            temp = ctypes.c_uint()
            self._nvml.nvmlDeviceGetTemperature(self._handle, 0, ctypes.byref(temp))
            pwr = ctypes.c_uint()
            self._nvml.nvmlDeviceGetPowerUsage(self._handle, ctypes.byref(pwr))
            util = nvmlUtilization_t()
            self._nvml.nvmlDeviceGetUtilizationRates(self._handle, ctypes.byref(util))
            sm_clock = ctypes.c_uint()
            self._nvml.nvmlDeviceGetClockInfo(self._handle, 1, ctypes.byref(sm_clock))
            mem_clock = ctypes.c_uint()
            self._nvml.nvmlDeviceGetClockInfo(self._handle, 2, ctypes.byref(mem_clock))

            return {
                "gpu_temp_celsius": float(temp.value),
                "gpu_power_watts": float(pwr.value) / 1000.0,
                "gpu_utilization_percent": int(util.gpu),
                "memory_utilization_percent": int(util.memory),
                "sm_clock_mhz": int(sm_clock.value),
                "memory_clock_mhz": int(mem_clock.value),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def close(self):
        if self._available:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._available = False


class ProcessTelemetryReader:
    """Reads /proc metrics for the current process and its threads."""

    def __init__(self, pid: int | None = None):
        self.pid = pid or os.getpid()
        self._clk_tck = os.sysconf(os.sysconf_names["SC_CLK_TCK"]) if hasattr(os, "sysconf") else 100
        self._prev_proc_stat: tuple[float, int, int] | None = None
        self._prev_thread_stats: dict[int, tuple[float, int, int]] = {}

    def read_status(self) -> dict[str, Any]:
        res = {"voluntary_ctx_switches": 0, "involuntary_ctx_switches": 0, "rss_kb": 0, "swap_kb": 0, "threads": 1}
        try:
            for line in Path(f"/proc/{self.pid}/status").read_text(encoding="utf-8").splitlines():
                if line.startswith("voluntary_ctxt_switches:"):
                    res["voluntary_ctx_switches"] = int(line.split(":")[1].strip())
                elif line.startswith("nonvoluntary_ctxt_switches:"):
                    res["involuntary_ctx_switches"] = int(line.split(":")[1].strip())
                elif line.startswith("VmRSS:"):
                    res["rss_kb"] = int(line.split(":")[1].strip().split()[0])
                elif line.startswith("VmSwap:"):
                    res["swap_kb"] = int(line.split(":")[1].strip().split()[0])
                elif line.startswith("Threads:"):
                    res["threads"] = int(line.split(":")[1].strip())
        except OSError:
            pass
        return res

    def sample_process_and_threads(self, now: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        proc_user_pct, proc_sys_pct = 0.0, 0.0
        try:
            p_stat = Path(f"/proc/{self.pid}/stat").read_text(encoding="utf-8").split()
            utime = int(p_stat[13])
            stime = int(p_stat[14])
            if self._prev_proc_stat is not None:
                p_time, p_u, p_s = self._prev_proc_stat
                dt = now - p_time
                if dt > 0.001:
                    proc_user_pct = max(0.0, 100.0 * (utime - p_u) / (self._clk_tck * dt))
                    proc_sys_pct = max(0.0, 100.0 * (stime - p_s) / (self._clk_tck * dt))
            self._prev_proc_stat = (now, utime, stime)
        except OSError:
            pass

        status = self.read_status()
        proc_summary = {
            "user_cpu_percent": round(proc_user_pct, 2),
            "system_cpu_percent": round(proc_sys_pct, 2),
            "total_cpu_percent": round(proc_user_pct + proc_sys_pct, 2),
            "rss_kb": status["rss_kb"],
            "swap_kb": status["swap_kb"],
            "threads": status["threads"],
            "voluntary_ctx_switches": status["voluntary_ctx_switches"],
            "involuntary_ctx_switches": status["involuntary_ctx_switches"],
        }

        curr_thread_samples: list[dict[str, Any]] = []
        new_thread_dict: dict[int, tuple[float, int, int]] = {}
        task_dir = Path(f"/proc/{self.pid}/task")
        try:
            for tid_path in task_dir.iterdir():
                if not tid_path.name.isdigit():
                    continue
                tid = int(tid_path.name)
                try:
                    stat_content = (tid_path / "stat").read_text(encoding="utf-8").split()
                    comm = stat_content[1].strip("()")
                    t_utime = int(stat_content[13])
                    t_stime = int(stat_content[14])
                    new_thread_dict[tid] = (now, t_utime, t_stime)
                    t_user_pct, t_sys_pct = 0.0, 0.0
                    if tid in self._prev_thread_stats:
                        pt_time, pt_u, pt_s = self._prev_thread_stats[tid]
                        dt = now - pt_time
                        if dt > 0.001:
                            t_user_pct = max(0.0, 100.0 * (t_utime - pt_u) / (self._clk_tck * dt))
                            t_sys_pct = max(0.0, 100.0 * (t_stime - pt_s) / (self._clk_tck * dt))
                    curr_thread_samples.append({
                        "tid": tid,
                        "name": comm,
                        "user_cpu_percent": round(t_user_pct, 2),
                        "system_cpu_percent": round(t_sys_pct, 2),
                        "total_cpu_percent": round(t_user_pct + t_sys_pct, 2),
                    })
                except OSError:
                    pass
            self._prev_thread_stats = new_thread_dict
        except OSError:
            pass

        curr_thread_samples.sort(key=lambda t: t["total_cpu_percent"], reverse=True)
        return proc_summary, curr_thread_samples[:5]


def read_active_core_frequencies() -> dict[str, float]:
    freqs: list[float] = []
    try:
        import glob
        for p in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq"):
            try:
                freqs.append(int(Path(p).read_text(encoding="utf-8").strip()) / 1000.0)
            except (OSError, ValueError):
                pass
    except Exception:
        pass
    if not freqs:
        return {}
    return {
        "min_mhz": round(min(freqs), 1),
        "max_mhz": round(max(freqs), 1),
        "mean_mhz": round(sum(freqs) / len(freqs), 1),
        "cores_measured": len(freqs),
    }


class TelemetryRecorder:
    """Thread-safe background telemetry recorder operating at 250ms intervals."""

    def __init__(self, interval_seconds: float = TELEMETRY_INTERVAL_SECONDS):
        self.interval = interval_seconds
        self.samples: list[dict[str, Any]] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._nvml = NvmlCollector()
        self._proc = ProcessTelemetryReader()
        self.abort_triggered: bool = False
        self.abort_reason: str | None = None
        self.abort_sample: dict[str, Any] | None = None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="TelemetryRecorder")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._nvml.close()

    def _loop(self):
        while not self._stop_event.is_set():
            now = time.time()
            now_perf = time.perf_counter()
            thermal = thermal_sample()
            max_c = thermal["max_celsius"]
            proc_stat, top_threads = self._proc.sample_process_and_threads(now_perf)
            gpu_sample = self._nvml.sample()
            core_freqs = read_active_core_frequencies()

            sample = {
                "timestamp": now,
                "max_temperature_celsius": max_c,
                "temperatures": thermal["readings"],
                "process": proc_stat,
                "top_threads": top_threads,
                "gpu": gpu_sample,
                "core_frequencies_mhz": core_freqs,
            }

            with self._lock:
                self.samples.append(sample)

            if max_c is not None and max_c >= HARD_ABORT_LIMIT_C and not self.abort_triggered:
                self.abort_triggered = True
                self.abort_reason = f"thermal safety limit {HARD_ABORT_LIMIT_C}°C exceeded (max: {max_c}°C)"
                self.abort_sample = sample

            self._stop_event.wait(self.interval)

    def get_samples(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.samples)

    def summary(self) -> dict[str, Any]:
        samples = self.get_samples()
        if not samples:
            return {"sample_count": 0}

        max_temps = [s["max_temperature_celsius"] for s in samples if s.get("max_temperature_celsius") is not None]
        proc_cpus = [s["process"]["total_cpu_percent"] for s in samples if "process" in s and "total_cpu_percent" in s["process"]]
        gpu_utils = [s["gpu"]["gpu_utilization_percent"] for s in samples if s.get("gpu") and "gpu_utilization_percent" in s["gpu"]]
        gpu_powers = [s["gpu"]["gpu_power_watts"] for s in samples if s.get("gpu") and "gpu_power_watts" in s["gpu"]]

        return {
            "sample_count": len(samples),
            "peak_max_temperature_celsius": max(max_temps) if max_temps else None,
            "mean_max_temperature_celsius": round(sum(max_temps) / len(max_temps), 2) if max_temps else None,
            "peak_process_cpu_percent": max(proc_cpus) if proc_cpus else None,
            "mean_process_cpu_percent": round(sum(proc_cpus) / len(proc_cpus), 2) if proc_cpus else None,
            "peak_gpu_utilization_percent": max(gpu_utils) if gpu_utils else None,
            "mean_gpu_utilization_percent": round(sum(gpu_utils) / len(gpu_utils), 2) if gpu_utils else None,
            "peak_gpu_power_watts": max(gpu_powers) if gpu_powers else None,
            "mean_gpu_power_watts": round(sum(gpu_powers) / len(gpu_powers), 2) if gpu_powers else None,
        }


def collect_host_fingerprint() -> dict[str, Any]:
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "None"
    driver_version = "unknown"
    try:
        res = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], capture_output=True, text=True, check=True)
        driver_version = res.stdout.strip()
    except Exception:
        pass

    return {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu_device_name": gpu_name,
        "nvidia_driver_version": driver_version,
    }


def execute_shadow_epoch(
    model_contract: Mapping[str, Any],
    train_indices: Sequence[int],
    validation_indices: Sequence[int],
    cache: EncodedCache,
    config: Mapping[str, Any],
    device: torch.device,
    telemetry: TelemetryRecorder,
) -> dict[str, Any]:
    """Execute exactly 1 natural-path shadow epoch without profiler or intermediate syncs."""

    training = config["training"]
    role = str(model_contract["role"])
    model_id = str(model_contract["model_id"])
    seed = int(training["initialization_seed"])
    seed_everything(seed)

    model = build_fresh_model(dict(model_contract), seed).to(device)
    model.train()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(training["learning_rate"]),
        weight_decay=float(training["weight_decay"]),
    )

    batch_size = int(training["batch_size"])
    train_set = PackedEncodedDataset(cache, train_indices)
    validation_set = PackedEncodedDataset(cache, validation_indices)
    train_loader = _loader(train_set, batch_size, True, int(training["shuffle_seed"]), device)
    validation_loader = _loader(validation_set, batch_size, False, None, device)

    epoch_started = time.perf_counter()
    train_total_loss = 0.0
    train_seen = 0
    train_batches = 0
    train_start = time.perf_counter()

    for raw in train_loader:
        if telemetry.abort_triggered:
            raise ThermalSafetyAbort("training_loop", telemetry.abort_sample["temperatures"] if telemetry.abort_sample else [], HARD_ABORT_LIMIT_C)
        batch = {key: value.to(device, non_blocking=device.type == "cuda") for key, value in raw.items()}
        optimizer.zero_grad(set_to_none=True)
        logits, values = model(batch["entities"], batch["entity_mask"], batch["global_features"], batch["actions"], batch["action_mask"])
        policy = policy_loss(logits, batch["policy_target"])
        value = nn.functional.mse_loss(values, batch["value_target"])
        loss = policy + float(training["value_loss_weight"]) * value
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), float(training["gradient_clip_norm"]))
        optimizer.step()
        count = int(logits.shape[0])
        train_total_loss += loss.item() * count
        train_seen += count
        train_batches += 1

    train_elapsed = time.perf_counter() - train_start

    # Validation loop (natural path evaluate)
    val_start = time.perf_counter()
    validation_metrics = evaluate(model, validation_loader, device)
    val_elapsed = time.perf_counter() - val_start
    val_batches = len(validation_loader)

    # In-memory best state CPU copy
    copy_start = time.perf_counter()
    in_memory_state_copy = copy.deepcopy({key: value.detach().cpu() for key, value in model.state_dict().items()})
    copy_elapsed = time.perf_counter() - copy_start

    total_elapsed = time.perf_counter() - epoch_started

    # Immediately discard state and model
    del in_memory_state_copy, optimizer, model, train_loader, validation_loader, train_set, validation_set
    if device.type == "cuda":
        torch.cuda.empty_cache()

    return {
        "role": role,
        "model_id": model_id,
        "train_batches_completed": train_batches,
        "train_examples_seen": train_seen,
        "train_mean_loss": train_total_loss / train_seen if train_seen else 0.0,
        "train_elapsed_seconds": train_elapsed,
        "train_ms_per_batch": (train_elapsed * 1000.0 / train_batches) if train_batches else 0.0,
        "validation_batches_completed": val_batches,
        "validation_metrics": validation_metrics,
        "validation_elapsed_seconds": val_elapsed,
        "in_memory_state_copy_seconds": copy_elapsed,
        "total_epoch_elapsed_seconds": total_elapsed,
    }


def wait_for_cooldown(target_celsius: float, max_wait_seconds: float = 180.0) -> dict[str, Any]:
    """Poll sensors until maximum temperature drops below target_celsius."""
    started = time.perf_counter()
    initial_sample = thermal_sample()
    current_max = initial_sample["max_celsius"]

    while current_max is not None and current_max >= target_celsius:
        if time.perf_counter() - started > max_wait_seconds:
            break
        time.sleep(1.0)
        current_max = thermal_sample()["max_celsius"]

    final_sample = thermal_sample()
    return {
        "cooldown_target_celsius": target_celsius,
        "initial_max_celsius": initial_sample["max_celsius"],
        "final_max_celsius": final_sample["max_celsius"],
        "elapsed_seconds": time.perf_counter() - started,
        "target_reached": (final_sample["max_celsius"] is not None and final_sample["max_celsius"] < target_celsius),
    }


def validate_qualification_contract(
    contract: Mapping[str, Any],
    config: Mapping[str, Any],
    config_path: Path,
    cache: EncodedCache,
) -> None:
    if contract.get("format") != QUALIFICATION_FORMAT or contract.get("version") != QUALIFICATION_VERSION:
        raise ValueError("unsupported M28B Qualification 2B contract format")
    if contract.get("milestone") != "M28B" or contract.get("status") != "AUTHORIZED":
        raise ValueError("M28B Qualification contract is not authorized")
    scientific = contract.get("scientific_config")
    if not isinstance(scientific, Mapping):
        raise ValueError("scientific config binding is missing")
    if file_sha256(config_path) != scientific.get("sha256"):
        raise ValueError("scientific config SHA-256 drifted")
    validate_config(dict(config))

    cache_contract = contract.get("cache")
    if not isinstance(cache_contract, Mapping):
        raise ValueError("cache binding is missing")
    if cache.manifest_sha256 != cache_contract.get("manifest_sha256"):
        raise ValueError("encoded cache manifest SHA-256 drifted")
    if cache.examples != int(cache_contract.get("examples", -1)):
        raise ValueError("encoded cache example count drifted")

    runtime = contract.get("runtime")
    if not isinstance(runtime, Mapping):
        raise ValueError("runtime contract is missing")
    if runtime.get("thread_environment") != EXPECTED_THREAD_ENV:
        raise ValueError("thread environment contract drifted")
    if runtime.get("torch_threads") != EXPECTED_CPU_THREADS:
        raise ValueError("Torch thread contract drifted")


def run_qualification(args: argparse.Namespace) -> dict[str, Any]:
    contract_path = Path(args.contract)
    config_path = Path(args.config)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    cache = EncodedCache.load(Path(args.encoded_cache))

    validate_qualification_contract(contract, config, config_path, cache)
    cpu_runtime = configure_cpu_runtime()
    device = resolve_device(str(config["training"]["device"]))

    # Prepare immutable output directory
    run_timestamp = int(time.time())
    run_id = f"run-{run_timestamp}"
    out_dir = Path(args.output_dir) if args.output_dir else Path(f"local-artifacts/m28b-qualification-2b-{run_timestamp}")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / "qualification-2b-report.json"
    telemetry_file = out_dir / "telemetry-samples.json"

    # Preflight check
    preflight_thermal = require_thermal_headroom("preflight", PREFLIGHT_MAX_C)
    start_time_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started_perf = time.perf_counter()

    # Telemetry recorder
    telemetry = TelemetryRecorder(interval_seconds=TELEMETRY_INTERVAL_SECONDS)
    telemetry.start()

    # Create frozen split indices: exactly 185 train batches (23680 examples clamped to 23654) and 62 val batches (7936 clamped to 7851)
    train_indices = range(SHADOW_TRAIN_BATCHES * int(config["training"]["batch_size"]))
    val_indices = range(SHADOW_VAL_BATCHES * int(config["training"]["batch_size"]))

    results: list[dict[str, Any]] = []
    cooldown_record: dict[str, Any] | None = None
    abort_info: dict[str, Any] | None = None
    status = "QUALIFICATION_COMPLETED_SUCCESSFULLY"

    try:
        # 1. Run Control Model (1 shadow epoch: 185 train + 62 val + 1 state copy)
        control_model_contract = EXPECTED_MODELS[0]
        control_res = execute_shadow_epoch(
            control_model_contract,
            train_indices,
            val_indices,
            cache,
            config,
            device,
            telemetry,
        )
        results.append(control_res)

        # 2. Cooldown Phase between Control and Candidate
        cooldown_record = wait_for_cooldown(PREFLIGHT_MAX_C)

        # 3. Run Candidate Model (1 shadow epoch: 185 train + 62 val + 1 state copy)
        candidate_model_contract = EXPECTED_MODELS[1]
        candidate_res = execute_shadow_epoch(
            candidate_model_contract,
            train_indices,
            val_indices,
            cache,
            config,
            device,
            telemetry,
        )
        results.append(candidate_res)

    except ThermalSafetyAbort as exc:
        status = "HOST_SAFETY_ABORT"
        abort_info = {
            "stage": exc.stage,
            "limit_celsius": exc.limit_c,
            "maximum_celsius": exc.maximum_c,
            "readings": exc.readings,
        }
    except Exception as exc:
        status = "RUNTIME_FAULT"
        abort_info = {"error": str(exc), "error_type": type(exc).__name__}
    finally:
        telemetry.stop()

    end_time_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    total_duration_seconds = time.perf_counter() - started_perf

    telemetry_summary = telemetry.summary()
    peak_temp = telemetry_summary.get("peak_max_temperature_celsius")

    # Decision logic per qualification 2B rules
    verdict = "FAIL"
    if status == "QUALIFICATION_COMPLETED_SUCCESSFULLY" and peak_temp is not None and peak_temp <= 85.0:
        verdict = "HOST_QUALIFIED"
    elif status == "HOST_SAFETY_ABORT" or (peak_temp is not None and peak_temp >= HARD_ABORT_LIMIT_C):
        verdict = "HOST_ENVELOPE_LIMIT"
    elif status == "QUALIFICATION_COMPLETED_SUCCESSFULLY" and peak_temp is not None and peak_temp > 85.0:
        verdict = "HOST_THERMAL_WARNING_MARGINAL"
    else:
        verdict = f"UNQUALIFIED_{status}"

    this_module_path = Path(__file__)
    module_sha256 = file_sha256(this_module_path)

    final_report = {
        "format": QUALIFICATION_FORMAT,
        "version": QUALIFICATION_VERSION,
        "milestone": "M28B",
        "qualification": "m28b_qualification_2b",
        "verdict": verdict,
        "status": status,
        "scientific_evidence": False,
        "formal_training": False,
        "checkpoint_written": False,
        "offline_result_written": False,
        "arena_authorization": "NOT_AUTHORIZED",
        "promotion": "NONE",
        "champion": "M07",
        "provenance": {
            "command": " ".join(sys.argv),
            "qualification_module_path": str(this_module_path),
            "qualification_module_sha256": module_sha256,
            "contract_path": str(contract_path),
            "contract_sha256": file_sha256(contract_path),
            "scientific_config_path": str(config_path),
            "scientific_config_sha256": file_sha256(config_path),
            "cache_manifest_sha256": cache.manifest_sha256,
            "host_fingerprint": collect_host_fingerprint(),
            "output_directory": str(out_dir),
            "start_time_utc": start_time_iso,
            "end_time_utc": end_time_iso,
            "total_duration_seconds": total_duration_seconds,
        },
        "preflight_thermal": preflight_thermal,
        "cooldown_between_models": cooldown_record,
        "models_executed": results,
        "abort_info": abort_info,
        "telemetry_summary": telemetry_summary,
    }

    # Save immutable artifacts
    write_json(report_file, final_report)
    write_json(telemetry_file, telemetry.get_samples())

    return final_report


def main():
    parser = argparse.ArgumentParser(description="M28B Runtime Qualification 2B Natural-Path Runner")
    parser.add_argument("--contract", default="benchmarks/m28b-qualification-2b.json", type=Path)
    parser.add_argument("--config", default="benchmarks/m28b-contextual-entity-interaction-v1.config.json", type=Path)
    parser.add_argument("--encoded-cache", default="local-artifacts/m28b-encoded-cache-v1", type=Path)
    parser.add_argument("--output-dir", default=None, type=Path)
    args = parser.parse_args()

    report = run_qualification(args)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
