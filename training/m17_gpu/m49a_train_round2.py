"""M49A-II: Run Round 2 FQI Training on the fully aggregated dataset (34,364 transitions)."""

import argparse
import json
import sys
from pathlib import Path
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from splendor_gpu.m49a_trainer import train_fqi_from_cache

REPO = Path(__file__).resolve().parent.parent.parent
R2_CACHE_DIR = REPO / "local-artifacts/m49a-round2-cache"
VAL_CACHE_PATH = REPO / "local-artifacts/m49a-round0-cache/validation_tensors.pt"
RUN_DIR = REPO / "local-artifacts/m49a-round2-run"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs-per-fqi", type=int, default=6)
    parser.add_argument("--fqi-iterations", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    train_path = R2_CACHE_DIR / "train_tensors.pt"
    val_path = VAL_CACHE_PATH

    print(f"Loading Round 2 train cache from {train_path}...")
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
    ckpt_path = RUN_DIR / "q2_model.pt"
    torch.save({"model_state": model.state_dict(), "report": report}, ckpt_path)
    print(f"Saved Q2 checkpoint to {ckpt_path}")

    # Export weights for Rust evaluation
    state = model.state_dict()
    weights = {
        "fc1_w": state["fc1.weight"].tolist(),
        "fc1_b": state["fc1.bias"].tolist(),
        "ln1_w": state["ln1.weight"].tolist(),
        "ln1_b": state["ln1.bias"].tolist(),
        "fc2_w": state["fc2.weight"].tolist(),
        "fc2_b": state["fc2.bias"].tolist(),
        "fc3_w": state["fc3.weight"].tolist(),
        "fc3_b": state["fc3.bias"].tolist(),
    }
    weights_path = RUN_DIR / "q2_weights.json"
    with open(weights_path, "w", encoding="utf-8") as f:
        json.dump(weights, f)
    print(f"Exported Q2 weights to {weights_path}")

    report_path = RUN_DIR / "q2_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
