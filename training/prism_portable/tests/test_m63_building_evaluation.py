"""M63 evaluation contracts: fixed seeds, ten gates, direct previous-Beta coverage."""
import copy
from pathlib import Path

import pytest

from scripts import prism_building_evaluation_m63 as m
from scripts import prism_building_prepare_m63 as prepare_m63


def policy():
    return copy.deepcopy(prepare_m63.evaluation_contract())

def test_policy_freezes_m63_seed_blocks_limits_and_ten_gates():
    m.validate_policy(policy())
    assert m.ACTION_SEED == 63042001 and m.BOOTSTRAP_SEED == 63049999
    assert m.LOWER_Q == .05 / 10 and len(m.GATES) == 10
    assert m.GATES['beta/building_utility'] == -.015
    assert m.GATES['beta/early_bonus_auc12'] == .25
    assert m.LIMITS['physical_games'] == 10304 and m.LIMITS['infrastructure_retries'] == 0


def test_policy_rejects_seed_count_or_gate_drift():
    p = policy(); p['acceptance']['direct_total_games'] -= 2
    with pytest.raises(ValueError):
        m.validate_policy(p)
    p = policy(); p['acceptance']['gates'] = {**m.GATES, 'beta/building_utility': .015}
    with pytest.raises(ValueError, ):
        m.validate_policy(p)


@pytest.mark.parametrize('path,value', [
    (('development', 'seed_start'), 9656001),
    (('development', 'seed_end'), 9656030),
    (('acceptance', 'seed_start'), 9661001),
    (('acceptance', 'seed_end'), 9661254),
    (('acceptance', 'direct_seed_end'), 9661510),
    (('acceptance', 'direct_previous_beta_games'), 1022),
    (('acceptance', 'bootstrap_rng_seed'), 63049998),
    (('acceptance', 'one_sided_claims'), 9),
    (('acceptance', 'no_extension_or_checkpoint_selection'), False),
])
def test_policy_rejects_each_frozen_seed_family_and_stop_rule_drift(path, value):
    contract = policy()
    current = contract
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value
    with pytest.raises(ValueError):
        m.validate_policy(contract)


def test_grid_has_shared_anchors_and_previous_beta_direct_match():
    p = policy()
    development = m.stage_grid('development', p)
    acceptance = m.stage_grid('acceptance', p)
    anchor = m.expected_grid(9661000, 9661255)
    direct = m.expected_grid(9661000, 9661511, True)
    assert (len(development), len(anchor), len(direct), len(acceptance)) == (576, 4608, 5120, 9728)
    assert ('beta', 'previous-beta-t1', 9661000, 0) in direct
    assert ('beta', 'previous-beta-t1', 9661511, 1) in direct
    assert len(acceptance | development) == 10304


def test_verdict_keeps_building_tolerance_distinct_from_positive_style_gate():
    measures = {key: {'simultaneous_one_sided_lower': threshold + .001}
                for key, threshold in m.GATES.items()}
    gates = {key: True for key in m.GATES}
    assert m.verdicts(measures, gates)['beta_accepted'] is True
    gates['beta/early_bonus_auc12'] = False
    measures['beta/early_bonus_auc12']['simultaneous_one_sided_lower'] = .249
    verdict = m.verdicts(measures, gates)
    assert verdict['beta_style'] == 'FAIL_BUILDING_STYLE_THRESHOLD'
    assert verdict['beta_acceptance'] == 'NOT_ACCEPTED_BUILDING_CANDIDATE'


def test_source_manifest_returns_exact_sha256_for_new_m63_entrypoints():
    pins = m.source_sha_manifest()
    assert all(len(digest) == 64 and set(digest) <= set('0123456789abcdef') for digest in pins.values())
    assert pins['scripts/prism_building_evaluation_m63.py']
    assert pins['scripts/prism_building_metrics_m63.py']
    assert pins['scripts/prism_building_report_m63.py']
    assert pins['scripts/prism_building_html_report_m63.py']
    assert pins['training/prism_portable/engine/ppo/building_timed.py']


def test_legacy_replay_collector_is_adapted_with_isolated_globals():
    original = m.alpha.collect.__globals__
    original_art = original['ART']
    namespace = dict(original)
    namespace.update(ART=Path('isolated-art'), MODELS=('base', 'control', 'beta'))
    adapted = m.isolated_replay_collector(namespace)
    assert adapted.__globals__ is not original
    assert adapted.__globals__['ART'] == Path('isolated-art')
    assert adapted.__globals__['MODELS'] == ('base', 'control', 'beta')
    assert m.alpha.collect.__globals__['ART'] == original_art


ENGINE = {'path': 'engine.bin', 'sha256': 'a' * 64}


def _tie_row(model, opponent, seed, seat, utility, auc):
    scores = [15, 15]
    return {
        'candidate': model, 'opponent': opponent, 'seed': seed, 'candidate_seat': seat,
        'candidate_score': .5, 'record': 'draw', 'candidate_points': 15, 'opponent_points': 15,
        'scores': scores, 'ranks': [0, 0], 'winners': [0, 1],
        'building_utility': utility[model], 'early_bonus_auc12': auc[model],
    }


def test_acceptance_shards_cover_five_direct_pairs_including_frozen_beta():
    def desc(name):
        return {'program': ENGINE['path'], 'sha256': ENGINE['sha256'],
                'args': ['agent-prism-sample', '--weights', name, '--seed', str(m.ACTION_SEED)],
                'files': [{'path': name, 'sha256': 'b' * 64}]}
    candidates = {name: desc(name) for name in m.MODELS}
    opponents = {name: desc(name) for name in (*m.ANCHORS, 'alpha-t1', 'previous-beta-t1')}
    shards = m.shard_configs('acceptance', policy(), ENGINE, 'catalog-fingerprint', candidates, opponents)
    direct = [item for item in shards if item[1].startswith('direct-')]
    assert len(shards) == 72
    assert len(direct) == 64
    assert sum(count for name, _, _, count in direct) == 5120
    previous = [cfg for _, mode, cfg, _ in direct if mode == 'direct-previous-beta']
    assert len(previous) == 16
    assert {op for cfg in previous for op in cfg['opponents']} == {'previous-beta-t1'}
    assert {seed for cfg in previous for seed in cfg['seeds']} == set(range(9661000, 9661512))
    assert all(set(cfg['candidates']) == {'beta'} for cfg in previous)


def test_measurements_include_previous_beta_as_512_paired_blocks(monkeypatch):
    stats = policy()['acceptance']
    grid = m.stage_grid('acceptance', policy())
    utility = {'base': .2, 'control': .2, 'beta': .2}
    auc = {'base': 1., 'control': 1., 'beta': 1.}
    rows = [_tie_row(model, op, seed, seat, utility, auc)
            for model, op, seed, seat in sorted(grid)]
    observed = {}
    def fake_joint(vectors, actual_stats):
        observed.update({key: value.copy() for key, value in vectors.items()})
        assert actual_stats['bootstrap_rng_seed'] == 63049999
        assert actual_stats['bootstrap_samples'] == 20000
        assert actual_stats['lower_quantile'] == .05 / 10
        return {key: {'mean': float(sum(vector) / len(vector)), 'ci95': [0., 1.],
                      'simultaneous_one_sided_lower': m.GATES[key] + .001,
                      'seed_blocks': len(vector)} for key, vector in vectors.items()}
    monkeypatch.setattr(m, 'joint_intervals', fake_joint)
    measurements, gates = m.measurements(rows, stats)
    assert set(measurements) == set(gates) == set(m.GATES)
    assert len(observed['beta/direct_previous_beta']) == 512
    assert observed['beta/direct_previous_beta'] == [.5] * 512
    assert measurements['beta/direct_previous_beta']['seed_blocks'] == 512
    assert all(gates.values())


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'bad_physical_seat'])
def test_m63_measurement_grid_rejects_missing_duplicate_or_bad_seat(damage):
    stats = policy()['acceptance']
    grid = m.stage_grid('acceptance', policy())
    values = {'base': .1, 'control': .2, 'beta': .3}
    auc = {'base': 1., 'control': 1., 'beta': 2.}
    rows = [_tie_row(model, op, seed, seat, values, auc)
            for model, op, seed, seat in sorted(grid)]
    if damage == 'missing':
        rows.pop()
    elif damage == 'duplicate':
        rows.append(rows[0].copy())
    else:
        rows[0]['candidate_seat'] = 2
    with pytest.raises(ValueError):
        m.measurements(rows, stats)


def test_verify_fails_closed_when_m63_source_sha_is_not_registered(tmp_path):
    work = tmp_path / 'evaluation'; work.mkdir()
    execution = {
        'format': 'm63-building-evaluation-execution-v1',
        **m.LIMITS, 'evaluation': policy(),
        'building_style': m.default_building_config(),
        'timed_building_style': m.default_timed_building_config(),
        'diagnostic_bigcard_style': m.DIAGNOSTIC_STYLE,
        'source_files': list(m.SOURCE_FILES), 'files': {},
    }
    with pytest.raises(ValueError, match='source not pinned'):
        m.verify(work, execution)


def test_verify_rejects_timed_contract_with_a_different_v1_base(tmp_path):
    work = tmp_path / 'evaluation'; work.mkdir()
    execution = {
        'format': 'm63-building-evaluation-execution-v1',
        **m.LIMITS, 'evaluation': policy(),
        'building_style': m.default_building_config(),
        'timed_building_style': m.default_timed_building_config(),
        'diagnostic_bigcard_style': m.DIAGNOSTIC_STYLE,
        'source_files': list(m.SOURCE_FILES), 'files': {},
    }
    execution['timed_building_style']['base_contract']['global_use_cap'] += 1
    with pytest.raises(ValueError):
        m.verify(work, execution)
