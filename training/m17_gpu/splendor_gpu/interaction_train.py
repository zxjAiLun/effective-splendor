"""M28B fresh-init contextual Entity Mixer trainer.

M28B keeps the M28A data, objective, optimizer, and evaluation protocol while
changing only the entity aggregation architecture. Both models are built from
their frozen ``ModelSpec`` and never loaded from an inherited checkpoint.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterator

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from .data import catalog_semantic_hash, load_catalog
import threading
from .encoded_cache import EncodedCache, PackedEncodedDataset, cache_manifest_sha256, collate_packed
from .model import ModelSpec, build_model
from .runtime import NvmlCollector, cpu_temperatures_c
from .self_play_train import (
    collate,
    dataset_contract,
    evaluate,
    packed_policy_loss,
    policy_loss,
    self_play_hash,
    split_examples,
)


CPU_THERMAL_LIMIT_C = 95.0
GPU_THERMAL_LIMIT_C = 90.0
NVME_THERMAL_LIMIT_C = 80.0
PLATFORM_THERMAL_LIMIT_C = 85.0
COOLDOWN_TARGET_C = 65.0
COOLDOWN_TIMEOUT_SECONDS = 180.0
TELEMETRY_INTERVAL_SECONDS = 0.250
PHYSICAL_MICROBATCH_SIZE = 32
THERMAL_PACING_TIMEOUT_SECONDS = 300.0
THERMAL_PACING_POLL_SECONDS = 1.0

VERIFIED_CONTROL_REPORT_SHA256 = "af006dc0825da8d687fe9d848a17a1aa5e54770a08e19f801e0256ee9a604f49"
VERIFIED_CONTROL_CHECKPOINT_SHA256 = "17041a98d2204d44c02a9777713e038e2fa6facccdfa0bf745acef8c0e8758db"
VERIFIED_CONTROL_SEMANTIC_HASH = "5d83e21634399d6eb1c1b798b496ca5c03f809f7802a575c436b78c9436f0d41"


def sensor_threshold(sensor_info: dict[str, Any] | str) -> float:
    if isinstance(sensor_info, dict):
        label = str(sensor_info.get("label", "")).lower()
        firmware_crit = sensor_info.get("firmware_crit")
    else:
        label = str(sensor_info).lower()
        firmware_crit = None

    if any(k in label for k in ("coretemp", "x86_pkg_temp", "tcpu")):
        limit = CPU_THERMAL_LIMIT_C
    elif "nvme" in label:
        limit = NVME_THERMAL_LIMIT_C
    else:
        limit = PLATFORM_THERMAL_LIMIT_C

    if firmware_crit is not None and isinstance(firmware_crit, (int, float)) and firmware_crit > 0:
        limit = min(limit, float(firmware_crit) - 2.0)
    return limit


class ThermalSafetyAbort(RuntimeError):
    """Raised when host sensor reaches or exceeds its specific safety abort threshold."""

    def __init__(
        self,
        stage: str,
        sensor_source: str,
        sensor_label: str,
        measured_c: float,
        limit_c: float,
    ):
        self.stage = stage
        self.sensor_source = sensor_source
        self.sensor_label = sensor_label
        self.measured_c = measured_c
        self.limit_c = limit_c
        super().__init__(
            f"host thermal safety abort at {stage}: sensor {sensor_label!r} ({sensor_source}) measured {measured_c:.1f}°C >= limit {limit_c:.1f}°C"
        )


class ThermalTelemetryUnavailable(RuntimeError):
    """Raised when no thermal sensor is available for a fail-closed run."""


def require_below_hard_thermal_limits(
    readings: list[dict[str, Any]],
    stage: str,
    limit_override_c: float | None = None,
) -> None:
    """Raise immediately when any sampled sensor is at its unchanged hard wall."""

    for sensor in readings:
        measured = float(sensor["celsius"])
        limit = float(
            sensor.get(
                "hard_limit_c",
                limit_override_c if limit_override_c is not None else sensor_threshold(sensor),
            )
        )
        if measured >= limit:
            raise ThermalSafetyAbort(
                stage,
                str(sensor.get("source", "")),
                str(sensor.get("label", "")),
                measured,
                limit,
            )


class BackgroundThermalGuard:
    """Fail-closed background thermal monitor polling every 250ms during training."""

    def __init__(
        self,
        device: torch.device | None = None,
        limit_c: float | None = None,
        interval_s: float = TELEMETRY_INTERVAL_SECONDS,
    ):
        self.device = device or (torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu"))
        self.limit_c = limit_c
        self.interval_s = interval_s
        self.abort_triggered = False
        self.abort_exception: Exception | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._nvml: NvmlCollector | None = NvmlCollector() if self.device.type == "cuda" else None
        self._sample_lock = threading.Lock()

    def sample_temperatures(self, stage: str) -> list[dict[str, Any]]:
        """Return one fail-closed host/GPU sample using the guard's NVML handle."""

        with self._sample_lock:
            temps = cpu_temperatures_c()
            valid = [dict(sensor) for sensor in temps if "celsius" in sensor]
            if not valid:
                raise ThermalTelemetryUnavailable(f"no valid host thermal sensor available at {stage}")

            if self.device.type == "cuda":
                if self._nvml is None or not self._nvml.is_available:
                    raise ThermalTelemetryUnavailable(f"NVML GPU thermal telemetry unavailable at {stage}")
                gpu_temp = self._nvml.sample_temperature()
                if gpu_temp is None:
                    raise ThermalTelemetryUnavailable(f"failed to read NVML GPU temperature at {stage}")
                valid.append(
                    {
                        "source": "nvml:gpu_0",
                        "label": "NVIDIA GPU",
                        "celsius": gpu_temp,
                        "hard_limit_c": self.limit_c if self.limit_c is not None else GPU_THERMAL_LIMIT_C,
                    }
                )
            return valid

    def _sample_and_check(self, stage: str = "startup"):
        try:
            temps = self.sample_temperatures(stage)
        except ThermalTelemetryUnavailable as exc:
            self.abort_triggered = True
            self.abort_exception = exc
            return
        try:
            require_below_hard_thermal_limits(temps, stage, self.limit_c)
        except ThermalSafetyAbort as exc:
            self.abort_triggered = True
            self.abort_exception = exc

    def start(self):
        self._stop_event.clear()
        self.abort_triggered = False
        self.abort_exception = None
        # Synchronous check before spawning thread: refuse to run from already-overheated state
        self._sample_and_check("guard_startup")
        self.check()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="BackgroundThermalGuard")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._nvml is not None:
            self._nvml.close()
            self._nvml = None

    def _loop(self):
        while not self._stop_event.is_set():
            self._sample_and_check("training_loop")
            if self.abort_triggered:
                break
            self._stop_event.wait(self.interval_s)

    def check(self):
        if self.abort_triggered and self.abort_exception is not None:
            raise self.abort_exception


def thermal_pacing_bounds(sensor: dict[str, Any]) -> tuple[float, float]:
    """Return soft trigger/resume temperatures below the unchanged hard wall."""

    label = str(sensor.get("label", "")).lower()
    hard_limit = float(sensor.get("hard_limit_c", sensor_threshold(sensor)))
    if "nvidia gpu" in label:
        return min(85.0, hard_limit - 5.0), min(78.0, hard_limit - 12.0)
    if any(key in label for key in ("coretemp", "x86_pkg_temp", "tcpu")):
        return min(90.0, hard_limit - 5.0), min(82.0, hard_limit - 13.0)
    if "nvme" in label:
        return min(75.0, hard_limit - 5.0), min(70.0, hard_limit - 10.0)
    return hard_limit - 4.0, hard_limit - 10.0


def wait_for_soft_thermal_envelope(
    guard: BackgroundThermalGuard,
    stats: dict[str, float | int],
    *,
    sample_fn: Callable[[], list[dict[str, Any]]] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.perf_counter,
) -> None:
    """Pause at a logical-batch boundary when a soft thermal trigger is reached."""

    guard.check()
    if guard.device.type == "cuda":
        torch.cuda.synchronize(guard.device)
    read = sample_fn or (lambda: guard.sample_temperatures("thermal_pacing"))
    readings = read()
    require_below_hard_thermal_limits(readings, "thermal_pacing")
    offenders = [sensor for sensor in readings if float(sensor["celsius"]) >= thermal_pacing_bounds(sensor)[0]]
    if not offenders:
        return

    started = monotonic_fn()
    stats["pause_count"] = int(stats.get("pause_count", 0)) + 1
    hottest = max(offenders, key=lambda sensor: float(sensor["celsius"]))
    print(
        "Thermal pacing pause: "
        f"{hottest.get('label')}={float(hottest['celsius']):.1f}°C; waiting for resume envelope...",
        flush=True,
    )
    while True:
        guard.check()
        readings = read()
        require_below_hard_thermal_limits(readings, "thermal_pacing")
        still_hot = [sensor for sensor in readings if float(sensor["celsius"]) >= thermal_pacing_bounds(sensor)[1]]
        if not still_hot:
            elapsed = monotonic_fn() - started
            stats["total_pause_seconds"] = float(stats.get("total_pause_seconds", 0.0)) + elapsed
            stats["max_pause_seconds"] = max(float(stats.get("max_pause_seconds", 0.0)), elapsed)
            print(f"Thermal pacing resumed after {elapsed:.1f}s", flush=True)
            return
        if monotonic_fn() - started > THERMAL_PACING_TIMEOUT_SECONDS:
            hottest = max(still_hot, key=lambda sensor: float(sensor["celsius"]))
            _, resume_c = thermal_pacing_bounds(hottest)
            raise ThermalSafetyAbort(
                "thermal_pacing_timeout",
                str(hottest.get("source", "")),
                str(hottest.get("label", "")),
                float(hottest["celsius"]),
                resume_c,
            )
        sleep_fn(THERMAL_PACING_POLL_SECONDS)


def iter_physical_microbatches(batch: dict[str, torch.Tensor], size: int) -> Iterator[dict[str, torch.Tensor]]:
    """Split one logical batch without changing packed-action sample boundaries."""

    examples = int(batch["entities"].shape[0])
    if size <= 0:
        raise ValueError("physical microbatch size must be positive")
    if "action_offsets" not in batch:
        for start in range(0, examples, size):
            stop = min(start + size, examples)
            yield {key: value[start:stop] for key, value in batch.items()}
        return

    sample_keys = {"entities", "entity_mask", "global_features", "value_target"}
    action_keys = {"actions", "policy_target"}
    expected = sample_keys | action_keys | {"action_offsets"}
    if set(batch) != expected:
        raise RuntimeError(f"unexpected packed batch keys: {sorted(set(batch) - expected)}")
    offsets = batch["action_offsets"]
    for start in range(0, examples, size):
        stop = min(start + size, examples)
        action_start = int(offsets[start].item())
        action_stop = int(offsets[stop].item())
        out = {key: batch[key][start:stop] for key in sample_keys}
        out.update({key: batch[key][action_start:action_stop] for key in action_keys})
        out["action_offsets"] = offsets[start : stop + 1] - action_start
        yield out


def require_fail_closed_cooldown(
    device: torch.device | None = None,
    target_c: float = COOLDOWN_TARGET_C,
    timeout_s: float = COOLDOWN_TIMEOUT_SECONDS,
) -> float:
    """Wait until host cools below target_c; fail closed on missing telemetry or timeout."""
    dev = device or (torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu"))
    nvml = NvmlCollector() if dev.type == "cuda" else None
    if dev.type == "cuda" and (nvml is None or not nvml.is_available):
        raise ThermalTelemetryUnavailable("NVML GPU telemetry unavailable for cooldown check")

    cooldown_start = time.perf_counter()
    print(f"Cooling down host between models (target: < {target_c:.1f}°C, timeout: {timeout_s:.0f}s)...")
    try:
        while True:
            temps = cpu_temperatures_c()
            if not temps:
                raise ThermalTelemetryUnavailable("no host thermal sensor available for cooldown check")
            vals = [float(t["celsius"]) for t in temps if "celsius" in t]
            if not vals:
                raise ThermalTelemetryUnavailable("no valid numeric thermal readings available during cooldown")

            if dev.type == "cuda":
                assert nvml is not None
                gpu_temp = nvml.sample_temperature()
                if gpu_temp is None:
                    raise ThermalTelemetryUnavailable("failed to read NVML GPU temperature during cooldown")
                vals.append(gpu_temp)

            max_c = max(vals)
            if max_c < target_c:
                elapsed = time.perf_counter() - cooldown_start
                print(f"Thermal cooldown successful (max: {max_c:.1f}°C, elapsed: {elapsed:.1f}s)")
                return max_c
            if time.perf_counter() - cooldown_start > timeout_s:
                hottest = max(temps, key=lambda s: float(s.get("celsius", -1e9)))
                raise ThermalSafetyAbort(
                    f"cooldown_timeout_{timeout_s:.0f}s",
                    str(hottest.get("source", "")),
                    str(hottest.get("label", "")),
                    float(hottest.get("celsius", max_c)),
                    target_c,
                )
            time.sleep(2.0)
    finally:
        if nvml is not None:
            nvml.close()
from .train import (
    CHECKPOINT_FORMAT,
    checkpoint_semantic_hash,
    file_sha256,
    resolve_device,
    seed_everything,
)
from .runtime import EXPECTED_CPU_THREADS, configure_cpu_runtime


CONFIG_FORMAT = "effective-splendor-m28b-contextual-entity-interaction"
TRAINING_CONFIG_HASH_DOMAIN = b"effective-splendor-m28b-interaction-training-config-v1\0"
EXPECTED_BASELINE_COMMIT = "c0caa883e47cadce1ae85c78b85ba7c4e69ac007"
EXPECTED_CATALOG_HASH = "4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26"

EXPECTED_MODELS: tuple[dict[str, Any], ...] = (
    {
        "role": "control",
        "model_id": "m28b-entity-mixer-h192-b4-control-v1",
        "architecture": "entity_mixer",
        "hidden_dim": 192,
        "blocks": 4,
        "dropout": 0.0,
        "interaction_blocks": 0,
        "expected_parameter_count": 949060,
    },
    {
        "role": "candidate",
        "model_id": "m28b-contextual-entity-mixer-h192-b4-i2-v1",
        "architecture": "contextual_entity_mixer",
        "hidden_dim": 192,
        "blocks": 4,
        "interaction_blocks": 2,
        "dropout": 0.0,
        "expected_parameter_count": 1689798,
    },
)

EXPECTED_DATASET = {
    "format": "effective-splendor-neural-self-play-v2",
    "version": 2,
    "games": 512,
    "examples": 31505,
    "self_play_hash": "b8a67f5fd41dde0ee3c1c5194c12e7b0886813039c8ccde9660b211f26838e46",
    "file_sha256": "ddf8575af6ad14032a448488cda5868e82096bde1f511587f8077b3bd0eaa07f",
    "generator_checkpoint_hash": "dc611f3d575f87e2b24221d633f8af55c98055357b05ccb822ef46ec0cb98c04",
}


def _assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def training_config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        TRAINING_CONFIG_HASH_DOMAIN
        + json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_spec(raw: dict[str, Any]) -> ModelSpec:
    return ModelSpec(
        architecture=str(raw["architecture"]),
        hidden_dim=int(raw["hidden_dim"]),
        blocks=int(raw["blocks"]),
        dropout=float(raw["dropout"]),
        interaction_blocks=int(raw.get("interaction_blocks", 0)),
    )


def validate_config(config: dict[str, Any]) -> None:
    """Fail closed unless the tracked M28B preregistration is unchanged."""

    _assert_equal(config.get("format"), CONFIG_FORMAT, "config format")
    _assert_equal(config.get("version"), 1, "config version")
    _assert_equal(config.get("milestone"), "M28B", "milestone")
    _assert_equal(config.get("revision"), "contextual-interaction-v1", "revision")
    _assert_equal(config.get("status"), "DESIGNED", "status")
    _assert_equal(config.get("baseline_commit"), EXPECTED_BASELINE_COMMIT, "baseline commit")
    _assert_equal(config.get("downstream_authorization"), False, "downstream authorization")
    _assert_equal(config.get("training_authorization"), "NOT_AUTHORIZED", "training authorization")
    _assert_equal(config.get("arena_authorization"), "NOT_AUTHORIZED", "Arena authorization")
    _assert_equal(config.get("promotion"), "NONE", "promotion")
    _assert_equal(config.get("champion"), "M07", "champion")

    parent = config.get("parent")
    if not isinstance(parent, dict):
        raise ValueError("M28A parent binding is missing")
    _assert_equal(parent.get("milestone"), "M28A", "parent milestone")
    _assert_equal(parent.get("status"), "ACCEPTED / CLOSED", "parent status")
    _assert_equal(parent.get("closure_commit"), EXPECTED_BASELINE_COMMIT, "M28A closure commit")
    _assert_equal(parent.get("outcome"), "M28A_OFFLINE_NO_CAPACITY_SIGNAL", "parent outcome")

    authorization = config.get("authorization")
    if not isinstance(authorization, dict):
        raise ValueError("authorization contract is missing")
    _assert_equal(authorization.get("training"), "NOT_AUTHORIZED", "nested training authorization")
    _assert_equal(authorization.get("arena"), "NOT_AUTHORIZED", "nested Arena authorization")
    _assert_equal(authorization.get("m25"), False, "M25 authorization")
    _assert_equal(authorization.get("m26"), False, "M26 authorization")
    _assert_equal(authorization.get("m28_downstream_continuation"), False, "M28 continuation authorization")

    scope = config.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("scope contract is missing")
    expected_scope = {
        "fixed_dataset": True,
        "fixed_entity_schema": True,
        "fixed_policy_value_objective": True,
        "fixed_optimizer_recipe": True,
        "fixed_search_algorithm": True,
        "single_architecture_intervention": True,
        "no_new_self_play": True,
        "no_teacher_change": True,
        "no_width_sweep": True,
        "no_transformer": True,
        "no_multi_head_attention": True,
        "no_target_redesign": True,
        "no_puct_tuning": True,
        "no_optimizer_sweep": True,
        "no_learning_rate_sweep": True,
        "no_promotion_trial": True,
    }
    _assert_equal(scope, expected_scope, "scope")

    dataset = config.get("dataset")
    if not isinstance(dataset, dict):
        raise ValueError("dataset contract is missing")
    for key, expected in EXPECTED_DATASET.items():
        _assert_equal(dataset.get(key), expected, f"dataset {key}")
    _assert_equal(
        dataset.get("catalog"),
        "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json",
        "catalog path",
    )

    split = config.get("split")
    if not isinstance(split, dict):
        raise ValueError("split contract is missing")
    _assert_equal(split.get("total_examples"), 31505, "split total examples")
    validation = split.get("validation")
    train = split.get("train")
    reference = split.get("s1_reference")
    if not all(isinstance(value, dict) for value in (validation, train, reference)):
        raise ValueError("split partitions are incomplete")
    _assert_equal(validation.get("game_index_modulus"), 4, "validation modulus")
    _assert_equal(validation.get("game_index_remainder"), 0, "validation remainder")
    _assert_equal(validation.get("examples"), 7851, "validation examples")
    _assert_equal(train.get("examples"), 23654, "train examples")
    _assert_equal(reference.get("game_index_lt"), 128, "S1 reference game bound")
    _assert_equal(reference.get("game_index_modulus"), 4, "S1 reference modulus")
    _assert_equal(reference.get("game_index_remainder"), 0, "S1 reference remainder")
    _assert_equal(reference.get("examples"), 1953, "S1 reference examples")

    _assert_equal(config.get("models"), list(EXPECTED_MODELS), "model specs")
    for raw in config["models"]:
        _model_spec(raw).validate()
    if config["models"][0]["architecture"] != "entity_mixer":
        raise ValueError("control must preserve the historical entity_mixer")
    if config["models"][1]["architecture"] != "contextual_entity_mixer":
        raise ValueError("candidate must use contextual_entity_mixer")

    interaction = config.get("interaction")
    if not isinstance(interaction, dict):
        raise ValueError("interaction contract is missing")
    _assert_equal(interaction.get("kind"), "masked_pairwise_contextual_mixer", "interaction kind")
    _assert_equal(interaction.get("interaction_blocks"), 2, "interaction blocks")
    _assert_equal(interaction.get("entity_encoder"), "existing_entity_encoder", "entity encoder")
    _assert_equal(interaction.get("pair_features"), ["q_i", "k_j", "q_i * k_j"], "pair features")
    _assert_equal(interaction.get("weight_activation"), "sigmoid", "interaction activation")
    _assert_equal(interaction.get("source_mask"), "visible_entities_only", "source mask")
    _assert_equal(interaction.get("target_mask"), "visible_entities_only", "target mask")
    _assert_equal(interaction.get("exclude_self_pair"), True, "self pair exclusion")
    _assert_equal(interaction.get("aggregation"), "masked_weighted_mean", "interaction aggregation")
    _assert_equal(interaction.get("residual_input"), ["entity", "context", "global_context"], "residual input")
    _assert_equal(interaction.get("standard_multi_head_attention"), False, "multi-head attention")
    _assert_equal(interaction.get("transformer_encoder"), False, "Transformer encoder")

    initialization = config.get("initialization")
    if not isinstance(initialization, dict):
        raise ValueError("initialization contract is missing")
    _assert_equal(initialization.get("mode"), "fresh", "initialization mode")
    _assert_equal(initialization.get("initialization_seed"), 280229, "initialization seed")
    _assert_equal(initialization.get("shuffle_seed"), 280229, "shuffle seed")
    _assert_equal(initialization.get("reset_before_each_model"), True, "reset before each model")
    _assert_equal(
        initialization.get("forbidden_sources"),
        [
            "M22 checkpoint weights",
            "M24-S1 checkpoint weights",
            "M24-S2 checkpoint weights",
            "M28A control checkpoint weights",
            "M28A candidate checkpoint weights",
            "partial weight transplant",
            "Net2Net",
            "weight interpolation",
            "checkpoint surgery",
        ],
        "fresh initialization forbidden sources",
    )

    training = config.get("training")
    if not isinstance(training, dict):
        raise ValueError("training recipe is missing")
    for key, expected in {
        "device": "cuda",
        "seed": 280229,
        "initialization_seed": 280229,
        "shuffle_seed": 280229,
        "batch_size": 128,
        "epochs": 32,
        "learning_rate": 0.0001,
        "weight_decay": 0.0001,
        "value_loss_weight": 0.5,
        "gradient_clip_norm": 1.0,
        "optimizer": "AdamW",
    }.items():
        _assert_equal(training.get(key), expected, f"training {key}")
    deterministic = training.get("determinism")
    if not isinstance(deterministic, dict):
        raise ValueError("determinism contract is missing")
    _assert_equal(deterministic.get("cublas_workspace_config"), ":4096:8", "CUBLAS workspace")
    _assert_equal(deterministic.get("torch_deterministic"), True, "torch deterministic")
    _assert_equal(deterministic.get("cudnn_benchmark"), False, "cuDNN benchmark")
    _assert_equal(deterministic.get("dataloader_workers"), 0, "DataLoader workers")
    _assert_equal(deterministic.get("new_generator_per_model"), True, "new generator per model")
    selection = training.get("selection")
    if not isinstance(selection, dict):
        raise ValueError("selection contract is missing")
    _assert_equal(selection.get("score"), "policy_cross_entropy + 0.5 * value_mse", "selection score")
    _assert_equal(selection.get("source"), "full S2 validation only", "selection source")
    _assert_equal(selection.get("arena_reselection"), False, "Arena reselection")

    offline = config.get("offline_gates")
    if not isinstance(offline, dict):
        raise ValueError("offline gate contract is missing")
    _assert_equal(offline.get("relative_improvement_formula"), "floor(10000 * (control - candidate) / control)", "relative improvement formula")
    _assert_equal(offline.get("top1_delta_formula"), "candidate_top1 - control_top1", "Top-1 delta formula")
    g1 = offline.get("G1_full_s2_validation")
    g2 = offline.get("G2_s1_reference_non_regression")
    if not isinstance(g1, dict) or not isinstance(g2, dict):
        raise ValueError("offline gates are incomplete")
    for gate, expected in (
        (g1, {"policy_ce_improvement_min_bps": 50, "value_mse_improvement_min_bps": 50, "policy_ce_non_regression_min_bps": -100, "value_mse_non_regression_min_bps": -100, "top1_delta_min": -0.01}),
        (g2, {"policy_ce_improvement_min_bps": -100, "value_mse_improvement_min_bps": -100, "top1_delta_min": -0.01}),
    ):
        for key, expected_value in expected.items():
            _assert_equal(gate.get(key), expected_value, f"offline gate {key}")
    _assert_equal(offline.get("fail_decision"), "M28B_OFFLINE_NO_INTERACTION_SIGNAL", "offline fail decision")
    _assert_equal(offline.get("fail_action"), "STOP_NO_ARENA", "offline fail action")

    arena = config.get("arena_screen")
    if not isinstance(arena, dict):
        raise ValueError("Arena screen contract is missing")
    _assert_equal(arena.get("condition"), "Only after explicit training review authorization and offline PASS; this prereg does not authorize execution.", "Arena condition")
    neural = arena.get("neural_search")
    matrix = arena.get("matrix")
    statistics = arena.get("statistics")
    if not all(isinstance(value, dict) for value in (neural, matrix, statistics)):
        raise ValueError("Arena contract is incomplete")
    _assert_equal(neural.get("simulations"), 16, "Arena simulations")
    _assert_equal(neural.get("max_depth_turns"), 1, "Arena depth")
    _assert_equal(neural.get("puct_exploration_milli"), 1500, "Arena PUCT")
    _assert_equal(neural.get("device"), "cuda", "Arena device")
    _assert_equal(matrix.get("pairs"), ["candidate_vs_control", "candidate_vs_m07", "control_vs_m07"], "Arena pairs")
    _assert_equal(matrix.get("game_seeds"), list(range(303001, 303033)), "Arena seeds")
    _assert_equal(matrix.get("seat_rotations"), 2, "Arena seat rotations")
    _assert_equal(matrix.get("matches_per_pair"), 64, "Arena matches per pair")
    _assert_equal(matrix.get("total_matches"), 192, "Arena total matches")
    _assert_equal(statistics.get("direct_capacity_threshold_bps"), 5500, "direct Arena threshold")
    _assert_equal(statistics.get("m07_anchor_threshold_bps"), 500, "M07 anchor threshold")
    _assert_equal(statistics.get("uncertainty_role"), "diagnostic_only", "Arena uncertainty role")

    decisions = config.get("decision_outputs")
    if not isinstance(decisions, dict):
        raise ValueError("decision output contract is missing")
    _assert_equal(
        decisions.get("allowed"),
        [
            "M28B_OFFLINE_NO_INTERACTION_SIGNAL",
            "M28B_ARENA_ELIGIBLE",
            "M28B_INTERACTION_SIGNAL",
            "M28B_NO_INTERACTION_SIGNAL",
            "M28B_MIXED",
            "M28B_EXECUTION_INVALID",
        ],
        "allowed decisions",
    )
    _assert_equal(decisions.get("promotion"), "NONE", "decision promotion")
    _assert_equal(decisions.get("champion"), "M07", "decision champion")


def validate_dataset(dataset_path: Path, config: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    raw_sha = file_sha256(dataset_path)
    expected = config["dataset"]
    _assert_equal(raw_sha, expected["file_sha256"], "dataset file SHA-256")
    version, _domain, checkpoint_field = dataset_contract(payload)
    _assert_equal(version, expected["version"], "dataset version")
    actual_self_play_hash = self_play_hash(payload)
    _assert_equal(actual_self_play_hash, expected["self_play_hash"], "self-play semantic hash")
    _assert_equal(payload.get(checkpoint_field), expected["generator_checkpoint_hash"], "generator checkpoint hash")
    _assert_equal(payload.get("format"), expected["format"], "dataset format")
    _assert_equal(len(payload.get("games", [])), expected["games"], "dataset games")
    _assert_equal(len(payload.get("examples", [])), expected["examples"], "dataset examples")
    game_indices = {int(example["game_index"]) for example in payload["examples"]}
    _assert_equal(len(game_indices), expected["games"], "dataset game-index cardinality")
    _assert_equal(min(game_indices), 0, "dataset first game index")
    _assert_equal(max(game_indices), expected["games"] - 1, "dataset last game index")
    return payload, actual_self_play_hash, raw_sha


def split_m28b_examples(payload: dict[str, Any], config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    split = config["split"]
    train, validation = split_examples(
        payload,
        int(split["validation"]["game_index_modulus"]),
        int(split["validation"]["game_index_remainder"]),
    )
    reference = [
        example
        for example in validation
        if int(example["game_index"]) < int(split["s1_reference"]["game_index_lt"])
    ]
    if any(int(example["game_index"]) % 4 == 0 for example in train):
        raise ValueError("validation games leaked into training partition")
    _assert_equal(len(train), split["train"]["examples"], "train split examples")
    _assert_equal(len(validation), split["validation"]["examples"], "validation split examples")
    _assert_equal(len(reference), split["s1_reference"]["examples"], "S1 reference examples")
    if any(int(example["game_index"]) >= 128 for example in reference):
        raise ValueError("non-S1 examples entered the frozen S1 reference subset")
    return train, validation, reference


def split_m28b_indices(payload: dict[str, Any], config: dict[str, Any]) -> tuple[list[int], list[int], list[int]]:
    """Return the frozen game-level partitions as indices into the full cache."""

    split = config["split"]
    modulus = int(split["validation"]["game_index_modulus"])
    remainder = int(split["validation"]["game_index_remainder"])
    reference_bound = int(split["s1_reference"]["game_index_lt"])
    train, validation, reference = [], [], []
    for index, example in enumerate(payload["examples"]):
        game_index = int(example["game_index"])
        if game_index % modulus == remainder:
            validation.append(index)
            if game_index < reference_bound:
                reference.append(index)
        else:
            train.append(index)
    _assert_equal(len(train), split["train"]["examples"], "train split indices")
    _assert_equal(len(validation), split["validation"]["examples"], "validation split indices")
    _assert_equal(len(reference), split["s1_reference"]["examples"], "S1 reference split indices")
    if set(train) & set(validation) or set(reference) - set(validation):
        raise ValueError("M28B cache partition indices overlap")
    return train, validation, reference


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


def build_fresh_model(model_contract: dict[str, Any], seed: int) -> nn.Module:
    spec = _model_spec(model_contract)
    seed_everything(int(seed))
    model = build_model(spec)
    actual_count = parameter_count(model)
    _assert_equal(actual_count, int(model_contract["expected_parameter_count"]), f"{model_contract['model_id']} parameter count")
    return model


def relative_improvement_bps(control: float, candidate: float) -> int:
    if control <= 0.0:
        raise ValueError("control metric must be positive")
    return math.floor(10000.0 * (control - candidate) / control)


def offline_comparison(control_report: dict[str, Any], candidate_report: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    gates = config["offline_gates"]
    comparisons: dict[str, dict[str, float | int]] = {}
    for label in ("validation", "s1_reference"):
        control = control_report[label]
        candidate = candidate_report[label]
        comparisons[label] = {
            "policy_ce_improvement_bps": relative_improvement_bps(float(control["policy_cross_entropy"]), float(candidate["policy_cross_entropy"])),
            "value_mse_improvement_bps": relative_improvement_bps(float(control["value_mse"]), float(candidate["value_mse"])),
            "top1_delta": float(candidate["visit_top1"]) - float(control["visit_top1"]),
        }
    full = comparisons["validation"]
    reference = comparisons["s1_reference"]
    g1 = gates["G1_full_s2_validation"]
    g2 = gates["G2_s1_reference_non_regression"]
    g1_pass = (
        (full["policy_ce_improvement_bps"] >= int(g1["policy_ce_improvement_min_bps"]) or full["value_mse_improvement_bps"] >= int(g1["value_mse_improvement_min_bps"]))
        and full["policy_ce_improvement_bps"] >= int(g1["policy_ce_non_regression_min_bps"])
        and full["value_mse_improvement_bps"] >= int(g1["value_mse_non_regression_min_bps"])
        and full["top1_delta"] >= float(g1["top1_delta_min"])
    )
    g2_pass = (
        reference["policy_ce_improvement_bps"] >= int(g2["policy_ce_improvement_min_bps"])
        and reference["value_mse_improvement_bps"] >= int(g2["value_mse_improvement_min_bps"])
        and reference["top1_delta"] >= float(g2["top1_delta_min"])
    )
    return {
        "G1_full_s2_validation": {"pass": g1_pass, "metrics": full},
        "G2_s1_reference_non_regression": {"pass": g2_pass, "metrics": reference},
        "decision": "M28B_ARENA_ELIGIBLE" if g1_pass and g2_pass else "M28B_OFFLINE_NO_INTERACTION_SIGNAL",
        "arena_authorization": "NOT_AUTHORIZED",
    }


class _IndexDataset(Dataset):
    def __init__(self, indices: Sequence[int]):
        self.indices = tuple(int(i) for i in indices)

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, index: int) -> int:
        return self.indices[index]


def _loader(dataset: Dataset, batch_size: int, shuffle: bool, seed: int | None, device: torch.device) -> DataLoader:
    generator = torch.Generator().manual_seed(int(seed)) if shuffle and seed is not None else None
    if isinstance(dataset, PackedEncodedDataset):
        return DataLoader(
            _IndexDataset(dataset.indices),
            batch_size=batch_size,
            shuffle=shuffle,
            generator=generator,
            num_workers=0,
            collate_fn=dataset.cache.batch,
            pin_memory=device.type == "cuda",
        )
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        generator=generator,
        num_workers=0,
        collate_fn=collate,
        pin_memory=device.type == "cuda",
    )


def build_checkpoint_metadata(
    model: nn.Module,
    model_contract: dict[str, Any],
    config: dict[str, Any],
    catalog: dict[str, Any],
    self_play_hash_value: str,
    dataset_file_sha256: str,
    train_examples: int,
    validation_examples: int,
    s1_reference_examples: int,
    cache_manifest_sha256_value: str | None = None,
) -> dict[str, Any]:
    training = config["training"]
    metadata = {
        "format": CHECKPOINT_FORMAT,
        "version": 1,
        "model_id": model_contract["model_id"],
        **model.checkpoint_metadata(),
        "parameter_count": parameter_count(model),
        "expected_parameter_count": int(model_contract["expected_parameter_count"]),
        "training_stage": "m28b_contextual_entity_interaction_v1",
        "initialization": "fresh",
        "initialization_seed": int(training["initialization_seed"]),
        "shuffle_seed": int(training["shuffle_seed"]),
        "model_role": model_contract["role"],
        "source_self_play_hash": self_play_hash_value,
        "source_self_play_file_sha256": dataset_file_sha256,
        "dataset_generator_checkpoint_hash": config["dataset"]["generator_checkpoint_hash"],
        "training_config_hash": training_config_hash(config),
        "catalog_hash": catalog_semantic_hash(catalog),
        "train_examples": train_examples,
        "validation_examples": validation_examples,
        "s1_reference_examples": s1_reference_examples,
        "interaction_contract": config["interaction"],
    }
    if cache_manifest_sha256_value is not None:
        metadata["runtime_repair"] = "m28b_runtime_repair_1"
        metadata["cpu_runtime"] = dict(EXPECTED_CPU_THREADS)
        metadata["encoded_cache_manifest_sha256"] = cache_manifest_sha256_value
    return metadata


def train_one(
    model_contract: dict[str, Any],
    train_indices: list[int],
    validation_indices: list[int],
    reference_indices: list[int],
    cache: EncodedCache,
    catalog: dict[str, Any],
    config: dict[str, Any],
    self_play_hash_value: str,
    dataset_file_sha256: str,
    out_dir: Path,
) -> dict[str, Any]:
    training = config["training"]
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != training["determinism"]["cublas_workspace_config"]:
        raise RuntimeError("CUBLAS_WORKSPACE_CONFIG does not match frozen M28B recipe")
    device = resolve_device(str(training["device"]))
    model = build_fresh_model(model_contract, int(training["initialization_seed"])).to(device)
    train_set = PackedEncodedDataset(cache, train_indices)
    validation_set = PackedEncodedDataset(cache, validation_indices)
    reference_set = PackedEncodedDataset(cache, reference_indices)
    train_loader = _loader(train_set, int(training["batch_size"]), True, int(training["shuffle_seed"]), device)
    validation_loader = _loader(validation_set, int(training["batch_size"]), False, None, device)
    reference_loader = _loader(reference_set, int(training["batch_size"]), False, None, device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(training["learning_rate"]), weight_decay=float(training["weight_decay"]))
    best_score = math.inf
    best_epoch = 0
    best_state: dict[str, torch.Tensor] | None = None
    history: list[dict[str, Any]] = []
    thermal_pacing: dict[str, float | int] = {
        "physical_microbatch_size": PHYSICAL_MICROBATCH_SIZE,
        "logical_batch_size": int(training["batch_size"]),
        "pause_count": 0,
        "total_pause_seconds": 0.0,
        "max_pause_seconds": 0.0,
    }
    start = time.perf_counter()
    guard = BackgroundThermalGuard(device=device, interval_s=TELEMETRY_INTERVAL_SECONDS)
    guard.start()

    def runtime_abort_check() -> None:
        guard.check()
        wait_for_soft_thermal_envelope(guard, thermal_pacing)

    try:
        for epoch in range(int(training["epochs"])):
            model.train()
            epoch_loss_sum = torch.zeros((), dtype=torch.float64, device=device)
            seen = 0
            for raw in train_loader:
                guard.check()
                optimizer.zero_grad(set_to_none=True)
                logical_count = int(raw["entities"].shape[0])
                logical_loss_sum = torch.zeros((), dtype=torch.float64, device=device)
                for micro_raw in iter_physical_microbatches(raw, PHYSICAL_MICROBATCH_SIZE):
                    guard.check()
                    batch = {
                        key: value.to(device, non_blocking=device.type == "cuda")
                        for key, value in micro_raw.items()
                    }
                    if "action_offsets" in batch:
                        logits, values = model.forward_packed(
                            batch["entities"], batch["entity_mask"], batch["global_features"],
                            batch["actions"], batch["action_offsets"],
                        )
                        policy = packed_policy_loss(logits, batch["policy_target"], batch["action_offsets"])
                        count = int(batch["entities"].shape[0])
                    else:
                        logits, values = model(
                            batch["entities"], batch["entity_mask"], batch["global_features"],
                            batch["actions"], batch["action_mask"],
                        )
                        policy = policy_loss(logits, batch["policy_target"])
                        count = int(logits.shape[0])

                    value = nn.functional.mse_loss(values, batch["value_target"])
                    loss = policy + float(training["value_loss_weight"]) * value
                    (loss * (count / logical_count)).backward()
                    logical_loss_sum += (loss.detach() * count).to(dtype=torch.float64)
                    guard.check()
                nn.utils.clip_grad_norm_(model.parameters(), float(training["gradient_clip_norm"]))
                optimizer.step()
                epoch_loss_sum += logical_loss_sum
                seen += logical_count
                guard.check()
                wait_for_soft_thermal_envelope(guard, thermal_pacing)

            validation_metrics = evaluate(
                model,
                validation_loader,
                device,
                abort_check=runtime_abort_check,
            )
            selection_score = float(validation_metrics["policy_cross_entropy"]) + float(training["value_loss_weight"]) * float(validation_metrics["value_mse"])
            mean_loss_val = float((epoch_loss_sum / seen).item())
            history.append({"epoch": epoch + 1, "mean_loss": mean_loss_val, "validation": validation_metrics, "selection_score": selection_score})
            if selection_score < best_score:
                best_score = selection_score
                best_epoch = epoch + 1
                best_state = copy.deepcopy(model.state_dict())

        if best_state is None:
            raise RuntimeError("M28B training produced no checkpoint candidate")
        model.load_state_dict(best_state, strict=True)
        validation_metrics = evaluate(
            model,
            validation_loader,
            device,
            abort_check=runtime_abort_check,
        )
        reference_metrics = evaluate(
            model,
            reference_loader,
            device,
            abort_check=runtime_abort_check,
        )
    finally:
        guard.stop()

    best_state_cpu = {key: value.detach().cpu() for key, value in best_state.items()}
    role = str(model_contract["role"])
    model_metadata = build_checkpoint_metadata(
        model,
        model_contract,
        config,
        catalog,
        self_play_hash_value,
        dataset_file_sha256,
        len(train_set),
        len(validation_set),
        len(reference_set),
        cache_manifest_sha256(cache.root),
    )
    checkpoint_hash = checkpoint_semantic_hash(model_metadata, best_state_cpu)
    role_dir = out_dir / role
    role_dir.mkdir(parents=True, exist_ok=False)
    checkpoint_path = role_dir / "checkpoint.pt"
    torch.save({"metadata": model_metadata, "state_dict": best_state_cpu}, checkpoint_path)
    report = {
        "format": "effective-splendor-m28b-interaction-training-report",
        "version": 1,
        "milestone": "M28B",
        "model_id": model_contract["model_id"],
        "model_role": role,
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "deterministic_algorithms_enabled": bool(torch.are_deterministic_algorithms_enabled()),
        "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
        "elapsed_seconds": time.perf_counter() - start,
        "parameter_count": parameter_count(model),
        "source_self_play_hash": self_play_hash_value,
        "source_self_play_file_sha256": dataset_file_sha256,
        "runtime_repair": "m28b_runtime_repair_1",
        "runtime_compute_pacing": thermal_pacing,
        "cpu_runtime": dict(EXPECTED_CPU_THREADS),
        "encoded_cache_manifest_sha256": model_metadata["encoded_cache_manifest_sha256"],
        "training_config_hash": model_metadata["training_config_hash"],
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_file_sha256": file_sha256(checkpoint_path),
        "metric_semantics": {"validation_kind": "offline_game_held_out_search_visit_fit", "diagnostic_only": True, "strength_authority": "frozen_arena_screen_only"},
        "selection": {"metric": "policy_cross_entropy + 0.5 * value_mse", "best_epoch": best_epoch, "best_score": best_score, "source": "full S2 validation only"},
        "validation": validation_metrics,
        "s1_reference": reference_metrics,
        "history": history,
    }
    (role_dir / "training-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def verify_and_reevaluate_control(
    model_contract: dict[str, Any],
    train_indices: list[int],
    validation_indices: list[int],
    reference_indices: list[int],
    cache: EncodedCache,
    catalog: dict[str, Any],
    config: dict[str, Any],
    self_play_hash_value: str,
    dataset_file_sha256: str,
    out_dir: Path,
    device: torch.device,
) -> dict[str, Any]:
    """Fail-closed validation and evaluator re-assessment for verified Control checkpoint."""
    role = str(model_contract["role"])
    if role != "control":
        raise ValueError(f"verify_and_reevaluate_control called for non-control role: {role}")

    role_dir = out_dir / role
    report_file = role_dir / "training-report.json"
    ckpt_file = role_dir / "checkpoint.pt"
    candidate_dir = out_dir / "candidate"
    summary_file = out_dir / "summary.json"

    # 1. Output directory safety assertions: No candidate or summary should exist yet
    if candidate_dir.exists():
        raise RuntimeError(f"fail-closed: candidate directory already exists at {candidate_dir}")
    if summary_file.exists():
        raise RuntimeError(f"fail-closed: summary.json already exists at {summary_file}")
    if not report_file.exists() or not ckpt_file.exists():
        raise RuntimeError(f"fail-closed: missing control report or checkpoint in {role_dir}")

    # Check for unexpected entries in out_dir
    allowed_top_entries = {role_dir.name}
    for entry in out_dir.iterdir():
        if entry.name not in allowed_top_entries:
            raise RuntimeError(f"fail-closed: unexpected entry in output directory: {entry}")

    # 2. File SHA256 matches confirmed immutable baseline
    actual_report_sha = file_sha256(report_file)
    actual_ckpt_sha = file_sha256(ckpt_file)
    if actual_report_sha != VERIFIED_CONTROL_REPORT_SHA256:
        raise RuntimeError(
            f"fail-closed: control report SHA256 mismatch: {actual_report_sha} != {VERIFIED_CONTROL_REPORT_SHA256}"
        )
    if actual_ckpt_sha != VERIFIED_CONTROL_CHECKPOINT_SHA256:
        raise RuntimeError(
            f"fail-closed: control checkpoint SHA256 mismatch: {actual_ckpt_sha} != {VERIFIED_CONTROL_CHECKPOINT_SHA256}"
        )

    # 3. Load checkpoint and verify semantic hash and metadata
    ckpt = torch.load(ckpt_file, map_location="cpu", weights_only=False)
    if not isinstance(ckpt, dict) or "metadata" not in ckpt or "state_dict" not in ckpt:
        raise RuntimeError("fail-closed: checkpoint format corrupt")

    meta = ckpt["metadata"]
    actual_semantic_hash = checkpoint_semantic_hash(meta, ckpt["state_dict"])
    if actual_semantic_hash != VERIFIED_CONTROL_SEMANTIC_HASH:
        raise RuntimeError(
            f"fail-closed: control checkpoint semantic hash mismatch: {actual_semantic_hash} != {VERIFIED_CONTROL_SEMANTIC_HASH}"
        )

    _assert_equal(meta.get("model_id"), model_contract["model_id"], "control metadata model_id")
    _assert_equal(meta.get("model_role"), "control", "control metadata model_role")
    _assert_equal(meta.get("source_self_play_hash"), self_play_hash_value, "control metadata self_play_hash")
    _assert_equal(meta.get("source_self_play_file_sha256"), dataset_file_sha256, "control metadata dataset_sha")
    _assert_equal(meta.get("training_config_hash"), training_config_hash(config), "control metadata config_hash")
    _assert_equal(meta.get("catalog_hash"), catalog_semantic_hash(catalog), "control metadata catalog_hash")
    _assert_equal(meta.get("parameter_count"), int(model_contract["expected_parameter_count"]), "control param count")
    _assert_equal(meta.get("train_examples"), len(train_indices), "control train examples")
    _assert_equal(meta.get("validation_examples"), len(validation_indices), "control val examples")
    _assert_equal(meta.get("s1_reference_examples"), len(reference_indices), "control ref examples")
    _assert_equal(meta.get("encoded_cache_manifest_sha256"), cache_manifest_sha256(cache.root), "control cache manifest sha")

    # 4. Load report and verify history and selection
    report = json.loads(report_file.read_text(encoding="utf-8"))
    _assert_equal(report.get("model_id"), model_contract["model_id"], "control report model_id")
    _assert_equal(report.get("model_role"), "control", "control report model_role")
    _assert_equal(report.get("checkpoint_file_sha256"), actual_ckpt_sha, "control report ckpt sha")
    _assert_equal(report.get("checkpoint_hash"), VERIFIED_CONTROL_SEMANTIC_HASH, "control report checkpoint hash")

    epochs = int(config["training"]["epochs"])
    history = report.get("history", [])
    if len(history) != epochs:
        raise RuntimeError(f"fail-closed: control report history length {len(history)} != {epochs}")
    epoch_numbers = [h.get("epoch") for h in history]
    if epoch_numbers != list(range(1, epochs + 1)):
        raise RuntimeError(f"fail-closed: control report history epoch sequence invalid: {epoch_numbers}")

    # 5. Cooldown before re-evaluation and run BackgroundThermalGuard during evaluation
    require_fail_closed_cooldown(device=device, target_c=COOLDOWN_TARGET_C, timeout_s=COOLDOWN_TIMEOUT_SECONDS)
    print(f"Re-evaluating verified Control checkpoint ({model_contract['model_id']}) with current evaluator on {device}...")
    spec = ModelSpec(
        model_contract["architecture"],
        int(model_contract["hidden_dim"]),
        int(model_contract["blocks"]),
        float(model_contract["dropout"]),
        int(model_contract.get("interaction_blocks", 0)),
    )
    model = build_model(spec).to(device)
    model.load_state_dict(ckpt["state_dict"], strict=True)

    validation_set = PackedEncodedDataset(cache, validation_indices)
    reference_set = PackedEncodedDataset(cache, reference_indices)
    validation_loader = _loader(validation_set, int(config["training"]["batch_size"]), False, None, device)
    reference_loader = _loader(reference_set, int(config["training"]["batch_size"]), False, None, device)

    guard = BackgroundThermalGuard(device=device, interval_s=TELEMETRY_INTERVAL_SECONDS)
    guard.start()
    try:
        val_metrics = evaluate(model, validation_loader, device, abort_check=guard.check)
        ref_metrics = evaluate(model, reference_loader, device, abort_check=guard.check)
    finally:
        guard.stop()

    # DO NOT overwrite training-report.json; preserve original report file immutable
    updated_report = dict(report)
    updated_report["validation"] = val_metrics
    updated_report["s1_reference"] = ref_metrics
    updated_report["original_report_sha256"] = VERIFIED_CONTROL_REPORT_SHA256
    updated_report["checkpoint_file_sha256"] = VERIFIED_CONTROL_CHECKPOINT_SHA256
    updated_report["checkpoint_hash"] = VERIFIED_CONTROL_SEMANTIC_HASH
    updated_report["evaluator_reassessed"] = True

    print("Control re-evaluation complete; original report preserved immutable.")
    return updated_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the frozen M28B contextual interaction pair.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"))
    parser.add_argument("--encoded-cache", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    configure_cpu_runtime()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    validate_config(config)
    payload, actual_self_play_hash, dataset_file_sha256 = validate_dataset(args.dataset, config)
    train_indices, validation_indices, reference_indices = split_m28b_indices(payload, config)
    catalog = load_catalog(args.catalog)
    actual_catalog_hash = catalog_semantic_hash(catalog)
    _assert_equal(actual_catalog_hash, EXPECTED_CATALOG_HASH, "catalog semantic hash")
    cache = EncodedCache.load(args.encoded_cache)
    cache.validate_identity(
        dataset_file_sha256=dataset_file_sha256,
        self_play_hash=actual_self_play_hash,
        catalog_hash=actual_catalog_hash,
        examples=len(payload["examples"]),
    )

    training = config["training"]
    device = resolve_device(str(training["device"]))

    # M28B continuation requirement: out_dir MUST already exist with verified control
    if not args.out_dir.exists():
        raise RuntimeError(
            f"fail-closed: M28B continuation requires existing output directory with verified control checkpoint: {args.out_dir}"
        )

    control_dir = args.out_dir / "control"
    if not control_dir.exists():
        raise RuntimeError(
            f"fail-closed: M28B continuation requires existing control directory at {control_dir}"
        )
    candidate_dir = args.out_dir / "candidate"
    if candidate_dir.exists():
        raise RuntimeError(
            f"fail-closed: candidate directory already exists at {candidate_dir}; refusing to overwrite"
        )
    summary_file = args.out_dir / "summary.json"
    if summary_file.exists():
        raise RuntimeError(
            f"fail-closed: summary.json already exists at {summary_file}; refusing to overwrite"
        )

    # Check for unexpected entries
    allowed_entries = {"control"}
    for entry in args.out_dir.iterdir():
        if entry.name not in allowed_entries:
            raise RuntimeError(f"fail-closed: unexpected entry in output directory: {entry}")

    reports = []
    for idx, model_contract in enumerate(config["models"]):
        role = str(model_contract["role"])
        role_dir = args.out_dir / role

        # If role is control, verify and re-evaluate
        if role == "control":
            report = verify_and_reevaluate_control(
                model_contract,
                train_indices,
                validation_indices,
                reference_indices,
                cache,
                catalog,
                config,
                actual_self_play_hash,
                dataset_file_sha256,
                args.out_dir,
                device,
            )
            reports.append(report)
            continue

        if role_dir.exists():
            raise RuntimeError(f"fail-closed: role directory already exists: {role_dir}")

        if idx > 0 or len(reports) > 0:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            require_fail_closed_cooldown(device=device, target_c=COOLDOWN_TARGET_C, timeout_s=COOLDOWN_TIMEOUT_SECONDS)

        report = train_one(
            model_contract,
            train_indices,
            validation_indices,
            reference_indices,
            cache,
            catalog,
            config,
            actual_self_play_hash,
            dataset_file_sha256,
            args.out_dir,
        )
        reports.append(report)
    by_role = {report["model_role"]: report for report in reports}
    summary = {
        "format": "effective-splendor-m28b-interaction-training-summary",
        "version": 1,
        "milestone": "M28B",
        "training_config_hash": training_config_hash(config),
        "dataset_file_sha256": dataset_file_sha256,
        "self_play_hash": actual_self_play_hash,
        "runtime_repair": "m28b_runtime_repair_1",
        "cpu_runtime": dict(EXPECTED_CPU_THREADS),
        "encoded_cache_manifest_sha256": cache.manifest_sha256,
        "models": reports,
        "offline_comparison": offline_comparison(by_role["control"], by_role["candidate"], config),
        "arena_authorization": "NOT_AUTHORIZED",
        "promotion": "NONE",
        "champion": "M07",
    }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir), "offline_comparison": summary["offline_comparison"]}))


if __name__ == "__main__":
    main()
