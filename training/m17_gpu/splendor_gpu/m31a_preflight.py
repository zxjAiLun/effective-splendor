"""M31A Preflight and Frozen Provenance Verification."""
import hashlib
from pathlib import Path
import torch

FROZEN_CONFIG_SHA256 = "bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250"
FROZEN_DATASET_FILE_SHA256 = "2e15cc9d3f96c0993e3746f45c4eb24d3e1bf92f80c2b515d5f171f1e1f05907"
FROZEN_DATASET_SEMANTIC_HASH = "1aa7212ff070e637d0f0aeabf6eddd16e0d00fc1d5a6aa9da93e75be69975419"
FROZEN_CATALOG_HASH = "4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26"
FROZEN_D2_RESULT_SHA256 = "403e4903044dfec929c6e92713b2bb9f3e120469ab872271dc82e78f752efc38"
FROZEN_PARAMETER_COUNT = 953476

def compute_file_sha256(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required artifact does not exist: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()

def preflight_m31a(
    config_path: Path,
    dataset_path: Path,
    catalog_path: Path,
    d2_result_path: Path,
    output_dir: Path,
    actual_dataset_semantic_hash: str,
    actual_catalog_hash: str,
    actual_param_count: int,
    require_cuda: bool = True,
) -> dict[str, str]:
    """Strict fail-closed validation of all frozen hashes, environment, and output directory BEFORE training."""
    if require_cuda and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for M31A training, but torch.cuda.is_available() is False")

    # 1. Output directory fail-closed check
    if output_dir.exists():
        raise RuntimeError(f"Output directory {output_dir} already exists — fail-closed protection")

    # 2. Config file SHA
    actual_config_sha = compute_file_sha256(config_path)
    if actual_config_sha != FROZEN_CONFIG_SHA256:
        raise ValueError(
            f"Config file SHA mismatch! Expected {FROZEN_CONFIG_SHA256}, got {actual_config_sha}"
        )

    # 3. Dataset file SHA
    actual_dataset_file_sha = compute_file_sha256(dataset_path)
    if actual_dataset_file_sha != FROZEN_DATASET_FILE_SHA256:
        raise ValueError(
            f"Dataset file SHA mismatch! Expected {FROZEN_DATASET_FILE_SHA256}, got {actual_dataset_file_sha}"
        )

    # 4. Dataset semantic hash
    if actual_dataset_semantic_hash != FROZEN_DATASET_SEMANTIC_HASH:
        raise ValueError(
            f"Dataset semantic hash mismatch! Expected {FROZEN_DATASET_SEMANTIC_HASH}, got {actual_dataset_semantic_hash}"
        )

    # 5. Catalog semantic hash
    if actual_catalog_hash != FROZEN_CATALOG_HASH:
        raise ValueError(
            f"Catalog hash mismatch! Expected {FROZEN_CATALOG_HASH}, got {actual_catalog_hash}"
        )

    # 6. D2 result file SHA
    actual_d2_sha = compute_file_sha256(d2_result_path)
    if actual_d2_sha != FROZEN_D2_RESULT_SHA256:
        raise ValueError(
            f"D2 baseline result file SHA mismatch! Expected {FROZEN_D2_RESULT_SHA256}, got {actual_d2_sha}"
        )

    # 7. Model parameter count
    if actual_param_count != FROZEN_PARAMETER_COUNT:
        raise ValueError(
            f"Model parameter count mismatch! Expected {FROZEN_PARAMETER_COUNT}, got {actual_param_count}"
        )

    return {
        "config_file_sha256": actual_config_sha,
        "dataset_file_sha256": actual_dataset_file_sha,
        "dataset_semantic_hash": actual_dataset_semantic_hash,
        "catalog_hash": actual_catalog_hash,
        "d2_result_file_sha256": actual_d2_sha,
    }
