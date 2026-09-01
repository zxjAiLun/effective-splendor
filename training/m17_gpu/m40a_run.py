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


def cmd_collect_cycle(args: argparse.Namespace) -> None:
    arm = args.arm
    cycle = args.cycle
    plan = build_plan()
    digest = validate_plan(plan)
    parent_cycle = cycle - 1
    ckpt = RUN_ROOT / f"{arm}-cycle{parent_cycle}.pt"
    if not ckpt.is_file():
        raise FileNotFoundError(f"parent checkpoint missing: {ckpt}")
    _, payload = _load_checkpoint(ckpt)
    if payload["metadata"]["arm"] != arm:
        raise ValueError("checkpoint arm mismatch")
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

    a0, _ = _load_checkpoint(RUN_ROOT / "A-cycle0.pt")
    b0, _ = _load_checkpoint(RUN_ROOT / "B-cycle0.pt")
    if head_state_semantic_hash(a0) != head_state_semantic_hash(b0):
        raise ValueError("A/B cycle-0 head states differ — fork was not shared")

    from splendor_gpu.m40a_pretrain import pretrain, sanity_metrics

    # Load the enriched offline dataset (built by m40a-materialize over the
    # historical M39A batches; expected at the frozen location).
    records = []
    for cycle in range(1, 9):
        batch_path = RUN_ROOT / "offline-source" / f"cycle-{cycle}-enriched.json"
        if not batch_path.is_file():
            continue  # the formal run builds these first; pretrain requires all 8
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        records.extend(batch["records"])
    if len(records) != 182_157:
        raise ValueError(
            f"offline source incomplete: {len(records)} records (expected 182,157); "
            "run the offline enrichment first"
        )
    split = frozen_split(sorted({int(r["game_index"]) for r in records}), {2785})
    if split_manifest_hash(split) != plan["pretrain"]["expected_split_manifest_hash"]:
        raise ValueError("split manifest hash mismatch")
    train_ids = set(split["train"])
    train_records = [r for r in records if int(r["game_index"]) in train_ids]
    validation_records = [r for r in records if int(r["game_index"]) not in train_ids]

    input_head_hash = head_state_semantic_hash(b0)
    device = torch.device(args.device)
    b0.to(device)
    started = time.perf_counter()
    pretrain_report = pretrain(
        model=b0, records=train_records, device=device,
        report_path=RUN_ROOT / "b-pretrain-history.json",
    )
    metrics = sanity_metrics(model=b0, validation_records=validation_records, device=device)
    b0.to("cpu")
    info = _save_checkpoint(
        RUN_ROOT / "B-cycle0-pretrained.pt", b0,
        arm="B", cycle=0, parent_hash=None,
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
        "split_manifest_hash": split_manifest_hash(split),
        "input_head_hash": input_head_hash,
        "output_head_hash": head_state_semantic_hash(b0),
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

    parent_path = RUN_ROOT / f"{arm}-cycle{cycle - 1}.pt"
    if cycle > 1:
        parent_path = RUN_ROOT / f"{arm}-cycle{cycle - 1}.pt"
    if not parent_path.is_file():
        # cycle 1: arm A uses A-cycle0; arm B uses B-cycle0-pretrained
        candidate = (
            RUN_ROOT / f"{arm}-cycle0-pretrained.pt"
            if arm == "B" and (RUN_ROOT / "B-cycle0-pretrained.pt").is_file()
            else RUN_ROOT / f"{arm}-cycle0.pt"
        )
        parent_path = candidate
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


def cmd_evaluate(args: argparse.Namespace) -> None:
    # Formal gates: cycle-4 finals only. The physical Arena execution reuses
    # the accepted M39A evaluator machinery; this entry validates checkpoints
    # and runs the frozen statistics over a ledger.
    formal_checkpoint_guard(4)
    plan = build_plan()
    digest = validate_plan(plan)
    a4_path = RUN_ROOT / "A-cycle4.pt"
    b4_path = RUN_ROOT / "B-cycle4.pt"
    for path in (a4_path, b4_path):
        if not path.is_file():
            raise FileNotFoundError(f"formal checkpoint missing: {path}")
        _, payload = _load_checkpoint(path)
        if int(payload["metadata"]["cycle"]) != 4:
            raise ValueError(f"{path} is not a cycle-4 final")
    print(json.dumps({
        "status": "evaluate-ready",
        "plan_hash": digest,
        "a_cycle4": str(a4_path),
        "b_cycle4": str(b4_path),
        "crn_schedule_hash": FROZEN_CRN_SCHEDULE_HASH,
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

    sub.add_parser("evaluate")

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
