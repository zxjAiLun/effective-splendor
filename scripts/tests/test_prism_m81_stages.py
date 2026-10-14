from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import prism_m81_evaluate as evaluate
from scripts import prism_m81_report as report

ROOT = Path(__file__).resolve().parents[2]
PLAN = json.loads((ROOT / "benchmarks/m81-anchor-coverage.execution-plan.json").read_text(encoding="utf-8"))


class M81StageContractTests(unittest.TestCase):
    def test_markdown_uses_plan_identity_from_result_schema(self):
        result = {
            'evaluation_state': 'INCOMPLETE',
            'grid': dict(completed_games=0, planned_games=1, missing_games=1, truncated_games=1),
            'resource_budget': {},
            'statistics': {'method_screen': {'status': 'INCOMPLETE'},
                           'mainline_candidate': {'status': 'INCOMPLETE'}, 'endpoints': {}},
            'pairs': [], 'profile': {'status': 'PASS_RUST_REPLAY_VERIFIED'},
            'shards': [], 'rows': [], 'missing': [],
            'plan': {'path': 'plan.json', 'sha256': 'bound-plan-sha'},
            'source_hashes': {'execution': 'execution-sha'},
        }
        with patch.object(report, 'ENDPOINT_ORDER', ()):
            rendered = report._markdown(result)
        self.assertIn('Plan SHA256: `bound-plan-sha`', rendered)
        self.assertIn('Evaluation state:** INCOMPLETE', rendered)
        self.assertNotIn('plan', result['source_hashes'])

    def test_grid_is_14336_games_with_base_only_4096(self):
        shards = evaluate._planned_shards(PLAN)
        self.assertEqual(len(shards), 224)
        self.assertEqual(sum(row["planned_games"] for row in shards), 14336)
        self.assertEqual(sum(row["planned_games"] for row in shards if row["actor"] == "base"), 4096)
        self.assertEqual(sum(row["planned_games"] for row in shards if row["opponent"] == "parent"), 2048)

    def test_actor_environment_filter_and_pinned_python(self):
        with patch.dict(os.environ, {"M81_EVAL_ACTORS": "base"}):
            self.assertEqual(evaluate._actors_from_env(), ("base",))
        with patch.dict(os.environ, {"M81_EVAL_ACTORS": "B,base"}):
            self.assertEqual(evaluate._actors_from_env(), ("base", "B"))
        self.assertEqual(evaluate.PYTHON,
                         "/mnt/workspace/envs/splendor-m79-ppo-py312/bin/python")

    def test_projector_and_profile_sources_are_frozen(self):
        projector = ROOT / "local-artifacts/prism/m79-mainline/completion-r36/projector/prism_building_projection"
        binding = report._profile_source_bindings(ROOT, projector)
        self.assertEqual(binding["projector"]["sha256"], report.PROFILE_PROJECTOR_SHA256)
        self.assertEqual(set(binding["sources"]), set(report.PROFILE_SOURCE_SHA256))

    def test_global_cpu_admission_includes_imported_finished_baseline(self):
        from training.prism_portable.common import read, write
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "evaluation/base-heuristic-81010000"
            baseline.mkdir(parents=True)
            write(baseline / "ledger.json", {"consumed_cpu_seconds": 40.0})
            plan = {"resources": {"evaluation_cpu_seconds": 100}}
            admitted = evaluate._reserve_cpu(root, plan, "A-alpha/game-1", 30.0, read, write)
            self.assertEqual(admitted, 30.0)
            resource = read(root / "evaluation/resource-budget.json")
            self.assertEqual(resource["spent_cpu_seconds"], 40.0)
            self.assertEqual(sum(row["reserved_cpu_seconds"] for row in resource["reservations"].values()), 30.0)
            evaluate._settle_cpu(root, "A-alpha/game-1", 20.0, failed=False, read=read, write=write)
            resource = read(root / "evaluation/resource-budget.json")
            self.assertEqual(resource["spent_cpu_seconds"], 60.0)
            self.assertEqual(resource["reservations"], {})

    @staticmethod
    def _complete_rows():
        rows = []

        def score(actor, opponent, seat):
            if actor == "B" and opponent in ("heuristic", "balance", "parent"):
                return 1.0 if seat == 1 else 0.5
            return 0.5

        e = PLAN["evaluation"]
        for actor in e["actors"]:
            for opponent in e["opponents"]:
                low, high = e["seed_by_opponent"][opponent]
                for seed in range(low, high + 1):
                    for seat in (0, 1):
                        rows.append({"candidate": actor, "opponent": opponent, "seed": seed,
                                     "candidate_seat": seat, "candidate_score": score(actor, opponent, seat)})
        low, high = e["direct_parent"]["seed_range"]
        for actor in e["direct_parent"]["actors"]:
            for seed in range(low, high + 1):
                for seat in (0, 1):
                    rows.append({"candidate": actor, "opponent": "parent", "seed": seed,
                                 "candidate_seat": seat, "candidate_score": score(actor, "parent", seat)})
        return rows

    def test_frozen_statistics_gates_pass_for_constructed_complete_evidence(self):
        with patch.object(report, "BOOTSTRAP_SAMPLES", 64), patch.object(report, "BOOTSTRAP_BATCH", 32):
            result = report._statistics(self._complete_rows(), PLAN)
        self.assertEqual(result["method_screen"]["status"], "PASS")
        self.assertEqual(result["mainline_candidate"]["status"], "PASS")
        self.assertEqual(tuple(result["endpoints"]), report.ENDPOINT_ORDER)
        self.assertAlmostEqual(result["endpoints"]["B-A-targets"]["estimate"], 0.25)
        self.assertAlmostEqual(result["endpoints"]["B-base-common"]["estimate"], 1 / 12)

    def test_missing_seed_seat_blocks_gate_without_imputation(self):
        rows = self._complete_rows()
        rows.remove(next(row for row in rows if row["candidate"] == "B" and
                         row["opponent"] == "latest-alpha" and row["seed"] == 81016000 and
                         row["candidate_seat"] == 1))
        with patch.object(report, "BOOTSTRAP_SAMPLES", 64), patch.object(report, "BOOTSTRAP_BATCH", 32):
            result = report._statistics(rows, PLAN)
        endpoint = result["endpoints"]["B-A-latest-alpha"]
        self.assertEqual(endpoint["status"], "INCOMPLETE")
        self.assertIsNone(endpoint["estimate"])
        self.assertIsNone(endpoint["interval"])
        self.assertEqual(endpoint["gates"]["method_retention"], "INCOMPLETE")
        self.assertEqual(result["method_screen"]["status"], "INCOMPLETE")
        self.assertEqual(result["mainline_candidate"]["status"], "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
