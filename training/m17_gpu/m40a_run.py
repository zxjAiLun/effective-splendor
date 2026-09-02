"""M40A formal orchestrator CLI: init / pretrain-b / collect-cycle / train-cycle /
evaluate. Deterministic; every schedule descends from m40a_contract."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("PYTHONPATH", str(Path(__file__).resolve().parent))

import torch

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m39a_contract import file_sha256
from splendor_gpu.m40a_constants import LEAGUE_ORDER
from splendor_gpu.m40a_contract import (
    CATALOG_REL,
    D2_CHECKPOINT_REL,
    D2_CHECKPOINT_SHA256,
    build_plan,
    checkpoint_semantic_hash,
    crn_schedule_hash,
    online_scheduled_game,
    online_seed,
    plan_hash as m40a_plan_hash,
    validate_plan,
)
from splendor_gpu.m40a_constants import HEAD_INIT_SEED, LR_WAYPOINTS
from splendor_gpu.m40a_gates import (
    evaluate_anchor,
    evaluate_h1,
    evaluate_league,
    formal_checkpoint_guard,
)
from splendor_gpu.m40a_model import (
    M40AModel,
    copy_head_state,
    head_state_semantic_hash,
    initialize_predictive_heads,
    load_d2_actor,
    load_head_state,
)
from splendor_gpu.m40a_dataset import frozen_split, split_manifest_hash

RUN_ROOT = Path("local-artifacts/m40a-run")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPLENDOR = Path("target/release/splendor.exe")
PLAN_PATH = Path("benchmarks/m40a-predictive-critic-warmstart.plan.json")
FROZEN_CRN_SCHEDULE_HASH = crn_schedule_hash()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _save_checkpoint(
    path: Path,
    model: M40AModel,
    *,
    arm: str,
    cycle: int,
    parent_hash: str | None,
    plan_digest: str,
    catalog_hash: str,
    optimizer_state: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = {
        "format": "effective-splendor-m40a-checkpoint",
        "version": 1,
        "model_id": "m40a-predictive-critic-warmstart-v1",
        "design_sha": "09fd8ec",
        "arm": arm,
        "cycle": cycle,
        "plan_hash": plan_digest,
        "parent_checkpoint_hash": parent_hash,
        "catalog_hash": catalog_hash,
        "head_init_seed": HEAD_INIT_SEED,
        "value_semantics": "V = p_win - p_loss",
        "parameter_count": sum(p.numel() for p in model.parameters()),
    }
    state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
    semantic = checkpoint_semantic_hash(metadata, state)
    payload = {
        "metadata": metadata,
        "state_dict": state,
        "checkpoint_hash": semantic,
        "optimizer_state_dict": optimizer_state,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    torch.save(payload, temporary)
    os.replace(temporary, path)
    return {
        "path": str(path),
        "checkpoint_hash": semantic,
        "checkpoint_file_sha256": file_sha256(path),
        "cycle": cycle,
        "arm": arm,
    }


def _load_checkpoint(path: Path) -> tuple[M40AModel, dict[str, Any]]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    from splendor_gpu.m40a_contract import checkpoint_semantic_hash

    actual = checkpoint_semantic_hash(payload["metadata"], payload["state_dict"])
    if actual != payload["checkpoint_hash"]:
        raise ValueError(f"checkpoint semantic hash mismatch at {path}")
    model = M40AModel()
    model.load_state_dict(payload["state_dict"], strict=True)
    return model, payload


def _start_server(checkpoint: Path, file_sha: str, digest: str, device: str) -> subprocess.Popen:
    ready = checkpoint.parent / f"server-ready-{int(time.time())}.json"
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "splendor_gpu.m40a_server",
            "--checkpoint", str(checkpoint),
            "--checkpoint-sha256", file_sha,
            "--plan-hash", digest,
            "--catalog", CATALOG_REL,
            "--device", device,
            "--ready-file", str(ready),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=dict(os.environ),
    )
    deadline = time.time() + 180
    while not ready.is_file():
        if proc.poll() is not None:
            raise RuntimeError(f"server failed: {proc.stderr.read()[:400]}")
        if time.time() > deadline:
            raise TimeoutError("server startup timeout")
        time.sleep(0.2)
    return proc, ready


def cmd_init(args: argparse.Namespace) -> None:
    plan = build_plan()
    digest = validate_plan(plan)
    catalog = load_catalog(Path(CATALOG_REL))
    cat_hash = catalog_semantic_hash(catalog)
    if plan["catalog"]["semantic_hash"] != cat_hash:
        raise ValueError("catalog semantic hash mismatch")

    shared = M40AModel()
    load_d2_actor(shared, Path(D2_CHECKPOINT_REL), D2_CHECKPOINT_SHA256)
    initialize_predictive_heads(shared, HEAD_INIT_SEED)

    head_state = copy_head_state(shared)
    for arm in ("A", "B"):
        model = copy.deepcopy(shared)
        load_head_state(model, head_state)
        info = _save_checkpoint(
            RUN_ROOT / f"{arm}-cycle0.pt",
            model,
            arm=arm, cycle=0, parent_hash=None,
            plan_digest=digest, catalog_hash=cat_hash, optimizer_state=None,
        )
        print(json.dumps(info))
    print(json.dumps({
        "status": "init-complete",
        "plan_hash": digest,
        "shared_head_hash": head_state_semantic_hash(shared),
        "crn_schedule_hash": FROZEN_CRN_SCHEDULE_HASH,
    }))


def _collect_arm_cycle(
    *,
    arm: str,
    cycle: int,
    checkpoint: Path,
    file_sha: str,
    semantic_hash: str,
    digest: str,
    device: str,
    out_dir: Path,
) -> dict[str, Any]:
    server, ready = _start_server(checkpoint, file_sha, digest, device)
    try:
        entries = [online_scheduled_game(g) for g in range((cycle - 1) * 512, cycle * 512)]
        sources = []
        for entry in entries:
            game_index = entry["game_index"]
            game_dir = out_dir / "games" / f"game-{game_index:06d}"
            if (game_dir / "arena-report.json").is_file():
                # resume
                sources.append(_manifest_entry(game_dir, game_index))
                continue
            game_dir.mkdir(parents=True, exist_ok=True)
            sidecars = {
                seat: game_dir / f"seat-{seat}.sidecar.json"
                for seat in entry["learner_seats"]
            }
            agents = []
            for seat in (0, 1):
                if seat in entry["learner_seats"]:
                    agents.append({
                        "program": sys.executable,
                        "args": [
                            "-m", "splendor_gpu.m40a_agent",
                            "--checkpoint-sha256", file_sha,
                            "--plan-hash", digest,
                            "--arm", arm,
                            "--game-index", str(game_index),
                            "--sidecar-out", str(sidecars[seat]),
                            "--server-url", f"127.0.0.1:{json.loads(ready.read_text(encoding='utf-8'))['port']}",
                            "--server-ready", str(ready),
                            "--action-selection", "categorical",
                        ],
                    })
                else:
                    from splendor_gpu.m39a_collect import _opponent_agent

                    agents.append(_opponent_agent(
                        entry["opponent"],
                        splendor=SPLENDOR,
                        catalog=Path(CATALOG_REL),
                        action_seed=20_260_830 + game_index,
                        device=device,
                    ))
            config = {
                "game_id": f"m40a-online-{arm}-{game_index:06d}",
                "seed": online_seed(game_index),
                "handshake_timeout_ms": 10_000,
                "move_timeout_ms": 30_000,
                "shutdown_grace_ms": 2_000,
                "agents": agents,
            }
            _atomic_json(game_dir / "arena-config.json", config)
            completed = subprocess.run(
                [str(SPLENDOR), "run-rollout", "--max-plies", "150",
                 "--config", str(game_dir / "arena-config.json"),
                 "--report-out", str(game_dir / "arena-report.json"),
                 "--replay-out", str(game_dir / "replay.json"),
                 "--prefix-out", str(game_dir / "rollout-prefix.json")],
                capture_output=True, text=True, timeout=60 * 60, check=False)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"game {game_index} rc={completed.returncode}: "
                    f"{completed.stderr[:300]}"
                )
            print(json.dumps({"game_index": game_index, "status": "completed"}), flush=True)
            sources.append(_manifest_entry(game_dir, game_index))
        return sources
    finally:
        server.terminate()
        server.wait(timeout=15)


def _manifest_entry(game_dir: Path, game_index: int) -> dict[str, Any]:
    prefix = {
        "prefix_path": f"games/game-{game_index:06d}/rollout-prefix.json"
    } if (game_dir / "rollout-prefix.json").is_file() else {}
    return {
        "game_index": game_index,
        "report_path": f"games/game-{game_index:06d}/arena-report.json",
        "replay_path": f"games/game-{game_index:06d}/replay.json",
        "sidecar_paths": [
            p.name and f"games/game-{game_index:06d}/{p.name}"
            for p in sorted(game_dir.glob("seat-*.sidecar.json"))
        ],
        **prefix,
    }


def ppo_parent_checkpoint(arm: str, cycle: int) -> Path:
    """The ONE canonical PPO parent resolution — shared by collect-cycle
    and train-cycle, with no fallback path.

    A cycle 1 -> A-cycle0.pt
    B cycle 1 -> B-cycle0-pretrained.pt  (REQUIRED; never B-cycle0.pt)
    A/B cycle N>1 -> {arm}-cycle{N-1}.pt
    """
    if arm not in ("A", "B"):
        raise ValueError(f"invalid arm {arm!r}")
    if cycle not in (1, 2, 3, 4):
        raise ValueError(f"invalid cycle {cycle}")
    if cycle == 1:
        if arm == "A":
            path = RUN_ROOT / "A-cycle0.pt"
        else:
            path = RUN_ROOT / "B-cycle0-pretrained.pt"
        if not path.is_file():
            if arm == "B":
                raise FileNotFoundError(
                    f"B cycle-1 requires the pretrained parent {path} — "
                    "run pretrain-b first; falling back to B-cycle0.pt is "
                    "forbidden (it would erase the warm-start treatment)"
                )
            raise FileNotFoundError(f"parent checkpoint missing: {path}")
        return path
    path = RUN_ROOT / f"{arm}-cycle{cycle - 1}.pt"
    if not path.is_file():
        raise FileNotFoundError(f"parent checkpoint missing: {path}")
    return path


def _verify_b_pretrain_provenance(digest: str, cat_hash: str) -> None:
    """Full treatment-entry provenance for B cycle 1, checked before any
    Arena work begins."""
    report_path = RUN_ROOT / "b-pretrain-report.json"
    if not report_path.is_file():
        raise FileNotFoundError(
            f"formal B pretrain report missing: {report_path}"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ckpt = RUN_ROOT / "B-cycle0-pretrained.pt"
    if not ckpt.is_file():
        raise FileNotFoundError(f"{ckpt} missing")
    _, payload = _load_checkpoint(ckpt)
    metadata = payload["metadata"]
    info = report["b_pretrain_checkpoint"]
    if info["checkpoint_hash"] != payload["checkpoint_hash"]:
        raise ValueError("report checkpoint semantic hash != actual B-pretrained")
    if info["checkpoint_file_sha256"] != file_sha256(ckpt):
        raise ValueError("report checkpoint file SHA != actual B-pretrained")
    if metadata["arm"] != "B":
        raise ValueError("B-pretrained metadata arm mismatch")
    if int(metadata["cycle"]) != 0:
        raise ValueError("B-pretrained metadata cycle mismatch")
    if metadata["plan_hash"] != digest:
        raise ValueError("B-pretrained plan hash mismatch")
    if metadata["catalog_hash"] != cat_hash:
        raise ValueError("B-pretrained catalog hash mismatch")
    b0, b0_payload = _load_checkpoint(RUN_ROOT / "B-cycle0.pt")
    del b0
    if metadata["parent_checkpoint_hash"] != b0_payload["checkpoint_hash"]:
        raise ValueError(
            "B-pretrained parent hash != B-cycle0 semantic hash — "
            "the shared-init chain is broken"
        )


def cmd_collect_cycle(args: argparse.Namespace) -> None:
    arm = args.arm
    cycle = args.cycle
    plan = build_plan()
    digest = validate_plan(plan)
    catalog = load_catalog(Path(CATALOG_REL))
    cat_hash = catalog_semantic_hash(catalog)
    parent_cycle = cycle - 1
    ckpt = ppo_parent_checkpoint(arm, cycle)
    if arm == "B" and cycle == 1:
        _verify_b_pretrain_provenance(digest, cat_hash)
    _, payload = _load_checkpoint(ckpt)
    if payload["metadata"]["arm"] != arm:
        raise ValueError("checkpoint arm mismatch")
    # cycle-1 parents are metadata-cycle 0 (A) or 0 (B-pretrained);
    # cycles N>1 parents are cycle N-1.
    if int(payload["metadata"]["cycle"]) != parent_cycle:
        raise ValueError("checkpoint cycle mismatch")

    out_dir = RUN_ROOT / f"arm-{arm}" / f"cycle-{cycle}"
    sources = _collect_arm_cycle(
        arm=arm, cycle=cycle,
        checkpoint=ckpt, file_sha=file_sha256(ckpt),
        semantic_hash=payload["checkpoint_hash"],
        digest=digest, device=args.device, out_dir=out_dir,
    )
    manifest = {
        "format": "effective-splendor-m40a-online-materialization-manifest",
        "version": 1,
        "plan_hash": digest,
        "design_sha": "09fd8ec",
        "arm": arm,
        "mode": "complete",
        "checkpoint_sha256": file_sha256(ckpt),
        "checkpoint_hash": payload["checkpoint_hash"],
        "checkpoint_cycle": parent_cycle,
        "cycle": cycle,
        "ply_cap": 150,
        "games": sources,
    }
    manifest_path = out_dir / "online-manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    _atomic_json(manifest_path, manifest)
    batch_out = out_dir / "batch.json"
    if batch_out.exists():
        batch_out.unlink()
    completed = subprocess.run(
        [str(SPLENDOR), "m40a-materialize-online",
         "--plan", str(PLAN_PATH),
         "--manifest", str(manifest_path), "--out", str(batch_out)],
        capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"online materialization failed: {completed.stderr[:300]}")
    print(json.dumps({
        "status": "collect-cycle-complete",
        "arm": arm, "cycle": cycle,
        "games": len(sources),
        "batch": str(batch_out),
        "batch_sha256": file_sha256(batch_out),
        "crn_schedule_hash": FROZEN_CRN_SCHEDULE_HASH,
    }))


def cmd_pretrain_b(args: argparse.Namespace) -> None:
    plan = build_plan()
    digest = validate_plan(plan)
    catalog = load_catalog(Path(CATALOG_REL))
    cat_hash = catalog_semantic_hash(catalog)

    a0, a0_payload = _load_checkpoint(RUN_ROOT / "A-cycle0.pt")
    b0, b0_payload = _load_checkpoint(RUN_ROOT / "B-cycle0.pt")
    # FULL fork proof (not just head hash): complete state_dicts equal.
    def _dicts_equal(x, y):
        if set(x) != set(y):
            return False
        return all(torch.equal(x[k], y[k]) for k in x)
    if not _dicts_equal(a0_payload["state_dict"], b0_payload["state_dict"]):
        raise ValueError("A/B cycle-0 full state_dicts differ — fork was not shared")
    b0_parent_semantic = b0_payload["checkpoint_hash"]

    from splendor_gpu.m40a_pretrain import pretrain, sanity_metrics

    # Load the enriched offline dataset: ALL EIGHT batch files are REQUIRED
    # (fail-closed on any missing file); each file's SHA is recorded.
    records = []
    batch_identities = []
    for cycle in range(1, 9):
        batch_path = RUN_ROOT / "offline-source" / f"cycle-{cycle}-enriched.json"
        if not batch_path.is_file():
            raise FileNotFoundError(
                f"offline source incomplete: {batch_path} missing — all 8 "
                "enriched batches are required before formal pretraining"
            )
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        records.extend(batch["records"])
        batch_identities.append({
            "cycle": cycle,
            "path": str(batch_path),
            "file_sha256": file_sha256(batch_path),
            "games": len(batch["games"]),
            "records": len(batch["records"]),
        })
    if len(records) != 182_157:
        raise ValueError(
            f"offline source record count {len(records)} != 182,157"
        )
    # Ordered dataset identity: SHA-256 over the canonical ordered list of
    # the 8 batch file hashes.
    identity_input = json.dumps(
        [entry["file_sha256"] for entry in batch_identities],
        separators=(",", ":"),
    ).encode("utf-8")
    offline_dataset_identity = hashlib.sha256(identity_input).hexdigest()

    split = frozen_split(sorted({int(r["game_index"]) for r in records}), {2785})
    if split_manifest_hash(split) != plan["pretrain"]["expected_split_manifest_hash"]:
        raise ValueError("split manifest hash mismatch")
    train_ids = set(split["train"])
    train_records = [r for r in records if int(r["game_index"]) in train_ids]
    validation_records = [r for r in records if int(r["game_index"]) not in train_ids]

    input_head_hash = head_state_semantic_hash(b0)
    input_state = {k: v.clone() for k, v in b0.state_dict().items()}
    device = torch.device(args.device)
    b0.to(device)
    started = time.perf_counter()
    pretrain_report = pretrain(
        model=b0, records=train_records, device=device,
        report_path=RUN_ROOT / "b-pretrain-history.json",
    )
    metrics = sanity_metrics(model=b0, validation_records=validation_records, device=device)
    b0.to("cpu")
    # Post-pretraining proofs: actor/trunk/policy unchanged; heads changed.
    output_state = b0.state_dict()
    trunk_keys = [k for k in input_state if not k.startswith("heads.")]
    trunk_unchanged = all(
        torch.equal(input_state[k], output_state[k]) for k in trunk_keys
    )
    if not trunk_unchanged:
        raise ValueError("B pretraining modified actor/trunk/policy tensors")
    head_keys = [k for k in input_state if k.startswith("heads.")]
    heads_changed = any(
        not torch.equal(input_state[k], output_state[k]) for k in head_keys
    )
    if not heads_changed:
        raise ValueError("B pretraining changed no predictive-head tensor")
    info = _save_checkpoint(
        RUN_ROOT / "B-cycle0-pretrained.pt", b0,
        arm="B", cycle=0, parent_hash=b0_parent_semantic,
        plan_digest=digest, catalog_hash=cat_hash, optimizer_state=None,
    )
    report = {
        "format": "effective-splendor-m40a-formal-pretrain-report",
        "version": 1,
        "design_sha": "09fd8ec",
        "source_plan_hash": plan["pretrain"]["source_plan_hash"],
        "source_records": len(records),
        "train_records": len(train_records),
        "validation_records": len(validation_records),
        "offline_source_batches": batch_identities,
        "offline_dataset_identity": offline_dataset_identity,
        "split_manifest_hash": split_manifest_hash(split),
        "input_head_hash": input_head_hash,
        "output_head_hash": head_state_semantic_hash(b0),
        "parent_checkpoint_hash": b0_parent_semantic,
        "trunk_actor_policy_unchanged": True,
        "predictive_heads_changed": True,
        "b_pretrain_checkpoint": info,
        "sanity_metrics": metrics,
        "elapsed_seconds": time.perf_counter() - started,
        "history": pretrain_report["history"],
    }
    _atomic_json(RUN_ROOT / "b-pretrain-report.json", report)
    print(json.dumps({
        "status": "pretrain-b-complete",
        "brier": metrics["outcome_brier_multiclass"],
        "value_mse_completed": metrics["value_mse_completed"],
        "value_rmse_completed": metrics["value_rmse_completed"],
        "value_mse_truncated": metrics["value_mse_truncated"],
        "validation_truncated_games": metrics["validation_truncated_games"],
        "offline_dataset_identity": offline_dataset_identity,
        "checkpoint": info,
    }))


def cmd_train_cycle(args: argparse.Namespace) -> None:
    arm = args.arm
    cycle = args.cycle
    plan = build_plan()
    digest = validate_plan(plan)
    catalog = load_catalog(Path(CATALOG_REL))
    batch_path = RUN_ROOT / f"arm-{arm}" / f"cycle-{cycle}" / "batch.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    if batch["format"] != "effective-splendor-m40a-authoritative-batch":
        raise ValueError("not an M40A authoritative batch")
    if batch["cycle"] != cycle or batch["checkpoint_cycle"] != cycle - 1:
        raise ValueError("batch cycle identity mismatch")
    # The batch does not carry the arm (single-arm materialization);
    # the manifest is the arm authority.
    manifest = json.loads(
        (RUN_ROOT / f"arm-{arm}" / f"cycle-{cycle}" / "online-manifest.json")
        .read_text(encoding="utf-8")
    )
    if manifest["arm"] != arm:
        raise ValueError("manifest arm mismatch")

    plan_for_parent = build_plan()
    digest_for_parent = validate_plan(plan_for_parent)
    catalog_for_parent = load_catalog(Path(CATALOG_REL))
    if arm == "B" and cycle == 1:
        _verify_b_pretrain_provenance(
            digest_for_parent,
            catalog_semantic_hash(catalog_for_parent),
        )
    parent_path = ppo_parent_checkpoint(arm, cycle)
    model, parent_payload = _load_checkpoint(parent_path)
    if parent_payload["metadata"]["arm"] != arm:
        raise ValueError("parent checkpoint arm mismatch")
    parent_optimizer = parent_payload.get("optimizer_state_dict")
    parent_semantic = parent_payload["checkpoint_hash"]
    if batch["checkpoint_hash"] != parent_semantic:
        raise ValueError("batch checkpoint_hash != parent checkpoint")

    from splendor_gpu.m40a_train import online_train_cycle

    device = torch.device(args.device)
    model.to(device)
    _, report = online_train_cycle(
        model=model, records=batch["records"], catalog=catalog, device=device,
        cycle=cycle, plan_hash=digest, arm=arm,
        parent_optimizer_state=parent_optimizer if cycle > 1 else None,
    )
    model.to("cpu")
    info = _save_checkpoint(
        RUN_ROOT / f"{arm}-cycle{cycle}.pt", model,
        arm=arm, cycle=cycle, parent_hash=parent_semantic,
        plan_digest=digest,
        catalog_hash=catalog_semantic_hash(catalog),
        optimizer_state=report["optimizer_state_dict"],
    )
    # immediate reload verification
    _, reloaded = _load_checkpoint(RUN_ROOT / f"{arm}-cycle{cycle}.pt")
    if reloaded["checkpoint_hash"] != info["checkpoint_hash"]:
        raise ValueError("child semantic hash failed reload verification")
    report_out = {
        "format": "effective-splendor-m40a-formal-train-report",
        "version": 1, "arm": arm, "cycle": cycle,
        "batch_sha256": file_sha256(batch_path),
        "checkpoint": info, "recomputation": report["recomputation"],
        "learning_rate": report["learning_rate"],
        "history": report["history"],
    }
    _atomic_json(RUN_ROOT / f"{arm}-train-cycle{cycle}.json", report_out)
    print(json.dumps({"status": "train-cycle-complete", "arm": arm, "cycle": cycle,
                      "checkpoint": info, "records": report["records"]}))


H1_SEEDS = list(range(8_100_000, 8_100_127 + 1))
LEAGUE_SEEDS = list(range(8_200_000, 8_200_031 + 1))
M07_SEEDS = list(range(8_300_000, 8_300_063 + 1))
D2_SEEDS = list(range(8_400_000, 8_400_063 + 1))


def _evaluation_schedules() -> dict[str, list[dict[str, Any]]]:
    """The four frozen formal evaluation schedules as physical match specs.

    Each spec is one physical Arena match: (pairing, seed, rotation, arms).
    H1 pairs B-vs-A; league pairs both arms against the 9 frozen opponents;
    the anchors pair B only against M07 / D2-v2. 1,664 physical matches.
    """
    h1 = [
        {"gate": "h1", "pairing": "H1", "seed": seed, "rotation": rotation,
         "arms": ("candidate", "baseline")}
        for seed in H1_SEEDS for rotation in (0, 1)
    ]
    league = [
        {"gate": "league", "pairing": opponent, "seed": seed,
         "rotation": rotation, "arms": ("candidate", "baseline")}
        for seed in LEAGUE_SEEDS
        for opponent in LEAGUE_ORDER
        for rotation in (0, 1)
    ]
    m07 = [
        {"gate": "m07", "pairing": "M07", "seed": seed, "rotation": rotation,
         "arms": ("candidate",)}
        for seed in M07_SEEDS for rotation in (0, 1)
    ]
    d2 = [
        {"gate": "d2", "pairing": "D2-v2", "seed": seed, "rotation": rotation,
         "arms": ("candidate",)}
        for seed in D2_SEEDS for rotation in (0, 1)
    ]
    return {"h1": h1, "league": league, "m07": m07, "d2": d2}


def _validate_schedules(schedules: dict[str, list[dict[str, Any]]]) -> str:
    h1, league, m07, d2 = (
        schedules["h1"], schedules["league"], schedules["m07"], schedules["d2"]
    )
    assert len(h1) == 256, f"H1 {len(h1)} != 256"
    # League schedule entries are (opponent, seed, rotation); each entry is
    # TWO physical matches (candidate arm + baseline arm vs the opponent),
    # so 576 entries = 1,152 physical matches.
    assert len(league) == 576, f"league {len(league)} != 576"
    assert len(m07) == 128, f"m07 {len(m07)} != 128"
    assert len(d2) == 128, f"d2 {len(d2)} != 128"
    total = len(h1) + 2 * len(league) + len(m07) + len(d2)
    assert total == 1664, f"total {total} != 1664"
    # Exact frozen seed ranges and no duplicate identities.
    assert [s["seed"] for s in h1] == H1_SEEDS * 2 or sorted({s["seed"] for s in h1}) == H1_SEEDS
    assert sorted({s["seed"] for s in league}) == LEAGUE_SEEDS
    assert sorted({s["seed"] for s in m07}) == M07_SEEDS
    assert sorted({s["seed"] for s in d2}) == D2_SEEDS
    for gate_schedule in schedules.values():
        identities = {(s["pairing"], s["seed"], s["rotation"]) for s in gate_schedule}
        assert len(identities) == len(gate_schedule), "duplicate schedule identity"
    canonical = json.dumps(
        {gate: [sorted(s.items(), key=lambda kv: kv[0]) for s in sched]
         for gate, sched in schedules.items()},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _start_arm_server(arm: str, checkpoint: Path, digest: str, device: str) -> dict[str, Any]:
    ready_dir = RUN_ROOT / "eval-servers"
    ready_dir.mkdir(parents=True, exist_ok=True)
    ready = ready_dir / f"{arm}-ready.json"
    if ready.exists():
        ready.unlink()
    file_sha = file_sha256(checkpoint)
    proc = subprocess.Popen(
        [sys.executable, "-m", "splendor_gpu.m40a_server",
         "--checkpoint", str(checkpoint), "--checkpoint-sha256", file_sha,
         "--plan-hash", digest, "--catalog", CATALOG_REL,
         "--device", device, "--ready-file", str(ready)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=dict(os.environ),
    )
    deadline = time.time() + 180
    while not ready.is_file():
        if proc.poll() is not None:
            raise RuntimeError(f"{arm} eval server failed: {proc.stderr.read()[:300]}")
        if time.time() > deadline:
            raise TimeoutError(f"{arm} eval server startup timeout")
        time.sleep(0.2)
    doc = json.loads(ready.read_text(encoding="utf-8"))
    return {
        "checkpoint_file_sha256": file_sha,
        "plan_hash": digest,
        "server_url": f"127.0.0.1:{doc['port']}",
        "server_ready": str(ready),
        "proc": proc,
    }


def cmd_evaluate(args: argparse.Namespace) -> None:
    formal_checkpoint_guard(4)
    plan = build_plan()
    digest = validate_plan(plan)
    a4_path = RUN_ROOT / "A-cycle4.pt"
    b4_path = RUN_ROOT / "B-cycle4.pt"
    infos = {}
    for arm, path in (("A", a4_path), ("B", b4_path)):
        if not path.is_file():
            raise FileNotFoundError(f"formal checkpoint missing: {path}")
        _, payload = _load_checkpoint(path)
        if int(payload["metadata"]["cycle"]) != 4:
            raise ValueError(f"{path} is not a cycle-4 final")
        if payload["metadata"]["arm"] != arm:
            raise ValueError(f"{path} arm mismatch")
        infos[arm] = {
            "path": str(path),
            "checkpoint_hash": payload["checkpoint_hash"],
            "checkpoint_file_sha256": file_sha256(path),
        }

    schedules = _evaluation_schedules()
    schedule_hash = _validate_schedules(schedules)

    if args.dry_run:
        spec_out = {
            "format": "effective-splendor-m40a-evaluation-dry-run",
            "version": 1,
            "design_sha": "09fd8ec",
            "plan_hash": digest,
            "schedule_hash": schedule_hash,
            "counts": {
                "h1_matches": 256,
                "league_schedule_entries": 576,
                "league_physical_matches": 1152,
                "m07_matches": 128,
                "d2_matches": 128,
                "total_physical_matches": 1664,
            },
            "a_cycle4": infos["A"],
            "b_cycle4": infos["B"],
            "schedules": schedules,
        }
        _atomic_json(RUN_ROOT / "m40a-evaluation-dry-run.json", spec_out)
        print(json.dumps({
            "status": "evaluate-dry-run",
            "plan_hash": digest,
            "schedule_hash": schedule_hash,
            "h1": 256, "league_physical": 1152, "m07": 128, "d2": 128,
            "total": 1664,
            "a_cycle4": infos["A"],
            "b_cycle4": infos["B"],
        }))
        return

    # Formal execution: the M40A evaluator with M39A-grade provenance.
    from splendor_gpu import m40a_evaluator as evaluator

    smoke = bool(getattr(args, "smoke", False))
    out_root = RUN_ROOT / ("evaluation-smoke" if smoke else "evaluation")
    device = args.device
    catalog_path = Path(CATALOG_REL)
    gate_seeds = {
        gate: evaluator.seeds_for_gate(gate, smoke=smoke)
        for gate in ("h1", "league", "m07", "d2")
    }

    # Run manifest BEFORE any match executes: binds design, plan, schedule,
    # checkpoint identities, seed families, and executor identity. Resume
    # with a different identity fails closed here.
    executor_identity = {
        "python": sys.version.split()[0],
        "orchestrator_sha256": file_sha256(Path(__file__).resolve()),
        "runtime_sources": {
            key: file_sha256(Path(REPO_ROOT) / rel)
            for key, rel in evaluator.RUNTIME_SOURCE_PATHS.items()
        },
    }
    manifest = evaluator.run_manifest_identity(
        design_sha="09fd8ec",
        plan_hash=digest,
        schedule_hash=schedule_hash,
        a_cycle4=infos["A"],
        b_cycle4=infos["B"],
        seed_families={gate: list(seeds) for gate, seeds in gate_seeds.items()},
        executor_identity=executor_identity,
    )
    manifest["mode"] = "smoke" if smoke else "formal"
    evaluator.establish_run_manifest(out_root / "run-manifest.json", manifest)

    b4_server = _start_arm_server("B", b4_path, digest, device)
    a4_server = _start_arm_server("A", a4_path, digest, device)
    servers = {
        "A": {"plan_hash": digest, "checkpoint_hash": infos["A"]["checkpoint_hash"], **a4_server},
        "B": {"plan_hash": digest, "checkpoint_hash": infos["B"]["checkpoint_hash"], **b4_server},
    }
    ledgers: dict[str, list[dict[str, Any]]] = {
        "h1": [], "league": [], "m07": [], "d2": [],
    }
    ledger_bindings = {
        "design_sha": "09fd8ec",
        "plan_hash": digest,
        "schedule_hash": schedule_hash,
        "a_cycle4": infos["A"],
        "b_cycle4": infos["B"],
        "run_manifest_sha256": file_sha256(out_root / "run-manifest.json"),
    }
    try:
        if smoke:
            # Authorized smoke scope: H1 r0 + r1 through the REAL M40A
            # servers — proving the generated Arena configs physically
            # swap A/B seats and that result attribution follows the
            # swapped seats. No league/anchor/formal seed is consumed.
            for rotation in (0, 1):
                rebuilt = evaluator._run_physical_match(
                    gate="h1", label="H1", seed=gate_seeds["h1"][0],
                    rotation=rotation,
                    out_root=out_root, servers=servers,
                    splendor=SPLENDOR, catalog=catalog_path, device=device,
                )
                ledgers["h1"].extend(
                    evaluator.ledger_rows_for_slot(
                        "h1", "H1", gate_seeds["h1"][0], rotation, rebuilt
                    )
                )
        else:
            # H1: 256 physical matches; primary = candidate B,
            # secondary = baseline A; r0 [B, A], r1 [A, B].
            for seed in gate_seeds["h1"]:
                for rotation in (0, 1):
                    rebuilt = evaluator._run_physical_match(
                        gate="h1", label="H1", seed=seed, rotation=rotation,
                        out_root=out_root, servers=servers,
                        splendor=SPLENDOR, catalog=catalog_path, device=device,
                    )
                    ledgers["h1"].extend(
                        evaluator.ledger_rows_for_slot("h1", "H1", seed, rotation, rebuilt)
                    )
            # League: both arms, 1,152 physical matches; primary =
            # the evaluated arm, secondary = the frozen league opponent.
            for arm in ("candidate", "baseline"):
                for opponent in LEAGUE_ORDER:
                    for seed in gate_seeds["league"]:
                        for rotation in (0, 1):
                            label = f"{arm}-{opponent}"
                            rebuilt = evaluator._run_physical_match(
                                gate="league", label=label, seed=seed,
                                rotation=rotation, out_root=out_root,
                                servers=servers, splendor=SPLENDOR,
                                catalog=catalog_path, device=device,
                            )
                            ledgers["league"].extend(
                                evaluator.ledger_rows_for_slot(
                                    "league", label, seed, rotation, rebuilt
                                )
                            )
            # Anchors: B only, 128 matches each; primary = B,
            # secondary = the frozen opponent.
            for gate, pairing in (("m07", "M07"), ("d2", "D2-v2")):
                for seed in gate_seeds[gate]:
                    for rotation in (0, 1):
                        rebuilt = evaluator._run_physical_match(
                            gate=gate, label=pairing, seed=seed, rotation=rotation,
                            out_root=out_root, servers=servers,
                            splendor=SPLENDOR, catalog=catalog_path, device=device,
                        )
                        ledgers[gate].extend(
                            evaluator.ledger_rows_for_slot(
                                gate, pairing, seed, rotation, rebuilt
                            )
                        )
    finally:
        b4_server["proc"].terminate()
        a4_server["proc"].terminate()

    # EXACT identity-set validation + canonical ledger persistence.
    # Smoke mode validates only the gates it executed (H1 r0+r1).
    ledger_hashes = {}
    validated_gates = ("h1",) if smoke else ("h1", "league", "m07", "d2")
    for gate in validated_gates:
        evaluator.validate_ledger(gate, ledgers[gate], smoke=smoke)
        document = evaluator.ledger_document(gate, ledgers[gate], ledger_bindings)
        ledger_path = out_root / f"{gate}-ledger.json"
        if ledger_path.exists():
            ledger_path.unlink()
        _atomic_json(ledger_path, document)
        ledger_hashes[gate] = evaluator.ledger_hash(document)

    if smoke:
        # Smoke mode exercises the executor, ledgers, and provenance, but
        # is NOT formal evidence: the frozen gate statistics (which
        # require the full formal seed families) are not computed.
        print(json.dumps({
            "status": "evaluate-smoke-complete",
            "mode": "smoke",
            "matches": {
                "h1": len(ledgers["h1"]) // 2,
                "league": len(ledgers["league"]),
                "m07": len(ledgers["m07"]),
                "d2": len(ledgers["d2"]),
            },
            "ledger_hashes": ledger_hashes,
            "out_root": str(out_root),
        }))
        return

    h1_result = evaluate_h1(ledgers["h1"])
    league_result = evaluate_league(ledgers["league"])
    m07_result = evaluate_anchor(ledgers["m07"], "m07")
    d2_result = evaluate_anchor(ledgers["d2"], "d2")
    final = {
        "format": "effective-splendor-m40a-final-evaluation",
        "version": 1,
        "design_sha": "09fd8ec",
        "plan_hash": digest,
        "schedule_hash": schedule_hash,
        "a_cycle4": infos["A"],
        "b_cycle4": infos["B"],
        "ledger_hashes": ledger_hashes,
        "h1": h1_result,
        "league": league_result,
        "m07_anchor": m07_result,
        "d2_anchor": d2_result,
    }
    _atomic_json(RUN_ROOT / "m40a-final-evaluation.json", final)
    print(json.dumps({
        "status": "evaluate-complete",
        "h1": h1_result["verdict"],
        "h1_lower95": h1_result["lower_95_bps"],
        "league": league_result["verdict"],
        "m07_anchor_delta": m07_result["mean_delta_bps"],
        "d2_anchor_delta": d2_result["mean_delta_bps"],
        "schedule_hash": schedule_hash,
        "ledger_hashes": ledger_hashes,
    }))


def main() -> None:
    parser = argparse.ArgumentParser(description="M40A formal orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")

    pre = sub.add_parser("pretrain-b")
    pre.add_argument("--device", default="cuda")

    collect = sub.add_parser("collect-cycle")
    collect.add_argument("--arm", choices=["A", "B"], required=True)
    collect.add_argument("--cycle", type=int, choices=[1, 2, 3, 4], required=True)
    collect.add_argument("--device", default="cuda")

    train = sub.add_parser("train-cycle")
    train.add_argument("--arm", choices=["A", "B"], required=True)
    train.add_argument("--cycle", type=int, choices=[1, 2, 3, 4], required=True)
    train.add_argument("--device", default="cuda")

    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("--dry-run", action="store_true",
                               help="emit the 1,664-match schedule without running Arena")
    evaluate_parser.add_argument("--device", default="cuda")
    evaluate_parser.add_argument(
        "--smoke", action="store_true",
        help="non-formal smoke: smoke-only seed namespaces (8_9xx), "
        "separate out-root, no gate statistics — never consumes a "
        "formal 8_1xx/8_2xx/8_3xx/8_4xx seed",
    )

    args = parser.parse_args()
    handlers = {
        "init": cmd_init,
        "pretrain-b": cmd_pretrain_b,
        "collect-cycle": cmd_collect_cycle,
        "train-cycle": cmd_train_cycle,
        "evaluate": cmd_evaluate,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
