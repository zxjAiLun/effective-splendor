#!/usr/bin/env python3
"""S2 Repair 1: recompute A2 (corrected Buy term mapping), seat-stratified
exposure tables (from the existing A1 rows), exact-nominee annotations, and
re-run A3 under the SAME frozen grammar/ranking.

Per the S2 final review (96a09c6): A1 census rows are NOT regenerated; the
term-gap rows are recomputed from the repaired Rust term decomposition
(term-gaps-repair1.jsonl); exposure tables are re-aggregated from the
existing census-rows.jsonl with opponent x heuristic-seat stratification.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "local-artifacts/s2-census"
ROWS = OUT_ROOT / "census-rows.jsonl"
GAPS = OUT_ROOT / "term-gaps-repair1.jsonl"

TERM_FIELDS = [
    "category_base", "prestige", "noble_gain", "noble_direct",
    "bonus_usefulness", "cost_efficiency", "deficit_reduction",
    "new_target", "return_penalty", "gold_value", "reserve_proximity",
    "reserve_gold", "reserve_blind_gold",
]


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
    rows = [json.loads(l) for l in ROWS.read_text().splitlines()
            if l.strip() and '"delta"' not in l]
    print(f"A1 census rows (unchanged): {len(rows)}")

    game_meta = {}
    for row in rows:
        gid = row["game_id"]
        if gid not in game_meta:
            rot = gid.split("-")[-1]
            game_meta[gid] = {
                "opponent": "n1" if gid.startswith("p1_") else "M07",
                "heuristic_seat": 0 if rot == "r0" else 1,
                "winners": row["winners"],
            }

    def h_won(gid: str) -> bool:
        g = game_meta[gid]
        return g["heuristic_seat"] in g["winners"] and len(g["winners"]) == 1

    # ---- strict divergences (from unchanged A1 rows) ----
    strict = []
    for row in rows:
        gid = row["game_id"]
        g = game_meta[gid]
        if row["actor_seat"] == g["heuristic_seat"]:
            continue
        a_opp = row["a_n1"] if g["opponent"] == "n1" else row["a_m07"]
        if act_key(a_opp) in {act_key(a) for a in row["h_star"]}:
            continue
        if row["h_star_size"] != 1:
            continue
        strict.append((row, g))
    print(f"SEARCH_ACTOR strict divergences (unchanged): {len(strict)}")

    # ---- A2 repair: term gaps from repaired decomposition ----
    all_gaps = [json.loads(l) for l in GAPS.read_text().splitlines() if '"delta"' in l]
    strict_keys = {
        (row["game_id"], row["ply"],
         "n1" if game_meta[row["game_id"]]["opponent"] == "n1" else "m07")
        for row, g in strict
    }
    gaps = []
    bad = 0
    for gp in all_gaps:
        key = (gp["game_id"], gp["ply"], gp["policy"])
        if key not in strict_keys:
            continue
        total = sum(gp["delta"][f] for f in TERM_FIELDS)
        if total != gp["score_gap"] or gp["score_gap"] <= 0:
            bad += 1
            continue
        gaps.append(gp)
    if bad:
        print(f"FAIL: term-gap parity violated on {bad} rows")
        sys.exit(1)
    print(f"TERM-GAP PARITY: PASS ({len(gaps)} strict rows, repaired mapping)")

    # gap-to-strict row correspondence (join by game/ply/policy)
    gaps_by_key = {(gp["game_id"], gp["ply"], gp["policy"]): gp for gp in gaps}

    # ---- A2 aggregate ----
    dominant_counts = defaultdict(int)
    cat_dom = feat_dom = 0
    for gp in gaps:
        deltas = {f: gp["delta"][f] for f in TERM_FIELDS}
        max_d = max(deltas.values())
        for w in sorted(f for f, v in deltas.items() if v == max_d and v > 0):
            dominant_counts[w] += 1
        cat = deltas["category_base"]
        feat = sum(v for k, v in deltas.items() if k != "category_base")
        if cat >= feat:
            cat_dom += 1
        else:
            feat_dom += 1
    print("\nA2 (repaired) dominant separating terms:")
    for k, v in sorted(dominant_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    print(f"category-dominated: {cat_dom} | feature-dominated: {feat_dom}")

    # ---- seat-stratified exposure tables (from unchanged A1 rows) ----
    def exposure_tables(pattern_fn):
        tables = {}
        for opp in ["n1", "M07"]:
            for seat in [0, 1]:
                gids = {gid for gid, g in game_meta.items()
                        if g["opponent"] == opp and g["heuristic_seat"] == seat}
                exposed = {row["game_id"] for row, g in strict
                           if g["opponent"] == opp and g["heuristic_seat"] == seat
                           and pattern_fn(row)}
                unexposed = gids - exposed
                e_win = sum(1 for gid in exposed if h_won(gid))
                u_win = sum(1 for gid in unexposed if h_won(gid))
                e_rate = e_win / len(exposed) if exposed else None
                u_rate = u_win / len(unexposed) if unexposed else None
                tables[(opp, seat)] = {
                    "exposed_games": len(exposed), "exposed_h_wins": e_win,
                    "exposed_rate": round(e_rate, 4) if e_rate is not None else None,
                    "unexposed_games": len(unexposed), "unexposed_h_wins": u_win,
                    "unexposed_rate": round(u_rate, 4) if u_rate is not None else None,
                    "delta": round(e_rate - u_rate, 4)
                    if e_rate is not None and u_rate is not None else None,
                    "wilson_exposed": [round(x, 4) for x in wilson(e_win, len(exposed))]
                    if exposed else None,
                }
        # pooled descriptive (opponent-pooled, per frozen contract as extras)
        pooled = {}
        for opp in ["n1", "M07"]:
            gids = {gid for gid, g in game_meta.items() if g["opponent"] == opp}
            exposed = {row["game_id"] for row, g in strict
                       if g["opponent"] == opp and pattern_fn(row)}
            unexposed = gids - exposed
            e_win = sum(1 for gid in exposed if h_won(gid))
            u_win = sum(1 for gid in unexposed if h_won(gid))
            pooled[opp] = {
                "exposed_games": len(exposed), "exposed_h_wins": e_win,
                "unexposed_games": len(unexposed), "unexposed_h_wins": u_win,
                "delta": round(e_win / len(exposed) - u_win / len(unexposed), 4)
                if exposed and unexposed else None,
            }
        return tables, pooled

    # ---- A3 re-synthesis (same grammar/gates/ranking) ----
    search_actor_total = sum(1 for row in rows
                             if row["actor_seat"] != game_meta[row["game_id"]]["heuristic_seat"])
    patterns = defaultdict(lambda: {"count": 0, "games": set(),
                                    "opp_games": defaultdict(set)})
    for row, g in strict:
        h_action = row["h_star"][0]
        base = f"{action_type(row['recorded_action'])}->{action_type(h_action)}"
        for key in [base, f"{base}|{row['stage']}"]:
            p = patterns[key]
            p["count"] += 1
            p["games"].add(row["game_id"])
            p["opp_games"][g["opponent"]].add(row["game_id"])

    def pattern_fn_for(key):
        if "|" in key:
            base, stage = key.split("|")
        else:
            base, stage = key, None
        def fn(row):
            h_action = row["h_star"][0]
            b = f"{action_type(row['recorded_action'])}->{action_type(h_action)}"
            return b == base and (stage is None or row["stage"] == stage)
        return fn

    candidates = []
    for key, p in patterns.items():
        rate = p["count"] / search_actor_total
        if rate < 0.05:
            continue
        if not p["opp_games"]["n1"] or not p["opp_games"]["M07"]:
            continue
        # seat-stratified AND pooled deltas (gate on pooled point estimates as
        # before — same frozen gates; seat tables reported alongside)
        tables, pooled = exposure_tables(pattern_fn_for(key))
        d_n1 = pooled["n1"]["delta"]
        d_m07 = pooled["M07"]["delta"]
        if d_n1 is None or d_m07 is None or d_n1 <= 0 or d_m07 <= 0:
            continue
        candidates.append({
            "pattern": key, "count": p["count"], "rate": round(rate, 4),
            "distinct_games": len(p["games"]),
            "delta_n1": d_n1, "delta_M07": d_m07,
            "seat_stratified": {f"{opp}|seat{seat}": v
                                for (opp, seat), v in tables.items()},
            "pooled_extras": pooled,
        })

    print(f"\nA3 (repair) candidates passing all four gates: {len(candidates)}")
    if candidates:
        candidates.sort(key=lambda c: (-c["rate"], -c["distinct_games"], c["pattern"]))
        for c in candidates:
            print(f"  {c['pattern']}: rate {c['rate']:.4f} ({c['count']}), "
                  f"games {c['distinct_games']}, pooled delta n1 {c['delta_n1']:+.3f} / "
                  f"M07 {c['delta_M07']:+.3f}")
            for k, v in c["seat_stratified"].items():
                print(f"    {k}: exp {v['exposed_h_wins']}/{v['exposed_games']} "
                      f"({v['exposed_rate']}) vs unexp {v['unexposed_h_wins']}/{v['unexposed_games']} "
                      f"({v['unexposed_rate']}) delta {v['delta']}")
        nominee = candidates[0]
    else:
        nominee = None

    # ---- exact-nominee annotations (the 853 SEARCH_ACTOR take->buy) ----
    nominee_ann = None
    if nominee and nominee["pattern"] == "take_tokens->buy_market":
        nom_rows = [(row, g) for row, g in strict
                    if action_type(row["recorded_action"]) == "take_tokens"
                    and action_type(row["h_star"][0]) == "buy_market"]
        print(f"\nExact nominee occurrences: {len(nom_rows)} (expected 853)")
        assert len(nom_rows) == 853, "nominee count drift"
        tiers = Counter(r["h_star"][0].get("tier") for r, _ in nom_rows)
        stages = Counter(r["stage"] for r, _ in nom_rows)
        # term gaps joined from repaired rows
        nom_gaps = []
        for row, g in nom_rows:
            key = (row["game_id"], row["ply"],
                   "n1" if g["opponent"] == "n1" else "m07")
            gp = gaps_by_key.get(key)
            if gp:
                nom_gaps.append(gp)
        assert len(nom_gaps) == 853, f"gap join mismatch: {len(nom_gaps)}"
        agg = defaultdict(int)
        dom = Counter()
        cat_dom_n = feat_dom_n = 0
        bu_pos = ng_pos = 0
        for gp in nom_gaps:
            for k, v in gp["delta"].items():
                agg[k] += v
            d = {k: v for k, v in gp["delta"].items() if v > 0}
            if d:
                m = max(d.values())
                for k in [k for k, v in d.items() if v == m]:
                    dom[k] += 1
            cat = gp["delta"]["category_base"]
            feat = sum(v for k, v in gp["delta"].items() if k != "category_base")
            if cat >= feat:
                cat_dom_n += 1
            else:
                feat_dom_n += 1
            if gp["delta"]["bonus_usefulness"] > 0:
                bu_pos += 1
            if gp["delta"]["noble_gain"] > 0:
                ng_pos += 1
        gaps_sorted = sorted(gp["score_gap"] for gp in nom_gaps)
        nominee_ann = {
            "occurrences": len(nom_rows),
            "h_action_tier": dict(tiers),
            "stage": dict(stages),
            "dominant_terms": dict(dom.most_common()),
            "category_dominated": cat_dom_n,
            "feature_dominated": feat_dom_n,
            "bonus_usefulness_positive": bu_pos,
            "noble_gain_positive": ng_pos,
            "score_gap_p50": gaps_sorted[len(gaps_sorted) // 2],
            "score_gap_min": gaps_sorted[0],
            "score_gap_max": gaps_sorted[-1],
            "aggregate_deltas": {k: v for k, v in sorted(agg.items(), key=lambda kv: -kv[1]) if v != 0},
        }
        print(f"  tiers: {dict(tiers)} | stages: {dict(stages)}")
        print(f"  dominant: {dict(dom.most_common())}")
        print(f"  category-dominated {cat_dom_n} | feature-dominated {feat_dom_n}")
        print(f"  bonus_usefulness>0: {bu_pos}/853 | noble_gain>0: {ng_pos}/853")
        print(f"  score_gap p50 {gaps_sorted[len(gaps_sorted)//2]:,} "
              f"[{gaps_sorted[0]:,}, {gaps_sorted[-1]:,}]")

    verdict = "ACTIONABLE_HYPOTHESIS_FOUND" if nominee else "NO_ACTIONABLE_PATTERN"
    result = {
        "format": "effective-splendor-s2-result",
        "version": 2,
        "experiment_id": "s2-heuristic-win-attribution-v1",
        "repair": "repair-1 (per final review of 96a09c6): Buy term mapping fixed "
                  "(category_base=SCORE_BUY; prestige separate); seat-stratified "
                  "exposure tables added; nominee annotations restricted to the "
                  "exact 853 SEARCH_ACTOR take->buy occurrences; A1 census rows "
                  "NOT regenerated",
        "design_doc": "docs/s2-heuristic-win-attribution.md @ 82fc400 (DESIGN_V2)",
        "a1_note": "unchanged from 12ec3c5 (rows identical; H* and search actions "
                   "do not depend on term decomposition)",
        "a2": {
            "strict_divergences": len(strict),
            "dominant_terms": dict(dominant_counts),
            "category_dominated": cat_dom,
            "feature_dominated": feat_dom,
        },
        "a3": {
            "search_actor_total": search_actor_total,
            "candidates": candidates,
            "nominee": nominee,
            "gate4_rationale": {
                "take_tokens->buy_market": "implementable as an n1 decision "
                "overlay that triggers only when n1 selects TakeTokens and "
                "heuristic has a unique BuyMarket optimum; requires no new "
                "search machinery",
            },
        },
        "nominee_annotation": nominee_ann,
        "verdict": verdict,
    }
    out = REPO / "benchmarks/s2-heuristic-win-attribution-v1.result.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nA3 VERDICT (repair): {verdict}")
    if nominee:
        print(f"Nominee: {nominee['pattern']}")
    print(f"Result: {out}")


if __name__ == "__main__":
    main()
