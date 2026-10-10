"""New-run-only bounded evaluation: save truncations, never adjudicate them.

prepare launches nothing. run is once-only, owns a resource-limited process
tree per game and continues ONLY validated ply truncations within a frozen
budget. No policy/action modifications, retries, training or promotion.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_eval_failure_guard as legacy
from scripts import prism_notebook_arena as arena
from scripts import prism_ppo_fixed_eval as fixed
from training.prism_portable.processes import directory_bytes

FORMAT = "prism-bounded-evaluation-v1"
SOURCES = (
    "scripts/prism_bounded_eval.py", "scripts/prism_eval_failure_guard.py",
    "scripts/prism_notebook_arena.py", "scripts/prism_ppo_fixed_eval.py",
    "scripts/prism_dsw_ppo_process.py", "training/prism_portable/processes.py",
    "training/prism_portable/common.py", "training/prism_portable/engine/ppo/processes.py",
)
require = fixed._require
read, write, sha = fixed.read_json, fixed.atomic_json, fixed.sha256_file


def runtime():
    return {"python": sys.version, "platform": sys.platform,
            "psutil": importlib.metadata.version("psutil")}


def validate_policy(policy, config):
    required = {"format", "max_games", "max_truncated_games", "ply_cap",
                "deadline_unix", "cpu_seconds", "memory_bytes", "storage_bytes",
                "max_processes", "automatic_game_retries"}
    require(set(policy) == required and policy["format"] == FORMAT, "invalid bounded policy")
    for key in required - {"format", "deadline_unix", "cpu_seconds"}:
        require(type(policy[key]) is int, "integer required: " + key)
    require(policy["max_games"] == len(legacy.jobs(config)) > 0, "grid budget mismatch")
    require(0 <= policy["max_truncated_games"] <= policy["max_games"], "invalid truncation budget")
    require(1 <= policy["ply_cap"] < 10000, "ply cap must be 1..9999")
    require(policy["automatic_game_retries"] == 0, "automatic retries forbidden")
    for key in ("deadline_unix", "cpu_seconds"):
        value = policy[key]
        require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                "positive finite budget required: " + key)
    require(policy["memory_bytes"] >= 64 * 1024**2 and policy["storage_bytes"] > 0,
            "invalid memory/storage budget")
    require(4 <= policy["max_processes"] <= 64, "invalid process budget")


def prepare(config_path, policy_path, output):
    config_path, output = Path(config_path).resolve(), Path(output).resolve()
    config, policy = read(config_path), read(policy_path)
    validated = arena.validate_arena_config(config, config_path)
    fixed.check_assets(validated)
    validate_policy(policy, config)
    require(policy["deadline_unix"] > time.time(), "deadline exhausted")
    output.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for rel in SOURCES:
        target = output / "source" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / rel).read_bytes())
        hashes[rel] = sha(target)
    write(output / "config.json", config)
    write(output / "policy.json", policy)
    manifest = {"format": FORMAT, "config_origin": str(config_path),
                "config_sha256": fixed.canonical_hash(config),
                "policy_sha256": fixed.canonical_hash(policy),
                "source_sha256": hashes, "runtime": runtime()}
    write(output / "manifest.json", manifest)
    require(directory_bytes(output) < policy["storage_bytes"], "prepare exceeds storage budget")
    return manifest


def load_bound(output):
    output = Path(output).resolve()
    manifest, config, policy = (read(output / name) for name in
                                ("manifest.json", "config.json", "policy.json"))
    require(manifest["format"] == FORMAT and manifest["runtime"] == runtime(), "runtime/format drift")
    require(manifest["config_sha256"] == fixed.canonical_hash(config), "config drift")
    require(manifest["policy_sha256"] == fixed.canonical_hash(policy), "policy drift")
    require(set(manifest["source_sha256"]) == set(SOURCES), "source list drift")
    for rel, digest in manifest["source_sha256"].items():
        require(sha(ROOT / rel) == sha(output / "source" / rel) == digest, "source drift: " + rel)
    validate_policy(policy, config)
    validated = arena.validate_arena_config(config, Path(manifest["config_origin"]))
    fixed.check_assets(validated)
    # The generic validator temporarily maps greedy to sample for schema checking.
    # Keep saved mode and actual commands identical in all downstream records.
    validated["config"] = config
    return validated, policy


def trace_metrics(trace):
    """Structural integrity and observed actions, not a substitute for Rust replay."""
    steps = trace["steps"]
    previous = trace["initial_state_hash"]
    require(re.fullmatch(r"[0-9a-f]{64}", previous) is not None, "invalid initial hash")
    fields = ("actions", "main", "purchases", "reserves", "noble_choices",
              "token_noops", "longest_own_token_noop_run")
    counts = [Counter(dict.fromkeys(fields, 0)), Counter(dict.fromkeys(fields, 0))]
    current_noop = [0, 0]
    current_no_buy = max_no_buy = main = 0
    for ply, step in enumerate(steps):
        actor, action = step["actor"], step["action"]
        require(type(actor) is int and actor in (0, 1), "invalid actor")
        require(type(step["ply"]) is int and step["ply"] == ply, "noncontiguous ply")
        require(step["state_hash_before"] == previous, "broken state hash chain")
        previous = step["state_hash_after"]
        require(isinstance(previous, str) and re.fullmatch(r"[0-9a-f]{64}", previous),
                "invalid state hash")
        kind = action["type"]
        require(kind in {"take_tokens", "buy_market", "buy_reserved", "reserve_market",
                         "reserve_deck", "choose_noble", "pass"}, "unknown action type")
        c = counts[actor]
        c["actions"] += 1
        if kind == "choose_noble":
            c["noble_choices"] += 1
            continue
        c["main"] += 1
        main += 1
        purchase = kind in ("buy_market", "buy_reserved")
        c["purchases"] += int(purchase)
        c["reserves"] += int(kind in ("reserve_market", "reserve_deck"))
        noop = kind == "take_tokens" and action["take"] == action["return"]
        c["token_noops"] += int(noop)
        if noop:
            current_noop[actor] += 1
        else:
            current_noop[actor] = 0
        c["longest_own_token_noop_run"] = max(c["longest_own_token_noop_run"], current_noop[actor])
        current_no_buy = 0 if purchase else current_no_buy + 1
        max_no_buy = max(max_no_buy, current_no_buy)
    expected = trace.get("cap_state_hash", trace.get("final_state_hash"))
    require(previous == expected, "trace final hash mismatch")
    return {"completed_plies": len(steps), "total_main": main,
            "by_actor": [dict(c) for c in counts],
            "longest_main_without_purchase": max_no_buy,
            "trailing_main_without_purchase": current_no_buy,
            "legal_purchase_opportunities": "NOT_MEASURED",
            "interpretation": "descriptive; waiting can be legal/useful; no payoff or infinite-loop proof"}


def validate_artifacts(directory, config, job, cap):
    m, o, seed, seat = job
    game_id = fixed._game_id(o, seed, seat)
    report = read(directory / "report.json")
    require(report.get("format") == "effective-splendor-arena-report"
            and type(report.get("version")) is int and report["version"] == 1, "invalid report")
    require(report.get("game_id") == game_id and report.get("player_count") == 2
            and report.get("ruleset_fingerprint") == config["catalog_fingerprint"],
            "report identity mismatch")
    outcome = report["outcome"]
    if outcome["status"] == "completed":
        require(not (directory / "prefix.json").exists(), "terminal game has prefix")
        replay = read(directory / "replay.json")
        require(type(replay.get("version")) is int and type(replay.get("seed")) is int,
                "invalid replay version/seed type")
        row = fixed._report_result(report, replay, game_id=game_id, seed=seed, seat=seat,
                                   catalog=config["catalog_fingerprint"])
        require(row["plies"] <= cap, "terminal beyond cap")
        row.update(candidate=m, opponent=o)
        return {"state": "COMPLETED", "row": row, "metrics": trace_metrics(replay)}
    require(outcome["status"] == "truncated", "unknown or aborted game")
    require(set(outcome) == {"status", "completed_plies", "cap_state_hash", "cap_scores"},
            "truncation contains unexpected/fabricated result fields")
    require(not (directory / "replay.json").exists(), "truncation has terminal replay")
    prefix = read(directory / "prefix.json")
    require(prefix.get("format") == "splendor-rollout-prefix"
            and type(prefix.get("version")) is int and prefix["version"] == 1,
            "invalid prefix")
    require("result" not in prefix and prefix.get("player_count") == 2
            and type(prefix.get("seed")) is int and prefix["seed"] == seed
            and prefix.get("ruleset_fingerprint") == config["catalog_fingerprint"],
            "prefix identity/result mismatch")
    require(type(prefix.get("ply_cap")) is int and type(outcome["completed_plies"]) is int
            and prefix["ply_cap"] == outcome["completed_plies"] == len(prefix["steps"]) == cap,
            "truncated ply cap mismatch")
    require(prefix["cap_state_hash"] == outcome["cap_state_hash"], "cap hash mismatch")
    require(isinstance(outcome["cap_scores"], list) and len(outcome["cap_scores"]) == 2
            and all(type(n) is int and 0 <= n <= 255 for n in outcome["cap_scores"]),
            "invalid cap scores")
    return {"state": "RETAINED_FAILURE", "kind": "PLY_CAP_TRUNCATED",
            "metrics": trace_metrics(prefix)}


@contextmanager
def scoped_environment(values):
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def launch(argv, directory, output, validated, policy, remaining_cpu):
    if os.name == "nt":
        from training.prism_portable.engine.ppo.processes import ProcessTree
    elif sys.platform.startswith("linux"):
        from scripts.prism_dsw_ppo_process import ProcessTree
    else:
        raise ValueError("unsupported supervision platform")
    wall = min(validated["config"]["timeouts"]["game_wall_seconds"],
               policy["deadline_unix"] - time.time())
    require(wall > 0 and remaining_cpu > 0, "resource budget exhausted")
    with scoped_environment({"PRISM_PPO_CONTROL_DIR": str(directory / "supervision"),
                             "PRISM_DSW_REMAINING_WALL": str(wall)}):
        with (directory / "stdout.log").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
            with ProcessTree(cpu_seconds=remaining_cpu, memory_bytes=policy["memory_bytes"],
                             max_processes=policy["max_processes"]) as tree:
                process = tree.start(argv, cwd=str(validated["base"]), stdout=stdout, stderr=stderr)
                import psutil
                write(directory / "process-identity.json",
                      {"pid": process.pid, "create_time": psutil.Process(process.pid).create_time(),
                       "argv": argv, "cwd": str(Path(validated["base"]).resolve()),
                       "node": platform.node(), "observed_at": time.time(),
                       "manifest_sha256": sha(output / "manifest.json")
                       if (output / "manifest.json").exists() else None})
                # Startup/identity recording consumes the same absolute deadline.
                remaining_wall = min(wall, max(0., policy["deadline_unix"] - time.time()))
                resources = tree.wait(wall_seconds=remaining_wall, storage_root=output,
                                      max_storage_bytes=policy["storage_bytes"])
    resources["cpu_seconds"] = resources.get("cpu_seconds", resources["user_cpu_seconds"]
                                             + resources["kernel_cpu_seconds"])
    return resources


def match_config(validated, job):
    m, o, seed, seat = job
    agents = [{"program": d["program_resolved"], "args": d["args_resolved"]}
              for d in (validated["candidates"][m], validated["opponents"][o])]
    return {"game_id": fixed._game_id(o, seed, seat), "seed": seed,
            **{k: validated["config"]["timeouts"][k] for k in
               ("handshake_timeout_ms", "move_timeout_ms", "shutdown_grace_ms")},
            "agents": agents if seat == 0 else agents[::-1]}


def rollout_command(validated, policy, directory):
    return [validated["engine"]["resolved_program"], "run-rollout", "--config",
            str(directory / "match-config.json"), "--max-plies", str(policy["ply_cap"]),
            "--report-out", str(directory / "report.json"), "--replay-out",
            str(directory / "replay.json"), "--prefix-out", str(directory / "prefix.json")]


def validate_resources(resources, argv):
    require(resources.get("argv") == argv, "process command drift")
    require(type(resources.get("returncode")) is int and resources["returncode"] == 0
            and resources.get("stop_reason") is None,
            "process/resource failure; no continuation")
    cpu = resources.get("cpu_seconds")
    require(type(cpu) in (int, float) and math.isfinite(cpu) and cpu >= 0,
            "invalid CPU accounting")
    return cpu


def evaluate(validated, policy, output, job, remaining_cpu):
    directory = legacy.game_directory(output, job)
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "match-config.json", match_config(validated, job))
    argv = rollout_command(validated, policy, directory)
    resources = launch(argv, directory, output, validated, policy, remaining_cpu)
    resources = dict(resources, argv=argv)
    write(directory / "process-result.json", resources)
    cpu = validate_resources(resources, argv)
    entry = validate_artifacts(directory, validated["config"], job, policy["ply_cap"])
    write(directory / "game.json", entry)
    return dict(entry, cpu_seconds=cpu)


def evidence(directory):
    return {p.relative_to(directory).as_posix(): sha(p) for p in directory.rglob("*") if p.is_file()}


def summary(config, ledger):
    # A persisted RUNNING row is not proof of a live owner after a crash.
    state = ledger["execution_state"]
    result = legacy.grid_status(config, ledger["entries"],
                                "RUNNING_UNCONFIRMED" if state == "RUNNING" else state)
    result.update(truncated_games=sum(e.get("kind") == "PLY_CAP_TRUNCATED"
                                     for e in ledger["entries"].values()),
                  consumed_cpu_seconds=ledger["consumed_cpu_seconds"],
                  policy_effectiveness="NOT_EVALUATED",
                  rule_replay_audit="NOT_RUN_INDEPENDENTLY",
                  observation_state="STORED_EVIDENCE_ONLY")
    result["completion_rate"] = result["completed_games"] / result["planned_games"]
    return result


def run(output):
    output = Path(output).resolve()
    validated, policy = load_bound(output)
    require(not (output / "ledger.json").exists() and not (output / "games").exists(),
            "existing dispatch/artifacts; inspect only, no retry")
    # Retained forever, including after successful exit: restart is not resume.
    with (output / "once-only.lock").open("x", encoding="ascii") as f:
        f.write(str(os.getpid()))
    ledger = {"execution_state": "RUNNING", "entries": {}, "consumed_cpu_seconds": 0.,
              "manifest_sha256": sha(output / "manifest.json")}
    truncated = 0
    write(output / "ledger.json", ledger)
    try:
        for job in legacy.jobs(validated["config"]):
            load_bound(output)
            remaining = policy["cpu_seconds"] - ledger["consumed_cpu_seconds"]
            require(remaining > 0, "CPU budget exhausted")
            require(time.time() + validated["config"]["timeouts"]["game_wall_seconds"]
                    <= policy["deadline_unix"], "insufficient deadline for next game")
            require(directory_bytes(output) < policy["storage_bytes"], "storage budget exhausted")
            fixed.check_assets(validated)
            key = fixed._game_key(*job)
            directory = legacy.game_directory(output, job)
            ledger["entries"][key] = {"state": "DISPATCHED"}
            write(output / "ledger.json", ledger)
            try:
                entry = evaluate(validated, policy, output, job, remaining)
            except BaseException as error:
                ledger["entries"][key] = {"state": "RETAINED_FAILURE", "kind": "UNKNOWN_OR_RESOURCE_FAILURE",
                                          "error": f"{type(error).__name__}: {error}",
                                          "evidence_sha256": evidence(directory)}
                # Unknown accounting is never interpreted as unused budget.
                ledger["consumed_cpu_seconds"] = policy["cpu_seconds"]
                ledger["cpu_charge"] = "FULL_REMAINDER_RESERVED_AFTER_FAILURE"
                raise
            ledger["consumed_cpu_seconds"] += entry.pop("cpu_seconds")
            entry["evidence_sha256"] = evidence(directory)
            ledger["entries"][key] = entry
            write(output / "ledger.json", ledger)
            truncated += int(entry.get("kind") == "PLY_CAP_TRUNCATED")
            require(truncated <= policy["max_truncated_games"], "truncation budget exhausted")
            require(ledger["consumed_cpu_seconds"] < policy["cpu_seconds"], "CPU budget exhausted")
            require(time.time() <= policy["deadline_unix"], "absolute deadline exhausted")
            require(directory_bytes(output) < policy["storage_bytes"], "storage budget exhausted")
        ledger["execution_state"] = "FINISHED"
    except BaseException as error:
        ledger.update(execution_state="STOPPED", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        write(output / "ledger.json", ledger)
        write(output / "grid-status.json", summary(validated["config"], ledger))
    return inspect(output)


def inspect(output):
    output = Path(output).resolve()
    validated, policy = load_bound(output)
    ledger = read(output / "ledger.json")
    require(ledger["manifest_sha256"] == sha(output / "manifest.json"), "manifest drift")
    require(ledger["execution_state"] in {"RUNNING", "STOPPED", "FINISHED"}, "invalid execution state")
    consumed = ledger["consumed_cpu_seconds"]
    require(type(consumed) in (int, float) and math.isfinite(consumed) and consumed >= 0,
            "invalid ledger CPU accounting")
    expected = {fixed._game_key(*job): job for job in legacy.jobs(validated["config"])}
    measured_cpu = {}
    unknown_failure = False
    for key, entry in ledger["entries"].items():
        require(key in expected, "unexpected game key")
        directory = legacy.game_directory(output, expected[key])
        if entry["state"] == "DISPATCHED":
            continue
        require(evidence(directory) == entry["evidence_sha256"], "artifact set/hash drift")
        if entry["state"] == "COMPLETED" or entry.get("kind") == "PLY_CAP_TRUNCATED":
            require(read(directory / "match-config.json") == match_config(validated, expected[key]),
                    "match config/command drift")
            checked = validate_artifacts(directory, validated["config"], expected[key], policy["ply_cap"])
            require(read(directory / "game.json") == checked, "game artifact drift")
            require({k: v for k, v in entry.items() if k != "evidence_sha256"} == checked,
                    "ledger row drift")
            resources = read(directory / "process-result.json")
            measured_cpu[key] = validate_resources(resources, rollout_command(validated, policy, directory))
        elif entry["state"] == "RETAINED_FAILURE":
            unknown_failure = True
    if unknown_failure:
        require(consumed == policy["cpu_seconds"] and
                ledger.get("cpu_charge") == "FULL_REMAINDER_RESERVED_AFTER_FAILURE",
                "failure CPU reservation drift")
    else:
        # JSON sorts ledger keys; re-add in dispatch order to preserve floating
        # point accounting for valid non-sorted seed cohorts.
        # Python 3.12's sum(float) uses compensated summation; dispatch uses
        # repeated +=. Reproduce dispatch arithmetic exactly, even at one ULP.
        total = 0.
        for key in expected:
            if key in measured_cpu:
                total += measured_cpu[key]
        require(consumed == total, "ledger CPU total drift")
    if ledger["execution_state"] == "FINISHED":
        require(set(ledger["entries"]) == set(expected)
                and all(e["state"] != "DISPATCHED" for e in ledger["entries"].values()),
                "finished execution has undispatched/interrupted games")
    result = summary(validated["config"], ledger)
    if ledger["execution_state"] != "RUNNING":
        require(result == read(output / "grid-status.json"), "grid status drift")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("prepare", "run", "inspect"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--config", type=Path)
    p.add_argument("--policy", type=Path)
    args = p.parse_args()
    if args.command == "prepare":
        if not args.config or not args.policy:
            p.error("prepare requires --config and --policy")
        result = prepare(args.config, args.policy, args.output)
    else:
        result = run(args.output) if args.command == "run" else inspect(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
