"""One frozen from-scratch Prism run, with exact epoch-boundary resume."""

import argparse
import math
import os
import platform
import random
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from .data import PrismDataset, collate_states
from .export import load_checkpoint_model, export_weights
from .io import read_json, save_checkpoint, sha256_file, tensor_identity, write_json
from .model import ACTION_DIM, ACTION_SCHEMA, ENTITY_DIM, HIDDEN_DIM, NUM_BLOCKS, OBS_SCHEMA, PrismModel

FIXED = {"epochs": 20, "batch_size": 64, "accumulation_steps": 2, "lr": 0.0003,
         "weight_decay": 0.0001, "value_weight": 0.5, "gradient_clip": 1.0,
         "dtype": "float32", "amp": False, "tf32": False, "cpu_threads": 2, "scheduler": "none"}
SELECTION = "minimum full validation CE+0.5*BCE epochs1..20, earliest exact tie"


def validate_config(config):
    if not isinstance(config, dict) or not isinstance(config.get("training"), dict):
        raise ValueError("missing training config")
    settings = dict(FIXED, seed=51000001, device="cuda")
    supplied = config["training"]
    allowed = set(settings) | {"data_dir", "out_dir", "checkpoint_selection", "initialization"}
    if set(supplied) - allowed:
        raise ValueError(f"unknown training options: {sorted(set(supplied) - allowed)}")
    settings.update(supplied)
    for key, value in FIXED.items():
        if settings[key] != value or isinstance(settings[key], bool) != isinstance(value, bool):
            raise ValueError(f"Prism v0.1 requires {key}={value!r}")
        if type(value) is int and type(settings[key]) is not int:
            raise ValueError(f"{key} requires an integer")
    if type(settings["seed"]) is not int or not 0 <= settings["seed"] < 2**32:
        raise ValueError("seed must be a uint32")
    for key in ("data_dir", "out_dir"):
        if not isinstance(settings.get(key), str) or not settings[key]:
            raise ValueError(f"{key} is required")
    if settings.get("checkpoint_selection", SELECTION) != SELECTION:
        raise ValueError("unsupported checkpoint selection")
    if settings.get("initialization", "from scratch; no Aran weights") != "from scratch; no Aran weights":
        raise ValueError("only from-scratch initialization is permitted")
    expected_model = {"entity_dim": ENTITY_DIM, "action_dim": ACTION_DIM, "hidden_dim": HIDDEN_DIM,
                      "num_blocks": NUM_BLOCKS, "observation_schema": OBS_SCHEMA,
                      "action_schema": ACTION_SCHEMA, "action_attention_layers": 1}
    model = config.get("model", {})
    for key, value in expected_model.items():
        if key in model and model[key] != value:
            raise ValueError(f"model {key} mismatch")
    return settings


def configure_runtime(settings, device_override=None):
    device = torch.device(device_override or settings["device"])
    if device.type not in ("cpu", "cuda"):
        raise ValueError("only CPU/CUDA are supported")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("configured CUDA is unavailable; no silent CPU fallback")
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    if os.environ["CUBLAS_WORKSPACE_CONFIG"] not in (":4096:8", ":16:8"):
        raise ValueError("non-deterministic CUBLAS_WORKSPACE_CONFIG")
    torch.set_num_threads(settings["cpu_threads"])
    torch.use_deterministic_algorithms(True)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    runtime = {"device": str(device), "device_override": device_override,
               "torch": str(torch.__version__), "numpy": np.__version__, "python": platform.python_version(),
               "cpu_threads": torch.get_num_threads(), "dtype": "float32", "amp": False, "tf32": False,
               "deterministic_algorithms": True, "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"]}
    if device.type == "cuda":
        runtime["cuda"] = torch.version.cuda
        runtime["gpu"] = torch.cuda.get_device_name(device)
        runtime["capability"] = list(torch.cuda.get_device_capability(device))
    return device, runtime


def _seed(seed, device):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)


def _rng_state(device):
    return {"python": random.getstate(), "numpy": np.random.get_state(),
            "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all() if device.type == "cuda" else []}


def _restore_rng(state, device):
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch"])
    if device.type == "cuda":
        torch.cuda.set_rng_state_all(state["cuda"])


def loss_terms(logits, value_logits, chosen, outcomes):
    """Per-state CE and outcome BCE. No winner mask, detach or smoothing."""
    ce = F.cross_entropy(logits, chosen, reduction="none")
    bce = F.binary_cross_entropy_with_logits(value_logits, outcomes, reduction="none")
    if not torch.isfinite(ce).all() or not torch.isfinite(bce).all():
        raise ValueError("nonfinite loss")
    return ce, bce


def _batch(dataset, indices, device):
    batch = collate_states([dataset[int(index)] for index in indices])
    return {key: tensor.to(device) for key, tensor in batch.items()}


def _metrics(ce, bce, correct, states, steps=0):
    result = {"states": states, "ce": ce / states, "bce": bce / states,
              "loss": (ce + 0.5 * bce) / states, "accuracy": correct / states,
              "optimizer_steps": steps}
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError("nonfinite epoch metrics")
    return result


def train_epoch(model, dataset, optimizer, settings, device, epoch):
    model.train()
    # Only the O(states) integer permutation is materialized, never features/actions.
    order = np.random.default_rng(settings["seed"] + epoch).permutation(len(dataset))
    batch_size = settings["batch_size"]
    group_size = batch_size * settings["accumulation_steps"]
    ce_total = bce_total = 0.0
    correct = steps = 0
    for group_start in range(0, len(order), group_size):
        group = order[group_start:group_start + group_size]
        optimizer.zero_grad(set_to_none=True)
        for start in range(0, len(group), batch_size):
            batch = _batch(dataset, group[start:start + batch_size], device)
            with torch.autocast(device_type=device.type, enabled=False):
                logits, values = model.forward_batch(batch)
                ce, bce = loss_terms(logits, values, batch["chosen"], batch["outcomes"])
                # A partial final accumulation group uses its actual state count.
                loss = (ce + settings["value_weight"] * bce).sum() / len(group)
            loss.backward()
            ce_total += ce.detach().double().sum().item()
            bce_total += bce.detach().double().sum().item()
            correct += (logits.detach().argmax(1) == batch["chosen"]).sum().item()
        torch.nn.utils.clip_grad_norm_(model.parameters(), settings["gradient_clip"], error_if_nonfinite=True)
        optimizer.step()
        steps += 1
    optimizer.zero_grad(set_to_none=True)
    return _metrics(ce_total, bce_total, correct, len(dataset), steps)


def evaluate(model, dataset, batch_size, device):
    model.eval()
    ce_total = bce_total = 0.0
    correct = 0
    with torch.inference_mode(), torch.autocast(device_type=device.type, enabled=False):
        for start in range(0, len(dataset), batch_size):
            batch = _batch(dataset, range(start, min(start + batch_size, len(dataset))), device)
            logits, values = model.forward_batch(batch)
            ce, bce = loss_terms(logits, values, batch["chosen"], batch["outcomes"])
            ce_total += ce.double().sum().item()
            bce_total += bce.double().sum().item()
            correct += (logits.argmax(1) == batch["chosen"]).sum().item()
    return _metrics(ce_total, bce_total, correct, len(dataset))


def select_best_epoch(history):
    if not history:
        raise ValueError("cannot select initialization or empty history")
    if [row["epoch"] for row in history] != list(range(1, len(history) + 1)):
        raise ValueError("history must contain every epoch starting at 1")
    if len(history) > 20 or any(not math.isfinite(row["val"]["loss"]) for row in history):
        raise ValueError("invalid selection history")
    # Python min is stable: an exact loss tie retains the earliest epoch.
    return min(history, key=lambda row: row["val"]["loss"])["epoch"]


def _cpu_state(model):
    return {key: tensor.detach().cpu().clone() for key, tensor in model.state_dict().items()}


def _publish(out, checkpoint, identity, init_sha, complete):
    """Derived artifacts can be rebuilt from the atomic last checkpoint after a crash."""
    best_state = checkpoint["best_state_dict"]
    best = dict(identity, format="prism-checkpoint-v1", epoch=checkpoint["best_epoch"],
                state_dict=best_state, tensor_sha256=tensor_identity(best_state),
                validation_loss=checkpoint["best_val_loss"], init_sha256=init_sha)
    save_checkpoint(out / "best_model.pt", best)
    write_json(out / "history.json", checkpoint["history"])
    manifest = export_weights(best_state, out / "weights.json", identity["catalog_fingerprint"], provenance={
        "config_sha256": identity["config_sha256"], "dataset_sha256": identity["dataset_sha256"],
        "checkpoint_sha256": sha256_file(out / "best_model.pt"), "epoch": best["epoch"],
    })
    changed = best["tensor_sha256"] != checkpoint["init_tensor_sha256"]
    if complete and not changed:
        raise ValueError("selected best model is identical to initialization")
    files = ("init.pt", "checkpoint-last.pt", "best_model.pt", "weights.json", "weights.manifest.json",
             "history.json", "run-manifest.json", "config.json")
    summary = dict(identity, format="prism-training-summary-v1", status="COMPLETE" if complete else "INTERRUPTED",
                   completed_epochs=checkpoint["epoch"], planned_epochs=20, best_epoch=best["epoch"],
                   best_val_loss=checkpoint["best_val_loss"], checkpoint_selection=SELECTION,
                   init_tensor_sha256=checkpoint["init_tensor_sha256"], best_tensor_sha256=manifest["tensor_sha256"],
                   last_tensor_sha256=checkpoint["tensor_sha256"], best_differs_from_init=changed,
                   hashes={name: sha256_file(out / name) for name in files})
    write_json(out / "training-summary.json", summary)
    write_json(out / "artifact-manifest.json", dict(identity, format="prism-artifact-manifest-v1",
               hashes=dict(summary["hashes"], **{"training-summary.json": sha256_file(out / "training-summary.json")})))
    return summary


def run_training(config_path, *, resume=False, device=None, stop_after_epoch=None):
    """stop_after_epoch simulates an epoch-boundary interruption; it never changes config."""
    config_path = Path(config_path)
    config = read_json(config_path)
    settings = validate_config(config)
    target_device, runtime = configure_runtime(settings, device)
    epochs = settings["epochs"]
    if stop_after_epoch is not None and (type(stop_after_epoch) is not int or not 1 <= stop_after_epoch <= epochs):
        raise ValueError("invalid stop_after_epoch")
    out = Path(settings["out_dir"])
    if not resume and out.exists() and any(out.iterdir()):
        raise ValueError("output directory is not empty; use same-config --resume")
    with PrismDataset(settings["data_dir"], "train") as train, PrismDataset(settings["data_dir"], "val") as val:
        if train.dataset_sha256 != val.dataset_sha256:
            raise ValueError("dataset changed during validation")
        dataset_config = config.get("dataset", {})
        for split, dataset in (("train", train), ("val", val)):
            if f"{split}_games" in dataset_config and dataset.meta["games"] != dataset_config[f"{split}_games"]:
                raise ValueError("dataset game count differs from config")
        if "val_modulus" in dataset_config:
            modulus = dataset_config["val_modulus"]
            remainder = dataset_config["val_remainder"]
            if type(modulus) is not int or modulus <= 0 or type(remainder) is not int or not 0 <= remainder < modulus:
                raise ValueError("invalid seed split config")
            for source in train.manifest["sources"]:
                expected = "val" if source["seed"] % modulus == remainder else "train"
                if source["split"] != expected:
                    raise ValueError("source seed violates configured split")
        identity = {"config_sha256": sha256_file(config_path), "dataset_sha256": train.dataset_sha256,
                    "dataset_manifest_sha256": train.manifest_sha256,
                    "catalog_fingerprint": train.manifest["catalog_fingerprint"], "runtime": runtime}
        _seed(settings["seed"], target_device)
        model = PrismModel().float().to(target_device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=settings["lr"], weight_decay=settings["weight_decay"],
                                      betas=(0.9, 0.999), eps=1e-8, foreach=False, fused=False)
        if resume:
            run_manifest = read_json(out / "run-manifest.json")
            for key, value in identity.items():
                if run_manifest.get(key) != value:
                    raise ValueError(f"resume {key} mismatch")
            init_sha = sha256_file(out / "init.pt")
            if init_sha != run_manifest["init_sha256"]:
                raise ValueError("resume initialization checkpoint mismatch")
            _, checkpoint = load_checkpoint_model(out / "checkpoint-last.pt",
                                                  expected_catalog_fingerprint=identity["catalog_fingerprint"])
            for key, value in identity.items():
                if checkpoint.get(key) != value:
                    raise ValueError(f"resume checkpoint {key} mismatch")
            if checkpoint.get("init_sha256") != init_sha:
                raise ValueError("resume init identity mismatch")
            history = checkpoint["history"]
            if checkpoint["epoch"] != len(history) or not 1 <= checkpoint["epoch"] <= epochs:
                raise ValueError("invalid resume epoch/history")
            if checkpoint["best_epoch"] != select_best_epoch(history):
                raise ValueError("invalid resume selection")
            if checkpoint["best_val_loss"] != history[checkpoint["best_epoch"] - 1]["val"]["loss"]:
                raise ValueError("invalid resume best loss")
            if tensor_identity(checkpoint["best_state_dict"]) != checkpoint["best_tensor_sha256"]:
                raise ValueError("invalid resume best tensor identity")
            model.load_state_dict(checkpoint["state_dict"], strict=True)
            optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
            _restore_rng(checkpoint["rng_state"], target_device)
            start_epoch = checkpoint["epoch"] + 1
        else:
            out.mkdir(parents=True, exist_ok=True)
            state = _cpu_state(model)
            init_tensor_sha = tensor_identity(state)
            save_checkpoint(out / "init.pt", dict(identity, format="prism-checkpoint-v1", epoch=0,
                            state_dict=state, tensor_sha256=init_tensor_sha, rng_state=_rng_state(target_device)))
            init_sha = sha256_file(out / "init.pt")
            write_json(out / "config.json", config)
            write_json(out / "run-manifest.json", dict(identity, format="prism-run-manifest-v1", config=config,
                       effective_training=settings, init_sha256=init_sha, init_tensor_sha256=init_tensor_sha,
                       splits=train.manifest["splits"], checkpoint_selection=SELECTION))
            checkpoint = dict(identity, format="prism-checkpoint-v1", epoch=0, init_sha256=init_sha,
                              init_tensor_sha256=init_tensor_sha, history=[], best_epoch=None,
                              best_val_loss=None, best_state_dict=None)
            history = checkpoint["history"]
            start_epoch = 1
        end_epoch = stop_after_epoch or epochs
        if end_epoch < start_epoch - 1:
            raise ValueError("stop epoch precedes resumed checkpoint")
        for epoch in range(start_epoch, end_epoch + 1):
            train_metrics = train_epoch(model, train, optimizer, settings, target_device, epoch)
            val_metrics = evaluate(model, val, settings["batch_size"], target_device)
            history.append({"epoch": epoch, "train": train_metrics, "val": val_metrics})
            state = _cpu_state(model)
            if checkpoint["best_val_loss"] is None or val_metrics["loss"] < checkpoint["best_val_loss"]:
                checkpoint.update(best_epoch=epoch, best_val_loss=val_metrics["loss"], best_state_dict=state,
                                  best_tensor_sha256=tensor_identity(state))
            checkpoint.update(epoch=epoch, state_dict=state, tensor_sha256=tensor_identity(state),
                              optimizer_state_dict=optimizer.state_dict(), rng_state=_rng_state(target_device), history=history)
            # The last checkpoint is the commit point, including best tensors/history.
            save_checkpoint(out / "checkpoint-last.pt", checkpoint)
            write_json(out / "history.json", history)
            print(f"epoch {epoch:02d}/20 train={train_metrics['loss']:.8f} val={val_metrics['loss']:.8f} "
                  f"best={checkpoint['best_epoch']}", flush=True)
        return _publish(out, checkpoint, identity, init_sha, checkpoint["epoch"] == epochs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--resume", action="store_true", help="resume checkpoint-last.pt, same config/data/runtime only")
    parser.add_argument("--device", help="engineering tiny-test override only; never silently falls back")
    args = parser.parse_args(argv)
    result = run_training(args.config, resume=args.resume, device=args.device)
    print(f"{result['status']}: best epoch {result['best_epoch']}")


if __name__ == "__main__":
    main()
