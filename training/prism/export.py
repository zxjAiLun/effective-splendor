"""Strict float32 JSON export/load and checkpoint tensor identity."""

import argparse
from collections.abc import Mapping
from pathlib import Path

import torch

from .io import canonical_hash, read_json, sha256_file, tensor_identity, tensor_manifest, write_json
from .model import ACTION_DIM, ACTION_SCHEMA, ENTITY_DIM, HIDDEN_DIM, NUM_BLOCKS, OBS_SCHEMA, PrismModel

METADATA = {"format": "prism-weights-v1", "observation_schema": OBS_SCHEMA,
            "action_schema": ACTION_SCHEMA, "hidden_dim": HIDDEN_DIM,
            "num_blocks": NUM_BLOCKS, "entity_dim": ENTITY_DIM, "action_dim": ACTION_DIM}


def _new_model():
    # Loading/checking/exporting must not consume the training RNG stream.
    with torch.random.fork_rng(devices=[]):
        return PrismModel().float()


def validate_state_dict(state_dict):
    expected = _new_model().state_dict()
    if not isinstance(state_dict, Mapping) or set(state_dict) != set(expected):
        raise ValueError("wrong state_dict keys")
    for key, tensor in state_dict.items():
        if not isinstance(tensor, torch.Tensor) or tensor.shape != expected[key].shape:
            raise ValueError(f"{key}: wrong tensor shape")
        if tensor.dtype != torch.float32 or not torch.isfinite(tensor).all():
            raise ValueError(f"{key}: weights must be finite float32")


def export_weights(model_or_state, path, catalog_fingerprint, *, provenance=None):
    """Write exact JSON plus <stem>.manifest.json; return the companion manifest."""
    if not isinstance(catalog_fingerprint, str) or not catalog_fingerprint:
        raise ValueError("catalog_fingerprint is required")
    state = model_or_state.state_dict() if isinstance(model_or_state, PrismModel) else model_or_state
    validate_state_dict(state)
    weights = dict(METADATA, catalog_fingerprint=catalog_fingerprint, state_dict={})
    for key, tensor in state.items():
        tensor = tensor.detach().cpu().contiguous()
        weights["state_dict"][key] = {"shape": list(tensor.shape), "data": tensor.flatten().tolist()}
    write_json(path, weights)
    restored = load_weights(path, expected_catalog_fingerprint=catalog_fingerprint)
    for key, tensor in restored.state_dict().items():
        if not torch.equal(tensor, state[key].detach().cpu()):
            raise ValueError(f"JSON tensor roundtrip mismatch: {key}")
    tensors = tensor_manifest(state)
    manifest = {"format": "prism-weights-manifest-v1", "weights_sha256": sha256_file(path),
                "tensor_sha256": canonical_hash(tensors), "tensors": tensors,
                "catalog_fingerprint": catalog_fingerprint, "provenance": provenance or {}}
    write_json(Path(path).with_suffix(".manifest.json"), manifest)
    return manifest


def load_weights(path, *, expected_catalog_fingerprint):
    """Reject unknown fields, malformed tensors and identity mismatch; never fallback."""
    return weights_from_dict(read_json(path), expected_catalog_fingerprint=expected_catalog_fingerprint)


def weights_from_dict(weights, *, expected_catalog_fingerprint):
    if not isinstance(expected_catalog_fingerprint, str) or not expected_catalog_fingerprint:
        raise ValueError("expected catalog fingerprint is required")
    if not isinstance(weights, dict) or set(weights) != set(METADATA) | {"catalog_fingerprint", "state_dict"}:
        raise ValueError("unknown/missing weights fields")
    for key, value in METADATA.items():
        if type(weights[key]) is not type(value) or weights[key] != value:
            raise ValueError(f"weights {key} mismatch")
    if weights["catalog_fingerprint"] != expected_catalog_fingerprint:
        raise ValueError("weights catalog fingerprint mismatch")
    model = _new_model()
    expected = model.state_dict()
    serialized = weights["state_dict"]
    if not isinstance(serialized, dict) or set(serialized) != set(expected):
        raise ValueError("wrong state_dict keys")
    state = {}
    for key, reference in expected.items():
        item = serialized[key]
        if not isinstance(item, dict) or set(item) != {"shape", "data"}:
            raise ValueError(f"{key}: unknown/missing tensor fields")
        shape, data = item["shape"], item["data"]
        if not isinstance(shape, list) or any(type(n) is not int for n in shape) or shape != list(reference.shape):
            raise ValueError(f"{key}: wrong shape")
        if not isinstance(data, list) or len(data) != reference.numel():
            raise ValueError(f"{key}: wrong data length")
        if any(type(value) not in (int, float) for value in data):
            raise ValueError(f"{key}: nonnumeric weight")
        try:
            state[key] = torch.tensor(data, dtype=torch.float32).reshape(shape)
        except (RuntimeError, TypeError, OverflowError) as exc:
            raise ValueError(f"{key}: invalid weights") from exc
    validate_state_dict(state)
    model.load_state_dict(state, strict=True)
    return model.eval()


def load_checkpoint_model(path, *, expected_catalog_fingerprint):
    """Only load trusted local .pt files: torch pickle checkpoints are executable."""
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(checkpoint, dict) or checkpoint.get("format") != "prism-checkpoint-v1":
        raise ValueError("wrong checkpoint format")
    if checkpoint.get("catalog_fingerprint") != expected_catalog_fingerprint:
        raise ValueError("checkpoint catalog fingerprint mismatch")
    state = checkpoint.get("state_dict")
    validate_state_dict(state)
    if checkpoint.get("tensor_sha256") != tensor_identity(state):
        raise ValueError("checkpoint tensor identity mismatch")
    model = _new_model()
    model.load_state_dict(state, strict=True)
    return model.eval(), checkpoint


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--catalog-fingerprint", required=True)
    args = parser.parse_args(argv)
    model, checkpoint = load_checkpoint_model(args.checkpoint, expected_catalog_fingerprint=args.catalog_fingerprint)
    export_weights(model, args.output, args.catalog_fingerprint, provenance={
        "checkpoint_sha256": sha256_file(args.checkpoint), "epoch": checkpoint["epoch"],
        "config_sha256": checkpoint["config_sha256"], "dataset_sha256": checkpoint["dataset_sha256"],
    })


if __name__ == "__main__":
    main()
