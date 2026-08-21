"""Read-only M28B Runtime Investigation 2A profiler.

This module profiles the cached training execution path only.  It deliberately
does not read the raw self-play JSON, rerun the accepted cache equality audit,
write checkpoints, compute offline gates, or run Arena.  It also has no code
path for changing Linux power policy, CPU frequency, Turbo, or GPU power
limits.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import torch
from torch import nn

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
from .runtime import (
    EXPECTED_CPU_THREADS,
    EXPECTED_THREAD_ENV,
    configure_cpu_runtime,
    cpu_temperatures_c,
    cpu_utilization_percent,
    runtime_snapshot,
    write_json,
)
from .train import file_sha256, resolve_device, seed_everything


INVESTIGATION_FORMAT = "effective-splendor-m28b-runtime-investigation"
INVESTIGATION_VERSION = 1
THERMAL_LIMIT_C = 90.0


class ThermalSafetyAbort(RuntimeError):
    """Raised when a host CPU temperature reaches the safety threshold."""

    def __init__(self, stage: str, readings: Sequence[Mapping[str, Any]], limit_c: float):
        maximum = max((float(item["celsius"]) for item in readings), default=None)
        self.stage = stage
        self.readings = [dict(item) for item in readings]
        self.maximum_c = maximum
        self.limit_c = limit_c
        super().__init__(
            f"host CPU thermal safety abort at {stage}: max={maximum!r}°C, limit={limit_c}°C"
        )


class ThermalTelemetryUnavailable(RuntimeError):
    """Raised when no CPU thermal sensor is available for a fail-closed run."""


def maximum_temperature_c(readings: Sequence[Mapping[str, Any]]) -> float | None:
    """Return the maximum numeric temperature from runtime sensor readings."""

    values = [float(item["celsius"]) for item in readings if "celsius" in item]
    return max(values) if values else None


def thermal_sample() -> dict[str, Any]:
    readings = cpu_temperatures_c()
    return {"readings": readings, "max_celsius": maximum_temperature_c(readings)}


def require_thermal_headroom(stage: str, limit_c: float = THERMAL_LIMIT_C) -> dict[str, Any]:
    """Read CPU sensors and abort at or above the host-only safety threshold."""

    sample = thermal_sample()
    maximum = sample["max_celsius"]
    if maximum is None:
        raise ThermalTelemetryUnavailable(f"no CPU thermal reading available at {stage}")
    if maximum >= limit_c:
        raise ThermalSafetyAbort(stage, sample["readings"], limit_c)
    return sample


def process_thread_count() -> int | None:
    """Return the current process's OS thread count without external tools."""

    task_dir = Path("/proc/self/task")
    try:
        return sum(1 for _ in task_dir.iterdir())
    except OSError:
        try:
            for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
                if line.startswith("Threads:"):
                    return int(line.split(":", 1)[1].strip())
        except (OSError, ValueError):
            return None
    return None


def thread_snapshot(cpu_runtime: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "torch_intra_op": torch.get_num_threads(),
        "torch_inter_op": torch.get_num_interop_threads(),
        "environment": dict(cpu_runtime.get("environment", {})),
        "process_os_threads": process_thread_count(),
        "dataloader_workers": 0,
    }


def _synchronize(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def _record_stage(
    totals: dict[str, list[float]],
    name: str,
    started: float,
    ended: float,
) -> None:
    totals.setdefault(name, []).append(ended - started)


def _summarize_stage_timings(totals: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name, values in totals.items():
        samples = [float(value) for value in values]
        summary[name] = {
            "count": len(samples),
            "total_seconds": sum(samples),
            "mean_milliseconds": (1000.0 * sum(samples) / len(samples)) if samples else None,
            "samples_milliseconds": [1000.0 * value for value in samples],
        }
    return summary


def _event_value(event: Any, name: str) -> float:
    try:
        value = getattr(event, name)
    except AttributeError:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _profiler_events(
    profiler: Any,
    *,
    sort_by: str,
    limit: int = 20,
    exclude_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded = exclude_names or set()
    events = []
    for event in profiler.key_averages():
        name = str(getattr(event, "key", "<unknown>"))
        if name in excluded:
            continue
        events.append(
            {
                "name": name,
                "calls": int(getattr(event, "count", 0)),
                "self_cpu_time_total_us": _event_value(event, "self_cpu_time_total"),
                "cpu_time_total_us": _event_value(event, "cpu_time_total"),
                "self_device_time_total_us": _event_value(event, "self_device_time_total"),
                "device_time_total_us": _event_value(event, "device_time_total"),
            }
        )
    events.sort(key=lambda item: float(item.get(sort_by, 0.0)), reverse=True)
    return events[:limit]


def _profile_activities(device: torch.device) -> list[Any]:
    activities = [torch.profiler.ProfilerActivity.CPU]
    if device.type == "cuda" and torch.cuda.is_available():
        activities.append(torch.profiler.ProfilerActivity.CUDA)
    return activities


def _export_trace(profiler: Any, trace_path: Path) -> dict[str, Any]:
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        profiler.export_chrome_trace(str(trace_path))
    except (OSError, RuntimeError) as exc:
        return {"path": str(trace_path), "exported": False, "error": str(exc)}
    return {
        "path": str(trace_path),
        "exported": True,
        "bytes": trace_path.stat().st_size,
        "sha256": file_sha256(trace_path),
    }


def _thermal_abort_payload(abort: ThermalSafetyAbort) -> dict[str, Any]:
    return {
        "stage": abort.stage,
        "limit_celsius": abort.limit_c,
        "maximum_celsius": abort.maximum_c,
        "readings": abort.readings,
    }


def profile_model(
    model_contract: Mapping[str, Any],
    cache: EncodedCache,
    config: Mapping[str, Any],
    device: torch.device,
    *,
    batches: int,
    trace_path: Path,
) -> dict[str, Any]:
    """Run a bounded forward/backward/optimizer profile with thermal abort."""

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
    dataset = PackedEncodedDataset(cache, range(cache.examples))
    loader = _loader(dataset, int(training["batch_size"]), True, int(training["shuffle_seed"]), device)
    iterator = iter(loader)
    totals: dict[str, list[float]] = {}
    thermal_samples: list[dict[str, Any]] = []
    profiler = None
    completed_batches = 0
    status = "PROFILE_COMPLETED_BELOW_LIMIT"
    abort_payload: dict[str, Any] | None = None
    before_profile = runtime_snapshot(device)
    started = time.perf_counter()

    try:
        sample = require_thermal_headroom(f"{role}:before_model_profile")
        thermal_samples.append({"stage": "before_model_profile", **sample})
        with torch.profiler.profile(
            activities=_profile_activities(device),
            record_shapes=True,
            profile_memory=True,
            with_stack=False,
        ) as active_profiler:
            profiler = active_profiler
            for step in range(batches):
                sample = require_thermal_headroom(f"{role}:before_batch_{step + 1}")
                thermal_samples.append({"stage": "before_batch", "batch": step + 1, **sample})

                stage_started = time.perf_counter()
                raw = next(iterator)
                _record_stage(totals, "data_wait_and_collate", stage_started, time.perf_counter())

                _synchronize(device)
                stage_started = time.perf_counter()
                batch = {
                    key: value.to(device, non_blocking=device.type == "cuda")
                    for key, value in raw.items()
                }
                _synchronize(device)
                _record_stage(totals, "host_to_device", stage_started, time.perf_counter())

                stage_started = time.perf_counter()
                optimizer.zero_grad(set_to_none=True)
                _synchronize(device)
                _record_stage(totals, "zero_grad", stage_started, time.perf_counter())

                stage_started = time.perf_counter()
                logits, values = model(
                    batch["entities"],
                    batch["entity_mask"],
                    batch["global_features"],
                    batch["actions"],
                    batch["action_mask"],
                )
                policy = policy_loss(logits, batch["policy_target"])
                value = nn.functional.mse_loss(values, batch["value_target"])
                loss = policy + float(training["value_loss_weight"]) * value
                _synchronize(device)
                _record_stage(totals, "forward_and_loss", stage_started, time.perf_counter())

                stage_started = time.perf_counter()
                loss.backward()
                _synchronize(device)
                _record_stage(totals, "backward", stage_started, time.perf_counter())

                stage_started = time.perf_counter()
                nn.utils.clip_grad_norm_(model.parameters(), float(training["gradient_clip_norm"]))
                _synchronize(device)
                _record_stage(totals, "gradient_clip", stage_started, time.perf_counter())

                stage_started = time.perf_counter()
                optimizer.step()
                _synchronize(device)
                _record_stage(totals, "optimizer_step", stage_started, time.perf_counter())

                active_profiler.step()
                completed_batches += 1
                sample = require_thermal_headroom(f"{role}:after_batch_{step + 1}")
                thermal_samples.append({"stage": "after_batch", "batch": step + 1, **sample})
    except ThermalSafetyAbort as exc:
        status = "HOST_SAFETY_ABORT"
        abort_payload = _thermal_abort_payload(exc)
    except ThermalTelemetryUnavailable as exc:
        status = "THERMAL_TELEMETRY_UNAVAILABLE"
        abort_payload = {"error": str(exc)}
    finally:
        after_profile = runtime_snapshot(device)
        ended = time.perf_counter()

    trace = _export_trace(profiler, trace_path) if profiler is not None else None
    cpu_utilization = cpu_utilization_percent(
        # The per-model snapshots are intentionally taken around the profile
        # rather than around trace export; trace serialization is not training.
        before_profile.get("cpu_counters", {}),
        after_profile.get("cpu_counters", {}),
    )
    result: dict[str, Any] = {
        "role": role,
        "model_id": model_id,
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "status": status,
        "batches_requested": batches,
        "batches_completed": completed_batches,
        "elapsed_seconds": ended - started,
        "stage_timings": _summarize_stage_timings(totals),
        "thermal_samples": thermal_samples,
        "abort": abort_payload,
        "telemetry_before_profile": before_profile,
        "telemetry_after_profile": after_profile,
        "process_threads": thread_snapshot({"environment": dict(EXPECTED_THREAD_ENV)}),
        "trace": trace,
        "profiler": {
            "activities": [str(activity).split(".")[-1] for activity in _profile_activities(device)],
            "top_self_cpu_raw": _profiler_events(profiler, sort_by="self_cpu_time_total_us") if profiler is not None else [],
            "top_self_cpu": (
                _profiler_events(
                    profiler,
                    sort_by="self_cpu_time_total_us",
                    exclude_names={"Unrecognized", "cudaDeviceSynchronize"},
                )
                if profiler is not None
                else []
            ),
            "top_device": _profiler_events(profiler, sort_by="self_device_time_total_us") if profiler is not None else [],
            "excluded_cpu_profile_entries": ["Unrecognized", "cudaDeviceSynchronize"],
            "synchronization_barriers_per_batch": 7,
            "cpu_utilization_percent": cpu_utilization,
        },
    }
    del optimizer, model, loader, dataset
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return result


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def validate_investigation_contract(
    contract: Mapping[str, Any],
    config: Mapping[str, Any],
    config_path: Path,
    cache: EncodedCache,
    requested_batches: int,
) -> None:
    if contract.get("format") != INVESTIGATION_FORMAT or contract.get("version") != INVESTIGATION_VERSION:
        raise ValueError("unsupported M28B Runtime Investigation contract")
    if contract.get("milestone") != "M28B" or contract.get("status") != "AUTHORIZED":
        raise ValueError("M28B Runtime Investigation contract is not authorized")
    scientific = contract.get("scientific_config")
    if not isinstance(scientific, Mapping):
        raise ValueError("scientific config binding is missing")
    if scientific.get("path") != "benchmarks/m28b-contextual-entity-interaction-v1.config.json":
        raise ValueError("scientific config path drifted")
    if not scientific.get("must_remain_unchanged"):
        raise ValueError("scientific config must remain unchanged")
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
    if cache_contract.get("dataset_raw_file_is_not_reread") is not True:
        raise ValueError("investigation must not reread the raw dataset")
    cache.validate_identity(
        dataset_file_sha256=str(config["dataset"]["file_sha256"]),
        self_play_hash=str(config["dataset"]["self_play_hash"]),
        catalog_hash=EXPECTED_CATALOG_HASH,
        examples=int(config["dataset"]["examples"]),
    )

    runtime = contract.get("runtime")
    if not isinstance(runtime, Mapping):
        raise ValueError("runtime contract is missing")
    if runtime.get("system_power_policy_mutation") is not False:
        raise ValueError("system power policy mutation is not allowed")
    if runtime.get("linux_governor_mutation") is not False:
        raise ValueError("Linux governor mutation is not allowed")
    if runtime.get("turbo_mutation") is not False:
        raise ValueError("Turbo mutation is not allowed")
    if runtime.get("gpu_power_limit_mutation") is not False:
        raise ValueError("GPU power-limit mutation is not allowed")
    if runtime.get("thread_environment") != EXPECTED_THREAD_ENV:
        raise ValueError("thread environment contract drifted")
    if runtime.get("torch_threads") != EXPECTED_CPU_THREADS:
        raise ValueError("Torch thread contract drifted")
    if int(runtime.get("batch_size", -1)) != int(config["training"]["batch_size"]):
        raise ValueError("profile batch size differs from frozen training batch size")

    profile = contract.get("profile")
    if not isinstance(profile, Mapping):
        raise ValueError("profile contract is missing")
    if list(profile.get("models", [])) != [str(model["model_id"]) for model in EXPECTED_MODELS]:
        raise ValueError("profile model list drifted")
    if profile.get("forward_backward_optimizer_path") is not True:
        raise ValueError("profile must exercise forward/backward/optimizer")
    if profile.get("checkpoint_written") is not False:
        raise ValueError("profile cannot write checkpoints")
    if profile.get("offline_result_written") is not False:
        raise ValueError("profile cannot write offline results")
    maximum_batches = int(profile.get("max_batches_per_model", 0))
    if requested_batches < 1 or requested_batches > maximum_batches:
        raise ValueError(f"requested batches must be in 1..{maximum_batches}")

    safety = contract.get("host_safety")
    if not isinstance(safety, Mapping):
        raise ValueError("host-safety contract is missing")
    if float(safety.get("cpu_temperature_limit_celsius", -1.0)) != THERMAL_LIMIT_C:
        raise ValueError("thermal safety limit drifted")
    if safety.get("abort_during_profile") is not True or safety.get("telemetry_required") is not True:
        raise ValueError("thermal safety must be fail-closed")


def run_investigation(args: argparse.Namespace) -> dict[str, Any]:
    contract = _load_json(args.contract)
    config = _load_json(args.config)
    cache = EncodedCache.load(args.encoded_cache)
    requested_batches = (
        int(args.batches)
        if args.batches is not None
        else int(contract["profile"]["default_batches_per_model"])
    )
    validate_investigation_contract(contract, config, args.config, cache, requested_batches)
    cpu_runtime = configure_cpu_runtime()
    device = resolve_device(str(config["training"]["device"]))
    trace_dir = args.trace_dir or args.report.parent / "m28b-runtime-investigation-2a-traces"
    before = runtime_snapshot(device)
    initial_thermal: dict[str, Any] | None = None
    initial_abort: dict[str, Any] | None = None
    initial_status = "PROFILE_IN_PROGRESS"
    try:
        initial_thermal = require_thermal_headroom("before_profile")
    except ThermalSafetyAbort as exc:
        initial_status = "HOST_SAFETY_ABORT"
        initial_abort = _thermal_abort_payload(exc)
    except ThermalTelemetryUnavailable as exc:
        initial_status = "THERMAL_TELEMETRY_UNAVAILABLE"
        initial_abort = {"error": str(exc)}
    base: dict[str, Any] = {
        "format": INVESTIGATION_FORMAT,
        "version": INVESTIGATION_VERSION,
        "milestone": "M28B",
        "investigation": "m28b_runtime_investigation_2a",
        "status": initial_status,
        "profile_only": True,
        "scientific_evidence": False,
        "formal_training": False,
        "checkpoint_written": False,
        "training_report_written": False,
        "offline_result_written": False,
        "arena_authorization": "NOT_AUTHORIZED",
        "promotion": "NONE",
        "champion": "M07",
        "contract_path": str(args.contract),
        "contract_sha256": file_sha256(args.contract),
        "scientific_config_path": str(args.config),
        "scientific_config_sha256": file_sha256(args.config),
        "training_config_hash": training_config_hash(config),
        "cache_path": str(args.encoded_cache),
        "cache_manifest_sha256": cache.manifest_sha256,
        "cache_examples": cache.examples,
        "cache_identity_mode": "manifest_vs_frozen_config_only; prior exact equality reused",
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "batches_requested_per_model": requested_batches,
        "cpu_runtime": cpu_runtime,
        "initial_process_threads": thread_snapshot(cpu_runtime),
        "thermal_limit_celsius": THERMAL_LIMIT_C,
        "telemetry": {
            "before_profile": before,
            "initial_thermal": initial_thermal,
            "initial_abort": initial_abort,
        },
        "models": [],
    }
    if initial_abort is not None:
        base["abort"] = initial_abort
        base["telemetry"]["after_profile"] = runtime_snapshot(device)
        return base
    for model_contract in EXPECTED_MODELS:
        result = profile_model(
            model_contract,
            cache,
            config,
            device,
            batches=requested_batches,
            trace_path=trace_dir / f"{model_contract['role']}.trace.json",
        )
        base["models"].append(result)
        if result["status"] != "PROFILE_COMPLETED_BELOW_LIMIT":
            base["status"] = result["status"]
            break
    else:
        base["status"] = "PROFILE_COMPLETED_BELOW_LIMIT"
    base["telemetry"]["after_profile"] = runtime_snapshot(device)
    return base


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile the cached M28B training path without scientific evaluation.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("benchmarks/m28b-contextual-entity-interaction-v1.config.json"),
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("benchmarks/m28b-runtime-investigation-2a.json"),
    )
    parser.add_argument(
        "--encoded-cache",
        type=Path,
        default=Path("local-artifacts/m28b-encoded-cache-v1"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("local-artifacts/m28b-runtime-investigation-2a.json"),
    )
    parser.add_argument("--trace-dir", type=Path)
    parser.add_argument("--batches", type=int)
    args = parser.parse_args()
    report = run_investigation(args)
    write_json(args.report, report)
    print(json.dumps({"report": str(args.report), "status": report["status"]}))


if __name__ == "__main__":
    main()
