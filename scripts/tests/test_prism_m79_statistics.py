import copy
import json
from pathlib import Path
import unittest

import numpy as np

from scripts import prism_m79_statistics as stats


ROOT = Path(__file__).resolve().parents[2]


def synthetic_plan():
    plan = json.loads((ROOT / "benchmarks/m79-prism-mainline.execution-plan.json")
                      .read_text(encoding="utf-8"))
    plan = copy.deepcopy(plan)
    ev = plan["evaluation"]
    for index, opponent in enumerate(stats.COMMON_OPPONENTS):
        start = 17010000 + 10 * index
        ev["common_seed_by_opponent"][opponent] = [start, start + 1]
    for index, opponent in enumerate(stats.COVERAGE_OPPONENTS):
        start = 17020000 + 10 * index
        ev["coverage_seed_by_opponent"][opponent] = [start, start + 1]
    ev["direct"]["seed_range"] = [17030000, 17030002]
    ev["common_games_per_actor"] = 2 * len(stats.COMMON_OPPONENTS) * 2
    ev["coverage_games_per_actor"] = 2 * len(stats.COVERAGE_OPPONENTS) * 2
    ev["direct"]["logical_attempts"] = 2 * 3
    ev["logical_attempts"] = (3 * ev["common_games_per_actor"] +
                              2 * ev["coverage_games_per_actor"] +
                              ev["direct"]["logical_attempts"])
    return plan


def synthetic_rows(plan, *, direct_values=(0.75, 0.75, 0.75)):
    ev = plan["evaluation"]
    rows = []

    def add(actor, opponent, seed, seat, score):
        rows.append({
            "candidate": actor,
            "opponent": opponent,
            "seed": seed,
            "candidate_seat": seat,
            "candidate_score": score,
        })

    for opponent_index, opponent in enumerate(stats.COMMON_OPPONENTS):
        start, end = ev["common_seed_by_opponent"][opponent]
        for seed in range(start, end + 1):
            for seat in stats.SEATS:
                add("base", opponent, seed, seat, 0.5)
                if opponent == "heuristic" and seed == end:
                    candidate_score = 1.0
                elif opponent == "heuristic":
                    candidate_score = 0.5
                else:
                    candidate_score = (1.0, 0.5)[seat]
                add("a", opponent, seed, seat, candidate_score)

    for opponent in stats.COVERAGE_OPPONENTS:
        start, end = ev["coverage_seed_by_opponent"][opponent]
        for seed in range(start, end + 1):
            for seat in stats.SEATS:
                add("base", opponent, seed, seat, 0.5)
                add("a", opponent, seed, seat, (1.0, 0.5)[seat])

    start, end = ev["direct"]["seed_range"]
    for seed, score in zip(range(start, end + 1), direct_values):
        for seat in stats.SEATS:
            if score == 0.75:
                seat_score = (1.0, 0.5)[seat]
            else:
                seat_score = score
            add("a", "parent", seed, seat, seat_score)
    return rows


class PrismM79StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.plan = synthetic_plan()

    def test_complete_competitive_grid_passes_without_style_reference_rows(self):
        rows = synthetic_rows(self.plan)
        result = stats.analyze(self.plan, rows)

        self.assertEqual(result["endpoints"]["common_delta"]["status"], "COMPLETE")
        self.assertAlmostEqual(result["endpoints"]["common_delta"]["estimate"], 0.25)
        self.assertAlmostEqual(result["endpoints"]["direct_parent"]["estimate"], 0.75)
        self.assertEqual(result["families"]["enhancement"]["status"], "PASS")
        self.assertEqual(result["families"]["latest_coverage_retention"]["status"], "PASS")
        self.assertEqual(result["families"]["old_anchor_retention"]["status"], "PASS")
        self.assertEqual(result["mainline_recommendation"]["status"], "PASS")

        refs = [row for row in result["grid_completeness"]
                if row["candidate"] == "style-reference"]
        self.assertEqual(len(refs), 6)
        self.assertTrue(all(row["status"] == "INCOMPLETE" for row in refs))
        self.assertEqual(
            [row["opponent"] for row in
             result["endpoints"]["common_delta"]["completeness"]["by_opponent"]],
            list(stats.COMMON_OPPONENTS),
        )

    def test_missing_rows_stay_incomplete_and_diagnostics_keep_opponents_equally_weighted(self):
        rows = synthetic_rows(self.plan, direct_values=(0.0, 0.5, 1.0))
        common_start, common_end = self.plan["evaluation"]["common_seed_by_opponent"]["heuristic"]
        rows = [row for row in rows if not (
            row["opponent"] == "heuristic" and row["seed"] == common_end
        )]
        latest_start, _ = self.plan["evaluation"]["coverage_seed_by_opponent"]["latest-alpha"]
        rows = [row for row in rows if not (
            row["candidate"] == "a" and row["opponent"] == "latest-alpha"
            and row["seed"] == latest_start and row["candidate_seat"] == 0
        )]

        result = stats.analyze(self.plan, rows)
        common = result["endpoints"]["common_delta"]
        self.assertEqual(common["status"], "INCOMPLETE")
        self.assertIsNone(common["estimate"])
        self.assertIsNone(common["interval"])
        self.assertEqual(common["gates"]["enhancement"], "INCOMPLETE")
        self.assertLess(common["worst_best_point_bounds"]["worst"],
                        common["worst_best_point_bounds"]["best"])
        # One of six opponents has one usable block at delta 0; the other five
        # have two blocks at delta .25. Equal opponent weighting is 0.2083...;
        # pooling all eleven remaining blocks would incorrectly give 0.2272...
        self.assertAlmostEqual(common["diagnostic_completed_only"]["estimate"], 0.25 * 5 / 6)

        latest = result["endpoints"]["latest-alpha"]
        self.assertEqual(latest["status"], "INCOMPLETE")
        self.assertEqual(latest["completeness"]["missing_rows"], 1)
        self.assertEqual(latest["gates"]["retention"], "INCOMPLETE")
        self.assertEqual(result["families"]["latest_coverage_retention"]["status"], "INCOMPLETE")
        self.assertEqual(result["endpoints"]["direct_parent"]["status"], "COMPLETE")
        self.assertEqual(result["endpoints"]["direct_parent"]["estimate"], 0.5)

        # The incomplete common endpoint still consumes its declared RNG slots.
        # Direct-parent's bootstrap therefore starts at the frozen second endpoint.
        rng = np.random.Generator(np.random.PCG64(stats.BOOTSTRAP_SEED))
        rng.integers(0, 2, size=(stats.BOOTSTRAP_SAMPLES, 6, 2), dtype=np.int64)
        indices = rng.integers(0, 3, size=(stats.BOOTSTRAP_SAMPLES, 3), dtype=np.int64)
        direct_bootstrap = np.asarray([0.0, 0.5, 1.0])[indices].mean(axis=1)
        expected = np.quantile(direct_bootstrap, [0.025, 0.975], method="linear")
        direct_interval = result["endpoints"]["direct_parent"]["interval"]["ordinary_95"]
        self.assertAlmostEqual(direct_interval["lower"], float(expected[0]))
        self.assertAlmostEqual(direct_interval["upper"], float(expected[1]))

    def test_duplicate_identity_illegal_actor_and_out_of_range_seed_are_rejected(self):
        row = synthetic_rows(self.plan)[0]
        with self.assertRaisesRegex(ValueError, "duplicate candidate/opponent/seed/seat"):
            stats.analyze(self.plan, [row, dict(row)])

        illegal_actor = dict(row, candidate="style-reference", opponent="latest-alpha")
        with self.assertRaisesRegex(ValueError, "illegal candidate/opponent identity"):
            stats.analyze(self.plan, [illegal_actor])

        start, _ = self.plan["evaluation"]["common_seed_by_opponent"]["heuristic"]
        out_of_range = dict(row, seed=start - 1)
        with self.assertRaisesRegex(ValueError, "outside declared identity grid"):
            stats.analyze(self.plan, [out_of_range])

        illegal_seat = dict(row, candidate_seat=2)
        with self.assertRaisesRegex(ValueError, "candidate_seat must be 0 or 1"):
            stats.analyze(self.plan, [illegal_seat])

        illegal_score = dict(row, candidate_score=0.25)
        with self.assertRaisesRegex(ValueError, "candidate_score must be 0, 0.5, or 1"):
            stats.analyze(self.plan, [illegal_score])

        changed_plan = copy.deepcopy(self.plan)
        changed_plan["statistics"]["bootstrap_samples"] += 1
        with self.assertRaisesRegex(ValueError, "bootstrap sample count drift"):
            stats.analyze(changed_plan, [row])


if __name__ == "__main__":
    unittest.main()
