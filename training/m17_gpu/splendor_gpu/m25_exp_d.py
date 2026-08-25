"""M25 Optimization Recovery - Experiment D: Action-Conditioned Delta Feature Probe (h192/b4, 128 epochs)."""
import time
import json
import math
from pathlib import Path
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

from splendor_gpu.data import load_catalog
from splendor_gpu.encoding import (
    ENTITY_SLOTS, ENTITY_FEATURES, GLOBAL_FEATURES, ACTION_FEATURES,
    encode_observation, encode_action, GEMS, COLORS, TIERS
)
from splendor_gpu.m25_train import split_m25_indices, compute_uniform_policy_ce
from splendor_gpu.model import ModelSpec, ResidualBlock, PolicyValueBase

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Running Experiment D (Action-Conditioned Delta Features) on {device}...", flush=True)

config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
config = json.loads(config_path.read_text(encoding="utf-8"))

dataset_path = Path("local-artifacts/m25-generation/m25-materialized-dataset.json")
ds_payload = json.loads(dataset_path.read_text(encoding="utf-8"))

catalog = load_catalog(Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"))

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

def encode_action_delta(observation, action, catalog):
    public = observation["public"]
    viewer = int(observation["viewer"])
    player = public["players"][viewer]
    tokens = {k: int(player["tokens"][k]) for k in GEMS}
    bonuses = list(player["bonuses"])
    prestige = int(player["prestige"])

    delta_vp = 0.0
    delta_bonuses = [0.0] * 5
    delta_tokens = [0.0] * 6
    card_cost = [0.0] * 5
    card_prestige = 0.0
    gold_spent = 0.0
    noble_delta = 0.0

    kind = action.get("type")
    if kind == "take_tokens":
        take = action.get("take", {})
        ret = action.get("return", {})
        for i, g in enumerate(GEMS):
            delta_tokens[i] = (take.get(g, 0) - ret.get(g, 0)) / 10.0
    elif kind in ("buy_market", "buy_reserved"):
        card = None
        if kind == "buy_market":
            tier = TIERS.index(action["tier"])
            slot = int(action["slot"])
            card_id = public["market"][tier][slot]
            if card_id is not None:
                card = catalog["cards"].get(int(card_id))
        else:
            slot = int(action["slot"])
            reserved = observation["private"]["reserved"]
            if slot < len(reserved):
                card_id = int(reserved[slot]["card"])
                card = catalog["cards"].get(card_id)
        if card is not None:
            card_prestige = card["prestige"] / 5.0
            delta_vp = card["prestige"] / 5.0
            color_idx = COLORS.index(str(card["bonus"]).lower())
            delta_bonuses[color_idx] = 1.0
            for i, c in enumerate(card["cost"]):
                card_cost[i] = c / 7.0
            total_gold_paid = 0
            for i, c in enumerate(COLORS):
                needed = max(0, card["cost"][i] - bonuses[i])
                paid = min(tokens[c], needed)
                deficit = needed - paid
                total_gold_paid += deficit
                delta_tokens[i] = -paid / 10.0
            delta_tokens[5] = -total_gold_paid / 10.0
            gold_spent = total_gold_paid / 5.0

            visible_nobles = [catalog["nobles"][int(nid)] for nid in public["nobles"] if int(nid) in catalog["nobles"]]
            if visible_nobles:
                cur_dist = min(sum(max(0, n["requirements"][c] - bonuses[c]) for c in range(5)) for n in visible_nobles)
                new_dist = min(sum(max(0, n["requirements"][c] - (bonuses[c] + (1 if c == color_idx else 0))) for c in range(5)) for n in visible_nobles)
                if cur_dist > new_dist:
                    noble_delta = 1.0
                    if new_dist == 0:
                        delta_vp += 3.0 / 5.0
    elif kind == "reserve_market":
        tier = TIERS.index(action["tier"])
        slot = int(action["slot"])
        card_id = public["market"][tier][slot]
        if card_id is not None:
            card = catalog["cards"].get(int(card_id))
            if card is not None:
                card_prestige = card["prestige"] / 5.0
                color_idx = COLORS.index(str(card["bonus"]).lower())
                delta_bonuses[color_idx] = 0.5
                for i, c in enumerate(card["cost"]):
                    card_cost[i] = c / 7.0
        ret = action.get("return", {})
        gold_taken = 1 if sum(tokens.values()) < 10 and public["bank"].get("gold", 0) > 0 else 0
        delta_tokens[5] = (gold_taken - ret.get("gold", 0)) / 10.0
    elif kind == "reserve_deck":
        ret = action.get("return", {})
        gold_taken = 1 if sum(tokens.values()) < 10 and public["bank"].get("gold", 0) > 0 else 0
        delta_tokens[5] = (gold_taken - ret.get("gold", 0)) / 10.0
    elif kind == "choose_noble":
        delta_vp = 3.0 / 5.0
        noble_delta = 1.0

    post_vp = (prestige + delta_vp * 5.0) / 15.0
    dist_15 = max(0.0, 15.0 - (prestige + delta_vp * 5.0)) / 15.0
    post_tokens = (sum(tokens.values()) + sum(delta_tokens) * 10.0) / 10.0

    delta_vec = [
        delta_vp, post_vp, dist_15,
        *delta_bonuses,
        *delta_tokens,
        post_tokens,
        *card_cost,
        card_prestige,
        gold_spent,
        noble_delta,
    ]
    return delta_vec

print("Pre-encoding examples with action-delta features...", flush=True)
t_enc = time.time()

class DeltaEncodedDataset(Dataset):
    def __init__(self, examples, catalog):
        self.items = []
        for ex in examples:
            obs = encode_observation(ex["observation"], catalog)
            actions = []
            for a in ex["legal_actions"]:
                base_act = encode_action(a).tolist()
                delta_act = encode_action_delta(ex["observation"], a, catalog)
                actions.append(base_act + delta_act)
            policy_target = [m / 1000000.0 for m in ex["policy_target_micros"]]
            self.items.append({
                "entities": obs.entities,
                "entity_mask": obs.mask,
                "global_features": obs.global_features,
                "actions": torch.tensor(actions, dtype=torch.float32),
                "policy_target": torch.tensor(policy_target, dtype=torch.float32),
                "value_target": torch.tensor(ex["value_target"], dtype=torch.float32),
            })
    def __len__(self):
        return len(self.items)
    def __getitem__(self, idx):
        return self.items[idx]

def packed_delta_collate(items):
    entities = torch.stack([it["entities"] for it in items])
    entity_mask = torch.stack([it["entity_mask"] for it in items])
    global_features = torch.stack([it["global_features"] for it in items])
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
        "value_target": value_target,
    }

train_dataset = DeltaEncodedDataset(train_examples, catalog)
val_dataset = DeltaEncodedDataset(val_examples, catalog)
print(f"Pre-encoding complete in {time.time()-t_enc:.1f}s", flush=True)

train_loader = DataLoader(train_dataset, batch_size=128, shuffle=True, collate_fn=packed_delta_collate)
eval_train_loader = DataLoader(train_dataset, batch_size=128, shuffle=False, collate_fn=packed_delta_collate)
val_loader = DataLoader(val_dataset, batch_size=128, shuffle=False, collate_fn=packed_delta_collate)

# Delta Action Model
ENHANCED_ACTION_FEATURES = 36 + 23  # 59

class DeltaEntityMixer(nn.Module):
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

def packed_policy_loss(logits, targets, offsets):
    losses = []
    for i in range(len(offsets) - 1):
        s, e = offsets[i], offsets[i + 1]
        l = logits[s:e]
        t = targets[s:e]
        log_p = F.log_softmax(l, dim=0)
        losses.append(-(t * log_p).sum())
    return torch.stack(losses).mean()

seed = int(config["model"]["initialization_seed"])
torch.manual_seed(seed)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(seed)

model = DeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0).to(device)
param_count = sum(p.numel() for p in model.parameters())
print(f"Built DeltaEntityMixer: {param_count:,} parameters (vs baseline {949060:,} params, +{param_count-949060} params)", flush=True)

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

print(f"Starting Experiment D: {epochs} epochs of Delta Action Feature Policy-Only (wd=1e-4, lr=3e-4 cosine)...", flush=True)
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

exp_a_path = Path("benchmarks/m25-recovery-exp-a.result.json")
exp_a_data = json.loads(exp_a_path.read_text(encoding="utf-8")) if exp_a_path.exists() else {}

out_payload = {
    "experiment": "M25_RECOVERY_EXP_D_ACTION_DELTA_FEATURES",
    "model": {
        "architecture": "delta_entity_mixer",
        "action_features": ENHANCED_ACTION_FEATURES,
        "hidden_dim": 192,
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
    "comparison_vs_control_exp_a": {
        "control_action_features": 36,
        "control_best_epoch": exp_a_data.get("best_epoch"),
        "control_val_ce": exp_a_data.get("best_checkpoint_val", {}).get("ce"),
        "control_val_excess_ce": exp_a_data.get("best_checkpoint_val", {}).get("excess_ce"),
        "control_val_top1": exp_a_data.get("best_checkpoint_val", {}).get("top1"),
        "delta_val_ce": final_val["ce"],
        "delta_val_excess_ce": final_val["excess_ce"],
        "delta_val_top1": final_val["top1"],
        "val_excess_ce_delta": final_val["excess_ce"] - exp_a_data.get("best_checkpoint_val", {}).get("excess_ce", 0.0),
        "val_top1_delta": final_val["top1"] - exp_a_data.get("best_checkpoint_val", {}).get("top1", 0.0),
        "val_ce_impr_bps_delta": final_val["impr_bps"] - exp_a_data.get("best_checkpoint_val", {}).get("impr_bps", 0),
    },
    "history": history,
}

out_path = Path("benchmarks/m25-recovery-exp-d.result.json")
out_path.write_text(json.dumps(out_payload, indent=2) + "\n", encoding="utf-8")
print(f"COMPLETE: Delta Action Best Epoch {best_epoch}, Val CE {final_val['ce']:.4f} (Exc {final_val['excess_ce']:+.4f}), Val Top1 {final_val['top1']*100:.2f}%, Train CE {final_train['ce']:.4f}, Train Top1 {final_train['top1']*100:.2f}%", flush=True)
