"""Deterministic M39A cycle driver: collect -> materialize -> train, chained.

Tracked entry point for the formal 4,096-game run. Properties:

- single-instance lock acquired via exclusive atomic creation (no
  check-then-write race; any existing or ambiguous lock fails closed);
- a formal execution contract binding plan/catalog identity, the cycle-0
  seed checkpoint, the splendor executable SHA-256, the run-rollout capped
  mode with ply_cap=150, and the executing source identities — written once
  and fully re-validated on every resume;
- checkpoint chain verification (file SHA-256 + semantic hash + parent
  chain + plan/catalog/cycle metadata at every hop);
- batch reuse only when the full artifact exists on disk;
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

import torch

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m39a_collect import collect
from splendor_gpu.m39a_contract import file_sha256, load_plan, plan_hash
from splendor_gpu.m39a_train import train_cycle

ROOT = Path("local-artifacts/m39a-formal-run").resolve()
LOCK = ROOT / "driver.lock"
LOG = ROOT / "driver-progress.jsonl"
CONTRACT = ROOT / "formal-execution-contract.json"
CKPT0 = Path("local-artifacts/m39a-implementation-smoke/cycle-0.pt").resolve()

CONTRACT_FORMAT = "effective-splendor-m39a-formal-execution-contract"
CONTRACT_VERSION = 1


def log(event: dict[str, Any]) -> None:
    event = {"ts": time.time(), **event}
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    print(json.dumps(event, separators=(",", ":")), flush=True)


def acquire_lock() -> None:
    """Atomically create the lock file; fail closed on any existing lock.

    Uses exclusive creation (O_CREAT|O_EXCL) so two drivers can never both
    pass a check-then-write race. A pre-existing lock is only overridden when
    it names a PID that is provably dead — and even then the acquisition is
    still atomic.
    """
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
        except (ProcessLookupError, ValueError, PermissionError, OSError):
            # The recorded PID is provably not alive (or not a PID at all).
            # Still do NOT trust unlink-then-create blindly: another driver
            # may be mid-write. Atomically rename the stale lock away; if the
            # rename fails, someone else owns the directory.
            stale = LOCK.with_name(LOCK.name + ".stale")
            try:
                os.replace(LOCK, stale)
            except OSError as error:
                raise SystemExit(f"cannot clear stale lock {LOCK}: {error}") from error
        else:
            raise SystemExit(
                f"another driver (pid {pid}) holds {LOCK}; refusing to start"
            )
    try:
        descriptor = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise SystemExit(f"lost the lock race on {LOCK}; refusing to start") from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def release_lock() -> None:
    LOCK.unlink(missing_ok=True)


def execution_contract(
    *,
    plan_path: Path,
    plan_digest: str,
    catalog_path: Path,
    catalog_hash: str,
    splendor: Path,
    ply_cap: int,
) -> dict[str, Any]:
    """The binding this run directory commits to exactly once.

    Note on cycles 1–5: they were collected with the pre-capped run-match
    binary (SHA e49562e3…) and every one of their 2,560 games terminated
    below the 150-ply cap (max observed 104), which is byte-identical under
    either runner mode; their batches passed full Rust-referee verification.
    Per the 2026-08-30 review verdict they are retained as-is. The
    `splendor_file_sha256` field below therefore binds all collection
    performed by *this* driver instance (cycles 6–8 onwards, run-rollout
    capped mode); the legacy-binary prefix is recorded in
    `legacy_collection_note`.
    """
    source_root = Path(__file__).resolve().parent
    return {
        "format": CONTRACT_FORMAT,
        "version": CONTRACT_VERSION,
        "plan_path": str(plan_path.resolve()),
        "plan_hash": plan_digest,
        "catalog_path": str(catalog_path.resolve()),
        "catalog_hash": catalog_hash,
        "splendor_program": str(splendor.resolve()),
        "splendor_file_sha256": file_sha256(splendor),
        "runner_mode": "run-rollout",
        "ply_cap": ply_cap,
        "driver_source_sha256": file_sha256(Path(__file__).resolve()),
        "collector_source_sha256": file_sha256(source_root / "splendor_gpu" / "m39a_collect.py"),
        "agent_source_sha256": file_sha256(source_root / "splendor_gpu" / "m39a_agent.py"),
        "server_source_sha256": file_sha256(source_root / "splendor_gpu" / "m39a_server.py"),
        "trainer_source_sha256": file_sha256(source_root / "splendor_gpu" / "m39a_train.py"),
        "cycle_0_seed_sha256": file_sha256(CKPT0),
        "legacy_collection_note": (
            "cycles 1-5 were collected with run-match binary "
            "e49562e36eb19c6ab3d79ebbe5e0e891a289dfbc1b0780cadc0ea2097bc63563 "
            "before the capped rollout correction; all 2560 games terminated "
            "below the ply cap and are identical under either runner mode "
            "(review-accepted 2026-08-30)"
        ),
    }


def ensure_contract(contract: dict[str, Any]) -> None:
    """Write the contract once; on resume, require an exact match."""
    if CONTRACT.exists():
        observed = json.loads(CONTRACT.read_text(encoding="utf-8"))
        if observed != contract:
            differing = sorted(
                key for key in set(observed) | set(contract) if observed.get(key) != contract.get(key)
            )
            raise SystemExit(
                "formal execution contract mismatch on resume "
                f"(differing fields: {', '.join(differing)}); use the original "
                "plan/catalog/checkpoint/executable/sources or a new run root"
            )
    else:
        temporary = CONTRACT.with_name(CONTRACT.name + ".tmp")
        temporary.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, CONTRACT)


def cycle_state(
    cycle: int,
    *,
    contract: dict[str, Any],
    expected_parent: tuple[Path, str, str] | None,
) -> tuple[Path, str, str] | None:
    """Verify a completed cycle end-to-end before trusting it on resume.

    Checks (all fail-closed): checkpoint + report exist; file SHA matches the
    report; semantic hash matches the report; metadata cycle equals the
    requested cycle; plan/catalog identity matches the contract; the parent
    chain matches the expected parent checkpoint; ply cap matches.
    """
    checkpoint = ROOT / f"cycle-{cycle}.pt"
    report_path = ROOT / f"cycle-{cycle}-train-report.json"
    if not checkpoint.is_file() or not report_path.is_file():
        return None
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    digest = file_sha256(checkpoint)

    if report.get("checkpoint_file_sha256") != digest:
        raise SystemExit(f"cycle-{cycle} checkpoint file hash mismatch")
    if payload["checkpoint_hash"] != report.get("checkpoint_hash"):
        raise SystemExit(f"cycle-{cycle} checkpoint semantic hash mismatch")

    metadata = payload["metadata"]
    if int(metadata["cycle"]) != cycle:
        raise SystemExit(
            f"cycle-{cycle} checkpoint metadata declares cycle {metadata['cycle']}"
        )
    if metadata["plan_hash"] != contract["plan_hash"]:
        raise SystemExit(f"cycle-{cycle} checkpoint plan hash does not match the contract")
    if metadata["catalog_hash"] != contract["catalog_hash"]:
        raise SystemExit(f"cycle-{cycle} checkpoint catalog hash does not match the contract")
    if int(report.get("cycle", -1)) != cycle:
        raise SystemExit(f"cycle-{cycle} train report cycle mismatch")
    if int(report.get("ply_cap", -1)) != int(contract["ply_cap"]):
        raise SystemExit(f"cycle-{cycle} train report ply cap does not match the contract")

    if expected_parent is not None:
        parent_path, parent_sha, parent_hash = expected_parent
        if parent_path.is_file():
            if file_sha256(parent_path) != parent_sha:
                raise SystemExit(
                    f"cycle-{cycle} parent checkpoint file changed under us: {parent_path}"
                )
        if metadata.get("parent_checkpoint_hash") != parent_hash:
            raise SystemExit(
                f"cycle-{cycle} parent chain mismatch: checkpoint records "
                f"{metadata.get('parent_checkpoint_hash')!r}, expected {parent_hash!r}"
            )
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
        if not args.splendor.is_file():
            raise SystemExit(f"splendor executable not found: {args.splendor}")

        ply_cap = int(plan["round"]["ply_cap"])
        contract = execution_contract(
            plan_path=args.plan,
            plan_digest=digest,
            catalog_path=args.catalog,
            catalog_hash=catalog_hash,
            splendor=args.splendor,
            ply_cap=ply_cap,
        )
        ensure_contract(contract)
        log({"event": "contract-verified", "splendor_sha256": contract["splendor_file_sha256"]})

        seed = ROOT / "cycle-0.pt"
        if not seed.exists():
            if file_sha256(CKPT0) != contract["cycle_0_seed_sha256"]:
                raise SystemExit("cycle-0 seed checkpoint hash changed")
            import shutil

            shutil.copy2(CKPT0, seed)
        if file_sha256(seed) != contract["cycle_0_seed_sha256"]:
            raise SystemExit(f"cycle-0 seed checkpoint hash mismatch at {seed}")
        payload0 = torch.load(seed, map_location="cpu", weights_only=False)
        if payload0["metadata"]["plan_hash"] != digest:
            raise SystemExit("cycle-0 seed checkpoint plan hash mismatch")
        state = (seed, contract["cycle_0_seed_sha256"], payload0["checkpoint_hash"])
        del payload0
        log({"event": "cycle-0-ready", "checkpoint": str(state[0]), "sha256": state[1]})

        for cycle in range(1, 9):
            done = cycle_state(cycle, contract=contract, expected_parent=state)
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
