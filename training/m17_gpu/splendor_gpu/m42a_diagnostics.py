"""M42A P2 offline validation diagnostics & Activation Audit (Repair 1).

Evaluates Baseline B, Arm X, and Arm R on the validation split:
  - Normal metrics (centered Huber, material-pair ranking @ tau=1.0, mean regret)
  - Pseudo-Q integrity ablations: zero and cyclic-shift-by-1
  - Relation-only diagnostics for Arm R: relation-zero and relation-shift
  - Activation audit: residual semantic SHAs, module-wise parameter deltas,
    q_residual magnitudes, within-state stds, score deltas (R vs relzero, R vs X)
  - Relation dataset audit: action discrimination rate, nonzero rate, pairwise distances
  - Decision table ruling (Cases A, B, C, D, E)
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
    assert_base_contracts,
    compute_module_param_deltas,
    compute_residual_semantic_hash,
    load_and_validate_derived_cache,
)

CATALOG_PATH = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
TAU = 1.0
DELTA_RANK = 0.10     # 10 percentage points
DELTA_REGRET = 0.05   # 0.05 points
USEFULNESS_DELTA_RANK = 0.03    # +3 percentage points
USEFULNESS_DELTA_REGRET = 0.05  # -0.05 points


def load_m42a_checkpoint(arm_name: str, base_arm: M41AArm, device: torch.device):
    ckpt_path = RUN_ROOT / f"m42a-{arm_name}-final.pt"
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    residual = M42ARelationResidual()
    residual.load_state_dict(ckpt["residual_state"])
    model = M42AModel(copy.deepcopy(base_arm), residual, arm_type=arm_name)
    return model.to(device).eval(), ckpt


def score_split(
    model: M42AModel | M41AArm,
    val_games: list[dict[str, Any]],
    device: torch.device,
    *,
    ablation: str | None = None,
) -> tuple[list[list[float]], list[list[float]]]:
    """Score all states in validation split.
    
    Returns (q_totals, q_residuals).
    """
    total_scores = []
    residual_scores = []
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
                    q_tot, q_b, q_res = model(entities, mask, global_features, act_in, offsets, rel_in)
                    total_scores.append(q_tot.detach().cpu().tolist())
                    residual_scores.append(q_res.detach().cpu().tolist())
                else:
                    counts = offsets[1:] - offsets[:-1]
                    s_emb = model.state_embedding(entities, mask, global_features)
                    a_emb = model.action_encoder(act_in)
                    exp_s = torch.repeat_interleave(s_emb, counts, dim=0)
                    z = torch.cat([exp_s, a_emb, exp_s * a_emb], dim=-1)
                    q_b = model.q_head(z)
                    total_scores.append(q_b.detach().cpu().tolist())
                    residual_scores.append([0.0] * n)

    return total_scores, residual_scores


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


def compute_q_res_stats(residual_scores: list[list[float]]) -> dict[str, float]:
    all_res = [val for state_res in residual_scores for val in state_res]
    abs_res = [abs(x) for x in all_res]

    within_stds = []
    for s_res in residual_scores:
        if len(s_res) > 1:
            mean_s = sum(s_res) / len(s_res)
            var_s = sum((x - mean_s) ** 2 for x in s_res) / (len(s_res) - 1)
            within_stds.append(var_s ** 0.5)
        else:
            within_stds.append(0.0)

    mean_s = sum(all_res) / len(all_res)
    std_all = (sum((x - mean_s) ** 2 for x in all_res) / max(1, len(all_res) - 1)) ** 0.5

    return {
        "mean_abs_q_res": sum(abs_res) / max(1, len(abs_res)),
        "std_q_res": std_all,
        "max_abs_q_res": max(abs_res) if abs_res else 0.0,
        "within_state_std_q_res": sum(within_stds) / max(1, len(within_stds)),
    }


def audit_relation_dataset(games: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit actual relation tensor distribution and variation across actions."""
    total_states = 0
    states_with_ge_2_distinct = 0

    total_pairs = 0
    different_pairs = 0
    l1_dists = []
    l2_dists = []

    nonzero_elements = 0
    total_elements = 0

    for game in games:
        for state in game["states"]:
            rels = state["relations"]  # (N, 31, 28)
            n_actions = rels.shape[0]
            total_states += 1

            nonzero_elements += int(torch.count_nonzero(rels))
            total_elements += int(rels.numel())

            # Distinct relations within state
            distinct_hashes = set()
            for i in range(n_actions):
                h = hashlib.sha256(rels[i].numpy().tobytes()).hexdigest()
                distinct_hashes.add(h)
            if len(distinct_hashes) >= 2:
                states_with_ge_2_distinct += 1

            # Pairwise distances
            for i in range(n_actions):
                for j in range(i + 1, n_actions):
                    total_pairs += 1
                    diff = rels[i] - rels[j]
                    if not torch.equal(rels[i], rels[j]):
                        different_pairs += 1
                        l1_dists.append(float(torch.sum(torch.abs(diff))))
                        l2_dists.append(float(torch.norm(diff)))

    return {
        "total_states": total_states,
        "states_with_ge_2_distinct": states_with_ge_2_distinct,
        "states_with_ge_2_distinct_rate": states_with_ge_2_distinct / max(1, total_states),
        "total_action_pairs": total_pairs,
        "different_action_pairs": different_pairs,
        "different_action_pairs_rate": different_pairs / max(1, total_pairs),
        "relation_dims_nonzero_rate": nonzero_elements / max(1, total_elements),
        "mean_pairwise_l1_dist": sum(l1_dists) / max(1, len(l1_dists)),
        "mean_pairwise_l2_dist": sum(l2_dists) / max(1, len(l2_dists)),
    }


def compare_models(model_X: M42AModel, model_R: M42AModel) -> dict[str, Any]:
    state_X = model_X.residual.state_dict()
    state_R = model_R.residual.state_dict()

    equal_count = 0
    diff_count = 0
    max_abs_delta = 0.0
    l2_delta_sq = 0.0

    for k in state_R.keys():
        t_X = state_X[k].detach().cpu()
        t_R = state_R[k].detach().cpu()
        if torch.equal(t_X, t_R):
            equal_count += 1
        else:
            diff_count += 1
            abs_diff = torch.abs(t_R - t_X)
            max_abs_delta = max(max_abs_delta, float(torch.max(abs_diff)))
            l2_delta_sq += float(torch.sum((t_R - t_X) ** 2))

    return {
        "number_of_equal_tensors": equal_count,
        "number_of_different_tensors": diff_count,
        "max_abs_tensor_delta": max_abs_delta,
        "l2_parameter_delta": float(l2_delta_sq ** 0.5),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M42A P2 Diagnostics (Repair 1)")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    device = torch.device(args.device)

    print(f"M42A Diagnostics (Repair 1) running on {device}...", flush=True)
    assert_base_contracts()
    catalog = load_catalog(CATALOG_PATH)

    val_games = load_and_validate_derived_cache("validation", catalog)

    # Load source indices
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

    # Load base arm B
    d2_model, _ = load_and_validate_checkpoint(
        "M25-D2-v2", catalog_hash=catalog_semantic_hash(catalog),
        device=torch.device("cpu"),
    )
    base_ckpt = torch.load(BASE_CHECKPOINT_PATH, map_location="cpu", weights_only=False)
    q_head = M41AQHead()
    q_head.load_state_dict(base_ckpt["q_head_state"])
    base_arm = M41AArm(d2_model, q_head, freeze_encoders=True).to(device).eval()

    # 1. Evaluate B
    scores_B_norm, _ = score_split(base_arm, val_games, device)
    scores_B_zero, _ = score_split(base_arm, val_games, device, ablation="zero")
    scores_B_shift, _ = score_split(base_arm, val_games, device, ablation="shift")
    m_B_norm = compute_metrics(scores_B_norm, val_games, source_indices)
    m_B_zero = compute_metrics(scores_B_zero, val_games, source_indices)
    m_B_shift = compute_metrics(scores_B_shift, val_games, source_indices)

    # 2. Load and evaluate Arm X
    model_X, ckpt_X = load_m42a_checkpoint("X", base_arm, device)
    scores_X_norm, q_res_X = score_split(model_X, val_games, device)
    scores_X_zero, _ = score_split(model_X, val_games, device, ablation="zero")
    scores_X_shift, _ = score_split(model_X, val_games, device, ablation="shift")
    m_X_norm = compute_metrics(scores_X_norm, val_games, source_indices)
    m_X_zero = compute_metrics(scores_X_zero, val_games, source_indices)
    m_X_shift = compute_metrics(scores_X_shift, val_games, source_indices)
    stats_q_res_X = compute_q_res_stats(q_res_X)

    # 3. Load and evaluate Arm R
    model_R, ckpt_R = load_m42a_checkpoint("R", base_arm, device)
    scores_R_norm, q_res_R = score_split(model_R, val_games, device)
    scores_R_zero, _ = score_split(model_R, val_games, device, ablation="zero")
    scores_R_shift, _ = score_split(model_R, val_games, device, ablation="shift")
    scores_R_relzero, _ = score_split(model_R, val_games, device, ablation="relation-zero")
    scores_R_relshift, _ = score_split(model_R, val_games, device, ablation="relation-shift")

    m_R_norm = compute_metrics(scores_R_norm, val_games, source_indices)
    m_R_zero = compute_metrics(scores_R_zero, val_games, source_indices)
    m_R_shift = compute_metrics(scores_R_shift, val_games, source_indices)
    m_R_relzero = compute_metrics(scores_R_relzero, val_games, source_indices)
    m_R_relshift = compute_metrics(scores_R_relshift, val_games, source_indices)
    stats_q_res_R = compute_q_res_stats(q_res_R)

    # 4. Activation audit: score deltas
    all_q_R_norm = [v for s in scores_R_norm for v in s]
    all_q_R_relzero = [v for s in scores_R_relzero for v in s]
    all_q_X_norm = [v for s in scores_X_norm for v in s]

    diff_R_relzero = [abs(r - rz) for r, rz in zip(all_q_R_norm, all_q_R_relzero)]
    diff_R_X = [abs(r - x) for r, x in zip(all_q_R_norm, all_q_X_norm)]

    score_deltas = {
        "mean_abs_R_normal_minus_relzero": sum(diff_R_relzero) / max(1, len(diff_R_relzero)),
        "max_abs_R_normal_minus_relzero": max(diff_R_relzero) if diff_R_relzero else 0.0,
        "mean_abs_R_minus_X": sum(diff_R_X) / max(1, len(diff_R_X)),
        "max_abs_R_minus_X": max(diff_R_X) if diff_R_X else 0.0,
    }

    # 5. Model parameter deltas
    torch.manual_seed(RELATION_INIT_SEED)
    initial_residual = M42ARelationResidual()
    param_deltas_X = compute_module_param_deltas(initial_residual, model_X.residual)
    param_deltas_R = compute_module_param_deltas(initial_residual, model_R.residual)
    comparison_X_R = compare_models(model_X, model_R)

    # 6. Relation dataset audit
    rel_audit_val = audit_relation_dataset(val_games)

    # 7. Gates
    gate_zero_X = (
        (m_X_norm["material_ranking_accuracy"] - m_X_zero["material_ranking_accuracy"] >= DELTA_RANK)
        or (m_X_zero["mean_regret"] - m_X_norm["mean_regret"] >= DELTA_REGRET)
    )
    gate_shift_X = (
        (m_X_norm["material_ranking_accuracy"] - m_X_shift["material_ranking_accuracy"] >= DELTA_RANK)
        or (m_X_shift["mean_regret"] - m_X_norm["mean_regret"] >= DELTA_REGRET)
    )
    pass_integrity_X = gate_zero_X and gate_shift_X

    gate_zero_R = (
        (m_R_norm["material_ranking_accuracy"] - m_R_zero["material_ranking_accuracy"] >= DELTA_RANK)
        or (m_R_zero["mean_regret"] - m_R_norm["mean_regret"] >= DELTA_REGRET)
    )
    gate_shift_R = (
        (m_R_norm["material_ranking_accuracy"] - m_R_shift["material_ranking_accuracy"] >= DELTA_RANK)
        or (m_R_shift["mean_regret"] - m_R_norm["mean_regret"] >= DELTA_REGRET)
    )
    pass_integrity_R = gate_zero_R and gate_shift_R

    # Usefulness
    r_vs_b_rank_pp = (m_R_norm["material_ranking_accuracy"] - m_B_norm["material_ranking_accuracy"]) * 100
    r_vs_b_regret = m_R_norm["mean_regret"] - m_B_norm["mean_regret"]
    useful_R = (r_vs_b_rank_pp >= USEFULNESS_DELTA_RANK * 100) or (r_vs_b_regret <= -USEFULNESS_DELTA_REGRET)

    decision_case = "Case A" if (not pass_integrity_X and not pass_integrity_R) else "Other"
    decision = "M42A_RELATION_REPRESENTATION_NOT_VALIDATED / CLOSED_NEGATIVE" if decision_case == "Case A" else "SEE_SUMMARY"

    report = {
        "milestone": "M42A",
        "title": "Visible Action-Entity Relation Residual Probe",
        "run_era": "run2_valid",
        "activation_audit_table": {
            "evidence": {
                "residual_semantic_sha256": {
                    "X": compute_residual_semantic_hash(model_X.residual.state_dict()),
                    "R": compute_residual_semantic_hash(model_R.residual.state_dict()),
                },
                "total_param_delta_from_init": {
                    "X": param_deltas_X["total_residual_l2_delta"],
                    "R": param_deltas_R["total_residual_l2_delta"],
                },
                "relation_encoder_delta": {
                    "X": param_deltas_X["relation_encoder"],
                    "R": param_deltas_R["relation_encoder"],
                },
                "pair_encoder_delta": {
                    "X": param_deltas_X["pair_encoder"],
                    "R": param_deltas_R["pair_encoder"],
                },
                "gate_delta": {
                    "X": param_deltas_X["entity_gate"],
                    "R": param_deltas_R["entity_gate"],
                },
                "residual_head_0_delta": {
                    "X": param_deltas_X["residual_head_0"],
                    "R": param_deltas_R["residual_head_0"],
                },
                "residual_head_final_delta": {
                    "X": param_deltas_X["residual_head_final"],
                    "R": param_deltas_R["residual_head_final"],
                },
                "mean_abs_q_res": {
                    "X": stats_q_res_X["mean_abs_q_res"],
                    "R": stats_q_res_R["mean_abs_q_res"],
                },
                "within_state_std_q_res": {
                    "X": stats_q_res_X["within_state_std_q_res"],
                    "R": stats_q_res_R["within_state_std_q_res"],
                },
                "mean_abs_R_normal_minus_relzero": score_deltas["mean_abs_R_normal_minus_relzero"],
                "max_abs_R_normal_minus_relzero": score_deltas["max_abs_R_normal_minus_relzero"],
                "mean_abs_R_minus_X": score_deltas["mean_abs_R_minus_X"],
                "max_abs_R_minus_X": score_deltas["max_abs_R_minus_X"],
            },
            "comparison_X_vs_R": comparison_X_R,
        },
        "relation_dataset_audit": rel_audit_val,
        "metrics_summary": {
            "B": {
                "normal": m_B_norm,
                "zero": m_B_zero,
                "shift": m_B_shift,
            },
            "X": {
                "normal": m_X_norm,
                "zero": m_X_zero,
                "shift": m_X_shift,
                "integrity_pass": pass_integrity_X,
            },
            "R": {
                "normal": m_R_norm,
                "zero": m_R_zero,
                "shift": m_R_shift,
                "relation_zero": m_R_relzero,
                "relation_shift": m_R_relshift,
                "integrity_pass": pass_integrity_R,
                "useful_vs_B": useful_R,
            },
        },
        "decision": {
            "case": decision_case,
            "verdict": decision,
        },
    }

    out_path = RUN_ROOT / "m42a-diagnostics-report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report written to {out_path}.", flush=True)
    print(json.dumps(report["activation_audit_table"], indent=2), flush=True)
    print(json.dumps(report["relation_dataset_audit"], indent=2), flush=True)
    print(json.dumps(report["decision"], indent=2), flush=True)


if __name__ == "__main__":
    main()
