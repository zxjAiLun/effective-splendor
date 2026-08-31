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
CONTRACT_VERSION = 4
LEGACY_RUNNER_SHA256 = (
    "e49562e36eb19c6ab3d79ebbe5e0e891a289dfbc1b0780cadc0ea2097bc63563"
)


def log(event: dict[str, Any]) -> None:
    event = {"ts": time.time(), **event}
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    print(json.dumps(event, separators=(",", ":")), flush=True)


def acquire_lock() -> None:
    """Acquire the lock exclusively via O_CREAT|O_EXCL; fail closed always.

    There is deliberately **no** liveness probe and **no** automatic stale
    lock recovery: on this platform `os.kill(pid, 0)` is not a documented
    harmless check (a review measured it terminating the target process on
    Windows), and any probe-then-unlink logic reintroduces a race. If the
    lock file exists for any reason — live driver or crash residue — this
    driver refuses to start. Clearing a stale lock after a crash is a
    human-confirmed step (verify no driver process, then delete the file).
    """
    try:
        descriptor = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise SystemExit(
            f"lock {LOCK} already exists; another driver may be running, or "
            "the lock is stale after a crash — verify no driver process "
            "exists, then remove the file manually"
        ) from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def release_lock() -> None:
    LOCK.unlink(missing_ok=True)


def legacy_cycle_attestation(cycle: int) -> dict[str, Any]:
    """Content-hash attestation of one legacy (run-match era) cycle.

    Cycles 1–5 were collected with the pre-capped binary (SHA
    `e49562e3…`) before the capped rollout correction. Every one of their
    2,560 games terminated below the 150-ply cap (max observed 104), which
    is byte-identical under either runner mode; their batches passed full
    Rust-referee verification. Per the 2026-08-30 review verdict they are
    retained as-is. This attestation binds their actual on-disk artifacts —
    batch, materialization manifest, train report, checkpoint — so any
    post-hoc modification of the legacy data fails resume.
    """
    cycle_dir = ROOT / f"cycle-{cycle}"
    batch = cycle_dir / "batch.json"
    manifest = cycle_dir / "materialization-manifest.json"
    report_path = ROOT / f"cycle-{cycle}-train-report.json"
    checkpoint = ROOT / f"cycle-{cycle}.pt"
    for path in (batch, manifest, report_path, checkpoint):
        if not path.is_file():
            raise SystemExit(f"legacy cycle-{cycle} artifact missing: {path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    batch_doc = json.loads(batch.read_text(encoding="utf-8"))
    games = len(batch_doc.get("games", []))
    if games != 512:
        raise SystemExit(f"legacy cycle-{cycle} batch binds {games} games, expected 512")
    if int(manifest_doc.get("ply_cap", -1)) != 150:
        raise SystemExit(f"legacy cycle-{cycle} manifest ply cap is not 150")
    max_plies = max(int(game["completed_plies"]) for game in batch_doc["games"])
    if max_plies >= 150:
        raise SystemExit(
            f"legacy cycle-{cycle} contains a game at or above the cap "
            f"({max_plies} plies); the identical-under-either-runner claim "
            "does not hold — do not resume this run root"
        )
    return {
        "cycle": cycle,
        "batch_sha256": file_sha256(batch),
        "manifest_sha256": file_sha256(manifest),
        "report_sha256": file_sha256(report_path),
        "checkpoint_file_sha256": file_sha256(checkpoint),
        "checkpoint_hash": report["checkpoint_hash"],
        "games": games,
        "manifest_ply_cap": int(manifest_doc["ply_cap"]),
        "observed_max_plies": max_plies,
        "runner_mode": "run-match",
        "runner_sha256": LEGACY_RUNNER_SHA256,
    }


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

    `splendor_file_sha256` / `runner_mode` bind all collection performed by
    this driver (capped run-rollout, cycles 6–8). Cycles 1–5 are legacy
    (run-match era) and are bound by the per-cycle content-hash
    attestations in `legacy_cycles` — computed from their actual on-disk
    artifacts at contract creation, so any later modification breaks resume.
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
        "legacy_cycles": [
            legacy_cycle_attestation(cycle) for cycle in range(1, 6)
        ],
    }


def ensure_contract(contract: dict[str, Any]) -> None:
    """Write the contract once; on resume, require an **exact** match.

    There is deliberately no migration path and no self-approval: any
    difference in any field — including agent or driver source hashes —
    fails closed. Source drift across a review is not handled here at all;
    it is handled by the *provenance ledger* (see
    `m39a_provenance_ledger.py`), which records execution segments and is
    validated separately. The contract binds the execution identity the
    driver itself enforces: plan, catalog, executable, runner mode, ply
    cap, and source identities of the code that is *about to run*.
    """
    if CONTRACT.exists():
        observed = json.loads(CONTRACT.read_text(encoding="utf-8"))
        if observed != contract:
            differing = sorted(
                key for key in set(observed) | set(contract) if observed.get(key) != contract.get(key)
            )
            raise SystemExit(
                "formal execution contract mismatch on resume "
                f"(differing fields: {', '.join(differing)}); source drift "
                "cannot self-approve — record it in the provenance ledger "
                "or use a new run root"
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

    Cycles 1–5 (legacy, run-match era) are validated against their
    per-cycle content-hash attestation in the contract: batch, manifest,
    report, and checkpoint hashes; 512 games; manifest ply cap 150; every
    observed game below the cap; plus the report's plan/catalog/parent
    identity and the checkpoint metadata chain.

    Cycles 6–8 (capped era) additionally require the train report to carry
    `ply_cap == 150` and the full checkpoint/report agreement.
    """
    checkpoint = ROOT / f"cycle-{cycle}.pt"
    report_path = ROOT / f"cycle-{cycle}-train-report.json"
    if not checkpoint.is_file() or not report_path.is_file():
        return None
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    digest = file_sha256(checkpoint)

    legacy = next(
        (entry for entry in contract["legacy_cycles"] if entry["cycle"] == cycle),
        None,
    )

    # --- Common checks: checkpoint <-> report agreement + metadata chain. ---
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
    if report.get("plan_hash") != contract["plan_hash"]:
        raise SystemExit(f"cycle-{cycle} train report plan hash does not match the contract")
    if report.get("catalog_hash") != contract["catalog_hash"]:
        raise SystemExit(f"cycle-{cycle} train report catalog hash does not match the contract")

    if expected_parent is not None:
        parent_path, parent_sha, parent_hash = expected_parent
        if parent_path.is_file():
            if file_sha256(parent_path) != parent_sha:
                raise SystemExit(
                    f"cycle-{cycle} parent checkpoint file changed under us: {parent_path}"
                )
        if report.get("parent_checkpoint_sha256") is not None and (
            report["parent_checkpoint_sha256"] != parent_sha
        ):
            raise SystemExit(
                f"cycle-{cycle} report parent file hash mismatch: expected "
                f"{parent_sha!r}, report has {report['parent_checkpoint_sha256']!r}"
            )
        if report.get("parent_checkpoint_hash") != parent_hash:
            raise SystemExit(
                f"cycle-{cycle} report parent chain mismatch: report records "
                f"{report.get('parent_checkpoint_hash')!r}, expected {parent_hash!r}"
            )
        if metadata.get("parent_checkpoint_hash") != parent_hash:
            raise SystemExit(
                f"cycle-{cycle} checkpoint parent chain mismatch: checkpoint records "
                f"{metadata.get('parent_checkpoint_hash')!r}, expected {parent_hash!r}"
            )

    # --- Era-specific checks. ---
    if legacy is not None:
        cycle_dir = ROOT / f"cycle-{cycle}"
        attestation_checks = (
            ("batch_sha256", cycle_dir / "batch.json"),
            ("manifest_sha256", cycle_dir / "materialization-manifest.json"),
            ("report_sha256", report_path),
            ("checkpoint_file_sha256", checkpoint),
        )
        for field, path in attestation_checks:
            actual = file_sha256(path)
            if actual != legacy[field]:
                raise SystemExit(
                    f"legacy cycle-{cycle} {field} mismatch: attestation "
                    f"{legacy[field][:16]}…, actual {actual[:16]}… ({path})"
                )
        if report.get("checkpoint_hash") != legacy["checkpoint_hash"]:
            raise SystemExit(f"legacy cycle-{cycle} report semantic hash mismatch")
        # Legacy reports predate the ply_cap field by design; their cap
        # binding is the manifest attestation checked above.
    else:
        # Capped-era cycles must carry the ply cap in the report.
        if int(report.get("ply_cap", -1)) != int(contract["ply_cap"]):
            raise SystemExit(
                f"cycle-{cycle} train report ply cap does not match the contract "
                f"(report has {report.get('ply_cap')!r})"
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
