"""M47S Residual Target Feasibility Diagnostic — orchestrator + metrics.

Frozen contract (docs/m47s-residual-target-feasibility-diagnostic.md):
- Corpus: M46A test split ONLY (256 games, 2048 roots, all used).
- Budgets: n1/n200/n500/n2000 (seed 20_260_703, count 4, depth 1).
- Tie-aware corrections: a_n1 ∉ A*_2000 (not raw canonical disagreement).
- F1: n2000 optimal-set miss rate >= 10%
- F2: stable/n2000-corrections >= 80% AND stable/all >= 8%
- F3: median normalized regret over stable corrections >= 0.05
- Descriptive: pairwise density, static margin, taxonomy, stage split.
- Verdict: RESIDUAL_TARGET_FEASIBLE / RESIDUAL_TARGET_WEAK_OR_UNSTABLE.

No training, no Arena, no model. Fail-closed throughout.
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
CORPUS = REPO / "local-artifacts/m46a-corpus"
OUT_ROOT = REPO / "local-artifacts/m47s-run"
RESULT_JSON = REPO / "benchmarks/m47s-residual-target-feasibility-v1.result.json"

TEST_SEED_RANGE = (6_602_304, 6_602_559)
BUDGETS = [1, 200, 500, 2000]
ROOTS_PER_GAME = 8
EXPECTED_ROOTS = 2048

F1_THRESHOLD = 0.10
F2_STABILITY_THRESHOLD = 0.80
F2_COVERAGE_THRESHOLD = 0.08
F3_MEDIAN_THRESHOLD = 0.05

STAGES = {"early": (1, 20), "mid": (21, 45), "late": (46, 10**9)}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_for(decision_ply: int) -> str:
    for name, (lo, hi) in STAGES.items():
        if lo <= decision_ply <= hi:
            return name
    return "late"


def action_kind(action: dict) -> str:
    t = action.get("type", "")
    mapping = {
        "take_tokens": "TakeTokens",
        "buy_market": "BuyMarket",
        "buy_reserved": "BuyReserved",
        "reserve_market": "ReserveMarket",
        "reserve_deck": "ReserveDeck",
        "pass": "Pass",
    }
    return mapping.get(t, t)


def analyze_one_game(seed: int) -> dict:
    gdir = CORPUS / "games" / "test" / f"seed-{seed}"
    rpl = gdir / "match-replay.json"
    shard = gdir / "shard.npz"
    out = OUT_ROOT / "games" / f"seed-{seed}" / "residual.json"
    roots_sidecar = OUT_ROOT / "games" / f"seed-{seed}" / "roots.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))

    out.parent.mkdir(parents=True, exist_ok=True)
    z = np.load(shard)
    root_meta = z["root_meta"]  # (8, 3): step_index, decision_ply, actor
    identity = z["root_identity"]  # (8, 3) S64
    # Cross-check identity triple lengths
    for ri in range(ROOTS_PER_GAME):
        for h in identity[ri]:
            if len(h.decode()) != 64:
                raise RuntimeError(f"seed {seed} root {ri}: bad identity hash")

    roots_spec = [[int(root_meta[ri][0]), int(root_meta[ri][2])]
                  for ri in range(ROOTS_PER_GAME)]
    roots_sidecar.write_text(json.dumps(roots_spec), encoding="utf-8")

    res = subprocess.run(
        [str(SPLN), "m47s-residual",
         "--replay", str(rpl), "--shard", str(shard),
         "--roots", str(roots_sidecar), "--out", str(out)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"seed {seed} analysis failed: {res.stderr[-2000:]}")
    return json.loads(out.read_text(encoding="utf-8"))


def compute_metrics(games: list[dict]) -> dict:
    n_roots = 0
    n2000_corrections = 0
    stable_corrections = 0
    regrets = []
    static_margins = []
    static_margins_norm = []
    legacy_disagreements = 0
    taxonomy: dict = {}
    taxonomy_stage: dict = {}
    pair_total = pair_correct = pair_tie = pair_reversed = 0
    corrections_by_stage = {"early": 0, "mid": 0, "late": 0}
    roots_by_stage = {"early": 0, "mid": 0, "late": 0}

    for g in games:
        for root in g["roots"]:
            n_roots += 1
            ply = root["decision_ply"]
            stage = stage_for(ply)
            roots_by_stage[stage] += 1
            b = {rec["max_nodes"]: rec for rec in root["budgets"]}
            b1, b200, b500, b2000 = b[1], b[200], b[500], b[2000]
            sel1 = b1["selected"]
            sel2000 = b2000["selected"]
            if sel1 != sel2000:
                legacy_disagreements += 1

            # F1: n1 selection strictly non-optimal under n2000
            idx_of_sel1 = b1["actions"].index(sel1)
            if idx_of_sel1 not in b2000["optimal_set"]:
                n2000_corrections += 1
                corrections_by_stage[stage] += 1

                # F2 stability: miss at 200/500/2000 AND common optimal action
                miss200 = idx_of_sel1 not in b200["optimal_set"]
                miss500 = idx_of_sel1 not in b500["optimal_set"]
                common = (set(b200["optimal_set"]) & set(b500["optimal_set"])
                          & set(b2000["optimal_set"]))
                if miss200 and miss500 and common:
                    stable_corrections += 1

                    # F3 regret under n2000 teacher
                    q = b2000["utilities"]
                    q_star = max(q)
                    q_sel = q[idx_of_sel1]
                    denom = max(q_star - min(q), 1)
                    regrets.append((q_star - q_sel) / denom)

                    # static margin: how much n1 preferred its own action
                    q1 = b1["utilities"]
                    # continuation-optimal action (canonical first in common set)
                    a_c_idx = min(common)
                    static_margins.append(q1[idx_of_sel1] - q1[a_c_idx])
                    static_margins_norm.append(
                        (q1[idx_of_sel1] - q1[a_c_idx])
                        / max(max(q1) - min(q1), 1))

                    # taxonomy: n1 kind -> continuation-optimal kind
                    from_kind = action_kind(sel1)
                    to_kind = action_kind(b2000["actions"][a_c_idx])
                    key = f"{from_kind} -> {to_kind}"
                    taxonomy[key] = taxonomy.get(key, 0) + 1
                    skey = f"{stage}: {key}"
                    taxonomy_stage[skey] = taxonomy_stage.get(skey, 0) + 1

            # pairwise density (all roots)
            q1 = b1["utilities"]
            q2 = b2000["utilities"]
            n_a = len(q2)
            for i in range(n_a):
                for j in range(i + 1, n_a):
                    if q2[i] == q2[j]:
                        continue
                    pair_total += 1
                    d1 = q1[i] - q1[j]
                    d2 = q2[i] - q2[j]
                    if d1 == 0:
                        pair_tie += 1
                    elif (d1 > 0) == (d2 > 0):
                        pair_correct += 1
                    else:
                        pair_reversed += 1

    if n_roots != EXPECTED_ROOTS:
        raise RuntimeError(f"expected {EXPECTED_ROOTS} roots, got {n_roots}")

    f1_rate = n2000_corrections / n_roots
    f2_stability = (stable_corrections / n2000_corrections
                    if n2000_corrections else 0.0)
    f2_coverage = stable_corrections / n_roots
    regrets_arr = np.array(regrets) if regrets else np.array([0.0])

    gates = {
        "F1_incidence": {
            "n2000_correction_roots": n2000_corrections,
            "rate": f1_rate,
            "threshold": F1_THRESHOLD,
            "pass": f1_rate >= F1_THRESHOLD,
        },
        "F2_stability": {
            "stable_corrections": stable_corrections,
            "stability_ratio": f2_stability,
            "stability_threshold": F2_STABILITY_THRESHOLD,
            "coverage": f2_coverage,
            "coverage_threshold": F2_COVERAGE_THRESHOLD,
            "pass": (f2_stability >= F2_STABILITY_THRESHOLD
                     and f2_coverage >= F2_COVERAGE_THRESHOLD),
        },
        "F3_magnitude": {
            "median_normalized_regret": float(np.median(regrets_arr)),
            "mean": float(regrets_arr.mean()),
            "p25": float(np.percentile(regrets_arr, 25)),
            "p50": float(np.percentile(regrets_arr, 50)),
            "p75": float(np.percentile(regrets_arr, 75)),
            "p90": float(np.percentile(regrets_arr, 90)),
            "p95": float(np.percentile(regrets_arr, 95)),
            "max": float(regrets_arr.max()),
            "threshold": F3_MEDIAN_THRESHOLD,
            "pass": float(np.median(regrets_arr)) >= F3_MEDIAN_THRESHOLD,
        },
    }
    overall_pass = all(g["pass"] for g in gates.values())

    return {
        "roots_total": n_roots,
        "legacy_canonical_disagreement": {
            "count": legacy_disagreements,
            "rate": legacy_disagreements / n_roots,
        },
        "gates": gates,
        "verdict": ("RESIDUAL_TARGET_FEASIBLE" if overall_pass
                    else "RESIDUAL_TARGET_WEAK_OR_UNSTABLE"),
        "descriptive": {
            "pairwise_density": {
                "teacher_strict_pairs": pair_total,
                "n1_correct": pair_correct,
                "n1_tie_on_strict": pair_tie,
                "n1_reversed": pair_reversed,
                "pairwise_correction_rate": (
                    (pair_tie + pair_reversed) / pair_total if pair_total else 0.0),
            },
            "static_margin": {
                "median": float(np.median(static_margins)) if static_margins else None,
                "mean": float(np.mean(static_margins)) if static_margins else None,
                "median_normalized": (float(np.median(static_margins_norm))
                                      if static_margins_norm else None),
                "max": float(np.max(static_margins)) if static_margins else None,
                "n": len(static_margins),
            },
            "correction_taxonomy": dict(sorted(taxonomy.items(),
                                               key=lambda kv: -kv[1])),
            "correction_taxonomy_by_stage": taxonomy_stage,
            "corrections_by_stage": corrections_by_stage,
            "roots_by_stage": roots_by_stage,
        },
    }


def main() -> None:
    t0 = time.time()
    assert SPLN.exists(), f"missing binary {SPLN}"
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    a, b = TEST_SEED_RANGE
    seeds = list(range(a, b + 1))
    print(f"M47S: analyzing {len(seeds)} games x {ROOTS_PER_GAME} roots "
          f"x {len(BUDGETS)} budgets", flush=True)

    games = []
    done = 0
    for seed in seeds:
        games.append(analyze_one_game(seed))
        done += 1
        if done % 32 == 0:
            print(f"  {done}/{len(seeds)} games ({time.time()-t0:.0f}s)", flush=True)
    print(f"  {done}/{len(seeds)} games complete ({time.time()-t0:.0f}s)", flush=True)

    metrics = compute_metrics(games)
    print(json.dumps({k: v for k, v in metrics.items()
                      if k != "descriptive"}, indent=2))

    # Identity audit: recompute the root-identity digest and compare to M46A.
    triples = []
    for g in games:
        for root in g["roots"]:
            triples.append((root["observation_hash"],
                            root["visible_history_hash"],
                            root["information_set_hash"]))
    if len(set(triples)) != EXPECTED_ROOTS:
        raise RuntimeError("duplicate root identities in M47S run")
    h = hashlib.sha256()
    h.update(b"effective-splendor-m46a-root-identities-v1\0")
    for trip in sorted(set(triples)):
        h.update(("|".join(trip) + "\n").encode())
    identity_digest = h.hexdigest()

    manifest = json.loads((CORPUS / "corpus-manifest.json").read_text(encoding="utf-8"))
    expected_digest = manifest["splits"]["test"]["root_identity_sha256"]
    if identity_digest != expected_digest:
        raise RuntimeError(
            f"root identity digest mismatch: {identity_digest} != M46A {expected_digest}")
    print(f"Identity digest matches M46A test manifest: {identity_digest[:16]}...")

    # Raw per-root records persisted for the final audit's recomputation.
    raw_path = OUT_ROOT / "raw-records.json"
    raw_path.write_text(json.dumps(games), encoding="utf-8")

    result = {
        "format": "effective-splendor-m47s-residual-target-feasibility",
        "version": 1,
        "milestone": "M47S",
        "title": "Residual Target Feasibility Diagnostic",
        "audit_completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "starting_point": "e159d64 (M46A permanently closed)",
        "design_commit": "7ba8f5f",
        "corpus": {
            "source": "M46A frozen test split (permanent diagnostic holdout)",
            "game_seeds": list(TEST_SEED_RANGE),
            "games": len(seeds),
            "roots": EXPECTED_ROOTS,
            "root_identity_sha256": identity_digest,
            "budgets": BUDGETS,
            "sample_seed": 20_260_703,
            "sample_count": 4,
            "max_depth_turns": 1,
        },
        **metrics,
        "provenance": {
            "splendor_exe_sha256": file_sha256(SPLN),
            "m46a_result_artifact_sha256": file_sha256(
                REPO / "benchmarks/m46a-relational-successor-representation-gate-v1.result.json"),
            "m47s_residual_command_sha256": file_sha256(
                REPO / "crates/splendor-cli/src/m47s_residual_command.rs"),
            "m47s_orchestrator_sha256": file_sha256(REPO / "scripts/m47s_residual_target_audit.py"),
            "raw_records_path": str(raw_path),
            "raw_records_sha256": file_sha256(raw_path),
        },
        "scientific_boundary": (
            "n2000 is the champion M07 continuation target, not ground truth; "
            "M42S left n2000-vs-n1 Arena advantage UNRESOLVED. This diagnostic "
            "tests the existence of an imitable, stable residual target, not "
            "ground-truth Q*. Playing-strength gains can only be decided by a "
            "future M48B Arena if ever authorized."),
    }
    RESULT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nTracked result: {RESULT_JSON}")
    print(f"SHA256: {file_sha256(RESULT_JSON)}")
    print(f"VERDICT: {metrics['verdict']}")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
