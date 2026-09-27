"""M50 Semantic Card-Entity SE-ResNet Dueling Q-Network (Mortal Step 3).

Key Architectural Enhancements:
1. Shared Card-Entity Encoder (Mortal-style weight sharing across card slots):
   - Rather than isolated disjoint weights for slot 0, slot 1, slot 2, slot 3,
     all 12 market cards share a single CardEncoder MLP:
       card_feat[12] -> Linear(12, 64) -> LayerNorm -> Mish -> Linear(64, 64) -> Mish
   - All 3 reserved cards share a ResCardEncoder:
       res_feat[16] -> Linear(16, 64) -> LayerNorm -> Mish -> Linear(64, 64) -> Mish
2. Permutation-Invariant Tier Poolings:
   - Within each tier (4 cards), computes mean_pool and max_pool.
   - Provides strict permutation invariance across slots within a tier:
     if cards swap slots, tier-level summary features remain perfectly stable!
3. SE-ResNet Channel Attention:
   - Deep residual blocks with SE gating and Mish non-linearity.
4. Dueling Q Architecture:
   - Q_steps(s, a) = V_steps(s) + (A_steps(s, a) - mean_a'(A_steps(s, a'))).
5. Critic Stop-Gradient:
   - val_head(state_h.detach()).
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

REPO_ROOT = Path("E:/AUbuntuProject/project/splendor")
DATA_DIR = REPO_ROOT / "local-artifacts" / "m50-semantic-dataset-v1"
RUN_DIR = REPO_ROOT / "local-artifacts" / "m50-semantic-entity-q-run"

OBS_DIM = 368
ACT_DIM = 48
STEPS_NORM = 20.0


class SEBlock(nn.Module):
    def __init__(self, dim: int, reduction: int = 4):
        super().__init__()
        mid = max(16, dim // reduction)
        self.fc = nn.Sequential(
            nn.Linear(dim, mid),
            nn.Mish(),
            nn.Linear(mid, dim),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        scale = self.fc(x)
        return x * scale


class SEResBlock(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.ln1 = nn.LayerNorm(dim)
        self.fc1 = nn.Linear(dim, dim)
        self.ln2 = nn.LayerNorm(dim)
        self.fc2 = nn.Linear(dim, dim)
        self.se = SEBlock(dim)
        self.act = nn.Mish()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = x
        h = self.act(self.fc1(self.ln1(x)))
        h = self.fc2(self.ln2(h))
        h = self.se(h)
        return self.act(residual + h)


class CardEntityBackbone(nn.Module):
    def __init__(self, hidden_dim: int = 256):
        super().__init__()
        # Shared Card Encoder for all 12 market cards
        self.card_encoder = nn.Sequential(
            nn.Linear(12, 64),
            nn.LayerNorm(64),
            nn.Mish(),
            nn.Linear(64, 64),
            nn.Mish(),
        )
        # Shared Reserved Card Encoder (16 -> 64)
        self.res_encoder = nn.Sequential(
            nn.Linear(16, 64),
            nn.LayerNorm(64),
            nn.Mish(),
            nn.Linear(64, 64),
            nn.Mish(),
        )
        # Context Encoder: non-card features (21 + 27 + 128 = 176 dims)
        self.context_encoder = nn.Sequential(
            nn.Linear(176, 128),
            nn.LayerNorm(128),
            nn.Mish(),
        )
        # Fusion projection:
        # Context (128) + 4 Tiers * (64 mean + 64 max) + 15 cards * 64 = 128 + 512 + 960 = 1600 dims
        self.fusion = nn.Sequential(
            nn.Linear(128 + 128 * 4 + 15 * 64, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.Mish(),
        )

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        B = obs.shape[0]
        header = obs[:, 0:21]
        t1_raw = obs[:, 21:69].reshape(B * 4, 12)
        t2_raw = obs[:, 69:117].reshape(B * 4, 12)
        t3_raw = obs[:, 117:165].reshape(B * 4, 12)
        middle = obs[:, 165:192]
        players = obs[:, 192:320]
        res_raw = obs[:, 320:368].reshape(B * 3, 16)

        # 1. Context embedding
        context_raw = torch.cat([header, middle, players], dim=-1)
        context_h = self.context_encoder(context_raw)

        # 2. Shared Card Entity encoding
        t1_cards = self.card_encoder(t1_raw).reshape(B, 4, 64)
        t2_cards = self.card_encoder(t2_raw).reshape(B, 4, 64)
        t3_cards = self.card_encoder(t3_raw).reshape(B, 4, 64)
        res_cards = self.res_encoder(res_raw).reshape(B, 3, 64)

        # 3. Permutation-invariant tier poolings
        t1_pool = torch.cat([t1_cards.mean(dim=1), t1_cards.max(dim=1)[0]], dim=-1)
        t2_pool = torch.cat([t2_cards.mean(dim=1), t2_cards.max(dim=1)[0]], dim=-1)
        t3_pool = torch.cat([t3_cards.mean(dim=1), t3_cards.max(dim=1)[0]], dim=-1)
        res_pool = torch.cat([res_cards.mean(dim=1), res_cards.max(dim=1)[0]], dim=-1)

        # 4. Flattened card slots
        all_cards_flat = torch.cat([
            t1_cards.reshape(B, 4 * 64),
            t2_cards.reshape(B, 4 * 64),
            t3_cards.reshape(B, 4 * 64),
            res_cards.reshape(B, 3 * 64),
        ], dim=-1)

        # 5. Fusion
        fused = torch.cat([context_h, t1_pool, t2_pool, t3_pool, res_pool, all_cards_flat], dim=-1)
        return self.fusion(fused)


class SemanticCardEntityDuelingQNet(nn.Module):
    def __init__(self, obs_dim: int = OBS_DIM, act_dim: int = ACT_DIM, hidden_dim: int = 256, num_blocks: int = 2):
        super().__init__()
        self.hidden_dim = hidden_dim

        # State Card Entity Backbone
        self.entity_backbone = CardEntityBackbone(hidden_dim=hidden_dim)

        # SE-ResNet Blocks
        self.state_res_blocks = nn.ModuleList([
            SEResBlock(hidden_dim) for _ in range(num_blocks)
        ])

        # Action Encoder: 48 -> hidden_dim
        self.action_net = nn.Sequential(
            nn.Linear(act_dim, 128),
            nn.LayerNorm(128),
            nn.Mish(),
            nn.Linear(128, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.Mish(),
        )

        # Stream 1: State Value Stream V_steps(s)
        self.v_head = nn.Sequential(
            nn.Linear(hidden_dim, 128),
            nn.Mish(),
            nn.Linear(128, 1),
        )

        # Stream 2: Action Advantage Stream A_steps(s, a)
        self.adv_head = nn.Sequential(
            nn.Linear(hidden_dim * 2 + act_dim, 128),
            nn.Mish(),
            nn.Linear(128, 64),
            nn.Mish(),
            nn.Linear(64, 1),
        )

        # Critic Head with detach(): Win probability logit
        self.val_head = nn.Sequential(
            nn.Linear(hidden_dim, 128),
            nn.Mish(),
            nn.Linear(128, 1),
        )

    def forward(
        self,
        obs: torch.Tensor,
        actions: torch.Tensor,
        parent_idx: torch.Tensor,
        lengths: list[int],
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        # Card Entity State Backbone
        h = self.entity_backbone(obs)
        for block in self.state_res_blocks:
            h = block(h)
        state_h = h

        # Mortal Critic Stop-Gradient: state_h.detach()
        val_logits = self.val_head(state_h.detach()).squeeze(-1)

        # Value Stream
        v_steps_norm = F.softplus(self.v_head(state_h).squeeze(-1))
        v_steps = v_steps_norm * STEPS_NORM
        v_expanded = v_steps[parent_idx]

        # Advantage Stream
        act_h = self.action_net(actions)
        state_expanded = state_h[parent_idx]
        joint = torch.cat([state_expanded, act_h, actions], dim=-1)
        adv = self.adv_head(joint).squeeze(-1)

        # Dueling Aggregation
        adv_splits = torch.split(adv, lengths)
        mean_adv_list = [split.mean() for split in adv_splits]
        mean_adv_per_state = torch.stack(mean_adv_list)
        mean_adv_expanded = mean_adv_per_state[parent_idx]

        q_steps = v_expanded + (adv - mean_adv_expanded)

        return q_steps, val_logits, v_steps


class SemanticDataset:
    def __init__(self, split_dir: Path):
        self.obs = np.memmap(split_dir / "obs.f32", dtype="<f4", mode="r").reshape(-1, OBS_DIM)
        self.actions = np.memmap(split_dir / "actions.f32", dtype="<f4", mode="r").reshape(-1, ACT_DIM)
        self.action_offsets = np.memmap(split_dir / "action_offsets.u64", dtype="<u8", mode="r")
        self.chosen_actions = np.memmap(split_dir / "chosen_action.u32", dtype="<u4", mode="r")
        self.values = np.memmap(split_dir / "values.f32", dtype="<f4", mode="r").reshape(-1, 3)

        self.count = len(self.obs)
        assert len(self.action_offsets) == self.count + 1

    def get_batch(
        self, indices: np.ndarray, device: torch.device
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, list[int], torch.Tensor, torch.Tensor, torch.Tensor]:
        batch_obs = torch.from_numpy(np.array(self.obs[indices], copy=True)).to(device)
        batch_won = torch.from_numpy(np.array(self.values[indices, 0], copy=True)).to(device)
        batch_steps = torch.from_numpy(np.array(self.values[indices, 2], copy=True)).to(device)

        actions_list = []
        parent_idx_list = []
        lengths = []
        chosen_global = []

        total_actions_so_far = 0
        for local_b_idx, i in enumerate(indices):
            start = self.action_offsets[i]
            end = self.action_offsets[i + 1]
            act_slice = np.array(self.actions[start:end], copy=True)
            k = len(act_slice)

            actions_list.append(act_slice)
            parent_idx_list.append(np.full(k, local_b_idx, dtype=np.int64))
            lengths.append(k)

            c = int(self.chosen_actions[i])
            chosen_global.append(total_actions_so_far + c)
            total_actions_so_far += k

        flat_actions = torch.from_numpy(np.concatenate(actions_list, axis=0)).to(device)
        flat_parents = torch.from_numpy(np.concatenate(parent_idx_list, axis=0)).to(device)
        chosen_indices = torch.tensor(chosen_global, dtype=torch.long, device=device)

        return batch_obs, flat_actions, flat_parents, lengths, chosen_indices, batch_won, batch_steps


def evaluate(
    model: SemanticCardEntityDuelingQNet,
    dataset: SemanticDataset,
    device: torch.device,
    batch_size: int = 512,
) -> dict[str, float]:
    model.eval()
    total = dataset.count
    indices = np.arange(total)

    total_q_mae = 0.0
    total_v_mae = 0.0
    total_val_acc = 0.0
    total_top1 = 0.0

    with torch.no_grad():
        for i in range(0, total, batch_size):
            b_idx = indices[i : min(i + batch_size, total)]
            obs, actions, parent_idx, lengths, chosen_global, won, steps_15 = dataset.get_batch(b_idx, device)

            q_steps, val_logits, v_steps = model(obs, actions, parent_idx, lengths)
            chosen_q = q_steps[chosen_global]

            q_mae = (chosen_q - steps_15).abs().mean()
            v_mae = (v_steps - steps_15).abs().mean()
            val_acc = ((val_logits > 0.0) == (won > 0.5)).float().mean()

            start = 0
            correct = 0
            for b_i, k in enumerate(lengths):
                end = start + k
                sub_q = q_steps[start:end]
                c_idx = chosen_global[b_i] - start
                if sub_q[c_idx] <= sub_q.min() + 1e-4:
                    correct += 1
                start = end

            b_len = len(b_idx)
            total_q_mae += q_mae.item() * b_len
            total_v_mae += v_mae.item() * b_len
            total_val_acc += val_acc.item() * b_len
            total_top1 += correct

    return {
        "q_mae": total_q_mae / total,
        "v_mae": total_v_mae / total,
        "val_acc": total_val_acc / total,
        "min_step_top1": total_top1 / total,
    }


def train_semantic_entity_q(
    data_dir: Path = DATA_DIR,
    out_dir: Path = RUN_DIR,
    hidden_dim: int = 256,
    num_blocks: int = 2,
    epochs: int = 6,
    batch_size: int = 512,
    lr: float = 3e-4,
    seed: int = 50000001,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    np.random.seed(seed)

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"M50 Semantic Card-Entity SE-ResNet Dueling Q (Mortal Step 3): device={device}, hidden_dim={hidden_dim}, blocks={num_blocks}")
    print("Shared Card Entity Encoder + Tier Permutation Invariance + SE-ResNet + Dueling Q + Critic detach()")

    train_data = SemanticDataset(data_dir / "train")
    val_data = SemanticDataset(data_dir / "val")
    print(f"Loaded: train={train_data.count} steps, val={val_data.count} steps")

    model = SemanticCardEntityDuelingQNet(hidden_dim=hidden_dim, num_blocks=num_blocks).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    out_dir.mkdir(parents=True, exist_ok=True)

    val_0 = evaluate(model, val_data, device)
    print(f"Epoch 0 (Untrained Baseline): Val Q MAE={val_0['q_mae']:.2f} turns, V MAE={val_0['v_mae']:.2f}, Min-Step Match={val_0['min_step_top1']*100:.2f}%")

    best_mae = 999.0
    best_epoch = 1
    history = []

    t_start = time.perf_counter()
    indices = np.arange(train_data.count)

    for epoch in range(1, epochs + 1):
        t0 = time.perf_counter()
        model.train()
        np.random.shuffle(indices)

        train_loss_sum = 0.0
        train_mae_sum = 0.0

        for i in range(0, train_data.count, batch_size):
            b_idx = indices[i : min(i + batch_size, train_data.count)]
            obs, actions, parent_idx, lengths, chosen_global, won, steps_15 = train_data.get_batch(b_idx, device)

            optimizer.zero_grad()
            q_steps, val_logits, v_steps = model(obs, actions, parent_idx, lengths)

            chosen_q = q_steps[chosen_global]

            # 1. State Value calibration: V(s) ~ y_steps
            loss_v_steps = F.smooth_l1_loss(v_steps / STEPS_NORM, steps_15 / STEPS_NORM)

            # 2. Chosen Action Q calibration: Q(s, a*) ~ y_steps
            loss_q_calib = F.smooth_l1_loss(chosen_q / STEPS_NORM, steps_15 / STEPS_NORM)

            # 3. Margin Ranking loss: other actions shouldn't take fewer steps than the winning action!
            chosen_expanded = chosen_q[parent_idx]
            margin_violation = F.relu((chosen_expanded - q_steps) / STEPS_NORM + 0.02)
            loss_margin = margin_violation.mean()

            # 4. Critic Value loss: BCE (gradients stopped from state_net by detach)
            loss_v = F.binary_cross_entropy_with_logits(val_logits, won)

            total_loss = 0.5 * loss_v_steps + 0.5 * loss_q_calib + 0.5 * loss_margin + 0.2 * loss_v
            total_loss.backward()

            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            mae = (chosen_q - steps_15).abs().mean()
            b_len = len(b_idx)
            train_loss_sum += total_loss.item() * b_len
            train_mae_sum += mae.item() * b_len

        scheduler.step()
        epoch_sec = time.perf_counter() - t0

        val_metrics = evaluate(model, val_data, device)
        train_mae = train_mae_sum / train_data.count

        row = {
            "epoch": epoch,
            "train_mae": train_mae,
            "val_q_mae": val_metrics["q_mae"],
            "val_v_mae": val_metrics["v_mae"],
            "val_min_step_top1": val_metrics["min_step_top1"],
            "epoch_seconds": epoch_sec,
        }
        history.append(row)

        is_best = val_metrics["q_mae"] < best_mae
        if is_best:
            best_mae = val_metrics["q_mae"]
            best_epoch = epoch
            torch.save(model.state_dict(), out_dir / "best_model.pt")

        torch.save(model.state_dict(), out_dir / "latest_model.pt")

        print(
            f"Epoch {epoch:2d}/{epochs:2d} ({epoch_sec:.2f}s) | "
            f"Q MAE: Train={train_mae:.2f} turns, Val={val_metrics['q_mae']:.2f} (V MAE={val_metrics['v_mae']:.2f}) | "
            f"Min-Step Match={val_metrics['min_step_top1']*100:.1f}% {'*' if is_best else ''}"
        )

    total_sec = time.perf_counter() - t_start
    print(f"\nTraining complete in {total_sec:.2f}s. Best Epoch {best_epoch} with Val Q MAE: {best_mae:.2f} turns")

    # Export weights JSON for Rust agent
    ckpt = torch.load(out_dir / "best_model.pt", weights_only=True)
    weights_json = {k: v.cpu().numpy().tolist() for k, v in ckpt.items()}
    with open(out_dir / "semantic_entity_q_weights.json", "w", encoding="utf-8") as f:
        json.dump(weights_json, f)
    print(f"Exported {out_dir / 'semantic_entity_q_weights.json'}")

    return history


def main():
    parser = argparse.ArgumentParser(description="M50 Semantic Card-Entity SE-ResNet Dueling Q Training")
    parser.add_argument("--data-dir", type=str, default=str(DATA_DIR))
    parser.add_argument("--out-dir", type=str, default=str(RUN_DIR))
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--num-blocks", type=int, default=2)
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=3e-4)
    args = parser.parse_args()

    train_semantic_entity_q(
        data_dir=Path(args.data_dir),
        out_dir=Path(args.out_dir),
        hidden_dim=args.hidden_dim,
        num_blocks=args.num_blocks,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
    )


if __name__ == "__main__":
    main()
