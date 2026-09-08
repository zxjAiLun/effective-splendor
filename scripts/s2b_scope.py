#!/usr/bin/env python3
"""S2b scope measurement (DESIGN_V2 @ ff7a4f1).

Runs s2b-scope over the S0 P1 + P3 replays' n1 mover contexts, performs
the exhaustive fixed-context pointwise parity assertions, computes
trigger counts/rates, and cross-checks the P1 trigger identity set
against the S2 A1 n1-side nominee rows.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
S0_ROOT = REPO / "local-artifacts/s0-baseline-calibration"
S2_ROWS = REPO / "local-artifacts/s2-census/census-rows.jsonl"
OUT = REPO / "local-artifacts/s2b-scope"
RESULT = REPO / "benchmarks/s2b-scope-v1.result.json"


def act_key(a: dict) -> str:
    return json.dumps(a, sort_keys=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows_path = OUT / "scope-rows.jsonl"
    if rows_path.exists():
        rows_path.unlink()

    # P1: heuristic(seat depends on rotation) vs n1. n1 seat = 1 if r0, 0 if r1.
    # P3: n1 (primary) vs M07. n1 seat = 0 if r0, 1 if r1.
    corpus = {
        "P1": list(S0_ROOT.glob("p1_heuristic_vs_n1/block-*/r*/match-replay.json")),
        "P3": list(S0_ROOT.glob("p3_n1_vs_m07/block-*/r*/match-replay.json")),
    }
    for part, replays in corpus.items():
        assert len(replays) == 128, f"{part}: {len(replays)} replays"
        for rpl in sorted(replays):
            gid = f"{rpl.parent.parent.parent.name}-{rpl.parent.parent.name}-{rpl.parent.name}"
            rot = rpl.parent.name  # r0 / r1
            if part == "P1":
                n1_seat = 1 if rot == "r0" else 0
            else:
                n1_seat = 0 if rot == "r0" else 1
            r = subprocess.run(
                [str(SPLN), "s2b-scope", "--input", str(rpl), "--out", str(rows_path),
                 "--game-id", gid, "--n1-seat", str(n1_seat)],
                capture_output=True, text=True)
            if r.returncode != 0:
                print(f"FAIL: {gid}: {r.stderr[:300]}")
                sys.exit(1)
        print(f"{part}: 128 replays processed", flush=True)

    rows = [json.loads(l) for l in rows_path.read_text().splitlines() if l.strip()]
    print(f"total n1 mover contexts: {len(rows)}")

    # ---- exhaustive pointwise parity ----
    violations = []
    for row in rows:
        base, cand, trig = row["base_n1"], row["candidate"], row["triggered"]
        h_star = row["h_star"]
        if not trig:
            if act_key(cand) != act_key(base):
                violations.append((row["game_id"], row["ply"], "non-trigger candidate != base"))
        else:
            if base.get("type") != "take_tokens":
                violations.append((row["game_id"], row["ply"], "trigger but base not take"))
            if row["h_star_size"] != 1:
                violations.append((row["game_id"], row["ply"], "trigger but |H*| != 1"))
            if h_star[0].get("type") != "buy_market":
                violations.append((row["game_id"], row["ply"], "trigger but H not buy"))
            if act_key(cand) != act_key(h_star[0]):
                violations.append((row["game_id"], row["ply"], "trigger but candidate != H buy"))
        # additional parity: base_n1 must equal the recorded action (the mover
        # WAS n1 in these replays — the S0 binding).
        if act_key(base) != act_key(row["recorded_action"]):
            violations.append((row["game_id"], row["ply"], "base_n1 != recorded action"))
    if violations:
        print(f"FAIL: {len(violations)} parity violations; first 5: {violations[:5]}")
        sys.exit(1)
    print("EXHAUSTIVE POINTWISE PARITY: PASS (100% of contexts)")

    # ---- trigger counts / rates per corpus part ----
    stats = {}
    for part in ["P1", "P3"]:
        part_rows = [r for r in rows if r["game_id"].startswith("p1_") == (part == "P1")]
        n = len(part_rows)
        k = sum(1 for r in part_rows if r["triggered"])
        stats[part] = {"contexts": n, "triggers": k,
                       "rate": round(k / n, 6) if n else None}
        print(f"{part}: {k}/{n} triggers ({k/n:.4f})" if n else f"{part}: no rows")

    # ---- P1 identity cross-check vs S2 A1 ----
    s2_rows = [json.loads(l) for l in S2_ROWS.read_text().splitlines()
               if l.strip() and '"delta"' not in l]
    # S2 A1 n1-side nominee rows: game in P1, SEARCH_ACTOR (actor != heuristic
    # seat), opponent n1, strict divergence, take -> unique H buy.
    def s2_nominee_identities():
        out = set()
        for row in s2_rows:
            gid = row["game_id"]
            if not gid.startswith("p1_"):
                continue
            rot = gid.split("-")[-1]
            heuristic_seat = 0 if rot == "r0" else 1
            if row["actor_seat"] == heuristic_seat:
                continue
            a_n1 = row["a_n1"]
            if act_key(a_n1) in {act_key(a) for a in row["h_star"]}:
                continue
            if row["h_star_size"] != 1:
                continue
            if a_n1.get("type") != "take_tokens":
                continue
            if row["h_star"][0].get("type") != "buy_market":
                continue
            out.add(f"{gid}|{row['ply']}")
        return out

    s2_ids = s2_nominee_identities()
    p1_trigger_ids = {f"{r['game_id']}|{r['ply']}" for r in rows
                      if r["game_id"].startswith("p1_") and r["triggered"]}
    match = s2_ids == p1_trigger_ids
    print(f"\nP1 identity cross-check: S2 nominee rows {len(s2_ids)}, "
          f"scope triggers {len(p1_trigger_ids)}, sets equal: {match}")
    if not match:
        only_s2 = sorted(s2_ids - p1_trigger_ids)[:5]
        only_scope = sorted(p1_trigger_ids - s2_ids)[:5]
        print(f"  only-in-S2: {only_s2}")
        print(f"  only-in-scope: {only_scope}")
        sys.exit(1)
    digest = hashlib.sha256("|".join(sorted(p1_trigger_ids)).encode()).hexdigest()

    result = {
        "format": "effective-splendor-s2b-scope-result",
        "version": 1,
        "experiment_id": "s2b-scope-v1",
        "design_doc": "docs/s2b-n1-buy-overlay.md @ ff7a4f1 (DESIGN_V2 APPROVED/FROZEN)",
        "corpus": {
            "P1": "S0 p1 replays, n1 mover contexts (S2 discovery overlap)",
            "P3": "S0 p3 replays, n1 mover contexts (additional development corpus)",
        },
        "contexts": len(rows),
        "parity": "exhaustive fixed-context pointwise PASS (100%)",
        "trigger_stats": stats,
        "p1_identity_cross_check": {
            "s2_nominee_count": len(s2_ids),
            "scope_trigger_count": len(p1_trigger_ids),
            "sets_equal": match,
            "identity_set_digest": digest,
        },
    }
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nScope result: {RESULT}")


if __name__ == "__main__":
    main()
