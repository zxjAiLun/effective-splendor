"""M50 Mortal-Aligned Actor-Critic Network (Mortal Step 4).

Key Architectural Enhancements:
1. Mortal-Aligned Actor Head (Policy Advantage Stream, argmax selection):
   - Directly maps board state and 56-dim action features to policy logits:
       A(s, a) = AdvNet([state_h, act_h, act_raw])
   - Action selection: argmax_a A(s, a) (higher is better, standard RL convention!)
   - Supervised on winning trajectories via Segmented Log-Softmax Cross-Entropy:
       loss_pi = (logsumexp(A(s, .)) - A(s, a*)).mean()
   - Avoids the vanishing gradient and AdamW weight decay collapse of min-step formulations!
2. Balanced Critic Head with detach():
   - Trained on the full dual-outcome dataset (86k wins, 86k losses) via BCE.
   - Learns pristine, calibrated win probabilities without bias.
   - Gradient detached from state backbone (Mortal Critic stop-gradient).
3. Auxiliary Physical Steps Head:
   - Predicts expected remaining turns to 15 VP for auxiliary representation learning.
4. Card-Entity Permutation Invariance + SE-ResNet Backbone + Mish.
5. Mortal Gradient Accumulation: effective_batch = 2,048.
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
DATA_DIR = REPO_ROOT / "local-artifacts" / "aran-v03-full-dataset"
RUN_DIR = REPO_ROOT / "local-artifacts" / "aran-v03-actor-critic-run"

OBS_DIM = 368
ACT_DIM = 56
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
        self.card_encoder = nn.Sequential(
            nn.Linear(12, 64),
            nn.LayerNorm(64),
            nn.Mish(),
            nn.Linear(64, 64),
            nn.Mish(),
        )
        self.res_encoder = nn.Sequential(
            nn.Linear(16, 64),
            nn.LayerNorm(64),
            nn.Mish(),
            nn.Linear(64, 64),
            nn.Mish(),
        )
        self.context_encoder = nn.Sequential(
            nn.Linear(176, 128),
            nn.LayerNorm(128),
            nn.Mish(),
        )
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

        context_raw = torch.cat([header, middle, players], dim=-1)
        context_h = self.context_encoder(context_raw)

        t1_cards = self.card_encoder(t1_raw).reshape(B, 4, 64)
        t2_cards = self.card_encoder(t2_raw).reshape(B, 4, 64)
        t3_cards = self.card_encoder(t3_raw).reshape(B, 4, 64)
        res_cards = self.res_encoder(res_raw).reshape(B, 3, 64)

        t1_pool = torch.cat([t1_cards.mean(dim=1), t1_cards.max(dim=1)[0]], dim=-1)
        t2_pool = torch.cat([t2_cards.mean(dim=1), t2_cards.max(dim=1)[0]], dim=-1)
        t3_pool = torch.cat([t3_cards.mean(dim=1), t3_cards.max(dim=1)[0]], dim=-1)
        res_pool = torch.cat([res_cards.mean(dim=1), res_cards.max(dim=1)[0]], dim=-1)

        all_cards_flat = torch.cat([
            t1_cards.reshape(B, 4 * 64),
            t2_cards.reshape(B, 4 * 64),
            t3_cards.reshape(B, 4 * 64),
            res_cards.reshape(B, 3 * 64),
        ], dim=-1)

        fused = torch.cat([context_h, t1_pool, t2_pool, t3_pool, res_pool, all_cards_flat], dim=-1)
        return self.fusion(fused)


class MortalActorCriticNet(nn.Module):
    def __init__(self, obs_dim: int = OBS_DIM, act_dim: int = ACT_DIM, hidden_dim: int = 256, num_blocks: int = 2):
        super().__init__()
        self.hidden_dim = hidden_dim

        # 1. State Backbone
        self.entity_backbone = CardEntityBackbone(hidden_dim=hidden_dim)
        self.state_res_blocks = nn.ModuleList([
            SEResBlock(hidden_dim) for _ in range(num_blocks)
        ])

        # 2. Action Semantic Encoder: 56 -> hidden_dim
        self.action_net = nn.Sequential(
            nn.Linear(act_dim, 128),
            nn.LayerNorm(128),
            nn.Mish(),
            nn.Linear(128, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.Mish(),
        )

        # 3. Actor Head: Policy Advantage Stream A(s, a) (higher is better!)
        self.adv_head = nn.Sequential(
            nn.Linear(hidden_dim * 2 + act_dim, 128),
            nn.Mish(),
            nn.Linear(128, 64),
            nn.Mish(),
            nn.Linear(64, 1),
        )

        # 4. Critic Head: Win Probability Logit from detached state_h
        self.val_head = nn.Sequential(
            nn.Linear(hidden_dim, 128),
            nn.Mish(),
            nn.Linear(128, 1),
        )

        # 5. Auxiliary Physical Steps Head: V_steps(s)
        self.v_steps_head = nn.Sequential(
            nn.Linear(hidden_dim, 128),
            nn.Mish(),
            nn.Linear(128, 1),
        )

    def forward(
        self,
        obs: torch.Tensor,
        actions: torch.Tensor,
        parent_idx: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        obs: [B, 368]
        actions: [M, 56]
        parent_idx: [M]
        Returns:
          adv_logits: [M] (policy advantage logits, higher is better!)
          val_logits: [B] (win prob logits from detached state_h)
          v_steps: [B] (predicted physical turns to 15 VP)
        """
        h = self.entity_backbone(obs)
        for block in self.state_res_blocks:
            h = block(h)
        state_h = h

        # Critic Head with detach()
        val_logits = self.val_head(state_h.detach()).squeeze(-1)

        # Auxiliary Steps Head
        v_steps_norm = F.softplus(self.v_steps_head(state_h).squeeze(-1))
        v_steps = v_steps_norm * STEPS_NORM

        # Actor Head
        act_h = self.action_net(actions)
        state_expanded = state_h[parent_idx]
        joint = torch.cat([state_expanded, act_h, actions], dim=-1)
        adv_logits = self.adv_head(joint).squeeze(-1)

        return adv_logits, val_logits, v_steps


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


def segmented_logsumexp(scores: torch.Tensor, lengths: list[int]) -> tuple[torch.Tensor, torch.Tensor]:
    splits = torch.split(scores, lengths)
    lse = torch.stack([s.logsumexp(dim=0) for s in splits])
    max_vals = torch.stack([s.max(dim=0)[0] for s in splits])
    return lse, max_vals


def evaluate(
    model: MortalActorCriticNet,
    dataset: SemanticDataset,
    device: torch.device,
    batch_size: int = 512,
) -> dict[str, float]:
    model.eval()
    total = dataset.count
    indices = np.arange(total)

    total_pi_loss = 0.0
    total_val_acc = 0.0
    total_steps_mae = 0.0
    total_top1 = 0.0

    with torch.no_grad():
        for i in range(0, total, batch_size):
            b_idx = indices[i : min(i + batch_size, total)]
            obs, actions, parent_idx, lengths, chosen_global, won, steps_15 = dataset.get_batch(b_idx, device)

            adv_logits, val_logits, v_steps = model(obs, actions, parent_idx)
            chosen_adv = adv_logits[chosen_global]

            lse, max_vals = segmented_logsumexp(adv_logits, lengths)
            loss_pi = (lse - chosen_adv).mean()

            val_acc = ((val_logits > 0.0) == (won > 0.5)).float().mean()
            steps_mae = (v_steps - steps_15).abs().mean()
            is_top1 = (chosen_adv >= max_vals - 1e-4).float().mean()

            b_len = len(b_idx)
            total_pi_loss += loss_pi.item() * b_len
            total_val_acc += val_acc.item() * b_len
            total_steps_mae += steps_mae.item() * b_len
            total_top1 += is_top1.item() * b_len

    return {
        "pi_loss": total_pi_loss / total,
        "val_acc": total_val_acc / total,
        "steps_mae": total_steps_mae / total,
        "top1_match": total_top1 / total,
    }


def train_mortal_actor_critic(
    data_dir: Path = DATA_DIR,
    out_dir: Path = RUN_DIR,
    hidden_dim: int = 256,
    num_blocks: int = 2,
    epochs: int = 8,
    batch_size: int = 512,
    accumulation_steps: int = 4,
    lr: float = 3e-4,
    pretrained: str = "",
    seed: int = 50000001,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    np.random.seed(seed)

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    effective_batch = batch_size * accumulation_steps
    print(f"Mortal Actor-Critic Network Training: device={device}, hidden_dim={hidden_dim}, act_dim={ACT_DIM}")
    print(f"Effective Batch: {batch_size} x {accumulation_steps} = {effective_batch} decisions")
    print("Mortal Actor Head (Policy Logits, argmax selection) + Balanced Critic (detach) + Aux Steps")

    train_data = SemanticDataset(data_dir / "train")
    val_data = SemanticDataset(data_dir / "val")
    print(f"Loaded: train={train_data.count} steps, val={val_data.count} steps")

    model = MortalActorCriticNet(hidden_dim=hidden_dim, num_blocks=num_blocks).to(device)

    if pretrained and Path(pretrained).exists():
        print(f"Loading pretrained weights from {pretrained}...")
        ckpt = torch.load(pretrained, weights_only=True, map_location=device)
        model_dict = model.state_dict()
        filtered_ckpt = {
            k: v for k, v in ckpt.items()
            if k in model_dict and model_dict[k].shape == v.shape
        }
        model_dict.update(filtered_ckpt)
        model.load_state_dict(model_dict)
        print(f"Transferred {len(filtered_ckpt)} tensors successfully from {pretrained}!")

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    out_dir.mkdir(parents=True, exist_ok=True)

    val_0 = evaluate(model, val_data, device)
    print(f"Epoch 0 (Baseline): Val Top-1 Match={val_0['top1_match']*100:.2f}%, Critic Acc={val_0['val_acc']*100:.2f}%, Steps MAE={val_0['steps_mae']:.2f}")

    best_match = 0.0
    best_epoch = 1
    history = []

    t_start = time.perf_counter()
    indices = np.arange(train_data.count)

    for epoch in range(1, epochs + 1):
        t0 = time.perf_counter()
        model.train()
        np.random.shuffle(indices)

        train_loss_sum = 0.0
        train_top1_sum = 0.0
        optimizer.zero_grad()

        for step_idx, i in enumerate(range(0, train_data.count, batch_size)):
            b_idx = indices[i : min(i + batch_size, train_data.count)]
            obs, actions, parent_idx, lengths, chosen_global, won, steps_15 = train_data.get_batch(b_idx, device)

            adv_logits, val_logits, v_steps = model(obs, actions, parent_idx)

            chosen_adv = adv_logits[chosen_global]
            lse, max_vals = segmented_logsumexp(adv_logits, lengths)

            # 1. Actor Head Policy Loss (on winning decisions):
            # Focus imitation of policy choices on moves that led to victory!
            win_mask = (won > 0.5)
            if win_mask.sum() > 0:
                loss_pi = (lse[win_mask] - chosen_adv[win_mask]).mean()
            else:
                loss_pi = (lse - chosen_adv).mean()

            # 2. Balanced Critic Value Loss (on ALL positions: wins & losses):
            loss_critic = F.binary_cross_entropy_with_logits(val_logits, won)

            # 3. Auxiliary Steps Head Loss (Smooth L1):
            loss_steps = F.smooth_l1_loss(v_steps[win_mask] / STEPS_NORM, steps_15[win_mask] / STEPS_NORM)

            total_loss = loss_pi + 0.5 * loss_critic + 0.25 * loss_steps

            (total_loss / accumulation_steps).backward()

            if (step_idx + 1) % accumulation_steps == 0 or (i + batch_size >= train_data.count):
                nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()
                optimizer.zero_grad()

            is_top1 = (chosen_adv >= max_vals - 1e-4).float().mean()
            b_len = len(b_idx)
            train_loss_sum += total_loss.item() * b_len
            train_top1_sum += is_top1.item() * b_len

        scheduler.step()
        epoch_sec = time.perf_counter() - t0

        val_metrics = evaluate(model, val_data, device)
        train_top1 = train_top1_sum / train_data.count

        row = {
            "epoch": epoch,
            "train_top1": train_top1,
            "val_top1": val_metrics["top1_match"],
            "val_critic_acc": val_metrics["val_acc"],
            "val_steps_mae": val_metrics["steps_mae"],
            "epoch_seconds": epoch_sec,
        }
        history.append(row)

        is_best = val_metrics["top1_match"] > best_match
        if is_best:
            best_match = val_metrics["top1_match"]
            best_epoch = epoch
            torch.save(model.state_dict(), out_dir / "best_model.pt")

        torch.save(model.state_dict(), out_dir / "latest_model.pt")

        print(
            f"Epoch {epoch:2d}/{epochs:2d} ({epoch_sec:.2f}s) | "
            f"Actor Top-1: Train={train_top1*100:.1f}%, Val={val_metrics['top1_match']*100:.2f}% | "
            f"Critic Acc={val_metrics['val_acc']*100:.1f}% | Steps MAE={val_metrics['steps_mae']:.2f} {'*' if is_best else ''}"
        )

    total_sec = time.perf_counter() - t_start
    print(f"\nTraining complete in {total_sec:.2f}s. Best Epoch {best_epoch} with Val Top-1: {best_match*100:.2f}%")

    # Export weights JSON for Rust agent (flagging is_argmax: true)
    ckpt = torch.load(out_dir / "best_model.pt", weights_only=True)
    weights_json = {k: v.cpu().numpy().tolist() for k, v in ckpt.items()}
    weights_json["is_argmax"] = True
    with open(out_dir / "mortal_actor_critic_weights.json", "w", encoding="utf-8") as f:
        json.dump(weights_json, f)
    print(f"Exported {out_dir / 'mortal_actor_critic_weights.json'}")

    return history


def main():
    parser = argparse.ArgumentParser(description="M50 Mortal-Aligned Actor-Critic Training")
    parser.add_argument("--data-dir", type=str, default=str(DATA_DIR))
    parser.add_argument("--out-dir", type=str, default=str(RUN_DIR))
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--num-blocks", type=int, default=2)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--accumulation-steps", type=int, default=4)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--pretrained", type=str, default="")
    args = parser.parse_args()

    train_mortal_actor_critic(
        data_dir=Path(args.data_dir),
        out_dir=Path(args.out_dir),
        hidden_dim=args.hidden_dim,
        num_blocks=args.num_blocks,
        epochs=args.epochs,
        batch_size=args.batch_size,
        accumulation_steps=args.accumulation_steps,
        lr=args.lr,
        pretrained=args.pretrained,
    )


if __name__ == "__main__":
    main()
