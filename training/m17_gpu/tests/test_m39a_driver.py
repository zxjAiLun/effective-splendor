from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

DRIVER = (
    Path(__file__).resolve().parent.parent / "m39a_cycle_driver.py"
).resolve()
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FORMAL_ROOT = REPO_ROOT / "local-artifacts" / "m39a-formal-run"


_DRIVER_MODULE = None


def _driver_module():
    global _DRIVER_MODULE
    if _DRIVER_MODULE is None:
        spec_dir = str(DRIVER.parent)
        if spec_dir not in sys.path:
            sys.path.insert(0, spec_dir)
        import importlib.util

        spec = importlib.util.spec_from_file_location("m39a_cycle_driver", DRIVER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _DRIVER_MODULE = module
    return _DRIVER_MODULE


@pytest.fixture()
def lock_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    module = _driver_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "LOCK", tmp_path / "driver.lock")
    module._TESTING = True
    yield tmp_path
    lock = tmp_path / "driver.lock"
    lock.unlink(missing_ok=True)


def test_second_driver_is_rejected_and_holder_survives(lock_root: Path) -> None:
    """A competing acquire must fail closed and never terminate the holder.

    The holder is an isolated real subprocess holding the lock file open by
    existence; the probe is exactly the code path a second driver takes.
    On Windows, os.kill(pid, 0) has been measured to terminate targets, so
    the driver must not call it at all — the assertion below guards that
    regression class: the holder subprocess must still be alive after the
    competing acquire fails.
    """
    module = _driver_module()
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import pathlib, sys, time
                lock = pathlib.Path(sys.argv[1])
                lock.write_text(str(os.getpid()) if False else "holder", encoding="utf-8")
                print("locked", flush=True)
                time.sleep(60)
                """
            ).replace("os.getpid()", "12345"),
            str(lock_root / "driver.lock"),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        # The competing driver must fail closed.
        with pytest.raises(SystemExit, match="already exists"):
            module.acquire_lock()
        # ... and must NOT have terminated the holder.
        time.sleep(0.5)
        assert holder.poll() is None, "competing driver killed the lock holder"
    finally:
        holder.kill()
        holder.wait(timeout=10)


def test_lock_acquired_and_released(lock_root: Path) -> None:
    module = _driver_module()
    module.acquire_lock()
    assert (lock_root / "driver.lock").is_file()
    module.release_lock()
    assert not (lock_root / "driver.lock").exists()


def test_stale_lock_is_never_auto_cleared(lock_root: Path) -> None:
    """Crash residue fails closed; recovery is a human-confirmed step."""
    module = _driver_module()
    (lock_root / "driver.lock").write_text("999999", encoding="utf-8")
    with pytest.raises(SystemExit, match="already exists"):
        module.acquire_lock()
    assert (lock_root / "driver.lock").exists()


@pytest.mark.skipif(
    not (FORMAL_ROOT / "cycle-1.pt").is_file(),
    reason="formal run artifacts are local-only",
)
def test_full_resume_recognizes_cycles_1_through_5() -> None:
    """The real legacy artifacts must resume cleanly from cycle 0.

    Guards the regression where cycle_state required a ply_cap field that
    legacy (and then-current) train reports did not carry, stopping the
    formal resume at cycle 1.
    """
    import torch

    module = _driver_module()
    plan = module.load_plan(REPO_ROOT / "benchmarks/m39a-arena-driven-policy-value-rl.plan.json")
    digest = module.plan_hash(plan)
    contract = module.execution_contract(
        plan_path=REPO_ROOT / "benchmarks/m39a-arena-driven-policy-value-rl.plan.json",
        plan_digest=digest,
        catalog_path=REPO_ROOT
        / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json",
        catalog_hash=plan["catalog"]["semantic_hash"],
        splendor=REPO_ROOT / "target/release/splendor.exe",
        ply_cap=150,
    )
    assert len(contract["legacy_cycles"]) == 5

    seed = FORMAL_ROOT / "cycle-0.pt"
    payload0 = torch.load(seed, map_location="cpu", weights_only=False)
    state = (
        seed,
        module.file_sha256(seed),
        payload0["checkpoint_hash"],
    )
    del payload0

    for cycle in range(1, 6):
        done = module.cycle_state(cycle, contract=contract, expected_parent=state)
        assert done is not None, f"cycle {cycle} must resume as complete"
        state = done

    # Cycles beyond 5 are capped-era: when present they must carry ply_cap.
    cycle6 = FORMAL_ROOT / "cycle-6.pt"
    if cycle6.is_file():
        done = module.cycle_state(6, contract=contract, expected_parent=state)
        assert done is not None, "completed capped cycle-6 must resume"
        state = done


@pytest.mark.skipif(
    not (FORMAL_ROOT / "cycle-1.pt").is_file(),
    reason="formal run artifacts are local-only",
)
def test_tampered_legacy_batch_fails_resume() -> None:
    """Any post-hoc modification of legacy artifacts breaks the contract."""
    module = _driver_module()
    plan = module.load_plan(REPO_ROOT / "benchmarks/m39a-arena-driven-policy-value-rl.plan.json")
    digest = module.plan_hash(plan)
    contract = module.execution_contract(
        plan_path=REPO_ROOT / "benchmarks/m39a-arena-driven-policy-value-rl.plan.json",
        plan_digest=digest,
        catalog_path=REPO_ROOT
        / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json",
        catalog_hash=plan["catalog"]["semantic_hash"],
        splendor=REPO_ROOT / "target/release/splendor.exe",
        ply_cap=150,
    )
    # Forge an attestation pointing at a wrong hash: cycle_state must reject.
    forged = json.loads(json.dumps(contract))
    forged["legacy_cycles"][0]["batch_sha256"] = "f" * 64
    import torch

    seed = FORMAL_ROOT / "cycle-0.pt"
    payload0 = torch.load(seed, map_location="cpu", weights_only=False)
    state = (seed, module.file_sha256(seed), payload0["checkpoint_hash"])
    with pytest.raises(SystemExit, match="batch_sha256 mismatch"):
        module.cycle_state(1, contract=forged, expected_parent=state)
