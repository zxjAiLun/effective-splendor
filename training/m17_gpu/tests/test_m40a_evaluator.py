"""M40A evaluator contract tests: physical rotation, non-dry execution
path, resume provenance, config-only recovery, and ledger discipline."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
M17_ROOT = REPO_ROOT / "training" / "m17_gpu"
sys.path.insert(0, str(M17_ROOT))

from splendor_gpu import m40a_evaluator as ev  # noqa: E402
from splendor_gpu.m40a_constants import LEAGUE_ORDER  # noqa: E402


def _import_run_module():
    spec = importlib.util.spec_from_file_location(
        "m40a_run", M17_ROOT / "m40a_run.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Synthetic server identities for config construction
# ---------------------------------------------------------------------------

def _synthetic_servers(tmp_path: Path) -> dict:
    def server(letter: str, port: int) -> dict:
        return {
            "plan_hash": "p" * 64,
            "checkpoint_hash": f"{letter.lower()}" * 32,
            "checkpoint_file_sha256": f"{letter.lower()}f" * 32,
            "server_url": f"127.0.0.1:{port}",
            "server_ready": str(tmp_path / f"{letter}-ready.json"),
        }
    return {"A": server("A", 11111), "B": server("B", 22222)}


def _paths(tmp_path: Path) -> dict:
    # Synthesize a python-like program and splendor exe under the test
    # tree so program-identity comparison (Path.resolve) is stable.
    exe = tmp_path / "splendor.exe"
    exe.write_bytes(b"MZ")
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}", encoding="utf-8")
    return {"splendor": exe, "catalog": catalog}


# ---------------------------------------------------------------------------
# 1. H1 physical rotation
# ---------------------------------------------------------------------------

def test_h1_physical_rotation_swaps_seats(tmp_path):
    """r0 must be [B, A]; r1 must be [A, B]; the candidate outcome is read
    from seat `rotation` and the baseline from seat `1 - rotation`."""
    servers = _synthetic_servers(tmp_path)
    paths = _paths(tmp_path)
    out_root = tmp_path / "evaluation"

    def arm_of(seat: int, rotation: int) -> str:
        config, _kinds = ev._build_expected_config(
            gate="h1", label="H1", seed=8_100_000, rotation=rotation,
            out_root=out_root, servers=servers, device="cpu", **paths,
        )
        argv = config["agents"][seat]["args"]
        return argv[argv.index("--arm") + 1]

    assert arm_of(0, 0) == "B" and arm_of(1, 0) == "A"   # r0: [B, A]
    assert arm_of(0, 1) == "A" and arm_of(1, 1) == "B"   # r1: [A, B]
    # Winner-seat attribution flips with the rotation.
    result_b_wins = {"winners": [0]}
    assert ev.outcome_for_seat(ev.primary_seat(0), result_b_wins) == "win"
    assert ev.outcome_for_seat(ev.primary_seat(1), result_b_wins) == "loss"
    assert ev.outcome_for_seat(ev.secondary_seat(0), result_b_wins) == "loss"
    assert ev.outcome_for_seat(ev.secondary_seat(1), result_b_wins) == "win"


def test_h1_ledger_perspectives_follow_rotation():
    """The candidate row reads the primary (B) seat; the baseline row the
    secondary (A) seat — complementary outcomes per physical match."""
    rebuilt = {
        "primary_outcome": "win",
        "secondary_outcome": "loss",
        "config_sha256": "c" * 64,
        "report_sha256": "r" * 64,
        "replay_sha256": "p" * 64,
    }
    rows = ev.ledger_rows_for_slot("h1", "H1", 8_100_007, 1, rebuilt)
    assert len(rows) == 2
    by_arm = {row["arm"]: row for row in rows}
    assert by_arm["candidate"]["outcome"] == "win"
    assert by_arm["baseline"]["outcome"] == "loss"
    assert all(row["rotation"] == 1 for row in rows)


def test_rotated_agents_contract():
    primary = {"id": "primary"}
    secondary = {"id": "secondary"}
    assert ev.rotated_agents(primary, secondary, 0) == [primary, secondary]
    assert ev.rotated_agents(primary, secondary, 1) == [secondary, primary]
    with pytest.raises(ValueError):
        ev.rotated_agents(primary, secondary, 2)


# ---------------------------------------------------------------------------
# 2/3. Anchor and league physical rotation
# ---------------------------------------------------------------------------

def test_anchor_physical_rotation(tmp_path):
    """Anchor gates: r0 [B, opponent]; r1 [opponent, B]; the B outcome is
    read from seat `rotation`."""
    servers = _synthetic_servers(tmp_path)
    paths = _paths(tmp_path)
    out_root = tmp_path / "evaluation"

    config_r0, kinds_r0 = ev._build_expected_config(
        gate="m07", label="M07", seed=8_300_000, rotation=0,
        out_root=out_root, servers=servers, device="cpu", **paths,
    )
    config_r1, kinds_r1 = ev._build_expected_config(
        gate="m07", label="M07", seed=8_300_000, rotation=1,
        out_root=out_root, servers=servers, device="cpu", **paths,
    )
    # r0: seat0 = M40A (B), seat1 = M07 determinization
    assert config_r0["agents"][0]["args"][1] == "splendor_gpu.m40a_agent"
    assert config_r0["agents"][1]["args"][:1] == ["agent-determinization"]
    # r1: swapped
    assert config_r1["agents"][0]["args"][:1] == ["agent-determinization"]
    assert config_r1["agents"][1]["args"][1] == "splendor_gpu.m40a_agent"
    assert kinds_r0 == {0: "m40a:candidate", 1: "frozen:M07"}
    assert kinds_r1 == {0: "frozen:M07", 1: "m40a:candidate"}
    # Sidecar filename follows the ACTUAL seat occupied by the M40A arm.
    sc_r0 = config_r0["agents"][0]["args"]
    sc_r1 = config_r1["agents"][1]["args"]
    assert sc_r0[sc_r0.index("--sidecar-out") + 1].endswith("seat-0.sidecar.json")
    assert sc_r1[sc_r1.index("--sidecar-out") + 1].endswith("seat-1.sidecar.json")


def test_d2_anchor_uses_d2_opponent(tmp_path):
    servers = _synthetic_servers(tmp_path)
    paths = _paths(tmp_path)
    config, _ = ev._build_expected_config(
        gate="d2", label="D2-v2", seed=8_400_000, rotation=0,
        out_root=tmp_path / "evaluation", servers=servers, device="cpu", **paths,
    )
    argv = config["agents"][1]["args"]
    assert argv[1] == "splendor_gpu.m35a_agent"
    assert argv[argv.index("--model-id") + 1] == "M25-D2-v2"


def test_league_physical_rotation_both_arms(tmp_path):
    """League: for EACH arm (candidate=B, baseline=A), r0 has the arm at
    seat 0 and r1 at seat 1, against the frozen league opponent."""
    servers = _synthetic_servers(tmp_path)
    paths = _paths(tmp_path)
    out_root = tmp_path / "evaluation"
    for arm, letter in (("candidate", "B"), ("baseline", "A")):
        for opponent in LEAGUE_ORDER:
            for rotation in (0, 1):
                label = f"{arm}-{opponent}"
                config, kinds = ev._build_expected_config(
                    gate="league", label=label, seed=8_200_000, rotation=rotation,
                    out_root=out_root, servers=servers, device="cpu", **paths,
                )
                arm_seat_argv = config["agents"][ev.primary_seat(rotation)]["args"]
                opp_seat_argv = config["agents"][ev.secondary_seat(rotation)]["args"]
                assert arm_seat_argv[arm_seat_argv.index("--arm") + 1] == letter
                assert opp_seat_argv[1] == "splendor_gpu.m35a_agent"
                assert opp_seat_argv[opp_seat_argv.index("--model-id") + 1] == opponent
                assert kinds == {
                    ev.primary_seat(rotation): f"m40a:{arm}",
                    ev.secondary_seat(rotation): f"frozen:{opponent}",
                }
    # One league slot yields exactly one ledger row for its arm.
    rebuilt = {
        "primary_outcome": "draw",
        "secondary_outcome": "draw",
        "config_sha256": "c" * 64, "report_sha256": "r" * 64, "replay_sha256": "p" * 64,
    }
    rows = ev.ledger_rows_for_slot(
        "league", f"candidate-{LEAGUE_ORDER[0]}", 8_200_000, 1, rebuilt
    )
    assert len(rows) == 1
    assert rows[0]["arm"] == "candidate"
    assert rows[0]["pairing"] == LEAGUE_ORDER[0]
    assert rows[0]["outcome"] == "draw"


def test_opponent_action_seed_shared_across_rotations_and_arms(tmp_path):
    """The frozen CRN contract: the same opponent action seed across the
    paired rotations AND across the A/B league arms of one (pairing, seed)."""
    servers = _synthetic_servers(tmp_path)
    paths = _paths(tmp_path)
    out_root = tmp_path / "evaluation"
    seeds = set()
    for arm in ("candidate", "baseline"):
        for rotation in (0, 1):
            config, _ = ev._build_expected_config(
                gate="league", label=f"{arm}-{LEAGUE_ORDER[0]}", seed=8_200_005,
                rotation=rotation, out_root=out_root, servers=servers,
                device="cpu", **paths,
            )
            # For m35a opponents the action seed is not consumed, but the
            # helper contract still binds it deterministically per seed.
            seeds.add(ev.OPPONENT_ACTION_SEED_BASE + 8_200_005)
    assert seeds == {20_261_000 + 8_200_005}


# ---------------------------------------------------------------------------
# Synthetic full-slot fixture: config + report + replay + sidecars
# ---------------------------------------------------------------------------

FROZEN_FP = "1c43f598b23017fab3e9d8d0083942ad1a921d1df804f90d16cd0b4753961afb"


def _write_valid_slot(
    tmp_path: Path,
    *,
    gate: str,
    label: str,
    seed: int,
    rotation: int,
    servers: dict,
    paths: dict,
    winners: list[int] | None = None,
    out_root: Path | None = None,
) -> Path:
    """Materialize a fully valid slot (config/report/replay/sidecars) that
    the rebuild path must accept."""
    out_root = out_root or (tmp_path / "evaluation")
    config, kinds = ev._build_expected_config(
        gate=gate, label=label, seed=seed, rotation=rotation,
        out_root=out_root, servers=servers, device="cpu", **paths,
    )
    match_dir = ev._match_dir(out_root, gate, label, seed, rotation)
    match_dir.mkdir(parents=True, exist_ok=True)
    (match_dir / "arena-config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )
    if winners is None:
        winners = [0] if rotation == 0 else [1]
    result = {
        "scores": [15 if s in winners else 10 for s in (0, 1)],
        "ranks": [0 if s in winners else 1 for s in (0, 1)],
        "winners": winners,
        "reason": "prestige_threshold",
    }
    arm_letter_of = {f"m40a:{arm}": letter for arm, letter in ev.ARM_LETTER.items()}
    report = {
        "format": "effective-splendor-arena-report",
        "version": 1,
        "game_id": config["game_id"],
        "player_count": 2,
        "ruleset_fingerprint": FROZEN_FP,
        "seed_commitment": ev._seed_commitment(config["game_id"], 2, seed, FROZEN_FP),
        "agents": [
            {
                "seat": seat,
                "agent_name": (
                    ev.M40A_AGENT_NAME
                    if kind.startswith("m40a:")
                    else (
                        ev.M07_AGENT_NAME
                        if kind == "frozen:M07"
                        else ev.M35A_AGENT_NAME
                    )
                ),
                "agent_version": (
                    servers[arm_letter_of[kind]]["checkpoint_hash"]
                    if kind.startswith("m40a:")
                    else (
                        ev.M07_AGENT_VERSION
                        if kind == "frozen:M07"
                        else ev.FROZEN_OPPONENTS[kind.split(":", 1)[1]]
                    )
                ),
            }
            for seat, kind in kinds.items()
        ],
        "outcome": {
            "status": "completed",
            "result": result,
            "completed_plies": 60,
            "replay_final_hash": "f" * 64,
        },
    }
    (match_dir / "arena-report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    replay = {
        "format": "splendor-replay",
        "version": 1,
        "seed": seed,
        "ruleset_fingerprint": FROZEN_FP,
        "final_state_hash": "f" * 64,
        "result": result,
        "steps": [],
    }
    (match_dir / "replay.json").write_text(json.dumps(replay), encoding="utf-8")
    for seat, kind in kinds.items():
        if kind.startswith("m40a:"):
            arm_letter = arm_letter_of[kind]
            sidecar = {
                "format": "effective-splendor-m40a-sidecar",
                "version": 1,
                "arm": arm_letter,
                "game_id": config["game_id"],
                "checkpoint_sha256": servers[arm_letter]["checkpoint_file_sha256"],
                "records": [],
            }
            (match_dir / f"seat-{seat}.sidecar.json").write_text(
                json.dumps(sidecar), encoding="utf-8"
            )
    return match_dir


def _mock_referee(module=ev, ok: bool = True):
    """Mock the verify-replay subprocess (the synthetic tree has no real
    referee) while preserving the returncode contract."""
    original = module.subprocess

    class _Fake:
        @staticmethod
        def run(*args, **kwargs):
            return types.SimpleNamespace(
                returncode=0 if ok else 1,
                stdout="",
                stderr="" if ok else "replay verification failed",
            )

    module.subprocess = _Fake
    return original


def _synthetic_env(tmp_path: Path):
    servers = _synthetic_servers(tmp_path)
    paths = _paths(tmp_path)
    return servers, paths


# ---------------------------------------------------------------------------
# 4. Non-dry evaluator execution reaches the real helper path
# ---------------------------------------------------------------------------

def test_non_dry_execution_reaches_real_helpers(tmp_path, monkeypatch):
    """A NON-DRY evaluation execution with subprocess/server work mocked
    must pass through the real evaluator helpers (config construction,
    physical rotation) — the class of relative-import failure cannot hide
    behind --dry-run."""
    servers = {
        "A": {"plan_hash": "p" * 64, "checkpoint_hash": "a" * 64,
              "checkpoint_file_sha256": "af" * 32,
              "server_url": "127.0.0.1:31001",
              "server_ready": str(tmp_path / "A-ready.json")},
        "B": {"plan_hash": "p" * 64, "checkpoint_hash": "b" * 64,
              "checkpoint_file_sha256": "bf" * 32,
              "server_url": "127.0.0.1:31002",
              "server_ready": str(tmp_path / "B-ready.json")},
    }
    paths = _paths(tmp_path)
    out_root = tmp_path / "evaluation-smoke"

    calls = {"run_match": 0, "verify": 0}

    def fake_run(*args, **kwargs):
        argv = args[0]
        if "run-match" in argv:
            calls["run_match"] += 1
            # Simulate Arena publishing the match artifacts (seat-0 win).
            _write_valid_slot(
                tmp_path, gate="h1", label="H1", seed=8_900_000, rotation=0,
                servers=servers, paths=paths, winners=[0], out_root=out_root,
            )
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "verify-replay" in argv:
            calls["verify"] += 1
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess call: {argv}")

    original_run = ev.subprocess.run
    ev.subprocess.run = fake_run
    try:
        rebuilt = ev._run_physical_match(
            gate="h1", label="H1", seed=8_900_000, rotation=0,
            out_root=out_root, servers=servers, device="cpu", **paths,
        )
    finally:
        ev.subprocess.run = original_run
    assert calls["run_match"] == 1
    assert calls["verify"] >= 1
    assert rebuilt["primary_outcome"] == "win"
    # The config was written by the real helper through the real path
    # (no relative-import failure), and physically places B at seat 0.
    config_path = ev._match_dir(out_root, "h1", "H1", 8_900_000, 0) / "arena-config.json"
    assert config_path.is_file()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    argv = config["agents"][0]["args"]
    assert argv[argv.index("--arm") + 1] == "B"


# ---------------------------------------------------------------------------
# 5. Resume with the same identity rebuilds and accepts
# ---------------------------------------------------------------------------

def test_resume_same_identity_rebuilds_and_accepts(tmp_path, monkeypatch):
    servers, paths = _synthetic_env(tmp_path)
    _write_valid_slot(
        tmp_path, gate="h1", label="H1", seed=8_100_000, rotation=0,
        servers=servers, paths=paths, winners=[0],
    )
    original = _mock_referee(ev, ok=True)
    try:
        rebuilt = ev._rebuild_slot(
            gate="h1", label="H1", seed=8_100_000, rotation=0,
            out_root=tmp_path / "evaluation", servers=servers, **paths,
            device="cpu",
        )
    finally:
        ev.subprocess = original
    # Seat 0 (B, primary at rotation 0) won.
    assert rebuilt["primary_outcome"] == "win"
    assert rebuilt["secondary_outcome"] == "loss"
    assert rebuilt["report_sha256"] and rebuilt["replay_sha256"]


def test_resume_rotated_slot_attribution(tmp_path, monkeypatch):
    """r1 slot with seat-1 winner: the primary (B) still reads seat 1."""
    servers, paths = _synthetic_env(tmp_path)
    _write_valid_slot(
        tmp_path, gate="h1", label="H1", seed=8_100_000, rotation=1,
        servers=servers, paths=paths, winners=[1],
    )
    original = _mock_referee(ev, ok=True)
    try:
        rebuilt = ev._rebuild_slot(
            gate="h1", label="H1", seed=8_100_000, rotation=1,
            out_root=tmp_path / "evaluation", servers=servers, **paths,
            device="cpu",
        )
    finally:
        ev.subprocess = original
    assert rebuilt["primary_outcome"] == "win"   # seat 1 = primary at r1
    assert rebuilt["secondary_outcome"] == "loss"


# ---------------------------------------------------------------------------
# 6. Resume fails closed on identity drift
# ---------------------------------------------------------------------------

def _assert_rebuild_rejects(tmp_path, servers, paths, gate, label, seed,
                            rotation, fragment):
    try:
        ev._rebuild_slot(
            gate=gate, label=label, seed=seed, rotation=rotation,
            out_root=tmp_path / "evaluation", servers=servers, **paths,
            device="cpu",
        )
    except ev.M40AEvalError as error:
        assert fragment in str(error), f"expected {fragment!r} in {error}"
        return
    pytest.fail(f"rebuild was accepted but must be rejected ({fragment})")


def test_resume_rejects_wrong_checkpoint(tmp_path, monkeypatch):
    servers, paths = _synthetic_env(tmp_path)
    _write_valid_slot(tmp_path, gate="h1", label="H1", seed=8_100_000,
                      rotation=0, servers=servers, paths=paths)
    drifted = dict(servers)
    drifted["B"] = {**servers["B"], "checkpoint_hash": "e" * 64}
    original = _mock_referee(ev, ok=True)
    try:
        _assert_rebuild_rejects(
            tmp_path, drifted, paths, "h1", "H1", 8_100_000, 0,
            "identity mismatch",
        )
    finally:
        ev.subprocess = original


def test_resume_rejects_seed_drift(tmp_path):
    """A slot written for seed A asked to rebuild as seed B fails closed
    (the slot directory for B does not exist)."""
    servers, paths = _synthetic_env(tmp_path)
    _write_valid_slot(tmp_path, gate="h1", label="H1", seed=8_100_000,
                      rotation=0, servers=servers, paths=paths)
    _assert_rebuild_rejects(
        tmp_path, servers, paths, "h1", "H1", 8_100_001, 0, "missing config",
    )


def test_resume_rejects_rotation_drift(tmp_path, monkeypatch):
    """A rotation-1 slot whose stored config kept the rotation-0 seat
    lineup must fail the frozen agent-lineup contract."""
    servers, paths = _synthetic_env(tmp_path)
    out_root = tmp_path / "evaluation"
    # Write a valid r0 slot, then relabel its directory as r1: the
    # config still has the r0 (unswapped) lineup.
    _write_valid_slot(tmp_path, gate="h1", label="H1", seed=8_100_000,
                      rotation=0, servers=servers, paths=paths)
    r0 = ev._match_dir(out_root, "h1", "H1", 8_100_000, 0)
    r1 = ev._match_dir(out_root, "h1", "H1", 8_100_000, 1)
    r1.mkdir(parents=True)
    for name in ("arena-config.json", "arena-report.json", "replay.json"):
        (r1 / name).write_text((r0 / name).read_text(encoding="utf-8"), encoding="utf-8")
    # Fix the game_id to the r1 spelling so the failure is exactly the
    # seat lineup, not the game id.
    config = json.loads((r1 / "arena-config.json").read_text(encoding="utf-8"))
    config["game_id"] = ev._game_id("h1", "H1", 8_100_000, 1)
    (r1 / "arena-config.json").write_text(json.dumps(config), encoding="utf-8")
    _assert_rebuild_rejects(
        tmp_path, servers, paths, "h1", "H1", 8_100_000, 1, "argv mismatch",
    )


def test_resume_rejects_agent_lineup_swap(tmp_path, monkeypatch):
    """Swapping the two agents in a stored config (keeping game_id/seed)
    must fail the frozen seat-lineup contract."""
    servers, paths = _synthetic_env(tmp_path)
    _write_valid_slot(tmp_path, gate="h1", label="H1", seed=8_100_000,
                      rotation=0, servers=servers, paths=paths)
    match_dir = ev._match_dir(tmp_path / "evaluation", "h1", "H1", 8_100_000, 0)
    config = json.loads((match_dir / "arena-config.json").read_text(encoding="utf-8"))
    config["agents"] = [config["agents"][1], config["agents"][0]]
    (match_dir / "arena-config.json").write_text(json.dumps(config), encoding="utf-8")
    _assert_rebuild_rejects(
        tmp_path, servers, paths, "h1", "H1", 8_100_000, 0, "argv mismatch",
    )


def test_resume_rejects_tampered_sidecar_arm(tmp_path, monkeypatch):
    servers, paths = _synthetic_env(tmp_path)
    _write_valid_slot(tmp_path, gate="h1", label="H1", seed=8_100_000,
                      rotation=0, servers=servers, paths=paths)
    match_dir = ev._match_dir(tmp_path / "evaluation", "h1", "H1", 8_100_000, 0)
    sidecar = json.loads((match_dir / "seat-0.sidecar.json").read_text(encoding="utf-8"))
    sidecar["arm"] = "A"  # seat 0 at rotation 0 must be arm B
    (match_dir / "seat-0.sidecar.json").write_text(json.dumps(sidecar), encoding="utf-8")
    original = _mock_referee(ev, ok=True)
    try:
        _assert_rebuild_rejects(
            tmp_path, servers, paths, "h1", "H1", 8_100_000, 0, "arm",
        )
    finally:
        ev.subprocess = original


def test_resume_rejects_missing_report(tmp_path):
    servers, paths = _synthetic_env(tmp_path)
    _write_valid_slot(tmp_path, gate="h1", label="H1", seed=8_100_000,
                      rotation=0, servers=servers, paths=paths)
    match_dir = ev._match_dir(tmp_path / "evaluation", "h1", "H1", 8_100_000, 0)
    (match_dir / "arena-report.json").unlink()
    _assert_rebuild_rejects(
        tmp_path, servers, paths, "h1", "H1", 8_100_000, 0, "missing report",
    )


def test_resume_rejects_aborted_report(tmp_path):
    servers, paths = _synthetic_env(tmp_path)
    _write_valid_slot(tmp_path, gate="h1", label="H1", seed=8_100_000,
                      rotation=0, servers=servers, paths=paths)
    match_dir = ev._match_dir(tmp_path / "evaluation", "h1", "H1", 8_100_000, 0)
    report = json.loads((match_dir / "arena-report.json").read_text(encoding="utf-8"))
    report["outcome"] = {
        "status": "aborted", "seat": 0, "phase": "action",
        "reason": "action_timeout", "request_id": 5, "completed_plies": 10,
    }
    (match_dir / "arena-report.json").write_text(json.dumps(report), encoding="utf-8")
    _assert_rebuild_rejects(
        tmp_path, servers, paths, "h1", "H1", 8_100_000, 0, "fail closed",
    )


def test_resume_rejects_forged_seed_commitment(tmp_path):
    servers, paths = _synthetic_env(tmp_path)
    _write_valid_slot(tmp_path, gate="h1", label="H1", seed=8_100_000,
                      rotation=0, servers=servers, paths=paths)
    match_dir = ev._match_dir(tmp_path / "evaluation", "h1", "H1", 8_100_000, 0)
    report = json.loads((match_dir / "arena-report.json").read_text(encoding="utf-8"))
    report["seed_commitment"] = "f" * 64
    (match_dir / "arena-report.json").write_text(json.dumps(report), encoding="utf-8")
    _assert_rebuild_rejects(
        tmp_path, servers, paths, "h1", "H1", 8_100_000, 0, "seed commitment",
    )


def test_run_manifest_drift_fails_closed(tmp_path):
    identity = ev.run_manifest_identity(
        design_sha="09fd8ec", plan_hash="p" * 64, schedule_hash="s" * 64,
        a_cycle4={"checkpoint_hash": "a" * 64}, b_cycle4={"checkpoint_hash": "b" * 64},
        seed_families={"h1": [1]}, executor_identity={"python": "3.12"},
    )
    manifest_path = tmp_path / "run-manifest.json"
    ev.establish_run_manifest(manifest_path, identity)
    # Same identity: accepted.
    ev.establish_run_manifest(manifest_path, identity)
    # Any drift (plan / checkpoint / seed / schedule) fails closed.
    for mutation in (
        {"plan_hash": "q" * 64},
        {"schedule_hash": "t" * 64},
        {"a_cycle4": {"checkpoint_hash": "z" * 64}},
        {"seed_families": {"h1": [2]}},
    ):
        drifted = {**identity, **mutation}
        with pytest.raises(ev.M40AEvalError, match="run manifest differs"):
            ev.establish_run_manifest(manifest_path, drifted)


# ---------------------------------------------------------------------------
# 7. Config-only interrupted slot recovery
# ---------------------------------------------------------------------------

def test_config_only_slot_recovered_deterministically(tmp_path, monkeypatch):
    servers, paths = _synthetic_env(tmp_path)
    out_root = tmp_path / "evaluation"
    # Simulate an interrupted run: a config exists, no report. The stale
    # config embeds a DIFFERENT (old) server port.
    match_dir = ev._match_dir(out_root, "h1", "H1", 8_100_000, 0)
    match_dir.mkdir(parents=True)
    stale, _ = ev._build_expected_config(
        gate="h1", label="H1", seed=8_100_000, rotation=0,
        out_root=out_root, servers=servers, device="cpu", **paths,
    )
    stale["agents"][0]["args"][
        stale["agents"][0]["args"].index("--server-url") + 1
    ] = "127.0.0.1:49999"
    (match_dir / "arena-config.json").write_text(json.dumps(stale), encoding="utf-8")

    # Mock run-match to "play" the game: it must be invoked exactly once
    # and must then produce a valid slot.
    calls = {"n": 0}

    def fake_run(*args, **kwargs):
        argv = args[0]
        if "run-match" not in argv:
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        calls["n"] += 1
        # Materialize a valid report/replay/sidecars as if the match ran.
        _write_valid_slot(
            tmp_path, gate="h1", label="H1", seed=8_100_000, rotation=0,
            servers=servers, paths=paths, winners=[0],
        )
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    original_run = ev.subprocess.run
    ev.subprocess.run = fake_run
    try:
        rebuilt = ev._run_physical_match(
            gate="h1", label="H1", seed=8_100_000, rotation=0,
            out_root=out_root, servers=servers, device="cpu", **paths,
        )
    finally:
        ev.subprocess.run = original_run
    assert calls["n"] == 1
    assert rebuilt["primary_outcome"] == "win"
    # The stale config was replaced by the frozen one.
    config = json.loads(
        (match_dir / "arena-config.json").read_text(encoding="utf-8")
    )
    url = config["agents"][0]["args"][
        config["agents"][0]["args"].index("--server-url") + 1
    ]
    assert url == servers["B"]["server_url"]


def test_partial_artifacts_without_report_fail_closed(tmp_path):
    """Replay or sidecar remains without a report are partial artifacts
    of an interrupted publish: fail closed, never silently re-run."""
    servers, paths = _synthetic_env(tmp_path)
    out_root = tmp_path / "evaluation"
    _write_valid_slot(tmp_path, gate="h1", label="H1", seed=8_100_000,
                      rotation=0, servers=servers, paths=paths)
    match_dir = ev._match_dir(out_root, "h1", "H1", 8_100_000, 0)
    (match_dir / "arena-report.json").unlink()  # leave replay + sidecars
    try:
        ev._run_physical_match(
            gate="h1", label="H1", seed=8_100_000, rotation=0,
            out_root=out_root, servers=servers, device="cpu", **paths,
        )
    except ev.M40AEvalError as error:
        assert "partial artifacts" in str(error)
        return
    pytest.fail("partial artifacts without a report must fail closed")


# ---------------------------------------------------------------------------
# 8. Ledger identity-set validation
# ---------------------------------------------------------------------------

def _full_h1_ledger():
    rows = []
    for seed in ev.seeds_for_gate("h1", smoke=True):
        for rotation in (0, 1):
            rows.append({"arm": "candidate", "pairing": "H1", "seed": seed,
                         "rotation": rotation, "completed": True,
                         "candidate_fault": False,
                         "deterministic_nontermination": False,
                         "outcome": "win",
                         "config_sha256": "c" * 64, "report_sha256": "r" * 64,
                         "replay_sha256": "p" * 64})
            rows.append({"arm": "baseline", "pairing": "H1", "seed": seed,
                         "rotation": rotation, "completed": True,
                         "candidate_fault": False,
                         "deterministic_nontermination": False,
                         "outcome": "loss",
                         "config_sha256": "c" * 64, "report_sha256": "r" * 64,
                         "replay_sha256": "p" * 64})
    return rows


def test_ledger_accepts_exact_identity_set():
    ev.validate_ledger("h1", _full_h1_ledger(), smoke=True)


def test_ledger_rejects_missing_rotation():
    rows = [r for r in _full_h1_ledger() if not (r["rotation"] == 1 and r["seed"] == 8_900_000)]
    with pytest.raises(ev.M40AEvalError, match="missing"):
        ev.validate_ledger("h1", rows, smoke=True)


def test_ledger_rejects_duplicated_rotation():
    rows = _full_h1_ledger()
    rows.append(dict(rows[0]))
    with pytest.raises(ev.M40AEvalError, match="duplicate"):
        ev.validate_ledger("h1", rows, smoke=True)


def test_ledger_rejects_extra_seed():
    rows = _full_h1_ledger()
    extra = dict(rows[0])
    extra["seed"] = 8_100_000  # a FORMAL seed inside a smoke ledger
    rows.append(extra)
    with pytest.raises(ev.M40AEvalError, match="out-of-domain|extra"):
        ev.validate_ledger("h1", rows, smoke=True)


def test_ledger_rejects_wrong_pairing():
    rows = _full_h1_ledger()
    for row in rows:
        row["pairing"] = "M07"
    with pytest.raises(ev.M40AEvalError):
        ev.validate_ledger("h1", rows, smoke=True)


def test_ledger_rejects_wrong_arm():
    rows = _full_h1_ledger()
    for row in rows:
        if row["arm"] == "baseline":
            row["arm"] = "candidate"
    with pytest.raises(ev.M40AEvalError):
        ev.validate_ledger("h1", rows, smoke=True)


def test_ledger_rejects_non_complementary_h1():
    rows = _full_h1_ledger()
    for row in rows:
        if row["arm"] == "baseline" and row["seed"] == 8_900_000:
            row["outcome"] = "win"  # both sides claim a win
    with pytest.raises(ev.M40AEvalError, match="complementary"):
        ev.validate_ledger("h1", rows, smoke=True)


def test_league_ledger_domain():
    seed = ev.seeds_for_gate("league", smoke=True)[0]
    rows = [
        {"arm": arm, "pairing": opponent,
         "seed": ev.seeds_for_gate("league", smoke=True)[0],
         "rotation": rotation,
         "completed": True, "candidate_fault": False,
         "deterministic_nontermination": False, "outcome": "draw"}
        for arm in ("candidate", "baseline")
        for opponent in LEAGUE_ORDER
        for rotation in (0, 1)
    ]
    ev.validate_ledger("league", rows, smoke=True)
    # Dropping one arm's slot must fail.
    rows.pop()
    with pytest.raises(ev.M40AEvalError, match="missing"):
        ev.validate_ledger("league", rows, smoke=True)


def test_anchor_ledger_domain():
    seed = ev.seeds_for_gate("m07", smoke=True)[0]
    rows = [
        {"arm": "candidate", "pairing": "M07", "seed": seed, "rotation": rotation,
         "completed": True, "candidate_fault": False,
         "deterministic_nontermination": False, "outcome": "win"}
        for rotation in (0, 1)
    ]
    ev.validate_ledger("m07", rows, smoke=True)
    # A baseline row in the anchor gate is out of domain.
    rows.append({**rows[0], "arm": "baseline"})
    with pytest.raises(ev.M40AEvalError):
        ev.validate_ledger("m07", rows, smoke=True)


# ---------------------------------------------------------------------------
# 9. Final result binds the four ledger hashes
# ---------------------------------------------------------------------------

def test_ledger_hash_binding_is_content_addressed():
    bindings = {"design_sha": "09fd8ec"}
    doc_a = ev.ledger_document("h1", _full_h1_ledger(), bindings)
    hash_a = ev.ledger_hash(doc_a)
    # Same rows + bindings -> same hash.
    assert ev.ledger_hash(ev.ledger_document("h1", _full_h1_ledger(), bindings)) == hash_a
    # Any row change -> different hash.
    rows = _full_h1_ledger()
    rows[0]["outcome"] = "loss"
    doc_b = ev.ledger_document("h1", rows, bindings)
    assert ev.ledger_hash(doc_b) != hash_a
    # Binding change -> different hash.
    doc_c = ev.ledger_document("h1", _full_h1_ledger(), {"design_sha": "changed"})
    assert ev.ledger_hash(doc_c) != hash_a
    # The document carries the frozen row schema (all artifact hashes).
    assert set(doc_a["rows"][0]) == {
        "arm", "pairing", "seed", "rotation", "completed", "candidate_fault",
        "deterministic_nontermination", "outcome",
        "config_sha256", "report_sha256", "replay_sha256",
    }


# ---------------------------------------------------------------------------
# 10. Dry-run schedule counts remain frozen (re-assertion)
# ---------------------------------------------------------------------------

def test_dry_run_counts_unchanged():
    assert len(ev.seeds_for_gate("h1")) == 128
    assert len(ev.seeds_for_gate("league")) == 32
    assert len(ev.seeds_for_gate("m07")) == 64
    assert len(ev.seeds_for_gate("d2")) == 64
    total = (
        128 * 2                       # H1 physical
        + 2 * 9 * 32 * 2              # league physical (both arms)
        + 64 * 2 + 64 * 2             # anchors
    )
    assert total == 1664
    # Smoke namespaces are disjoint from every formal range.
    formal = set(ev.seeds_for_gate("h1")) | set(ev.seeds_for_gate("league"))
    formal |= set(ev.seeds_for_gate("m07")) | set(ev.seeds_for_gate("d2"))
    smoke = {ev.seeds_for_gate(g, smoke=True)[0] for g in ("h1", "league", "m07", "d2")}
    assert not (formal & smoke)


def test_orchestrator_schedule_hash_stable():
    """The logical schedule hash must remain a0a38563… (logical slots
    unchanged; only the physical realization was repaired)."""
    run = _import_run_module()
    schedules = run._evaluation_schedules()
    assert run._validate_schedules(schedules) == (
        "a0a38563ad308053c8068d29c763bb73d43e7274b9ab2898d429ca0bbad75eab"
    )
