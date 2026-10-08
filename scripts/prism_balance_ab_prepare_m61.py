"""Freeze M61 same-parent Alpha/Balance arms; deploy-time serial controller lives outside engine."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import digest, identity, numerical_identity, package_identity, read, write

ART = ROOT / "local-artifacts/prism/balance-ab-m61"
CONFIG = ROOT / "benchmarks/m61-prism-alpha-balance-ab.config.json"
BLUEPRINTS = {arm: ROOT / f"benchmarks/m61-prism-{arm}-ab.train.json" for arm in ("alpha", "balance")}
CLOUD = "/home/ubuntu/splendor-ppo-m61"
RESERVATIONS = [(9611000, 9611511, "m61-training-paired-arms"),
                (9616000, 9616031, "m61-development-never-train"),
                (9621000, 9621511, "m61-independent-never-train")]


def build_blueprints(m60, expected):
    result = {}
    order = ["prism-general-v011", "alpha-parent-v013", "prism-general-v011", "prism-v01",
             "prism-general-v011", "alpha-parent-v013", "prism-general-v011", "heuristic-v031"]
    for arm in ("alpha", "balance"):
        bp = copy.deepcopy(m60)
        bp.update(purpose="finite-same-parent-alpha-balance-ab", cancel_fixture=False,
                  model_label=f"M61 unpublished {arm} final-c4 candidate from Prism Alpha v0.1.3")
        bp["weight_hashes"] = {key: expected[key] for key in ("parent", "general", "initial")}
        t = bp["template"]
        t["opponents"]["heuristic-v031"] = t["opponents"].pop("heuristic-portable-v029")
        t["opponents"]["alpha-parent-v013"] = t["opponents"].pop("alpha-parent-v012")
        t["opponents"]["alpha-parent-v013"]["args"][-1] = "61031003"
        t["opponents"]["prism-general-v011"]["args"][-1] = "61031002"
        run = t["run"]
        run.update(run_id=f"m61-{arm}-ab", seed=61031001)
        run["opponents"] = {name: "" for name in t["opponents"]}
        run["ppo"].update(style_beta=0.3 if arm == "alpha" else 0.0,
                          style_value_weight=0.5 if arm == "alpha" else 0.0)
        t["cycles"] = [[{"job_id": f"m61-{arm}-c{c+1}-b{b}-s{s}", "actor": s,
                         "opponent_id": order[b % 8], "environment_seed": 9611000 + c * 128 + b}
                        for b in range(128) for s in (0, 1)] for c in range(4)]
        result[arm] = bp
    return result


def validate_blueprints(blueprints):
    a, b = (copy.deepcopy(blueprints[arm]) for arm in ("alpha", "balance"))
    for bp in (a, b):
        bp.pop("model_label")
        bp["template"]["run"].pop("run_id")
        bp["template"]["run"]["ppo"].pop("style_beta")
        bp["template"]["run"]["ppo"].pop("style_value_weight")
        for cycle in bp["template"]["cycles"]:
            for job in cycle:
                job.pop("job_id")
    if a != b:
        raise ValueError("arms differ outside identity and two authorized style coefficients")
    for arm, bp in blueprints.items():
        jobs = [j for cycle in bp["template"]["cycles"] for j in cycle]
        counts = {name: sum(j["opponent_id"] == name for j in jobs) for name in bp["template"]["opponents"]}
        if counts != {"prism-general-v011": 512, "alpha-parent-v013": 256, "prism-v01": 128, "heuristic-v031": 128}:
            raise ValueError("opponent mix drift")
        if len(jobs) != 1024 or len({j["job_id"] for j in jobs}) != 1024:
            raise ValueError("bounded schedule mismatch")
        for seed in range(9611000, 9611512):
            if sorted(j["actor"] for j in jobs if j["environment_seed"] == seed) != [0, 1]:
                raise ValueError("schedule is not exactly paired")


def initialization_parity(parent, catalog):
    import torch
    from training.prism_portable.engine.ppo.model import warm_start
    from training.prism_portable.protocol import state_digest
    models = [warm_start(parent, catalog, style_enabled=enabled, initialization_seed=61031001)
              for enabled in (True, False)]
    aa, bb = [model.state_dict() for model in models]
    if set(aa) != set(bb) or not all(torch.equal(aa[k], bb[k]) for k in aa):
        raise ValueError("style enablement perturbs initial tensors")
    tensors = {k: state_digest(v) for k, v in aa.items()}
    return {"status": "PASS", "new_games": 0, "policy_value_tensor_count": sum(k.startswith("policy.") for k in aa),
            "all_tensor_count": len(aa), "per_tensor_sha256": tensors,
            "model_state_sha256": state_digest(aa), "initialization_seed": 61031001,
            "style_enabled": {"alpha": True, "balance": False},
            "scope": "all initial policy/value/style tensors exactly equal; style gradient enablement differs"}


def dynamic_seed_ranges(value, label):
    """Collect declared intervals, schedules and standalone seed constants conservatively."""
    found = []
    if isinstance(value, dict):
        if isinstance(value.get("seed_start"), int):
            lo = value["seed_start"]
            ends = [value[k] for k in ("seed_end", "direct_seed_end") if isinstance(value.get(k), int)]
            if not ends:
                counts = [value[k] for k in ("seed_count", "blocks", "seed_blocks", "games", "total_games")
                          if isinstance(value.get(k), int)]
                ends = [lo + max(counts, default=1) - 1]
            found.append((lo, max(ends), label))
        for k, v in value.items():
            if "seed" in k and isinstance(v, int):
                found.append((v, v, label + "/" + k))
            if k == "seed_reservations" and isinstance(v, list):
                found.extend((r[0], r[1], label + "/" + str(r[2])) for r in v if isinstance(r, list) and len(r) == 3)
            found.extend(dynamic_seed_ranges(v, label + "/" + k))
    elif isinstance(value, list):
        for i, row in enumerate(value):
            found.extend(dynamic_seed_ranges(row, label + "/" + str(i)))
    return found


def prepare():
    if CONFIG.exists() or ART.exists() or any(p.exists() for p in BLUEPRINTS.values()):
        raise ValueError("M61 already reserved; never overwrite a frozen contract")
    m60 = read(ROOT / "benchmarks/m60-prism-alpha-cloud-ppo.config.json")
    assets = {"parent": ROOT / "local-artifacts/prism/alpha-v0.1.3/weights.json",
              "general": Path(m60["assets"]["general"]["path"]),
              "initial": Path(m60["assets"]["initial"]["path"]),
              "fixtures": Path(m60["assets"]["fixtures"]["path"])}
    expected = {k: m60["assets"][k]["sha256"] for k in assets}
    expected["parent"] = "7f6cdbc2acdff129b0ef6a3417e79d4b8f27bf59f40be53ae2892bf00b5e1544"
    parent_identity = read(ROOT / "benchmarks/m60-prism-alpha-v0.1.3.model.json")
    if parent_identity["weights_sha256"] != expected["parent"]:
        raise ValueError("registered parent identity drift")
    for name, path in assets.items():
        if digest(path) != expected[name]:
            raise ValueError("fixed input drift: " + name)
    frozen = read(ROOT / "local-artifacts/prism/portable-m57/original-frozen-inputs.json")
    rust = read(ROOT / "local-artifacts/prism/portable-m57/rust-source.json")
    for evidence in (frozen, rust):
        for path, sha in evidence["files"].items():
            if digest(ROOT / path) != sha:
                raise ValueError("historical source drift: " + path)
    if package_identity() != m60["runtime"]["package_identity"] or numerical_identity() != m60["runtime"]["numerical_identity"]:
        raise ValueError("M61 must use exactly the M60 portable engine/package")
    spec = importlib.util.spec_from_file_location("seed_registry", ROOT / "scripts/s0_seed_registry.py")
    registry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(registry)
    historical = list(registry.REGISTRY)
    for filename in ("m56-prism-alpha-v0.1.1.config.json", "m59-prism-alpha-cloud-ppo.config.json", "m60-prism-alpha-cloud-ppo.config.json"):
        historical.extend(tuple(row) for row in read(ROOT / "benchmarks" / filename)["seed_reservations"])
    m57 = read(ROOT / "benchmarks/m57-prism-portable-ppo.config.json")
    for name, bp in m57["blueprints"].items():
        seeds = [j["environment_seed"] for cycle in bp["template"]["cycles"] for j in cycle]
        historical.append((min(seeds), max(seeds), "m57-" + name))
    dynamic_files = {}
    for path in sorted((ROOT / "benchmarks").glob("*.json")):
        if path.name.startswith("m61-") or not any(token in path.name for token in (".config.", ".train.", ".evaluate.", ".evaluation-execution.")):
            continue
        dynamic_files[path.relative_to(ROOT).as_posix()] = digest(path)
        historical.extend(dynamic_seed_ranges(read(path), path.name))
    historical = sorted(set(historical))
    for lo, hi, label in RESERVATIONS:
        for old_lo, old_hi, old_label in historical:
            if max(lo, old_lo) <= min(hi, old_hi):
                raise ValueError(label + " overlaps " + old_label)
    bps = build_blueprints(read(ROOT / "benchmarks/m60-prism-alpha-cloud-ppo.train.json"), expected)
    validate_blueprints(bps)
    parity = initialization_parity(assets["parent"], bps["alpha"]["template"]["run"]["catalog_fingerprint"])
    anchors = ["heuristic-v031", "prism-v01", "prism-general-v011"]
    development = copy.deepcopy(m60["evaluation"]["development"])
    development.update(seed_start=9616000, seed_end=9616031, action_seed=61032001, total_games=576,
                       models=["base", "alpha", "balance"], anchors=anchors, blocks=32)
    acceptance = copy.deepcopy(m60["evaluation"]["acceptance"])
    acceptance.update(seed_start=9621000, seed_end=9621255, direct_seed_end=9621511, action_seed=61032001,
                      bootstrap_rng_seed=61039999, bootstrap_samples=20000, family_alpha=0.05,
                      one_sided_claims=0, simultaneous_comparisons=7, interval_sides="two-sided",
                      lower_quantile=0.05 / (2 * 7), upper_quantile=1 - 0.05 / (2 * 7),
                      anchors=anchors, models=["base", "alpha", "balance"], anchor_total_games=4608,
                      direct_parent_games=2048, between_arms_games=1024, total_games=7680,
                      total_physical_budget=10304, require_all_three_gates=False,
                      required_gates={"alpha": ["strength_pool", "direct_parent", "bigcard_auc24"],
                                      "balance": ["strength_pool", "direct_parent"]},
                      balance_alpha_pool_delta_lower_gt=0.0, balance_alpha_direct_score_lower_gt=0.5,
                      alpha_balance_pool_delta_upper_lt=0.0, alpha_balance_direct_score_upper_lt=0.5,
                      directional_claims_required_for_acceptance=False,
                      enhancement_reporting="seven simultaneous two-sided intervals; Balance confirmed by lower>0/.5, Alpha by upper<0/.5; otherwise INCONCLUSIVE",
                      balanced_style_descriptor="NOT_RUN; beta=0 does not establish observed balanced style")
    arms = {}
    import hashlib
    for arm, bp in bps.items():
        serialized = (json.dumps(bp, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        arms[arm] = {"blueprint_path": BLUEPRINTS[arm].relative_to(ROOT).as_posix(),
                     "blueprint_sha256": hashlib.sha256(serialized).hexdigest(), "blueprint_identity": identity(bp),
                     "campaign": CLOUD + f"/campaigns/m61-{arm}-ab-g0", "line": f"m61-{arm}-ab",
                     "identity": {"label": bp["model_label"], "status": "NOT_RUN", "published": False},
                     "ppo": bp["template"]["run"]["ppo"], "style": bp["template"]["run"]["style"]}
    heuristic_hashes = {p: sha for p, sha in rust["files"].items()
                        if p == "crates/splendor-agent/src/heuristic_v02.rs" or "/heuristic_v02/" in p}
    if len(heuristic_hashes) != 7:
        raise ValueError("Heuristic v0.3.1 must bind seven source files")
    sources = {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted((ROOT / "training/prism_portable").rglob("*.py")) if "tests" not in p.parts}
    sources["scripts/prism_balance_ab_prepare_m61.py"] = digest(__file__)
    audit_sources = ["scripts/prism_balance_ab_audit_m61.py", "scripts/prism_balance_ab_training_report_m61.py",
                     "scripts/prism_portable_report.py"]
    for name in audit_sources:
        if not (ROOT / name).exists():
            raise ValueError("audit source not ready: " + name)
        sources[name] = digest(ROOT / name)
    config = {"format": "m61-prism-alpha-balance-ab-v1", "status": "FROZEN_BEFORE_FIRST_GAME",
              "frozen_at": datetime.now(timezone.utc).isoformat(), "owner_authorization": "okay let go",
              "baseline_git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "base_model": {"name": "Prism Alpha v0.1.3", "path": str(assets["parent"]), "sha256": expected["parent"]},
              "assets": {k: {"path": str(p), "sha256": expected[k]} for k, p in assets.items()},
              "training": {"arms": arms, "cycles": 4, "games_per_cycle": 256, "games_per_arm": 1024,
                           "total_games": 2048, "run_seed": 61031001,
                           "opponent_action_seeds": {"prism-general-v011": 61031002, "alpha-parent-v013": 61031003},
                           "mix_per_arm": {"prism-general-v011": 512, "alpha-parent-v013": 256, "prism-v01": 128, "heuristic-v031": 128},
                           "opponents_action_mode": "greedy", "action_mode": "categorical-T1 learned policy",
                           "execution_order": ["alpha", "balance"], "selection": "only each final c4",
                           "initialization": "same fixed parent; fresh AdamW/style head/RNG per arm; no checkpoint resume",
                           "pairing": "same seed/seat/opponent schedule; different policies yield different trajectories; shared RNG is not multi-seed replication"},
              "seed_reservations": RESERVATIONS, "seed_collision_check": {"status": "PASS", "prior_ranges": len(historical),
                                                                          "dynamic_files_count": len(dynamic_files), "dynamic_files_sha256": dynamic_files}, 
              "evaluation": {"status": "NOT_RUN", "development": development, "acceptance": acceptance,
                             "candidate_and_parent_mode": "agent-prism-sample T1, action seed 61032001",
                             "anchor_modes": {"heuristic-v031": "greedy", "prism-v01": "greedy", "prism-general-v011": "T1, action seed 61032001"},
                             "native_path_and_sha256": m60["runtime"]["engine"], "total_games": 8256,
                             "selection": "fixed c4, no tuning, checkpoint selection or grid extension"},
              "resources": copy.deepcopy(m60["resources"]),
              "runtime": {"cloud_root": CLOUD, "python": m60["runtime"]["python"],
                          "package_identity": package_identity(), "numerical_identity": numerical_identity(),
                          "source_hashes": sources, "rust_source_snapshot": rust,
                          "engine": m60["runtime"]["engine"], "metrics": m60["runtime"]["metrics"]},
              "heuristic_identity": {"name": "Heuristic v0.3.1", "opponent_id": "heuristic-v031",
                                     "policy_identity": "handwritten-heuristic-v031", "engine": m60["runtime"]["engine"],
                                     "source_hashes": heuristic_hashes,
                                     "hello": {"agent_name": "splendor-cli-heuristic-v02", "agent_version": "0.2.9"},
                                     "hello_note": "protocol compatibility constant, not policy version; seven source hashes bind v0.3.1",
                                     "evidence": "docs/prism/heuristic-anchor-v031-identity.md"},
              "constraints": ["new root only; preserve historical freezes", "no default/pool/Studio change", "no automatic retry",
                              "create Balance only immediately before its turn; do not consume its deadline during Alpha",
                              "per-arm resource ceiling; never concurrently run two 8 GiB arms", "no acceptance inference from training"]}
    config["resources"].update(scope="per training arm", serial_execution=True)
    ART.mkdir(parents=True)
    for arm, bp in bps.items():
        write(BLUEPRINTS[arm], bp)
    (ART / "inputs").mkdir()
    for name, path in assets.items():
        shutil.copyfile(path, ART / "inputs" / (name + (".jsonl" if name == "fixtures" else ".json")))
    write(CONFIG, config)
    write(ART / "initialization-tensor-parity.json", parity)
    write(ART / "historical-input-check.json", {"status": "PASS", "count": len(frozen["files"]), "files": frozen["files"], "new_games": 0})
    write(ART / "rust-source-check.json", {"status": "PASS", "count": len(rust["files"]), "files": rust["files"], "new_games": 0})
    write(ART / "profiles.json", {"cloud1": {"host_file": CLOUD + "/host.json", "project": CLOUD, "python": config["runtime"]["python"],
                                            "root": CLOUD, "rpc": CLOUD + "/training/prism_portable/rpc.py", "ssh": "cloud1"}})
    with tarfile.open(ART / "portable-package.tar.gz", "w:gz") as archive:
        for name in audit_sources + ["scripts/prism_balance_ab_prepare_m61.py"]:
            archive.add(ROOT / name, arcname=name, recursive=False)
        for p in sorted((ROOT / "training/prism_portable").rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                archive.add(p, arcname=p.relative_to(ROOT).as_posix(), recursive=False)
        init = ROOT / "training/__init__.py"
        if init.exists():
            archive.add(init, arcname="training/__init__.py", recursive=False)
    receipt = {"status": "FROZEN", "new_games": 0, "config_sha256": digest(CONFIG),
               "blueprint_sha256": {k: digest(p) for k, p in BLUEPRINTS.items()},
               "package_archive_sha256": digest(ART / "portable-package.tar.gz"),
               "code_identity": package_identity(), "numerical_identity": numerical_identity(),
               "prepare_source_sha256": digest(__file__), "initialization_tensor_parity_sha256": digest(ART / "initialization-tensor-parity.json")}
    write(ART / "freeze-receipt.json", receipt)
    print(json.dumps(receipt))


def serial_train(config_path):
    """Single non-retrying durable sequencer. Balance is not initialized before Alpha ends."""
    import gc
    import os
    import time
    import traceback
    from training.prism_portable.control import host_config, start, status
    from training.prism_portable.protocol import create, state_digest
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.processes import cgroup_accounting, systemctl
    config = read(config_path)
    root = Path(config["runtime"]["cloud_root"])
    receipts = root / "training-receipts"
    receipts.mkdir(exist_ok=True)
    final_path = receipts / "serial-final.json"
    if (receipts / "serial-start.json").exists():
        raise ValueError("serial campaign already launched; no automatic restart")
    for name, sha in config["runtime"]["source_hashes"].items():
        if digest(root / name) != sha:
            raise ValueError("deployed source drift: " + name)
    if package_identity() != config["runtime"]["package_identity"]:
        raise ValueError("portable package drift")
    host = host_config(root / "host.json")
    for name, row in config["assets"].items():
        if host["assets"][name]["sha256"] != row["sha256"]:
            raise ValueError("host asset binding drift: " + name)
    for name in ("engine", "metrics"):
        if host["assets"][name] != config["runtime"][name]:
            raise ValueError("native runtime binding drift: " + name)
    record = {"status": "RUNNING", "started_at": time.time(), "config_sha256": digest(config_path),
              "pid": os.getpid(), "arms": {}, "automatic_retries": 0, "max_training_games": 2048}
    write(receipts / "serial-start.json", record)
    first_initial = None
    try:
        for arm in config["training"]["execution_order"]:
            spec = config["training"]["arms"][arm]
            campaign = Path(spec["campaign"])
            blueprint_path = root / spec["blueprint_path"]
            if digest(blueprint_path) != spec["blueprint_sha256"]:
                raise ValueError("blueprint drift: " + arm)
            arm_receipts = receipts / arm
            arm_receipts.mkdir()
            row = record["arms"][arm] = {"status": "INITIALIZING", "campaign": str(campaign)}
            owner = create(campaign, read(blueprint_path), host, spec["line"])
            write(arm_receipts / "create.json", {"campaign": str(campaign), "ownership": owner})
            initial = read(campaign / "initialization.json")
            head = read(campaign / "run/HEAD.json")
            store = CommitStore(campaign / "run", head["identity"])
            commit = read(campaign / "run/commits" / (initial["commit"] + ".json"))
            state = store.get_payload(commit["payload"])
            if state["optimizer"]["state"] or state["cycle"] != 0 or state["global_step"] != 0:
                raise ValueError("campaign did not start with fresh empty optimizer")
            evidence = {"status": "PASS", "commit": initial["commit"], "commit_payload": commit["payload"],
                        "new_games": 0, "optimizer_state_empty": True,
                        "per_tensor_sha256": {k: state_digest(v) for k, v in state["model"].items()},
                        "rng_sha256": state_digest(state["rng"]), "initialization": initial}
            if first_initial is not None and (evidence["per_tensor_sha256"] != first_initial["per_tensor_sha256"] or
                                               evidence["rng_sha256"] != first_initial["rng_sha256"]):
                raise ValueError("actual arm initial tensors or RNG differ")
            first_initial = evidence
            write(arm_receipts / "initialization-actual.json", evidence)
            shutil.copyfile(campaign / "run/objects" / (commit["payload"] + ".pt"), arm_receipts / "initial-checkpoint.pt")
            del state, store
            gc.collect()
            launch = start(host, campaign, 4)
            write(arm_receipts / "start.json", launch)
            row.update(status="RUNNING", started_at=time.time(), unit=launch["unit"], slice=launch["slice"])
            write(receipts / "serial-status.json", record)
            deadline = read(campaign / "resource-ledger.json")["deadline"]
            arena_observed = False
            started_observed = False
            while True:
                current = status(host, campaign)
                props = systemctl("show", launch["unit"], "--property=ActiveState,SubState,Result,ExecMainStatus,MemoryMax,RuntimeMaxUSec,ControlGroup", check=False).stdout
                slice_props = systemctl("show", launch["slice"], "--property=MemoryMax,CPUQuotaPerSecUSec,ControlGroup", check=False).stdout
                resource = {"observed_at": time.time(), "unit_properties": props, "slice_properties": slice_props,
                            "accounting": cgroup_accounting(launch["slice"])}
                cg = next((line.split("=", 1)[1] for line in slice_props.splitlines() if line.startswith("ControlGroup=")), "")
                events = Path("/sys/fs/cgroup") / cg.lstrip("/") / "memory.events"
                if cg and events.exists():
                    resource["memory_events"] = events.read_text()
                write(arm_receipts / "resource-latest.json", resource)
                write(arm_receipts / "status-latest.json", current)
                if not started_observed and current["status"] == "RUNNING":
                    if "MemoryMax=8589934592" not in props or "MemoryMax=8589934592" not in slice_props or "CPUQuotaPerSecUSec=2s" not in slice_props:
                        raise ValueError("actual worker cgroup does not match 8 GiB/CPU200% contract")
                    write(arm_receipts / "startup-observation.json", {"status": current, "launch": launch, "resources": resource})
                    started_observed = True
                if not arena_observed:
                    completed = next(campaign.glob("attempts/*/completion.json"), None)
                    if completed is not None:
                        write(arm_receipts / "first-arena-observation.json", {"status": "OBSERVED_REAL_TRAINING_COMPLETION",
                              "path": str(completed), "sha256": digest(completed), "completion": read(completed),
                              "scope": "existing authorized training game; no extra preflight game"})
                        arena_observed = True
                if current["status"] not in ("RUNNING", "STARTING", "NOT_STARTED"):
                    for _ in range(15):
                        if not current.get("alive"):
                            break
                        time.sleep(1)
                        current = status(host, campaign)
                    break
                if time.time() > deadline + 60:
                    raise RuntimeError("owned arm exceeded original deadline; supervisor evidence retained")
                time.sleep(10)
            write(arm_receipts / "final-status.json", current)
            write(arm_receipts / "final-resource.json", resource)
            row.update(status=current["status"], finished_at=time.time(), resources=current.get("resources"),
                       resource_receipt_sha256=digest(arm_receipts / "final-resource.json"))
            if current["status"] != "STOPPED_COMMITTED" or current.get("alive"):
                raise RuntimeError(arm + " training failed/interrupted; stop without retry or second arm")
            progress = read(campaign / "control/progress.json")
            if progress["cycle"] != 4 or progress["attempts"] != 1024 or len(progress["jobs"]) != 256 or len(progress["consumed"]) != 4:
                raise ValueError("final committed training counts mismatch")
            for path in sorted(campaign.glob("cycle-*-summary.json")):
                shutil.copyfile(path, arm_receipts / path.name)
            for path in sorted(campaign.glob("cycle-*-portable-summary.json")):
                shutil.copyfile(path, arm_receipts / path.name)
            for number in range(1, 5):
                shutil.copytree(campaign / f"cycle-{number}-export", arm_receipts / f"cycle-{number}-export")
            for path in (campaign / "control").glob("*.json"):
                shutil.copyfile(path, arm_receipts / ("control-" + path.name))
            for path in (campaign / "control").glob("*.log"):
                shutil.copyfile(path, arm_receipts / ("control-" + path.name))
            shutil.copyfile(campaign / "resource-ledger.json", arm_receipts / "resource-ledger.json")
            head = read(campaign / "run/HEAD.json")
            commit = read(campaign / "run/commits" / (head["commit"] + ".json"))
            shutil.copyfile(campaign / "run/objects" / (commit["payload"] + ".pt"), arm_receipts / "final-checkpoint.pt")
            shutil.copyfile(campaign / "run/HEAD.json", arm_receipts / "final-HEAD.json")
            shutil.copyfile(campaign / "run/commits" / (head["commit"] + ".json"), arm_receipts / "final-commit.json")
            row.update(progress=progress, final_weights_sha256=digest(campaign / "cycle-4-export/weights.json"))
            write(receipts / "serial-status.json", record)
        record.update(status="TRAINING_COMPLETED_PENDING_INDEPENDENT_AUDIT", finished_at=time.time(), training_games=2048)
        write(final_path, record)
    except BaseException as exc:
        record.update(status="FAILED_STOPPED_NO_RETRY", finished_at=time.time(), error=type(exc).__name__ + ": " + str(exc), traceback=traceback.format_exc())
        write(final_path, record)
        raise
    finally:
        files = {p.relative_to(receipts).as_posix(): digest(p) for p in sorted(receipts.rglob("*")) if p.is_file()}
        write(root / "training-evidence-manifest.json", {"config_sha256": digest(config_path), "files": files})
        with tarfile.open(root / "training-evidence.tar.gz", "w:gz", compresslevel=1) as archive:
            archive.add(receipts, arcname="training-receipts")
            archive.add(root / "training-evidence-manifest.json", arcname="training-evidence-manifest.json")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--serial":
        serial_train(sys.argv[2])
    else:
        prepare()
