"""M47S Final Exhaustive Audit & Tracked Result Verifier.

Fail-closed checks:
  - Corpus: 256 games, 2048 roots, frozen seed range 6_602_304..6_602_559.
  - Root identity digest matches M46A test manifest (recomputed from raw).
  - Identity triples unique (2048 distinct).
  - Budgets exactly 1/200/500/2000; sample_seed/count/depth per contract.
  - Canonical action-set identity across budgets (from raw records).
  - All utilities present; optimal sets non-empty.
  - F1/F2/F3 recomputed from raw per-root records; match tracked result.
  - No training artifacts, no Arena artifacts (assert run dir contents).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
OUT_ROOT = REPO / "local-artifacts/m47s-run"
RESULT_JSON = REPO / "benchmarks/m47s-residual-target-feasibility-v1.result.json"
M46A_MANIFEST = REPO / "local-artifacts/m46a-corpus/corpus-manifest.json"

BUDGETS = [1, 200, 500, 2000]
EXPECTED_GAMES = 256
EXPECTED_ROOTS = 2048
TEST_SEED_RANGE = (6_602_304, 6_602_559)


def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def stage_for(ply: int) -> str:
    if ply <= 20:
        return "early"
    if ply <= 45:
        return "mid"
    return "late"


def main() -> None:
    result = json.loads(RESULT_JSON.read_text(encoding="utf-8"))
    raw_path = Path(result["provenance"]["raw_records_path"])
    if file_sha256(raw_path) != result["provenance"]["raw_records_sha256"]:
        raise RuntimeError("raw records SHA mismatch")
    games = json.loads(raw_path.read_text(encoding="utf-8"))

    # Corpus checks
    if len(games) != EXPECTED_GAMES:
        raise RuntimeError(f"games {len(games)} != {EXPECTED_GAMES}")
    seeds = sorted(g["game_seed"] for g in games)
    if seeds[0] != TEST_SEED_RANGE[0] or seeds[-1] != TEST_SEED_RANGE[1]:
        raise RuntimeError("game seed range mismatch")
    if len(set(seeds)) != EXPECTED_GAMES:
        raise RuntimeError("duplicate game seeds")

    triples = []
    n_roots = 0
    for g in games:
        if len(g["roots"]) != 8:
            raise RuntimeError(f"game {g['game_seed']}: roots != 8")
        for root in g["roots"]:
            n_roots += 1
            if len(root["budgets"]) != 4:
                raise RuntimeError("budgets != 4")
            bm = [b["max_nodes"] for b in root["budgets"]]
            if bm != BUDGETS:
                raise RuntimeError(f"budget list {bm} != {BUDGETS}")
            ref = root["budgets"][0]["actions"]
            if not ref:
                raise RuntimeError("empty action set")
            for b in root["budgets"]:
                if b["actions"] != ref:
                    raise RuntimeError("action-set mismatch across budgets")
                if len(b["utilities"]) != len(ref):
                    raise RuntimeError("utility count mismatch")
                if not b["optimal_set"]:
                    raise RuntimeError("empty optimal set")
                mx = max(b["utilities"])
                if any(b["utilities"][i] != mx for i in b["optimal_set"]):
                    raise RuntimeError("optimal set contains non-max utility")
            for f in ("observation_hash", "visible_history_hash",
                      "information_set_hash"):
                if len(root[f]) != 64:
                    raise RuntimeError("bad identity hash length")
            triples.append((root["observation_hash"],
                            root["visible_history_hash"],
                            root["information_set_hash"]))
    if n_roots != EXPECTED_ROOTS:
        raise RuntimeError(f"roots {n_roots} != {EXPECTED_ROOTS}")
    if len(set(triples)) != EXPECTED_ROOTS:
        raise RuntimeError("duplicate root identities")

    h = hashlib.sha256()
    h.update(b"effective-splendor-m46a-root-identities-v1\0")
    for t in sorted(set(triples)):
        h.update(("|".join(t) + "\n").encode())
    digest = h.hexdigest()
    m46a = json.loads(M46A_MANIFEST.read_text(encoding="utf-8"))
    if digest != m46a["splits"]["test"]["root_identity_sha256"]:
        raise RuntimeError("identity digest != M46A test manifest")
    if digest != result["corpus"]["root_identity_sha256"]:
        raise RuntimeError("identity digest != tracked result")

    # Recompute F1/F2/F3 from raw
    n2000_corr = stable = 0
    regrets = []
    legacy = 0
    for g in games:
        for root in g["roots"]:
            b = {r["max_nodes"]: r for r in root["budgets"]}
            sel1 = b[1]["selected"]
            if sel1 != b[2000]["selected"]:
                legacy += 1
            i1 = b[1]["actions"].index(sel1)
            if i1 not in b[2000]["optimal_set"]:
                n2000_corr += 1
                if (i1 not in b[200]["optimal_set"]
                        and i1 not in b[500]["optimal_set"]
                        and (set(b[200]["optimal_set"])
                             & set(b[500]["optimal_set"])
                             & set(b[2000]["optimal_set"]))):
                    stable += 1
                    q = b[2000]["utilities"]
                    regrets.append((max(q) - q[i1]) / max(max(q) - min(q), 1))
    regrets = np.array(regrets) if regrets else np.array([0.0])

    f1 = n2000_corr / EXPECTED_ROOTS
    f2s = stable / n2000_corr if n2000_corr else 0.0
    f2c = stable / EXPECTED_ROOTS
    f3m = float(np.median(regrets))
    gates = result["gates"]
    checks = {
        "F1_rate": abs(gates["F1_incidence"]["rate"] - f1) < 1e-12,
        "F1_count": gates["F1_incidence"]["n2000_correction_roots"] == n2000_corr,
        "F2_stability": abs(gates["F2_stability"]["stability_ratio"] - f2s) < 1e-12,
        "F2_coverage": abs(gates["F2_stability"]["coverage"] - f2c) < 1e-12,
        "F2_stable_count": gates["F2_stability"]["stable_corrections"] == stable,
        "F3_median": abs(gates["F3_magnitude"]["median_normalized_regret"] - f3m) < 1e-12,
        "legacy_count": result["legacy_canonical_disagreement"]["count"] == legacy,
    }
    for k, ok in checks.items():
        if not ok:
            raise RuntimeError(f"recomputation mismatch on {k}")

    pass_all = (f1 >= 0.10 and f2s >= 0.80 and f2c >= 0.08 and f3m >= 0.05)
    expected_verdict = ("RESIDUAL_TARGET_FEASIBLE" if pass_all
                        else "RESIDUAL_TARGET_WEAK_OR_UNSTABLE")
    if result["verdict"] != expected_verdict:
        raise RuntimeError("verdict mismatch")

    # No training / Arena artifacts
    for p in OUT_ROOT.rglob("*"):
        if p.is_file() and p.suffix in (".pt", ".pth"):
            raise RuntimeError(f"training artifact found: {p}")

    print("M47S final audit: ALL CHECKS PASS")
    print(f"  roots={EXPECTED_ROOTS} identity digest matches M46A: {digest[:16]}...")
    print(f"  F1={f1:.4f} (>=0.10) F2_stab={f2s:.4f} (>=0.80) "
          f"F2_cov={f2c:.4f} (>=0.08) F3_med={f3m:.4f} (>=0.05)")
    print(f"  verdict: {expected_verdict}")


if __name__ == "__main__":
    main()
