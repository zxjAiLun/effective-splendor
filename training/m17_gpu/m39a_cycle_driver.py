"""Deterministic M39A cycle driver: collect -> materialize -> train, chained.

Tracked entry point for the formal 4,096-game run. Properties:

- checkpoint chain verification (file SHA-256 + semantic hash at every hop);
- batch reuse only when the full artifact exists on disk;
- single-instance lock (fail-closed on a competing driver);
- append-only JSONL progress log (never truncated);
- a cycle is fully complete (report + checkpoint verified) before the next
  cycle starts;
- artifacts under local-artifacts/m39a-formal-run/ (ignored, not published).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training" / "m17_gpu"))

import torch

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m39a_collect import collect
from splendor_gpu.m39a_contract import file_sha256, load_plan, plan_hash
from splendor_gpu.m39a_train import train_cycle

ROOT = Path("local-artifacts/m39a-formal-run").resolve()
LOCK = ROOT / "driver.lock"
LOG = ROOT / "driver-progress.jsonl"
CKPT0 = Path("local-artifacts/m39a-implementation-smoke/cycle-0.pt").resolve()


def log(event: dict[str, Any]) -> None:
    event = {"ts": time.time(), **event}
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    print(json.dumps(event, separators=(",", ":")), flush=True)


def acquire_lock() -> None:
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            raise SystemExit(f"another driver (pid {pid}) holds {LOCK}")
        except (ProcessLookupError, ValueError, PermissionError, OSError):
            LOCK.unlink()
    LOCK.write_text(str(os.getpid()), encoding="utf-8")


def release_lock() -> None:
    LOCK.unlink(missing_ok=True)


def cycle_state(cycle: int) -> tuple[Path, str, str] | None:
    """Return (checkpoint, file_sha256, semantic_hash) for a completed cycle."""
    checkpoint = ROOT / f"cycle-{cycle}.pt"
    report_path = ROOT / f"cycle-{cycle}-train-report.json"
    if not checkpoint.is_file() or not report_path.is_file():
        return None
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    expected_file = report.get("checkpoint_file_sha256")
    digest = file_sha256(checkpoint)
    if expected_file is not None and expected_file != digest:
        raise SystemExit(f"cycle-{cycle} checkpoint file hash mismatch")
    if payload["checkpoint_hash"] != report.get("checkpoint_hash"):
        raise SystemExit(f"cycle-{cycle} checkpoint semantic hash mismatch")
    return checkpoint, digest, payload["checkpoint_hash"]


def main() -> None:
    parser = argparse.ArgumentParser(description="M39A formal cycle driver")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--splendor", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    args = parser.parse_args()

    ROOT.mkdir(parents=True, exist_ok=True)
    acquire_lock()
    try:
        plan = load_plan(args.plan)
        digest = plan_hash(plan)
        catalog = load_catalog(args.catalog)
        catalog_hash = catalog_semantic_hash(catalog)
        if plan["catalog"]["semantic_hash"] != catalog_hash:
            raise SystemExit("catalog does not match plan")

        seed = ROOT / "cycle-0.pt"
        if not seed.exists():
            import shutil

            shutil.copy2(CKPT0, seed)
        state = (seed, file_sha256(seed), None)
        payload0 = torch.load(seed, map_location="cpu", weights_only=False)
        state = (seed, file_sha256(seed), payload0["checkpoint_hash"])
        del payload0
        log({"event": "cycle-0-ready", "checkpoint": str(state[0]), "sha256": state[1]})

        for cycle in range(1, 9):
            done = cycle_state(cycle)
            if done is not None:
                log({"event": "cycle-resumed-complete", "cycle": cycle})
                state = done
                continue

            checkpoint, checkpoint_sha256, checkpoint_hash = state
            cycle_dir = ROOT / f"cycle-{cycle}"
            batch_path = cycle_dir / "batch.json"
            batch_reused = batch_path.is_file()

            started = time.perf_counter()
            result = collect(
                plan_path=args.plan,
                checkpoint=checkpoint,
                checkpoint_sha256=checkpoint_sha256,
                checkpoint_hash=checkpoint_hash,
                cycle=cycle,
                catalog_path=args.catalog,
                splendor=args.splendor,
                out_dir=cycle_dir,
                mode="complete_cycle",
                smoke_games=512,
                device=args.device,
                materialize=not batch_reused,
                batch_out=batch_path,
                resident_server=True,
            )
            log(
                {
                    "event": "collected",
                    "cycle": cycle,
                    "batch_reused": batch_reused,
                    "games": result["games"],
                    "collect_seconds": round(time.perf_counter() - started, 1),
                }
            )
            if not batch_path.is_file():
                raise SystemExit(f"cycle-{cycle}: materialization produced no batch")

            payload, report = train_cycle(
                plan=plan,
                plan_digest=digest,
                batch=json.loads(batch_path.read_text(encoding="utf-8")),
                checkpoint_path=checkpoint,
                checkpoint_sha256=checkpoint_sha256,
                catalog=catalog,
                catalog_hash=catalog_hash,
                cycle=cycle,
                device=torch.device(args.device),
            )
            out = ROOT / f"cycle-{cycle}.pt"
            temporary = out.with_name(out.name + ".tmp")
            torch.save(payload, temporary)
            out.unlink(missing_ok=True)
            temporary.replace(out)
            report["checkpoint_file_sha256"] = file_sha256(out)
            (ROOT / f"cycle-{cycle}-train-report.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            state = (out, report["checkpoint_file_sha256"], payload["checkpoint_hash"])
            log(
                {
                    "event": "trained",
                    "cycle": cycle,
                    "checkpoint_hash": payload["checkpoint_hash"],
                    "records": report["records"],
                    "recomputation": report["recomputation"],
                    "train_seconds": round(time.perf_counter() - started, 1),
                }
            )

        log({"event": "run-complete", "final_checkpoint": str(state[0])})
    finally:
        release_lock()


if __name__ == "__main__":
    main()
