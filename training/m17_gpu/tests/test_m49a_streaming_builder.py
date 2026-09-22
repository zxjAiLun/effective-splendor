"""Verification tests for M49A streaming target builder vs reference calculation."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
import torch

from splendor_gpu.m49a_trainer import EfficiencyQNet


def test_streaming_target_builder_cli_parity():
    # 1. Create a dummy synthetic EfficiencyQNet
    torch.manual_seed(42)
    net = EfficiencyQNet(in_features=428, hidden1=256, hidden2=128)

    # Convert weights to dict matching EfficiencyQWeightsV1
    state = net.state_dict()
    weights_dict = {
        "fc1_w": state["fc1.weight"].cpu().numpy().tolist(),
        "fc1_b": state["fc1.bias"].cpu().numpy().tolist(),
        "ln1_w": state["ln1.weight"].cpu().numpy().tolist(),
        "ln1_b": state["ln1.bias"].cpu().numpy().tolist(),
        "fc2_w": state["fc2.weight"].cpu().numpy().tolist(),
        "fc2_b": state["fc2.bias"].cpu().numpy().tolist(),
        "fc3_w": state["fc3.weight"].cpu().numpy().tolist(),
        "fc3_b": state["fc3.bias"].cpu().numpy().tolist(),
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        weights_file = tmp_path / "weights.json"
        with open(weights_file, "w") as f:
            json.dump(weights_dict, f)

        # 2. Create sample compact transitions:
        # - Reached15 main: step_cost=1.0 -> target=1.0
        # - Reached15 noble: step_cost=0.0 -> target=0.0
        # - Stalled main: step_cost=1.0 -> target=101.0
        # - TurnCap main: step_cost=1.0 -> target=101.0
        transitions = [
            {
                "step_cost": 1.0,
                "outcome": "reached15",
                "next_observation": None,
                "next_legal_actions": [],
                "next_remaining_main_turns": 10,
                "max_main_turns": 35,
            },
            {
                "step_cost": 0.0,
                "outcome": "reached15",
                "next_observation": None,
                "next_legal_actions": [],
                "next_remaining_main_turns": 10,
                "max_main_turns": 35,
            },
            {
                "step_cost": 1.0,
                "outcome": "stalled",
                "next_observation": None,
                "next_legal_actions": [],
                "next_remaining_main_turns": 0,
                "max_main_turns": 35,
            },
            {
                "step_cost": 1.0,
                "outcome": "turn_cap",
                "next_observation": None,
                "next_legal_actions": [],
                "next_remaining_main_turns": 0,
                "max_main_turns": 35,
            },
        ]

        trans_file = tmp_path / "compact_transitions.jsonl"
        with open(trans_file, "w") as f:
            for t in transitions:
                f.write(json.dumps(t) + "\n")

        targets_file = tmp_path / "targets.f32"

        # 3. Call Rust CLI: splendor m49a-build-targets
        cmd = [
            "cargo",
            "run",
            "-q",
            "-p",
            "splendor-cli",
            "--bin",
            "splendor",
            "--",
            "m49a-build-targets",
            "--transitions",
            str(trans_file),
            "--weights",
            str(weights_file),
            "--out-targets",
            str(targets_file),
            "--failure-penalty",
            "100.0",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0, f"m49a-build-targets failed: {res.stderr}\n{res.stdout}"

        # 4. Read binary float32 targets
        raw_bytes = targets_file.read_bytes()
        targets = np.frombuffer(raw_bytes, dtype=np.float32)
        assert len(targets) == 4

        expected = np.array([1.0, 0.0, 101.0, 101.0], dtype=np.float32)
        np.testing.assert_allclose(targets, expected, atol=1e-5)
