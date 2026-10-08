"""M62 frozen evaluation contracts: policy, grid, intervals, verdicts, fail-closed paths.

Synthetic mathematical fixtures only: no games, no network, no formal execution and
no writes outside pytest tmp_path. The frozen nine-claim one-sided family, the
9,280-game physical grid and every fail-closed guard of the evaluation script are
checked against the prepare module's verbatim evaluation contract.
"""
import copy
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from scripts import prism_building_evaluation_m62 as m
from scripts import prism_building_prepare_m62 as prepare

CONTRACT = prepare.evaluation_contract()
ENGINE = dict(path='engine.bin', sha256='a' * 64)


def policy():
    return copy.deepcopy(CONTRACT)


def candidates_and_opponents():
    def desc(name):
        return dict(program='engine.bin', sha256='a' * 64,
                    args=['agent-prism-sample', '--weights', name + '.json', '--seed', str(m.ACTION_SEED)],
                    files=[dict(path=name + '.json', sha256='b' * 64)])
    return ({name: desc(name) for name in m.MODELS},
            {op: desc(op) for op in (*m.ANCHORS, 'alpha-t1')})


def outcome_row(model, op, seed, seat, value, utility, auc):
    """One terminal row whose outcome conserves candidate_score/record/points."""
    if value == 1:
        scores, ranks, winners = ([15, 14], [0, 1], [0]) if seat == 0 else ([14, 15], [1, 0], [1])
    elif value == 0:
        scores, ranks, winners = ([14, 15], [1, 0], [1]) if seat == 0 else ([15, 14], [0, 1], [0])
    else:
        scores, ranks, winners = [15, 15], [0, 0], [0, 1]
    return dict(candidate=model, opponent=op, seed=seed, candidate_seat=seat,
                candidate_score=value, record='win' if value == 1 else 'draw' if value == .5 else 'loss',
                candidate_points=scores[seat], opponent_points=scores[1 - seat],
                scores=scores, ranks=ranks, winners=list(winners),
                building_utility=utility[model], early_bonus_auc12=auc[model])


def outcome_rows(outcome, utility, auc, stats):
    grid = m.expected_grid(stats['seed_start'], stats['seed_end']) | \
        m.expected_grid(stats['seed_start'], stats['direct_seed_end'], True)
    return [outcome_row(model, op, seed, seat, outcome[(model, op)], utility, auc)
            for model, op, seed, seat in sorted(grid)]


def uniform_outcome(mapping):
    """Same terminal outcome for every seed and physical seat of a pair.

    Combined with equal per-seat results this makes every per-seed block value a
    constant, so bootstrap quantiles equal the block value exactly and gate
    floor/strict semantics can be asserted at exact boundaries.
    """
    return {(model, op): value for (model, op), value in mapping.items()}


# control draws heuristic/prism-v01 and beats the general anchor; beta beats the
# first two anchors and loses the general anchor; direct floors are split.
MIXED = uniform_outcome({
    ('base', 'heuristic-v031'): 0, ('base', 'prism-v01'): 0, ('base', 'prism-general-v011'): 0,
    ('control', 'heuristic-v031'): .5, ('control', 'prism-v01'): .5, ('control', 'prism-general-v011'): 1,
    ('beta', 'heuristic-v031'): 1, ('beta', 'prism-v01'): 1, ('beta', 'prism-general-v011'): 0,
    ('control', 'base-t1'): .5, ('beta', 'base-t1'): .5, ('beta', 'control-t1'): 1, ('beta', 'alpha-t1'): 0})
MIXED_UTILITY = {'base': .10, 'control': .10, 'beta': .12}
MIXED_AUC = {'base': 1., 'control': 1., 'beta': 1.2}
MIXED_GATES = {'control/strength_pool': True, 'control/direct_parent': True, 'beta/strength_pool': True,
               'beta/general_anchor': False, 'beta/direct_control': True, 'beta/direct_alpha': False,
               'beta/direct_parent': True, 'beta/building_utility': True, 'beta/early_bonus_auc12': False}
MIXED_LOWER = {'control/strength_pool': 2 / 3, 'control/direct_parent': .5, 'beta/strength_pool': 0.,
               'beta/general_anchor': -1., 'beta/direct_control': 1., 'beta/direct_alpha': 0.,
               'beta/direct_parent': .5, 'beta/building_utility': .02, 'beta/early_bonus_auc12': .2}

# Base wins every anchor game, control only draws them: the control pool floor fails.
BLOCKED = uniform_outcome({
    ('base', 'heuristic-v031'): 1, ('base', 'prism-v01'): 1, ('base', 'prism-general-v011'): 1,
    ('control', 'heuristic-v031'): .5, ('control', 'prism-v01'): .5, ('control', 'prism-general-v011'): .5,
    ('beta', 'heuristic-v031'): 1, ('beta', 'prism-v01'): 1, ('beta', 'prism-general-v011'): 1,
    ('control', 'base-t1'): 0, ('beta', 'base-t1'): 1, ('beta', 'control-t1'): 1, ('beta', 'alpha-t1'): 1})
BLOCKED_UTILITY = {'base': .125, 'control': .125, 'beta': .15625}
BLOCKED_AUC = {'base': 1., 'control': 1., 'beta': 1.3}

# Every floor passes exactly at its threshold (auc lower == .25, direct == .5,
# pool == 0 >= -.05) while no strict directional claim (>0 / >.5) is confirmed.
FLOOR = uniform_outcome({
    ('base', 'heuristic-v031'): 0, ('base', 'prism-v01'): 0, ('base', 'prism-general-v011'): 0,
    ('control', 'heuristic-v031'): .5, ('control', 'prism-v01'): .5, ('control', 'prism-general-v011'): .5,
    ('beta', 'heuristic-v031'): .5, ('beta', 'prism-v01'): .5, ('beta', 'prism-general-v011'): .5,
    ('control', 'base-t1'): .5, ('beta', 'base-t1'): .5, ('beta', 'control-t1'): .5, ('beta', 'alpha-t1'): .5})
FLOOR_UTILITY = {'base': .125, 'control': .125, 'beta': .15625}
FLOOR_AUC = {'base': 1., 'control': 1., 'beta': 1.25}


def test_policy_accepts_prepared_contract_verbatim_and_extra_metadata():
    m.validate_policy(prepare.evaluation_contract())
    deployed = policy()
    deployed['acceptance']['native_path_and_sha256'] = dict(path='engine.bin', sha256='c' * 64)
    deployed['status'] = 'FROZEN_BEFORE_FIRST_GAME'
    m.validate_policy(deployed)


def test_family_has_lower_bounds_only():
    p = policy()
    p['acceptance']['upper_quantile'] = 1 - m.LOWER_Q
    with pytest.raises(ValueError, match='lower bound'):
        m.validate_policy(p)


def test_frozen_thresholds_required_gates_and_seed_constants():
    assert m.GATES == {'control/strength_pool': -.05, 'control/direct_parent': .45,
                       'beta/strength_pool': -.05, 'beta/general_anchor': -.075,
                       'beta/direct_control': .45, 'beta/direct_alpha': .45,
                       'beta/direct_parent': .45, 'beta/building_utility': .015,
                       'beta/early_bonus_auc12': .25}
    assert m.REQUIRED_GATES == {'control': ['strength_pool', 'direct_parent'],
                                'beta': ['strength_pool', 'general_anchor', 'direct_control',
                                         'direct_alpha', 'direct_parent', 'building_utility',
                                         'early_bonus_auc12']}
    assert (m.ACTION_SEED, m.BOOTSTRAP_SEED, m.SAMPLES) == (62042001, 62049999, 20000)
    assert m.LOWER_Q == .05 / 9
    assert m.MODELS == ('base', 'control', 'beta') and m.ARMS == ('control', 'beta')
    assert m.ANCHORS == ('heuristic-v031', 'prism-v01', 'prism-general-v011')
    assert m.LIMITS['physical_games'] == 9280 and m.LIMITS['infrastructure_retries'] == 0
    acceptance = CONTRACT['acceptance']
    assert acceptance['gates'] == m.GATES and acceptance['required_gates'] == m.REQUIRED_GATES
    assert [(model, op + '-t1') for model, op in acceptance['direct_pairs']] == list(m.DIRECT_PAIRS)
    assert acceptance['shared_draws_for_equal_length_vectors'] is True
    assert (CONTRACT['total_games'], CONTRACT['development']['total_games'],
            acceptance['total_games'], acceptance['anchor_total_games'],
            acceptance['direct_total_games'], acceptance['total_physical_budget']) == \
        (9280, 576, 8704, 4608, 4096, 11328)
    assert (CONTRACT['development']['blocks'], acceptance['blocks'], acceptance['direct_blocks']) == \
        (32, 256, 512)


DRIFT = [
    (('total_games',), 9000),
    (('development', 'seed_start'), 9636001),
    (('development', 'seed_end'), 9636030),
    (('development', 'total_games'), 512),
    (('development', 'blocks'), 31),
    (('development', 'action_seed'), 62042002),
    (('development', 'anchors'), ['prism-v01', 'heuristic-v031', 'prism-general-v011']),
    (('development', 'models'), ['control', 'base', 'beta']),
    (('acceptance', 'seed_start'), 9641001),
    (('acceptance', 'seed_end'), 9641254),
    (('acceptance', 'total_games'), 8703),
    (('acceptance', 'blocks'), 255),
    (('acceptance', 'direct_seed_end'), 9641510),
    (('acceptance', 'direct_blocks'), 511),
    (('acceptance', 'anchor_total_games'), 4607),
    (('acceptance', 'direct_total_games'), 4095),
    (('acceptance', 'action_seed'), 62042002),
    (('acceptance', 'one_sided_claims'), 8),
    (('acceptance', 'simultaneous_comparisons'), 8),
    (('acceptance', 'family_alpha'), .06),
    (('acceptance', 'interval_sides'), 'two-sided'),
    (('acceptance', 'lower_quantile'), .05 / 7),
    (('acceptance', 'bootstrap_samples'), 19999),
    (('acceptance', 'bootstrap_rng_seed'), 62049998),
    (('acceptance', 'no_extension_or_checkpoint_selection'), False),
    (('acceptance', 'once_only_final_candidate'), False),
    (('acceptance', 'gates'), {**m.GATES, 'beta/building_utility': .02}),
    (('acceptance', 'required_gates'),
     {'control': ['strength_pool', 'direct_parent'], 'beta': ['strength_pool', 'general_anchor',
      'direct_control', 'direct_alpha', 'building_utility', 'early_bonus_auc12']}),
]


@pytest.mark.parametrize('path,bad', DRIFT)
def test_reject_frozen_policy_drift_on_every_key(path, bad):
    p = policy()
    target = p
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad
    with pytest.raises(ValueError):
        m.validate_policy(p)


def stage_shards(stage):
    shards = m.shard_configs(stage, policy(), ENGINE, 'catalog-fingerprint', *candidates_and_opponents())
    keys = [(model, op, seed, seat) for _, _, cfg, _ in shards for model in cfg['candidates']
            for op in cfg['opponents'] for seed in cfg['seeds'] for seat in (0, 1)]
    return shards, keys


def test_development_grid_is_576_games_in_16_seed_shards():
    shards, keys = stage_shards('development')
    assert [name for name, _, _, _ in shards] == ['anchors-0', 'anchors-1']
    assert [games for *_, games in shards] == [288, 288]
    assert len(keys) == len(set(keys)) == 576
    assert {seed for *_, seed, _ in keys} == set(range(9636000, 9636032))
    assert sum(key[0] == 'base' for key in keys) == 192
    assert sum(key[1] == 'prism-general-v011' for key in keys) == 192
    assert set(keys) == m.stage_grid('development', policy())


def test_acceptance_grid_has_anchors_plus_four_1024_game_direct_pairs():
    shards, keys = stage_shards('acceptance')
    names = [name for name, _, _, _ in shards]
    assert len(shards) == 56
    assert names[:8] == [f'anchors-{index}' for index in range(8)]
    for mode in ('direct-parent', 'direct-control', 'direct-alpha'):
        assert sum(name.startswith(mode + '-') for name in names) == 16
    assert len(keys) == len(set(keys)) == 8704
    direct_seeds = {seed for _, op, seed, _ in keys if op.endswith('-t1')}
    assert direct_seeds == set(range(9641000, 9641512))
    anchor_seeds = {seed for _, op, seed, _ in keys if not op.endswith('-t1')}
    assert anchor_seeds == set(range(9641000, 9641256))
    for pair in (('control', 'base-t1'), ('beta', 'base-t1'), ('beta', 'control-t1'), ('beta', 'alpha-t1')):
        assert sum(key[:2] == pair for key in keys) == 1024
    for model in m.MODELS:
        for op in m.ANCHORS:
            assert sum(key[:2] == (model, op) for key in keys) == 512
    assert sum(key[0] == 'base' and key[1].endswith('-t1') for key in keys) == 0
    assert set(keys) == m.stage_grid('acceptance', policy())


def test_stage_grids_are_disjoint_and_match_the_physical_budget():
    development = m.expected_grid(9636000, 9636031)
    anchors = m.expected_grid(9641000, 9641255)
    direct = m.expected_grid(9641000, 9641511, True)
    assert (len(development), len(anchors), len(direct)) == (576, 4608, 4096)
    assert len(anchors | direct) == 8704
    assert not development.intersection(anchors | direct)
    assert len(development | anchors | direct) == m.LIMITS['physical_games'] == 9280


def test_nine_real_intervals_gates_and_bootstrap_provenance():
    stats = policy()['acceptance']
    rows = outcome_rows(MIXED, MIXED_UTILITY, MIXED_AUC, stats)
    out, gates = m.measurements(rows, stats)
    assert len(rows) == 8704
    assert set(out) == set(gates) == set(m.GATES)
    for key, expected in MIXED_LOWER.items():
        assert out[key]['mean'] == pytest.approx(expected, abs=1e-9)
        assert out[key]['simultaneous_one_sided_lower'] == pytest.approx(expected, abs=1e-9)
        assert out[key]['ci95'] == [pytest.approx(expected, abs=1e-9)] * 2
    assert gates == MIXED_GATES
    for key, measurement in out.items():
        assert measurement['seed_blocks'] == (512 if '/direct_' in key else 256)
        assert measurement['bootstrap_rng_seed'] == m.BOOTSTRAP_SEED
        assert measurement['bootstrap_samples'] == m.SAMPLES == 20000
        assert measurement['lower_quantile'] == m.LOWER_Q
        assert 'simultaneous_upper' not in measurement and 'upper_quantile' not in measurement


def test_measurements_deterministic_under_row_order_and_verdicts_recorded():
    stats = policy()['acceptance']
    rows = outcome_rows(MIXED, MIXED_UTILITY, MIXED_AUC, stats)
    out, gates = m.measurements(rows, stats)
    reordered, reordered_gates = m.measurements(list(reversed(rows)), stats)
    assert (out, gates) == (reordered, reordered_gates)
    verdicts = m.verdicts(out, gates)
    assert verdicts['control_retention'] == 'PASS_RETENTION_FLOORS'
    assert verdicts['beta_seven_gates'] == 'FAIL_BETA_GATES'
    assert verdicts['beta_style'] == 'FAIL_BUILDING_STYLE_THRESHOLDS'
    assert verdicts['cohort_qualified'] is True and verdicts['beta_accepted'] is False
    assert verdicts['beta_acceptance'] == 'NOT_ACCEPTED_BUILDING_CANDIDATE'
    assert verdicts['confirmed_enhancement'] == {
        'control/strength_pool': True, 'control/direct_parent': False, 'beta/strength_pool': False,
        'beta/general_anchor': False, 'beta/direct_control': True, 'beta/direct_alpha': False,
        'beta/direct_parent': False, 'beta/building_utility': True, 'beta/early_bonus_auc12': True}


def test_blocked_control_blocks_an_accomplished_beta():
    stats = policy()['acceptance']
    out, gates = m.measurements(outcome_rows(BLOCKED, BLOCKED_UTILITY, BLOCKED_AUC, stats), stats)
    assert gates['control/strength_pool'] is False and gates['control/direct_parent'] is False
    assert all(gates[key] for key in gates if key.startswith('beta/'))
    verdicts = m.verdicts(out, gates)
    assert verdicts['control_retention'] == 'FAIL_RETENTION_FLOORS'
    assert verdicts['beta_seven_gates'] == 'PASS_BETA_GATES'
    assert verdicts['beta_style'] == 'PASS_BUILDING_STYLE_THRESHOLDS'
    assert verdicts['cohort_qualified'] is False and verdicts['beta_accepted'] is False
    assert verdicts['beta_acceptance'] == 'BLOCKED_UNQUALIFIED_CONTROL'
    assert all(verdicts['confirmed_enhancement'][key] for key in gates if key.startswith('beta/'))


def test_floors_pass_at_equality_while_strict_directions_stay_inconclusive():
    stats = policy()['acceptance']
    out, gates = m.measurements(outcome_rows(FLOOR, FLOOR_UTILITY, FLOOR_AUC, stats), stats)
    assert out['beta/early_bonus_auc12']['simultaneous_one_sided_lower'] == .25
    assert gates == {key: True for key in m.GATES}
    verdicts = m.verdicts(out, gates)
    assert verdicts['control_retention'] == 'PASS_RETENTION_FLOORS'
    assert verdicts['beta_seven_gates'] == 'PASS_BETA_GATES'
    assert verdicts['beta_style'] == 'PASS_BUILDING_STYLE_THRESHOLDS'
    assert verdicts['cohort_qualified'] is True and verdicts['beta_accepted'] is True
    assert verdicts['beta_acceptance'] == 'ACCEPTED_BUILDING_CANDIDATE'
    # Score claims straddle: pool lower == 0 and direct lowers == .5 exactly, so the
    # strict > 0 / > .5 enhancements stay unconfirmed. The style floors are not
    # directional-at-zero claims and their positive deltas are genuinely confirmed.
    assert verdicts['confirmed_enhancement'] == {
        'control/strength_pool': True, 'control/direct_parent': False, 'beta/strength_pool': False,
        'beta/general_anchor': False, 'beta/direct_control': False, 'beta/direct_alpha': False,
        'beta/direct_parent': False, 'beta/building_utility': True, 'beta/early_bonus_auc12': True}


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'extra_model', 'bad_points', 'bad_seat'])
def test_measurements_fail_closed_on_grid_or_outcome_damage(mutation):
    stats = policy()['acceptance']
    rows = outcome_rows(MIXED, MIXED_UTILITY, MIXED_AUC, stats)
    if mutation == 'missing':
        rows.pop()
    elif mutation == 'duplicate':
        rows.append(copy.deepcopy(rows[0]))
    elif mutation == 'extra_model':
        rows[0]['candidate'] = 'gamma'
    elif mutation == 'bad_points':
        rows[0]['candidate_points'] = 99
    else:
        rows[0]['ranks'] = [0, 2]
    with pytest.raises(ValueError):
        m.measurements(rows, stats)


def test_validate_outcomes_rejects_record_and_score_mismatch():
    stats = policy()
    grid = m.stage_grid('development', stats)
    values = {('base', 'heuristic-v031'): 0, ('base', 'prism-v01'): .5, ('base', 'prism-general-v011'): 1,
              ('control', 'heuristic-v031'): 1, ('control', 'prism-v01'): .5, ('control', 'prism-general-v011'): 0,
              ('beta', 'heuristic-v031'): .5, ('beta', 'prism-v01'): 1, ('beta', 'prism-general-v011'): 0}
    rows = [outcome_row(model, op, seed, seat, values[(model, op)], MIXED_UTILITY, MIXED_AUC)
            for model, op, seed, seat in sorted(grid)]
    m.validate_outcomes(rows, grid)
    damaged = copy.deepcopy(rows)
    damaged[0]['record'] = 'win' if damaged[0]['record'] != 'win' else 'loss'
    with pytest.raises(ValueError, match='conservation'):
        m.validate_outcomes(damaged, grid)
    damaged = copy.deepcopy(rows)
    damaged[0]['candidate_score'] = .25
    with pytest.raises(ValueError, match='conservation'):
        m.validate_outcomes(damaged, grid)


def write_synthetic_stage(work, stage, execution):
    """Full virtual stage: shard configs plus completed progress/result artifacts."""
    candidates, opponents = candidates_and_opponents()
    stage_root = work / stage
    (stage_root / 'configs').mkdir(parents=True)
    shards = []
    for name, mode, cfg, games in m.shard_configs(stage, execution['evaluation'], ENGINE,
                                                  'catalog-fingerprint', candidates, opponents):
        path = stage_root / 'configs' / (name + '.json')
        m.write(path, cfg)
        m.fixed.validate_config(cfg, path)
        out = stage_root / 'runs' / name
        out.mkdir(parents=True)
        records = {}
        for model in cfg['candidates']:
            for op in cfg['opponents']:
                for seed in cfg['seeds']:
                    for seat in (0, 1):
                        row = outcome_row(model, op, seed, seat, MIXED[(model, op)],
                                          MIXED_UTILITY, MIXED_AUC)
                        records[m.fixed._game_key(model, op, seed, seat)] = \
                            dict(status='completed', row=row)
        m.write(out / 'progress.json', dict(games=records))
        m.write(out / 'result.json', dict(status='ok'))
        m.write(out / 'completion.json', dict(result_sha256=m.sha(out / 'result.json')))
        shards.append(dict(mode=mode, config=str(path), config_sha256=m.sha(path),
                           output=str(out), games=games))
    m.write(stage_root / 'plan.json', dict(format='m62-building-evaluation-plan-v1',
                                           stage=stage, shards=shards))
    return stage_root


def test_all_grid_completed_passes_then_fails_closed_on_damage(tmp_path):
    execution = dict(evaluation=policy())
    work = tmp_path / 'evaluation'
    for stage in ('development', 'acceptance'):
        write_synthetic_stage(work, stage, execution)
    m.all_grid_completed(work, execution)
    completion = next((work / 'development' / 'runs').glob('*/completion.json'))
    document = m.read(completion)
    original = copy.deepcopy(document)
    document['result_sha256'] = '0' * 64
    m.write(completion, document)
    with pytest.raises(ValueError, match='result drift'):
        m.all_grid_completed(work, execution)
    m.write(completion, original)
    progress_path = next((work / 'acceptance' / 'runs').glob('*/progress.json'))
    progress = m.read(progress_path)
    original_progress = copy.deepcopy(progress)
    del progress['games'][sorted(progress['games'])[0]]
    m.write(progress_path, progress)
    with pytest.raises(ValueError, match='incomplete game'):
        m.all_grid_completed(work, execution)
    m.write(progress_path, original_progress)
    damaged_progress = copy.deepcopy(original_progress)
    damaged_progress['games']['intruder/seed-0/seat-0'] = dict(status='completed', row={})
    m.write(progress_path, damaged_progress)
    with pytest.raises(ValueError, match='unexpected game records'):
        m.all_grid_completed(work, execution)


def test_descriptive_ci_uses_half_draw_and_pure_win_semantics():
    rows = [dict(seed=seed, candidate_seat=seat, candidate_score=.5 if seat else 1.,
                 record='draw' if seat else 'win') for seed in range(4) for seat in (0, 1)]
    half = m.descriptive_ci(rows)
    assert half['mean'] == .75 and half['seed_blocks'] == 4
    assert half['rng_seed'] == m.BOOTSTRAP_SEED and half['resamples'] == m.SAMPLES
    assert half['kind'].endswith('half-draw')
    win = m.descriptive_ci(rows, True)
    assert win['mean'] == .5 and win['ordinary_95_ci'] == [.5, .5]
    assert win['kind'].endswith('pure-win')
    with pytest.raises(ValueError, match='incomplete descriptive seed block'):
        m.descriptive_ci(rows[:-1])


def test_joint_intervals_share_draws_and_discard_the_upper_tail():
    stats = dict(bootstrap_rng_seed=m.BOOTSTRAP_SEED, bootstrap_samples=m.SAMPLES,
                 lower_quantile=m.LOWER_Q)
    base = np.array([0., .5, 1., .25, -.5, .75])
    vectors = {'v': base, 'up3': base + 3, 'down2': base - 2}
    out = m.joint_intervals(vectors, stats)
    assert set(out) == set(vectors)
    for key in out:
        assert set(out[key]) == {'mean', 'ci95', 'simultaneous_one_sided_lower', 'seed_blocks',
                                 'bootstrap_rng_seed', 'bootstrap_samples', 'lower_quantile'}
        assert out[key]['bootstrap_rng_seed'] == m.BOOTSTRAP_SEED
        assert out[key]['bootstrap_samples'] == m.SAMPLES
        assert out[key]['lower_quantile'] == m.LOWER_Q
    # Equal-length vectors share one resampling stream: exact shifts stay exact.
    assert out['up3']['simultaneous_one_sided_lower'] == \
        pytest.approx(out['v']['simultaneous_one_sided_lower'] + 3, abs=1e-9)
    assert out['down2']['simultaneous_one_sided_lower'] == \
        pytest.approx(out['v']['simultaneous_one_sided_lower'] - 2, abs=1e-9)
    assert out == m.joint_intervals(vectors, stats)


def test_lower_bound_is_the_frozen_quantile_of_the_shared_generator():
    vector = np.array([.1, -.2, .3, 0., .5])
    stats = dict(bootstrap_rng_seed=m.BOOTSTRAP_SEED, bootstrap_samples=200,
                 lower_quantile=m.LOWER_Q)
    out = m.joint_intervals({'v': vector, 'w': 2 * vector}, stats)
    rng = np.random.default_rng(m.BOOTSTRAP_SEED)
    indices = rng.integers(0, len(vector), (200, len(vector)))
    samples = vector[indices].mean(axis=1)
    assert out['v']['simultaneous_one_sided_lower'] == float(np.quantile(samples, m.LOWER_Q))
    assert out['w']['simultaneous_one_sided_lower'] == float(np.quantile(2 * samples, m.LOWER_Q))
    assert out['v']['seed_blocks'] == len(vector)


def test_collector_adapter_restores_alpha_globals_on_failure(tmp_path):
    saved = (m.alpha.ART, m.alpha.ROOT, m.alpha.MODELS, m.alpha.ANCHORS, m.alpha.DISPLAY,
             m.alpha.expected_grid)
    with pytest.raises(RuntimeError):
        with m.collector_adapter(tmp_path):
            assert m.alpha.ART == tmp_path and m.alpha.MODELS == ('base', 'control', 'beta')
            assert m.alpha.expected_grid is m.expected_grid
            raise RuntimeError('collection failed')
    assert (m.alpha.ART, m.alpha.ROOT, m.alpha.MODELS, m.alpha.ANCHORS, m.alpha.DISPLAY,
            m.alpha.expected_grid) == saved


def test_display_names_carry_full_model_versions():
    assert m.DISPLAY['base'] == 'Prism Balance v0.1.0 (T=1)'
    assert m.DISPLAY['control'] == 'Prism Balance v0.1.1 candidate (unpublished final-c4; T=1)'
    assert m.DISPLAY['beta'] == 'Prism Beta v0.1.0 candidate (unpublished final-c4; T=1)'
    assert m.DISPLAY['alpha-t1'] == 'Prism Alpha v0.1.4 (T=1)'
    assert set(m.DISPLAY) >= set(m.MODELS) | set(m.ANCHORS) | {'base-t1', 'control-t1', 'alpha-t1'}
