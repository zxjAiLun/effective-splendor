
import time
import json
import math
from pathlib import Path
import torch
import torch.nn.functional as F

from splendor_gpu.encoded_cache import EncodedCache, PackedEncodedDataset
from splendor_gpu.interaction_train import _loader, packed_policy_loss
from splendor_gpu.m25_train import split_m25_indices, compute_uniform_policy_ce, build_m25_model

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {device}", flush=True)

config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
config = json.loads(config_path.read_text(encoding="utf-8"))

dataset_path = Path("local-artifacts/m25-generation/m25-materialized-dataset.json")
ds_payload = json.loads(dataset_path.read_text(encoding="utf-8"))

cache_dir = Path("local-artifacts/m25-training-run-v1/encoded_cache")
cache = EncodedCache.load(cache_dir)

train_indices, _ = split_m25_indices(ds_payload, config)
sanity_indices = train_indices[:1024]
sanity_examples = [ds_payload["examples"][i] for i in sanity_indices]

entropies = []
top1_probs = []
legal_counts = []
for ex in sanity_examples:
    micros = ex["policy_target_micros"]
    probs = [m / 1000000.0 for m in micros]
    legal_counts.append(len(probs))
    top1_probs.append(max(probs))
    ent = -sum(p * math.log(p) for p in probs if p > 0)
    entropies.append(ent)

H = sum(entropies) / len(entropies)
uniform_ce = compute_uniform_policy_ce(sanity_examples)
mean_top1_teacher = sum(top1_probs) / len(top1_probs)

print(f"1024-subset Stats: Count={len(sanity_examples)}, H={H:.4f} nats, Uniform CE={uniform_ce:.4f}, Mean Teacher Top1 Prob={mean_top1_teacher*100:.2f}%", flush=True)

sanity_dataset = PackedEncodedDataset(cache, sanity_indices)
sanity_loader = _loader(sanity_dataset, 64, True, 20260823, device)
eval_loader = _loader(sanity_dataset, 128, False, None, device)

seed = int(config["model"]["initialization_seed"])
model = build_m25_model(config, seed=seed).to(device)

optimizer = torch.optim.AdamW(
    model.parameters(),
    lr=3e-4,
    weight_decay=0.0,
)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=200, eta_min=1e-5)

def evaluate_sanity(mod):
    mod.eval()
    total_examples = 0
    total_ce = 0.0
    total_top1_matches = 0
    with torch.no_grad():
        for batch in eval_loader:
            batch_dev = {k: v.to(device) for k, v in batch.items()}
            logits, values = mod.forward_packed(
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
    excess_ce = ce - H
    return ce, excess_ce, top1

t0 = time.time()
best_excess_ce = float("inf")
best_epoch = 0
history = []

for ep in range(1, 201):
    model.train()
    for batch in sanity_loader:
        batch_dev = {k: v.to(device) for k, v in batch.items()}
        optimizer.zero_grad(set_to_none=True)
        logits, values = model.forward_packed(
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
    
    if ep % 20 == 0 or ep in (1, 5, 10, 200):
        ce, excess_ce, top1 = evaluate_sanity(model)
        if excess_ce < best_excess_ce:
            best_excess_ce = excess_ce
            best_epoch = ep
        history.append({"epoch": ep, "ce": ce, "excess_ce": excess_ce, "top1": top1, "lr": optimizer.param_groups[0]["lr"]})
        print(f"Epoch {ep:3d}/200: Policy CE={ce:.4f}, Excess CE={excess_ce:+.4f} nats, Top-1={top1*100:.2f}% (Best={best_excess_ce:.4f} @ ep {best_epoch}) [{time.time()-t0:.1f}s]", flush=True)

final_ce, final_excess_ce, final_top1 = evaluate_sanity(model)
result = {
    "n_examples": 1024,
    "target_entropy_H": H,
    "uniform_ce": uniform_ce,
    "mean_teacher_top1_prob": mean_top1_teacher,
    "best_epoch": best_epoch,
    "best_excess_ce": best_excess_ce,
    "final_epoch": 200,
    "final_policy_ce": final_ce,
    "final_excess_ce": final_excess_ce,
    "final_top1_agreement": final_top1,
    "history": history,
}

Path("benchmarks/m25-policy-fit-sanity.result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print("Saved benchmarks/m25-policy-fit-sanity.result.json", flush=True)
