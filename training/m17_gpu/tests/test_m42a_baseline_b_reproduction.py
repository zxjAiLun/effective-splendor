"""P0 Hard Gate: Verify reproduction of immutable baseline B (M41A-F Run 3)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import torch

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m35a_registry import load_and_validate_checkpoint
from splendor_gpu.m41a_train import M41AArm, M41AQHead, load_split
from splendor_gpu.m41a_p4_diagnostics import (
    score_states,
    metrics,
    DELTA_RANK,
    DELTA_REGRET,
)
from splendor_gpu.m42a_model import create_m42a_paired_arms

REPO = Path(__file__).resolve().parent.parent.parent.parent
CATALOG_PATH = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
RUN = REPO / "local-artifacts/m41a-run"
CORPUS = REPO / "local-artifacts/m41a-corpus"


def test_baseline_b_reproduction():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    catalog = load_catalog(CATALOG_PATH)
    val_games = load_split("validation")
    assert len(val_games) == 48

    # Load source indices
    source_indices = []
    for gdir in sorted((CORPUS / "validation").glob("game-*")):
        for sdir in sorted(gdir.glob("branch-ply*")):
            manifest = json.loads((sdir / "state-manifest.json").read_text(encoding="utf-8"))
            replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
            source_action = replay["steps"][manifest["branch_ply"]]["action"]
            entries = sorted(manifest["actions"], key=lambda e: e["action_index"])
            idx = next(i for i, e in enumerate(entries)
                       if e["forced_action"] == source_action)
            source_indices.append(idx)
    assert len(source_indices) == 144

    # Load D2 and M41A-F checkpoint
    d2_model, _ = load_and_validate_checkpoint(
        "M25-D2-v2", catalog_hash=catalog_semantic_hash(catalog),
        device=torch.device("cpu"),
    )
    ckpt = torch.load(RUN / "m41a-F-final.pt", map_location="cpu", weights_only=False)
    q_head = M41AQHead()
    q_head.load_state_dict(ckpt["q_head_state"])
    base_arm = M41AArm(d2_model, q_head, freeze_encoders=True).to(device).eval()

    # 1. Base arm scores
    scores_B = score_states(base_arm, val_games, catalog, device)
    m_B = metrics(scores_B, val_games, source_indices)

    # Frozen validation anchor checks
    assert m_B["states"] == 144
    assert pytest.approx(m_B["material_ranking_accuracy"], abs=1e-5) == 0.5930556
    assert pytest.approx(m_B["mean_regret"], abs=1e-5) == 0.8750
    assert pytest.approx(m_B["mean_d2_baseline_regret"], abs=1e-5) == 0.8750

    # 2. Check that M42A Model at initialization gives bit-exact identical metrics
    arm_X, arm_R = create_m42a_paired_arms(base_arm)
    arm_X = arm_X.to(device).eval()
    arm_R = arm_R.to(device).eval()

    from splendor_gpu.m42a_relation_v1 import compute_observation_relation_tensors

    def score_m42a(model):
        from splendor_gpu.encoding import encode_observation, encode_action
        from splendor_gpu.m25_delta_v2 import encode_action_delta_v2
        results = []
        with torch.no_grad():
            for game in val_games:
                for state in game["states"]:
                    encoded = encode_observation(state["observation"], catalog)
                    entities = encoded.entities.unsqueeze(0).to(device)
                    mask = encoded.mask.unsqueeze(0).to(device)
                    global_features = encoded.global_features.unsqueeze(0).to(device)
                    actions = state["actions"]
                    n = len(actions)
                    encoded_actions = []
                    for a in actions:
                        base = encode_action(a).tolist()
                        delta = encode_action_delta_v2(state["observation"], a, catalog)
                        encoded_actions.append(base + delta)
                    actions_t = torch.tensor(encoded_actions, dtype=torch.float32, device=device)
                    offsets = torch.tensor([0, n], dtype=torch.long, device=device)
                    relations = compute_observation_relation_tensors(
                        state["observation"], actions, catalog
                    ).to(device)
                    q = model.q_values(entities, mask, global_features, actions_t, offsets, relations)
                    results.append(q.tolist())
        return results

    scores_R_init = score_m42a(arm_R)
    m_R_init = metrics(scores_R_init, val_games, source_indices)

    assert m_R_init["material_ranking_accuracy"] == m_B["material_ranking_accuracy"]
    assert m_R_init["mean_regret"] == m_B["mean_regret"]
    assert m_R_init["huber_mean"] == m_B["huber_mean"]
