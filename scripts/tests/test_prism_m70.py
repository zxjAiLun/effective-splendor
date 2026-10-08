"""M70 contract and stage-gating checks, zero research games."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import prism_m70_prepare as prepare
from scripts import prism_m70_run as run
from scripts import prism_m70_report as report


class M70Tests(unittest.TestCase):
    def setUp(self):
        self.c = prepare.read(prepare.ROOT / prepare.CONFIG)
        self.bp = prepare.read(prepare.ROOT / prepare.ARMS["a"]["blueprint"])

    def test_fixed_budget_parent_and_no_reselection(self):
        prepare.validate(self.c, {"a": self.bp})
        parent = prepare.ROOT / self.c["assets"]["parent"]["local_path"]
        if not parent.exists():
            parent = prepare.ROOT / "inputs/parent.json"
        self.assertEqual(prepare.digest(parent), prepare.PARENT_SHA)
        self.assertEqual(self.c["training"]["games"], 1024)
        self.assertEqual(self.c["evaluation"]["total_games"], 7168)
        self.assertIn("final c4", self.c["training"]["selection"])
        self.assertEqual(self.c["resources"]["automatic_retries"], 0)

    def test_seed_and_opponent_coverage(self):
        ranges = prepare.RANGES
        for i, (lo, hi, _) in enumerate(ranges):
            for a, b, _ in ranges[i+1:]:
                self.assertGreater(max(lo, a), min(hi, b))
        jobs = [j for group in self.bp["template"]["cycles"] for j in group]
        self.assertEqual(len(jobs), 1024)
        self.assertEqual(len({j["environment_seed"] for j in jobs}), 512)
        self.assertEqual(self.c["evaluation"]["common_opponents"], prepare.OPPONENTS)
        self.assertIn("released-alpha", prepare.OPPONENTS)
        self.assertIn("heuristic", prepare.OPPONENTS)

    def test_engineering_is_separate_and_finite(self):
        bp = prepare.blueprint(prepare.read(prepare.ROOT / "benchmarks/m63-prism-control-building.train.json"),
                               {k: v["sha256"] for k, v in self.c["assets"].items()}, engineering=True)
        jobs = bp["template"]["cycles"][0]
        self.assertEqual(len(jobs), 8)
        self.assertEqual({j["environment_seed"] for j in jobs}, set(range(10000000, 10000004)))
        self.assertEqual(bp["template"]["run"]["budget"]["max_attempts"], 8)

    def test_science_drift_is_rejected(self):
        for group, key, value in (("evaluation", "common_seed_start", 1),
                                  ("evaluation", "mode", "sample"),
                                  ("base_model", "sha256", "0"*64)):
            bad = copy.deepcopy(self.c)
            bad[group][key] = value
            with self.subTest(group=group, key=key), self.assertRaises(ValueError):
                prepare.validate(bad, {"a": self.bp})
        bad = copy.deepcopy(self.bp)
        bad["template"]["cycles"][0][0]["environment_seed"] = 99
        self.c["training"]["arms"]["a"]["blueprint_identity"] = prepare.identity(bad)
        with self.assertRaisesRegex(ValueError, "schedule"):
            prepare.validate(self.c, {"a": bad})

    def test_freeze_is_once_only(self):
        with self.assertRaisesRegex(ValueError, "already frozen"):
            prepare.freeze()

    def test_source_and_config_pin_drift_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepare.write(root / prepare.CONFIG, self.c)
            prepare.write(root / "host.json", {})
            pin = dict(config_sha256="wrong", host_sha256=prepare.digest(root / "host.json"), files={})
            prepare.write(root / "execution.json", pin)
            with patch.object(run, "ROOT", root), patch.object(run, "contract", return_value=self.c):
                with self.assertRaisesRegex(ValueError, "config pin"):
                    run.verify()

    def test_stage_order_and_engineering_failure_stops_research(self):
        class Tree:
            calls = []
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def start(self, argv, **kwargs): self.calls.append(argv)
            def wait(self, **kwargs):
                return {"returncode": 1 if len(self.calls) == 2 else 0, "stop_reason": None}
        with tempfile.TemporaryDirectory() as temp, patch.object(run, "ROOT", Path(temp)), \
             patch.object(run, "verify", return_value=(self.c, {})), \
             patch.object(run, "bounds", return_value=21600), \
             patch.object(run, "digest", return_value="source"), patch.object(run, "ProcessTree", Tree):
            with self.assertRaisesRegex(ValueError, "phase failed audit-engineering"):
                run.pipeline()
            self.assertEqual(len(Tree.calls), 2)
            self.assertEqual(Tree.calls[0][-1], "engineering")
            self.assertEqual(Tree.calls[1][-1], "engineering")
            self.assertEqual(prepare.read(Path(temp) / "pipeline/status.json")["state"],
                             "FAILED_STOPPED_NO_RETRY")

    def test_paired_estimator_full_cohort_and_modes(self):
        c = copy.deepcopy(self.c)
        c["evaluation"].update(common_seed_start=1, common_seed_end=2,
                                direct_seed_start=4, direct_seed_end=5,
                                bootstrap_samples=20)
        def rows(model, opponents, seeds, score):
            return [dict(candidate=model, opponent=o, seed=s, candidate_seat=seat,
                         candidate_score=score) for o in opponents for s in seeds for seat in (0, 1)]
        base = rows("base", prepare.OPPONENTS, [1, 2], .5)
        candidate = rows("candidate", prepare.OPPONENTS, [1, 2], 1)
        direct = rows("candidate", ["parent"], [4, 5], 1)
        measurements, gates, enhanced = report.competitive(c, base, candidate, direct)
        self.assertEqual(measurements["candidate/strength_pool"]["mean"], .5)
        self.assertTrue(all(gates.values()) and all(enhanced.values()))
        candidate.pop()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            report.competitive(c, base, candidate, direct)


if __name__ == "__main__":
    unittest.main()
