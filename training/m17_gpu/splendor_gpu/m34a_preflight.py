"""M34A Preflight and Provenance Verification for Hierarchical Policy."""
import hashlib
from pathlib import Path
import torch

FROZEN_CONFIG_SHA256 = "bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250"
FROZEN_DATASET_FILE_SHA256 = "2e15cc9d3f96c0993e3746f45c4eb24d3e1bf92f80c2b515d5f171f1e1f05907"
FROZEN_DATASET_SEMANTIC_HASH = "1aa7212ff070e637d0f0aeabf6eddd16e0d00fc1d5a6aa9da93e75be69975419"
FROZEN_CATALOG_HASH = "4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26"
FROZEN_D2_RESULT_SHA256 = "403e4903044dfec929c6e92713b2bb9f3e120469ab872271dc82e78f752efc38"
FROZEN_D2_CKPT_SHA256 = "a00c783a4af5e61b753b8ba12bd84176f3b47ffce7331e10c478fcc91b0f82ca"

# Model parameter calculation:
# D2 Base Parameters: 953,476
# Hierarchical Heads:
# - family_head: Linear(192, 192) + Linear(192, 5) = 37,056 + 965 = 38,021
# - take_pattern_head: Linear(192, 192) + Linear(192, 30) = 37,056 + 5,790 = 42,846
# - return_penalty_head: Linear(192, 192) + Linear(192, 6) = 37,056 + 1,158 = 38,214
# Total Hierarchical Parameters = 38,021 + 42,846 + 38,214 = 119,081
# Total Model Parameters = 953,476 + 119,081 = 1,072,557
FROZEN_M34A_PARAMETER_COUNT = 1072557

def compute_file_sha256(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required artifact does not exist: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()

def preflight_m34a(
    config_path: Path,
    dataset_path: Path,
    catalog_path: Path,
    d2_result_path: Path,
    d2_ckpt_path: Path,
    output_dir: Path,
    actual_dataset_semantic_hash: str,
    actual_catalog_hash: str,
    actual_param_count: int,
    require_cuda: bool = True,
) -> dict[str, str | int]:
    """Strict fail-closed preflight validation for M34A."""
    if require_cuda and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for M34A training, but torch.cuda.is_available() is False")

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

    actual_d2_ckpt_sha = compute_file_sha256(d2_ckpt_path)
    if actual_d2_ckpt_sha != FROZEN_D2_CKPT_SHA256:
        raise ValueError(f"D2 checkpoint SHA mismatch! Expected {FROZEN_D2_CKPT_SHA256}, got {actual_d2_ckpt_sha}")

    if actual_param_count != FROZEN_M34A_PARAMETER_COUNT:
        raise ValueError(f"Model parameter count mismatch! Expected {FROZEN_M34A_PARAMETER_COUNT}, got {actual_param_count}")

    return {
        "config_file_sha256": actual_config_sha,
        "dataset_file_sha256": actual_dataset_file_sha,
        "dataset_semantic_hash": actual_dataset_semantic_hash,
        "catalog_hash": actual_catalog_hash,
        "d2_result_file_sha256": actual_d2_sha,
        "d2_ckpt_file_sha256": actual_d2_ckpt_sha,
        "parameter_count": actual_param_count,
    }
