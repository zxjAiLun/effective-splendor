import copy
import json
from pathlib import Path

import pytest
import torch

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m39a_agent import categorical_index
from splendor_gpu.m39a_contract import (
    BATCH_FORMAT,
    BATCH_VERSION,
    decision_seed,
    file_sha256,
    load_plan,
    plan_hash,
)
from splendor_gpu.m39a_model import build_initial_checkpoint, infer_decision
from splendor_gpu.m39a_train import train_cycle, validate_authoritative_batch


PLAN_PATH = Path(__file__).resolve().parent.parent.parent.parent / "benchmarks/m39a-arena-driven-policy-value-rl.plan.json"
FIXTURE = Path(__file__).resolve().parent.parent.parent.parent / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"


def _real_batch(tmp_path: Path):
    plan = load_plan(PLAN_PATH)
    base = Path(plan["initialization"]["checkpoint_path"])
    if not base.exists():
        pytest.skip("local D2-v2 checkpoint is intentionally not tracked")
    digest = plan_hash(plan)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    frame = fixture["frames"][0]
    catalog = load_catalog(FIXTURE)
    cat_hash = catalog_semantic_hash(catalog)
    initial = build_initial_checkpoint(
        base_checkpoint=base,
        expected_base_sha256=plan["initialization"]["checkpoint_file_sha256"],
        plan_hash=digest,
        catalog_hash=cat_hash,
    )
    checkpoint = tmp_path / "cycle-0.pt"
    torch.save(initial, checkpoint)
    model = __import__("splendor_gpu.m39a_model", fromlist=["M39APolicyValue"]).M39APolicyValue()
    model.load_state_dict(initial["state_dict"], strict=True)
    logits, values, _ = infer_decision(
        model,
        frame["player_view"],
        frame["legal_actions"],
        catalog,
        torch.device("cpu"),
    )
    seed = decision_seed(0, 0, 1)
    chosen, log_probability = categorical_index(logits, seed)
    result = copy.deepcopy(fixture["result"])
    result["centered_returns"] = [1.0, -1.0]
    record = {
        "game_index": 0,
        "game_id": "m39a-unit-game-0",
        "seat": 0,
        "ply_index": 0,
        "request_id": 1,
        "observation_hash": frame["observation_hash"],
        "observation": frame["player_view"],
        "legal_actions": frame["legal_actions"],
        "action": frame["legal_actions"][chosen],
        "decision_seed": seed,
        "old_log_probability": log_probability,
        "old_value": float(values[0].item()),
        "old_value_by_player": [float(value) for value in values.tolist()],
        "old_auxiliary_score": 0.0,
        "result": result,
        "arena_report_hash": "11" * 32,
        "replay_document_hash": "22" * 32,
    }
    batch = {
        "format": BATCH_FORMAT,
        "version": BATCH_VERSION,
        "plan_hash": digest,
        "checkpoint_sha256": file_sha256(checkpoint),
        "checkpoint_hash": initial["checkpoint_hash"],
        "cycle": 1,
        "checkpoint_cycle": 0,
        "mode": "smoke",
        "ply_cap": 150,
        "games": [
            {
                "game_index": 0,
                "game_id": "m39a-unit-game-0",
                "completed_plies": 1,
                "training_plies": 1,
                "arena_report_hash": "11" * 32,
                "replay_document_hash": "22" * 32,
            }
        ],
        "records": [record],
    }
    return plan, digest, catalog, cat_hash, checkpoint, batch


def test_batch_fail_closed_and_one_cycle_optimizer_smoke(tmp_path):
    plan, digest, catalog, cat_hash, checkpoint, batch = _real_batch(tmp_path)
    checkpoint_sha = file_sha256(checkpoint)
    validate_authoritative_batch(
        batch,
        expected_plan_hash=digest,
        expected_checkpoint_sha256=checkpoint_sha,
        expected_checkpoint_hash=batch["checkpoint_hash"],
        cycle=1,
    )
    tampered = copy.deepcopy(batch)
    tampered["records"][0]["decision_seed"] ^= 1
    with pytest.raises(ValueError, match="decision seed"):
        validate_authoritative_batch(
            tampered,
            expected_plan_hash=digest,
            expected_checkpoint_sha256=checkpoint_sha,
            expected_checkpoint_hash=batch["checkpoint_hash"],
            cycle=1,
        )
    output, report = train_cycle(
        plan=plan,
        plan_digest=digest,
        batch=batch,
        checkpoint_path=checkpoint,
        checkpoint_sha256=checkpoint_sha,
        catalog=catalog,
        catalog_hash=cat_hash,
        cycle=1,
        device=torch.device("cpu"),
    )
    assert output["metadata"]["cycle"] == 1
    assert output["metadata"]["parent_checkpoint_hash"] == batch["checkpoint_hash"]
    assert report["records"] == 1
    assert report["recomputation"]["bit_exact"] == 1
    assert len(report["history"]) == 4
    assert output["checkpoint_hash"] != batch["checkpoint_hash"]
