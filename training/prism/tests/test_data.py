import numpy as np
import pytest
import torch

from training.prism import PrismDataset, collate
from training.prism.data import ARRAYS
from training.prism.io import read_json, sha256_file, write_json
from conftest import CATALOG, make_state


def test_readonly_memmap_and_batch_no_provenance_or_filtering(dataset_factory):
    root = dataset_factory()
    with PrismDataset(root, expected_catalog_fingerprint=CATALOG) as dataset:
        assert len(dataset) == 7
        for name in ARRAYS:
            assert isinstance(dataset.arrays[name], np.memmap)
            assert not dataset.arrays[name].flags.writeable
        samples = [dataset[i] for i in range(len(dataset))]
        batch = collate(samples)
        assert set(batch) == {"entities", "actions", "targets", "entity_mask", "action_mask", "chosen", "outcomes"}
        assert set(batch["outcomes"].tolist()) == {0.0, 0.5, 1.0}
        assert batch["outcomes"].numel() == 7
        assert batch["entity_mask"].sum().item() == dataset.meta["entities"]
        assert batch["action_mask"].sum().item() == dataset.meta["actions"]
        assert batch["targets"][~batch["action_mask"]].eq(-1).all()
        assert np.shares_memory(samples[1]["entities"], dataset.entities)
        assert batch["entities"].dtype == torch.float32


@pytest.mark.parametrize("filename,index,value", [
    ("entity_offsets.u64", 0, 1), ("entity_offsets.u64", 1, 0),
    ("entity_offsets.u64", 2, 2**64 - 1), ("entity_offsets.u64", -1, 1),
    ("action_offsets.u64", 1, 5000), ("action_offsets.u64", -1, 0),
    ("targets.i32", 0, -2), ("targets.i32", 0, 1),
    ("chosen.u32", 0, 1), ("chosen.u32", -1, 2**32 - 1),
    ("outcomes.f32", 0, 0.3), ("outcomes.f32", 1, float("nan")),
    ("entities.f32", 0, float("inf")), ("actions.f32", 1, float("nan")),
])
def test_malformed_numeric_arrays_fail_without_hash_shortcut(dataset_factory, filename, index, value):
    root = dataset_factory()
    path = root / "train" / filename
    array = np.fromfile(path, dtype=ARRAYS[filename][0])
    array[index] = value
    array.tofile(path)
    with pytest.raises(ValueError):
        PrismDataset(root, verify_hashes=False)


@pytest.mark.parametrize("filename", list(ARRAYS))
def test_truncated_arrays_fail(dataset_factory, filename):
    root = dataset_factory()
    path = root / "train" / filename
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match="file size"):
        PrismDataset(root, verify_hashes=False)


@pytest.mark.parametrize("field,value", [("format", "wrong"), ("observation_schema", "wrong"),
                                         ("action_schema", "wrong"), ("entity_dim", 95), ("action_dim", 79)])
def test_bad_dataset_schema(dataset_factory, field, value):
    root = dataset_factory()
    manifest = read_json(root / "manifest.json")
    manifest[field] = value
    write_json(root / "manifest.json", manifest)
    with pytest.raises(ValueError, match="mismatch"):
        PrismDataset(root)


@pytest.mark.parametrize("mutation", ["duplicate_seed", "counts", "hash", "hash_location", "rows", "catalog", "empty"])
def test_manifest_sources_hashes_and_counts(dataset_factory, mutation):
    root = dataset_factory()
    manifest = read_json(root / "manifest.json")
    if mutation == "duplicate_seed":
        manifest["sources"][1]["seed"] = manifest["sources"][0]["seed"]
    elif mutation == "counts":
        manifest["sources"][0]["steps"] += 1
    elif mutation == "hash":
        manifest["splits"]["train"]["hashes"]["actions.f32"] = "0" * 64
    elif mutation == "hash_location":
        manifest["splits"]["train"]["files"] = manifest["splits"]["train"].pop("hashes")
    elif mutation == "rows":
        (root / "train" / "rows.jsonl").write_text("{}\n", encoding="utf-8")
        manifest["splits"]["train"]["hashes"]["rows.jsonl"] = sha256_file(root / "train" / "rows.jsonl")
    elif mutation == "catalog":
        manifest["catalog_fingerprint"] = "wrong"
    else:
        manifest["splits"]["train"]["states"] = 0
    write_json(root / "manifest.json", manifest)
    with pytest.raises(ValueError):
        PrismDataset(root, expected_catalog_fingerprint=CATALOG)


@pytest.mark.parametrize("mutation", ["width", "empty", "many_entities", "many_actions", "float_target",
                                      "missing_target", "bad_target", "seed", "label", "chosen", "outcome",
                                      "string_features", "boolean_features"])
def test_collate_rejects_malformed_state(mutation):
    state = make_state()
    if mutation == "width":
        state["entities"] = np.zeros((3, 95))
    elif mutation == "empty":
        state["actions"] = np.zeros((0, 80))
    elif mutation == "many_entities":
        state["entities"] = np.zeros((129, 96))
    elif mutation == "many_actions":
        state["actions"] = np.zeros((4097, 80))
    elif mutation == "float_target":
        state["targets"] = np.zeros(4, dtype=np.float32)
    elif mutation == "missing_target":
        state["targets"] = [0]
    elif mutation == "bad_target":
        state["targets"][0] = 3
    elif mutation == "seed":
        state["seed"] = 1
    elif mutation == "label":
        state["chosen"] = 0
    elif mutation == "chosen":
        state.update(chosen=4, outcome=0.5)
    elif mutation == "string_features":
        state["entities"] = np.full((3, 96), "0.5")
    elif mutation == "boolean_features":
        state["entities"] = np.zeros((3, 96), dtype=bool)
    else:
        state.update(chosen=0, outcome=float("nan"))
    with pytest.raises(ValueError):
        collate([state])


def test_provenance_cannot_change_features(dataset_factory):
    root = dataset_factory()
    with PrismDataset(root) as dataset:
        before = collate([dataset[0]])
    rows = root / "train" / "rows.jsonl"
    rows.write_text('{"hidden_future": [900, 800], "outcome": 1}\n' * 7, encoding="utf-8")
    manifest = read_json(root / "manifest.json")
    manifest["splits"]["train"]["hashes"]["rows.jsonl"] = sha256_file(rows)
    write_json(root / "manifest.json", manifest)
    with PrismDataset(root) as dataset:
        after = collate([dataset[0]])
    for key in before:
        assert torch.equal(before[key], after[key])
