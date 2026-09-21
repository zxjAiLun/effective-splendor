"""Cross-language Q forward pass parity test matching Rust EfficiencyQWeightsV1."""

import json
from pathlib import Path
import pytest
import torch
import torch.nn as nn
from splendor_gpu.m49a_trainer import EfficiencyQNet


def test_q_forward_parity():
    fixture_path = Path("crates/splendor-learning/tests/fixtures/m49a_q_forward_parity_v1.json")
    assert fixture_path.is_file(), f"missing fixture at {fixture_path}"

    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    weights = payload["weights"]
    inputs = torch.tensor(payload["inputs"], dtype=torch.float32)
    expected_outputs = payload["outputs"]

    net = EfficiencyQNet(428)
    net.fc1.weight.data = torch.tensor(weights["fc1_w"], dtype=torch.float32)
    net.fc1.bias.data = torch.tensor(weights["fc1_b"], dtype=torch.float32)
    net.ln1.weight.data = torch.tensor(weights["ln1_w"], dtype=torch.float32)
    net.ln1.bias.data = torch.tensor(weights["ln1_b"], dtype=torch.float32)
    net.fc2.weight.data = torch.tensor(weights["fc2_w"], dtype=torch.float32)
    net.fc2.bias.data = torch.tensor(weights["fc2_b"], dtype=torch.float32)
    net.fc3.weight.data = torch.tensor(weights["fc3_w"], dtype=torch.float32)
    net.fc3.bias.data = torch.tensor(weights["fc3_b"], dtype=torch.float32)

    net.eval()
    with torch.no_grad():
        actual_outputs = net(inputs).tolist()

    for idx, (actual, expected) in enumerate(zip(actual_outputs, expected_outputs)):
        diff = abs(actual - expected)
        assert diff < 1e-5, f"Sample {idx} mismatch: actual={actual}, expected={expected}, diff={diff}"
