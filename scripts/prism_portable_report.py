"""Offline M57 replay validation and full model-oriented Markdown results."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import time

import numpy as np

ACTIONS = ("buy_market", "buy_reserved", "take_tokens", "reserve_market",
           "reserve_deck", "choose_noble", "pass")
COLORS = ("White", "Blue", "Green", "Red", "Black")
LABELS = {"heuristic-v031": "本轮源码快照 Heuristic", "prism-v01": "Prism v0.1.0"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                                    allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def table(columns, rows):
    return "\n".join(["| " + " | ".join(map(str, columns)) + " |",
                      "| " + " | ".join("---" for _ in columns) + " |"] +
                     ["| " + " | ".join(map(str, r)) + " |" for r in rows]) + "\n"


def num(value, percent=False):
    return "NOT_MEASURED" if value is None else f"{value:.3f}" + ("%" if percent else "")


def paired_ci(rows, pure=False):
    pairs = defaultdict(dict)
    for row in rows:
        pairs[row["seed"]][row["actor"]] = float(row["record"] == "win") if pure else row["score"]
    require(all(set(p) == {0, 1} for p in pairs.values()), "incomplete physical-seat pair")
    blocks = np.array([sum(p.values()) / 2 for _, p in sorted(pairs.items())])
    rng = np.random.default_rng(57049999)
    samples = blocks[rng.integers(0, len(blocks), (20000, len(blocks)))].mean(1)
    return {"estimate": float(blocks.mean()), "ci95": np.quantile(samples, [.025, .975]).tolist(),
            "seed_blocks": len(blocks), "resamples": 20000, "bootstrap_seed": 57049999,
            "scope": "descriptive paired-seed bootstrap; one-block CI is degenerate"}


def player(rows, batches, candidate):
    n = len(rows)
    points = sum(r["candidate_vp" if candidate else "opponent_vp"] for r in rows)
    action = Counter()
    for r in rows:
        action.update(r["candidate_actions" if candidate else "opponent_actions"])
    total = sum(action.values())
    mean = lambda k: sum(m[k] * count for m, count in batches) / n
    out = {k: mean(k) for k in ("mean_prestige", "mean_nobles", "mean_permanent_bonuses",
                                "mean_reserves_acquired", "mean_reserves_bought", "mean_reserves_stranded")}
    out["mean_cards_by_vp"] = {v: sum(m["mean_cards_by_vp"].get(v, 0) * c for m, c in batches) / n
                               for v in map(str, range(6))}
    out["mean_bonuses_by_color"] = {v: sum(m["mean_bonuses_by_color"].get(v, 0) * c for m, c in batches) / n
                                    for v in COLORS}
    out["noble_coverage_percent"] = 100 * sum(m["games_with_nobles"] for m, _ in batches) / n
    native = {a: sum(m["action_distribution"].get(a, 0) for m, _ in batches) for a in ACTIONS}
    require(native == {a: action[a] for a in ACTIONS}, "model-oriented action mixing")
    require(math.isclose(out["mean_prestige"], points / n, abs_tol=1e-9), "model-oriented VP mixing")
    cards = out["mean_cards_by_vp"]
    require(math.isclose(sum(cards.values()), out["mean_permanent_bonuses"], abs_tol=1e-9), "card conservation")
    require(math.isclose(sum(int(v) * x for v, x in cards.items()) + 3 * out["mean_nobles"],
                         points / n, abs_tol=1e-9), "card/noble VP conservation")
    require(math.isclose(out["mean_permanent_bonuses"], (action["buy_market"] + action["buy_reserved"]) / n,
                         abs_tol=1e-9), "buy/discount conservation")
    acquired = action["reserve_market"] + action["reserve_deck"]
    bought = action["buy_reserved"]
    require(math.isclose(out["mean_reserves_stranded"], (acquired-bought) / n, abs_tol=1e-9), "reserve conservation")
    out.update(total_decisions=total, main_actions=total-action["choose_noble"],
               vp_per_decision=points/total, vp_per_main=points/(total-action["choose_noble"]),
               vp_per_global_ply=points/sum(r["plies"] for r in rows),
               reserve_redemption_percent=100*bought/acquired if acquired else None,
               actions={a: {"count": action[a], "percent": 100*action[a]/total} for a in ACTIONS})
    wins = sum(r["record"]==("win" if candidate else "loss") for r in rows)
    draws = sum(r["record"]=="draw" for r in rows)
    out.update(games=n,wins=wins,ties=draws,losses=n-wins-draws,
               win_rate_percent=100*wins/n,score_rate=(wins+.5*draws)/n)
    return out


def macro(rows):
    plies = [r["plies"] for r in rows]
    rounds = [(p+1)//2 for p in plies]
    main = [(sum(r["candidate_actions"].values())+sum(r["opponent_actions"].values())
             -r["candidate_actions"].get("choose_noble",0)-r["opponent_actions"].get("choose_noble",0)+1)//2 for r in rows]
    margins = [abs(r["candidate_vp"]-r["opponent_vp"]) for r in rows]
    walls = [r["wall_seconds"] for r in rows]
    return {"total_games":len(rows),"total_plies":sum(plies),"mean_plies":statistics.mean(plies),
            "mean_turns":statistics.mean(rounds),"median_turns":statistics.median(rounds),
            "min_turns":min(rounds),"max_turns":max(rounds),"std_turns":statistics.pstdev(rounds),
            "mean_main_rounds":statistics.mean(main),"mean_victory_margin":statistics.mean(margins),
            "close_games_margin_le_2_percent":100*sum(x<=2 for x in margins)/len(rows),
            "game_wall_seconds_sum":sum(walls),"game_wall_seconds_mean":statistics.mean(walls),
            "game_wall_seconds_p95":float(np.quantile(walls,.95)),
            "decision_latency_ms":"NOT_MEASURED","inference_latency_ms":"NOT_MEASURED"}


def collect(art):
    groups, campaigns, seen = defaultdict(list), [], set()
    for parent in (art/"campaigns", art/"cloud1-evidence/campaigns"):
        for camp in sorted(parent.iterdir()):
            owner, spec = read(camp/"ownership.json"), read(camp/"contract.json")
            host, line = owner["host_id"], owner["line"]
            status = read(camp/"control/status.json")
            require(status["status"] in ("STOPPED_COMMITTED", "STOPPED_BOUNDARY"), "unfinished campaign")
            campaigns.append({"path": str(camp), "line": line, "host": host, "ownership": owner,
                              "status": status, "contract_sha256": sha(camp/"contract.json"),
                              "resource_ledger": read(camp/"resource-ledger.json"),
                              "cycles": [read(p) for p in sorted(camp.glob("cycle-*-portable-summary.json"))]})
            jobs = {j["job_id"]: (i+1, j) for i, cycle in enumerate(spec["cycles"]) for j in cycle}
            for done in sorted((camp/"attempts").glob("*/completion.json")):
                c = read(done)
                cycle, job = jobs[c["job"]["job_id"]]
                require(c["job"] == job and c["contract"] == spec, "completion provenance mismatch")
                unique = (host, line, job["job_id"])
                require(unique not in seen, "completed game duplicated")
                seen.add(unique)
                path, hashes = done.parent, {}
                for name in ("replay", "report", "sidecar"):
                    file = path/(name+(".jsonl" if name=="sidecar" else ".json"))
                    hashes[name] = sha(file)
                    require(hashes[name] == c["files"][name]["sha256"], "saved game artifact drift")
                hashes.update(completion=sha(done), process_result=sha(path/"process-result.json"),
                              arena_config=sha(path/"arena-config.json"))
                replay, report = read(path/"replay.json"), read(path/"report.json")
                outcome = report["outcome"]
                require(outcome["status"] == "completed" and outcome["result"] == replay["result"], "invalid terminal game")
                require(replay["seed"] == job["environment_seed"] and len(replay["steps"]) == outcome["completed_plies"],
                        "seed/ply mismatch")
                actor, actions = job["actor"], [Counter(), Counter()]
                for step in replay["steps"]:
                    actions[step["actor"]][step["action"]["type"]] += 1
                ranks = replay["result"]["ranks"]
                score = .5 if ranks[0] == ranks[1] else float(ranks[actor] < ranks[1-actor])
                row = {"host": host, "line": line, "cycle": cycle, "job_id": job["job_id"],
                       "opponent_id": job["opponent_id"], "actor": actor, "seed": job["environment_seed"],
                       "record": "win" if score==1 else "draw" if score==.5 else "loss", "score": score,
                       "candidate_vp": replay["result"]["scores"][actor],
                       "opponent_vp": replay["result"]["scores"][1-actor], "plies": len(replay["steps"]),
                       "candidate_actions": dict(actions[actor]), "opponent_actions": dict(actions[1-actor]),
                       "wall_seconds": c["resources"]["wall_seconds"], "resources": c["resources"],
                       "behavior_id": c["behavior_id"], "snapshot_sha256": c["snapshot_sha256"],
                       "opponent_identity": spec["run"]["opponents"][job["opponent_id"]],
                       "runtime_engine_sha256": spec["arena"]["sha256"], "hashes": hashes,
                       "local_replay": str(path/"replay.json"), "original_artifacts": c["files"]}
                require(c["resources"]["returncode"] == 0 and row["wall_seconds"] > 0, "failed/unmeasured process")
                groups[(line, host, cycle, job["opponent_id"])].append(row)
    require(len(seen) == 92, "frozen completed-game count mismatch")
    result, work = [], art/"match-metrics"
    work.mkdir(exist_ok=True)
    for index, (key, rows) in enumerate(sorted(groups.items())):
        line, host, cycle, opp = key
        require(len({r["behavior_id"] for r in rows}) == 1, "different models mixed")
        a, b, receipts = [], [], []
        for seat in (0, 1):
            subset = [r for r in rows if r["actor"] == seat]
            manifest, output = work/f"g{index}-s{seat}.manifest.json", work/f"g{index}-s{seat}.metrics.json"
            write(manifest, {"rows": [{"replay_path": r["local_replay"]} for r in subset]})
            argv = [str(art/"build/release/examples/s4_batch_metrics.exe"), str(manifest), str(output)]
            start = time.perf_counter()
            p = subprocess.run(argv, capture_output=True, text=True, timeout=120)
            require(p.returncode == 0, "independent replay analysis failed: "+p.stderr)
            metric = read(output)
            require(metric["total_games"] == len(subset), "Rust replay count mismatch")
            seats = [metric["seat_p0_first"], metric["seat_p1_second"]]
            a.append((seats[seat], len(subset)))
            b.append((seats[1-seat], len(subset)))
            receipts.append({"argv": argv, "exit_code": p.returncode, "seconds": time.perf_counter()-start,
                             "manifest_sha256": sha(manifest), "metrics_sha256": sha(output)})
        result.append({"line": line, "host": host, "cycle": cycle, "opponent_id": opp,
                       "label": f"{line} / {host} / 第{cycle}轮 / {LABELS[opp]}",
                       "behavior_id": rows[0]["behavior_id"], "opponent_identity": rows[0]["opponent_identity"],
                       "games": rows, "score_ci": paired_ci(rows), "win_ci": paired_ci(rows, True),
                       "candidate": player(rows, a, True), "opponent": player(rows, b, False),
                       "macro":macro(rows),"receipts": receipts})
    return campaigns, result


def group_tables(g):
    rows, a, b = g["games"], g["candidate"], g["opponent"]
    n = len(rows)
    w, d = sum(r["record"]=="win" for r in rows), sum(r["record"]=="draw" for r in rows)
    ci, pure = g["score_ci"]["ci95"], g["win_ci"]["ci95"]
    lines = ["\n### "+g["label"]+"\n",
             f"测量模型：**未发布训练检查点 c{g['cycle']-1}，采样T=1**；"
             f"对手：**{LABELS[g['opponent_id']]}，greedy**。个人表左右分别为学习模型/对手，整局指标另表。"
             "独立棋力/风格验收 **NOT_RUN**。\n",
             table(["局数/种子块", "W/D/L", "纯胜率", "半和得分率", "配对95%CI：纯胜 / 半和"],
                   [[f"{n}/{g['score_ci']['seed_blocks']}", f"{w}/{d}/{n-w-d}", num(100*w/n,True),
                     num(100*(w+.5*d)/n,True),
                     f"[{100*pure[0]:.2f}%,{100*pure[1]:.2f}%] / [{100*ci[0]:.2f}%,{100*ci[1]:.2f}%]"]])]
    if g["score_ci"]["seed_blocks"] == 1:
        lines.append("只有一个种子块，bootstrap区间退化，不能据此确认强弱或稳定性。\n")
    sr = []
    for seat in (0, 1):
        rs = [r for r in rows if r["actor"]==seat]
        sw, sd = sum(r["record"]=="win" for r in rs), sum(r["record"]=="draw" for r in rs)
        sr.append([f"P{seat}（{'先' if seat==0 else '后'}手）",len(rs),f"{sw}/{sd}/{len(rs)-sw-sd}",
                   num(100*sw/len(rs),True),num(100*(sw+.5*sd)/len(rs),True),
                   num(statistics.mean(r["candidate_vp"] for r in rs)),
                   num(statistics.mean(r["opponent_vp"] for r in rs))])
    lines.append(table(["模型物理座位","局数","W/D/L","纯胜率","半和得分率","模型VP/局","对手VP/局"],sr))
    metrics = [("最终VP/局","mean_prestige"),("VP/自身决策（含贵族选择）","vp_per_decision"),
               ("VP/自身Main","vp_per_main"),("VP/全局ply","vp_per_global_ply"),
               ("永久折扣/购卡数每局","mean_permanent_bonuses"),("贵族/局","mean_nobles"),
               ("获得贵族的对局比例%","noble_coverage_percent"),("预留获取/局","mean_reserves_acquired"),
               ("预留买回/局","mean_reserves_bought"),("终局未买回预留/局","mean_reserves_stranded"),
               ("预留买回/获取%","reserve_redemption_percent")]
    pr = [[label,num(a[k]),num(b[k])] for label,k in metrics]
    pr.extend([[f"购入{v} VP卡/局",num(a["mean_cards_by_vp"][str(v)]),
                num(b["mean_cards_by_vp"][str(v)])] for v in range(6)])
    pr.append(["购入3+ VP卡/局（描述性）",num(sum(a["mean_cards_by_vp"][str(v)] for v in (3,4,5))),
               num(sum(b["mean_cards_by_vp"][str(v)] for v in (3,4,5)))])
    pr.extend([[f"{color}永久折扣/局",num(a["mean_bonuses_by_color"][color]),
                num(b["mean_bonuses_by_color"][color])] for color in COLORS])
    lines.append(table(["个人指标","学习模型","对手"],pr))
    lines.append(table(["动作（占各自全部决策）","模型次数 / 占比","对手次数 / 占比"],
                       [[x,f"{a['actions'][x]['count']} / {num(a['actions'][x]['percent'],True)}",
                         f"{b['actions'][x]['count']} / {num(b['actions'][x]['percent'],True)}"] for x in ACTIONS]))
    plies = [r["plies"] for r in rows]
    rounds = [(x+1)//2 for x in plies]
    main_rounds = [(sum(r["candidate_actions"].values())+sum(r["opponent_actions"].values())
                    -r["candidate_actions"].get("choose_noble",0)-r["opponent_actions"].get("choose_noble",0)+1)//2 for r in rows]
    walls = [r["wall_seconds"] for r in rows]
    margins = [abs(r["candidate_vp"]-r["opponent_vp"]) for r in rows]
    lines.append(table(["全局/整局指标","实测值"],
                       [["总 / 均ply",f"{sum(plies)} / {num(statistics.mean(plies))}"],
                        ["含贵族决策轮数均 / 中位 / 最小 / 最大 / 总体SD",
                         " / ".join(num(x) for x in (statistics.mean(rounds),statistics.median(rounds),min(rounds),max(rounds),statistics.pstdev(rounds)))],
                        ["Main轮数均值",num(statistics.mean(main_rounds))],
                        ["终局绝对VP差均值",num(statistics.mean(margins))],
                        ["VP差≤2对局%",num(100*sum(x<=2 for x in margins)/n)],
                        ["对局监督墙钟均 / P95 / 总（秒）"," / ".join(num(x) for x in (statistics.mean(walls),float(np.quantile(walls,.95)),sum(walls)))],
                        ["逐决策 / 推理耗时","NOT_MEASURED / NOT_MEASURED"]]))
    lines.append("种子："+", ".join(str(x) for x in sorted({r["seed"] for r in rows}))+
                 "；行为身份 "+g["behavior_id"]+"；对手描述hash "+g["opponent_identity"]+"。\n")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact-root",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--document",type=Path,required=True)
    args = ap.parse_args()
    art = args.artifact_root.resolve()
    campaigns, groups = collect(art)
    cal = {c["host"]:c for c in campaigns if c["line"]=="m57-calibration"}
    for c in cal.values():
        require(c["status"]["resources"]["returncode"]==0 and len(c["cycles"])==2,"incomplete calibration")
        require(sum(x["groups"]["all"]["games"] for x in c["cycles"])==32,"calibration budget changed")
    repo = Path(__file__).resolve().parents[1]
    result = {"format":"prism-portable-calibration-results-v1","status":"PASS",
              "competitive_acceptance":"NOT_RUN","style_acceptance":"NOT_RUN",
              "completed_games":92,"interrupted_synthetic_attempts":2,
              "config_sha256":sha(repo/"benchmarks/m57-prism-portable-ppo.config.json"),
              "report_script_sha256":sha(__file__),"campaigns":campaigns,"groups":groups,
              "speed_ratio_local_over_cloud1":cal["local"]["status"]["resources"]["wall_seconds"] /
                                             cal["cloud1"]["status"]["resources"]["wall_seconds"]}
    evidence = [*sorted((art/"checks").glob("*.json")), art/"execution-revision-v3.json",
                art/"execution-revision-v4.json",art/"cloud1-evidence/execution-revision-v4.json",
                art/"cloud1-evidence/unit-tests-v4.json",art/"cloud1-evidence/execution-revision-v3.json",
                art/"cloud1-evidence/final-state-verification.json",
                art/"preflight.json", art/"cloud1-evidence/preflight.json"]
    result["engineering_evidence"] = [{"path":str(p),"sha256":sha(p),"receipt":read(p)} for p in evidence]
    result["transfers"] = [dict(read(p), journal_path=str(p), journal_sha256=sha(p))
                           for p in sorted((art/"transfers").glob("*.json"))]
    result["execution_revisions"] = [read(p) for p in sorted((repo/"benchmarks").glob("m57-prism-portable-ppo.execution-*.json"))]
    result["measured_calibration_execution"] = "41f5942feca75c11c0e7e5248b06c2849e09818382b24c390d9709967f31d87e"
    result["current_control_execution"] = read(repo/"benchmarks/m57-prism-portable-ppo.execution-v4.json")["code_identity"]
    result["rust_source_snapshot"] = read(art/"rust-source.json")
    result["calibration_initial_state"] = {
        h:read(art/("campaigns" if h=="local" else "cloud1-evidence/campaigns")/
               "m57-calibration-g0/initialization.json") for h in ("local","cloud1")}
    matching = []
    by_host = {h:{r["job_id"]:r for g in groups if g["line"]=="m57-calibration" and g["host"]==h
                  for r in g["games"]} for h in ("local","cloud1")}
    require(set(by_host["local"])==set(by_host["cloud1"]),"calibration schedule not matched")
    for job in sorted(by_host["local"]):
        a,b = by_host["local"][job],by_host["cloud1"][job]
        fields = ("seed","actor","record","candidate_vp","opponent_vp","plies","candidate_actions","opponent_actions")
        matching.append({"job_id":job,"outcomes_actions_match":all(a[k]==b[k] for k in fields)})
    result["matched_calibration_games"] = matching
    write(args.output,result)
    lines = ["# M57 便携PPO：校准与恢复完整对战表\n",
             "产物结论：执行、恢复与92局保存回放核验 **PASS**；检查点均未发布。"
             "竞技结论：以下为采样T=1的训练/工程数据，独立棋力验收 **NOT_RUN**。"
             "风格结论：继续 Prism Alpha v0.1.1 的大牌冲分合同，风格晋级验收 **NOT_RUN**。\n",
             "各线从固定 Prism Alpha v0.1.1 推理权重初始化，本轮建立新的优化器。"
             "第1轮使用c0、第2轮使用更新后的c1，往返恢复第3轮使用c2；"
             "这些编号是未发布检查点。Heuristic为本次源码快照运行实例，兼容握手0.2.9，"
             "不能将其比赛当成M56冻结二进制的独立棋力验收。\n",
             "## 同预算本机 → cloud1 对比\n",
             "两端均32局/2轮、相同环境/action/job种子、CPU两线程。"
             "箭头只表示方向。单次小预算校准没有速度置信区间；跨架构不承诺更新逐位相同。\n"]
    timing = [
        ("整批监督墙钟（秒，含worker启动、采样、接纳、更新、导出）",lambda c:c["status"]["resources"]["wall_seconds"]),
        ("轮内流水线墙钟合计（秒，含导出）",lambda c:sum(x["portable_cycle_wall_seconds"] for x in c["cycles"])),
        ("对局进程监督墙钟合计（秒）",lambda c:sum(x["game_wall_seconds"] for x in c["cycles"])),
        ("接纳/审计合计（秒，包含在launch中）",lambda c:sum(x["ingest_seconds"] for x in c["cycles"])),
        ("启动到接纳合计（秒，含对局与ingest）",lambda c:sum(x["launch_seconds"] for x in c["cycles"])),
        ("优化阶段合计（秒，不含导出）",lambda c:sum(x["this_session_update_seconds"] for x in c["cycles"])),
        ("整批监督CPU（秒）",lambda c:c["status"]["resources"]["cpu_seconds"])]
    compare = []
    for label,get in timing:
        first,second = get(cal["local"]),get(cal["cloud1"])
        delta = second-first
        compare.append([label,num(first),f"**{num(second)}**",f"**{'↑' if delta>0 else '↓' if delta<0 else '→'} {delta:+.3f}**"])
    lines.append(table(["测量项目 / 单位","本机基线","cloud1","有符号变化"],compare))
    lines.append(f"本次整批速度比：**cloud1为本机的 {result['speed_ratio_local_over_cloud1']:.3f} 倍**。"
                 "范围是本次同步CPU流水线与负载，不含环境下载、编译、SSH传输，"
                 "不是GPU结论，也不能直接外推为M56的256局大轮耗时。\n")
    lines.append(table(["主机","两轮更新次数","监督内存峰值MiB / 口径","开始前CPU%（1秒样本）","可用内存MiB"],
                       [[h,sum(x["optimizer_steps"] for x in cal[h]["cycles"]),
                         num(cal[h]["status"]["resources"]["peak_memory_bytes"]/1024**2)+
                         (" / Job提交量" if h=="local" else " / cgroup含缓存"),
                         num(read(art/f"checks/calibration-load-before-{h}.json")["cpu_percent_1s"]),
                         num(read(art/f"checks/calibration-load-before-{h}.json")["memory_available_bytes"]/1024**2)]
                        for h in ("local","cloud1")]))
    lines.append("Linux整批CPU包括专属slice中的supervisor与对局，Windows统计worker Job及后代。"
                 "两端内存口径不同，不能直接排序。逐决策/推理时间 **NOT_MEASURED**；"
                 "launch包含ingest，两者不能相加。监督对局墙钟从拥有进程就绪后的wait计时，"
                 "启动前配置写入和systemd派发由launch/整批时钟覆盖。\n")
    lines.append(f"本次32个匹配job中，{sum(x['outcomes_actions_match'] for x in matching)}个的"
                 "胜负、双方VP、ply与动作类型计数均相同；不同主机行为/runtime身份分别保留。"
                 "本机开跑前CPU约26.8%、cloud1约0%，可用内存也不同，"
                 "速度比是当前负载下的整条流水线测量，不能认定为硬件峰值倍数。"
                 "保存回放重新核验不增加对局。所有小样本区间均为训练描述，"
                 "相同经验块得分也可能形成退化区间，不能用于确认晋级。\n")
    lines.append("初始化检查：32项固定policy/value张量完全相同，优化器/RNG状态相同；"
                 "两个训练专用style_head初始张量的hash在两种运行环境中不同，完整初态各自保留。"
                 "因此这是相同推理权重与配置/种子的配对流水线校准，"
                 "不能称为完整训练模型逐位相同的两个克隆。"
                 "往返恢复直接复制完整源状态，两次导入的全部数值hash相同。\n")
    for kind,title in ((True,"校准对战完整表"),(False,"终止恢复与往返恢复完整表")):
        lines.append("\n## "+title+"\n")
        if not kind:
            lines.append("工程检查使用独立种子，不参与同预算速度比较；各轮按固定行为检查点分开。\n")
        lines.extend(group_tables(g) for g in groups if (g["line"]=="m57-calibration")==kind)
    lines.append("\n## 冻结来源\n")
    lines.append("[M57配置](../../benchmarks/m57-prism-portable-ppo.config.json) SHA "+result["config_sha256"]+
                 "；[M57机器结果](../../benchmarks/m57-prism-portable-ppo.result.json) SHA "+sha(args.output)+
                 "；[执行与恢复记录](../m57-prism-portable-ppo.md)。"
                 "每局配置、结果、回放、sidecar源路径/hash与原生审计回执均保存在结果games清单。\n")
    lines.append("校准与往返实测执行包SHA "+result["measured_calibration_execution"]+
                 "；校准完成后的v4仅修复旧PID复用的状态/终止判断，当前控制包SHA "+
                 result["current_control_execution"]+"，两端21项测试PASS，新增对局0。"
                 "原92局数据、归档和数值状态保留，速度表仍是v3实测，未冒充v4重跑。\n")
    lines.append(table(["主机","原生arena SHA256","Torch / Python / NumPy"],
                       [[h,read(art/("host.json" if h=="local" else "cloud1-evidence/host.json"))["assets"]["engine"]["sha256"],
                         "2.6.0"+("+cu124" if h=="local" else "+cpu")+" / 3.12.6 / 2.2.4"] for h in ("local","cloud1")]))
    lines.append("起点 Prism Alpha v0.1.1 权重SHA d57ebe2407b5d061ae890f3d2586924754e0d2d8e502e1f3f32d12c1fc9af4ff；"
                 "对手 Prism v0.1.0 权重SHA 5db70b773083858b83c6e679d5641f1b78d4c5fbe34c48950cc906064f821b54。"
                 "协议0.5、引擎0.4.0、splendor-base-v1；原始材料位于"
                 "本机local-artifacts/prism/portable-m57与cloud1 /home/ubuntu/splendor-ppo-m57。\n")
    args.document.parent.mkdir(parents=True,exist_ok=True)
    args.document.write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"status":"PASS","games":92,"groups":len(groups),
                      "speed_ratio":result["speed_ratio_local_over_cloud1"],
                      "result_sha256":sha(args.output),"document":str(args.document)}))


if __name__ == "__main__":
    main()
