"""M43A: Successor dataset materialization and caching with branch-level provenance (Repair 1).

Binds for every branch:
  - M41 run-contract SHA
  - source replay SHA
  - branch replay SHA
  - branch report SHA
  - state probe SHA
  - state manifest SHA
  - source state hash
  - source observation hash
  - root actor
  - canonical action identity hash
  - post-state hash
  - post-observation hash
  - terminal rank and target y in {0.0, 1.0}

Enforces fail-closed cache loading: validates all manifest records, file SHAs,
canonical manifest hash, and loaded tensor counts.
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
RUN_CONTRACT_PATH = CORPUS_ROOT / "run-contract.json"
EXPECTED_RUN_CONTRACT_SHA256 = "2a449550c179425a58fb536851c8f78d907fa227b8de58f2704357a0ec716563"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_one_state(sdir: Path, source_replay_path: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    # 1. Source and manifest file SHAs
    source_replay_sha = file_sha256(source_replay_path)
    state_probe_file = sdir / "state-probe.json"
    state_manifest_file = sdir / "state-manifest.json"

    if not state_probe_file.is_file():
        raise FileNotFoundError(f"Missing state-probe.json at {state_probe_file}")
    if not state_manifest_file.is_file():
        raise FileNotFoundError(f"Missing state-manifest.json at {state_manifest_file}")

    state_probe_sha = file_sha256(state_probe_file)
    state_manifest_sha = file_sha256(state_manifest_file)

    # 2. Call Rust exporter (reconstructs s' and validates H0/H1/H2 fail-closed)
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

    # 3. Read state manifest for legal actions and M41 G returns
    manifest = json.loads(state_manifest_file.read_text(encoding="utf-8"))
    actions_manifest = sorted(manifest["actions"], key=lambda e: e["action_index"])
    g_returns = [float(e["acting_seat_return"]) for e in actions_manifest]

    # Pre-encode successor observations and assemble branch provenance records
    entities_list = []
    masks_list = []
    globals_list = []
    targets_list = []
    actions_list = []
    branch_provenance_records = []

    for succ in successors:
        action_idx = succ["action_index"]
        obs = succ["post_action_observation"]
        target_y = float(succ["target_y"])
        act = succ["forced_action"]
        post_state_hash = succ["post_action_state_hash"]
        post_obs_hash = succ["post_action_observation_hash"]

        # Branch replay and report files
        action_dir = sdir / f"action-{action_idx:03d}"
        br_replay_file = action_dir / "replay.json"
        br_report_file = action_dir / "report.json"

        if not br_replay_file.is_file():
            raise FileNotFoundError(f"Missing branch replay at {br_replay_file}")
        if not br_report_file.is_file():
            raise FileNotFoundError(f"Missing branch report at {br_report_file}")

        br_replay_sha = file_sha256(br_replay_file)
        br_report_sha = file_sha256(br_report_file)

        action_canonical_bytes = json.dumps(act, sort_keys=True, separators=(",", ":")).encode("utf-8")
        canonical_action_hash = hashlib.sha256(action_canonical_bytes).hexdigest()

        branch_provenance_records.append({
            "action_index": action_idx,
            "source_replay_sha256": source_replay_sha,
            "branch_replay_sha256": br_replay_sha,
            "branch_report_sha256": br_report_sha,
            "state_probe_sha256": state_probe_sha,
            "state_manifest_sha256": state_manifest_sha,
            "source_state_hash": source_state_hash,
            "source_observation_hash": source_obs_hash,
            "root_actor": root_actor,
            "canonical_action_hash": canonical_action_hash,
            "post_state_hash": post_state_hash,
            "post_observation_hash": post_obs_hash,
            "target_y": target_y,
        })

        enc = encode_observation(obs, catalog)
        entities_list.append(enc.entities)
        masks_list.append(enc.mask)
        globals_list.append(enc.global_features)
        targets_list.append(target_y)
        actions_list.append(act)

    entities_tensor = torch.stack(entities_list)
    masks_tensor = torch.stack(masks_list)
    globals_tensor = torch.stack(globals_list)
    targets_tensor = torch.tensor(targets_list, dtype=torch.float32)

    # Encode source observation (for PRESTATE ablation)
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
        "branch_provenance": branch_provenance_records,
    }


def export_split_successors(split: str, catalog: dict[str, Any], max_workers: int = 6) -> list[dict[str, Any]]:
    assert_split_allowed(split)
    split_dir = DATA_ROOT / split
    split_file = split_dir / "successor_games.pt"
    manifest_file = split_dir / "successor_manifest.json"

    # Contract assertion on M41 run-contract SHA
    actual_run_contract_sha = file_sha256(RUN_CONTRACT_PATH)
    if actual_run_contract_sha != EXPECTED_RUN_CONTRACT_SHA256:
        raise RuntimeError(
            f"M41 run-contract SHA mismatch: expected {EXPECTED_RUN_CONTRACT_SHA256}, "
            f"found {actual_run_contract_sha}"
        )

    cat_sem_hash = catalog_semantic_hash(catalog)

    # If cache exists, strictly validate fail-closed
    if split_file.is_file() and manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if (
                manifest.get("run_contract_sha256") == EXPECTED_RUN_CONTRACT_SHA256
                and manifest.get("catalog_semantic_hash") == cat_sem_hash
                and file_sha256(split_file) == manifest.get("data_file_sha256")
            ):
                # Verify canonical manifest digest
                canonical_manifest_bytes = json.dumps(
                    manifest["branch_records"], sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                recomputed_digest = hashlib.sha256(canonical_manifest_bytes).hexdigest()
                if recomputed_digest == manifest.get("split_canonical_manifest_sha256"):
                    games = torch.load(split_file, map_location="cpu", weights_only=False)
                    total_loaded_branches = sum(
                        len(s["targets"]) for g in games for s in g["states"]
                    )
                    if total_loaded_branches == manifest.get("branches_count"):
                        print(
                            f"Validated cached successor dataset for {split} from {split_file} "
                            f"({len(games)} games, {total_loaded_branches} branches, fail-closed PASS).",
                            flush=True,
                        )
                        return games
        except Exception as e:
            print(f"Cache validation failed ({e}), rebuilding fresh...", flush=True)

    print(f"Rebuilding fresh successor dataset for {split} from M41 corpus...", flush=True)
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

    # Group by game and aggregate branch provenance
    exported_games = []
    all_branch_records = []
    total_branches = 0
    total_states = 0

    for gdir in games_dirs:
        gname = gdir.name
        game_states = []
        for sdir in sorted(gdir.glob("branch-ply*")):
            sname = sdir.name
            st = results_by_sdir[(gname, sname)]
            game_states.append(st)
            total_branches += st["n_branches"]
            total_states += 1
            for rec in st["branch_provenance"]:
                all_branch_records.append({
                    "game_id": gname,
                    "ply": st["ply"],
                    **rec,
                })
        exported_games.append({
            "game_id": gname,
            "states": game_states,
        })

    # Save data tensor first to get data_file_sha256
    split_dir.mkdir(parents=True, exist_ok=True)
    torch.save(exported_games, split_file)
    data_sha = file_sha256(split_file)

    canonical_manifest_bytes = json.dumps(
        all_branch_records, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    split_manifest_sha = hashlib.sha256(canonical_manifest_bytes).hexdigest()

    manifest_data = {
        "format": "effective-splendor-m43a-successor-branch-manifest",
        "version": 2,
        "split": split,
        "exported_at": time.time(),
        "run_contract_sha256": EXPECTED_RUN_CONTRACT_SHA256,
        "catalog_semantic_hash": cat_sem_hash,
        "data_file_sha256": data_sha,
        "games_count": len(exported_games),
        "states_count": total_states,
        "branches_count": total_branches,
        "split_canonical_manifest_sha256": split_manifest_sha,
        "branch_records": all_branch_records,
    }
    manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    elapsed = time.time() - t0
    print(
        f"Rebuilt {split} successor cache in {elapsed:.1f}s: {len(exported_games)} games, "
        f"{total_states} states, {total_branches} branches, manifest SHA: {split_manifest_sha[:16]}...",
        flush=True,
    )
    return exported_games


def load_successor_split(split: str, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    return export_split_successors(split, catalog)


if __name__ == "__main__":
    cat = load_catalog(CATALOG_PATH)
    train_data = export_split_successors("train", cat)
    val_data = export_split_successors("validation", cat)
    print("Done materializing train and val successor datasets with branch-level provenance.")
