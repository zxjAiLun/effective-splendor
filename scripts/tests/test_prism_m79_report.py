"""Focused regressions for M79 report accounting and result-bound reading."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import prism_m79_reading as reading
from scripts import prism_m79_report as report


ROOT = Path(__file__).resolve().parents[2]


def _json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dispatch_fixture(root: Path):
    plan = json.loads((ROOT / report.PLAN_PATH).read_text(encoding="utf-8"))
    plan_path = root / report.PLAN_PATH
    _json(plan_path, plan)
    registry_path = root / "candidate-registry.json"
    _json(registry_path, {"fixture": "registry"})
    shards = []
    for shard in report._planned_shards(plan):
        output = root / "shards" / shard["label"]
        output.mkdir(parents=True)
        manifest = output / "manifest.json"
        _json(manifest, {"label": shard["label"]})
        shards.append({
            "label": shard["label"],
            "category": "independent",
            "output": output.relative_to(root).as_posix(),
            "planned_games": shard["planned_games"],
            "manifest_sha256": _hash(manifest),
        })
    evaluation_plan = {
        "format": "prism-m79-bounded-shards-v1",
        "shards": shards,
        "total_games": plan["evaluation"]["logical_attempts"],
        "plan_sha256": _hash(plan_path),
        "candidate_registry_sha256": _hash(registry_path),
    }
    evaluation_path = root / "evaluation-plan.json"
    _json(evaluation_path, evaluation_plan)
    completion = {
        "status": "FINISHED_WITH_EXPLICIT_MISSINGNESS",
        "shards": [],
        "completed_games": 0,
        "truncated_games": 0,
        "plan_sha256": _hash(evaluation_path),
    }
    return plan, registry_path, evaluation_plan, completion


def _metric(games: int) -> dict:
    return {
        "games": games, "wins": games, "ties": 0, "losses": 0,
        "score_rate": 1.0, "mean_prestige": 15.0,
    }


def _reading_fixture(root: Path):
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "prism_m79_report.py").write_bytes((ROOT / "scripts/prism_m79_report.py").read_bytes())
    (scripts / "prism_m79_reading.py").write_bytes((ROOT / "scripts/prism_m79_reading.py").read_bytes())
    contract = json.loads((ROOT / report.PLAN_PATH).read_text(encoding="utf-8"))
    contract_path = root / report.PLAN_PATH
    _json(contract_path, contract)
    registry_path = root / "candidate-registry.json"
    _json(registry_path, {"models": {"a": {"sha256": "a" * 64}}})
    evaluation_path = root / "evaluation-plan.json"
    _json(evaluation_path, {
        "total_games": contract["evaluation"]["logical_attempts"],
        "plan_sha256": _hash(contract_path),
        "candidate_registry_sha256": _hash(registry_path),
    })
    completion_path = root / "evaluation-completion.json"

    pairs = {}
    for shard in report._planned_shards(contract):
        key = (shard["candidate"], shard["opponent"])
        pairs[key] = pairs.get(key, 0) + shard["planned_games"]
    pair_rows = []
    for (candidate, opponent), games in sorted(pairs.items()):
        opponent_metric = _metric(games)
        opponent_metric.update(wins=0, losses=games, score_rate=0.0, mean_prestige=12.0)
        seats = [
            {"candidate_seat": seat, "games": games // 2,
             "candidate": _metric(games // 2), "opponent": _metric(games // 2)}
            for seat in (0, 1)
        ]
        pair_rows.append({
            "candidate": candidate, "opponent": opponent,
            "candidate_metrics": _metric(games), "opponent_metrics": opponent_metric,
            "seats": seats, "planned_games": games, "completed_games": games,
            "missing_games": 0, "status": "COMPLETE",
        })
    planned = contract["evaluation"]["logical_attempts"]
    conclusions = [
        {"label": "产物", "value": "固定", "explanation": "身份已核验。"},
        {"label": "竞技", "value": "PASS", "explanation": "冻结端点已列。"},
        {"label": "风格", "value": "描述性", "explanation": "画像单独交付。"},
    ]
    result_path = root / report.RESULT_PATH
    result = {
        "format": "prism-m79-mainline-result-v1", "round": "M79",
        "status": "RESULTS_READY", "planned_games": planned, "completed_games": planned,
        "truncated_games": 0, "missing": [], "caps": [], "pairs": pair_rows,
        "grid": {"planned_games": planned, "completed_games": planned,
                 "truncated_games": 0, "missing_games": 0, "status": "COMPLETE"},
        "completion_receipt": {}, "statistics": {"endpoints": {}},
        "result_source_hashes": {}, "conclusions": conclusions,
    }
    completion = {"completed_games": planned, "truncated_games": 0,
                  "plan_sha256": _hash(evaluation_path)}
    _json(completion_path, completion)
    result["completion_receipt"] = completion
    result["result_source_hashes"] = {
        "report_builder": _hash(ROOT / "scripts/prism_m79_report.py"),
        "reading_adapter": _hash(ROOT / "scripts/prism_m79_reading.py"),
        "execution_plan": _hash(contract_path),
        "candidate_registry": _hash(registry_path),
        "evaluation_plan": _hash(evaluation_path),
        "evaluation_completion": _hash(completion_path),
    }
    _json(result_path, result)
    markdown_path = root / report.EVIDENCE_PATH
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("# Evidence\n\n| Pair | State |\n| --- | --- |\n", encoding="utf-8")
    spec = {
        "format": "prism-m79-bounded-reading-v1",
        "result": result_path.relative_to(root).as_posix(), "result_sha256": _hash(result_path),
        "markdown": markdown_path.relative_to(root).as_posix(), "markdown_sha256": _hash(markdown_path),
        "contract": contract_path.relative_to(root).as_posix(), "contract_sha256": _hash(contract_path),
        "candidate_registry": registry_path.relative_to(root).as_posix(),
        "candidate_registry_sha256": _hash(registry_path),
        "evaluation_plan": evaluation_path.relative_to(root).as_posix(),
        "evaluation_plan_sha256": _hash(evaluation_path),
        "evaluation_completion": completion_path.relative_to(root).as_posix(),
        "evaluation_completion_sha256": _hash(completion_path),
        "output": "docs/prism/report.html", "names": {k: k for k in ("a", "base", "style-reference")},
        "story": {
            "round": "M79", "title": "M79 report fixture", "headline": "Frozen fixture.",
            "identity": "a compared with fixed references.",
            "interpretation": "Missing results retain their original status.",
            "next": "继续已授权的画像与归档。", "conclusions": conclusions,
        },
    }
    spec_path = root / "benchmarks/reports/m79-reading.json"
    _json(spec_path, spec)
    return spec_path, result_path, result


class PrismM79ReportTests(unittest.TestCase):
    def test_evaluation_plan_rejects_contract_registry_and_count_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, registry_path, evaluation, _ = _dispatch_fixture(root)
            self.assertEqual(len(report._check_evaluation_plan(root, plan, {}, evaluation)[0]), 192)

            bad = copy.deepcopy(evaluation)
            bad["plan_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "contract hash drift"):
                report._check_evaluation_plan(root, plan, {}, bad)
            bad = copy.deepcopy(evaluation)
            bad["candidate_registry_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "registry hash drift"):
                report._check_evaluation_plan(root, plan, {}, bad)
            bad = copy.deepcopy(evaluation)
            bad["total_games"] -= 1
            with self.assertRaisesRegex(ValueError, "count/schema drift"):
                report._check_evaluation_plan(root, plan, {}, bad)
            self.assertTrue(registry_path.is_file())

    def test_undispatched_config_shards_report_every_identity_without_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, registry_path, evaluation, completion = _dispatch_fixture(root)
            _json(root / "evaluation-completion.json", completion)
            with mock.patch.object(report, "_validate_shard_config", return_value=None), \
                    mock.patch.object(report.bounded, "inspect", side_effect=AssertionError("no ledger to inspect")):
                rows, missing, caps, shards, retries = report._collect_rows(
                    root, plan, json.loads(registry_path.read_text(encoding="utf-8")),
                    evaluation, completion)
            self.assertEqual((rows, caps, retries), ([], [], []))
            self.assertEqual(len(missing), 12288)
            self.assertEqual(len({(r["candidate"], r["opponent"], r["seed"], r["candidate_seat"])
                                  for r in missing}), 12288)
            self.assertTrue(all(r["reason"] == "NO_LEDGER_NOT_DISPATCHED" for r in missing))
            self.assertEqual(sum(s["missing_games"] for s in shards), 12288)

    def test_dispatch_artifacts_without_ledger_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, registry_path, evaluation, completion = _dispatch_fixture(root)
            _json(root / "evaluation-completion.json", completion)
            first = Path(evaluation["shards"][0]["output"])
            (root / first / "games").mkdir()
            with mock.patch.object(report, "_validate_shard_config", return_value=None):
                with self.assertRaisesRegex(ValueError, "dispatch artifacts without a ledger"):
                    report._collect_rows(root, plan,
                                         json.loads(registry_path.read_text(encoding="utf-8")),
                                         evaluation, completion)

    def test_build_writes_result_schema_with_unpacked_actor_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = json.loads((ROOT / report.PLAN_PATH).read_text(encoding="utf-8"))
            _json(root / report.PLAN_PATH, plan)
            registry = {"status": "FROZEN_FINAL_C20_BEFORE_EVALUATION",
                        "models": {"a": {"display_name": "fixed c20"}}}
            registry_path = root / "candidate-registry.json"
            _json(registry_path, registry)
            _json(root / "evaluation-plan.json", {"fixture": "plan"})
            completion = {"fixture": "completion", "status": "FINISHED_WITH_EXPLICIT_MISSINGNESS"}
            _json(root / "evaluation-completion.json", completion)
            _json(root / "execution.json", {"fixture": "execution"})
            _json(root / "audits/a/audit.json", {"fixture": "audit"})
            actor_hashes = {"a": "a" * 64, "base": "b" * 64,
                            "style-reference": "c" * 64}
            incomplete = [{}] * plan["evaluation"]["logical_attempts"]
            statistics = {
                "mainline_recommendation": {"status": "INCOMPLETE"},
                "endpoints": {}, "opponent_descriptives": [],
            }

            def render(spec_path, root=None, templates=None):
                output = Path(root) / report.READING_HTML_PATH
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("<!doctype html><p>fixture</p>", encoding="utf-8")
                return {"pixel_visual": "NOT_VERIFIED"}

            with (mock.patch.object(report.prism_m79_run, "verify", return_value=(plan, {})),
                  mock.patch.object(report.prism_m79_run, "bounds", return_value=3600.0),
                  mock.patch.object(report, "_check_upstream", return_value=(registry, actor_hashes)),
                  mock.patch.object(report, "_collect_rows", return_value=([], incomplete, [], [], [])),
                  mock.patch.object(report, "_rust_metrics", return_value=({}, [], "NOT_RUN_NO_COMPLETED_REPLAYS")),
                  mock.patch.object(report, "_pair_rows", return_value=[]),
                  mock.patch.object(report.prism_m79_statistics, "analyze", return_value=statistics),
                  mock.patch.object(report, "_markdown", return_value="# fixture evidence\n"),
                  mock.patch.object(report, "_reading_spec", return_value={"format": "fixture"}),
                  mock.patch("scripts.prism_m79_reading.build", side_effect=render)):
                receipt = report.build(root)

            result_path = root / report.RESULT_PATH
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["format"], "prism-m79-mainline-result-v1")
            self.assertEqual(result["candidate_sha256"], actor_hashes)
            self.assertEqual(result["planned_games"], 12288)
            self.assertEqual(result["completed_games"], 0)
            self.assertEqual(result["grid"]["missing_games"], 12288)
            self.assertEqual(result["games_dispatched"], 0)
            self.assertEqual(result["model_forward_calls"], 0)
            self.assertEqual(receipt["status"], "RESULTS_READY_INCOMPLETE")

    def test_reading_rejects_result_hash_and_count_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path, result_path, result = _reading_fixture(root)
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            spec["result_sha256"] = "0" * 64
            _json(spec_path, spec)
            with self.assertRaisesRegex(ValueError, "input hash drift: result"):
                reading.validate(spec_path, root)

            spec["result_sha256"] = _hash(result_path)
            result["grid"]["completed_games"] -= 1
            _json(result_path, result)
            spec["result_sha256"] = _hash(result_path)
            _json(spec_path, spec)
            with self.assertRaisesRegex(ValueError, "counts do not balance"):
                reading.validate(spec_path, root)

    def test_common_template_render_is_bound_and_lists_three_conclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path, result_path, _ = _reading_fixture(root)
            receipt = reading.build(spec_path, root=root, templates=ROOT / "scripts/templates")
            output = root / "docs/prism/report.html"
            text = output.read_text(encoding="utf-8")
            self.assertIn("prism-m79-human-reading-payload-v1", text)
            self.assertIn("M79 report fixture", text)
            self.assertIn("style-reference", text)
            self.assertIn("metric-win better", text)
            self.assertIn("显示持平不强调", text)
            self.assertNotIn("新对局：0", text)
            self.assertNotIn("模型forward：0", text)
            self.assertNotIn("像素视觉：NOT_VERIFIED", text)
            self.assertEqual(receipt["conclusions"], ["产物", "竞技", "风格"])
            self.assertEqual(receipt["result_sha256"], _hash(result_path))
            self.assertEqual(receipt["games_dispatched"], 0)
            self.assertEqual(receipt["model_forward_calls"], 0)
            self.assertEqual(receipt["pixel_visual"], "NOT_VERIFIED")

    def test_report_entrypoint_has_no_game_or_model_execution_path(self):
        tree = ast.parse((ROOT / "scripts/prism_m79_report.py").read_text(encoding="utf-8"))
        build = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build")
        calls = {node.func.id if isinstance(node.func, ast.Name) else
                 node.func.attr if isinstance(node.func, ast.Attribute) else ""
                 for node in ast.walk(build) if isinstance(node, ast.Call)}
        self.assertFalse(calls & {"dispatch", "evaluate", "forward", "Popen"})
        source = (ROOT / "scripts/prism_m79_report.py").read_text(encoding="utf-8")
        self.assertNotIn("prism_m79_evaluate", source)
        self.assertNotIn("import torch", source)
        self.assertIn("games_dispatched=0", source)
        self.assertIn("model_forward_calls=0", source)


if __name__ == "__main__":
    unittest.main()
