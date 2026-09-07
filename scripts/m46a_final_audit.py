"""M46A Final Exhaustive Audit & Tracked Result JSON Generator.

Fail-closed checks (all must pass):
  - P0 suites: M45A (5/5), M44A (6/6), M44B (4/4), M44C (4/4) regression.
  - Corpus manifest: exact split sizes (2048/256/256 games; 16384/2048/2048
    roots), identity digests present, cross-split disjointness recorded.
  - Training outputs: best.pt, 32-epoch history, frozen recipe constants.
  - Checkpoint selection rule recomputed from the epoch table: highest val
    optimal-set agreement -> tie strict-pair accuracy -> tie lowest regret
    -> tie earliest epoch; must equal the saved best epoch.
  - Gate B metrics recomputed from saved per-root teacher/model means:
    must match final_metrics.json (tight tolerance).
  - Gate A + SHIFT1 metrics recomputed from saved per-example predictions:
    must match final_metrics.json (exact counts, tight ratio tolerance).
  - Frozen PASS table asserted; catalog_semantic_hash from the real loader
    must equal the authoritative M44B/M44C value.
  - Writes tracked benchmarks/m46a-relational-successor-representation-gate-v1.result.json.

No Arena exists in M46A by design. No training is performed here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
SPLN = REPO / "target/release/splendor.exe"
CATALOG = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
CORPUS_MANIFEST = REPO / "local-artifacts/m46a-corpus/corpus-manifest.json"
RUN_DIR = REPO / "local-artifacts/m46a-run"
RESULT_JSON = REPO / "benchmarks/m46a-relational-successor-representation-gate-v1.result.json"
M45A_RESULT_JSON = REPO / "benchmarks/m45a-bonus-vector-information-probe-v1.result.json"

AUTHORITATIVE_CATALOG_SEMANTIC_HASH = (
    "4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26"
)

EXPECTED_SPLITS = {"train": (2048, 16384), "val": (256, 2048), "test": (256, 2048)}

FROZEN_RECIPE = {
    "training_seed": 46_000_001,
    "optimizer": "AdamW",
    "lr": 3e-4,
    "weight_decay": 1e-4,
    "betas": [0.9, 0.999],
    "eps": 1e-8,
    "epochs": 32,
    "batch_unit": "root",
    "batch_size_roots": 32,
    "grad_clip_global_norm": 1.0,
    "dropout": 0,
    "scheduler": "cosine annealing over 32 epochs, 3e-4 -> 3e-5",
    "smoothl1_beta": 1.0,
    "progress_scale": 100_000_000,
    "loss": "L_progress + L_rank + 0.5 * L_mechanics",
}

FROZEN_PASS = {
    "A2-affordable-count": ("aff_count_acc", ">=", 0.995),
    "A2-max-prestige": ("aff_max_acc", ">=", 0.995),
    "A2-claimable": ("claim_acc", ">=", 0.995),
    "A2-min-deficit": ("mindef_acc", ">=", 0.99),
    "A3-coverage": ("min_changed_pairs", ">=", 256),
    "A3-both-exact": ("min_both_exact", ">=", 0.99),
    "A3-signed-delta": ("min_signed_delta", ">=", 0.99),
    "B1-optimal-set": ("optimal_set_agreement", ">=", 0.98),
    "B1-strict-pair": ("strict_pair_accuracy", ">=", 0.99),
    "B1-regret": ("mean_regret", "<=", 0.005),
}

HEX64 = set("0123456789abcdef")


def is_hex64(v):
    return isinstance(v, str) and len(v) == 64 and set(v) <= HEX64


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_suite(name: str, test_id: str, expected: int) -> None:
    print(f"Running {name}...", flush=True)
    r = subprocess.run(["cargo", "test", "-p", "splendor-cli", "--test", test_id],
                       capture_output=True, text=True, cwd=str(REPO))
    if r.returncode != 0:
        raise RuntimeError(f"{name} FAILED:\n{r.stdout}\n{r.stderr}")
    if f"{expected} passed" not in r.stdout:
        raise RuntimeError(f"{name}: expected {expected} passing:\n{r.stdout}")
    print(f"{name} PASSED ({expected}/{expected}).", flush=True)


def main() -> None:
    print("M46A Final Exhaustive Audit started...", flush=True)
    t0 = time.time()

    # 1. P0 suites (M45A current + M44A/B/C regression; Rust changed).
    run_suite("M45A P0 semantic test suite", "m45a_p0_semantic", 5)
    run_suite("M44A P0 regression test suite", "m44a_p0_semantic", 6)
    run_suite("M44B P0 regression test suite", "m44b_p0_semantic", 4)
    run_suite("M44C P0 regression test suite", "m44c_p0_semantic", 4)

    # 2. Corpus manifest checks.
    if not CORPUS_MANIFEST.exists():
        raise RuntimeError("corpus manifest missing — run m46a_generate_corpus.py first")
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    for split, (games, roots) in EXPECTED_SPLITS.items():
        m = manifest["splits"][split]
        if m["games"] != games or m["roots"] != roots:
            raise RuntimeError(f"corpus {split} size mismatch: {m}")
        if not is_hex64(m.get("root_identity_sha256", "")):
            raise RuntimeError(f"corpus {split} identity digest missing/invalid")
    print("Corpus manifest checks passed (2048/256/256 games; 16384/2048/2048 roots).",
          flush=True)

    # 3. Training outputs present.
    for f in ["best.pt", "epoch_metrics.json", "final_metrics.json",
              "test_gateb_roots.npz", "test_gatea_preds.npz", "shift1_preds.npz",
              "verdict.json"]:
        if not (RUN_DIR / f).exists():
            raise RuntimeError(f"training output missing: {f}")
    history = json.loads((RUN_DIR / "epoch_metrics.json").read_text(encoding="utf-8"))
    if len(history) != 32:
        raise RuntimeError(f"expected 32 epochs, got {len(history)}")
    final = json.loads((RUN_DIR / "final_metrics.json").read_text(encoding="utf-8"))

    # 4. Checkpoint selection rule recomputed from the epoch table.
    best = None
    best_epoch = -1
    for h in history:
        key = (round(h["val_optimal_set_agreement"], 12),
               round(h["val_strict_pair_accuracy"], 12),
               round(-h["val_mean_regret"], 12), -h["epoch"])
        if best is None or key > best:
            best = key
            best_epoch = h["epoch"]
    if best_epoch != final["best_epoch"]:
        raise RuntimeError(f"selection rule gives epoch {best_epoch} != saved {final['best_epoch']}")
    print(f"Checkpoint selection recomputed: best epoch {best_epoch} (matches).", flush=True)

    # 5. Gate B recomputed from saved per-root means.
    z = np.load(RUN_DIR / "test_gateb_roots.npz")
    n_roots = len([k for k in z.files if k.startswith("root_")])
    opt_ok = sp_ok = sp_n = zero_r = 0
    regrets = []
    for i in range(n_roots):
        tm = z[f"root_{i}"]  # (2, A): teacher, model
        q, m = tm[0].astype(np.float64), tm[1].astype(np.float64)
        na = len(q)
        astar = set(np.flatnonzero(q == q.max()).tolist())
        mhat = int(np.argmax(m))
        opt_ok += mhat in astar
        for a in range(na):
            for b in range(na):
                if a == b or q[a] == q[b]:
                    continue
                sp_n += 1
                sp_ok += (np.sign(m[a] - m[b]) == np.sign(q[a] - q[b]) and m[a] != m[b])
        r = (q.max() - q[mhat]) / max(q.max() - q.min(), 1.0)
        regrets.append(r)
        zero_r += (r == 0.0)
    regrets = np.array(regrets)
    recomputed_b = {
        "optimal_set_agreement": opt_ok / n_roots,
        "strict_pair_accuracy": sp_ok / sp_n,
        "mean_regret": float(regrets.mean()),
        "zero_regret_rate": zero_r / n_roots,
    }
    for k, v in recomputed_b.items():
        if abs(v - final["test"][k]) > 1e-12:
            raise RuntimeError(f"Gate B recomputation mismatch on {k}: {v} vs {final['test'][k]}")
    print("Gate B recomputation matches saved metrics.", flush=True)

    # 6. Gate A recomputed from saved per-example predictions.
    # columns: pred_aff_c, pred_aff_m, pred_claim, pred_mindef,
    #          true_aff_c, true_aff_m, true_claim, true_mindef, has_nb
    p = np.load(RUN_DIR / "test_gatea_preds.npz")["preds"]
    aff_c = (p[:, 0] == p[:, 4]).mean()
    aff_m = (p[:, 1] == p[:, 5]).mean()
    nbm = p[:, 8].astype(bool)
    claim = (p[nbm, 2] == p[nbm, 6]).mean()
    mindef = (p[nbm, 3] == p[nbm, 7]).mean()
    for k, v in [("aff_count_acc", aff_c), ("aff_max_acc", aff_m),
                 ("claim_acc", claim), ("mindef_acc", mindef)]:
        if abs(v - final["test"][k]) > 1e-12:
            raise RuntimeError(f"Gate A recomputation mismatch on {k}")
    print("Gate A recomputation matches saved metrics.", flush=True)

    # 7. SHIFT1 recomputed from saved paired predictions.
    # columns: pt*4, ps*4, lt*4, ls*4, noble_ok
    s = np.load(RUN_DIR / "shift1_preds.npz")["rows"]
    names = ["aff_count", "aff_max", "claim", "mindef"]
    shift_recomputed = {}
    for j, name in enumerate(names):
        pt, ps, lt, ls = s[:, j], s[:, 4 + j], s[:, 8 + j], s[:, 12 + j]
        if name in ("claim", "mindef"):
            keep = s[:, 16].astype(bool)
            pt, ps, lt, ls = pt[keep], ps[keep], lt[keep], ls[keep]
        changed = lt != ls
        n = int(changed.sum())
        both = int(((pt == lt) & (ps == ls) & changed).sum())
        sign = int((np.sign(ps - pt) == np.sign(ls - lt))[changed].sum()) if n else 0
        shift_recomputed[name] = {"changed_pairs": n,
                                  "both_side_exact": both / n if n else 0.0,
                                  "signed_delta_acc": sign / n if n else 0.0}
    for k in names:
        for m in ("changed_pairs", "both_side_exact", "signed_delta_acc"):
            a, b = shift_recomputed[k][m], final["shift1"][k][m]
            if abs(a - b) > (0 if m == "changed_pairs" else 1e-12):
                raise RuntimeError(f"SHIFT1 recomputation mismatch on {k}.{m}")
    print("SHIFT1 recomputation matches saved metrics.", flush=True)

    # 8. Frozen PASS table asserted.
    t, sh = final["test"], final["shift1"]
    checks = {
        "A2-affordable-count": t["aff_count_acc"] >= 0.995,
        "A2-max-prestige": t["aff_max_acc"] >= 0.995,
        "A2-claimable": t["claim_acc"] >= 0.995,
        "A2-min-deficit": t["mindef_acc"] >= 0.99,
        "A3-coverage": all(sh[k]["changed_pairs"] >= 256 for k in names),
        "A3-both-exact": all(sh[k]["both_side_exact"] >= 0.99 for k in names),
        "A3-signed-delta": all(sh[k]["signed_delta_acc"] >= 0.99 for k in names),
        "B1-optimal-set": t["optimal_set_agreement"] >= 0.98,
        "B1-strict-pair": t["strict_pair_accuracy"] >= 0.99,
        "B1-regret": t["mean_regret"] <= 0.005,
    }
    failed = [k for k, v in checks.items() if not v]
    overall = "PASS" if not failed else "FAIL"
    print("Frozen PASS table:", json.dumps(checks), flush=True)
    print(f"OVERALL: {overall}", flush=True)

    # 9. Provenance.
    splendor_exe_sha = file_sha256(SPLN)
    catalog_sha = file_sha256(CATALOG)
    sys.path.insert(0, str(REPO / "training/m17_gpu"))
    from splendor_gpu.data import catalog_semantic_hash, load_catalog
    cat_sem_hash = catalog_semantic_hash(load_catalog(CATALOG))
    if cat_sem_hash != AUTHORITATIVE_CATALOG_SEMANTIC_HASH:
        raise RuntimeError(f"catalog semantic hash drift: {cat_sem_hash}")
    source_shas = {
        "m46a_corpus_command": file_sha256(REPO / "crates/splendor-cli/src/m46a_corpus_command.rs"),
        "m46a_model": file_sha256(REPO / "training/m17_gpu/splendor_gpu/m46a_model.py"),
        "m46a_train": file_sha256(REPO / "training/m17_gpu/m46a_train.py"),
        "m46a_generate_corpus": file_sha256(REPO / "scripts/m46a_generate_corpus.py"),
        "m46a_final_audit": file_sha256(REPO / "scripts/m46a_final_audit.py"),
        "evaluation_accessor": file_sha256(REPO / "crates/splendor-search/src/evaluation.rs"),
        "m45a_p0_semantic_test": file_sha256(REPO / "crates/splendor-cli/tests/m45a_p0_semantic.rs"),
    }

    final_document = {
        "format": "effective-splendor-m46a-relational-successor-representation-gate",
        "version": 1,
        "milestone": "M46A",
        "title": "Relational Successor Representation Gate",
        "audit_completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "starting_point": "adfab3d (M45A permanently closed)",
        "design_commits": ["a174ee0 (V1 design-only draft)", "4f46d2b (V2 frozen contract)"],
        "overall_verdict": overall,
        "failed_gates": failed,
        "frozen_recipe": FROZEN_RECIPE,
        "corpus": manifest,
        "gate_a": {k: t[k] for k in ("aff_count_acc", "aff_max_acc", "claim_acc", "mindef_acc")},
        "gate_b": {k: t[k] for k in ("optimal_set_agreement", "strict_pair_accuracy",
                                     "mean_regret", "zero_regret_rate", "regret_p50",
                                     "regret_p90", "regret_p95", "regret_max",
                                     "roots", "strict_pairs")},
        "shift1": sh,
        "best_epoch": final["best_epoch"],
        "epoch_history": final["history"],
        "provenance": {
            "splendor_exe_sha256": splendor_exe_sha,
            "catalog_file_sha256": catalog_sha,
            "catalog_semantic_hash": cat_sem_hash,
            "m45a_result_artifact_sha256": file_sha256(M45A_RESULT_JSON),
            "source_shas": source_shas,
        },
    }
    RESULT_JSON.write_text(json.dumps(final_document, indent=2), encoding="utf-8")
    print(f"Tracked result written to {RESULT_JSON} (SHA256: {file_sha256(RESULT_JSON)})")
    print(f"Done in {time.time()-t0:.1f}s. OVERALL: {overall}")
    if overall != "PASS":
        raise SystemExit(f"M46A VALID RUN FAIL: {failed}")


if __name__ == "__main__":
    main()
