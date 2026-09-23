"""M49A-II C2: Polyak target-update stability control (FROZEN contract).

Exactly one change versus the C1 hard-target baseline:

    target = 0.95 * target + 0.05 * online          (tau = 0.05)

applied once after each complete FQI iteration. Everything else is identical
to C1: fixed D2 (36,674 transitions), same network/optimizer/seed/batch,
8 epochs/FQI, exactly 80 FQI updates (NO extension to 100/120), checkpoints
every 10 updates. Saved/evaluated checkpoints are the ONLINE network in both
arms. No tau sweep. No live validation early stopping. Canonical 64 HOLD.

Discipline: tau is a frozen module constant, not a CLI flag, so this script
cannot be repurposed into a tau sweep without an explicit code change.
"""

import hashlib
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from splendor_gpu.m49a_trainer import export_net_weights_dict, train_fqi_streaming

REPO = Path(__file__).resolve().parent.parent.parent
COMPACT_DIR = REPO / "local-artifacts/m49a-clean2-round2-compact"
RUN_DIR = REPO / "local-artifacts/m49a-c2-polyak005"

# Frozen C2 contract (owner-authorized; single-variable vs C1).
RUN_ID = "m49a-c2-polyak005-v1"
POLYAK_TAU = 0.05
FQI_ITERATIONS = 80
EPOCHS_PER_FQI = 8
BATCH_SIZE = 256
LR = 1e-3
WEIGHT_DECAY = 1e-4
SEED = 49000001
CHECKPOINT_EVERY = 10
DEVICE = "cpu"  # C1 arm ran on CPU; keep device parity for clean comparison.

# Exact eight-file D2 transport identity recorded before C1a; do not silently
# train a same-named but changed dataset. These hashes include the binary
# current-side data and compact on-demand target records for train and val.
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


def main():
    train_x = COMPACT_DIR / "train" / "current_x.f32"
    train_transitions = COMPACT_DIR / "train" / "compact_transitions.jsonl"
    val_x = COMPACT_DIR / "val" / "current_x.f32"
    val_transitions = COMPACT_DIR / "val" / "compact_transitions.jsonl"
    for p in (train_x, train_transitions, val_x, val_transitions):
        if not p.is_file():
            raise FileNotFoundError(f"missing C2 input: {p}")

    input_paths = {
        "train/current_x.f32": train_x,
        "train/step_costs.f32": COMPACT_DIR / "train" / "step_costs.f32",
        "train/outcomes.u8": COMPACT_DIR / "train" / "outcomes.u8",
        "train/compact_transitions.jsonl": train_transitions,
        "val/current_x.f32": val_x,
        "val/step_costs.f32": COMPACT_DIR / "val" / "step_costs.f32",
        "val/outcomes.u8": COMPACT_DIR / "val" / "outcomes.u8",
        "val/compact_transitions.jsonl": val_transitions,
    }
    for name, path in input_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing frozen D2 input {name}: {path}")
    input_hashes = {name: sha256_file(path) for name, path in input_paths.items()}
    if input_hashes != FROZEN_D2_SHA256:
        raise RuntimeError("D2 input hashes do not match the frozen C1 dataset; refusing C2")
    if train_x.stat().st_size != 36674 * 428 * 4:
        raise RuntimeError("D2 train current_x row count is not 36,674")
    if val_x.stat().st_size != 2402 * 428 * 4:
        raise RuntimeError("D2 validation current_x row count is not 2,402")

    # Never overwrite or silently mix checkpoints from an earlier/partial run.
    if RUN_DIR.exists() and any(RUN_DIR.iterdir()):
        raise FileExistsError(f"refusing to reuse non-empty C2 run directory: {RUN_DIR}")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = RUN_DIR / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)

    print(f"C2 frozen contract: run_id={RUN_ID}, tau={POLYAK_TAU}, "
          f"FQI={FQI_ITERATIONS}, epochs/FQI={EPOCHS_PER_FQI}, device={DEVICE}")
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
        target_update="polyak",
        polyak_tau=POLYAK_TAU,
    )

    final_input_hashes = {name: sha256_file(path) for name, path in input_paths.items()}
    if final_input_hashes != input_hashes or final_input_hashes != FROZEN_D2_SHA256:
        raise RuntimeError("C2 input files changed during training; refusing to publish run manifest")

    torch.save({"model_state": model.state_dict(), "report": report},
               RUN_DIR / "c2_model.pt")
    with open(RUN_DIR / "c2_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    final_weights = export_net_weights_dict(model)
    with open(RUN_DIR / "c2_weights.json", "w", encoding="utf-8") as f:
        json.dump(final_weights, f)

    # C1a-P2: lightweight training-run identity. Binds the selection input to
    # this exact run: config, D2 input hashes, and per-checkpoint weight hashes.
    manifest = {
        "run_id": RUN_ID,
        "training_contract": {
            "baseline": "C1 hard-target (efa4298 / fd9dfba)",
            "only_change": "polyak target update tau=0.05 once per FQI iteration",
            "target_update": "polyak",
            "polyak_tau": POLYAK_TAU,
            "fqi_iterations": FQI_ITERATIONS,
            "epochs_per_fqi": EPOCHS_PER_FQI,
            "batch_size": BATCH_SIZE,
            "lr": LR,
            "weight_decay": WEIGHT_DECAY,
            "seed": SEED,
            "device": DEVICE,
            "checkpoint_schedule": [10, 20, 30, 40, 50, 60, 70, 80],
            "checkpoint_object": "online_net",
        },
        "d2_input_sha256": input_hashes,
        "checkpoints": {
            f"weights_iter{it:03d}.json": sha256_file(checkpoint_dir / f"weights_iter{it:03d}.json")
            for it in (10, 20, 30, 40, 50, 60, 70, 80)
        },
    }
    with open(checkpoint_dir / "training_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"C2 complete. Report: {RUN_DIR / 'c2_report.json'}")
    print(f"Manifest: {checkpoint_dir / 'training_manifest.json'}")


if __name__ == "__main__":
    main()
