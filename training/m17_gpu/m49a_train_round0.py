"""M49A-II: Run Streaming Round 0 FQI Training using memory-mapped binary current_x and Rust target builder."""

import argparse
import json
import sys
from pathlib import Path
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from splendor_gpu.m49a_trainer import train_fqi_streaming, export_net_weights_dict

REPO = Path(__file__).resolve().parent.parent.parent
COMPACT_DIR = REPO / "local-artifacts/m49a-round0-compact"
RUN_DIR = REPO / "local-artifacts/m49a-round0-run"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs-per-fqi", type=int, default=15)
    parser.add_argument("--fqi-iterations", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compact-dir", type=str, default=str(COMPACT_DIR))
    parser.add_argument("--out-dir", type=str, default=str(RUN_DIR))
    args = parser.parse_args()

    compact_dir = Path(args.compact_dir)
    train_x = compact_dir / "train" / "current_x.f32"
    train_transitions = compact_dir / "train" / "compact_transitions.jsonl"
    val_x = compact_dir / "val" / "current_x.f32"
    val_transitions = compact_dir / "val" / "compact_transitions.jsonl"

    if not train_x.is_file() or not train_transitions.is_file():
        raise FileNotFoundError(f"Missing train dataset in {compact_dir / 'train'}")
    if not val_x.is_file() or not val_transitions.is_file():
        raise FileNotFoundError(f"Missing validation dataset in {compact_dir / 'val'}")

    device = torch.device(args.device)
    print(f"Starting Streaming FQI training on {device}...")
    model, report = train_fqi_streaming(
        train_x_path=train_x,
        train_transitions_path=train_transitions,
        val_x_path=val_x,
        val_transitions_path=val_transitions,
        device=device,
        epochs_per_fqi=args.epochs_per_fqi,
        fqi_iterations=args.fqi_iterations,
        batch_size=args.batch_size,
        lr=args.lr,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "q0_model.pt"
    torch.save({"model_state": model.state_dict(), "report": report}, ckpt_path)
    print(f"Saved Q0 checkpoint to {ckpt_path}")

    report_path = out_dir / "q0_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Saved Q0 report to {report_path}")

    # Also automatically export weights JSON for native Rust evaluation
    weights_path = out_dir / "q0_weights.json"
    weights_dict = export_net_weights_dict(model)
    with open(weights_path, "w", encoding="utf-8") as f:
        json.dump(weights_dict, f)
    print(f"Exported Q0 weights to {weights_path}")


if __name__ == "__main__":
    main()
