"""Read-only audit of the committed M79 c20 training artifact and attempts.

This auditor owns M79's logical/physical attempt and retained-cap rules. It
does not import or patch the M75 auditor or its recovery policy.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import html
import importlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOGICAL_ATTEMPTS = 5120
CYCLES = 20
INFRA_LIMIT = 64
TRUNCATION_LIMIT = 8
TENSOR_COUNT = 32
PARITY_INPUTS = 68
INFRA_REASONS = {"handshake_timeout", "action_timeout", "agent_eof", "agent_io"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_json(path: str | Path) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    with Path(path).open("r", encoding="utf-8") as source:
        return json.load(
            source,
            object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number: {value}")),
        )


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def _jobs_from_spec(spec: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    cycles = spec.get("cycles")
    require(isinstance(cycles, list) and len(cycles) == CYCLES,
            "campaign contract must declare exactly 20 cycles")
    flattened: list[dict[str, Any]] = []
    all_cycles: list[list[dict[str, Any]]] = []
    for index, cycle in enumerate(cycles, start=1):
        require(isinstance(cycle, list) and cycle,
                f"campaign cycle {index} is empty or malformed")
        copied: list[dict[str, Any]] = []
        for job in cycle:
            require(isinstance(job, dict), "scheduled job must be an object")
            require(set(job) == {"job_id", "actor", "opponent_id", "environment_seed"},
                    "scheduled job schema drift")
            require(isinstance(job["job_id"], str) and job["job_id"], "invalid job id")
            require(type(job["actor"]) is int and job["actor"] in (0, 1), "invalid job actor")
            require(isinstance(job["opponent_id"], str) and job["opponent_id"], "invalid opponent id")
            require(type(job["environment_seed"]) is int and job["environment_seed"] >= 0,
                    "invalid environment seed")
            copied.append(job)
        all_cycles.append(copied)
        flattened.extend(copied)
    ids = [job["job_id"] for job in flattened]
    require(len(flattened) == LOGICAL_ATTEMPTS, "campaign logical schedule is not 5120 jobs")
    require(len(ids) == len(set(ids)), "duplicate scheduled logical job")
    return flattened, all_cycles


def _job_id_map(jobs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {job["job_id"]: job for job in jobs}


def _validate_infra_row(row: Mapping[str, Any]) -> None:
    """Require explicit infrastructure evidence; caps/deadlines are scientific failures."""
    outcome = row.get("outcome")
    resources = row.get("resources")
    reason = row.get("reason")
    if isinstance(outcome, dict):
        require(outcome.get("status") == "aborted", "infrastructure row contains non-aborted outcome")
        require(outcome.get("reason") in INFRA_REASONS, "abort is not an authorized infrastructure cause")
        return
    if isinstance(resources, dict) and resources.get("stop_reason") == "spawn_infrastructure":
        return
    require(reason == "interrupted_unpublished",
            "infrastructure abort lacks a recognized infrastructure cause")


def validate_ledger(
    ledger: Mapping[str, Any],
    state: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one result per logical job and separately charge physical retries.

    COMPLETE and TRUNCATED each resolve one scheduled logical job. INFRA_ABORT
    adds one physical attempt for that same job and never fills another slot.
    """
    jobs, cycles = _jobs_from_spec(spec)
    jobs_by_id = _job_id_map(jobs)
    expected_ids = [job["job_id"] for job in jobs]
    expected_set = set(expected_ids)

    require(ledger.get("format") == "prism-ppo-launch-ledger-v1", "unknown M79 launch ledger format")
    require(ledger.get("failed") is False, "failed campaign ledger cannot pass training audit")
    attempts = ledger.get("attempts")
    require(isinstance(attempts, dict), "launch ledger attempts must be an object")
    require(type(state.get("attempts")) is int and state["attempts"] == len(attempts),
            "physical attempts disagree with committed run state")
    require(state.get("phase") == "COMMITTED", "run is not COMMITTED")
    require(type(state.get("cycle")) is int and state["cycle"] == CYCLES,
            "run is not committed at cycle 20")
    consumed = state.get("consumed")
    require(isinstance(consumed, list) and len(consumed) == CYCLES
            and len(set(consumed)) == CYCLES
            and all(_is_sha(batch_id) for batch_id in consumed),
            "cycle batches were missing or consumed more than once")
    all_jobs = state.get("all_jobs")
    require(isinstance(all_jobs, list) and all_jobs == expected_ids,
            "committed logical job order differs from frozen schedule")

    budget = spec.get("run", {}).get("budget", {})
    limits = spec.get("limits", {})
    if "max_jobs" in budget:
        require(budget["max_jobs"] == LOGICAL_ATTEMPTS, "run logical job budget drift")
    if "max_cycles" in budget:
        require(budget["max_cycles"] == CYCLES, "run cycle budget drift")
    if "max_attempts" in budget:
        require(type(budget["max_attempts"]) is int
                and budget["max_attempts"] == LOGICAL_ATTEMPTS + INFRA_LIMIT,
                "M79 physical attempt ceiling drift")
    if "max_infra_retries" in limits:
        require(limits["max_infra_retries"] == INFRA_LIMIT, "M79 infrastructure retry budget drift")

    physical_ids: list[int] = []
    by_job: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    statuses: Counter[str] = Counter()
    charged = 0
    for raw_number, row in attempts.items():
        require(isinstance(raw_number, str) and raw_number.isdecimal()
                and str(int(raw_number)) == raw_number,
                "physical attempt ids must be canonical positive integers")
        number = int(raw_number)
        require(number > 0, "physical attempt id must be positive")
        require(number not in physical_ids, "duplicate physical attempt id")
        physical_ids.append(number)
        require(isinstance(row, dict), "physical attempt row must be an object")
        job = row.get("job")
        require(isinstance(job, dict) and isinstance(job.get("job_id"), str),
                "physical attempt lacks logical job identity")
        job_id = job["job_id"]
        require(job_id in expected_set, f"attempt is outside frozen schedule: {job_id}")
        require(job == jobs_by_id[job_id], f"physical attempt job definition drift: {job_id}")
        status = row.get("status")
        require(status in ("COMPLETE", "TRUNCATED", "INFRA_ABORT"),
                f"unresolved or scientific-failure attempt status: {status}")
        retry_charged = row.get("retry_charged")
        require(type(retry_charged) is bool, "physical attempt retry charge is missing")
        require(retry_charged is (status == "INFRA_ABORT"),
                "retry charge does not match infrastructure attempt status")
        decisions = row.get("charged_decisions")
        require(type(decisions) is int and decisions >= 0,
                "physical attempt decision charge is missing")
        max_job_decisions = budget.get("max_job_decisions")
        if max_job_decisions is not None:
            require(decisions <= max_job_decisions, "physical attempt decision charge exceeds job cap")
        charged += decisions
        statuses[status] += 1
        if status == "INFRA_ABORT":
            _validate_infra_row(row)
        elif status == "TRUNCATED":
            require(isinstance(row.get("outcome"), dict)
                    and row["outcome"].get("status") == "truncated",
                    "TRUNCATED attempt lacks a scientific cap outcome")
        by_job[job_id].append((number, row))

    require(sorted(physical_ids) == list(range(1, len(attempts) + 1)),
            "physical attempt ledger has a missing attempt number")
    physical_count = len(attempts)
    infra_count = statuses["INFRA_ABORT"]
    cap_count = statuses["TRUNCATED"]
    terminal_count = statuses["COMPLETE"]
    require(infra_count <= INFRA_LIMIT, "global M79 infrastructure retry limit exceeded")
    require(cap_count <= TRUNCATION_LIMIT, "M79 scientific truncation limit exceeded")
    require(physical_count == LOGICAL_ATTEMPTS + infra_count,
            "physical attempts must equal logical jobs plus infrastructure aborts")
    if "max_attempts" in budget:
        require(physical_count <= budget["max_attempts"], "physical attempt ceiling exceeded")
    require(terminal_count + cap_count == LOGICAL_ATTEMPTS,
            "terminal and capped attempts do not resolve exactly 5120 logical jobs")
    require(type(ledger.get("retries")) is int and ledger["retries"] == infra_count,
            "launch ledger retry total disagrees with infrastructure attempts")
    require(type(ledger.get("physical_decisions")) is int and ledger["physical_decisions"] == charged,
            "physical decision ledger mismatch")
    maximum_physical_decisions = limits.get("max_physical_decisions")
    if maximum_physical_decisions is not None:
        require(charged <= maximum_physical_decisions, "physical decision budget exceeded")

    valid_attempt_by_job: dict[str, tuple[int, Mapping[str, Any]]] = {}
    infra_by_job: Counter[str] = Counter()
    for job_id in expected_ids:
        rows = by_job.get(job_id, [])
        valid = [(number, row) for number, row in rows if row["status"] in ("COMPLETE", "TRUNCATED")]
        infra_rows = [(number, row) for number, row in rows if row["status"] == "INFRA_ABORT"]
        require(len(valid) == 1, f"logical job must resolve exactly once: {job_id}")
        require(len(infra_rows) <= 1, f"logical job exceeded one infrastructure retry: {job_id}")
        if infra_rows:
            require(infra_rows[0][0] < valid[0][0],
                    f"infrastructure abort occurred after job resolution: {job_id}")
        valid_attempt_by_job[job_id] = valid[0]
        infra_by_job[job_id] = len(infra_rows)
    require(sum(infra_by_job.values()) == infra_count, "orphan infrastructure attempt")

    state_jobs = state.get("jobs")
    if state_jobs is not None:
        final_jobs = {job["job_id"]: job for job in cycles[-1]}
        require(isinstance(state_jobs, dict) and set(state_jobs) == set(final_jobs),
                "committed final-cycle job map differs from schedule")
        for job_id in final_jobs:
            number, attempt_row = valid_attempt_by_job[job_id]
            committed = state_jobs[job_id]
            require(isinstance(committed, dict)
                    and committed.get("status") == attempt_row["status"]
                    and committed.get("attempt") == number,
                    f"committed final-cycle job disagrees with physical ledger: {job_id}")

    return {
        "logical_attempts": LOGICAL_ATTEMPTS,
        "physical_attempts": physical_count,
        "terminal_games": terminal_count,
        "truncated_games": cap_count,
        "infra_abort_attempts": infra_count,
        "resolved_logical_jobs": len(valid_attempt_by_job),
        "physical_decisions": charged,
        "attempt_by_job": valid_attempt_by_job,
        "jobs_by_cycle": cycles,
    }


def _remaining_seconds(bounds: Callable[[], Any]) -> float:
    value = bounds()
    if isinstance(value, Mapping):
        for key in ("remaining_seconds", "seconds_remaining", "deadline_remaining_seconds"):
            if key in value:
                value = value[key]
                break
        else:
            if "deadline" in value:
                value = float(value["deadline"]) - time.time()
            else:
                raise ValueError("M79 bounds() did not return a remaining-time bound")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("M79 finite audit deadline is exhausted or invalid")
    return float(value)


def checked(
    argv: list[str | Path],
    receipt: Path,
    *,
    timeout: float = 600,
    bounds: Callable[[], Any],
) -> None:
    command = list(map(str, argv))
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=min(timeout, _remaining_seconds(bounds)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        write_json(receipt, {
            "argv": command,
            "status": "TIMEOUT",
            "timeout_seconds": exc.timeout,
            "wall_seconds": time.monotonic() - started,
        })
        raise ValueError(f"bounded M79 audit command timed out: {receipt}") from exc
    write_json(receipt, {
        "argv": command,
        "exit": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "wall_seconds": time.monotonic() - started,
    })
    if result.returncode:
        raise ValueError(f"offline M79 audit command failed: {receipt}")


def _cycle_behavior_map(
    run: Any,
    state: Mapping[str, Any],
    cycles: list[list[dict[str, Any]]],
    summary: Mapping[str, Any],
    campaign: Path,
) -> dict[int, str]:
    from training.prism_portable.engine.ppo.learner import validate_batch

    sealed_rows = [row for row in state.get("metrics", []) if row.get("event") == "sealed"]
    require(len(sealed_rows) == CYCLES, "committed run lacks one sealed PPO batch per cycle")
    by_cycle: dict[int, Mapping[str, Any]] = {}
    for row in sealed_rows:
        cycle = row.get("cycle")
        require(type(cycle) is int and 1 <= cycle <= CYCLES and cycle not in by_cycle,
                "duplicate or invalid sealed cycle")
        by_cycle[cycle] = row
    require(set(by_cycle) == set(range(1, CYCLES + 1)), "missing sealed PPO cycle")
    require(state["consumed"] == [by_cycle[index]["batch_id"] for index in range(1, CYCLES + 1)],
            "PPO batches were not consumed once in cycle order")

    # A sealed batch's semantic ID excludes the ID field itself.  The binding
    # therefore supplies the separate CommitStore object key for direct reads.
    commit_chain: set[str] = set()
    cursor = run.parent
    while cursor is not None:
        require(cursor not in commit_chain, "cyclic M79 run commit chain")
        commit_chain.add(cursor)
        record = json.loads(run.store._get("commits", cursor, ".json").decode("utf-8"))
        require(record.get("format") == "prism-ppo-commit-v1"
                and record.get("identity") == run.identity,
                "M79 binding commit chain identity mismatch")
        cursor = record.get("parent")

    behavior_by_cycle: dict[int, str] = {}
    for cycle, schedule in enumerate(cycles, start=1):
        binding = read_json(campaign / f"cycle-{cycle}-batch-binding.json")
        require(binding.get("cycle") == cycle
                and binding.get("batch_id") == by_cycle[cycle]["batch_id"]
                and _is_sha(binding.get("batch_object_sha256"))
                and _is_sha(binding.get("behavior_id"))
                and type(binding.get("cursor")) is int and binding["cursor"] == 0
                and _is_sha(binding.get("run_commit"))
                and binding["run_commit"] in commit_chain,
                f"cycle {cycle} batch binding mismatch")
        if cycle == CYCLES:
            require(binding["batch_object_sha256"] == state.get("batch"),
                    "cycle-20 object binding differs from committed run batch pointer")
        batch = run.store.get_json(binding["batch_object_sha256"])
        validate_batch(batch, run.ppo)
        require(batch.get("batch_id") == binding["batch_id"]
                and batch.get("behavior_id") == binding["behavior_id"],
                f"cycle {cycle} semantic batch/behavior binding mismatch")
        key_to_indices: dict[tuple[str, int], set[int]] = defaultdict(set)
        for row in batch["rows"]:
            key = row.get("key")
            require(isinstance(key, list) and len(key) == 3 and isinstance(key[0], str)
                    and type(key[1]) is int and key[1] in (0, 1)
                    and type(key[2]) is int and key[2] >= 0,
                    f"cycle {cycle} contains a malformed PPO row key")
            key_to_indices[(key[0], key[1])].add(key[2])
        terminal_jobs = {
            (job["job_id"], job["actor"])
            for job in schedule
            if summary["attempt_by_job"][job["job_id"]][1]["status"] == "COMPLETE"
        }
        require(set(key_to_indices) == terminal_jobs,
                f"cycle {cycle} PPO batch does not contain exactly its terminal jobs")
        for job_key, indices in key_to_indices.items():
            require(indices == set(range(len(indices))), f"cycle {cycle} PPO decisions have a gap: {job_key[0]}")
        behavior_by_cycle[cycle] = binding["behavior_id"]
    return behavior_by_cycle


def validate_cap(
    spec: Mapping[str, Any],
    job: Mapping[str, Any],
    row: Mapping[str, Any],
    report: Mapping[str, Any],
    prefix: Mapping[str, Any],
    resources: Mapping[str, Any],
    *,
    sidecar_count: int,
    replay_exists: bool,
    behavior_id: str,
    sidecar_path: Path,
) -> dict[str, Any]:
    """Validate a generic retained M79 ply-cap prefix without M75 policy."""
    from training.prism_portable.engine.ppo.execution import verify_report
    from scripts.prism_bounded_eval import trace_metrics

    outcome = verify_report(spec, dict(job), dict(report))
    cap = spec["limits"]["max_plies"]
    require(row.get("status") == "TRUNCATED" and row.get("job") == job,
            "attempt is not the scheduled M79 retained cap")
    require(row.get("resources") == resources, "cap process resource receipt drift")
    require(resources.get("returncode") == 0 and resources.get("stop_reason") is None,
            "scientific cap must be a normally completed Arena process")
    require(outcome.get("status") == "truncated" and row.get("outcome") == outcome,
            "cap report/ledger outcome mismatch")
    require(not replay_exists, "truncated game must not have a terminal replay")
    require(prefix.get("format") == "splendor-rollout-prefix"
            and type(prefix.get("version")) is int and prefix["version"] == 1
            and prefix.get("seed") == job["environment_seed"]
            and prefix.get("player_count") == 2
            and prefix.get("ruleset_fingerprint") == spec["run"]["catalog_fingerprint"],
            "cap prefix identity mismatch")
    require("result" not in prefix, "cap prefix contains a fabricated terminal result")
    steps = prefix.get("steps")
    require(isinstance(steps, list)
            and type(prefix.get("ply_cap")) is int
            and prefix["ply_cap"] == outcome.get("completed_plies") == len(steps) == cap,
            "strict prefix length does not equal frozen M79 cap")
    require(prefix.get("cap_state_hash") == outcome.get("cap_state_hash"),
            "cap prefix/report final hash mismatch")
    cap_scores = outcome.get("cap_scores")
    require(isinstance(cap_scores, list) and len(cap_scores) == 2
            and all(type(score) is int and 0 <= score <= 255 for score in cap_scores),
            "invalid nonterminal cap score snapshot")
    metrics = trace_metrics(dict(prefix))
    learner_decisions = metrics["by_actor"][job["actor"]]["actions"]
    require(type(sidecar_count) is int and sidecar_count == learner_decisions,
            "cap sidecar count differs from learner actions in strict prefix")
    require(row.get("charged_decisions") == sidecar_count,
            "cap physical decision charge differs from sidecar")
    sidecar_rows = _read_sidecar(sidecar_path)
    require(len(sidecar_rows) == sidecar_count, "cap sidecar file/count mismatch")
    _validate_sidecar_identity(
        sidecar_path, sidecar_rows, job=job, behavior_id=behavior_id,
        catalog_fingerprint=spec["run"]["catalog_fingerprint"], max_decisions=cap,
    )
    return metrics


def _verify_training_plan(plan: Mapping[str, Any], spec: Mapping[str, Any]) -> None:
    training = plan.get("training")
    require(isinstance(training, dict), "M79 run verifier did not return the frozen training plan")
    require(training.get("cycles") == CYCLES
            and training.get("logical_attempts") == LOGICAL_ATTEMPTS
            and training.get("seed_blocks_per_cycle") == 128
            and training.get("seats") == [0, 1]
            and training.get("seed_range") == [17001000, 17003559]
            and training.get("ply_cap") == 256
            and training.get("max_scientific_truncations") == TRUNCATION_LIMIT,
            "M79 frozen training budget drift")
    order = training.get("opponent_order")
    require(order == ["general", "parent", "latest-alpha", "latest-balance"],
            "M79 frozen opponent order drift")
    seed_start = training["seed_range"][0]
    require(len(spec["cycles"]) == CYCLES, "runtime campaign cycle count drift")
    require(spec["limits"].get("max_plies") == training["ply_cap"]
            and spec["run"]["budget"].get("max_job_decisions") == training["ply_cap"],
            "M79 runtime cap/decision reservation differs from frozen plan")
    for cycle_index, cycle in enumerate(spec["cycles"]):
        require(len(cycle) == 256, f"M79 cycle {cycle_index + 1} must contain 256 logical jobs")
        expected = [
            {
                "job_id": f"m79-a-c{cycle_index + 1}-b{block}-s{seat}",
                "actor": seat,
                "opponent_id": order[block % 4],
                "environment_seed": seed_start + 128 * cycle_index + block,
            }
            for block in range(128) for seat in (0, 1)
        ]
        require(cycle == expected,
                f"M79 cycle {cycle_index + 1} schedule differs from frozen plan")
    recovery = plan.get("recovery", {})
    if "infra_retry_per_unfinished_logical_job" in recovery:
        require(recovery["infra_retry_per_unfinished_logical_job"] == 1,
                "M79 per-job infrastructure retry budget drift")
    if "infra_retry_total_extra_physical_attempts" in recovery:
        require(recovery["infra_retry_total_extra_physical_attempts"] == INFRA_LIMIT,
                "M79 global infrastructure retry budget drift")
    if "physical_attempt_ceiling_including_infra" in recovery:
        require(recovery["physical_attempt_ceiling_including_infra"]
                == plan.get("logical_attempt_total", -1) + INFRA_LIMIT,
                "M79 round physical attempt ceiling drift")


def _run_api() -> tuple[Mapping[str, Any], Mapping[str, Any], Callable[[], Any], Any]:
    try:
        module = importlib.import_module("scripts.prism_m79_run")
    except ImportError as exc:
        raise ValueError("M79 run verifier scripts.prism_m79_run is not available") from exc
    verified = module.verify()
    if isinstance(verified, tuple) and len(verified) == 2:
        plan, execution = verified
    elif isinstance(verified, Mapping) and "plan" in verified and "execution" in verified:
        plan, execution = verified["plan"], verified["execution"]
    else:
        raise ValueError("M79 verify() must return the frozen plan and execution")
    require(isinstance(plan, Mapping) and isinstance(execution, Mapping),
            "M79 verifier returned malformed plan/execution")
    _remaining_seconds(module.bounds)
    return plan, execution, module.bounds, module


def _execution_sources(execution: Mapping[str, Any]) -> dict[str, str]:
    files = execution.get("files", {})
    require(isinstance(files, dict) and files,
            "M79 execution file pins must be a nonempty object")
    pinned = {}
    for relative, expected in files.items():
        require(isinstance(relative, str) and _is_sha(expected), "malformed M79 execution source pin")
        path = Path(relative)
        if not path.is_absolute():
            path = ROOT / path
        require(path.is_file() and digest(path) == expected,
                f"M79 execution source SHA mismatch: {relative}")
        pinned[path.resolve().relative_to(ROOT.resolve()).as_posix()] = expected
    return pinned


def _assert_source_pins(pinned: Mapping[str, str]) -> None:
    for relative, expected in pinned.items():
        path = ROOT / relative
        require(path.is_file() and digest(path) == expected,
                f"M79 pinned source bytes changed during audit: {relative}")


def _protected_m75_bytes(plan: Mapping[str, Any]) -> dict[str, str]:
    paths = [
        ROOT / "scripts/prism_m75_audit.py",
        ROOT / "scripts/prism_m75_run.py",
        ROOT / "scripts/prism_m75_resume.py",
        ROOT / "docs/m75-prism-continuation.md",
        ROOT / "benchmarks/m75-prism-continuation.result.json",
    ]
    blueprint = plan.get("planning_evidence", {}).get("numeric_blueprint_reference", {})
    if isinstance(blueprint, dict) and isinstance(blueprint.get("path"), str):
        blueprint_path = Path(blueprint["path"])
        paths.append(blueprint_path if blueprint_path.is_absolute() else ROOT / blueprint_path)
    parent = plan.get("assets", {}).get("parent", {})
    if isinstance(parent, dict) and isinstance(parent.get("local_path"), str):
        parent_path = Path(parent["local_path"])
        paths.append(parent_path if parent_path.is_absolute() else ROOT / parent_path)
    protected = {}
    for path in paths:
        if path.is_file():
            protected[path.resolve().relative_to(ROOT.resolve()).as_posix()] = digest(path)
    return protected


def _assert_protected_m75_bytes(before: Mapping[str, str]) -> None:
    for relative, expected in before.items():
        path = ROOT / relative
        require(path.is_file() and digest(path) == expected,
                f"M79 audit changed a protected M75 byte: {relative}")


def _cycle_for_jobs(cycles: list[list[dict[str, Any]]]) -> dict[str, int]:
    return {job["job_id"]: cycle for cycle, group in enumerate(cycles, start=1) for job in group}


def _verify_snapshot_behavior(run: Any, completion: Mapping[str, Any], expected_behavior: str,
                              cache: dict[str, str]) -> None:
    from training.prism_portable.engine.ppo.sampling import Behavior

    snapshot_sha = completion.get("snapshot_sha256")
    require(_is_sha(snapshot_sha), "completion snapshot SHA is malformed")
    observed = cache.get(snapshot_sha)
    if observed is None:
        payload = run.store.get_payload(snapshot_sha)
        behavior = Behavior.from_payload(payload, runtime=run.runtime)
        observed = behavior.identity
        cache[snapshot_sha] = observed
    require(observed == expected_behavior == completion.get("behavior_id"),
            "completion behavior is not bound to its cycle's consumed snapshot")


def _read_sidecar(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed sidecar line {number}: {path}") from exc
        require(isinstance(row, dict), f"sidecar row {number} is not an object")
        rows.append(row)
    return rows


def _validate_sidecar_identity(
    sidecar: Path,
    rows: list[dict[str, Any]],
    *,
    job: Mapping[str, Any],
    behavior_id: str,
    catalog_fingerprint: str,
    max_decisions: int,
) -> None:
    from training.prism_portable.engine.ppo.contract import validate_row

    require(len(rows) <= max_decisions, f"sidecar exceeds physical decision cap: {sidecar}")
    for index, row in enumerate(rows):
        validate_row(row)
        request = row["request"]
        require(request["behavior_id"] == behavior_id
                and request["catalog_fingerprint"] == catalog_fingerprint
                and request["job_id"] == job["job_id"]
                and request["game_id"] == job["job_id"]
                and request["actor"] == job["actor"]
                and request["decision_index"] == index,
                f"sidecar behavior/job identity mismatch: {job['job_id']}")


def _verify_terminal_sidecar(
    path: Path,
    *,
    job: Mapping[str, Any],
    behavior_id: str,
    spec: Mapping[str, Any],
    result: Mapping[str, Any],
    replay: Mapping[str, Any],
) -> None:
    from training.prism_portable.engine.ppo.contract import validate_audit

    rows = _read_sidecar(path)
    _validate_sidecar_identity(
        path, rows, job=job, behavior_id=behavior_id,
        catalog_fingerprint=spec["run"]["catalog_fingerprint"],
        max_decisions=spec["run"]["budget"]["max_job_decisions"],
    )
    game = {
        "format": "prism-ppo-game-v1",
        "behavior_id": behavior_id,
        "job_id": job["job_id"],
        "actor": job["actor"],
        "game_id": replay.get("game_id", job["job_id"]),
        "catalog_fingerprint": spec["run"]["catalog_fingerprint"],
        "replay_sha256": digest(path.parent / "replay.json"),
        "sidecar_sha256": digest(path),
        "terminal": True,
        "result": result,
        "decisions": rows,
    }
    validate_audit(
        game,
        behavior_id=behavior_id,
        catalog_fingerprint=spec["run"]["catalog_fingerprint"],
        max_decisions=spec["run"]["budget"]["max_job_decisions"],
    )


def _verify_completion(
    run: Any,
    spec: Mapping[str, Any],
    attempt_number: int,
    row: Mapping[str, Any],
    job: Mapping[str, Any],
    *,
    expected_behavior: str,
    snapshot_cache: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    from training.prism_portable.engine.ppo.execution import verify_completion

    directory = ROOT / "campaigns/a/attempts" / f"{attempt_number:03d}"
    completion_path = directory / "completion.json"
    replay_path = directory / "replay.json"
    sidecar_path = directory / "sidecar.jsonl"
    completion = read_json(completion_path)
    _verify_snapshot_behavior(run, completion, expected_behavior, snapshot_cache)
    result = verify_completion(
        run.config,
        dict(job),
        attempt_number,
        completion_path,
        replay=replay_path,
        sidecar=sidecar_path,
        behavior_id=expected_behavior,
    )
    require(row.get("completion_sha256") == digest(completion_path),
            f"completion source SHA differs from launch ledger: {job['job_id']}")
    replay = read_json(replay_path)
    report = read_json(directory / "report.json")
    _verify_terminal_sidecar(
        sidecar_path, job=job, behavior_id=expected_behavior, spec=spec,
        result=result, replay=replay,
    )
    require(report["outcome"]["result"] == result, "verified terminal result drift")
    source_files = ("completion.json", "report.json", "replay.json", "sidecar.jsonl",
                    "arena-config.json", "process-result.json")
    hashes = {name: digest(directory / name) for name in source_files}
    return completion, replay, hashes


def _validate_with_run_helper(
    run_module: Any,
    spec: Mapping[str, Any],
    job: Mapping[str, Any],
    row: Mapping[str, Any],
    report: Mapping[str, Any],
    prefix: Mapping[str, Any],
    resources: Mapping[str, Any],
    *,
    sidecar_count: int,
    replay_exists: bool,
    behavior_id: str,
    sidecar_path: Path,
) -> None:
    helper = getattr(run_module, "validate_cap", None)
    require(callable(helper), "M79 run module lacks its pinned validate_cap helper")
    import inspect

    parameters = inspect.signature(helper).parameters
    positional = [
        name for name, parameter in parameters.items()
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    require(positional[:6] == ["spec", "job", "row", "report", "prefix", "resources"],
            "M79 validate_cap positional API drift")
    kwargs = {
        "sidecar_count": sidecar_count,
        "replay_exists": replay_exists,
        "behavior_id": behavior_id,
        "sidecar_path": sidecar_path,
    }
    accepted = {name: value for name, value in kwargs.items() if name in parameters}
    helper(spec, dict(job), dict(row), dict(report), dict(prefix), dict(resources), **accepted)


class _CampaignReadView:
    """Read-only subset consumed by the pinned M79 cap_files helper."""

    def __init__(self, root: Path, spec: Mapping[str, Any], head: str, ledger: Mapping[str, Any]):
        self.root = root
        self.spec = spec
        self.head = head
        self.ledger = ledger

    def _load(self) -> tuple[str, Mapping[str, Any]]:
        return self.head, self.ledger


def _verify_cap_attempt(
    spec: Mapping[str, Any],
    attempt_number: int,
    row: Mapping[str, Any],
    job: Mapping[str, Any],
    *,
    expected_behavior: str,
    run_module: Any,
    campaign_view: _CampaignReadView,
) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = ROOT / "campaigns/a/attempts" / f"{attempt_number:03d}"
    require(not (directory / "completion.json").exists(),
            "TRUNCATED attempt unexpectedly has terminal completion package")
    replay_path = directory / "replay.json"
    report_path = directory / "report.json"
    prefix_path = directory / "prefix.json"
    process_path = directory / "process-result.json"
    sidecar_path = directory / "sidecar.jsonl"
    report = read_json(report_path)
    prefix = read_json(prefix_path)
    resources = read_json(process_path)
    sidecar_rows = _read_sidecar(sidecar_path)
    _validate_with_run_helper(
        run_module, spec, job, row, report, prefix, resources,
        sidecar_count=len(sidecar_rows), replay_exists=replay_path.exists(),
        behavior_id=expected_behavior, sidecar_path=sidecar_path,
    )
    metrics = validate_cap(
        spec, job, row, report, prefix, resources,
        sidecar_count=len(sidecar_rows), replay_exists=replay_path.exists(),
        behavior_id=expected_behavior, sidecar_path=sidecar_path,
    )
    helper = getattr(run_module, "cap_files", None)
    require(callable(helper), "M79 run module lacks its pinned cap_files helper")
    hashes = {name: digest(directory / name) for name in
              ("report.json", "prefix.json", "sidecar.jsonl", "process-result.json", "arena-config.json")}
    helper_result = helper(campaign_view, attempt_number)
    require(isinstance(helper_result, Mapping)
            and helper_result.get("job") == job
            and helper_result.get("files") == hashes
            and helper_result.get("metrics") == metrics,
            "M79 cap_files evidence/source inventory mismatch")
    return metrics, hashes


def _assert_attempt_sources_unchanged(campaign: Path, sources: list[Mapping[str, Any]]) -> None:
    for source in sources:
        directory = campaign / "attempts" / f"{source['attempt']:03d}"
        for name, expected in source["files"].items():
            path = directory / name
            require(path.is_file() and digest(path) == expected,
                    f"M79 training source changed during audit: {path}")


def _verify_infra_attempt(attempt_number: int, row: Mapping[str, Any]) -> dict[str, str]:
    directory = ROOT / "campaigns/a/attempts" / f"{attempt_number:03d}"
    require(not (directory / "completion.json").exists(),
            "infrastructure abort has a terminal completion package")
    report_path = directory / "report.json"
    if report_path.exists():
        report = read_json(report_path)
        outcome = report.get("outcome")
        require(outcome is None or outcome.get("status") == "aborted",
                "infrastructure retry would discard a terminal or scientific cap")
        if outcome is not None:
            require(outcome.get("reason") in INFRA_REASONS,
                    "infrastructure attempt report contains a non-infrastructure abort")
    resources_path = directory / "process-result.json"
    resources = read_json(resources_path) if resources_path.exists() else row.get("resources", {})
    _validate_infra_row({**row, "resources": resources})
    return {
        name: digest(directory / name)
        for name in ("report.json", "prefix.json", "sidecar.jsonl", "process-result.json", "arena-config.json")
        if (directory / name).is_file()
    }


def _compare_json(expected: Any, actual: Any, *, atol: float, rtol: float, path: str = "$") -> list[float]:
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(expected) == set(actual), f"parity object fields differ at {path}")
        errors: list[float] = []
        for key in expected:
            errors.extend(_compare_json(expected[key], actual[key], atol=atol, rtol=rtol, path=f"{path}.{key}"))
        return errors
    if isinstance(expected, list):
        require(isinstance(actual, list) and len(expected) == len(actual), f"parity array lengths differ at {path}")
        errors = []
        for index, (left, right) in enumerate(zip(expected, actual)):
            errors.extend(_compare_json(left, right, atol=atol, rtol=rtol, path=f"{path}[{index}]"))
        return errors
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        require(type(expected) is type(actual) and expected == actual, f"parity scalar differs at {path}")
        return []
    if isinstance(expected, (int, float)):
        require(not isinstance(actual, bool) and isinstance(actual, (int, float)),
                f"parity number differs at {path}")
        require(math.isfinite(float(expected)) and math.isfinite(float(actual)),
                f"non-finite parity value at {path}")
        error = abs(float(expected) - float(actual))
        require(math.isclose(float(expected), float(actual), abs_tol=atol, rel_tol=rtol),
                f"Rust/Python numerical parity differs at {path}")
        return [error]
    raise ValueError(f"unsupported parity value at {path}")


def _parity(export: Path, spec: Mapping[str, Any], out: Path, bounds: Callable[[], Any]) -> dict[str, Any]:
    from training.prism_portable.engine.parity import predict_jsonl

    fixtures = ROOT / "inputs/fixtures.jsonl"
    binary = ROOT / "bin/splendor"
    require(fixtures.is_file() and binary.is_file(), "M79 parity fixtures or Rust executable are missing")
    raw = out / "parity-inputs.jsonl"
    rows = []
    for line in fixtures.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            rows.append(value.get("input", value))
    require(len(rows) == PARITY_INPUTS, "M79 Rust/Python parity requires all 68 frozen inputs")
    raw.write_text(
        "".join(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n" for value in rows),
        encoding="utf-8",
    )
    rust_path, python_path = out / "rust-parity.jsonl", out / "python-parity.jsonl"
    checked([binary, "prism-predict", "--weights", export, "--input", raw, "--output", rust_path],
            out / "rust-parity-command.json", bounds=bounds)
    predict_jsonl(export, raw, python_path,
                  expected_catalog_fingerprint=spec["run"]["catalog_fingerprint"])
    rust = [json.loads(line) for line in rust_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    python = [json.loads(line) for line in python_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(rust) == len(python) == PARITY_INPUTS, "M79 parity output row count mismatch")
    errors: list[float] = []
    for index, (expected, actual) in enumerate(zip(rust, python)):
        errors.extend(_compare_json(expected, actual, atol=1e-4, rtol=1e-4, path=f"row[{index}]"))
    receipt = {
        "status": "PASS",
        "rows": PARITY_INPUTS,
        "max_abs_error": max(errors, default=0.0),
        "atol": 1e-4,
        "rtol": 1e-4,
        "weights_sha256": digest(export),
        "fixtures_sha256": digest(fixtures),
        "rust_binary_sha256": digest(binary),
    }
    write_json(out / "parity.json", receipt)
    return receipt


def _write_training_report(
    out: Path,
    groups: Mapping[tuple[int, str, int], list[dict[str, Any]]],
    metrics_paths: Mapping[tuple[int, str, int], str],
    summary: Mapping[str, int],
) -> tuple[str, str]:
    opponents = sorted({key[1] for key in groups})
    table_rows = []
    for cycle in range(1, CYCLES + 1):
        for opponent in opponents:
            for actor in (0, 1):
                key = (cycle, opponent, actor)
                games = groups.get(key, [])
                if not games:
                    continue
                outcomes = Counter(item["record"] for item in games)
                score = math.fsum(item["candidate_score"] for item in games) / len(games)
                table_rows.append({
                    "cycle": cycle, "opponent": opponent, "learner_seat": actor,
                    "terminal_games": len(games), "wins": outcomes["win"],
                    "draws": outcomes["draw"], "losses": outcomes["loss"],
                    "half_point_score": score, "rust_metrics": metrics_paths[key],
                })
    lines = [
        "# M79 training behavior report\n\n",
        "M79 cycle behavior is training evidence. It is not an independent c20 competitive evaluation.\n\n",
        f"- Logical jobs: {summary['logical_attempts']}\n",
        f"- Physical attempts: {summary['physical_attempts']}\n",
        f"- Terminal training games: {summary['terminal_games']}\n",
        f"- Retained scientific caps: {summary['truncated_games']}\n",
        f"- Infrastructure abort attempts: {summary['infra_abort_attempts']}\n",
        "- Retained caps are excluded from terminal W/D/L and PPO batches.\n\n",
        "| Cycle | Opponent | Learner seat | Terminal games | W-D-L | Half-point score | Rust metrics |\n",
        "| ---: | --- | ---: | ---: | ---: | ---: | --- |\n",
    ]
    for row in table_rows:
        lines.append(
            f"| {row['cycle']} | {row['opponent']} | {row['learner_seat']} | {row['terminal_games']} "
            f"| {row['wins']}-{row['draws']}-{row['losses']} | {row['half_point_score']:.6f} "
            f"| {row['rust_metrics']} |\n"
        )
    markdown_path = out / "training-report.md"
    markdown_path.write_text("".join(lines), encoding="utf-8")
    html_rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row[key]))}</td>" for key in
                         ("cycle", "opponent", "learner_seat", "terminal_games", "wins", "draws", "losses"))
        + f"<td>{row['half_point_score']:.6f}</td><td><code>{html.escape(row['rust_metrics'])}</code></td></tr>"
        for row in table_rows
    )
    html_path = out / "training-report.html"
    html_path.write_text(
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<title>M79 training behavior report</title><h1>M79 training behavior report</h1>"
        "<p>M79 cycle behavior is training evidence, not an independent c20 evaluation.</p>"
        f"<p>Logical jobs: {summary['logical_attempts']}; physical attempts: {summary['physical_attempts']}; "
        f"terminal games: {summary['terminal_games']}; retained caps: {summary['truncated_games']}; "
        f"infrastructure aborts: {summary['infra_abort_attempts']}.</p>"
        "<table><thead><tr><th>Cycle</th><th>Opponent</th><th>Learner seat</th><th>Terminal games</th>"
        "<th>Wins</th><th>Draws</th><th>Losses</th><th>Half-point score</th><th>Rust metrics</th></tr></thead>"
        f"<tbody>{html_rows}</tbody></table></html>\n",
        encoding="utf-8",
    )
    return digest(markdown_path), digest(html_path)


def _head_sha(path: Path) -> str:
    require(path.is_file(), f"missing immutable commit pointer: {path}")
    return digest(path)


def _assert_commit_state_unchanged(
    run: Any,
    campaign: Path,
    run_head_sha: str,
    ledger_head_sha: str,
    before_state_sha: str,
) -> None:
    from training.prism_portable.protocol import state_digest
    from training.prism_portable.engine.ppo.coordinator import Run

    require(_head_sha(campaign / "run/HEAD.json") == run_head_sha,
            "M79 audit changed the committed run HEAD")
    require(_head_sha(campaign / "launch-ledger/HEAD.json") == ledger_head_sha,
            "M79 audit changed the physical ledger HEAD")
    require(state_digest(run.state) == before_state_sha,
            "M79 audit changed the in-memory committed run state")
    after = Run.open(campaign / "run")
    require(state_digest(after.state) == before_state_sha,
            "M79 audit changed exact committed run state")


def audit() -> dict[str, Any]:
    """Audit campaigns/a and write audits/a/audit.json without resuming the run."""
    plan, execution, bounds, run_module = _run_api()
    execution_path = ROOT / "execution.json"
    plan_path = ROOT / "benchmarks/m79-prism-mainline.execution-plan.json"
    execution_sha = digest(execution_path)
    plan_sha = digest(plan_path)
    auditor_sha = digest(__file__)
    pinned_sources = _execution_sources(execution)
    campaign = ROOT / "campaigns/a"
    output = ROOT / "audits/a"
    require(campaign.is_dir(), "M79 campaign directory is missing")
    output.mkdir(parents=True, exist_ok=False)
    protected_m75 = _protected_m75_bytes(plan)

    contract_path = campaign / "contract.json"
    contract_sha = digest(contract_path)
    spec = read_json(contract_path)
    _verify_training_plan(plan, spec)
    from training.prism_portable.engine.ppo.execution import check_assets, validate_spec
    from scripts.prism_m67_storage import install as install_storage_adapter
    install_storage_adapter()
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.engine.export import load_weights
    from training.prism_portable.protocol import state_digest

    validate_spec(spec)
    check_assets(spec)
    require(spec["run"]["run_id"] == "m79-a"
            and spec["run"]["seed"] == plan["training"]["run_seed"]
            and spec["run"]["parent_sha256"] == plan["assets"]["parent"]["sha256"],
            "M79 run identity or exact M75 parent differs from frozen plan")
    run = Run.open(campaign / "run")
    require(run.config == spec["run"], "campaign run/config identity mismatch")
    state = run.state
    run_state_sha = state_digest(state)
    run_head_sha = _head_sha(campaign / "run/HEAD.json")
    ledger_head_sha = _head_sha(campaign / "launch-ledger/HEAD.json")
    ledger_store = CommitStore(campaign / "launch-ledger", run.config["arena_contract_sha256"])
    ledger_head, ledger = ledger_store.load()
    summary = validate_ledger(ledger, state, spec)

    worker_completion_path = campaign / "worker-completion.json"
    worker_completion_sha = digest(worker_completion_path)
    worker_completion = read_json(worker_completion_path)
    require(worker_completion.get("status", worker_completion.get("state")) == "STOPPED_COMMITTED",
            "worker completion is not STOPPED_COMMITTED")
    require(worker_completion.get("cycle") == CYCLES
            and worker_completion.get("logical_attempts") == LOGICAL_ATTEMPTS
            and worker_completion.get("physical_attempts") == state["attempts"]
            and worker_completion.get("games") == summary["terminal_games"]
            and worker_completion.get("truncated_games") == summary["truncated_games"]
            and worker_completion.get("global_step") == state["global_step"]
            and worker_completion.get("update_attempts") == state["update_attempts"],
            "worker completion counters disagree with committed state/ledger")
    require(worker_completion.get("execution_sha256") == execution_sha,
            "worker completion execution SHA mismatch")

    export = Path(worker_completion.get("weights", ""))
    if not export.is_absolute():
        export = ROOT / export
    export = export.resolve()
    expected_export = (campaign / f"cycle-{CYCLES}-export/weights.json").resolve()
    require(export == expected_export and export.is_file(),
            "worker did not export fixed M79 cycle-20 weights")
    weight_sha = digest(export)
    require(_is_sha(worker_completion.get("weights_sha256"))
            and worker_completion["weights_sha256"] == weight_sha,
            "worker completion weights SHA mismatch")

    initialization_path = campaign / "initialization-verification.json"
    initialization_sha = digest(initialization_path)
    initialization = read_json(initialization_path)
    parent_sha = spec["run"]["parent_sha256"]
    require(initialization.get("status") == "PASS"
            and initialization.get("exact_parent_tensors") == TENSOR_COUNT
            and initialization.get("optimizer_slots") == 0
            and initialization.get("parent_sha256") == parent_sha
            and initialization.get("run_seed") == plan["training"]["run_seed"],
            "fresh M79 initialization receipt mismatch")
    require(_is_sha(initialization.get("torch_rng_sha256")), "fresh RNG receipt is missing")

    model = load_weights(export, expected_catalog_fingerprint=run.config["catalog_fingerprint"])
    require(len(model.state_dict()) == TENSOR_COUNT, "cycle-20 export tensor count is not 32")
    require(len(state["optimizer"]["state"]) == TENSOR_COUNT,
            "committed AdamW optimizer does not contain 32 parameter slots")
    require(set(state["model"]) == {"policy." + key for key in model.state_dict()},
            "committed model tensor inventory is not the exact 32-tensor policy")
    torch = importlib.import_module("torch")
    for key, tensor in model.state_dict().items():
        state_key = "policy." + key
        require(state_key in state["model"] and torch.equal(tensor, state["model"][state_key]),
                f"cycle-20 export tensor differs from committed run: {key}")
    parent_path = Path(spec["parent_weights"])
    require(parent_path.is_file() and digest(parent_path) == parent_sha,
            "exact M75 parent weight SHA mismatch")
    parent = load_weights(parent_path, expected_catalog_fingerprint=run.config["catalog_fingerprint"])
    changed = any(not torch.equal(tensor, parent.state_dict()[key])
                  for key, tensor in model.state_dict().items())
    require(changed, "M79 c20 export is bytewise unchanged from its parent tensors")
    del parent, model

    binding_hashes = {
        f"cycle-{cycle}-batch-binding.json": digest(
            campaign / f"cycle-{cycle}-batch-binding.json")
        for cycle in range(1, CYCLES + 1)
    }
    behavior_by_cycle = _cycle_behavior_map(
        run, state, summary["jobs_by_cycle"], summary, campaign,
    )
    require(set(behavior_by_cycle) == set(range(1, CYCLES + 1)),
            "M79 cycle behavior map is incomplete")
    parity = _parity(export, spec, output, bounds)
    write_json(output / "checkpoint.json", {
        "status": "PASS",
        "cycle": CYCLES,
        "logical_attempts": LOGICAL_ATTEMPTS,
        "physical_attempts": summary["physical_attempts"],
        "terminal_games": summary["terminal_games"],
        "truncated_games": summary["truncated_games"],
        "infra_abort_attempts": summary["infra_abort_attempts"],
        "global_step": state["global_step"],
        "update_attempts": state["update_attempts"],
        "optimizer_slots": TENSOR_COUNT,
        "exact_export_tensors": TENSOR_COUNT,
        "changed_from_parent": changed,
        "weights_sha256": weight_sha,
        "run_identity": run.identity,
        "run_commit": run.parent,
        "ledger_commit": ledger_head,
        "initialization": initialization,
    })

    source_records: list[dict[str, Any]] = []
    groups: dict[tuple[int, str, int], list[dict[str, Any]]] = defaultdict(list)
    all_attempts = ledger["attempts"]
    cycle_by_job = _cycle_for_jobs(summary["jobs_by_cycle"])
    valid_by_number = {
        number: (job_id, row)
        for job_id, (number, row) in summary["attempt_by_job"].items()
    }
    cycle_behavior_cache: dict[str, str] = {}
    campaign_view = _CampaignReadView(campaign, spec, ledger_head, ledger)

    for raw_number, row in sorted(all_attempts.items(), key=lambda pair: int(pair[0])):
        number = int(raw_number)
        job = row["job"]
        job_id = job["job_id"]
        cycle = cycle_by_job[job_id]
        status = row["status"]
        directory = campaign / "attempts" / f"{number:03d}"
        if status == "INFRA_ABORT":
            hashes = _verify_infra_attempt(number, row)
            source_records.append({
                "attempt": number, "cycle": cycle, "job": job, "status": status, "files": hashes,
            })
            continue

        expected_behavior = behavior_by_cycle[cycle]
        if status == "COMPLETE":
            completion, replay, hashes = _verify_completion(
                run, spec, number, row, job,
                expected_behavior=expected_behavior,
                snapshot_cache=cycle_behavior_cache,
            )
            result = read_json(directory / "report.json")["outcome"]["result"]
            actor = job["actor"]
            score = .5 if result["ranks"][0] == result["ranks"][1] else float(
                result["ranks"][actor] < result["ranks"][1 - actor])
            actions = [Counter(), Counter()]
            for step in replay["steps"]:
                actions[step["actor"]][step["action"]["type"]] += 1
            groups[(cycle, job["opponent_id"], actor)].append({
                "candidate": f"train-m79-a-c{cycle}",
                "opponent": job["opponent_id"],
                "seed": job["environment_seed"],
                "candidate_seat": actor,
                "candidate_score": score,
                "record": "win" if score == 1 else "draw" if score == .5 else "loss",
                "candidate_points": result["scores"][actor],
                "opponent_points": result["scores"][1 - actor],
                "plies": len(replay["steps"]),
                "_candidate_actions": actions[actor],
                "_opponent_actions": actions[1 - actor],
                "_wall_seconds": completion.get("resources", {}).get("wall_seconds"),
                "_replay_path": str(directory / "replay.json"),
            })
            source_records.append({
                "attempt": number, "cycle": cycle, "job": job, "status": status,
                "behavior_id": completion["behavior_id"], "files": hashes,
            })
        else:
            cap_metrics, hashes = _verify_cap_attempt(
                spec, number, row, job,
                expected_behavior=expected_behavior,
                run_module=run_module,
                campaign_view=campaign_view,
            )
            source_records.append({
                "attempt": number, "cycle": cycle, "job": job, "status": status,
                "cap_metrics": cap_metrics, "files": hashes,
            })

    require(set(valid_by_number) == {
        int(number) for number, row in all_attempts.items()
        if row["status"] in ("COMPLETE", "TRUNCATED")
    }, "resolved attempt inventory differs from logical ledger")
    require(sum(len(group) for group in groups.values()) == summary["terminal_games"],
            "terminal source inventory differs from training ledger")
    write_json(output / "training-sources.json", source_records)

    binary = ROOT / "bin/s4_batch_metrics"
    require(binary.is_file(), "pinned Rust s4_batch_metrics executable is missing")
    metrics_paths: dict[tuple[int, str, int], str] = {}
    for index, (key, items) in enumerate(sorted(groups.items())):
        manifest = output / f"group-{index:03d}.json"
        target = output / f"group-{index:03d}.metrics.json"
        receipt = output / f"group-{index:03d}.receipt.json"
        write_json(manifest, {"rows": [{"replay_path": item["_replay_path"]} for item in items]})
        checked([binary, manifest, target], receipt, timeout=600, bounds=bounds)
        metrics_paths[key] = target.relative_to(output).as_posix()
    write_json(output / "training-summary.json", [
        {
            "cycle": key[0],
            "opponent": key[1],
            "learner_seat": key[2],
            "terminal_games": len(items),
            "wins": sum(item["record"] == "win" for item in items),
            "draws": sum(item["record"] == "draw" for item in items),
            "losses": sum(item["record"] == "loss" for item in items),
            "half_point_score": math.fsum(item["candidate_score"] for item in items) / len(items),
            "rust_metrics": metrics_paths[key],
            "rust_metrics_sha256": digest(output / metrics_paths[key]),
        }
        for key, items in sorted(groups.items())
    ])
    report_hashes = _write_training_report(output, groups, metrics_paths, summary)

    _assert_attempt_sources_unchanged(campaign, source_records)
    require(all(digest(campaign / name) == expected
                for name, expected in binding_hashes.items()),
            "M79 cycle batch binding changed during audit")
    _assert_commit_state_unchanged(
        run, campaign, run_head_sha, ledger_head_sha, run_state_sha,
    )
    _assert_source_pins(pinned_sources)
    _assert_protected_m75_bytes(protected_m75)
    require(digest(execution_path) == execution_sha
            and digest(plan_path) == plan_sha
            and digest(contract_path) == contract_sha
            and digest(worker_completion_path) == worker_completion_sha
            and digest(initialization_path) == initialization_sha
            and digest(export) == weight_sha
            and digest(__file__) == auditor_sha,
            "M79 execution plan/source changed during audit")
    result = {
        "status": "PASS_TRAINING_ARTIFACT_AUDIT",
        "round": "M79",
        "weights_sha256": weight_sha,
        "logical_attempts": summary["logical_attempts"],
        "physical_attempts": summary["physical_attempts"],
        "completed_games": summary["terminal_games"],
        "truncated_games": summary["truncated_games"],
        "infra_abort_attempts": summary["infra_abort_attempts"],
        "checkpoint_sha256": digest(output / "checkpoint.json"),
        "parity_sha256": digest(output / "parity.json"),
        "training_sources_sha256": digest(output / "training-sources.json"),
        "launch_ledger_head_sha256": ledger_head_sha,
        "batch_binding_sha256": binding_hashes,
        "contract_sha256": contract_sha,
        "worker_completion_sha256": worker_completion_sha,
        "initialization_sha256": initialization_sha,
        "run_commit": run.parent,
        "ledger_commit": ledger_head,
        "new_games": 0,
        "new_optimizer_updates": 0,
        "automatic_retries": 0,
        "rust_terminal_replay_validation":
            f"all {summary['terminal_games']} terminal replays via pinned s4_batch_metrics",
        "training_report_markdown_sha256": report_hashes[0],
        "training_report_html_sha256": report_hashes[1],
        "protected_m75_bytes": protected_m75,
        "pinned_execution_sources": pinned_sources,
    }
    write_json(output / "audit.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
