"""M63 metric contract keeps old utility and reports timing-weighted use descriptively."""
import pytest

from scripts import prism_building_metrics_m63 as metrics
from training.prism_portable.engine.ppo import building_timed


def profile(utility, timed, units):
    return {
        'building_utility': utility, 'timed_building_utility': timed,
        'early_bonus_auc12': 1.0, 'building_use_units': 4,
        'building_use_units_before_global_cap': 4, 'building_observed_use_units': 4,
        'timed_building_use_units': units, 'early_buys': 2, 'early_lowvp_buys': 1,
        'redeemed_investments': 1, 'unredeemed_investments': 0, 'censored_investments': 0,
        'unredeemed_censored_investments': 0, 'late_vp_bought_main13to24': 2,
        'late_scoring_vp_main25to32': 3, 'observed_main13to24': 12,
        'observed_main25to32': 8, 'shorter_than_early_window': False,
        'redemption_horizon_censored': False, 'late_scoring_main25to32_censored': False,
    }


def test_profile_summary_aggregates_timed_utility_without_replacing_original():
    result = metrics.profile_summary([profile(.25, .12, 2), profile(.5, .2, 4)])
    assert result['mean_building_utility'] == .375
    assert result['mean_timed_building_utility'] == .16
    assert result['mean_timed_building_use_units'] == 3
    assert result['mean_building_utility'] != result['mean_timed_building_utility']


def test_timed_utility_uses_real_main_time_and_preserves_v1_profile():
    config = building_timed.default_timed_building_config()
    profile = {
        'format': 'prism-building-profile-v1', 'main_actions': 24,
        'investments': [{'acquired_main': 1, 'use_main_actions': [2, 5, 24],
                         'observed_uses': 3, 'credited_uses': 3}],
    }
    timed = building_timed._timed_utility(profile, config)
    assert timed['time_weighted_use_units'] == pytest.approx((23 + 20 + 1) / 24)
    assert timed['time_weighted_utility'] == pytest.approx(((23 + 20 + 1) / 24) / 24)
    assert profile['format'] == 'prism-building-profile-v1'
    assert len(profile['investments'][0]['use_main_actions']) == 3


def test_timed_utility_rejects_source_profile_outside_observed_main_horizon():
    profile = {
        'format': 'prism-building-profile-v1', 'main_actions': 12,
        'investments': [{'acquired_main': 1, 'use_main_actions': [2, 13],
                         'observed_uses': 2, 'credited_uses': 2}],
    }
    import pytest
    with pytest.raises(ValueError, match='outside its real post-acquisition horizon'):
        building_timed._timed_utility(profile, building_timed.default_timed_building_config())


def test_timed_utility_rejects_use_conservation_drift():
    profile = {
        'format': 'prism-building-profile-v1', 'main_actions': 12,
        'investments': [{'acquired_main': 1, 'use_main_actions': [2],
                         'observed_uses': 2, 'credited_uses': 1}],
    }
    import pytest
    with pytest.raises(ValueError, match='conservation mismatch'):
        building_timed._timed_utility(profile, building_timed.default_timed_building_config())
