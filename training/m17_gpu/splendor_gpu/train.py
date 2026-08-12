"""Supervised GPU warm start for both M17 architectures."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import time
import copy
from pathlib import Path
from typing import Any

# CUDA 10.2+ requires this process-level workspace contract before torch first
# initializes cuBLAS when deterministic algorithms are enabled.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import torch
from torch import nn
from torch.utils.data import DataLoader

from .data import SplendorDataset, canonical_json, catalog_semantic_hash, collate, dataset_hash, load_catalog, split_examples
from .model import ModelSpec, build_model

CONFIG_FORMAT = "effective-splendor-gpu-training-config"
CHECKPOINT_FORMAT = "effective-splendor-gpu-checkpoint"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def checkpoint_semantic_hash(metadata: dict[str, Any], state_dict: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256(b"effective-splendor-gpu-checkpoint-v1\0")
    digest.update(canonical_json(metadata))
    for name in sorted(state_dict):
        tensor = state_dict[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(str(tensor.dtype).encode("ascii") + b"\0")
        digest.update(canonical_json(list(tensor.shape)))
        digest.update(tensor.view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


def validate_config(config: dict[str, Any], dataset: dict[str, Any]) -> None:
    if config.get("format") != CONFIG_FORMAT or config.get("version") != 1:
        raise ValueError("unsupported M17 training config")
    bindings = {
        "expected_dataset_id": "dataset_id",
        "expected_league_manifest_hash": "league_manifest_hash",
        "expected_evaluation_plan_hash": "evaluation_plan_hash",
        "expected_evaluation_report_hash": "evaluation_report_hash",
    }
    for expected, actual in bindings.items():
        if config[expected] != dataset[actual]:
            raise ValueError(f"config {expected} does not match dataset {actual}")
    if config["expected_dataset_hash"] != dataset_hash(dataset):
        raise ValueError("config expected_dataset_hash does not match canonical dataset")
    if not config.get("models"):
        raise ValueError("at least one M17 model is required")


def resolve_device(name: str) -> torch.device:
    if name == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("config requires CUDA, but torch.cuda.is_available() is false")
    if name not in {"cpu", "cuda"}:
        raise ValueError("device must be cpu or cuda")
    return torch.device(name)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False


def move(batch: dict[str, torch.Tensor], device: torch.device) -> dict[str, torch.Tensor]:
    return {key: value.to(device, non_blocking=device.type == "cuda") for key, value in batch.items()}


@torch.no_grad()
def evaluate(model: nn.Module, loader: DataLoader, device: torch.device) -> dict[str, float | int]:
    model.eval()
    policy_loss = value_loss = correct = examples = 0.0
    uniform_nll = 0.0
    for raw in loader:
        batch = move(raw, device)
        logits, values = model(batch["entities"], batch["entity_mask"], batch["global_features"], batch["actions"], batch["action_mask"])
        count = batch["chosen"].shape[0]
        policy_loss += nn.functional.cross_entropy(logits, batch["chosen"], reduction="sum").item()
        value_loss += nn.functional.mse_loss(values, batch["value_target"], reduction="sum").item()
        correct += logits.argmax(dim=-1).eq(batch["chosen"]).sum().item()
        uniform_nll += batch["action_mask"].sum(dim=-1).float().log().sum().item()
        examples += count
    return {"examples": int(examples), "policy_top1": correct / examples, "policy_nll": policy_loss / examples, "uniform_policy_nll": uniform_nll / examples, "value_mse": value_loss / (examples * 2.0)}


def train_one(spec: ModelSpec, train_set: SplendorDataset, validation_set: SplendorDataset, config: dict[str, Any], out_dir: Path, catalog_source: Path) -> dict[str, Any]:
    device = resolve_device(config["device"])
    seed_everything(int(config["seed"]))
    model = build_model(spec).to(device)
    generator = torch.Generator().manual_seed(int(config["seed"]))
    train_loader = DataLoader(train_set, batch_size=int(config["batch_size"]), shuffle=True, generator=generator, num_workers=0, collate_fn=collate, pin_memory=device.type == "cuda")
    validation_loader = DataLoader(validation_set, batch_size=int(config["batch_size"]), shuffle=False, num_workers=0, collate_fn=collate, pin_memory=device.type == "cuda")
    train_value_targets = torch.stack([train_set[index].value_target for index in range(len(train_set))])
    validation_value_targets = torch.stack([validation_set[index].value_target for index in range(len(validation_set))])
    train_value_prior = train_value_targets.mean(dim=0)
    value_prior_mse = nn.functional.mse_loss(
        train_value_prior.expand_as(validation_value_targets), validation_value_targets
    ).item()
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(config["learning_rate"]), weight_decay=float(config["weight_decay"]))
    start = time.perf_counter()
    history = []
    best_score = math.inf
    best_epoch = 0
    best_state = None
    for epoch in range(int(config["epochs"])):
        model.train()
        sum_loss = 0.0
        seen = 0
        for raw in train_loader:
            batch = move(raw, device)
            optimizer.zero_grad(set_to_none=True)
            logits, values = model(batch["entities"], batch["entity_mask"], batch["global_features"], batch["actions"], batch["action_mask"])
            policy = nn.functional.cross_entropy(logits, batch["chosen"])
            value = nn.functional.mse_loss(values, batch["value_target"])
            loss = policy + float(config["value_loss_weight"]) * value
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), float(config["gradient_clip_norm"]))
            optimizer.step()
            sum_loss += loss.item() * batch["chosen"].shape[0]
            seen += batch["chosen"].shape[0]
        validation = evaluate(model, validation_loader, device)
        selection_score = float(validation["policy_nll"]) + float(config["value_loss_weight"]) * float(validation["value_mse"])
        history.append({"epoch": epoch + 1, "mean_loss": sum_loss / seen, "validation": validation, "selection_score": selection_score})
        if selection_score < best_score:
            best_score = selection_score
            best_epoch = epoch + 1
            best_state = copy.deepcopy({key: value.detach().cpu() for key, value in model.state_dict().items()})

    if best_state is None:
        raise RuntimeError("training produced no checkpoint candidate")
    model.load_state_dict(best_state, strict=True)
    metrics = evaluate(model, validation_loader, device)
    architecture_dir = out_dir / spec.architecture
    architecture_dir.mkdir(parents=True, exist_ok=False)
    checkpoint_path = architecture_dir / "checkpoint.pt"
    metadata = {
        "format": CHECKPOINT_FORMAT, "version": 1,
        "model_id": f"m17-{spec.architecture}-v1",
        **model.checkpoint_metadata(),
        "source_dataset_id": config["expected_dataset_id"],
        "source_dataset_hash": config["expected_dataset_hash"],
        "league_manifest_hash": config["expected_league_manifest_hash"],
        "evaluation_plan_hash": config["expected_evaluation_plan_hash"],
        "evaluation_report_hash": config["expected_evaluation_report_hash"],
        "training_config_hash": hashlib.sha256(b"effective-splendor-gpu-training-config-v1\0" + canonical_json(config)).hexdigest(),
        "catalog_hash": catalog_semantic_hash(train_set.catalog),
        "train_examples": len(train_set), "validation_examples": len(validation_set),
        "validation_seed_modulus": config["validation_seed_modulus"], "validation_seed_remainder": config["validation_seed_remainder"],
    }
    checkpoint_hash = checkpoint_semantic_hash(metadata, best_state)
    torch.save({"metadata": metadata, "state_dict": best_state}, checkpoint_path)
    checkpoint_file_sha256 = file_sha256(checkpoint_path)
    report = {"format": "effective-splendor-gpu-training-report", "version": 1, "training_id": config["training_id"], "model_id": metadata["model_id"], "device": str(device), "torch_version": torch.__version__, "cuda_version": torch.version.cuda, "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None, "elapsed_seconds": time.perf_counter() - start, "parameter_count": sum(p.numel() for p in model.parameters()), "selection": {"metric": "policy_nll + value_loss_weight * value_mse", "best_epoch": best_epoch, "best_score": best_score}, "baselines": {"uniform_policy_nll": metrics["uniform_policy_nll"], "train_prior_value": train_value_prior.tolist(), "train_prior_value_mse": value_prior_mse}, "checkpoint_hash": checkpoint_hash, "checkpoint_file_sha256": checkpoint_file_sha256, "validation": metrics, "history": history}
    (architecture_dir / "training-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    agent_entry = (Path(__file__).resolve().parents[1] / "agent_entry.py").resolve()
    registry = {"id": f"m17-{spec.architecture}-v1", "display_name": f"M17 {spec.architecture}", "class": "checkpoint", "policy_version": f"gpu-policy-value-{spec.architecture}-v1", "model_version": metadata["model_id"], "checkpoint_hash": checkpoint_hash, "runtime_name": "effective-splendor-gpu-agent-v1", "runtime_version": "1", "command": {"program": "python", "args": [str(agent_entry), "--checkpoint", str(checkpoint_path.resolve()), "--checkpoint-hash", checkpoint_hash, "--catalog", str(catalog_source.resolve()), "--device", "cpu"]}}
    (architecture_dir / "rating-registry-agent.json").write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("../../apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"))
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    validate_config(config, dataset)
    catalog = load_catalog(args.catalog)
    train_examples, validation_examples = split_examples(dataset, set(config["policy_teacher_agent_ids"]), int(config["validation_seed_modulus"]), int(config["validation_seed_remainder"]))
    args.out_dir.mkdir(parents=True, exist_ok=False)
    reports = []
    for raw_spec in config["models"]:
        reports.append(train_one(ModelSpec(**raw_spec), SplendorDataset(train_examples, catalog), SplendorDataset(validation_examples, catalog), config, args.out_dir, args.catalog))
    summary = {"format": "effective-splendor-gpu-training-summary", "version": 1, "training_id": config["training_id"], "dataset_hash": dataset_hash(dataset), "models": reports}
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir), "models": [{"model_id": r["model_id"], "validation": r["validation"]} for r in reports]}))


if __name__ == "__main__": main()
