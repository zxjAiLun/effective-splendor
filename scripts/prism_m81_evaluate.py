"""M81 frozen greedy evaluation grid and bounded shard runner.

The M81 runtime owns stage admission and resource-mode patches. This module
owns only the immutable evaluation contract, shard ledgers, and evaluation
receipt. No calendar deadline or replacement seed is used.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLAN_REL = Path("benchmarks/m81-anchor-coverage.execution-plan.json")
PYTHON = "/mnt/workspace/envs/splendor-m79-ppo-py312/bin/python"
ACTORS = ("base", "A", "B")
_RUNTIME_CACHE: dict[str, tuple[Any, dict[str, Any], dict[str, Any], Any]] = {}


class _EvaluationBudgetExhausted(ValueError):
    pass


def _common(root: Path):
    from training.prism_portable.common import digest, lock, read, write
    return read, write, digest, lock


def _root(root: str | Path | None = None) -> Path:
    global ROOT
    if root is not None:
        ROOT = Path(root).resolve()
    return ROOT


def _plan(root: Path) -> dict[str, Any]:
    return _common(root)[0](root / PLAN_REL)


def _runtime(root: Path):
    """Verify source identity, then install the runtime's finite-resource mode."""
    cache_key = str(root.resolve())
    if cache_key in _RUNTIME_CACHE:
        return _RUNTIME_CACHE[cache_key]
    sys.path.insert(0, str(root))
    from scripts import prism_m81_run as runtime
    runtime.ROOT = root
    plan, execution = runtime.verify()
    runtime.install_resource_mode()
    from scripts import prism_bounded_eval as bounded
    bounded.ROOT = root
    bounded.legacy.ROOT = root
    remaining = runtime.bounds()
    if not isinstance(remaining, (int, float)) or not math.isfinite(remaining) or remaining <= 0:
        raise ValueError("M81 runtime must provide a finite positive resource watchdog")
    resolved = (runtime, plan, execution, bounded)
    _RUNTIME_CACHE[cache_key] = resolved
    return resolved


def _asset_path(root: Path, actor: str, opponent: str) -> tuple[Path, Path]:
    candidate = (root / "inputs/parent.json" if actor == "base" else
                 root / f"campaigns/{actor}/cycle-20-export/weights.json")
    other = (root / "bin/splendor" if opponent == "heuristic" else
             root / "inputs/parent.json" if opponent == "parent" else
             root / f"inputs/{opponent}.json")
    return candidate, other


def config(actor: str, opponent: str, seeds: list[int], *, root: str | Path | None = None,
           plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the frozen two-greedy-player config for one shard."""
    root_path = _root(root)
    plan = _plan(root_path) if plan is None else plan
    evaluation = plan["evaluation"]
    if actor not in ACTORS or opponent not in (*evaluation["opponents"], "parent"):
        raise ValueError(f"invalid M81 actor/opponent: {actor}/{opponent}")
    if not seeds or any(type(seed) is not int for seed in seeds):
        raise ValueError("shard seeds must be a nonempty integer list")
    candidate_path, opponent_path = _asset_path(root_path, actor, opponent)
    from scripts import prism_notebook_arena as arena
    from training.prism_portable.common import digest, read
    engine = root_path / "bin/splendor"
    candidate = arena.model(candidate_path, actor, engine, mode="greedy",
                            action_seed=evaluation["action_seed"])["descriptor"]
    other = (arena.heuristic(engine, "Heuristic v0.3.1", evaluation["action_seed"])["descriptor"]
             if opponent == "heuristic" else
             arena.model(opponent_path, opponent, engine, mode="greedy",
                         action_seed=evaluation["action_seed"])["descriptor"])
    if opponent == "heuristic" and digest(engine) != plan["assets"]["heuristic"]["engine_sha256"]:
        raise ValueError("M81 heuristic engine SHA differs from frozen plan")
    assets = plan["assets"]
    if actor == "base" and digest(candidate_path) != assets["parent"]["sha256"]:
        raise ValueError("M81 frozen base weights drift")
    if actor in ("A", "B") and not candidate_path.is_file():
        raise FileNotFoundError(f"fixed c20 weights are not available yet: {candidate_path}")
    if opponent not in ("heuristic", "parent") and digest(opponent_path) != assets[opponent]["sha256"]:
        raise ValueError(f"M81 opponent weights drift: {opponent}")
    catalog = read(root_path / "inputs/parent.json")["catalog_fingerprint"]
    return {
        "format": "prism-ppo-fixed-eval-v1",
        "engine": {"program": str(engine), "sha256": digest(engine)},
        "catalog_fingerprint": catalog,
        "action_seed": evaluation["action_seed"],
        "seeds": list(seeds),
        "candidates": {actor: candidate},
        "opponents": {opponent: other},
        "timeouts": {"game_wall_seconds": plan["resources"]["game_wall_seconds"],
                     "handshake_timeout_ms": plan["resources"]["handshake_timeout_ms"],
                     "move_timeout_ms": plan["resources"]["move_timeout_ms"],
                     "shutdown_grace_ms": 1000},
    }


def _groups(plan: dict[str, Any]) -> list[tuple[str, str, int, int]]:
    e = plan["evaluation"]
    groups = [(actor, opponent, *e["seed_by_opponent"][opponent])
              for actor in ACTORS for opponent in e["opponents"]]
    groups.extend((actor, "parent", *e["direct_parent"]["seed_range"])
                  for actor in e["direct_parent"]["actors"])
    return groups


def _planned_shards(plan: dict[str, Any]) -> list[dict[str, Any]]:
    e = plan["evaluation"]
    width = e["shard_seed_blocks"]
    result = []
    for actor, opponent, low, high in _groups(plan):
        for start in range(low, high + 1, width):
            stop = min(start + width - 1, high)
            result.append({"label": f"{actor}-{opponent}-{start}", "actor": actor,
                           "opponent": opponent, "seed_start": start, "seed_end": stop,
                           "seeds": list(range(start, stop + 1)),
                           "planned_games": (stop - start + 1) * 2})
    expected = e["total_games"]
    if sum(row["planned_games"] for row in result) != expected or len(result) != 224:
        raise ValueError("M81 evaluation grid count drift")
    return result


def freeze(label: str, cfg: dict[str, Any], category: str = "independent", *,
           root: str | Path | None = None) -> dict[str, Any]:
    """Persist an immutable config/policy and prepare a bounded shard once."""
    root_path = _root(root)
    _, plan, _, bounded = _runtime(root_path)
    read, write, digest, _ = _common(root_path)
    if category != "independent":
        raise ValueError("M81 evaluation shards must be independent")
    evaluation = plan["evaluation"]
    label = str(label)
    cfg_path = root_path / "evaluation-configs" / f"{label}.json"
    policy_path = cfg_path.with_suffix(".policy.json")
    output = root_path / "evaluation" / label
    count = len(cfg["seeds"]) * 2
    policy = {"format": bounded.FORMAT, "max_games": count,
              "max_truncated_games": count, "ply_cap": evaluation["ply_cap"],
              "deadline_unix": None,
              "cpu_seconds": plan["resources"]["evaluation_cpu_seconds"],
              "memory_bytes": plan["resources"]["eval_rss_bytes_per_worker"],
              "storage_bytes": 128 * 1024**2, "max_processes": 12,
              "automatic_game_retries": 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        validated, prior_policy = bounded.load_bound(output)
        if validated["config"] != cfg or prior_policy != policy:
            raise ValueError(f"existing M81 shard differs from frozen contract: {label}")
    else:
        if cfg_path.exists() and read(cfg_path) != cfg:
            raise ValueError(f"frozen M81 config drift: {label}")
        if policy_path.exists() and read(policy_path) != policy:
            raise ValueError(f"frozen M81 policy drift: {label}")
        write(cfg_path, cfg)
        write(policy_path, policy)
        bounded.prepare(cfg_path, policy_path, output)
    return {**{k: v for k, v in _shard_from_config(label, cfg, plan).items()
               if k != "seeds"}, "output": str(output),
            "manifest_sha256": digest(output / "manifest.json")}


def _shard_from_config(label: str, cfg: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    actor = next(iter(cfg["candidates"]))
    opponent = next(iter(cfg["opponents"]))
    seeds = cfg["seeds"]
    expected = next((s for s in _planned_shards(plan) if s["label"] == label), None)
    if expected is None or (actor, opponent, seeds) != (expected["actor"], expected["opponent"], expected["seeds"]):
        raise ValueError(f"shard label/config identity mismatch: {label}")
    return expected


def grid(output: str | Path, *, root: str | Path | None = None) -> dict[str, Any]:
    """Execute one shard or return its already-finished ledger without replay."""
    root_path = _root(root)
    runtime, plan, _, bounded = _runtime(root_path)
    from training.prism_portable.common import lock, read, write, digest
    output = Path(output).resolve()
    validated, policy = bounded.load_bound(output)
    ledger_path = output / "ledger.json"
    with lock(output / "m81-dispatch-owner"):
        ledger = (read(ledger_path) if ledger_path.exists() else
                  {"execution_state": "RUNNING", "entries": {}, "consumed_cpu_seconds": 0.0,
                   "manifest_sha256": digest(output / "manifest.json")})
        if ledger["manifest_sha256"] != digest(output / "manifest.json"):
            raise ValueError("M81 ledger/manifest drift")
        if ledger["execution_state"] == "FINISHED":
            return bounded.inspect(output)
        if ledger["execution_state"] == "RUNNING" and ledger["entries"]:
            raise ValueError("interrupted M81 shard requires owner/evidence review; no duplicate games")
        if any(row.get("state") == "RETAINED_FAILURE" and
               row.get("kind") != "PLY_CAP_TRUNCATED" for row in ledger["entries"].values()):
            raise ValueError("retained M81 scientific/resource failure")
        ledger["execution_state"] = "RUNNING"
        write(ledger_path, ledger)
        jobs = bounded.legacy.jobs(validated["config"])
        try:
            for job in jobs:
                runtime.bounds()
                key = bounded.fixed._game_key(*job)
                if key in ledger["entries"] and ledger["entries"][key].get("state") in ("COMPLETED", "RETAINED_FAILURE"):
                    continue
                cap_count = _scientific_caps(root_path, read)
                if cap_count >= plan["evaluation"]["max_scientific_truncations"]:
                    ledger["stop_reason"] = "SCIENTIFIC_CAP_BUDGET"
                    break
                remaining = policy["cpu_seconds"] - ledger["consumed_cpu_seconds"]
                if remaining <= 0:
                    ledger["stop_reason"] = "SHARD_CPU_BUDGET"
                    break
                reservation_key = output.name + "/" + key
                try:
                    admitted_cpu = _reserve_cpu(root_path, plan, reservation_key,
                                                min(30.0, remaining), read, write)
                except _EvaluationBudgetExhausted:
                    ledger["stop_reason"] = "EVALUATION_CPU_BUDGET"
                    break
                ledger["entries"][key] = {"state": "DISPATCHED"}
                write(ledger_path, ledger)
                try:
                    entry = bounded.evaluate(validated, policy, output, job, admitted_cpu)
                except BaseException as exc:
                    ledger["entries"][key] = {"state": "RETAINED_FAILURE",
                                              "kind": "UNKNOWN_OR_RESOURCE_FAILURE",
                                              "error": repr(exc),
                                              "evidence_sha256": bounded.evidence(
                                                  bounded.legacy.game_directory(output, job))}
                    ledger["consumed_cpu_seconds"] = policy["cpu_seconds"]
                    ledger["cpu_charge"] = "FULL_REMAINDER_RESERVED_AFTER_FAILURE"
                    write(ledger_path, ledger)
                    _settle_cpu(root_path, reservation_key, 0.0, failed=True,
                                read=read, write=write)
                    raise
                actual_cpu = entry.pop("cpu_seconds")
                ledger["consumed_cpu_seconds"] += actual_cpu
                ledger["entries"][key] = dict(entry, evidence_sha256=bounded.evidence(
                    bounded.legacy.game_directory(output, job)))
                write(ledger_path, ledger)
                _settle_cpu(root_path, reservation_key, actual_cpu, failed=False,
                            read=read, write=write)
            ledger["execution_state"] = ("FINISHED" if len(ledger["entries"]) == len(jobs)
                                         else "STOPPED")
            if ledger["execution_state"] == "STOPPED" and "stop_reason" not in ledger:
                ledger["stop_reason"] = "INCOMPLETE_WITH_RETAINED_EVIDENCE"
        finally:
            write(ledger_path, ledger)
            write(output / "grid-status.json", bounded.summary(validated["config"], ledger))
        return bounded.summary(validated["config"], ledger)


def _scientific_caps(root: Path, read) -> int:
    total = 0
    eval_dir = root / "evaluation"
    if not eval_dir.exists():
        return 0
    for path in eval_dir.glob("*/ledger.json"):
        ledger = read(path)
        total += sum(entry.get("kind") == "PLY_CAP_TRUNCATED"
                     for entry in ledger.get("entries", {}).values())
    return total


@contextmanager
def _resource_lock(root: Path):
    """Acquire the shared CPU ledger lock across local worker processes."""
    from training.prism_portable.common import lock
    while True:
        manager = lock(root / "evaluation-resource-control")
        try:
            manager.__enter__()
        except RuntimeError:
            time.sleep(0.01)
            continue
        try:
            yield
        finally:
            manager.__exit__(None, None, None)
        return


def _reserve_cpu(root: Path, plan: dict[str, Any], key: str, maximum: float,
                 read, write) -> float:
    """Admit each game against the shared 150k CPU-second research ceiling."""
    path = root / "evaluation" / "resource-budget.json"
    budget = float(plan["resources"]["evaluation_cpu_seconds"])
    with _resource_lock(root):
        if path.exists():
            ledger = read(path)
            if ledger.get("budget_cpu_seconds") != budget:
                raise ValueError("M81 shared evaluation CPU budget drift")
        else:
            spent = 0.0
            for ledger_path in (root / "evaluation").glob("*/ledger.json"):
                item = read(ledger_path)
                value = item.get("consumed_cpu_seconds", 0.0)
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"invalid imported shard CPU accounting: {ledger_path}")
                spent += value
            ledger = {"format": "prism-m81-evaluation-resource-budget-v1",
                      "budget_cpu_seconds": budget, "spent_cpu_seconds": spent,
                      "reservations": {}, "adopted_shard_cpu_seconds": spent}
        reservations = ledger.setdefault("reservations", {})
        if ledger.get("exhausted"):
            raise ValueError("M81 shared evaluation CPU budget closed after a retained failure")
        if key in reservations:
            raise ValueError(f"M81 game already has an unresolved CPU reservation: {key}")
        reserved = sum(float(item["reserved_cpu_seconds"]) for item in reservations.values())
        available = budget - float(ledger["spent_cpu_seconds"]) - reserved
        if available <= 0:
            raise _EvaluationBudgetExhausted("M81 shared evaluation CPU budget exhausted")
        amount = min(maximum, available)
        reservations[key] = {"reserved_cpu_seconds": amount, "state": "RESERVED",
                             "observed_at": time.time(), "pid": os.getpid()}
        write(path, ledger)
        return amount


def _settle_cpu(root: Path, key: str, actual: float, *, failed: bool,
                read, write) -> None:
    path = root / "evaluation" / "resource-budget.json"
    with _resource_lock(root):
        ledger = read(path)
        reservation = ledger.get("reservations", {}).get(key)
        if reservation is None:
            raise ValueError(f"M81 CPU reservation disappeared: {key}")
        maximum = float(reservation["reserved_cpu_seconds"])
        if failed:
            ledger["spent_cpu_seconds"] = float(ledger["spent_cpu_seconds"]) + maximum
            del ledger["reservations"][key]
            ledger["exhausted"] = True
        else:
            if not math.isfinite(actual) or actual < 0 or actual > maximum + 1e-6:
                raise ValueError(f"M81 game CPU exceeds admitted reservation: {key}")
            ledger["spent_cpu_seconds"] = float(ledger["spent_cpu_seconds"]) + actual
            del ledger["reservations"][key]
        write(path, ledger)


def _actors_from_env() -> tuple[str, ...]:
    raw = os.environ.get("M81_EVAL_ACTORS", "base,A,B")
    actors = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not actors or len(set(actors)) != len(actors) or any(a not in ACTORS for a in actors):
        raise ValueError("M81_EVAL_ACTORS must be a unique comma-separated subset of base,A,B")
    return tuple(a for a in ACTORS if a in actors)


def evaluate(root: str | Path | None = None) -> dict[str, Any]:
    """Freeze and run selected actors; M81_EVAL_ACTORS=base is the aux path."""
    root_path = _root(root)
    runtime, plan, execution, bounded = _runtime(root_path)
    read, write, digest, _ = _common(root_path)
    actors = _actors_from_env()
    all_shards = _planned_shards(plan)
    # Bind the exact replay projector and its Rust/feature sources before any
    # evaluation game can be admitted. Both nodes must see the same root and SHA.
    from scripts.prism_m81_report import _profile_source_bindings
    profile_bindings = _profile_source_bindings(root_path)
    plan_record = {"format": "prism-m81-evaluation-grid-v1", "round": "M81",
                   "total_games": plan["evaluation"]["total_games"],
                   "plan_sha256": digest(root_path / PLAN_REL),
                   "execution_plan_sha256": execution.get("plan_sha256"),
                   "profile_source_bindings": profile_bindings,
                   "shards": [{k: v for k, v in shard.items() if k != "seeds"}
                              for shard in all_shards]}
    plan_path = root_path / "evaluation-plan.json"
    if plan_path.exists() and read(plan_path) != plan_record:
        raise ValueError("M81 evaluation plan identity drift")
    write(plan_path, plan_record)

    selected = [shard for shard in all_shards if shard["actor"] in actors]
    frozen = []
    for shard in selected:
        cfg = config(shard["actor"], shard["opponent"], shard["seeds"], root=root_path, plan=plan)
        frozen.append(freeze(shard["label"], cfg, root=root_path))

    profile = __import__("scripts.prism_notebook_arena", fromlist=["resource_profile"])
    workers = min(plan["resources"]["eval_worker_slots_max"],
                  profile.worker_limit(profile.resource_profile()))
    done = []
    failures = []
    # A baseline shard already FINISHED on the auxiliary node is adopted by
    # its immutable ledger. No game is replayed when the main stage reaches it.
    pending = []
    for shard in frozen:
        ledger_path = Path(shard["output"]) / "ledger.json"
        if ledger_path.exists() and read(ledger_path).get("execution_state") == "FINISHED":
            done.append({**shard, "grid": bounded.inspect(shard["output"])})
        else:
            pending.append(shard)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_run_child, shard, root_path): shard for shard in pending}
        for future in as_completed(futures):
            shard = futures[future]
            try:
                status = future.result()
                done.append({**shard, "grid": status})
                if status.get("execution_state") != "FINISHED":
                    failures.append({"label": shard["label"], "reason": status.get("stop_reason", "INCOMPLETE")})
            except BaseException as exc:
                failures.append({"label": shard["label"], "reason": repr(exc)})
                # A hard shard error stops admitting further work. Already
                # running jobs are allowed to publish their bounded evidence.
                for other in futures:
                    if other is not future:
                        other.cancel()
                break

    receipt = {"format": "prism-m81-evaluation-stage-v1", "round": "M81",
               "status": "PASS" if not failures and len(done) == len(selected) else "INCOMPLETE",
               "actor_filter": list(actors), "auxiliary_baseline_only": actors == ("base",),
               "planned_games_selected": sum(s["planned_games"] for s in selected),
               "completed_games": sum(s.get("grid", {}).get("completed_games", 0) for s in done),
               "truncated_games": _scientific_caps(root_path, read),
               "selected_shards": len(selected), "finished_shards": sum(
                   s.get("grid", {}).get("execution_state") == "FINISHED" for s in done),
               "failures": failures, "plan_sha256": digest(plan_path),
               "resource_mode": "finite CPU and work bounds; no calendar deadline",
               "observed_at": time.time()}
    write(root_path / "evaluation-completion.json", receipt)
    return receipt


def _run_child(shard: dict[str, Any], root: Path) -> dict[str, Any]:
    output = shard["output"]
    log = Path(output) / "worker.log"
    # This pinned wrapper activates the remote package environment. sys.executable
    # may resolve to the bundled interpreter without the required child packages.
    argv = [PYTHON, "-B", str(Path(__file__).resolve()), "grid", "--output", output,
            "--root", str(root)]
    with log.open("ab") as stream:
        proc = subprocess.run(argv, cwd=root, stdout=stream, stderr=subprocess.STDOUT,
                              check=False)
    if proc.returncode:
        raise RuntimeError(f"M81 shard child exited {proc.returncode}: {shard['label']}")
    from training.prism_portable.common import read
    return read(Path(output) / "grid-status.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    grid_parser = sub.add_parser("grid")
    grid_parser.add_argument("--output", required=True)
    grid_parser.add_argument("--root")
    args = parser.parse_args()
    print(json.dumps(grid(args.output, root=args.root), ensure_ascii=False), flush=True)
