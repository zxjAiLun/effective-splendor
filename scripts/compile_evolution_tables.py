import json
from pathlib import Path

ROOT = Path(".")

def get_pairing_stats(artifact_dir, result_json_path, opponent):
    res = json.load(open(ROOT / result_json_path, "r", encoding="utf-8"))
    pairing_res = next(p for p in res["pairings"] if p["opponent"] == opponent)

    r0 = json.load(open(ROOT / artifact_dir / f"metrics_{opponent}_r0.json", "r", encoding="utf-8"))
    r1 = json.load(open(ROOT / artifact_dir / f"metrics_{opponent}_r1.json", "r", encoding="utf-8"))

    # In r0: Candidate is P0, Opponent is P1
    cand_p0 = r0["seat_p0_first"]
    opp_p1 = r0["seat_p1_second"]

    # In r1: Candidate is P1, Opponent is P0
    cand_p1 = r1["seat_p1_second"]
    opp_p0 = r1["seat_p0_first"]

    matches = pairing_res["matches"]
    w = pairing_res["wins"]
    t = pairing_res["ties"]
    l = pairing_res["losses"]
    wr = pairing_res.get("win_rate_percent", (w + 0.5 * t) / matches * 100)
    ci_lo = pairing_res["ci_95_bps"][0] / 100.0
    ci_hi = pairing_res["ci_95_bps"][1] / 100.0

    # Seat winrates
    if "seat_p0_first" in pairing_res:
        s0_wr = pairing_res["seat_p0_first"]["win_rate_percent"]
        s1_wr = pairing_res["seat_p1_second"]["win_rate_percent"]
    else:
        s0_wr = (cand_p0["wins"] + 0.5 * cand_p0["ties"]) / (matches / 2) * 100
        s1_wr = (cand_p1["wins"] + 0.5 * cand_p1["ties"]) / (matches / 2) * 100

    # Prestige
    cand_prestige = (cand_p0["mean_prestige"] + cand_p1["mean_prestige"]) / 2.0
    opp_prestige = (opp_p0["mean_prestige"] + opp_p1["mean_prestige"]) / 2.0

    # Mean turns across all games
    mean_turns = (r0["mean_turns"] + r1["mean_turns"]) / 2.0
    cand_vp_turn = cand_prestige / mean_turns
    opp_vp_turn = opp_prestige / mean_turns

    mean_plies = (r0["mean_plies"] + r1["mean_plies"]) / 2.0
    cand_vp_ply = cand_prestige / mean_plies
    opp_vp_ply = opp_prestige / mean_plies

    # Cards / Discounts
    cand_cards = (cand_p0["mean_permanent_bonuses"] + cand_p1["mean_permanent_bonuses"]) / 2.0
    opp_cards = (opp_p0["mean_permanent_bonuses"] + opp_p1["mean_permanent_bonuses"]) / 2.0

    # VP Tier Distribution: [0, 1, 2, 3, 4, 5]
    c_vp0 = cand_p0.get("mean_cards_by_vp", {})
    c_vp1 = cand_p1.get("mean_cards_by_vp", {})
    o_vp0 = opp_p0.get("mean_cards_by_vp", {})
    o_vp1 = opp_p1.get("mean_cards_by_vp", {})

    cand_vps = [(c_vp0.get(str(v), 0.0) + c_vp1.get(str(v), 0.0)) / 2.0 for v in range(6)]
    opp_vps = [(o_vp0.get(str(v), 0.0) + o_vp1.get(str(v), 0.0)) / 2.0 for v in range(6)]

    cand_vp_dist = " / ".join(f"{v:.2f}" for v in cand_vps)
    opp_vp_dist = " / ".join(f"{v:.2f}" for v in opp_vps)

    # Reserves
    cand_res_acq = (cand_p0["mean_reserves_acquired"] + cand_p1["mean_reserves_acquired"]) / 2.0
    cand_res_bought = (cand_p0["mean_reserves_bought"] + cand_p1["mean_reserves_bought"]) / 2.0
    cand_res_stranded = (cand_p0["mean_reserves_stranded"] + cand_p1["mean_reserves_stranded"]) / 2.0
    cand_redemption = 100.0 * cand_res_bought / max(cand_res_acq, 1e-6)

    opp_res_acq = (opp_p0["mean_reserves_acquired"] + opp_p1["mean_reserves_acquired"]) / 2.0
    opp_res_bought = (opp_p0["mean_reserves_bought"] + opp_p1["mean_reserves_bought"]) / 2.0
    opp_res_stranded = (opp_p0["mean_reserves_stranded"] + opp_p1["mean_reserves_stranded"]) / 2.0
    opp_redemption = 100.0 * opp_res_bought / max(opp_res_acq, 1e-6)

    # Nobles
    cand_nobles = (cand_p0["mean_nobles"] + cand_p1["mean_nobles"]) / 2.0
    opp_nobles = (opp_p0["mean_nobles"] + opp_p1["mean_nobles"]) / 2.0

    # Timing
    wall_sec = pairing_res["total_match_wall_seconds"]
    sec_per_game = wall_sec / matches

    verdict = pairing_res.get("exploratory_verdict", "EXPLORATORY_STRONGER" if wr > 50 else "UNRESOLVED")

    return {
        "opponent": opponent,
        "matches": matches,
        "record": f"{w} - {t} - {l}",
        "win_rate": wr,
        "ci": f"[{ci_lo:.2f}%, {ci_hi:.2f}%]",
        "seat0_wr": s0_wr,
        "seat1_wr": s1_wr,
        "cand_prestige": cand_prestige,
        "opp_prestige": opp_prestige,
        "prestige_diff": cand_prestige - opp_prestige,
        "cand_vp_turn": cand_vp_turn,
        "opp_vp_turn": opp_vp_turn,
        "cand_vp_ply": cand_vp_ply,
        "opp_vp_ply": opp_vp_ply,
        "cand_cards": cand_cards,
        "opp_cards": opp_cards,
        "cand_vp_dist": cand_vp_dist,
        "opp_vp_dist": opp_vp_dist,
        "cand_res": f"{cand_res_acq:.2f} / {cand_res_bought:.2f} / {cand_res_stranded:.2f} (兑现率 {cand_redemption:.1f}%)",
        "opp_res": f"{opp_res_acq:.2f} / {opp_res_bought:.2f} / {opp_res_stranded:.2f} (兑现率 {opp_redemption:.1f}%)",
        "nobles": f"{cand_nobles:.2f} vs {opp_nobles:.2f} 个",
        "time": f"{wall_sec:.1f} 秒 ({sec_per_game:.3f} 秒/局)",
        "verdict": verdict,
    }

def main():
    versions = [
        ("heuristic-v0.2.9", "local-artifacts/s4-heuristic-v029-pilot", "benchmarks/s4-heuristic-v029-pilot-v1.result.json", ["heuristic-v028", "s3-rollout", "heuristic-v01"]),
        ("heuristic-v0.3.0", "local-artifacts/s4-heuristic-v030-pilot", "benchmarks/s4-heuristic-v030-pilot-v1.result.json", ["heuristic-v029", "heuristic-v028", "s3-rollout", "heuristic-v01"]),
        ("heuristic-v0.3.1", "local-artifacts/s4-heuristic-v031-pilot", "benchmarks/s4-heuristic-v031-pilot-v1.result.json", ["heuristic-v030", "heuristic-v029", "heuristic-v028", "s3-rollout", "heuristic-v01"]),
        ("heuristic-v0.3.2", "local-artifacts/s4-heuristic-twoply-pilot", "benchmarks/s4-heuristic-twoply-pilot-v1.result.json", ["heuristic-v031", "heuristic-v030", "heuristic-v029", "s3-rollout", "heuristic-v01"]),
        ("heuristic-v0.3.2a", "local-artifacts/s4-heuristic-v032a-pilot", "benchmarks/s4-heuristic-v032a-pilot-v1.result.json", ["heuristic-v031", "heuristic-v030", "heuristic-v029", "s3-rollout", "heuristic-v01"])
    ]

    for vname, art_dir, res_json, opps in versions:
        print(f"\n==================== {vname} ====================")
        for opp in opps:
            st = get_pairing_stats(art_dir, res_json, opp)
            print(f"vs {opp}: {st['record']} ({st['win_rate']:.2f}%) CI {st['ci']} | VP: {st['cand_prestige']:.2f} vs {st['opp_prestige']:.2f} | Cards: {st['cand_cards']:.2f} vs {st['opp_cards']:.2f} | VP Dist: [{st['cand_vp_dist']}] vs [{st['opp_vp_dist']}]")

if __name__ == "__main__":
    main()
