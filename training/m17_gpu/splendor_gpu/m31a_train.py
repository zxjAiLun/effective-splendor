"""M31A Objective-v2: Canonical Soft-CE + 0.5 * Weighted Pairwise Logistic Ranking Loss Training (128 epochs)."""
import time
import json
import math
import hashlib
from pathlib import Path
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

from splendor_gpu.data import load_catalog, catalog_semantic_hash
from splendor_gpu.encoding import (
    ENTITY_SLOTS, ENTITY_FEATURES, GLOBAL_FEATURES, ACTION_FEATURES,
    encode_observation, encode_action, GEMS, COLORS, TIERS
)
from splendor_gpu.m25_train import split_m25_indices, compute_uniform_policy_ce, validate_m25_dataset_provenance
from splendor_gpu.m25_delta_v2 import encode_action_delta_v2
from splendor_gpu.model import ResidualBlock
from splendor_gpu.m31a_loss import extract_ranking_pair_info, compute_canonical_ce_and_ranking_loss

ENHANCED_ACTION_FEATURES = 36 + 23  # 59

class DeltaEntityMixer(nn.Module):
    """Canonical D2 Architecture (h192/b4, 59-dim exact action deltas)."""
    def __init__(self, hidden_dim=192, blocks=4, dropout=0.0):
        super().__init__()
        h = hidden_dim
        self.entity_encoder = nn.Sequential(nn.Linear(ENTITY_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.entity_gate = nn.Linear(h, 1)
        self.global_encoder = nn.Sequential(nn.Linear(GLOBAL_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.mix = nn.Linear(h * 2, h)
        self.blocks = nn.Sequential(*(ResidualBlock(h, dropout) for _ in range(blocks)))
        self.norm = nn.LayerNorm(h)

        self.action_encoder = nn.Sequential(nn.Linear(ENHANCED_ACTION_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.policy = nn.Sequential(nn.Linear(h * 3, h), nn.GELU(), nn.Linear(h, 1))
        self.value = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 2), nn.Sigmoid())

    def state_embedding(self, entities, mask, global_features):
        encoded = self.entity_encoder(entities)
        gate = self.entity_gate(encoded).squeeze(-1).masked_fill(~mask, torch.finfo(encoded.dtype).min)
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded * weights).sum(dim=1)
        state = self.mix(torch.cat([pooled, self.global_encoder(global_features)], dim=-1))
        return self.norm(self.blocks(state))

    def forward_packed(self, entities, mask, global_features, actions, action_offsets):
        state = self.state_embedding(entities, mask, global_features)
        action = self.action_encoder(actions)
        counts = action_offsets[1:] - action_offsets[:-1]
        expanded = torch.repeat_interleave(state, counts, dim=0)
        logits = self.policy(torch.cat([expanded, action, expanded * action], dim=-1)).squeeze(-1)
        return logits, self.value(state)

if __name__ == "__main__":
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Running M31A Objective-v2 (Canonical Soft-CE + 0.5 * Weighted Ranking) on {device}...", flush=True)

    # Fail-closed output directory check BEFORE burning compute
    ckpt_dir = Path("local-artifacts/m31a-ranking-objective")
    if ckpt_dir.exists():
        raise RuntimeError(f"Output directory {ckpt_dir} already exists — fail-closed protection")
    ckpt_dir.mkdir(parents=True, exist_ok=False)

    config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
    config_text = config_path.read_text(encoding="utf-8")
    config = json.loads(config_text)
    config_file_sha256 = hashlib.sha256(config_text.encode("utf-8")).hexdigest()

    dataset_path = Path("local-artifacts/m25-generation/m25-materialized-dataset.json")
    dataset_text = dataset_path.read_text(encoding="utf-8")
    ds_payload = json.loads(dataset_text)
    dataset_file_sha256 = hashlib.sha256(dataset_text.encode("utf-8")).hexdigest()

    actual_dataset_hash = validate_m25_dataset_provenance(ds_payload, config)
    print(f"Validated Dataset Semantic Hash: {actual_dataset_hash}", flush=True)

    catalog_path = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
    catalog = load_catalog(catalog_path)
    catalog_hash = catalog_semantic_hash(catalog)

    train_indices, val_indices = split_m25_indices(ds_payload, config)
    train_examples = [ds_payload["examples"][i] for i in train_indices]
    val_examples = [ds_payload["examples"][i] for i in val_indices]

    def get_entropy_and_top1(examples):
        ents = []
        top1s = []
        for ex in examples:
            micros = ex["policy_target_micros"]
            probs = [m / 1000000.0 for m in micros]
            top1s.append(max(probs))
            ents.append(-sum(p * math.log(p) for p in probs if p > 0))
        return sum(ents) / len(ents), sum(top1s) / len(top1s)

    train_H, _ = get_entropy_and_top1(train_examples)
    val_H, _ = get_entropy_and_top1(val_examples)
    train_u_ce = compute_uniform_policy_ce(train_examples)
    val_u_ce = compute_uniform_policy_ce(val_examples)

    print("Pre-encoding dataset with exact action deltas and ranking pairs...", flush=True)
    t_enc = time.time()

    class DeltaRankingDataset(Dataset):
        def __init__(self, examples, catalog):
            self.items = []
            for ex in examples:
                obs = encode_observation(ex["observation"], catalog)
                actions = []
                for a in ex["legal_actions"]:
                    base_act = encode_action(a).tolist()
                    delta_act = encode_action_delta_v2(ex["observation"], a, catalog)
                    actions.append(base_act + delta_act)

                micros = ex["policy_target_micros"]
                policy_target = [m / 1000000.0 for m in micros]

                # Extract ranking pair info: (top1_idx, runner_up_idx, weight)
                top1_idx, runner_up_idx, weight = extract_ranking_pair_info(micros)

                self.items.append({
                    "entities": obs.entities,
                    "entity_mask": obs.mask,
                    "global_features": obs.global_features,
                    "actions": torch.tensor(actions, dtype=torch.float32),
                    "policy_target": torch.tensor(policy_target, dtype=torch.float32),
                    "ranking_pair": torch.tensor([top1_idx, runner_up_idx, weight], dtype=torch.float32),
                    "value_target": torch.tensor(ex["value_target"], dtype=torch.float32),
                })

        def __len__(self):
            return len(self.items)

        def __getitem__(self, idx):
            return self.items[idx]

    def packed_delta_ranking_collate(items):
        entities = torch.stack([it["entities"] for it in items])
        entity_mask = torch.stack([it["entity_mask"] for it in items])
        global_features = torch.stack([it["global_features"] for it in items])
        ranking_pairs = torch.stack([it["ranking_pair"] for it in items])
        value_target = torch.stack([it["value_target"] for it in items])

        action_list = [it["actions"] for it in items]
        policy_list = [it["policy_target"] for it in items]

        offsets = [0]
        for acts in action_list:
            offsets.append(offsets[-1] + acts.shape[0])

        return {
            "entities": entities,
            "entity_mask": entity_mask,
            "global_features": global_features,
            "actions": torch.cat(action_list, dim=0),
            "action_offsets": torch.tensor(offsets, dtype=torch.long),
            "policy_target": torch.cat(policy_list, dim=0),
            "ranking_pairs": ranking_pairs,
            "value_target": value_target,
        }

    train_dataset = DeltaRankingDataset(train_examples, catalog)
    eval_train_dataset = DeltaRankingDataset(train_examples, catalog)
    val_dataset = DeltaRankingDataset(val_examples, catalog)
    print(f"Pre-encoding complete in {time.time()-t_enc:.1f}s", flush=True)

    SHUFFLE_SEED = 20260823
    train_generator = torch.Generator().manual_seed(SHUFFLE_SEED)
    train_loader = DataLoader(train_dataset, batch_size=128, shuffle=True, generator=train_generator, collate_fn=packed_delta_ranking_collate)
    eval_train_loader = DataLoader(eval_train_dataset, batch_size=128, shuffle=False, collate_fn=packed_delta_ranking_collate)
    val_loader = DataLoader(val_dataset, batch_size=128, shuffle=False, collate_fn=packed_delta_ranking_collate)

    INIT_SEED = int(config["model"]["initialization_seed"])
    torch.manual_seed(INIT_SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(INIT_SEED)

    model = DeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0).to(device)
    param_count = sum(p.numel() for p in model.parameters())
    print(f"Built DeltaEntityMixer (M31A): {param_count:,} parameters", flush=True)

    epochs = 128
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=3e-4,
        weight_decay=1e-4,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    def evaluate_split(loader, H_val, u_ce):
        model.eval()
        total_examples = 0
        total_ce = 0.0
        total_composite = 0.0
        total_top1_matches = 0
        with torch.no_grad():
            for batch in loader:
                batch_dev = {k: v.to(device) for k, v in batch.items()}
                logits, _ = model.forward_packed(
                    batch_dev["entities"],
                    batch_dev["entity_mask"],
                    batch_dev["global_features"],
                    batch_dev["actions"],
                    batch_dev["action_offsets"],
                )
                tot_loss, p_ce, _ = compute_canonical_ce_and_ranking_loss(
                    logits,
                    batch_dev["policy_target"],
                    batch_dev["action_offsets"],
                    batch_dev["ranking_pairs"],
                    ranking_weight=0.5,
                )
                n = int(batch_dev["entities"].shape[0])
                total_examples += n
                total_ce += p_ce.item() * n
                total_composite += tot_loss.item() * n

                offsets = batch_dev["action_offsets"].tolist()
                policy_target = batch_dev["policy_target"]
                for i in range(len(offsets) - 1):
                    start = offsets[i]
                    end = offsets[i + 1]
                    pred_act = torch.argmax(logits[start:end]).item()
                    teacher_top1 = torch.argmax(policy_target[start:end]).item()
                    if pred_act == teacher_top1:
                        total_top1_matches += 1
        ce = total_ce / total_examples
        composite_loss = total_composite / total_examples
        top1 = total_top1_matches / total_examples
        excess_ce = ce - H_val
        impr_bps = int(round((u_ce - ce) / u_ce * 10000))
        return {
            "ce": ce,
            "composite_loss": composite_loss,
            "excess_ce": excess_ce,
            "top1": top1,
            "impr_bps": impr_bps,
        }

    print(f"Starting M31A: {epochs} epochs of Canonical Soft-CE + 0.5 * Ranking Loss...", flush=True)
    best_val_ce = float("inf")
    best_epoch = 0
    best_state = None
    history = []
    t0 = time.time()

    for ep in range(1, epochs + 1):
        model.train()
        for batch in train_loader:
            batch_dev = {k: v.to(device) for k, v in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            logits, _ = model.forward_packed(
                batch_dev["entities"],
                batch_dev["entity_mask"],
                batch_dev["global_features"],
                batch_dev["actions"],
                batch_dev["action_offsets"],
            )
            total_loss, ce_loss, rank_loss = compute_canonical_ce_and_ranking_loss(
                logits,
                batch_dev["policy_target"],
                batch_dev["action_offsets"],
                batch_dev["ranking_pairs"],
                ranking_weight=0.5,
            )
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

        val_res = evaluate_split(val_loader, val_H, val_u_ce)
        # Checkpoint is strictly selected by validation canonical policy CE
        is_best = val_res["ce"] < best_val_ce
        if is_best:
            best_val_ce = val_res["ce"]
            best_epoch = ep
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        if ep % 8 == 0 or ep in (1, 5, epochs) or is_best:
            print(
                f"Ep {ep:3d}/{epochs}: "
                f"Val [CE={val_res['ce']:.4f}, Exc={val_res['excess_ce']:+.4f}, Top1={val_res['top1']*100:.2f}%, Impr={val_res['impr_bps']}bps, CompLoss={val_res['composite_loss']:.4f}] "
                f"(Best Val CE={best_val_ce:.4f} @ ep {best_epoch}) [{time.time()-t0:.1f}s]",
                flush=True,
            )
        history.append({"epoch": ep, "lr": optimizer.param_groups[0]["lr"], "val": val_res})

    model.load_state_dict(best_state)
    final_val = evaluate_split(val_loader, val_H, val_u_ce)
    final_train = evaluate_split(eval_train_loader, train_H, train_u_ce)

    ckpt_path = ckpt_dir / "checkpoint.pt"
    torch.save({
        "metadata": {
            "milestone": "M31A",
            "loss_objective": "canonical_soft_ce_plus_0.5_weighted_pairwise_logistic_ranking",
            "ranking_loss_weight": 0.5,
            "architecture": "delta_entity_mixer_h192_b4",
            "best_epoch": best_epoch,
            "best_val_ce": best_val_ce,
            "best_val_top1": final_val["top1"],
            "parameter_count": param_count,
            "config_file_sha256": config_file_sha256,
            "dataset_file_sha256": dataset_file_sha256,
            "dataset_semantic_hash": actual_dataset_hash,
            "catalog_hash": catalog_hash,
            "initialization_seed": INIT_SEED,
            "shuffle_seed": SHUFFLE_SEED,
        },
        "state_dict": best_state,
    }, ckpt_path)

    ckpt_bytes = ckpt_path.read_bytes()
    ckpt_file_sha256 = hashlib.sha256(ckpt_bytes).hexdigest()

    exp_d2_path = Path("benchmarks/m25-recovery-exp-d2.result.json")
    exp_d2_data = json.loads(exp_d2_path.read_text(encoding="utf-8")) if exp_d2_path.exists() else {}

    d2_val_ce = exp_d2_data.get("best_checkpoint_val", {}).get("ce", 0.0)
    d2_val_excess = exp_d2_data.get("best_checkpoint_val", {}).get("excess_ce", 0.0)
    d2_val_top1 = exp_d2_data.get("best_checkpoint_val", {}).get("top1", 0.0)

    delta_ce_vs_d2 = final_val["ce"] - d2_val_ce
    delta_top1_vs_d2 = final_val["top1"] - d2_val_top1

    g1_top1_pass = final_val["top1"] >= 0.45
    g1_ce_bps_pass = final_val["impr_bps"] >= 1000

    ranking_signal_pass = (delta_top1_vs_d2 >= 0.03) and (delta_ce_vs_d2 <= 0.005)

    if g1_top1_pass and g1_ce_bps_pass:
        decision = "M31A_G1_PASS_AUTHORIZE_G2"
    elif ranking_signal_pass:
        decision = "M31A_RANKING_SIGNAL_CONFIRMED_G1_FAIL"
    else:
        decision = "STOP_WEIGHTED_PAIRWISE_LOGISTIC_RANKING_ROUTE"

    out_payload = {
        "milestone": "M31A",
        "objective": "OBJECTIVE_V2_WEIGHTED_PAIRWISE_LOGISTIC_RANKING",
        "provenance": {
            "config_file": str(config_path),
            "config_file_sha256": config_file_sha256,
            "dataset_file": str(dataset_path),
            "dataset_file_sha256": dataset_file_sha256,
            "dataset_semantic_hash": actual_dataset_hash,
            "catalog_file": str(catalog_path),
            "catalog_hash": catalog_hash,
            "checkpoint_path": str(ckpt_path),
            "checkpoint_file_sha256": ckpt_file_sha256,
            "initialization_seed": INIT_SEED,
            "shuffle_seed": SHUFFLE_SEED,
        },
        "model": {
            "architecture": "delta_entity_mixer",
            "action_features": ENHANCED_ACTION_FEATURES,
            "hidden_dim": 192,
            "blocks": 4,
            "parameter_count": param_count,
        },
        "loss_formulation": {
            "base_loss": "canonical_soft_ce",
            "auxiliary_loss": "weighted_pairwise_logistic_ranking",
            "ranking_weight_lambda": 0.5,
            "pair_selection": "unique_teacher_top1_vs_first_max_runner_up",
            "weight_formula": "(top1_micros - runner_up_micros) / 900000.0",
            "batch_normalization": "sum_of_margin_weights",
        },
        "epochs": epochs,
        "initial_lr": 3e-4,
        "schedule": "cosine_annealing",
        "weight_decay": 1e-4,
        "value_loss_weight": 0.0,
        "best_epoch": best_epoch,
        "best_val_ce": best_val_ce,
        "best_checkpoint_train": final_train,
        "best_checkpoint_val": final_val,
        "comparison_vs_exp_d2_baseline": {
            "d2_best_epoch": exp_d2_data.get("best_epoch"),
            "d2_val_ce": d2_val_ce,
            "d2_val_excess_ce": d2_val_excess,
            "d2_val_top1": d2_val_top1,
            "d2_val_impr_bps": exp_d2_data.get("best_checkpoint_val", {}).get("impr_bps"),
            "m31a_val_ce": final_val["ce"],
            "m31a_val_excess_ce": final_val["excess_ce"],
            "m31a_val_top1": final_val["top1"],
            "m31a_val_impr_bps": final_val["impr_bps"],
            "delta_val_ce_vs_d2": delta_ce_vs_d2,
            "delta_val_top1_vs_d2": delta_top1_vs_d2,
        },
        "gate_evaluations": {
            "g1_heldout_teacher_fit": {
                "target_top1": ">= 0.45 (45.00%)",
                "achieved_top1": final_val["top1"],
                "top1_pass": g1_top1_pass,
                "target_ce_impr_bps": ">= 1000 bps",
                "achieved_ce_impr_bps": final_val["impr_bps"],
                "ce_impr_bps_pass": g1_ce_bps_pass,
                "g1_pass": g1_top1_pass and g1_ce_bps_pass,
            },
            "ranking_objective_signal_gate": {
                "target_top1_delta_vs_d2": ">= +0.03 (+3.0 pp)",
                "achieved_top1_delta_vs_d2": delta_top1_vs_d2,
                "target_max_ce_degradation_vs_d2": "<= +0.005 nats",
                "achieved_ce_delta_vs_d2": delta_ce_vs_d2,
                "ranking_signal_pass": ranking_signal_pass,
            },
            "decision": decision,
            "arena_authorized": False,
        },
        "history": history,
    }

    out_path = Path("benchmarks/m31a-ranking-objective.result.json")
    out_path.write_text(json.dumps(out_payload, indent=2) + "\n", encoding="utf-8")
    print(f"COMPLETE M31A: Best Epoch {best_epoch}, Val CE {final_val['ce']:.4f} (Exc {final_val['excess_ce']:+.4f}), Val Top1 {final_val['top1']*100:.2f}%, Train CE {final_train['ce']:.4f}, Train Top1 {final_train['top1']*100:.2f}%, Decision: {decision}", flush=True)
