"""M42A P2 offline validation diagnostics.

Evaluates Baseline B, Arm X, and Arm R on the validation split:
  - Normal metrics (centered Huber, material-pair ranking @ tau=1.0, mean regret)
  - Pseudo-Q integrity ablations: zero and cyclic-shift-by-1
  - Relation-only diagnostics for Arm R: relation-zero and relation-shift
  - Gate evaluations (integrity gate, usefulness gate, decision table ruling)
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "training/m17_gpu"))

import torch
import torch.nn.functional as F

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m35a_registry import load_and_validate_checkpoint
from splendor_gpu.m41a_train import (
    CORPUS_ROOT,
    M41AArm,
    M41AQHead,
    load_split,
)
from splendor_gpu.m42a_model import (
    M42AModel,
    M42ARelationResidual,
    RELATION_INIT_SEED,
)
from splendor_gpu.m42a_train import (
    BASE_CHECKPOINT_PATH,
    DERIVED_ROOT,
    RUN_ROOT,
    precompute_derived_cache,
)

CATALOG_PATH = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
TAU = 1.0
DELTA_RANK = 0.10     # 10 percentage points
DELTA_REGRET = 0.05   # 0.05 points
USEFULNESS_DELTA_RANK = 0.03    # +3 percentage points
USEFULNESS_DELTA_REGRET = 0.05  # -0.05 points


def load_m42a_checkpoint(arm_name: str, base_arm: M41AArm, device: torch.device) -> M42AModel:
    ckpt_path = RUN_ROOT / f"m42a-{arm_name}-final.pt"
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    residual = M42ARelationResidual()
    residual.load_state_dict(ckpt["residual_state"])
    model = M42AModel(copy.deepcopy(base_arm), residual, arm_type=arm_name)
    return model.to(device).eval()


def score_split(
    model: M42AModel | M41AArm,
    val_games: list[dict[str, Any]],
    device: torch.device,
    *,
    ablation: str | None = None,
) -> list[list[float]]:
    """Score all states in validation split.
    
    ablation:
      None             - normal scoring
      'zero'           - entire action bundle (actions + relations) zeroed
      'shift'          - entire action bundle (actions + relations) shifted by 1
      'relation-zero'  - actions unchanged, relations zeroed
      'relation-shift' - actions unchanged, relations shifted by 1
    """
    results = []
    is_m42 = isinstance(model, M42AModel)

    with torch.no_grad():
        for game in val_games:
            for state in game["states"]:
                entities = state["entities"].unsqueeze(0).to(device)
                mask = state["mask"].unsqueeze(0).to(device)
                global_features = state["global_features"].unsqueeze(0).to(device)
                actions = state["actions"].to(device)
                relations = state["relations"].to(device)
                n = actions.shape[0]
                offsets = torch.tensor([0, n], dtype=torch.long, device=device)

                # Apply ablations
                act_in = actions
                rel_in = relations

                if ablation == "zero":
                    act_in = torch.zeros_like(actions)
                    rel_in = torch.zeros_like(relations)
                elif ablation == "shift":
                    act_in = torch.cat([actions[1:], actions[:1]], dim=0)
                    rel_in = torch.cat([relations[1:], relations[:1]], dim=0)
                elif ablation == "relation-zero":
                    rel_in = torch.zeros_like(relations)
                elif ablation == "relation-shift":
                    rel_in = torch.cat([relations[1:], relations[:1]], dim=0)

                if is_m42:
                    q = model.q_values(entities, mask, global_features, act_in, offsets, rel_in)
                else:
                    counts = offsets[1:] - offsets[:-1]
                    s_emb = model.state_embedding(entities, mask, global_features)
                    a_emb = model.action_encoder(act_in)
                    exp_s = torch.repeat_interleave(s_emb, counts, dim=0)
                    z = torch.cat([exp_s, a_emb, exp_s * a_emb], dim=-1)
                    q = model.q_head(z)

                results.append(q.detach().cpu().tolist())
    return results


def compute_metrics(
    scores: list[list[float]],
    val_games: list[dict[str, Any]],
    source_indices: list[int],
) -> dict[str, Any]:
    huber_total = 0.0
    states = 0
    material_pairs = 0
    material_correct = 0.0
    regrets = []
    d2_regrets = []

    state_idx = 0
    for game in val_games:
        for state in game["states"]:
            q = scores[state_idx]
            returns = state["returns"]
            src_idx = source_indices[state_idx]
            state_idx += 1
            states += 1

            # Legal-set centered Huber
            q_mean = sum(q) / len(q)
            a_theta = [x - q_mean for x in q]
            mean_return = sum(returns) / len(returns)
            a_cf = [g - mean_return for g in returns]
            huber_total += float(
                F.huber_loss(
                    torch.tensor(a_theta, dtype=torch.float32),
                    torch.tensor(a_cf, dtype=torch.float32),
                    reduction="mean",
                    delta=1.0,
                )
            )

            # Material-pair ranking @ tau = 1.0 (with 0.5 tie credit)
            n_actions = len(q)
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
            regrets.append(g_best - returns[pred_best_idx])
            d2_regrets.append(g_best - returns[src_idx])

    return {
        "states": states,
        "huber_mean": huber_total / states,
        "material_pairs": material_pairs,
        "material_ranking_accuracy": material_correct / material_pairs if material_pairs else 0.0,
        "mean_regret": sum(regrets) / len(regrets),
        "mean_d2_baseline_regret": sum(d2_regrets) / len(d2_regrets),
    }


def evaluate_arm(
    arm_name: str,
    model: M42AModel | M41AArm,
    val_games: list[dict[str, Any]],
    source_indices: list[int],
    device: torch.device,
) -> dict[str, Any]:
    print(f"Evaluating {arm_name} on validation split...", flush=True)

    # 1. Normal
    scores_normal = score_split(model, val_games, device)
    m_normal = compute_metrics(scores_normal, val_games, source_indices)

    # 2. Zero ablation
    scores_zero = score_split(model, val_games, device, ablation="zero")
    m_zero = compute_metrics(scores_zero, val_games, source_indices)

    # 3. Shift ablation
    scores_shift = score_split(model, val_games, device, ablation="shift")
    m_shift = compute_metrics(scores_shift, val_games, source_indices)

    # Integrity gate checks
    zero_degrades_rank = (m_normal["material_ranking_accuracy"] - m_zero["material_ranking_accuracy"]) >= DELTA_RANK
    zero_degrades_regret = (m_zero["mean_regret"] - m_normal["mean_regret"]) >= DELTA_REGRET
    gate_zero = zero_degrades_rank or zero_degrades_regret

    shift_degrades_rank = (m_normal["material_ranking_accuracy"] - m_shift["material_ranking_accuracy"]) >= DELTA_RANK
    shift_degrades_regret = (m_shift["mean_regret"] - m_normal["mean_regret"]) >= DELTA_REGRET
    gate_shift = shift_degrades_rank or shift_degrades_regret

    arm_report = {
        "normal": m_normal,
        "zero_ablation": m_zero,
        "shift_ablation": m_shift,
        "integrity_gate": {
            "zero": bool(gate_zero),
            "zero_degrades_rank_pp": float(m_normal["material_ranking_accuracy"] - m_zero["material_ranking_accuracy"]) * 100,
            "zero_degrades_regret": float(m_zero["mean_regret"] - m_normal["mean_regret"]),
            "shift": bool(gate_shift),
            "shift_degrades_rank_pp": float(m_normal["material_ranking_accuracy"] - m_shift["material_ranking_accuracy"]) * 100,
            "shift_degrades_regret": float(m_shift["mean_regret"] - m_normal["mean_regret"]),
            "pass": bool(gate_zero and gate_shift),
        },
    }

    # Relation-only diagnostics for R
    if arm_name == "R":
        print("Evaluating R relation-only mechanism diagnostics...", flush=True)
        scores_rel_zero = score_split(model, val_games, device, ablation="relation-zero")
        m_rel_zero = compute_metrics(scores_rel_zero, val_games, source_indices)

        scores_rel_shift = score_split(model, val_games, device, ablation="relation-shift")
        m_rel_shift = compute_metrics(scores_rel_shift, val_games, source_indices)

        arm_report["relation_only_diagnostics"] = {
            "relation_zero": m_rel_zero,
            "relation_zero_rank_delta_pp": float(m_rel_zero["material_ranking_accuracy"] - m_normal["material_ranking_accuracy"]) * 100,
            "relation_zero_regret_delta": float(m_rel_zero["mean_regret"] - m_normal["mean_regret"]),
            "relation_shift": m_rel_shift,
            "relation_shift_rank_delta_pp": float(m_rel_shift["material_ranking_accuracy"] - m_normal["material_ranking_accuracy"]) * 100,
            "relation_shift_regret_delta": float(m_rel_shift["mean_regret"] - m_normal["mean_regret"]),
        }

    return arm_report


def determine_decision(
    m_B: dict[str, Any],
    eval_X: dict[str, Any],
    eval_R: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate against the frozen M42A decision table (Section 20)."""
    x_integrity_pass = eval_X["integrity_gate"]["pass"]
    r_integrity_pass = eval_R["integrity_gate"]["pass"]

    b_rank = m_B["material_ranking_accuracy"]
    b_regret = m_B["mean_regret"]

    r_rank = eval_R["normal"]["material_ranking_accuracy"]
    r_regret = eval_R["normal"]["mean_regret"]
    x_rank = eval_X["normal"]["material_ranking_accuracy"]
    x_regret = eval_X["normal"]["mean_regret"]

    r_vs_b_rank_pp = (r_rank - b_rank) * 100
    r_vs_b_regret_delta = r_regret - b_regret

    r_useful = (r_vs_b_rank_pp >= USEFULNESS_DELTA_RANK * 100) or (r_vs_b_regret_delta <= -USEFULNESS_DELTA_REGRET)

    r_vs_x_rank_pp = (r_rank - x_rank) * 100
    r_vs_x_regret_delta = r_regret - x_regret
    r_materially_beats_x = (r_vs_x_rank_pp >= USEFULNESS_DELTA_RANK * 100) or (r_vs_x_regret_delta <= -USEFULNESS_DELTA_REGRET)

    decision = ""
    case = ""

    if not x_integrity_pass and not r_integrity_pass:
        case = "Case A"
        decision = "M42A_RELATION_REPRESENTATION_NOT_VALIDATED / CLOSED_NEGATIVE"
    elif x_integrity_pass and r_integrity_pass and not r_materially_beats_x:
        case = "Case B"
        decision = "GENERIC_INTERACTION_SUFFICIENT_NO_EXPLICIT_RELATION_GAIN"
    elif not x_integrity_pass and r_integrity_pass and r_useful:
        case = "Case C"
        decision = "EXPLICIT_ACTION_ENTITY_RELATION_SIGNAL_VALIDATED"
    elif x_integrity_pass and r_integrity_pass and r_materially_beats_x:
        case = "Case D"
        decision = "GENERIC_INTERACTION_HELPS_AND_EXPLICIT_RELATIONS_ADD_MATERIAL_VALUE"
    elif r_integrity_pass and not r_useful:
        case = "Case E"
        decision = "STRUCTURAL_ACTION_BINDING_SIGNAL_ONLY"
    else:
        case = "Indeterminate"
        decision = "INCONCLUSIVE"

    return {
        "case": case,
        "decision": decision,
        "arm_X_integrity_pass": x_integrity_pass,
        "arm_R_integrity_pass": r_integrity_pass,
        "arm_R_useful_vs_B": r_useful,
        "R_minus_B_ranking_pp": r_vs_b_rank_pp,
        "R_minus_B_regret_delta": r_vs_b_regret_delta,
        "R_minus_X_ranking_pp": r_vs_x_rank_pp,
        "R_minus_X_regret_delta": r_vs_x_regret_delta,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M42A P2 Offline Validation Diagnostics")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    device = torch.device(args.device)

    print(f"M42A Diagnostics running on {device}...", flush=True)
    catalog = load_catalog(CATALOG_PATH)

    # 1. Load validation derived features
    val_games = precompute_derived_cache("validation", catalog)

    # 2. Extract source indices from corpus manifests
    source_indices = []
    for gdir in sorted((CORPUS_ROOT / "validation").glob("game-*")):
        for sdir in sorted(gdir.glob("branch-ply*")):
            manifest = json.loads((sdir / "state-manifest.json").read_text(encoding="utf-8"))
            replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
            source_action = replay["steps"][manifest["branch_ply"]]["action"]
            entries = sorted(manifest["actions"], key=lambda e: e["action_index"])
            idx = next(i for i, e in enumerate(entries)
                       if e["forced_action"] == source_action)
            source_indices.append(idx)
    assert len(source_indices) == 144

    # 3. Load baseline B
    d2_model, _ = load_and_validate_checkpoint(
        "M25-D2-v2", catalog_hash=catalog_semantic_hash(catalog),
        device=torch.device("cpu"),
    )
    base_ckpt = torch.load(BASE_CHECKPOINT_PATH, map_location="cpu", weights_only=False)
    q_head = M41AQHead()
    q_head.load_state_dict(base_ckpt["q_head_state"])
    base_arm = M41AArm(d2_model, q_head, freeze_encoders=True).eval()

    # 4. Evaluate Baseline B
    eval_B = evaluate_arm("B", base_arm.to(device), val_games, source_indices, device)

    # 5. Evaluate Arm X
    model_X = load_m42a_checkpoint("X", base_arm, device)
    eval_X = evaluate_arm("X", model_X, val_games, source_indices, device)

    # 6. Evaluate Arm R
    model_R = load_m42a_checkpoint("R", base_arm, device)
    eval_R = evaluate_arm("R", model_R, val_games, source_indices, device)

    # 7. Decision table ruling
    decision_summary = determine_decision(eval_B["normal"], eval_X, eval_R)

    report = {
        "milestone": "M42A",
        "description": "Visible Action-Entity Relation Residual Probe",
        "validation_states": 144,
        "material_pairs": 27677,
        "tau": TAU,
        "arms": {
            "B": eval_B,
            "X": eval_X,
            "R": eval_R,
        },
        "decision_summary": decision_summary,
    }

    report_path = RUN_ROOT / "m42a-diagnostics-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n=======================================================", flush=True)
    print(f"M42A DIAGNOSTICS COMPLETE", flush=True)
    print(f"Report written to {report_path}", flush=True)
    print(f"=======================================================", flush=True)
    print(json.dumps(decision_summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
