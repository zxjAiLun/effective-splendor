import json
from pathlib import Path

opps = ["heuristic-v030", "heuristic-v029", "heuristic-v028", "s3-rollout", "heuristic-v01"]
manifest = json.load(open("local-artifacts/s4-heuristic-v031-pilot/manifest.json", "r", encoding="utf-8"))
res = json.load(open("benchmarks/s4-heuristic-v031-pilot-v1.result.json", "r", encoding="utf-8"))

lines = []
lines.append("# S4 Heuristic v0.3.1 Pilot Evaluation Tables")
lines.append("")
lines.append("### 表 1：全基线对抗总览 (Head-to-Head Overview，1280 局双换座)")
lines.append("| 对手基线 | 对局数 | 胜-平-负 | 胜率 (%) | 95% Bootstrap CI | 中心分 (bps) | 探索性裁决 | 平均 Plies | 总耗时 (s) |")
lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
for p in res["pairings"]:
    ci_lo = p["ci_95_bps"][0] / 100.0
    ci_hi = p["ci_95_bps"][1] / 100.0
    lines.append(f"| **{p['opponent']}** | {p['matches']} | {p['wins']}-{p['ties']}-{p['losses']} | **{p['win_rate_percent']:.2f}%** | [{ci_lo:.2f}%, {ci_hi:.2f}%] | {p['center_bps']:.1f} | `{p['exploratory_verdict']}` | {p['mean_plies']:.2f} | {p['total_match_wall_seconds']:.1f} |")

lines.append("")
lines.append("### 表 2：先后手胜率与平衡性 (Seat Fairness & First/Second Advantage)")
lines.append("| 对手基线 | 先手 (P0 First) 胜-平-负 | 先手胜率 (%) | 后手 (P1 Second) 胜-平-负 | 后手胜率 (%) | 先后手落差 (pp) |")
lines.append("| :--- | :---: | :---: | :---: | :---: | :---: |\n")
for p in res["pairings"]:
    p0 = p["seat_p0_first"]
    p1 = p["seat_p1_second"]
    rec0 = f"{p0['wins']}-{p0['ties']}-{p0['losses']}"
    rec1 = f"{p1['wins']}-{p1['ties']}-{p1['losses']}"
    wr0 = f"{p0['win_rate_percent']:.2f}%"
    wr1 = f"{p1['win_rate_percent']:.2f}%"
    diff = p0["win_rate_percent"] - p1["win_rate_percent"]
    lines.append(f"| **{p['opponent']}** | {rec0} | **{wr0}** | {rec1} | **{wr1}** | {diff:+.2f} |")

lines.append("")
lines.append("### 表 3：得分速率与宏观节奏 (Scoring Velocity & Macro Tempo)")
lines.append("| 对手基线 | v0.3.1 均分 | 对手均分 | 分差 | v0.3.1 VP/Turn | 对手 VP/Turn | 平均回合 | 回合范围 [Min-Med-Max] | 紧凑局 (分差≤2) % |")
lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
for opp in opps:
    m = json.load(open(f"local-artifacts/s4-heuristic-v031-pilot/metrics_{opp}.json", "r", encoding="utf-8"))
    rows = [r for r in manifest["rows"] if r["opponent"] == opp]
    c_scores = [r["scores"][r["candidate_seat"]] for r in rows]
    o_scores = [r["scores"][1 - r["candidate_seat"]] for r in rows]
    c_vp = sum(c_scores) / len(c_scores)
    o_vp = sum(o_scores) / len(o_scores)
    diff = c_vp - o_vp
    mean_turns = m["mean_turns"]
    c_vp_turn = c_vp / mean_turns
    o_vp_turn = o_vp / mean_turns
    rng = f"[{m['min_turns']} - {int(m['median_turns'])} - {m['max_turns']}]"
    lines.append(f"| **{opp}** | **{c_vp:.2f}** | {o_vp:.2f} | **{diff:+.2f}** | **{c_vp_turn:.3f}** | {o_vp_turn:.3f} | {mean_turns:.2f} | {rng} | {m['close_games_margin_le_2_percent']:.1f}% |")

lines.append("")
lines.append("### 表 4：宏观局均统计与结构对比 (Batch Macro & Resource Indicators)")
lines.append("| 对手基线 | 局均 Plies | 局均贵族/人 | 拿贵族局占比 (%) | 局均卡牌数/人 | 局均预留/人 | 预留兑现率 (%) | 紧凑局占比 (%) |")
lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
for opp in opps:
    m = json.load(open(f"local-artifacts/s4-heuristic-v031-pilot/metrics_{opp}.json", "r", encoding="utf-8"))
    p0 = m["seat_p0_first"]
    p1 = m["seat_p1_second"]
    avg_cards = (p0["mean_permanent_bonuses"] + p1["mean_permanent_bonuses"]) / 2.0
    avg_res_acq = (p0["mean_reserves_acquired"] + p1["mean_reserves_acquired"]) / 2.0
    avg_res_bought = (p0["mean_reserves_bought"] + p1["mean_reserves_bought"]) / 2.0
    redemption_pct = 100.0 * avg_res_bought / max(avg_res_acq, 1e-6)
    noble_pct = (p0["games_with_nobles_percent"] + p1["games_with_nobles_percent"]) / 2.0
    lines.append(f"| **{opp}** | {m['mean_plies']:.2f} | {m['overall_mean_nobles_per_player']:.3f} | {noble_pct:.1f}% | {avg_cards:.2f} | {avg_res_acq:.2f} | {redemption_pct:.1f}% | {m['close_games_margin_le_2_percent']:.1f}% |")

content = "\n".join(lines) + "\n"
with open("local-artifacts/s4-heuristic-v031-pilot/evaluation_tables.md", "w", encoding="utf-8") as f:
    f.write(content)
print("Saved evaluation_tables.md")
