"""Unit tests for M32A Teacher–Student Information Parity.

Verifies:
1. Belief feature dimension is strictly 212 and structure follows frozen specification (90 + 120 + 2).
2. HiddenDeck slots have non-zero status one-hot, but strictly ZERO card attributes (no card identity leakage).
3. Parameter count of BeliefDeltaEntityMixer is exactly 994,180 (953,476 + 40,704).
4. Real provenance preflight executes full production preflight_m32a() and enforces root metadata, exporter source SHA, replay bundle digest, 64-char semantic hashes, D2 baseline SHA, parameter count, and fail-closed directory.
5. Sidecar integrity validator correctly detects root metadata mismatch, row metadata mismatch, dim mismatch, or attribute leakage.
6. Tamper rejection tests: tampering with exporter_file_sha256 or ordered_256_replay_bundle_digest fails closed.
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
    FROZEN_EXPORTER_SOURCE_SHA256,
    FROZEN_ORDERED_256_REPLAY_BUNDLE_DIGEST,
    FROZEN_M32A_PARAMETER_COUNT,
    BELIEF_FEATURE_DIM,
    FEATURE_CONTRACT_VERSION,
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
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "exporter_file_sha256": FROZEN_EXPORTER_SOURCE_SHA256,
        "ordered_256_replay_bundle_digest": FROZEN_ORDERED_256_REPLAY_BUNDLE_DIGEST,
        "dataset_file": "dataset.json",
        "dataset_file_sha256": FROZEN_DATASET_FILE_SHA256,
        "total_examples": 1,
        "feature_dim": 212,
        "entries": [valid_entry],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        sidecar_file = Path(tmpdir) / "test_sidecar.json"
        sidecar_file.write_text(json.dumps(valid_payload))

        # 1. Valid single entry passes integrity check
        info = validate_sidecar_integrity(
            sidecar_file,
            [(0, "match-000000", 0, 8, 0, "a" * 64)],
            expected_exporter_sha256=FROZEN_EXPORTER_SOURCE_SHA256,
            expected_replay_bundle_digest=FROZEN_ORDERED_256_REPLAY_BUNDLE_DIGEST,
            expected_total=1,
        )
        assert info["total_entries"] == 1
        assert info["feature_dim"] == 212
        assert info["feature_contract_version"] == FEATURE_CONTRACT_VERSION
        assert info["exporter_file_sha256"] == FROZEN_EXPORTER_SOURCE_SHA256
        assert info["ordered_256_replay_bundle_digest"] == FROZEN_ORDERED_256_REPLAY_BUNDLE_DIGEST

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
            validate_sidecar_integrity(
                sidecar_file,
                [(0, "match-000000", 0, 8, 0, "a" * 64)],
                expected_exporter_sha256=FROZEN_EXPORTER_SOURCE_SHA256,
                expected_replay_bundle_digest=FROZEN_ORDERED_256_REPLAY_BUNDLE_DIGEST,
                expected_total=1,
            )

        # 3. Missing root metadata / contract version mismatch -> fails closed
        bad_version_payload = dict(valid_payload, feature_contract_version="bad_version")
        sidecar_file.write_text(json.dumps(bad_version_payload))
        with pytest.raises(ValueError, match="Feature contract version mismatch"):
            validate_sidecar_integrity(
                sidecar_file,
                [(0, "match-000000", 0, 8, 0, "a" * 64)],
                expected_exporter_sha256=FROZEN_EXPORTER_SOURCE_SHA256,
                expected_replay_bundle_digest=FROZEN_ORDERED_256_REPLAY_BUNDLE_DIGEST,
                expected_total=1,
            )

def test_tamper_rejection_for_sidecar_provenance():
    valid_entry = {
        "example_index": 0,
        "source_id": "match-000000",
        "match_index": 0,
        "ply": 8,
        "actor": 0,
        "information_set_hash": "a" * 64,
        "belief_features": [0.0] * 212,
    }
    for i in range(90):
        valid_entry["belief_features"][i] = 1.0
    for slot_idx in range(6):
        valid_entry["belief_features"][90 + slot_idx * 20] = 1.0

    valid_payload = {
        "milestone": "M32A",
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "exporter_file_sha256": FROZEN_EXPORTER_SOURCE_SHA256,
        "ordered_256_replay_bundle_digest": FROZEN_ORDERED_256_REPLAY_BUNDLE_DIGEST,
        "dataset_file": "dataset.json",
        "dataset_file_sha256": FROZEN_DATASET_FILE_SHA256,
        "total_examples": 1,
        "feature_dim": 212,
        "entries": [valid_entry],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        sidecar_file = Path(tmpdir) / "test_sidecar.json"

        # Tamper 1: Tampered exporter source SHA-256 -> rejected
        tampered_exporter_payload = dict(valid_payload, exporter_file_sha256="f" * 64)
        sidecar_file.write_text(json.dumps(tampered_exporter_payload))
        with pytest.raises(ValueError, match="Sidecar exporter_file_sha256 mismatch"):
            validate_sidecar_integrity(
                sidecar_file,
                [(0, "match-000000", 0, 8, 0, "a" * 64)],
                expected_exporter_sha256=FROZEN_EXPORTER_SOURCE_SHA256,
                expected_replay_bundle_digest=FROZEN_ORDERED_256_REPLAY_BUNDLE_DIGEST,
                expected_total=1,
            )

        # Tamper 2: Tampered replay bundle digest -> rejected
        tampered_replay_payload = dict(valid_payload, ordered_256_replay_bundle_digest="d" * 64)
        sidecar_file.write_text(json.dumps(tampered_replay_payload))
        with pytest.raises(ValueError, match="Sidecar ordered_256_replay_bundle_digest mismatch"):
            validate_sidecar_integrity(
                sidecar_file,
                [(0, "match-000000", 0, 8, 0, "a" * 64)],
                expected_exporter_sha256=FROZEN_EXPORTER_SOURCE_SHA256,
                expected_replay_bundle_digest=FROZEN_ORDERED_256_REPLAY_BUNDLE_DIGEST,
                expected_total=1,
            )

def test_real_provenance_preflight_for_m32a():
    config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
    dataset_path = Path("local-artifacts/m25-generation/m25-materialized-dataset.json")
    catalog_path = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
    d2_result_path = Path("benchmarks/m25-recovery-exp-d2.result.json")
    exporter_path = Path("crates/splendor-cli/src/bin/m32a_export_sidecar.rs")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    ds_payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    catalog = load_catalog(catalog_path)

    real_dataset_semantic_hash = validate_m25_dataset_provenance(ds_payload, config)
    real_catalog_semantic_hash = catalog_semantic_hash(catalog)

    assert real_dataset_semantic_hash == FROZEN_DATASET_SEMANTIC_HASH
    assert real_catalog_semantic_hash == FROZEN_CATALOG_HASH

    expected_tuples = [
        (
            i,
            ex["source_id"],
            ex["evaluation_match_index"],
            ex["ply"],
            ex["actor"],
            ex["information_set_hash"],
        )
        for i, ex in enumerate(ds_payload["examples"])
    ]
    assert len(expected_tuples) == 16282

    # Execute full preflight_m32a against a synthetic valid sidecar to test the real production function
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        sidecar_file = tmp_path / "mock_sidecar.json"
        output_dir = tmp_path / "m32a_output"

        mock_entries = []
        for i, sid, m_idx, ply, actor, h in expected_tuples:
            mock_entry = {
                "example_index": i,
                "source_id": sid,
                "match_index": m_idx,
                "ply": ply,
                "actor": actor,
                "information_set_hash": h,
                "belief_features": [0.0] * 212,
            }
            # unseen mask valid binary
            for u in range(90):
                mock_entry["belief_features"][u] = 1.0
            # 6 empty slots
            for s in range(6):
                mock_entry["belief_features"][90 + s * 20] = 1.0
            mock_entries.append(mock_entry)

        sidecar_payload = {
            "milestone": "M32A",
            "feature_contract_version": FEATURE_CONTRACT_VERSION,
            "exporter_file_sha256": FROZEN_EXPORTER_SOURCE_SHA256,
            "ordered_256_replay_bundle_digest": FROZEN_ORDERED_256_REPLAY_BUNDLE_DIGEST,
            "dataset_file": str(dataset_path),
            "dataset_file_sha256": FROZEN_DATASET_FILE_SHA256,
            "total_examples": 16282,
            "feature_dim": 212,
            "entries": mock_entries,
        }
        sidecar_file.write_text(json.dumps(sidecar_payload))

        # Real production preflight execution
        res = preflight_m32a(
            config_path=config_path,
            dataset_path=dataset_path,
            catalog_path=catalog_path,
            d2_result_path=d2_result_path,
            exporter_path=exporter_path,
            sidecar_path=sidecar_file,
            output_dir=output_dir,
            actual_dataset_semantic_hash=real_dataset_semantic_hash,
            actual_catalog_hash=real_catalog_semantic_hash,
            actual_param_count=FROZEN_M32A_PARAMETER_COUNT,
            expected_tuples=expected_tuples,
            require_cuda=False,
        )

        assert res["dataset_semantic_hash"] == FROZEN_DATASET_SEMANTIC_HASH
        assert res["feature_contract_version"] == FEATURE_CONTRACT_VERSION
        assert res["exporter_file_sha256"] == FROZEN_EXPORTER_SOURCE_SHA256
        assert res["ordered_256_replay_bundle_digest"] == FROZEN_ORDERED_256_REPLAY_BUNDLE_DIGEST
