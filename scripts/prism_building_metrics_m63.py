"""Offline M63 building profiles from SHA-pinned Rust own-view projections.

The exporter verifies/replays saved matches. Only actor-visible Observation and
chosen_action rows reach the building extractor; no FullState or hidden deck data.
Projection batches are bounded and deleted only after their hash and profiles are
persisted, keeping the formal evaluator inside its frozen storage budget.
"""
from collections import Counter
import math
from pathlib import Path
import subprocess
import time

from scripts import prism_balance_ab_evaluation_m61 as frozen
from scripts import prism_match_details as details
from training.prism_portable.engine.ppo import building, building_timed

read, write, sha, require = frozen.read, frozen.write, frozen.sha, frozen.require
FORMAT = 'prism-building-projection-v1'
PUBLIC_KEYS = {'player_count', 'current_player', 'phase', 'bank', 'market', 'deck_counts', 'nobles',
               'players', 'end_game_triggered', 'turns_remaining_in_final_round',
               'consecutive_forced_passes', 'pending_nobles'}
PLAYER_KEYS = {'id', 'tokens', 'bonuses', 'prestige', 'reserved_count', 'public_reserved', 'purchased', 'nobles'}
MEANS = ('building_utility', 'timed_building_utility', 'early_bonus_auc12', 'building_use_units', 'building_use_units_before_global_cap',
         'building_observed_use_units', 'timed_building_use_units', 'early_buys', 'early_lowvp_buys', 'redeemed_investments',
         'unredeemed_investments', 'censored_investments', 'unredeemed_censored_investments',
         'late_vp_bought_main13to24', 'late_scoring_vp_main25to32', 'observed_main13to24', 'observed_main25to32')


def visible_observation(observation, actor):
    require(set(observation) == {'viewer', 'ruleset_fingerprint', 'public', 'private'}, 'unexpected hidden projection field')
    require(type(observation['viewer']) is int and observation['viewer'] == actor, 'projection viewer mismatch')
    public, private = observation['public'], observation['private']
    require(set(public) == PUBLIC_KEYS and set(private) == {'reserved'}, 'projection observation boundary drift')
    require(public['player_count'] == 2 and public['current_player'] == actor and
            len(public['players']) == 2, 'projection public actor/count drift')
    for seat, player in enumerate(public['players']):
        require(set(player) == PLAYER_KEYS and player['id'] == seat, 'hidden/private public player field')
    for reserve in private['reserved']:
        require(set(reserve) == {'slot', 'card', 'tier', 'from_deck'}, 'own reserve projection field drift')
    return observation


def profiles_from_projection(row, projected, replay, config):
    require(Path(projected['replay_path']).resolve() == Path(row['_replay_path']).resolve(), 'projection replay path drift')
    require(projected['replay_sha256'] == sha(row['_replay_path']), 'projection replay SHA drift')
    require(projected['seed'] == row['seed'] == replay['seed'] and projected['terminal'] is True and
            projected['catalog_fingerprint'] == replay['ruleset_fingerprint'] == building.BASE_CATALOG_FINGERPRINT,
            'projection seed/catalog/terminal drift')
    require(projected['result'] == replay['result'] and replay['result']['scores'] == row['scores'] and
            replay['result']['ranks'] == row['ranks'] and replay['result']['winners'] == row['winners'], 'projection terminal result drift')
    players = projected['players']
    require(len(players) == 2 and [p['actor'] for p in players] == [0, 1], 'projection must cover both physical actors')
    profiles = []
    for actor, player in enumerate(players):
        steps = [step for step in replay['steps'] if step['actor'] == actor]
        decisions = player['decisions']
        require(len(steps) == len(decisions) and bool(decisions), 'projection omitted own decisions')
        for step, decision in zip(steps, decisions):
            require(set(decision) == {'ply', 'observation', 'chosen_action'} and decision['ply'] == step['ply'] and
                    decision['chosen_action'] == step['action'], 'projection own ply/action coverage drift')
            visible_observation(decision['observation'], actor)
        # No full replay is passed across this call boundary.
        timed_profile = building_timed.profile_from_own_decisions(decisions, actor, config, terminal=True)
        # Retain the exact original v1 profile and append M63 timing fields.
        profile = timed_profile['building_v1_profile']
        profile['timed_building_use_units'] = timed_profile['time_weighted_use_units']
        profile['timed_building_use_units_before_global_cap'] = timed_profile['time_weighted_use_units_before_global_cap']
        profile['timed_building_utility'] = timed_profile['time_weighted_utility']
        counts = Counter(step['action']['type'] for step in steps)
        require(set(counts) <= set(details.ACTIONS), 'unknown action in own projection')
        require(profile['decision_actions'] == sum(counts.values()) and
                profile['main_actions'] == sum(counts.values()) - counts['choose_noble'], 'building Main/action conservation')
        profile['actor'] = actor
        profiles.append(profile)
    return profiles


def profile_summary(profiles):
    require(bool(profiles), 'empty building profile aggregation')
    n = len(profiles)
    out = dict(games=n, early_bonus_auc12_unit='permanent-discounts',
        early_bonus_auc12_padding='held-at-terminal-descriptive-only',
        utility_padding='none; real subsequent purchases only',
        short_game_fraction=sum(p['shorter_than_early_window'] for p in profiles) / n,
        redemption_horizon_censored_fraction=sum(p['redemption_horizon_censored'] for p in profiles) / n,
        late_scoring_main25to32_censored_fraction=sum(p['late_scoring_main25to32_censored'] for p in profiles) / n)
    for field in MEANS: out['mean_' + field] = math.fsum(p[field] for p in profiles) / n
    for field in ('early_lowvp_buys', 'redeemed_investments', 'unredeemed_investments', 'censored_investments',
                  'unredeemed_censored_investments', 'late_scoring_vp_main25to32', 'observed_main25to32'):
        out['total_' + field] = sum(p[field] for p in profiles)
    denominator = out['total_early_lowvp_buys']
    out['investment_redemption_rate'] = out['total_redeemed_investments'] / denominator if denominator else None
    out['investment_unredeemed_rate'] = out['total_unredeemed_investments'] / denominator if denominator else None
    out['investment_censored_rate'] = out['total_censored_investments'] / denominator if denominator else None
    observed = out['total_observed_main25to32']
    out['late_scoring_vp_per_observed_main25to32'] = out['total_late_scoring_vp_main25to32'] / observed if observed else None
    return out


def collect(rows, stage_root, execution):
    stage_root = Path(stage_root)
    binary = execution['binaries']['projection']; config = execution['building_style']
    building.validate_building_config(config)
    require(sha(binary['path']) == binary['sha256'] and execution['files'].get(binary['path']) == binary['sha256'],
            'projection native not execution-pinned')
    require(len({Path(r['_replay_path']).resolve() for r in rows}) == len(rows), 'duplicate projection replay path')
    result, games, receipts = {}, [], []
    for index, first in enumerate(range(0, len(rows), 16)):
        batch = rows[first:first + 16]
        manifest = stage_root / f'building-projection-{index}.manifest.json'
        output = stage_root / f'building-projection-{index}.json'
        require(not output.exists() and not manifest.exists(), 'refuse duplicate/partial building metrics batch')
        write(manifest, {'rows': [{'replay_path': r['_replay_path']} for r in batch]})
        argv = [binary['path'], str(manifest), str(output)]
        start = time.monotonic()
        process = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
        receipt = dict(argv=argv, returncode=process.returncode, elapsed_wall_seconds=time.monotonic() - start,
                       clock_scope='saved replay verification and own-view projection; zero games',
                       manifest_path=str(manifest), manifest_sha256=sha(manifest), native_sha256=binary['sha256'],
                       stderr=process.stderr, stdout=process.stdout)
        receipt_path = stage_root / f'building-projection-{index}.receipt.json'; write(receipt_path, receipt)
        require(process.returncode == 0, 'native own-view projection failed without retry')
        projected = read(output)
        require(projected['format'] == FORMAT and len(projected['games']) == len(batch), 'projection format/game coverage drift')
        receipt['projection_sha256'] = sha(output)
        for row, game in zip(batch, projected['games']):
            profiles = profiles_from_projection(row, game, read(row['_replay_path']), config)
            key = (row['candidate'], row['opponent'], row['seed'], row['candidate_seat'])
            require(key not in result, 'duplicate building metric match'); result[key] = profiles
            games.append(dict(candidate=row['candidate'], opponent=row['opponent'], seed=row['seed'],
                candidate_seat=row['candidate_seat'], replay_path=row['_replay_path'],
                replay_sha256=game['replay_sha256'], profiles=profiles, projection_sha256=receipt['projection_sha256']))
        # The reusable evidence is the immutable saved replay plus pinned native
        # exporter/source. Keep all profile/raw projection digests and actual argv.
        receipt['projection_retention'] = 'discarded after profile extraction; reproducible from pinned saved replay/native'
        write(receipt_path, receipt)
        receipts.append(dict(path=str(receipt_path), sha256=sha(receipt_path), **receipt))
        output.unlink()
    write(stage_root / 'building-metrics.json', dict(format='m63-building-replay-metrics-v1',
        status='VERIFIED_OFFLINE_VISIBLE_BUILDING_PROFILES', new_games=0, all_players=True,
        style_contract=config, style_contract_sha256=frozen.fixed.canonical_hash(config),
        projection_native=binary, projection_receipts=receipts, games=games,
        fixed_state_panel=dict(status='NOT_RUN', verdict='DIAGNOSTIC_ONLY; no added frozen gate')))
    return result
