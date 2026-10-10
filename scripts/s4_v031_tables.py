import json
from pathlib import Path

res_path = Path("benchmarks/s4-heuristic-v031-pilot-v1.result.json")
res = json.load(open(res_path, "r", encoding="utf-8"))

print("### 表 1：全基线对抗总览 (Head-to-Head Overview，1280 局双换座)")
print("| 对手基线 | 对局数 | 胜-平-负 | 胜率 (%) | 95% Bootstrap CI | 中心分 (bps) | 探索性裁决 | 平均 Plies | 总耗时 (s) |")
print("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
for p in res["pairings"]:
    ci_lo = p["ci_95_bps"][0] / 100.0
    ci_hi = p["ci_95_bps"][1] / 100.0
    opp = p["opponent"]
    matches = p["matches"]
    rec = f"{p['wins']}-{p['ties']}-{p['losses']}"
    wr = f"{p['win_rate_percent']:.2f}%"
    ci = f"[{ci_lo:.2f}%, {ci_hi:.2f}%]"
    bps = f"{p['center_bps']:.1f}"
    erd = p["exploratory_verdict"]
    plies = f"{p['mean_plies']:.2f}"
    sec = f"{p['total_match_wall_seconds']:.1f}"
    print(f"| **{opp}** | {matches} | {rec} | **{wr}** | {ci} | {bps} | `{erd}` | {plies} | {sec} |")

print("\n### 表 2：先后手胜率与平衡性 (Seat Fairness & First/Second Advantage)")
print("| 对手基线 | 先手 (P0 First) 胜-平-负 | 先手胜率 (%) | 后手 (P1 Second) 胜-平-负 | 后手胜率 (%) | 先后手落差 (pp) |")
print("| :--- | :---: | :---: | :---: | :---: | :---: |")
for p in res["pairings"]:
    opp = p["opponent"]
    p0 = p["seat_p0_first"]
    p1 = p["seat_p1_second"]
    rec0 = f"{p0['wins']}-{p0['ties']}-{p0['losses']}"
    rec1 = f"{p1['wins']}-{p1['ties']}-{p1['losses']}"
    wr0 = f"{p0['win_rate_percent']:.2f}%"
    wr1 = f"{p1['win_rate_percent']:.2f}%"
    diff = p0["win_rate_percent"] - p1["win_rate_percent"]
    diff_str = f"{diff:+.2f}"
    print(f"| **{opp}** | {rec0} | **{wr0}** | {rec1} | **{wr1}** | {diff_str} |")
