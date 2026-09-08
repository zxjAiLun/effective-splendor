#!/usr/bin/env python3
"""S2 A2 + A3: strict-divergence term attribution and candidate synthesis
(DESIGN_V2 frozen contract).

A2: for SEARCH_ACTOR strict divergences only, compute signed per-term gaps
    between the unique H action and the search recorded action, with the
    category/feature split.
A3: apply the frozen candidate grammar, gates, and frequency-first ranking.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
S0_ROOT = REPO / "local-artifacts/s0-baseline-calibration"
OUT_ROOT = REPO / "local-artifacts/s2-census"
ROWS = OUT_ROOT / "census-rows.jsonl"

# Frozen term fields (must match HeuristicTermScores).
TERM_FIELDS = [
    "category_base", "prestige", "noble_gain", "noble_direct",
    "bonus_usefulness", "cost_efficiency", "deficit_reduction",
    "new_target", "return_penalty", "gold_value", "reserve_proximity",
    "reserve_gold", "reserve_blind_gold",
]

STAGES = ["early", "mid", "late"]


def act_key(a: dict) -> str:
    return json.dumps(a, sort_keys=True)


def action_type(a: dict) -> str:
    return a["type"]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (center - half, center + half)


def main() -> None:
    rows = [json.loads(l) for l in ROWS.read_text().splitlines() if l.strip()]

    game_meta = {}
    for row in rows:
        gid = row["game_id"]
        if gid not in game_meta:
            pairing = "p1_heuristic_vs_n1" if gid.startswith("p1_") else "p2_heuristic_vs_m07"
            rot = gid.split("-")[-1]
            game_meta[gid] = {
                "opponent": "n1" if pairing.startswith("p1") else "M07",
                "heuristic_seat": 0 if rot == "r0" else 1,
                "winners": row["winners"],
                "replay": None,  # filled below
            }

    def h_won(gid: str) -> bool:
        g = game_meta[gid]
        return g["heuristic_seat"] in g["winners"] and len(g["winners"]) == 1

    # ---- collect SEARCH_ACTOR strict divergences ----
    strict = []
    for row in rows:
        gid = row["game_id"]
        g = game_meta[gid]
        if row["actor_seat"] == g["heuristic_seat"]:
            continue  # REFERENCE_ACTOR
        a_opp = row["a_n1"] if g["opponent"] == "n1" else row["a_m07"]
        if act_key(a_opp) in {act_key(a) for a in row["h_star"]}:
            continue
        if row["h_star_size"] != 1:
            continue
        strict.append((row, g))

    print(f"SEARCH_ACTOR strict divergences: {len(strict)}")

    # ---- A2: term gaps via a term-decomposition probe ----
    # We need per-action term vectors for the two actions at each strict
    # context. Add a tiny probe mode to s2-census? Instead: reuse
    # heuristic_term_scores through a new small CLI flag would require
    # another rebuild; simpler: the census rows don't carry terms, so we run
    # a second pass with a dedicated term-gap command batched per replay.
    # To keep this script self-contained we shell out to a per-replay term
    # pass implemented below in Rust? — No: implement the term-gap pass
    # directly via the s1-probe pattern is too heavy. Instead, we extend the
    # census rows: rerun s2-census with --emit-terms (implemented in the
    # same Rust command) writing term vectors for h_action and recorded
    # action at strict divergences.
    print("Running term-gap pass (s2-census --emit-terms)...")
    terms_path = OUT_ROOT / "term-gaps.jsonl"
    if terms_path.exists():
        terms_path.unlink()
    for pairing in ["p1_heuristic_vs_n1", "p2_heuristic_vs_m07"]:
        for rpl in sorted(S0_ROOT.glob(f"{pairing}/block-*/r*/match-replay.json")):
            gid = f"{rpl.parent.parent.parent.name}-{rpl.parent.parent.name}-{rpl.parent.name}"
            r = subprocess.run(
                [str(SPLN), "s2-census", "--input", str(rpl), "--out", str(terms_path),
                 "--game-id", gid, "--heuristic-seed", "20260812",
                 "--sample-seed", "20260703", "--emit-terms"],
                capture_output=True, text=True)
            if r.returncode != 0:
                print(f"FAIL: {gid}: {r.stderr[:300]}")
                sys.exit(1)
    gaps = [json.loads(l) for l in terms_path.read_text().splitlines()
            if l.strip() and '"delta"' in l]
    print(f"term-gap rows: {len(gaps)}")

    # The Rust side emits gap rows for BOTH search policies at every
    # |H*|==1 context where that policy's action differs from the unique H
    # action. The Python side keeps only the game's actual opponent AND the
    # strict-divergence filter (search action not in H*, |H*|==1) — matching
    # the A1 classification. score_gap must be > 0 on every kept row and the
    # deltas must sum exactly to it.
    strict_keys = {
        (row["game_id"], row["ply"], "n1" if game_meta[row["game_id"]]["opponent"] == "n1" else "m07")
        for row, g in strict
    }
    kept = []
    parity_bad = 0
    for gp in gaps:
        key = (gp["game_id"], gp["ply"], gp["policy"])
        if key not in strict_keys:
            continue
        total_gap = sum(gp["delta"][f] for f in TERM_FIELDS)
        if total_gap != gp["score_gap"] or gp["score_gap"] <= 0:
            parity_bad += 1
            continue
        kept.append(gp)
    if parity_bad:
        print(f"FAIL: term-gap parity violated on {parity_bad} strict rows")
        sys.exit(1)
    print(f"TERM-GAP PARITY: PASS ({len(kept)} strict rows, sum of deltas == score gap > 0)")
    gaps = kept

    # ---- aggregate dominant separating terms ----
    dominant_counts = defaultdict(int)
    cat_dominated = 0
    feature_dominated = 0
    for gp in gaps:
        deltas = {f: gp["delta"][f] for f in TERM_FIELDS}
        max_d = max(deltas.values())
        winners = sorted(f for f, v in deltas.items() if v == max_d and v > 0)
        for w in winners:
            dominant_counts[w] += 1
        cat = gp["delta"]["category_base"]
        feat = sum(v for k, v in deltas.items() if k != "category_base")
        if cat >= feat:
            cat_dominated += 1
        else:
            feature_dominated += 1
    print(f"\nDominant separating terms (strict divergences):")
    for k, v in sorted(dominant_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    print(f"category-dominated: {cat_dominated} | feature-dominated: {feature_dominated}")

    # ---- A3: candidate grammar + gates + ranking ----
    # pattern = (recorded search action type -> unique H action type) [+ stage]
    search_actor_total = sum(1 for row in rows
                             if row["actor_seat"] != game_meta[row["game_id"]]["heuristic_seat"])
    patterns = defaultdict(lambda: {"count": 0, "games": set(),
                                    "opp_games": defaultdict(set)})
    for row, g in strict:
        h_action = row["h_star"][0]
        base = f"{action_type(row['recorded_action'])}->{action_type(h_action)}"
        stage = row["stage"]
        for key in [base, f"{base}|{stage}"]:
            p = patterns[key]
            p["count"] += 1
            p["games"].add(row["game_id"])
            p["opp_games"][g["opponent"]].add(row["game_id"])

    candidates = []
    for key, p in patterns.items():
        rate = p["count"] / search_actor_total
        if rate < 0.05:
            continue
        if not p["opp_games"]["n1"] or not p["opp_games"]["M07"]:
            continue
        deltas = {}
        for opp in ["n1", "M07"]:
            exposed = p["opp_games"][opp]
            all_g = {gid for gid, g in game_meta.items() if g["opponent"] == opp}
            unexposed = all_g - exposed
            if not exposed or not unexposed:
                deltas[opp] = None
                continue
            e = sum(1 for gid in exposed if h_won(gid)) / len(exposed)
            u = sum(1 for gid in unexposed if h_won(gid)) / len(unexposed)
            deltas[opp] = round(e - u, 4)
        if deltas.get("n1") is None or deltas.get("M07") is None:
            continue
        if deltas["n1"] <= 0 or deltas["M07"] <= 0:
            continue
        candidates.append({
            "pattern": key, "count": p["count"], "rate": round(rate, 4),
            "distinct_games": len(p["games"]),
            "delta_n1": deltas["n1"], "delta_M07": deltas["M07"],
        })

    print(f"\nCandidates passing all four gates: {len(candidates)}")
    if candidates:
        candidates.sort(key=lambda c: (-c["rate"], -c["distinct_games"], c["pattern"]))
        for c in candidates:
            print(f"  {c['pattern']}: rate {c['rate']:.4f} ({c['count']}), "
                  f"games {c['distinct_games']}, delta n1 {c['delta_n1']:+.3f} / M07 {c['delta_M07']:+.3f}")
        nominee = candidates[0]
    else:
        nominee = None

    verdict = "ACTIONABLE_HYPOTHESIS_FOUND" if nominee else "NO_ACTIONABLE_PATTERN"
    result = {
        "format": "effective-splendor-s2-result",
        "version": 1,
        "experiment_id": "s2-heuristic-win-attribution-v1",
        "design_doc": "docs/s2-heuristic-win-attribution.md @ 82fc400 (DESIGN_V2 APPROVED/FROZEN)",
        "a1": json.load(open(OUT_ROOT / "a1_summary.json")),
        "a2": {
            "strict_divergences": len(strict),
            "dominant_terms": dict(dominant_counts),
            "category_dominated": cat_dominated,
            "feature_dominated": feature_dominated,
        },
        "a3": {
            "search_actor_total": search_actor_total,
            "candidates": candidates,
            "nominee": nominee,
        },
        "verdict": verdict,
    }
    out = REPO / "benchmarks/s2-heuristic-win-attribution-v1.result.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nA3 VERDICT: {verdict}")
    if nominee:
        print(f"Nominee: {nominee['pattern']}")
    print(f"Result: {out}")


if __name__ == "__main__":
    main()
