"""Public wire-format mathematical fixtures; no games or training are launched."""
import copy
import json
import math
from pathlib import Path
import re

import pytest

from training.prism.ppo import style as legacy_rush
from training.prism_portable.engine.io import canonical_hash
from training.prism_portable.engine.ppo import style
from training.prism_portable.engine.ppo.building import (
    BASE_CATALOG_FINGERPRINT, CARD_CATALOG, COLORS, default_building_config,
    extract_building_profile, profile_from_own_decisions, validate_building_config,
)

ROOT = Path(__file__).resolve().parents[3]


def gems(**counts):
    return dict.fromkeys((*COLORS, 'gold'), 0) | counts


def projected(events, actor=0):
    """Match Rust Observation/Action wire shape using real public catalog IDs.

    These fixtures check measurement mathematics and continuity, not action
    legality. The production Rust auditor verifies legality/terminal provenance.
    """
    owned, reserved, bonuses, rows = [], [], [0] * 5, []
    prestige = 0
    for event in events:
        if type(event) is int:
            kind, card_id = 'buy_market', event
        elif isinstance(event, tuple):
            kind, card_id = event
        else:
            kind, card_id = event, None
        market = [[12, 16, 22, 13], [65, 63, 43, 57], [81, 87, 76, 83]]
        if card_id is not None:
            tier = CARD_CATALOG[card_id][0]
        if kind in ('buy_market', 'reserve_market'):
            market[('One', 'Two', 'Three').index(tier)][2] = card_id
            action = {'type': kind, 'tier': tier, 'slot': 2}
            if kind == 'reserve_market':
                action['return'] = gems()
        elif kind == 'reserve_deck':
            action = {'type': kind, 'tier': tier, 'return': gems()}
        elif kind == 'buy_reserved':
            slot = next(i for i, r in enumerate(reserved) if r['card'] == card_id)
            action = {'type': kind, 'slot': slot}
        elif kind == 'choose_noble':
            action = {'type': kind, 'noble': 0}
        elif kind == 'take_tokens':
            action = {'type': kind, 'take': gems(blue=2), 'return': gems()}
        else:
            action = {'type': kind}
        players = [{'id': j, 'tokens': gems(), 'bonuses': list(bonuses) if j == actor else [0] * 5,
                    'prestige': prestige if j == actor else 14, 'reserved_count': len(reserved) if j == actor else 3,
                    'public_reserved': [r['card'] for r in reserved if not r['from_deck']] if j == actor else [],
                    'purchased': sorted(owned) if j == actor else [], 'nobles': []} for j in range(2)]
        obs = {'viewer': actor, 'ruleset_fingerprint': BASE_CATALOG_FINGERPRINT,
               'public': {'player_count': 2, 'current_player': actor,
                          'phase': 'choose_noble' if kind == 'choose_noble' else 'main',
                          'bank': gems(white=4, blue=4, green=4, red=4, black=4, gold=5),
                          'market': market, 'deck_counts': [36, 26, 16], 'nobles': [0, 1, 2],
                          'players': players, 'end_game_triggered': False,
                          'turns_remaining_in_final_round': None, 'consecutive_forced_passes': 0,
                          'pending_nobles': [0, 1] if kind == 'choose_noble' else []},
               'private': {'reserved': copy.deepcopy(reserved)}}
        rows.append({'observation': obs, 'chosen_action': action, 'visible_history': []})
        if kind in ('buy_market', 'buy_reserved'):
            owned.append(card_id)
            bonuses[CARD_CATALOG[card_id][1]] += 1
            prestige += CARD_CATALOG[card_id][2]
            if kind == 'buy_reserved':
                reserved.pop(action['slot'])
                for slot, entry in enumerate(reserved):
                    entry['slot'] = slot
        elif kind in ('reserve_market', 'reserve_deck'):
            reserved.append({'slot': len(reserved), 'card': card_id, 'tier': tier,
                             'from_deck': kind == 'reserve_deck'})
        elif kind == 'choose_noble':
            prestige += 3
    scores = [15, 15]
    scores[actor] = prestige
    return {'format': 'prism-ppo-game-v1', 'job_id': 'fixture', 'actor': actor,
            'catalog_fingerprint': BASE_CATALOG_FINGERPRINT, 'terminal': True,
            'decisions': rows, 'result': {'scores': scores, 'ranks': [1, 0] if actor == 0 else [0, 1],
                                        'winners': [1 - actor], 'reason': 'prestige_threshold'},
            'replay_sha256': 'a' * 64, 'sidecar_sha256': 'b' * 64}


def profile(events, actor=0):
    return extract_building_profile(projected(events, actor), default_building_config())


def test_public_catalog_exactly_matches_rust_and_colour_order():
    source = (ROOT / 'crates/splendor-catalog/src/cards.rs').read_text(encoding='utf-8')
    pattern = r'c\((\d+), (One|Two|Three), (White|Blue|Green|Red|Black), ([\d, ]+)\)'
    definitions = re.findall(pattern, source)
    assert len(definitions) == len(CARD_CATALOG) == 90
    assert COLORS == ('white', 'blue', 'green', 'red', 'black')
    for index, (card_id, tier, colour, numbers) in enumerate(definitions):
        vp, *cost = map(int, numbers.split(','))
        assert int(card_id) == index
        assert CARD_CATALOG[index] == (tier, COLORS.index(colour.lower()), vp, tuple(cost))
    rust_colours = (ROOT / 'crates/splendor-catalog/src/lib.rs').read_text(encoding='utf-8')
    for index, colour in enumerate(COLORS):
        assert f'{colour.title()} = {index}' in rust_colours


@pytest.mark.parametrize('key', list(default_building_config()))
def test_config_is_an_exact_fixed_discriminator(key):
    config = default_building_config()
    assert style.validate_style_config(config) is config
    assert validate_building_config(config) is config
    broken = copy.deepcopy(config)
    value = broken[key]
    broken[key] = True if type(value) is int else (False if type(value) is bool else 'wrong')
    with pytest.raises(ValueError):
        style.validate_style_config(broken)
    broken = config | {'unknown': 0}
    with pytest.raises(ValueError):
        style.validate_style_config(broken)
    broken = dict(config)
    del broken[key]
    with pytest.raises(ValueError):
        style.validate_style_config(broken)


@pytest.mark.parametrize('actor', [0, 1])
def test_own_market_purchases_bonus_ordinal_and_no_self_credit(actor):
    p = profile([0, 1, 4, 42], actor)
    # Blue ordinals 1,2,3. Card4's blue printed cost1 uses ordinal1 only;
    # its new ordinal3 cannot credit its acquisition. Card42 cost5 uses all3.
    assert [i['bonus_ordinal'] for i in p['investments']] == [1, 2, 3]
    assert [i['use_main_actions'] for i in p['investments']] == [[3, 4], [4], [4]]
    assert p['building_use_units'] == 4
    assert p['building_utility'] == 4 / 24
    assert p['early_lowvp_buys'] == 3 and p['early_buys'] == 4
    assert p['after_main_bonuses'][-1] == [0, 4, 0, 0, 0]
    assert profile([4], actor)['building_utility'] == 0


@pytest.mark.parametrize('investment,target,colour', [(24, 8, 'white'), (0, 9, 'blue'),
                                                      (32, 16, 'green'), (8, 32, 'red'),
                                                      (16, 0, 'black')])
def test_canonical_colour_order(investment, target, colour):
    p = profile([investment, target])
    assert p['investments'][0]['colour'] == colour
    assert p['investments'][0]['use_main_actions'] == [2]
    assert p['building_use_units'] == 1


def test_noninvestment_bonus_still_determines_later_ordinal():
    p = profile([42, 0, 4])
    assert p['early_lowvp_buys'] == 2
    assert p['investments'][0]['bonus_ordinal'] == 2
    assert p['building_use_units'] == 0  # Card4 has blue cost1 < ordinal2.
    assert p['early_bonus_auc12'] == pytest.approx((1 + 2 + 10 * 3) / 12)


@pytest.mark.parametrize('from_deck', [False, True])
def test_reserved_purchase_resolves_current_own_slot_and_known_id(from_deck):
    reserve = 'reserve_deck' if from_deck else 'reserve_market'
    g = projected([0, ('reserve_market', 47), (reserve, 42), ('buy_reserved', 42), ('buy_reserved', 47)])
    p = extract_building_profile(g, default_building_config())
    assert g['decisions'][3]['chosen_action'] == {'type': 'buy_reserved', 'slot': 1}
    assert g['decisions'][4]['chosen_action'] == {'type': 'buy_reserved', 'slot': 0}
    assert p['main_actions'] == 5
    assert p['investments'][0]['use_main_actions'] == [4, 5]
    assert p['building_utility'] == 2 / 24
    assert p['early_lowvp_buys'] == 2  # Reservation itself earns no reward.


def test_choose_noble_belongs_to_purchase_and_does_not_advance_main():
    base = projected(['take_tokens'] * 10 + [0, 42])
    noble = projected(['take_tokens'] * 10 + [0, 'choose_noble', 42, 'choose_noble'])
    a = extract_building_profile(base, default_building_config())
    b = extract_building_profile(noble, default_building_config())
    assert b['main_actions'] == 12 and b['decision_actions'] == 14
    assert b['building_utility'] == a['building_utility'] == 1 / 24
    assert b['after_main_bonuses'] == a['after_main_bonuses']
    assert b['investments'] == a['investments']


def test_short_losses_unredeemed_and_descriptive_terminal_padding_retained():
    short = projected([0])
    no_buys = projected(['take_tokens'])
    targets, summary = style.extract_style_targets([short, no_buys | {'job_id': 'zero'}], default_building_config())
    assert len(summary['games']) == 2 and set(targets.values()) == {0.0}
    p = summary['games'][0]
    assert p['early_bonus_auc12'] == 1.0  # Raw held discounts, not reward.
    assert p['early_bonus_auc12_unit'] == 'permanent-discounts'
    assert p['early_bonus_auc12_padding'] == 'held-at-terminal-descriptive-only'
    assert p['early_bonus_auc12_padding_main_actions'] == 11
    assert p['unredeemed_investments'] == p['censored_investments'] == 1
    assert p['unredeemed_censored_investments'] == 1
    assert p['building_observed_use_units'] == 0
    assert p['observed_main13to24'] == p['observed_main25to32'] == 0
    assert p['late_vp_bought_main13to24'] == p['late_scoring_vp_main25to32'] == 0
    assert summary['short_game_fraction'] == 1.0
    assert summary['mean_early_bonus_auc12'] == 0.5
    assert summary['investment_redemption_rate'] == 0.0
    _, empty = style.extract_style_targets([no_buys], default_building_config())
    assert empty['investment_redemption_rate'] is None


def test_per_investment_cap_and_actual_uses_preserved():
    p = profile([0, 42, 45, 67, 87])
    assert p['building_observed_use_units'] == 4
    assert p['building_use_units'] == 3 and p['building_utility'] == 3 / 24
    assert p['investments'][0]['use_main_actions'] == [2, 3, 4, 5]
    assert not p['investments'][0]['censored']  # Cap already exhausted.
    assert p['redemption_horizon_censored']


def test_global_cap_exactly_bounded_and_full_profile_retained():
    # Twelve lowVP investments, three each in W/G/R/K. Later cards have
    # printed costs >= ordinal3 in several colours, reaching 36 capped units.
    early = [24, 25, 26, 32, 33, 34, 8, 9, 10, 16, 17, 18]
    p = profile(early + list(range(70, 82)))
    assert p['early_lowvp_buys'] == 12
    assert p['building_use_units_before_global_cap'] == 36
    assert p['building_use_units'] == 24 and p['building_utility'] == 1.0
    assert not p['redemption_horizon_censored']
    assert p['censored_investments'] == 0
    assert all(i['credited_uses'] <= 3 for i in p['investments'])
    assert p['early_bonus_auc12'] == 6.5


def test_reward_window_edges_late_investment_and_postwindow_scoring():
    events = ['take_tokens'] * 11 + [0, 1] + ['take_tokens'] * 10 + [42, 45]
    # Main12 investment0, Main13 lowVP1 is ignored. Main24 uses bonus0;
    # Main25 is scoring diagnostic only and cannot add a rewarded use.
    p = profile(events)
    assert p['main_actions'] == 25 and p['early_lowvp_buys'] == 1
    assert p['investments'][0]['acquired_main'] == 12
    assert p['investments'][0]['use_main_actions'] == [24]
    assert p['building_utility'] == 1 / 24
    assert p['late_vp_bought_main13to24'] == 2
    assert p['late_scoring_vp_main25to32'] == 3
    assert p['observed_main13to24'] == 12 and p['observed_main25to32'] == 1
    assert p['early_bonus_auc12'] == 1 / 12
    late_only = profile(['take_tokens'] * 12 + [0, 42])
    assert late_only['building_utility'] == 0 and late_only['early_lowvp_buys'] == 0
    main32 = profile(['take_tokens'] * 24 + [42] + ['take_tokens'] * 6 + [45, 87])
    assert main32['late_scoring_vp_main25to32'] == 5  # Main33 excluded.
    assert main32['observed_main25to32'] == 8
    assert not main32['late_scoring_main25to32_censored']


@pytest.mark.parametrize('actor', [0, 1])
def test_hidden_card_and_opponent_and_tokens_independence(actor):
    g = projected([0, ('reserve_deck', 87), ('reserve_market', 42), ('buy_reserved', 42)], actor)
    expected = extract_building_profile(g, default_building_config())
    changed = copy.deepcopy(g)
    changed['raw_replay'] = {'private_deck': 'poison', 'opponent_reserved': 'poison'}
    changed['result'] = {'scores': ['poison', 'poison'], 'ranks': ['ignored']}
    for row in changed['decisions']:
        obs = row['observation']
        obs['public']['players'][1 - actor] = {'hidden_card': 'poison', 'bonuses': 'poison'}
        obs['public']['players'][actor]['tokens'] = 'poison'
        obs['public']['players'][actor]['prestige'] = 'poison'
        obs['public']['bank'] = obs['public']['deck_counts'] = 'poison'
        obs['opponent_private'] = 'poison'
        row['visible_history'] = 'poison'
        # Non-target own reserved identities are not inputs. The chosen own
        # card's known identity remains unchanged when buying slot1.
        for entry in obs['private']['reserved']:
            if entry['slot'] == 0:
                entry['card'] = 89
        if row['chosen_action']['type'] != 'buy_reserved':
            obs['private'] = 'poison'
    assert extract_building_profile(changed, default_building_config()) == expected


@pytest.mark.parametrize('fault', ['prefix', 'viewer', 'bool_viewer', 'actor', 'id', 'phase',
                                   'catalog', 'obs_catalog', 'missing_target', 'missing_slot',
                                   'bad_colour_counts', 'missing_bonus', 'bool_bonus', 'bonus_width',
                                   'purchase_gap', 'initial_purchase', 'unknown_card', 'bool_card',
                                   'inline_card', 'tier_mismatch', 'repeated_purchase', 'duplicate_history',
                                   'unknown_action', 'noble_main', 'noble_first', 'noble_after_tokens'])
def test_malformed_and_incomplete_own_states_fail_closed(fault):
    g = projected([0, 42])
    first, second = g['decisions']
    obs = first['observation']
    own = obs['public']['players'][0]
    if fault == 'prefix': g['terminal'] = False
    if fault == 'viewer': obs['viewer'] = 1
    if fault == 'bool_viewer': obs['viewer'] = False
    if fault == 'actor': obs['public']['current_player'] = 1
    if fault == 'id': own['id'] = 1
    if fault == 'phase': obs['public']['phase'] = 'unknown'
    if fault == 'catalog': g['catalog_fingerprint'] = 'arbitrary'
    if fault == 'obs_catalog': obs['ruleset_fingerprint'] = 'arbitrary'
    if fault == 'missing_target': obs['public']['market'][0][2] = None
    if fault == 'missing_slot': del first['chosen_action']['slot']
    if fault == 'bad_colour_counts': second['observation']['public']['players'][0]['bonuses'] = [1, 0, 0, 0, 0]
    if fault == 'missing_bonus': del own['bonuses']
    if fault == 'bool_bonus': own['bonuses'][0] = False
    if fault == 'bonus_width': own['bonuses'] = [0] * 4
    if fault == 'purchase_gap': second['observation']['public']['players'][0].update(purchased=[0, 1], bonuses=[0, 2, 0, 0, 0])
    if fault == 'initial_purchase': own.update(purchased=[1], bonuses=[0, 1, 0, 0, 0])
    if fault == 'unknown_card': obs['public']['market'][0][2] = 90
    if fault == 'bool_card': obs['public']['market'][0][2] = False
    if fault == 'inline_card': obs['public']['market'][0][2] = {'id': 0, 'bonus': 'gold'}
    if fault == 'tier_mismatch': obs['public']['market'][0][2] = 42
    if fault == 'repeated_purchase': second['chosen_action'].update(tier='One'); second['observation']['public']['market'][0][2] = 0
    if fault == 'duplicate_history': second['observation']['public']['players'][0].update(purchased=[0, 0], bonuses=[0, 2, 0, 0, 0])
    if fault == 'unknown_action': first['chosen_action'] = {'type': 'invented'}
    if fault == 'noble_main': second['chosen_action'] = {'type': 'choose_noble', 'noble': 0}
    if fault == 'noble_first': g = projected(['choose_noble'])
    if fault == 'noble_after_tokens': g = projected(['take_tokens', 'choose_noble'])
    with pytest.raises(ValueError):
        extract_building_profile(g, default_building_config())


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'wrong_tier', 'unknown_id', 'bool_slot'])
def test_missing_or_malformed_reserved_target_rejected(fault):
    g = projected([0, ('reserve_deck', 42), ('buy_reserved', 42)])
    row = g['decisions'][-1]
    reserved = row['observation']['private']['reserved']
    if fault == 'missing': reserved.clear()
    if fault == 'duplicate': reserved.append(dict(reserved[0]))
    if fault == 'wrong_tier': reserved[0]['tier'] = 'One'
    if fault == 'unknown_id': reserved[0]['card'] = -1
    if fault == 'bool_slot': row['chosen_action']['slot'] = False
    with pytest.raises(ValueError):
        extract_building_profile(g, default_building_config())


def test_profiles_both_seats_targets_coverage_and_ratios_from_totals():
    games = [projected([0, 42]), projected([0, 1, 4], actor=1)]
    targets, summary = style.extract_style_targets(games, default_building_config())
    assert set(targets) == {('fixture', 0), ('fixture', 1)}
    assert targets == {('fixture', 0): 1 / 24, ('fixture', 1): 1 / 24}
    assert summary['mean_building_utility'] == math.fsum(targets.values()) / 2
    assert summary['investment_redemption_rate'] == 2 / 4  # Not mean(1/1, 1/3).
    assert summary['format'] == 'prism-building-targets-v1'
    assert 'mean_rush_auc' not in summary
    assert summary['style_contract_sha256'] == canonical_hash(default_building_config())
    for g, p in zip(games, summary['games']):
        offline = profile_from_own_decisions(g['decisions'], g['actor'], default_building_config())
        assert all(p[key] == value for key, value in offline.items())
    with pytest.raises(ValueError, match='duplicate'):
        style.extract_style_targets([games[0], games[0]], default_building_config())
    with pytest.raises(ValueError):
        style.extract_style_targets([], default_building_config())
    with pytest.raises(ValueError):
        profile_from_own_decisions(games[0]['decisions'], 0, default_building_config(), terminal=False)


def rush_config():
    return {'format': 'prism-rush-style-v1', 'window_main_actions': 16, 'score_cap': 15,
            'diagnostic_horizon_main_actions': 20, 'diagnostic_score_threshold': 8,
            'short_game_padding': 'terminal-prestige',
            'phase_semantics': 'choose_noble-belongs-to-preceding-main', 'terminal_only': True,
            'style_reward_input': 'player-visible-own-prestige-and-terminal-own-prestige'}


@pytest.mark.parametrize('actor', [0, 1])
@pytest.mark.parametrize('curve', [[0], [0, 3, 8], [0, 3, 18], [0] * 25, [0] * 16 + [8] * 5])
def test_rush_profiles_and_summary_serialized_bytes_unchanged(actor, curve):
    config = rush_config()
    assert style.validate_style_config(config) is config
    assert style.profile_from_after_main(curve, curve[-1], config) == legacy_rush.profile_from_after_main(curve, curve[-1], config)
    g = projected(['take_tokens'] * len(curve), actor)
    for row, score in zip(g['decisions'], [0] + curve[:-1]):
        row['observation']['public']['players'][actor]['prestige'] = score
        # Rush must remain insensitive to all building-specific inputs.
        row['observation']['private'] = 'poison'
        row['observation']['public']['market'] = 'poison'
        row['observation']['public']['players'][actor]['bonuses'] = 'poison'
        row['observation']['public']['players'][actor]['purchased'] = 'poison'
    g['result']['scores'][actor] = curve[-1]
    if len(curve) > 1:
        row = copy.deepcopy(g['decisions'][1])
        row['observation']['public']['phase'] = 'choose_noble'
        row['chosen_action'] = {'type': 'choose_noble', 'noble': 0}
        g['decisions'].insert(2, row)
    actual_targets, actual_summary = style.extract_style_targets([g], config)
    old_targets, old_summary = legacy_rush.extract_style_targets([g], config)
    assert actual_targets == old_targets
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    assert encode(actual_summary) == encode(old_summary)
    assert style.extract_rush_profile(g, config) == legacy_rush.extract_rush_profile(g, config)


@pytest.mark.parametrize('fault', ['bool_window', 'extra', 'bad_semantics', 'wrong_format'])
def test_old_rush_invalid_configs_still_rejected(fault):
    config = rush_config()
    if fault == 'bool_window': config['window_main_actions'] = True
    if fault == 'extra': config['early_max_printed_vp'] = 1
    if fault == 'bad_semantics': config['short_game_padding'] = 'none'
    if fault == 'wrong_format': config['format'] = 'prism-building-style-v1'
    with pytest.raises(ValueError): style.validate_style_config(config)
    with pytest.raises(ValueError): legacy_rush.validate_style_config(config)
