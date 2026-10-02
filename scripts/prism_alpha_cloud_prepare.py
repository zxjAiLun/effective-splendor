"""Freeze the finite M59 cloud PPO contract before its first real game."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import digest, identity, numerical_identity, package_identity, read, write

ART = ROOT / "local-artifacts/prism/alpha-cloud-m59"
CONFIG = ROOT / "benchmarks/m59-prism-alpha-cloud-ppo.config.json"
BLUEPRINT = ROOT / "benchmarks/m59-prism-alpha-cloud-ppo.train.json"
CLOUD = "/home/ubuntu/splendor-ppo-m59"
LINE = "m59-alpha-bigcard"


def prepare():
    if CONFIG.exists() or BLUEPRINT.exists() or ART.exists():
        raise ValueError("M59 is already reserved; do not overwrite its frozen contract")
    m56 = read(ROOT / "benchmarks/m56-prism-alpha-v0.1.1.config.json")
    m57 = read(ROOT / "benchmarks/m57-prism-portable-ppo.config.json")
    assets = {
        "parent": ROOT / "local-artifacts/prism/alpha-v0.1.1/weights.json",
        "general": ROOT / "local-artifacts/prism/v0.1.1/weights.json",
        "initial": ROOT / "local-artifacts/prism/v01/run/weights.json",
        "fixtures": ROOT / "local-artifacts/prism/portable-m57/inputs/boundary-fixtures.jsonl",
    }
    expected = {"parent": "d57ebe2407b5d061ae890f3d2586924754e0d2d8e502e1f3f32d12c1fc9af4ff",
                "general": "a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85",
                "initial": "5db70b773083858b83c6e679d5641f1b78d4c5fbe34c48950cc906064f821b54",
                "fixtures": "81c3f01dcd0d31fcb7dc54acfd125892a2692ff13e31a996889282d35ea817c1"}
    for name, path in assets.items():
        if digest(path) != expected[name]:
            raise ValueError("fixed input drift: " + name)
    frozen = read(ROOT / "local-artifacts/prism/portable-m57/original-frozen-inputs.json")
    for path, value in frozen["files"].items():
        if digest(ROOT / path) != value:
            raise ValueError("historical frozen input drift: " + path)

    module_spec = importlib.util.spec_from_file_location("old_seed_registry", ROOT / "scripts/s0_seed_registry.py")
    registry = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(registry)
    historical = list(registry.REGISTRY) + [tuple(r) for r in m56["seed_reservations"]]
    for name, bp in m57["blueprints"].items():
        seeds = [j["environment_seed"] for c in bp["template"]["cycles"] for j in c]
        historical.append((min(seeds), max(seeds), "m57-" + name))
    reservations = [(9590000, 9590511, "m59-training"),
                    (9595000, 9595031, "m59-development-never-train"),
                    (9600000, 9600511, "m59-independent-never-train")]
    for lo, hi, label in reservations:
        for old_lo, old_hi, old_label in historical:
            if max(lo, old_lo) <= min(hi, old_hi):
                raise ValueError(label + " overlaps " + old_label)

    bp = copy.deepcopy(m57["blueprints"]["calibration"])
    bp.update(purpose="finite-model-training-bigcard-continuation", cancel_fixture=False,
              model_label="M59 unpublished final-c4 candidate, warm-started from Prism Alpha v0.1.1")
    bp["weight_hashes"] = {k: expected[k] for k in ("parent", "initial", "general")}
    t = bp["template"]
    run = t["run"]
    run.update(run_id=LINE, seed=59010001)
    run["budget"].update(max_cycles=4, max_jobs=1024, max_attempts=1024,
                         max_decisions=262144, max_job_decisions=256,
                         max_optimizer_steps=2048, max_update_attempts=2048,
                         max_run_seconds=28800, max_storage_bytes=32 * 1024**3)
    t["limits"].update(campaign_cpu_seconds=40000, memory_bytes=4 * 1024**3,
                       max_physical_decisions=262144)
    heuristic = t["opponents"].pop("heuristic-v031")
    # This is the portable ARM source snapshot, not the M56 frozen Windows teacher.
    t["opponents"]["heuristic-portable-v029"] = heuristic
    for name, asset, seed in [("prism-general-v011", "general", 59010002),
                               ("alpha-parent-v011", "parent", 59010003)]:
        row = copy.deepcopy(t["opponents"]["prism-v01"])
        row["args"] = ["agent-prism", "--weights", "@" + asset, "--seed", str(seed)]
        row["files"] = {"@" + asset: "@" + asset + "_sha256"}
        t["opponents"][name] = row
    run["opponents"] = {name: "" for name in t["opponents"]}
    order = ["prism-general-v011", "alpha-parent-v011", "prism-general-v011", "prism-v01",
             "prism-general-v011", "alpha-parent-v011", "prism-general-v011", "heuristic-portable-v029"]
    t["cycles"] = [[{"job_id": f"m59-c{c+1}-b{b}-s{s}", "actor": s,
                     "opponent_id": order[b % 8], "environment_seed": 9590000 + c * 128 + b}
                    for b in range(128) for s in (0, 1)] for c in range(4)]
    if run["ppo"] != m57["blueprints"]["calibration"]["template"]["run"]["ppo"]:
        raise ValueError("PPO parameters changed unexpectedly")
    development = copy.deepcopy(m56["development"])
    development.update(seed_start=9595000, seed_end=9595031, action_seed=59020001)
    development["anchors"] = ["heuristic-portable-v029", "prism-v01", "prism-general-v011"]
    acceptance = copy.deepcopy(m56["acceptance"])
    acceptance.update(seed_start=9600000, seed_end=9600255, direct_seed_end=9600511,
                      action_seed=59020001, bootstrap_rng_seed=59029999)
    acceptance["anchors"] = ["heuristic-portable-v029", "prism-v01", "prism-general-v011"]
    sources = {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p)
               for p in sorted((ROOT / "training/prism_portable").rglob("*.py"))}
    sources["scripts/prism_alpha_cloud_prepare.py"] = digest(__file__)
    native = read(ROOT / "local-artifacts/prism/portable-m57/cloud1-evidence/host.json")["assets"]
    config = {
        "format": "m59-prism-alpha-cloud-ppo-v1", "status": "FROZEN_BEFORE_FIRST_GAME",
        "owner_authorization": "在云端现在启动迭代训练", "frozen_at": datetime.now(timezone.utc).isoformat(),
        "baseline_git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "base_model": {"name": "Prism Alpha v0.1.1", "path": str(assets["parent"]), "sha256": expected["parent"]},
        "candidate": {"label": "M59 unpublished final-c4 training candidate", "release_name_if_accepted": "Prism Alpha v0.1.2",
                      "checkpoint_selection": "only final c4; no development selection", "status": "NOT_RUN"},
        "start_from": "fixed parent inference weights; fresh AdamW, style head and RNG; not an M57 calibration checkpoint",
        "seed_reservations": reservations,
        "seed_collision_check": {"status": "PASS", "prior_ranges": len(historical), "prior_registry_sha256": digest(ROOT / "scripts/s0_seed_registry.py"),
                                 "m56_config_sha256": digest(ROOT / "benchmarks/m56-prism-alpha-v0.1.1.config.json"),
                                 "m57_config_sha256": digest(ROOT / "benchmarks/m57-prism-portable-ppo.config.json")},
        "training": {"cycles": 4, "games_per_cycle": 256, "total_games": 1024, "action_mode": "categorical-T1 learned policy",
                     "opponents_action_mode": "greedy", "mix": {"prism-general-v011": 512, "alpha-parent-v011": 256,
                     "prism-v01": 128, "heuristic-portable-v029": 128}, "ppo": run["ppo"], "style": run["style"],
                     "blueprint_path": str(BLUEPRINT.relative_to(ROOT)).replace("\\", "/"), "blueprint_identity": identity(bp)},
        "evaluation": {"status": "NOT_RUN", "development": development, "acceptance": acceptance,
                       "candidate_and_parent_mode": "agent-prism-sample T1, action seed 59020001",
                       "anchor_modes": {"heuristic-portable-v029": "greedy", "prism-v01": "greedy", "prism-general-v011": "T1, action seed 59020001"},
                       "native_path_and_sha256": native["engine"], "selection": "one final c4; no retuning/extension after results"},
        "resources": {"wall_seconds_from_initialization": 28800, "cpu_seconds": 40000,
                      "memory_bytes": 4 * 1024**3, "storage_bytes": 32 * 1024**3, "cpu_threads": 2,
                      "cpu_quota_percent": 200, "infrastructure_retries": 0, "wall_deadline_survives_transfer": True},
        "runtime": {"cloud_root": CLOUD, "campaign": CLOUD + "/campaigns/" + LINE + "-g0",
                    "python": "/home/ubuntu/splendor-ppo-m57/venv/bin/python", "package_identity": package_identity(),
                    "numerical_identity": numerical_identity(), "source_hashes": sources,
                    "rust_source_snapshot": read(ROOT / "local-artifacts/prism/portable-m57/rust-source.json"),
                    "engine": native["engine"], "metrics": native["metrics"]},
        "assets": {name: {"path": str(path), "sha256": expected[name]} for name, path in assets.items()},
        "constraints": ["no automatic release/default/shared-pool change", "retain original M55/M56/M57 evidence",
                        "training results are diagnostic; acceptance is NOT_RUN until measured",
                        "report all detailed tables by identity and both seats; inference/decision time NOT_MEASURED"],
        "runtime_caveat": "portable ARM heuristic is version 0.2.9 by Hello, not the frozen M56 Heuristic v0.3.1 Windows teacher; no claim of isolated opponent-mix causality"
    }
    ART.mkdir(parents=True)
    (ART / "inputs").mkdir()
    import shutil
    for name, path in assets.items():
        shutil.copyfile(path, ART / "inputs" / (name + (".jsonl" if name == "fixtures" else ".json")))
    write(BLUEPRINT, bp)
    config["training"]["blueprint_sha256"] = digest(BLUEPRINT)
    write(CONFIG, config)
    write(ART / "historical-input-check.json", {"status": "PASS", "count": len(frozen["files"]), "files": frozen["files"]})
    profile = {"host_file": CLOUD + "/host.json", "project": CLOUD, "python": config["runtime"]["python"],
               "root": CLOUD, "rpc": CLOUD + "/training/prism_portable/rpc.py", "ssh": "cloud1"}
    write(ART / "profiles.json", {"cloud1": profile})
    with tarfile.open(ART / "portable-package.tar.gz", "w:gz") as archive:
        for p in sorted((ROOT / "training/prism_portable").rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                archive.add(p, arcname=str(p.relative_to(ROOT)), recursive=False)
        init = ROOT / "training/__init__.py"
        if init.exists():
            archive.add(init, arcname="training/__init__.py", recursive=False)
    receipt = {"status": "FROZEN", "config_sha256": digest(CONFIG), "blueprint_sha256": digest(BLUEPRINT),
               "package_archive_sha256": digest(ART / "portable-package.tar.gz"), "new_games": 0,
               "code_identity": package_identity(), "numerical_identity": numerical_identity()}
    write(ART / "freeze-receipt.json", receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    prepare()
