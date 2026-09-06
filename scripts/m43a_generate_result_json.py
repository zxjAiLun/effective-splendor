"""M43A: Generate tracked result artifact benchmarks/m43a-successor-state-value-decoupling-v1.result.json."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "training/m17_gpu"))

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m35a_registry import load_and_validate_checkpoint
from splendor_gpu.m43a_successor_model import build_m43a_model

SPLN = REPO / "target/release/splendor.exe"
CATALOG = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
D2_PATH = REPO / "local-artifacts/m25-recovery-exp-d2-v2/checkpoint.pt"
RUN_DIR = REPO / "local-artifacts/m43a-run"
DATA_DIR = REPO / "local-artifacts/m43a-successor-data"
RESULT_JSON = REPO / "benchmarks/m43a-successor-state-value-decoupling-v1.result.json"
RUN_CONTRACT_PATH = REPO / "local-artifacts/m41a-corpus/run-contract.json"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    catalog = load_catalog(CATALOG)
    cat_sem_hash = catalog_semantic_hash(catalog)

    d2_model, _ = load_and_validate_checkpoint(
        "M25-D2-v2", catalog_hash=cat_sem_hash, device=torch.device("cpu") if "torch" in sys.modules else "cpu"
    )
    _, init_audit = build_m43a_model(d2_model)

    train_manifest = json.loads((DATA_DIR / "train/successor_manifest.json").read_text(encoding="utf-8"))
    val_manifest = json.loads((DATA_DIR / "validation/successor_manifest.json").read_text(encoding="utf-8"))

    train_report = json.loads((RUN_DIR / "m43a-training-report.json").read_text(encoding="utf-8"))
    ckpt_file = RUN_DIR / "m43a-successor-value-best.pt"
    ckpt_sha = file_sha256(ckpt_file)
    training_report_sha = file_sha256(RUN_DIR / "m43a-training-report.json")

    p1_diag = train_report["best_diagnostics"]

    payload = {
        "format": "effective-splendor-m43a-successor-value-decoupling-result",
        "version": 1,
        "milestone": "M43A",
        "title": "Successor-State Value Decoupling Probe",
        "generated_at": time.time(),
        "design_baseline": "14108de",
        "repair_1_commit": "16bbc7f",
        "runs": {
            "run_1": {
                "status": "VOID",
                "reason": "Validation game-weighting distortion (batch means 32 vs 16), unmutated H3 test, and deterministic CUDA contract drift. Artifacts preserved.",
                "best_epoch": 4,
                "uncorrected_val_brier": 0.245868,
            },
            "run_2": {
                "status": "VALID",
                "validation_game_weighting": "Exact unweighted mean over all 48 individual validation game losses",
                "deterministic_cuda": "torch.use_deterministic_algorithms(True) + CUBLAS :4096:8",
                "epochs_trained": 32,
                "best_epoch": train_report["best_epoch"],
                "best_val_brier": train_report["best_val_brier"],
                "constant_brier": p1_diag["constant_brier"],
                "brier_skill_score": p1_diag["brier_skill_score"],
                "p1_gate_threshold": 0.05,
                "p1_gate_verdict": "FAIL",
                "checkpoint_file_sha256": ckpt_sha,
                "training_report_file_sha256": training_report_sha,
                "p1_diagnostics": p1_diag,
                "encoder_l2_delta": train_report["encoder_l2_delta"],
                "value_head_l2_delta": train_report["value_head_l2_delta"],
            }
        },
        "dataset": {
            "train": {
                "games_count": train_manifest["games_count"],
                "states_count": train_manifest["states_count"],
                "branches_count": train_manifest["branches_count"],
                "manifest_sha256": train_manifest["split_canonical_manifest_sha256"],
                "data_file_sha256": train_manifest["data_file_sha256"],
            },
            "validation": {
                "games_count": val_manifest["games_count"],
                "states_count": val_manifest["states_count"],
                "branches_count": val_manifest["branches_count"],
                "manifest_sha256": val_manifest["split_canonical_manifest_sha256"],
                "data_file_sha256": val_manifest["data_file_sha256"],
            }
        },
        "initialization_audit": init_audit,
        "provenance": {
            "m41_run_contract_sha256": file_sha256(RUN_CONTRACT_PATH),
            "catalog_file_sha256": file_sha256(CATALOG),
            "catalog_semantic_hash": cat_sem_hash,
            "d2_checkpoint_file_sha256": file_sha256(D2_PATH),
            "splendor_exe_sha256": file_sha256(SPLN),
            "source_shas": {
                "trainer": file_sha256(REPO / "training/m17_gpu/splendor_gpu/m43a_train.py"),
                "model": file_sha256(REPO / "training/m17_gpu/splendor_gpu/m43a_successor_model.py"),
                "dataset": file_sha256(REPO / "training/m17_gpu/splendor_gpu/m43a_successor_dataset.py"),
                "eval": file_sha256(REPO / "training/m17_gpu/splendor_gpu/m43a_eval.py"),
                "rust_command": file_sha256(REPO / "crates/splendor-cli/src/m43a_command.rs"),
                "p0_semantic_test": file_sha256(REPO / "crates/splendor-cli/tests/m43a_p0_semantic.rs"),
            },
            "training_contract": {
                "value_head_init_seed": 43_261_001,
                "trainer_seed": 43_261_002,
                "optimizer": "AdamW",
                "lr": 1e-4,
                "weight_decay": 1e-4,
                "betas": [0.9, 0.999],
                "eps": 1e-8,
                "amsgrad": False,
                "foreach": False,
                "fused": False,
                "gradient_clip": 1.0,
                "batch_games": 32,
                "epochs": 32,
            }
        },
        "gates_and_decisions": {
            "p1_bss_pass": False,
            "p2_run_2": "NOT RUN (frozen gate BSS < 0.05 triggered STOP)",
            "p3_arena": "NOT RUN (frozen gate BSS < 0.05 triggered STOP)",
            "formal_verdict": "M43A_SUCCESSOR_VALUE_NOT_LEARNED",
        }
    }

    RESULT_JSON.parent.mkdir(parents=True, exist_ok=True)
    RESULT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Generated tracked result artifact at {RESULT_JSON}.", flush=True)


if __name__ == "__main__":
    import torch
    main()
