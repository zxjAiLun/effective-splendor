"""M63 report assembly from a synthetic evaluation result; verdicts render, never recompute.

The fixture mirrors the documented result/pair schema (both-player metrics, physical
seats, building profiles) but contains no games, training, network or filesystem
writes. Gate cells and verdict strings must come strictly from the recorded
`gates`/`verdicts` fields; a mean above a failed threshold must still render FAIL.
"""
import copy

import pytest

from scripts import prism_building_evaluation_m63 as evaluation
from scripts import prism_building_metrics_m63 as building_metrics
from scripts import prism_building_report_m63 as report
from scripts import prism_building_prepare_m63 as prepare
from scripts import prism_match_details as details

ACTIONS = details.ACTIONS
COLORS = details.COLORS
DIRECT_OPPONENTS = ('base-t1', 'control-t1', 'alpha-t1', 'previous-beta-t1')


def side_metrics(n, wins, ties):
    """One player's per-pair metrics; counts are integers, means derive from them."""
    losses = n - wins - ties
    counts = {'buy_market': 100, 'buy_reserved': 20, 'take_tokens': 800,
              'reserve_market': 30, 'reserve_deck': 10, 'choose_noble': 16, 'pass': 24}
    total = sum(counts.values())
    cards = {'0': 0., '1': 80., '2': 30., '3': 10., '4': 0., '5': 0.}
    points = 80 * 1 + 30 * 2 + 10 * 3 + 3 * 16
    permanent = sum(counts[a] for a in ('buy_market', 'buy_reserved'))
    acquired = counts['reserve_market'] + counts['reserve_deck']
    bought = counts['buy_reserved']
    noble_games = min(n, 8)
    return dict(games=n, wins=wins, ties=ties, losses=losses, games_with_nobles=noble_games,
                mean_prestige=points / n, mean_nobles=16 / n, mean_permanent_bonuses=permanent / n,
                mean_reserves_acquired=acquired / n, mean_reserves_bought=bought / n,
                mean_reserves_stranded=(acquired - bought) / n,
                mean_cards_by_vp={key: value / n for key, value in cards.items()},
                mean_bonuses_by_color={color: permanent / 5 / n for color in COLORS},
                action_distribution=dict(counts), total_actor_decisions=total,
                total_main_actions=total - counts['choose_noble'],
                win_rate_percent=100 * wins / n, score_rate=(wins + .5 * ties) / n,
                games_with_nobles_percent=100 * noble_games / n,
                vp_per_turn=points / total, vp_per_main_action=points / (total - counts['choose_noble']),
                vp_per_ply=points / (19 * n),
                reserve_redemption_rate_percent=100 * bought / acquired,
                action_percentages={action: 100 * count / total for action, count in counts.items()})


def macro(n):
    return dict(total_games=n, total_plies=38 * n, mean_plies=38., mean_turns=19., min_turns=9,
                max_turns=30, median_turns=19., std_turns=3.1, mean_main_rounds=15.4,
                mean_victory_margin=2.4, close_games_margin_le_2_percent=41.5,
                process_wall_seconds_sum=1.7 * n, process_wall_seconds_mean=1.7,
                process_wall_seconds_p95=2.3, decision_latency_ms=None, inference_latency_ms=None,
                missing_latency_reason='per-decision/inference timings were not recorded')


def building_profile(mains, utility, auc, lowvp, redeemed, late1324=2., late2532=3.):
    observed1324 = max(0, min(mains, 24) - 12)
    observed2532 = max(0, min(mains, 32) - 24)
    return dict(building_utility=utility, timed_building_utility=utility * .8, timed_building_use_units=utility * 24 * .8, early_bonus_auc12=auc,
                building_use_units=utility * 24, building_use_units_before_global_cap=utility * 24,
                building_observed_use_units=utility * 24, early_buys=lowvp + 1, early_lowvp_buys=lowvp,
                redeemed_investments=redeemed, unredeemed_investments=lowvp - redeemed,
                censored_investments=max(0, lowvp - redeemed - 1),
                unredeemed_censored_investments=max(0, lowvp - redeemed - 1),
                late_vp_bought_main13to24=late1324, late_scoring_vp_main25to32=late2532,
                observed_main13to24=observed1324, observed_main25to32=observed2532,
                shorter_than_early_window=mains < 12, redemption_horizon_censored=mains < 24,
                late_scoring_main25to32_censored=mains < 32)


def building_summary(mains=26, utility=.5, auc=1.5, lowvp=2, redeemed=1, late1324=2., late2532=3.,
                     count=1):
    return building_metrics.profile_summary(
        [building_profile(mains, utility, auc, lowvp, redeemed, late1324, late2532)
         for _ in range(count)])


def bigcard_summary(games, total_auc=4.2, large_auc=1.8):
    """Same shape as the descriptive bigcard/trajectory profile summary."""
    return dict(games=games, mean_total_vp_auc24=total_auc, mean_large_card_vp_auc24=large_auc,
                mean_terminal_large_card_printed_vp=5.1, mean_large_card_buys_within24=2.2,
                first_large_card_main=dict(coverage_games=games // 2, coverage_rate=.5,
                                           conditional_mean=9.5),
                first_4plus_card_main=dict(coverage_games=games // 4, coverage_rate=.25,
                                           conditional_mean=12.),
                score_checkpoints=[dict(own_main=main, mean_vp=4. + main / 10,
                                        mean_large_card_printed_vp=main / 12,
                                        observed_games=games, games=games)
                                   for main in (8, 12, 16, 20, 24)])


def uncertainty(blocks):
    return dict(seed_blocks=blocks, rng_seed=evaluation.BOOTSTRAP_SEED, resamples=20000,
                ordinary_95_ci=[.42, .58], mean=.5, kind='synthetic descriptive bootstrap')


def pair(candidate, opponent, n, wins, ties):
    half = n // 2
    w0, w1 = wins // 2, wins - wins // 2
    t0, t1 = ties // 2, ties - ties // 2
    seats = [dict(candidate_seat=seat, candidate=side_metrics(half, w, t),
                  opponent=side_metrics(half, half - w - t, t), macro=macro(half),
                  candidate_building=building_summary(count=half),
                  opponent_building=building_summary(mains=13, utility=.4, lowvp=0, redeemed=0,
                                                     late2532=0., count=half))
             for seat, (w, t) in ((0, (w0, t0)), (1, (w1, t1)))]
    return dict(candidate=candidate, opponent=opponent,
                candidate_metrics=side_metrics(n, wins, ties),
                opponent_metrics=side_metrics(n, n - wins - ties, ties),
                candidate_building=building_summary(count=n),
                opponent_building=building_summary(mains=13, utility=.4, lowvp=0, redeemed=0,
                                                   late2532=0., count=n),
                candidate_bigcard=bigcard_summary(n), opponent_bigcard=bigcard_summary(n, 3.9, 1.5),
                seats=seats, macro=macro(n),
                score_uncertainty=uncertainty(half), win_uncertainty=uncertainty(half),
                mean_rush_auc=4.05, vp8_by_main20_rate=.31, short_game_fraction=.02)


DEFAULT_WINS = {'base': 24, 'control': 36, 'beta': 44}
ACCEPTANCE_WINS = {'base': 205, 'control': 307, 'beta': 410}
DIRECT_WINS = {('control', 'base-t1'): 563, ('beta', 'base-t1'): 563,
               ('beta', 'control-t1'): 563, ('beta', 'alpha-t1'): 460, ('beta', 'previous-beta-t1'): 500}


def stage_record(stage, anchor_wins=None, direct_wins=None):
    anchor_wins = anchor_wins or (DEFAULT_WINS if stage == 'development' else ACCEPTANCE_WINS)
    direct_wins = direct_wins or DIRECT_WINS
    pairs, games = [], 0
    for model in evaluation.MODELS:
        for op in evaluation.ANCHORS:
            if stage == 'development':
                n, wins, ties = 64, anchor_wins[model], 8
            else:
                n, wins, ties = 512, anchor_wins[model], 51
            pairs.append(pair(model, op, n, wins, ties))
            games += n
    if stage == 'acceptance':
        for pair_key, wins in direct_wins.items():
            pairs.append(pair(pair_key[0], pair_key[1], 1024, wins, 100))
            games += 1024
    return dict(games=games, pairs=pairs, stage_wall_seconds=1.5, plan_sha256='a' * 64,
                source_ledger_sha256='b' * 64, style_metrics_sha256='c' * 64,
                building_metrics_sha256='d' * 64, match_details_sha256='e' * 64)


def measurements_fixture(fail=('beta/early_bonus_auc12',)):
    """Ten measurements whose recorded gates mix PASS and FAIL.

    The failing gate keeps its mean (.30) ABOVE its frozen threshold (.25) while the
    recorded simultaneous lower bound (.20) is below it: rendering must show FAIL.
    """
    measures, gates = {}, {}
    for key, threshold in evaluation.GATES.items():
        lower = threshold + (-.05 if key in fail else .01)
        mean = lower + .1
        measures[key] = dict(mean=mean, ci95=[mean - .02, mean + .02],
                             simultaneous_one_sided_lower=lower,
                             seed_blocks=512 if '/direct_' in key else 256,
                             bootstrap_rng_seed=evaluation.BOOTSTRAP_SEED,
                             bootstrap_samples=20000, lower_quantile=evaluation.LOWER_Q)
        gates[key] = lower >= threshold
    return measures, gates, evaluation.verdicts(measures, gates)


def full_result(measured=True):
    result = dict(format='m63-building-evaluation-result-v1',
                  status='COMPLETED_FIXED_BUILDING_EVALUATION',
                  started_at='2026-10-03T00:00:00+00:00', elapsed_wall_seconds=1.2,
                  execution_sha256='a' * 64, config_sha256='b' * 64,
                  candidate_sha256={'control': 'c' * 64, 'beta': 'd' * 64},
                  inference_time='NOT_MEASURED', decision_time='NOT_MEASURED',
                  retries=0, physical_games=10304,
                  clock_scope='synthetic fixture; no games were played')
    result['development'] = stage_record('development')
    if measured:
        result['acceptance'] = stage_record('acceptance')
        result['measurements'], result['gates'], result['verdicts'] = measurements_fixture()
    return result


def execution():
    return dict(evaluation=prepare.evaluation_contract())


def test_full_measured_report_renders_recorded_gates_not_recomputed_ones():
    text = report.render_report(full_result(), execution())
    assert text.count('**PASS**') == 9 and text.count('**FAIL**') == 1
    failing = [line for line in text.splitlines()
               if 'beta/early_bonus_auc12' in line and 'FAIL' in line]
    assert len(failing) == 1
    # Mean 0.300000 exceeds the 0.25 threshold; the recorded lower bound 0.200000
    # does not. The cell must show the recorded FAIL, not a recomputed verdict.
    assert '0.300000' in failing[0] and '0.200000' in failing[0] and '**FAIL**' in failing[0]
    for key in evaluation.GATES:
        if key != 'beta/early_bonus_auc12':
            passing = [line for line in text.splitlines() if key in line and '**PASS**' in line]
            assert len(passing) == 1, key
    assert 'NOT_MEASURED / NOT_MEASURED' in text
    assert '| 门 |' in text and '同时单侧下界' in text


def test_competitive_and_style_verdicts_are_rendered_separately():
    text = report.render_report(full_result(), execution())
    assert '**风格：**FAIL_BUILDING_STYLE_THRESHOLD' in text
    assert 'FAIL_BETA_GATES' in text and 'PASS_RETENTION_FLOORS' in text
    assert 'NOT_ACCEPTED_BUILDING_CANDIDATE' in text
    assert 'cohort_qualified' in text
    # The competitive provenance section excludes the style verdict key; the full
    # verdict record (including beta_style) only appears in its own later section.
    head, _, tail = text.partition('## 原验收与增强记录')
    assert 'beta_style' not in head and 'beta_style' in tail
    # Style metric rows keep their raw permanent-discount unit labels.
    assert '原始永久折扣个数' in text
    assert '原building效用（归一化0..1，既有门）' in text


def test_unmeasured_report_renders_not_run_and_keeps_development_only():
    text = report.render_report(full_result(measured=False), execution())
    assert '**PASS**' not in text and '**FAIL**' not in text
    assert text.count('NOT_RUN') >= 3
    assert '## 开发评测（仅描述，576局）' in text
    assert '## 独立验收（9,728局）\n\nNOT_RUN；不从开发推断验收。' in text
    assert '**风格：**NOT_RUN' in text


def test_validate_measurements_accepts_consistent_recorded_outcomes():
    result = full_result()
    report.validate_measurements(result)
    assert result['verdicts'] == evaluation.verdicts(result['measurements'], result['gates'])


def test_validate_measurements_rejects_gate_flip_and_strict_boundary_flip():
    result = full_result()
    result['gates']['beta/building_utility'] = not result['gates']['beta/building_utility']
    with pytest.raises(ValueError, match='gate/lower bound'):
        report.validate_measurements(result)
    result = full_result()
    # recorded enhancement True while the lower bound (.46) is not > .5
    result['verdicts']['confirmed_enhancement']['beta/direct_parent'] = True
    with pytest.raises(ValueError, match='verdict'):
        report.validate_measurements(result)
    result = full_result()
    result['verdicts']['beta_acceptance'] = 'ACCEPTED_BUILDING_CANDIDATE'
    with pytest.raises(ValueError, match='verdict'):
        report.validate_measurements(result)


@pytest.mark.parametrize('field,value', [
    ('seed_blocks', 255), ('bootstrap_rng_seed', 63049998), ('bootstrap_samples', 10000),
    ('lower_quantile', .006)])
def test_validate_measurements_rejects_bootstrap_provenance_drift(field, value):
    result = full_result()
    result['measurements']['beta/direct_alpha'][field] = value
    with pytest.raises(ValueError, match='provenance'):
        report.validate_measurements(result)


def test_validate_measurements_rejects_missing_extra_or_nonfinite_claims():
    result = full_result()
    del result['measurements']['beta/direct_alpha']
    with pytest.raises(ValueError, match='ten claims'):
        report.validate_measurements(result)
    result = full_result()
    result['measurements']['extra/claim'] = result['measurements']['beta/direct_alpha']
    with pytest.raises(ValueError, match='ten claims'):
        report.validate_measurements(result)
    result = full_result()
    result['measurements']['beta/direct_alpha']['mean'] = float('inf')
    with pytest.raises(ValueError, match='nonfinite'):
        report.validate_measurements(result)


def test_validate_measurements_requires_formal_measurements_for_acceptance():
    result = full_result()
    for key in ('measurements', 'gates', 'verdicts'):
        del result[key]
    with pytest.raises(ValueError, match='ten formal measurements'):
        report.validate_measurements(result)


def test_comparison_tables_average_anchors_per_model_identity():
    record = stage_record('acceptance')
    table = report.comparison_tables(record)
    for name in (evaluation.DISPLAY['base'], evaluation.DISPLAY['control'], evaluation.DISPLAY['beta']):
        assert name in table
    keyed = {(p['candidate'], p['opponent']): p for p in record['pairs']}
    for model in evaluation.MODELS:
        expected = sum(keyed[(model, op)]['candidate_metrics']['score_rate']
                       for op in evaluation.ANCHORS) / 3
        assert report.pct(expected) in table


def test_direction_table_flags_opposite_development_acceptance_directions():
    result = full_result()
    # development: control below base; acceptance: control above base.
    result['development'] = stage_record('development', anchor_wins={'base': 24, 'control': 16, 'beta': 44})
    result['acceptance'] = stage_record('acceptance', anchor_wins={'base': 205, 'control': 307, 'beta': 410})
    table = report.direction_table(result)
    assert table.count('**方向相反；原数据保留**') >= 1
    assert '同向/零变化；不合并样本' in table
    assert report.direction_table({'development': stage_record('development')}) == 'NOT_RUN'


def test_detailed_match_tables_cover_every_opponent_and_both_seats():
    text = report.detailed_match_tables(stage_record('acceptance'))
    for op in evaluation.ANCHORS + DIRECT_OPPONENTS:
        assert evaluation.DISPLAY[op] in text
    assert '先手 P0' in text and '后手 P1' in text
    assert '早期bonus AUC12（原始永久折扣个数；非reward）' in text
    # Direct pairs' opponent building profiles carry no investments -> NOT_APPLICABLE.
    assert 'NOT_APPLICABLE' in text
    assert '（描述性；非M63奖励）' in text


def test_stage_summary_rows_report_pair_and_seed_block_counts():
    record = stage_record('acceptance')
    summary = report.legacy.stage_summary(record, evaluation.DISPLAY)
    assert '512 / 256' in summary and '1024 / 512' in summary
    assert f"{record['games']} / " not in summary


@pytest.mark.parametrize('mutation,message', [
    ('games', 'pair/full count'), ('wdl', 'outcome conservation'), ('seats', 'physical seats'),
    ('building', 'building coverage'), ('ci', 'provenance'), ('macro', 'pair count'),
    ('actions', 'denominator'), ('percentages', 'action share')])
def test_validate_stage_rejects_drifted_stage_fixtures(mutation, message):
    record = stage_record('acceptance')
    if mutation == 'games':
        record['games'] += 1
    elif mutation == 'wdl':
        record['pairs'][0]['candidate_metrics']['losses'] += 1
    elif mutation == 'seats':
        record['pairs'][0]['seats'] = record['pairs'][0]['seats'][:1]
    elif mutation == 'building':
        record['pairs'][0]['candidate_building']['games'] += 1
    elif mutation == 'ci':
        record['pairs'][0]['score_uncertainty']['rng_seed'] = 54049999
    elif mutation == 'macro':
        record['pairs'][0]['macro']['total_games'] += 1
    elif mutation == 'actions':
        record['pairs'][0]['candidate_metrics']['action_distribution']['choose_noble'] += 1
    else:
        record['pairs'][0]['candidate_metrics']['action_percentages']['pass'] = 99.
    with pytest.raises(ValueError, match=message):
        report.validate_stage(record, 'acceptance')


def test_render_report_rejects_wrong_result_format():
    with pytest.raises(ValueError, match='format'):
        report.render_report({'format': 'm61-balance-ab-evaluation-result-v1'}, execution())
