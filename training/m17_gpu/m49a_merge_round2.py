"""Fast merger for Round 2."""

import json
from pathlib import Path
import time
import numpy as np
import torch

REPO = Path(__file__).resolve().parent.parent.parent
R1_CACHE = REPO / "local-artifacts/m49a-round1-cache/train_tensors.pt"
BIN_DIR = REPO / "local-artifacts/m49a-round2-cache"
OUT_CACHE = REPO / "local-artifacts/m49a-round2-cache/train_tensors.pt"


def main():
    t0 = time.time()
    print("Loading Round 1 train cache...")
    r1 = torch.load(R1_CACHE, map_location="cpu", weights_only=False)

    print("Loading binary Round 2 data...")
    with open(BIN_DIR / "new_meta.json", "r", encoding="utf-8") as f:
        meta = json.load(f)

    row_count = meta["rowCount"]
    flat_count = meta["flatCount"]

    new_x = np.fromfile(BIN_DIR / "new_x.bin", dtype=np.float32).reshape(row_count, 428)
    new_costs = np.fromfile(BIN_DIR / "new_costs.bin", dtype=np.float32)
    new_outcomes = np.fromfile(BIN_DIR / "new_outcomes.bin", dtype=np.int32)
    new_flat = np.fromfile(BIN_DIR / "new_flat.bin", dtype=np.float32).reshape(flat_count, 428)

    t_new_x = torch.from_numpy(new_x)
    t_new_costs = torch.from_numpy(new_costs)
    t_new_outcomes = torch.from_numpy(new_outcomes).long()
    t_new_flat = torch.from_numpy(new_flat)

    base_len = r1["x"].shape[0]
    base_flat_len = r1["flat_next"].shape[0]

    t_new_offsets = torch.tensor(meta["offsets"], dtype=torch.long) + base_flat_len
    t_new_running = torch.tensor(meta["runningIndices"], dtype=torch.long) + base_len

    combined_x = torch.cat([r1["x"], t_new_x], dim=0)
    combined_costs = torch.cat([r1["step_costs"], t_new_costs], dim=0)
    combined_outcomes = torch.cat([r1["outcomes"], t_new_outcomes], dim=0)
    combined_flat_next = torch.cat([r1["flat_next"], t_new_flat], dim=0)
    combined_offsets = torch.cat([r1["offsets"], t_new_offsets], dim=0)
    combined_running = torch.cat([r1["running_indices"], t_new_running], dim=0)

    assert torch.isfinite(combined_x).all(), "combined_x contains non-finite values"
    assert torch.isfinite(combined_costs).all(), "combined_costs contains non-finite values"
    assert torch.isfinite(combined_flat_next).all(), "combined_flat_next contains non-finite values"

    payload = {
        "x": combined_x,
        "step_costs": combined_costs,
        "outcomes": combined_outcomes,
        "flat_next": combined_flat_next,
        "offsets": combined_offsets,
        "running_indices": combined_running,
    }

    torch.save(payload, OUT_CACHE)
    print(f"Merged in {time.time()-t0:.2f}s: x={combined_x.shape} (23187 + {row_count} = {len(combined_x)}), flat_next={combined_flat_next.shape} to {OUT_CACHE}")


if __name__ == "__main__":
    main()
