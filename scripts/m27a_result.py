#!/usr/bin/env python3
"""Build and verify the M27A formal result from the accepted raw reports.

The result's selected decision is deliberately not an input to this script.
Both the curve and the stable-region decision are recomputed from the raw
EvaluationReportV1 records each time it runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ACCEPTED_ROOT = ROOT / "local-artifacts/m27a-formal-execution-v1/eval-reports-accepted"
BUDGETS = [16, 24, 32, 48, 64, 96, 128]
PAIRS = ["s2_vs_m07", "s1_vs_m07"]
SEEDS = list(range(301001, 301033))
SOURCE_COMMIT = "b3440d42e059888f939de31232c89b4141248e81"
EXECUTION_BINDING_COMMIT = "27455cb6935902db1aab4692f42f880a3ca13364"
BINARY_SHA256 = "5003a58db33ffcd85fc0fc6a1edfb59dfb5cb9abf396c7c8a2b98f4b0017f56e"
RESULT_REVIEW_BASIS_COMMIT = "e5f5dc616decb04cb43b9d060c8183487ec3e060"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_plan_hash(plan: dict[str, Any]) -> str:
    encoded = json.dumps(plan, ensure_ascii=False, separators=(",", ":")).encode()
    return sha256_bytes(encoded)


def ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def ceil_sqrt(value: int) -> int:
    root = math.isqrt(value)
    return root if root * root == value else root + 1


def score_bps(wins: int, ties: int, losses: int) -> int:
    completed = wins + ties + losses
    assert completed > 0
    return (10000 * (wins * 2 + ties)) // (2 * completed)


def score_margin_bps(blocks: int) -> int:
    return ceil_sqrt(ceil_div(150000000, blocks))


def anchor_margin_bps(blocks: int) -> int:
    return ceil_sqrt(ceil_div(600000000, blocks))


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def artifact_ref(path: Path) -> dict[str, str]:
    return {"path": relative(path), "sha256": sha256_file(path)}


def expected_agent_ids(pair: str) -> tuple[str, str]:
    candidate = "m27a-s2-candidate" if pair == "s2_vs_m07" else "m27a-s1-candidate"
    return candidate, "m07-champion"


def wtl_for_record(record: dict[str, Any], candidate_id: str) -> tuple[str, int]:
    outcome = record["outcome"]
    assert outcome["status"] == "completed"
    winners = outcome["result"]["winners"]
    assert winners in ([0, 1], [1, 0], [0], [1])
    candidate_seat = record["agent_ids_by_seat"].index(candidate_id)
    if len(winners) == 2:
        return "T", candidate_seat
    return ("W" if candidate_seat in winners else "L"), candidate_seat


def digest_files(paths: list[Path]) -> str:
    lines = []
    for path in sorted(paths):
        lines.append(f"{path.name}:{sha256_file(path)}\n")
    return sha256_bytes("".join(lines).encode())


def eval_summary(pair: str, simulations: int) -> dict[str, Any]:
    evaluation_id = f"m27a-{pair}-v1-sim{simulations}"
    plan_path = ROOT / f"benchmarks/{evaluation_id}.plan.json"
    eval_dir = ACCEPTED_ROOT / evaluation_id
    eval_report_path = eval_dir / "eval-report.json"
    plan = read_json(plan_path)
    report = read_json(eval_report_path)
    candidate_id, m07_id = expected_agent_ids(pair)

    assert plan["evaluation_id"] == evaluation_id
    assert plan["game_seeds"] == SEEDS
    assert [agent["id"] for agent in plan["agents"]] == [candidate_id, m07_id]
    assert plan["handshake_timeout_ms"] == 5000
    assert plan["move_timeout_ms"] == 30000
    assert plan["shutdown_grace_ms"] == 2000
    assert canonical_plan_hash(plan) == report["plan_hash"]
    assert report["format"] == "effective-splendor-evaluation-report"
    assert report["version"] == 1
    assert report["evaluation_id"] == evaluation_id
    assert report["scheduled_matches"] == 64

    records = report["records"]
    assert len(records) == 64
    counts = {"W": 0, "T": 0, "L": 0}
    by_seat = {
        0: {"W": 0, "T": 0, "L": 0},
        1: {"W": 0, "T": 0, "L": 0},
    }
    raw_records: dict[tuple[int, int], dict[str, Any]] = {}
    for index, record in enumerate(records):
        seed_index = index // 2
        rotation = index % 2
        expected_seats = [candidate_id, m07_id] if rotation == 0 else [m07_id, candidate_id]
        assert record["match_index"] == index
        assert record["seed_index"] == seed_index
        assert record["rotation"] == rotation
        assert record["agent_ids_by_seat"] == expected_seats
        assert record["game_id"] == f"{evaluation_id}-s{seed_index:06d}-r{rotation:02d}"
        assert record["outcome"]["status"] == "completed"
        outcome, candidate_seat = wtl_for_record(record, candidate_id)
        counts[outcome] += 1
        by_seat[candidate_seat][outcome] += 1
        raw_records[(seed_index, rotation)] = {
            "outcome": outcome,
            "candidate_seat": candidate_seat,
        }

    report_candidate = next(agent for agent in report["agents"] if agent["agent_id"] == candidate_id)
    candidate_faults = report_candidate["faults_caused"]
    assert candidate_faults == 0
    assert all(agent["aborted_matches"] == 0 for agent in report["agents"])

    report_files = sorted((eval_dir / "matches").glob("*.report.json"))
    replay_files = sorted((eval_dir / "matches").glob("*.replay.json"))
    assert len(report_files) == 64
    assert len(replay_files) == 64
    assert [path.name for path in report_files] == [f"match-{i:06d}.report.json" for i in range(64)]
    assert [path.name for path in replay_files] == [f"match-{i:06d}.replay.json" for i in range(64)]

    margin = score_margin_bps(32)
    center = score_bps(counts["W"], counts["T"], counts["L"])
    seat_split = {}
    for seat in (0, 1):
        seat_counts = by_seat[seat]
        seat_split[f"seat_{seat}"] = {
            "scheduled_matches": 32,
            "completed_matches": sum(seat_counts.values()),
            "aborted_matches": 0,
            "wins": seat_counts["W"],
            "ties": seat_counts["T"],
            "losses": seat_counts["L"],
            "center_bps": score_bps(seat_counts["W"], seat_counts["T"], seat_counts["L"]),
        }

    return {
        "evaluation_id": evaluation_id,
        "pair": pair,
        "simulations": simulations,
        "realized_plan_path": relative(plan_path),
        "realized_plan_file_sha256": sha256_file(plan_path),
        "plan_hash": report["plan_hash"],
        "eval_report_path": relative(eval_report_path),
        "eval_report_file_sha256": sha256_file(eval_report_path),
        "scheduled_matches": 64,
        "completed_matches": 64,
        "aborted_matches": 0,
        "candidate_faults": candidate_faults,
        "raw_wtl": {
            "wins": counts["W"],
            "ties": counts["T"],
            "losses": counts["L"],
        },
        "center_bps": center,
        "margin_bps": margin,
        "lower_bps": max(0, center - margin),
        "upper_bps": min(10000, center + margin),
        "seat_rotation_split": seat_split,
        "report_files": 64,
        "report_files_sha256_digest": digest_files(report_files),
        "replay_files": 64,
        "replay_files_sha256_digest": digest_files(replay_files),
        "_raw_records": raw_records,
    }


def public_eval_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if not key.startswith("_")}


def paired_blocks(s2: dict[str, Any], s1: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = []
    for seed_index, seed in enumerate(SEEDS):
        def block(pair_summary: dict[str, Any]) -> dict[str, Any]:
            counts = {"W": 0, "T": 0, "L": 0}
            for rotation in (0, 1):
                counts[pair_summary["_raw_records"][(seed_index, rotation)]["outcome"]] += 1
            return {
                "raw_wtl": {
                    "wins": counts["W"],
                    "ties": counts["T"],
                    "losses": counts["L"],
                },
                "score_bps": score_bps(counts["W"], counts["T"], counts["L"]),
            }

        s2_block = block(s2)
        s1_block = block(s1)
        blocks.append(
            {
                "seed_index": seed_index,
                "game_seed": seed,
                "s2_vs_m07": s2_block,
                "s1_vs_m07": s1_block,
                "anchor_block_delta_bps": s2_block["score_bps"] - s1_block["score_bps"],
            }
        )
    return blocks


def anchor_summary(s2: dict[str, Any], s1: dict[str, Any]) -> dict[str, Any]:
    blocks = paired_blocks(s2, s1)
    assert len(blocks) == 32
    delta_sum = sum(block["anchor_block_delta_bps"] for block in blocks)
    completed_blocks = len(blocks)
    center = delta_sum // completed_blocks
    margin = anchor_margin_bps(completed_blocks)
    return {
        "completed_paired_seed_blocks": completed_blocks,
        "anchor_block_delta_sum_bps": delta_sum,
        "center_bps": center,
        "margin_bps": margin,
        "lower_bps": max(-10000, center - margin),
        "upper_bps": min(10000, center + margin),
        "paired_blocks": blocks,
    }


def choose_region(curve: list[dict[str, Any]]) -> tuple[int | None, dict[str, Any] | None]:
    for start in range(len(curve)):
        if not curve[start]["eligibility"]["eligible"]:
            continue
        minimum = maximum = curve[start]["matched_anchor"]["center_bps"]
        for end in range(start + 1, len(curve)):
            current = curve[end]
            previous = curve[end - 1]
            if not current["eligibility"]["eligible"]:
                break
            if abs(current["matched_anchor"]["center_bps"] - previous["matched_anchor"]["center_bps"]) >= 2000:
                break
            minimum = min(minimum, current["matched_anchor"]["center_bps"])
            maximum = max(maximum, current["matched_anchor"]["center_bps"])
            if maximum - minimum >= 2000:
                break
            if end - start + 1 >= 3:
                return curve[start]["simulations"], {
                    "start_budget": curve[start]["simulations"],
                    "end_budget": current["simulations"],
                    "budget_count": end - start + 1,
                    "center_min_bps": minimum,
                    "center_max_bps": maximum,
                    "center_span_bps": maximum - minimum,
                }
    return None, None


def build_result() -> dict[str, Any]:
    config_path = ROOT / "benchmarks/m27a-search-budget-scaling-v1.json"
    bundle_path = ROOT / "benchmarks/m27a-search-budget-scaling-v1.bundle.json"
    config = read_json(config_path)
    bundle = read_json(bundle_path)
    assert config["execution_authorization"] == "NOT_AUTHORIZED"
    assert bundle["authorization"]["plan_execution"] == "NOT_AUTHORIZED"

    evaluations = [eval_summary(pair, simulations) for pair in PAIRS for simulations in BUDGETS]
    bundle_cells = {cell["evaluation_id"]: cell for cell in bundle["cells"]}
    assert set(bundle_cells) == {item["evaluation_id"] for item in evaluations}
    for item in evaluations:
        cell = bundle_cells[item["evaluation_id"]]
        assert cell["plan_path"] == item["realized_plan_path"]
        assert cell["plan_file_sha256"] == item["realized_plan_file_sha256"]
        assert cell["plan_hash"] == item["plan_hash"]
    by_key = {(item["pair"], item["simulations"]): item for item in evaluations}
    curve = []
    for simulations in BUDGETS:
        s2 = by_key[("s2_vs_m07", simulations)]
        s1 = by_key[("s1_vs_m07", simulations)]
        anchor = anchor_summary(s2, s1)
        eligibility = {
            "complete_matrix": s2["completed_matches"] == 64 and s1["completed_matches"] == 64,
            "zero_aborts": s2["aborted_matches"] == 0 and s1["aborted_matches"] == 0,
            "zero_candidate_faults": s2["candidate_faults"] == 0 and s1["candidate_faults"] == 0,
            "anchor_center_min_bps": 1000,
        }
        eligibility["eligible"] = all(
            [
                eligibility["complete_matrix"],
                eligibility["zero_aborts"],
                eligibility["zero_candidate_faults"],
                anchor["center_bps"] >= eligibility["anchor_center_min_bps"],
            ]
        )
        curve.append(
            {
                "simulations": simulations,
                "s2_vs_m07": public_eval_summary(s2),
                "s1_vs_m07": public_eval_summary(s1),
                "matched_anchor": anchor,
                "eligibility": eligibility,
            }
        )

    selected_budget, stable_region = choose_region(curve)
    failed_root = ROOT / "local-artifacts/m27a-formal-execution-v1/failed-attempts"
    failed_attempts = []
    for manifest_path in sorted(failed_root.glob("attempt-*/failure-manifest.json")):
        manifest = read_json(manifest_path)
        attempt = manifest["attempt"]
        failed_attempts.append(
            {
                "path": relative(manifest_path.parent),
                "manifest_sha256": sha256_file(manifest_path),
                "status": manifest["status"],
                "scientific_evidence": manifest["scientific_evidence"],
                "formal_M27A_result": manifest["formal_M27A_result"],
                "plan": manifest["plan"],
                "completed_matches": attempt["completed_matches"],
                "aborted_matches": attempt["aborted_matches"],
                "candidate_faults": attempt["candidate_faults"],
                "eval_report_sha256": attempt["eval_report_sha256"],
                "rerun_same_frozen_plan": manifest["rerun_policy"]["same_frozen_plan_required"],
                "plan_or_timeout_modified": manifest["rerun_policy"]["plan_or_timeout_modified"],
                "binary_or_checkpoint_modified": manifest["rerun_policy"]["binary_or_checkpoint_modified"],
            }
        )

    runtime_snapshot = ROOT / "local-artifacts/m27a-runtime-freeze-2026-08-18/runtime-snapshot.json"
    smoke_manifest = ROOT / "local-artifacts/m27a-runtime-freeze-2026-08-18/smoke-manifest.json"
    wrapper = ROOT / "local-artifacts/m27a-runtime-freeze-2026-08-18/run-m27a-runtime-smoke.sh"
    binary = ROOT / "target/debug/splendor"
    execution_log = ROOT / "local-artifacts/m27a-formal-execution-v1/eval-reports-pending-v1.execution.log"
    retry_log = ROOT / "local-artifacts/m27a-formal-execution-v1/eval-reports-rerun-3/m27a-s2_vs_m07-v1-sim32.execution.log"
    assert sha256_file(binary) == BINARY_SHA256

    return {
        "format": "effective-splendor-m27a-search-budget-scaling-result",
        "version": 1,
        "status": "ACCEPTED",
        "milestone": "M27A",
        "generated_on": "2026-08-18",
        "review": {
            "status": "ACCEPTED",
            "review_basis_commit": RESULT_REVIEW_BASIS_COMMIT,
            "findings": {"P0": 0, "P1": 0, "P2": 2},
            "p2_followups": [
                "Make the verifier read and exact-assert the frozen decision thresholds from preregistration.",
                "Optionally fold semantic verify-replay into a tracked verifier gate instead of relying only on external validation.",
            ],
            "downstream_authorization": "No downstream milestone is authorized by this acceptance.",
        },
        "authorization": {
            "arena_execution": "AUTHORIZED",
            "authorization_basis_source_commit": SOURCE_COMMIT,
            "runtime_smoke_binding_commit": EXECUTION_BINDING_COMMIT,
            "promotion": "NONE",
        },
        "preregistration": {
            "path": relative(config_path),
            "revision": config["revision"],
            "status": "ACCEPTED/FROZEN",
            "sha256": sha256_file(config_path),
        },
        "materialization_bundle": {
            "path": relative(bundle_path),
            "revision": bundle["revision"],
            "sha256": sha256_file(bundle_path),
        },
        "runtime": {
            "source_commit": SOURCE_COMMIT,
            "execution_binding_commit": EXECUTION_BINDING_COMMIT,
            "binary_path": relative(binary),
            "binary_sha256": sha256_file(binary),
            "wrapper": artifact_ref(wrapper),
            "runtime_snapshot": artifact_ref(runtime_snapshot),
            "reviewed_smoke_manifest": artifact_ref(smoke_manifest),
            "pythonpath_exported": False,
        },
        "matrix": {
            "candidate_pairs": PAIRS,
            "simulations": BUDGETS,
            "game_seeds": SEEDS,
            "game_seed_count": 32,
            "seat_rotations": 2,
            "plans": 14,
            "matches_per_plan": 64,
            "total_matches": 896,
            "game_seeds_sha256": bundle["matrix"]["game_seeds_sha256"],
        },
        "execution": {
            "status": "VERIFIED",
            "accepted_output_root": relative(ACCEPTED_ROOT),
            "scheduled_matches": 896,
            "completed_matches": 896,
            "aborted_matches": 0,
            "candidate_faults": 0,
            "eval_report_files": 896,
            "replay_files": 896,
            "execution_log": artifact_ref(execution_log),
            "sim32_exact_retry_log": artifact_ref(retry_log),
            "failed_attempts_preserved": True,
            "invalid_attempts_excluded_from_scientific_evidence": True,
            "failed_attempts": failed_attempts,
        },
        "evaluations": [public_eval_summary(item) for item in evaluations],
        "curve": curve,
        "decision": {
            "contract": "effective-splendor-m27a-stable-operating-region-v2",
            "decision_mode": "diagnostic_practical_center",
            "ordered_budgets": BUDGETS,
            "eligible_budgets": [
                point["simulations"] for point in curve if point["eligibility"]["eligible"]
            ],
            "stable_region": stable_region,
            "selected_budget": selected_budget,
            "decision": "M27A_STABLE_REGION_SELECTED" if selected_budget is not None else "M27A_INCONCLUSIVE",
            "decision_recomputed_from_raw_reports": True,
            "higher_simulations_not_preferred_by_default": True,
            "promotion_authorization": "NONE",
            "champion_unchanged": "m07-champion",
            "m25_authorized": False,
            "m26_authorized": False,
            "m28_authorized": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write the tracked result JSON")
    parser.add_argument(
        "--result",
        type=Path,
        default=ROOT / "benchmarks/m27a-search-budget-scaling-v1.result.json",
    )
    args = parser.parse_args()
    expected = build_result()
    if args.write:
        args.result.write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"WROTE {args.result}")
        return 0

    actual = read_json(args.result)
    if actual != expected:
        print("M27A_RESULT_VERIFY FAIL: tracked result differs from raw-report recomputation")
        return 1
    decision = expected["decision"]
    execution = expected["execution"]
    print(
        "M27A_RESULT_VERIFY PASS: "
        f"{execution['completed_matches']}/{expected['matrix']['total_matches']} matches, "
        f"{execution['aborted_matches']} abort, {execution['candidate_faults']} candidate_fault, "
        f"decision={decision['decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
