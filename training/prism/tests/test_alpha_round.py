"""M56 checks cover acceptance tradeoffs, seed layout and missing timing data."""
import copy
import pytest
from scripts import prism_alpha_round as round


def synthetic_rows():
    stats = {'seed_start': 1, 'seed_end': 4, 'direct_seed_end': 8,
             'bootstrap_samples': 2000, 'bootstrap_rng_seed': 56029999,
             'lower_quantile': .05 / 3, 'one_sided_claims': 3,
             'strength_pool_delta_lower_gte': -.05,
             'direct_parent_score_lower_gte': .45, 'bigcard_auc24_delta_lower_gte': -.015}
    rows = []
    for model, op, seed, seat in sorted(round.expected_grid(1, 4) | round.expected_grid(1, 8, True)):
        # One opponent gets worse, another better; overall remains unchanged.
        score = .5
        if model == 'candidate' and op == round.ANCHORS[0]: score = 0.
        if model == 'candidate' and op == round.ANCHORS[1]: score = 1.
        rows.append({'candidate': model, 'opponent': op, 'seed': seed, 'candidate_seat': seat,
                     'candidate_score': score, 'large_card_vp_auc24': .05 if model == 'base' else .04,
                     'rush_auc': .1, 'vp_threshold_by_horizon': False})
    return stats, rows


def test_tradeoffs_can_pass_without_every_metric_positive():
    stats, rows = synthetic_rows()
    measures, gates = round.measurements(rows, stats)
    assert all(gates.values())
    assert measures['diagnostic/strength/' + round.ANCHORS[0]]['mean'] == -.5
    assert measures['bigcard_auc24']['mean'] < 0
    assert measures['direct_parent']['seed_blocks'] == 8
    assert measures['strength_pool']['seed_blocks'] == 4


@pytest.mark.parametrize('bad', ['style', 'direct', 'pool'])
def test_each_prospective_floor_can_independently_fail(bad):
    stats, rows = synthetic_rows()
    for row in rows:
        if bad == 'style' and row['candidate'] == 'candidate': row['large_card_vp_auc24'] = .02
        if bad == 'direct' and row['opponent'] == 'base-t1': row['candidate_score'] = 0
        if bad == 'pool' and row['candidate'] == 'candidate' and row['opponent'] != 'base-t1': row['candidate_score'] = 0
    _, gates = round.measurements(rows, stats)
    assert gates[{'style': 'bigcard_auc24', 'direct': 'direct_parent', 'pool': 'strength_pool'}[bad]] is False


def test_missing_or_duplicate_seat_is_fatal():
    stats, rows = synthetic_rows()
    with pytest.raises(Exception, match='grid'): round.measurements(rows[:-1], stats)
    with pytest.raises(Exception, match='grid'): round.measurements(rows + [copy.deepcopy(rows[0])], stats)


def test_no_large_purchase_has_missing_conditional_time_and_zero_coverage():
    profile = {'rush_auc': .1, 'large_card_vp_auc24': 0., 'terminal_large_card_printed_vp': 0,
               'high_vp_buys_within_window': 0, 'first_large_card_main': None, 'first_4plus_card_main': None,
               'score_checkpoints': [{'vp': 3, 'large_card_printed_vp': 0, 'observed_before_terminal': i < 2}
                                     for i in range(5)]}
    out = round.profile_summary([profile])
    assert out['first_large_card_main'] == {'coverage_games': 0, 'coverage_rate': 0., 'conditional_mean': None}
    assert out['score_checkpoints'][-1]['observed_games'] == 0
    assert out['score_checkpoints'][-1]['mean_vp'] == 3
