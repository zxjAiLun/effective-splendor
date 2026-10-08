"""Building style from complete own decisions and the immutable public catalog.

A use means a later real purchase has printed cost[colour] >= the investment's
bonus ordinal. It is a descriptive discount application, not a counterfactual
claim about tokens saved or whether that purchase would otherwise be possible.
Only early <=1 printed-VP purchases are reward investments. No terminal reward
padding is allowed. The separate bonus AUC is in raw permanent discounts and
holds terminal bonuses for short games, solely for descriptive comparison.
"""
import math

from ..io import canonical_hash
from .contract import exact, integer

COLORS = ('white', 'blue', 'green', 'red', 'black')
TIERS = ('One', 'Two', 'Three')
BASE_CATALOG_FINGERPRINT = '1c43f598b23017fab5e9d8b0083942ad1a921d1df804f90d16cd0b4753961afb'

# Dense CardId -> (tier, bonus colour index, printed VP, printed [W,B,G,R,K]
# cost). Public data copied from splendor-catalog/src/cards.rs, not deck order.
# A source parity test binds all 90 definitions and the canonical colour order.
CARD_CATALOG = (
    ('One', 1, 0, (0, 0, 0, 0, 3)),
    ('One', 1, 0, (1, 0, 0, 0, 2)),
    ('One', 1, 0, (0, 0, 2, 0, 2)),
    ('One', 1, 0, (1, 0, 2, 2, 0)),
    ('One', 1, 0, (0, 1, 3, 1, 0)),
    ('One', 1, 0, (1, 0, 1, 1, 1)),
    ('One', 1, 0, (1, 0, 1, 2, 1)),
    ('One', 1, 1, (0, 0, 0, 4, 0)),
    ('One', 3, 0, (3, 0, 0, 0, 0)),
    ('One', 3, 0, (0, 2, 1, 0, 0)),
    ('One', 3, 0, (2, 0, 0, 2, 0)),
    ('One', 3, 0, (2, 0, 1, 0, 2)),
    ('One', 3, 0, (1, 0, 0, 1, 3)),
    ('One', 3, 0, (1, 1, 1, 0, 1)),
    ('One', 3, 0, (2, 1, 1, 0, 1)),
    ('One', 3, 1, (4, 0, 0, 0, 0)),
    ('One', 4, 0, (0, 0, 3, 0, 0)),
    ('One', 4, 0, (0, 0, 2, 1, 0)),
    ('One', 4, 0, (2, 0, 2, 0, 0)),
    ('One', 4, 0, (2, 2, 0, 1, 0)),
    ('One', 4, 0, (0, 0, 1, 3, 1)),
    ('One', 4, 0, (1, 1, 1, 1, 0)),
    ('One', 4, 0, (1, 2, 1, 1, 0)),
    ('One', 4, 1, (0, 4, 0, 0, 0)),
    ('One', 0, 0, (0, 3, 0, 0, 0)),
    ('One', 0, 0, (0, 0, 0, 2, 1)),
    ('One', 0, 0, (0, 2, 0, 0, 2)),
    ('One', 0, 0, (0, 2, 2, 0, 1)),
    ('One', 0, 0, (3, 1, 0, 0, 1)),
    ('One', 0, 0, (0, 1, 1, 1, 1)),
    ('One', 0, 0, (0, 1, 2, 1, 1)),
    ('One', 0, 1, (0, 0, 4, 0, 0)),
    ('One', 2, 0, (0, 0, 0, 3, 0)),
    ('One', 2, 0, (2, 1, 0, 0, 0)),
    ('One', 2, 0, (0, 2, 0, 2, 0)),
    ('One', 2, 0, (0, 1, 0, 2, 2)),
    ('One', 2, 0, (1, 3, 1, 0, 0)),
    ('One', 2, 0, (1, 1, 0, 1, 1)),
    ('One', 2, 0, (1, 1, 0, 1, 2)),
    ('One', 2, 1, (0, 0, 0, 0, 4)),
    ('Two', 1, 1, (0, 2, 2, 3, 0)),
    ('Two', 1, 1, (0, 2, 3, 0, 3)),
    ('Two', 1, 2, (0, 5, 0, 0, 0)),
    ('Two', 1, 2, (5, 3, 0, 0, 0)),
    ('Two', 1, 2, (2, 0, 0, 1, 4)),
    ('Two', 1, 3, (0, 6, 0, 0, 0)),
    ('Two', 3, 1, (2, 0, 0, 2, 3)),
    ('Two', 3, 1, (0, 3, 0, 2, 3)),
    ('Two', 3, 2, (0, 0, 0, 0, 5)),
    ('Two', 3, 2, (3, 0, 0, 0, 5)),
    ('Two', 3, 2, (1, 4, 2, 0, 0)),
    ('Two', 3, 3, (0, 0, 0, 6, 0)),
    ('Two', 4, 1, (3, 2, 2, 0, 0)),
    ('Two', 4, 1, (3, 0, 3, 0, 2)),
    ('Two', 4, 2, (5, 0, 0, 0, 0)),
    ('Two', 4, 2, (0, 0, 5, 3, 0)),
    ('Two', 4, 2, (0, 1, 4, 2, 0)),
    ('Two', 4, 3, (0, 0, 0, 0, 6)),
    ('Two', 0, 1, (0, 0, 3, 2, 2)),
    ('Two', 0, 1, (2, 3, 0, 3, 0)),
    ('Two', 0, 2, (0, 0, 0, 5, 0)),
    ('Two', 0, 2, (0, 0, 0, 5, 3)),
    ('Two', 0, 2, (0, 0, 1, 4, 2)),
    ('Two', 0, 3, (6, 0, 0, 0, 0)),
    ('Two', 2, 1, (2, 3, 0, 0, 2)),
    ('Two', 2, 1, (3, 0, 2, 3, 0)),
    ('Two', 2, 2, (0, 0, 5, 0, 0)),
    ('Two', 2, 2, (0, 5, 3, 0, 0)),
    ('Two', 2, 2, (4, 2, 0, 0, 1)),
    ('Two', 2, 3, (0, 0, 6, 0, 0)),
    ('Three', 1, 3, (3, 0, 3, 3, 5)),
    ('Three', 1, 4, (7, 0, 0, 0, 0)),
    ('Three', 1, 4, (6, 3, 0, 0, 3)),
    ('Three', 1, 5, (7, 3, 0, 0, 0)),
    ('Three', 3, 3, (3, 5, 3, 0, 3)),
    ('Three', 3, 4, (0, 0, 7, 0, 0)),
    ('Three', 3, 4, (0, 3, 6, 3, 0)),
    ('Three', 3, 5, (0, 0, 7, 3, 0)),
    ('Three', 4, 3, (3, 3, 5, 3, 0)),
    ('Three', 4, 4, (0, 0, 0, 7, 0)),
    ('Three', 4, 4, (0, 0, 3, 6, 3)),
    ('Three', 4, 5, (0, 0, 0, 7, 3)),
    ('Three', 0, 3, (0, 3, 3, 5, 3)),
    ('Three', 0, 4, (0, 0, 0, 0, 7)),
    ('Three', 0, 4, (3, 0, 0, 3, 6)),
    ('Three', 0, 5, (3, 0, 0, 0, 7)),
    ('Three', 2, 3, (5, 3, 0, 3, 3)),
    ('Three', 2, 4, (0, 7, 0, 0, 0)),
    ('Three', 2, 4, (3, 6, 3, 0, 0)),
    ('Three', 2, 5, (0, 7, 3, 0, 0)),
)


def default_building_config():
    """The exact v1 contract; modifying fixed values requires a new format."""
    return {'format': 'prism-building-style-v1', 'early_window_main_actions': 12,
            'redemption_horizon_main_actions': 24, 'early_max_printed_vp': 1,
            'per_investment_use_cap': 3, 'global_use_cap': 24,
            'short_game_padding': 'none',
            'phase_semantics': 'choose_noble-belongs-to-preceding-main',
            'terminal_only': True,
            'style_reward_input': 'player-visible-own-purchases-and-prepurchase-bonuses',
            'diagnostic_early_bonus_padding': 'held-at-terminal'}


def validate_building_config(value):
    expected = default_building_config()
    exact(value, expected, 'building style contract')
    if any(type(value[k]) is not type(v) or value[k] != v for k, v in expected.items()):
        raise ValueError('unsupported building utility semantics')
    return value


def _card(card_id):
    return CARD_CATALOG[integer(card_id, 0, 89, 'visible public catalog card ID')]


def _own_state(obs, actor):
    if type(obs['viewer']) is not int or obs['viewer'] != actor:
        raise ValueError('building projection viewer mismatch')
    if obs['ruleset_fingerprint'] != BASE_CATALOG_FINGERPRINT:
        raise ValueError('building requires the frozen public base catalog')
    public = obs['public']
    if type(public['current_player']) is not int or public['current_player'] != actor:
        raise ValueError('building projected actor mismatch')
    players = public['players']
    if not isinstance(players, list) or len(players) != 2:
        raise ValueError('building requires two public player slots')
    own = players[actor]
    if type(own['id']) is not int or own['id'] != actor:
        raise ValueError('building public player index mismatch')
    bonuses = own['bonuses']
    if not isinstance(bonuses, list) or len(bonuses) != 5:
        raise ValueError('building bonuses require [white,blue,green,red,black]')
    for bonus in bonuses:
        integer(bonus, 0, 90, 'own pre-purchase bonus')
    purchased = own['purchased']
    if not isinstance(purchased, list):
        raise ValueError('own visible purchase history required')
    counts = [0] * 5
    for card_id in purchased:
        counts[_card(card_id)[1]] += 1
    if len(set(purchased)) != len(purchased) or counts != bonuses:
        raise ValueError('own purchase history / bonus colour counts inconsistent')
    return public, bonuses, set(purchased)


def _purchase_target(obs, action):
    if action['type'] == 'buy_market':
        exact(action, {'type', 'tier', 'slot'}, 'buy_market target')
        tier = action['tier']
        if not isinstance(tier, str) or tier not in TIERS:
            raise ValueError('invalid visible market tier')
        slot = integer(action['slot'], 0, 3, 'visible market slot')
        market = obs['public']['market']
        if not isinstance(market, list) or len(market) != 3:
            raise ValueError('visible market target missing')
        row = market[TIERS.index(tier)]
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError('visible market target missing')
        card_id = row[slot]
    else:
        exact(action, {'type', 'slot'}, 'buy_reserved target')
        slot = integer(action['slot'], 0, 2, 'own reserved slot')
        reserved = obs['private']['reserved']
        if not isinstance(reserved, list):
            raise ValueError('own visible reserved target missing')
        matches = []
        for entry in reserved:
            entry_slot = integer(entry['slot'], 0, 2, 'own visible reserved slot')
            if entry_slot == slot:
                matches.append(entry)
        if len(matches) != 1:
            raise ValueError('own visible reserved target missing/duplicate')
        card_id, tier = matches[0]['card'], matches[0]['tier']
    card = _card(card_id)
    if card[0] != tier:
        raise ValueError('visible purchase target / catalog tier mismatch')
    return card_id, card


def profile_from_own_decisions(decisions, actor, config, *, terminal=True):
    """Evaluate one player's full visible sequence, for either physical seat.

    Rows need only observation/chosen_action. A replay adapter must project each
    actor's decisions first; this function never accepts a full/private replay.
    The pinned Rust ingestion remains responsible for legality and real terminal
    evidence. Python additionally checks complete own ownership/bonus continuity.
    """
    validate_building_config(config)
    integer(actor, 0, 1, 'building actor')
    if terminal is not True:
        raise ValueError('building utility requires a real terminal, never a prefix')
    if not isinstance(decisions, list) or not decisions:
        raise ValueError('complete nonempty own decision sequence required')
    k, horizon = config['early_window_main_actions'], config['redemption_horizon_main_actions']
    use_cap, global_cap = config['per_investment_use_cap'], config['global_use_cap']
    expected_owned, expected_bonuses = set(), [0] * 5
    after_main, investments = [], []
    early_buys = late_vp = postwindow_vp = 0
    last_was_purchase = False
    try:
        for row in decisions:
            obs, action = row['observation'], row['chosen_action']
            public, bonuses, owned = _own_state(obs, actor)
            if owned != expected_owned or bonuses != expected_bonuses:
                raise ValueError('building requires complete own purchase / prebonus continuity')
            kind = action['type']
            if kind == 'choose_noble':
                exact(action, {'type', 'noble'}, 'choose_noble action')
                integer(action['noble'], 0, 9, 'visible noble')
                if public['phase'] != 'choose_noble' or not last_was_purchase:
                    raise ValueError('noble decision must follow its own purchase Main')
                last_was_purchase = False
                continue
            if public['phase'] != 'main' or kind not in (
                    'buy_market', 'buy_reserved', 'take_tokens', 'reserve_market', 'reserve_deck', 'pass'):
                raise ValueError('unknown building Main action / phase')
            main = len(after_main) + 1
            last_was_purchase = kind in ('buy_market', 'buy_reserved')
            if last_was_purchase:
                card_id, (_, colour, printed_vp, cost) = _purchase_target(obs, action)
                if card_id in owned:
                    raise ValueError('duplicate own purchase target')
                # Redeem existing investments BEFORE creating this purchase's
                # bonus. No investment can credit its own acquisition purchase.
                if main <= horizon:
                    for investment in investments:
                        if cost[COLORS.index(investment['colour'])] >= investment['bonus_ordinal']:
                            investment['use_main_actions'].append(main)
                if main <= k:
                    early_buys += 1
                    if printed_vp <= config['early_max_printed_vp']:
                        investments.append({'card': card_id, 'colour': COLORS[colour],
                                            'bonus_ordinal': bonuses[colour] + 1,
                                            'acquired_main': main, 'printed_vp': printed_vp,
                                            'use_main_actions': []})
                if k < main <= horizon:
                    late_vp += printed_vp
                if 25 <= main <= 32 and printed_vp > 0:
                    postwindow_vp += printed_vp
                expected_owned.add(card_id)
                expected_bonuses[colour] += 1
            after_main.append(list(expected_bonuses))
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('malformed building visible decision / purchase target') from exc
    if not after_main:
        raise ValueError('building requires complete game from initial Main')
    main_actions = len(after_main)
    for investment in investments:
        observed = len(investment['use_main_actions'])
        investment.update(observed_uses=observed, credited_uses=min(observed, use_cap),
                          unredeemed=observed == 0,
                          censored=main_actions < horizon and observed < use_cap)
    observed_units = sum(i['observed_uses'] for i in investments)
    capped_units = sum(i['credited_uses'] for i in investments)
    credited_units = min(capped_units, global_cap)
    totals = [sum(bonuses) for bonuses in after_main]
    pad = max(0, k - main_actions)
    auc = math.fsum(totals[:k] + [totals[-1]] * pad) / k
    return {'format': 'prism-building-profile-v1',
            'building_utility': credited_units / global_cap,
            'building_use_units': credited_units,
            'building_use_units_before_global_cap': capped_units,
            'building_observed_use_units': observed_units,
            'main_actions': main_actions, 'decision_actions': len(decisions),
            'after_main_bonuses': after_main,
            'early_bonus_auc12': auc, 'early_bonus_auc12_unit': 'permanent-discounts',
            'early_bonus_auc12_padding': 'held-at-terminal-descriptive-only',
            'early_bonus_auc12_padding_main_actions': pad,
            'early_buys': early_buys, 'early_lowvp_buys': len(investments),
            'investments': investments,
            'redeemed_investments': sum(not i['unredeemed'] for i in investments),
            'unredeemed_investments': sum(i['unredeemed'] for i in investments),
            'censored_investments': sum(i['censored'] for i in investments),
            'unredeemed_censored_investments': sum(i['unredeemed'] and i['censored'] for i in investments),
            'shorter_than_early_window': main_actions < k,
            'redemption_horizon_censored': main_actions < horizon,
            'late_vp_bought_main13to24': late_vp,
            'observed_main13to24': max(0, min(main_actions, 24) - 12),
            'late_scoring_vp_main25to32': postwindow_vp,
            'observed_main25to32': max(0, min(main_actions, 32) - 24),
            'late_scoring_main25to32_censored': main_actions < 32}


def extract_building_profile(game, config):
    if game.get('catalog_fingerprint') != BASE_CATALOG_FINGERPRINT:
        raise ValueError('building game public catalog fingerprint mismatch')
    profile = profile_from_own_decisions(game['decisions'], game['actor'], config,
                                        terminal=game.get('terminal'))
    return dict(profile, job_id=game['job_id'], actor=game['actor'],
                replay_sha256=game['replay_sha256'], sidecar_sha256=game['sidecar_sha256'])


def extract_building_targets(games, config):
    validate_building_config(config)
    if not isinstance(games, list) or not games:
        raise ValueError('nonempty building terminal games required')
    profiles = [extract_building_profile(game, config) for game in games]
    targets = {(p['job_id'], p['actor']): p['building_utility'] for p in profiles}
    if len(targets) != len(games):
        raise ValueError('duplicate style actor coverage')
    total_investments = sum(p['early_lowvp_buys'] for p in profiles)
    summary = {'format': 'prism-building-targets-v1', 'style_contract_sha256': canonical_hash(config),
               'games': profiles, 'early_bonus_auc12_unit': 'permanent-discounts',
               'early_bonus_auc12_padding': 'held-at-terminal-descriptive-only',
               'investment_redemption_rate': (sum(p['redeemed_investments'] for p in profiles)
                                              / total_investments if total_investments else None),
               'short_game_fraction': sum(p['shorter_than_early_window'] for p in profiles) / len(profiles),
               'redemption_horizon_censored_fraction': sum(p['redemption_horizon_censored'] for p in profiles) / len(profiles),
               'late_scoring_main25to32_censored_fraction': sum(p['late_scoring_main25to32_censored'] for p in profiles) / len(profiles)}
    for metric in ('building_utility', 'early_bonus_auc12', 'building_use_units',
                   'building_use_units_before_global_cap', 'building_observed_use_units',
                   'early_lowvp_buys', 'redeemed_investments', 'unredeemed_investments',
                   'censored_investments', 'unredeemed_censored_investments',
                   'late_vp_bought_main13to24', 'late_scoring_vp_main25to32',
                   'observed_main13to24', 'observed_main25to32'):
        summary['mean_' + metric] = math.fsum(p[metric] for p in profiles) / len(profiles)
    summary['total_early_lowvp_buys'] = total_investments
    summary['total_redeemed_investments'] = sum(p['redeemed_investments'] for p in profiles)
    return targets, summary
