"""M40A formal evaluation executor: physical two-seat rotation, resume
provenance, and canonical ledger discipline.

This module is the single executor behind ``m40a_run.py evaluate``. It
inherits the accepted M39A evaluation guarantees (``m39a_eval_runner.py``
/ ``m39a_eval_provenance.py``) and re-links them to the M40A four-gate
plan:

- every match is a formal ``run-match`` (argmax both sides, no ply cap);
- the PHYSICAL seat lineup follows the frozen rotation contract: the
  primary arm (H1 candidate=B, anchor B, league evaluated arm) sits at
  seat ``rotation`` and the secondary at ``1 - rotation`` — rotation 0
  and rotation 1 genuinely swap seats;
- resume never blind-trusts an existing ``arena-report.json``: every
  resumed slot is rebuilt from its artifact chain (exact frozen config,
  report identity/seed commitment/agent lineup, replay binding, strict
  referee verification);
- a config-only interrupted slot is recovered deterministically (the
  stale config is rewritten), mirroring the accepted M39A rule;
- the four ledgers are persisted canonically, validated against the
  EXACT expected identity sets, and hash-bound into the final report.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .m39a_collect import _opponent_agent
from .m39a_contract import file_sha256
from .m40a_contract import (
    M40A_AGENT_NAME,
)
from .m40a_constants import LEAGUE_ORDER

RUN_MANIFEST_FORMAT = "effective-splendor-m40a-evaluation-run-manifest"
RUN_MANIFEST_VERSION = 1
LEDGER_FORMAT = "effective-splendor-m40a-evaluation-ledger"
LEDGER_VERSION = 1

M07_AGENT_NAME = "effective-splendor-determinization-agent-v1"
M07_AGENT_VERSION = "1"
M35A_AGENT_NAME = "effective-splendor-m35a-direct-agent-v1"

# Ledger arm -> checkpoint arm letter (candidate is always B, the
# warm-start arm; baseline is always A).
ARM_LETTER = {"candidate": "B", "baseline": "A"}

H1_SEEDS = tuple(range(8_100_000, 8_100_127 + 1))
LEAGUE_SEEDS = tuple(range(8_200_000, 8_200_031 + 1))
M07_SEEDS = tuple(range(8_300_000, 8_300_063 + 1))
D2_SEEDS = tuple(range(8_400_000, 8_400_063 + 1))

# NON-FORMAL smoke seed namespaces (disjoint from every formal range by
# construction; a smoke run may NEVER consume a formal 8_1xx/8_2xx/8_3xx/
# 8_4xx seed). Smoke runs reuse the same executor path but a different
# out-root and a smoke manifest; their ledgers are never formal evidence.
SMOKE_SEED_BASE = 8_900_000
SMOKE_H1_SEEDS = (SMOKE_SEED_BASE,)
SMOKE_LEAGUE_SEEDS = (SMOKE_SEED_BASE + 100,)
SMOKE_M07_SEEDS = (SMOKE_SEED_BASE + 200,)
SMOKE_D2_SEEDS = (SMOKE_SEED_BASE + 300,)


def seeds_for_gate(gate: str, smoke: bool = False) -> tuple[int, ...]:
    if smoke:
        return {
            "h1": SMOKE_H1_SEEDS,
            "league": SMOKE_LEAGUE_SEEDS,
            "m07": SMOKE_M07_SEEDS,
            "d2": SMOKE_D2_SEEDS,
        }[gate]
    return {
        "h1": H1_SEEDS,
        "league": LEAGUE_SEEDS,
        "m07": M07_SEEDS,
        "d2": D2_SEEDS,
    }[gate]

# The frozen opponent action-seed offset shared by the paired rotations
# and the A/B league arms (identical for candidate and baseline on the
# same (pairing, seed) — the frozen CRN contract).
OPPONENT_ACTION_SEED_BASE = 20_261_000

# Ledger pairing label -> frozen opponent runtime. M07 is the Rust
# determinization agent; every other label maps to an m35a registry
# model id (the D2-v2 anchor's runtime is the M25-D2-v2 checkpoint,
# identical to the M39A baseline).
FROZEN_OPPONENTS = {"M07": "M07", "D2-v2": "M25-D2-v2", **{
    opponent: opponent for opponent in LEAGUE_ORDER
}}


def _frozen_opponent_agent(pairing: str, *, splendor: Path, catalog: Path,
                           action_seed: int, device: str) -> dict[str, Any]:
    if pairing not in FROZEN_OPPONENTS:
        raise ValueError(f"unknown frozen opponent pairing {pairing!r}")
    return _opponent_agent(
        FROZEN_OPPONENTS[pairing],
        splendor=splendor,
        catalog=catalog,
        action_seed=action_seed,
        device=device,
    )

EXPECTED_LEDGER_ROWS = {
    "h1": 512,        # 256 physical x (candidate + baseline perspectives)
    "league": 1152,   # (2 arms x 9 opponents x 32 seeds x 2 rotations)
    "m07": 128,
    "d2": 128,
}

RUNTIME_SOURCE_PATHS = {
    "orchestrator": "training/m17_gpu/m40a_run.py",
    "evaluator": "training/m17_gpu/splendor_gpu/m40a_evaluator.py",
    "m40a_agent": "training/m17_gpu/splendor_gpu/m40a_agent.py",
    "m40a_server": "training/m17_gpu/splendor_gpu/m40a_server.py",
    "m39a_collect": "training/m17_gpu/splendor_gpu/m39a_collect.py",
    "m35a_agent": "training/m17_gpu/splendor_gpu/m35a_agent.py",
    "m40a_gates": "training/m17_gpu/splendor_gpu/m40a_gates.py",
}


def rotated_agents(
    primary: dict[str, Any], secondary: dict[str, Any], rotation: int
) -> list[dict[str, Any]]:
    """THE canonical physical two-seat rotation.

    rotation 0 -> [primary, secondary]  (primary at seat 0)
    rotation 1 -> [secondary, primary]  (primary at seat 1)

    The primary's seat is therefore always ``rotation`` and the
    secondary's seat is ``1 - rotation``.
    """
    if rotation not in (0, 1):
        raise ValueError(f"rotation must be 0 or 1, got {rotation!r}")
    return [primary, secondary] if rotation == 0 else [secondary, primary]


def primary_seat(rotation: int) -> int:
    if rotation not in (0, 1):
        raise ValueError(f"rotation must be 0 or 1, got {rotation!r}")
    return rotation


def secondary_seat(rotation: int) -> int:
    return 1 - primary_seat(rotation)


def outcome_for_seat(seat: int, result: dict[str, Any]) -> str:
    """Map a terminal GameResult to one seat's win/draw/loss outcome."""
    winners = [int(w) for w in result.get("winners", [])]
    if len(winners) == 2:
        return "draw"
    if seat in winners:
        return "win"
    return "loss"


def _m40a_arm_agent(
    *,
    arm_letter: str,
    server: dict[str, Any],
    seed: int,
    sidecar: Path,
) -> dict[str, Any]:
    return {
        "program": sys.executable,
        "args": [
            "-m", "splendor_gpu.m40a_agent",
            "--checkpoint-sha256", server["checkpoint_file_sha256"],
            "--plan-hash", server["plan_hash"],
            "--arm", arm_letter,
            "--game-index", str(seed),
            "--sidecar-out", str(sidecar),
            "--server-url", server["server_url"],
            "--server-ready", server["server_ready"],
            "--action-selection", "argmax",
        ],
    }


def _match_dir(out_root: Path, gate: str, label: str, seed: int,
               rotation: int) -> Path:
    return out_root / gate / f"{label}-{seed}-r{rotation}"


def _game_id(gate: str, label: str, seed: int, rotation: int) -> str:
    return f"m40a-eval-{gate}-{label}-{seed}-r{rotation}"


def _seed_commitment(game_id: str, player_count: int, seed: int,
                     fingerprint_hex: str) -> str:
    """Recompute the v1 seed commitment (mirrors the Rust algorithm)."""
    hasher = hashlib.sha256()
    hasher.update(b"effective-splendor-seed-v1\x00")
    hasher.update(len(game_id).to_bytes(4, "little"))
    hasher.update(game_id.encode("utf-8"))
    hasher.update(bytes([player_count]))
    hasher.update(seed.to_bytes(8, "little"))
    hasher.update(fingerprint_hex.encode("ascii"))
    return hasher.hexdigest()


def _normalize_server_url(argv: list[str]) -> list[str]:
    """Freeze the dynamic resident-server port to a canonical token.

    The host must remain loopback; the port must be a valid dynamic port.
    Anything else is a tamper and fails the comparison downstream.
    """
    normalized = list(argv)
    if "--server-url" in normalized:
        index = normalized.index("--server-url")
        if index + 1 >= len(normalized):
            raise ValueError("valueless --server-url")
        value = normalized[index + 1]
        host, _, port_text = value.rpartition(":")
        if host != "127.0.0.1":
            raise ValueError(f"--server-url host {host!r} != frozen loopback 127.0.0.1")
        if not port_text.isdigit() or not (1024 <= int(port_text) <= 65535):
            raise ValueError(f"--server-url port {port_text!r} is not a valid dynamic port")
        normalized[index + 1] = "SERVER_URL"
    return normalized


class M40AEvalError(RuntimeError):
    """Fail-closed evaluation error."""


# ---------------------------------------------------------------------------
# Frozen slot contracts
# ---------------------------------------------------------------------------

def _slot_kinds(gate: str, label: str, rotation: int) -> dict[int, str]:
    """The expected agent kinds per PHYSICAL seat for one slot.

    H1:      primary = candidate B,  secondary = baseline A
    m07/d2:  primary = candidate B,  secondary = frozen opponent
    league:  primary = the evaluated arm, secondary = frozen league opponent

    The primary sits at seat ``rotation``; kinds are keyed by seat.
    """
    if gate == "h1":
        primary, secondary = "m40a:candidate", "m40a:baseline"
    elif gate in ("m07", "d2"):
        primary, secondary = "m40a:candidate", f"frozen:{label}"
    elif gate == "league":
        arm, opponent = label.split("-", 1)
        primary, secondary = f"m40a:{arm}", f"frozen:{opponent}"
    else:
        raise ValueError(f"unknown gate {gate!r}")
    if primary_seat(rotation) == 0:
        return {0: primary, 1: secondary}
    return {0: secondary, 1: primary}


def expected_slot_set(gate: str, smoke: bool = False) -> set[tuple[str, int, int]]:
    """The EXACT expected (label, seed, rotation) identity set per gate.

    H1 labels:        ``H1`` (candidate=B vs baseline=A)
    league labels:    ``candidate-<opponent>`` / ``baseline-<opponent>``
    m07/d2 labels:    ``M07`` / ``D2-v2`` (candidate=B only)

    ``smoke`` selects the non-formal smoke seed namespaces (disjoint from
    every formal range; smoke ledgers are never formal evidence).
    """
    if gate == "h1":
        return {
            ("H1", seed, rotation)
            for seed in seeds_for_gate("h1", smoke)
            for rotation in (0, 1)
        }
    if gate == "league":
        return {
            (f"{arm}-{opponent}", seed, rotation)
            for arm in ("candidate", "baseline")
            for opponent in LEAGUE_ORDER
            for seed in seeds_for_gate("league", smoke)
            for rotation in (0, 1)
        }
    if gate == "m07":
        return {
            ("M07", seed, rotation)
            for seed in seeds_for_gate("m07", smoke)
            for rotation in (0, 1)
        }
    if gate == "d2":
        return {
            ("D2-v2", seed, rotation)
            for seed in seeds_for_gate("d2", smoke)
            for rotation in (0, 1)
        }
    raise ValueError(f"unknown gate {gate!r}")


def _build_expected_config(
    *,
    gate: str,
    label: str,
    seed: int,
    rotation: int,
    out_root: Path,
    servers: dict[str, dict[str, Any]],
    splendor: Path,
    catalog: Path,
    device: str,
) -> tuple[dict[str, Any], dict[int, str]]:
    """The complete frozen arena config for one slot, plus its seat kinds.

    Paths embedded in agent argv (sidecars, ready files) are the SAME
    spellings the executor uses, so resume comparison is exact except
    for the dynamic server port (normalized by ``_normalize_server_url``).
    """
    match_dir = _match_dir(out_root, gate, label, seed, rotation)
    game_id = _game_id(gate, label, seed, rotation)
    action_seed = OPPONENT_ACTION_SEED_BASE + seed

    def arm_agent(arm_letter: str, seat: int) -> dict[str, Any]:
        return _m40a_arm_agent(
            arm_letter=arm_letter,
            server=servers[arm_letter],
            seed=seed,
            sidecar=match_dir / f"seat-{seat}.sidecar.json",
        )

    def opponent_agent(pairing: str) -> dict[str, Any]:
        return _frozen_opponent_agent(
            pairing, splendor=splendor, catalog=catalog,
            action_seed=action_seed, device=device,
        )

    if gate == "h1":
        primary = arm_agent("B", primary_seat(rotation))
        secondary = arm_agent("A", secondary_seat(rotation))
    elif gate in ("m07", "d2"):
        primary = arm_agent("B", primary_seat(rotation))
        secondary = opponent_agent(label)
    elif gate == "league":
        arm, opponent = label.split("-", 1)
        arm_letter = "B" if arm == "candidate" else "A"
        primary = arm_agent(arm_letter, primary_seat(rotation))
        secondary = opponent_agent(opponent)
    else:
        raise ValueError(f"unknown gate {gate!r}")

    kinds = _slot_kinds(gate, label, rotation)
    config = {
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 30_000,
        "shutdown_grace_ms": 2_000,
        "agents": rotated_agents(primary, secondary, rotation),
    }
    return config, kinds


# ---------------------------------------------------------------------------
# Resume provenance: rebuild one slot from its artifact chain
# ---------------------------------------------------------------------------

def _verify_config(actual: dict[str, Any], expected: dict[str, Any],
                   slot: str) -> None:
    for field in (
        "game_id", "seed", "handshake_timeout_ms", "move_timeout_ms",
        "shutdown_grace_ms",
    ):
        if actual.get(field) != expected[field]:
            raise M40AEvalError(
                f"slot {slot}: config {field} {actual.get(field)!r} != "
                f"frozen {expected[field]!r}"
            )
    actual_agents = actual.get("agents", [])
    expected_agents = expected["agents"]
    if len(actual_agents) != 2 or len(expected_agents) != 2:
        raise M40AEvalError(f"slot {slot}: config must have exactly two agents")
    for seat, (got, want) in enumerate(zip(actual_agents, expected_agents)):
        got_program = str(got.get("program", "")).strip()
        want_program = want["program"]
        if Path(got_program).resolve() != Path(want_program).resolve():
            raise M40AEvalError(
                f"slot {slot}: agent seat {seat} program mismatch "
                f"({got_program!r} != frozen {want_program!r})"
            )
        got_norm = _normalize_server_url([str(a) for a in got.get("args", [])])
        want_norm = _normalize_server_url(list(want["args"]))
        if got_norm != want_norm:
            raise M40AEvalError(
                f"slot {slot}: agent seat {seat} argv mismatch "
                f"(got {got_norm!r} != frozen {want_norm!r})"
            )


def _verify_report_agents(report: dict[str, Any], kinds: dict[str, str],
                          servers: dict[str, dict[str, Any]], slot: str) -> None:
    """The report's agent lineup must match the frozen seat assignment —
    name AND version per role (M40A arms identify by semantic hash;
    frozen opponents by their own frozen identities)."""
    report_agents = sorted(report.get("agents", []), key=lambda a: a.get("seat", -1))
    if len(report_agents) != 2 or [a.get("seat") for a in report_agents] != [0, 1]:
        raise M40AEvalError(f"slot {slot}: report agent seats are not exactly 0 and 1")
    for seat, report_agent in enumerate(report_agents):
        kind = kinds[seat]
        name = report_agent.get("agent_name")
        version = report_agent.get("agent_version")
        if kind.startswith("m40a:"):
            arm = kind.split(":", 1)[1]
            arm_letter = ARM_LETTER[arm]
            expected_version = servers[arm_letter]["checkpoint_hash"]
            if name != M40A_AGENT_NAME or version != expected_version:
                raise M40AEvalError(
                    f"slot {slot}: report seat {seat} M40A {arm_letter} identity "
                    f"mismatch ({name!r}@{version!r} != "
                    f"{M40A_AGENT_NAME!r}@{expected_version[:12]}…)"
                )
        elif kind.startswith("frozen:"):
            pairing = kind.split(":", 1)[1]
            if pairing == "M07":
                if name != M07_AGENT_NAME or version != M07_AGENT_VERSION:
                    raise M40AEvalError(
                        f"slot {slot}: report seat {seat} M07 identity mismatch "
                        f"({name!r}@{version!r})"
                    )
            else:
                expected_model = FROZEN_OPPONENTS[pairing]
                if name != M35A_AGENT_NAME or version != expected_model:
                    raise M40AEvalError(
                        f"slot {slot}: report seat {seat} frozen-opponent identity "
                        f"mismatch ({name!r}@{version!r}, expected model "
                        f"{expected_model!r})"
                    )
        else:
            raise M40AEvalError(f"slot {slot}: unknown agent kind {kind!r}")


def _rebuild_slot(
    *,
    gate: str,
    label: str,
    seed: int,
    rotation: int,
    out_root: Path,
    servers: dict[str, dict[str, Any]],
    splendor: Path,
    catalog: Path,
    device: str,
) -> dict[str, Any]:
    """Rebuild one slot's outcome from its artifacts, verifying the chain.

    Returns the rebuilt row WITHOUT the arm/pairing perspective fields
    (the caller adds those per the ledger schema).
    """
    slot = f"{gate}/{label}/{seed}/r{rotation}"
    match_dir = _match_dir(out_root, gate, label, seed, rotation)
    config_path = match_dir / "arena-config.json"
    report_path = match_dir / "arena-report.json"
    replay_path = match_dir / "replay.json"

    if not config_path.is_file():
        raise M40AEvalError(f"slot {slot}: missing config")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    expected_config, kinds = _build_expected_config(
        gate=gate, label=label, seed=seed, rotation=rotation,
        out_root=out_root, servers=servers, splendor=splendor,
        catalog=catalog, device=device,
    )
    _verify_config(config, expected_config, slot)

    if not report_path.is_file():
        # M40A has NO exempted non-termination slot: every missing report
        # on a resumable slot is a data-loss/tamper condition.
        raise M40AEvalError(
            f"slot {slot}: missing report — M40A has no exempted "
            "non-termination slot; every scheduled match must complete"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("game_id") != expected_config["game_id"]:
        raise M40AEvalError(f"slot {slot}: report game_id mismatch")
    if (
        report.get("format") != "effective-splendor-arena-report"
        or report.get("version") != 1
    ):
        raise M40AEvalError(f"slot {slot}: unsupported report format/version")
    if report.get("player_count") != 2:
        raise M40AEvalError(f"slot {slot}: report player_count is not 2")

    _verify_report_agents(report, kinds, servers, slot)

    fingerprint = report.get("ruleset_fingerprint", "")
    recomputed = _seed_commitment(
        expected_config["game_id"], 2, seed, fingerprint
    )
    if report.get("seed_commitment") != recomputed:
        raise M40AEvalError(f"slot {slot}: report seed commitment does not bind the slot")

    outcome = report.get("outcome", {})
    if outcome.get("status") != "completed":
        # M40A fail-closed rule: any abort / non-completion in a formal
        # measurement fails that measurement closed (recorded, no rerun).
        raise M40AEvalError(
            f"slot {slot}: outcome is not completed "
            f"({outcome.get('status')}: {outcome.get('reason', 'unknown')}) — "
            "fail closed"
        )
    if not replay_path.is_file():
        raise M40AEvalError(f"slot {slot}: missing replay")

    # Strict replay/referee verification via the Rust referee.
    verified = subprocess.run(
        [str(splendor), "verify-replay", "--input", str(replay_path)],
        capture_output=True, text=True, check=False,
    )
    if verified.returncode != 0:
        raise M40AEvalError(
            f"slot {slot}: replay failed verification: {verified.stderr[:200]}"
        )
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    if int(replay.get("seed", -1)) != seed:
        raise M40AEvalError(f"slot {slot}: replay seed mismatch")
    if replay.get("ruleset_fingerprint") != fingerprint:
        raise M40AEvalError(f"slot {slot}: replay ruleset fingerprint mismatch")
    result = outcome.get("result", {})
    if replay.get("result") != result:
        raise M40AEvalError(f"slot {slot}: report/replay result mismatch")
    if outcome.get("replay_final_hash") != replay.get("final_state_hash"):
        raise M40AEvalError(
            f"slot {slot}: report replay_final_hash does not match the replay"
        )
    # The M40A arm sidecars must exist and bind the arm identity.
    for seat, kind in kinds.items():
        if kind.startswith("m40a:"):
            arm_letter = ARM_LETTER[kind.split(":", 1)[1]]
            sidecar_path = match_dir / f"seat-{seat}.sidecar.json"
            if not sidecar_path.is_file():
                raise M40AEvalError(
                    f"slot {slot}: missing M40A {arm_letter} sidecar at seat {seat}"
                )
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            if (
                sidecar.get("format") != "effective-splendor-m40a-sidecar"
                or int(sidecar.get("version", 0)) != 1
            ):
                raise M40AEvalError(
                    f"slot {slot}: sidecar at seat {seat} is not an M40A v1 sidecar"
                )
            if sidecar.get("arm") != arm_letter:
                raise M40AEvalError(
                    f"slot {slot}: sidecar at seat {seat} arm "
                    f"{sidecar.get('arm')!r} != expected {arm_letter!r}"
                )
            if sidecar.get("game_id") != expected_config["game_id"]:
                raise M40AEvalError(
                    f"slot {slot}: sidecar at seat {seat} game_id mismatch"
                )
            if sidecar.get("checkpoint_sha256") != servers[arm_letter]["checkpoint_file_sha256"]:
                raise M40AEvalError(
                    f"slot {slot}: sidecar at seat {seat} checkpoint identity "
                    "mismatch"
                )
    return {
        "primary_outcome": outcome_for_seat(primary_seat(rotation), result),
        "secondary_outcome": outcome_for_seat(secondary_seat(rotation), result),
        "config_sha256": file_sha256(config_path),
        "report_sha256": file_sha256(report_path),
        "replay_sha256": file_sha256(replay_path),
    }


# ---------------------------------------------------------------------------
# Physical execution
# ---------------------------------------------------------------------------

def _run_physical_match(
    *,
    gate: str,
    label: str,
    seed: int,
    rotation: int,
    out_root: Path,
    servers: dict[str, dict[str, Any]],
    splendor: Path,
    catalog: Path,
    device: str,
) -> dict[str, Any]:
    """Execute (or resume-with-provenance) ONE physical match and return
    the rebuilt/outcome payload with artifact hashes."""
    match_dir = _match_dir(out_root, gate, label, seed, rotation)
    config_path = match_dir / "arena-config.json"
    report_path = match_dir / "arena-report.json"
    replay_path = match_dir / "replay.json"

    if report_path.is_file():
        # Resume is NOT a blind trust: rebuild from the artifact chain.
        return _rebuild_slot(
            gate=gate, label=label, seed=seed, rotation=rotation,
            out_root=out_root, servers=servers, splendor=splendor,
            catalog=catalog, device=device,
        )

    # No report: the only recoverable state is config-ONLY. Replay or
    # sidecar remains without a report are partial artifacts of an
    # interrupted publish and fail closed (preserve and diagnose), per
    # the accepted M39A rule.
    leftovers = [
        name for name in ("replay.json",)
        if (match_dir / name).is_file()
    ] + [p.name for p in match_dir.glob("seat-*.sidecar.json")] if match_dir.is_dir() else []
    if leftovers:
        raise M40AEvalError(
            f"slot {gate}/{label}/{seed}/r{rotation}: partial artifacts "
            f"without a report ({sorted(leftovers)}) — preserve and "
            "diagnose; not recoverable"
        )

    if config_path.exists():
        # config-only interrupted slot: the match never started (an
        # aborted match would have left a report). Deterministic
        # recovery: drop the stale config (it embeds the previous run's
        # dynamic server port) and re-execute the frozen slot.
        config_path.unlink()

    expected_config, _kinds = _build_expected_config(
        gate=gate, label=label, seed=seed, rotation=rotation,
        out_root=out_root, servers=servers, splendor=splendor,
        catalog=catalog, device=device,
    )
    match_dir.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_name(config_path.name + f".tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(expected_config, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, config_path)

    completed = subprocess.run(
        [
            str(splendor), "run-match",
            "--config", str(config_path),
            "--report-out", str(report_path),
            "--replay-out", str(replay_path),
        ],
        capture_output=True, text=True, timeout=60 * 60, check=False,
    )
    if completed.returncode != 0:
        stderr_text = completed.stderr or ""
        if "exceeded ply safety limit" in stderr_text:
            # M40A fail-closed rule: deterministic non-termination fails
            # the measurement closed (recorded; no rerun, no exemption).
            raise M40AEvalError(
                f"slot {gate}/{label}/{seed}/r{rotation}: deterministic "
                "non-termination (engine ply safety limit) — the formal "
                "measurement fails closed"
            )
        raise M40AEvalError(
            f"eval {gate}/{label}/{seed}/r{rotation} failed "
            f"rc={completed.returncode}: {stderr_text[:300]}"
        )
    # The freshly executed match is validated through the SAME rebuild
    # path (defense in depth: execution and resume share one contract).
    return _rebuild_slot(
        gate=gate, label=label, seed=seed, rotation=rotation,
        out_root=out_root, servers=servers, splendor=splendor,
        catalog=catalog, device=device,
    )


# ---------------------------------------------------------------------------
# Ledger schema, validation, canonical hash
# ---------------------------------------------------------------------------

def ledger_rows_for_slot(
    gate: str, label: str, seed: int, rotation: int, rebuilt: dict[str, Any]
) -> list[dict[str, Any]]:
    """Expand one rebuilt slot into its frozen ledger perspective rows.

    H1:      candidate row (arm=candidate, B's seat) + baseline row
             (arm=baseline, A's seat) — complementary outcomes.
    league:  one row for the evaluated arm.
    m07/d2:  one candidate row.
    """
    base = {
        "seed": seed,
        "rotation": rotation,
        "completed": True,
        "candidate_fault": False,
        "deterministic_nontermination": False,
        "config_sha256": rebuilt["config_sha256"],
        "report_sha256": rebuilt["report_sha256"],
        "replay_sha256": rebuilt["replay_sha256"],
    }
    if gate == "h1":
        return [
            {
                "arm": "candidate",
                "pairing": "H1",
                "outcome": rebuilt["primary_outcome"],
                **base,
            },
            {
                "arm": "baseline",
                "pairing": "H1",
                "outcome": rebuilt["secondary_outcome"],
                **base,
            },
        ]
    if gate in ("m07", "d2"):
        return [
            {
                "arm": "candidate",
                "pairing": label,
                "outcome": rebuilt["primary_outcome"],
                **base,
            }
        ]
    if gate == "league":
        arm, opponent = label.split("-", 1)
        return [
            {
                "arm": arm,
                "pairing": opponent,
                "outcome": rebuilt["primary_outcome"],
                **base,
            }
        ]
    raise ValueError(f"unknown gate {gate!r}")


def validate_ledger(gate: str, rows: list[dict[str, Any]],
                    smoke: bool = False) -> None:
    """EXACT identity-set validation before any statistics.

    H1:      every (seed, rotation) once, physically candidate+B and
             baseline+A perspective rows, complementary outcomes,
             rotations exactly {0, 1}.
    league:  every (arm, opponent, seed, rotation) once.
    m07/d2:  every (candidate, anchor, seed, rotation) once.

    No missing, duplicate, out-of-domain, or extra rows.
    """
    expected = expected_slot_set(gate, smoke)
    seen: dict[tuple[str, str, int, int], str] = {}
    for row in rows:
        if not row.get("completed"):
            raise M40AEvalError(f"{gate}: incomplete row — fail closed")
        if row.get("candidate_fault") or row.get("deterministic_nontermination"):
            raise M40AEvalError(f"{gate}: fault/non-termination present — fail closed")
        key = (str(row["arm"]), str(row["pairing"]), int(row["seed"]), int(row["rotation"]))
        if key in seen:
            raise M40AEvalError(f"{gate}: duplicate ledger identity {key}")
        seen[key] = str(row["outcome"])

    # Domain checks: arms, pairings, seeds, rotations.
    if gate == "h1":
        domain = {("candidate", "H1", seed, rotation)
                  for seed in seeds_for_gate("h1", smoke)
                  for rotation in (0, 1)}
        domain |= {("baseline", "H1", seed, rotation)
                   for seed in seeds_for_gate("h1", smoke)
                   for rotation in (0, 1)}
    elif gate == "league":
        domain = {(arm, opponent, seed, rotation)
                  for arm in ("candidate", "baseline")
                  for opponent in LEAGUE_ORDER
                  for seed in seeds_for_gate("league", smoke)
                  for rotation in (0, 1)}
    elif gate == "m07":
        domain = {("candidate", "M07", seed, rotation)
                  for seed in seeds_for_gate("m07", smoke)
                  for rotation in (0, 1)}
    elif gate == "d2":
        domain = {("candidate", "D2-v2", seed, rotation)
                  for seed in seeds_for_gate("d2", smoke)
                  for rotation in (0, 1)}
    else:
        raise ValueError(f"unknown gate {gate!r}")

    extra = set(seen) - domain
    if extra:
        raise M40AEvalError(f"{gate}: out-of-domain/extra ledger rows: {sorted(extra)[:4]}")
    missing = domain - set(seen)
    if missing:
        raise M40AEvalError(
            f"{gate}: missing {len(missing)} ledger identities "
            f"(e.g. {sorted(missing)[:4]})"
        )
    if len(rows) != len(domain):
        raise M40AEvalError(
            f"{gate}: row count {len(rows)} != expected {len(domain)}"
        )
    # Rotation completeness per (arm, pairing, seed): exactly {0, 1}.
    by_block: dict[tuple[str, str, int], set[int]] = {}
    for (arm, pairing, seed, rotation) in seen:
        by_block.setdefault((arm, pairing, seed), set()).add(rotation)
    for block, rotations in by_block.items():
        if rotations != {0, 1}:
            raise M40AEvalError(
                f"{gate}: block {block} rotations {sorted(rotations)} != [0, 1]"
            )

    if gate == "h1":
        # Complementary perspective pairs per physical match.
        complementary = {("win", "loss"), ("loss", "win"), ("draw", "draw")}
        for (_label, seed, rotation) in expected:
            candidate = seen[("candidate", "H1", seed, rotation)]
            baseline = seen[("baseline", "H1", seed, rotation)]
            if (candidate, baseline) not in complementary:
                raise M40AEvalError(
                    f"h1: non-complementary outcomes at ({seed}, r{rotation}): "
                    f"{candidate}/{baseline}"
                )


def canonical_ledger(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The canonical row ordering for hashing (sort by the identity key)."""
    return sorted(
        rows,
        key=lambda row: (
            str(row["arm"]), str(row["pairing"]), int(row["seed"]), int(row["rotation"])
        ),
    )


def ledger_document(gate: str, rows: list[dict[str, Any]],
                    bindings: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": LEDGER_FORMAT,
        "version": LEDGER_VERSION,
        "gate": gate,
        "bindings": bindings,
        "rows": [
            {
                "arm": row["arm"],
                "pairing": row["pairing"],
                "seed": row["seed"],
                "rotation": row["rotation"],
                "completed": row["completed"],
                "candidate_fault": row["candidate_fault"],
                "deterministic_nontermination": row["deterministic_nontermination"],
                "outcome": row["outcome"],
                "config_sha256": row["config_sha256"],
                "report_sha256": row["report_sha256"],
                "replay_sha256": row["replay_sha256"],
            }
            for row in canonical_ledger(rows)
        ],
    }


def ledger_hash(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Run manifest: provenance binding BEFORE any match executes
# ---------------------------------------------------------------------------

def run_manifest_identity(
    *,
    design_sha: str,
    plan_hash: str,
    schedule_hash: str,
    a_cycle4: dict[str, Any],
    b_cycle4: dict[str, Any],
    seed_families: dict[str, list[int]],
    executor_identity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "format": RUN_MANIFEST_FORMAT,
        "version": RUN_MANIFEST_VERSION,
        "design_sha": design_sha,
        "plan_hash": plan_hash,
        "schedule_hash": schedule_hash,
        "a_cycle4": a_cycle4,
        "b_cycle4": b_cycle4,
        "seed_families": seed_families,
        "executor": executor_identity,
    }


def establish_run_manifest(path: Path, identity: dict[str, Any]) -> None:
    """Create the run manifest before execution, or verify an existing
    one matches the current evaluation EXACTLY (fail closed on drift)."""
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != identity:
            differing = sorted(
                key
                for key in set(existing) | set(identity)
                if existing.get(key) != identity.get(key)
            )
            raise M40AEvalError(
                f"existing evaluation run manifest differs from the current "
                f"evaluation (fields: {differing}) — stale evaluation "
                "directory must be cleared deliberately, never reused"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(identity, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
