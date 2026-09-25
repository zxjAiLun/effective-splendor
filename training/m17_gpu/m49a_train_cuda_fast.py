"""Owner-authorized CUDA fast-iteration FQI run (not comparable to legacy C1/C2)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m49a_build_cuda_cache import (  # noqa: E402
    CACHE_DIR,
    COMPACT_DIR,
    EXPORTER_EXE,
    EXPORTER_SHA256,
    EXPORTER_SOURCE_COMMIT,
    FROZEN_D2_SHA256,
    sha256_file,
    snapshot_input_hashes,
    verify_existing_cache,
    verify_exporter,
)
from splendor_gpu.m49a_cuda_trainer import (  # noqa: E402
    SuccessorFeatureCache,
    train_fqi_cuda_cached,
)
from splendor_gpu.m49a_trainer import export_net_weights_dict  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RUN_ID = "m49a-cuda-fast-v1"
RUN_DIR = REPO / "local-artifacts/m49a-cuda-fast-v1"
CHECKPOINT_EVERY = 10
FQI_ITERATIONS = 80
EPOCHS_PER_FQI = 8
HARD_TARGET_REFRESH_EPOCHS = 4
BATCH_SIZE = 256
ACTION_BATCH_SIZE = 131072
LR = 1e-3
WEIGHT_DECAY = 1e-4
SEED = 49000001
FAILURE_PENALTY = 100.0
DEVICE = torch.device("cuda:0")
ALLOW_TF32 = True
SOURCE_RELATIVE_PATHS = (
    "training/m17_gpu/m49a_train_cuda_fast.py",
    "training/m17_gpu/m49a_build_cuda_cache.py",
    "training/m17_gpu/splendor_gpu/m49a_cuda_trainer.py",
    "training/m17_gpu/splendor_gpu/m49a_trainer.py",
    "training/m17_gpu/m49a_train_c3_refresh4.py",
)

_STATUS_ENABLED = False
_STARTED_AT: str | None = None


def _write_status(state: str, exit_code: int | None, error: str | None = None) -> None:
    if not _STATUS_ENABLED:
        return
    payload = {
        "run_id": RUN_ID,
        "pid": os.getpid(),
        "state": state,
        "exit_code": exit_code,
        "started_at_utc": _STARTED_AT,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }
    tmp = RUN_DIR / "process-status.json.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(RUN_DIR / "process-status.json")


def _write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(path)


def _git_output(args: list[str]) -> str:
    kwargs: dict[str, Any] = {
        "cwd": REPO,
        "capture_output": True,
        "text": True,
        "check": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(["git", *args], **kwargs).stdout.strip()


def _git_head() -> str:
    return _git_output(["rev-parse", "HEAD"])


def _source_hashes(*, require_clean: bool) -> dict[str, str]:
    if require_clean:
        dirty = _git_output(["status", "--porcelain", "--", *SOURCE_RELATIVE_PATHS])
        if dirty:
            raise RuntimeError("training source files have uncommitted changes:\\n" + dirty)
    return {
        relative: sha256_file(REPO / relative)
        for relative in SOURCE_RELATIVE_PATHS
    }


def _validate_shapes() -> tuple[int, int]:
    train_x = COMPACT_DIR / "train/current_x.f32"
    val_x = COMPACT_DIR / "val/current_x.f32"
    if train_x.stat().st_size != 36674 * 428 * 4:
        raise ValueError("train current_x is not the expected [36674, 428] D2 matrix")
    if val_x.stat().st_size != 2402 * 428 * 4:
        raise ValueError("validation current_x is not the expected [2402, 428] D2 matrix")
    return 36674, 2402


def main() -> None:
    global _STATUS_ENABLED, _STARTED_AT
    source_commit_start = _git_head()
    source_hashes = _source_hashes(require_clean=True)
    input_hashes = snapshot_input_hashes()
    if input_hashes != FROZEN_D2_SHA256:
        raise RuntimeError("D2 input hashes differ from the fixed dataset")
    exporter_hash = verify_exporter()
    cache_manifest = verify_existing_cache(input_hashes, exporter_hash)
    train_rows, val_rows = _validate_shapes()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; this fast path does not fall back to CPU")
    if not RUN_DIR.exists():
        RUN_DIR.mkdir(parents=True)
    if any(RUN_DIR.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty run directory: {RUN_DIR}")

    train_cache = SuccessorFeatureCache(CACHE_DIR / "train", train_rows)
    val_cache = SuccessorFeatureCache(CACHE_DIR / "val", val_rows)
    checkpoint_dir = RUN_DIR / "checkpoints"
    checkpoint_dir.mkdir()

    torch.backends.cuda.matmul.allow_tf32 = ALLOW_TF32
    torch.backends.cudnn.allow_tf32 = ALLOW_TF32
    torch.cuda.reset_peak_memory_stats(DEVICE)
    _STARTED_AT = datetime.now(timezone.utc).isoformat()
    _STATUS_ENABLED = True
    _write_status("running", None)

    gpu = torch.cuda.get_device_properties(DEVICE)
    print(
        f"CUDA fast run: {RUN_ID}; device={gpu.name}; VRAM={gpu.total_memory / 2**30:.2f} GiB; "
        f"TF32={ALLOW_TF32}; cache actions train/val="
        f"{train_cache.successor_count}/{val_cache.successor_count}",
        flush=True,
    )
    print(
        f"Budget: FQI={FQI_ITERATIONS} x {EPOCHS_PER_FQI} epochs, "
        f"refresh={HARD_TARGET_REFRESH_EPOCHS}, batch={BATCH_SIZE}, "
        f"steps={FQI_ITERATIONS * EPOCHS_PER_FQI * ((train_rows + BATCH_SIZE - 1) // BATCH_SIZE)}",
        flush=True,
    )

    model, report = train_fqi_cuda_cached(
        train_x_path=COMPACT_DIR / "train/current_x.f32",
        train_cache=train_cache,
        train_costs_path=COMPACT_DIR / "train/step_costs.f32",
        train_outcomes_path=COMPACT_DIR / "train/outcomes.u8",
        val_x_path=COMPACT_DIR / "val/current_x.f32",
        val_cache=val_cache,
        val_costs_path=COMPACT_DIR / "val/step_costs.f32",
        val_outcomes_path=COMPACT_DIR / "val/outcomes.u8",
        device=DEVICE,
        fqi_iterations=FQI_ITERATIONS,
        epochs_per_fqi=EPOCHS_PER_FQI,
        hard_target_refresh_epochs=HARD_TARGET_REFRESH_EPOCHS,
        batch_size=BATCH_SIZE,
        action_batch_size=ACTION_BATCH_SIZE,
        lr=LR,
        weight_decay=WEIGHT_DECAY,
        seed=SEED,
        checkpoint_dir=checkpoint_dir,
        checkpoint_every=CHECKPOINT_EVERY,
        progress_path=RUN_DIR / "progress.json",
    )

    expected_config = {
        "target_update": "hard",
        "hard_target_refresh_epochs": HARD_TARGET_REFRESH_EPOCHS,
        "fqi_iterations": FQI_ITERATIONS,
        "epochs_per_fqi": EPOCHS_PER_FQI,
        "batch_size": BATCH_SIZE,
        "action_batch_size": ACTION_BATCH_SIZE,
        "lr": LR,
        "weight_decay": WEIGHT_DECAY,
        "failure_penalty": FAILURE_PENALTY,
        "seed": SEED,
        "device": str(DEVICE),
        "cuda_tf32": ALLOW_TF32,
        "optimizer_fused": True,
        "target_builder_runtime": "precomputed_split_cache_cuda",
    }
    if report.get("config") != expected_config:
        raise RuntimeError(f"trainer config drift: {report.get('config')}")
    if len(report.get("history", [])) != FQI_ITERATIONS:
        raise RuntimeError("GPU trainer did not complete all 80 blocks")

    final_input_hashes = snapshot_input_hashes()
    if final_input_hashes != input_hashes:
        raise RuntimeError("D2 source data changed during training")
    final_exporter_hash = verify_exporter()
    if final_exporter_hash != exporter_hash:
        raise RuntimeError("frozen cache exporter changed during training")
    final_cache = verify_existing_cache(input_hashes, exporter_hash)
    if final_cache.get("manifest_sha256") != cache_manifest.get("manifest_sha256"):
        raise RuntimeError("feature cache manifest or output hashes changed during training")
    final_cache_manifest_hash = sha256_file(CACHE_DIR / "cache_manifest.json")
    final_source_hashes = _source_hashes(require_clean=False)
    if final_source_hashes != source_hashes:
        raise RuntimeError("training source files changed during the CUDA run")
    source_commit_end = _git_head()

    checkpoint_hashes: dict[str, str] = {}
    for iteration in range(CHECKPOINT_EVERY, FQI_ITERATIONS + 1, CHECKPOINT_EVERY):
        name = f"weights_iter{iteration:03d}.json"
        path = checkpoint_dir / name
        if not path.is_file():
            raise RuntimeError(f"missing online checkpoint: {path}")
        checkpoint_hashes[name] = sha256_file(path)

    report["provenance"] = {
        "git_commit_start": source_commit_start,
        "git_commit_end": source_commit_end,
        "source_sha256": source_hashes,
    }
    report["runtime"] = {
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu_name": gpu.name,
        "gpu_total_memory_bytes": int(gpu.total_memory),
        "peak_cuda_memory_bytes": int(torch.cuda.max_memory_allocated(DEVICE)),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "cuda_tf32": ALLOW_TF32,
        "cache_manifest_sha256": final_cache_manifest_hash,
    }
    torch.save({"model_state": model.state_dict(), "report": report}, RUN_DIR / "model.pt")
    _write_json(RUN_DIR / "report.json", report)
    _write_json(RUN_DIR / "weights.json", export_net_weights_dict(model))
    run_manifest = {
        "run_id": RUN_ID,
        "classification": "owner-authorized exploratory CUDA fast-iteration run; not comparable to historical CPU C1/C2/C3",
        "training_contract": {
            "objective": "same Solo15 cost-to-reach-15 Bellman objective",
            "fqi_iterations": FQI_ITERATIONS,
            "epochs_per_fqi": EPOCHS_PER_FQI,
            "hard_target_refresh_epochs": HARD_TARGET_REFRESH_EPOCHS,
            "batch_size": BATCH_SIZE,
            "action_batch_size": ACTION_BATCH_SIZE,
            "lr": LR,
            "weight_decay": WEIGHT_DECAY,
            "failure_penalty": FAILURE_PENALTY,
            "seed": SEED,
            "device": str(DEVICE),
            "tf32": ALLOW_TF32,
            "optimizer_fused": True,
            "checkpoint_schedule": list(range(CHECKPOINT_EVERY, FQI_ITERATIONS + 1, CHECKPOINT_EVERY)),
            "checkpoint_object": "online_net",
        },
        "d2_input_sha256": final_input_hashes,
        "source_identity": {
            "git_commit_start": source_commit_start,
            "git_commit_end": source_commit_end,
            "source_sha256": source_hashes,
        },
        "successor_cache": {
            "path": str(CACHE_DIR.relative_to(REPO)).replace("\\", "/"),
            "manifest_sha256": final_cache_manifest_hash,
            "exporter_sha256": final_exporter_hash,
            "exporter_source_commit": EXPORTER_SOURCE_COMMIT,
        },
        "checkpoints": checkpoint_hashes,
        "runtime": report["runtime"],
    }
    _write_json(checkpoint_dir / "training_manifest.json", run_manifest)
    _write_json(RUN_DIR / "run_manifest.json", run_manifest)
    print(f"CUDA run complete: {RUN_DIR / 'report.json'}", flush=True)
    _write_status("completed", 0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt as exc:
        _write_status("interrupted", 130, f"{type(exc).__name__}: {exc}")
        raise
    except BaseException as exc:
        exit_code = exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, int) else 1
        _write_status("failed", exit_code, f"{type(exc).__name__}: {exc}")
        raise
