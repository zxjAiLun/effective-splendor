"""M61 pairing and initialization invariants, without new arena games."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("m61_prepare", ROOT / "scripts/prism_balance_ab_prepare_m61.py")
m61 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m61)


class M61PrepareTests(unittest.TestCase):
    def setUp(self):
        self.m60 = m61.read(ROOT / "benchmarks/m60-prism-alpha-cloud-ppo.train.json")
        self.bps = m61.build_blueprints(self.m60, {"parent": "1" * 64, "general": "2" * 64, "initial": "3" * 64})

    def test_only_authorized_numeric_difference(self):
        m61.validate_blueprints(self.bps)
        a = self.bps["alpha"]["template"]["run"]["ppo"]
        b = self.bps["balance"]["template"]["run"]["ppo"]
        self.assertEqual({key for key in a if a[key] != b[key]}, {"style_beta", "style_value_weight"})
        self.assertEqual(a, self.m60["template"]["run"]["ppo"])

    def test_learning_rate_drift_rejected(self):
        self.bps["balance"]["template"]["run"]["ppo"]["lr"] *= 2
        with self.assertRaises(ValueError):
            m61.validate_blueprints(self.bps)

    def test_opponent_and_seed_pairing_drift_rejected(self):
        self.bps["balance"]["template"]["cycles"][0][0]["environment_seed"] += 1
        with self.assertRaises(ValueError):
            m61.validate_blueprints(self.bps)

    def test_dynamic_ranges_include_direct_and_schedule(self):
        rows = m61.dynamic_seed_ranges({"acceptance": {"seed_start": 100, "seed_end": 110, "direct_seed_end": 120},
                                       "cycles": [[{"environment_seed": 300}]],
                                       "seed_reservations": [[400, 410, "held"]]}, "config")
        self.assertIn((100, 120, "config/acceptance"), rows)
        self.assertTrue(any(lo == 300 == hi for lo, hi, _ in rows))
        self.assertTrue(any(lo == 400 and hi == 410 for lo, hi, _ in rows))

    def test_actual_parent_policy_value_initialization_equal(self):
        receipt = m61.initialization_parity(ROOT / "local-artifacts/prism/alpha-v0.1.3/weights.json",
                                            self.m60["template"]["run"]["catalog_fingerprint"])
        self.assertEqual(receipt["policy_value_tensor_count"], 32)
        self.assertEqual(receipt["all_tensor_count"], 36)
        self.assertEqual(receipt["new_games"], 0)

    def test_reservation_refuses_overwrite(self):
        old = m61.ART
        try:
            with tempfile.TemporaryDirectory() as directory:
                m61.ART = Path(directory)
                with self.assertRaisesRegex(ValueError, "already reserved"):
                    m61.prepare()
        finally:
            m61.ART = old


if __name__ == "__main__":
    unittest.main()
