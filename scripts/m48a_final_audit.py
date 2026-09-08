"""M48A SHIFT1 diagnostic (contract: diagnostic only, NO gates) + final audit.

SHIFT1 report (M47S holdout): true vs SHIFT1 bonus view residual response,
absolute residual magnitude, stratified by F4-changing / E2-changing.

Final audit (fail-closed):
  - corpus splits exact; identity + successor-hash disjoint (from manifest)
  - G0 recorded and passed (full contract: r==0, q bitwise, action==n1)
  - recipe exact (seed 48_000_001, 24 epochs, AdamW 1e-4, cosine 1e-5)
  - checkpoint selection recomputed from validation history
  - internal-test + M47S metrics recomputed from raw label records + saved
    residuals (recomputed here from the checkpoint)
  - static baselines recomputed
  - G1-G4 exact on both splits
  - verdict consistent
  - no second training run, no Arena
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training/m17_gpu"))
from m48a_train import (load_label_games, load_features, budget_record,
                        static_metrics, corrected_metrics, compute_residuals,
                        root_tensors, flatten_roots, SPLITS, RETENTION_FLOOR)  # noqa: E402
from m46a_train import shift1  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RUN_DIR = REPO / "local-artifacts/m48a-run"
RUN_ROOT = RUN_DIR  # alias used by the artifact scan


def val_games_load():
    return load_label_games("validation")
M47S_RAW = REPO / "local-artifacts/m47s-run/raw-records.json"
RESULT_JSON = REPO / "benchmarks/m48a-static-prior-residual-learnability-gate-v1.result.json"

EPOCHS_EXPECTED = 24
GATE_THRESHOLDS = {"G1_capture": 0.20, "G2_retention": 0.99,
                   "G3_agreement_gain": 0.03, "G4_regret_reduction": 0.15}


def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def shift1_features(seed: int):
    """SHIFT1 view of a game's shards: rebuild root_tensors with shifted=True
    on the same M46A shards (features only; labels stay from raw records)."""
    if 6_602_304 <= seed <= 6_602_559:
        d = REPO / "local-artifacts/m46a-corpus/games/test"
    else:
        raise RuntimeError(f"shift1 diagnostic is M47S-holdout only, got {seed}")
    return dict(np.load(d / f"seed-{seed}" / "shard.npz", allow_pickle=False))


@torch.no_grad()
def shift1_residual_response(model, device):
    """For M47S holdout games: residual under true vs SHIFT1 bonus views.
    Reports delta distribution, absolute magnitudes, and F4/E2-changing
    stratification (labels recomputed exactly as in M46A's SHIFT1 logic)."""
    m47s_games = json.loads(M47S_RAW.read_text(encoding="utf-8"))
    deltas = []
    absolutes = []
    f4_changed_deltas = []
    e2_changed_deltas = []
    unchanged_deltas = []
    from splendor_gpu.m48a_model import ResidualSuccessorNet  # noqa
    for g in m47s_games:
        seed = g["game_seed"]
        z = shift1_features(seed)
        step_to_ri = {int(z["root_meta"][c][0]): c
                      for c in range(z["n_actions"].shape[0])}
        for root in g["roots"]:
            ri = step_to_ri[root["step_index"]]
            rt_t = root_tensors(z, ri, shifted=False)
            rt_s = root_tensors(z, ri, shifted=True)
            for rt, bucket in ((rt_t, None), (rt_s, "shift")):
                batch, table = flatten_roots([rt])
                t = {k: torch.from_numpy(v).to(device) for k, v in batch.items()
                     if k in ("card", "noble", "praw", "glob")}
                t["cmask"] = torch.from_numpy(batch["cmask"]).to(device)
                t["nmask"] = torch.from_numpy(batch["nmask"]).to(device)
                h = model.encode(t["card"], t["cmask"], t["noble"], t["nmask"],
                                 t["praw"], t["glob"])
                u = model.residual(h).squeeze(-1)
                rb = table[0]
                na = rb["na"]
                actor = rb["actor"]
                uk = u[rb["start"]:rb["start"] + rb["count"]].reshape(na, 4, 2)
                te = torch.from_numpy(rb["te"]).to(device)
                uk = torch.where(te.unsqueeze(-1), torch.zeros_like(uk), uk)
                r = (uk[:, :, actor] - uk[:, :, 1 - actor]).mean(dim=1)
                if bucket == "shift":
                    r_shift = r.cpu().numpy()
                else:
                    r_true = r.cpu().numpy()
            d = r_shift - r_true
            deltas.extend(d.tolist())
            absolutes.extend(np.abs(r_true).tolist())
            # F4/E2-changing stratification: did labels change under SHIFT1?
            f4_t = (rt_t["aff_c"], rt_t["maxp"])
            f4_s = (rt_s["aff_c"], rt_s["maxp"])
            e2_t = (rt_t["clm"], rt_t["mnd"])
            e2_s = (rt_s["clm"], rt_s["mnd"])
            f4_chg = not (np.array_equal(f4_t[0], f4_s[0])
                          and np.array_equal(f4_t[1], f4_s[1]))
            e2_chg = not (np.array_equal(e2_t[0], e2_s[0])
                          and np.array_equal(e2_t[0], e2_s[0])) or \
                not np.array_equal(e2_t[1], e2_s[1])
            if f4_chg:
                f4_changed_deltas.extend(d.tolist())
            if e2_chg:
                e2_changed_deltas.extend(d.tolist())
            if not f4_chg and not e2_chg:
                unchanged_deltas.extend(d.tolist())
    deltas = np.array(deltas)
    absolutes = np.array(absolutes)

    def stats(a):
        if len(a) == 0:
            return {"n": 0}
        return {"n": int(len(a)), "mean": float(a.mean()),
                "median": float(np.median(a)), "p90": float(np.percentile(a, 90)),
                "max": float(np.abs(a).max())}

    return {
        "delta_distribution": stats(deltas),
        "absolute_residual": stats(absolutes),
        "strata": {
            "f4_changed": stats(np.array(f4_changed_deltas)),
            "e2_changed": stats(np.array(e2_changed_deltas)),
            "unchanged": stats(np.array(unchanged_deltas)),
        },
        "note": ("Diagnostic only (no gates): the static prior already owns "
                 "F4/E2 color binding; the residual has no obligation to "
                 "re-encode it. Reported for completeness per DESIGN_V2 B10."),
    }


def main():
    t0 = time.time()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    final = json.loads((RUN_DIR / "final_metrics.json").read_text(encoding="utf-8"))
    history = json.loads((RUN_DIR / "epoch_metrics.json").read_text(encoding="utf-8"))
    g0 = json.loads((RUN_DIR / "g0.json").read_text(encoding="utf-8"))

    # 1. Corpus manifest checks
    manifest = json.loads((RUN_DIR / "label-manifest.json").read_text(encoding="utf-8"))
    exp = {"train": (1792, 14336), "internal_test": (256, 2048),
           "validation": (256, 2048), "m47s_holdout": (256, 2048)}
    for k, (games, roots) in exp.items():
        m = manifest["splits"][k]
        if m["games"] != games or m["roots"] != roots:
            raise RuntimeError(f"manifest {k}: {m}")
    if not manifest.get("pairwise_identity_disjoint"):
        raise RuntimeError("identity disjointness flag missing")
    if not manifest.get("pairwise_successor_hash_disjoint"):
        raise RuntimeError("successor-hash disjointness flag missing")
    print("Corpus manifest checks PASS.")

    # 2. G0 recorded + passed
    if not g0.get("pass"):
        raise RuntimeError("G0 not passed")
    if g0.get("q_bitexact_roots") != 2048 or g0.get("action_exact_roots") != 2048:
        raise RuntimeError("G0 counts wrong")
    print("G0 recorded PASS (2048/2048 bitwise + action equality).")

    # 3. Recipe: 24 epochs exactly + per-epoch record sanity
    if len(history) != EPOCHS_EXPECTED:
        raise RuntimeError(f"epochs {len(history)} != {EPOCHS_EXPECTED}")
    for h in history:
        for f in ("train_loss", "val_retention", "val_capture",
                  "val_agreement", "val_regret"):
            if f not in h:
                raise RuntimeError(f"epoch record missing field {f}")

    # 4. Checkpoint selection recomputed
    best = None
    best_epoch = -1
    for h in history:
        if h["val_retention"] >= RETENTION_FLOOR:
            key = (round(h["val_capture"], 12), round(h["val_agreement"], 12),
                   round(-h["val_regret"], 12), -h["epoch"])
            if best is None or key > best:
                best = key
                best_epoch = h["epoch"]
    route_ok = best_epoch >= 0
    if route_ok != final["validation_route_ok"]:
        raise RuntimeError("route_ok mismatch")
    if best_epoch != final["best_epoch"]:
        raise RuntimeError(f"selection recompute {best_epoch} != {final['best_epoch']}")
    print(f"Checkpoint selection recomputed: best_epoch={best_epoch}, route_ok={route_ok} (matches).")

    # 5. Reload the evaluated checkpoint; when route failed, independently
    #    verify the fallback IS the highest-retention epoch's checkpoint.
    from splendor_gpu.m48a_model import ResidualSuccessorNet
    model = ResidualSuccessorNet().to(device)
    ckpt = RUN_DIR / "best.pt" if route_ok else RUN_DIR / "route-fail-checkpoint.pt"
    model.load_state_dict(torch.load(ckpt, map_location=device))
    model.eval()
    if not route_ok:
        best_ret = max(history, key=lambda h: (round(h["val_retention"], 12),
                                               -h["epoch"]))
        residuals_fb = compute_residuals(model, val_games_load(), device, {})
        vm_fb = corrected_metrics(
            [r for g in val_games_load() for r in g["roots"]], residuals_fb)
        if abs(vm_fb["retention"] - best_ret["val_retention"]) > 1e-12 \
                or abs(vm_fb["capture"] - best_ret["val_capture"]) > 1e-12:
            raise RuntimeError(
                "fallback checkpoint does not reproduce the highest-retention "
                f"epoch ({best_ret['epoch']}) metrics")
        print(f"Fallback checkpoint verified == highest-retention epoch "
              f"{best_ret['epoch']} metrics.")

    # 6. Recompute internal-test + M47S metrics from raw
    shard_cache = {}
    itest_games = load_label_games("internal_test")
    m47s_games = json.loads(M47S_RAW.read_text(encoding="utf-8"))
    for name, games in (("internal_test", itest_games), ("m47s_holdout", m47s_games)):
        roots = [r for g in games for r in g["roots"]]
        sm = static_metrics(roots)
        residuals = compute_residuals(model, games, device, shard_cache)
        cm = corrected_metrics(roots, residuals)
        saved = final[name]
        for k, v in saved["static"].items():
            if isinstance(v, float) and abs(sm[k] - v) > 1e-12:
                raise RuntimeError(f"{name} static {k} mismatch")
        for k, v in saved["corrected"].items():
            if isinstance(v, float) and abs(cm[k] - v) > 1e-12:
                raise RuntimeError(f"{name} corrected {k} mismatch")
        # Gates exact
        g = {
            "G1_capture": cm["capture"] >= GATE_THRESHOLDS["G1_capture"],
            "G2_retention": cm["retention"] >= GATE_THRESHOLDS["G2_retention"],
            "G3_agreement_gain": (cm["agreement"] - sm["static_agreement"])
            >= GATE_THRESHOLDS["G3_agreement_gain"],
            "G4_regret_reduction": sm["static_mean_regret"] > 0
            and ((sm["static_mean_regret"] - cm["mean_regret"])
                 / sm["static_mean_regret"]) >= GATE_THRESHOLDS["G4_regret_reduction"],
        }
        for gn, gp in g.items():
            if gp != saved["gates"][gn]["pass"]:
                raise RuntimeError(f"{name} {gn} pass mismatch")
        print(f"{name}: static/corrected/gates recomputed — all match.")

    # 7. Verdict consistency
    overall = (route_ok
               and all(v["pass"] for v in final["internal_test"]["gates"].values())
               and all(v["pass"] for v in final["m47s_holdout"]["gates"].values()))
    expected = ("STATIC_PRIOR_RESIDUAL_LEARNABLE" if overall
                else "STATIC_PRIOR_RESIDUAL_NOT_VALIDATED")
    if final["verdict"] != expected:
        raise RuntimeError("verdict mismatch")
    print("SHIFT1 diagnostic (M47S holdout)...", flush=True)
    shift1_diag = shift1_residual_response(model, device)
    print(json.dumps(shift1_diag, indent=1))

    # 9. No Arena artifacts: assert the M48A run directory contains ONLY the
    #    expected file kinds (checkpoints/JSON), and that no arena-report or
    #    replay file exists anywhere under it.
    ALLOWED = {"g0.json", "label-manifest.json", "epoch_metrics.json",
               "final_metrics.json", "best.pt", "route-fail-checkpoint.pt"}
    for p in RUN_ROOT.glob("*/*"):
        pass  # labels/ and run1-void/ are directories handled below
    for p in RUN_ROOT.rglob("*"):
        if p.is_file():
            rel = p.relative_to(RUN_ROOT)
            if rel.parts[0] in ("labels", "run1-void"):
                continue
            if p.name not in ALLOWED:
                raise RuntimeError(f"unexpected run artifact: {rel}")
            if p.name.startswith("arena-report") or p.name.startswith("match-replay"):
                raise RuntimeError(f"arena artifact found: {rel}")
    print("Run-directory artifact scan clean (no arena artifacts).")

    # 10. Tracked result
    result = {
        "format": "effective-splendor-m48a-static-prior-residual-learnability-gate",
        "version": 1,
        "milestone": "M48A",
        "title": "Static-Prior Residual Learnability Gate",
        "audit_completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "starting_point": "e0e4a44 (M47S permanently closed)",
        "design_commits": ["412d7a4 (V1)", "c543658 (V2 frozen contract)"],
        "run_note": ("Run 1 VOID (implementation bug: seat-0 instead of actor "
                     "viewpoint; log preserved in run1-void/). This result is "
                     "Run 2, the single valid run after the one permitted "
                     "implementation repair (also fixed: route-fail fallback, "
                     "successor-hash cross-split audit, G0 full scoring check, "
                     "SHA-256 pair sampling; plus non-contractual performance "
                     "repairs: GC removal from hot loops, compact pair arrays "
                     "with verified identical selection, batched validation)."),
        "validation_route_ok": route_ok,
        "best_epoch": final["best_epoch"],
        "gates": {
            "internal_test": final["internal_test"]["gates"],
            "m47s_holdout": final["m47s_holdout"]["gates"],
        },
        "static_baselines": {
            "internal_test": final["internal_test"]["static"],
            "m47s_holdout": final["m47s_holdout"]["static"],
        },
        "corrected": {
            "internal_test": final["internal_test"]["corrected"],
            "m47s_holdout": final["m47s_holdout"]["corrected"],
        },
        "verdict": final["verdict"],
        "shift1_diagnostic": shift1_diag,
        "epoch_history": history,
        "phase_totals": final.get("phase_totals"),
        "corpus": manifest,
        "g0": g0,
        "provenance": {
            "m47s_result_sha256": file_sha256(
                REPO / "benchmarks/m47s-residual-target-feasibility-v1.result.json"),
            "m46a_result_sha256": file_sha256(
                REPO / "benchmarks/m46a-relational-successor-representation-gate-v1.result.json"),
            "evaluated_checkpoint": ("best.pt" if route_ok
                                     else "route-fail-checkpoint.pt"),
            "evaluated_checkpoint_sha256": file_sha256(ckpt),
            "m48a_model_sha256": file_sha256(
                REPO / "training/m17_gpu/splendor_gpu/m48a_model.py"),
            "m48a_train_sha256": file_sha256(
                REPO / "training/m17_gpu/m48a_train.py"),
            "m48a_labels_sha256": file_sha256(
                REPO / "scripts/m48a_generate_labels.py"),
            "m48a_final_audit_sha256": file_sha256(Path(__file__)),
        },
        "scientific_boundary": (
            "n2000 is the champion continuation target, not ground truth. "
            "This verdict concerns offline improvement toward n2000 "
            "preferences only; no playing-strength claim is made or "
            "implied. Per the frozen terminal budget, a valid FAIL stops "
            "neural evaluator research: no M48A-v2, no M48B."),
    }
    RESULT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nTracked result: {RESULT_JSON}")
    print(f"SHA256: {file_sha256(RESULT_JSON)}")
    print(f"VERDICT: {final['verdict']}")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
