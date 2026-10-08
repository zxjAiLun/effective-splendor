"""Freeze one bounded B-c20 continuation; no dispatch or overwrite."""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write, digest, identity, numerical_identity
from scripts.prism_m66_prepare import ORDER

CONFIG = "benchmarks/m70-prism-b-continuation.config.json"
PARENT_SHA = "e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4"
ARMS = {"a": {"games": 1024, "cycles": 4, "run_seed": 70010001, "seed_start": 10001000,
              "blueprint": "benchmarks/m70-prism-b-continuation.train.json"}}
RANGES = [(10000000, 10000003, "m70-engineering"),
          (10001000, 10001511, "m70-training"),
          (10010000, 10010255, "m70-common-independent"),
          (10020000, 10020511, "m70-direct-independent")]
OPPONENTS = ["heuristic", "general", "balance", "alpha", "beta", "released-alpha"]


def blueprint(template, hashes, arm="a", engineering=False):
    bp = copy.deepcopy(template)
    bp.update(purpose="finite-m67-b-start-outcome-only-ppo", cancel_fixture=False,
              model_label="M70 engineering" if engineering else "M70 final c4 unpublished checkpoint")
    bp["weight_hashes"] = {k: hashes[k] for k in ("parent", "general", "alpha", "beta")}
    t = bp["template"]
    descriptor = t["opponents"]["prism-general-v011"]
    t["opponents"] = {}
    for i, key in enumerate(("general", "parent", "alpha", "beta")):
        row = copy.deepcopy(descriptor)
        row["args"] = ["agent-prism", "--weights", "@" + key, "--seed", str(70011000 + i)]
        row["files"] = {"@" + key: "@" + key + "_sha256"}
        t["opponents"][key] = row
    r = t["run"]
    r.update(run_id="m70-engineering" if engineering else "m70-b-continuation",
             seed=70000001 if engineering else ARMS[arm]["run_seed"],
             format="prism-ppo-run-v2", cpu_threads=2)
    r.pop("style", None)
    r["ppo"].update(style_beta=0., style_value_weight=0.)
    r["opponents"] = {k: "" for k in t["opponents"]}
    count, cycles, blocks, start = (8, 1, 4, 10000000) if engineering else (1024, 4, 128, 10001000)
    r["budget"].update(max_cycles=cycles, max_jobs=count, max_attempts=count,
                      max_decisions=count * 256, max_job_decisions=256,
                      max_optimizer_steps=2048, max_update_attempts=2048,
                      max_run_seconds=1200 if engineering else 10800,
                      max_storage_bytes=(2 if engineering else 8) * 1024**3)
    t["limits"].update(memory_bytes=8 * 1024**3,
                       campaign_cpu_seconds=2400 if engineering else 40000,
                       max_physical_decisions=count * 256, max_infra_retries=0)
    order = ("general", "parent", "alpha", "beta") if engineering else ORDER
    t["cycles"] = [[dict(job_id=f'{r["run_id"]}-c{c+1}-b{b}-s{s}', actor=s,
                        opponent_id=order[b % len(order)], environment_seed=start+c*blocks+b)
                    for b in range(blocks) for s in (0, 1)] for c in range(cycles)]
    return bp


def validate(c, bps):
    if c["format"] != "m70-prism-b-continuation-v1" or c["base_model"]["sha256"] != PARENT_SHA:
        raise ValueError("M70 contract/parent drift")
    if set(bps) != {"a"} or c["training"]["arms"] != {
            "a": dict(ARMS["a"], blueprint_identity=identity(bps["a"]))}:
        raise ValueError("training/blueprint drift")
    bp = bps["a"]
    expected = blueprint(read(ROOT / "benchmarks/m63-prism-control-building.train.json"),
                         {k: v["sha256"] for k, v in c["assets"].items()})
    if bp != expected:
        raise ValueError("training schedule/numerical drift")
    if bp["template"]["run"]["ppo"] != read(ROOT / "benchmarks/m67-prism-alpha-repeat.config.json")["training"]["ppo"]:
        raise ValueError("PPO numerical drift")
    e = c["evaluation"]
    if (e["total_games"], e["common_games_per_model"], e["direct_games"],
            e["mode"], e["lower_quantile"]) != (7168, 3072, 1024, "both-greedy", .025):
        raise ValueError("evaluation scope drift")
    if e["common_opponents"] != OPPONENTS or (e["common_seed_start"], e["common_seed_end"],
            e["direct_seed_start"], e["direct_seed_end"]) != (10010000, 10010255, 10020000, 10020511):
        raise ValueError("evaluation cohort drift")
    if e["gates"] != {"candidate/strength_pool": -.05, "candidate/direct_parent": .45}:
        raise ValueError("gate drift")
    if e["enhancement_thresholds"] != {"candidate/strength_pool": 0., "candidate/direct_parent": .5}:
        raise ValueError("enhancement drift")
    if [list(r) for r in c["seed_reservations"]] != [list(r) for r in RANGES]:
        raise ValueError("seed reservation drift")
    return c


def freeze():
    if any((ROOT / p).exists() for p in (CONFIG, ARMS["a"]["blueprint"])):
        raise ValueError("M70 already frozen")
    c = copy.deepcopy(read(ROOT / "benchmarks/m66-prism-alpha-dsw.config.json"))
    c["assets"]["released-alpha"] = copy.deepcopy(c["assets"]["parent"])
    c["assets"]["parent"] = dict(local_path="local-artifacts/prism/m67-alpha-repeat/"
        "r2-failure-harvest-20261007/campaigns/b/cycle-20-export/weights.json", sha256=PARENT_SHA)
    for a in c["assets"].values():
        if digest(ROOT / a["local_path"]) != a["sha256"]:
            raise ValueError("asset drift")
    from scripts.s0_seed_registry import REGISTRY
    prior, sources = list(REGISTRY), {}
    for path in (ROOT / "benchmarks").glob("m*.config.json"):
        saved = read(path)
        prior.extend(tuple(r) for r in saved.get("seed_reservations", []))
        sources[path.relative_to(ROOT).as_posix()] = digest(path)
    for lo, hi, label in RANGES:
        if any(max(lo, a) <= min(hi, b) for a, b, _ in prior):
            raise ValueError("seed overlap: " + label)
    bp = blueprint(read(ROOT / "benchmarks/m63-prism-control-building.train.json"),
                   {k: v["sha256"] for k, v in c["assets"].items()})
    c.update(format="m70-prism-b-continuation-v1", frozen_at=datetime.now(timezone.utc).isoformat(),
             authorization=dict(source="human_owner", date="2026-10-08",
                                request="修复让另一个agent在做 先继续在dsw上跑下一轮迭代"),
             base_model=dict(name="M67 seed B final c20 unpublished checkpoint", sha256=PARENT_SHA),
             seed_reservations=RANGES, seed_check=dict(status="PASS", prior_ranges=len(prior), configs=sources))
    c["names"].update(parent=c["base_model"]["name"], candidate="M70 final c4 unpublished checkpoint",
                       **{"candidate-a": "M70 final c4 unpublished checkpoint",
                          "released-alpha": "Prism Alpha v0.1.5"})
    c["training"].update(arms={"a": dict(ARMS["a"], blueprint_identity=identity(bp))},
                         blueprint=ARMS["a"]["blueprint"], blueprint_identity=identity(bp),
                         total_games=1024, run_seed=70010001, storage_bytes=8*1024**3)
    c["engineering"].update(run_seed=70000001)
    c["evaluation"].update(common_opponents=OPPONENTS, action_seed=70020001,
                          common_seed_start=10010000, common_seed_end=10010255,
                          direct_seed_start=10020000, direct_seed_end=10020511,
                          bootstrap_seed=70029999, storage_bytes_per_arena=2*1024**3)
    c["resources"].update(total_storage_bytes=16*1024**3, minimum_free_bytes=20*1024**3)
    c["runtime"].update(remote_root="/mnt/workspace/splendor-m70-b-continuation",
                        training_python="/mnt/workspace/envs/splendor-ppo-m67-py312/bin/python",
                        arena_python="/mnt/workspace/envs/splendor-arena-py312/bin/python",
                        arena_environment=dict(numpy="2.2.4", psutil="7.0.0", Markdown="3.8"))
    c["runtime"]["training_environment"]["Markdown"] = "3.7"
    c["runtime"]["numeric_source_identity"] = numerical_identity()
    c["comparison_limit"] = "Single training seed, finite continuation; not a population robustness claim or M67 repeat."
    c["coverage"] = "Parent B direct; General/Balance/Alpha1.4/Beta/Alpha1.5 + non-Prism heuristic common. Initial omitted to keep six opponents; still used for parity."
    c["failure_policy"] = "All errors stop and retain evidence; zero research retries. No live M69 repair integration."
    c["sample_size_rationale"] = "Reuse bounded M66 grid under 23GiB free disk; estimate per-checkpoint changes, not small-effect equivalence. No extension if inconclusive."
    validate(c, {"a": bp})
    write(ROOT / ARMS["a"]["blueprint"], bp)
    write(ROOT / CONFIG, c)
    return dict(status="FROZEN_BEFORE_FIRST_GAME", config_sha256=digest(ROOT / CONFIG), new_games=0)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(freeze()))
