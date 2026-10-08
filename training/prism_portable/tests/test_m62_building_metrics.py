"""M62 building metrics from synthetic own-view projections and paired-seat rows.

The native projection intake is exercised against the documented wire schema
{"format": "prism-building-projection-v1", "games": [{"replay_path", "replay_sha256",
"seed", "catalog_fingerprint", "terminal", "result", "players": [{"actor",
"decisions": [{"ply", "observation", "chosen_action"}]}]}]} via a fake pinned
exporter. All fixtures are synthetic decisions over the public catalog; no games,
network, benchmark or local-artifact writes. Seat aggregation always goes through
model identity: physical P0 is not the candidate by definition.
"""
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts import prism_building_metrics_m62 as bmetrics
from scripts import prism_match_details as details
from training.prism_portable.engine.io import canonical_hash
from training.prism_portable.engine.ppo.building import (
    BASE_CATALOG_FINGERPRINT, CARD_CATALOG, COLORS, default_building_config,
    profile_from_own_decisions)

SCHEMA = 'prism-building-projection-v1'
CONFIG = default_building_config()
# Card 7: One/blue/VP1, 15: One/red/VP1, 31: One/white/VP1,
# 43: Two/blue/VP2 cost (5,3,0,0,0) redeems blue only, 45: Two/red/VP2 cost (3,0,0,0,5) redeems nothing.
# Actor 0 buys card 7 then card 43 at main 13 (one redeemed investment).
ACTOR0_EVENTS = [('buy_market', 7)] + ['take_tokens'] * 11 + [('buy_market', 43)]
# Actor 1 buys card 15 (never redeemed) -> utility 0, auc 11/12.
ACTOR1_EVENTS = ['take_tokens', ('buy_market', 15)] + ['take_tokens'] * 10 + [('buy_market', 45)]
# Actor 1b buys three early low-VP investments; card 42 (blue-only cost) redeems
# exactly the blue one -> 1 of 3 redeemed, utility 1/24, auc (1+2+3+3*9)/12 = 2.75.
ACTOR1B_EVENTS = [('buy_market', 7), ('buy_market', 15), ('buy_market', 31)] + \
    ['take_tokens'] * 9 + [('buy_market', 42)]


def empty_gems():
    return dict.fromkeys((*COLORS, 'gold'), 0)


def decision_row(actor, owned, bonuses, reserved, kind, card_id):
    market = [[12, 16, 22, 13], [65, 63, 43, 57], [81, 87, 76, 83]]
    tier = None
    if card_id is not None:
        tier = CARD_CATALOG[card_id][0]
        market[('One', 'Two', 'Three').index(tier)][2] = card_id
    if kind == 'buy_market':
        action = {'type': 'buy_market', 'tier': tier, 'slot': 2}
    else:
        action = {'type': 'take_tokens', 'take': dict(empty_gems(), blue=2), 'return': empty_gems()}
    players = []
    for seat in range(2):
        own = seat == actor
        players.append(dict(id=seat, tokens=empty_gems(), bonuses=list(bonuses) if own else [0] * 5,
                            prestige=5 if own else 14, reserved_count=len(reserved) if own else 3,
                            public_reserved=[r['card'] for r in reserved if not r['from_deck']]
                            if own else [],
                            purchased=sorted(owned) if own else [], nobles=[]))
    observation = dict(viewer=actor, ruleset_fingerprint=BASE_CATALOG_FINGERPRINT,
                       public=dict(player_count=2, current_player=actor, phase='main',
                                   bank=dict(empty_gems(), white=4, blue=4, green=4, red=4,
                                             black=4, gold=5),
                                   market=market, deck_counts=[36, 26, 16], nobles=[0, 1, 2],
                                   players=players, end_game_triggered=False,
                                   turns_remaining_in_final_round=None,
                                   consecutive_forced_passes=0, pending_nobles=[]),
                       private=dict(reserved=[dict(entry) for entry in reserved]))
    return {'observation': observation, 'chosen_action': action}


def own_decisions(actor, events):
    owned, bonuses, reserved = [], [0] * 5, []
    rows = []
    for event in events:
        kind, card_id = ('take_tokens', None) if event == 'take_tokens' else event
        rows.append(decision_row(actor, owned, bonuses, reserved, kind, card_id))
        if kind == 'buy_market':
            owned.append(card_id)
            bonuses[CARD_CATALOG[card_id][1]] += 1
    return rows


def synthetic_replay(path, seed, result, events0=ACTOR0_EVENTS, events1=ACTOR1_EVENTS):
    """Saved replay with both actors' own views; the exporter re-projects each actor."""
    first, second = own_decisions(0, events0), own_decisions(1, events1)
    steps = []
    for index in range(max(len(first), len(second))):
        for actor, decisions in ((0, first), (1, second)):
            if index < len(decisions):
                decisions[index]['ply'] = len(steps)
                steps.append(dict(actor=actor, ply=len(steps), action=decisions[index]['chosen_action']))
    replay = dict(seed=seed, ruleset_fingerprint=BASE_CATALOG_FINGERPRINT, result=result,
                  steps=steps, own_views=[[row['observation'] for row in first],
                                          [row['observation'] for row in second]])
    bmetrics.write(path, replay)
    return replay


def match_row(candidate, opponent, seed, seat, replay_path, *, win=True, points=(15, 14)):
    winner = seat if win else 1 - seat
    scores = list(points) if winner == 0 else list(reversed(points))
    return dict(candidate=candidate, opponent=opponent, seed=seed, candidate_seat=seat,
                candidate_score=1. if win else 0., record='win' if win else 'loss',
                candidate_points=scores[seat], opponent_points=scores[1 - seat],
                scores=scores, ranks=[0, 1] if winner == 0 else [1, 0], winners=[winner],
                _replay_path=str(replay_path))


def documented_projection(replay, replay_path):
    """The exact documented schema emitted by the pinned native projection tool."""
    players, seen = [], {0: 0, 1: 0}
    for actor in (0, 1):
        decisions = []
        for step in replay['steps']:
            if step['actor'] == actor:
                decisions.append(dict(ply=step['ply'],
                                      observation=replay['own_views'][actor][seen[actor]],
                                      chosen_action=step['action']))
                seen[actor] += 1
        players.append(dict(actor=actor, decisions=decisions))
    return dict(format=SCHEMA, replay_path=str(replay_path), replay_sha256=bmetrics.sha(replay_path),
                seed=replay['seed'], catalog_fingerprint=replay['ruleset_fingerprint'],
                terminal=True, result=replay['result'], players=players)


def fake_projection_tool(argv, **kwargs):
    """Stand-in for the pinned exporter: manifest in, documented schema out."""
    manifest = bmetrics.read(argv[1])
    games = []
    for row in manifest['rows']:
        if not Path(row['replay_path']).exists():
            return SimpleNamespace(returncode=3, stdout='', stderr='replay verification failed')
        replay = bmetrics.read(row['replay_path'])
        games.append(documented_projection(replay, row['replay_path']))
    bmetrics.write(argv[2], dict(format=SCHEMA, games=games))
    return SimpleNamespace(returncode=0, stdout='', stderr='')


def execution_with_projection(tmp_path, *, pin=True):
    binary = tmp_path / 'projection-tool.exe'
    binary.write_bytes(b'synthetic native projection tool')
    digest = bmetrics.sha(binary)
    projection = dict(path=str(binary), sha256=digest if pin else 'e' * 64)
    return dict(binaries=dict(projection=projection), building_style=CONFIG,
                files={str(binary): digest} if pin else {})


def run_collect(rows, execution, stage_root, tool=fake_projection_tool):
    stage_root = Path(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)
    with patch.object(bmetrics.subprocess, 'run', side_effect=tool):
        return bmetrics.collect(rows, stage_root, execution)


def beta_alpha_rows(tmp_path):
    """Two games of beta vs alpha-t1 with beta's physical seat exchanged.

    Game one: beta owns ACTOR0_EVENTS at physical seat 0. Game two: beta owns the
    same sequence at physical seat 1 and alpha-t1 takes the seat-0 side.
    """
    result0 = dict(scores=[15, 14], ranks=[0, 1], winners=[0], reason='prestige_threshold')
    result1 = dict(scores=[14, 15], ranks=[1, 0], winners=[1], reason='prestige_threshold')
    synthetic_replay(tmp_path / 'replay-seat0.json', 9641510, result0)
    synthetic_replay(tmp_path / 'replay-seat1.json', 9641511, result1,
                     events0=ACTOR1_EVENTS, events1=ACTOR0_EVENTS)
    return [match_row('beta', 'alpha-t1', 9641510, 0, tmp_path / 'replay-seat0.json'),
            match_row('beta', 'alpha-t1', 9641511, 1, tmp_path / 'replay-seat1.json')]


def test_projection_intake_accepts_the_documented_schema_verbatim(tmp_path):
    replay_path = tmp_path / 'replay.json'
    replay = synthetic_replay(replay_path, 9641511, dict(scores=[15, 14], ranks=[0, 1], winners=[0], reason='prestige_threshold'))
    row = match_row('beta', 'alpha-t1', 9641511, 0, replay_path)
    game = documented_projection(replay, replay_path)
    assert set(game) == {'format', 'replay_path', 'replay_sha256', 'seed', 'catalog_fingerprint',
                         'terminal', 'result', 'players'}
    assert game['format'] == SCHEMA and game['terminal'] is True
    for player in game['players']:
        assert set(player) == {'actor', 'decisions'}
        assert all(set(decision) == {'ply', 'observation', 'chosen_action'}
                   for decision in player['decisions'])
    profiles = bmetrics.profiles_from_projection(row, game, replay, CONFIG)
    assert [profile['actor'] for profile in profiles] == [0, 1]
    assert profiles[0]['main_actions'] == 13 and profiles[0]['decision_actions'] == 13
    assert profiles[0]['building_utility'] == pytest.approx(1 / 24)
    assert profiles[0]['early_bonus_auc12'] == pytest.approx(1.)
    assert profiles[1]['building_utility'] == 0.
    assert profiles[1]['early_bonus_auc12'] == pytest.approx(11 / 12)
    assert profiles[1]['unredeemed_investments'] == 1


def test_projection_intake_rejects_schema_drift(tmp_path):
    replay_path = tmp_path / 'replay.json'
    replay = synthetic_replay(replay_path, 9641511, dict(scores=[15, 14], ranks=[0, 1], winners=[0], reason='prestige_threshold'))
    row = match_row('beta', 'alpha-t1', 9641511, 0, replay_path)

    def damaged(mutate):
        game = documented_projection(replay, replay_path)
        mutate(game)
        with pytest.raises(ValueError):
            bmetrics.profiles_from_projection(row, game, replay, CONFIG)

    damaged(lambda g: g['players'][0]['decisions'].pop())                     # omitted own decision
    damaged(lambda g: g['players'][0]['decisions'][0].__setitem__('ply', 99))  # ply coverage
    damaged(lambda g: g['players'][0]['decisions'][0].__setitem__('chosen_action',
                                                                  {'type': 'pass'}))  # action mismatch
    damaged(lambda g: g['players'][0]['decisions'][0].__setitem__('extra', 1))  # hidden field
    damaged(lambda g: g['players'].__setitem__(0, dict(g['players'][0], actor=1)))  # actor order
    damaged(lambda g: g['players'].append(dict(g['players'][0], actor=2)))    # extra actor
    damaged(lambda g: g.__setitem__('replay_sha256', '0' * 64))               # hash mismatch
    damaged(lambda g: g.__setitem__('replay_path', str(tmp_path / 'other.json')))
    damaged(lambda g: g.__setitem__('seed', 1))                               # seed drift
    damaged(lambda g: g.__setitem__('terminal', False))                       # non-terminal prefix
    damaged(lambda g: g.__setitem__('catalog_fingerprint', 'f' * 64))         # catalog drift
    damaged(lambda g: g.__setitem__('result', dict(scores=[0, 0], ranks=[0, 0], winners=[0, 1], reason='x')))
    damaged(lambda g: g['players'][0]['decisions'][0]['observation']['public'].__setitem__(
        'FullState', {}))                                                     # hidden observation field


def test_visible_observation_enforces_the_actor_visible_boundary():
    import json

    def json_copy(value):
        return json.loads(json.dumps(value))

    observation = own_decisions(0, ACTOR0_EVENTS)[0]['observation']
    assert bmetrics.visible_observation(json_copy(observation), 0)
    cases = [
        (lambda o: o['public'].pop('bank'), 'projection observation boundary drift'),
        (lambda o: o.__setitem__('viewer', 1), 'projection viewer mismatch'),
        (lambda o: o['public'].__setitem__('player_count', 3),
         'projection public actor/count drift'),
        (lambda o: o['public']['players'][0].__setitem__('hidden', 1),
         'hidden/private public player field'),
        (lambda o: o['private'].__setitem__('full_deck', []),
         'projection observation boundary drift'),
        (lambda o: o['public'].__setitem__('current_player', 1),
         'projection public actor/count drift')]
    for mutate, message in cases:
        broken = json_copy(observation)
        mutate(broken)
        with pytest.raises(ValueError, match=message.replace('(', '\\(')):
            bmetrics.visible_observation(broken, 0)
    # Viewer must equal the requesting actor even for a valid observation.
    with pytest.raises(ValueError, match='viewer'):
        bmetrics.visible_observation(json_copy(observation), 1)


def test_collect_covers_both_actors_and_aggregates_by_model_identity(tmp_path):
    execution = execution_with_projection(tmp_path)
    stage_root = tmp_path / 'stage'
    rows = beta_alpha_rows(tmp_path)
    result = run_collect(rows, execution, stage_root)
    keys = {(row['candidate'], row['opponent'], row['seed'], row['candidate_seat']) for row in rows}
    assert set(result) == keys
    for row in rows:
        profiles = result[(row['candidate'], row['opponent'], row['seed'], row['candidate_seat'])]
        assert [profile['actor'] for profile in profiles] == [0, 1]
    # Beta won from seat 0 in game one and seat 1 in game two: identity aggregation
    # selects result[key][candidate_seat] both times, physical P0 pooling does not.
    identity = bmetrics.profile_summary([result[key][row['candidate_seat']]
                                        for row, key in zip(rows, sorted(keys))])
    assert identity['games'] == 2
    assert identity['mean_building_utility'] == pytest.approx(1 / 24)
    pooled_p0 = bmetrics.profile_summary([result[key][0] for key in sorted(keys)])
    assert pooled_p0['mean_building_utility'] == pytest.approx((1 / 24 + 0.) / 2)
    assert pooled_p0['mean_building_utility'] != identity['mean_building_utility']
    document = bmetrics.read(stage_root / 'building-metrics.json')
    assert document['format'] == 'm62-building-replay-metrics-v1'
    assert document['status'] == 'VERIFIED_OFFLINE_VISIBLE_BUILDING_PROFILES'
    assert document['all_players'] is True and document['new_games'] == 0
    assert document['style_contract'] == CONFIG
    assert document['style_contract_sha256'] == canonical_hash(CONFIG)
    assert document['fixed_state_panel']['status'] == 'NOT_RUN'
    assert len(document['games']) == 2
    for entry, row in zip(document['games'], rows):
        assert entry['replay_sha256'] == bmetrics.sha(row['_replay_path'])
        assert len(entry['profiles']) == 2
    receipts = document['projection_receipts']
    assert receipts[0]['returncode'] == 0
    assert 'zero games' in receipts[0]['clock_scope']
    assert 'discarded after profile extraction' in receipts[0]['projection_retention']


def test_collect_fail_closed_on_missing_replay_native_failure_and_drift(tmp_path):
    execution = execution_with_projection(tmp_path)
    missing = match_row('beta', 'alpha-t1', 1, 0, tmp_path / 'missing' / 'replay.json')
    with pytest.raises(ValueError, match='without retry'):
        run_collect([missing], execution, tmp_path / 'stage-missing')
    assert not (tmp_path / 'stage-missing' / 'building-metrics.json').exists()
    replay_path = tmp_path / 'replay.json'
    synthetic_replay(replay_path, 1, dict(scores=[15, 14], ranks=[0, 1], winners=[0], reason='prestige_threshold'))
    def failing_tool(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout='', stderr='boom')
    with pytest.raises(ValueError, match='without retry'):
        run_collect([match_row('beta', 'alpha-t1', 1, 0, replay_path)], execution,
                    tmp_path / 'stage-native-fail', tool=failing_tool)
    with pytest.raises(ValueError, match='duplicate projection replay path'):
        run_collect([match_row('beta', 'alpha-t1', 1, 0, replay_path),
                     match_row('beta', 'alpha-t1', 2, 0, replay_path)], execution,
                    tmp_path / 'stage-duplicate')
    with pytest.raises(ValueError, match='execution-pinned'):
        run_collect([match_row('beta', 'alpha-t1', 1, 0, replay_path)],
                    execution_with_projection(tmp_path, pin=False), tmp_path / 'stage-unpinned')
    stage_root = tmp_path / 'stage-partial'
    stage_root.mkdir()
    (stage_root / 'building-projection-0.json').write_bytes(b'leftover partial batch')
    with pytest.raises(ValueError, match='duplicate/partial building metrics batch'):
        run_collect([match_row('beta', 'alpha-t1', 1, 0, replay_path)], execution, stage_root)


def test_profile_summary_means_and_totals_come_from_the_profile_counts():
    profiles = [dict.fromkeys(
        ('building_utility', 'early_bonus_auc12', 'building_use_units',
         'building_use_units_before_global_cap', 'building_observed_use_units', 'early_buys',
         'early_lowvp_buys', 'redeemed_investments', 'unredeemed_investments',
         'censored_investments', 'unredeemed_censored_investments',
         'late_vp_bought_main13to24', 'late_scoring_vp_main25to32', 'observed_main13to24',
         'observed_main25to32'), 1.) | dict(shorter_than_early_window=False,
                                            redemption_horizon_censored=False,
                                            late_scoring_main25to32_censored=False)
        for _ in range(3)]
    summary = bmetrics.profile_summary(profiles)
    assert summary['games'] == 3
    assert summary['mean_building_utility'] == 1. and summary['mean_early_bonus_auc12'] == 1.
    assert summary['total_early_lowvp_buys'] == 3 and summary['total_redeemed_investments'] == 3
    assert summary['investment_redemption_rate'] == 1.
    assert summary['late_scoring_vp_per_observed_main25to32'] == 1.
    assert summary['short_game_fraction'] == 0.
    assert summary['early_bonus_auc12_unit'] == 'permanent-discounts'
    assert summary['early_bonus_auc12_padding'] == 'held-at-terminal-descriptive-only'
    assert summary['utility_padding'] == 'none; real subsequent purchases only'


def test_profile_summary_rates_use_summed_counts_never_averaged_ratios(tmp_path):
    from pathlib import Path as _Path
    config = CONFIG
    def real_profile(events, actor):
        return profile_from_own_decisions(own_decisions(actor, events), actor, config)
    redeeming = real_profile(ACTOR0_EVENTS, 0)          # 1 investment, redeemed
    multi = real_profile(ACTOR1B_EVENTS, 1)             # 3 investments, only blue redeemed
    assert redeeming['early_lowvp_buys'] == 1 and redeeming['redeemed_investments'] == 1
    assert multi['early_lowvp_buys'] == 3 and multi['redeemed_investments'] == 1
    summary = bmetrics.profile_summary([redeeming, multi])
    # Summed: (1 + 1) / (1 + 3) = .5; averaged per-profile ratios would give 2/3.
    assert summary['total_early_lowvp_buys'] == 4
    assert summary['total_redeemed_investments'] == 2
    assert summary['investment_redemption_rate'] == pytest.approx(.5)
    assert summary['investment_redemption_rate'] != pytest.approx((1. + 1. / 3.) / 2)
    assert summary['investment_unredeemed_rate'] == pytest.approx(.5)
    assert summary['mean_building_utility'] == pytest.approx((1 / 24 + 1 / 24) / 2)
    # redeeming profile auc = 1.0; multi profile auc = (1+2+3+3*9)/12 = 2.75.
    assert summary['mean_early_bonus_auc12'] == pytest.approx((1. + 2.75) / 2)


def test_profile_summary_handles_censored_and_empty_denominators():
    short = dict.fromkeys(
        ('building_utility', 'early_bonus_auc12', 'building_use_units',
         'building_use_units_before_global_cap', 'building_observed_use_units', 'early_buys',
         'early_lowvp_buys', 'redeemed_investments', 'unredeemed_investments',
         'censored_investments', 'unredeemed_censored_investments',
         'late_vp_bought_main13to24', 'late_scoring_vp_main25to32', 'observed_main13to24',
         'observed_main25to32'), 0.) | dict(shorter_than_early_window=True,
                                            redemption_horizon_censored=True,
                                            late_scoring_main25to32_censored=True)
    summary = bmetrics.profile_summary([short])
    assert summary['investment_redemption_rate'] is None
    assert summary['investment_unredeemed_rate'] is None
    assert summary['investment_censored_rate'] is None
    assert summary['late_scoring_vp_per_observed_main25to32'] is None
    assert summary['short_game_fraction'] == 1.
    assert summary['redemption_horizon_censored_fraction'] == 1.
    assert summary['late_scoring_main25to32_censored_fraction'] == 1.
    with pytest.raises(ValueError, match='empty building profile aggregation'):
        bmetrics.profile_summary([])


def native_seat_metrics(rows, side):
    """Simulated s4_batch_metrics output for one physical seat and side.

    side 'candidate'/'opponent' follows model identity; side 'physical0' pools
    whatever sat at physical seat 0 — the orientation the M62 contract forbids.
    """
    n = len(rows)
    def keys_for(row):
        candidate = (side == 'candidate') or (side == 'physical0' and row['candidate_seat'] == 0)
        return ('_candidate_actions' if candidate else '_opponent_actions',
                'candidate_points' if candidate else 'opponent_points',
                '_candidate_cards' if candidate else '_opponent_cards',
                '_candidate_nobles' if candidate else '_opponent_nobles',
                '_candidate_colors' if candidate else '_opponent_colors',
                '_candidate_reserves' if candidate else '_opponent_reserves')
    actions, cards, colors = Counter(), Counter(), Counter()
    points = nobles = acquired = bought = noble_games = 0
    for row in rows:
        action_key, point_key, card_key, noble_key, color_key, reserve_key = keys_for(row)
        actions.update(row[action_key])
        cards.update(row[card_key])
        colors.update({index: count for index, count in enumerate(row[color_key])})
        points += row[point_key]
        nobles += row[noble_key]
        noble_games += row[noble_key] > 0
        acquired += row[reserve_key][0]
        bought += row[reserve_key][1]
    if side == 'candidate':
        wins = sum(row['record'] == 'win' for row in rows)
    elif side == 'opponent':
        wins = sum(row['record'] == 'loss' for row in rows)
    else:  # physical0 pools whatever happened to sit at physical seat 0
        wins = sum((row['record'] == 'win') == (row['candidate_seat'] == 0) for row in rows)
    ties = sum(row['record'] == 'draw' for row in rows)
    buys = actions['buy_market'] + actions['buy_reserved']
    return dict(wins=wins, ties=ties, losses=n - wins - ties, games_with_nobles=noble_games,
                mean_prestige=points / n, mean_nobles=nobles / n, mean_permanent_bonuses=buys / n,
                mean_reserves_acquired=acquired / n, mean_reserves_bought=bought / n,
                mean_reserves_stranded=(acquired - bought) / n,
                mean_cards_by_vp={str(vp): cards[str(vp)] / n for vp in range(6)},
                mean_bonuses_by_color={color: colors[index] / n
                                       for index, color in enumerate(COLORS)},
                action_distribution={action: actions[action] for action in details.ACTIONS})


def metric_row(candidate, opponent, seed, seat, *, win, cand_actions, cand_cards, cand_colors,
               cand_nobles, opp_actions, opp_cards, opp_colors, opp_nobles, plies):
    cand_actions, opp_actions = Counter(cand_actions), Counter(opp_actions)
    cand_points = sum(int(vp) * count for vp, count in cand_cards.items()) + 3 * cand_nobles
    opp_points = sum(int(vp) * count for vp, count in opp_cards.items()) + 3 * opp_nobles
    assert sum(cand_cards.values()) == cand_actions['buy_market'] + cand_actions['buy_reserved']
    assert sum(opp_cards.values()) == opp_actions['buy_market'] + opp_actions['buy_reserved']
    assert sum(cand_colors) == sum(cand_cards.values())
    assert sum(opp_colors) == sum(opp_cards.values())
    winner = seat if win else 1 - seat
    return dict(candidate=candidate, opponent=opponent, seed=seed, candidate_seat=seat,
                candidate_score=1. if win else 0., record='win' if win else 'loss',
                candidate_points=cand_points, opponent_points=opp_points,
                scores=[cand_points, opp_points] if seat == 0 else [opp_points, cand_points],
                ranks=[0, 1] if winner == 0 else [1, 0], winners=[winner],
                plies=plies, _wall_seconds=1.5,
                _candidate_actions=cand_actions, _opponent_actions=opp_actions,
                _candidate_cards=Counter(cand_cards), _opponent_cards=Counter(opp_cards),
                _candidate_nobles=cand_nobles, _opponent_nobles=opp_nobles,
                _candidate_colors=cand_colors, _opponent_colors=opp_colors,
                _candidate_reserves=(cand_actions['reserve_market'] + cand_actions['reserve_deck'],
                                     cand_actions['buy_reserved']),
                _opponent_reserves=(opp_actions['reserve_market'] + opp_actions['reserve_deck'],
                                    opp_actions['buy_reserved']))


def exchanged_seat_fixture():
    """beta vs alpha-t1: 3 games with beta at P0, 1 game with beta at P1; beta wins all."""
    seat0 = [metric_row('beta', 'alpha-t1', 9641000 + i, 0, win=True,
                        cand_actions=dict(buy_market=2, buy_reserved=1, take_tokens=5,
                                          reserve_market=2, choose_noble=1),
                        cand_cards={'1': 2, '2': 1}, cand_colors=[1, 0, 1, 1, 0], cand_nobles=1,
                        opp_actions=dict(buy_market=1, take_tokens=6, reserve_deck=1),
                        opp_cards={'1': 1}, opp_colors=[0, 1, 0, 0, 0], opp_nobles=0,
                        plies=40 + i)
             for i in range(3)]
    seat1 = [metric_row('beta', 'alpha-t1', 9641003, 1, win=True,
                        cand_actions=dict(buy_market=1, take_tokens=7),
                        cand_cards={'1': 1}, cand_colors=[0, 1, 0, 0, 0], cand_nobles=0,
                        opp_actions=dict(buy_market=2, take_tokens=6),
                        opp_cards={'1': 2}, opp_colors=[1, 1, 0, 0, 0], opp_nobles=1,
                        plies=44)]
    return seat0, seat1


def test_merge_player_aggregates_by_model_identity_across_exchanged_seats():
    seat0, seat1 = exchanged_seat_fixture()
    metrics0 = dict(seat_p0_first=native_seat_metrics(seat0, 'candidate'),
                    seat_p1_second=native_seat_metrics(seat0, 'opponent'))
    metrics1 = dict(seat_p0_first=native_seat_metrics(seat1, 'opponent'),
                    seat_p1_second=native_seat_metrics(seat1, 'candidate'))
    rows = seat0 + seat1
    candidate_batches = [(metrics0['seat_p0_first'], len(seat0)),
                         (metrics1['seat_p1_second'], len(seat1))]
    opponent_batches = [(metrics0['seat_p1_second'], len(seat0)),
                        (metrics1['seat_p0_first'], len(seat1))]
    candidate = details.merge_player(candidate_batches, rows, True)
    opponent = details.merge_player(opponent_batches, rows, False)
    assert candidate['games'] == opponent['games'] == 4
    assert candidate['wins'] == 4 and opponent['losses'] == 4
    assert (candidate['ties'], candidate['losses']) == (opponent['ties'], opponent['wins']) == (0, 0)
    # Naive physical-seat pooling (P0 == candidate) over the same rows credits only
    # the three seat-0 wins, and the frozen helper refuses to merge such a batch
    # with candidate-side rows at all: orientation errors fail closed.
    pooled = native_seat_metrics(rows, 'physical0')
    assert pooled['wins'] == 3 and pooled['wins'] != candidate['wins']
    assert pooled['mean_permanent_bonuses'] != candidate['mean_permanent_bonuses']
    with pytest.raises(ValueError, match='action counts mismatch'):
        details.merge_player([(pooled, 4)], rows, True)
    # Seat records keep both physical seats with their own identity-side metrics.
    seats = [dict(candidate_seat=0, candidate=details.merge_player(
                      [(metrics0['seat_p0_first'], len(seat0))], seat0, True),
                  opponent=details.merge_player([(metrics0['seat_p1_second'], len(seat0))],
                                                seat0, False)),
             dict(candidate_seat=1, candidate=details.merge_player(
                      [(metrics1['seat_p1_second'], len(seat1))], seat1, True),
                  opponent=details.merge_player([(metrics1['seat_p0_first'], len(seat1))],
                                                seat1, False))]
    assert sum(seat['candidate']['games'] for seat in seats) == 4
    assert seats[0]['candidate']['wins'] == 3 and seats[1]['candidate']['wins'] == 1


def test_merge_player_fields_cover_final_vp_scoring_reserves_and_actions():
    seat0, seat1 = exchanged_seat_fixture()
    rows = seat0 + seat1
    batches = [(native_seat_metrics(seat0, 'candidate'), len(seat0)),
               (native_seat_metrics(seat1, 'candidate'), len(seat1))]
    candidate = details.merge_player(batches, rows, True)
    opponent = details.merge_player(
        [(native_seat_metrics(seat0, 'opponent'), len(seat0)),
         (native_seat_metrics(seat1, 'opponent'), len(seat1))], rows, False)
    for side in (candidate, opponent):
        for field in ('mean_prestige', 'score_rate', 'win_rate_percent', 'mean_reserves_acquired',
                      'mean_reserves_bought', 'mean_reserves_stranded',
                      'reserve_redemption_rate_percent', 'action_distribution',
                      'action_percentages', 'total_actor_decisions', 'total_main_actions',
                      'vp_per_main_action', 'mean_cards_by_vp', 'mean_bonuses_by_color',
                      'mean_nobles', 'mean_permanent_bonuses', 'games_with_nobles_percent',
                      'vp_per_turn', 'vp_per_ply'):
            assert field in side
        assert set(side['action_distribution']) == set(details.ACTIONS)
        assert set(side['action_percentages']) == set(details.ACTIONS)
        assert set(side['mean_cards_by_vp']) == {str(vp) for vp in range(6)}
        assert set(side['mean_bonuses_by_color']) == set(details.COLORS)
    assert candidate['total_actor_decisions'] == sum(candidate['action_distribution'].values())
    assert candidate['total_main_actions'] == candidate['total_actor_decisions'] - \
        candidate['action_distribution']['choose_noble']
    assert candidate['reserve_redemption_rate_percent'] is not None
    # The opponent reserved three cards but never bought one back: 0%, all stranded.
    assert opponent['reserve_redemption_rate_percent'] == 0.0
    assert opponent['mean_reserves_bought'] == 0.
    assert opponent['mean_reserves_stranded'] == opponent['mean_reserves_acquired'] > 0.


def test_merge_player_weights_means_by_summed_counts_not_average_of_ratios():
    seat0, seat1 = exchanged_seat_fixture()
    rows = seat0 + seat1
    candidate = details.merge_player([(native_seat_metrics(seat0, 'candidate'), 3),
                                      (native_seat_metrics(seat1, 'candidate'), 1)], rows, True)
    # Summed buys: 3 games x 3 buys + 1 game x 1 buy = 10 over 4 games = 2.5.
    # Unweighted average of the two per-seat ratios would be (3 + 1) / 2 = 2.
    assert candidate['mean_permanent_bonuses'] == pytest.approx(2.5)
    assert candidate['mean_permanent_bonuses'] != pytest.approx(2.)
    assert candidate['mean_prestige'] == pytest.approx(
        sum(row['candidate_points'] for row in rows) / 4)
    assert candidate['vp_per_main_action'] == pytest.approx(
        sum(row['candidate_points'] for row in rows) / candidate['total_main_actions'])
