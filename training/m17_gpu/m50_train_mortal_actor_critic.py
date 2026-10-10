"""M50 Mortal-Aligned Actor-Critic Network (Mortal Step 4).

Key Architectural Enhancements:
1. Mortal-Aligned Actor Head (Policy Advantage Stream, argmax selection):
   - Directly maps board state and 56/72/97-dim action features to policy logits:
       A(s, a) = AdvNet([state_h, act_h, act_raw])
   - Action selection: argmax_a A(s, a) (higher is better, standard RL convention!)
   - Legacy supervises winning trajectories; teacher-bc supervises every valid
     teacher label via Segmented Log-Softmax Cross-Entropy, with no auxiliary loss:
       loss_pi = (logsumexp(A(s, .)) - A(s, a*)).mean()
   - Policy logits are imitation scores, not calibrated action-value advantages.
2. Outcome Critic Head:
   - Trained on the full dual-outcome dataset via BCE.
   - Detached by default; --critic-backbone-grad enables shared representation learning.
3. Auxiliary Physical Steps Head:
   - Predicts expected remaining turns to 15 VP for auxiliary representation learning.
4. Shared Card Encoders + Tier Pooling/Flatten + SE-ResNet Backbone + Mish.
5. Mortal Gradient Accumulation: effective_batch = 2,048.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import time
from collections.abc import Mapping
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
ACTION_REPRESENTATIONS = {
    56: "semantic-v1",
    72: "semantic-reserve-target-v1",
    97: "semantic-full-target-v1",
}
RESERVE_TARGET_INPUT_WEIGHTS = ("action_net.0.weight", "adv_head.0.weight")


def validate_action_schema(act_dim: int, action_representation: str | None = None) -> str:
    """Only the historical 56-wide manifest may omit its schema name."""
    if type(act_dim) is not int or act_dim not in ACTION_REPRESENTATIONS:
        raise ValueError(f"Unsupported action_width/action_dim: {act_dim!r}")
    if action_representation is None and act_dim == ACT_DIM:
        action_representation = ACTION_REPRESENTATIONS[ACT_DIM]
    expected = ACTION_REPRESENTATIONS[act_dim]
    if action_representation != expected:
        raise ValueError(
            f"action_representation={action_representation!r} does not match "
            f"action_width/action_dim={act_dim} (expected {expected!r})"
        )
    return expected


def load_action_schema(data_dir: Path) -> tuple[int, str]:
    """Read the extractor's existing observation_width/action_width fields."""
    manifest = json.loads((Path(data_dir) / "manifest.json").read_text(encoding="utf-8"))
    if type(manifest.get("observation_width")) is not int or manifest["observation_width"] != OBS_DIM:
        raise ValueError(f"Expected observation_width={OBS_DIM}")
    act_dim = manifest.get("action_width")
    schema = validate_action_schema(act_dim, manifest.get("action_representation"))
    return act_dim, schema


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
    def __init__(self, obs_dim: int = OBS_DIM, act_dim: int = ACT_DIM, hidden_dim: int = 256, num_blocks: int = 2, critic_backbone_grad: bool = False, action_representation: str | None = None):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.act_dim = act_dim
        self.action_representation = validate_action_schema(
            act_dim, ACTION_REPRESENTATIONS.get(act_dim) if action_representation is None else action_representation,
        )
        self.critic_backbone_grad = critic_backbone_grad

        # 1. State Backbone
        self.entity_backbone = CardEntityBackbone(hidden_dim=hidden_dim)
        self.state_res_blocks = nn.ModuleList([
            SEResBlock(hidden_dim) for _ in range(num_blocks)
        ])

        # 2. Action Semantic Encoder: act_dim -> hidden_dim
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

        # 4. Critic Head: optional outcome gradients into the shared backbone.
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
        actions: [M, act_dim]
        parent_idx: [M]
        Returns:
          adv_logits: [M] (policy advantage logits, higher is better!)
          val_logits: [B] (win prob logits; gradient routing is configurable)
          v_steps: [B] (predicted physical turns to 15 VP)
        """
        h = self.entity_backbone(obs)
        for block in self.state_res_blocks:
            h = block(h)
        state_h = h

        # Preserve the v0.2.2 default; opt in to outcome representation learning.
        critic_h = state_h if self.critic_backbone_grad else state_h.detach()
        val_logits = self.val_head(critic_h).squeeze(-1)

        # Auxiliary Steps Head
        v_steps_norm = F.softplus(self.v_steps_head(state_h).squeeze(-1))
        v_steps = v_steps_norm * STEPS_NORM

        # Actor Head
        act_h = self.action_net(actions)
        state_expanded = state_h[parent_idx]
        joint = torch.cat([state_expanded, act_h, actions], dim=-1)
        adv_logits = self.adv_head(joint).squeeze(-1)

        return adv_logits, val_logits, v_steps


def migrate_state_dict(
    model: MortalActorCriticNet,
    state_dict: Mapping[str, torch.Tensor],
    *,
    source_action_representation: str | None = None,
) -> tuple[dict[str, torch.Tensor], list[dict[str, Any]]]:
    """Validate every tensor; allow only 56 -> 72 or 72 -> 97 zero-suffix migration.

    Bare state_dict checkpoints have no metadata: infer their schema from the
    action input width, then check every other key, shape and dtype. Callers with
    external schema metadata can supply it to reject a mislabeled checkpoint.
    This helper does not mutate either the source state_dict or the model.
    """
    target = model.state_dict()
    if not isinstance(state_dict, Mapping):
        raise TypeError("Expected a bare tensor state_dict")
    missing = sorted(set(target) - set(state_dict))
    unexpected = sorted(set(state_dict) - set(target))
    if missing or unexpected:
        raise ValueError(f"Checkpoint keys differ: missing={missing}, unexpected={unexpected}")
    for name, value in state_dict.items():
        if not isinstance(value, torch.Tensor):
            raise TypeError(f"Checkpoint {name} must be a tensor")
        if value.dtype != target[name].dtype:
            raise ValueError(f"Checkpoint dtype mismatch for {name}: {value.dtype} != {target[name].dtype}")

    action_weight = state_dict["action_net.0.weight"]
    if action_weight.ndim != 2:
        raise ValueError("Checkpoint action_net.0.weight must be a matrix")
    source_dim = action_weight.shape[1]
    validate_action_schema(
        source_dim,
        ACTION_REPRESENTATIONS.get(source_dim) if source_action_representation is None else source_action_representation,
    )
    validate_action_schema(model.act_dim, model.action_representation)
    expanding = (source_dim, model.act_dim) in ((56, 72), (72, 97))
    suffix = model.act_dim - source_dim
    if source_dim != model.act_dim and not expanding:
        raise ValueError(f"Unsupported checkpoint action migration: {source_dim} -> {model.act_dim}")

    migrated = {}
    migrations = []
    for name, expected in target.items():
        value = state_dict[name]
        source_shape = tuple(expected.shape)
        if expanding and name in RESERVE_TARGET_INPUT_WEIGHTS:
            source_shape = (expected.shape[0], expected.shape[1] - suffix)
        if tuple(value.shape) != source_shape:
            raise ValueError(f"Checkpoint shape mismatch for {name}: {tuple(value.shape)} != {source_shape}")
        if expanding and name in RESERVE_TARGET_INPUT_WEIGHTS:
            migrated[name] = torch.cat([value, value.new_zeros((value.shape[0], suffix))], dim=1)
            migrations.append({
                "parameter": name,
                "from_shape": list(value.shape),
                "to_shape": list(expected.shape),
                "zero_suffix_columns": suffix,
            })
        else:
            migrated[name] = value
    return migrated, migrations


def load_pretrained_weights(
    model: MortalActorCriticNet,
    pretrained: str | Path,
    *,
    source_action_representation: str | None = None,
) -> dict[str, Any]:
    """Strictly load a bare checkpoint and return its identity/migration record."""
    path = Path(pretrained)
    payload = path.read_bytes()  # Missing paths must fail, not train from random weights.
    state_dict = torch.load(io.BytesIO(payload), weights_only=True, map_location="cpu")
    migrated, migrations = migrate_state_dict(
        model, state_dict, source_action_representation=source_action_representation,
    )
    model.load_state_dict(migrated, strict=True)
    source_dim = state_dict["action_net.0.weight"].shape[1]
    return {
        "parent_checkpoint": str(path.resolve()),
        "parent_sha256": hashlib.sha256(payload).hexdigest(),
        "parent_action_dim": source_dim,
        "parent_action_representation": ACTION_REPRESENTATIONS[source_dim],
        "migration": migrations,
    }


def export_weights(
    model: MortalActorCriticNet,
    path: str | Path,
    action_representation: str | None = None,
    training_objective: str = "legacy",
) -> None:
    """Export flat Rust-compatible tensors plus explicit action schema identity."""
    validate_policy_objective(training_objective)
    schema = validate_action_schema(
        model.act_dim, model.action_representation if action_representation is None else action_representation,
    )
    weights = {name: value.detach().cpu().tolist() for name, value in model.state_dict().items()}
    weights.update(is_argmax=True, action_representation=schema, action_dim=model.act_dim)
    if training_objective == "teacher-bc":
        weights["training_objective"] = training_objective
    payload = json.dumps(weights, allow_nan=False)
    Path(path).write_text(payload, encoding="utf-8")


def validate_policy_objective(policy_objective: str) -> None:
    if policy_objective not in ("legacy", "teacher-bc"):
        raise ValueError(f"Unsupported policy_objective: {policy_objective!r}")


def selection_improved(policy_objective: str, metrics: dict, best: float) -> bool:
    """Strict comparison preserves the earlier trained epoch on ties."""
    validate_policy_objective(policy_objective)
    return metrics["pi_loss"] < best if policy_objective == "teacher-bc" else metrics["top1_match"] > best


class SemanticDataset:
    def __init__(self, split_dir: Path, policy_objective: str = "legacy"):
        validate_policy_objective(policy_objective)
        self.policy_objective = policy_objective
        self.act_dim, self.action_representation = load_action_schema(split_dir.parent)
        self.obs = np.memmap(split_dir / "obs.f32", dtype="<f4", mode="r").reshape(-1, OBS_DIM)
        self.actions = np.memmap(split_dir / "actions.f32", dtype="<f4", mode="r").reshape(-1, self.act_dim)
        self.action_offsets = np.memmap(split_dir / "action_offsets.u64", dtype="<u8", mode="r")
        self.chosen_actions = np.memmap(split_dir / "chosen_action.u32", dtype="<u4", mode="r")
        self.values = np.memmap(split_dir / "values.f32", dtype="<f4", mode="r").reshape(-1, 3)

        self.count = len(self.obs)
        if (len(self.action_offsets) != self.count + 1 or len(self.chosen_actions) != self.count
                or len(self.values) != self.count):
            raise ValueError("Dataset arrays must align by dataset row")
        if (self.action_offsets[0] != 0 or self.action_offsets[-1] != len(self.actions)
                or np.any(self.action_offsets[1:] <= self.action_offsets[:-1])):
            raise ValueError("Action offsets must span nonempty legal-action segments")
        lengths = self.action_offsets[1:] - self.action_offsets[:-1]
        if np.any(self.chosen_actions >= lengths):
            raise ValueError("chosen_action contains an illegal local action index")

        # Labels are local legal-action indices, one entry per original dataset row.
        # Metadata is a provenance declaration, not proof: the pipeline must audit
        # teacher identity and whole-game split before invoking this trainer.
        metadata = json.loads((split_dir.parent / "manifest.json").read_text(encoding="utf-8"))
        source = metadata.get("policy_label_source", "chosen_action.u32")
        mask_source = metadata.get("policy_mask", "all")
        supervision = metadata.get("policy_supervision")
        if policy_objective == "teacher-bc":
            if supervision not in ("teacher-only", "teacher-query"):
                raise ValueError("teacher-bc requires explicit teacher-only or teacher-query provenance")
            if (metadata.get("policy_row_alignment") != "dataset-row"
                    or "policy_label_source" not in metadata or "policy_mask" not in metadata):
                raise ValueError("Declare policy_label_source, policy_mask and dataset-row alignment")
            if supervision == "teacher-query" and source != "policy_target.u32":
                raise ValueError("teacher-query requires independent policy_target.u32")
        elif (supervision == "teacher-query" or source != "chosen_action.u32" or mask_source != "all"
              or (split_dir / "policy_target.u32").exists() or (split_dir / "policy_mask.u8").exists()):
            raise ValueError("legacy cannot train query/overridden/masked policy supervision")
        if source not in ("chosen_action.u32", "policy_target.u32"):
            raise ValueError("Unknown policy_label_source")
        if mask_source not in ("all", "policy_mask.u8"):
            raise ValueError("Unknown policy_mask")
        for filename, declared in (("policy_target.u32", source == "policy_target.u32"),
                                   ("policy_mask.u8", mask_source == "policy_mask.u8"),
                                   ("policy_group.u8", metadata.get("policy_group") == "policy_group.u8")):
            if (split_dir / filename).exists() and not declared:
                raise ValueError(f"Undeclared policy sidecar: {filename}")
        self.policy_targets = self.chosen_actions if source == "chosen_action.u32" else np.fromfile(split_dir / source, dtype="<u4")
        self.policy_mask = np.ones(self.count, dtype=np.uint8) if mask_source == "all" else np.fromfile(split_dir / mask_source, dtype="u1")
        if len(self.policy_targets) != self.count or len(self.policy_mask) != self.count:
            raise ValueError("Policy labels/mask must align by dataset row")
        if not np.isin(self.policy_mask, [0, 1]).all():
            raise ValueError("policy_mask must contain only 0 or 1")
        if np.any(self.policy_targets[self.policy_mask != 0] >= lengths[self.policy_mask != 0]):
            raise ValueError("Valid policy target must be a legal local action index")
        self.policy_groups = None
        if metadata.get("policy_group") is not None:
            if (metadata["policy_group"] != "policy_group.u8"
                    or metadata.get("policy_group_labels") != {"0": "teacher", "1": "query"}
                    or metadata.get("policy_row_alignment") != "dataset-row"):
                raise ValueError("Declare policy_group.u8, dataset-row alignment and group labels 0=teacher, 1=query")
            self.policy_groups = np.fromfile(split_dir / "policy_group.u8", dtype="u1")
            if len(self.policy_groups) != self.count or not np.isin(self.policy_groups, [0, 1]).all():
                raise ValueError("policy_group must align by dataset row with values 0 or 1")
        self.policy_metadata = {key: metadata.get(key) for key in (
            "policy_supervision", "policy_label_source", "policy_mask", "policy_row_alignment",
            "policy_group", "policy_group_labels",
        )}

    def epoch_indices(self, sampling: str = "shuffle", rng=None) -> np.ndarray:
        """Exactly count valid draws per epoch; never unbounded oversampling.

        Balanced sampling cycles each shuffled group as needed, with at most a
        one-row imbalance. Missing group metadata falls back to ordinary shuffle.
        """
        if sampling not in ("shuffle", "balanced-groups"):
            raise ValueError(f"Unsupported train_sampling: {sampling!r}")
        if sampling != "shuffle" and self.policy_objective != "teacher-bc":
            raise ValueError("balanced-groups sampling is policy-only")
        rng = np.random if rng is None else rng
        valid = np.flatnonzero(self.policy_mask)
        if not len(valid):
            raise ValueError("No valid policy samples")
        if sampling == "shuffle" or self.policy_groups is None:
            draws = [rng.permutation(valid) for _ in range(math.ceil(self.count / len(valid)))]
            return np.concatenate(draws)[:self.count]
        groups = [valid[self.policy_groups[valid] == g] for g in (0, 1)]
        if any(len(group) == 0 for group in groups):
            raise ValueError("balanced-groups requires valid rows in both groups")
        budget = self.count
        samples = []
        for group, needed in zip(groups, ((budget + 1) // 2, budget // 2)):
            while needed:
                draw = rng.permutation(group)[:needed]
                samples.append(draw)
                needed -= len(draw)
        return rng.permutation(np.concatenate(samples))

    def batch_policy_mask(self, indices: np.ndarray, device: torch.device) -> torch.Tensor:
        return torch.as_tensor(self.policy_mask[indices] != 0, device=device)

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

            # Masked rows may hold a sentinel target; use a safe gather index.
            c = int(self.policy_targets[i]) if self.policy_mask[i] else 0
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


def compute_training_loss(
    adv_logits: torch.Tensor, val_logits: torch.Tensor, v_steps: torch.Tensor,
    lengths: list[int], chosen_global: torch.Tensor, won: torch.Tensor,
    steps_15: torch.Tensor, policy_objective: str = "legacy",
    policy_mask: torch.Tensor | None = None,
) -> torch.Tensor | None:
    """None means an empty teacher batch: skip backward AND optimizer update.

    Query targets supervise policy only, never fabricated outcome/steps labels.
    Legacy retains its historical winner-CE (all-row fallback), .5 BCE, .25
    winner-steps loss; a no-winner batch has zero steps loss instead of NaN.
    """
    validate_policy_objective(policy_objective)
    lse, _ = segmented_logsumexp(adv_logits, lengths)
    if policy_objective == "teacher-bc":
        mask = torch.ones_like(won, dtype=torch.bool) if policy_mask is None else policy_mask.bool()
        if not mask.any():
            return None
        return (lse[mask] - adv_logits[chosen_global[mask]]).mean()
    win_mask = won > 0.5
    ce = lse - adv_logits[chosen_global]
    loss_pi = ce[win_mask].mean() if win_mask.any() else ce.mean()
    loss_critic = F.binary_cross_entropy_with_logits(val_logits, won)
    loss_steps = (F.smooth_l1_loss(v_steps[win_mask] / STEPS_NORM, steps_15[win_mask] / STEPS_NORM)
                  if win_mask.any() else v_steps.sum() * 0.0)
    return loss_pi + 0.5 * loss_critic + 0.25 * loss_steps


def evaluate(
    model: MortalActorCriticNet,
    dataset: SemanticDataset,
    device: torch.device,
    batch_size: int = 512,
    policy_objective: str = "legacy",
) -> dict[str, float]:
    validate_policy_objective(policy_objective)
    model.eval()
    indices = np.arange(dataset.count)
    if policy_objective == "teacher-bc":
        indices = indices[dataset.policy_mask != 0]
    total = len(indices)
    if not total:
        raise ValueError("Validation has no valid policy samples")
    totals = {"pi_loss": 0.0, "top1_match": 0.0}
    if policy_objective == "legacy":
        totals.update(val_acc=0.0, steps_mae=0.0)
    with torch.no_grad():
        for i in range(0, total, batch_size):
            b_idx = indices[i:i + batch_size]
            obs, actions, parent_idx, lengths, chosen, won, steps = dataset.get_batch(b_idx, device)
            adv, val, predicted_steps = model(obs, actions, parent_idx)
            lse, maxima = segmented_logsumexp(adv, lengths)
            totals["pi_loss"] += (lse - adv[chosen]).sum().item()
            totals["top1_match"] += (adv[chosen] >= maxima - 1e-4).float().sum().item()
            if policy_objective == "legacy":
                totals["val_acc"] += ((val > 0) == (won > .5)).float().sum().item()
                totals["steps_mae"] += (predicted_steps - steps).abs().sum().item()
    return {key: value / total for key, value in totals.items()}


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
    critic_backbone_grad: bool = False,
    policy_objective: str = "legacy",
    train_sampling: str = "shuffle",
) -> list[dict[str, Any]]:
    validate_policy_objective(policy_objective)
    if train_sampling not in ("shuffle", "balanced-groups"):
        raise ValueError("Unknown train_sampling")
    if train_sampling != "shuffle" and policy_objective != "teacher-bc":
        raise ValueError("balanced-groups sampling is policy-only")
    if batch_size < 1 or accumulation_steps < 1:
        raise ValueError("batch_size and accumulation_steps must be positive")
    if epochs < 1:
        raise ValueError("epochs must be >= 1; epoch 0 is diagnostic only")
    if pretrained and not Path(pretrained).is_file():
        raise FileNotFoundError(f"Pretrained checkpoint not found: {pretrained}")
    # Do not reuse an earlier run's best checkpoint or exported weights on failure.
    for name in ("best_model.pt", "latest_model.pt", "mortal_actor_critic_weights.json", "training-summary.json"):
        if (out_dir / name).exists():
            raise FileExistsError(f"Run output already exists: {out_dir / name}; choose a fresh out_dir")

    torch.manual_seed(seed)
    np.random.seed(seed)

    train_data = SemanticDataset(data_dir / "train", policy_objective)
    val_data = SemanticDataset(data_dir / "val", policy_objective)
    if not train_data.policy_mask.any() or not val_data.policy_mask.any():
        raise ValueError("Train and validation must each contain valid policy samples")
    act_dim = train_data.act_dim
    action_representation = train_data.action_representation
    if (val_data.act_dim, val_data.action_representation) != (act_dim, action_representation):
        raise ValueError("Train and validation action schemas differ")

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    effective_batch = batch_size * accumulation_steps
    print(f"Mortal Actor-Critic Network Training: device={device}, hidden_dim={hidden_dim}, act_dim={act_dim}")
    print(f"Effective Batch: {batch_size} x {accumulation_steps} = {effective_batch} decisions")
    critic_mode = "shared-gradient" if critic_backbone_grad else "detach"
    print(f"Policy objective={policy_objective}; critic routing={critic_mode}; "
          f"auxiliary losses={'enabled' if policy_objective == 'legacy' else 'disabled (not calibrated)'}")
    print(f"Loaded: train={train_data.count} steps, val={val_data.count} steps")

    model = MortalActorCriticNet(
        hidden_dim=hidden_dim, num_blocks=num_blocks, act_dim=act_dim,
        critic_backbone_grad=critic_backbone_grad, action_representation=action_representation,
    ).to(device)

    parent_identity = {
        "parent_checkpoint": None,
        "parent_sha256": None,
        "parent_action_dim": None,
        "parent_action_representation": None,
        "migration": [],
    }
    if pretrained:
        print(f"Loading pretrained weights from {pretrained}...")
        parent_identity = load_pretrained_weights(model, pretrained)
        print(f"Strictly loaded {len(model.state_dict())} tensors; migration={parent_identity['migration']}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    out_dir.mkdir(parents=True, exist_ok=True)

    val_0 = evaluate(model, val_data, device, 512, policy_objective)
    if not all(math.isfinite(value) for value in val_0.values()):
        raise FloatingPointError(f"Non-finite baseline metrics: {val_0}")
    print(f"Epoch 0 (diagnostic only): {val_0}")

    best_score = math.inf if policy_objective == "teacher-bc" else -math.inf
    best_match = None
    best_ce = None
    best_epoch = None
    history = []

    t_start = time.perf_counter()
    indices = np.arange(train_data.count)

    for epoch in range(1, epochs + 1):
        t0 = time.perf_counter()
        model.train()
        if policy_objective == "legacy":
            np.random.shuffle(indices)  # Preserve the historical seeded shuffle.
        else:
            indices = train_data.epoch_indices(train_sampling)

        train_loss_sum = 0.0
        train_top1_sum = 0.0
        optimizer.zero_grad()

        for step_idx, i in enumerate(range(0, train_data.count, batch_size)):
            b_idx = indices[i : min(i + batch_size, train_data.count)]
            obs, actions, parent_idx, lengths, chosen_global, won, steps_15 = train_data.get_batch(b_idx, device)

            adv_logits, val_logits, v_steps = model(obs, actions, parent_idx)

            chosen_adv = adv_logits[chosen_global]
            lse, max_vals = segmented_logsumexp(adv_logits, lengths)

            total_loss = compute_training_loss(
                adv_logits, val_logits, v_steps, lengths, chosen_global, won, steps_15,
                policy_objective, train_data.batch_policy_mask(b_idx, device),
            )
            if total_loss is None:
                continue
            if not torch.isfinite(total_loss):
                raise FloatingPointError(f"Non-finite loss at epoch {epoch}, batch {step_idx}")

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

        val_metrics = evaluate(model, val_data, device, 512, policy_objective)
        train_top1 = train_top1_sum / train_data.count
        if not all(math.isfinite(value) for value in val_metrics.values()):
            raise FloatingPointError(f"Non-finite validation metrics at epoch {epoch}: {val_metrics}")
        if not math.isfinite(train_loss_sum) or not math.isfinite(train_top1):
            raise FloatingPointError(f"Non-finite training metrics at epoch {epoch}")

        row = {
            "epoch": epoch,
            "train_loss": train_loss_sum / train_data.count,
            "train_top1": train_top1,
            "val_top1": val_metrics["top1_match"],
            "val_ce": val_metrics["pi_loss"],
            "epoch_seconds": epoch_sec,
        }
        if policy_objective == "legacy":
            row.update(val_critic_acc=val_metrics["val_acc"], val_steps_mae=val_metrics["steps_mae"])
        history.append(row)

        is_best = selection_improved(policy_objective, val_metrics, best_score)
        if is_best:
            best_score = val_metrics["pi_loss"] if policy_objective == "teacher-bc" else val_metrics["top1_match"]
            best_match = val_metrics["top1_match"]
            best_ce = val_metrics["pi_loss"]
            best_epoch = epoch
            torch.save(model.state_dict(), out_dir / "best_model.pt")

        torch.save(model.state_dict(), out_dir / "latest_model.pt")

        print(
            f"Epoch {epoch:2d}/{epochs:2d} ({epoch_sec:.2f}s) | "
            f"Actor Top-1: Train={train_top1*100:.1f}%, Val={val_metrics['top1_match']*100:.2f}% | "
            f"Val metrics={val_metrics} {'*' if is_best else ''}"
        )

    total_sec = time.perf_counter() - t_start
    if best_epoch is None:
        raise RuntimeError("No finite trained epoch was selected; refusing to export")
    print(f"\nTraining complete in {total_sec:.2f}s. Best Epoch {best_epoch}: CE={best_ce:.6f}, Top-1={best_match*100:.2f}%")

    # Export only this run's selected trained epoch, never the epoch-0 parent.
    model.load_state_dict(torch.load(out_dir / "best_model.pt", weights_only=True), strict=True)
    export_weights(model, out_dir / "mortal_actor_critic_weights.json", training_objective=policy_objective)
    print(f"Exported {out_dir / 'mortal_actor_critic_weights.json'}")

    with open(out_dir / "training-summary.json", "w", encoding="utf-8") as f:
        json.dump({
            "action_representation": action_representation,
            "action_dim": act_dim,
            **parent_identity,
            "critic_backbone_grad": critic_backbone_grad,
            "seed": seed,
            "epochs": epochs,
            "best_epoch": best_epoch,
            "best_val_top1": best_match,
            "best_val_ce": best_ce,
            "policy_objective": policy_objective,
            "selection": "min-val-ce" if policy_objective == "teacher-bc" else "max-val-top1",
            "selection_epochs": [1, epochs],
            "selection_tie_break": "earliest",
            "auxiliary_heads_trained": policy_objective == "legacy",
            "train_sampling": train_sampling,
            "epoch_sample_budget": train_data.count,
            "policy_metadata": train_data.policy_metadata,
            "val_ce_history": [row["val_ce"] for row in history],
            "baseline": val_0,
            "history": history,
            "total_seconds": total_sec,
        }, f, indent=2, allow_nan=False)

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
    parser.add_argument(
        "--critic-backbone-grad", action="store_true",
        help="Allow outcome BCE to train the shared state backbone (default: detached).",
    )
    parser.add_argument("--policy-objective", choices=("legacy", "teacher-bc"), default="legacy")
    parser.add_argument("--train-sampling", choices=("shuffle", "balanced-groups"), default="shuffle")
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
        critic_backbone_grad=args.critic_backbone_grad,
        policy_objective=args.policy_objective,
        train_sampling=args.train_sampling,
    )


if __name__ == "__main__":
    main()
