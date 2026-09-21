"""Export PyTorch EfficiencyQNet weights to flat JSON for Rust native evaluation."""

import json
from pathlib import Path
import torch

REPO = Path(__file__).resolve().parent.parent.parent
CKPT_PATH = REPO / "local-artifacts/m49a-round0-run/q0_model.pt"
OUT_PATH = REPO / "local-artifacts/m49a-round0-run/q0_weights.json"


def export():
    data = torch.load(CKPT_PATH, map_location="cpu", weights_only=False)
    state = data["model_state"]

    weights = {
        "fc1_w": state["fc1.weight"].tolist(),  # [256, 428]
        "fc1_b": state["fc1.bias"].tolist(),    # [256]
        "ln1_w": state["ln1.weight"].tolist(),  # [256]
        "ln1_b": state["ln1.bias"].tolist(),    # [256]
        "fc2_w": state["fc2.weight"].tolist(),  # [128, 256]
        "fc2_b": state["fc2.bias"].tolist(),    # [128]
        "fc3_w": state["fc3.weight"].tolist(),  # [1, 128]
        "fc3_b": state["fc3.bias"].tolist(),    # [1]
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(weights, f)
    print(f"Exported Q0 weights to {OUT_PATH} (fc1={len(weights['fc1_w'])}x{len(weights['fc1_w'][0])})")


if __name__ == "__main__":
    export()
