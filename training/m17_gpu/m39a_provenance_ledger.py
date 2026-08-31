"""M39A formal-run provenance ledger: generate and validate.

The formal run executed across three source revisions with one
infrastructure abort and recovery. The execution contract only binds the
identity of the *last* driver invocation, so this ledger records the full
segmented truth: per-cycle content attestations for all eight cycles
(batch / materialization-manifest / train-report / checkpoint, file and
semantic hashes), the execution segments with their source identities, and
the failed-then-retried game 3335 attempts.

Commands:
    python m39a_provenance_ledger.py generate --out <ledger.json>
    python m39a_provenance_ledger.py validate --ledger <ledger.json>

`validate` is the reviewer's instrument: it re-hashes every attested
artifact from disk, checks the successful-game index covers 0..4095
exactly once, verifies the incident records exist, and fails closed on any
mismatch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import torch

from splendor_gpu.m39a_contract import file_sha256

ROOT = Path("local-artifacts/m39a-formal-run").resolve()

LEDGER_FORMAT = "effective-splendor-m39a-formal-provenance-ledger"
LEDGER_VERSION = 1

# Source identities of the three revisions that executed this run, taken
# from the pushed commits (git show <sha>:<path> | sha256). These are
# historical facts about the repository, not properties of the current
# checkout.
SEGMENTS = [
    {
        "segment": "cycles-1-5",
        "commits": "7d647ec..de36357 (agent/driver as of de36357)",
        "cycles": [1, 2, 3, 4, 5],
        "runner_mode": "run-match",
        "runner_sha256": "e49562e36eb19c6ab3d79ebbe5e0e891a289dfbc1b0780cadc0ea2097bc63563",
        "games": [0, 2559],
        "note": "legacy pre-capped collection; all 2560 games terminated below the 150-ply cap",
    },
    {
        "segment": "cycle-6-recollected",
        "commits": "de36357 agent/driver + capped runner (release d8c2ee52)",
        "cycles": [6],
        "runner_mode": "run-rollout",
        "runner_sha256": "d8c2ee524e4a58b221986025d77ce5857527e2ca0db79292c9160d3a449a5828",
        "games": [2560, 3071],
        "note": "fresh collection from cycle-5 checkpoint after the pre-capped partial was moved to incidents",
    },
    {
        "segment": "cycle-7-old-agent",
        "commits": "de36357 agent/driver (pre-retry)",
        "cycles": [7],
        "runner_mode": "run-rollout",
        "runner_sha256": "d8c2ee524e4a58b221986025d77ce5857527e2ca0db79292c9160d3a449a5828",
        "games": [3072, 3334],
        "note": "263 games collected before the infrastructure abort at game 3335",
    },
    {
        "segment": "cycle-7-game-3335-attempt-1-ABORTED",
        "commits": "de36357 agent/driver (pre-retry)",
        "cycles": [7],
        "runner_mode": "run-rollout",
        "runner_sha256": "d8c2ee524e4a58b221986025d77ce5857527e2ca0db79292c9160d3a449a5828",
        "games": [3335, 3335],
        "note": "learner proxy connection to the resident inference server broke mid-flight (agent_eof at ply 54); aborted report preserved at incidents/cycle-7-game-3335-agent-eof/; no training data produced; NOT part of the accepted 4096",
    },
    {
        "segment": "cycle-7-retry-agent",
        "commits": "d9ca5cc agent (transient-connection retry) / 24f6d74 driver",
        "cycles": [7],
        "runner_mode": "run-rollout",
        "runner_sha256": "d8c2ee524e4a58b221986025d77ce5857527e2ca0db79292c9160d3a449a5828",
        "games": [3335, 3583],
        "note": "game 3335 re-collected from the same frozen seed (4001667) plus games 3336-3583",
    },
    {
        "segment": "cycle-8",
        "commits": "d9ca5cc agent / 24f6d74 driver",
        "cycles": [8],
        "runner_mode": "run-rollout",
        "runner_sha256": "d8c2ee524e4a58b221986025d77ce5857527e2ca0db79292c9160d3a449a5828",
        "games": [3584, 4095],
        "note": "final cycle",
    },
]

INCIDENTS = [
    {
        "name": "cycle-6-pre-capped-2026-08-30T22-50",
        "path": "incidents/cycle-6-pre-capped-2026-08-30T22-50",
        "required_files": ["README.txt"],
        "description": "225 pre-capped cycle-6 games (run-match era) preserved before re-collection",
    },
    {
        "name": "cycle-7-game-3335-agent-eof",
        "path": "incidents/cycle-7-game-3335-agent-eof",
        "required_files": ["README.txt", "arena-config.json", "arena-report.json"],
        "description": "aborted attempt 1 of game 3335 (agent_eof at ply 54, seed 4001667)",
    },
]

ORIGINAL_CONTRACT_NOTE = (
    "The original v2 execution contract bytes were not preserved before the "
    "v3 rewrite on 2026-08-31 (the driver overwrote the file in place). The "
    "pre-rewrite execution identity recorded here was reconstructed from "
    "Git commit history (source hashes), artifact mtimes, and the driver "
    "progress log; it is a reconstruction, not the original bytes."
)


def cycle_attestation(cycle: int) -> dict[str, Any]:
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
    games = len(batch_doc.get("games", []))
    truncated = sum(1 for game in batch_doc["games"] if game["truncated"])
    max_plies = max(int(game["completed_plies"]) for game in batch_doc["games"])
    return {
        "cycle": cycle,
        "batch_sha256": file_sha256(batch),
        "manifest_sha256": file_sha256(manifest),
        "report_sha256": file_sha256(report_path),
        "checkpoint_file_sha256": file_sha256(checkpoint),
        "checkpoint_hash": payload["checkpoint_hash"],
        "report_checkpoint_hash": report["checkpoint_hash"],
        "games": games,
        "truncated_games": truncated,
        "manifest_ply_cap": int(manifest_doc["ply_cap"]),
        "observed_max_plies": max_plies,
        "records": int(report["records"]),
        "learning_rate": float(report["learning_rate"]),
    }


def generate(out: Path) -> None:
    ledger = {
        "format": LEDGER_FORMAT,
        "version": LEDGER_VERSION,
        "generated": "2026-08-31",
        "original_contract_note": ORIGINAL_CONTRACT_NOTE,
        "result": {
            "formal_run_training": "COMPLETE",
            "result": "VALID_WITH_RECORDED_INFRASTRUCTURE_RETRY",
            "accepted_games": 4096,
            "attempts": 4097,
            "terminal_games": 4095,
            "truncated_games": 1,
            "infrastructure_aborts": 1,
            "records": 182157,
        },
        "segments": SEGMENTS,
        "incidents": INCIDENTS,
        "cycles": [cycle_attestation(cycle) for cycle in range(1, 9)],
    }
    out.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "generated", "ledger": str(out)}))


def validate(ledger_path: Path) -> None:
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger.get("format") != LEDGER_FORMAT or ledger.get("version") != LEDGER_VERSION:
        raise SystemExit("unsupported ledger format/version")

    failures: list[str] = []

    # 1. Per-cycle content hashes re-hashed from disk.
    for attested in ledger["cycles"]:
        cycle = attested["cycle"]
        cycle_dir = ROOT / f"cycle-{cycle}"
        checks = (
            ("batch_sha256", cycle_dir / "batch.json"),
            ("manifest_sha256", cycle_dir / "materialization-manifest.json"),
            ("report_sha256", ROOT / f"cycle-{cycle}-train-report.json"),
            ("checkpoint_file_sha256", ROOT / f"cycle-{cycle}.pt"),
        )
        for field, path in checks:
            if not path.is_file():
                failures.append(f"cycle-{cycle}: missing {path.name}")
                continue
            actual = file_sha256(path)
            if actual != attested[field]:
                failures.append(f"cycle-{cycle}: {field} mismatch")
        if attested["games"] != 512:
            failures.append(f"cycle-{cycle}: attested {attested['games']} games, expected 512")
        if attested["manifest_ply_cap"] != 150:
            failures.append(f"cycle-{cycle}: manifest ply cap is not 150")

    # 2. The successful-game index covers 0..4095 exactly once.
    seen: dict[int, int] = {}
    for cycle in range(1, 9):
        batch = json.loads(
            (ROOT / f"cycle-{cycle}" / "batch.json").read_text(encoding="utf-8")
        )
        for game in batch["games"]:
            index = int(game["game_index"])
            seen[index] = seen.get(index, 0) + 1
    expected = set(range(4096))
    missing = sorted(expected - set(seen))
    duplicated = sorted(index for index, count in seen.items() if count > 1)
    out_of_range = sorted(set(seen) - expected)
    if missing:
        failures.append(f"missing game indices: {missing[:8]}{'…' if len(missing) > 8 else ''}")
    if duplicated:
        failures.append(f"duplicated game indices: {duplicated[:8]}")
    if out_of_range:
        failures.append(f"out-of-range game indices: {out_of_range[:8]}")

    # 3. Incidents exist with their required files.
    for incident in ledger["incidents"]:
        directory = ROOT / incident["path"]
        if not directory.is_dir():
            failures.append(f"incident directory missing: {incident['path']}")
            continue
        for name in incident["required_files"]:
            if not (directory / name).is_file():
                failures.append(
                    f"incident {incident['name']}: missing {name}"
                )

    # 4. Result-block arithmetic.
    result = ledger["result"]
    if result["terminal_games"] + result["truncated_games"] != result["accepted_games"]:
        failures.append("result block: terminal + truncated != accepted")
    if result["attempts"] != result["accepted_games"] + result["infrastructure_aborts"]:
        failures.append("result block: attempts != accepted + aborts")
    total_records = sum(entry["records"] for entry in ledger["cycles"])
    if total_records != result["records"]:
        failures.append(
            f"result block: records {result['records']} != sum of cycles {total_records}"
        )

    # 5. Segment coverage of the accepted index space: the accepted
    #    segments must tile 0..4095 exactly once. The aborted attempt at
    #    game 3335 is excluded from the accepted segments, and the retry
    #    segment re-covers index 3335 exactly once — so there is no
    #    overlap anywhere by construction.
    accepted_segments = [
        segment
        for segment in ledger["segments"]
        if "ABORTED" not in segment["segment"]
    ]
    covered: dict[int, int] = {}
    for segment in accepted_segments:
        for index in range(segment["games"][0], segment["games"][1] + 1):
            covered[index] = covered.get(index, 0) + 1
    if set(covered) != expected:
        failures.append("accepted segments do not cover exactly 0..4095")
    double_covered = sorted(index for index, count in covered.items() if count > 1)
    if double_covered:
        failures.append(f"accepted segments overlap on {double_covered}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "status": "valid",
                "cycles": len(ledger["cycles"]),
                "accepted_games": result["accepted_games"],
                "attempts": result["attempts"],
                "records": result["records"],
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
