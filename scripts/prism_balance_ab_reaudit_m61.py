"""M61 read-only audit execution revision r1. Existing artifacts only, zero games.

Checkpoint/report bodies below are explicit file-backed revisions of the frozen
M61 scripts. No monkeypatch, Run.open, writer lock or original receipt writes.
The report is the game identity authority after frozen completion verification.
Only --project/reaudit-r1 is writable; refuse reuse of an execution directory.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

# Direct CLI may live under project/reaudit-r1, separate from frozen scripts.
SCRIPT = Path(__file__).resolve()
PROJECT_DEFAULT = SCRIPT.parent.parent
if SCRIPT.parent.name == "reaudit-r1":
    PROJECT_DEFAULT = SCRIPT.parent.parent
if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT_DEFAULT / "scripts"))
import prism_balance_ab_audit_m61 as audit
import prism_balance_ab_training_report_m61 as frozen_report

CANDIDATES = {
    "alpha": "d3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9",
    "balance": "225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1",
}
CONFIG_SHA = "280efde1a7441e82d072f33f22b97c24b2d1f5653de76ccfeecb72729ac53fd9"
FROZEN = {
    "scripts/prism_balance_ab_audit_m61.py": "0c9897cb412aa7c56b35f1f8ee769cc5d3ab5899f0fde38cf644f019a49735c7",
    "scripts/prism_balance_ab_training_report_m61.py": "7bb460bdd236658fa4f8babd0874233d35f14033754a2a11dfd02d438bb2a434",
    "scripts/prism_portable_report.py": audit.LEGACY_HASHES["prism_portable_report.py"],
}


def write_new(path, value):
    """Exclusive publication; completed execution records are never overwritten."""
    path = Path(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o444)


def ref(path):
    return {"path": str(path), "sha256": audit.sha(path)}


@contextmanager
def read_guard(root):
    """Lock the existing control file read-only, without creating any lock file."""
    import fcntl
    with (root / "control/writer.lock").open("rb") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def verified_game(spec, job, completion, replay, report, sidecar, replay_path, sidecar_path):
    """Called after verify_completion; independently verify report before using id.

    Never add game_id to ReplayV1. Missing or disagreeing report/sidecar identity
    fails closed even if a sidecar was internally consistent or hash-rebound.
    """
    from training.prism_portable.engine.ppo.execution import verify_report
    from training.prism_portable.engine.ppo.contract import validate_audit
    outcome = verify_report(spec, job, report, replay)
    audit.require(outcome["status"] == "completed", "report must be terminal")
    game_id = report["game_id"]
    audit.require(game_id == job["job_id"], "verified report/job identity mismatch")
    if "game_id" in replay:
        audit.require(replay["game_id"] == game_id, "replay/report game identity mismatch")
    shard = {"format": "prism-ppo-game-v1", "behavior_id": completion["behavior_id"],
             "job_id": job["job_id"], "actor": job["actor"], "game_id": game_id,
             "catalog_fingerprint": spec["run"]["catalog_fingerprint"],
             "replay_sha256": audit.sha(replay_path), "sidecar_sha256": audit.sha(sidecar_path),
             "terminal": True, "result": outcome["result"], "decisions": sidecar}
    score = validate_audit(shard, behavior_id=completion["behavior_id"],
                           catalog_fingerprint=spec["run"]["catalog_fingerprint"],
                           max_decisions=spec["run"]["budget"]["max_job_decisions"])
    return shard, score


def native_game(spec, job, completion, shard, replay, sidecar, output):
    from training.prism_portable.engine.ppo.audit import audit_game
    from training.prism_portable.engine.ppo.contract import validate_audit
    argv = [spec["arena"]["program"], "prism-ppo-audit", "--replay", str(replay),
            "--sidecar", str(sidecar), "--output", str(output), "--behavior-id",
            completion["behavior_id"], "--job-id", job["job_id"], "--actor", str(job["actor"])]
    start = time.time()
    checked = audit_game(spec["arena"]["program"], spec["arena"]["sha256"], replay, sidecar, output,
                         behavior_id=completion["behavior_id"], job_id=job["job_id"], actor=job["actor"])
    validate_audit(checked, behavior_id=completion["behavior_id"],
                   catalog_fingerprint=spec["run"]["catalog_fingerprint"],
                   max_decisions=spec["run"]["budget"]["max_job_decisions"])
    # Rust independently reconstructs every projection/encoding/action. Its JSON
    # float serialization need not be byte-identical to Python's parsed floats.
    # Source-byte hashes bind all sidecar decisions; compare identities/result
    # exactly and conserve count, without weakening the native rules verifier.
    keys = ("behavior_id", "job_id", "actor", "game_id", "catalog_fingerprint",
            "replay_sha256", "sidecar_sha256", "terminal", "result")
    audit.require(all(checked[k] == shard[k] for k in keys) and
                  len(checked["decisions"]) == len(shard["decisions"]),
                  "native/report/sidecar audit identity or content mismatch")
    return {"argv": argv, "started_at": start, "ended_at": time.time(), "exit_code": 0,
            "output": ref(output), "engine_sha256": spec["arena"]["sha256"]}


def verified_receipts(project, arm, root, config, work):
    checkpoint, parity = (audit.read(work / name) for name in
                          ("checkpoint-validation.json", "final-parity.json"))
    old_checkpoint, old_parity = frozen_report.verified_receipts(project, arm, root, config)
    # All content-based checkpoint facts must agree with the old receipt.
    ignored = {"observed_at", "revision", "manifest"}
    audit.require({k: v for k, v in checkpoint.items() if k not in ignored} ==
                  {k: v for k, v in old_checkpoint.items() if k not in ignored},
                  "fresh checkpoint differs from preserved receipt")
    for key in ("status", "arm", "boundary_inputs", "max_abs_error", "atol", "rtol",
                "weights_sha256", "run_identity", "commit", "config_sha256", "native_sha256",
                "fixtures_sha256", "outputs_sha256"):
        audit.require(parity[key] == old_parity[key], "fresh parity differs: " + key)
    audit.require(checkpoint["final_weights_sha256"] == CANDIDATES[arm], "unexpected final candidate")
    return checkpoint, parity


def checkpoint_arm(project, arm, work):
    import torch
    from training.prism_portable.engine.export import load_weights
    from training.prism_portable.engine.parity import predict_jsonl
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.protocol import validate_launch_ledger
    config, host, root, spec = audit.load_contract(project, arm)
    with read_guard(root):
        supervisor = audit.stopped(root)
        run = None
        try:
            run = Run(root / "run", spec["run"])
            run._reload()  # read-only load; no writer lock or transaction
            state = run.state
            summaries = [audit.read(root / f"cycle-{i}-portable-summary.json") for i in range(1, 5)]
            progress = audit.progress_evidence(state, run.config, summaries)
            _, ledger = CommitStore(root / "launch-ledger", spec["run"]["arena_contract_sha256"]).load()
            validate_launch_ledger(ledger, state, spec)
            audit.require(ledger["retries"] == 0 and all(r["status"] == "COMPLETE" for r in ledger["attempts"].values()),
                    "failed/incomplete/retried physical training")
            audit.require(set(state["all_jobs"]) == {j["job_id"] for cycle in spec["cycles"] for j in cycle}, "checkpoint jobs outside schedule")
            optimizer = audit.optimizer_evidence(run.learner.model, run.learner.optimizer, state["optimizer"], arm, state["global_step"])
            export_path = root / "cycle-4-export/weights.json"
            exported = load_weights(export_path, expected_catalog_fingerprint=run.config["catalog_fingerprint"])
            exported_sd = exported.state_dict()
            audit.require(len(exported_sd) == 32, "wrong policy/value export tensor count")
            for key, tensor in exported_sd.items():
                audit.require(torch.equal(tensor.cpu(), state["model"]["policy." + key].cpu()), "export/checkpoint tensor drift: " + key)
            from training.prism_portable.engine.io import tensor_manifest, canonical_hash
            manifest_path = export_path.with_suffix(".manifest.json")
            manifest = audit.read(manifest_path)
            tensors = tensor_manifest(exported_sd)
            audit.require(manifest["format"] == "prism-weights-manifest-v1" and
                          manifest["weights_sha256"] == audit.sha(export_path) == CANDIDATES[arm] and
                          manifest["catalog_fingerprint"] == run.config["catalog_fingerprint"] and
                          manifest["tensors"] == tensors and manifest["tensor_sha256"] == canonical_hash(tensors) and
                          manifest["provenance"]["commit"] == run.parent and manifest["provenance"]["cycle"] == 4 and
                          manifest["provenance"]["run_identity"] == run.identity,
                          "final export manifest tensor/provenance mismatch")
            parent = load_weights(host["assets"]["parent"]["path"], expected_catalog_fingerprint=run.config["catalog_fingerprint"])
            parent_sd = parent.state_dict()
            initial = audit.initial_evidence(run, root, parent_sd, arm)
            different = any(not torch.equal(parent_sd[k].cpu(), exported_sd[k].cpu()) for k in exported_sd)
            # Probe autograd without backward or an optimizer update.
            if arm == "balance":
                from training.prism_portable.engine.data import collate_states
                fixture = json.loads(Path(host["assets"]["fixtures"]["path"]).read_text().splitlines()[0])
                _, values, style = run.learner.model.forward_batch(collate_states([fixture.get("input", fixture)]))
                audit.require(values.requires_grad and not style.requires_grad and bool((style == 0).all()),
                        "Balance style output is not detached zero")
                optimizer["style_output_requires_grad"] = style.requires_grad
                del values, style
            receipt = {"format": "m61-checkpoint-validation-v1", "status": "PASS", "arm": arm,
                       "phase": state["phase"], "cycle": state["cycle"], **progress,
                       "jobs": len(state["all_jobs"]), "attempts": state["attempts"], "decisions": state["decisions"],
                       "consumed_batches": len(state["consumed"]), **optimizer, "initial": initial,
                       "exact_export_tensors": 32, "different_from_parent": bool(different),
                       "final_weights_sha256": audit.sha(export_path), "candidate_path": str(export_path),
                       "parent_sha256": audit.PARENT, "commit": run.parent, "run_identity": run.identity,
                       "config_sha256": audit.sha(project / audit.CONFIG), "blueprint_sha256": audit.sha(root / "blueprint.json"),
                       "bound_contract_sha256": audit.sha(root / "contract.json"), "launch_ledger_commit":
                       CommitStore(root / "launch-ledger", spec["run"]["arena_contract_sha256"]).head(),
                       "supervisor": supervisor, "source_hashes": config["runtime"]["source_hashes"],
                       "native_assets": host["assets"], "new_games": 0, "new_optimizer_updates": 0,
                       "observed_at": time.time(), "revision": "r1", "manifest": ref(manifest_path)}
            catalog = run.config["catalog_fingerprint"]
        finally:
            # No complete Run or retained batch lives into parity or the next arm.
            run = state = ledger = exported = exported_sd = parent = parent_sd = None
            gc.collect()
        rows = [json.loads(line) for line in Path(host["assets"]["fixtures"]["path"]).read_text().splitlines()]
        audit.require(len(rows) == 68, "expected exactly 68 boundary inputs")
        raw, rust, python_out = work / "inputs.jsonl", work / "final-rust.jsonl", work / "final-python.jsonl"
        raw.write_text("".join(json.dumps(row.get("input", row)) + "\n" for row in rows), encoding="utf-8")
        argv = [host["assets"]["engine"]["path"], "prism-predict", "--weights", str(export_path),
                "--input", str(raw), "--output", str(rust)]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=300)
        audit.require(result.returncode == 0, "native final prediction failed: " + result.stderr[-500:])
        predict_jsonl(export_path, raw, python_out, expected_catalog_fingerprint=catalog)
        a, b = ([json.loads(line) for line in path.read_text().splitlines()] for path in (rust, python_out))
        audit.require(len(a) == len(b) == 68, "boundary output count mismatch")
        errors = []
        for x, y in zip(a, b):
            audit.compare_values(x, y, errors)
        audit.require(bool(errors), "no numeric predictions checked")
        parity = {"format": "m61-final-parity-v1", "status": "PASS", "arm": arm, "boundary_inputs": 68,
                  "max_abs_error": max(errors), "atol": 1e-4, "rtol": 1e-4,
                  "weights_sha256": receipt["final_weights_sha256"], "run_identity": receipt["run_identity"],
                  "commit": receipt["commit"], "config_sha256": receipt["config_sha256"],
                  "native_command": argv, "native_exit_code": result.returncode,
                  "native_sha256": host["assets"]["engine"]["sha256"],
                  "fixtures_sha256": host["assets"]["fixtures"]["sha256"],
                  "outputs_sha256": {path.name: audit.sha(path) for path in (raw, rust, python_out)},
                  "new_games": 0, "new_optimizer_updates": 0, "observed_at": time.time()}
        audit.require(audit.stopped(root) == supervisor, "supervisor changed during audit")
        audit.write(work / "checkpoint-validation.json", receipt)
        audit.write(work / "final-parity.json", parity)
    gc.collect()
    return receipt


def training_arm(project, arm, work):
    from training.prism_portable.engine.ppo.audit import bounded_json
    from training.prism_portable.engine.ppo.contract import validate_audit
    from training.prism_portable.engine.ppo.execution import verify_completion
    from training.prism_portable.engine.ppo.model import behavior_identity
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.protocol import state_digest
    detail = frozen_report.helper()
    config, host, root, spec = audit.load_contract(project, arm)
    output = work / "training-audit.json"
    native_work = work / "native-audit"
    native_work.mkdir()
    native_receipts = []
    with read_guard(root):
        supervisor = audit.stopped(root)
        checkpoint, parity = verified_receipts(project, arm, root, config, work)
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
            shard, score = verified_game(spec, job, c, replay, report, sidecar, replay_path, sidecar_path)
            native_receipts.append(native_game(spec, job, c, shard, replay_path, sidecar_path,
                                               native_work / f"attempt-{c['attempt']:04d}.json"))
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
                   "outcome": report["outcome"]}
            groups[(cycle, job["opponent_id"])].append(row)
            seen.add(job_id)
        audit.require(set(expected) == seen and decisions == checkpoint["decisions"] == ledger["physical_decisions"],
                      "training job/decision conservation failed")
        audit.require(len(groups) == 16 and set(snapshot_by_cycle) == {1, 2, 3, 4}, "incomplete training groups")
        snapshots = {}
        for cycle, (digest, behavior_id_value) in sorted(snapshot_by_cycle.items()):
            payload = store.get_payload(digest)
            try:
                audit.require(payload["style_enabled"] is (arm == "alpha") and payload["action_seed"] == spec["run"]["seed"] and
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
                            "label": f"{arm}臂 / 第{cycle}轮 / 未发布训练快照c{cycle-1} / {detail.LABELS[opponent]}",
                            "behavior_id": rows[0]["behavior_id"], "opponent_identity": rows[0]["opponent_identity"],
                            "games": rows, "score_ci": detail.paired_ci(rows), "win_ci": detail.paired_ci(rows, True),
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
        audit.write(source_ledger, {"format": "m61-training-source-ledger-v1", "arm": arm,
                                   "candidate_sha256": checkpoint["final_weights_sha256"],
                                   "config_sha256": checkpoint["config_sha256"],
                                   "rows": [{k: r[k] for k in ("job_id", "attempt", "cycle", "seed", "actor", "hashes",
                                                              "local_replay", "behavior_id", "snapshot_sha256")}
                                            for g in results for r in g["games"]]})
        audit.write(work / "native-audit-receipts.json", native_receipts)
        result = {"format": "m61-prism-balance-ab-training-audit-v1", "status": "PASS_TRAINING_ARTIFACT_AUDIT",
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
                  "revision": "r1", "native_audits": len(native_receipts),
                  "native_audit_receipts": ref(work / "native-audit-receipts.json"), "new_matches": 0, "new_optimizer_updates": 0, "observed_at": time.time()}
        lines = [f"# M61 {arm}臂：完整训练诊断双方对战表\n",
                 f"**产物：PASS_TRAINING_ARTIFACT_AUDIT。**4轮1,024局 / {checkpoint['global_step']}次实际更新，"
                 "32 policy/value导出张量逐元素相同；来源、规则回放与双方经济/动作守恒PASS。\n",
                 "**竞技：NOT_RUN。**独立最终c4对战尚未运行，训练胜率不能替代独立结果。\n",
                 "**风格：NOT_RUN。**训练风格参数和head状态已核验，风格效果需独立评测。\n",
                 "父模型 **Prism Alpha v0.1.3** → 最终候选c4的匹配对战比较：**NOT_RUN**。"
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
                 "配对95%区间为训练描述，20,000次bootstrap / RNG57049999；不是独立验收门。"
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




def compare_evidence(project, arm, work):
    old_work = project / f"audit-{arm}"
    old = audit.read(old_work / "training-audit.json")
    new = audit.read(work / "training-audit.json")
    old_ledger = audit.read(old_work / "training-source-ledger.json")
    new_ledger = audit.read(work / "training-source-ledger.json")
    audit.require(old_ledger == new_ledger, "old/revised source ledgers differ")
    ignored = {"receipts"}
    old_groups = [{k: v for k, v in g.items() if k not in ignored} for g in old["groups"]]
    new_groups = [{k: v for k, v in g.items() if k not in ignored} for g in new["groups"]]
    audit.require(old_groups == new_groups, "old/revised game ledgers or metrics differ")
    for key in ("snapshots", "opponents", "supervisor", "cycle_summaries", "candidate_sha256",
                "completed_games", "group_count", "rust_manifests", "source_hashes", "metrics"):
        audit.require(old[key] == new[key], "old/revised evidence differs: " + key)
    metrics = []
    for old_g, new_g in zip(old["groups"], new["groups"]):
        for left, right in zip(old_g["receipts"], new_g["receipts"]):
            audit.require(left["metrics_sha256"] == right["metrics_sha256"] and
                          left["manifest_sha256"] == right["manifest_sha256"], "native metrics bytes differ")
            metrics.append(right["metrics_sha256"])
    return {"status": "PASS_EXACT_CONTENT_PARITY", "source_ledger_equal": True,
            "game_rows_and_metrics_equal": True, "cycle_snapshot_evidence_equal": True,
            "native_metric_hashes_equal": len(metrics), "preserved_training_audit": ref(old_work / "training-audit.json"),
            "preserved_source_ledger": ref(old_work / "training-source-ledger.json"),
            "revised_training_audit": ref(work / "training-audit.json"), "failures": []}


def runtime_pins():
    """Hash imported runtime files and mapped shared libraries, including stdlib."""
    paths = {Path(sys.executable), Path(sys.executable).resolve()}
    for module in list(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        path = Path(filename)
        if path.suffix == ".pyc":
            try:
                path = Path(importlib.util.source_from_cache(str(path)))
            except ValueError:
                pass
        if path.is_file():
            paths.add(path.resolve())
    maps = Path("/proc/self/maps")
    if maps.exists():
        for line in maps.read_text().splitlines():
            pieces = line.split(maxsplit=5)
            if len(pieces) == 6 and pieces[5].startswith("/"):
                path = Path(pieces[5])
                if path.is_file():
                    paths.add(path)
    cfg = Path(sys.prefix) / "pyvenv.cfg"
    if cfg.exists():
        paths.add(cfg)
    return {str(p): audit.sha(p) for p in sorted(paths)}


def resource_snapshot():
    import resource
    own, child = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    row = {"scope": "audit process and waited native children; cgroup counters at observation",
           "self_cpu_seconds": own.ru_utime + own.ru_stime,
           "children_cpu_seconds": child.ru_utime + child.ru_stime,
           "self_max_rss_bytes": own.ru_maxrss * 1024, "children_max_rss_bytes": child.ru_maxrss * 1024}
    entry = next(line.split(":", 2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines()
                 if line.startswith("0::"))
    cgroup = Path("/sys/fs/cgroup") / entry.lstrip("/")
    row["cgroup"] = str(cgroup)
    row["cgroup_files"] = {name: (cgroup / name).read_text().strip() for name in
                           ("memory.max", "memory.peak", "memory.events", "cpu.max", "cpu.stat")}
    audit.require(row["cgroup_files"]["memory.max"] == "8589934592", "wrong unit MemoryMax")
    audit.require(row["cgroup_files"]["cpu.max"] == "200000 100000", "wrong unit CPUQuota")
    return row


def inventory(project):
    config = audit.read(project / audit.CONFIG)
    audit.require(audit.sha(project / audit.CONFIG) == CONFIG_SHA, "frozen config drift")
    source = dict(config["runtime"]["source_hashes"])
    for name, digest in FROZEN.items():
        audit.require(source[name] == digest, "frozen helper pin mismatch")
    paths = {project / audit.CONFIG, project / "host.json", project / "training-artifact-audit.json"}
    for name, digest in source.items():
        path = audit.project_path(project, name)
        audit.require(audit.sha(path) == digest, "frozen source drift: " + name)
        paths.add(path)
    for name, digest in audit.LEGACY_HASHES.items():
        path = project / "scripts" / name
        if path.exists():
            audit.require(audit.sha(path) == digest, "legacy source drift")
            paths.add(path)
    for asset in audit.read(project / "host.json")["assets"].values():
        paths.add(Path(asset["path"]))
    for arm, descriptor in config["training"]["arms"].items():
        root = Path(descriptor["campaign"])
        audit.stopped(root)
        paths.add(audit.project_path(project, descriptor["blueprint_path"]))
        for name in ("blueprint.json", "contract.json", "initialization.json", "run/config.json", "run/HEAD.json",
                     "control/status.json", "control/writer.lock", "run/writer.lock", "launch-ledger/HEAD.json",
                     "cycle-4-export/weights.json", "cycle-4-export/weights.manifest.json"):
            paths.add(root / name)
        paths.update(root / f"cycle-{n}-portable-summary.json" for n in range(1, 5))
        paths.update(p for p in (project / f"audit-{arm}").rglob("*") if p.is_file())
        for folder in ("run", "launch-ledger"):
            paths.update((root / folder / "commits").glob("*.json"))
            head = audit.read(root / folder / "HEAD.json")
            record = audit.read(root / folder / "commits" / (head["commit"] + ".json"))
            paths.add(root / folder / "objects" / (record["payload"] + ".pt"))
        init = audit.read(root / "initialization.json")
        record = audit.read(root / "run/commits" / (init["commit"] + ".json"))
        paths.add(root / "run/objects" / (record["payload"] + ".pt"))
        # Snapshot objects are independently content-addressed and checked during training audit.
        old_training = audit.read(project / f"audit-{arm}/training-audit.json")
        paths.update(root / "run/objects" / (s["snapshot_sha256"] + ".pt") for s in old_training["snapshots"].values())
    for name in ("training-evidence-manifest.json", "evaluation/execution.json", "evaluation/completion.json",
                 "evaluation/result.json", "evaluation/m61-prism-alpha-balance-ab-report.md"):
        path = project / name
        if path.exists():
            paths.add(path)
    return {str(p): audit.sha(p) for p in sorted(paths)}, {str(project / k): v for k, v in source.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--unit", required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    audit.require(project == PROJECT_DEFAULT.resolve(), "revision must execute inside the frozen project")
    output = project / "reaudit-r1"
    audit.require(SCRIPT.parent == output and output.is_dir(), "revision must live in owned r1 root")
    audit.require(not (output / "execution.json").exists() and not (output / "completion.json").exists(),
                  "immutable execution already exists; no retry")
    started = time.time()
    arms, failures, status, exit_code = {}, [], "FAILED", 1
    inputs, source_pins, execution_hash = {}, {}, None
    with audit.project_context(project):
        try:
            inputs, source_pins = inventory(project)
            source_pins.update({str(SCRIPT): audit.sha(SCRIPT),
                                str(output / "test_m61_reaudit.py"): audit.sha(output / "test_m61_reaudit.py")})
            inputs.update({str(p): audit.sha(p) for p in output.glob("*") if p.is_file() and
                           p.name not in ("stdout.log", "stderr.log")})
            inputs.update({str(p): audit.sha(p) for p in (output / "regression").rglob("*") if p.is_file()})
            resources_before = resource_snapshot()
            unit = subprocess.run(["systemctl", "show", args.unit, "--property=MemoryMax,CPUQuotaPerSecUSec,RuntimeMaxUSec,ExecStart,ControlGroup"],
                                  capture_output=True, text=True, check=True).stdout
            audit.require("RuntimeMaxUSec=1h" in unit, "wrong unit RuntimeMaxSec")
            execution = {"format": "m61-reaudit-r1-execution-v1", "revision": "M61 re-audit-r1", "revision_script": ref(SCRIPT), "argv": [sys.executable, "-B", *sys.argv],
                         "cwd": str(project), "started_at": started, "source_pins": source_pins,
                         "runtime_pins": runtime_pins(), "inputs": inputs, "unit": args.unit,
                         "unit_properties": unit, "resource_limits": {"memory_bytes": 8589934592,
                         "cpu_quota_percent": 200, "runtime_max_seconds": 3600}, "resources_before": resources_before,
                         "identity_authority": "frozen verify_completion -> verified report.game_id -> strict sidecar/native audit",
                         "new_games": 0, "new_optimizer_updates": 0, "retries": 0}
            write_new(output / "execution.json", execution)
            execution_hash = audit.sha(output / "execution.json")
            for arm in ("alpha", "balance"):
                work = output / f"audit-{arm}"
                work.mkdir()
                print(json.dumps({"arm": arm, "stage": "checkpoint/parity", "execution_sha256": execution_hash}), flush=True)
                checkpoint_arm(project, arm, work)
                print(json.dumps({"arm": arm, "stage": "full training/native"}), flush=True)
                summary = training_arm(project, arm, work)
                comparison = compare_evidence(project, arm, work)
                audit.write(work / "comparison.json", comparison)
                checkpoint = audit.read(work / "checkpoint-validation.json")
                parity = audit.read(work / "final-parity.json")
                manifest = Path(checkpoint["manifest"]["path"])
                arms[arm] = {"status": summary["status"], "games": summary["games"],
                             "candidate_sha256": checkpoint["final_weights_sha256"],
                             "candidate_path": checkpoint["candidate_path"], "manifest_path": str(manifest),
                             "manifest_sha256": audit.sha(manifest), "parity_max_abs_error": parity["max_abs_error"],
                             "checkpoint_validation": ref(work / "checkpoint-validation.json"),
                             "final_parity": ref(work / "final-parity.json"), "training_audit": ref(work / "training-audit.json"),
                             "source_ledger": ref(work / "training-source-ledger.json"), "comparison": ref(work / "comparison.json")}
                print(json.dumps(summary, sort_keys=True), flush=True)
            left, right = [audit.read(output / f"audit-{a}/checkpoint-validation.json")["initial"] for a in ("alpha", "balance")]
            audit.require(left["rng_sha256"] == right["rng_sha256"] and
                          left["policy_value_sha256"] == right["policy_value_sha256"], "initial two-arm policy/value/RNG differ")
            for arm in ("alpha", "balance"):
                training = audit.read(output / f"audit-{arm}/training-audit.json")
                for group in training["groups"]:
                    for row in group["games"]:
                        directory = Path(row["local_replay"]).parent
                        inputs.update({str(directory / name): digest for name, digest in row["hashes"].items()})
            for path, digest in inputs.items():
                audit.require(audit.sha(path) == digest, "input changed during r1: " + path)
            status, exit_code = "PASS_M61_REAUDIT_R1", 0
        except Exception as exc:
            failures.append({"type": type(exc).__name__, "message": str(exc)})
            import traceback
            traceback.print_exc()
        finally:
            outputs = {str(p): audit.sha(p) for p in output.rglob("*") if p.is_file() and str(p) not in inputs
                       and p.name not in ("completion.json", "stdout.log", "stderr.log")}
            receipt = {"format": "m61-reaudit-r1-execution-receipt-v1", "status": status,
                       "execution_sha256": execution_hash, "execution_path": str(output / "execution.json"),
                       "source_pins": source_pins, "runtime_pins": runtime_pins(), "inputs": inputs, "outputs": outputs,
                       "argv": [sys.executable, "-B", *sys.argv], "unit": args.unit, "started_at": started,
                       "ended_at": time.time(), "wall_seconds": time.time()-started, "exit_code": exit_code,
                       "resources": resource_snapshot(), "arms": arms, "failures": failures,
                       "new_games": 0, "new_optimizer_updates": 0, "retries": 0,
                       "old_receipts_preserved": status == "PASS_M61_REAUDIT_R1",
                       "competitive_verdict": "UNCHANGED_RECORDED_RETENTION_PASS_INCONCLUSIVE",
                       "style_acceptance": "NOT_CLAIMED"}
            write_new(output / "completion.json", receipt)
            print(json.dumps({"status": status, "execution_sha256": execution_hash, "arms": arms,
                              "failures": failures, "receipt": str(output / "completion.json")}, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
