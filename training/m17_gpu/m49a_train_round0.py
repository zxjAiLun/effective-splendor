"""M49A-II: Run Fast Round 0 FQI Training from pre-batched cache."""

import argparse
import json
import sys
from pathlib import Path
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from splendor_gpu.m49a_trainer import train_fqi_from_cache

REPO = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = REPO / "local-artifacts/m49a-round0-cache"
RUN_DIR = REPO / "local-artifacts/m49a-round0-run"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs-per-fqi", type=int, default=15)
    parser.add_argument("--fqi-iterations", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    train_path = CACHE_DIR / "train_tensors.pt"
    val_path = CACHE_DIR / "validation_tensors.pt"

    if not train_path.is_file() or not val_path.is_file():
        raise FileNotFoundError("Run m49a_prepare_cache.py first!")

    print(f"Loading tensor cache from {CACHE_DIR}...")
    train_cache = torch.load(train_path, map_location=args.device, weights_only=False)
    val_cache = torch.load(val_path, map_location=args.device, weights_only=False)

    device = torch.device(args.device)
    model, report = train_fqi_from_cache(
        train_cache,
        val_cache,
        device=device,
        epochs_per_fqi=args.epochs_per_fqi,
        fqi_iterations=args.fqi_iterations,
        batch_size=args.batch_size,
        lr=args.lr,
    )

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    ckpt_path = RUN_DIR / "q0_model.pt"
    torch.save({"model_state": model.state_dict(), "report": report}, ckpt_path)
    print(f"Saved Q0 checkpoint to {ckpt_path}")

    report_path = RUN_DIR / "q0_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Saved Q0 report to {report_path}")


if __name__ == "__main__":
    main()
