"""Pre-process JSONL datasets into pre-batched PyTorch tensors for fast FQI iterations."""

import json
from pathlib import Path
import time
import torch

REPO = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = REPO / "local-artifacts/m49a-round0-dataset"
CACHE_DIR = REPO / "local-artifacts/m49a-round0-cache"


def process_split(split_name: str):
    jsonl_path = DATASET_DIR / f"m49a_round0_{split_name}.jsonl"
    out_path = CACHE_DIR / f"{split_name}_tensors.pt"

    print(f"Processing {jsonl_path}...")
    t0 = time.time()

    input_feats = []
    step_costs = []
    outcomes = []  # 0: reached_15, 1: stalled/turn_cap, 2: running

    flat_next_feats = []
    offsets = []  # (start, end)
    running_row_indices = []

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            r = json.loads(line)
            input_feats.append(r["input_features"])
            step_costs.append(float(r["step_cost"]))

            outcome = r["outcome"]
            if outcome == "reached_15":
                outcomes.append(0)
            elif outcome in ("stalled", "turn_cap"):
                outcomes.append(1)
            elif outcome == "running":
                outcomes.append(2)
                next_f = r["next_action_features"]
                if not next_f:
                    # treat as stalled
                    outcomes[-1] = 1
                else:
                    start = len(flat_next_feats)
                    flat_next_feats.extend(next_f)
                    offsets.append((start, len(flat_next_feats)))
                    running_row_indices.append(i)
            else:
                raise ValueError(f"Unknown outcome {outcome}")

    x = torch.tensor(input_feats, dtype=torch.float32)
    step_costs = torch.tensor(step_costs, dtype=torch.float32)
    outcomes = torch.tensor(outcomes, dtype=torch.long)
    flat_next = torch.tensor(flat_next_feats, dtype=torch.float32)
    offsets = torch.tensor(offsets, dtype=torch.long)
    running_indices = torch.tensor(running_row_indices, dtype=torch.long)

    payload = {
        "x": x,
        "step_costs": step_costs,
        "outcomes": outcomes,
        "flat_next": flat_next,
        "offsets": offsets,
        "running_indices": running_indices,
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(payload, out_path)
    print(f"  Saved {split_name} cache in {time.time()-t0:.2f}s: x={x.shape}, flat_next={flat_next.shape} to {out_path}")


def main():
    process_split("train")
    process_split("validation")


if __name__ == "__main__":
    main()
