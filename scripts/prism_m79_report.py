"""Read-only M79 result, replay-metric, and conclusion-first report builder."""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import prism_bounded_eval as bounded
from scripts import prism_match_details as details
from scripts import prism_m79_run
from scripts import prism_m79_statistics
from training.prism_portable.common import read, write, digest

PLAN_PATH = "benchmarks/m79-prism-mainline.execution-plan.json"
RESULT_PATH = "benchmarks/m79-prism-mainline.result.json"
EVIDENCE_PATH = "docs/prism/m79-prism-mainline-evidence.md"
READING_SPEC_PATH = "benchmarks/reports/m79-reading.json"
READING_HTML_PATH = "docs/prism/m79-prism-mainline-comparison.html"
CAP_STOP_REASON = "SCIENTIFIC_CAP_BUDGET"


def _identity(row: dict[str, Any] | tuple[Any, ...]) -> tuple[str, str, int, int]:
    if isinstance(row, dict):
        return (row["candidate"], row["opponent"], row["seed"], row["candidate_seat"])
    return (row[0], row[1], row[2], row[3])


def _identity_json(value: tuple[str, str, int, int], **extra: Any) -> dict[str, Any]:
    actor, opponent, seed, seat = value
    return dict(candidate=actor, opponent=opponent, seed=seed,
                candidate_seat=seat, **extra)


def _expected_identities(plan: dict[str, Any]) -> set[tuple[str, str, int, int]]:
    prism_m79_statistics._validate_plan(plan)
    evaluation = plan["evaluation"]
    expected: set[tuple[str, str, int, int]] = set()

    def add(actor: str, opponent: str, limits: list[int]) -> None:
        start, end = limits
        for seed in range(start, end + 1):
            for seat in evaluation["seats"]:
                identity = (actor, opponent, seed, seat)
                if identity in expected:
                    raise ValueError(f"duplicate planned M79 identity: {identity}")
                expected.add(identity)

    for actor in evaluation["common_actors"]:
        for opponent, limits in evaluation["common_seed_by_opponent"].items():
            add(actor, opponent, limits)
    for actor in evaluation["coverage_actors"]:
        for opponent, limits in evaluation["coverage_seed_by_opponent"].items():
            add(actor, opponent, limits)
    add(evaluation["direct"]["candidate"], "parent", evaluation["direct"]["seed_range"])
    if len(expected) != evaluation["logical_attempts"]:
        raise ValueError("M79 planned identity count drift")
    return expected


def _planned_shards(plan: dict[str, Any]) -> list[dict[str, Any]]:
    evaluation = plan["evaluation"]
    width = evaluation["shard_seed_blocks"]
    groups: list[tuple[str, str, list[int]]] = []
    groups.extend((actor, opponent, limits)
                  for actor in evaluation["common_actors"]
                  for opponent, limits in evaluation["common_seed_by_opponent"].items())
    groups.extend((actor, opponent, limits)
                  for actor in evaluation["coverage_actors"]
                  for opponent, limits in evaluation["coverage_seed_by_opponent"].items())
    groups.append((evaluation["direct"]["candidate"], "parent",
                   evaluation["direct"]["seed_range"]))

    shards = []
    for actor, opponent, limits in groups:
        low, high = limits
        for start in range(low, high + 1, width):
            stop = min(start + width, high + 1)
            identities = [(actor, opponent, seed, seat)
                          for seed in range(start, stop)
                          for seat in evaluation["seats"]]
            shards.append(dict(label=f"{actor}-{opponent}-{start}",
                               candidate=actor, opponent=opponent,
                               seed_range=[start, stop - 1],
                               identities=identities,
                               planned_games=len(identities)))
    return shards


def _resolve_under(root: Path, value: str | Path) -> Path:
    path = Path(value)
    path = path if path.is_absolute() else root / path
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"M79 evidence path escapes execution root: {value}") from error
    return path


@contextmanager
def _execution_root(root: Path):
    old_run = prism_m79_run.ROOT
    old_bounded = bounded.ROOT
    prism_m79_run.ROOT = root
    bounded.ROOT = root
    try:
        yield
    finally:
        prism_m79_run.ROOT = old_run
        bounded.ROOT = old_bounded


def _check_upstream(root: Path, plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    for stage in ("train", "audit", "candidates"):
        receipt = read(root / "pipeline" / f"{stage}.completion.json")
        if receipt.get("status") != "PASS":
            raise ValueError(f"M79 {stage} stage did not pass; dependent report stopped")

    registry_path = root / "candidate-registry.json"
    registry = read(registry_path)
    if registry.get("status") != "FROZEN_FINAL_C20_BEFORE_EVALUATION":
        raise ValueError("M79 fixed final candidate is not frozen")
    model = registry.get("models", {}).get("a")
    if not isinstance(model, dict):
        raise ValueError("M79 candidate registry has no actor a")

    candidate_path = _resolve_under(root, model["path"])
    if digest(candidate_path) != model.get("sha256"):
        raise ValueError("M79 candidate weight SHA drift")
    if model.get("parent_sha256") not in (None, plan["assets"]["parent"]["sha256"]):
        raise ValueError("M79 candidate parent identity drift")
    audit_path = root / "audits" / "a" / "audit.json"
    if digest(audit_path) != model.get("audit_sha256"):
        raise ValueError("M79 candidate audit SHA drift")
    audit = read(audit_path)
    if audit.get("status") != "PASS_TRAINING_ARTIFACT_AUDIT":
        raise ValueError("M79 final c20 artifact audit did not pass")
    if audit.get("weights_sha256") != model["sha256"]:
        raise ValueError("M79 audit and candidate weight SHA differ")

    actor_hashes = {
        "base": plan["assets"]["parent"]["sha256"],
        "a": model["sha256"],
        "style-reference": plan["assets"]["style-reference"]["sha256"],
    }
    for actor, asset in (("base", "parent"), ("style-reference", "style-reference")):
        path = root / "inputs" / f"{asset}.json"
        if digest(path) != actor_hashes[actor]:
            raise ValueError(f"M79 {actor} input SHA drift")
    return registry, actor_hashes


def _check_evaluation_plan(root: Path, plan: dict[str, Any], registry: dict[str, Any],
                           evaluation_plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    plan_path = root / PLAN_PATH
    registry_path = root / "candidate-registry.json"
    if evaluation_plan.get("format") != "prism-m79-bounded-shards-v1":
        raise ValueError("invalid M79 evaluation plan schema")
    if evaluation_plan.get("plan_sha256") != digest(plan_path):
        raise ValueError("M79 evaluation plan contract hash drift")
    if evaluation_plan.get("candidate_registry_sha256") != digest(registry_path):
        raise ValueError("M79 evaluation plan registry hash drift")
    planned = _planned_shards(plan)
    declared = evaluation_plan.get("shards")
    if not isinstance(declared, list) or evaluation_plan.get("total_games") != plan["evaluation"]["logical_attempts"]:
        raise ValueError("M79 evaluation plan count/schema drift")
    by_label = {}
    by_output = set()
    for item in declared:
        label = item.get("label")
        if not isinstance(label, str) or label in by_label:
            raise ValueError("duplicate or invalid M79 shard label")
        if item.get("category") != "independent":
            raise ValueError(f"M79 shard has wrong role: {label}")
        if item.get("planned_games") != next((s["planned_games"] for s in planned if s["label"] == label), None):
            raise ValueError(f"M79 shard planned count drift: {label}")
        output = _resolve_under(root, item["output"])
        if output in by_output:
            raise ValueError("duplicate M79 shard output path")
        by_output.add(output)
        item = dict(item, _output_path=output)
        by_label[label] = item
    if set(by_label) != {shard["label"] for shard in planned}:
        raise ValueError("M79 evaluation plan does not cover the frozen shard grid")
    if len(declared) != len(planned):
        raise ValueError("M79 evaluation plan shard count drift")
    return planned, by_label


def _validate_shard_config(output: Path, actor: str, opponent: str,
                           identities: list[tuple[str, str, int, int]], plan: dict[str, Any]):
    validated, policy = bounded.load_bound(output)
    config = validated["config"]
    if set(config.get("candidates", {})) != {actor} or set(config.get("opponents", {})) != {opponent}:
        raise ValueError(f"M79 shard actor/opponent config drift: {output.name}")
    expected_seeds = sorted({identity[2] for identity in identities})
    if config.get("seeds") != expected_seeds:
        raise ValueError(f"M79 shard seed config drift: {output.name}")
    jobs = {_identity(job) for job in bounded.legacy.jobs(config)}
    if jobs != set(identities):
        raise ValueError(f"M79 shard command grid drift: {output.name}")
    if policy.get("automatic_game_retries") != 0 or policy.get("ply_cap") != plan["evaluation"]["ply_cap"]:
        raise ValueError(f"M79 shard policy drift: {output.name}")
    return config, policy


def _collect_rows(root: Path, plan: dict[str, Any], registry: dict[str, Any],
                  evaluation_plan: dict[str, Any], completion: dict[str, Any]):
    planned, by_label = _check_evaluation_plan(root, plan, registry, evaluation_plan)
    all_expected = _expected_identities(plan)
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    caps: list[dict[str, Any]] = []
    shard_summaries: list[dict[str, Any]] = []
    expected_to_shard: dict[tuple[str, str, int, int], str] = {}
    key_to_identity: dict[str, tuple[str, str, int, int]] = {}
    inspections: dict[str, dict[str, Any]] = {}
    completion_shards = {}

    if completion.get("plan_sha256") != digest(root / "evaluation-plan.json"):
        raise ValueError("M79 evaluation completion plan hash drift")
    if completion.get("status") != "FINISHED_WITH_EXPLICIT_MISSINGNESS":
        raise ValueError("M79 evaluation stage has no valid completion receipt")
    for item in completion.get("shards", []):
        label = item.get("label")
        if label in completion_shards or label not in by_label:
            raise ValueError("M79 completion contains duplicate or unknown shard")
        completion_shards[label] = item

    for spec in planned:
        label = spec["label"]
        shard = by_label[label]
        output = shard["_output_path"]
        for identity in spec["identities"]:
            if identity in expected_to_shard:
                raise ValueError(f"duplicate M79 expected identity: {identity}")
            expected_to_shard[identity] = label

        manifest_path = output / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"M79 frozen shard config is missing: {label}")
        if digest(manifest_path) != shard.get("manifest_sha256"):
            raise ValueError(f"M79 shard manifest hash drift: {label}")
        _validate_shard_config(output, spec["candidate"], spec["opponent"],
                               spec["identities"], plan)

        ledger_path = output / "ledger.json"
        if not ledger_path.is_file():
            if (output / "games").exists() or (output / "once-only.lock").exists():
                raise ValueError(f"M79 shard has dispatch artifacts without a ledger: {label}")
            for identity in spec["identities"]:
                missing.append(_identity_json(identity, shard=label,
                                              reason="NO_LEDGER_NOT_DISPATCHED"))
            shard_summaries.append(dict(label=label, state="NO_LEDGER_NOT_DISPATCHED",
                                        planned_games=spec["planned_games"], completed_games=0,
                                        truncated_games=0, missing_games=spec["planned_games"]))
            if label in completion_shards:
                raise ValueError(f"M79 completion claims a shard with no ledger: {label}")
            continue

        inspection = bounded.inspect(output)
        inspections[label] = inspection
        ledger = read(ledger_path)
        if ledger.get("manifest_sha256") != digest(manifest_path):
            raise ValueError(f"M79 shard ledger manifest hash drift: {label}")
        state = ledger.get("execution_state")
        stop_reason = ledger.get("stop_reason")
        if state == "RUNNING":
            raise ValueError(f"M79 shard still has an unconfirmed live/interrupted owner: {label}")
        if state == "STOPPED" and stop_reason != CAP_STOP_REASON:
            raise ValueError(f"M79 non-cap shard failure stops dependent reporting: {label}")
        if state not in ("FINISHED", "STOPPED"):
            raise ValueError(f"invalid M79 shard ledger state: {label}")

        local_keys = {}
        for identity in spec["identities"]:
            key = bounded.fixed._game_key(*identity)
            if key in local_keys:
                raise ValueError(f"M79 duplicate ledger key: {key}")
            local_keys[key] = identity
            key_to_identity[f"{label}\0{key}"] = identity
        entries = ledger.get("entries", {})
        unknown = set(entries) - set(local_keys)
        if unknown:
            raise ValueError(f"M79 shard ledger has unexpected identities: {label}")

        shard_rows = 0
        shard_caps = 0
        for key, identity in local_keys.items():
            entry = entries.get(key)
            if entry is None:
                reason = "NOT_DISPATCHED_AFTER_CAP_LIMIT" if stop_reason == CAP_STOP_REASON else "LEDGER_ENTRY_MISSING"
                missing.append(_identity_json(identity, shard=label, reason=reason))
                continue
            if entry.get("state") == "COMPLETED":
                row = entry.get("row")
                if not isinstance(row, dict) or _identity(row) != identity:
                    raise ValueError(f"M79 completed row identity drift: {label}/{key}")
                directory = output / "games" / identity[0] / identity[1] / f"seed-{identity[2]}-seat-{identity[3]}"
                replay_path = directory / "replay.json"
                replay = read(replay_path)
                candidate_actions, opponent_actions = Counter(), Counter()
                for step in replay["steps"]:
                    target = candidate_actions if step["actor"] == identity[3] else opponent_actions
                    target[step["action"]["type"]] += 1
                row = dict(row)
                row["_candidate_actions"] = candidate_actions
                row["_opponent_actions"] = opponent_actions
                row["_replay_path"] = str(replay_path)
                row["_wall_seconds"] = read(directory / "process-result.json")["wall_seconds"]
                rows.append(row)
                shard_rows += 1
            elif entry.get("state") == "RETAINED_FAILURE" and entry.get("kind") == "PLY_CAP_TRUNCATED":
                caps.append(_identity_json(identity, shard=label, reason="PLY_CAP_TRUNCATED",
                                           evidence_sha256=entry.get("evidence_sha256")))
                shard_caps += 1
            elif entry.get("state") == "RETAINED_FAILURE":
                raise ValueError(f"M79 non-cap failure stops dependent reporting: {label}/{key}")
            elif entry.get("state") == "DISPATCHED":
                raise ValueError(f"M79 unresolved dispatched identity stops dependent reporting: {label}/{key}")
            else:
                raise ValueError(f"invalid M79 ledger entry state: {label}/{key}")

        shard_missing = spec["planned_games"] - shard_rows - shard_caps
        shard_summaries.append(dict(label=label, state=state,
                                    stop_reason=stop_reason, planned_games=spec["planned_games"],
                                    completed_games=shard_rows, truncated_games=shard_caps,
                                    missing_games=shard_missing,
                                    consumed_cpu_seconds=ledger.get("consumed_cpu_seconds")))
        reported = completion_shards.get(label)
        if reported is None:
            raise ValueError(f"M79 completion omits a shard with a ledger: {label}")
        grid = reported.get("grid", {})
        if reported.get("manifest_sha256") != shard.get("manifest_sha256"):
            raise ValueError(f"M79 completion shard manifest drift: {label}")
        if (grid.get("execution_state") != state
                or grid.get("completed_games") != shard_rows
                or grid.get("truncated_games") != shard_caps
                or grid.get("planned_games") != spec["planned_games"]):
            raise ValueError(f"M79 shard completion and ledger disagree: {label}")

    if set(expected_to_shard) != all_expected:
        raise ValueError("M79 shard grid does not exactly cover expected identities")
    if set(completion_shards) != set(inspections):
        raise ValueError("M79 evaluation completion and shard ledgers disagree")
    completed = len(rows)
    truncated = len(caps)
    if completion.get("completed_games") != completed:
        raise ValueError("M79 evaluation completion completed-game count drift")
    if completion.get("truncated_games") != truncated:
        raise ValueError("M79 evaluation completion truncation count drift")
    if completed + truncated + len(missing) != len(all_expected):
        raise ValueError("M79 completed, capped, and missing identity counts do not balance")
    if truncated > plan["evaluation"]["max_scientific_truncations"]:
        if not any(s["state"] == "STOPPED" and s.get("stop_reason") == CAP_STOP_REASON
                   for s in shard_summaries):
            raise ValueError("M79 ninth-cap stop lacks a stopped shard ledger")

    retries_path = root / "infrastructure-retries.json"
    retries = read(retries_path) if retries_path.exists() else []
    retry_keys = [item.get("logical_key") for item in retries]
    if len(retry_keys) != len(set(retry_keys)) or len(retries) > plan["recovery"]["infra_retry_total_extra_physical_attempts"]:
        raise ValueError("M79 infrastructure retry ledger count/identity drift")
    return rows, missing, caps, shard_summaries, retries


def _rust_metrics(root: Path, rows: list[dict[str, Any]]):
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["candidate"], row["opponent"], row["candidate_seat"])].append(row)
    metrics: dict[tuple[str, str, int], dict[str, Any]] = {}
    receipts = []
    if not groups:
        return metrics, receipts, "NOT_RUN_NO_COMPLETED_REPLAYS"
    audit_root = root / "analysis" / "m79-report-rust-audit"
    audit_root.mkdir(parents=True, exist_ok=False)
    binary = root / "bin" / "s4_batch_metrics"
    for index, (key, group_rows) in enumerate(sorted(groups.items())):
        manifest = audit_root / f"metrics-{index:03d}.manifest.json"
        output = audit_root / f"metrics-{index:03d}.json"
        write(manifest, dict(rows=[dict(replay_path=row["_replay_path"]) for row in group_rows]))
        argv = [str(binary), str(manifest), str(output)]
        started = time.monotonic()
        process = subprocess.run(argv, capture_output=True, text=True, timeout=900)
        receipt = dict(group=dict(candidate=key[0], opponent=key[1], candidate_seat=key[2]),
                       argv=argv, exit_code=process.returncode,
                       wall_seconds=time.monotonic() - started,
                       manifest_sha256=digest(manifest),
                       stdout=process.stdout, stderr=process.stderr)
        write(audit_root / f"metrics-{index:03d}.receipt.json", receipt)
        receipts.append(receipt)
        if process.returncode:
            raise ValueError(f"M79 Rust saved-replay audit failed for {key}: {process.stderr}")
        metrics[key] = read(output)
    return metrics, receipts, "PASS_ALL_COMPLETED_SAVED_REPLAYS"


def _pair_rows(plan: dict[str, Any], rows: list[dict[str, Any]], metrics: dict[tuple[str, str, int], dict[str, Any]]):
    expected = _expected_identities(plan)
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["candidate"], row["opponent"], row["candidate_seat"])].append(row)
    identities = sorted({(candidate, opponent) for candidate, opponent, _, _ in expected})
    pairs = []
    for candidate, opponent in identities:
        pair_rows = groups.get((candidate, opponent, 0), []) + groups.get((candidate, opponent, 1), [])
        planned = sum(1 for item in expected if item[:2] == (candidate, opponent))
        by_seed: dict[int, set[int]] = defaultdict(set)
        for row in pair_rows:
            by_seed[row["seed"]].add(row["candidate_seat"])
        complete = (len(pair_rows) == planned and all(seats == {0, 1} for seats in by_seed.values()))
        if not pair_rows:
            pairs.append(dict(candidate=candidate, opponent=opponent,
                              candidate_metrics=None, opponent_metrics=None,
                              seats=[], macro=None, planned_games=planned,
                              completed_games=0, missing_games=planned,
                              status="INCOMPLETE", uncertainty="NOT_MEASURED_NO_TERMINAL_ROWS"))
            continue
        candidate_batches = []
        opponent_batches = []
        seats = []
        for seat in (0, 1):
            seat_rows = groups.get((candidate, opponent, seat), [])
            if not seat_rows:
                continue
            raw = metrics[(candidate, opponent, seat)]
            candidate_metrics = raw["seat_p0_first" if seat == 0 else "seat_p1_second"]
            opponent_metrics = raw["seat_p1_second" if seat == 0 else "seat_p0_first"]
            candidate_batches.append((candidate_metrics, len(seat_rows)))
            opponent_batches.append((opponent_metrics, len(seat_rows)))
            seats.append(dict(candidate_seat=seat,
                              candidate=details.merge_player([(candidate_metrics, len(seat_rows))], seat_rows, True),
                              opponent=details.merge_player([(opponent_metrics, len(seat_rows))], seat_rows, False),
                              games=len(seat_rows)))
        pair = dict(candidate=candidate, opponent=opponent,
                    candidate_metrics=details.merge_player(candidate_batches, pair_rows, True),
                    opponent_metrics=details.merge_player(opponent_batches, pair_rows, False),
                    seats=seats, macro=details.macro(pair_rows), planned_games=planned,
                    completed_games=len(pair_rows), missing_games=planned-len(pair_rows),
                    status="COMPLETE" if complete else "INCOMPLETE",
                    uncertainty="DESCRIPTIVE_COMPLETE_GRID" if complete else "NOT_MEASURED_INCOMPLETE_PAIRING")
        pairs.append(pair)
    return pairs


def _name_map(plan: dict[str, Any], registry: dict[str, Any]) -> dict[str, str]:
    asset_names = {}
    for key, asset in plan["assets"].items():
        stem = Path(asset["local_path"]).parent.name
        asset_names[key] = stem.replace("-", " ")
    candidate = registry["models"]["a"]
    return {
        "a": candidate.get("display_name", "M79 fixed final c20 (unpublished)"),
        "base": plan["parent_label"],
        "style-reference": asset_names.get("style-reference", "Fixed style reference"),
        **{key: key.replace("-", " ").title()
           for key in ("parent", "heuristic", "general", "balance", "alpha", "beta",
                       "released-alpha", "latest-alpha", "latest-balance")},
    }


def _verdicts(result: dict[str, Any]) -> tuple[list[dict[str, str]], str]:
    stats = result["statistics"]
    recommendation = stats["mainline_recommendation"]["status"]
    if recommendation == "PASS":
        competition = "冻结主线父候选推荐门通过"
        competition_detail = "增强与保留端点均通过冻结门；该结论只推荐下一段主线父候选。"
    elif recommendation == "FAIL":
        competition = "冻结主线推荐门未通过"
        competition_detail = "失败端点按原合同保留；未通过不自动等同于真实退化。"
    else:
        competition = "竞技结论 INCOMPLETE"
        competition_detail = "缺失身份保留为缺项；不以已完成子集替代冻结端点。"
    grid = result["grid"]
    if grid["missing_games"] or result["truncated_games"]:
        artifact = "最终 c20 已冻结，独立网格有缺项"
        artifact_detail = f"c20权重与训练审计已核验；独立网格完成{grid['completed_games']}/{grid['planned_games']}局，科学截断{result['truncated_games']}局。"
    else:
        artifact = "最终 c20 与独立网格完整"
        artifact_detail = f"候选SHA、训练产物审计和{grid['planned_games']}局网格均已核验。"
    style = "行为画像由独立 M79 profile 阶段交付"
    style_detail = "三演员网格保留固定风格参照；路线结论等待保存回放画像，当前上限为描述性。"
    conclusions = [
        dict(label="产物", value=artifact, explanation=artifact_detail),
        dict(label="竞技", value=competition, explanation=competition_detail),
        dict(label="风格", value=style, explanation=style_detail),
    ]
    next_action = ("继续已授权的 M79 回放画像与候选卡归档，完成桌面和窄屏像素核验后收口。")
    return conclusions, next_action


def _reading_spec(root: Path, result: dict[str, Any], result_path: Path,
                  markdown_path: Path, plan_path: Path, registry_path: Path,
                  evaluation_plan_path: Path, completion_path: Path,
                  names: dict[str, str], conclusions: list[dict[str, str]],
                  next_action: str) -> dict[str, Any]:
    return dict(
        format="prism-m79-bounded-reading-v1",
        result=result_path.relative_to(root).as_posix(), result_sha256=digest(result_path),
        markdown=markdown_path.relative_to(root).as_posix(), markdown_sha256=digest(markdown_path),
        contract=plan_path.relative_to(root).as_posix(), contract_sha256=digest(plan_path),
        candidate_registry=registry_path.relative_to(root).as_posix(),
        candidate_registry_sha256=digest(registry_path),
        evaluation_plan=evaluation_plan_path.relative_to(root).as_posix(),
        evaluation_plan_sha256=digest(evaluation_plan_path),
        evaluation_completion=completion_path.relative_to(root).as_posix(),
        evaluation_completion_sha256=digest(completion_path),
        output=READING_HTML_PATH,
        story=dict(round="M79", title="M79 Prism 主线独立评测",
                   headline=f"独立评测完成{result['completed_games']}/{result['planned_games']}局；所有缺项和冻结端点分别列出。",
                   identity=f"{names['base']} → fresh AdamW/RNG warm-start → 固定最终 c20；双方greedy，三演员共同对手网格。",
                   conclusions=conclusions,
                   interpretation="竞技门按冻结配对单位和计划分母计算。科学截断、未派局和终局结果分别记录；描述值不替代不完整门。",
                   next=next_action),
        names=names, focus="a", baseline="base",
        style_reference="style-reference", games_dispatched=0,
    )


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "NOT_MEASURED"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "NOT_MEASURED"
        return f"{value:.{digits}f}"
    return str(value)


def _metrics_markdown(pair: dict[str, Any], names: dict[str, str]) -> list[str]:
    lines = [f"### {names.get(pair['candidate'], pair['candidate'])} 对阵 {names.get(pair['opponent'], pair['opponent'])}", "",
             f"状态：**{pair['status']}**；终局{pair['completed_games']}/{pair['planned_games']}，缺项{pair['missing_games']}。"]
    if not pair["candidate_metrics"]:
        return lines + ["", "双方指标：NOT_MEASURED（没有已完成终局）。", ""]
    candidate = pair["candidate_metrics"]
    opponent = pair["opponent_metrics"]
    lines += ["", "双方个人指标（按已完成局数合并；不完整对手组仅作描述）：", "",
              "| 指标 | 模型本人 | 对手本人 |", "| --- | ---: | ---: |"]
    fields = [
        ("局数", "games", 0), ("胜", "wins", 0), ("平", "ties", 0), ("负", "losses", 0),
        ("纯胜率%", "win_rate_percent", 2), ("半平得分率", "score_rate", 4),
        ("最终VP/局", "mean_prestige", 4), ("VP/本人Main", "vp_per_main_action", 4),
        ("VP/本人决策", "vp_per_turn", 4), ("VP/全局步", "vp_per_ply", 4),
        ("贵族/局", "mean_nobles", 4), ("贵族覆盖率%", "games_with_nobles_percent", 2),
        ("永久折扣/局", "mean_permanent_bonuses", 4), ("预留获得/局", "mean_reserves_acquired", 4),
        ("预留买回/局", "mean_reserves_bought", 4), ("未买回预留/局", "mean_reserves_stranded", 4),
        ("预留买回率%", "reserve_redemption_rate_percent", 2),
    ]
    for label, key, digits in fields:
        lines.append(f"| {label} | {_fmt(candidate.get(key), digits)} | {_fmt(opponent.get(key), digits)} |")
    lines += ["", "#### VP牌与折扣颜色", "", "| 指标 | 模型本人 | 对手本人 |", "| --- | ---: | ---: |"]
    for vp in range(6):
        key = str(vp)
        lines.append(f"| {vp} VP牌/局 | {_fmt(candidate.get('mean_cards_by_vp', {}).get(key))} | {_fmt(opponent.get('mean_cards_by_vp', {}).get(key))} |")
    colors = (("White", "白"), ("Blue", "蓝"), ("Green", "绿"), ("Red", "红"), ("Black", "黑"))
    for color, label in colors:
        lines.append(f"| {label}折扣/局 | {_fmt(candidate.get('mean_bonuses_by_color', {}).get(color))} | {_fmt(opponent.get('mean_bonuses_by_color', {}).get(color))} |")
    lines += ["", "#### 座位", "", "| 模型座位 | 局数 | 模型 W/D/L | 模型半平得分 | 对手 W/D/L | 对手半平得分 |", "| ---: | ---: | --- | ---: | --- | ---: |"]
    for seat in pair["seats"]:
        cm, om = seat["candidate"], seat["opponent"]
        lines.append(f"| {seat['candidate_seat']} | {seat['games']} | {cm['wins']}/{cm['ties']}/{cm['losses']} | {_fmt(cm.get('score_rate'))} | {om['wins']}/{om['ties']}/{om['losses']} | {_fmt(om.get('score_rate'))} |")
    lines += ["", "配对逐seed普通区间：NOT_MEASURED；每对手区间不属于冻结主门。正式端点区间见下方统计表。", ""]
    return lines


def _markdown(result: dict[str, Any], names: dict[str, str], source_hashes: dict[str, str]) -> str:
    conclusions, next_action = _verdicts(result)
    lines = ["# M79 Prism 主线独立评测", "", result["headline"], "",
             "| 结论 | 判断 | 解释 |", "| --- | --- | --- |"]
    lines += [f"| {row['label']} | **{row['value']}** | {row['explanation']} |" for row in conclusions]
    grid = result["grid"]
    lines += ["", f"网格：{grid['completed_games']}/{grid['planned_games']}终局；{result['truncated_games']}科学截断；{grid['missing_games']}未形成终局。",
              f"分片状态：{result['dispatch_state']}；第九次及后续科学截断按原规则停止新增派局。",
              f"Rust保存回放审计：{result['rule_replay_audit']}。基础设施重试记录：{len(result['infrastructure_retries'])}次。",
              "", "## 冻结竞技端点", "",
              "| 端点 | 状态 | 估计 | 普通95%区间 | 冻结门 | 缺失界 |", "| --- | --- | ---: | --- | --- | --- |"]
    for name, endpoint in result["statistics"]["endpoints"].items():
        estimate = endpoint.get("estimate")
        interval = endpoint.get("interval") or {}
        ci = interval.get("ordinary_95_ci", interval.get("ci95"))
        ci_text = "NOT_MEASURED" if not ci or any(v is None for v in ci) else f"[{100*ci[0]:.2f}%, {100*ci[1]:.2f}%]"
        gates = ", ".join(f"{key}={value}" for key, value in endpoint.get("gates", {}).items()) or "NOT_RUN"
        bounds = endpoint.get("diagnostic_bounds") or endpoint.get("point_bounds") or "NOT_MEASURED"
        lines.append(f"| {name} | {endpoint.get('status', 'UNKNOWN')} | {_fmt(estimate)} | {ci_text} | {gates} | `{json.dumps(bounds, ensure_ascii=False)}` |")
    lines += ["", "## 对手组与演员分母", "", "| 模型本人 | 对手 | 已完成/计划 | W/D/L | 半平得分 | 座位0 W/D/L | 座位1 W/D/L | 状态 |",
              "| --- | --- | ---: | --- | ---: | --- | --- | --- |"]
    stats_pairs = {(p["candidate"], p["opponent"]): p for p in result["statistics"]["opponent_descriptives"]}
    for pair in result["pairs"]:
        stat = stats_pairs.get((pair["candidate"], pair["opponent"]), {})
        overall = stat.get("overall", {})
        seats = stat.get("by_candidate_seat", {})
        wdl = f"{overall.get('wins', 0)}/{overall.get('draws', 0)}/{overall.get('losses', 0)}" if overall.get("games") else "NOT_MEASURED"
        seat_text = [seats.get(str(s), {}) for s in (0, 1)]
        seat_wdl = [f"{v.get('wins', 0)}/{v.get('draws', 0)}/{v.get('losses', 0)}" if v.get("games") else "NOT_MEASURED" for v in seat_text]
        half = _fmt(overall.get("half_score"))
        lines.append(f"| {names.get(pair['candidate'], pair['candidate'])} | {names.get(pair['opponent'], pair['opponent'])} | {pair['completed_games']}/{pair['planned_games']} | {wdl} | {half} | {seat_wdl[0]} | {seat_wdl[1]} | {pair['status']} |")
    for pair in result["pairs"]:
        lines += ["", *_metrics_markdown(pair, names)]
    lines += ["", "## 分片账本", "", "| 分片 | 状态 | 已完成 | 截断 | 缺项 | 停止原因 |", "| --- | --- | ---: | ---: | ---: | --- |"]
    for shard in result["shards"]:
        lines.append(f"| {shard['label']} | {shard['state']} | {shard['completed_games']} | {shard['truncated_games']} | {shard['missing_games']} | {shard.get('stop_reason', '—')} |")
    lines += ["", "## 缺失的预期对局身份", "", "以下清单只列计划身份与真实缺失原因；没有给缺失对局填入胜、平或负。", "",
              "| 模型本人 | 对手 | seed | 模型座位 | 分片 | 原因 |", "| --- | --- | ---: | ---: | --- | --- |"]
    for row in result["missing"]:
        lines.append(f"| {names.get(row['candidate'], row['candidate'])} | {names.get(row['opponent'], row['opponent'])} | {row['seed']} | {row['candidate_seat']} | {row['shard']} | {row['reason']} |")
    lines += ["", "## 科学截断", "", "| 模型本人 | 对手 | seed | 模型座位 | 分片 | 分类 |", "| --- | --- | ---: | ---: | --- | --- |"]
    for row in result["caps"]:
        lines.append(f"| {names.get(row['candidate'], row['candidate'])} | {names.get(row['opponent'], row['opponent'])} | {row['seed']} | {row['candidate_seat']} | {row['shard']} | {row['reason']} |")
    lines += ["", "## 身份与来源哈希", "", "| 来源 | SHA256 |", "| --- | --- |"]
    lines += [f"| {key} | `{value}` |" for key, value in source_hashes.items()]
    lines += ["", "统计：半平得分=(胜+0.5×平)/局数；纯胜率=胜/局数。配对重采样先对同seed两座取平均；六个共同对手等权。固定风格参照仅作描述比较，不计入父子主门。",
              "", "路线：M79合同将风格证据限定为DESCRIPTIVE。当前报告不生成行为画像；下一阶段使用保存回放完成固定Balance v0.2.0与父代画像。",
              "", "下一步：" + next_action, ""]
    return "\n".join(lines)


def _json_safe(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def build(root: str | Path | None = None, *, templates: str | Path | None = None) -> dict[str, Any]:
    """Freeze M79 reporting artifacts from saved ledgers and replays only."""
    root = Path(root or prism_m79_run.ROOT).resolve()
    template_root = Path(templates).resolve() if templates else root / "scripts" / "templates"
    with _execution_root(root):
        plan, execution = prism_m79_run.verify()
        remaining_seconds = prism_m79_run.bounds()
    if plan.get("round") != "M79":
        raise ValueError("report input is not the frozen M79 contract")

    plan_path = root / PLAN_PATH
    registry_path = root / "candidate-registry.json"
    evaluation_plan_path = root / "evaluation-plan.json"
    completion_path = root / "evaluation-completion.json"
    registry, actor_hashes = _check_upstream(root, plan)
    evaluation_plan = read(evaluation_plan_path)
    completion = read(completion_path)
    result_path = root / RESULT_PATH
    markdown_path = root / EVIDENCE_PATH
    spec_path = root / READING_SPEC_PATH
    output_path = root / READING_HTML_PATH
    targets = [result_path, markdown_path, spec_path, output_path,
               output_path.with_suffix(".audit.html"), output_path.with_suffix(".reading.md"),
               output_path.with_suffix(".reading-receipt.json")]
    existing = [str(path.relative_to(root)) for path in targets if path.exists()]
    if existing:
        raise FileExistsError("preserve existing M79 report revision: " + ", ".join(existing))

    rows, missing, caps, shards, retries = _collect_rows(root, plan, registry,
                                                         evaluation_plan, completion)
    if len(rows) + len(missing) + len(caps) != plan["evaluation"]["logical_attempts"]:
        raise ValueError("M79 report identities do not balance to the frozen evaluation count")

    metrics, rust_receipts, replay_audit = _rust_metrics(root, rows)
    pairs = _pair_rows(plan, rows, metrics)
    statistics = prism_m79_statistics.analyze(plan, rows)
    completed = len(rows)
    planned_games = plan["evaluation"]["logical_attempts"]

    source_hashes = {
        "execution_plan": digest(plan_path),
        "execution": digest(root / "execution.json"),
        "candidate_registry": digest(registry_path),
        "candidate_audit": digest(root / "audits" / "a" / "audit.json"),
        "evaluation_plan": digest(evaluation_plan_path),
        "evaluation_completion": digest(completion_path),
        "report_builder": digest(Path(__file__)),
        "reading_adapter": digest(Path(__file__).with_name("prism_m79_reading.py")),
    }
    names = _name_map(plan, registry)
    gate_status = statistics["mainline_recommendation"]["status"]
    grid = dict(planned_games=planned_games, completed_games=completed,
                truncated_games=len(caps), missing_games=len(missing),
                status="COMPLETE" if not missing and not caps else "INCOMPLETE")
    result = dict(
        format="prism-m79-mainline-result-v1", round="M79",
        status="RESULTS_READY" if grid["status"] == "COMPLETE" else "RESULTS_READY_INCOMPLETE",
        question=plan["question"], headline=f"M79独立评测完成{completed}/{planned_games}局；主线推荐门为{gate_status}。",
        planned_games=planned_games, completed_games=completed,
        grid=grid, dispatch_state=completion["status"],
        completion_receipt=completion, shards=shards, missing=missing, caps=caps,
        truncated_games=len(caps), infrastructure_retries=retries,
        candidate_sha256=actor_hashes, artifact=dict(status="FROZEN_FINAL_C20_AUDIT_PASS",
            registry_sha256=digest(registry_path), candidate_sha256=actor_hashes["a"],
            audit_sha256=source_hashes["candidate_audit"]),
        pairs=pairs, statistics=statistics,
        rule_replay_audit=replay_audit, rust_metric_receipts=rust_receipts,
        result_source_hashes=source_hashes,
        style=dict(status="DESCRIPTIVE_PROFILE_PENDING", reference="style-reference",
                   route="undetermined", profile_imported=False),
        next_action="继续已授权的 M79 回放画像与候选卡归档，完成桌面和窄屏像素核验后收口。",
        bounds_remaining_seconds=remaining_seconds,
        games_dispatched=0, model_forward_calls=0,
    )
    result["headline"] = f"M79独立评测完成{completed}/{planned_games}局；所有缺项与冻结端点分别列出。"
    conclusions, next_action = _verdicts(result)
    result["conclusions"] = conclusions
    result["next_action"] = next_action
    markdown_text = _markdown(result, names, source_hashes)

    _json_safe(result_path, result)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown_text, encoding="utf-8")
    spec = _reading_spec(root, result, result_path, markdown_path, plan_path,
                         registry_path, evaluation_plan_path, completion_path,
                         names, conclusions, next_action)
    _json_safe(spec_path, spec)
    from scripts.prism_m79_reading import build as render
    reading_receipt = render(spec_path, root=root, templates=template_root)
    receipt = dict(format="prism-m79-report-receipt-v1", status=result["status"],
                   result_sha256=digest(result_path), markdown_sha256=digest(markdown_path),
                   reading_spec_sha256=digest(spec_path), html_sha256=digest(output_path),
                   reading_receipt=reading_receipt, completed_games=completed,
                   planned_games=planned_games, truncated_games=len(caps),
                   missing_games=len(missing), missing_identities=len(missing),
                   mainline_recommendation=gate_status, games_dispatched=0,
                   model_forward_calls=0, pixel_visual="NOT_VERIFIED")
    return receipt


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--templates", type=Path, default=None)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.root, templates=arguments.templates),
                     ensure_ascii=False, indent=2))
