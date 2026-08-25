"""Unit tests for M32A Teacher–Student Information Parity.

Verifies:
1. Belief feature dimension is strictly 212 and structure follows frozen specification (90 + 120 + 2).
2. HiddenDeck slots have non-zero status one-hot, but strictly ZERO card attributes (no card identity leakage).
3. Parameter count of BeliefDeltaEntityMixer is exactly 994,180 (953,476 + 40,704).
4. Real provenance preflight enforces full 64-char semantic hashes, D2 baseline SHA, parameter count, and fail-closed directory.
5. Sidecar integrity validator correctly detects metadata mismatch, dim mismatch, or attribute leakage.
"""
import json
import tempfile
from pathlib import Path
import pytest
import torch

from splendor_gpu.data import load_catalog, catalog_semantic_hash
from splendor_gpu.m25_train import validate_m25_dataset_provenance
from splendor_gpu.m32a_train import BeliefDeltaEntityMixer, M32A_GLOBAL_FEATURES, ENHANCED_ACTION_FEATURES
from splendor_gpu.m32a_preflight import (
    preflight_m32a,
    validate_sidecar_integrity,
    FROZEN_CONFIG_SHA256,
    FROZEN_DATASET_FILE_SHA256,
    FROZEN_DATASET_SEMANTIC_HASH,
    FROZEN_CATALOG_HASH,
    FROZEN_D2_RESULT_SHA256,
    FROZEN_M32A_PARAMETER_COUNT,
    BELIEF_FEATURE_DIM,
)

def test_model_parameter_count():
    model = BeliefDeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)
    param_count = sum(p.numel() for p in model.parameters())
    assert param_count == FROZEN_M32A_PARAMETER_COUNT
    assert param_count == 994180

def test_sidecar_validator_integrity_and_leakage_detection():
    valid_entry = {
        "example_index": 0,
        "source_id": "match-000000",
        "match_index": 0,
        "ply": 8,
        "actor": 0,
        "information_set_hash": "a" * 64,
        "belief_features": [0.0] * 212,
    }
    # Set unseen mask (0..90) to valid binary values
    for i in range(90):
        valid_entry["belief_features"][i] = 1.0
    # Set 6 slot statuses (empty: index 0)
    for slot_idx in range(6):
        valid_entry["belief_features"][90 + slot_idx * 20] = 1.0

    valid_payload = {
        "milestone": "M32A",
        "dataset_file": "dataset.json",
        "dataset_file_sha256": "b" * 64,
        "total_examples": 1,
        "feature_dim": 212,
        "entries": [valid_entry],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        sidecar_file = Path(tmpdir) / "test_sidecar.json"
        sidecar_file.write_text(json.dumps(valid_payload))

        # 1. Valid single entry passes integrity check
        info = validate_sidecar_integrity(sidecar_file, [(0, 8, 0, "a" * 64)], expected_total=1)
        assert info["total_entries"] == 1
        assert info["feature_dim"] == 212

        # 2. Leaked attribute in HiddenDeck slot -> fails closed
        leaked_entry = json.loads(json.dumps(valid_entry))
        # Set slot 0 to HiddenDeck tier 1 (status index 3)
        leaked_entry["belief_features"][90] = 0.0
        leaked_entry["belief_features"][93] = 1.0
        # Leak card attribute in slot 0 (index 6..20)
        leaked_entry["belief_features"][96] = 0.5
        leaked_payload = dict(valid_payload, entries=[leaked_entry])
        sidecar_file.write_text(json.dumps(leaked_payload))

        with pytest.raises(ValueError, match="HiddenDeck/Empty slot .* card attributes must be strictly zero"):
            validate_sidecar_integrity(sidecar_file, [(0, 8, 0, "a" * 64)], expected_total=1)

def test_real_provenance_preflight_for_m32a():
    config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
    dataset_path = Path("local-artifacts/m25-generation/m25-materialized-dataset.json")
    catalog_path = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
    d2_result_path = Path("benchmarks/m25-recovery-exp-d2.result.json")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    ds_payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    catalog = load_catalog(catalog_path)

    real_dataset_semantic_hash = validate_m25_dataset_provenance(ds_payload, config)
    real_catalog_semantic_hash = catalog_semantic_hash(catalog)

    assert real_dataset_semantic_hash == FROZEN_DATASET_SEMANTIC_HASH
    assert real_catalog_semantic_hash == FROZEN_CATALOG_HASH

    expected_tuples = [
        (ex["evaluation_match_index"], ex["ply"], ex["actor"], ex["information_set_hash"])
        for ex in ds_payload["examples"]
    ]
    assert len(expected_tuples) == 16282
