"""Read-only final training audit for the two M81 c20 campaigns."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = Path("benchmarks/m81-anchor-coverage.execution-plan.json")
ARMS = ("A", "B")
POLICY_TENSORS = 32
STYLE_TENSORS = {
    "style_head.0.weight",
    "style_head.0.bias",
    "style_head.2.weight",
    "style_head.2.bias",
}
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
        value: dict[str, Any] = {}
        for key, item in pairs:
            require(key not in value, f"duplicate JSON key: {key}")
            value[key] = item
        return value

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
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return repr(value)
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return repr(value)


def _validate_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    require(plan.get("round") == "M81", "wrong round plan")
    training = plan.get("training")
    resources = plan.get("resources")
    recovery = plan.get("recovery")
    require(isinstance(training, Mapping), "plan training section is missing")
    require(isinstance(resources, Mapping), "plan resources section is missing")
    require(isinstance(recovery, Mapping), "plan recovery section is missing")
    arms = training.get("arms")
    require(isinstance(arms, Mapping) and set(arms) == set(ARMS),
            "plan must define exactly arms A and B")
    cycles = training.get("cycles")
    blocks = training.get("seed_blocks_per_cycle")
    seats = training.get("seats")
    planned = training.get("games_per_arm")
    require(type(cycles) is int and cycles > 0, "invalid planned cycle count")
    require(type(blocks) is int and blocks > 0, "invalid seed blocks per cycle")
    require(seats == [0, 1], "M81 training must schedule both seats")
    require(type(planned) is int and planned == cycles * blocks * len(seats),
            "plan logical game count disagrees with its cycle grid")
    require(cycles == 20 and blocks == 128 and seats == [0, 1]
            and planned == 5120 and training.get("games_per_arm") == 5120,
            "M81 final audit requires exactly 20 cycles and 5120 paired logical jobs per arm")
    require(type(training.get("run_seed")) is int, "plan run seed is missing")
    ppo = training.get("ppo")
    require(isinstance(ppo, Mapping) and ppo.get("style_beta") == 0
            and ppo.get("style_value_weight") == 0,
            "M81 training must keep the four-tensor style head frozen")
    seed_range = training.get("environment_seed_range")
    require(isinstance(seed_range, list) and len(seed_range) == 2
            and all(type(item) is int for item in seed_range),
            "plan environment seed range is malformed")
    require(seed_range[1] - seed_range[0] + 1 == cycles * blocks,
            "plan seed range does not cover its cycle grid")
    for arm in ARMS:
        period = arms[arm].get("opponent_period")
        require(isinstance(period, list) and period and all(
            isinstance(opponent, str) and opponent for opponent in period),
            f"arm {arm} has an invalid opponent period")
        require(len(period) == 16,
                f"arm {arm} must use the frozen 16-slot opponent period")
        assets = plan.get("assets")
        require(isinstance(assets, Mapping) and set(period).issubset(assets),
                f"arm {arm} opponent period references an undeclared plan asset")
    require(resources.get("deadline_mode") == "resource_bounded_no_calendar_stop"
            and resources.get("absolute_stop") is None
            and resources.get("round_elapsed_wall_stop") is None
            and resources.get("eta_is_stop_condition") is False,
            "M81 plan contains a calendar or elapsed-wall stop")
    require(resources.get("engineering_new_games") == 0,
            "audit contract must remain zero-game")
    extra = resources.get("extra_infrastructure_attempts")
    require(type(extra) is int and extra >= 0
            and recovery.get("whole_round_extra_attempts") == extra,
            "plan infrastructure-attempt bounds disagree")
    per_job = recovery.get("infrastructure_retries_per_unfinished_job")
    require(type(per_job) is int and per_job >= 0,
            "plan per-job infrastructure retry bound is invalid")
    cap_limit = training.get("max_scientific_truncations_per_arm")
    require(type(cap_limit) is int and 0 <= cap_limit <= 8,
            "plan retained-cap limit exceeds the strict eight-cap ceiling")
    require(extra % len(ARMS) == 0,
            "plan infrastructure-attempt budget cannot be split evenly across arms")
    require(training.get("exports") == [5, 10, 15, 20],
            "M81 checkpoint inventory must be fixed at c5/c10/c15/c20")
    return {
        "training": training,
        "resources": resources,
        "recovery": recovery,
        "cycles": cycles,
        "blocks": blocks,
        "seats": seats,
        "logical_attempts": planned,
        "infra_total": extra,
        "infra_per_arm": extra // len(ARMS),
        "infra_per_job": per_job,
        "cap_limit": cap_limit,
    }


def _expected_cycles(plan: Mapping[str, Any], arm: str) -> list[list[dict[str, Any]]]:
    facts = _validate_plan(plan)
    require(arm in ARMS, f"unknown M81 arm: {arm}")
    training = facts["training"]
    seed_start = training["environment_seed_range"][0]
    period = training["arms"][arm]["opponent_period"]
    cycles: list[list[dict[str, Any]]] = []
    for cycle_index in range(facts["cycles"]):
        cycle: list[dict[str, Any]] = []
        for block in range(facts["blocks"]):
            seed = seed_start + facts["blocks"] * cycle_index + block
            opponent = period[block % len(period)]
            for actor in facts["seats"]:
                cycle.append({
                    "actor": actor,
                    "opponent_id": opponent,
                    "environment_seed": seed,
                })
        cycles.append(cycle)
    return cycles


def _validate_campaign_contract(
    plan: Mapping[str, Any], arm: str, spec: Mapping[str, Any]
) -> list[list[dict[str, Any]]]:
    facts = _validate_plan(plan)
    expected = _expected_cycles(plan, arm)
    training = facts["training"]
    require(spec.get("format") == "prism-ppo-arena-v1",
            "unknown portable Arena campaign format")
    run = spec.get("run")
    require(isinstance(run, Mapping), "campaign run config is missing")
    require(run.get("seed") == training["run_seed"],
            "campaign initialization seed differs from the frozen plan")
    require(run.get("run_id") == f"m81-{arm}",
            "campaign run identity differs from its frozen arm")
    parent = plan.get("assets", {}).get(training["parent"], {})
    require(isinstance(parent, Mapping) and _is_sha(parent.get("sha256")),
            "frozen parent identity is missing from the plan")
    require(run.get("parent_sha256") == parent["sha256"],
            "campaign parent differs from the frozen M81 parent")
    require(run.get("ppo") == training.get("ppo"),
            "campaign PPO settings differ from the frozen plan")
    require(run.get("budget", {}).get("max_run_seconds") is None,
            "campaign inherited a calendar or elapsed-wall stop")
    require(spec.get("limits", {}).get("max_plies") == training.get("ply_cap"),
            "campaign game cap differs from the frozen plan")
    opponents = spec.get("opponents")
    require(isinstance(opponents, Mapping)
            and set(opponents) == set(training["arms"][arm]["opponent_period"]),
            "campaign opponent pool differs from the frozen plan")
    for name, descriptor in opponents.items():
        planned_asset = plan["assets"][name]
        require(isinstance(descriptor, Mapping), f"opponent descriptor is malformed: {name}")
        if name == "heuristic":
            require(descriptor.get("sha256") == planned_asset.get("engine_sha256")
                    and descriptor.get("args") == planned_asset.get("command")
                    and descriptor.get("hello") == {
                        "agent_name": "splendor-cli-heuristic-v02",
                        "agent_version": "0.2.9",
                    },
                    "heuristic descriptor differs from the frozen plan")
        else:
            expected_weight_sha = planned_asset.get("sha256")
            file_hashes = descriptor.get("files")
            require(_is_sha(expected_weight_sha) and isinstance(file_hashes, Mapping)
                    and list(file_hashes.values()) == [expected_weight_sha],
                    f"opponent {name} does not bind its exact planned weight")
    require(len(spec.get("cycles", [])) == facts["cycles"],
            "campaign cycle count differs from the frozen plan")
    job_ids: set[str] = set()
    for cycle_index, (actual_cycle, expected_cycle) in enumerate(
        zip(spec["cycles"], expected), start=1
    ):
        require(isinstance(actual_cycle, list) and len(actual_cycle) == len(expected_cycle),
                f"campaign cycle {cycle_index} has the wrong logical job count")
        seen_blocks: dict[tuple[str, int], list[int]] = defaultdict(list)
        for index, (job, planned_job) in enumerate(zip(actual_cycle, expected_cycle)):
            require(isinstance(job, Mapping)
                    and set(job) == {"job_id", "actor", "opponent_id", "environment_seed"},
                    f"campaign cycle {cycle_index} job {index} schema drift")
            job_id = job.get("job_id")
            require(isinstance(job_id, str) and job_id and job_id not in job_ids,
                    "campaign has missing or duplicate logical job IDs")
            block, seat = divmod(index, len(facts["seats"]))
            expected_job_id = f"m81-{arm}-c{cycle_index}-b{block}-s{seat}"
            require(job_id == expected_job_id,
                    f"campaign job ID differs from the M81 grid: {expected_job_id}")
            job_ids.add(job_id)
            for key, wanted in planned_job.items():
                require(job.get(key) == wanted,
                        f"campaign cycle {cycle_index} {key} differs from the frozen schedule")
            require(job["opponent_id"] in spec.get("opponents", {}),
                    f"campaign lacks the scheduled opponent {job['opponent_id']}")
            seen_blocks[(job["opponent_id"], job["environment_seed"])].append(job["actor"])
        require(all(sorted(actors) == [0, 1] for actors in seen_blocks.values()),
                f"campaign cycle {cycle_index} does not contain exact paired seats")
    return spec["cycles"]


def validate_ledger(
    ledger: Mapping[str, Any],
    state: Mapping[str, Any],
    spec: Mapping[str, Any],
    plan: Mapping[str, Any],
    arm: str,
) -> dict[str, Any]:
    """Resolve each planned M81 job once and charge infrastructure attempts separately."""
    facts = _validate_plan(plan)
    cycles = _validate_campaign_contract(plan, arm, spec)
    jobs = [job for cycle in cycles for job in cycle]
    jobs_by_id = {job["job_id"]: job for job in jobs}
    expected_ids = [job["job_id"] for job in jobs]
    attempts = ledger.get("attempts")
    require(ledger.get("format") == "prism-ppo-launch-ledger-v1",
            "unknown portable launch-ledger format")
    require(ledger.get("failed") is False, "campaign ledger retains a fatal failure")
    require(isinstance(attempts, Mapping) and attempts,
            "zero-game campaign cannot pass final training audit")
    require(type(state.get("attempts")) is int and state["attempts"] == len(attempts),
            "committed physical-attempt count disagrees with the ledger")
    budget = spec["run"].get("budget", {})
    limits = spec.get("limits", {})
    logical = facts["logical_attempts"]
    infra_per_arm = facts["infra_per_arm"]
    require(budget.get("max_jobs") == logical,
            "campaign logical-job budget differs from the frozen plan")
    require(budget.get("max_cycles") == facts["cycles"],
            "campaign cycle budget differs from the frozen plan")
    require(budget.get("max_attempts") == logical + infra_per_arm,
            "campaign physical-attempt budget differs from the frozen plan")
    require(limits.get("max_infra_retries") == infra_per_arm,
            "campaign infrastructure retry limit differs from the frozen plan")
    max_decisions = budget.get("max_job_decisions")
    require(type(max_decisions) is int and max_decisions > 0,
            "campaign per-job decision cap is missing")
    require(max_decisions == plan["training"]["ply_cap"]
            and budget.get("max_decisions") == facts["resources"]["max_decisions_per_arm"]
            and budget.get("max_update_attempts") == facts["resources"]["max_update_attempts_per_arm"]
            and budget.get("max_optimizer_steps") == facts["resources"]["max_update_attempts_per_arm"]
            and budget.get("max_storage_bytes") == facts["resources"]["per_arm_storage_bytes"],
            "campaign decision, optimizer, or storage budget differs from the frozen plan")
    require(limits.get("max_physical_decisions") == (logical + infra_per_arm) * max_decisions,
            "campaign physical-decision ceiling differs from its retry reservation")
    require(limits.get("campaign_cpu_seconds") == facts["resources"]["training_cpu_seconds_per_arm"]
            and limits.get("game_cpu_seconds") == facts["resources"]["game_cpu_seconds"]
            and limits.get("game_wall_seconds") == facts["resources"]["game_wall_seconds"]
            and limits.get("handshake_timeout_ms") == facts["resources"]["handshake_timeout_ms"]
            and limits.get("move_timeout_ms") == facts["resources"]["move_timeout_ms"],
            "campaign process limits differ from the frozen resource plan")

    rows_by_job: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    valid_by_job: dict[str, tuple[int, Mapping[str, Any]]] = {}
    physical_ids: list[int] = []
    counts: Counter[str] = Counter()
    charged_decisions = 0
    for raw_number, row in attempts.items():
        require(isinstance(raw_number, str) and raw_number.isdecimal()
                and str(int(raw_number)) == raw_number and int(raw_number) > 0,
                "physical attempt IDs must be canonical positive integers")
        number = int(raw_number)
        require(number not in physical_ids, "duplicate physical attempt ID")
        physical_ids.append(number)
        require(isinstance(row, Mapping), "physical attempt row is malformed")
        job = row.get("job")
        require(isinstance(job, Mapping) and isinstance(job.get("job_id"), str),
                "physical attempt has no logical job identity")
        job_id = job["job_id"]
        require(job_id in jobs_by_id and dict(job) == jobs_by_id[job_id],
                f"physical attempt differs from the frozen schedule: {job_id}")
        status = row.get("status")
        require(status in {"COMPLETE", "TRUNCATED", "INFRA_ABORT"},
                f"unresolved or fatal physical attempt: {status}")
        retry = row.get("retry_charged")
        require(type(retry) is bool and retry is (status == "INFRA_ABORT"),
                "retry charge does not match the attempt status")
        decisions = row.get("charged_decisions")
        require(type(decisions) is int and 0 <= decisions <= max_decisions,
                "physical decision charge is missing or exceeds the per-job cap")
        charged_decisions += decisions
        counts[status] += 1
        if status == "INFRA_ABORT":
            outcome = row.get("outcome")
            resources = row.get("resources")
            infra_reasons = {"handshake_timeout", "action_timeout", "agent_eof", "agent_io"}
            recognized = row.get("reason") == "interrupted_unpublished"
            recognized |= isinstance(resources, Mapping) and resources.get("stop_reason") == "spawn_infrastructure"
            recognized |= (isinstance(outcome, Mapping) and outcome.get("status") == "aborted"
                           and outcome.get("reason") in infra_reasons)
            require(recognized, "infrastructure retry lacks a recognized infrastructure cause")
        elif status == "COMPLETE":
            require(_is_sha(row.get("completion_sha256")),
                    f"terminal attempt lacks a completion SHA: {job_id}")
        else:
            require(isinstance(row.get("outcome"), Mapping)
                    and row["outcome"].get("status") == "truncated",
                    f"retained cap lacks a scientific truncation outcome: {job_id}")
        rows_by_job[job_id].append((number, row))

    require(sorted(physical_ids) == list(range(1, len(attempts) + 1)),
            "physical attempt ledger has a numbering gap")
    infra_count = counts["INFRA_ABORT"]
    cap_count = counts["TRUNCATED"]
    terminal_count = counts["COMPLETE"]
    require(infra_count <= infra_per_arm,
            "campaign exceeded its plan-bound infrastructure retry budget")
    require(cap_count <= facts["cap_limit"],
            "campaign exceeded its retained scientific-cap limit")
    require(len(attempts) == logical + infra_count,
            "physical attempts do not equal logical jobs plus infrastructure retries")
    require(terminal_count + cap_count == logical,
            "terminal and retained-cap attempts do not resolve every logical job")
    require(type(ledger.get("retries")) is int and ledger["retries"] == infra_count,
            "ledger retry total disagrees with infrastructure attempts")
    require(type(ledger.get("physical_decisions")) is int
            and ledger["physical_decisions"] == charged_decisions,
            "ledger physical-decision total is incorrect")
    max_physical_decisions = limits.get("max_physical_decisions")
    if max_physical_decisions is not None:
        require(type(max_physical_decisions) is int
                and charged_decisions <= max_physical_decisions,
                "campaign exceeded its physical decision budget")

    for job_id in expected_ids:
        rows = rows_by_job.get(job_id, [])
        valid = [(number, row) for number, row in rows
                 if row["status"] in {"COMPLETE", "TRUNCATED"}]
        infrastructure = [(number, row) for number, row in rows
                          if row["status"] == "INFRA_ABORT"]
        require(len(valid) == 1, f"logical job must resolve exactly once: {job_id}")
        require(len(infrastructure) <= facts["infra_per_job"],
                f"logical job exceeded its infrastructure retry allowance: {job_id}")
        if infrastructure:
            require(infrastructure[0][0] < valid[0][0],
                    f"infrastructure attempt occurred after resolution: {job_id}")
        valid_by_job[job_id] = valid[0]

    require(state.get("phase") == "COMMITTED"
            and state.get("cycle") == facts["cycles"]
            and state.get("paused") is False,
            "run state is not a completed, unpaused final cycle")
    committed_decisions = sum(
        row["charged_decisions"] for _, row in valid_by_job.values()
        if row["status"] == "COMPLETE"
    )
    require(type(state.get("decisions")) is int
            and state["decisions"] == committed_decisions,
            "committed learner-decision total differs from terminal attempt charges")
    require(type(state.get("cursor")) is int and state["cursor"] == 0
            and state.get("order") == [] and _is_sha(state.get("snapshot"))
            and _is_sha(state.get("batch")),
            "final update cursor or snapshot/batch binding is incomplete")
    require(isinstance(state.get("consumed"), list)
            and len(state["consumed"]) == facts["cycles"]
            and len(set(state["consumed"])) == facts["cycles"]
            and all(_is_sha(item) for item in state["consumed"]),
            "cycle batches are missing or consumed more than once")
    require(state.get("all_jobs") == expected_ids,
            "committed logical job order differs from the frozen schedule")
    require(state.get("schedule") == cycles[-1],
            "committed final-cycle schedule differs from the frozen plan")
    require(type(state.get("global_step")) is int and state["global_step"] > 0,
            "no optimizer update was committed")
    require(type(state.get("update_attempts")) is int
            and state["update_attempts"] >= state["global_step"]
            and state["update_attempts"] <= facts["resources"].get("max_update_attempts_per_arm", math.inf),
            "optimizer update-attempt counters are invalid")
    jobs_state = state.get("jobs")
    final_jobs = {job["job_id"]: job for job in cycles[-1]}
    require(isinstance(jobs_state, Mapping) and set(jobs_state) == set(final_jobs),
            "committed final-cycle job map differs from the schedule")
    for job_id in final_jobs:
        number, row = valid_by_job[job_id]
        committed = jobs_state[job_id]
        require(isinstance(committed, Mapping)
                and committed.get("status") == row["status"]
                and committed.get("attempt") == number,
                f"committed final-cycle job disagrees with ledger: {job_id}")

    return {
        "logical_attempts": logical,
        "physical_attempts": len(attempts),
        "terminal_games": terminal_count,
        "truncated_games": cap_count,
        "infra_abort_attempts": infra_count,
        "resolved_logical_jobs": len(valid_by_job),
        "physical_decisions": charged_decisions,
        "attempt_by_job": valid_by_job,
        "physical_attempts_by_number": {
            int(number): row for number, row in attempts.items()
        },
        "jobs_by_cycle": cycles,
    }


def _validate_committed_tensor_inventory(
    committed: Mapping[str, Any], exported_policy: Mapping[str, Any], torch: Any
) -> dict[str, int]:
    require(isinstance(committed, Mapping) and isinstance(exported_policy, Mapping),
            "checkpoint tensor inventory is malformed")
    require(len(exported_policy) == POLICY_TENSORS,
            "final export does not contain exactly 32 policy tensors")
    policy_keys = {"policy." + key for key in exported_policy}
    style_keys = {"policy." + key for key in exported_policy
                  if key.startswith("style_head.")}
    require(not style_keys, "policy export unexpectedly contains style-head tensors")
    expected_keys = policy_keys | STYLE_TENSORS
    require(set(committed) == expected_keys,
            "committed checkpoint must contain exactly 32 policy and 4 style-head tensors")
    for key, tensor in exported_policy.items():
        stored = committed["policy." + key]
        require(isinstance(tensor, torch.Tensor) and isinstance(stored, torch.Tensor)
                and tensor.shape == stored.shape and torch.equal(tensor, stored),
                f"exported policy tensor differs from the committed checkpoint: {key}")
    for key in STYLE_TENSORS:
        tensor = committed[key]
        require(isinstance(tensor, torch.Tensor) and tensor.is_floating_point()
                and torch.isfinite(tensor).all(),
                f"committed style-head tensor is invalid: {key}")
    return {"policy_tensors": len(policy_keys), "style_head_tensors": len(STYLE_TENSORS)}


def _validate_rng(value: Any, *, expected_torch_sha256: str | None = None) -> dict[str, Any]:
    import torch

    require(isinstance(value, Mapping) and set(value) == {"python", "numpy", "torch", "cuda"},
            "checkpoint RNG inventory is incomplete")
    require(isinstance(value["python"], tuple) and isinstance(value["numpy"], tuple),
            "checkpoint Python/NumPy RNG state is malformed")
    require(isinstance(value["torch"], torch.Tensor) and value["torch"].dtype == torch.uint8,
            "checkpoint Torch RNG state is malformed")
    require(isinstance(value["cuda"], list)
            and all(isinstance(item, torch.Tensor) and item.dtype == torch.uint8
                    for item in value["cuda"]),
            "checkpoint CUDA RNG inventory is malformed")
    torch_sha = hashlib.sha256(bytes(value["torch"].cpu().tolist())).hexdigest()
    if expected_torch_sha256 is not None:
        require(_is_sha(expected_torch_sha256) and torch_sha == expected_torch_sha256,
                "initialization RNG receipt differs from the committed initial state")
    return {"torch_sha256": torch_sha, "cuda_states": len(value["cuda"])}


def _validate_optimizer(run: Any, state: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    import torch

    optimizer = state.get("optimizer")
    require(isinstance(optimizer, Mapping)
            and isinstance(optimizer.get("state"), Mapping)
            and isinstance(optimizer.get("param_groups"), list)
            and len(optimizer["param_groups"]) == 1,
            "committed optimizer state is malformed")
    named = [(name, parameter) for name, parameter in run.learner.model.named_parameters()
             if parameter.requires_grad]
    require(len(named) == POLICY_TENSORS
            and all(name.startswith("policy.") for name, _ in named),
            "M81 trainable parameter inventory differs from the 32 policy tensors")
    group = optimizer["param_groups"][0]
    parameter_ids = group.get("params")
    require(isinstance(parameter_ids, list) and len(parameter_ids) == len(named)
            and len(set(parameter_ids)) == len(parameter_ids),
            "optimizer parameter-group inventory is invalid")
    slots = optimizer["state"]
    require(set(slots) == set(parameter_ids),
            "optimizer must retain one state slot for each trainable policy tensor")
    updates = state.get("global_step")
    for (name, parameter), parameter_id in zip(named, parameter_ids):
        slot = slots[parameter_id]
        require(isinstance(slot, Mapping)
                and set(slot) == {"step", "exp_avg", "exp_avg_sq"},
                f"optimizer slot schema differs for {name}")
        step = slot["step"]
        if isinstance(step, torch.Tensor):
            require(step.numel() == 1 and torch.isfinite(step).all(),
                    f"optimizer step is invalid for {name}")
            step_value = float(step.item())
        else:
            require(type(step) in (int, float) and math.isfinite(float(step)),
                    f"optimizer step is invalid for {name}")
            step_value = float(step)
        require(0 < step_value <= updates,
                f"optimizer step is outside committed updates for {name}")
        for key in ("exp_avg", "exp_avg_sq"):
            moment = slot[key]
            require(isinstance(moment, torch.Tensor) and moment.shape == parameter.shape
                    and moment.dtype == parameter.dtype and torch.isfinite(moment).all(),
                    f"optimizer moment is invalid for {name}.{key}")
    ppo = plan["training"]["ppo"]
    require(group.get("lr") == ppo["lr"]
            and group.get("weight_decay") == ppo["weight_decay"],
            "optimizer learning rate or weight decay differs from the plan")
    return {"optimizer_slots": len(slots), "trainable_parameters": len(named)}


def _commit_chain_and_genesis(
    run: Any,
) -> tuple[list[str], Mapping[str, Any], dict[str, str]]:
    chain: list[str] = []
    payload_by_commit: dict[str, str] = {}
    cursor = run.parent
    genesis: Mapping[str, Any] | None = None
    while cursor is not None:
        require(_is_sha(cursor) and cursor not in chain, "run commit chain is malformed or cyclic")
        chain.append(cursor)
        record = json.loads(run.store._get("commits", cursor, ".json").decode("utf-8"))
        require(record.get("format") == "prism-ppo-commit-v1"
                and record.get("identity") == run.identity,
                "run commit chain identity mismatch")
        require(_is_sha(record.get("payload")), "run commit payload identity is malformed")
        payload_by_commit[cursor] = record["payload"]
        if record.get("parent") is None:
            genesis = run.store.get_payload(record["payload"])
            break
        cursor = record.get("parent")
    require(genesis is not None, "run has no fresh initialization commit")
    return chain, genesis, payload_by_commit


def _verify_fresh_parent(
    root: Path,
    campaign: Path,
    plan: Mapping[str, Any],
    spec: Mapping[str, Any],
    run: Any,
) -> tuple[dict[str, Any], dict[str, str]]:
    import torch
    from training.prism_portable.engine.export import load_weights
    from training.prism_portable.engine.io import canonical_hash, tensor_manifest

    facts = _validate_plan(plan)
    parent_sha = plan["assets"][facts["training"]["parent"]]["sha256"]
    parent_path = Path(spec["parent_weights"])
    if not parent_path.is_absolute():
        parent_path = root / parent_path
    parent_path = parent_path.resolve()
    require(parent_path.is_file() and digest(parent_path) == parent_sha,
            "campaign parent bytes differ from the frozen parent identity")
    receipt = read_json(campaign / "initialization-verification.json")
    require(receipt.get("status") == "PASS"
            and receipt.get("exact_parent_tensors") == POLICY_TENSORS
            and receipt.get("optimizer_slots") == 0
            and receipt.get("parent_sha256") == parent_sha
            and receipt.get("run_seed") == facts["training"]["run_seed"],
            "fresh-parent initialization receipt does not match the plan")
    chain, genesis, payload_by_commit = _commit_chain_and_genesis(run)
    require(genesis.get("phase") == "READY" and genesis.get("cycle") == 0
            and genesis.get("attempts") == 0 and genesis.get("global_step") == 0
            and genesis.get("update_attempts") == 0 and genesis.get("all_jobs") == []
            and genesis.get("consumed") == [] and genesis.get("cursor") == 0,
            "run genesis is not a fresh, unused optimizer warm-start")
    require(isinstance(genesis.get("optimizer"), Mapping)
            and genesis["optimizer"].get("state") == {},
            "run genesis inherited optimizer slots")
    rng = _validate_rng(genesis.get("rng"), expected_torch_sha256=receipt.get("torch_rng_sha256"))
    parent_model = load_weights(parent_path,
                                expected_catalog_fingerprint=run.config["catalog_fingerprint"])
    committed = genesis.get("model")
    require(isinstance(committed, Mapping), "fresh run genesis has no model tensors")
    inventory = _validate_committed_tensor_inventory(
        committed, parent_model.state_dict(), torch,
    )
    initial_style = {key: genesis["model"][key] for key in STYLE_TENSORS}
    require(torch.count_nonzero(initial_style["style_head.2.weight"]).item() == 0
            and torch.count_nonzero(initial_style["style_head.2.bias"]).item() == 0,
            "fresh style head does not have its required zero output projection")
    require(len(chain) >= 1, "run commit chain is empty")
    return ({
            "parent_sha256": parent_sha,
            "run_seed": facts["training"]["run_seed"],
            "initialization_commit": chain[-1],
            "initial_rng_torch_sha256": rng["torch_sha256"],
            "parent_tensor_match": inventory,
            "initial_style_head_sha256": canonical_hash(tensor_manifest(initial_style)),
        }, payload_by_commit)


def _checkpoint_inventory(
    campaign: Path,
    plan: Mapping[str, Any],
    spec: Mapping[str, Any],
    completion: Mapping[str, Any],
    committed_model: Mapping[str, Any],
    run: Any,
    payload_by_commit: Mapping[str, str],
    initial_style_head_sha256: str,
) -> dict[str, Any]:
    import torch
    from training.prism_portable.engine.export import load_weights
    from training.prism_portable.engine.io import canonical_hash, tensor_manifest

    facts = _validate_plan(plan)
    declared = plan["training"].get("exports")
    require(isinstance(declared, list) and declared
            and all(type(cycle) is int and 1 <= cycle <= facts["cycles"] for cycle in declared)
            and len(set(declared)) == len(declared)
            and facts["cycles"] in declared,
            "plan checkpoint inventory must include fixed final c20")
    directories: dict[int, Path] = {}
    for path in campaign.glob("cycle-*-export"):
        match = re.fullmatch(r"cycle-(\d+)-export", path.name)
        require(match is not None, f"unrecognized checkpoint directory: {path.name}")
        cycle = int(match.group(1))
        require(cycle not in directories and 1 <= cycle <= facts["cycles"],
                f"duplicate or out-of-range checkpoint directory: {path.name}")
        directories[cycle] = path
    require(set(declared).issubset(directories),
            "one or more plan-required checkpoints are missing")
    require(set(directories) == set(declared),
            "checkpoint directory inventory differs from the exact plan exports")
    require(facts["cycles"] in directories, "fixed final checkpoint c20 is missing")

    observed: list[dict[str, Any]] = []
    final_policy = None
    for cycle, directory in sorted(directories.items()):
        weights_path = directory / "weights.json"
        manifest_path = directory / "weights.manifest.json"
        require(weights_path.is_file() and manifest_path.is_file(),
                f"checkpoint c{cycle} is missing weights or manifest")
        model = load_weights(weights_path,
                             expected_catalog_fingerprint=spec["run"]["catalog_fingerprint"])
        policy = model.state_dict()
        require(len(policy) == POLICY_TENSORS,
                f"checkpoint c{cycle} has an unexpected policy tensor count")
        manifest = read_json(manifest_path)
        tensors = tensor_manifest(policy)
        require(set(manifest) == {
                    "format", "weights_sha256", "tensor_sha256",
                    "tensors", "catalog_fingerprint", "provenance",
                }
                and manifest.get("format") == "prism-weights-manifest-v1"
                and manifest.get("weights_sha256") == digest(weights_path)
                and manifest.get("catalog_fingerprint") == spec["run"]["catalog_fingerprint"]
                and manifest.get("tensors") == tensors
                and manifest.get("tensor_sha256") == canonical_hash(tensors),
                f"checkpoint c{cycle} tensor manifest mismatch")
        provenance = manifest.get("provenance")
        require(isinstance(provenance, Mapping)
                and set(provenance) == {"run_identity", "commit", "cycle", "sampling", "not_promoted"}
                and provenance.get("run_identity") == run.identity
                and type(provenance.get("cycle")) is int
                and provenance.get("cycle") == cycle
                and provenance.get("sampling") == "softmax-t1"
                and provenance.get("not_promoted") is True
                and _is_sha(provenance.get("commit"))
                and provenance["commit"] in payload_by_commit,
                f"checkpoint c{cycle} is not bound to its committed M81 cycle")
        checkpoint_state = run.store.get_payload(payload_by_commit[provenance["commit"]])
        require(checkpoint_state.get("cycle") == cycle
                and checkpoint_state.get("phase") == "COMMITTED",
                f"checkpoint c{cycle} commit is not a completed cycle boundary")
        checkpoint_model = checkpoint_state.get("model")
        require(isinstance(checkpoint_model, Mapping),
                f"checkpoint c{cycle} commit has no full learner state")
        _validate_committed_tensor_inventory(checkpoint_model, policy, torch)
        checkpoint_style = {key: checkpoint_model[key] for key in STYLE_TENSORS}
        require(canonical_hash(tensor_manifest(checkpoint_style))
                == initial_style_head_sha256,
                f"checkpoint c{cycle} style head differs from fresh initialization")
        observed.append({
            "cycle": cycle,
            "weights_sha256": digest(weights_path),
            "manifest_sha256": digest(manifest_path),
            "policy_tensors": len(policy),
        })
        if cycle == facts["cycles"]:
            final_policy = policy

    require(final_policy is not None, "fixed final policy was not loaded")
    exact_counts = _validate_committed_tensor_inventory(committed_model, final_policy, torch)
    weights_ref = Path(str(completion.get("weights", "")))
    if not weights_ref.is_absolute():
        weights_ref = campaign.parent.parent / weights_ref
    expected_final = (campaign / f"cycle-{facts['cycles']}-export/weights.json").resolve()
    require(weights_ref.resolve() == expected_final,
            "worker selected a checkpoint other than fixed final c20")
    require(completion.get("weights_sha256") == digest(expected_final),
            "worker completion final checkpoint SHA mismatch")
    return {"checkpoints": observed, "final_tensor_match": exact_counts}


def _verify_worker_completion(
    root: Path,
    campaign: Path,
    plan: Mapping[str, Any],
    execution_sha: str,
    summary: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    completion_path = campaign / "worker-completion.json"
    completion = read_json(completion_path)
    require(completion.get("status") == "COMMITTED_FULL",
            "worker completion does not declare a full committed run")
    require(completion.get("logical_attempts") == summary["logical_attempts"]
            and completion.get("physical_attempts") == summary["physical_attempts"]
            and completion.get("games") == summary["terminal_games"]
            and completion.get("truncated_games") == summary["truncated_games"]
            and completion.get("global_step") == state["global_step"]
            and completion.get("update_attempts") == state["update_attempts"],
            "worker completion counters disagree with the committed run and ledger")
    require(completion.get("execution_sha256") == execution_sha,
            "worker completion is bound to a different execution")
    require(completion.get("logical_attempts") == plan["training"]["games_per_arm"],
            "worker completion does not account for the full planned workload")
    return completion


def _verify_infra_attempt(
    campaign: Path,
    spec: Mapping[str, Any],
    number: int,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    from training.prism_portable.engine.ppo.execution import verify_report

    directory = campaign / "attempts" / f"{number:03d}"
    job = row["job"]
    resources = row.get("resources")
    report_path = directory / "report.json"
    replay_path = directory / "replay.json"
    completion_path = directory / "completion.json"
    require(not completion_path.exists(),
            f"infrastructure attempt {number} has a terminal completion package")
    if row.get("reason") == "interrupted_unpublished":
        require(row.get("charged_decisions") == spec["run"]["budget"]["max_job_decisions"],
                f"interrupted attempt {number} did not reserve its full unknown-work charge")
    else:
        require(directory.is_dir(), f"infrastructure attempt {number} has no retained directory")
        process_path = directory / "process-result.json"
        require(process_path.is_file(), f"infrastructure attempt {number} lacks process resources")
        observed_resources = read_json(process_path)
        require(isinstance(resources, Mapping) and observed_resources == resources,
                f"infrastructure attempt {number} process resources differ from its ledger")

    outcome = row.get("outcome")
    if report_path.is_file():
        report = read_json(report_path)
        replay = read_json(replay_path) if replay_path.is_file() else None
        observed = verify_report(spec, dict(job), report, replay)
        require(observed.get("status") == "aborted"
                and observed.get("reason") in {"handshake_timeout", "action_timeout", "agent_eof", "agent_io"},
                f"infrastructure attempt {number} report is not an allowed infrastructure abort")
        require(outcome == observed or (
                    row.get("reason") == "interrupted_unpublished" and outcome is None
                ), f"infrastructure attempt {number} report differs from the ledger outcome")
    else:
        require(row.get("reason") == "interrupted_unpublished"
                or (outcome is None and isinstance(resources, Mapping)
                    and resources.get("stop_reason") == "spawn_infrastructure"),
                f"infrastructure attempt {number} has no matching report or spawn failure")

    sidecar = directory / "sidecar.jsonl"
    if sidecar.is_file():
        rows = _read_sidecar(sidecar)
        require(
            len(rows) <= row.get("charged_decisions")
            if row.get("reason") == "interrupted_unpublished"
            else len(rows) == row.get("charged_decisions"),
                f"infrastructure attempt {number} sidecar count differs from its charge")
    else:
        require(row.get("reason") == "interrupted_unpublished"
                or row.get("charged_decisions") == 0,
                f"infrastructure attempt {number} charged decisions without a sidecar")

    files = {
        path.name: digest(path)
        for path in directory.iterdir()
        if path.is_file() and path.name in {
            "arena-config.json", "stdout.log", "stderr.log", "process-result.json",
            "report.json", "replay.json", "prefix.json", "sidecar.jsonl",
        }
    } if directory.is_dir() else {}
    return {"attempt": number, "files": files}


def _validate_attempt_artifacts(
    campaign: Path,
    spec: Mapping[str, Any],
    run: Any,
    summary: Mapping[str, Any],
    run_module: Any,
) -> dict[str, Any]:
    from training.prism_portable.engine.ppo import execution as execution_module

    shared = importlib.import_module("scripts.prism_m79_audit")
    cycles = summary["jobs_by_cycle"]
    require(len(cycles) == shared.CYCLES,
            "shared PPO batch verifier does not support the plan cycle count")
    behavior_by_cycle = shared._cycle_behavior_map(
        run, run.state, cycles, summary, campaign,
    )
    behavior_cache: dict[str, str] = {}
    verified = Counter()
    infrastructure_receipts = []
    for number, row in sorted(summary["physical_attempts_by_number"].items()):
        if row["status"] == "INFRA_ABORT":
            infrastructure_receipts.append(
                _verify_infra_attempt(campaign, spec, number, row)
            )
            verified["infrastructure"] += 1
    original_check_assets = execution_module.check_assets

    # Asset hashes are checked around the complete scan. The package verifier
    # still checks every embedded contract, report, replay and sidecar.
    def cached_asset_check(candidate: Mapping[str, Any]) -> None:
        require(candidate == spec, "attempt package contract differs from its campaign")

    execution_module.check_assets = cached_asset_check
    try:
        for job_id, (number, row) in summary["attempt_by_job"].items():
            job = row["job"]
            cycle_index = next(
                index for index, cycle in enumerate(cycles, start=1)
                if any(item["job_id"] == job_id for item in cycle)
            )
            behavior_id = behavior_by_cycle[cycle_index]
            directory = campaign / "attempts" / f"{number:03d}"
            replay_path = directory / "replay.json"
            sidecar_path = directory / "sidecar.jsonl"
            if row["status"] == "COMPLETE":
                completion_path = directory / "completion.json"
                completion = read_json(completion_path)
                shared._verify_snapshot_behavior(run, completion, behavior_id, behavior_cache)
                result = execution_module.verify_completion(
                    run.config,
                    dict(job),
                    number,
                    completion_path,
                    replay=replay_path,
                    sidecar=sidecar_path,
                    behavior_id=behavior_id,
                )
                require(row.get("completion_sha256") == digest(completion_path),
                        f"completion SHA differs from ledger: {job_id}")
                replay = read_json(replay_path)
                report = read_json(directory / "report.json")
                shared._verify_terminal_sidecar(
                    sidecar_path,
                    job=job,
                    behavior_id=behavior_id,
                    spec=spec,
                    result=result,
                    replay=replay,
                )
                require(report.get("outcome", {}).get("result") == result,
                        f"verified terminal result differs from report: {job_id}")
                verified["terminal"] += 1
            elif row["status"] == "TRUNCATED":
                report = read_json(directory / "report.json")
                prefix = read_json(directory / "prefix.json")
                resources = read_json(directory / "process-result.json")
                require(isinstance(row.get("resources"), Mapping),
                        f"retained cap lacks process resources: {job_id}")
                helper = getattr(run_module, "validate_cap", None)
                if not callable(helper):
                    helper = shared.validate_cap
                sidecar_rows = shared._read_sidecar(sidecar_path)
                helper(
                    spec,
                    dict(job),
                    dict(row),
                    report,
                    prefix,
                    resources,
                    sidecar_count=len(sidecar_rows),
                    replay_exists=replay_path.exists(),
                    behavior_id=behavior_id,
                    sidecar_path=sidecar_path,
                )
                verified["retained_caps"] += 1
        return {**dict(verified), "infrastructure_receipts": infrastructure_receipts}
    finally:
        execution_module.check_assets = original_check_assets


def _audit_campaign(
    root: Path,
    plan: Mapping[str, Any],
    execution: Mapping[str, Any],
    execution_sha: str,
    arm: str,
    run_module: Any,
    resource_bounds: Any,
) -> dict[str, Any]:
    campaign = root / "campaigns" / arm
    require(campaign.is_dir(), f"campaign {arm} is missing")
    contract_path = campaign / "contract.json"
    spec = read_json(contract_path)
    from training.prism_portable.engine.ppo.execution import check_assets, validate_spec
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.ppo.store import CommitStore
    import training.prism_portable.engine.ppo.execution as execution_module

    validate_spec(spec)
    cycles = _validate_campaign_contract(plan, arm, spec)
    check_assets(spec)
    run = Run.open(campaign / "run")
    require(run.config == spec["run"], "campaign run config differs from its contract")
    state = run.state
    ledger_store = CommitStore(campaign / "launch-ledger", run.config["arena_contract_sha256"])
    ledger_head, ledger = ledger_store.load()
    require(isinstance(ledger_head, str) and _is_sha(ledger_head),
            "campaign ledger has no valid committed head")
    summary = validate_ledger(ledger, state, spec, plan, arm)
    rng = _validate_rng(state.get("rng"))
    optimizer = _validate_optimizer(run, state, plan)
    fresh_parent, payload_by_commit = _verify_fresh_parent(root, campaign, plan, spec, run)
    from training.prism_portable.engine.io import canonical_hash, tensor_manifest
    final_style = {key: state["model"][key] for key in STYLE_TENSORS}
    final_style_sha = canonical_hash(tensor_manifest(final_style))
    require(final_style_sha == fresh_parent["initial_style_head_sha256"],
            "frozen style-head tensors changed after fresh initialization")
    fresh_parent["final_style_head_sha256"] = final_style_sha
    completion = _verify_worker_completion(
        root, campaign, plan, execution_sha, summary, state,
    )
    inventory = _checkpoint_inventory(
        campaign, plan, spec, completion, state["model"], run, payload_by_commit,
        fresh_parent["initial_style_head_sha256"],
    )

    from training.prism_portable.engine.ppo.execution import check_assets as check_assets_again
    attempt_evidence = _validate_attempt_artifacts(
        campaign, spec, run, summary, run_module,
    )
    check_assets_again(spec)
    run_head = run.parent
    require(_is_sha(run_head), "run checkpoint head is invalid")
    return {
        "status": "PASS",
        "round": "M81",
        "arm": arm,
        "plan_sha256": digest(root / PLAN_PATH),
        "execution_sha256": execution_sha,
        "contract_sha256": digest(contract_path),
        "run_identity": run.identity,
        "run_commit": run_head,
        "ledger_commit": ledger_head,
        "logical_attempts": summary["logical_attempts"],
        "physical_attempts": summary["physical_attempts"],
        "terminal_games": summary["terminal_games"],
        "truncated_games": summary["truncated_games"],
        "infra_abort_attempts": summary["infra_abort_attempts"],
        "global_step": state["global_step"],
        "update_attempts": state["update_attempts"],
        "optimizer": optimizer,
        "rng": rng,
        "fresh_parent": fresh_parent,
        "checkpoints": inventory,
        "attempt_evidence": attempt_evidence,
        "resource_bounds": _json_value(resource_bounds),
    }


def _run_api(root: Path, disk_plan: Mapping[str, Any]) -> tuple[Any, Mapping[str, Any], Any]:
    try:
        run_module = importlib.import_module("scripts.prism_m81_run")
    except ImportError as exc:
        raise ValueError("M81 run verifier scripts.prism_m81_run is unavailable") from exc
    required = ("verify", "bounds", "install_resource_mode")
    require(all(callable(getattr(run_module, name, None)) for name in required),
            "M81 run module lacks verify/bounds/install_resource_mode")
    had_root = hasattr(run_module, "ROOT")
    previous_root = getattr(run_module, "ROOT", None)
    if had_root:
        run_module.ROOT = root
    try:
        verified = run_module.verify()
        if isinstance(verified, tuple) and len(verified) == 2:
            verified_plan, execution = verified
        elif isinstance(verified, Mapping) and "plan" in verified and "execution" in verified:
            verified_plan, execution = verified["plan"], verified["execution"]
        else:
            raise ValueError("M81 verify() returned an unsupported result")
        require(isinstance(verified_plan, Mapping) and dict(verified_plan) == dict(disk_plan),
                "run verifier plan differs from the plan on disk")
        require(isinstance(execution, Mapping), "M81 execution binding is malformed")
        run_module.install_resource_mode()
        resource_bounds = run_module.bounds()
        if resource_bounds is False:
            raise ValueError("M81 resource bounds rejected the audit")
        if isinstance(resource_bounds, Mapping):
            require(resource_bounds.get("ok", True) is not False
                    and resource_bounds.get("within_bounds", True) is not False
                    and resource_bounds.get("status") not in {"FAIL", "EXHAUSTED", "BLOCKED"},
                    "M81 resource bounds report failure")
        if isinstance(resource_bounds, (int, float)):
            require(math.isfinite(float(resource_bounds)) and resource_bounds >= 0,
                    "M81 resource bound is invalid")
        return run_module, execution, resource_bounds
    finally:
        if had_root:
            run_module.ROOT = previous_root


def _failure_receipt(root: Path, arm: str, plan_sha: str | None, error: BaseException) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "round": "M81",
        "arm": arm,
        "plan_sha256": plan_sha,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "error": f"{type(error).__name__}: {error}",
        "research_started": False,
    }


def audit(root: str | Path | None = None) -> dict[str, Any]:
    """Audit campaigns/A and campaigns/B; this function never launches games."""
    audit_root = Path(root).resolve() if root is not None else ROOT
    plan_sha: str | None = None
    plan: Mapping[str, Any] | None = None
    execution: Mapping[str, Any] | None = None
    resource_bounds: Any = None
    run_module: Any = None
    setup_error: BaseException | None = None
    try:
        plan_path = audit_root / PLAN_PATH
        plan_sha = digest(plan_path)
        plan = read_json(plan_path)
        _validate_plan(plan)
        run_module, execution, resource_bounds = _run_api(audit_root, plan)
        execution_path = audit_root / "execution.json"
        require(execution_path.is_file(), "M81 execution receipt is missing")
        execution_sha = digest(execution_path)
        declared_sha = execution.get("plan_sha256")
        require(declared_sha == plan_sha,
                "M81 execution receipt is not bound to the frozen plan")
    except BaseException as exc:
        setup_error = exc
        execution_sha = ""

    receipts: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        try:
            if setup_error is not None:
                raise ValueError(f"M81 setup verification failed: {setup_error}")
            assert plan is not None and execution is not None and run_module is not None
            receipt = _audit_campaign(
                audit_root, plan, execution, execution_sha, arm, run_module, resource_bounds,
            )
            receipt["observed_at"] = datetime.now(timezone.utc).isoformat()
        except BaseException as exc:
            receipt = _failure_receipt(audit_root, arm, plan_sha, exc)
        write_json(audit_root / "audits" / arm / "audit.json", receipt)
        receipts[arm] = receipt

    status = "PASS" if all(receipts[arm].get("status") == "PASS" for arm in ARMS) else "FAIL"
    return {
        "status": status,
        "round": "M81",
        "arms": {arm: receipts[arm]["status"] for arm in ARMS},
        "audit_paths": {arm: f"audits/{arm}/audit.json" for arm in ARMS},
        "research_started": False,
    }


if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
