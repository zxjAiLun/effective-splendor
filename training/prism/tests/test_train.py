import copy
import random
import shutil
from pathlib import Path

import numpy as np
import pytest
import torch

from training.prism import PrismDataset, PrismModel, collate, load_weights
from training.prism.export import load_checkpoint_model
from training.prism.io import read_json, sha256_file, tensor_identity, write_json
from training.prism.train import FIXED, evaluate, loss_terms, run_training, select_best_epoch, train_epoch, validate_config
from conftest import CATALOG, make_state


def tiny_config(tmp_path, root):
    path = tmp_path / "config.json"
    config = {"training": dict(FIXED, data_dir=str(root), out_dir=str(tmp_path / "run"),
                                seed=51000001, device="cpu"),
              "dataset": {"train_games": 1, "val_games": 1, "val_modulus": 5, "val_remainder": 0}}
    write_json(path, config)
    return path


def assert_tree_equal(a, b):
    assert type(a) is type(b)
    if isinstance(a, torch.Tensor):
        assert torch.equal(a, b)
    elif isinstance(a, np.ndarray):
        np.testing.assert_array_equal(a, b)
    elif isinstance(a, dict):
        assert a.keys() == b.keys()
        for key in a:
            assert_tree_equal(a[key], b[key])
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b)
        for left, right in zip(a, b):
            assert_tree_equal(left, right)
    else:
        assert a == b


def test_tiny_complete_20_epochs_and_exact_same_config_resume(tmp_path, dataset_factory):
    # Small tensors, but both 64+64+1 accumulation and 64+1 validation tails occur.
    root = dataset_factory(train_states=129, val_states=65)
    config = tiny_config(tmp_path, root)
    out = tmp_path / "run"
    full_summary = run_training(config)
    full_checkpoint = torch.load(out / "checkpoint-last.pt", weights_only=False)
    assert full_summary["status"] == "COMPLETE" and full_summary["completed_epochs"] == 20
    assert full_summary["best_differs_from_init"]
    assert full_summary["config_sha256"] == sha256_file(config)
    assert full_summary["dataset_manifest_sha256"] == sha256_file(root / "manifest.json")
    history = read_json(out / "history.json")
    assert len(history) == 20
    assert full_summary["best_epoch"] == select_best_epoch(history)
    assert all(row["train"]["states"] == 129 and row["train"]["optimizer_steps"] == 2 for row in history)
    assert all(row["val"]["states"] == 65 for row in history)
    for name, digest in full_summary["hashes"].items():
        assert sha256_file(out / name) == digest
    best, checkpoint = load_checkpoint_model(out / "best_model.pt", expected_catalog_fingerprint=CATALOG)
    exported = load_weights(out / "weights.json", expected_catalog_fingerprint=CATALOG)
    assert tensor_identity(best.state_dict()) == tensor_identity(exported.state_dict())
    assert checkpoint["epoch"] == full_summary["best_epoch"]
    with PrismDataset(root, "val") as val:
        metrics = evaluate(best, val, 64, torch.device("cpu"))
    assert metrics["loss"] == full_summary["best_val_loss"]
    for group in full_checkpoint["optimizer_state_dict"]["param_groups"]:
        assert group["lr"] == 3e-4 and group["weight_decay"] == 1e-4
    assert not torch.backends.cuda.matmul.allow_tf32 and not torch.backends.cudnn.allow_tf32
    assert torch.get_num_threads() == 2
    baseline = tmp_path / "uninterrupted"
    shutil.move(str(out), baseline)

    paused = run_training(config, stop_after_epoch=5)
    assert paused["status"] == "INTERRUPTED" and paused["completed_epochs"] == 5
    with pytest.raises(ValueError, match="not empty"):
        run_training(config)
    # Byte-for-byte config identity, even a whitespace-only edit, is frozen.
    original = config.read_bytes()
    config.write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="config_sha256"):
        run_training(config, resume=True)
    config.write_bytes(original)
    manifest_path = root / "manifest.json"
    original_manifest = manifest_path.read_bytes()
    changed = read_json(manifest_path)
    changed["provenance_note"] = "identity changed"
    write_json(manifest_path, changed)
    with pytest.raises(ValueError, match="dataset_sha256"):
        run_training(config, resume=True)
    manifest_path.write_bytes(original_manifest)
    with pytest.raises(ValueError, match="runtime"):
        run_training(config, resume=True, device="cpu")
    # Simulate a crash after checkpoint commit but before derived files publish.
    (out / "best_model.pt").unlink()
    (out / "history.json").write_text("not valid JSON", encoding="utf-8")
    random.seed(999)
    np.random.seed(999)
    torch.manual_seed(999)
    resumed = run_training(config, resume=True)
    final = torch.load(out / "checkpoint-last.pt", weights_only=False)
    for key in ("state_dict", "best_state_dict", "optimizer_state_dict", "rng_state", "history"):
        assert_tree_equal(final[key], full_checkpoint[key])
    assert resumed["best_epoch"] == full_summary["best_epoch"]
    assert resumed["best_tensor_sha256"] == full_summary["best_tensor_sha256"]
    assert resumed["last_tensor_sha256"] == full_summary["last_tensor_sha256"]
    assert sha256_file(out / "weights.json") == sha256_file(baseline / "weights.json")
    assert read_json(out / "history.json") == history


def test_full_validation_mean_is_not_mean_of_batch_means():
    torch.manual_seed(8)
    model = PrismModel()
    samples = [dict(make_state(i, 2, i + 1), chosen=0, outcome=(i % 3) * 0.5) for i in range(5)]
    # Force the final state to be unlike the first batch.
    samples[-1]["actions"] *= 10
    measured = evaluate(model, samples, 2, torch.device("cpu"))
    ce_values, bce_values = [], []
    with torch.no_grad():
        for sample in samples:
            batch = collate([sample])
            logits, values = model.forward_batch(batch)
            ce, bce = loss_terms(logits, values, batch["chosen"], batch["outcomes"])
            ce_values.extend(ce.tolist())
            bce_values.extend(bce.tolist())
    expected = (sum(ce_values) + 0.5 * sum(bce_values)) / len(samples)
    assert measured["loss"] == pytest.approx(expected, abs=1e-6)
    assert measured["states"] == 5


def test_partial_accumulation_uses_actual_state_count():
    torch.manual_seed(10)
    model = PrismModel()
    reference = copy.deepcopy(model)
    samples = [dict(make_state(i, 2, 3), chosen=i % 3, outcome=(i % 3) * 0.5) for i in range(3)]
    settings = dict(FIXED, batch_size=2, accumulation_steps=2, seed=5)
    # SGD exposes a normalization error directly without Adam's near scale-invariance.
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
    reference_optimizer = torch.optim.SGD(reference.parameters(), lr=0.01)
    metrics = train_epoch(model, samples, optimizer, settings, torch.device("cpu"), 1)
    order = np.random.default_rng(6).permutation(3)
    batch = collate([samples[i] for i in order])
    logits, values = reference.forward_batch(batch)
    ce, bce = loss_terms(logits, values, batch["chosen"], batch["outcomes"])
    (ce + 0.5 * bce).mean().backward()
    torch.nn.utils.clip_grad_norm_(reference.parameters(), 1.0)
    reference_optimizer.step()
    assert metrics["states"] == 3 and metrics["optimizer_steps"] == 1
    for key, value in model.state_dict().items():
        torch.testing.assert_close(value, reference.state_dict()[key], atol=1e-7, rtol=1e-6)


def test_selection_earliest_tie_never_initialization():
    history = [{"epoch": i + 1, "val": {"loss": loss}} for i, loss in enumerate([2.0, 1.0, 1.0, 1.1])]
    assert select_best_epoch(history) == 2
    with pytest.raises(ValueError):
        select_best_epoch([])
    with pytest.raises(ValueError):
        select_best_epoch([{"epoch": 0, "val": {"loss": 0.0}}])


@pytest.mark.parametrize("key,value", [("epochs", 19), ("amp", True), ("tf32", True), ("lr", 1e-3),
                                       ("weight_decay", 0), ("value_weight", 0), ("cpu_threads", 8),
                                       ("scheduler", "cosine"), ("batch_size", 32), ("winner_only", True)])
def test_frozen_training_contract(key, value):
    config = {"training": {"data_dir": "unused", "out_dir": "unused", key: value}}
    with pytest.raises(ValueError):
        validate_config(config)


def test_approved_config_is_supported_without_training():
    config = read_json(Path(__file__).resolve().parents[3] / "benchmarks" / "m51-prism-v01.config.json")
    settings = validate_config(config)
    assert settings["epochs"] == 20 and settings["accumulation_steps"] == 2
