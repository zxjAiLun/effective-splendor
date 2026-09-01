from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from splendor_gpu.m40a_constants import LEAGUE_ORDER  # noqa: F401


def _import_run_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "m40a_run",
        Path(__file__).resolve().parent.parent / "m40a_run.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ppo_parent_resolution_contract(tmp_path, monkeypatch):
    """The treatment-entry contract: A cycle1 -> A-cycle0; B cycle1 ->
    B-cycle0-pretrained (REQUIRED, no fallback); cycles N>1 -> previous
    same-arm checkpoint."""
    run = _import_run_module()
    monkeypatch.setattr(run, "RUN_ROOT", tmp_path)

    (tmp_path / "A-cycle0.pt").write_bytes(b"a")
    (tmp_path / "B-cycle0.pt").write_bytes(b"b")
    (tmp_path / "B-cycle0-pretrained.pt").write_bytes(b"bp")

    # A cycle 1 -> A-cycle0
    assert run.ppo_parent_checkpoint("A", 1) == tmp_path / "A-cycle0.pt"
    # B cycle 1 -> B-cycle0-pretrained (NEVER B-cycle0)
    assert run.ppo_parent_checkpoint("B", 1) == tmp_path / "B-cycle0-pretrained.pt"
    # cycles N>1
    (tmp_path / "A-cycle2.pt").write_bytes(b"a2")
    (tmp_path / "B-cycle3.pt").write_bytes(b"b3")
    assert run.ppo_parent_checkpoint("A", 3) == tmp_path / "A-cycle2.pt"
    assert run.ppo_parent_checkpoint("B", 4) == tmp_path / "B-cycle3.pt"


def test_b_cycle1_fails_closed_without_pretrained(tmp_path, monkeypatch):
    """Deleting B-cycle0-pretrained must fail B cycle-1 resolution even
    though B-cycle0 exists — the warm-start treatment may never be
    silently bypassed."""
    run = _import_run_module()
    monkeypatch.setattr(run, "RUN_ROOT", tmp_path)
    (tmp_path / "A-cycle0.pt").write_bytes(b"a")
    (tmp_path / "B-cycle0.pt").write_bytes(b"b")
    # NO B-cycle0-pretrained.pt
    with pytest.raises(FileNotFoundError, match="pretrained"):
        run.ppo_parent_checkpoint("B", 1)


def test_b_pretrained_parent_hash_binds_b_cycle0(tmp_path):
    """The pretrain save path must descend from B-cycle0 (parent hash ==
    its semantic hash), forming shared init -> B-cycle0 -> B-pretrained.
    (Exercised against the _save_checkpoint contract directly.)"""
    run = _import_run_module()
    # build a tiny M40A model
    from splendor_gpu.m40a_model import M40AModel, initialize_predictive_heads

    model = M40AModel()
    initialize_predictive_heads(model)
    b0_info = run._save_checkpoint(
        tmp_path / "B-cycle0.pt", model,
        arm="B", cycle=0, parent_hash=None,
        plan_digest="p", catalog_hash="c", optimizer_state=None,
    )
    b0_semantic = b0_info["checkpoint_hash"]
    info = run._save_checkpoint(
        tmp_path / "B-cycle0-pretrained.pt", model,
        arm="B", cycle=0, parent_hash=b0_semantic,
        plan_digest="p", catalog_hash="c", optimizer_state=None,
    )
    payload = torch.load(tmp_path / "B-cycle0-pretrained.pt", weights_only=False)
    assert payload["metadata"]["parent_checkpoint_hash"] == b0_semantic


def test_evaluate_dry_run_schedule_counts():
    """The frozen schedule: H1=256, league=1152, M07=128, D2=128, total
    1664 physical matches; exact frozen seed ranges; no duplicates."""
    run = _import_run_module()
    schedules = run._evaluation_schedules()
    digest = run._validate_schedules(schedules)
    assert len(schedules["h1"]) == 256
    assert len(schedules["league"]) == 576  # entries; x2 arms = 1152 matches
    assert len(schedules["m07"]) == 128
    assert len(schedules["d2"]) == 128
    total = (
        len(schedules["h1"])
        + 2 * len(schedules["league"])
        + len(schedules["m07"])
        + len(schedules["d2"])
    )
    assert total == 1664
    assert digest == run._validate_schedules(run._evaluation_schedules())
    assert min(s["seed"] for s in schedules["h1"]) == 8_100_000
    assert max(s["seed"] for s in schedules["h1"]) == 8_100_127
    assert min(s["seed"] for s in schedules["league"]) == 8_200_000
    assert max(s["seed"] for s in schedules["league"]) == 8_200_031


def test_collect_cycle_uses_pretrained_parent_for_b(tmp_path, monkeypatch):
    """cmd_collect_cycle --arm B --cycle 1 resolves B-cycle0-pretrained
    and verifies the full pretrain provenance, not B-cycle0."""
    run = _import_run_module()
    monkeypatch.setattr(run, "RUN_ROOT", tmp_path)
    # Build real checkpoints for A/B cycle0 and B-pretrained with a
    # matching formal pretrain report.
    from splendor_gpu.m40a_model import M40AModel, initialize_predictive_heads
    from splendor_gpu.data import load_catalog, catalog_semantic_hash
    from splendor_gpu.m40a_contract import build_plan, validate_plan

    catalog = load_catalog(
        Path(__file__).resolve().parent.parent.parent.parent
        / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
    )
    cat_hash = catalog_semantic_hash(catalog)
    plan = build_plan()
    digest = validate_plan(plan)

    a0 = M40AModel(); initialize_predictive_heads(a0)
    b0 = M40AModel(); initialize_predictive_heads(b0)
    b0_info = run._save_checkpoint(
        tmp_path / "B-cycle0.pt", b0, arm="B", cycle=0, parent_hash=None,
        plan_digest=digest, catalog_hash=cat_hash, optimizer_state=None)
    bp = M40AModel(); initialize_predictive_heads(bp)
    bp_info = run._save_checkpoint(
        tmp_path / "B-cycle0-pretrained.pt", bp, arm="B", cycle=0,
        parent_hash=b0_info["checkpoint_hash"],
        plan_digest=digest, catalog_hash=cat_hash, optimizer_state=None)
    report = {
        "b_pretrain_checkpoint": {
            "checkpoint_hash": bp_info["checkpoint_hash"],
            "checkpoint_file_sha256": bp_info["checkpoint_file_sha256"],
        }
    }
    (tmp_path / "b-pretrain-report.json").write_text(json.dumps(report), encoding="utf-8")

    # Provenance verification passes and the resolved parent is pretrained.
    run._verify_b_pretrain_provenance(digest, cat_hash)
    assert run.ppo_parent_checkpoint("B", 1) == tmp_path / "B-cycle0-pretrained.pt"


def test_evaluate_rejects_missing_cycle4(tmp_path, monkeypatch):
    run = _import_run_module()
    monkeypatch.setattr(run, "RUN_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError, match="cycle4"):
        import argparse as _ap

        run.cmd_evaluate(_ap.Namespace(dry_run=True, device="cpu"))
