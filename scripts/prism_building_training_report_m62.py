"""Offline M62 training provenance and full two-player tables, using pinned M60 helpers.

No Run.open, training or new games. --arm beta/control (repeatable); omitted
runs both sequentially. Publishes global binding only once both arms pass.
"""
from collections import Counter, defaultdict
import gc
import json
from pathlib import Path
import subprocess
import sys
import time
import math

import prism_building_audit_m62 as audit


def helper():
    import importlib.util
    path = Path(__file__).with_name("prism_portable_report.py")
    audit.require(audit.sha(path) == audit.LEGACY_HASHES[path.name], "frozen training report helper hash drift")
    spec = importlib.util.spec_from_file_location("m61_pinned_report_helper", path)
    detail = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(detail)
    detail.LABELS.update({"prism-general-v011": "Prism v0.1.1",
                          "balance-parent-v010": "固定研究父 Prism Balance v0.1.0",
                          "heuristic-v031": "Heuristic v0.3.1（协议 Hello 0.2.9）"})
    return detail


def provenance():
    return {"argv": list(sys.argv), "cwd": str(Path.cwd()), "source_path": str(Path(__file__).resolve()),
            "source_sha256": audit.sha(__file__), "new_games": 0, "new_optimizer_updates": 0}


def training_shard(job, completion, report, replay, sidecar, spec, replay_path, sidecar_path):
    """Arena game identity belongs to report.json; replay intentionally lacks it."""
    audit.require(report["game_id"] == job["job_id"], "explicit report game identity drift")
    return {"format": "prism-ppo-game-v1", "behavior_id": completion["behavior_id"], "job_id": job["job_id"],
            "actor": job["actor"], "game_id": report["game_id"], "catalog_fingerprint": spec["run"]["catalog_fingerprint"],
            "replay_sha256": audit.sha(replay_path), "sidecar_sha256": audit.sha(sidecar_path),
            "terminal": True, "result": replay["result"], "decisions": sidecar}


def paired_ci(rows, pure=False):
    import numpy as np
    pairs = defaultdict(dict)
    for row in rows:
        audit.require(row["actor"] not in pairs[row["seed"]], "duplicate descriptive seed/seat")
        pairs[row["seed"]][row["actor"]] = float(row["record"] == "win") if pure else row["score"]
    audit.require(pairs and all(set(pair) == {0, 1} for pair in pairs.values()), "incomplete descriptive seed pair")
    blocks = np.array([sum(pair.values())/2 for _, pair in sorted(pairs.items())])
    rng = np.random.default_rng(62049999)
    samples = blocks[rng.integers(0, len(blocks), (20000, len(blocks)))].mean(1)
    return {"estimate": float(blocks.mean()), "ci95": np.quantile(samples, [.025, .975]).tolist(),
            "seed_blocks": len(blocks), "resamples": 20000, "bootstrap_seed": 62049999,
            "scope": "training descriptive paired-seed bootstrap; not acceptance"}


def style_summary(profiles):
    audit.require(profiles, "empty building profiles")
    keys = ("building_utility", "building_use_units", "early_bonus_auc12", "early_lowvp_buys",
            "redeemed_investments", "unredeemed_investments", "late_scoring_vp_main25to32")
    result = {"games": len(profiles), **{"mean_"+key: math.fsum(p[key] for p in profiles)/len(profiles) for key in keys}}
    total = sum(p["early_lowvp_buys"] for p in profiles)
    result.update(total_investments=total, total_redeemed=sum(p["redeemed_investments"] for p in profiles),
                  investment_redemption_rate=sum(p["redeemed_investments"] for p in profiles)/total if total else None,
                  censored_games=sum(p["redemption_horizon_censored"] for p in profiles),
                  scope="all observed games, including early losses; descriptive only")
    return result


def verify_file_pins(project, ledger):
    for path, expected in ledger["files"].items():
        audit.require(audit.sha(audit.project_path(project, path)) == expected, "training source file drift: "+path)


def verified_receipts(project, arm, root, config):
    checkpoint = audit.read(project / f"audit-{arm}/checkpoint-validation.json")
    parity = audit.read(project / f"audit-{arm}/final-parity.json")
    audit.require(checkpoint["status"] == parity["status"] == "PASS", "checkpoint/parity not PASS")
    audit.require(checkpoint["arm"] == parity["arm"] == arm and checkpoint["cycle"] == 4,
                  "wrong arm/final cycle receipt")
    audit.require(checkpoint["config_sha256"] == parity["config_sha256"] == audit.sha(project / audit.CONFIG), "audit config drift")
    audit.require(checkpoint["blueprint_sha256"] == audit.sha(root / "blueprint.json") and
                  checkpoint["bound_contract_sha256"] == audit.sha(root / "contract.json"), "receipt contract drift")
    head = audit.read(root / "run/HEAD.json")
    audit.require(head["identity"] == checkpoint["run_identity"] == parity["run_identity"] and
                  head["commit"] == checkpoint["commit"] == parity["commit"], "receipt checkpoint HEAD drift")
    candidate = root / "cycle-4-export/weights.json"
    audit.require(audit.sha(candidate) == checkpoint["final_weights_sha256"] == parity["weights_sha256"], "candidate hash drift")
    audit.require(checkpoint["source_hashes"] == config["runtime"]["source_hashes"], "receipt source identity drift")
    audit.require(parity["boundary_inputs"] == 68 and parity["atol"] == parity["rtol"] == 1e-4, "wrong parity gate")
    audit.require(checkpoint["jobs"] == checkpoint["attempts"] == 1024 and checkpoint["consumed_batches"] == 4,
                  "checkpoint training grid incomplete")
    return checkpoint, parity


def audit_arm(project, arm):
    from training.prism_portable.common import lock
    from training.prism_portable.engine.ppo.audit import bounded_json
    from training.prism_portable.engine.ppo.contract import validate_audit
    from training.prism_portable.engine.ppo.execution import verify_completion
    from training.prism_portable.engine.ppo.model import behavior_identity
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.protocol import state_digest
    detail = helper()
    config, host, root, spec = audit.load_contract(project, arm)
    work = project / f"audit-{arm}"
    output = work / "training-audit.json"
    output.unlink(missing_ok=True)
    (project / "training-artifact-audit.json").unlink(missing_ok=True)
    with lock(root / "control"):
        supervisor = audit.stopped(root)
        checkpoint, parity = verified_receipts(project, arm, root, config)
        store = CommitStore(root / "run", checkpoint["run_identity"])
        ledger_store = CommitStore(root / "launch-ledger", spec["run"]["arena_contract_sha256"])
        ledger_head, ledger = ledger_store.load()
        audit.require(ledger_head == checkpoint["launch_ledger_commit"] and not ledger["failed"] and ledger["retries"] == 0,
                      "physical ledger drift/failure")
        expected = {j["job_id"]: (i+1, j) for i, cycle in enumerate(spec["cycles"]) for j in cycle}
        groups, seen, snapshot_by_cycle, decisions = defaultdict(list), set(), {}, 0
        paths = sorted((root / "attempts").glob("*/completion.json"))
        audit.require(len(paths) == len(ledger["attempts"]) == 1024, "incomplete/extra training attempts")
        for path in paths:
            c = bounded_json(path)
            job_id = c["job"]["job_id"]
            audit.require(job_id in expected and job_id not in seen, "unexpected/duplicate completed job")
            cycle, job = expected[job_id]
            audit.require(c["contract"] == spec and c["job"] == job, "completion contract/job drift")
            entry = ledger["attempts"][str(c["attempt"])]
            audit.require(entry["status"] == "COMPLETE" and entry["job"] == job and
                          entry["completion_sha256"] == audit.sha(path), "completion/ledger hash drift")
            replay_path, sidecar_path = path.parent / "replay.json", path.parent / "sidecar.jsonl"
            verify_completion(spec["run"], job, c["attempt"], path, replay=replay_path,
                              sidecar=sidecar_path, behavior_id=c["behavior_id"])
            replay, report = bounded_json(replay_path), bounded_json(path.parent / "report.json")
            audit.require(audit.read(path.parent / "process-result.json") == c["resources"], "process result drift")
            audit.require(c["resources"]["wall_seconds"] > 0, "unmeasured game wall clock")
            sidecar = [json.loads(line) for line in sidecar_path.read_text().splitlines()]
            shard = training_shard(job, c, report, replay, sidecar, spec, replay_path, sidecar_path)
            from training.prism_portable.engine.ppo.building import extract_building_profile
            profile = extract_building_profile(shard, spec["run"]["style"])
            score = validate_audit(shard, behavior_id=c["behavior_id"],
                                   catalog_fingerprint=spec["run"]["catalog_fingerprint"],
                                   max_decisions=spec["run"]["budget"]["max_job_decisions"])
            audit.require(len(sidecar) == entry["charged_decisions"], "physical sidecar decision charge drift")
            decisions += len(sidecar)
            identity = (c["snapshot_sha256"], c["behavior_id"])
            audit.require(snapshot_by_cycle.setdefault(cycle, identity) == identity, "mixed training snapshots in cycle")
            actions = [Counter(), Counter()]
            for step in replay["steps"]:
                audit.require(step["actor"] in (0, 1) and step["action"]["type"] in detail.ACTIONS, "invalid replay actor/action")
                actions[step["actor"]][step["action"]["type"]] += 1
            actor = job["actor"]
            audit.require(len(sidecar) == sum(actions[actor].values()), "learner sidecar/replay decision mismatch")
            hashes = {p.name: audit.sha(p) for p in (path, replay_path, sidecar_path, path.parent / "report.json",
                                                    path.parent / "process-result.json", path.parent / "arena-config.json")}
            row = {"job_id": job_id, "attempt": c["attempt"], "cycle": cycle, "opponent_id": job["opponent_id"],
                   "actor": actor, "seed": job["environment_seed"], "score": score,
                   "record": "win" if score == 1 else "draw" if score == .5 else "loss",
                   "candidate_vp": replay["result"]["scores"][actor], "opponent_vp": replay["result"]["scores"][1-actor],
                   "candidate_actions": dict(actions[actor]), "opponent_actions": dict(actions[1-actor]),
                   "plies": len(replay["steps"]), "wall_seconds": c["resources"]["wall_seconds"],
                   "resources": c["resources"], "behavior_id": c["behavior_id"], "snapshot_sha256": c["snapshot_sha256"],
                   "opponent_identity": spec["run"]["opponents"][job["opponent_id"]],
                   "local_replay": str(replay_path), "hashes": hashes, "original_artifacts": c["files"],
                   "outcome": report["outcome"], "building_profile": profile,
                   "artifact_paths": {p.name: str(p) for p in (path, replay_path, sidecar_path, path.parent / "report.json",
                                      path.parent / "process-result.json", path.parent / "arena-config.json")}}
            groups[(cycle, job["opponent_id"])].append(row)
            seen.add(job_id)
        audit.require(set(expected) == seen and decisions == checkpoint["decisions"] == ledger["physical_decisions"],
                      "training job/decision conservation failed")
        audit.require(len(groups) == 16 and set(snapshot_by_cycle) == {1, 2, 3, 4}, "incomplete training groups")
        snapshots = {}
        for cycle, (digest, behavior_id_value) in sorted(snapshot_by_cycle.items()):
            payload = store.get_payload(digest)
            try:
                audit.require(payload["style_enabled"] is (arm == "beta") and payload["action_seed"] == spec["run"]["seed"] and
                              payload["catalog_fingerprint"] == spec["run"]["catalog_fingerprint"], "snapshot mode/seed/catalog drift")
                from training.prism_portable.engine.ppo.model import new_model
                model = new_model(style_enabled=payload["style_enabled"], state_dict=payload["state_dict"])
                audit.require(behavior_identity(model, catalog_fingerprint=payload["catalog_fingerprint"],
                              action_seed=payload["action_seed"], runtime=payload["runtime"]) == payload["behavior_id"] == behavior_id_value,
                              "snapshot behavior content identity drift")
                if cycle == 1:
                    audit.require(state_digest({k: v for k, v in payload["state_dict"].items() if k.startswith("policy.")}) ==
                                  checkpoint["initial"]["policy_value_sha256"], "c0 differs from verified initial parent")
                snapshots[str(cycle)] = {"snapshot_sha256": digest, "behavior_id": behavior_id_value, "runtime": payload["runtime"]}
            finally:
                payload = model = None
                gc.collect()
        metrics = host["assets"]["metrics"]
        metric_work = work / "training-metrics"
        metric_work.mkdir(exist_ok=True)
        results = []
        for index, ((cycle, opponent), rows) in enumerate(sorted(groups.items())):
            audit.require(opponent in detail.LABELS, "unmapped opponent label: " + opponent)
            a, b, receipts = [], [], []
            for seat in (0, 1):
                subset = [r for r in rows if r["actor"] == seat]
                audit.require(bool(subset), "missing training physical seat")
                manifest, metric_output = metric_work / f"g{index}-s{seat}.manifest.json", metric_work / f"g{index}-s{seat}.metrics.json"
                detail.write(manifest, {"rows": [{"replay_path": r["local_replay"]} for r in subset]})
                argv = [metrics["path"], str(manifest), str(metric_output)]
                start = time.perf_counter()
                p = subprocess.run(argv, capture_output=True, text=True, timeout=120)
                audit.require(p.returncode == 0, "Rust rule replay/metrics failed: " + p.stderr[-500:])
                m = detail.read(metric_output)
                audit.require(m["total_games"] == len(subset), "Rust replay count drift")
                seats = [m["seat_p0_first"], m["seat_p1_second"]]
                a.append((seats[seat], len(subset)))
                b.append((seats[1-seat], len(subset)))
                receipts.append({"argv": argv, "exit_code": p.returncode, "seconds": time.perf_counter()-start,
                                 "manifest_sha256": audit.sha(manifest), "metrics_sha256": audit.sha(metric_output)})
            results.append({"cycle": cycle, "opponent_id": opponent,
                            "label": f"{config['training']['arms'][arm]['identity']['label']} / 第{cycle}轮 / 未发布训练快照c{cycle-1} / {detail.LABELS[opponent]} / 学习方及对手greedy / 双方个人指标",
                            "behavior_id": rows[0]["behavior_id"], "opponent_identity": rows[0]["opponent_identity"],
                            "games": rows, "score_ci": paired_ci(rows), "win_ci": paired_ci(rows, True),
                            "candidate": detail.player(rows, a, True), "opponent": detail.player(rows, b, False),
                            "macro": detail.macro(rows), "receipts": receipts})
        summaries = [audit.read(root / f"cycle-{i}-portable-summary.json") for i in range(1, 5)]
        for cycle, summary in enumerate(summaries, 1):
            rs = [r for g in results if g["cycle"] == cycle for r in g["games"]]
            for name, group in summary["groups"].items():
                if name == "all":
                    subset = rs
                elif "/seat" in name:
                    opponent, seat = name.split("/seat")
                    subset = [r for r in rs if r["opponent_id"] == opponent and r["actor"] == int(seat)]
                else:
                    subset = [r for r in rs if r["opponent_id"] == name]
                audit.require(group["games"] == len(subset) and group["reward_sum"] == sum(r["score"] for r in subset)
                              and all(group[k] == sum(r["record"] == v for r in subset) for k, v in
                                      (("wins", "win"), ("draws", "draw"), ("losses", "loss"))), "summary outcome conservation drift")
        audit.require(audit.stopped(root) == supervisor and store.head() == checkpoint["commit"], "training changed during report")
        source_ledger = work / "training-source-ledger.json"
        audit.write(source_ledger, {"format": "m62-training-source-ledger-v1", "arm": arm,
                                   "candidate_sha256": checkpoint["final_weights_sha256"],
                                   "config_sha256": checkpoint["config_sha256"],
                                   "rows": [{k: r[k] for k in ("job_id", "attempt", "cycle", "seed", "actor", "hashes",
                                                              "local_replay", "behavior_id", "snapshot_sha256")}
                                            for g in results for r in g["games"]]})
        result = {"format": "m62-prism-building-training-audit-v1", "status": "PASS_TRAINING_ARTIFACT_AUDIT",
                  "source_ledger": {"path": str(source_ledger), "sha256": audit.sha(source_ledger)},
                  "arm": arm, "competitive_verdict": "NOT_RUN", "style_verdict": "NOT_RUN", "checkpoint": checkpoint,
                  "candidate_sha256": checkpoint["final_weights_sha256"], "completed_games": 1024,
                  "group_count": 16, "rust_manifests": 32, "groups": results, "snapshots": snapshots,
                  "opponents": spec["opponents"], "supervisor": supervisor, "cycle_summaries": summaries,
                  "config_sha256": checkpoint["config_sha256"], "training_blueprint_sha256": checkpoint["blueprint_sha256"],
                  "bound_contract_sha256": checkpoint["bound_contract_sha256"], "source_hashes": config["runtime"]["source_hashes"],
                  "helper_sha256": audit.sha(detail.__file__), "metrics": metrics,
                  "checkpoint_validation_sha256": audit.sha(work / "checkpoint-validation.json"),
                  "final_parity_sha256": audit.sha(work / "final-parity.json"),
                  "new_matches": 0, "new_optimizer_updates": 0, "observed_at": time.time()}
        lines = [f"# M62 {arm}臂：完整训练诊断双方对战表\n",
                 f"**产物：PASS_TRAINING_ARTIFACT_AUDIT。**4轮1,024局 / {checkpoint['global_step']}次实际更新，"
                 "32 policy/value导出张量逐元素相同；来源、规则回放与双方经济/动作守恒PASS。\n",
                 "**竞技：NOT_RUN。**独立最终c4对战尚未运行，训练胜率不能替代独立结果。\n",
                 "**风格：NOT_RUN。**训练风格参数和head状态已核验，风格效果需独立评测。\n",
                 "父模型 **Prism Balance v0.1.0** → 最终候选c4的匹配对战比较：**NOT_RUN**。"
                 "下表为c0..c3未发布训练snapshots；不同轮种子不相同，不推断跨轮增强。\n",
                 "Heuristic v0.3.1为共享M57冻结源码/原生引擎策略；协议Hello保留0.2.9，完整descriptor/hash见机器证据。\n",
                 detail.table(["实际采样snapshot", "局数", "学习决策", "实际更新", "轮内流水线秒", "更新阶段秒", "结束原因"],
                              [[f"未发布c{s['cycle']-1}", s['groups']['all']['games'], s['groups']['all']['decisions'],
                                s['optimizer_steps'], s['portable_cycle_wall_seconds'], s['this_session_update_seconds'],
                                s['stop_reason']] for s in summaries]),
                 "时钟：轮内流水线包含采样、接纳、更新、导出；阶段时钟存在包含关系。整批监督tree资源："
                 + json.dumps(supervisor["resources"], ensure_ascii=False) + "。负载/配额由冻结合同limits与run.cpu_threads定义："
                 + json.dumps({"limits": spec["limits"], "cpu_threads": spec["run"]["cpu_threads"]}, ensure_ascii=False)
                 + "。逐决策/推理时间 **NOT_MEASURED**。\n",
                 "配对95%区间为训练描述，20,000次bootstrap / RNG62049999；不是独立验收门。"
                 "比例使用总次数与总分母，个人表双方按实际模型座位聚合。\n",
                 "冻结来源：config SHA " + result["config_sha256"] + "；blueprint SHA " + result["training_blueprint_sha256"]
                 + "；bound contract SHA " + result["bound_contract_sha256"] + "；candidate SHA " + result["candidate_sha256"]
                 + "；原生engine SHA " + spec["arena"]["sha256"] + "；metric SHA " + metrics["sha256"]
                 + "。逐局seed/seat/completion/report/replay/sidecar/hash、行为及runtime来源详见同目录training-audit.json。\n"]
        lines.extend(detail.group_tables(g) for g in results)
        text = "\n".join(lines)
        document = work / "training-matches.md"
        document.write_text(text, encoding="utf-8", newline="\n")
        result["training_matches_sha256"] = audit.sha(document)
        audit.write(output, result)
    gc.collect()
    return {"arm": arm, "status": result["status"], "games": 1024, "groups": 16, "output": str(output)}


def publish_binding(project):
    """Never treat a single-arm PASS or copied/stale receipt as a two-arm PASS."""
    rows, initials = {}, []
    for arm in ("control", "beta"):
        work = project / f"audit-{arm}"
        if not (work / "training-audit.json").exists():
            return None
        config, _, root, _ = audit.load_contract(project, arm)
        supervisor = audit.stopped(root)
        checkpoint, _ = verified_receipts(project, arm, root, config)
        training = audit.read(work / "training-audit.json")
        audit.require(training["status"] == "PASS_TRAINING_ARTIFACT_AUDIT" and training["arm"] == arm and
                      training["checkpoint"] == checkpoint and training["supervisor"] == supervisor and
                      training["candidate_sha256"] == checkpoint["final_weights_sha256"], "full training audit binding drift")
        audit.require(training["completed_games"] == 1024 and training["group_count"] == len(training["groups"]) == 16,
                      "full training report incomplete")
        row = {"candidate_sha256": checkpoint["final_weights_sha256"], "candidate_path": checkpoint["candidate_path"],
               "run_identity": checkpoint["run_identity"], "commit": checkpoint["commit"],
               "config_sha256": checkpoint["config_sha256"], "blueprint_sha256": checkpoint["blueprint_sha256"],
               "bound_contract_sha256": checkpoint["bound_contract_sha256"]}
        for name, filename in (("checkpoint_validation", "checkpoint-validation.json"), ("final_parity", "final-parity.json"),
                               ("training_audit", "training-audit.json"), ("training_matches", "training-matches.md")):
            row[name + "_path"] = str(work / filename)
            row[name + "_sha256"] = audit.sha(work / filename)
        audit.require(row["checkpoint_validation_sha256"] == training["checkpoint_validation_sha256"] and
                      row["final_parity_sha256"] == training["final_parity_sha256"] and
                      row["training_matches_sha256"] == training["training_matches_sha256"], "report evidence hash drift")
        audit.require(audit.sha(training["source_ledger"]["path"]) == training["source_ledger"]["sha256"], "training source ledger drift")
        row["evidence"] = {
            "checkpoint": {"path": row["checkpoint_validation_path"], "sha256": row["checkpoint_validation_sha256"]},
            "parity": {"path": row["final_parity_path"], "sha256": row["final_parity_sha256"]},
            "full_training": {"path": row["training_audit_path"], "sha256": row["training_audit_sha256"]},
            "campaign_status": {"path": str(root / "control/status.json"), "sha256": audit.sha(root / "control/status.json")},
            "source_ledger": training["source_ledger"],
        }
        rows[arm] = row
        initials.append(checkpoint["initial"])
    audit.require(initials[0]["rng_sha256"] == initials[1]["rng_sha256"] and
                  initials[0]["policy_value_sha256"] == initials[1]["policy_value_sha256"], "initial two-arm policy/value/RNG differ")
    binding = {"format": "m62-training-audit-binding-v1", "status": "PASS_TRAINING_ARTIFACT_AUDIT",
               "arms": rows, "initial_policy_value_and_rng_equal": True, "completed_games": 2048, "groups": 32,
               "competitive_verdict": "NOT_RUN", "style_verdict": "NOT_RUN", "new_matches": 0,
               "new_optimizer_updates": 0, "observed_at": time.time()}
    audit.write(project / "training-artifact-audit.json", binding)
    return binding


def main():
    args = audit.parser().parse_args()
    arms = args.arm or ["control", "beta"]
    audit.require(len(set(arms)) == len(arms), "repeated arm")
    with audit.project_context(args.project) as project:
        for arm in arms:
            print(json.dumps(audit_arm(project, arm), sort_keys=True))
        binding = publish_binding(project)
        if binding:
            print(json.dumps({"status": binding["status"], "binding": str(project / "training-artifact-audit.json")}, sort_keys=True))


if __name__ == "__main__":
    main()
