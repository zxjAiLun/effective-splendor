"""M55 mathematical/transaction fixtures; no extra live games are launched."""
import copy
import math

import pytest
import torch

from training.prism.export import export_weights
from training.prism.io import sha256_file, tensor_identity
from training.prism.model import PrismModel
from training.prism.ppo.coordinator import Run, validate_config
from training.prism.ppo.style import (extract_rush_profile, extract_style_targets,
                                      profile_from_after_main, validate_style_config)
from training.prism.tests.ppo_support import CATALOG, game, run_config, schedule


def style():
    return {'format': 'prism-rush-style-v1', 'window_main_actions': 16, 'score_cap': 15,
            'diagnostic_horizon_main_actions': 20, 'diagnostic_score_threshold': 8,
            'short_game_padding': 'terminal-prestige',
            'phase_semantics': 'choose_noble-belongs-to-preceding-main', 'terminal_only': True,
            'style_reward_input': 'player-visible-own-prestige-and-terminal-own-prestige'}


def projected(before, terminal, actor=0, noble_at=None):
    rows = []
    for i, score in enumerate(before):
        rows.append({'observation': {'viewer': actor, 'private': {'ignored': 'never read'},
                                     'public': {'current_player': actor, 'phase': 'main',
                                                'players': [{'id': j, 'prestige': score if j == actor else 99}
                                                            for j in range(2)]}},
                     'chosen_action': {'type': 'buy_market'}})
        if noble_at == i:
            r = copy.deepcopy(rows[-1]); r['observation']['public']['phase'] = 'choose_noble'
            r['chosen_action']['type'] = 'choose_noble'; rows.append(r)
    scores = [0, 0]; scores[actor] = terminal
    return {'job_id': 'fixture', 'actor': actor, 'terminal': True, 'decisions': rows,
            'result': {'scores': scores}, 'replay_sha256': 'a'*64, 'sidecar_sha256': 'b'*64}


def test_fixed_denominator_cap_and_no_dropped_short_losses():
    p = profile_from_after_main([0, 3, 8], 8, style())
    assert p['rush_auc'] == pytest.approx((0 + 3 + 8 + 13*8) / (16*15))
    assert p['main_actions'] == 3 and p['shorter_than_reward_window']
    assert p['vp_threshold_by_horizon'] and p['first_main_to_threshold'] == 3
    q = profile_from_after_main([0, 3, 18], 18, style())
    assert q['rush_auc'] == pytest.approx((0 + 3 + 14*15) / (16*15))
    assert profile_from_after_main([0]*25, 0, style())['rush_auc'] == 0


@pytest.mark.parametrize('actor', [0, 1])
def test_projection_uses_own_public_curve_and_counts_noble_once(actor):
    g = projected([0, 0, 3, 8], 15, actor, noble_at=1)
    p = extract_rush_profile(g, style())
    assert p['after_main_prestige'] == [0, 3, 8, 15]
    assert p['main_actions'] == 4 and p['first_main_to_threshold'] == 3
    changed = copy.deepcopy(g)
    for row in changed['decisions']:
        row['observation']['private'] = {'reserved': 'poison', 'future': 2000}
        row['observation']['public']['players'][1-actor]['prestige'] = 123
    changed['result']['scores'][1-actor] = 77
    assert extract_rush_profile(changed, style()) == p


def test_diagnostic_is_distinct_from_reward_window():
    curve = [0]*16 + [8]*5
    p = profile_from_after_main(curve, 8, style())
    assert p['rush_auc'] == 0 and p['vp_threshold_by_horizon']
    assert p['first_main_to_threshold'] == 17


@pytest.mark.parametrize('fault', ['prefix', 'viewer', 'actor', 'phase', 'decrease', 'initial', 'bool'])
def test_rejects_incomplete_or_misbound_projected_curves(fault):
    g = projected([0, 1, 3], 15)
    if fault == 'prefix': g['terminal'] = False
    if fault == 'viewer': g['decisions'][0]['observation']['viewer'] = 1
    if fault == 'actor': g['decisions'][0]['observation']['public']['current_player'] = 1
    if fault == 'phase': g['decisions'][0]['observation']['public']['phase'] = 'unknown'
    if fault == 'decrease': g['decisions'][2]['observation']['public']['players'][0]['prestige'] = 0
    if fault == 'initial': g['decisions'][0]['observation']['public']['players'][0]['prestige'] = 1
    if fault == 'bool': g['result']['scores'][0] = True
    with pytest.raises(ValueError): extract_rush_profile(g, style())


@pytest.mark.parametrize('key', ['window_main_actions', 'score_cap', 'diagnostic_horizon_main_actions', 'diagnostic_score_threshold'])
def test_style_contract_rejects_bool_and_unknown_fields(key):
    c = style(); c[key] = True
    with pytest.raises(ValueError): validate_style_config(c)
    c = style(); c['arbitrary_style_labels'] = True
    with pytest.raises(ValueError): validate_style_config(c)


def test_targets_have_exact_actor_coverage():
    a = projected([0, 2], 15); b = projected([0, 5], 12, actor=1)
    values, summary = extract_style_targets([a, b], style())
    assert set(values) == {('fixture', 0), ('fixture', 1)}
    assert summary['mean_rush_auc'] == math.fsum(values.values()) / 2
    with pytest.raises(ValueError): extract_style_targets([a, a], style())


def test_v3_beta_zero_is_identical_initial_model_and_legacy_style_stays_rejected(tmp_path):
    weights = tmp_path/'weights.json'; export_weights(PrismModel(), weights, CATALOG)
    config = run_config(sha256_file(weights))
    legacy = Run.create(tmp_path/'legacy', config, weights)
    new = copy.deepcopy(config); new.update(format='prism-ppo-run-v3', arena_contract_sha256='0'*64, style=style())
    current = Run.create(tmp_path/'v3-zero', new, weights)
    assert not current.learner.model.style_enabled
    assert tensor_identity(current.learner.model.state_dict()) == tensor_identity(legacy.learner.model.state_dict())
    config['ppo'].update(style_beta=.3, style_value_weight=.5)
    with pytest.raises(ValueError, match='reward-extractor'): validate_config(config)


def test_positive_style_targets_and_optimizer_survive_seal_step_and_reopen(tmp_path):
    weights = tmp_path/'weights.json'; export_weights(PrismModel(), weights, CATALOG)
    cfg = run_config(sha256_file(weights)); cfg.update(format='prism-ppo-run-v3', arena_contract_sha256='0'*64, style=style())
    cfg['ppo'].update(style_beta=.3, style_value_weight=.5)
    run = Run.create(tmp_path/'style', cfg, weights)
    before_policy = tensor_identity(run.learner.model.policy.state_dict())
    assert run.learner.model.style_enabled
    snapshot = run.begin_cycle(schedule())
    behavior = run._behavior_cache[snapshot['snapshot_sha256']]
    g = game(behavior, count=3)
    projected_rows = projected([0, 2, 4], 15)['decisions']
    for row, visible in zip(g['decisions'], projected_rows):
        row['observation'] = visible['observation']
    # Explicit synthetic completed shard; no process or game is launched.
    with run._transaction():
        run.state['jobs'][g['job_id']] = {'status': 'COMPLETE', 'attempt': 1, 'artifact': run.store.put_json(g)}
        run.state['decisions'] = 3
        run._commit()
    run.seal()
    batch = run.store.get_json(run.state['batch'])
    expected = (2 + 4 + 14*15)/(16*15)
    assert all(r['style_return'] == pytest.approx(expected) and r['outcome'] == 1 for r in batch['rows'])
    resumed = Run.open(tmp_path/'style')
    assert resumed.learner.model.style_enabled
    assert tensor_identity(resumed.learner.model.state_dict()) == tensor_identity(run.learner.model.state_dict())
    metrics = resumed.step()
    assert metrics['optimizer_applied']
    after = Run.open(tmp_path/'style')
    assert after.state['cursor'] == 2 and after.state['global_step'] == 1
    assert tensor_identity(after.learner.model.policy.state_dict()) != before_policy
    assert any(m.get('event') == 'style_extracted' for m in after.state['metrics'])
    assert after.learner.optimizer.state_dict()['state']
