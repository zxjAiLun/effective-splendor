"""M25 Optimization Recovery - Experiment B: h320/b4 Capacity Probe (Policy-Only Full Data, 128 epochs)."""
import time
import json
import math
from pathlib import Path
import torch
import torch.nn.functional as F

from splendor_gpu.encoded_cache import EncodedCache, PackedEncodedDataset
from splendor_gpu.interaction_train import _loader, packed_policy_loss
from splendor_gpu.m25_train import split_m25_indices, compute_uniform_policy_ce, build_m25_model
from splendor_gpu.model import ModelSpec, build_model

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Running Experiment B (h320/b4) on {device}...", flush=True)

config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
config = json.loads(config_path.read_text(encoding="utf-8"))

dataset_path = Path("local-artifacts/m25-generation/m25-materialized-dataset.json")
ds_payload = json.loads(dataset_path.read_text(encoding="utf-8"))

cache_dir = Path("local-artifacts/m25-training-run-v1/encoded_cache")
cache = EncodedCache.load(cache_dir)

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

train_dataset = PackedEncodedDataset(cache, train_indices)
val_dataset = PackedEncodedDataset(cache, val_indices)

train_loader = _loader(train_dataset, 128, True, 20260823, device)
eval_train_loader = _loader(train_dataset, 128, False, None, device)
val_loader = _loader(val_dataset, 128, False, None, device)

# Build h320/b4 Entity Mixer model
spec_h320 = ModelSpec(
    architecture="entity_mixer",
    hidden_dim=320,
    blocks=4,
    dropout=0.0,
    interaction_blocks=0,
)
seed = int(config["model"]["initialization_seed"])
torch.manual_seed(seed)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(seed)
model = build_model(spec_h320).to(device)
param_count = sum(p.numel() for p in model.parameters())
print(f"Built h320/b4 Entity Mixer: {param_count:,} parameters (vs h192/b4 949,060 params)", flush=True)

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
            p_loss = packed_policy_loss(logits, batch_dev["policy_target"], batch_dev["action_offsets"])
            n = int(batch_dev["entities"].shape[0])
            total_examples += n
            total_ce += p_loss.item() * n
            
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
    top1 = total_top1_matches / total_examples
    excess_ce = ce - H_val
    impr_bps = int(round((u_ce - ce) / u_ce * 10000))
    return {"ce": ce, "excess_ce": excess_ce, "top1": top1, "impr_bps": impr_bps}

print(f"Starting Experiment B: {epochs} epochs of h320/b4 Policy-Only (wd=1e-4, lr=3e-4 cosine)...", flush=True)
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
        p_loss = packed_policy_loss(logits, batch_dev["policy_target"], batch_dev["action_offsets"])
        p_loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
    scheduler.step()
    
    val_res = evaluate_split(val_loader, val_H, val_u_ce)
    is_best = val_res["ce"] < best_val_ce
    if is_best:
        best_val_ce = val_res["ce"]
        best_epoch = ep
        best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        
    if ep % 8 == 0 or ep in (1, 5, epochs) or is_best:
        print(
            f"Ep {ep:3d}/{epochs}: "
            f"Val [CE={val_res['ce']:.4f}, Exc={val_res['excess_ce']:+.4f}, Top1={val_res['top1']*100:.2f}%, Impr={val_res['impr_bps']}bps] "
            f"(Best Val CE={best_val_ce:.4f} @ ep {best_epoch}) [{time.time()-t0:.1f}s]",
            flush=True,
        )
    history.append({"epoch": ep, "lr": optimizer.param_groups[0]["lr"], "val": val_res})

model.load_state_dict(best_state)
final_val = evaluate_split(val_loader, val_H, val_u_ce)
final_train = evaluate_split(eval_train_loader, train_H, train_u_ce)

# Load Experiment A baseline for direct comparison
exp_a_path = Path("benchmarks/m25-recovery-exp-a.result.json")
exp_a_data = json.loads(exp_a_path.read_text(encoding="utf-8")) if exp_a_path.exists() else {}

out_payload = {
    "experiment": "M25_RECOVERY_EXP_B_H320_CAPACITY_PROBE",
    "model": {
        "architecture": "entity_mixer",
        "hidden_dim": 320,
        "blocks": 4,
        "parameter_count": param_count,
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
    "comparison_vs_h192_exp_a": {
        "h192_best_epoch": exp_a_data.get("best_epoch"),
        "h192_val_ce": exp_a_data.get("best_checkpoint_val", {}).get("ce"),
        "h192_val_excess_ce": exp_a_data.get("best_checkpoint_val", {}).get("excess_ce"),
        "h192_val_top1": exp_a_data.get("best_checkpoint_val", {}).get("top1"),
        "h320_val_ce": final_val["ce"],
        "h320_val_excess_ce": final_val["excess_ce"],
        "h320_val_top1": final_val["top1"],
        "val_excess_ce_delta_h320_minus_h192": final_val["excess_ce"] - exp_a_data.get("best_checkpoint_val", {}).get("excess_ce", 0.0),
        "val_top1_delta_h320_minus_h192": final_val["top1"] - exp_a_data.get("best_checkpoint_val", {}).get("top1", 0.0),
    },
    "history": history,
}

out_path = Path("benchmarks/m25-recovery-exp-b.result.json")
out_path.write_text(json.dumps(out_payload, indent=2) + "\n", encoding="utf-8")
print(f"COMPLETE: h320 Best Epoch {best_epoch}, Val CE {final_val['ce']:.4f} (Exc {final_val['excess_ce']:+.4f}), Val Top1 {final_val['top1']*100:.2f}%, Train CE {final_train['ce']:.4f}, Train Top1 {final_train['top1']*100:.2f}%", flush=True)
