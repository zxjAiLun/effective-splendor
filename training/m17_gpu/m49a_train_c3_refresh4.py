"""M49A-II C3: hard-target refresh every 4 epochs within each 8-epoch block.

Exactly one change versus the C1 hard-target reference is the refresh
granularity: C1 holds targets for all 8 epochs, C3 hard-copies online -> target
after epochs 4 and 8, recomputing Bellman labels between segments. The trainer
owns one seeded RNG and one AdamW optimizer for the full 80 x 8-epoch run.
Saved/evaluated checkpoints remain ONLINE-net weights. No interval sweep,
extra training data, live validation stopping, or Canonical evaluation.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from splendor_gpu.m49a_trainer import export_net_weights_dict, train_fqi_streaming

REPO = Path(__file__).resolve().parent.parent.parent
COMPACT_DIR = REPO / "local-artifacts/m49a-clean2-round2-compact"
RUN_DIR = REPO / "local-artifacts/m49a-c3-hard-refresh4"

# Frozen C3 contract. Keep constants literal; this entrypoint is not a sweep.
RUN_ID = "m49a-c3-hard-refresh4-v1"
FQI_ITERATIONS = 80
EPOCHS_PER_FQI = 8
HARD_TARGET_REFRESH_EPOCHS = 4
BATCH_SIZE = 256
LR = 1e-3
WEIGHT_DECAY = 1e-4
SEED = 49000001
CHECKPOINT_EVERY = 10
DEVICE = "cpu"
TOTAL_OPTIMIZER_EPOCHS = FQI_ITERATIONS * EPOCHS_PER_FQI
TOTAL_OPTIMIZER_STEPS = 92160  # ceil(36,674 / 256) * 640, no dropped tail.
_RUN_STATUS_ENABLED = False
_RUN_STARTED_AT = None

# Exact D2 identity from the accepted C1/C2 manifest. Do not train on a
# same-named but changed transport dataset.
FROZEN_D2_SHA256 = {
    "train/current_x.f32": "3925fba7c1be76bd1a64bf91d57ffa3a8b36fcf1f43131faf917707d82c16684",
    "train/step_costs.f32": "eb14824fdb0dc5e3ddff3c9471e3aa480f72912e0cf9ac47d5f4edd32e8fb59d",
    "train/outcomes.u8": "cd4f838fe643367fba885ee505fcb4233eb0de801a31a5f9390f70d8b4c79718",
    "train/compact_transitions.jsonl": "4948b8346d0ff30a2d7bce4ce7c9ba03fe28a69c3740f98f10a917198961d5ba",
    "val/current_x.f32": "85590f9934e5692a47e8d7c241a8e3f21bf29296ca235520615706772c8553b3",
    "val/step_costs.f32": "406ef86ff3786eeef0db679b4fdc4d59f75cc4b7bd662d64d9a795aea1bb6066",
    "val/outcomes.u8": "544bf02aa87624aa372fecae9f5604bfb1c71b8ee9553633b785c3236b8623c1",
    "val/compact_transitions.jsonl": "1640db39573756dda6b1df8eecb57f33e2c1d06ee079baf167a0a7a0b91dea9a",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_process_status(state: str, exit_code: int | None, error: str | None = None) -> None:
    if not _RUN_STATUS_ENABLED:
        return
    path = RUN_DIR / "process-status.json"
    temp_path = path.with_suffix(".json.tmp")
    payload = {
        "run_id": RUN_ID,
        "pid": os.getpid(),
        "state": state,
        "exit_code": exit_code,
        "started_at_utc": _RUN_STARTED_AT,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    temp_path.replace(path)


def main() -> None:
    global _RUN_STATUS_ENABLED, _RUN_STARTED_AT
    train_x = COMPACT_DIR / "train" / "current_x.f32"
    train_transitions = COMPACT_DIR / "train" / "compact_transitions.jsonl"
    val_x = COMPACT_DIR / "val" / "current_x.f32"
    val_transitions = COMPACT_DIR / "val" / "compact_transitions.jsonl"

    input_paths = {
        "train/current_x.f32": train_x,
        "train/step_costs.f32": COMPACT_DIR / "train" / "step_costs.f32",
        "train/outcomes.u8": COMPACT_DIR / "train" / "outcomes.u8",
        "train/compact_transitions.jsonl": train_transitions,
        "val/current_x.f32": COMPACT_DIR / "val" / "current_x.f32",
        "val/step_costs.f32": COMPACT_DIR / "val" / "step_costs.f32",
        "val/outcomes.u8": COMPACT_DIR / "val" / "outcomes.u8",
        "val/compact_transitions.jsonl": val_transitions,
    }
    for name, path in input_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing frozen D2 input {name}: {path}")

    input_hashes = {name: sha256_file(path) for name, path in input_paths.items()}
    if input_hashes != FROZEN_D2_SHA256:
        raise RuntimeError("D2 input hashes do not match the frozen C1 dataset; refusing C3")
    if train_x.stat().st_size != 36674 * 428 * 4:
        raise RuntimeError("D2 train current_x row count is not 36,674")
    if val_x.stat().st_size != 2402 * 428 * 4:
        raise RuntimeError("D2 validation current_x row count is not 2,402")
    if TOTAL_OPTIMIZER_EPOCHS != 640 or TOTAL_OPTIMIZER_STEPS != 92160:
        raise AssertionError("frozen C3 optimizer budget constants are inconsistent")

    # Never overwrite or mix a partial run with a new attempt.
    if RUN_DIR.exists() and any(RUN_DIR.iterdir()):
        raise FileExistsError(f"refusing to reuse non-empty C3 run directory: {RUN_DIR}")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = RUN_DIR / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    _RUN_STATUS_ENABLED = True
    _RUN_STARTED_AT = datetime.now(timezone.utc).isoformat()
    _write_process_status("running", None)

    print(
        f"C3 frozen contract: run_id={RUN_ID}, hard_refresh_epochs="
        f"{HARD_TARGET_REFRESH_EPOCHS}, FQI={FQI_ITERATIONS}, "
        f"epochs/FQI={EPOCHS_PER_FQI}, device={DEVICE}"
    )
    print("Checkpoint/eval objects: ONLINE net only; target net = label source only.")

    model, report = train_fqi_streaming(
        train_x_path=train_x,
        train_transitions_path=train_transitions,
        val_x_path=val_x,
        val_transitions_path=val_transitions,
        device=torch.device(DEVICE),
        epochs_per_fqi=EPOCHS_PER_FQI,
        fqi_iterations=FQI_ITERATIONS,
        batch_size=BATCH_SIZE,
        lr=LR,
        weight_decay=WEIGHT_DECAY,
        seed=SEED,
        checkpoint_dir=checkpoint_dir,
        checkpoint_every=CHECKPOINT_EVERY,
        target_update="hard",
        hard_target_refresh_epochs=HARD_TARGET_REFRESH_EPOCHS,
    )

    expected_config = {
        "target_update": "hard",
        "polyak_tau": None,
        "epochs_per_fqi": EPOCHS_PER_FQI,
        "fqi_iterations": FQI_ITERATIONS,
        "batch_size": BATCH_SIZE,
        "lr": LR,
        "weight_decay": WEIGHT_DECAY,
        "seed": SEED,
        "device": DEVICE,
        "hard_target_refresh_epochs": HARD_TARGET_REFRESH_EPOCHS,
    }
    if report.get("config") != expected_config:
        raise RuntimeError(f"trainer config drifted from frozen C3 contract: {report.get('config')}")
    if len(report.get("history", [])) != FQI_ITERATIONS:
        raise RuntimeError("C3 report does not contain exactly 80 completed blocks")

    final_input_hashes = {name: sha256_file(path) for name, path in input_paths.items()}
    if final_input_hashes != input_hashes or final_input_hashes != FROZEN_D2_SHA256:
        raise RuntimeError("C3 input files changed during training; refusing to publish run manifest")

    expected_checkpoint_names = [f"weights_iter{it:03d}.json" for it in range(10, 81, 10)]
    checkpoint_hashes = {}
    for name in expected_checkpoint_names:
        path = checkpoint_dir / name
        if not path.is_file():
            raise RuntimeError(f"missing expected C3 online checkpoint: {path}")
        checkpoint_hashes[name] = sha256_file(path)

    torch.save({"model_state": model.state_dict(), "report": report}, RUN_DIR / "c3_model.pt")
    with open(RUN_DIR / "c3_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    with open(RUN_DIR / "c3_weights.json", "w", encoding="utf-8") as f:
        json.dump(export_net_weights_dict(model), f)

    manifest = {
        "run_id": RUN_ID,
        "training_contract": {
            "baseline": "C1 hard-target (efa4298 / fd9dfba)",
            "only_change": "hard target refresh after epochs 4 and 8 within each 8-epoch comparison block",
            "target_update": "hard",
            "hard_target_refresh_epochs": HARD_TARGET_REFRESH_EPOCHS,
            "fqi_iterations": FQI_ITERATIONS,
            "epochs_per_fqi": EPOCHS_PER_FQI,
            "total_optimizer_epochs": TOTAL_OPTIMIZER_EPOCHS,
            "total_optimizer_steps": TOTAL_OPTIMIZER_STEPS,
            "batch_size": BATCH_SIZE,
            "lr": LR,
            "weight_decay": WEIGHT_DECAY,
            "seed": SEED,
            "device": DEVICE,
            "minibatch_rng": "one seeded stream; same torch.randperm sequence as C1",
            "checkpoint_schedule": [10, 20, 30, 40, 50, 60, 70, 80],
            "checkpoint_object": "online_net",
        },
        "d2_input_sha256": input_hashes,
        "checkpoints": checkpoint_hashes,
    }
    with open(checkpoint_dir / "training_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"C3 complete. Report: {RUN_DIR / 'c3_report.json'}")
    print(f"Manifest: {checkpoint_dir / 'training_manifest.json'}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt as exc:
        _write_process_status("interrupted", 130, f"{type(exc).__name__}: {exc}")
        raise
    except BaseException as exc:
        exit_code = exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, int) else 1
        _write_process_status("failed", exit_code, f"{type(exc).__name__}: {exc}")
        raise
    else:
        _write_process_status("completed", 0)
