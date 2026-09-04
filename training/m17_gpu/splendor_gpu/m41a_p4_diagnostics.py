"""M41A P4 offline diagnostics (validation split ONLY; power-calibration
remains SEALED).

Metrics per arm (F, U) on the validation split:
  - centered Huber/MSE diagnostic
  - material-pair ranking accuracy @ tau = 1.0 (truth-set fixed by the
    teacher; predicted tie = 0.5 credit, never removed)
  - top-1 regret (argmax ties broken by earliest authoritative legal
    index) vs the D2 baseline regret
  - action-ablation pseudo-Q gates: zero-action and cyclic-shift-by-1,
    each must degrade (ranking -10 pp OR regret +0.05) — frozen §9.5.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "training/m17_gpu"))

import torch

from splendor_gpu.data import load_catalog
from splendor_gpu.m41a_helpers import HEAD_INIT_SEED
from splendor_gpu import m41a_train as trainer

CORPUS = REPO / "local-artifacts/m41a-corpus"
CATALOG_PATH = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
RUN = REPO / "local-artifacts/m41a-run"
TAU = 1.0
DELTA_RANK = 0.10
DELTA_REGRET = 0.05


def load_checkpoint(arm: str):
    ckpt = torch.load(RUN / f"m41a-{arm}-final.pt", map_location="cpu", weights_only=False)
    return ckpt


def build_arm(arm_name: str, ckpt, d2_model, device):
    import copy

    d2_arm = copy.deepcopy(d2_model)
    torch.manual_seed(HEAD_INIT_SEED)
    q_head = trainer.M41AQHead()
    q_head.load_state_dict(ckpt["q_head_state"])
    arm = trainer.M41AArm(d2_arm, q_head, freeze_encoders=(arm_name == "F"))
    arm.load_state_dict({**ckpt["encoder_state"], **{f"q_head.{k}": v for k, v in ckpt["q_head_state"].items()},
                         **{k: v for k, v in arm.state_dict().items()
                            if k.startswith(("policy.", "value.")) and k not in ckpt["encoder_state"]}},
                        strict=False)
    return arm.to(device).eval()


def score_states(arm, games, catalog, device, ablation=None):
    """Score every legal action of every state; returns per-state lists
    of q-scores aligned with the corpus action order.

    ablation:
      None        — normal
      'zero'      — action embedding zeroed (z = [s, 0, 0])
      'shift'     — cyclic shift by 1 within each state's legal set
    """
    from splendor_gpu.encoding import encode_observation, encode_action
    from splendor_gpu.m25_delta_v2 import encode_action_delta_v2

    results = []
    with torch.no_grad():
        for game in games:
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
                if ablation == "shift":
                    encoded_actions = encoded_actions[1:] + encoded_actions[:1]
                actions_t = torch.tensor(encoded_actions, dtype=torch.float32, device=device)
                s = arm.state_embedding(entities, mask, global_features)  # (1, 192)
                if ablation == "zero":
                    a_emb = torch.zeros(n, 192, device=device)
                    z = torch.cat([s.expand(n, -1), a_emb, s.expand(n, -1) * a_emb], dim=-1)
                else:
                    a_emb = arm.action_encoder(actions_t)
                    s_exp = s.expand(n, -1)
                    z = torch.cat([s_exp, a_emb, s_exp * a_emb], dim=-1)
                q = arm.q_head(z).reshape(-1)
                results.append(q.tolist())
    return results


def metrics(scores, games, source_indices=None):
    """All frozen §9.4 metrics from per-state q-scores.

    source_indices: per-state index of the SOURCE (D2) action within the
    authoritative legal ordering (for the D2 baseline regret)."""
    import torch.nn.functional as F

    huber_total = 0.0
    states = 0
    material_pairs = 0
    material_correct = 0.0
    regrets = []
    d2_regrets = []
    state_index = 0
    for game in games:
        for state in game["states"]:
            q = scores[state_index]
            returns = state["returns"]
            mean_return = sum(returns) / len(returns)
            a_cf = [g - mean_return for g in returns]
            src = source_indices[state_index] if source_indices else 0
            state_index += 1
            states += 1
            # Huber diagnostic on the LEGAL-SET CENTERED prediction (the
            # frozen §3 objective; identical centering to training).
            q_mean = sum(q) / len(q)
            a_theta = [x - q_mean for x in q]
            huber_total += float(F.huber_loss(
                torch.tensor(a_theta), torch.tensor(a_cf), reduction="mean", delta=1.0
            ))
            for i in range(len(q)):
                for j in range(i + 1, len(q)):
                    if abs(returns[i] - returns[j]) >= TAU:
                        material_pairs += 1
                        qi, qj = q[i], q[j]
                        if qi == qj:
                            material_correct += 0.5
                        elif (qi > qj) == (returns[i] > returns[j]):
                            material_correct += 1.0
            g_best = max(returns)
            model = q.index(max(q))  # earliest index tie-break
            regrets.append(g_best - returns[model])
            d2_regrets.append(g_best - returns[src])
    return {
        "states": states,
        "huber_mean": huber_total / states,
        "material_pairs": material_pairs,
        "material_ranking_accuracy": material_correct / material_pairs if material_pairs else None,
        "mean_regret": sum(regrets) / len(regrets),
        "mean_d2_baseline_regret": sum(d2_regrets) / len(d2_regrets),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M41A P4 offline diagnostics")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    device = torch.device(args.device)

    catalog = load_catalog(CATALOG_PATH)
    val_games = trainer.load_split("validation")
    print(json.dumps({"validation_games": len(val_games)}), flush=True)

    # Per-state source-action index within the authoritative legal
    # ordering (the D2 baseline regret), from the corpus manifests.
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
    print(json.dumps({"source_indices_loaded": len(source_indices)}), flush=True)

    from splendor_gpu.m35a_registry import load_and_validate_checkpoint
    from splendor_gpu.data import catalog_semantic_hash
    d2_model, _ = load_and_validate_checkpoint(
        "M25-D2-v2", catalog_hash=catalog_semantic_hash(catalog),
        device=torch.device("cpu"),
    )

    report: dict[str, Any] = {}
    for arm_name in ("F", "U"):
        ckpt = load_checkpoint(arm_name)
        arm = build_arm(arm_name, ckpt, d2_model, device)
        scores_normal = score_states(arm, val_games, catalog, device)
        scores_zero = score_states(arm, val_games, catalog, device, ablation="zero")
        scores_shift = score_states(arm, val_games, catalog, device, ablation="shift")

        m_normal = metrics(scores_normal, val_games, source_indices)
        m_zero = metrics(scores_zero, val_games, source_indices)
        m_shift = metrics(scores_shift, val_games, source_indices)

        # Pseudo-Q gate: for EACH ablation, at least one metric must
        # degrade beyond the frozen threshold.
        gate_zero = (
            m_normal["material_ranking_accuracy"] - m_zero["material_ranking_accuracy"] >= DELTA_RANK
            or m_zero["mean_regret"] - m_normal["mean_regret"] >= DELTA_REGRET
        )
        gate_shift = (
            m_normal["material_ranking_accuracy"] - m_shift["material_ranking_accuracy"] >= DELTA_RANK
            or m_shift["mean_regret"] - m_normal["mean_regret"] >= DELTA_REGRET
        )
        report[arm_name] = {
            "normal": m_normal,
            "zero_ablation": m_zero,
            "shift_ablation": m_shift,
            "ablation_gate": {"zero": gate_zero, "shift": gate_shift,
                              "pass": gate_zero and gate_shift},
        }
        print(json.dumps({"arm": arm_name, "metrics": m_normal,
                          "gate": report[arm_name]["ablation_gate"]}), flush=True)

    out = RUN / "m41a-p4-offline-diagnostics.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": "p4-offline-complete"}), flush=True)


if __name__ == "__main__":
    main()
