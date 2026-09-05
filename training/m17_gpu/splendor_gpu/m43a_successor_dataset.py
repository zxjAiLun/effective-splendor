"""M43A: Successor dataset materialization and caching.

Extracts immediate child successor observations s' = T(s, a) and terminal
targets y in {0.0, 1.0} across M41A audited branch corpus:
  - Train: 192 games, 576 states, 12,249 legal-action branches
  - Validation: 48 games, 144 states, 3,258 legal-action branches

Viewer is strictly locked to root_actor (preserving private knowledge).
Encodes states into torch tensors for high-speed training and evaluation.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import torch

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "training/m17_gpu"))

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.encoding import encode_observation
from splendor_gpu.m41a_train import ALLOWED_SPLITS, CORPUS_ROOT, assert_split_allowed

SPLN = REPO / "target/release/splendor.exe"
CATALOG_PATH = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
DATA_ROOT = REPO / "local-artifacts/m43a-successor-data"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_one_state(sdir: Path, source_replay_path: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    cmd = [
        str(SPLN), "m43a-export-successors",
        "--state-dir", str(sdir),
        "--source-replay", str(source_replay_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"m43a-export-successors failed on {sdir}: {res.stderr}")

    data = json.loads(res.stdout)
    branch_ply = data["branch_ply"]
    root_actor = data["root_actor"]
    source_state_hash = data["source_state_hash"]
    source_obs_hash = data["source_observation_hash"]
    successors = data["successors"]

    # Read state probe for legal actions and M41 G returns
    manifest = json.loads((sdir / "state-manifest.json").read_text(encoding="utf-8"))
    actions_manifest = sorted(manifest["actions"], key=lambda e: e["action_index"])
    g_returns = [float(e["acting_seat_return"]) for e in actions_manifest]

    # Pre-encode successor observations
    entities_list = []
    masks_list = []
    globals_list = []
    targets_list = []
    actions_list = []

    for succ in successors:
        obs = succ["post_action_observation"]
        target_y = float(succ["target_y"])
        act = succ["forced_action"]

        enc = encode_observation(obs, catalog)
        entities_list.append(enc.entities)
        masks_list.append(enc.mask)
        globals_list.append(enc.global_features)
        targets_list.append(target_y)
        actions_list.append(act)

    entities_tensor = torch.stack(entities_list)  # (N, 31, 32)
    masks_tensor = torch.stack(masks_list)        # (N, 31)
    globals_tensor = torch.stack(globals_list)    # (N, 40)
    targets_tensor = torch.tensor(targets_list, dtype=torch.float32)  # (N,)

    # Also encode source observation (for PRESTATE ablation)
    probe_legal_out = subprocess.run(
        [
            str(SPLN), "probe-legal", "--emit-observation",
            "--source-replay", str(source_replay_path),
            "--branch-ply", str(branch_ply),
        ],
        capture_output=True, text=True, check=True
    )
    src_doc = json.loads(probe_legal_out.stdout)
    src_obs = src_doc["observation"]
    enc_src = encode_observation(src_obs, catalog)

    return {
        "ply": branch_ply,
        "root_actor": root_actor,
        "source_state_hash": source_state_hash,
        "source_obs_hash": source_obs_hash,
        "n_branches": len(successors),
        "entities": entities_tensor,
        "mask": masks_tensor,
        "global_features": globals_tensor,
        "targets": targets_tensor,
        "g_returns": g_returns,
        "actions": actions_list,
        "src_entities": enc_src.entities,
        "src_mask": enc_src.mask,
        "src_global_features": enc_src.global_features,
        "src_obs": src_obs,
    }


def export_split_successors(split: str, catalog: dict[str, Any], max_workers: int = 6) -> list[dict[str, Any]]:
    assert_split_allowed(split)
    split_dir = DATA_ROOT / split
    split_file = split_dir / "successor_games.pt"
    manifest_file = split_dir / "successor_manifest.json"

    if split_file.is_file() and manifest_file.is_file():
        print(f"Loading cached successor dataset for {split} from {split_file}...", flush=True)
        return torch.load(split_file, map_location="cpu", weights_only=False)

    print(f"Exporting successor dataset for {split}...", flush=True)
    t0 = time.time()
    games_dirs = sorted(list((CORPUS_ROOT / split).glob("game-*")))

    tasks = []
    for gdir in games_dirs:
        rpl_path = gdir / "replay.json"
        for sdir in sorted(gdir.glob("branch-ply*")):
            tasks.append((gdir.name, sdir, rpl_path))

    results_by_sdir = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(process_one_state, sdir, rpl_path, catalog): (gname, sdir.name)
            for gname, sdir, rpl_path in tasks
        }
        for future in concurrent.futures.as_completed(future_to_task):
            gname, sname = future_to_task[future]
            try:
                res = future.result()
                results_by_sdir[(gname, sname)] = res
            except Exception as e:
                print(f"Failed processing {gname}/{sname}: {e}", flush=True)
                raise e

    # Group by game
    exported_games = []
    manifest_records = []
    total_branches = 0

    for gdir in games_dirs:
        gname = gdir.name
        game_states = []
        for sdir in sorted(gdir.glob("branch-ply*")):
            sname = sdir.name
            st = results_by_sdir[(gname, sname)]
            game_states.append(st)
            total_branches += st["n_branches"]
            manifest_records.append({
                "game_id": gname,
                "ply": st["ply"],
                "root_actor": st["root_actor"],
                "source_state_hash": st["source_state_hash"],
                "source_obs_hash": st["source_obs_hash"],
                "branches_count": st["n_branches"],
            })
        exported_games.append({
            "game_id": gname,
            "states": game_states,
        })

    elapsed = time.time() - t0
    print(
        f"Exported {len(exported_games)} games, {len(manifest_records)} states, "
        f"{total_branches} branches in {elapsed:.1f}s.",
        flush=True,
    )

    split_dir.mkdir(parents=True, exist_ok=True)
    torch.save(exported_games, split_file)
    manifest_data = {
        "format": "effective-splendor-m43a-successor-manifest",
        "version": 1,
        "split": split,
        "exported_at": time.time(),
        "games_count": len(exported_games),
        "states_count": len(manifest_records),
        "branches_count": total_branches,
        "manifest_sha256": hashlib.sha256(
            json.dumps(manifest_records, sort_keys=True).encode()
        ).hexdigest(),
        "states": manifest_records,
    }
    manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    return exported_games


def load_successor_split(split: str, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    return export_split_successors(split, catalog)


if __name__ == "__main__":
    cat = load_catalog(CATALOG_PATH)
    train_data = export_split_successors("train", cat)
    val_data = export_split_successors("validation", cat)
    print("Done materializing train and validation successor datasets.")
