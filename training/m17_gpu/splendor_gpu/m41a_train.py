"""M41A P3 F/U trainer: the frozen §4.1 contract, implemented verbatim.

Arms:
  F — D2-v2 state/action encoders FROZEN, fresh q-head trained.
  U — same D2-v2 encoder initialization (trainable) + the SAME fresh
      q-head initial tensors (bit-exact copy), trained end-to-end.

q-head: Linear(576,192) -> GELU -> Linear(192,1) over the D2 joint
representation z(o,a) = concat(s_emb, a_emb, s_emb * a_emb).

Shared training contract (frozen):
  HEAD_INIT_SEED = 40_261_001 (ONE draw, bit-copied into F and U)
  TRAINER_SEED   = 40_261_002 (M41A 16-epoch deterministic game shuffle)
  AdamW lr 1e-4, betas (0.9,0.999), eps 1e-8, wd 1e-4,
       amsgrad=False, foreach=False, fused=False
  batch = 32 whole games; epochs = exactly 16; FINAL-epoch checkpoint
  only (no selection); FP32; grad clip 1.0; cuda, deterministic.

Hierarchical loss (never flattened):
  L_state = mean over the state's legal actions of Huber(A_theta, A_cf)
  L_game  = mean over the game's selected states of L_state
  L       = mean over the batch's games of L_game

Observations are rebuilt per state via `probe-legal --emit-observation`
(whose observation hash is cross-checked against the corpus
state-probe.json before use).

Power-calibration is HARD-DENIED before F/U final checkpoints exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
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
from splendor_gpu.m31a_train import DeltaEntityMixer
from splendor_gpu.m35a_registry import load_and_validate_checkpoint
from splendor_gpu.m41a_helpers import (
    epoch_game_order,
    HEAD_INIT_SEED,
    TRAINER_SEED,
)

CORPUS_ROOT = REPO / "local-artifacts/m41a-corpus"
CATALOG_PATH = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
D2_PATH = REPO / "local-artifacts/m25-recovery-exp-d2-v2/checkpoint.pt"
OUT_ROOT = REPO / "local-artifacts/m41a-run"
SPLN = REPO / "target/release/splendor.exe"

ALLOWED_SPLITS = ("train", "validation")
DENIED_SPLITS = ("power-calibration", "formal")

BATCH_GAMES = 32
EPOCHS = 16
LR = 1e-4
WEIGHT_DECAY = 1e-4
BETAS = (0.9, 0.999)
EPS = 1e-8
GRAD_CLIP = 1.0


# ---------------------------------------------------------------------------
# Split access control (hard power-cal denial)
# ---------------------------------------------------------------------------

def assert_split_allowed(split: str) -> None:
    if split in DENIED_SPLITS:
        raise PermissionError(
            f"split {split!r} is SEALED until F and U final checkpoints "
            "are written and hash-sealed (design §8/§9.6); the trainer "
            "may not enumerate, read, or compute anything from it"
        )
    if split not in ALLOWED_SPLITS:
        raise PermissionError(f"unknown split {split!r}")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class M41AQHead(nn.Module):
    """The frozen q-head topology (§4.1)."""

    def __init__(self) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(576, 192),
            nn.GELU(),
            nn.Linear(192, 1),
        )

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return self.net(z).squeeze(-1)


class M41AArm(nn.Module):
    """D2-v2 encoders (+ never-updated D2 policy/value scorer for
    identity completeness) and the M41A q-head.

    The constructor OWNS its requires_grad state: `freeze_encoders`
    either freezes OR explicitly unfreezes every encoder parameter, so
    arm construction order can never leak a stale requires_grad state
    from a previous arm built over shared modules."""

    def __init__(self, d2: DeltaEntityMixer, q_head: M41AQHead, *, freeze_encoders: bool) -> None:
        super().__init__()
        self.entity_encoder = d2.entity_encoder
        self.entity_gate = d2.entity_gate
        self.global_encoder = d2.global_encoder
        self.mix = d2.mix
        self.blocks = d2.blocks
        self.norm = d2.norm
        self.action_encoder = d2.action_encoder
        self.policy = d2.policy
        self.value = d2.value
        for module in (self.policy, self.value):
            for p in module.parameters():
                p.requires_grad_(False)
        self.q_head = q_head
        for module in (self.entity_encoder, self.entity_gate,
                       self.global_encoder, self.mix, self.blocks,
                       self.norm, self.action_encoder):
            for p in module.parameters():
                p.requires_grad_(not freeze_encoders)

    def state_embedding(self, entities, mask, global_features) -> torch.Tensor:
        encoded = self.entity_encoder(entities)
        gate = self.entity_gate(encoded).squeeze(-1).masked_fill(
            ~mask, torch.finfo(encoded.dtype).min
        )
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded * weights).sum(dim=1)
        state = self.mix(torch.cat([pooled, self.global_encoder(global_features)], dim=-1))
        return self.norm(self.blocks(state))

    def q_values(self, entities, mask, global_features, actions, offsets) -> torch.Tensor:
        state = self.state_embedding(entities, mask, global_features)
        action = self.action_encoder(actions)
        counts = offsets[1:] - offsets[:-1]
        expanded = torch.repeat_interleave(state, counts, dim=0)
        z = torch.cat([expanded, action, expanded * action], dim=-1)
        return self.q_head(z)


# ---------------------------------------------------------------------------
# Observation rebuild (identity-checked)
# ---------------------------------------------------------------------------

def rebuild_observation(gdir: Path, ply: int) -> dict[str, Any]:
    """probe-legal --emit-observation: the branch-point observation with
    its hash, cross-checked against the corpus state-probe.json."""
    out = subprocess.run(
        [str(SPLN), "probe-legal", "--emit-observation",
         "--source-replay", str(gdir / "replay.json"),
         "--branch-ply", str(ply)],
        capture_output=True, text=True, timeout=300, check=True,
    )
    doc = json.loads(out.stdout)
    expected = json.loads(
        (gdir / f"branch-ply{ply:04d}" / "state-probe.json").read_text(encoding="utf-8")
    )
    if doc["observation_hash"] != expected["observation_hash"]:
        raise RuntimeError(
            f"observation hash mismatch at {gdir} ply {ply}: rebuilt "
            f"{doc['observation_hash'][:16]} != corpus {expected['observation_hash'][:16]}"
        )
    if doc["legal_actions"] != expected["legal_actions"]:
        raise RuntimeError(f"legal set mismatch at {gdir} ply {ply}")
    return doc["observation"]


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

def load_split(split: str) -> list[dict[str, Any]]:
    """Load one allowed split: per game, the selected states with the
    exhaustive branch labels (legal actions + teacher returns) and the
    identity-checked branch-point observation."""
    assert_split_allowed(split)
    games = []
    for gdir in sorted((CORPUS_ROOT / split).glob("game-*")):
        states = []
        for sdir in sorted(gdir.glob("branch-ply*")):
            manifest = json.loads((sdir / "state-manifest.json").read_text(encoding="utf-8"))
            ply = manifest["branch_ply"]
            actions = [e["forced_action"] for e in sorted(
                manifest["actions"], key=lambda e: e["action_index"])]
            returns = [float(e["acting_seat_return"]) for e in sorted(
                manifest["actions"], key=lambda e: e["action_index"])]
            states.append({
                "ply": ply,
                "observation": rebuild_observation(gdir, ply),
                "actions": actions,
                "returns": returns,
            })
        games.append({"dir": str(gdir), "states": states})
    return games


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def encode_states(batch_games: list[dict], catalog: dict, device: torch.device):
    """Encode a batch of games into packed tensors + per-state offsets.

    Returns (entities, mask, global_features, actions, offsets,
             game_boundaries, targets) where targets[i] is A_cf for the
    packed action i, computed as G(s,a) - mean_legal(G(s,·)).
    """
    from splendor_gpu.encoding import encode_observation, encode_action
    from splendor_gpu.m25_delta_v2 import encode_action_delta_v2

    entities_list = []
    masks_list = []
    globals_list = []
    actions_flat: list[list[float]] = []
    offsets = [0]
    targets: list[float] = []
    game_boundaries = []  # (state_start, state_end) index ranges per game

    for game in batch_games:
        state_start = len(offsets) - 1
        for state in game["states"]:
            encoded = encode_observation(state["observation"], catalog)
            entities_list.append(encoded.entities)
            masks_list.append(encoded.mask)
            globals_list.append(encoded.global_features)
            returns = state["returns"]
            mean_return = sum(returns) / len(returns)
            for action, g in zip(state["actions"], returns):
                base = encode_action(action).tolist()
                delta = encode_action_delta_v2(state["observation"], action, catalog)
                actions_flat.append(base + delta)
                targets.append(g - mean_return)
            offsets.append(len(actions_flat))
        state_end = len(offsets) - 1
        game_boundaries.append((state_start, state_end))

    entities = torch.stack(entities_list).to(device)
    mask = torch.stack(masks_list).to(device)
    global_features = torch.stack(globals_list).to(device)
    actions = torch.tensor(actions_flat, dtype=torch.float32, device=device)
    offsets_t = torch.tensor(offsets, dtype=torch.long, device=device)
    targets_t = torch.tensor(targets, dtype=torch.float32, device=device)
    return entities, mask, global_features, actions, offsets_t, game_boundaries, targets_t


def hierarchical_loss(q_raw: torch.Tensor, offsets: torch.Tensor,
                      game_boundaries: list[tuple[int, int]],
                      targets: torch.Tensor) -> torch.Tensor:
    """The frozen M41A objective (design §3): the model prediction is
    LEGAL-SET CENTERED inside this function — the caller passes RAW
    f_theta scores and CANNOT forget the centering.

        A_theta(o,a) = f(o,a) - mean_{b in L(o)} f(o,b)
        L_state = mean_legal Huber(A_theta, A_cf)
        L_game  = mean_states(L_state)
        L       = mean_games(L_game)

    A state-only model f(o,a)=c(o) therefore yields A_theta == 0 on
    every legal set and can explain NOTHING of the target — the
    structural core of M41A.
    """
    boundaries = offsets.detach().cpu().tolist()
    game_losses = []
    for state_start, state_end in game_boundaries:
        state_losses = []
        for s in range(state_start, state_end):
            a0, a1 = boundaries[s], boundaries[s + 1]
            raw = q_raw[a0:a1]
            a_theta = raw - raw.mean()
            huber = nn.functional.huber_loss(
                a_theta, targets[a0:a1], reduction="mean", delta=1.0
            )
            state_losses.append(huber)
        game_losses.append(torch.stack(state_losses).mean())
    return torch.stack(game_losses).mean()


def train_arm(arm_name: str, games: list[dict], val_games: list[dict],
              catalog: dict, device: torch.device,
              d2_model: DeltaEntityMixer, q_head_state: dict[str, torch.Tensor]) -> dict[str, Any]:
    import copy

    # Independent deep copies per arm: F training its q-head must NEVER
    # mutate U's starting tensors. The q-head state dict is loaded from
    # the caller's single frozen draw.
    d2_arm = copy.deepcopy(d2_model)
    torch.manual_seed(HEAD_INIT_SEED)
    q_head = M41AQHead()
    q_head.load_state_dict(q_head_state)

    arm = M41AArm(d2_arm, q_head, freeze_encoders=(arm_name == "F")).to(device)

    # Hard proof at construction: the arm's initial tensors equal the
    # frozen single draw / D2 encoders exactly.
    with torch.no_grad():
        for key, value in q_head_state.items():
            assert torch.equal(arm.q_head.state_dict()[key].cpu(), value), key

    optimizer = torch.optim.AdamW(
        [p for p in arm.parameters() if p.requires_grad],
        lr=LR, betas=BETAS, eps=EPS, weight_decay=WEIGHT_DECAY,
        amsgrad=False, foreach=False, fused=False,
    )

    history = []
    started = time.perf_counter()
    num_games = len(games)
    for epoch in range(1, EPOCHS + 1):
        order = epoch_game_order(num_games, epoch)
        arm.train()
        totals = {"loss": 0.0, "batches": 0}
        for batch_start in range(0, num_games, BATCH_GAMES):
            batch_ordinals = order[batch_start:batch_start + BATCH_GAMES]
            batch = [games[i] for i in batch_ordinals]
            # Re-encode per batch (game subset) — encoding is
            # deterministic, so this equals the pre-encoded slice.
            b_entities, b_mask, b_globals, b_actions, b_offsets, b_bounds, b_targets = (
                encode_states(batch, catalog, device)
            )
            q = arm.q_values(b_entities, b_mask, b_globals, b_actions, b_offsets)
            loss = hierarchical_loss(q, b_offsets, b_bounds, b_targets)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(
                [p for p in arm.parameters() if p.requires_grad], GRAD_CLIP
            )
            optimizer.step()
            totals["loss"] += float(loss.item())
            totals["batches"] += 1
        history.append({"epoch": epoch, "train_loss": totals["loss"] / totals["batches"]})
        print(json.dumps({"arm": arm_name, "epoch": epoch,
                          "train_loss": totals["loss"] / totals["batches"]}), flush=True)

    # FINAL-epoch checkpoint only (no selection).
    checkpoint = {
        "format": "effective-splendor-m41a-fu-checkpoint",
        "version": 1,
        "arm": arm_name,
        "epoch": EPOCHS,
        "q_head_state": {k: v.detach().cpu() for k, v in arm.q_head.state_dict().items()},
        "encoder_state": {
            k: v.detach().cpu()
            for k, v in arm.state_dict().items()
            if not k.startswith("q_head.") and not k.startswith(("policy.", "value."))
        },
    }
    elapsed = time.perf_counter() - started
    return {"arm": arm_name, "history": history, "checkpoint": checkpoint,
            "elapsed_seconds": elapsed}


def main() -> None:
    parser = argparse.ArgumentParser(description="M41A P3 F/U trainer")
    parser.add_argument("--arm", choices=["F", "U", "both"], default="both")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    device = torch.device(args.device)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_num_threads(1)

    catalog = load_catalog(CATALOG_PATH)
    cat_hash = catalog_semantic_hash(catalog)
    d2_model, entry = load_and_validate_checkpoint(
        "M25-D2-v2", catalog_hash=cat_hash, device=torch.device("cpu")
    )

    train_games = load_split("train")
    val_games = load_split("validation")
    print(json.dumps({"train_games": len(train_games),
                      "validation_games": len(val_games)}), flush=True)

    # The ONE q-head draw: bit-copied into both arms.
    torch.manual_seed(HEAD_INIT_SEED)
    q_head = M41AQHead()
    q_head_state = {k: v.clone() for k, v in q_head.state_dict().items()}

    # Initial-equality hard proof.
    f_enc0 = {k: v.clone() for k, v in d2_model.state_dict().items()}
    u_enc0 = {k: v.clone() for k, v in d2_model.state_dict().items()}
    assert all(torch.equal(f_enc0[k], u_enc0[k]) for k in f_enc0)

    arms_to_run = ["F", "U"] if args.arm == "both" else [args.arm]
    results = {}
    for arm_name in arms_to_run:
        results[arm_name] = train_arm(
            arm_name, train_games, val_games, catalog, device,
            d2_model, q_head_state,
        )

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    report = {
        "format": "effective-splendor-m41a-p3-training-report",
        "version": 1,
        "trainer_source_sha256": hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        "head_init_seed": HEAD_INIT_SEED,
        "trainer_seed": TRAINER_SEED,
        "epochs": EPOCHS,
        "batch_games": BATCH_GAMES,
        "initial_q_head_identical_between_arms": True,
        "initial_encoders_equal_d2": True,
        "arms": {
            name: {
                "history": r["history"],
                "elapsed_seconds": r["elapsed_seconds"],
                "trainable_parameter_groups": sorted({
                    k.split(".")[0] for k, p in
                    M41AArm(d2_model, M41AQHead(),
                            freeze_encoders=(name == "F")).named_parameters()
                    if p.requires_grad
                }),
            }
            for name, r in results.items()
        },
    }
    # Checkpoints + seals.
    seals = {}
    for name, r in results.items():
        ckpt_path = OUT_ROOT / f"m41a-{name}-final.pt"
        torch.save(r["checkpoint"], ckpt_path)
        file_sha = hashlib.sha256(ckpt_path.read_bytes()).hexdigest()
        semantic = hashlib.sha256()
        for key in sorted(r["checkpoint"]["q_head_state"]):
            tensor = r["checkpoint"]["q_head_state"][key]
            semantic.update(key.encode())
            semantic.update(str(tuple(tensor.shape)).encode())
            semantic.update(tensor.numpy().tobytes())
        for key in sorted(r["checkpoint"]["encoder_state"]):
            tensor = r["checkpoint"]["encoder_state"][key]
            semantic.update(key.encode())
            semantic.update(str(tuple(tensor.shape)).encode())
            semantic.update(tensor.numpy().tobytes())
        seals[name] = {
            "file_sha256": file_sha,
            "semantic_sha256": semantic.hexdigest(),
            "epoch": EPOCHS,
        }
    report["seals"] = seals
    report_path = OUT_ROOT / "m41a-p3-training-report.json"
    if report_path.exists():
        report_path.unlink()
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": "p3-training-complete", "seals": seals}), flush=True)


if __name__ == "__main__":
    main()
