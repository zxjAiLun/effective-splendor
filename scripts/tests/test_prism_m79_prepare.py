"""Zero-game validation for the frozen M79 training blueprint."""
import copy
import sys
import unittest
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from training.prism_portable.common import digest, identity, numerical_identity, package_identity, read  # noqa: E402
from scripts.prism_m79_prepare import (  # noqa: E402
    INFRA_RETRIES,
    LOGICAL_JOBS,
    OPPONENTS,
    PLAN,
    PLAN_SHA256,
    make_blueprint,
    validate,
)


class PrismM79PrepareTest(unittest.TestCase):
    def setUp(self):
        self.plan = read(ROOT / PLAN)
        self.plan_before = copy.deepcopy(self.plan)
        self.plan_file_sha = digest(ROOT / PLAN)
        self.blueprint = make_blueprint(self.plan)

    def test_identity_and_fixed_inputs_are_returned_by_zero_game_validation(self):
        result = validate(self.plan, self.blueprint)
        self.assertEqual(result["status"], "VERIFIED_ZERO_GAMES")
        self.assertEqual(result["new_games"], 0)
        self.assertEqual(result["numeric_source_identity"], numerical_identity())
        self.assertEqual(result["portable_package_identity"], package_identity())
        self.assertEqual(result["plan_sha256"], PLAN_SHA256)
        self.assertEqual(result["blueprint_identity"], identity(self.blueprint))
        self.assertEqual(result["asset_sha256"]["parent"], self.plan["assets"]["parent"]["sha256"])
        self.assertEqual(digest(ROOT / PLAN), self.plan_file_sha)
        self.assertEqual(self.plan, self.plan_before)

    def test_complete_schedule_is_unique_balanced_and_dual_seat(self):
        result = validate(self.plan, self.blueprint)
        cycles = self.blueprint["template"]["cycles"]
        jobs = [job for cycle in cycles for job in cycle]
        self.assertEqual(len(cycles), 20)
        self.assertEqual([len(cycle) for cycle in cycles], [256] * 20)
        self.assertEqual(len(jobs), LOGICAL_JOBS)
        self.assertEqual(len({job["job_id"] for job in jobs}), LOGICAL_JOBS)
        self.assertEqual({job["environment_seed"] for job in jobs}, set(range(17001000, 17003560)))
        self.assertEqual(Counter(job["opponent_id"] for job in jobs), {name: 1280 for name in OPPONENTS})
        paired = {}
        for job in jobs:
            paired.setdefault(job["environment_seed"], []).append(job)
        self.assertTrue(all(len(rows) == 2 for rows in paired.values()))
        self.assertTrue(all({row["actor"] for row in rows} == {0, 1} for rows in paired.values()))
        self.assertEqual(result["logical_jobs"], 5120)
        self.assertEqual(result["environment_seed_count"], 2560)

    def test_ppo_drift_is_rejected(self):
        changed = copy.deepcopy(self.blueprint)
        changed["template"]["run"]["ppo"]["lr"] *= 2
        with self.assertRaisesRegex(ValueError, "blueprint differs|PPO drift"):
            validate(self.plan, changed)

    def test_global_infrastructure_budget_preserves_logical_jobs(self):
        result = validate(self.plan, self.blueprint)
        budget = self.blueprint["template"]["run"]["budget"]
        limits = self.blueprint["template"]["limits"]
        self.assertEqual(budget["max_jobs"], 5120)
        self.assertEqual(budget["max_attempts"], 5184)
        self.assertEqual(limits["max_infra_retries"], INFRA_RETRIES)
        self.assertEqual(limits["max_physical_decisions"], 5184 * 256)
        self.assertEqual(result["infra_retry_per_unfinished_logical_job"], 1)
        for field, value in (("max_jobs", 5184), ("max_attempts", 5120), ("max_decisions", 5184 * 256)):
            changed = copy.deepcopy(self.blueprint)
            changed["template"]["run"]["budget"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(self.plan, changed)
        changed = copy.deepcopy(self.blueprint)
        changed["template"]["limits"]["max_infra_retries"] = 1
        with self.assertRaises(ValueError):
            validate(self.plan, changed)
        changed = copy.deepcopy(self.blueprint)
        changed["template"]["limits"]["max_physical_decisions"] = 5120 * 256
        with self.assertRaises(ValueError):
            validate(self.plan, changed)

    def test_raw_plan_and_blueprint_source_drift_are_rejected(self):
        changed_plan = copy.deepcopy(self.plan)
        changed_plan["training"]["run_seed"] += 1
        with self.assertRaisesRegex(ValueError, "plan object drift"):
            make_blueprint(changed_plan)
        changed = copy.deepcopy(self.blueprint)
        changed["weight_hashes"]["parent"] = "0" * 64
        with self.assertRaises(ValueError):
            validate(self.plan, changed)


if __name__ == "__main__":
    unittest.main()
