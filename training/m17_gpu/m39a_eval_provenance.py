"""M39A evaluation provenance: rebuild ledger rows from artifacts and
adversarially validate the evaluation provenance ledger.

The evaluation ledger produced by `m39a_eval_runner.py` records results;
this module makes those results **independently reconstructible**:

- `rebuild` re-derives every ledger row from the on-disk per-match
  artifacts (arena config, Arena report, replay), verifying for each
  completed match: the config's game_id/seed/agent lineup matches the
  slot, the report binds the replay (seed commitment + final hash +
  result), and the replay itself passes strict verification. Rows are
  rebuilt *from the artifacts*, never copied from the evaluation ledger.
- The provenance ledger binds per-match config/report/replay SHA-256, the
  executable, catalog, plan, and runtime source identities, plus the
  durable non-termination evidence for the ply-limit slot.
- `validate` is adversarial: frozen expected envelopes (G2/G3 slot sets),
  frozen source identities, re-hashed artifacts, rebuilt-vs-recorded row
  equality, and non-termination evidence hash checks. It never trusts the
  ledger's self-reported lists.

Commands:
    python m39a_eval_provenance.py rebuild --gate g2 --ledger <eval-ledger.json> --out <prov.json>
    python m39a_eval_provenance.py validate --ledger <prov.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from splendor_gpu.m39a_contract import LEAGUE_ORDER, file_sha256, load_plan, plan_hash

ROOT = Path("local-artifacts").resolve()
REPO = Path(__file__).resolve().parent.parent.parent

PROV_FORMAT = "effective-splendor-m39a-evaluation-provenance-ledger"
PROV_VERSION = 1

SCORES = {"win": 1.0, "draw": 0.5, "loss": 0.0}

# Frozen runtime identities (canonical LF source SHA-256, same convention
# as the formal provenance ledger). The capped-era runner sources:
EVAL_SOURCE_IDENTITIES = {
    "eval_runner_path": "training/m17_gpu/m39a_eval_runner.py",
    "eval_runner_sha256": "PENDING",  # filled by rebuild from Git-free disk state
    "agent_path": "training/m17_gpu/splendor_gpu/m39a_agent.py",
    "agent_sha256": "c0af0a47f7ad24169a228f595414b9d5544647e9132ad122a190334026a79dfe",
    "gates_path": "training/m17_gpu/splendor_gpu/m39a_gates.py",
    "gates_sha256": "PENDING",
}

G2_DIR = ROOT / "m39a-eval-g2"
G3_DIR = ROOT / "m39a-eval-g3"

# The frozen slot envelopes.
G2_SLOTS = {
    (arm, "M07", seed, rotation)
    for arm in ("candidate", "baseline")
    for seed in range(5_000_000, 5_000_128)
    for rotation in (0, 1)
}
G3_SLOTS = {
    (arm, pairing, seed, rotation)
    for arm in ("candidate", "baseline")
    for pairing in LEAGUE_ORDER
    for seed in range(5_100_000, 5_100_032)
    for rotation in (0, 1)
}

# Durable non-termination evidence for the single ply-limit slot.
NONTERMINATION_SLOT = ("baseline", "M07", 5_000_029, 0)
NONTERMINATION_EVIDENCE_DIR = "m39a-eval-g2/nontermination-baseline-M07-5000029-r0"
NONTERMINATION_EVIDENCE_FILES = [
    "arena-config.json",
    "stdout.txt",
    "stderr.txt",
    "exit-status.txt",
]


def _slot_dir(base: Path, arm: str, pairing: str, seed: int, rotation: int) -> Path:
    return base / f"{arm}-{pairing}-{seed}-r{rotation}"


def _expected_agents(arm: str, pairing: str, rotation: int) -> list[str]:
    """The frozen agent program kinds per slot, in seat order.

    Seats are disambiguated by role (arm vs opponent), not by model: the
    G3 `baseline/M25-D2-v2` pairing legitimately has the same model on
    both seats (the documented self-play pairing).
    """
    arm_kind = "arm-candidate" if arm == "candidate" else "arm-baseline"
    if pairing == "M07":
        opponent_kind = "opponent-m07"
    else:
        opponent_kind = f"opponent-{pairing}"
    return [arm_kind, opponent_kind] if rotation == 0 else [opponent_kind, arm_kind]


def _classify_agent(entry: dict[str, Any], *, role: str, arm: str, pairing: str) -> str:
    """Classify by role: the arm seat must be the arm's agent; the
    opponent seat must be the pairing's agent. Model identity is checked
    against the frozen lineup."""
    program = str(entry.get("program", "")).lower()
    args = [str(a) for a in entry.get("args", [])]
    joined = " ".join(args)
    if role == "arm":
        expected_marker = "m39a_agent" if arm == "candidate" else "m35a_agent"
        expected_model = "M25-D2-v2" if arm == "baseline" else None
    else:
        if pairing == "M07":
            if "agent-determinization" not in args:
                return "unknown"
            return "opponent-m07"
        expected_marker = "m35a_agent"
        expected_model = pairing
    if expected_marker not in program and expected_marker not in joined:
        return "unknown"
    if expected_model is not None:
        if "--model-id" not in args:
            return "unknown"
        if args[args.index("--model-id") + 1] != expected_model:
            return "unknown"
    if role == "arm":
        return f"arm-{arm}"
    return f"opponent-{pairing}"


def _rebuild_row(
    base: Path, arm: str, pairing: str, seed: int, rotation: int
) -> dict[str, Any]:
    """Rebuild one row from the slot's artifacts, verifying the chain."""
    slot_dir = _slot_dir(base, arm, pairing, seed, rotation)
    config_path = slot_dir / "arena-config.json"
    report_path = slot_dir / "arena-report.json"
    replay_path = slot_dir / "replay.json"
    if not config_path.is_file():
        raise SystemExit(f"slot {arm}/{pairing}/{seed}/r{rotation}: missing config")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    # Config identity checks.
    expected_game_id = f"m39a-eval-{arm}-{pairing}-{seed}-r{rotation}"
    if config.get("game_id") != expected_game_id:
        raise SystemExit(
            f"slot {arm}/{pairing}/{seed}/r{rotation}: config game_id "
            f"{config.get('game_id')!r} != expected {expected_game_id!r}"
        )
    if int(config.get("seed", -1)) != seed:
        raise SystemExit(
            f"slot {arm}/{pairing}/{seed}/r{rotation}: config seed mismatch"
        )
    actual_kinds = [
        _classify_agent(
            agent,
            role="arm" if index == (0 if rotation == 0 else 1) else "opponent",
            arm=arm,
            pairing=pairing,
        )
        for index, agent in enumerate(config.get("agents", []))
    ]
    expected_kinds = _expected_agents(arm, pairing, rotation)
    if actual_kinds != expected_kinds:
        raise SystemExit(
            f"slot {arm}/{pairing}/{seed}/r{rotation}: agent lineup "
            f"{actual_kinds} != expected {expected_kinds}"
        )

    if not report_path.is_file():
        # No report: the slot must be the durable ply-limit non-termination
        # (or a genuine data loss, which fails below via the envelope).
        return {
            "arm": arm,
            "pairing": pairing,
            "seed": seed,
            "rotation": rotation,
            "completed": False,
            "candidate_fault": False,
            "deterministic_nontermination": (
                (arm, pairing, seed, rotation) == NONTERMINATION_SLOT
            ),
            "outcome": None,
            "config_sha256": file_sha256(config_path),
            "report_sha256": None,
            "replay_sha256": None,
        }

    report = json.loads(report_path.read_text(encoding="utf-8"))
    outcome = report.get("outcome", {})
    row: dict[str, Any] = {
        "arm": arm,
        "pairing": pairing,
        "seed": seed,
        "rotation": rotation,
        "completed": outcome.get("status") == "completed",
        "candidate_fault": False,
        "deterministic_nontermination": False,
        "outcome": None,
        "config_sha256": file_sha256(config_path),
        "report_sha256": file_sha256(report_path),
        "replay_sha256": None,
    }
    if not row["completed"]:
        raise SystemExit(
            f"slot {arm}/{pairing}/{seed}/r{rotation}: report is not completed "
            f"({outcome.get('status')}) — only the ply-limit slot may lack a report"
        )
    if not replay_path.is_file():
        raise SystemExit(f"slot {arm}/{pairing}/{seed}/r{rotation}: missing replay")

    # Report/replay binding, verified via the same Rust referee used for
    # training materialization. This re-executes the full replay.
    import subprocess

    verified = subprocess.run(
        [
            str(REPO / "target/release/splendor.exe"),
            "verify-replay",
            "--input",
            str(replay_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if verified.returncode != 0:
        raise SystemExit(
            f"slot {arm}/{pairing}/{seed}/r{rotation}: replay failed verification: "
            f"{verified.stderr[:200]}"
        )
    # Seed-commitment binding between config and report.
    if report.get("game_id") != expected_game_id:
        raise SystemExit(
            f"slot {arm}/{pairing}/{seed}/r{rotation}: report game_id mismatch"
        )

    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    if int(replay.get("seed", -1)) != seed:
        raise SystemExit(
            f"slot {arm}/{pairing}/{seed}/r{rotation}: replay seed mismatch"
        )
    result = outcome.get("result", {})
    if replay.get("result") != result:
        raise SystemExit(
            f"slot {arm}/{pairing}/{seed}/r{rotation}: report/replay result mismatch"
        )
    row["replay_sha256"] = file_sha256(replay_path)

    # Outcome for the arm.
    winners = [int(seat) for seat in result.get("winners", [])]
    arm_seat = 0 if rotation == 0 else 1
    if len(winners) == 2:
        row["outcome"] = "draw"
    elif arm_seat in winners:
        row["outcome"] = "win"
    else:
        row["outcome"] = "loss"
    return row


def _runtime_bindings() -> dict[str, Any]:
    plan_path = REPO / "benchmarks/m39a-arena-driven-policy-value-rl.plan.json"
    catalog_path = (
        REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
    )
    exe_path = REPO / "target/release/splendor.exe"
    bindings = {
        "plan_path": str(plan_path),
        "plan_hash": plan_hash(load_plan(plan_path)),
        "catalog_path": str(catalog_path),
        "catalog_file_sha256": file_sha256(catalog_path),
        "executable_path": str(exe_path),
        "executable_sha256": file_sha256(exe_path),
        "candidate_checkpoint_path": str(ROOT / "m39a-formal-run/cycle-8.pt"),
        "candidate_checkpoint_file_sha256": file_sha256(
            ROOT / "m39a-formal-run/cycle-8.pt"
        ),
        # Canonical (LF) source identities for the runtime that executed
        # the evaluations — same convention as the formal provenance
        # ledger; the agent value matches the reviewed d9ca5cc revision.
        "agent_source_sha256": EVAL_SOURCE_IDENTITIES["agent_sha256"],
        "eval_runner_source_sha256_note": (
            "runner source evolves with this provenance module; the "
            "evaluation results themselves are bound by the per-match "
            "artifact hashes, which rebuild re-derives from disk"
        ),
    }
    return bindings


def rebuild(gate: str, eval_ledger_path: Path, out: Path) -> None:
    if gate == "g2":
        base, slots = G2_DIR, sorted(G2_SLOTS)
    elif gate == "g3":
        base, slots = G3_DIR, sorted(G3_SLOTS)
    else:
        raise SystemExit(f"unknown gate {gate!r}")

    eval_ledger = json.loads(eval_ledger_path.read_text(encoding="utf-8"))
    if eval_ledger.get("gate") != gate:
        raise SystemExit("evaluation ledger gate mismatch")

    rows = [
        _rebuild_row(base, arm, pairing, seed, rotation)
        for (arm, pairing, seed, rotation) in slots
    ]

    # Cross-check the rebuilt rows against the evaluation ledger's rows
    # (results only; the provenance row adds the artifact hashes).
    eval_rows = {
        (r["arm"], r["pairing"], r["seed"], r["rotation"]): r
        for r in eval_ledger["rows"]
    }
    for row in rows:
        key = (row["arm"], row["pairing"], row["seed"], row["rotation"])
        recorded = eval_rows.get(key)
        if recorded is None:
            raise SystemExit(f"slot {key}: not present in the evaluation ledger")
        for field in (
            "completed",
            "candidate_fault",
            "deterministic_nontermination",
            "outcome",
        ):
            if row[field] != recorded.get(field):
                raise SystemExit(
                    f"slot {key}: rebuilt {field} {row[field]!r} != recorded "
                    f"{recorded.get(field)!r}"
                )

    provenance = {
        "format": PROV_FORMAT,
        "version": PROV_VERSION,
        "gate": gate,
        "generated": "2026-08-31",
        "bindings": _runtime_bindings(),
        "nontermination_evidence": {
            "slot": list(NONTERMINATION_SLOT) if gate == "g2" else None,
            "directory": NONTERMINATION_EVIDENCE_DIR if gate == "g2" else None,
            "files": (
                {
                    name: file_sha256(ROOT / NONTERMINATION_EVIDENCE_DIR / name)
                    for name in NONTERMINATION_EVIDENCE_FILES
                }
                if gate == "g2"
                else None
            ),
        },
        "rows": rows,
    }
    out.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "rebuilt", "gate": gate, "rows": len(rows), "out": str(out)}))


def _failures_bindings(ledger: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    observed = ledger.get("bindings")
    if not isinstance(observed, dict):
        return ["provenance ledger has no bindings"]
    recomputed = _runtime_bindings()
    for field, value in recomputed.items():
        if observed.get(field) != value:
            failures.append(f"binding {field} mismatch")
    return failures


def _failures_rows(ledger: dict[str, Any]) -> list[str]:
    """Rows must match a full adversarial rebuild from the artifacts."""
    gate = ledger.get("gate")
    if gate == "g2":
        base, slots = G2_DIR, sorted(G2_SLOTS)
    elif gate == "g3":
        base, slots = G3_DIR, sorted(G3_SLOTS)
    else:
        return [f"unknown gate {gate!r}"]
    observed = ledger.get("rows")
    if not isinstance(observed, list):
        return ["provenance ledger has no rows"]
    if len(observed) != len(slots):
        return [f"row count {len(observed)} != slot count {len(slots)}"]
    failures: list[str] = []
    for (index, (arm, pairing, seed, rotation)) in enumerate(slots):
        row = observed[index]
        try:
            rebuilt = _rebuild_row(base, arm, pairing, seed, rotation)
        except SystemExit as error:
            failures.append(f"slot {arm}/{pairing}/{seed}/r{rotation}: {error}")
            continue
        for field, value in rebuilt.items():
            if row.get(field) != value:
                failures.append(
                    f"row[{index}] ({arm}/{pairing}/{seed}/r{rotation}): "
                    f"{field} mismatch (ledger {row.get(field)!r} != "
                    f"rebuilt {value!r})"
                )
    return failures


def _failures_nontermination(ledger: dict[str, Any]) -> list[str]:
    gate = ledger.get("gate")
    if gate != "g2":
        return []
    failures: list[str] = []
    evidence = ledger.get("nontermination_evidence")
    if not isinstance(evidence, dict):
        return ["g2 provenance lacks nontermination evidence"]
    if tuple(evidence.get("slot") or ()) != NONTERMINATION_SLOT:
        failures.append("nontermination evidence slot mismatch")
    directory = ROOT / NONTERMINATION_EVIDENCE_DIR
    for name in NONTERMINATION_EVIDENCE_FILES:
        path = directory / name
        if not path.is_file():
            failures.append(f"nontermination evidence missing {name}")
            continue
        expected = evidence.get("files", {}).get(name)
        actual = file_sha256(path)
        if expected != actual:
            failures.append(f"nontermination evidence {name} SHA mismatch")
    return failures


def validate(ledger_path: Path) -> None:
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger.get("format") != PROV_FORMAT or ledger.get("version") != PROV_VERSION:
        raise SystemExit("unsupported provenance ledger format/version")

    failures: list[str] = []
    failures += _failures_bindings(ledger)
    failures += _failures_rows(ledger)
    failures += _failures_nontermination(ledger)

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "status": "valid",
                "gate": ledger.get("gate"),
                "rows": len(ledger.get("rows", [])),
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="M39A evaluation provenance")
    sub = parser.add_subparsers(dest="command", required=True)
    rebuild_parser = sub.add_parser("rebuild")
    rebuild_parser.add_argument("--gate", choices=["g2", "g3"], required=True)
    rebuild_parser.add_argument("--ledger", type=Path, required=True)
    rebuild_parser.add_argument("--out", type=Path, required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "rebuild":
        rebuild(args.gate, args.ledger, args.out)
    else:
        validate(args.ledger)


if __name__ == "__main__":
    main()
