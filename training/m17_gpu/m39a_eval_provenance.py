"""M39A evaluation provenance: rebuild ledger rows from artifacts and
adversarially validate the evaluation provenance ledger.

The evaluation ledger produced by `m39a_eval_runner.py` records results;
this module makes those results **independently reconstructible** and binds
the frozen execution semantics:

- `rebuild` re-derives every ledger row from the on-disk per-match
  artifacts, verifying for each slot: the arena config matches the frozen
  contract **exactly** (game id, seed, timeouts, and the complete agent
  argv for each seat — candidate checkpoint/plan/argmax, M07 search
  parameters, m35a model ids, catalog); the Arena report's seed commitment
  is recomputed from (game_id, seed, ruleset fingerprint), the outcome's
  `replay_final_hash` equals the replay's final state hash, and the report
  agent lineup matches the config's seat assignment; and the replay itself
  passes strict referee verification.
- The provenance ledger binds per-match config/report/replay SHA-256, the
  executable, catalog, plan, candidate checkpoint, the runtime source
  identities (runner / m39a agent / m35a agent / server / gates), and the
  original evaluation ledger and gate report hashes.
- Non-termination evidence is validated **semantically**: the evidence
  config must equal the frozen slot config, exit status must be 1, and
  stderr must identify the ply safety limit — not merely hash-match.
- `validate` re-runs the full rebuild adversarially against frozen slot
  envelopes and bindings; it never trusts the ledger's self-reported lists.

Commands:
    python m39a_eval_provenance.py rebuild --gate g2 --ledger <eval-ledger.json> --out <prov.json>
    python m39a_eval_provenance.py validate --ledger <prov.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from splendor_gpu.m39a_contract import LEAGUE_ORDER, file_sha256, load_plan, plan_hash

ROOT = Path("local-artifacts").resolve()
REPO = Path(__file__).resolve().parent.parent.parent

PROV_FORMAT = "effective-splendor-m39a-evaluation-provenance-ledger"
PROV_VERSION = 3

SCORES = {"win": 1.0, "draw": 0.5, "loss": 0.0}

G2_DIR = ROOT / "m39a-eval-g2"
G3_DIR = ROOT / "m39a-eval-g3"

CANDIDATE_CHECKPOINT_FILE_SHA256 = (
    "ab7d1faada1e75cd226e14e324d634acbb643509f159a3f373e86b210f48041f"
)
CANDIDATE_CHECKPOINT_SEMANTIC_HASH = (
    "5fea7da5e6b394b3b1d1da413041f7826e1a604acebb0b3f4af242ca6d9b9cf3"
)
PLAN_HASH = "06cbd7b2413b7e640402799ff25c25ae57985ab3ea25b113b3eddf053f2841d6"
CATALOG_PATH = "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
EXE_REL = "target/release/splendor.exe"

# Canonical (LF-normalized) source SHA-256 identities. Two eras are
# recorded separately:
#
# - EXECUTION_*: the identities of the code that **actually executed the
#   1,664 evaluation matches** (commit aa98237). Historical facts; never
#   compared against the current checkout.
# - CURRENT_*: the identities of the runtime files the **validator itself**
#   depends on at validation time (this provenance module and the gates
#   evaluator). Drift here changes the validator, not the executed results,
#   and fails validation so the ledger is regenerated deliberately.
EXECUTION_COMMIT = "aa98237"
EXECUTION_SOURCE_SHA256 = {
    "eval_runner": "3fb12f6175db708ca677c4133b8d0eaddb7da1b2dccb2515d0ec484735e00537",
    "m39a_agent": "c0af0a47f7ad24169a228f595414b9d5544647e9132ad122a190334026a79dfe",
    "m35a_agent": "e8478d01cb5c972bd78d40c62cb073daea995b4659d091332f375d48f0394fbe",
    "m39a_server": "1a12afc739875650d201f7d42dbaede6594b2dda5bc24398cfb05001b2f79234",
    "m39a_gates": "3a8c3a1534e30ca571ec62f132c7b8cf53aa0bd4fcf2c2220f6261f166668d53",
}
# The validator-era identities checked against the working tree.
VALIDATOR_SOURCE_SHA256 = {
    "m39a_agent": "c0af0a47f7ad24169a228f595414b9d5544647e9132ad122a190334026a79dfe",
    "m35a_agent": "e8478d01cb5c972bd78d40c62cb073daea995b4659d091332f375d48f0394fbe",
    "m39a_server": "1a12afc739875650d201f7d42dbaede6594b2dda5bc24398cfb05001b2f79234",
    "m39a_gates": "3a8c3a1534e30ca571ec62f132c7b8cf53aa0bd4fcf2c2220f6261f166668d53",
}
RUNTIME_SOURCE_PATHS = {
    "eval_runner": "training/m17_gpu/m39a_eval_runner.py",
    "m39a_agent": "training/m17_gpu/splendor_gpu/m39a_agent.py",
    "m35a_agent": "training/m17_gpu/splendor_gpu/m35a_agent.py",
    "m39a_server": "training/m17_gpu/splendor_gpu/m39a_server.py",
    "m39a_gates": "training/m17_gpu/splendor_gpu/m39a_gates.py",
}

# Frozen content hashes of the result artifacts — compared as CONSTANTS,
# not re-read from mutable disk state at validation time.
FROZEN_EVALUATION_LEDGER_SHA256 = {
    "g2": "7686e8423d3e52c906e5a3aa875a1d092c204c4dc61a1ab51119c6cc186e42d9",
    "g3": "fd79b80ac00739574f7b081e2d268df7a1c55fcd882dc5c791a63a24149f16f3",
}
FROZEN_GATE_REPORT_SHA256 = {
    "g2": "37f8a1115cea8f7fbe1c99c6c4c126650dcd6ded2395cf8a9ae49674c3f30bc3",
    "g3": "c7409e25df0746d6f5f93b42176753b1e54950444ae17188e1af278486374a2f",
}
FROZEN_PLAN_SHA256 = None  # plan is hash-bound via PLAN_HASH (canonical JSON)
FROZEN_CATALOG_SHA256 = "4e6e5bc7f6134500fc501674e1be97dd34dd5306188dd2fb9220e6d8c58612d4"
FROZEN_RULESET_FINGERPRINT = (
    "1c43f598b23017fab5e9d8b0083942ad1a921d1df804f90d16cd0b4753961afb"
)

M39A_AGENT_NAME = "effective-splendor-m39a-policy-value-agent-v1"
M35A_AGENT_NAME = "effective-splendor-m35a-direct-agent-v1"
DETERMINIZATION_AGENT_NAME = "effective-splendor-determinization-agent-v1"

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

NONTERMINATION_SLOT = ("baseline", "M07", 5_000_029, 0)
NONTERMINATION_EVIDENCE_DIR = "m39a-eval-g2/nontermination-baseline-M07-5000029-r0"
NONTERMINATION_EVIDENCE_FILES = [
    "arena-config.json",
    "stdout.txt",
    "stderr.txt",
    "exit-status.txt",
]


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _slot_dir(base: Path, arm: str, pairing: str, seed: int, rotation: int) -> Path:
    return base / f"{arm}-{pairing}-{seed}-r{rotation}"


def _python_exe() -> Path:
    """The interpreter identity that executed the evaluation agents.

    A module-level indirection so tests can pin it to a synthetic path.
    """
    return Path(sys.executable).resolve()


def _expected_config(arm: str, pairing: str, seed: int, rotation: int, base: Path) -> dict[str, Any]:
    """The complete frozen arena config for a slot, as the runner writes it.

    Every field is exact: timeouts, game id, seed, and the full agent argv
    per seat. Paths are normalized to the same spellings the runner used so
    the comparison is byte-exact on semantics, not on absolute prefixes.
    """
    sidecar = (base / f"{arm}-{pairing}-{seed}-r{rotation}" / "eval-sidecar.json").resolve()
    server_ready = (base / "server-ready.json").resolve()
    catalog = (REPO / CATALOG_PATH).resolve()
    exe = (REPO / EXE_REL).resolve()
    python = _python_exe()

    candidate_argv = [
        "-m", "splendor_gpu.m39a_agent",
        "--checkpoint-sha256", CANDIDATE_CHECKPOINT_FILE_SHA256,
        "--plan-hash", PLAN_HASH,
        "--game-index", "0",
        "--sidecar-out", str(sidecar),
        "--server-url", "SERVER_URL",
        "--server-ready", str(server_ready),
        "--action-selection", "argmax",
    ]
    baseline_argv = [
        "-m", "splendor_gpu.m35a_agent",
        "--model-id", "M25-D2-v2",
        "--catalog", str(catalog),
        "--device", "cuda",
    ]
    m07_argv = [
        "agent-determinization",
        "--sample-seed", "20260810",
        "--sample-count", "4",
        "--max-depth-turns", "1",
        "--max-nodes", "2000",
    ]

    def league_argv(model_id: str) -> list[str]:
        return [
            "-m", "splendor_gpu.m35a_agent",
            "--model-id", model_id,
            "--catalog", str(catalog),
            "--device", "cuda",
        ]

    if arm == "candidate":
        arm_agent = {"program": str(python), "args": candidate_argv, "kind": "candidate"}
    else:
        arm_agent = {"program": str(python), "args": baseline_argv, "kind": "baseline"}

    if pairing == "M07":
        opponent = {"program": str(exe), "args": m07_argv, "kind": "m07"}
    else:
        opponent = {
            "program": str(python),
            "args": league_argv(pairing),
            "kind": f"league-{pairing}",
        }

    agents = [arm_agent, opponent] if rotation == 0 else [opponent, arm_agent]
    return {
        "game_id": f"m39a-eval-{arm}-{pairing}-{seed}-r{rotation}",
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 30_000,
        "shutdown_grace_ms": 2_000,
        "agents": agents,
    }


def _seed_commitment(game_id: str, player_count: int, seed: int, fingerprint_hex: str) -> str:
    """Recompute the v1 seed commitment (mirrors the Rust algorithm)."""
    import hashlib as _hashlib

    hasher = _hashlib.sha256()
    hasher.update(b"effective-splendor-seed-v1\x00")
    hasher.update(len(game_id).to_bytes(4, "little"))
    hasher.update(game_id.encode("utf-8"))
    hasher.update(bytes([player_count]))
    hasher.update(seed.to_bytes(8, "little"))
    hasher.update(fingerprint_hex.encode("ascii"))
    return hasher.hexdigest()


def _verify_config(actual: dict[str, Any], expected: dict[str, Any], slot: str) -> None:
    """Exact semantic comparison of the on-disk config against the frozen
    contract. Agent argv is compared flag-by-flag with the single dynamic
    exception of `--server-url` (the ephemeral resident-server port)."""
    for field in ("game_id", "seed", "handshake_timeout_ms", "move_timeout_ms", "shutdown_grace_ms"):
        if actual.get(field) != expected[field]:
            raise SystemExit(
                f"slot {slot}: config {field} {actual.get(field)!r} != "
                f"frozen {expected[field]!r}"
            )
    actual_agents = actual.get("agents", [])
    expected_agents = expected["agents"]
    if len(actual_agents) != 2 or len(expected_agents) != 2:
        raise SystemExit(f"slot {slot}: config must have exactly two agents")
    for seat, (got, want) in enumerate(zip(actual_agents, expected_agents)):
        # Program identity: the executable itself is part of the frozen
        # contract. Replacing python/splendor with an arbitrary binary
        # while keeping the argv unchanged is a tamper. The comparison is
        # on the resolved path, case-normalized for Windows.
        got_program = str(got.get("program", "")).strip()
        want_program = want["program"]
        if Path(got_program).resolve() != Path(want_program).resolve():
            raise SystemExit(
                f"slot {slot}: agent seat {seat} program mismatch "
                f"({got_program!r} != frozen {want_program!r})"
            )
        got_args = [str(a) for a in got.get("args", [])]
        want_args = want["args"]
        # Normalize the dynamic server URL.
        got_norm = list(got_args)
        if "--server-url" in got_norm:
            index = got_norm.index("--server-url")
            if index + 1 >= len(got_norm):
                raise SystemExit(f"slot {slot}: agent {seat} has a valueless --server-url")
            got_norm[index + 1] = "SERVER_URL"
        if got_norm != want_args:
            raise SystemExit(
                f"slot {slot}: agent seat {seat} argv mismatch "
                f"(got {got_norm!r} != frozen {want_args!r})"
            )


def _rebuild_row(
    base: Path, arm: str, pairing: str, seed: int, rotation: int
) -> dict[str, Any]:
    """Rebuild one row from the slot's artifacts, verifying the chain."""
    slot = f"{arm}/{pairing}/{seed}/r{rotation}"
    slot_dir = _slot_dir(base, arm, pairing, seed, rotation)
    config_path = slot_dir / "arena-config.json"
    report_path = slot_dir / "arena-report.json"
    replay_path = slot_dir / "replay.json"
    if not config_path.is_file():
        raise SystemExit(f"slot {slot}: missing config")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    expected_config = _expected_config(arm, pairing, seed, rotation, base)
    _verify_config(config, expected_config, slot)

    if not report_path.is_file():
        # Only the single frozen non-termination slot may lack a report.
        # Every other slot failing to produce a report is a data-loss or
        # tamper condition and fails closed immediately.
        if (arm, pairing, seed, rotation) != NONTERMINATION_SLOT:
            raise SystemExit(
                f"slot {slot}: missing report — only the frozen "
                f"non-termination slot {NONTERMINATION_SLOT} may lack one"
            )
        return {
            "arm": arm,
            "pairing": pairing,
            "seed": seed,
            "rotation": rotation,
            "completed": False,
            "candidate_fault": False,
            "deterministic_nontermination": True,
            "outcome": None,
            "config_sha256": file_sha256(config_path),
            "report_sha256": None,
            "replay_sha256": None,
        }

    report = json.loads(report_path.read_text(encoding="utf-8"))
    outcome = report.get("outcome", {})

    # Report identity and compatibility metadata.
    if report.get("game_id") != expected_config["game_id"]:
        raise SystemExit(f"slot {slot}: report game_id mismatch")
    if report.get("format") != "effective-splendor-arena-report" or report.get("version") != 1:
        raise SystemExit(f"slot {slot}: unsupported report format/version")
    if report.get("player_count") != 2:
        raise SystemExit(f"slot {slot}: report player_count is not 2")

    # Agent lineup in the report must match the config's seat assignment —
    # name AND version per role.
    report_agents = sorted(report.get("agents", []), key=lambda a: a.get("seat", -1))
    if len(report_agents) != 2 or [a.get("seat") for a in report_agents] != [0, 1]:
        raise SystemExit(f"slot {slot}: report agent seats are not exactly 0 and 1")
    expected_kinds = [agent["kind"] for agent in expected_config["agents"]]
    for seat, (report_agent, kind) in enumerate(zip(report_agents, expected_kinds)):
        name = report_agent.get("agent_name")
        version = report_agent.get("agent_version")
        if kind == "candidate":
            if name != M39A_AGENT_NAME or version != CANDIDATE_CHECKPOINT_SEMANTIC_HASH:
                raise SystemExit(
                    f"slot {slot}: report seat {seat} candidate identity mismatch "
                    f"({name!r}@{version!r})"
                )
        elif kind == "m07":
            if name != DETERMINIZATION_AGENT_NAME or version != "1":
                raise SystemExit(
                    f"slot {slot}: report seat {seat} M07 identity mismatch "
                    f"({name!r}@{version!r})"
                )
        elif kind == "baseline":
            if name != M35A_AGENT_NAME or version != "M25-D2-v2":
                raise SystemExit(
                    f"slot {slot}: report seat {seat} baseline identity mismatch "
                    f"({name!r}@{version!r})"
                )
        else:  # league-<model>
            expected_model = kind[len("league-"):]
            if name != M35A_AGENT_NAME or version != expected_model:
                raise SystemExit(
                    f"slot {slot}: report seat {seat} league identity mismatch "
                    f"({name!r}@{version!r}, expected model {expected_model!r})"
                )

    # Ruleset fingerprint must equal the frozen engine fingerprint (and the
    # replay's fingerprint is checked against the same constant below).
    fingerprint = report.get("ruleset_fingerprint", "")
    if fingerprint != FROZEN_RULESET_FINGERPRINT:
        raise SystemExit(
            f"slot {slot}: report ruleset fingerprint {fingerprint!r} != frozen"
        )

    # Seed commitment: recompute from (game_id, player_count, seed, fingerprint).
    fingerprint = report.get("ruleset_fingerprint", "")
    recomputed = _seed_commitment(
        expected_config["game_id"], 2, seed, fingerprint
    )
    if report.get("seed_commitment") != recomputed:
        raise SystemExit(f"slot {slot}: report seed commitment does not bind the slot")

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
            f"slot {slot}: report is not completed ({outcome.get('status')}) — "
            "only the ply-limit slot may lack a report"
        )
    if not replay_path.is_file():
        raise SystemExit(f"slot {slot}: missing replay")

    # Replay verification via the Rust referee.
    verified = subprocess.run(
        [str(REPO / EXE_REL), "verify-replay", "--input", str(replay_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if verified.returncode != 0:
        raise SystemExit(
            f"slot {slot}: replay failed verification: {verified.stderr[:200]}"
        )
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    if int(replay.get("seed", -1)) != seed:
        raise SystemExit(f"slot {slot}: replay seed mismatch")
    if replay.get("ruleset_fingerprint") != FROZEN_RULESET_FINGERPRINT:
        raise SystemExit(f"slot {slot}: replay ruleset fingerprint != frozen")
    result = outcome.get("result", {})
    if replay.get("result") != result:
        raise SystemExit(f"slot {slot}: report/replay result mismatch")
    # outcome.replay_final_hash must equal the replay's final state hash.
    if outcome.get("replay_final_hash") != replay.get("final_state_hash"):
        raise SystemExit(
            f"slot {slot}: report replay_final_hash does not match the replay"
        )
    row["replay_sha256"] = file_sha256(replay_path)

    winners = [int(seat) for seat in result.get("winners", [])]
    arm_seat = 0 if rotation == 0 else 1
    if len(winners) == 2:
        row["outcome"] = "draw"
    elif arm_seat in winners:
        row["outcome"] = "win"
    else:
        row["outcome"] = "loss"
    return row


def _runtime_bindings(gate: str) -> dict[str, Any]:
    """Bindings recorded into the ledger.

    Frozen constants are recorded as constants; the on-disk re-hash is
    done separately in `_failures_bindings` so that tampering with the
    artifacts after the fact is caught against the frozen value, not
    silently re-blessed by a rebuild.
    """
    plan_path = REPO / "benchmarks/m39a-arena-driven-policy-value-rl.plan.json"
    catalog_path = REPO / CATALOG_PATH
    exe_path = REPO / EXE_REL
    ledger_path = (G2_DIR if gate == "g2" else G3_DIR) / f"{gate}-ledger.json"
    report_path = (G2_DIR if gate == "g2" else G3_DIR) / f"{gate}-report.json"
    return {
        "plan_path": str(plan_path),
        "plan_hash": PLAN_HASH,
        "catalog_path": str(catalog_path),
        "catalog_file_sha256": FROZEN_CATALOG_SHA256,
        "executable_path": str(exe_path),
        "executable_sha256": file_sha256(exe_path),
        "candidate_checkpoint_path": str(ROOT / "m39a-formal-run/cycle-8.pt"),
        "candidate_checkpoint_file_sha256": CANDIDATE_CHECKPOINT_FILE_SHA256,
        "candidate_checkpoint_semantic_hash": CANDIDATE_CHECKPOINT_SEMANTIC_HASH,
        "execution_commit": EXECUTION_COMMIT,
        "execution_source_sha256": dict(EXECUTION_SOURCE_SHA256),
        "validator_source_sha256": dict(VALIDATOR_SOURCE_SHA256),
        "runtime_source_paths": dict(RUNTIME_SOURCE_PATHS),
        "ruleset_fingerprint": FROZEN_RULESET_FINGERPRINT,
        "original_evaluation_ledger_path": str(ledger_path),
        "original_evaluation_ledger_sha256": FROZEN_EVALUATION_LEDGER_SHA256[gate],
        "original_gate_report_path": str(report_path),
        "original_gate_report_sha256": FROZEN_GATE_REPORT_SHA256[gate],
    }


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
        "generated": "2026-09-01",
        "bindings": _runtime_bindings(gate),
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
    gate = ledger.get("gate")
    recomputed = _runtime_bindings(gate)
    for field, value in recomputed.items():
        if observed.get(field) != value:
            failures.append(f"binding {field} mismatch")

    # Frozen constants must match the CURRENT on-disk artifacts: any
    # post-hoc modification of the catalog, candidate checkpoint,
    # evaluation ledger, or gate report fails against the frozen value
    # (a rebuild alone cannot re-bless it).
    disk_checks = (
        ("catalog_file_sha256", REPO / CATALOG_PATH, FROZEN_CATALOG_SHA256),
        (
            "candidate_checkpoint_file_sha256",
            ROOT / "m39a-formal-run/cycle-8.pt",
            CANDIDATE_CHECKPOINT_FILE_SHA256,
        ),
        (
            "original_evaluation_ledger_sha256",
            (G2_DIR if gate == "g2" else G3_DIR) / f"{gate}-ledger.json",
            FROZEN_EVALUATION_LEDGER_SHA256[gate],
        ),
        (
            "original_gate_report_sha256",
            (G2_DIR if gate == "g2" else G3_DIR) / f"{gate}-report.json",
            FROZEN_GATE_REPORT_SHA256[gate],
        ),
    )
    for label, path, frozen in disk_checks:
        if not path.is_file():
            failures.append(f"binding {label}: artifact missing ({path})")
            continue
        actual = file_sha256(path)
        if actual != frozen:
            failures.append(
                f"binding {label}: on-disk artifact {actual[:16]}… != frozen "
                f"{frozen[:16]}… — post-hoc modification"
            )

    # The plan on disk must still hash to the frozen plan hash.
    from splendor_gpu.m39a_contract import load_plan as _load_plan
    from splendor_gpu.m39a_contract import plan_hash as _plan_hash

    try:
        if _plan_hash(_load_plan(REPO / "benchmarks/m39a-arena-driven-policy-value-rl.plan.json")) != PLAN_HASH:
            failures.append("binding plan_hash: on-disk plan drifted from the frozen plan")
    except Exception as error:  # noqa: BLE001
        failures.append(f"binding plan_hash: plan unreadable ({error})")

    # Validator-era source identities are checked against the current
    # repository files (LF-normalized). The execution-era identities are
    # historical facts recorded above and are NOT compared to the checkout
    # (the runner has legitimately evolved since aa98237).
    for key, path in RUNTIME_SOURCE_PATHS.items():
        if key not in VALIDATOR_SOURCE_SHA256:
            continue
        actual = _lf_sha256(REPO / path)
        if actual != VALIDATOR_SOURCE_SHA256[key]:
            failures.append(
                f"validator source {key} drifted from the frozen identity "
                f"({actual[:16]}… != {VALIDATOR_SOURCE_SHA256[key][:16]}…)"
            )
    return failures


def _failures_rows(ledger: dict[str, Any]) -> list[str]:
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

    # Semantic validation: the evidence must actually demonstrate the
    # non-termination, not merely hash-match itself.
    config_path = directory / "arena-config.json"
    if not config_path.is_file():
        failures.append("nontermination evidence missing arena-config.json")
    else:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            expected = _expected_config(*NONTERMINATION_SLOT, G2_DIR)
            _verify_config(config, expected, "evidence/nontermination")
        except SystemExit as error:
            failures.append(f"nontermination evidence config: {error}")

    exit_path = directory / "exit-status.txt"
    if not exit_path.is_file():
        failures.append("nontermination evidence missing exit-status.txt")
    else:
        text = exit_path.read_text(encoding="utf-8").strip()
        if text != "exit_code=1":
            failures.append(
                f"nontermination evidence exit status {text!r} != 'exit_code=1'"
            )

    stderr_path = directory / "stderr.txt"
    if not stderr_path.is_file():
        failures.append("nontermination evidence missing stderr.txt")
    else:
        stderr_text = stderr_path.read_text(encoding="utf-8")
        if "exceeded ply safety limit" not in stderr_text:
            failures.append(
                "nontermination evidence stderr does not identify the ply "
                "safety limit"
            )

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
