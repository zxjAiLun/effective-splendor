import unittest

from scripts.prism_building_profile_diagnostic_m62 import (
    ANCHORS, aggregate, distribution, load_profiles, matched_differences, summarize, validate_profile,
)


def profile(uses=(3,), acquired=1, main_actions=24, auc=1.0, late_vp=2.0, investment_count=1):
    count = len(uses)
    invs = [{"acquired_main": acquired, "bonus_ordinal": 1,
             "credited_uses": min(count, 3), "observed_uses": count,
             "use_main_actions": list(uses), "unredeemed": count == 0,
             "censored": main_actions < 24 and count < 3}
            for _ in range(investment_count)]
    observed = investment_count * count
    credited = min(investment_count * min(count, 3), 24)
    return {
        "main_actions": main_actions,
        "investments": invs,
        "building_observed_use_units": observed,
        "building_use_units_before_global_cap": investment_count * min(count, 3),
        "building_use_units": credited, "building_utility": credited / 24,
        "early_lowvp_buys": investment_count, "redeemed_investments": investment_count * int(count > 0),
        "unredeemed_investments": investment_count * int(count == 0),
        "censored_investments": investment_count * int(main_actions < 24 and count < 3),
        "unredeemed_censored_investments": investment_count * int(main_actions < 24 and count == 0),
        "early_bonus_auc12": auc, "late_vp_bought_main13to24": late_vp,
    }


def game(candidate, opponent, seed, seat, candidate_profile, opponent_profile=None):
    opponent_profile = opponent_profile or profile(uses=(), auc=0, late_vp=0)
    profiles = [None, None]
    profiles[seat] = candidate_profile
    profiles[1 - seat] = opponent_profile
    return {"candidate": candidate, "opponent": opponent, "seed": seed,
            "candidate_seat": seat, "profiles": profiles}


class BuildingProfileDiagnosticTests(unittest.TestCase):
    def test_candidate_physical_seat_selection_and_opponent_pool(self):
        rows = load_profiles({"games": [game("beta", "heuristic-v031", 7, 1, profile((3, 5, 8)))]})
        row = rows[0]
        self.assertEqual(row["candidate_profile"]["utility"], 3 / 24)
        self.assertEqual(row["opponent_profile"]["utility"], 0)
        summaries = aggregate([dict(row, stage="development")])
        keys = {(r["role"], r["opponent_group"], r["model"]): r["summary"] for r in summaries}
        self.assertEqual(keys[("candidate", "COMMON_ANCHORS", "beta")]["games"], 1)
        self.assertEqual(keys[("opponent", "COMMON_ANCHORS", "heuristic-v031")]["games"], 1)

    def test_anchor_keys_match_recorded_data_names(self):
        self.assertEqual(ANCHORS, ("heuristic-v031", "prism-v01", "prism-general-v011"))

    def test_ratio_aggregation_uses_total_investments(self):
        first, second = profile((3,)), profile((), main_actions=10, investment_count=3)
        rows = load_profiles({"games": [game("control", "prism-v01", 1, 0, first),
                                          game("control", "prism-v01", 2, 1, second)]})
        summary = summarize([r["candidate_profile"] for r in rows])
        self.assertEqual(summary["redemption_rate_by_total_investments"], .25)
        self.assertEqual(summary["censored_rate_by_total_investments"], .75)

    def test_per_investment_cap_and_loss_are_recomputed(self):
        p = profile(tuple(range(2, 25)))
        inv = p["investments"][0]
        inv.update(observed_uses=23, credited_uses=3, use_main_actions=list(range(2, 25)))
        p.update(building_observed_use_units=23, building_use_units_before_global_cap=3,
                 building_use_units=3, building_utility=3 / 24)
        summary = summarize([validate_profile(p)])
        self.assertEqual(summary["per_investment_cap_loss_units"], 20)
        self.assertEqual(summary["investment_3plus_use_rate"], 1)

    def test_global_cap_and_use_timing_diagnostics(self):
        p = profile((4, 7, 9), acquired=2)
        p["investments"] = [dict(p["investments"][0]) for _ in range(9)]
        p["early_lowvp_buys"] = 9
        p["redeemed_investments"] = 9
        p["building_observed_use_units"] = 27
        p["building_use_units_before_global_cap"] = 27
        p["building_use_units"] = 24
        p["building_utility"] = 1
        summary = summarize([validate_profile(p)])
        self.assertEqual(summary["global_cap_loss_units"], 3)
        self.assertEqual(summary["utility_globalcap24_games"], 1)
        self.assertEqual(summary["first_use_main"]["mean"], 4)
        self.assertEqual(summary["third_use_delay_main"]["mean"], 7)

    def test_utility_zero_variance_correlations_are_null(self):
        records = [validate_profile(profile((3,))) for _ in range(3)]
        self.assertTrue(all(x is None for x in summarize(records)["correlations"].values()))

    def test_invalid_utility_and_conservation_fail(self):
        p = profile()
        p["building_utility"] = .25
        with self.assertRaises(ValueError):
            validate_profile(p)
        p = profile()
        p["investments"][0]["credited_uses"] = 2
        with self.assertRaises(ValueError):
            validate_profile(p)

    def test_use_after_terminal_fails(self):
        with self.assertRaises(ValueError):
            validate_profile(profile((3,), main_actions=2))

    def test_nearest_rank_distribution_reports_count_and_definition(self):
        result = distribution([1, 2, 3, 4])
        self.assertEqual(result["n"], 4)
        self.assertEqual(result["p10"], 1)
        self.assertTrue(result["quantile_definition"].startswith("nearest-rank"))

    def test_matched_delta_tracks_candidate_when_candidate_is_seat_one(self):
        rows = []
        for arm, uses in (("control", (3,)), ("beta", (3, 5, 8))):
            row = game(arm, "prism-general-v011", 11, 1, profile(uses),
                       profile((), auc=0, late_vp=0))
            row["stage"] = "acceptance"
            rows.append(row)
        checked = load_profiles({"games": rows})
        for row in checked:
            row["stage"] = "acceptance"
        delta = matched_differences(checked)[0]
        self.assertEqual(delta["matched_seed_seat_rows"], 1)
        self.assertAlmostEqual(delta["mean_beta_minus_control"]["utility"], 2 / 24)

    def test_unmatched_control_beta_key_fails(self):
        row = game("beta", "prism-v01", 11, 1, profile())
        row["stage"] = "acceptance"
        checked = load_profiles({"games": [row]})
        checked[0]["stage"] = "acceptance"
        with self.assertRaisesRegex(ValueError, "unmatched control/beta"):
            matched_differences(checked)


if __name__ == "__main__":
    unittest.main()
