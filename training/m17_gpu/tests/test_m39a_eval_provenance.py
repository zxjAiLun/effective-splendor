from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT = REPO_ROOT / "training" / "m17_gpu" / "m39a_eval_provenance.py"

_MODULE = None


def _module():
    global _MODULE
    if _MODULE is None:
        sys.path.insert(0, str(REPO_ROOT / "training" / "m17_gpu"))
        spec = importlib.util.spec_from_file_location(
            "m39a_eval_provenance", SCRIPT
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULE = module
    return _MODULE


def _make_slot_dir(base: Path, arm: str, pairing: str, seed: int, rotation: int) -> Path:
    module = _module()
    slot_dir = base / f"{arm}-{pairing}-{seed}-r{rotation}"
    slot_dir.mkdir(parents=True, exist_ok=True)
    return slot_dir


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the module's repo root so the frozen config contract
    resolves catalog/exe/python paths inside the synthetic tree."""
    module = _module()
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(
        module,
        "_python_exe",
        lambda: Path("C:/Python312/python.exe"),
    )
    return tmp_path


def _write_config(
    slot_dir: Path,
    *,
    max_nodes: str = "2000",
    catalog: str = "catalog.json",
    exe: str = "splendor.exe",
) -> None:
    config = {
        "game_id": "m39a-eval-baseline-M07-5000000-r0",
        "seed": 5_000_000,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 30_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            {
                "program": "C:\\Python312\\python.exe",
                "args": [
                    "-m", "splendor_gpu.m35a_agent",
                    "--model-id", "M25-D2-v2",
                    "--catalog", catalog,
                    "--device", "cuda",
                ],
            },
            {
                "program": exe,
                "args": [
                    "agent-determinization",
                    "--sample-seed", "20260810",
                    "--sample-count", "4",
                    "--max-depth-turns", "1",
                    "--max-nodes", max_nodes,
                ],
            },
        ],
    }
    (slot_dir / "arena-config.json").write_text(json.dumps(config), encoding="utf-8")


def _expect_rebuild_rejection(monkeypatch, reason_fragment: str) -> None:
    module = _module()
    base = Path("synthetic-base")
    monkeypatch.setattr(module, "_verify_config", module._verify_config)
    try:
        module._rebuild_row(base, "baseline", "M07", 5_000_000, 0)
    except SystemExit as error:
        assert reason_fragment in str(error), f"expected {reason_fragment!r} in {error}"
        return
    pytest.fail("rebuild was accepted but must be rejected")


def _frozen_catalog(synthetic_repo: Path) -> str:
    module = _module()
    return str((synthetic_repo / module.CATALOG_PATH).resolve())


def _frozen_exe(synthetic_repo: Path) -> str:
    module = _module()
    return str((synthetic_repo / module.EXE_REL).resolve())


def test_tampered_m07_search_parameter_is_rejected(tmp_path: Path, synthetic_repo: Path) -> None:
    """The reviewer's exact tamper: --max-nodes 2000 -> 1 must fail the
    frozen argv contract, even with a forged report."""
    module = _module()
    slot_dir = _make_slot_dir(tmp_path, "baseline", "M07", 5_000_000, 0)
    _write_config(slot_dir, max_nodes="1", catalog=_frozen_catalog(synthetic_repo), exe=_frozen_exe(synthetic_repo))
    (slot_dir / "arena-report.json").write_text("{}", encoding="utf-8")
    try:
        module._rebuild_row(tmp_path, "baseline", "M07", 5_000_000, 0)
    except SystemExit as error:
        assert "argv mismatch" in str(error)
        assert "--max-nodes" in str(error) or "frozen" in str(error)
        return
    pytest.fail("tampered --max-nodes must be rejected")


def test_tampered_timeout_is_rejected(tmp_path: Path, synthetic_repo: Path) -> None:
    module = _module()
    slot_dir = _make_slot_dir(tmp_path, "baseline", "M07", 5_000_000, 0)
    _write_config(slot_dir, catalog=_frozen_catalog(synthetic_repo), exe=_frozen_exe(synthetic_repo))
    config = json.loads((slot_dir / "arena-config.json").read_text(encoding="utf-8"))
    config["move_timeout_ms"] = 60_000
    (slot_dir / "arena-config.json").write_text(json.dumps(config), encoding="utf-8")
    try:
        module._rebuild_row(tmp_path, "baseline", "M07", 5_000_000, 0)
    except SystemExit as error:
        assert "move_timeout_ms" in str(error)
        return
    pytest.fail("tampered timeout must be rejected")


def test_tampered_seed_commitment_is_rejected(tmp_path: Path, synthetic_repo: Path) -> None:
    """A report with a forged seed_commitment must fail even when the
    other fields are plausible (the reviewer's second tamper)."""
    module = _module()
    slot_dir = _make_slot_dir(tmp_path, "baseline", "M07", 5_000_000, 0)
    _write_config(slot_dir, catalog=_frozen_catalog(synthetic_repo), exe=_frozen_exe(synthetic_repo))
    report = {
        "format": "effective-splendor-arena-report",
        "version": 1,
        "game_id": "m39a-eval-baseline-M07-5000000-r0",
        "player_count": 2,
        "ruleset_fingerprint": "1c43f598b23017fab5e9d8b0083942ad1a921d1df804f90d16cd0b4753961afb",
        "seed_commitment": "f" * 64,
        "agents": [
            {"seat": 0, "agent_name": "effective-splendor-m35a-direct-agent-v1", "agent_version": "M25-D2-v2"},
            {"seat": 1, "agent_name": "effective-splendor-determinization-agent-v1", "agent_version": "1"},
        ],
        "outcome": {"status": "completed", "result": {}, "completed_plies": 60, "replay_final_hash": "a" * 64},
    }
    (slot_dir / "arena-report.json").write_text(json.dumps(report), encoding="utf-8")
    # Replay verification is skipped by pointing at a nonexistent replay:
    # the commitment check fires before the replay is read.
    try:
        module._rebuild_row(tmp_path, "baseline", "M07", 5_000_000, 0)
    except SystemExit as error:
        assert "seed commitment" in str(error)
        return
    pytest.fail("forged seed commitment must be rejected")


def test_nontermination_evidence_semantics_are_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Evidence with exit_code=0 and unrelated stderr must be rejected even
    when the ledger's self-reported hashes are synchronized (the
    reviewer's third tamper)."""
    module = _module()
    evidence_dir = tmp_path / "nontermination-evidence"
    evidence_dir.mkdir(parents=True)
    _write_config(evidence_dir, catalog=_frozen_catalog(tmp_path), exe=_frozen_exe(tmp_path))
    (evidence_dir / "stdout.txt").write_text("", encoding="utf-8")
    (evidence_dir / "stderr.txt").write_text("some unrelated error\n", encoding="utf-8")
    (evidence_dir / "exit-status.txt").write_text("exit_code=0\n", encoding="utf-8")

    ledger = {
        "gate": "g2",
        "nontermination_evidence": {
            "slot": ["baseline", "M07", 5_000_029, 0],
            "directory": "synthetic",
            "files": {
                name: module.file_sha256(evidence_dir / name)
                for name in module.NONTERMINATION_EVIDENCE_FILES
            },
        },
    }
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "NONTERMINATION_EVIDENCE_DIR", "nontermination-evidence")
    failures = module._failures_nontermination(ledger)
    fragments = " ".join(failures)
    assert "exit status" in fragments
    assert "ply safety limit" in fragments or "ply" in fragments


def test_frozen_config_contract_rejects_changed_checkpoint(tmp_path: Path, synthetic_repo: Path) -> None:
    """A candidate slot whose checkpoint hash differs from the frozen
    cycle-8 identity fails the argv contract."""
    module = _module()
    slot_dir = _make_slot_dir(tmp_path, "candidate", "M07", 5_000_000, 0)
    sidecar = (tmp_path / "candidate-M07-5000000-r0" / "eval-sidecar.json").resolve()
    server_ready = (tmp_path / "server-ready.json").resolve()
    config = {
        "game_id": "m39a-eval-candidate-M07-5000000-r0",
        "seed": 5_000_000,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 30_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            {
                "program": "C:\\Python312\\python.exe",
                "args": [
                    "-m", "splendor_gpu.m39a_agent",
                    "--checkpoint-sha256", "0" * 64,
                    "--plan-hash", module.PLAN_HASH,
                    "--game-index", "0",
                    "--sidecar-out", str(sidecar),
                    "--server-url", "127.0.0.1:19753",
                    "--server-ready", str(server_ready),
                    "--action-selection", "argmax",
                ],
            },
            {
                "program": _frozen_exe(synthetic_repo),
                "args": [
                    "agent-determinization",
                    "--sample-seed", "20260810",
                    "--sample-count", "4",
                    "--max-depth-turns", "1",
                    "--max-nodes", "2000",
                ],
            },
        ],
    }
    (slot_dir / "arena-config.json").write_text(json.dumps(config), encoding="utf-8")
    try:
        module._rebuild_row(tmp_path, "candidate", "M07", 5_000_000, 0)
    except SystemExit as error:
        assert "argv mismatch" in str(error)
        return
    pytest.fail("changed candidate checkpoint must be rejected")


def test_frozen_config_contract_rejects_categorical_selection(tmp_path: Path, synthetic_repo: Path) -> None:
    """A candidate slot run with categorical sampling instead of the frozen
    argmax fails the argv contract."""
    module = _module()
    slot_dir = _make_slot_dir(tmp_path, "candidate", "M07", 5_000_000, 0)
    sidecar = (tmp_path / "candidate-M07-5000000-r0" / "eval-sidecar.json").resolve()
    server_ready = (tmp_path / "server-ready.json").resolve()
    config = {
        "game_id": "m39a-eval-candidate-M07-5000000-r0",
        "seed": 5_000_000,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 30_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            {
                "program": "C:\\Python312\\python.exe",
                "args": [
                    "-m", "splendor_gpu.m39a_agent",
                    "--checkpoint-sha256", module.CANDIDATE_CHECKPOINT_FILE_SHA256,
                    "--plan-hash", module.PLAN_HASH,
                    "--game-index", "0",
                    "--sidecar-out", str(sidecar),
                    "--server-url", "127.0.0.1:19753",
                    "--server-ready", str(server_ready),
                    "--action-selection", "categorical",
                ],
            },
            {
                "program": _frozen_exe(synthetic_repo),
                "args": [
                    "agent-determinization",
                    "--sample-seed", "20260810",
                    "--sample-count", "4",
                    "--max-depth-turns", "1",
                    "--max-nodes", "2000",
                ],
            },
        ],
    }
    (slot_dir / "arena-config.json").write_text(json.dumps(config), encoding="utf-8")
    try:
        module._rebuild_row(tmp_path, "candidate", "M07", 5_000_000, 0)
    except SystemExit as error:
        assert "argv mismatch" in str(error)
        return
    pytest.fail("categorical action selection must be rejected")


def test_replay_final_hash_binding_is_checked(tmp_path: Path, synthetic_repo: Path) -> None:
    """A report whose replay_final_hash does not equal the replay's final
    state hash fails (forged report passes commitment but not binding)."""
    module = _module()
    slot_dir = _make_slot_dir(tmp_path, "baseline", "M07", 5_000_000, 0)
    _write_config(slot_dir, catalog=_frozen_catalog(synthetic_repo), exe=_frozen_exe(synthetic_repo))
    fingerprint = "1c43f598b23017fab5e9d8b0083942ad1a921d1df804f90d16cd0b4753961afb"
    commitment = module._seed_commitment(
        "m39a-eval-baseline-M07-5000000-r0", 2, 5_000_000, fingerprint
    )
    report = {
        "format": "effective-splendor-arena-report",
        "version": 1,
        "game_id": "m39a-eval-baseline-M07-5000000-r0",
        "player_count": 2,
        "ruleset_fingerprint": fingerprint,
        "seed_commitment": commitment,
        "agents": [
            {"seat": 0, "agent_name": "effective-splendor-m35a-direct-agent-v1", "agent_version": "M25-D2-v2"},
            {"seat": 1, "agent_name": "effective-splendor-determinization-agent-v1", "agent_version": "1"},
        ],
        "outcome": {
            "status": "completed",
            "result": {"scores": [15, 10], "ranks": [0, 1], "winners": [0], "reason": "prestige_threshold"},
            "completed_plies": 60,
            "replay_final_hash": "f" * 64,
        },
    }
    (slot_dir / "arena-report.json").write_text(json.dumps(report), encoding="utf-8")
    replay = {
        "format": "splendor-replay",
        "version": 1,
        "seed": 5_000_000,
        "ruleset_fingerprint": module.FROZEN_RULESET_FINGERPRINT,
        "final_state_hash": "0" * 64,
        "result": report["outcome"]["result"],
        "steps": [],
    }
    (slot_dir / "replay.json").write_text(json.dumps(replay), encoding="utf-8")
    # Mock the referee subprocess (synthetic tree has no splendor.exe):
    # verification succeeds; the binding check must still catch the forgery.
    import types

    fake_subprocess = types.SimpleNamespace(
        run=lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr="")
    )
    original_subprocess = module.subprocess
    module.subprocess = fake_subprocess
    try:
        module._rebuild_row(tmp_path, "baseline", "M07", 5_000_000, 0)
    except SystemExit as error:
        text = str(error)
        assert "replay_final_hash" in text
        return
    finally:
        module.subprocess = original_subprocess
    pytest.fail("forged replay_final_hash must be rejected")


def test_tampered_agent_program_is_rejected(tmp_path: Path, synthetic_repo: Path) -> None:
    """Replacing an agent executable with an arbitrary path while keeping
    the argv unchanged must fail the frozen program-identity check (the
    reviewer's first new tamper)."""
    module = _module()
    slot_dir = _make_slot_dir(tmp_path, "baseline", "M07", 5_000_000, 0)
    _write_config(slot_dir, catalog=_frozen_catalog(synthetic_repo), exe=_frozen_exe(synthetic_repo))
    config = json.loads((slot_dir / "arena-config.json").read_text(encoding="utf-8"))
    config["agents"][1]["program"] = "C:\\malicious\\evil.exe"
    (slot_dir / "arena-config.json").write_text(json.dumps(config), encoding="utf-8")
    (slot_dir / "arena-report.json").write_text("{}", encoding="utf-8")
    try:
        module._rebuild_row(tmp_path, "baseline", "M07", 5_000_000, 0)
    except SystemExit as error:
        assert "program mismatch" in str(error)
        return
    pytest.fail("tampered agent program must be rejected")


def test_missing_report_on_normal_slot_is_rejected(tmp_path: Path, synthetic_repo: Path) -> None:
    """A normal slot without a report must fail closed immediately — only
    the single frozen non-termination slot (baseline/M07/5000029/r0) may
    lack one. Uses a perfectly valid frozen config with NO report at all,
    so the failure is exactly the missing-report rule (the reviewer's
    second new tamper, which succeeded on an arbitrary slot before)."""
    module = _module()
    slot_dir = _make_slot_dir(tmp_path, "baseline", "M07", 5_000_030, 1)
    _write_config(slot_dir, catalog=_frozen_catalog(synthetic_repo), exe=_frozen_exe(synthetic_repo))
    config = json.loads((slot_dir / "arena-config.json").read_text(encoding="utf-8"))
    config["game_id"] = "m39a-eval-baseline-M07-5000030-r1"
    config["seed"] = 5_000_030
    # _write_config writes the rotation-0 lineup; this slot is rotation 1,
    # so swap the seats to the frozen r1 arrangement (M07 first).
    config["agents"] = [config["agents"][1], config["agents"][0]]
    (slot_dir / "arena-config.json").write_text(json.dumps(config), encoding="utf-8")
    # No report is written at all.
    try:
        module._rebuild_row(tmp_path, "baseline", "M07", 5_000_030, 1)
    except SystemExit as error:
        text = str(error)
        assert "missing report" in text
        assert "non-termination slot" in text
        return
    pytest.fail("a normal slot missing its report must fail closed")


def test_foreign_server_host_is_rejected(tmp_path: Path, synthetic_repo: Path) -> None:
    """The reviewer's discriminating counter-example: replacing
    127.0.0.1:9703 with attacker.example:443 must fail. The host is frozen
    (loopback only); only the port is dynamic."""
    module = _module()
    slot_dir = _make_slot_dir(tmp_path, "baseline", "M07", 5_000_000, 0)
    _write_config(slot_dir, catalog=_frozen_catalog(synthetic_repo), exe=_frozen_exe(synthetic_repo))
    config = json.loads((slot_dir / "arena-config.json").read_text(encoding="utf-8"))
    # Baseline agent has no --server-url; give the M07 seat a server-url
    # argument it must reject? No — the M07 agent never uses the server.
    # Instead build a candidate-shaped config with a foreign host.
    sidecar = (tmp_path / "candidate-M07-5000000-r0" / "eval-sidecar.json").resolve()
    server_ready = (tmp_path / "server-ready.json").resolve()
    config = {
        "game_id": "m39a-eval-candidate-M07-5000000-r0",
        "seed": 5_000_000,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 30_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            {
                "program": "C:\\Python312\\python.exe",
                "args": [
                    "-m", "splendor_gpu.m39a_agent",
                    "--checkpoint-sha256", module.CANDIDATE_CHECKPOINT_FILE_SHA256,
                    "--plan-hash", module.PLAN_HASH,
                    "--game-index", "0",
                    "--sidecar-out", str(sidecar),
                    "--server-url", "attacker.example:443",
                    "--server-ready", str(server_ready),
                    "--action-selection", "argmax",
                ],
            },
            {
                "program": _frozen_exe(synthetic_repo),
                "args": [
                    "agent-determinization",
                    "--sample-seed", "20260810",
                    "--sample-count", "4",
                    "--max-depth-turns", "1",
                    "--max-nodes", "2000",
                ],
            },
        ],
    }
    slot_dir = _make_slot_dir(tmp_path, "candidate", "M07", 5_000_000, 0)
    (slot_dir / "arena-config.json").write_text(json.dumps(config), encoding="utf-8")
    (slot_dir / "arena-report.json").write_text("{}", encoding="utf-8")
    try:
        module._rebuild_row(tmp_path, "candidate", "M07", 5_000_000, 0)
    except SystemExit as error:
        assert "127.0.0.1" in str(error)
        assert "attacker.example" in str(error)
        return
    pytest.fail("a foreign --server-url host must be rejected")


def test_invalid_server_port_is_rejected(tmp_path: Path, synthetic_repo: Path) -> None:
    """Ports outside the dynamic range (e.g. 80) fail the frozen contract."""
    module = _module()
    sidecar = (tmp_path / "candidate-M07-5000000-r0" / "eval-sidecar.json").resolve()
    server_ready = (tmp_path / "server-ready.json").resolve()
    config = {
        "game_id": "m39a-eval-candidate-M07-5000000-r0",
        "seed": 5_000_000,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 30_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            {
                "program": "C:\\Python312\\python.exe",
                "args": [
                    "-m", "splendor_gpu.m39a_agent",
                    "--checkpoint-sha256", module.CANDIDATE_CHECKPOINT_FILE_SHA256,
                    "--plan-hash", module.PLAN_HASH,
                    "--game-index", "0",
                    "--sidecar-out", str(sidecar),
                    "--server-url", "127.0.0.1:80",
                    "--server-ready", str(server_ready),
                    "--action-selection", "argmax",
                ],
            },
            {
                "program": _frozen_exe(synthetic_repo),
                "args": [
                    "agent-determinization",
                    "--sample-seed", "20260810",
                    "--sample-count", "4",
                    "--max-depth-turns", "1",
                    "--max-nodes", "2000",
                ],
            },
        ],
    }
    slot_dir = _make_slot_dir(tmp_path, "candidate", "M07", 5_000_000, 0)
    (slot_dir / "arena-config.json").write_text(json.dumps(config), encoding="utf-8")
    (slot_dir / "arena-report.json").write_text("{}", encoding="utf-8")
    try:
        module._rebuild_row(tmp_path, "candidate", "M07", 5_000_000, 0)
    except SystemExit as error:
        assert "dynamic port" in str(error)
        return
    pytest.fail("a non-dynamic --server-url port must be rejected")


def test_tampered_executable_is_caught_by_frozen_constant(tmp_path: Path) -> None:
    """A ledger re-blessing a replaced executable fails: the binding is a
    frozen constant and the on-disk exe is checked against it."""
    module = _module()
    ledger = {
        "gate": "g2",
        "bindings": {"executable_sha256": "f" * 64},
    }
    # Only the frozen-constant mismatch matters here; use the binding
    # comparison path directly.
    recomputed = module._runtime_bindings("g2")
    assert ledger["bindings"]["executable_sha256"] != recomputed["executable_sha256"]
    assert recomputed["executable_sha256"] == module.FROZEN_EXECUTABLE_SHA256
