"""M42A trainer: Visible Action-Entity Relation Residual Probe (Repair 1).

Enforces:
  - AdamW explicit foreach=False (P0-1)
  - Hard assertions on B file SHA256, B semantic SHA256, M41 run-contract SHA256 (P1-3)
  - Fully bound per-state derived cache with authoritative hashes and fail-closed validation (P1-2)
  - Parameter delta and gradient norm activation tracking (P1-1)
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

# Frozen contract constants
EXPECTED_RUN_CONTRACT_SHA256 = "2a449550c179425a58fb536851c8f78d907fa227b8de58f2704357a0ec716563"
EXPECTED_B_FILE_SHA256 = "6af9d23597ade13663748d96c82d43f0e3159ae60c5e7cd7d8a2066553b7dd9a"
EXPECTED_B_SEMANTIC_SHA256 = "c475f6f20761e1580f8ec39517f940ab81fa848689ccf6c3473fa676f42cc05c"

BATCH_GAMES = 32
EPOCHS = 16
LR = 1e-4
WEIGHT_DECAY = 1e-4
BETAS = (0.9, 0.999)
EPS = 1e-8
GRAD_CLIP = 1.0


def compute_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_m41a_semantic_hash(ckpt: dict[str, Any]) -> str:
    hasher = hashlib.sha256()
    for key in sorted(ckpt["q_head_state"].keys()):
        t = ckpt["q_head_state"][key].detach().cpu()
        hasher.update(key.encode())
        hasher.update(str(tuple(t.shape)).encode())
        hasher.update(t.numpy().tobytes())
    for key in sorted(ckpt["encoder_state"].keys()):
        t = ckpt["encoder_state"][key].detach().cpu()
        hasher.update(key.encode())
        hasher.update(str(tuple(t.shape)).encode())
        hasher.update(t.numpy().tobytes())
    return hasher.hexdigest()


def compute_residual_semantic_hash(residual_state: dict[str, torch.Tensor]) -> str:
    hasher = hashlib.sha256()
    for key in sorted(residual_state.keys()):
        t = residual_state[key].detach().cpu()
        hasher.update(key.encode())
        hasher.update(str(tuple(t.shape)).encode())
        hasher.update(t.numpy().tobytes())
    return hasher.hexdigest()


def assert_base_contracts() -> None:
    """Fail-closed hard assertions on frozen parent contracts (P1-3)."""
    # 1. M41 run contract exact SHA
    if not RUN_CONTRACT_PATH.is_file():
        raise FileNotFoundError(f"M41 run contract not found at {RUN_CONTRACT_PATH}")
    actual_contract_sha = compute_file_sha256(RUN_CONTRACT_PATH)
    if actual_contract_sha != EXPECTED_RUN_CONTRACT_SHA256:
        raise RuntimeError(
            f"M41 run-contract SHA mismatch: expected {EXPECTED_RUN_CONTRACT_SHA256}, "
            f"found {actual_contract_sha}"
        )

    # 2. Immutable baseline B file SHA
    if not BASE_CHECKPOINT_PATH.is_file():
        raise FileNotFoundError(f"Base checkpoint B not found at {BASE_CHECKPOINT_PATH}")
    actual_b_file_sha = compute_file_sha256(BASE_CHECKPOINT_PATH)
    if actual_b_file_sha != EXPECTED_B_FILE_SHA256:
        raise RuntimeError(
            f"Immutable baseline B file SHA mismatch: expected {EXPECTED_B_FILE_SHA256}, "
            f"found {actual_b_file_sha}"
        )

    # 3. Immutable baseline B semantic SHA
    b_ckpt = torch.load(BASE_CHECKPOINT_PATH, map_location="cpu", weights_only=False)
    actual_b_semantic_sha = compute_m41a_semantic_hash(b_ckpt)
    if actual_b_semantic_sha != EXPECTED_B_SEMANTIC_SHA256:
        raise RuntimeError(
            f"Immutable baseline B semantic SHA mismatch: expected {EXPECTED_B_SEMANTIC_SHA256}, "
            f"found {actual_b_semantic_sha}"
        )


def get_provenance_metadata(catalog: dict[str, Any]) -> dict[str, str]:
    return {
        "m41_run_contract_sha256": compute_file_sha256(RUN_CONTRACT_PATH),
        "relation_schema_version": "v1",
        "relation_schema_sha256": compute_file_sha256(RELATION_V1_PY),
        "catalog_hash": catalog_semantic_hash(catalog),
        "probe_legal_binary_sha256": compute_file_sha256(SPLN),
    }


def rebuild_and_cache_derived_split(split: str, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Build derived cache from scratch with per-state authoritative hashes (P1-2)."""
    assert_split_allowed(split)
    split_dir = DERIVED_ROOT / split
    split_dir.mkdir(parents=True, exist_ok=True)
    provenance = get_provenance_metadata(catalog)

    print(f"Building derived cache for {split} from authoritative corpus...", flush=True)
    t0 = time.time()
    raw_games = load_split(split)
    encoded_games = []
    state_manifest_records = []

    for game in raw_games:
        gdir = Path(game["dir"])
        encoded_states = []
        for state in game["states"]:
            ply = state["ply"]
            sdir = gdir / f"branch-ply{ply:04d}"
            state_probe = json.loads((sdir / "state-probe.json").read_text(encoding="utf-8"))
            state_manifest = json.loads((sdir / "state-manifest.json").read_text(encoding="utf-8"))

            auth_obs_hash = state_probe["observation_hash"]
            auth_state_hash = state_probe["state_hash"]
            auth_legal_hash = hashlib.sha256(
                json.dumps(state_probe["legal_actions"], sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            ordered_actions_hash = hashlib.sha256(
                json.dumps(state["actions"], sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()

            obs = state["observation"]
            actions = state["actions"]
            returns = state["returns"]

            # 1. Observation encoding
            enc_obs = encode_observation(obs, catalog)
            entities = enc_obs.entities
            mask = enc_obs.mask
            global_features = enc_obs.global_features

            # 2. Action encoding
            actions_list = []
            for a in actions:
                base = encode_action(a).tolist()
                delta = encode_action_delta_v2(obs, a, catalog)
                actions_list.append(base + delta)
            actions_tensor = torch.tensor(actions_list, dtype=torch.float32)

            # 3. Relation tensor encoding
            relations_tensor = compute_observation_relation_tensors(obs, actions, catalog)
            relation_tensor_sha256 = hashlib.sha256(relations_tensor.numpy().tobytes()).hexdigest()

            # 4. Target computation
            mean_return = sum(returns) / len(returns)
            targets = [g - mean_return for g in returns]
            targets_tensor = torch.tensor(targets, dtype=torch.float32)

            state_record = {
                "game_id": gdir.name,
                "ply": ply,
                "seed": state_probe["seed"],
                "authoritative_observation_hash": auth_obs_hash,
                "authoritative_state_hash": auth_state_hash,
                "authoritative_legal_hash": auth_legal_hash,
                "ordered_actions_hash": ordered_actions_hash,
                "relation_tensor_sha256": relation_tensor_sha256,
            }
            state_manifest_records.append(state_record)

            encoded_states.append({
                "ply": ply,
                "obs_hash": auth_obs_hash,
                "state_hash": auth_state_hash,
                "legal_hash": auth_legal_hash,
                "ordered_actions_hash": ordered_actions_hash,
                "relation_tensor_sha256": relation_tensor_sha256,
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
            "dir": str(gdir),
            "states": encoded_states,
        })

    # Compute canonical manifest hash over all state records
    canonical_manifest_bytes = json.dumps(
        state_manifest_records, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    canonical_manifest_sha256 = hashlib.sha256(canonical_manifest_bytes).hexdigest()

    manifest_payload = {
        "format": "effective-splendor-m42a-derived-split-manifest",
        "version": 1,
        "split": split,
        "computed_at": time.time(),
        **provenance,
        "games_count": len(encoded_games),
        "states_count": len(state_manifest_records),
        "canonical_manifest_sha256": canonical_manifest_sha256,
        "states": state_manifest_records,
    }

    manifest_path = split_dir / "cache_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    torch.save(encoded_games, split_dir / "encoded_games.pt")
    print(
        f"Derived cache for {split} created in {time.time() - t0:.1f}s "
        f"({len(state_manifest_records)} states, manifest SHA: {canonical_manifest_sha256[:16]}...).",
        flush=True,
    )
    return encoded_games


def load_and_validate_derived_cache(split: str, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Load derived cache and validate EVERY state fail-closed against manifest (P1-2)."""
    assert_split_allowed(split)
    split_dir = DERIVED_ROOT / split
    manifest_path = split_dir / "cache_manifest.json"
    data_path = split_dir / "encoded_games.pt"

    if not manifest_path.is_file() or not data_path.is_file():
        return rebuild_and_cache_derived_split(split, catalog)

    provenance = get_provenance_metadata(catalog)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 1. Global provenance check
    for k, expected_val in provenance.items():
        if manifest.get(k) != expected_val:
            print(f"Provenance drift detected on {k}, rebuilding cache for {split}...", flush=True)
            return rebuild_and_cache_derived_split(split, catalog)

    # 2. Canonical manifest hash verification
    canonical_bytes = json.dumps(
        manifest["states"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    recomputed_manifest_sha = hashlib.sha256(canonical_bytes).hexdigest()
    if recomputed_manifest_sha != manifest.get("canonical_manifest_sha256"):
        print(f"Manifest canonical hash corruption in {split}, rebuilding...", flush=True)
        return rebuild_and_cache_derived_split(split, catalog)

    # 3. Load games and validate every single state
    try:
        games = torch.load(data_path, map_location="cpu", weights_only=False)
    except Exception as e:
        print(f"Error reading cache data ({e}), rebuilding...", flush=True)
        return rebuild_and_cache_derived_split(split, catalog)

    manifest_states = manifest["states"]
    state_counter = 0

    for game in games:
        for state in game["states"]:
            if state_counter >= len(manifest_states):
                raise RuntimeError(f"Cached states count exceeds manifest in {split}")
            m_rec = manifest_states[state_counter]
            state_counter += 1

            # Fail-closed checks on per-state hashes
            if state["obs_hash"] != m_rec["authoritative_observation_hash"]:
                raise RuntimeError(f"State observation hash mismatch in {split} state {state_counter}")
            if state["legal_hash"] != m_rec["authoritative_legal_hash"]:
                raise RuntimeError(f"State legal hash mismatch in {split} state {state_counter}")
            if state["ordered_actions_hash"] != m_rec["ordered_actions_hash"]:
                raise RuntimeError(f"State ordered actions hash mismatch in {split} state {state_counter}")
            actual_rel_sha = hashlib.sha256(state["relations"].numpy().tobytes()).hexdigest()
            if actual_rel_sha != m_rec["relation_tensor_sha256"]:
                raise RuntimeError(f"State relation tensor SHA mismatch in {split} state {state_counter}")

    if state_counter != len(manifest_states):
        raise RuntimeError(
            f"State count mismatch in {split}: data has {state_counter}, manifest has {len(manifest_states)}"
        )

    print(f"Validated {state_counter} cached states for {split} (all hashes bit-exact).", flush=True)
    return games


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


def compute_module_param_deltas(
    initial_residual: M42ARelationResidual,
    final_residual: M42ARelationResidual,
) -> dict[str, float]:
    """Compute module-wise L2 parameter deltas ||theta_final - theta_init||_2 (P1-1)."""
    deltas = {}
    modules = {
        "relation_encoder": (initial_residual.relation_encoder, final_residual.relation_encoder),
        "pair_encoder": (initial_residual.pair_encoder, final_residual.pair_encoder),
        "entity_gate": (initial_residual.entity_gate, final_residual.entity_gate),
        "residual_head_0": (initial_residual.residual_head[0], final_residual.residual_head[0]),
        "residual_head_final": (initial_residual.residual_head[-1], final_residual.residual_head[-1]),
    }
    total_sq = 0.0
    for mod_name, (m_init, m_final) in modules.items():
        sq = 0.0
        for p_i, p_f in zip(m_init.parameters(), m_final.parameters()):
            sq += float(torch.sum((p_f.detach().cpu() - p_i.detach().cpu()) ** 2))
        deltas[mod_name] = float(sq ** 0.5)
        total_sq += sq

    deltas["total_residual_l2_delta"] = float(total_sq ** 0.5)
    return deltas


def train_arm(
    arm_name: str,
    base_arm: M41AArm,
    train_games: list[dict[str, Any]],
    val_games: list[dict[str, Any]],
    device: torch.device,
) -> dict[str, Any]:
    print(f"\n=======================================================", flush=True)
    print(f"Starting Training for Arm {arm_name} (Repair 1 Run 2)...", flush=True)
    print(f"=======================================================", flush=True)

    # 1. Build arm model
    torch.manual_seed(RELATION_INIT_SEED)
    initial_residual = M42ARelationResidual()
    initial_residual_copy = copy.deepcopy(initial_residual)

    model = M42AModel(copy.deepcopy(base_arm), initial_residual, arm_type=arm_name).to(device)

    # 2. Setup AdamW optimizer (P0-1 explicit foreach=False)
    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(
        trainable_params,
        lr=LR,
        betas=BETAS,
        eps=EPS,
        weight_decay=WEIGHT_DECAY,
        amsgrad=False,
        foreach=False,  # P0-1 contract fix
        fused=False,
    )

    num_games = len(train_games)
    assert num_games == 192, f"expected 192 train games, found {num_games}"

    epoch_losses = []
    grad_norms = []
    first_batch_grad_norm: float | None = None
    final_batch_grad_norm: float | None = None

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

            # P1-1 Gradient norm tracking
            total_norm = float(nn.utils.clip_grad_norm_(trainable_params, GRAD_CLIP))
            if first_batch_grad_norm is None:
                first_batch_grad_norm = total_norm
            final_batch_grad_norm = total_norm
            grad_norms.append(total_norm)

            optimizer.step()
            batch_losses.append(loss.item())

        mean_ep_loss = sum(batch_losses) / len(batch_losses)
        epoch_losses.append(mean_ep_loss)
        print(
            f"[Arm {arm_name}] Epoch {epoch:02d}/{EPOCHS} - "
            f"Loss: {mean_ep_loss:.6f} - GradNorm: {final_batch_grad_norm:.6f} "
            f"({time.time() - t_ep_start:.2f}s)",
            flush=True,
        )

    total_time = time.time() - t_train_start
    print(f"Arm {arm_name} training complete in {total_time:.1f}s.", flush=True)

    # 3. Activation audit: module-wise deltas from initialization
    param_deltas = compute_module_param_deltas(initial_residual_copy, model.residual)
    residual_semantic_sha = compute_residual_semantic_hash(model.residual.state_dict())

    # 4. Save final checkpoint
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    ckpt_path = RUN_ROOT / f"m42a-{arm_name}-final.pt"
    ckpt_payload = {
        "arm": arm_name,
        "run_era": "run2_valid",
        "epoch": EPOCHS,
        "residual_state": model.residual.state_dict(),
        "residual_semantic_sha256": residual_semantic_sha,
        "base_checkpoint_file_sha256": EXPECTED_B_FILE_SHA256,
        "base_checkpoint_semantic_sha256": EXPECTED_B_SEMANTIC_SHA256,
        "run_contract_sha256": EXPECTED_RUN_CONTRACT_SHA256,
        "relation_init_seed": RELATION_INIT_SEED,
        "trainer_seed": TRAINER_SEED,
        "loss_history": epoch_losses,
        "final_loss": epoch_losses[-1],
        "training_time_seconds": total_time,
        "first_batch_grad_norm": first_batch_grad_norm,
        "final_batch_grad_norm": final_batch_grad_norm,
        "mean_grad_norm": sum(grad_norms) / len(grad_norms),
        "param_deltas_from_init": param_deltas,
    }
    torch.save(ckpt_payload, ckpt_path)
    file_sha = compute_file_sha256(ckpt_path)
    print(
        f"Saved Arm {arm_name} checkpoint to {ckpt_path}\n"
        f"  File SHA-256:     {file_sha}\n"
        f"  Residual Semantic: {residual_semantic_sha}\n"
        f"  Total L2 Delta:   {param_deltas['total_residual_l2_delta']:.6f}",
        flush=True,
    )

    return {
        "arm": arm_name,
        "checkpoint_path": str(ckpt_path),
        "file_sha256": file_sha,
        "residual_semantic_sha256": residual_semantic_sha,
        "final_loss": epoch_losses[-1],
        "first_batch_grad_norm": first_batch_grad_norm,
        "final_batch_grad_norm": final_batch_grad_norm,
        "param_deltas": param_deltas,
        "training_time_seconds": total_time,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M42A Paired Training Pipeline (Repair 1)")
    parser.add_argument("--arm", choices=["X", "R", "both"], default="both")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    device = torch.device(args.device)

    print(f"M42A Training Pipeline (Repair 1) on {device}.", flush=True)

    # 1. Hard fail-closed assertion on B and run-contract contracts (P1-3)
    assert_base_contracts()
    print("Base contracts asserted bit-exact:", flush=True)
    print(f"  M41 Run-Contract: {EXPECTED_RUN_CONTRACT_SHA256}", flush=True)
    print(f"  B File SHA:       {EXPECTED_B_FILE_SHA256}", flush=True)
    print(f"  B Semantic SHA:   {EXPECTED_B_SEMANTIC_SHA256}", flush=True)

    catalog = load_catalog(CATALOG_PATH)

    # 2. Derived cache loading with full fail-closed state validation (P1-2)
    train_games = load_and_validate_derived_cache("train", catalog)
    val_games = load_and_validate_derived_cache("validation", catalog)

    # 3. Load D2 and Base Arm
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
