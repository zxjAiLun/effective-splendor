"""M62 same-parent building experiment freeze and non-retrying serial controller.

Draft builders perform no writes. `prepare --project PATH` freezes only after
registered M61 re-audit evidence, source checks and readiness receipt pass.
`serial --project PATH --serial-unit UNIT` is for the bounded cloud controller.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import digest, identity, numerical_identity, package_identity, read, write

ART_REL = "local-artifacts/prism/building-beta-m62"
CONFIG_REL = "benchmarks/m62-prism-beta-building.config.json"
CONFIG = ROOT / CONFIG_REL
ART = ROOT / ART_REL
ARMS = ("control", "beta")
BLUEPRINT_RELS = {arm: f"benchmarks/m62-prism-{arm}-building.train.json" for arm in ARMS}
CLOUD = "/home/ubuntu/splendor-ppo-m62"
PARENT = "225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1"
ALPHA = "d3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9"
LABELS = {"control": "Prism Balance v0.1.1 CANDIDATE", "beta": "Prism Beta v0.1.0 CANDIDATE"}
RESERVATIONS = [(9631000, 9631511, "m62-training-paired-arms"),
                (9636000, 9636031, "m62-development-never-train"),
                (9641000, 9641511, "m62-independent-never-train")]
MIX = {"prism-general-v011": 512, "balance-parent-v010": 256, "prism-v01": 128, "heuristic-v031": 128}
ORDER = ["prism-general-v011", "balance-parent-v010", "prism-general-v011", "prism-v01",
         "prism-general-v011", "balance-parent-v010", "prism-general-v011", "heuristic-v031"]
GATES = {"control/strength_pool": -.05, "control/direct_parent": .45,
         "beta/strength_pool": -.05, "beta/general_anchor": -.075,
         "beta/direct_control": .45, "beta/direct_alpha": .45, "beta/direct_parent": .45,
         "beta/building_utility": .015, "beta/early_bonus_auc12": .25}
SCRIPTS = ["scripts/prism_building_prepare_m62.py", "scripts/prism_building_audit_m62.py",
           "scripts/prism_building_training_report_m62.py", "scripts/prism_building_evaluation_m62.py",
           "scripts/prism_building_report_m62.py", "scripts/prism_portable_report.py"]


def require(value, message):
    if not value:
        raise ValueError("M62 prepare: " + message)


def serialized_sha(value):
    return hashlib.sha256((json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()).hexdigest()


def building_config():
    from training.prism_portable.engine.ppo.building import default_building_config
    return default_building_config()


def build_blueprints(previous, expected):
    """Pure draft construction from the fixed M61 Balance blueprint."""
    result = {}
    for arm in ARMS:
        bp = copy.deepcopy(previous)
        bp.update(purpose="finite-same-parent-building-control-beta", cancel_fixture=False, model_label=LABELS[arm])
        bp["weight_hashes"] = {key: expected[key] for key in ("parent", "general", "initial")}
        template = bp["template"]
        template["opponents"]["balance-parent-v010"] = template["opponents"].pop("alpha-parent-v013")
        template["opponents"]["balance-parent-v010"]["args"][-1] = "62041003"
        template["opponents"]["prism-general-v011"]["args"][-1] = "62041002"
        run = template["run"]
        run.update(run_id=f"m62-{arm}-building", seed=62041001, style=building_config())
        run["opponents"] = {name: "" for name in template["opponents"]}
        run["ppo"].update(style_beta=.3 if arm == "beta" else 0.0,
                          style_value_weight=.5 if arm == "beta" else 0.0)
        template["cycles"] = [[{"job_id": f"m62-{arm}-c{cycle+1}-b{block}-s{seat}", "actor": seat,
                                "opponent_id": ORDER[block % 8], "environment_seed": 9631000+cycle*128+block}
                               for block in range(128) for seat in (0, 1)] for cycle in range(4)]
        result[arm] = bp
    return result


def validate_blueprints(blueprints):
    require(set(blueprints) == set(ARMS), "expected exactly control/beta")
    normalized = []
    for arm in ARMS:
        bp = blueprints[arm]
        template, run = bp["template"], bp["template"]["run"]
        require(bp["model_label"] == LABELS[arm], "model version/label drift")
        require(run["run_id"] == f"m62-{arm}-building" and run["seed"] == 62041001, "run identity/seed drift")
        require(run["style"] == building_config(), "building contract drift")
        require((run["ppo"]["style_beta"], run["ppo"]["style_value_weight"]) ==
                ((.3, .5) if arm == "beta" else (0, 0)), "style coefficient drift")
        require(set(template["opponents"]) == set(run["opponents"]) == set(MIX), "opponent set drift")
        require(all(row["mode"] == "greedy" for row in template["opponents"].values()), "training opponents must be greedy")
        for name, seed in (("prism-general-v011", "62041002"), ("balance-parent-v010", "62041003")):
            require(template["opponents"][name]["args"][-2:] == ["--seed", seed], "opponent action seed drift")
        expected = [[{"job_id": f"m62-{arm}-c{c+1}-b{b}-s{s}", "actor": s,
                      "opponent_id": ORDER[b % 8], "environment_seed": 9631000+c*128+b}
                     for b in range(128) for s in (0, 1)] for c in range(4)]
        require(template["cycles"] == expected, "exact paired schedule/count/order drift")
        budget, limits = run["budget"], template["limits"]
        require(tuple(budget[k] for k in ("max_cycles", "max_jobs", "max_attempts", "max_run_seconds", "max_storage_bytes")) ==
                (4, 1024, 1024, 28800, 32*1024**3), "bounded campaign budget drift")
        require(limits["memory_bytes"] == 8*1024**3 and limits["campaign_cpu_seconds"] == 40000 and
                limits["max_infra_retries"] == 0 and run["cpu_threads"] == 2, "resource ceiling drift")
        x = copy.deepcopy(bp)
        x.pop("model_label")
        x["template"]["run"].pop("run_id")
        for key in ("style_beta", "style_value_weight"):
            x["template"]["run"]["ppo"].pop(key)
        for cycle in x["template"]["cycles"]:
            for job in cycle:
                job.pop("job_id")
        normalized.append(x)
    require(normalized[0] == normalized[1], "arms differ outside identity/two coefficients")


def evaluation_contract():
    anchors = ["heuristic-v031", "prism-v01", "prism-general-v011"]
    models = ["base", "control", "beta"]
    return {"status": "NOT_RUN", "total_games": 9280,
            "candidate_and_parent_mode": "agent-prism-sample T1, action seed 62042001",
            "anchor_modes": {"heuristic-v031": "greedy", "prism-v01": "greedy", "prism-general-v011": "T1, action seed 62042001"},
            "selection": "only final c4; no tuning, checkpoint selection or grid extension",
            "development": {"seed_start": 9636000, "seed_end": 9636031, "blocks": 32, "total_games": 576,
                            "models": models, "anchors": anchors, "action_seed": 62042001,
                            "selection": "descriptive only; final c4 fixed before samples; no tuning"},
            "acceptance": {"seed_start": 9641000, "seed_end": 9641255, "direct_seed_end": 9641511,
                           "blocks": 256, "direct_blocks": 512, "action_seed": 62042001,
                           "models": models, "anchors": anchors, "anchor_total_games": 4608,
                           "direct_parent_games": 2048, "between_arms_games": 1024, "direct_alpha_games": 1024,
                           "direct_total_games": 4096, "total_games": 8704, "total_physical_budget": 11328,
                           "direct_pairs": [["control", "base"], ["beta", "base"], ["beta", "control"], ["beta", "alpha"]],
                           "bootstrap_rng_seed": 62049999, "bootstrap_samples": 20000, "family_alpha": .05,
                           "simultaneous_comparisons": 9, "one_sided_claims": 9, "interval_sides": "one-sided",
                           "lower_quantile": .05/9, "shared_draws_for_equal_length_vectors": True,
                           "gates": copy.deepcopy(GATES),
                           "required_gates": {arm: [name.split("/", 1)[1] for name in GATES if name.startswith(arm+"/")] for arm in ARMS},
                           "unused_for_training": True, "no_extension_or_checkpoint_selection": True,
                           "once_only_final_candidate": True,
                           "per_opponent_metrics": "diagnostic only except frozen general_anchor gate",
                           "control_cohort_required": True,
                           "enhancement_reporting": "retention, confirmed enhancement, style and release verdicts separately; no gate relaxation"}}


def build_draft_config(previous_config, blueprints, assets, runtime=None):
    """Pure normative schema for tests and evaluator integration; never freezes."""
    validate_blueprints(blueprints)
    arms = {arm: {"blueprint_path": BLUEPRINT_RELS[arm], "blueprint_sha256": serialized_sha(bp),
                  "blueprint_identity": identity(bp), "campaign": CLOUD+f"/campaigns/m62-{arm}-building-g0",
                  "line": f"m62-{arm}-building", "identity": {"label": LABELS[arm], "status": "CANDIDATE", "published": False},
                  "ppo": copy.deepcopy(bp["template"]["run"]["ppo"]), "style": copy.deepcopy(bp["template"]["run"]["style"])}
            for arm, bp in blueprints.items()}
    rt = copy.deepcopy(runtime if runtime is not None else previous_config["runtime"])
    rt["cloud_root"] = CLOUD
    evaluation = evaluation_contract()
    evaluation["native_path_and_sha256"] = rt["engine"]
    config = {"format": "m62-prism-beta-building-v1", "status": "DESIGNED",
              "base_model": {"name": "Prism Balance v0.1.0", **assets["parent"]},
              "alpha_model": {"name": "Prism Alpha v0.1.4", **assets["alpha"]}, "assets": copy.deepcopy(assets),
              "training": {"arms": arms, "cycles": 4, "games_per_cycle": 256, "games_per_arm": 1024, "total_games": 2048,
                           "run_seed": 62041001, "opponent_action_seeds": {"prism-general-v011": 62041002, "balance-parent-v010": 62041003},
                           "mix_per_arm": copy.deepcopy(MIX), "opponents_action_mode": "greedy",
                           "action_mode": "categorical-T1 learned policy", "execution_order": list(ARMS),
                           "selection": "only each final c4", "initialization": "same fixed Balance parent; fresh AdamW/style head/RNG; no resume",
                           "pairing": "same seed/seat/opponent schedule; differing policies need not share trajectories; single training seed"},
              "seed_reservations": copy.deepcopy(RESERVATIONS), "evaluation": evaluation,
              "resources": {"memory_bytes": 8*1024**3, "cpu_quota_percent": 200, "cpu_seconds": 40000,
                            "cpu_threads": 2, "storage_bytes": 32*1024**3, "wall_seconds_from_initialization": 28800,
                            "infrastructure_retries": 0, "wall_deadline_survives_transfer": True,
                            "scope": "per training arm", "serial_execution": True},
              "serial_resources": {"memory_bytes": 1024**3, "cpu_quota_percent": 20, "wall_seconds": 17*3600},
              "runtime": rt, "heuristic_identity": copy.deepcopy(previous_config["heuristic_identity"]),
              "constraints": ["preserve historical source/config/results", "create beta only after control stopped committed",
                              "no retry or extension", "independent evaluation required for competitive/style verdict",
                              "no default, pool, Studio or deployment change"]}
    validate_config(config, blueprints)
    return config


def validate_config(config, blueprints=None):
    require(config["format"] == "m62-prism-beta-building-v1", "config format")
    require(set(config["assets"]) == {"parent", "general", "initial", "fixtures", "alpha"}, "asset set drift")
    require(config["base_model"]["name"] == "Prism Balance v0.1.0" and config["base_model"]["sha256"] ==
            config["assets"]["parent"]["sha256"] == PARENT, "registered parent identity drift")
    require(config["alpha_model"]["name"] == "Prism Alpha v0.1.4" and config["alpha_model"]["sha256"] ==
            config["assets"]["alpha"]["sha256"] == ALPHA, "fixed Alpha identity drift")
    training = config["training"]
    require(training["execution_order"] == list(ARMS) and set(training["arms"]) == set(ARMS), "serial arm order drift")
    require([training[k] for k in ("cycles", "games_per_cycle", "games_per_arm", "total_games", "run_seed")] ==
            [4, 256, 1024, 2048, 62041001] and training["mix_per_arm"] == MIX, "training count/mix/seed drift")
    require(training["opponent_action_seeds"] == {"prism-general-v011": 62041002, "balance-parent-v010": 62041003}, "action seed drift")
    require([list(r) for r in config["seed_reservations"]] == [list(r) for r in RESERVATIONS], "reservations drift")
    expected = evaluation_contract()
    for section in ("development", "acceptance"):
        for key, value in expected[section].items():
            require(config["evaluation"][section].get(key) == value, "evaluation contract drift: "+section+"/"+key)
    require(config["evaluation"]["total_games"] == 9280 and config["runtime"]["cloud_root"] == CLOUD, "total/cloud root drift")
    require(config["resources"] == {"memory_bytes": 8*1024**3, "cpu_quota_percent": 200, "cpu_seconds": 40000,
            "cpu_threads": 2, "storage_bytes": 32*1024**3, "wall_seconds_from_initialization": 28800,
            "infrastructure_retries": 0, "wall_deadline_survives_transfer": True, "scope": "per training arm", "serial_execution": True}, "resource contract drift")
    require(config["serial_resources"] == {"memory_bytes": 1024**3, "cpu_quota_percent": 20, "wall_seconds": 61200}, "serial resource drift")
    if blueprints is not None:
        validate_blueprints(blueprints)
        for arm, bp in blueprints.items():
            row = training["arms"][arm]
            require(row["blueprint_identity"] == identity(bp) and row["blueprint_sha256"] == serialized_sha(bp), "blueprint binding drift")
            require(row["style"] == bp["template"]["run"]["style"] and row["ppo"] == bp["template"]["run"]["ppo"], "arm numerical binding drift")
            require(bp["weight_hashes"] == {name: config["assets"][name]["sha256"] for name in ("parent", "general", "initial")}, "blueprint weights drift")
    return config


def initialization_parity(parent, catalog):
    import torch
    from training.prism_portable.engine.ppo.model import warm_start
    from training.prism_portable.protocol import state_digest
    aa, bb = [warm_start(parent, catalog, style_enabled=enabled, initialization_seed=62041001).state_dict()
              for enabled in (False, True)]
    require(set(aa) == set(bb) and len(aa) == 36 and all(torch.equal(aa[k], bb[k]) for k in aa), "initial 36 tensors unequal")
    return {"status": "PASS", "new_games": 0, "policy_value_tensor_count": 32, "all_tensor_count": 36,
            "per_tensor_sha256": {k: state_digest(v) for k, v in aa.items()}, "model_state_sha256": state_digest(aa),
            "initialization_seed": 62041001, "style_enabled": {"control": False, "beta": True}}


def dynamic_seed_ranges(value, label):
    found = []
    if isinstance(value, dict):
        if type(value.get("seed_start")) is int:
            lo = value["seed_start"]
            ends = [value[k] for k in ("seed_end", "direct_seed_end") if type(value.get(k)) is int]
            counts = [value[k] for k in ("seed_count", "blocks", "seed_blocks", "games", "total_games") if type(value.get(k)) is int]
            found.append((lo, max(ends) if ends else lo+max(counts, default=1)-1, label))
        for key, item in value.items():
            if "seed" in key and type(item) is int:
                found.append((item, item, label+"/"+key))
            if key == "seed_reservations" and isinstance(item, list):
                found.extend((r[0], r[1], label+"/"+str(r[2])) for r in item if isinstance(r, list) and len(r) == 3)
            found.extend(dynamic_seed_ranges(item, label+"/"+key))
    elif isinstance(value, list):
        for index, row in enumerate(value):
            found.extend(dynamic_seed_ranges(row, label+"/"+str(index)))
    return found


def source_change_check(project):
    ledger_path = project / ART_REL / "round-start-source-ledger.json"
    ledger = read(ledger_path)
    require(ledger["format"] == "m62-before-source-ledger-v1", "source-before ledger format")
    allowed = {"training/prism_portable/engine/ppo/style.py", "training/prism_portable/engine/ppo/coordinator.py"}
    changes = {}
    for name, expected in ledger["files"].items():
        archived = project / ART_REL / "source-before" / name
        if name.startswith("training/"):
            require(digest(archived) == expected, "archived original source drift: "+name)
        current = digest(project / name)
        if current != expected:
            require(name in allowed, "unauthorized legacy source drift: "+name)
            changes[name] = {"before": expected, "current": current}
    require(set(changes) == allowed, "both new style/coordinator sources must be ready")
    return {"status": "PASS", "ledger_path": str(ledger_path), "ledger_sha256": digest(ledger_path), "changes": changes,
            "new_source": {"training/prism_portable/engine/ppo/building.py": digest(project / "training/prism_portable/engine/ppo/building.py")}}


def registered_inputs(project):
    """Use the registrar's exact evidence validator, never a synthetic PASS flag."""
    from scripts import prism_m61_version_records as registrar
    result = read(project / "local-artifacts/prism/balance-ab-m61/result.json")
    records, evidence = {}, {}
    for asset, arm, version, expected in (("parent", "balance", "0.1.0", PARENT), ("alpha", "alpha", "0.1.4", ALPHA)):
        record_path = project / f"benchmarks/m61-prism-{arm}-v{version}.model.json"
        row = read(record_path)
        require(row["status"] == "REGISTERED_EXPERIMENTAL_MODEL" and row["weights_sha256"] == expected and
                row["model_version"] == version, "registered identity drift: "+asset)
        for key in ("weights", "companion"):
            require(digest(project / row[key+"_path"]) == row[key+"_sha256"], "registered artifact drift: "+asset+"/"+key)
        reaudit = registrar.validate_reaudit(project, row["reaudit"]["completion"]["path"], result,
                                             row["reaudit"]["fetch_receipt"]["path"])
        require(row["reaudit"] == {k: v for k, v in reaudit.items() if k != "candidates"}, "registered re-audit chain drift")
        records[asset] = {"path": str(project / row["weights_path"]), "sha256": expected}
        evidence[asset] = {"record": {"path": str(record_path), "sha256": digest(record_path)},
                           "companion": {"path": str(project / row["companion_path"]), "sha256": row["companion_sha256"]},
                           "reaudit": row["reaudit"]}
    return records, evidence


def readiness_check(project):
    path = project / ART_REL / "helper-readiness.json"
    row = read(path)
    require(row.get("format") == "m62-helper-readiness-v1" and row.get("status") == "PASS" and
            row.get("freeze_authorized") is True and row.get("new_games") == 0, "main readiness/freeze authorization missing")
    require(row.get("checks") and all(c.get("exit_code") == 0 and c.get("argv") for c in row["checks"]), "tests not ready")
    require(set(SCRIPTS) <= set(row.get("source_hashes", {})) and
            any("test_m62" in name for name in row["source_hashes"]), "helpers/tests not bound")
    for name, expected in row["source_hashes"].items():
        require(digest(project / name) == expected, "readiness source drift: "+name)
    return {"path": str(path), "sha256": digest(path)}


def prepare(project=ROOT):
    project = Path(project).resolve()
    art, config_path = project / ART_REL, project / CONFIG_REL
    require(not config_path.exists() and not (art / "freeze-receipt.json").exists() and
            not any((project / name).exists() for name in BLUEPRINT_RELS.values()), "M62 already reserved; never overwrite")
    for name in ("inputs", "portable-package.tar.gz", "initialization-tensor-parity.json", "profiles.json", "source-change-check.json"):
        require(not (art / name).exists(), "preparation output already exists: "+name)
    readiness = readiness_check(project)
    change_check = source_change_check(project)
    old = read(project / "benchmarks/m61-prism-alpha-balance-ab.config.json")
    assets = {k: copy.deepcopy(old["assets"][k]) for k in ("general", "initial", "fixtures")}
    registered, versions = registered_inputs(project)
    assets.update(registered)
    for name, row in assets.items():
        require(digest(row["path"]) == row["sha256"], "fixed asset drift: "+name)
    rust = read(project / "local-artifacts/prism/portable-m57/rust-source.json")
    frozen = read(project / "local-artifacts/prism/portable-m57/original-frozen-inputs.json")
    for evidence in (rust, frozen):
        for name, expected in evidence["files"].items():
            require(digest(project / name) == expected, "historical input drift: "+name)
    require(len(old["heuristic_identity"]["source_hashes"]) == 7, "seven heuristic source pins required")
    for name, expected in old["heuristic_identity"]["source_hashes"].items():
        require(digest(project / name) == expected, "heuristic source drift: "+name)
    spec = importlib.util.spec_from_file_location("m62_seed_registry", project / "scripts/s0_seed_registry.py")
    registry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(registry)
    historical, files = list(registry.REGISTRY), {}
    for path in sorted((project / "benchmarks").glob("*.json")):
        if path.name.startswith("m62-") or not any(token in path.name for token in (".config.", ".train.", ".evaluate.", ".evaluation-execution.")):
            continue
        files[path.relative_to(project).as_posix()] = digest(path)
        historical.extend(dynamic_seed_ranges(read(path), path.name))
    for lo, hi, label in RESERVATIONS:
        for old_lo, old_hi, old_label in historical:
            require(max(lo, old_lo) > min(hi, old_hi), label+" overlaps "+old_label)
    bps = build_blueprints(read(project / "benchmarks/m61-prism-balance-ab.train.json"), {k: v["sha256"] for k, v in assets.items()})
    sources = {p.relative_to(project).as_posix(): digest(p) for p in sorted((project / "training/prism_portable").rglob("*.py")) if "tests" not in p.parts}
    sources.update({name: digest(project / name) for name in SCRIPTS})
    rt = {k: copy.deepcopy(old["runtime"][k]) for k in ("python", "engine", "metrics", "rust_source_snapshot")}
    ready_runtime = read(project / ART_REL / "helper-readiness.json").get("runtime", {})
    require({"projection", "projection_source_snapshot", "bigcard_metrics"} <= set(ready_runtime), "projection/native tools not ready")
    rt.update({key: copy.deepcopy(ready_runtime[key]) for key in ("projection", "projection_source_snapshot", "bigcard_metrics")})
    require(all(set(rt[name]) == {"path", "sha256"} and len(rt[name]["sha256"]) == 64
                for name in ("projection", "bigcard_metrics")), "tool descriptors require exact path/SHA")
    require(rt["projection_source_snapshot"].get("files"), "projection exporter source pins missing")
    for name, expected in rt["projection_source_snapshot"]["files"].items():
        require(digest(project / name) == expected, "projection exporter source drift: "+name)
    rt.update(package_identity=package_identity(), numerical_identity=numerical_identity(), source_hashes=sources)
    require(rt["package_identity"] != old["runtime"]["package_identity"] and rt["numerical_identity"] != old["runtime"]["numerical_identity"], "new style must have new numerical/package identities")
    config = build_draft_config(old, bps, assets, rt)
    config.update(status="FROZEN_BEFORE_FIRST_GAME", frozen_at=datetime.now(timezone.utc).isoformat(),
                  baseline_git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip(),
                  owner_authorization="Beta route and experimental versions authorized; bounded same-parent control",
                  registered_models=versions, helper_readiness=readiness, source_change_check=change_check,
                  seed_collision_check={"status": "PASS", "prior_ranges": len(historical), "dynamic_files_sha256": files})
    parity = initialization_parity(assets["parent"]["path"], bps["control"]["template"]["run"]["catalog_fingerprint"])
    art.mkdir(parents=True, exist_ok=True)  # the immutable source-before archive already lives here
    for arm, bp in bps.items():
        write(project / BLUEPRINT_RELS[arm], bp)
    (art / "inputs").mkdir()
    for name, row in assets.items():
        shutil.copyfile(row["path"], art / "inputs" / (name+(".jsonl" if name == "fixtures" else ".json")))
    write(config_path, config)
    write(art / "initialization-tensor-parity.json", parity)
    write(art / "source-change-check.json", change_check)
    write(art / "profiles.json", {"cloud1": {"host_file": CLOUD+"/host.json", "project": CLOUD, "python": rt["python"],
                                           "root": CLOUD, "rpc": CLOUD+"/training/prism_portable/rpc.py", "ssh": "cloud1"}})
    with tarfile.open(art / "portable-package.tar.gz", "w:gz") as archive:
        for name in SCRIPTS:
            archive.add(project / name, arcname=name, recursive=False)
        for path in sorted((project / "training/prism_portable").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.add(path, arcname=path.relative_to(project).as_posix(), recursive=False)
        init = project / "training/__init__.py"
        if init.exists():
            archive.add(init, arcname="training/__init__.py", recursive=False)
    receipt = {"status": "FROZEN", "new_games": 0, "config_sha256": digest(config_path),
               "blueprint_sha256": {arm: digest(project / name) for arm, name in BLUEPRINT_RELS.items()},
               "package_archive_sha256": digest(art / "portable-package.tar.gz"), "code_identity": rt["package_identity"],
               "numerical_identity": rt["numerical_identity"], "prepare_source_sha256": digest(__file__),
               "initialization_tensor_parity_sha256": digest(art / "initialization-tensor-parity.json"),
               "helper_readiness": readiness, "registered_models": versions, "command": list(sys.argv)}
    write(art / "freeze-receipt.json", receipt)
    return receipt


def storage_snapshot(root):
    """Only disappearing entries are tolerated; other I/O failures abort."""
    total = 0
    for path in Path(root).rglob("*"):
        try:
            metadata = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISREG(metadata.st_mode):
            total += metadata.st_size
    return total


def parse_properties(text):
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def controller_resources(unit):
    from training.prism_portable.processes import systemctl
    require(unit and unit.startswith("prism-m62-training-serial-") and unit.endswith(".service"), "owned serial unit required")
    props = parse_properties(systemctl("show", unit, "--property=MainPID,MemoryMax,CPUQuotaPerSecUSec,RuntimeMaxUSec,ControlGroup").stdout)
    require(props.get("MainPID") == str(os.getpid()), "controller is not owned service MainPID")
    require(props.get("MemoryMax") == str(1024**3) and props.get("CPUQuotaPerSecUSec") == "200ms" and
            props.get("RuntimeMaxUSec") in ("17h", "61200000000"), "serial cgroup must be 1 GiB/20%/17h")
    return props


def validate_final_progress(progress):
    require(progress["cycle"] == 4 and progress["attempts"] == 1024 and
            len(progress["jobs"]) == 256 and len(progress["consumed"]) == len(set(progress["consumed"])) == 4,
            "final committed counts mismatch")


def serial_train(config_path, project, serial_unit):
    """Control first. Beta is created only after Control succeeds and is dead."""
    import gc
    import time
    import traceback
    from training.prism_portable.control import host_config, start, status, stop, hard_kill
    from training.prism_portable.protocol import create, state_digest
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.processes import cgroup_accounting, systemctl
    project = Path(project).resolve()
    config = validate_config(read(config_path))
    require(config["status"] == "FROZEN_BEFORE_FIRST_GAME" and str(project) == CLOUD, "serial requires frozen new cloud project")
    for name, expected in config["runtime"]["source_hashes"].items():
        require(digest(project / name) == expected, "deployed source drift: "+name)
    require(package_identity() == config["runtime"]["package_identity"] and numerical_identity() == config["runtime"]["numerical_identity"], "runtime identity drift")
    controller = controller_resources(serial_unit)
    host = host_config(project / "host.json")
    for name, row in config["assets"].items():
        require(host["assets"][name]["sha256"] == row["sha256"], "host asset binding drift: "+name)
    for name in ("engine", "metrics"):
        require(host["assets"][name] == config["runtime"][name], "native binding drift")
    bps = {arm: read(project / config["training"]["arms"][arm]["blueprint_path"]) for arm in ARMS}
    validate_config(config, bps)
    receipts = project / "training-receipts"
    receipts.mkdir(exist_ok=True)
    require(not (receipts / "serial-start.json").exists() and not (receipts / "serial-final.json").exists(), "serial already launched; no restart")
    require(all(not Path(config["training"]["arms"][arm]["campaign"]).exists() for arm in ARMS), "deferred campaign already exists")
    record = {"status": "RUNNING", "started_at": time.time(), "config_sha256": digest(config_path),
              "pid": os.getpid(), "arms": {}, "automatic_retries": 0, "max_training_games": 2048,
              "controller": controller, "command": list(sys.argv), "source_sha256": digest(__file__)}
    # Exclusive marker makes simultaneous serial invocations fail closed.
    with (receipts / "serial-start.json").open("x", encoding="utf-8") as stream:
        json.dump(record, stream, allow_nan=False)
    first_initial, active = None, None
    try:
        for arm in ARMS:
            spec = config["training"]["arms"][arm]
            campaign = Path(spec["campaign"])
            require(not campaign.exists(), "arm already initialized: "+arm)
            if arm == "beta":
                previous = status(host, config["training"]["arms"]["control"]["campaign"])
                require(previous["status"] == "STOPPED_COMMITTED" and not previous["alive"], "control must finish before beta create")
            arm_receipts = receipts / arm
            arm_receipts.mkdir()
            row = record["arms"][arm] = {"status": "INITIALIZING", "campaign": str(campaign), "created_at": time.time()}
            owner = create(campaign, bps[arm], host, spec["line"])
            active = campaign
            write(arm_receipts / "create.json", {"campaign": str(campaign), "ownership": owner})
            initial = read(campaign / "initialization.json")
            head = read(campaign / "run/HEAD.json")
            store = CommitStore(campaign / "run", head["identity"])
            commit = read(campaign / "run/commits" / (initial["commit"]+".json"))
            state = store.get_payload(commit["payload"])
            require(not state["optimizer"]["state"] and state["cycle"] == state["global_step"] == state["attempts"] == 0, "optimizer not fresh")
            evidence = {"status": "PASS", "commit": initial["commit"], "commit_payload": commit["payload"], "new_games": 0,
                        "optimizer_state_empty": True, "per_tensor_sha256": {k: state_digest(v) for k, v in state["model"].items()},
                        "rng_sha256": state_digest(state["rng"]), "initialization": initial}
            require(len(evidence["per_tensor_sha256"]) == 36, "initial tensor count drift")
            if first_initial is not None:
                require(evidence["per_tensor_sha256"] == first_initial["per_tensor_sha256"] and evidence["rng_sha256"] == first_initial["rng_sha256"], "actual initial 36 tensors/RNG unequal")
            first_initial = evidence
            write(arm_receipts / "initialization-actual.json", evidence)
            del state, store
            gc.collect()
            launch = start(host, campaign, 4)
            write(arm_receipts / "start.json", launch)
            row.update(status="RUNNING", started_at=time.time(), unit=launch["unit"], slice=launch["slice"])
            deadline = read(campaign / "resource-ledger.json")["deadline"]
            observed = False
            while True:
                current = status(host, campaign)
                props = systemctl("show", launch["unit"], "--property=ActiveState,SubState,Result,ExecMainStatus,MemoryMax,RuntimeMaxUSec,ControlGroup", check=False).stdout
                slice_props = systemctl("show", launch["slice"], "--property=MemoryMax,CPUQuotaPerSecUSec,ControlGroup", check=False).stdout
                resource = {"observed_at": time.time(), "unit_properties": props, "slice_properties": slice_props,
                            "accounting": cgroup_accounting(launch["slice"]), "storage_bytes": storage_snapshot(campaign)}
                write(arm_receipts / "resource-latest.json", resource)
                write(arm_receipts / "status-latest.json", current)
                write(receipts / "serial-status.json", record)
                if current["status"] == "RUNNING" and not observed:
                    require("MemoryMax=8589934592" in props and "MemoryMax=8589934592" in slice_props and
                            "CPUQuotaPerSecUSec=2s" in slice_props, "worker cgroup ceiling drift")
                    write(arm_receipts / "startup-observation.json", {"status": current, "launch": launch, "resources": resource})
                    observed = True
                require(resource["storage_bytes"] <= 32*1024**3, "arm storage ceiling exceeded")
                if current["status"] not in ("RUNNING", "STARTING", "NOT_STARTED"):
                    for _ in range(15):
                        if not current.get("alive"):
                            break
                        time.sleep(1)
                        current = status(host, campaign)
                    break
                require(time.time() <= deadline+60, "original arm deadline exceeded")
                time.sleep(10)
            write(arm_receipts / "final-status.json", current)
            write(arm_receipts / "final-resource.json", resource)
            require(current["status"] == "STOPPED_COMMITTED" and not current.get("alive"), arm+" failed; no second arm/retry")
            require(current["resources"]["returncode"] == 0 and current["resources"]["stop_reason"] is None, "resource stop/failure")
            progress = read(campaign / "control/progress.json")
            validate_final_progress(progress)
            row.update(status=current["status"], finished_at=time.time(), progress=progress,
                       final_weights_sha256=digest(campaign / "cycle-4-export/weights.json"), resources=current["resources"],
                       resource_receipt_sha256=digest(arm_receipts / "final-resource.json"))
            for path in sorted(campaign.glob("cycle-*-*summary.json")):
                shutil.copyfile(path, arm_receipts / path.name)
            shutil.copyfile(campaign / "resource-ledger.json", arm_receipts / "resource-ledger.json")
            active = None
            write(receipts / "serial-status.json", record)
        record.update(status="TRAINING_COMPLETED_PENDING_INDEPENDENT_AUDIT", finished_at=time.time(), training_games=2048)
    except BaseException as exc:
        record.update(status="FAILED_STOPPED_NO_RETRY", finished_at=time.time(), error=type(exc).__name__+": "+str(exc), traceback=traceback.format_exc())
        if active is not None:
            try:
                stop(host, active, "force")
                for _ in range(15):
                    if not status(host, active)["alive"]:
                        break
                    time.sleep(1)
                if status(host, active)["alive"]:
                    hard_kill(host, active)
                record["failure_stop"] = status(host, active)
            except BaseException as stop_error:
                record["failure_stop_error"] = str(stop_error)
        raise
    finally:
        write(receipts / "serial-final.json", record)
        write(project / "training-evidence-manifest.json", {"config_sha256": digest(config_path),
              "files": {p.relative_to(receipts).as_posix(): digest(p) for p in sorted(receipts.rglob("*")) if p.is_file()}})
    return record


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("prepare", "serial"), nargs="?", default="prepare")
    result.add_argument("--project", type=Path, default=ROOT)
    result.add_argument("--config", type=Path)
    result.add_argument("--serial", action="store_true", help="alias for serial command")
    result.add_argument("--serial-unit", default=os.environ.get("PRISM_M62_SERIAL_UNIT"))
    return result


def main():
    args = parser().parse_args()
    if args.command == "serial" or args.serial:
        result = serial_train(args.config or args.project / CONFIG_REL, args.project, args.serial_unit)
    else:
        result = prepare(args.project)
    print(json.dumps(result, allow_nan=False, sort_keys=True))


if __name__ == "__main__":
    main()
