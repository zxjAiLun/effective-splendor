"""M43A P2: Offline root-action evaluation and integrity ablations.

Evaluates the trained M43ASuccessorValueModel on the 144 validation source states:
  - Normal successor valuation: q(a) = V(o'_a)
  - PRESTATE ablation: q(a) = V(o) (identical score for all actions)
  - CYCLIC-SUCCESSOR ablation: q(a_i) = V(o'_{a_{i+1}})
  - Evaluates material-pair ranking @ tau=1.0, top-1 regret, chosen G vs D2 G
  - Asserts integrity gate: both corruptions must degrade ranking >= 10 pp OR worsen regret >= 0.05
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "training/m17_gpu"))

import numpy as np
import torch

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m35a_registry import load_and_validate_checkpoint
from splendor_gpu.m43a_successor_dataset import load_successor_split
from splendor_gpu.m43a_successor_model import (
    M43ASuccessorValueModel,
    build_m43a_model,
)

CATALOG_PATH = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
RUN_ROOT = REPO / "local-artifacts/m43a-run"
TAU = 1.0
DELTA_RANK = 0.10     # 10 percentage points
DELTA_REGRET = 0.05   # 0.05 points


def load_best_m43a_model(device: torch.device) -> tuple[M43ASuccessorValueModel, dict[str, Any]]:
    ckpt_path = RUN_ROOT / "m43a-successor-value-best.pt"
    if not ckpt_path.is_file():
        raise FileNotFoundError(f"Checkpoint not found at {ckpt_path}")

    catalog = load_catalog(CATALOG_PATH)
    d2_model, _ = load_and_validate_checkpoint(
        "M25-D2-v2", catalog_hash=catalog_semantic_hash(catalog),
        device=torch.device("cpu"),
    )
    model, _ = build_m43a_model(d2_model)

    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    model.load_state_dict(ckpt["state_dict"])
    return model.to(device).eval(), ckpt


def score_validation_states(
    model: M43ASuccessorValueModel,
    val_games: list[dict[str, Any]],
    device: torch.device,
    *,
    ablation: str | None = None,
) -> list[list[float]]:
    all_scores = []
    with torch.no_grad():
        for game in val_games:
            for state in game["states"]:
                entities = state["entities"].to(device)
                mask = state["mask"].to(device)
                global_features = state["global_features"].to(device)
                n = entities.shape[0]

                if ablation is None:
                    preds = model(entities, mask, global_features)
                    all_scores.append(preds.detach().cpu().tolist())

                elif ablation == "prestate":
                    # Score every action from the identical source observation V(o)
                    src_ent = state["src_entities"].unsqueeze(0).to(device)
                    src_mask = state["src_mask"].unsqueeze(0).to(device)
                    src_glob = state["src_global_features"].unsqueeze(0).to(device)
                    src_pred = model(src_ent, src_mask, src_glob).item()
                    all_scores.append([src_pred] * n)

                elif ablation == "cyclic_successor":
                    # Cyclically shift successor representations by 1 within L(s)
                    shifted_entities = torch.cat([entities[1:], entities[:1]], dim=0)
                    shifted_mask = torch.cat([mask[1:], mask[:1]], dim=0)
                    shifted_globals = torch.cat([global_features[1:], global_features[:1]], dim=0)
                    preds = model(shifted_entities, shifted_mask, shifted_globals)
                    all_scores.append(preds.detach().cpu().tolist())

                else:
                    raise ValueError(f"unknown ablation {ablation}")

    return all_scores


def compute_offline_metrics(
    scores: list[list[float]],
    val_games: list[dict[str, Any]],
    source_indices: list[int],
) -> dict[str, Any]:
    states = 0
    material_pairs = 0
    material_correct = 0.0
    regrets = []
    d2_regrets = []
    chosen_g_list = []
    d2_g_list = []

    state_idx = 0
    for game in val_games:
        for state in game["states"]:
            q = scores[state_idx]
            returns = state["g_returns"]
            src_idx = source_indices[state_idx]
            state_idx += 1
            states += 1

            n_actions = len(q)
            # Material-pair ranking @ tau = 1.0 (with 0.5 tie credit)
            for i in range(n_actions):
                for j in range(i + 1, n_actions):
                    if abs(returns[i] - returns[j]) >= TAU:
                        material_pairs += 1
                        qi, qj = q[i], q[j]
                        if qi == qj:
                            material_correct += 0.5
                        elif (qi > qj) == (returns[i] > returns[j]):
                            material_correct += 1.0

            # Top-1 regret (earliest index tie-break)
            g_best = max(returns)
            pred_best_idx = q.index(max(q))

            chosen_g = returns[pred_best_idx]
            d2_g = returns[src_idx]

            chosen_g_list.append(chosen_g)
            d2_g_list.append(d2_g)

            regrets.append(g_best - chosen_g)
            d2_regrets.append(g_best - d2_g)

    return {
        "states": states,
        "material_pairs": material_pairs,
        "material_ranking_accuracy": material_correct / material_pairs if material_pairs else 0.0,
        "mean_regret": sum(regrets) / len(regrets),
        "mean_d2_baseline_regret": sum(d2_regrets) / len(d2_regrets),
        "mean_chosen_g": sum(chosen_g_list) / len(chosen_g_list),
        "mean_d2_g": sum(d2_g_list) / len(d2_g_list),
    }


def evaluate_m43a_offline(device: torch.device) -> dict[str, Any]:
    print(f"M43A P2 Offline Evaluation initialized on {device}.", flush=True)
    catalog = load_catalog(CATALOG_PATH)
    val_games = load_successor_split("validation", catalog)

    # 1. Load source action indices from corpus manifests
    source_indices = []
    corpus_root = REPO / "local-artifacts/m41a-corpus/validation"
    for gdir in sorted(corpus_root.glob("game-*")):
        for sdir in sorted(gdir.glob("branch-ply*")):
            manifest = json.loads((sdir / "state-manifest.json").read_text(encoding="utf-8"))
            replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
            source_action = replay["steps"][manifest["branch_ply"]]["action"]
            entries = sorted(manifest["actions"], key=lambda e: e["action_index"])
            idx = next(i for i, e in enumerate(entries) if e["forced_action"] == source_action)
            source_indices.append(idx)
    assert len(source_indices) == 144, f"expected 144 source indices, got {len(source_indices)}"

    # 2. Load trained model
    model, ckpt = load_best_m43a_model(device)

    # 3. Normal scoring
    scores_normal = score_validation_states(model, val_games, device)
    m_normal = compute_offline_metrics(scores_normal, val_games, source_indices)

    # 4. PRESTATE ablation
    scores_prestate = score_validation_states(model, val_games, device, ablation="prestate")
    m_prestate = compute_offline_metrics(scores_prestate, val_games, source_indices)

    # 5. CYCLIC-SUCCESSOR ablation
    scores_cyclic = score_validation_states(model, val_games, device, ablation="cyclic_successor")
    m_cyclic = compute_offline_metrics(scores_cyclic, val_games, source_indices)

    # 6. Evaluate Integrity Gates (Section 18)
    prestate_degrades_rank = (m_normal["material_ranking_accuracy"] - m_prestate["material_ranking_accuracy"]) >= DELTA_RANK
    prestate_worsens_regret = (m_prestate["mean_regret"] - m_normal["mean_regret"]) >= DELTA_REGRET
    gate_prestate = prestate_degrades_rank or prestate_worsens_regret

    cyclic_degrades_rank = (m_normal["material_ranking_accuracy"] - m_cyclic["material_ranking_accuracy"]) >= DELTA_RANK
    cyclic_worsens_regret = (m_cyclic["mean_regret"] - m_normal["mean_regret"]) >= DELTA_REGRET
    gate_cyclic = cyclic_degrades_rank or cyclic_worsens_regret

    pass_integrity = gate_prestate and gate_cyclic

    # Check P1 BSS gate from checkpoint
    p1_bss_pass = ckpt["p1_diagnostics"]["bss_pass"]
    arena_authorized = p1_bss_pass and pass_integrity

    report = {
        "milestone": "M43A",
        "best_epoch": ckpt["best_epoch"],
        "p1_diagnostics": ckpt["p1_diagnostics"],
        "normal": m_normal,
        "prestate_ablation": m_prestate,
        "cyclic_successor_ablation": m_cyclic,
        "integrity_gates": {
            "prestate": {
                "pass": gate_prestate,
                "rank_delta_pp": (m_normal["material_ranking_accuracy"] - m_prestate["material_ranking_accuracy"]) * 100,
                "regret_delta": m_prestate["mean_regret"] - m_normal["mean_regret"],
            },
            "cyclic_successor": {
                "pass": gate_cyclic,
                "rank_delta_pp": (m_normal["material_ranking_accuracy"] - m_cyclic["material_ranking_accuracy"]) * 100,
                "regret_delta": m_cyclic["mean_regret"] - m_normal["mean_regret"],
            },
            "overall_integrity_pass": pass_integrity,
        },
        "gates_summary": {
            "p1_bss_pass": p1_bss_pass,
            "p2_integrity_pass": pass_integrity,
            "arena_authorized": arena_authorized,
            "verdict": "ARENA_AUTHORIZED" if arena_authorized else (
                "M43A_SUCCESSOR_VALUE_NOT_LEARNED" if not p1_bss_pass else "M43A_SUCCESSOR_MAPPING_NOT_VALIDATED"
            ),
        },
    }

    out_file = RUN_ROOT / "m43a-offline-eval-report.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Offline evaluation report written to {out_file}.", flush=True)
    print(json.dumps(report["gates_summary"], indent=2), flush=True)
    return report


if __name__ == "__main__":
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    evaluate_m43a_offline(device)
