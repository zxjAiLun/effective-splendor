"""Freeze M57 diagnostic schedules and package the versioned portable code."""
import copy
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import digest, identity, package_identity, read, write

ART = ROOT / "local-artifacts/prism/portable-m57"


def blueprint(template, name, cycles, games_per_cycle, seed_start, cancel=False):
    spec = copy.deepcopy(template)
    spec["arena"].update(program="@engine", sha256="@engine_sha256")
    spec["learner"] = {"program": "@engine", "sha256": "@engine_sha256"}
    spec["parent_weights"] = "@parent"
    spec["opponents"]["heuristic-v031"].update(program="@engine", sha256="@engine_sha256")
    opponent = spec["opponents"]["prism-v01"]
    opponent.update(program="@engine", sha256="@engine_sha256")
    opponent["args"][2] = "@initial"
    opponent["files"] = {"@initial": "@initial_sha256"}
    spec["run"].update(run_id=name, parent_sha256="@parent_sha256", auditor_sha256="@engine_sha256",
                       arena_contract_sha256="", seed=57010001)
    count = cycles * games_per_cycle
    spec["run"]["budget"].update(max_cycles=cycles, max_jobs=count, max_attempts=count + int(cancel),
                                max_decisions=count * 256, max_optimizer_steps=128,
                                max_update_attempts=128, max_run_seconds=7200,
                                max_storage_bytes=4 * 1024**3)
    spec["limits"].update(max_infra_retries=int(cancel), max_physical_decisions=(count + int(cancel)) * 256,
                          memory_bytes=2 * 1024**3, campaign_cpu_seconds=3600,
                          game_cpu_seconds=30, game_wall_seconds=90)
    spec["cycles"] = []
    seed = seed_start
    names = sorted(spec["opponents"])
    for c in range(cycles):
        jobs = []
        for block in range(games_per_cycle // 2):
            opponent_id = names[block % len(names)]
            for actor in (0, 1):
                jobs.append({"job_id": f"{name}-c{c+1}-b{block}-s{actor}", "actor": actor,
                             "opponent_id": opponent_id, "environment_seed": seed})
            seed += 1
        spec["cycles"].append(jobs)
    return {"format": "prism-portable-blueprint-v1", "purpose": "engineering-calibration-only",
            "model_label": "unpublished engineering learner warm-started from Prism Alpha v0.1.1",
            "template": spec, "cancel_fixture": cancel,
            "weight_hashes": {"parent": digest(ART / "inputs/parent.json"),
                              "initial": digest(ART / "inputs/initial.json")}}


def main():
    config = ROOT / "benchmarks/m57-prism-portable-ppo.config.json"
    if config.exists():
        raise ValueError("M57 config already frozen; do not overwrite")
    template = read(ROOT / "benchmarks/m56-prism-alpha-v0.1.1.train.json")
    plans = {"calibration": blueprint(template, "m57-calibration", 2, 16, 9570000),
             "handoff": blueprint(template, "m57-handoff", 3, 4, 9571000),
             "force-local": blueprint(template, "m57-force-local", 2, 4, 9572000, True),
             "force-cloud1": blueprint(template, "m57-force-cloud1", 2, 4, 9573000, True)}
    cfg = {"format": "m57-portable-calibration-v1", "status": "FROZEN_BEFORE_MATCHES",
           "authorized_by": "owner-portability-control-resume-calibration", "code_identity": package_identity(),
           "source_head": "bcdaca7cb33c53cc43d5dcc9e92c07be3c1aaa57",
           "calibration_clones": ["local", "cloud1"], "blueprints": plans,
           "maximum_completed_games": 92, "maximum_interrupted_unpublished_attempts": 2,
           "statistical_scope": "diagnostic throughput; no strength/style acceptance",
           "gates": {"native_parity": {"atol": 1e-4, "rtol": 1e-4, "inputs": 68},
                     "numeric_restore": "model/optimizer/RNG exact state digests and budget counters retained",
                     "ownership": "released source rejected; duplicate target ticket rejected; one active writer",
                     "process_control": "both hosts stop owned descendants and resume without consumed-game replay",
                     "calibration": "same two-cycle/32-game schedule and parameters per host; no speed threshold"}}
    write(config, cfg)
    for name, value in plans.items():
        write(ART / ("blueprints/" + name + ".json"), value)
    files = [p for p in (ROOT / "training/prism_portable").rglob("*")
             if p.is_file() and p.suffix in (".py", ".json") and "__pycache__" not in p.parts]
    manifest = {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p) for p in files}
    with tarfile.open(ART / "portable-code.tar.gz", "w:gz") as stream:
        for p in files:
            stream.add(p, arcname=str(p.relative_to(ROOT)).replace("\\", "/"), recursive=False)
    write(ART / "deployment-manifest.json", {"format": "m57-portable-deployment-v1", "files": manifest,
                                            "archive_sha256": digest(ART / "portable-code.tar.gz")})
    print(json.dumps({"status": "FROZEN", "files": len(files), "config_sha256": digest(config),
                      "code_identity": cfg["code_identity"], "completed_game_budget": 92}))


if __name__ == "__main__":
    main()
