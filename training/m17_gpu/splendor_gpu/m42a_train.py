"""M42A trainer: Visible Action-Entity Relation Residual Probe.

Trains paired arms X (generic residual control) and R (explicit relation residual).
Shared contract:
  RELATION_INIT_SEED = 42_261_001 (single draw bit-copied to X and R)
  TRAINER_SEED       = 40_261_002 (M41A 16-epoch deterministic game shuffle)
  AdamW lr=1e-4, wd=1e-4, betas=(0.9, 0.999), eps=1e-8
  32 games/batch, 16 epochs, final-epoch checkpoint only
  Hierarchical loss: state -> game -> batch mean of legal-set centered Huber(delta=1.0)
  FP32, grad clip 1.0, CUDA deterministic
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "training/m17_gpu"))

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import torch
import torch.nn as nn

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.encoding import encode_action, encode_observation
from splendor_gpu.m25_delta_v2 import encode_action_delta_v2
from splendor_gpu.m35a_registry import load_and_validate_checkpoint
from splendor_gpu.m41a_helpers import (
    HEAD_INIT_SEED,
    TRAINER_SEED,
    epoch_game_order,
)
from splendor_gpu.m41a_train import (
    ALLOWED_SPLITS,
    CORPUS_ROOT,
    assert_split_allowed,
    load_split,
    M41AArm,
    M41AQHead,
)
from splendor_gpu.m42a_model import (
    M42AModel,
    M42ARelationResidual,
    RELATION_INIT_SEED,
    create_m42a_paired_arms,
)
from splendor_gpu.m42a_relation_v1 import (
    compute_observation_relation_tensors,
)

CATALOG_PATH = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
BASE_CHECKPOINT_PATH = REPO / "local-artifacts/m41a-run/m41a-F-final.pt"
RUN_ROOT = REPO / "local-artifacts/m42a-run"
DERIVED_ROOT = REPO / "local-artifacts/m42a-derived"
SPLN = REPO / "target/release/splendor.exe"
RUN_CONTRACT_PATH = CORPUS_ROOT / "run-contract.json"
RELATION_V1_PY = REPO / "training/m17_gpu/splendor_gpu/m42a_relation_v1.py"

BATCH_GAMES = 32
EPOCHS = 16
LR = 1e-4
WEIGHT_DECAY = 1e-4
BETAS = (0.9, 0.999)
EPS = 1e-8
GRAD_CLIP = 1.0


def compute_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_provenance_metadata(catalog: dict[str, Any]) -> dict[str, str]:
    return {
        "m41_run_contract_sha256": compute_file_sha256(RUN_CONTRACT_PATH),
        "relation_schema_version": "v1",
        "relation_schema_sha256": compute_file_sha256(RELATION_V1_PY),
        "catalog_hash": catalog_semantic_hash(catalog),
        "probe_legal_binary_sha256": compute_file_sha256(SPLN),
    }


def precompute_derived_cache(split: str, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Precompute or load derived features for a split, saving to DERIVED_ROOT/split."""
    assert_split_allowed(split)
    split_dir = DERIVED_ROOT / split
    cache_meta_path = split_dir / "cache_manifest.json"
    provenance = get_provenance_metadata(catalog)

    # Check if cache exists and is valid
    if cache_meta_path.is_file():
        try:
            meta = json.loads(cache_meta_path.read_text(encoding="utf-8"))
            if all(meta.get(k) == v for k, v in provenance.items()):
                print(f"Loading cached derived features for {split} from {split_dir}...", flush=True)
                cached_games = torch.load(split_dir / "encoded_games.pt", map_location="cpu", weights_only=False)
                return cached_games
        except Exception as e:
            print(f"Cache invalid or unreadable ({e}), recomputing...", flush=True)

    print(f"Computing derived features for {split}...", flush=True)
    t0 = time.time()
    raw_games = load_split(split)
    encoded_games = []

    for g_idx, game in enumerate(raw_games):
        encoded_states = []
        for s_idx, state in enumerate(game["states"]):
            obs = state["observation"]
            actions = state["actions"]
            returns = state["returns"]

            # 1. Base observation encoding
            enc_obs = encode_observation(obs, catalog)
            entities = enc_obs.entities  # (31, 32)
            mask = enc_obs.mask          # (31,)
            global_features = enc_obs.global_features  # (40,)

            # 2. Base actions encoding (59-dim: base 36 + delta 23)
            actions_list = []
            for a in actions:
                base = encode_action(a).tolist()
                delta = encode_action_delta_v2(obs, a, catalog)
                actions_list.append(base + delta)
            actions_tensor = torch.tensor(actions_list, dtype=torch.float32)

            # 3. Relation tensor encoding (N, 31, 28)
            relations_tensor = compute_observation_relation_tensors(obs, actions, catalog)

            # 4. Target computation: A_cf = G(s,a) - mean_legal(G)
            mean_return = sum(returns) / len(returns)
            targets = [g - mean_return for g in returns]
            targets_tensor = torch.tensor(targets, dtype=torch.float32)

            # Provenance hashes for state
            obs_hash = obs.get("observation_hash", "")
            actions_canonical_json = json.dumps(actions, sort_keys=True)
            legal_hash = hashlib.sha256(actions_canonical_json.encode("utf-8")).hexdigest()

            encoded_states.append({
                "ply": state["ply"],
                "obs_hash": obs_hash,
                "legal_hash": legal_hash,
                "entities": entities,
                "mask": mask,
                "global_features": global_features,
                "actions": actions_tensor,
                "relations": relations_tensor,
                "targets": targets_tensor,
                "returns": returns,
                "raw_actions": actions,
                "observation": obs,
            })
        encoded_games.append({
            "dir": game["dir"],
            "states": encoded_states,
        })

    split_dir.mkdir(parents=True, exist_ok=True)
    torch.save(encoded_games, split_dir / "encoded_games.pt")
    cache_meta = {
        **provenance,
        "split": split,
        "games_count": len(encoded_games),
        "states_count": sum(len(g["states"]) for g in encoded_games),
        "computed_at": time.time(),
    }
    cache_meta_path.write_text(json.dumps(cache_meta, indent=2), encoding="utf-8")
    print(f"Derived features for {split} saved in {time.time() - t0:.1f}s.", flush=True)
    return encoded_games


def pack_batch(batch_games: list[dict[str, Any]], device: torch.device):
    """Pack a list of encoded games into batched tensors."""
    entities_list = []
    masks_list = []
    globals_list = []
    actions_list = []
    relations_list = []
    offsets = [0]
    targets_list = []
    game_boundaries = []

    for game in batch_games:
        state_start = len(offsets) - 1
        for state in game["states"]:
            entities_list.append(state["entities"])
            masks_list.append(state["mask"])
            globals_list.append(state["global_features"])
            actions_list.append(state["actions"])
            relations_list.append(state["relations"])
            targets_list.append(state["targets"])
            offsets.append(offsets[-1] + state["actions"].shape[0])
        state_end = len(offsets) - 1
        game_boundaries.append((state_start, state_end))

    entities = torch.stack(entities_list).to(device)
    mask = torch.stack(masks_list).to(device)
    global_features = torch.stack(globals_list).to(device)
    actions = torch.cat(actions_list, dim=0).to(device)
    relations = torch.cat(relations_list, dim=0).to(device)
    offsets_t = torch.tensor(offsets, dtype=torch.long, device=device)
    targets = torch.cat(targets_list, dim=0).to(device)

    return entities, mask, global_features, actions, relations, offsets_t, game_boundaries, targets


def hierarchical_loss(
    q_raw: torch.Tensor,
    offsets: torch.Tensor,
    game_boundaries: list[tuple[int, int]],
    targets: torch.Tensor,
) -> torch.Tensor:
    """Legal-set centered Huber loss with hierarchical state->game->batch mean."""
    boundaries = offsets.detach().cpu().tolist()
    game_losses = []
    for state_start, state_end in game_boundaries:
        state_losses = []
        for s in range(state_start, state_end):
            a0, a1 = boundaries[s], boundaries[s + 1]
            raw = q_raw[a0:a1]
            a_theta = raw - raw.mean()  # Centering inside loss
            target = targets[a0:a1]
            state_losses.append(
                nn.functional.huber_loss(a_theta, target, delta=1.0, reduction="mean")
            )
        game_losses.append(torch.stack(state_losses).mean())
    return torch.stack(game_losses).mean()


def train_arm(
    arm_name: str,
    base_arm: M41AArm,
    train_games: list[dict[str, Any]],
    val_games: list[dict[str, Any]],
    device: torch.device,
) -> dict[str, Any]:
    print(f"\n=======================================================", flush=True)
    print(f"Starting Training for Arm {arm_name}...", flush=True)
    print(f"=======================================================", flush=True)

    # 1. Build arm model
    torch.manual_seed(RELATION_INIT_SEED)
    residual = M42ARelationResidual()
    model = M42AModel(copy.deepcopy(base_arm), residual, arm_type=arm_name).to(device)

    # 2. Setup AdamW optimizer (trainable residual parameters only)
    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(
        trainable_params,
        lr=LR,
        betas=BETAS,
        eps=EPS,
        weight_decay=WEIGHT_DECAY,
        amsgrad=False,
        fused=False,
    )

    num_games = len(train_games)
    assert num_games == 192, f"expected 192 train games, found {num_games}"

    epoch_losses = []
    t_train_start = time.time()

    for epoch in range(1, EPOCHS + 1):
        model.train()
        t_ep_start = time.time()
        order = epoch_game_order(num_games, epoch)
        shuffled_games = [train_games[i] for i in order]

        batch_losses = []
        for b_idx in range(0, num_games, BATCH_GAMES):
            batch = shuffled_games[b_idx : b_idx + BATCH_GAMES]
            (
                entities,
                mask,
                global_features,
                actions,
                relations,
                offsets,
                game_boundaries,
                targets,
            ) = pack_batch(batch, device)

            optimizer.zero_grad()
            q_total, _, _ = model(
                entities, mask, global_features, actions, offsets, relations
            )
            loss = hierarchical_loss(q_total, offsets, game_boundaries, targets)
            loss.backward()
            nn.utils.clip_grad_norm_(trainable_params, GRAD_CLIP)
            optimizer.step()
            batch_losses.append(loss.item())

        mean_ep_loss = sum(batch_losses) / len(batch_losses)
        epoch_losses.append(mean_ep_loss)
        print(
            f"[Arm {arm_name}] Epoch {epoch:02d}/{EPOCHS} - "
            f"Loss: {mean_ep_loss:.6f} ({time.time() - t_ep_start:.2f}s)",
            flush=True,
        )

    total_time = time.time() - t_train_start
    print(f"Arm {arm_name} training complete in {total_time:.1f}s.", flush=True)

    # 3. Save final checkpoint
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    ckpt_path = RUN_ROOT / f"m42a-{arm_name}-final.pt"
    ckpt_payload = {
        "arm": arm_name,
        "epoch": EPOCHS,
        "residual_state": model.residual.state_dict(),
        "base_checkpoint_sha256": compute_file_sha256(BASE_CHECKPOINT_PATH),
        "relation_init_seed": RELATION_INIT_SEED,
        "trainer_seed": TRAINER_SEED,
        "loss_history": epoch_losses,
        "final_loss": epoch_losses[-1],
        "training_time_seconds": total_time,
    }
    torch.save(ckpt_payload, ckpt_path)
    file_sha = compute_file_sha256(ckpt_path)
    print(f"Saved Arm {arm_name} checkpoint to {ckpt_path} (SHA-256: {file_sha}).", flush=True)

    return {
        "arm": arm_name,
        "checkpoint_path": str(ckpt_path),
        "checkpoint_sha256": file_sha,
        "loss_history": epoch_losses,
        "final_loss": epoch_losses[-1],
        "training_time_seconds": total_time,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M42A Paired Training Pipeline")
    parser.add_argument("--arm", choices=["X", "R", "both"], default="both")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    device = torch.device(args.device)

    print(f"M42A Training Pipeline initialized on {device}.", flush=True)
    catalog = load_catalog(CATALOG_PATH)

    # 1. Precompute or load derived cache for train and validation
    train_games = precompute_derived_cache("train", catalog)
    val_games = precompute_derived_cache("validation", catalog)

    # 2. Load D2 and Base Arm
    d2_model, _ = load_and_validate_checkpoint(
        "M25-D2-v2", catalog_hash=catalog_semantic_hash(catalog),
        device=torch.device("cpu"),
    )
    base_ckpt = torch.load(BASE_CHECKPOINT_PATH, map_location="cpu", weights_only=False)
    q_head = M41AQHead()
    q_head.load_state_dict(base_ckpt["q_head_state"])
    base_arm = M41AArm(d2_model, q_head, freeze_encoders=True).eval()

    arms_to_run = ["X", "R"] if args.arm == "both" else [args.arm]
    results = {}
    for arm_name in arms_to_run:
        res = train_arm(arm_name, base_arm, train_games, val_games, device)
        results[arm_name] = res

    # Write training summary report
    report_path = RUN_ROOT / "m42a-training-summary.json"
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"All training runs complete. Summary written to {report_path}.", flush=True)


if __name__ == "__main__":
    main()
