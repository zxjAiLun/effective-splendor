#!/usr/bin/env python3
"""S2 A1: set-aware disagreement census over the 256 heuristic-participating
S0 replays (DESIGN_V2 frozen contract in docs/s2-heuristic-win-attribution.md).

Consumes s2-census JSONL rows, classifies per context (set-aware, actor-role
separated), and computes GAME-level exposure win association stratified by
opponent and heuristic seat. All gates fail-closed.
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
HEURISTIC_SEED = 20260812
SAMPLE_SEED = 20260703

PAIRINGS = {
    "p1_heuristic_vs_n1": "n1",
    "p2_heuristic_vs_m07": "M07",
}


def act_key(a: dict) -> str:
    """Canonical comparable action key (type + params)."""
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
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows_path = OUT_ROOT / "census-rows.jsonl"
    if rows_path.exists():
        rows_path.unlink()

    total_games = 0
    for pairing, opp in PAIRINGS.items():
        replays = sorted(S0_ROOT.glob(f"{pairing}/block-*/r*/match-replay.json"))
        assert len(replays) == 128, f"{pairing}: {len(replays)} replays"
        for rpl in replays:
            # game_id encodes pairing/block/rotation; heuristic seat from pairing+rotation
            game_id = f"{rpl.parent.parent.parent.name}-{rpl.parent.parent.name}-{rpl.parent.name}"
            # rotation r0: seat0 = primary. p1/p2 primary = heuristic-v1.
            rot = rpl.parent.name  # r0 or r1
            heuristic_seat = 0 if rot == "r0" else 1
            r = subprocess.run(
                [str(SPLN), "s2-census", "--input", str(rpl), "--out", str(rows_path),
                 "--game-id", game_id, "--heuristic-seed", str(HEURISTIC_SEED),
                 "--sample-seed", str(SAMPLE_SEED)],
                capture_output=True, text=True)
            if r.returncode != 0:
                print(f"FAIL: census failed {game_id}: {r.stderr[:300]}")
                sys.exit(1)
            total_games += 1
        print(f"{pairing}: 128 replays processed ({total_games} total)", flush=True)

    rows = [json.loads(l) for l in rows_path.read_text().splitlines() if l.strip()]
    print(f"total contexts: {len(rows)} across {total_games} games")

    # ---- game metadata ----
    game_meta = {}
    for row in rows:
        gid = row["game_id"]
        if gid not in game_meta:
            pairing = "p1_heuristic_vs_n1" if gid.startswith("p1_") else "p2_heuristic_vs_m07"
            rot = gid.split("-")[-1]
            game_meta[gid] = {
                "opponent": PAIRINGS[pairing],
                "heuristic_seat": 0 if rot == "r0" else 1,
                "winners": row["winners"],
            }

    def h_won(gid: str) -> bool:
        g = game_meta[gid]
        return g["heuristic_seat"] in g["winners"] and len(g["winners"]) == 1

    # ---- parity gates ----
    # We need the mover identity per row: actor_seat vs heuristic_seat, and the
    # pairing determines whether the search mover is n1 or M07. The census rows
    # carry both frozen search actions; the recorded action must equal the
    # mover policy's recomputation.
    parity_fail = []
    for row in rows:
        gid = row["game_id"]
        g = game_meta[gid]
        is_heuristic_mover = row["actor_seat"] == g["heuristic_seat"]
        rec = row["recorded_action"]
        if is_heuristic_mover:
            # REFERENCE_ACTOR parity: recorded in H*.
            h_star_keys = {act_key(a) for a in row["h_star"]}
            if act_key(rec) not in h_star_keys:
                parity_fail.append((gid, row["ply"], "recorded not in H*"))
            if row["h_star_size"] == 1 and act_key(rec) != act_key(row["h_star"][0]):
                parity_fail.append((gid, row["ply"], "unique H* mismatch"))
        else:
            # SEARCH_ACTOR parity: recorded == that opponent's recomputed action.
            if g["opponent"] == "n1":
                if act_key(rec) != act_key(row["a_n1"]):
                    parity_fail.append((gid, row["ply"], "n1 recomputation mismatch"))
            else:
                if act_key(rec) != act_key(row["a_m07"]):
                    parity_fail.append((gid, row["ply"], "M07 recomputation mismatch"))
    if parity_fail:
        print(f"FAIL: {len(parity_fail)} parity violations; first 5: {parity_fail[:5]}")
        sys.exit(1)
    print("PARITY GATES: PASS (100% of contexts)")

    # ---- set-aware classification ----
    stats = defaultdict(int)
    by_role = {"REFERENCE_ACTOR": 0, "SEARCH_ACTOR": 0}
    strict_div = []  # rows that are strict divergences for the acting opponent
    tie_rate = defaultdict(int)
    for row in rows:
        gid = row["game_id"]
        g = game_meta[gid]
        is_heuristic_mover = row["actor_seat"] == g["heuristic_seat"]
        role = "REFERENCE_ACTOR" if is_heuristic_mover else "SEARCH_ACTOR"
        by_role[role] += 1
        stats[f"role={role}"] += 1
        if row["h_star_size"] > 1:
            tie_rate[role] += 1
        # classification vs the OPPONENT in this game (both search actions
        # recomputed; the game's opponent is the relevant one)
        a_opp = row["a_n1"] if g["opponent"] == "n1" else row["a_m07"]
        if act_key(a_opp) in {act_key(a) for a in row["h_star"]}:
            cls = "X_IN_H*"
        elif row["h_star_size"] == 1:
            cls = "X_NOT_IN_H*_UNIQUE"
        else:
            cls = "X_NOT_IN_H*_TIE"
        stats[f"{role}:{g['opponent']}:{cls}"] += 1
        if cls == "X_NOT_IN_H*_UNIQUE":
            strict_div.append((row, role, g))

    print("\nRole counts:", dict(by_role))
    print("Tie rate (|H*|>1) by role:", dict(tie_rate))
    print("\nSet-aware classification (role x opponent x class):")
    for k in sorted(stats):
        if k.startswith("role=") or ":" not in k:
            continue
        print(f"  {k}: {stats[k]}")

    # ---- strict divergence transition distribution (SEARCH_ACTOR only) ----
    transitions = defaultdict(int)
    search_actor_total = by_role["SEARCH_ACTOR"]
    for row, role, g in strict_div:
        if role != "SEARCH_ACTOR":
            continue
        h_action = row["h_star"][0]
        s_action = row["recorded_action"]
        trans = f"{action_type(s_action)}->{action_type(h_action)}"
        transitions[trans] += 1
    print(f"\nSEARCH_ACTOR strict divergence transitions (total {search_actor_total} contexts):")
    for k, v in sorted(transitions.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v} ({v / search_actor_total:.4f} of SEARCH_ACTOR contexts)")

    # ---- game-level exposure win association, stratified ----
    print("\nGame-level exposure analysis (top transitions, stratified):")
    report = {}
    for trans in sorted(transitions, key=lambda k: -transitions[k])[:8]:
        report[trans] = {}
        for opp in ["n1", "M07"]:
            exposed = {gid for row, role, g in strict_div
                       if role == "SEARCH_ACTOR" and g["opponent"] == opp
                       and f"{action_type(row['recorded_action'])}->{action_type(row['h_star'][0])}" == trans
                       for gid in [row["game_id"]]}
            all_gids = {gid for gid, g in game_meta.items() if g["opponent"] == opp}
            unexposed = all_gids - exposed
            e_win = sum(1 for gid in exposed if h_won(gid))
            u_win = sum(1 for gid in unexposed if h_won(gid))
            e_rate = e_win / len(exposed) if exposed else float("nan")
            u_rate = u_win / len(unexposed) if unexposed else float("nan")
            report[trans][opp] = {
                "exposed_games": len(exposed), "exposed_h_wins": e_win,
                "exposed_rate": round(e_rate, 4) if exposed else None,
                "unexposed_games": len(unexposed), "unexposed_h_wins": u_win,
                "unexposed_rate": round(u_rate, 4) if unexposed else None,
                "delta": round(e_rate - u_rate, 4) if exposed and unexposed else None,
                "wilson_exposed": [round(x, 4) for x in wilson(e_win, len(exposed))] if exposed else None,
            }
            print(f"  {trans} [{opp}]: exposed {e_win}/{len(exposed)} ({e_rate:.3f}) "
                  f"vs unexposed {u_win}/{len(unexposed)} ({u_rate:.3f}) delta {e_rate-u_rate:+.3f}")

    # save intermediate
    out = OUT_ROOT / "a1_summary.json"
    out.write_text(json.dumps({
        "total_games": total_games,
        "total_contexts": len(rows),
        "role_counts": dict(by_role),
        "tie_rate": {k: v for k, v in tie_rate.items()},
        "classification": {k: v for k, v in stats.items() if ":" in k},
        "search_actor_transitions": dict(transitions),
        "search_actor_total": search_actor_total,
        "exposure_report": report,
    }, indent=2))
    print(f"\nA1 summary written: {out}")


if __name__ == "__main__":
    main()
