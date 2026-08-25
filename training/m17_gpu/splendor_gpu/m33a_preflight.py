"""M33A Preflight and Provenance Verification for Factorized Legal-Action Policy."""
import hashlib
import json
from pathlib import Path
import torch
from splendor_gpu.m33a_model import FactorizedDeltaEntityMixer

FROZEN_CONFIG_SHA256 = "bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250"
FROZEN_DATASET_FILE_SHA256 = "2e15cc9d3f96c0993e3746f45c4eb24d3e1bf92f80c2b515d5f171f1e1f05907"
FROZEN_DATASET_SEMANTIC_HASH = "1aa7212ff070e637d0f0aeabf6eddd16e0d00fc1d5a6aa9da93e75be69975419"
FROZEN_CATALOG_HASH = "4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26"
FROZEN_D2_RESULT_SHA256 = "403e4903044dfec929c6e92713b2bb9f3e120469ab872271dc82e78f752efc38"

# Model parameter calculation:
# D2 Base Parameters = 953,476
# Structured Branch:
# - intent_head: Linear(192, 192) + Linear(192, 5) = 192*193 + 192*5 + 5 = 37,056 + 965 = 38,021
# - take_mode_head: Linear(192, 192) + Linear(192, 4) = 37,056 + 192*4 + 4 = 37,828
# - color_desirability_head: Linear(192, 192) + Linear(192, 5) = 38,021
# - keep_penalty_head: Linear(192, 192) + Linear(192, 6) = 37,056 + 192*6 + 6 = 38,214
# - entity_conditioned_scorer: Linear(192*3=576, 192) + Linear(192, 3) = 576*192 + 192 + 192*3 + 3 = 110,784 + 192 + 576 + 3 = 111,555
# - deck_tier_head: Linear(192, 192) + Linear(192, 3) = 37,056 + 192*3 + 3 = 37,635
# Total Structured Parameters = 38,021 + 37,828 + 38,021 + 38,214 + 111,555 + 37,635 = 311,274
# Total Model Parameters = 953,476 + 311,274 = 1,264,750
FROZEN_M33A_PARAMETER_COUNT = 1254558

def compute_file_sha256(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required artifact does not exist: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()

def preflight_m33a(
    config_path: Path,
    dataset_path: Path,
    catalog_path: Path,
    d2_result_path: Path,
    output_dir: Path,
    actual_dataset_semantic_hash: str,
    actual_catalog_hash: str,
    actual_param_count: int,
    require_cuda: bool = True,
) -> dict[str, str | int]:
    """Strict fail-closed preflight validation for M33A."""
    if require_cuda and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for M33A training, but torch.cuda.is_available() is False")

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

    if actual_param_count != FROZEN_M33A_PARAMETER_COUNT:
        raise ValueError(f"Model parameter count mismatch! Expected {FROZEN_M33A_PARAMETER_COUNT}, got {actual_param_count}")

    return {
        "config_file_sha256": actual_config_sha,
        "dataset_file_sha256": actual_dataset_file_sha,
        "dataset_semantic_hash": actual_dataset_semantic_hash,
        "catalog_hash": actual_catalog_hash,
        "d2_result_file_sha256": actual_d2_sha,
        "parameter_count": actual_param_count,
    }
