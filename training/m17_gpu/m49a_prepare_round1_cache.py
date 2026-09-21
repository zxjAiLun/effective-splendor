"""Merge Round 0 train cache with Round 1 new transitions into Round 1 cache."""

import json
from pathlib import Path
import time
import torch

REPO = Path(__file__).resolve().parent.parent.parent
R0_CACHE = REPO / "local-artifacts/m49a-round0-cache/train_tensors.pt"
NEW_JSONL = REPO / "local-artifacts/m49a-round1-dataset/round1_new_train.jsonl"
OUT_CACHE = REPO / "local-artifacts/m49a-round1-cache/train_tensors.pt"


def main():
    t0 = time.time()
    print("Loading Round 0 base train cache...")
    r0 = torch.load(R0_CACHE, map_location="cpu", weights_only=False)

    print(f"Reading new Round 1 JSONL {NEW_JSONL}...")
    new_input_feats = []
    new_step_costs = []
    new_outcomes = []
    new_flat_next = []
    new_offsets = []
    new_running_indices = []

    base_len = r0["x"].shape[0]

    with open(NEW_JSONL, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            r = json.loads(line)
            new_input_feats.append(r["input_features"])
            new_step_costs.append(float(r["step_cost"]))

            outcome = r["outcome"]
            row_idx = base_len + i
            if outcome == "reached_15":
                new_outcomes.append(0)
            elif outcome in ("stalled", "turn_cap"):
                new_outcomes.append(1)
            elif outcome == "running":
                new_outcomes.append(2)
                next_f = r["next_action_features"]
                if not next_f:
                    new_outcomes[-1] = 1
                else:
                    start = len(new_flat_next)
                    new_flat_next.extend(next_f)
                    new_offsets.append((start, len(new_flat_next)))
                    new_running_indices.append(row_idx)
            else:
                raise ValueError(f"Unknown outcome {outcome}")

    print(f"Read {len(new_input_feats)} new rows in {time.time()-t0:.1f}s.")

    # Convert new data to tensors
    t_new_x = torch.tensor(new_input_feats, dtype=torch.float32)
    t_new_costs = torch.tensor(new_step_costs, dtype=torch.float32)
    t_new_outcomes = torch.tensor(new_outcomes, dtype=torch.long)
    t_new_flat_next = torch.tensor(new_flat_next, dtype=torch.float32)

    # Offset adjustments for flat_next
    base_flat_len = r0["flat_next"].shape[0]
    t_new_offsets = torch.tensor(new_offsets, dtype=torch.long) + base_flat_len
    t_new_running = torch.tensor(new_running_indices, dtype=torch.long)

    # Concatenate
    combined_x = torch.cat([r0["x"], t_new_x], dim=0)
    combined_costs = torch.cat([r0["step_costs"], t_new_costs], dim=0)
    combined_outcomes = torch.cat([r0["outcomes"], t_new_outcomes], dim=0)
    combined_flat_next = torch.cat([r0["flat_next"], t_new_flat_next], dim=0)
    combined_offsets = torch.cat([r0["offsets"], t_new_offsets], dim=0)
    combined_running = torch.cat([r0["running_indices"], t_new_running], dim=0)

    payload = {
        "x": combined_x,
        "step_costs": combined_costs,
        "outcomes": combined_outcomes,
        "flat_next": combined_flat_next,
        "offsets": combined_offsets,
        "running_indices": combined_running,
    }

    OUT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, OUT_CACHE)
    print(f"Saved combined Round 1 train cache: x={combined_x.shape} ({base_len} + {len(new_input_feats)}), "
          f"flat_next={combined_flat_next.shape} in {time.time()-t0:.1f}s to {OUT_CACHE}")


if __name__ == "__main__":
    main()
