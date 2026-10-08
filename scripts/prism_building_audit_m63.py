"""Read-only M63 final checkpoint/parity audit. No training or new games.

--arm may be repeated; omitted means control then beta, sequentially. Only
arm-specific receipts are written. The training report publishes the global
binding after checkpoint, parity AND full training evidence pass for both arms.
"""
import argparse
from contextlib import contextmanager
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

CONFIG = "benchmarks/m63-prism-beta-timed-building.config.json"
PARENT = "225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1"
M57_NATIVE = {"engine": "1a13af46327650c20675994b3347047ecadd5068e701ad3808322ec8ac528d4b",
              "metrics": "ba3f2cbe49e5839ae0b5ca220425c5e79ec901f368eabfc12bc2463c0fe265dc"}
LEGACY_HASHES = {
    "prism_alpha_cloud_audit_m60.py": "7ec8d8df62d91a3ff4c44ec00001aee8002a1adeff5b9774a486613078e05801",
    "prism_alpha_cloud_training_report_m60.py": "de7e0fb923b9f4b98cf886f7c278ae29724f907709b5f48ad2c379983557d2b0",
    "prism_portable_report.py": "603210f2a363327d9d7a46ae0c42c0b97b38341f06a90b541627cbe4285d6286",
}


def require(condition, message):
    if not condition:
        raise ValueError("M63 audit: " + message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    from training.prism_portable.common import write as atomic_write
    atomic_write(path, value)


@contextmanager
def project_context(project):
    project = Path(project).resolve()
    previous = Path.cwd()
    sys.path.insert(0, str(project))
    os.chdir(project)  # verify_completion binds the original launch cwd.
    try:
        yield project
    finally:
        os.chdir(previous)
        sys.path.remove(str(project))


def project_path(project, path):
    path = Path(path)
    return path if path.is_absolute() else project / path


def matched_blueprints(a, b):
    """Only run/job identity and the designated style contract may vary."""
    import copy
    left, right = copy.deepcopy(a["template"]), copy.deepcopy(b["template"])
    for template in (left, right):
        template["run"].pop("run_id")
        template["run"].pop("arena_contract_sha256", None)
        template["run"].pop("style")
        for cycle in template["cycles"]:
            for job in cycle:
                job.pop("job_id")
    require(left == right, "arms differ in RNG, schedule, opponents, budget or numerical configuration")
    require(a["template"]["run"]["ppo"] == b["template"]["run"]["ppo"], "arm PPO configuration differs")
    require((a["template"]["run"]["ppo"]["style_beta"],
             a["template"]["run"]["ppo"]["style_value_weight"]) == (.3, .5),
            "both M63 arms must share active style coefficients")
    require(a["template"]["run"]["style"]["format"] == "prism-building-style-v1" and
            b["template"]["run"]["style"]["format"] == "prism-building-timed-style-v1",
            "wrong old/timed style contract pairing")
    require(a["weight_hashes"] == b["weight_hashes"], "arms have different frozen weights")


def load_contract(project, arm):
    from training.prism_portable.common import identity, package_identity, numerical_identity
    from training.prism_portable.protocol import bind
    import prism_building_prepare_m63 as prepare
    config = prepare.validate_config(read(project / CONFIG))
    require(config["status"] == "FROZEN_BEFORE_FIRST_GAME", "config not frozen before sampling")
    arms = config["training"]["arms"]
    require(set(arms) == {"beta", "control"}, "expected exactly beta/control arms")
    require(config["base_model"]["sha256"] == PARENT, "wrong Prism Balance v0.1.0 parent")
    host = read(project / "host.json")
    runtime = config["runtime"]
    require(host["code_identity"] == runtime["package_identity"] == package_identity(), "portable source drift")
    require(runtime["numerical_identity"] == numerical_identity(), "numerical source drift")
    pins = runtime["source_hashes"]
    required_sources = set(prepare.SCRIPTS)
    actual_engine = {p.relative_to(project).as_posix() for p in
                     (project / "training/prism_portable").rglob("*.py") if "tests" not in p.parts}
    require(required_sources | actual_engine <= set(pins), "missing audit/helper/engine source pins")
    for path, expected in pins.items():
        require(sha(project_path(project, path)) == expected, "source hash drift: " + path)
    require(sha(project / "scripts/prism_portable_report.py") == LEGACY_HASHES["prism_portable_report.py"],
            "frozen M57/M60 report helper drift")
    # Legacy sources are provenance only; deployed copies are checked when present.
    for name, expected in LEGACY_HASHES.items():
        p = project / "scripts" / name
        if p.exists():
            require(sha(p) == expected, "frozen legacy source drift: " + name)
    for name in ("engine", "metrics"):
        require(host["assets"][name]["sha256"] == runtime[name]["sha256"], "native config/host mismatch")
        require(host["assets"][name]["sha256"] == M57_NATIVE[name], "not the shared M57 native input")
    require(host["assets"]["parent"]["sha256"] == PARENT, "host parent hash mismatch")
    for name, row in config["assets"].items():
        require(host["assets"][name]["sha256"] == row["sha256"], "host fixed asset mismatch: "+name)
    for name in ("projection", "bigcard_metrics"):
        require(sha(runtime[name]["path"]) == runtime[name]["sha256"], "audit tool drift: "+name)
    blueprints = {}
    for name, row in arms.items():
        bp_path = project_path(project, row["blueprint_path"])
        require(sha(bp_path) == row["blueprint_sha256"], "frozen blueprint drift: " + name)
        bp = read(bp_path)
        require(identity(bp) == row["blueprint_identity"], "blueprint identity drift: " + name)
        require(bp["template"]["run"]["style"] == row["style"], "config/blueprint style drift: " + name)
        require(bp["template"]["run"]["ppo"] == row["ppo"], "config/blueprint PPO drift: " + name)
        ppo = row["ppo"]
        require((ppo["style_beta"], ppo["style_value_weight"]) == (.3, .5),
                "M63 requires equal active style coefficients in both arms")
        require(bp["weight_hashes"]["parent"] == PARENT, "blueprint parent drift")
        budget = bp["template"]["run"]["budget"]
        require((budget["max_cycles"], budget["max_jobs"], budget["max_attempts"]) == (4, 1024, 1024),
                "wrong frozen campaign budget")
        require(len(bp["template"]["cycles"]) == 4 and all(len(c) == 256 for c in bp["template"]["cycles"]),
                "wrong cycle schedule")
        blueprints[name] = bp
    prepare.validate_config(config, blueprints)
    matched_blueprints(blueprints["control"], blueprints["beta"])
    root = project_path(project, arms[arm]["campaign"]).resolve()
    require(root.parent == (project / "campaigns").resolve() and root.name.startswith(f"m63-{arm}-"),
            "arm campaign outside project or wrong arm")
    require(read(root / "blueprint.json") == blueprints[arm], "campaign blueprint drift")
    spec = bind(blueprints[arm], host)  # hashes every native/weight/fixture and validates contract.
    require(spec == read(root / "contract.json"), "bound campaign contract drift")
    require(read(root / "run/config.json") == spec["run"], "checkpoint configuration drift")
    return config, host, root, spec


def stopped(root):
    from training.prism_portable.control import owned_alive
    row = read(root / "control/status.json")
    require(row["status"] == "STOPPED_COMMITTED", "supervisor incomplete/failed: " + row["status"])
    require(not row.get("alive", False), "retained supervisor alive")
    for key in ("pid", "worker_pid"):
        if key in row:
            require(not owned_alive(dict(row, pid=row[key]), root), "owned process still alive: " + key)
    resources = row["resources"]
    require(resources["returncode"] == 0 and resources["stop_reason"] is None, "failed supervisor resources")
    require(0 < resources.get("wall_seconds", 0) <= 28800 and 0 <= resources.get("cpu_seconds", float("inf")) <= 40000,
            "supervisor wall/CPU ceiling drift")
    require(resources.get("peak_memory_bytes") is not None and resources["peak_memory_bytes"] <= 8*1024**3,
            "supervisor memory ceiling unmeasured/exceeded")
    from prism_building_prepare_m63 import storage_snapshot
    require(storage_snapshot(root) <= 32*1024**3, "final campaign storage ceiling exceeded")
    return row


def provenance():
    return {"argv": list(sys.argv), "cwd": str(Path.cwd()), "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha(__file__), "new_games": 0, "new_optimizer_updates": 0}


def style_evidence(state, store, style_config, arm):
    from training.prism_portable.engine.ppo.building import default_building_config
    from training.prism_portable.engine.ppo.building_timed import default_timed_building_config
    from training.prism_portable.common import identity
    expected_config = default_building_config() if arm == "control" else default_timed_building_config()
    require(style_config == expected_config, "building/timed cap/window contract drift")
    events = [m for m in state["metrics"] if m.get("event") == "style_extracted"]
    require([m["cycle"] for m in events] == [1, 2, 3, 4], "style extraction cycle drift")
    from training.prism_portable.engine.ppo.building_timed import _timed_utility
    artifacts = {}
    for event in events:
        summary = store.get_json(event["artifact"])
        expected_format = "prism-building-targets-v1" if arm == "control" else "prism-building-timed-targets-v1"
        require(summary["format"] == expected_format and len(summary["games"]) == 256 and
                summary["style_contract_sha256"] == identity(style_config) == event["style_contract_sha256"], "style summary binding drift")
        for profile in summary["games"]:
            require(0 <= profile["building_use_units"] <= 24 and profile["building_utility"] == profile["building_use_units"]/24,
                    "style global cap/unit drift")
            source = profile if arm == "control" else profile.get("building_v1_profile")
            require(isinstance(source, dict) and source.get("format") == "prism-building-profile-v1",
                    "missing original v1 profile evidence")
            require(type(source.get("main_actions")) is int and 0 <= source["main_actions"] <= 256 and
                    isinstance(source.get("investments"), list), "invalid source profile action/investment shape")
            observed_total = credited_total = 0
            for investment in source["investments"]:
                require(type(investment.get("acquired_main")) is int and
                        1 <= investment["acquired_main"] <= source["main_actions"],
                        "investment acquisition outside own Main-action range")
                uses = investment.get("use_main_actions")
                require(isinstance(uses, list) and all(type(t) is int for t in uses) and
                        uses == sorted(set(uses)), "actual use times must be sorted unique integer Main actions")
                require(investment.get("observed_uses") == len(uses) and
                        investment.get("credited_uses") == min(len(uses), 3), "investment use-count conservation drift")
                observed_total += len(uses)
                credited_total += min(len(uses), 3)
            require(source["building_observed_use_units"] == observed_total and
                    source["building_use_units"] == min(credited_total, 24),
                    "profile investment totals/global cap drift")
            require(source["building_utility"] == profile["building_utility"] and
                    source["early_bonus_auc12"] == profile["early_bonus_auc12"] and
                    all(i["credited_uses"] == min(i["observed_uses"], 3) and i["printed_vp"] <= 1 and
                        i["acquired_main"] <= 12 and
                        all(t > i["acquired_main"] and t <= min(source["main_actions"], 24)
                            for t in i["use_main_actions"])
                        for i in source["investments"]), "style investment cap/window/use evidence drift")
            # Recompute the base evidence under the exact timed wrapper as an
            # independent conservation check in both arms.
            timed_config = default_timed_building_config()
            weighted = _timed_utility(source, timed_config)
            if arm == "beta":
                require(profile["time_weighted_use_units"] == weighted["time_weighted_use_units"] and
                        profile["time_weighted_utility"] == weighted["time_weighted_utility"],
                        "timed target does not recompute from v1 actual uses")
                require(profile["format"] == "prism-building-timed-profile-v1" and
                        profile["time_weighted_utility"] == profile["time_weighted_use_units"] / 24,
                        "timed target format/unit drift")
            else:
                require(profile.get("format") == "prism-building-profile-v1", "control profile format drift")
        require(summary["mean_building_utility"] == event["mean_building_utility"] and
                summary["mean_early_bonus_auc12"] == event["mean_early_bonus_auc12"], "style metric summary drift")
        if arm == "beta":
            require(summary["mean_time_weighted_utility"] == event["mean_time_weighted_utility"] and
                    summary["mean_time_weighted_utility"] ==
                    math.fsum(p["time_weighted_utility"] for p in summary["games"]) / len(summary["games"]),
                    "timed target summary unit/mean drift")
        artifacts[str(event["cycle"])] = {"artifact": event["artifact"], "summary": summary}
    return {"style_extraction_events": 4, "style_contract": style_config, "target_unit": "normalized_0_to_1",
            "style_enabled": True, "artifacts": artifacts}


def progress_evidence(state, config, summaries):
    require(state["phase"] == "COMMITTED" and state["cycle"] == 4, "final checkpoint not committed cycle 4")
    require(state["attempts"] == 1024 and len(state["all_jobs"]) == len(set(state["all_jobs"])) == 1024,
            "incomplete/repeated jobs or attempts")
    require(len(state["consumed"]) == len(set(state["consumed"])) == 4, "incomplete/repeated consumed batches")
    budget = config["budget"]
    steps = [m for m in state["metrics"] if m.get("event") == "optimizer_step"]
    attempts = [m for m in state["metrics"] if m.get("event") == "optimizer_attempt"]
    sealed = [m for m in state["metrics"] if m.get("event") == "sealed"]
    require([m["global_step"] for m in steps] == list(range(1, state["global_step"] + 1)), "optimizer step ledger drift")
    require([m["attempt"] for m in attempts] == list(range(1, state["update_attempts"] + 1)), "update attempt ledger drift")
    require(0 < state["global_step"] <= budget["max_optimizer_steps"], "optimizer budget exceeded/empty")
    require(state["global_step"] <= state["update_attempts"] <= budget["max_update_attempts"], "update budget exceeded")
    require([m["cycle"] for m in sealed] == [1, 2, 3, 4], "sealed cycle ledger drift")
    require([m["batch_id"] for m in sealed] == state["consumed"], "consumed batch binding drift")
    require(sum(m["decisions"] for m in sealed) == state["decisions"] and
            0 < state["decisions"] <= budget["max_decisions"], "decision ledger/budget drift")
    require(len(summaries) == 4, "missing cycle summaries")
    for cycle, summary in enumerate(summaries, 1):
        updates = [m for m in state["metrics"] if m.get("cycle") == cycle and
                   m.get("event") in ("optimizer_step", "optimizer_diagnostic")]
        reasons = [m for m in state["metrics"] if m.get("cycle") == cycle and
                   m.get("event") in ("passes_complete", "kl_stop")]
        require(len(reasons) == 1 and reasons[0]["batch_id"] == sealed[cycle-1]["batch_id"], "cycle stop ledger drift")
        require(summary["cycle"] == cycle and summary["stop_reason"] == reasons[0]["event"], "summary cycle/stop drift")
        require(summary["updates"] == updates and summary["optimizer_steps"] == sum(m["optimizer_applied"] for m in updates),
                "summary optimizer ledger drift")
        require(summary["update_attempts"] == sum(m.get("cycle") == cycle for m in attempts), "summary attempt drift")
        require(summary["groups"]["all"]["games"] == 256 and
                summary["groups"]["all"]["decisions"] == sealed[cycle-1]["decisions"], "summary decision/game drift")
    return {"global_step": state["global_step"], "update_attempts": state["update_attempts"],
            "cycle_optimizer_steps": [s["optimizer_steps"] for s in summaries]}


def optimizer_evidence(model, optimizer, saved, arm, global_step):
    """Bind saved IDs to the actual Learner parameter order, not just slot count."""
    import torch
    named = list(model.named_parameters())
    trainable = [(name, p) for name, p in named if p.requires_grad]
    live = [p for group in optimizer.param_groups for p in group["params"]]
    require(len(live) == len(trainable) and all(p is q for p, (_, q) in zip(live, trainable)),
            "AdamW actual parameter order differs from effective model parameters")
    ids = [i for group in saved["param_groups"] for i in group["params"]]
    require(len(ids) == len(set(ids)) == len(trainable), "saved AdamW parameter order/count mismatch")
    require(set(saved["state"]) == set(ids), "missing/extra AdamW slots")
    expected_count = 36
    require(len(trainable) == expected_count, "effective model parameter count changed")
    require(model.style_enabled, "M63 style architecture must be enabled in both arms")
    mapping = []
    for slot_id, (name, p) in zip(ids, trainable):
        slot = saved["state"][slot_id]
        require(set(slot) == {"step", "exp_avg", "exp_avg_sq"}, "unexpected AdamW slot schema")
        require(float(slot["step"]) == global_step, "AdamW slot update count mismatch: " + name)
        for key in ("exp_avg", "exp_avg_sq"):
            value = slot[key]
            require(isinstance(value, torch.Tensor) and value.shape == p.shape and value.dtype == p.dtype
                    and bool(torch.isfinite(value).all()), "AdamW slot shape/dtype/finite mismatch: " + name)
        mapping.append({"slot_id": slot_id, "parameter": name, "shape": list(p.shape), "step": float(slot["step"])})
    style = [(name, p) for name, p in named if name.startswith("style_head.")]
    require(len(style) == 4, "unexpected style architecture")
    require(all(p.requires_grad for _, p in style), "M63 style parameters are not all trainable")
    require(sum(x["parameter"].startswith("style_head.") for x in mapping) == 4,
            "M63 style head AdamW slots missing")
    return {"optimizer_slots": len(mapping), "optimizer_parameter_order": mapping,
            "style_enabled": model.style_enabled, "style_disabled": not model.style_enabled,
            "style_parameters_require_grad": [p.requires_grad for _, p in style],
            "style_gradients_present": [p.grad is not None for _, p in style]}


def initial_evidence(run, root, parent_sd, arm):
    import torch
    from training.prism_portable.protocol import state_digest, state_fingerprints
    receipt = read(root / "initialization.json")
    require(receipt["status"] == "PASS" and receipt["run_identity"] == run.identity, "initialization identity drift")
    record = json.loads(run.store._get("commits", receipt["commit"], ".json"))
    require(record["identity"] == run.identity and record["sequence"] == 0 and record["parent"] is None,
            "initialization is not fresh root commit")
    cursor, visited = run.parent, set()
    while cursor is not None:
        require(cursor not in visited, "cyclic initialization ancestry")
        visited.add(cursor)
        ancestor = json.loads(run.store._get("commits", cursor, ".json"))
        if ancestor["parent"] is None:
            require(cursor == receipt["commit"], "initialization not in final commit ancestry")
        cursor = ancestor["parent"]
    initial = run.store.get_payload(record["payload"])
    try:
        require(state_fingerprints(initial) == receipt["state"], "initialization fingerprints drift")
        require(initial["phase"] == "READY" and all(initial[k] == 0 for k in
                ("cycle", "global_step", "update_attempts", "attempts", "decisions")), "initial state already trained")
        require(not initial["optimizer"]["state"] and not initial["all_jobs"] and not initial["consumed"], "AdamW not fresh")
        for key, tensor in parent_sd.items():
            require(torch.equal(initial["model"]["policy." + key], tensor.cpu()), "initial policy/value differs from parent: " + key)
        require(all(key in initial["model"] for key in run.state["model"]), "initial model tensor coverage drift")
        return {"commit": receipt["commit"], "initialization_sha256": sha(root / "initialization.json"),
                "exact_parent_policy_value_tensors": len(parent_sd), "fresh_adamw": True,
                "rng_sha256": state_digest(initial["rng"]),
                "all_tensor_count": len(initial["model"]), "model_state_sha256": state_digest(initial["model"]),
                "per_tensor_sha256": {k: state_digest(v) for k, v in initial["model"].items()},
                "policy_value_sha256": state_digest({k: v for k, v in initial["model"].items() if k.startswith("policy.")}),
                "style_head_trainable": True}
    finally:
        del initial
        gc.collect()


def compare_values(a, b, errors):
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        require(isinstance(b, (int, float)) and not isinstance(b, bool) and math.isfinite(a) and math.isfinite(b)
                and math.isclose(a, b, rel_tol=1e-4, abs_tol=1e-4), "boundary parity drift/nonfinite")
        errors.append(abs(a-b))
    elif isinstance(a, dict):
        require(isinstance(b, dict) and set(a) == set(b), "prediction schema mismatch")
        for key in a:
            compare_values(a[key], b[key], errors)
    elif isinstance(a, list):
        require(isinstance(b, list) and len(a) == len(b), "prediction dimension mismatch")
        for x, y in zip(a, b):
            compare_values(x, y, errors)
    else:
        require(type(a) is type(b) and a == b, "prediction mode/action mismatch")


def audit_arm(project, arm):
    import torch
    from training.prism_portable.common import lock
    from training.prism_portable.engine.export import load_weights
    from training.prism_portable.engine.parity import predict_jsonl
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.protocol import validate_launch_ledger
    config, host, root, spec = load_contract(project, arm)
    work = project / f"audit-{arm}"
    work.mkdir(exist_ok=True)
    # Invalidate prior success before an attempted rerun, including global binding.
    for path in (work / "checkpoint-validation.json", work / "final-parity.json", work / "training-audit.json",
                 project / "training-artifact-audit.json"):
        path.unlink(missing_ok=True)
    with lock(root / "control"):
        supervisor = stopped(root)
        run = None
        try:
            run = Run.open(root / "run")
            state = run.state
            summaries = [read(root / f"cycle-{i}-portable-summary.json") for i in range(1, 5)]
            progress = progress_evidence(state, run.config, summaries)
            style_audit = style_evidence(state, run.store, run.config["style"], arm)
            _, ledger = CommitStore(root / "launch-ledger", spec["run"]["arena_contract_sha256"]).load()
            validate_launch_ledger(ledger, state, spec)
            require(ledger["retries"] == 0 and all(r["status"] == "COMPLETE" for r in ledger["attempts"].values()),
                    "failed/incomplete/retried physical training")
            require(set(state["all_jobs"]) == {j["job_id"] for cycle in spec["cycles"] for j in cycle}, "checkpoint jobs outside schedule")
            optimizer = optimizer_evidence(run.learner.model, run.learner.optimizer, state["optimizer"], arm, state["global_step"])
            export_path = root / "cycle-4-export/weights.json"
            exported = load_weights(export_path, expected_catalog_fingerprint=run.config["catalog_fingerprint"])
            exported_sd = exported.state_dict()
            require(len(exported_sd) == 32, "wrong policy/value export tensor count")
            for key, tensor in exported_sd.items():
                require(torch.equal(tensor.cpu(), state["model"]["policy." + key].cpu()), "export/checkpoint tensor drift: " + key)
            parent = load_weights(host["assets"]["parent"]["path"], expected_catalog_fingerprint=run.config["catalog_fingerprint"])
            parent_sd = parent.state_dict()
            initial = initial_evidence(run, root, parent_sd, arm)
            different = any(not torch.equal(parent_sd[k].cpu(), exported_sd[k].cpu()) for k in exported_sd)
            # Probe style autograd in both arms, without backward or optimizer update.
            from training.prism_portable.engine.data import collate_states
            fixture = json.loads(Path(host["assets"]["fixtures"]["path"]).read_text().splitlines()[0])
            _, values, style = run.learner.model.forward_batch(collate_states([fixture.get("input", fixture)]))
            require(values.requires_grad and style.requires_grad and bool(torch.isfinite(style).all()),
                    "M63 style output is not a finite trainable tensor")
            optimizer["style_output_requires_grad"] = style.requires_grad
            del values, style
            receipt = {"format": "m63-checkpoint-validation-v1", "status": "PASS", "arm": arm,
                       "phase": state["phase"], "cycle": state["cycle"], **progress,
                       "jobs": len(state["all_jobs"]), "attempts": state["attempts"], "decisions": state["decisions"],
                       "consumed_batches": len(state["consumed"]), **optimizer, "initial": initial,
                       "exact_export_tensors": 32, "different_from_parent": bool(different),
                       "final_weights_sha256": sha(export_path), "candidate_path": str(export_path),
                       "parent_sha256": PARENT, "commit": run.parent, "run_identity": run.identity,
                       "config_sha256": sha(project / CONFIG), "blueprint_sha256": sha(root / "blueprint.json"),
                       "bound_contract_sha256": sha(root / "contract.json"), "launch_ledger_commit":
                       CommitStore(root / "launch-ledger", spec["run"]["arena_contract_sha256"]).head(),
                       "supervisor": supervisor, "source_hashes": config["runtime"]["source_hashes"],
                       "native_assets": host["assets"], "new_games": 0, "new_optimizer_updates": 0,
                       "observed_at": time.time(), "provenance": provenance(), "style_audit": style_audit}
            catalog = run.config["catalog_fingerprint"]
        finally:
            # No complete Run or retained batch lives into parity or the next arm.
            run = state = ledger = exported = exported_sd = parent = parent_sd = None
            gc.collect()
        rows = [json.loads(line) for line in Path(host["assets"]["fixtures"]["path"]).read_text().splitlines()]
        require(len(rows) == 68, "expected exactly 68 boundary inputs")
        raw, rust, python_out = work / "inputs.jsonl", work / "final-rust.jsonl", work / "final-python.jsonl"
        raw.write_text("".join(json.dumps(row.get("input", row)) + "\n" for row in rows), encoding="utf-8")
        argv = [host["assets"]["engine"]["path"], "prism-predict", "--weights", str(export_path),
                "--input", str(raw), "--output", str(rust)]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=300)
        require(result.returncode == 0, "native final prediction failed: " + result.stderr[-500:])
        predict_jsonl(export_path, raw, python_out, expected_catalog_fingerprint=catalog)
        a, b = ([json.loads(line) for line in path.read_text().splitlines()] for path in (rust, python_out))
        require(len(a) == len(b) == 68, "boundary output count mismatch")
        errors = []
        for x, y in zip(a, b):
            compare_values(x, y, errors)
        require(bool(errors), "no numeric predictions checked")
        parity = {"format": "m63-final-parity-v1", "status": "PASS", "arm": arm, "boundary_inputs": 68,
                  "max_abs_error": max(errors), "atol": 1e-4, "rtol": 1e-4,
                  "weights_sha256": receipt["final_weights_sha256"], "run_identity": receipt["run_identity"],
                  "commit": receipt["commit"], "config_sha256": receipt["config_sha256"],
                  "native_command": argv, "native_exit_code": result.returncode,
                  "native_sha256": host["assets"]["engine"]["sha256"],
                  "fixtures_sha256": host["assets"]["fixtures"]["sha256"],
                  "outputs_sha256": {path.name: sha(path) for path in (raw, rust, python_out)},
                  "new_games": 0, "new_optimizer_updates": 0, "observed_at": time.time(), "provenance": provenance()}
        require(stopped(root) == supervisor, "supervisor changed during audit")
        write(work / "checkpoint-validation.json", receipt)
        write(work / "final-parity.json", parity)
    gc.collect()
    return receipt


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--project", required=True, type=Path)
    result.add_argument("--arm", action="append", choices=("control", "beta"))
    return result


def main():
    args = parser().parse_args()
    arms = args.arm or ["control", "beta"]
    require(len(arms) == len(set(arms)), "repeated arm")
    with project_context(args.project) as project:
        for arm in arms:
            receipt = audit_arm(project, arm)
            print(json.dumps({"arm": arm, "status": receipt["status"],
                              "candidate_sha256": receipt["final_weights_sha256"],
                              "global_step": receipt["global_step"], "output": str(project / f"audit-{arm}")}, sort_keys=True))


if __name__ == "__main__":
    main()
