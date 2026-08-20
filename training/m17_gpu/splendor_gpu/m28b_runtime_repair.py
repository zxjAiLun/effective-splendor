"""M28B Runtime Repair 1 cache/equality/thermal diagnostic.

This command is intentionally not a trainer.  It builds or loads the local
encoded cache, checks every example against the original online encoder, and
runs only a small inference smoke on both frozen model variants.  It writes no
checkpoint, training report, offline result, Arena plan, or replay.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import torch

from .data import catalog_semantic_hash, load_catalog
from .encoded_cache import EncodedCache, PackedEncodedDataset, build_encoded_cache, validate_cache_exact
from .interaction_train import (
    EXPECTED_CATALOG_HASH,
    EXPECTED_MODELS,
    _loader,
    build_fresh_model,
    validate_config,
    validate_dataset,
)
from .runtime import configure_cpu_runtime, cpu_utilization_percent, runtime_snapshot, write_json
from .train import resolve_device


def _move(batch: dict[str, torch.Tensor], device: torch.device) -> dict[str, torch.Tensor]:
    return {key: value.to(device, non_blocking=device.type == "cuda") for key, value in batch.items()}


def _model_smoke(
    cache: EncodedCache,
    config: dict[str, Any],
    device: torch.device,
    batches: int,
) -> list[dict[str, Any]]:
    training = config["training"]
    batch_size = int(training["batch_size"])
    sample_count = min(cache.examples, batch_size * batches)
    dataset = PackedEncodedDataset(cache, range(sample_count))
    loader = _loader(dataset, batch_size, False, None, device)
    records: list[dict[str, Any]] = []
    for model_contract in EXPECTED_MODELS:
        model = build_fresh_model(model_contract, int(training["initialization_seed"])).to(device).eval()
        torch.cuda.reset_peak_memory_stats(device)
        started = time.perf_counter()
        batch_count = 0
        example_count = 0
        with torch.inference_mode():
            for raw in loader:
                batch = _move(raw, device)
                logits, values = model(
                    batch["entities"],
                    batch["entity_mask"],
                    batch["global_features"],
                    batch["actions"],
                    batch["action_mask"],
                )
                if not torch.isfinite(logits).all() or not torch.isfinite(values).all():
                    raise RuntimeError(f"non-finite Runtime Repair 1 smoke output for {model_contract['role']}")
                batch_count += 1
                example_count += int(logits.shape[0])
                if batch_count >= batches:
                    break
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        records.append(
            {
                "role": model_contract["role"],
                "model_id": model_contract["model_id"],
                "batches": batch_count,
                "examples": example_count,
                "elapsed_seconds": time.perf_counter() - started,
                "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
                "torch_cuda_peak": {
                    "max_allocated_bytes": torch.cuda.max_memory_allocated(device),
                    "max_reserved_bytes": torch.cuda.max_memory_reserved(device),
                },
            }
        )
        del model
        torch.cuda.empty_cache()
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="M28B Runtime Repair 1 diagnostic only")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"))
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--batches", type=int, default=4)
    args = parser.parse_args()
    if args.batches < 1:
        raise ValueError("--batches must be positive")

    started = time.perf_counter()
    cpu_runtime = configure_cpu_runtime()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    validate_config(config)
    payload, self_play_hash_value, dataset_file_sha256 = validate_dataset(args.dataset, config)
    catalog = load_catalog(args.catalog)
    catalog_hash = catalog_semantic_hash(catalog)
    if catalog_hash != EXPECTED_CATALOG_HASH:
        raise ValueError("catalog semantic hash mismatch")

    before_cache = runtime_snapshot()
    build_elapsed: float | None = None
    if args.cache_dir.exists():
        cache = EncodedCache.load(args.cache_dir)
        cache_origin = "existing_valid_cache"
    else:
        build_started = time.perf_counter()
        build_encoded_cache(
            payload["examples"],
            catalog,
            args.cache_dir,
            dataset_file_sha256=dataset_file_sha256,
            self_play_hash=self_play_hash_value,
            catalog_hash=catalog_hash,
        )
        cache = EncodedCache.load(args.cache_dir)
        cache_origin = "built_once"
        build_elapsed = time.perf_counter() - build_started
    cache.validate_identity(
        dataset_file_sha256=dataset_file_sha256,
        self_play_hash=self_play_hash_value,
        catalog_hash=catalog_hash,
        examples=len(payload["examples"]),
    )
    exact_started = time.perf_counter()
    exact_count = validate_cache_exact(cache, payload["examples"], catalog, progress_every=5000)
    exact_elapsed = time.perf_counter() - exact_started
    after_exact = runtime_snapshot()

    device = resolve_device("cuda")
    before_smoke = runtime_snapshot(device)
    smoke_started = time.perf_counter()
    smoke = _model_smoke(cache, config, device, args.batches)
    after_smoke = runtime_snapshot(device)
    smoke_elapsed = time.perf_counter() - smoke_started
    report = {
        "format": "effective-splendor-m28b-runtime-repair-1-diagnostic",
        "version": 1,
        "milestone": "M28B",
        "runtime_repair": "m28b_runtime_repair_1",
        "scientific_evidence": False,
        "formal_training": False,
        "arena_authorization": "NOT_AUTHORIZED",
        "promotion": "NONE",
        "source": {
            "dataset_file_sha256": dataset_file_sha256,
            "self_play_hash": self_play_hash_value,
            "catalog_semantic_hash": catalog_hash,
            "examples": len(payload["examples"]),
        },
        "cache": {
            "path": str(args.cache_dir),
            "origin": cache_origin,
            "manifest_sha256": cache.manifest_sha256,
            "examples": cache.examples,
            "total_actions": cache.total_actions,
        },
        "cpu_runtime": cpu_runtime,
        "cache_build_elapsed_seconds": build_elapsed,
        "exact_online_cache_equality": {
            "passed": exact_count == len(payload["examples"]),
            "examples_checked": exact_count,
            "elapsed_seconds": exact_elapsed,
        },
        "model_smoke": {
            "batches_requested_per_model": args.batches,
            "elapsed_seconds": smoke_elapsed,
            "records": smoke,
        },
        "telemetry": {
            "before_cache": before_cache,
            "after_exact": after_exact,
            "before_smoke": before_smoke,
            "after_smoke": after_smoke,
            "cpu_utilization_exact_percent": cpu_utilization_percent(
                before_cache.get("cpu_counters", {}), after_exact.get("cpu_counters", {})
            ),
            "cpu_utilization_smoke_percent": cpu_utilization_percent(
                before_smoke.get("cpu_counters", {}), after_smoke.get("cpu_counters", {})
            ),
        },
        "elapsed_seconds": time.perf_counter() - started,
        "no_checkpoint_or_result_written": True,
    }
    write_json(args.report, report)
    print(json.dumps({"report": str(args.report), "cache_manifest_sha256": cache.manifest_sha256}))


if __name__ == "__main__":
    main()
