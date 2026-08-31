"""M39A formal-run provenance ledger: generate and validate.

The formal run executed across three source revisions with one
infrastructure abort and recovery. This ledger records the segmented
execution truth with **canonical source identities** (SHA-256 over the
LF-normalized file content as committed at each Git revision — the same
convention as the review's `82ff5ec3…` value) and per-cycle content
attestations for all eight cycles.

Validation is adversarial: the validator does **not** trust the ledger's
self-reported lists or counts. It compares the ledger against a frozen
schema embedded in this file, recomputes every attestation field from the
on-disk artifacts (batch/manifest/report/checkpoint file hashes, checkpoint
semantic hashes, truncated/terminal counts, max plies, records), verifies
the incident evidence by SHA-256, and requires the top-level bindings
(plan/catalog/executable/on-disk execution contract) to match the run root.

Commands:
    python m39a_provenance_ledger.py generate --out <ledger.json>
    python m39a_provenance_ledger.py validate --ledger <ledger.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import torch

from splendor_gpu.m39a_contract import file_sha256, load_plan, plan_hash

ROOT = Path("local-artifacts/m39a-formal-run").resolve()
REPO = Path(__file__).resolve().parent.parent.parent

LEDGER_FORMAT = "effective-splendor-m39a-formal-provenance-ledger"
LEDGER_VERSION = 2

# ---------------------------------------------------------------------------
# Frozen execution-identity schema. The validator compares segments against
# THIS table, not against anything the ledger itself claims.
# ---------------------------------------------------------------------------

# Canonical source SHA-256 helper values (SHA-256 over LF content at the
# given commit). Extracted from Git history; the pre-retry agent value
# (82ff5ec3…) matches the review's independent derivation.
SOURCE_IDENTITIES = {
    "80a5ace": {
        "agent": "771012ec5694168134e148031548ec38f4cae11dec15a2f05a76a5b1227d2584",
        "collector": "1573dd016aaa308325af19225d85c4701070f1ffe9fa20aae5b8c0402c918293",
        "server": "1a12afc739875650d201f7d42dbaede6594b2dda5bc24398cfb05001b2f79234",
    },
    "de36357": {
        "agent": "82ff5ec3be783e4b3f5a82a3330df8235dd5350cada7c18bb0cda80a374b9f75",
        "collector": "923eeab5cf7817195ca180ffa7e183be7e33218bed21e286a9cfcc1fb9421c5b",
        "server": "1a12afc739875650d201f7d42dbaede6594b2dda5bc24398cfb05001b2f79234",
    },
    "d9ca5cc": {
        "agent": "c0af0a47f7ad24169a228f595414b9d5544647e9132ad122a190334026a79dfe",
        "collector": "923eeab5cf7817195ca180ffa7e183be7e33218bed21e286a9cfcc1fb9421c5b",
        "server": "1a12afc739875650d201f7d42dbaede6594b2dda5bc24398cfb05001b2f79234",
    },
    "24f6d74": {
        "agent": "c0af0a47f7ad24169a228f595414b9d5544647e9132ad122a190334026a79dfe",
        "collector": "923eeab5cf7817195ca180ffa7e183be7e33218bed21e286a9cfcc1fb9421c5b",
        "server": "1a12afc739875650d201f7d42dbaede6594b2dda5bc24398cfb05001b2f79234",
    },
}

# The frozen expected segment table. `driver_sha256` of None means the
# historical driver source was NOT preserved (executed by an uncommitted
# temporary script); the ledger must say exactly `NOT_PRESERVED`.
EXPECTED_SEGMENTS = [
    {
        "segment": "cycles-1-5",
        "game_range": [0, 2559],
        "cycles": [1, 2, 3, 4, 5],
        "runner_mode": "run-match",
        "runner_sha256": "e49562e36eb19c6ab3d79ebbe5e0e891a289dfbc1b0780cadc0ea2097bc63563",
        "source_commit": "80a5ace",
        "agent_path": "training/m17_gpu/splendor_gpu/m39a_agent.py",
        "agent_source_sha256": SOURCE_IDENTITIES["80a5ace"]["agent"],
        "collector_source_sha256": SOURCE_IDENTITIES["80a5ace"]["collector"],
        "server_source_sha256": SOURCE_IDENTITIES["80a5ace"]["server"],
        "driver_path": None,
        "driver_source_sha256": "NOT_PRESERVED",
        "note": (
            "Executed by an uncommitted temporary driver script "
            "(never tracked); the driver source genuinely cannot be "
            "recovered. Agent/collector/server identities are from commit "
            "80a5ace, whose checkout served this segment."
        ),
    },
    {
        "segment": "cycle-6-recollected",
        "game_range": [2560, 3071],
        "cycles": [6],
        "runner_mode": "run-rollout",
        "runner_sha256": "d8c2ee524e4a58b221986025d77ce5857527e2ca0db79292c9160d3a449a5828",
        "source_commit": "de36357",
        "agent_path": "training/m17_gpu/splendor_gpu/m39a_agent.py",
        "agent_source_sha256": SOURCE_IDENTITIES["de36357"]["agent"],
        "collector_source_sha256": SOURCE_IDENTITIES["de36357"]["collector"],
        "server_source_sha256": SOURCE_IDENTITIES["de36357"]["server"],
        "driver_path": "training/m17_gpu/m39a_cycle_driver.py",
        "driver_source_sha256": "ea81045e7541056bd0a726e71b1394cb7cb96f745058f6991a1652bf66749017",
        "note": "fresh capped re-collection from the cycle-5 checkpoint",
    },
    {
        "segment": "cycle-7-pre-retry",
        "game_range": [3072, 3334],
        "cycles": [7],
        "runner_mode": "run-rollout",
        "runner_sha256": "d8c2ee524e4a58b221986025d77ce5857527e2ca0db79292c9160d3a449a5828",
        "source_commit": "de36357",
        "agent_path": "training/m17_gpu/splendor_gpu/m39a_agent.py",
        "agent_source_sha256": SOURCE_IDENTITIES["de36357"]["agent"],
        "collector_source_sha256": SOURCE_IDENTITIES["de36357"]["collector"],
        "server_source_sha256": SOURCE_IDENTITIES["de36357"]["server"],
        "driver_path": "training/m17_gpu/m39a_cycle_driver.py",
        "driver_source_sha256": "ea81045e7541056bd0a726e71b1394cb7cb96f745058f6991a1652bf66749017",
        "note": "263 games before the infrastructure abort at game 3335",
    },
    {
        "segment": "cycle-7-game-3335-attempt-1-ABORTED",
        "game_range": [3335, 3335],
        "cycles": [7],
        "runner_mode": "run-rollout",
        "runner_sha256": "d8c2ee524e4a58b221986025d77ce5857527e2ca0db79292c9160d3a449a5828",
        "source_commit": "de36357",
        "agent_path": "training/m17_gpu/splendor_gpu/m39a_agent.py",
        "agent_source_sha256": SOURCE_IDENTITIES["de36357"]["agent"],
        "collector_source_sha256": SOURCE_IDENTITIES["de36357"]["collector"],
        "server_source_sha256": SOURCE_IDENTITIES["de36357"]["server"],
        "driver_path": "training/m17_gpu/m39a_cycle_driver.py",
        "driver_source_sha256": "ea81045e7541056bd0a726e71b1394cb7cb96f745058f6991a1652bf66749017",
        "note": (
            "aborted attempt: learner proxy connection to the resident "
            "inference server broke mid-flight (agent_eof at ply 54); "
            "evidence preserved at incidents/cycle-7-game-3335-agent-eof/; "
            "no training data produced; NOT part of the accepted 4096"
        ),
    },
    {
        "segment": "cycle-7-retry-agent",
        "game_range": [3335, 3583],
        "cycles": [7],
        "runner_mode": "run-rollout",
        "runner_sha256": "d8c2ee524e4a58b221986025d77ce5857527e2ca0db79292c9160d3a449a5828",
        "source_commit": "d9ca5cc+24f6d74",
        "agent_path": "training/m17_gpu/splendor_gpu/m39a_agent.py",
        "agent_source_sha256": SOURCE_IDENTITIES["d9ca5cc"]["agent"],
        "collector_source_sha256": SOURCE_IDENTITIES["d9ca5cc"]["collector"],
        "server_source_sha256": SOURCE_IDENTITIES["d9ca5cc"]["server"],
        "driver_path": "training/m17_gpu/m39a_cycle_driver.py",
        "driver_source_sha256": SOURCE_IDENTITIES["24f6d74"]["agent"],  # driver at 24f6d74
        "driver_note": "driver source at 24f6d74 (contract v3)",
        "note": (
            "game 3335 re-collected from the same frozen seed 4001667 plus "
            "games 3336-3583; agent carries the reviewed transient-"
            "connection retry (d9ca5cc), driver the contract v3 resume "
            "semantics (24f6d74)"
        ),
    },
    {
        "segment": "cycle-8",
        "game_range": [3584, 4095],
        "cycles": [8],
        "runner_mode": "run-rollout",
        "runner_sha256": "d8c2ee524e4a58b221986025d77ce5857527e2ca0db79292c9160d3a449a5828",
        "source_commit": "d9ca5cc+24f6d74",
        "agent_path": "training/m17_gpu/splendor_gpu/m39a_agent.py",
        "agent_source_sha256": SOURCE_IDENTITIES["d9ca5cc"]["agent"],
        "collector_source_sha256": SOURCE_IDENTITIES["d9ca5cc"]["collector"],
        "server_source_sha256": SOURCE_IDENTITIES["d9ca5cc"]["server"],
        "driver_path": "training/m17_gpu/m39a_cycle_driver.py",
        "driver_source_sha256": SOURCE_IDENTITIES["24f6d74"]["agent"],
        "driver_note": "driver source at 24f6d74 (contract v3)",
        "note": "final cycle",
    },
]

# Fix the two driver SHA entries (the dict above used the agent value by
# mistake-prone design; set the true driver hashes explicitly).
_DRIVER_SHA = {
    "24f6d74": "ce60d4bacd0f2ec062fbc7d7e951fead96d413335439bd793c37ab79f063955b",
    "de36357": "ea81045e7541056bd0a726e71b1394cb7cb96f745058f6991a1652bf66749017",
}
for _segment in EXPECTED_SEGMENTS:
    if _segment["driver_source_sha256"] == SOURCE_IDENTITIES["24f6d74"]["agent"]:
        _segment["driver_source_sha256"] = _DRIVER_SHA["24f6d74"]

# Frozen expected incident table (paths relative to ROOT; SHA-256 of the
# evidence files verified from disk).
EXPECTED_INCIDENTS = [
    {
        "name": "cycle-6-pre-capped-2026-08-30T22-50",
        "path": "incidents/cycle-6-pre-capped-2026-08-30T22-50",
        "files": {"README.txt": None},
        "description": "225 pre-capped cycle-6 games preserved before re-collection",
    },
    {
        "name": "cycle-7-game-3335-agent-eof",
        "path": "incidents/cycle-7-game-3335-agent-eof",
        "files": {
            "README.txt": None,
            "arena-config.json": "516a76e82066c4ee98707896bddcde9934de119bdac9640fbd396339a19253f2",
            "arena-report.json": "1a57b2dc1d896e43d1adbe90e9b77aa5d15fb60ae0d29164b9f7d1ee83353d4f",
        },
        "description": "aborted attempt 1 of game 3335 (agent_eof at ply 54, seed 4001667)",
    },
]

ORIGINAL_CONTRACT_NOTE = (
    "The original v2 execution contract bytes were not preserved before the "
    "v3 rewrite on 2026-08-31 (the driver overwrote the file in place). The "
    "pre-rewrite execution identity recorded here was reconstructed from "
    "Git commit history (canonical source SHA-256 values), artifact mtimes, "
    "and the driver progress log; it is a reconstruction, not the original "
    "bytes. The on-disk contract at run completion (v3, written by the "
    "final driver invocation) is itself hash-bound in this ledger's "
    "top-level bindings."
)

RESULT_BLOCK = {
    "formal_run_training": "COMPLETE",
    "result": "VALID_WITH_RECORDED_INFRASTRUCTURE_RETRY",
    "accepted_games": 4096,
    "attempts": 4097,
    "terminal_games": 4095,
    "truncated_games": 1,
    "infrastructure_aborts": 1,
    "records": 182157,
}


def cycle_attestation(cycle: int) -> dict[str, Any]:
    """Recompute one cycle's full attestation from the on-disk artifacts."""
    cycle_dir = ROOT / f"cycle-{cycle}"
    batch = cycle_dir / "batch.json"
    manifest = cycle_dir / "materialization-manifest.json"
    report_path = ROOT / f"cycle-{cycle}-train-report.json"
    checkpoint = ROOT / f"cycle-{cycle}.pt"
    for path in (batch, manifest, report_path, checkpoint):
        if not path.is_file():
            raise SystemExit(f"cycle-{cycle} artifact missing: {path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    batch_doc = json.loads(batch.read_text(encoding="utf-8"))
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    games = batch_doc["games"]
    return {
        "cycle": cycle,
        "batch_sha256": file_sha256(batch),
        "manifest_sha256": file_sha256(manifest),
        "report_sha256": file_sha256(report_path),
        "checkpoint_file_sha256": file_sha256(checkpoint),
        "checkpoint_hash": payload["checkpoint_hash"],
        "report_checkpoint_hash": report["checkpoint_hash"],
        "games": len(games),
        "truncated_games": sum(1 for game in games if game["truncated"]),
        "terminal_games": sum(1 for game in games if not game["truncated"]),
        "manifest_ply_cap": int(manifest_doc["ply_cap"]),
        "observed_max_plies": max(int(game["completed_plies"]) for game in games),
        "records": int(report["records"]),
        "learning_rate": float(report["learning_rate"]),
        "plan_hash": report["plan_hash"],
        "catalog_hash": report["catalog_hash"],
    }


def top_level_bindings() -> dict[str, Any]:
    plan_path = REPO / "benchmarks/m39a-arena-driven-policy-value-rl.plan.json"
    catalog_path = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
    exe_path = REPO / "target/release/splendor.exe"
    contract_path = ROOT / "formal-execution-contract.json"
    return {
        "plan_path": str(plan_path),
        "plan_hash": plan_hash(load_plan(plan_path)),
        "catalog_path": str(catalog_path),
        "catalog_file_sha256": file_sha256(catalog_path),
        "executable_path": str(exe_path),
        "executable_sha256": file_sha256(exe_path),
        "on_disk_execution_contract_path": str(contract_path),
        "on_disk_execution_contract_sha256": file_sha256(contract_path),
        "on_disk_execution_contract_version": json.loads(
            contract_path.read_text(encoding="utf-8")
        ).get("version"),
    }


def generate(out: Path) -> None:
    ledger = {
        "format": LEDGER_FORMAT,
        "version": LEDGER_VERSION,
        "generated": "2026-08-31",
        "original_contract_note": ORIGINAL_CONTRACT_NOTE,
        "bindings": top_level_bindings(),
        "result": RESULT_BLOCK,
        "segments": EXPECTED_SEGMENTS,
        "incidents": EXPECTED_INCIDENTS,
        "cycles": [cycle_attestation(cycle) for cycle in range(1, 9)],
    }
    out.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "generated", "ledger": str(out)}))


def _failures_recompute(ledger: dict[str, Any]) -> list[str]:
    """Recompute every attested field from disk; compare to the ledger."""
    failures: list[str] = []
    observed_cycles = ledger.get("cycles")
    if not isinstance(observed_cycles, list) or len(observed_cycles) != 8:
        count = len(observed_cycles) if isinstance(observed_cycles, list) else "non-list"
        return [f"ledger must list exactly 8 cycles (got {count})"]
    for cycle in range(1, 9):
        attested = observed_cycles[cycle - 1]
        if attested.get("cycle") != cycle:
            failures.append(f"cycle entry {cycle-1} declares cycle {attested.get('cycle')}")
            continue
        recomputed = cycle_attestation(cycle)
        for field, value in recomputed.items():
            if attested.get(field) != value:
                failures.append(
                    f"cycle-{cycle}: {field} mismatch (ledger "
                    f"{attested.get(field)!r} vs recomputed {value!r})"
                )
    return failures


def _failures_segments(ledger: dict[str, Any]) -> list[str]:
    """Segments must match the frozen table exactly (order included)."""
    failures: list[str] = []
    observed = ledger.get("segments")
    if observed is None or not isinstance(observed, list):
        return ["ledger has no segments list"]
    if len(observed) != len(EXPECTED_SEGMENTS):
        return [
            f"segment count {len(observed)} != frozen expectation {len(EXPECTED_SEGMENTS)}"
        ]
    for index, (got, want) in enumerate(zip(observed, EXPECTED_SEGMENTS)):
        for field, value in want.items():
            if got.get(field) != value:
                failures.append(
                    f"segment[{index}] ({want['segment']}): {field} mismatch "
                    f"(ledger {got.get(field)!r} != frozen {value!r})"
                )
    return failures


def _failures_incidents(ledger: dict[str, Any]) -> list[str]:
    """Incidents must match the frozen table, and evidence SHAs from disk.

    Every self-reported field of each incident entry is compared against
    the frozen table (so a ledger cannot claim different file lists), and
    the evidence files on disk are hashed against the frozen SHA-256
    values (so the artifacts themselves cannot have been swapped).
    """
    failures: list[str] = []
    observed = ledger.get("incidents")
    if observed is None or not isinstance(observed, list):
        return ["ledger has no incidents list"]
    if len(observed) != len(EXPECTED_INCIDENTS):
        return [
            f"incident count {len(observed)} != frozen expectation "
            f"{len(EXPECTED_INCIDENTS)}"
        ]
    for index, (got, want) in enumerate(zip(observed, EXPECTED_INCIDENTS)):
        for field, value in want.items():
            if got.get(field) != value:
                failures.append(
                    f"incident[{index}] ({want['name']}): {field} mismatch "
                    f"(ledger {got.get(field)!r} != frozen {value!r})"
                )
        directory = ROOT / want["path"]
        if not directory.is_dir():
            failures.append(f"incident {want['name']}: directory missing")
            continue
        for name, expected_sha in want["files"].items():
            path = directory / name
            if not path.is_file():
                failures.append(f"incident {want['name']}: missing {name}")
                continue
            if expected_sha is None:
                continue
            actual = file_sha256(path)
            if actual != expected_sha:
                failures.append(
                    f"incident {want['name']}: {name} SHA mismatch "
                    f"({actual[:16]}… != {expected_sha[:16]}…)"
                )
    return failures


def _failures_bindings(ledger: dict[str, Any]) -> list[str]:
    """Top-level bindings must match the current run root / repo state."""
    failures: list[str] = []
    observed = ledger.get("bindings")
    if observed is None or not isinstance(observed, dict):
        return ["ledger has no bindings object"]
    recomputed = top_level_bindings()
    for field, value in recomputed.items():
        if observed.get(field) != value:
            failures.append(
                f"binding {field} mismatch (ledger {observed.get(field)!r} "
                f"vs recomputed {value!r})"
            )
    return failures


def _failures_result(ledger: dict[str, Any]) -> list[str]:
    """The result block must match the frozen constants AND the artifacts."""
    failures: list[str] = []
    observed = ledger.get("result")
    if observed != RESULT_BLOCK:
        failures.append("result block does not match the frozen expectations")
        return failures
    # Cross-check counts against the recomputed cycles.
    terminal = 0
    truncated = 0
    records = 0
    for cycle in range(1, 9):
        attestation = cycle_attestation(cycle)
        terminal += attestation["terminal_games"]
        truncated += attestation["truncated_games"]
        records += attestation["records"]
    if terminal != RESULT_BLOCK["terminal_games"]:
        failures.append(
            f"recomputed terminal {terminal} != claimed {RESULT_BLOCK['terminal_games']}"
        )
    if truncated != RESULT_BLOCK["truncated_games"]:
        failures.append(
            f"recomputed truncated {truncated} != claimed {RESULT_BLOCK['truncated_games']}"
        )
    if records != RESULT_BLOCK["records"]:
        failures.append(
            f"recomputed records {records} != claimed {RESULT_BLOCK['records']}"
        )
    return failures


def _failures_coverage(ledger: dict[str, Any]) -> list[str]:
    """The accepted segments (frozen table) must tile 0..4095 exactly once,
    and the on-disk batches must agree index-for-index."""
    failures: list[str] = []
    accepted = [
        segment
        for segment in EXPECTED_SEGMENTS
        if "ABORTED" not in segment["segment"]
    ]
    covered: dict[int, int] = {}
    for segment in accepted:
        for index in range(segment["game_range"][0], segment["game_range"][1] + 1):
            covered[index] = covered.get(index, 0) + 1
    expected = set(range(4096))
    if set(covered) != expected:
        failures.append("accepted segments do not cover exactly 0..4095")
    doubled = sorted(index for index, count in covered.items() if count > 1)
    if doubled:
        failures.append(f"accepted segments overlap on {doubled[:8]}")
    seen: dict[int, int] = {}
    for cycle in range(1, 9):
        batch = json.loads(
            (ROOT / f"cycle-{cycle}" / "batch.json").read_text(encoding="utf-8")
        )
        for game in batch["games"]:
            index = int(game["game_index"])
            seen[index] = seen.get(index, 0) + 1
    missing = sorted(expected - set(seen))
    duplicated = sorted(index for index, count in seen.items() if count > 1)
    out_of_range = sorted(set(seen) - expected)
    if missing:
        failures.append(f"batches missing indices: {missing[:8]}")
    if duplicated:
        failures.append(f"batches duplicate indices: {duplicated[:8]}")
    if out_of_range:
        failures.append(f"batches have out-of-range indices: {out_of_range[:8]}")
    return failures


def validate(ledger_path: Path) -> None:
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger.get("format") != LEDGER_FORMAT or ledger.get("version") != LEDGER_VERSION:
        raise SystemExit("unsupported ledger format/version")

    failures: list[str] = []
    failures += _failures_bindings(ledger)
    failures += _failures_segments(ledger)
    failures += _failures_incidents(ledger)
    failures += _failures_recompute(ledger)
    failures += _failures_result(ledger)
    failures += _failures_coverage(ledger)

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "status": "valid",
                "cycles": 8,
                "accepted_games": RESULT_BLOCK["accepted_games"],
                "attempts": RESULT_BLOCK["attempts"],
                "records": RESULT_BLOCK["records"],
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="M39A provenance ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    generate_parser = sub.add_parser("generate")
    generate_parser.add_argument("--out", type=Path, required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate":
        generate(args.out)
    else:
        validate(args.ledger)


if __name__ == "__main__":
    main()
