"""Opt-in failure isolation for NEW fixed-evaluation batches, never old runs.

This worker must run under the caller's CPU/RSS/process-tree supervisor. It adds
an explicit finite failure budget, absolute deadline, durable dispatch records,
and complete-grid status. It does not train, retry, adjudicate or promote.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_notebook_arena as arena
from scripts import prism_ppo_fixed_eval as fixed

FORMAT = "prism-eval-failure-policy-v1"
SOURCES = ("scripts/prism_eval_failure_guard.py", "scripts/prism_notebook_arena.py",
           "scripts/prism_ppo_fixed_eval.py")
SAFETY_MESSAGE = "match exceeded ply safety limit"


def jobs(config):
    return [(m, o, s, seat) for m in config["candidates"]
            for o in config["opponents"] for s in config["seeds"] for seat in (0, 1)]


def validate_policy(policy, config):
    required = {"format", "max_games", "max_safety_failures", "deadline_unix",
                "automatic_game_retries", "supervisor_identity"}
    fixed._require(set(policy) == required and policy["format"] == FORMAT, "invalid failure policy")
    for name in ("max_games", "max_safety_failures"):
        fixed._require(type(policy[name]) is int and policy[name] >= 0, "invalid " + name)
    fixed._require(policy["max_games"] == len(jobs(config)), "policy/grid budget mismatch")
    fixed._require(policy["max_safety_failures"] <= policy["max_games"], "failure budget exceeds grid")
    fixed._require(type(policy["automatic_game_retries"]) is int
                   and policy["automatic_game_retries"] == 0, "retries are forbidden")
    deadline = policy["deadline_unix"]
    fixed._require(type(deadline) in (int, float) and math.isfinite(deadline)
                   and deadline > 0, "invalid absolute deadline")
    fixed._require(isinstance(policy["supervisor_identity"], str)
                   and policy["supervisor_identity"].strip(), "supervisor identity required")


def prepare(config_path, policy_path, output):
    """Freeze a new batch without dispatching any game."""
    config_path, output = Path(config_path).resolve(), Path(output).resolve()
    config, policy = fixed.read_json(config_path), fixed.read_json(policy_path)
    validated = arena.validate_arena_config(config, config_path)
    fixed.check_assets(validated)
    validate_policy(policy, config)
    fixed._require(policy["deadline_unix"] > time.time(), "deadline exhausted")
    # Exclusive creation prevents an old evaluation directory from being adopted.
    output.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for relative in SOURCES:
        source = ROOT / relative
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        hashes[relative] = fixed.sha256_file(target)
    fixed.atomic_json(output / "config.json", config)
    fixed.atomic_json(output / "policy.json", policy)
    manifest = {"format": "prism-guarded-eval-v1", "config_origin": str(config_path),
                "config_sha256": fixed.canonical_hash(config),
                "policy_sha256": fixed.canonical_hash(policy), "source_sha256": hashes}
    fixed.atomic_json(output / "manifest.json", manifest)
    return manifest


def load_bound(output):
    manifest = fixed.read_json(output / "manifest.json")
    config, policy = fixed.read_json(output / "config.json"), fixed.read_json(output / "policy.json")
    fixed._require(manifest["format"] == "prism-guarded-eval-v1", "manifest format drift")
    fixed._require(fixed.canonical_hash(config) == manifest["config_sha256"], "config drift")
    fixed._require(fixed.canonical_hash(policy) == manifest["policy_sha256"], "policy drift")
    fixed._require(set(manifest["source_sha256"]) == set(SOURCES), "source list drift")
    for relative, expected in manifest["source_sha256"].items():
        fixed._require(fixed.sha256_file(ROOT / relative) == expected
                       and fixed.sha256_file(output / "source" / relative) == expected,
                       "source drift: " + relative)
    validate_policy(policy, config)
    validated = arena.validate_arena_config(config, Path(manifest["config_origin"]))
    fixed.check_assets(validated)
    validated.update(saved_config=config, config_sha256=manifest["config_sha256"])
    return validated, policy


def game_directory(output, job):
    m, o, seed, seat = job
    return output / "games" / m / o / f"seed-{seed}-seat-{seat}"


def classify_failure(directory, entry, key, job):
    """Only the pinned engine's exact safety-limit failure is continuable."""
    if not entry or entry.get("status") != "error":
        return "UNKNOWN_FAILURE"
    try:
        process = fixed.read_json(directory / "process-result.json")
        game = fixed.read_json(directory / "game.json")
        config = fixed.read_json(directory / "match-config.json")
        stderr = (directory / "stderr.log").read_text(encoding="utf-8").strip()
        expected_id = fixed._game_id(job[1], job[2], job[3])
        expected_error = f"ValueError: run-match failed for {key}: exit 1"
        valid = (process["returncode"] == 1 and game == entry
                 and entry.get("game_id") == expected_id
                 and config["game_id"] == expected_id and config["seed"] == job[2]
                 and entry.get("error") == expected_error
                 and stderr == "error: engine internal error: " + SAFETY_MESSAGE
                 and not (directory / "report.json").exists()
                 and not (directory / "replay.json").exists())
        return "PLY_SAFETY_LIMIT" if valid else "UNKNOWN_FAILURE"
    except (OSError, ValueError, KeyError, TypeError):
        return "UNKNOWN_FAILURE"


def grid_status(config, entries, execution_state):
    expected = {fixed._game_key(*job): job for job in jobs(config)}
    fixed._require(set(entries) <= set(expected), "unexpected game key")
    completed, failed, interrupted = [], [], []
    for key, entry in entries.items():
        state = entry["state"]
        if state == "COMPLETED":
            row = entry["row"]
            m, o, seed, seat = expected[key]
            fixed._require((row["candidate"], row["opponent"], row["seed"],
                            row["candidate_seat"]) == (m, o, seed, seat), "row identity drift")
            fixed._require(type(row["candidate_seat"]) is int
                           and type(row["seed"]) is int
                           and type(row["candidate_score"]) in (int, float)
                           and row["candidate_score"] in (0, .5, 1), "invalid score/seat/seed")
            fixed._require(row["record"] == {0: "loss", .5: "draw", 1: "win"}[row["candidate_score"]],
                           "score/record mismatch")
            completed.append(key)
        elif state == "RETAINED_FAILURE":
            failed.append(key)
        elif state == "DISPATCHED":
            interrupted.append(key)
        else:
            raise ValueError("unknown ledger state")
    completed = set(completed)
    missing = sorted(set(expected) - completed)
    paired = {}
    for m in config["candidates"]:
        for o in config["opponents"]:
            paired[f"{m}/{o}"] = sum(all(fixed._game_key(m, o, s, seat) in completed
                                      for seat in (0, 1)) for s in config["seeds"])
    return {"execution_state": execution_state,
            "grid_state": "COMPLETE" if not missing else "INCOMPLETE",
            "formal_grid_eligible": not missing, "planned_games": len(expected),
            "completed_games": len(completed), "missing_keys": missing,
            "retained_failure_keys": sorted(failed), "interrupted_keys": sorted(interrupted),
            "pending_keys": sorted(set(expected) - set(entries)),
            "complete_seed_pairs": paired, "automatic_game_retries": 0,
            "rule_replay_audit": "NOT_RUN", "promotion": "NOT_EVALUATED"}


def run(output, *, before_game):
    """Run once under a caller-supplied supervisor/budget check (no auto-resume)."""
    output = Path(output).resolve()
    validated, policy = load_bound(output)
    fixed._require(callable(before_game), "supervisor/budget callback required")
    lock = output / "writer.lock"
    # A crash leaves this lock and the dispatched key for explicit investigation.
    with lock.open("x", encoding="ascii") as stream:
        stream.write("single writer; never clear automatically\n")
    ledger_path, evaluation = output / "ledger.json", output / "evaluation"
    try:
        fixed._require(not ledger_path.exists() and not evaluation.exists(),
                       "batch already dispatched; inspect only, no automatic resume")
        ledger = {"execution_state": "RUNNING", "entries": {},
                  "manifest_sha256": fixed.sha256_file(output / "manifest.json")}
        fixed.atomic_json(ledger_path, ledger)
        progress = fixed._load_progress(evaluation, validated)
        safety_failures = 0
        try:
            for job in jobs(validated["config"]):
                key = fixed._game_key(*job)
                before_game()
                fixed._require(time.time() + validated["config"]["timeouts"]["game_wall_seconds"]
                               <= policy["deadline_unix"], "insufficient deadline for next game")
                fixed.check_assets(validated)
                directory = game_directory(evaluation, job)
                fixed._require(not directory.exists(), "orphan game directory; no respawn")
                ledger["entries"][key] = {"state": "DISPATCHED"}
                fixed.atomic_json(ledger_path, ledger)
                try:
                    row = fixed._evaluate_one(validated, evaluation, *job, progress)
                except Exception:
                    kind = classify_failure(directory, progress["games"].get(key), key, job)
                    evidence = {p.name: fixed.sha256_file(p) for p in directory.iterdir()
                                if p.is_file()} if directory.exists() else {}
                    ledger["entries"][key] = {"state": "RETAINED_FAILURE",
                                               "kind": kind, "evidence_sha256": evidence}
                    fixed.atomic_json(ledger_path, ledger)
                    if kind != "PLY_SAFETY_LIMIT":
                        raise
                    safety_failures += 1
                    if safety_failures > policy["max_safety_failures"]:
                        raise ValueError("safety failure budget exhausted")
                else:
                    entry = {"state": "COMPLETED", "row": row,
                             "evidence_sha256": {p.name: fixed.sha256_file(p)
                                                 for p in directory.iterdir() if p.is_file()}}
                    checked = dict(ledger["entries"], **{key: entry})
                    grid_status(validated["config"], checked, "RUNNING")
                    ledger["entries"][key] = entry
                    fixed.atomic_json(ledger_path, ledger)
            ledger["execution_state"] = "FINISHED"
        except BaseException as error:
            ledger["execution_state"] = "STOPPED"
            ledger["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            fixed.atomic_json(ledger_path, ledger)
            fixed.atomic_json(output / "grid-status.json",
                              grid_status(validated["config"], ledger["entries"],
                                          ledger["execution_state"]))
        return fixed.read_json(output / "grid-status.json")
    finally:
        lock.unlink()


def inspect(output):
    """Read stored evidence; never dispatch or repair an interrupted batch."""
    output = Path(output).resolve()
    validated, _ = load_bound(output)
    ledger = fixed.read_json(output / "ledger.json")
    fixed._require(ledger["manifest_sha256"] == fixed.sha256_file(output / "manifest.json"),
                   "ledger identity drift")
    expected_jobs = {fixed._game_key(*job): job for job in jobs(validated["config"])}
    for key, entry in ledger["entries"].items():
        job = expected_jobs.get(key)
        fixed._require(job is not None, "unexpected game key")
        directory = game_directory(output / "evaluation", job)
        if entry["state"] == "COMPLETED":
            fixed._require({"game.json", "report.json", "replay.json", "process-result.json",
                            "match-config.json"} <= set(entry.get("evidence_sha256", {})),
                           "completed evidence missing")
        for filename, expected in entry.get("evidence_sha256", {}).items():
            fixed._require(Path(filename).name == filename, "invalid artifact filename")
            fixed._require(fixed.sha256_file(directory / filename)
                           == expected, "saved game artifact drift")
        if entry["state"] == "COMPLETED":
            game = fixed.read_json(directory / "game.json")
            fixed._require(game.get("status") == "completed" and game.get("row") == entry["row"],
                           "ledger/game row drift")
    return grid_status(validated["config"], ledger["entries"], ledger["execution_state"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "inspect"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--policy", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.config is None or args.policy is None:
            parser.error("prepare requires --config and --policy")
        result = prepare(args.config, args.policy, args.output)
    else:
        result = inspect(args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
