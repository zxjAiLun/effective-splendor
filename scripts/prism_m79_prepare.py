"""Build and validate the frozen M79 training blueprint without games."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.prism_portable.common import (  # noqa: E402
    digest,
    identity,
    numerical_identity,
    package_identity,
    read,
    write,
)

PLAN = "benchmarks/m79-prism-mainline.execution-plan.json"
TEMPLATE = "benchmarks/m75-prism-continuation-a.train.json"
OUTPUT = "benchmarks/m79-prism-mainline.a-train.json"
PLAN_SHA256 = "e16351f17ed8bbcaeb21dcdd3d0b23f39c27aefa0a112101a7b555caa79a8176"
PLAN_IDENTITY = "5fa5f6b2c0541e59621f955ea9260c47af0ce803f628d9e9de84c09f203e0252"
TEMPLATE_SHA256 = "85ca6c268b5eb35295f499ba366146a37e4649c1d61ce267038382dab522e11b"
PARENT_SHA256 = "eaa1331b29599f239299b5a9037100ae042c6021b2195df3f675c2eb5bd62bf5"
OPPONENTS = ("general", "parent", "latest-alpha", "latest-balance")
LOGICAL_JOBS = 5120
INFRA_RETRIES = 64
JOB_DECISIONS = 256


def _assert_frozen_plan(plan):
    if digest(ROOT / PLAN) != PLAN_SHA256:
        raise ValueError("M79 raw execution plan drift")
    if identity(plan) != PLAN_IDENTITY:
        raise ValueError("M79 plan object drift")
    if plan.get("format") != "prism-m79-execution-handoff-v1" or plan.get("round") != "M79":
        raise ValueError("M79 contract identity drift")


def _load_template(plan):
    reference = plan["planning_evidence"]["numeric_blueprint_reference"]
    if reference.get("path") != TEMPLATE or reference.get("sha256") != TEMPLATE_SHA256:
        raise ValueError("frozen M75 numeric blueprint reference drift")
    if digest(ROOT / TEMPLATE) != TEMPLATE_SHA256:
        raise ValueError("frozen M75 blueprint bytes changed")
    return read(ROOT / TEMPLATE)


def _expected_schedule(plan):
    training = plan["training"]
    seed_start, seed_end = training["seed_range"]
    cycles = training["cycles"]
    blocks_per_cycle = training["seed_blocks_per_cycle"]
    if (seed_start, seed_end, cycles, blocks_per_cycle, training["seats"],
            training["logical_attempts"], training["run_seed"], training["opponent_order"]) != (
            17001000, 17003559, 20, 128, [0, 1], LOGICAL_JOBS, 79010001, list(OPPONENTS)):
        raise ValueError("M79 training schedule identity drift")
    if seed_end - seed_start + 1 != cycles * blocks_per_cycle:
        raise ValueError("M79 seed range does not cover every cycle block")

    return [
        [
            {
                "job_id": f"m79-a-c{cycle + 1}-b{block}-s{seat}",
                "actor": seat,
                "opponent_id": OPPONENTS[block % len(OPPONENTS)],
                "environment_seed": seed_start + blocks_per_cycle * cycle + block,
            }
            for block in range(blocks_per_cycle)
            for seat in (0, 1)
        ]
        for cycle in range(cycles)
    ]


def _build_blueprint(plan):
    template = _load_template(plan)
    training = plan["training"]
    retries = plan["recovery"]
    if retries.get("infra_retry_per_unfinished_logical_job") != 1:
        raise ValueError("M79 per-job infrastructure retry rule drift")
    if retries.get("infra_retry_total_extra_physical_attempts") != INFRA_RETRIES:
        raise ValueError("M79 global infrastructure retry budget drift")
    if retries.get("physical_attempt_ceiling_including_infra") != plan["logical_attempt_total"] + INFRA_RETRIES:
        raise ValueError("M79 whole-round physical attempt ceiling drift")
    if training.get("ppo") != template["template"]["run"]["ppo"]:
        raise ValueError("M79 PPO differs from the frozen M75 template")

    blueprint = copy.deepcopy(template)
    blueprint["model_label"] = "M79 fixed final c20 candidate"
    blueprint["purpose"] = "practical-longer-training-stronger-pool"
    blueprint["template"]["cycles"] = _expected_schedule(plan)
    run = blueprint["template"]["run"]
    budget = run["budget"]
    run["run_id"] = "m79-a"
    run["seed"] = training["run_seed"]
    budget.update(
        max_cycles=training["cycles"],
        max_jobs=LOGICAL_JOBS,
        max_attempts=LOGICAL_JOBS + INFRA_RETRIES,
        max_job_decisions=JOB_DECISIONS,
        max_decisions=LOGICAL_JOBS * JOB_DECISIONS,
        max_run_seconds=training["wall_seconds"],
        max_storage_bytes=training["storage_bytes"],
    )
    limits = blueprint["template"]["limits"]
    limits.update(
        max_infra_retries=INFRA_RETRIES,
        max_physical_decisions=(LOGICAL_JOBS + INFRA_RETRIES) * JOB_DECISIONS,
        max_plies=training["ply_cap"],
        campaign_cpu_seconds=training["cpu_seconds"],
        memory_bytes=training["rss_bytes"],
    )
    blueprint["weight_hashes"] = {
        name: plan["assets"][name]["sha256"] for name in OPPONENTS
    }
    return blueprint


def make_blueprint(plan):
    """Return the independent M79 blueprint derived from frozen M75 numerics."""
    _assert_frozen_plan(plan)
    return _build_blueprint(plan)


def validate(plan, bp):
    """Validate plan, assets, schedule, budgets and runtime identities; run no games."""
    _assert_frozen_plan(plan)
    expected = _build_blueprint(plan)
    if bp != expected:
        raise ValueError("M79 blueprint differs from its frozen plan/template")

    training = plan["training"]
    expected_assets = plan["assets"]
    actual_assets = {}
    for name, asset in expected_assets.items():
        path = (ROOT / asset["local_path"]).resolve()
        if ROOT.resolve() not in path.parents:
            raise ValueError("M79 asset path escapes workspace: " + name)
        actual = digest(path)
        if actual != asset["sha256"]:
            raise ValueError("fixed M79 asset SHA drift: " + name)
        actual_assets[name] = actual
    if actual_assets["parent"] != PARENT_SHA256:
        raise ValueError("M79 parent is not the frozen M75 c20 export")

    jobs = [job for cycle in bp["template"]["cycles"] for job in cycle]
    seeds = {job["environment_seed"] for job in jobs}
    if len(jobs) != LOGICAL_JOBS or len({job["job_id"] for job in jobs}) != LOGICAL_JOBS:
        raise ValueError("M79 logical job count or identity drift")
    if seeds != set(range(17001000, 17003560)):
        raise ValueError("M79 environment seed schedule drift")
    if any(len(cycle) != 256 for cycle in bp["template"]["cycles"]):
        raise ValueError("M79 cycle job count drift")
    for seed in seeds:
        rows = [job for job in jobs if job["environment_seed"] == seed]
        if len(rows) != 2 or {job["actor"] for job in rows} != {0, 1}:
            raise ValueError("M79 double-seat schedule drift")
        if len({job["opponent_id"] for job in rows}) != 1:
            raise ValueError("M79 paired opponent schedule drift")

    counts = {name: sum(job["opponent_id"] == name for job in jobs) for name in OPPONENTS}
    if counts != {name: 1280 for name in OPPONENTS}:
        raise ValueError("M79 opponent allocation drift")
    run = bp["template"]["run"]
    budget = run["budget"]
    limits = bp["template"]["limits"]
    if run["seed"] != 79010001 or run["run_id"] != "m79-a":
        raise ValueError("M79 run identity drift")
    if run["ppo"] != training["ppo"] or run["ppo"] != _load_template(plan)["template"]["run"]["ppo"]:
        raise ValueError("M79 PPO drift")
    if (budget["max_jobs"], budget["max_cycles"], budget["max_attempts"],
            budget["max_job_decisions"], budget["max_decisions"]) != (
            LOGICAL_JOBS, 20, 5184, JOB_DECISIONS, LOGICAL_JOBS * JOB_DECISIONS):
        raise ValueError("M79 logical/physical training budget drift")
    if (limits["max_infra_retries"], limits["max_physical_decisions"],
            plan["recovery"]["infra_retry_per_unfinished_logical_job"]) != (
            INFRA_RETRIES, 5184 * JOB_DECISIONS, 1):
        raise ValueError("M79 infrastructure retry budget drift")
    if budget["max_run_seconds"] != training["wall_seconds"]:
        raise ValueError("M79 wall-clock budget drift")
    if budget["max_storage_bytes"] != training["storage_bytes"]:
        raise ValueError("M79 storage budget drift")
    if limits["campaign_cpu_seconds"] != training["cpu_seconds"]:
        raise ValueError("M79 campaign CPU budget drift")

    numeric_source = numerical_identity()
    portable_package = package_identity()
    runtime_reference = plan["planning_evidence"]["runtime_reference"]
    if numeric_source != runtime_reference["numeric_source_identity"]:
        raise ValueError("M79 numerical source identity drift")
    if portable_package != runtime_reference["portable_package_identity"]:
        raise ValueError("M79 portable package identity drift")

    if digest(ROOT / PLAN) != PLAN_SHA256:
        raise ValueError("M79 raw execution plan changed during validation")
    return {
        "status": "VERIFIED_ZERO_GAMES",
        "new_games": 0,
        "plan_sha256": PLAN_SHA256,
        "m75_template_sha256": TEMPLATE_SHA256,
        "blueprint_identity": identity(bp),
        "logical_jobs": len(jobs),
        "environment_seed_count": len(seeds),
        "opponent_job_counts": counts,
        "max_jobs": budget["max_jobs"],
        "max_attempts": budget["max_attempts"],
        "max_infra_retries": limits["max_infra_retries"],
        "max_physical_decisions": limits["max_physical_decisions"],
        "infra_retry_per_unfinished_logical_job": 1,
        "numeric_source_identity": numeric_source,
        "portable_package_identity": portable_package,
        "asset_sha256": actual_assets,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    plan_bytes_sha = digest(ROOT / PLAN)
    if plan_bytes_sha != PLAN_SHA256:
        raise ValueError("M79 raw execution plan drift")
    plan = read(ROOT / PLAN)
    blueprint = make_blueprint(plan)
    validate(plan, blueprint)
    if digest(ROOT / PLAN) != plan_bytes_sha:
        raise ValueError("M79 raw execution plan changed before blueprint write")
    write(ROOT / OUTPUT, blueprint)
    saved = read(ROOT / OUTPUT)
    evidence = validate(plan, saved)
    if digest(ROOT / PLAN) != plan_bytes_sha:
        raise ValueError("M79 raw execution plan changed during blueprint write")
    print(json.dumps(evidence, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
