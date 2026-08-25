"""M32A Preflight and Frozen Provenance Verification for Information-Parity Belief Sidecar."""
import hashlib
import json
from pathlib import Path
import torch

FROZEN_CONFIG_SHA256 = "bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250"
FROZEN_DATASET_FILE_SHA256 = "2e15cc9d3f96c0993e3746f45c4eb24d3e1bf92f80c2b515d5f171f1e1f05907"
FROZEN_DATASET_SEMANTIC_HASH = "1aa7212ff070e637d0f0aeabf6eddd16e0d00fc1d5a6aa9da93e75be69975419"
FROZEN_CATALOG_HASH = "4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26"
FROZEN_D2_RESULT_SHA256 = "403e4903044dfec929c6e92713b2bb9f3e120469ab872271dc82e78f752efc38"
FROZEN_M32A_PARAMETER_COUNT = 994180
BELIEF_FEATURE_DIM = 212

def compute_file_sha256(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required artifact does not exist: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate_sidecar_integrity(
    sidecar_path: Path,
    expected_tuples: list[tuple[int, int, int, str]],
    expected_total: int = 16282,
) -> dict[str, str | int]:
    """Strictly validate sidecar completeness, feature bounds, non-leakage, and 1-to-1 matching."""
    if not sidecar_path.exists():
        raise FileNotFoundError(f"Sidecar file does not exist: {sidecar_path}")

    sidecar_bytes = sidecar_path.read_bytes()
    sidecar_sha256 = hashlib.sha256(sidecar_bytes).hexdigest()
    data = json.loads(sidecar_bytes.decode("utf-8"))

    entries = data.get("entries", [])
    if len(entries) != expected_total:
        raise ValueError(f"Sidecar must have exactly {expected_total} entries, found {len(entries)}")

    for i, entry in enumerate(entries):
        ex_idx = entry.get("example_index", i)
        if ex_idx != i:
            raise ValueError(f"Entry index mismatch at row {i}: got {ex_idx}")

        m_idx = entry["match_index"]
        ply = entry["ply"]
        actor = entry["actor"]
        info_hash = entry["information_set_hash"]

        if expected_tuples:
            exp_m, exp_ply, exp_actor, exp_hash = expected_tuples[i]
            if (m_idx, ply, actor, info_hash) != (exp_m, exp_ply, exp_actor, exp_hash):
                raise ValueError(f"Entry {i} metadata mismatch with dataset: got ({m_idx}, {ply}, {actor}, {info_hash}), expected ({exp_m}, {exp_ply}, {exp_actor}, {exp_hash})")

        feats = entry["belief_features"]
        if len(feats) != BELIEF_FEATURE_DIM:
            raise ValueError(f"Feature dim mismatch for row {i}: expected {BELIEF_FEATURE_DIM}, got {len(feats)}")

        # Part A (0..90): Unseen mask must be binary
        for dim_idx in range(90):
            if feats[dim_idx] not in (0.0, 1.0):
                raise ValueError(f"Unseen mask must be binary at dim {dim_idx} for row {i}: {feats[dim_idx]}")

        # Part B (90..210): Check 6 slots (2 players * 3 slots)
        for slot_idx in range(6):
            base = 90 + slot_idx * 20
            slot_status = feats[base:base + 6]
            if sum(slot_status) != 1.0:
                raise ValueError(f"Slot {slot_idx} status one-hot must sum to 1 for row {i}")

            # If slot is HiddenDeck (status index 3, 4, 5) or Empty (status index 0), attributes MUST be 0
            if slot_status[0] == 1.0 or sum(slot_status[3:6]) == 1.0:
                attrs = feats[base + 6:base + 20]
                if any(x != 0.0 for x in attrs):
                    raise ValueError(f"HiddenDeck/Empty slot {slot_idx} card attributes must be strictly zero for row {i}")

        # Part C (210..212): Purchased count in [0, 1]
        if not (0.0 <= feats[210] <= 1.0 and 0.0 <= feats[211] <= 1.0):
            raise ValueError(f"Purchased counts out of range for row {i}")

    return {
        "sidecar_file_sha256": sidecar_sha256,
        "total_entries": len(entries),
        "feature_dim": BELIEF_FEATURE_DIM,
    }

def preflight_m32a(
    config_path: Path,
    dataset_path: Path,
    catalog_path: Path,
    d2_result_path: Path,
    sidecar_path: Path,
    output_dir: Path,
    actual_dataset_semantic_hash: str,
    actual_catalog_hash: str,
    actual_param_count: int,
    expected_tuples: list[tuple[int, int, int, str]],
    require_cuda: bool = True,
) -> dict[str, str | int]:
    """Strict fail-closed validation of all frozen inputs, sidecar, and output directory BEFORE training."""
    if require_cuda and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for M32A training, but torch.cuda.is_available() is False")

    if output_dir.exists():
        raise RuntimeError(f"Output directory {output_dir} already exists — fail-closed protection")

    actual_config_sha = compute_file_sha256(config_path)
    if actual_config_sha != FROZEN_CONFIG_SHA256:
        raise ValueError(f"Config SHA mismatch! Expected {FROZEN_CONFIG_SHA256}, got {actual_config_sha}")

    actual_dataset_file_sha = compute_file_sha256(dataset_path)
    if actual_dataset_file_sha != FROZEN_DATASET_FILE_SHA256:
        raise ValueError(f"Dataset SHA mismatch! Expected {FROZEN_DATASET_FILE_SHA256}, got {actual_dataset_file_sha}")

    if actual_dataset_semantic_hash != FROZEN_DATASET_SEMANTIC_HASH:
        raise ValueError(f"Dataset semantic hash mismatch! Expected {FROZEN_DATASET_SEMANTIC_HASH}, got {actual_dataset_semantic_hash}")

    if actual_catalog_hash != FROZEN_CATALOG_HASH:
        raise ValueError(f"Catalog hash mismatch! Expected {FROZEN_CATALOG_HASH}, got {actual_catalog_hash}")

    actual_d2_sha = compute_file_sha256(d2_result_path)
    if actual_d2_sha != FROZEN_D2_RESULT_SHA256:
        raise ValueError(f"D2 result SHA mismatch! Expected {FROZEN_D2_RESULT_SHA256}, got {actual_d2_sha}")

    if actual_param_count != FROZEN_M32A_PARAMETER_COUNT:
        raise ValueError(f"Model parameter count mismatch! Expected {FROZEN_M32A_PARAMETER_COUNT}, got {actual_param_count}")

    sidecar_info = validate_sidecar_integrity(sidecar_path, expected_tuples, expected_total=16282)

    return {
        "config_file_sha256": actual_config_sha,
        "dataset_file_sha256": actual_dataset_file_sha,
        "dataset_semantic_hash": actual_dataset_semantic_hash,
        "catalog_hash": actual_catalog_hash,
        "d2_result_file_sha256": actual_d2_sha,
        "sidecar_file_sha256": str(sidecar_info["sidecar_file_sha256"]),
    }
