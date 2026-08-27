"""Strict Model Registry for M35A Direct Policy Retrospective Arena."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import torch
import torch.nn as nn

from splendor_gpu.model import (
    ModelSpec,
    EntityMixerPolicyValue,
    ContextualEntityMixerPolicyValue,
)
from splendor_gpu.m31a_train import DeltaEntityMixer
from splendor_gpu.m29a_v2_model import NestedResidualActionEntityMixer
from splendor_gpu.m32a_train import BeliefDeltaEntityMixer
from splendor_gpu.m33a_model import FactorizedDeltaEntityMixer
from splendor_gpu.m34a_model import HierarchicalDeltaEntityMixer

FROZEN_CATALOG_HASH = "4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26"
CANONICAL_M25_DATASET_HASH = "1aa7212ff070e637d0f0aeabf6eddd16e0d00fc1d5a6aa9da93e75be69975419"


def compute_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ModelRegistryEntry:
    model_id: str
    milestone: str
    checkpoint_path: Path
    checkpoint_file_sha256: str
    architecture_name: str
    parameter_count: int
    catalog_hash: str
    dataset_hash: str
    action_feature_dim: int
    global_feature_dim: int
    output_semantics: str  # "flat_logits" | "composite_residual_logits" | "hierarchical_log_probs"
    factory: Callable[[], nn.Module]


REGISTRY: dict[str, ModelRegistryEntry] = {
    "M24-S2": ModelRegistryEntry(
        model_id="M24-S2",
        milestone="M24",
        checkpoint_path=Path("local-artifacts/m24-self-play-s2-v1/trained/checkpoint.pt"),
        checkpoint_file_sha256="0ba19302a5cd0fe618fc5246a3d5bc9c562460d558cff2a128d1c25b6fe0543e",
        architecture_name="EntityMixerPolicyValue(h192, b4)",
        parameter_count=949060,
        catalog_hash=FROZEN_CATALOG_HASH,
        dataset_hash="3f8adcd4e8e6ec224a029085a817f87a06fb450d08dbd37cca05d488f1d29c24",
        action_feature_dim=36,
        global_feature_dim=40,
        output_semantics="flat_logits",
        factory=lambda: EntityMixerPolicyValue(ModelSpec("entity_mixer", hidden_dim=192, blocks=4)),
    ),
    "M25-D2-v2": ModelRegistryEntry(
        model_id="M25-D2-v2",
        milestone="M25",
        checkpoint_path=Path("local-artifacts/m25-recovery-exp-d2-v2/checkpoint.pt"),
        checkpoint_file_sha256="113372fc1092e611804cb7261844ac2a104608772f68ab74a854a038370c7e17",
        architecture_name="DeltaEntityMixer(h192, b4, 59-dim delta)",
        parameter_count=953476,
        catalog_hash=FROZEN_CATALOG_HASH,
        dataset_hash=CANONICAL_M25_DATASET_HASH,
        action_feature_dim=59,
        global_feature_dim=40,
        output_semantics="flat_logits",
        factory=lambda: DeltaEntityMixer(hidden_dim=192, blocks=4),
    ),
    "M28A": ModelRegistryEntry(
        model_id="M28A",
        milestone="M28A",
        checkpoint_path=Path("local-artifacts/m28a-entity-mixer-width-v1/candidate/checkpoint.pt"),
        checkpoint_file_sha256="b0a7947c2c1af003f99e72970867f73cb0d40e7c75e9c966b4e8895e5fef868f",
        architecture_name="EntityMixerPolicyValue(h320, b4)",
        parameter_count=2605764,
        catalog_hash=FROZEN_CATALOG_HASH,
        dataset_hash="b8a67f5fd41dde0ee3c1c5194c12e7b0886813039c8ccde9660b211f26838e46",
        action_feature_dim=36,
        global_feature_dim=40,
        output_semantics="flat_logits",
        factory=lambda: EntityMixerPolicyValue(ModelSpec("entity_mixer", hidden_dim=320, blocks=4)),
    ),
    "M28B": ModelRegistryEntry(
        model_id="M28B",
        milestone="M28B",
        checkpoint_path=Path("local-artifacts/m28b-contextual-entity-interaction-v1-rerun-compute-repair/candidate/checkpoint.pt"),
        checkpoint_file_sha256="46f68b20d863c450f375999713f869e5c71c6abeb4e025c45f6b42a004b47b6b",
        architecture_name="ContextualEntityMixerPolicyValue(h192, b4, interactions=2)",
        parameter_count=1689798,
        catalog_hash=FROZEN_CATALOG_HASH,
        dataset_hash="b8a67f5fd41dde0ee3c1c5194c12e7b0886813039c8ccde9660b211f26838e46",
        action_feature_dim=36,
        global_feature_dim=40,
        output_semantics="flat_logits",
        factory=lambda: ContextualEntityMixerPolicyValue(ModelSpec("contextual_entity_mixer", hidden_dim=192, blocks=4, interaction_blocks=2)),
    ),
    "M29A-v2": ModelRegistryEntry(
        model_id="M29A-v2",
        milestone="M29A",
        checkpoint_path=Path("local-artifacts/m29a-v2-nested-residual-attention/checkpoint.pt"),
        checkpoint_file_sha256="f3bd8104b1d8177843d9eb919c00aa2923d7fb513f21f6960c662a5e16198873",
        architecture_name="NestedResidualActionEntityMixer(h192, b4)",
        parameter_count=1212484,
        catalog_hash=FROZEN_CATALOG_HASH,
        dataset_hash=CANONICAL_M25_DATASET_HASH,
        action_feature_dim=59,
        global_feature_dim=40,
        output_semantics="flat_logits",
        factory=lambda: NestedResidualActionEntityMixer(hidden_dim=192, blocks=4),
    ),
    "M31A": ModelRegistryEntry(
        model_id="M31A",
        milestone="M31A",
        checkpoint_path=Path("local-artifacts/m31a-ranking-objective/checkpoint.pt"),
        checkpoint_file_sha256="1225ec99c0a09b875a3ef8f9724ebbc271d7f224ceadcd79a9af49aca6ea13f5",
        architecture_name="DeltaEntityMixer(h192, b4, Ranking Loss)",
        parameter_count=953476,
        catalog_hash=FROZEN_CATALOG_HASH,
        dataset_hash=CANONICAL_M25_DATASET_HASH,
        action_feature_dim=59,
        global_feature_dim=40,
        output_semantics="flat_logits",
        factory=lambda: DeltaEntityMixer(hidden_dim=192, blocks=4),
    ),
    "M32A": ModelRegistryEntry(
        model_id="M32A",
        milestone="M32A",
        checkpoint_path=Path("local-artifacts/m32a-information-parity/checkpoint.pt"),
        checkpoint_file_sha256="3653045b5d50be3d11a00b6f7a960658bd1e1b4bf9efed6141ea28aae51582be",
        architecture_name="BeliefDeltaEntityMixer(h192, b4, 252-dim global)",
        parameter_count=994180,
        catalog_hash=FROZEN_CATALOG_HASH,
        dataset_hash=CANONICAL_M25_DATASET_HASH,
        action_feature_dim=59,
        global_feature_dim=252,
        output_semantics="flat_logits",
        factory=lambda: BeliefDeltaEntityMixer(hidden_dim=192, blocks=4),
    ),
    "M33A": ModelRegistryEntry(
        model_id="M33A",
        milestone="M33A",
        checkpoint_path=Path("local-artifacts/m33a-factorized-policy/checkpoint.pt"),
        checkpoint_file_sha256="f636de570b196cd9bff0ec2705f1d3dea18a186b402923bc34031eebe728d5f5",
        architecture_name="FactorizedDeltaEntityMixer(h192, b4)",
        parameter_count=1254558,
        catalog_hash=FROZEN_CATALOG_HASH,
        dataset_hash=CANONICAL_M25_DATASET_HASH,
        action_feature_dim=59,
        global_feature_dim=40,
        output_semantics="composite_residual_logits",
        factory=lambda: FactorizedDeltaEntityMixer(hidden_dim=192, blocks=4),
    ),
    "M34A": ModelRegistryEntry(
        model_id="M34A",
        milestone="M34A",
        checkpoint_path=Path("local-artifacts/m34a-hierarchical-policy/checkpoint.pt"),
        checkpoint_file_sha256="a958aefb6aadd2caeeb717b15dfb6386c4cbff23113a256bdae2963b1da68b9c",
        architecture_name="HierarchicalDeltaEntityMixer(h192, b4)",
        parameter_count=1072557,
        catalog_hash=FROZEN_CATALOG_HASH,
        dataset_hash=CANONICAL_M25_DATASET_HASH,
        action_feature_dim=59,
        global_feature_dim=40,
        output_semantics="hierarchical_log_probs",
        factory=lambda: HierarchicalDeltaEntityMixer(hidden_dim=192, blocks=4),
    ),
}


def load_and_validate_checkpoint(
    model_id: str,
    catalog_hash: str,
    device: torch.device,
) -> tuple[nn.Module, ModelRegistryEntry]:
    """Strictly loads, validates, and instantiates a model from the registry."""
    if model_id not in REGISTRY:
        raise ValueError(f"Unknown model_id: '{model_id}'. Allowed: {list(REGISTRY.keys())}")
    entry = REGISTRY[model_id]

    # 1. Pre-load: verify file existence and exact SHA256
    if not entry.checkpoint_path.exists():
        raise FileNotFoundError(f"Checkpoint not found at {entry.checkpoint_path}")
    actual_sha = compute_file_sha256(entry.checkpoint_path)
    if actual_sha != entry.checkpoint_file_sha256:
        raise ValueError(
            f"Checkpoint SHA256 mismatch for {model_id}: "
            f"expected {entry.checkpoint_file_sha256}, got {actual_sha}"
        )

    # 2. Load payload
    payload = torch.load(entry.checkpoint_path, map_location="cpu", weights_only=False)
    metadata = payload.get("metadata", {})
    state_dict = payload.get("state_dict", {})

    # 3. Validate metadata
    ckpt_cat_hash = metadata.get("catalog_hash") or metadata.get("frozen_catalog_hash")
    if ckpt_cat_hash != catalog_hash:
        raise ValueError(
            f"Catalog hash mismatch for {model_id}: "
            f"expected {catalog_hash}, got {ckpt_cat_hash}"
        )

    ckpt_ds_hash = (
        metadata.get("dataset_semantic_hash")
        or metadata.get("source_dataset_hash")
        or metadata.get("source_self_play_hash")
    )
    if ckpt_ds_hash != entry.dataset_hash:
        raise ValueError(
            f"Dataset hash mismatch for {model_id}: "
            f"expected {entry.dataset_hash}, got {ckpt_ds_hash}"
        )

    # 4. Instantiate model and verify parameter count
    model = entry.factory()
    actual_params = sum(p.numel() for p in model.parameters())
    if actual_params != entry.parameter_count:
        raise ValueError(
            f"Parameter count mismatch for {model_id}: "
            f"expected {entry.parameter_count}, got {actual_params}"
        )

    # 5. Load weights strictly
    model.load_state_dict(state_dict, strict=True)
    model.to(device).eval()

    return model, entry
