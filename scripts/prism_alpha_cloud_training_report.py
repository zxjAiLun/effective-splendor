"""Read-only M59 training audit; preserves the actual failed supervisor verdict."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess
import time

import prism_portable_report as detail

LABELS = {"prism-general-v011": "通用 Prism v0.1.1",
          "alpha-parent-v011": "父模型 Prism Alpha v0.1.1",
          "prism-v01": "初代 Prism v0.1.0",
          "heuristic-portable-v029": "便携 Heuristic v0.2.9"}
detail.LABELS.update(LABELS)


def audit(project):
    project = Path(project).resolve()
    root = project / "campaigns/m59-alpha-bigcard-g0"
    spec = detail.read(root / "contract.json")
    actual_status = detail.read(root / "control/status.json")
    checkpoint = detail.read(project / "checkpoint-validation.json")
    detail.require(checkpoint["status"] == "PASS" and checkpoint["cycle"] == 4, "final checkpoint not verified")
    detail.require(checkpoint["global_step"] == 216, "unexpected optimizer count")
    expected = {j["job_id"]: (i + 1, j) for i, cycle in enumerate(spec["cycles"]) for j in cycle}
    groups, seen = defaultdict(list), set()
    for path in sorted((root / "attempts").glob("*/completion.json")):
        c = detail.read(path)
        cycle, job = expected[c["job"]["job_id"]]
        detail.require(c["job"] == job and c["contract"] == spec, "completion binding changed")
        detail.require(job["job_id"] not in seen, "repeated completed job")
        seen.add(job["job_id"])
        hashes = {}
        for name in ("replay", "report", "sidecar"):
            asset = path.parent / (name + (".jsonl" if name == "sidecar" else ".json"))
            hashes[name] = detail.sha(asset)
            detail.require(hashes[name] == c["files"][name]["sha256"], "artifact hash drift")
        hashes.update(completion=detail.sha(path), process_result=detail.sha(path.parent / "process-result.json"))
        replay, report = detail.read(path.parent / "replay.json"), detail.read(path.parent / "report.json")
        outcome = report["outcome"]
        detail.require(outcome["status"] == "completed" and outcome["result"] == replay["result"], "nonterminal game")
        detail.require(replay["seed"] == job["environment_seed"] and len(replay["steps"]) == outcome["completed_plies"], "seed/ply drift")
        detail.require(c["resources"]["returncode"] == 0 and c["resources"]["wall_seconds"] > 0, "failed game process")
        actor, actions = job["actor"], [Counter(), Counter()]
        for step in replay["steps"]:
            actions[step["actor"]][step["action"]["type"]] += 1
        ranks = replay["result"]["ranks"]
        score = .5 if ranks[0] == ranks[1] else float(ranks[actor] < ranks[1-actor])
        row = {"job_id": job["job_id"], "cycle": cycle, "opponent_id": job["opponent_id"],
               "actor": actor, "seed": job["environment_seed"], "score": score,
               "record": "win" if score == 1 else "draw" if score == .5 else "loss",
               "candidate_vp": replay["result"]["scores"][actor], "opponent_vp": replay["result"]["scores"][1-actor],
               "candidate_actions": dict(actions[actor]), "opponent_actions": dict(actions[1-actor]),
               "plies": len(replay["steps"]), "wall_seconds": c["resources"]["wall_seconds"],
               "behavior_id": c["behavior_id"], "snapshot_sha256": c["snapshot_sha256"],
               "opponent_identity": spec["run"]["opponents"][job["opponent_id"]],
               "local_replay": str(path.parent / "replay.json"), "hashes": hashes}
        groups[(cycle, job["opponent_id"])].append(row)
    detail.require(set(expected) == seen and len(seen) == 1024, "incomplete frozen grid")
    work = project / "training-metrics"
    work.mkdir(exist_ok=True)
    metrics = detail.read(project / "host.json")["assets"]["metrics"]
    detail.require(detail.sha(metrics["path"]) == metrics["sha256"], "native metric program drift")
    results = []
    for index, ((cycle, opponent), rows) in enumerate(sorted(groups.items())):
        detail.require(len({r["behavior_id"] for r in rows}) == 1, "mixed behavior identities")
        a, b, receipts = [], [], []
        for seat in (0, 1):
            subset = [r for r in rows if r["actor"] == seat]
            manifest, output = work / f"g{index}-s{seat}.manifest.json", work / f"g{index}-s{seat}.metrics.json"
            detail.write(manifest, {"rows": [{"replay_path": r["local_replay"]} for r in subset]})
            argv = [metrics["path"], str(manifest), str(output)]
            started = time.perf_counter()
            p = subprocess.run(argv, capture_output=True, text=True, timeout=120)
            detail.require(p.returncode == 0, "Rust replay analysis: " + p.stderr[-500:])
            m = detail.read(output)
            detail.require(m["total_games"] == len(subset), "Rust replay count drift")
            seats = [m["seat_p0_first"], m["seat_p1_second"]]
            a.append((seats[seat], len(subset)))
            b.append((seats[1-seat], len(subset)))
            receipts.append({"argv": argv, "exit_code": p.returncode, "seconds": time.perf_counter()-started,
                             "manifest_sha256": detail.sha(manifest), "metrics_sha256": detail.sha(output)})
        results.append({"cycle": cycle, "opponent_id": opponent,
                        "label": f"第{cycle}轮 / 未发布检查点c{cycle-1} / {LABELS[opponent]}",
                        "behavior_id": rows[0]["behavior_id"], "opponent_identity": rows[0]["opponent_identity"],
                        "games": rows, "score_ci": detail.paired_ci(rows), "win_ci": detail.paired_ci(rows, True),
                        "candidate": detail.player(rows, a, True), "opponent": detail.player(rows, b, False),
                        "macro": detail.macro(rows), "receipts": receipts})
    summaries = [detail.read(root / f"cycle-{i}-portable-summary.json") for i in range(1, 5)]
    result = {"format": "m59-prism-alpha-training-audit-v1", "status": "PASS_TRAINING_ARTIFACT_AUDIT",
              "competitive_verdict": "NOT_RUN", "style_verdict": "NOT_RUN", "supervisor_status_preserved": actual_status["status"],
              "supervisor_resources": actual_status["resources"], "checkpoint": checkpoint, "groups": results,
              "completed_games": len(seen), "new_matches": 0, "new_optimizer_updates": 0,
              "source_hashes": {Path(__file__).name: detail.sha(__file__), "prism_portable_report.py": detail.sha(detail.__file__)},
              "config_sha256": detail.sha(project / "m59-prism-alpha-cloud-ppo.config.json"),
              "metrics": metrics, "training_blueprint_sha256": detail.sha(root / "blueprint.json"),
              "bound_contract_sha256": detail.sha(root / "contract.json"), "observed_at": time.time()}
    output = project / "training-audit.json"
    detail.write(output, result)
    text = "# M59云端PPO：完整训练诊断对战表\n\n"
    text += "**产物：**四轮1,024局、216次更新已提交，最终c4的32导出张量与checkpoint逐元素一致。原监督器因4GiB cgroup OOM在收尾退出，历史状态 **FAILED** 保留。\n\n"
    text += "**竞技：NOT_RUN。风格：NOT_RUN。**下表测量的是c0、c1、c2、c3各自采样的训练局，最终c4尚无独立对战。不同轮使用不同种子，不能据跨轮胜率变化推出增强；没有替换父模型。\n\n"
    text += "共同种子匹配的父模型→最终c4比较仍为NOT_RUN，详见[本轮评测记录](prism-alpha-cloud-m59-evaluation.md)。最终版本名Prism Alpha v0.1.2仍待独立验收。\n\n"
    text += detail.table(["轮次 / 实际采样模型", "局数", "训练决策", "新更新", "轮内墙钟", "更新墙钟", "结束原因"],
                         [[f"{s['cycle']} / 未发布c{s['cycle']-1}", s['groups']['all']['games'], s['groups']['all']['decisions'],
                           s['optimizer_steps'], f"{s['portable_cycle_wall_seconds']:.3f}s", f"{s['this_session_update_seconds']:.3f}s", s['stop_reason']] for s in summaries])
    text += "\n完整监督墙钟47分11.08秒，含收尾异常；四轮流水线时钟和各阶段时钟存在包含关系，不能简单相加。CPU两线程/200% quota；启动时空闲CPU、约10.8GiB可用主机内存，任务受4GiB cap。逐决策/推理耗时 **NOT_MEASURED**。\n\n"
    text += "各组配对95%区间为新描述性统计，20,000次bootstrap/RNG57049999，沿用固定M57统计实现；它们不是三门验收的RNG59029999/多重校正下界，没有替换冻结门。双方指标按模型身份选择物理座位后聚合，比例来自总次数。\n\n"
    text += "每组出处包含原生程序、opponent descriptor、behavior/snapshot身份与逐回放/report/sidecar SHA。原机器证据保留于cloud1专属目录；本地汇总在local-artifacts/prism/alpha-cloud-m59/training-audit.json（SHA " + detail.sha(output) + "）。Rust独立重放解析全部1,024局、32分座manifest，守恒检查通过；没有新增比赛。\n\n"
    text += "原生ARM splendor SHA " + spec['arena']['sha256'] + "；合同SHA " + result['bound_contract_sha256'] + "；最终权重SHA " + checkpoint['final_weights_sha256'] + "。四个对手权重/argv/Hello已在[M59合同](../m59-prism-alpha-cloud-ppo.md)及冻结JSON明确。\n"
    for g in results:
        text += detail.group_tables(g)
    document = project / "training-matches.md"
    document.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "games": len(seen), "groups": len(results), "rust_manifests": 32,
                      "new_games": 0, "supervisor": actual_status["status"], "result_sha256": detail.sha(output), "document": str(document)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    audit(parser.parse_args().project)
