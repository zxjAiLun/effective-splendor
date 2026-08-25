"""M33A Factorized Legal-Action Policy Training Runner."""
import time
import json
import math
from pathlib import Path
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from splendor_gpu.data import load_catalog, catalog_semantic_hash
from splendor_gpu.encoding import encode_observation, encode_action
from splendor_gpu.m25_train import split_m25_indices, compute_uniform_policy_ce, validate_m25_dataset_provenance
from splendor_gpu.m25_delta_v2 import encode_action_delta_v2
from splendor_gpu.self_play_train import packed_policy_loss
from splendor_gpu.m33a_model import FactorizedDeltaEntityMixer, ENHANCED_ACTION_FEATURES
from splendor_gpu.m33a_encoding import decompose_legal_action
from splendor_gpu.m33a_eval import evaluate_m33a_diagnostics
from splendor_gpu.m33a_preflight import preflight_m33a, compute_file_sha256

if __name__ == "__main__":
    runner_path = Path(__file__)
    model_path = Path("training/m17_gpu/splendor_gpu/m33a_model.py")
    encoding_path = Path("training/m17_gpu/splendor_gpu/m33a_encoding.py")
    eval_path = Path("training/m17_gpu/splendor_gpu/m33a_eval.py")
    preflight_path = Path("training/m17_gpu/splendor_gpu/m33a_preflight.py")

    runner_file_sha256 = compute_file_sha256(runner_path)
    model_file_sha256 = compute_file_sha256(model_path)
    encoding_file_sha256 = compute_file_sha256(encoding_path)
    eval_file_sha256 = compute_file_sha256(eval_path)
    preflight_file_sha256 = compute_file_sha256(preflight_path)

    config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
    dataset_path = Path("local-artifacts/m25-generation/m25-materialized-dataset.json")
    catalog_path = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
    d2_result_path = Path("benchmarks/m25-recovery-exp-d2.result.json")
    ckpt_dir = Path("local-artifacts/m33a-factorized-policy")

    config_text = config_path.read_text(encoding="utf-8")
    config = json.loads(config_text)
    ds_payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    actual_dataset_hash = validate_m25_dataset_provenance(ds_payload, config)
    catalog = load_catalog(catalog_path)
    actual_catalog_hash = catalog_semantic_hash(catalog)

    # 1. Set seed BEFORE constructing official model
    INIT_SEED = int(config["model"]["initialization_seed"])
    torch.manual_seed(INIT_SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(INIT_SEED)

    # 2. Construct official model
    model = FactorizedDeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)
    param_count = sum(p.numel() for p in model.parameters())

    # 3. Strict fail-closed preflight check BEFORE creating output directory
    provenance_hashes = preflight_m33a(
        config_path=config_path,
        dataset_path=dataset_path,
        catalog_path=catalog_path,
        d2_result_path=d2_result_path,
        output_dir=ckpt_dir,
        actual_dataset_semantic_hash=actual_dataset_hash,
        actual_catalog_hash=actual_catalog_hash,
        actual_param_count=param_count,
        require_cuda=True,
    )
    print(f"Preflight validation passed: all frozen hashes match. Param count: {param_count:,}.", flush=True)

    # 4. Create output directory only after preflight succeeds
    ckpt_dir.mkdir(parents=True, exist_ok=False)

    device = torch.device("cuda")
    model = model.to(device)
    print(f"Running M33A Factorized Policy on {device} (Init seed={INIT_SEED})...", flush=True)

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

    print("Pre-encoding dataset with exact action deltas and factorized components...", flush=True)
    t_enc = time.time()

    class FactorizedDataset(Dataset):
        def __init__(self, examples, catalog):
            self.items = []
            for ex in examples:
                obs_raw = ex["observation"]
                obs = encode_observation(obs_raw, catalog)

                actions = []
                family_indices = []
                take_mode_indices = []
                selected_colors = []
                returned_colors = []
                target_entity_slots = []
                target_deck_tiers = []

                for a in ex["legal_actions"]:
                    base_act = encode_action(a).tolist()
                    delta_act = encode_action_delta_v2(obs_raw, a, catalog)
                    actions.append(base_act + delta_act)

                    decomp = decompose_legal_action(obs_raw, a)
                    family_indices.append(decomp["family_idx"])
                    take_mode_indices.append(decomp["take_mode_idx"])
                    selected_colors.append(decomp["selected_colors"])
                    returned_colors.append(decomp["returned_colors"])
                    target_entity_slots.append(decomp["target_entity_slot"])
                    target_deck_tiers.append(decomp["target_deck_tier"])

                micros = ex["policy_target_micros"]
                policy_target = [m / 1000000.0 for m in micros]

                self.items.append({
                    "entities": obs.entities,
                    "entity_mask": obs.mask,
                    "global_features": obs.global_features,
                    "actions": torch.tensor(actions, dtype=torch.float32),
                    "family_indices": torch.tensor(family_indices, dtype=torch.long),
                    "take_mode_indices": torch.tensor(take_mode_indices, dtype=torch.long),
                    "selected_colors": torch.tensor(selected_colors, dtype=torch.float32),
                    "returned_colors": torch.tensor(returned_colors, dtype=torch.float32),
                    "target_entity_slots": torch.tensor(target_entity_slots, dtype=torch.long),
                    "target_deck_tiers": torch.tensor(target_deck_tiers, dtype=torch.long),
                    "policy_target": torch.tensor(policy_target, dtype=torch.float32),
                    "value_target": torch.tensor(ex["value_target"], dtype=torch.float32),
                })

        def __len__(self):
            return len(self.items)

        def __getitem__(self, idx):
            return self.items[idx]

    def packed_factorized_collate(items):
        entities = torch.stack([it["entities"] for it in items])
        entity_mask = torch.stack([it["entity_mask"] for it in items])
        global_features = torch.stack([it["global_features"] for it in items])
        value_target = torch.stack([it["value_target"] for it in items])

        action_list = [it["actions"] for it in items]
        family_list = [it["family_indices"] for it in items]
        take_mode_list = [it["take_mode_indices"] for it in items]
        selected_colors_list = [it["selected_colors"] for it in items]
        returned_colors_list = [it["returned_colors"] for it in items]
        target_entity_list = [it["target_entity_slots"] for it in items]
        target_deck_list = [it["target_deck_tiers"] for it in items]
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
            "family_indices": torch.cat(family_list, dim=0),
            "take_mode_indices": torch.cat(take_mode_list, dim=0),
            "selected_colors": torch.cat(selected_colors_list, dim=0),
            "returned_colors": torch.cat(returned_colors_list, dim=0),
            "target_entity_slots": torch.cat(target_entity_list, dim=0),
            "target_deck_tiers": torch.cat(target_deck_list, dim=0),
            "policy_target": torch.cat(policy_list, dim=0),
            "value_target": value_target,
        }

    train_dataset = FactorizedDataset(train_examples, catalog)
    eval_train_dataset = FactorizedDataset(train_examples, catalog)
    val_dataset = FactorizedDataset(val_examples, catalog)
    print(f"Pre-encoding complete in {time.time()-t_enc:.1f}s", flush=True)

    SHUFFLE_SEED = 20260823
    train_generator = torch.Generator().manual_seed(SHUFFLE_SEED)
    train_loader = DataLoader(train_dataset, batch_size=128, shuffle=True, generator=train_generator, collate_fn=packed_factorized_collate)
    eval_train_loader = DataLoader(eval_train_dataset, batch_size=128, shuffle=False, collate_fn=packed_factorized_collate)
    val_loader = DataLoader(val_dataset, batch_size=128, shuffle=False, collate_fn=packed_factorized_collate)

    epochs = 128
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=3e-4,
        weight_decay=1e-4,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    print(f"Starting M33A: {epochs} epochs of Canonical Soft-CE with Factorized Decomposition...", flush=True)
    best_val_ce = float("inf")
    best_epoch = 0
    best_state = None
    history = []
    t0 = time.time()

    for ep in range(1, epochs + 1):
        model.train()
        for batch in train_loader:
            batch_dev = {k: v.to(device, non_blocking=True) for k, v in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            logits, _ = model.forward_packed(
                batch_dev["entities"],
                batch_dev["entity_mask"],
                batch_dev["global_features"],
                batch_dev["actions"],
                batch_dev["action_offsets"],
                batch_dev["family_indices"],
                batch_dev["take_mode_indices"],
                batch_dev["selected_colors"],
                batch_dev["returned_colors"],
                batch_dev["target_entity_slots"],
                batch_dev["target_deck_tiers"],
            )
            loss = packed_policy_loss(logits, batch_dev["policy_target"], batch_dev["action_offsets"])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

        val_res = evaluate_m33a_diagnostics(model, val_loader, val_examples, val_H, val_u_ce, device)
        is_best = val_res["ce"] < best_val_ce
        if is_best:
            best_val_ce = val_res["ce"]
            best_epoch = ep
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        if ep % 8 == 0 or ep in (1, 5, epochs) or is_best:
            print(
                f"Ep {ep:3d}/{epochs}: "
                f"Val [CE={val_res['ce']:.4f}, Exc={val_res['excess_ce']:+.4f}, Top1={val_res['top1']*100:.2f}%, FamTop1={val_res['family_top1']*100:.2f}%] "
                f"Take [Recall={val_res['take']['family_recall']*100:.1f}%, Top1={val_res['take']['exact_top1']*100:.1f}%] "
                f"Buy [Top1={val_res['buy']['exact_top1']*100:.1f}%] "
                f"Reserve [Recall={val_res['reserve']['family_recall']*100:.1f}%, Top1={val_res['reserve']['exact_top1']*100:.1f}%] "
                f"(Best Val CE={best_val_ce:.4f} @ ep {best_epoch}) [{time.time()-t0:.1f}s]",
                flush=True,
            )
        history.append({"epoch": ep, "lr": optimizer.param_groups[0]["lr"], "val": val_res})

    model.load_state_dict(best_state)
    final_val = evaluate_m33a_diagnostics(model, val_loader, val_examples, val_H, val_u_ce, device)
    final_train = evaluate_m33a_diagnostics(model, eval_train_loader, train_examples, train_H, train_u_ce, device)

    ckpt_path = ckpt_dir / "checkpoint.pt"
    torch.save({
        "metadata": {
            "milestone": "M33A",
            "loss_objective": "canonical_soft_ce",
            "architecture": "factorized_delta_entity_mixer_h192_b4",
            "best_epoch": best_epoch,
            "best_val_ce": best_val_ce,
            "best_val_top1": final_val["top1"],
            "parameter_count": param_count,
            "config_file_sha256": provenance_hashes["config_file_sha256"],
            "dataset_file_sha256": provenance_hashes["dataset_file_sha256"],
            "dataset_semantic_hash": actual_dataset_hash,
            "catalog_hash": actual_catalog_hash,
            "d2_result_file_sha256": provenance_hashes["d2_result_file_sha256"],
            "runner_file_sha256": runner_file_sha256,
            "model_file_sha256": model_file_sha256,
            "encoding_file_sha256": encoding_file_sha256,
            "eval_file_sha256": eval_file_sha256,
            "preflight_file_sha256": preflight_file_sha256,
            "initialization_seed": INIT_SEED,
            "shuffle_seed": SHUFFLE_SEED,
        },
        "state_dict": best_state,
    }, ckpt_path)

    ckpt_file_sha256 = compute_file_sha256(ckpt_path)

    exp_d2_data = json.loads(d2_result_path.read_text(encoding="utf-8"))
    d2_val_ce = exp_d2_data["best_checkpoint_val"]["ce"]
    d2_val_excess = exp_d2_data["best_checkpoint_val"]["excess_ce"]
    d2_val_top1 = exp_d2_data["best_checkpoint_val"]["top1"]

    delta_ce_vs_d2 = final_val["ce"] - d2_val_ce
    delta_top1_vs_d2 = final_val["top1"] - d2_val_top1

    # Gate Evaluations
    g1_top1_pass = final_val["top1"] >= 0.45
    g1_ce_bps_pass = final_val["impr_bps"] >= 1000
    g1_overall_pass = g1_top1_pass and g1_ce_bps_pass

    global_signal_pass = (delta_ce_vs_d2 <= -0.0200) and (delta_top1_vs_d2 >= 0.0200)
    targeted_take_fam_pass = final_val["take"]["family_recall"] >= 0.3911  # +10 pp vs 29.11%
    targeted_take_top1_pass = final_val["take"]["exact_top1"] >= 0.0832   # +5 pp vs 3.32%
    targeted_res_top1_pass = final_val["reserve"]["exact_top1"] >= 0.1722 # +3 pp vs 14.22%
    targeted_buy_top1_pass = final_val["buy"]["exact_top1"] >= 0.7415    # max 2 pp drop vs 76.15%

    targeted_signal_pass = (
        targeted_take_fam_pass
        and targeted_take_top1_pass
        and targeted_res_top1_pass
        and targeted_buy_top1_pass
    )

    factorization_signal_pass = global_signal_pass and targeted_signal_pass

    if g1_overall_pass:
        decision = "M33A_G1_PASS_AUTHORIZE_G2"
    elif factorization_signal_pass:
        decision = "M33A_FACTORIZATION_SIGNAL_CONFIRMED_G1_FAIL"
    else:
        decision = "STOP_FACTORIZED_LEGAL_ACTION_POLICY_ROUTE"

    out_payload = {
        "milestone": "M33A",
        "objective": "FACTORIZED_LEGAL_ACTION_POLICY_V1",
        "provenance": {
            "config_file": str(config_path),
            "config_file_sha256": provenance_hashes["config_file_sha256"],
            "dataset_file": str(dataset_path),
            "dataset_file_sha256": provenance_hashes["dataset_file_sha256"],
            "dataset_semantic_hash": actual_dataset_hash,
            "catalog_file": str(catalog_path),
            "catalog_hash": actual_catalog_hash,
            "d2_result_file": str(d2_result_path),
            "d2_result_file_sha256": provenance_hashes["d2_result_file_sha256"],
            "runner_file": str(runner_path),
            "runner_file_sha256": runner_file_sha256,
            "model_file": str(model_path),
            "model_file_sha256": model_file_sha256,
            "encoding_file": str(encoding_path),
            "encoding_file_sha256": encoding_file_sha256,
            "eval_file": str(eval_path),
            "eval_file_sha256": eval_file_sha256,
            "preflight_file": str(preflight_path),
            "preflight_file_sha256": preflight_file_sha256,
            "checkpoint_path": str(ckpt_path),
            "checkpoint_file_sha256": ckpt_file_sha256,
            "initialization_seed": INIT_SEED,
            "shuffle_seed": SHUFFLE_SEED,
        },
        "model": {
            "architecture": "factorized_delta_entity_mixer",
            "action_features": ENHANCED_ACTION_FEATURES,
            "hidden_dim": 192,
            "blocks": 4,
            "parameter_count": param_count,
        },
        "epochs": epochs,
        "initial_lr": 3e-4,
        "schedule": "cosine_annealing",
        "weight_decay": 1e-4,
        "best_epoch": best_epoch,
        "best_val_ce": best_val_ce,
        "best_checkpoint_train": final_train,
        "best_checkpoint_val": final_val,
        "comparison_vs_exp_d2_baseline": {
            "d2_best_epoch": exp_d2_data["best_epoch"],
            "d2_val_ce": d2_val_ce,
            "d2_val_excess_ce": d2_val_excess,
            "d2_val_top1": d2_val_top1,
            "d2_val_impr_bps": exp_d2_data["best_checkpoint_val"]["impr_bps"],
            "d2_diagnostics": {
                "family_top1": 0.6803,
                "take_family_recall": 0.2911,
                "take_exact_top1": 0.0332,
                "buy_exact_top1": 0.7615,
                "reserve_family_recall": 0.6871,
                "reserve_exact_top1": 0.1422,
            },
            "m33a_val_ce": final_val["ce"],
            "m33a_val_excess_ce": final_val["excess_ce"],
            "m33a_val_top1": final_val["top1"],
            "m33a_val_impr_bps": final_val["impr_bps"],
            "delta_val_ce_vs_d2": delta_ce_vs_d2,
            "delta_val_top1_vs_d2": delta_top1_vs_d2,
        },
        "gate_evaluations": {
            "g1_primary_gate": {
                "target_top1": ">= 0.4500 (45.00%)",
                "achieved_top1": final_val["top1"],
                "top1_pass": g1_top1_pass,
                "target_ce_impr_bps": ">= 1000 bps",
                "achieved_ce_impr_bps": final_val["impr_bps"],
                "ce_impr_bps_pass": g1_ce_bps_pass,
                "g1_pass": g1_overall_pass,
            },
            "factorization_signal_gate": {
                "global_signal": {
                    "target_ce_delta_vs_d2": "<= -0.0200 nats (<= 2.7977)",
                    "achieved_ce_delta_vs_d2": delta_ce_vs_d2,
                    "target_top1_delta_vs_d2": ">= +0.0200 pp (>= 40.42%)",
                    "achieved_top1_delta_vs_d2": delta_top1_vs_d2,
                    "global_pass": global_signal_pass,
                },
                "targeted_signal": {
                    "take_family_recall": {
                        "target": ">= 0.3911 (+10 pp)",
                        "achieved": final_val["take"]["family_recall"],
                        "pass": targeted_take_fam_pass,
                    },
                    "take_exact_top1": {
                        "target": ">= 0.0832 (+5 pp)",
                        "achieved": final_val["take"]["exact_top1"],
                        "pass": targeted_take_top1_pass,
                    },
                    "reserve_exact_top1": {
                        "target": ">= 0.1722 (+3 pp)",
                        "achieved": final_val["reserve"]["exact_top1"],
                        "pass": targeted_res_top1_pass,
                    },
                    "buy_exact_top1": {
                        "target": ">= 0.7415 (max -2 pp drop)",
                        "achieved": final_val["buy"]["exact_top1"],
                        "pass": targeted_buy_top1_pass,
                    },
                    "targeted_pass": targeted_signal_pass,
                },
                "factorization_signal_pass": factorization_signal_pass,
            },
            "decision": decision,
            "arena_authorized": False,
        },
        "history": history,
    }

    out_path = Path("benchmarks/m33a-factorized-policy.result.json")
    out_path.write_text(json.dumps(out_payload, indent=2) + "\n", encoding="utf-8")
    print(f"COMPLETE M33A: Best Epoch {best_epoch}, Val CE {final_val['ce']:.4f}, Val Top1 {final_val['top1']*100:.2f}%, Take Top1 {final_val['take']['exact_top1']*100:.1f}%, Decision: {decision}", flush=True)
