"""Terminal rush utility from player-visible prestige, without private-card inputs."""
import math

from ..io import canonical_hash
from .contract import exact, integer

STYLE_KEYS = {'format', 'window_main_actions', 'score_cap', 'diagnostic_horizon_main_actions',
              'diagnostic_score_threshold', 'short_game_padding', 'phase_semantics',
              'terminal_only', 'style_reward_input'}


def validate_style_config(value):
    exact(value, STYLE_KEYS, 'rush style contract')
    expected = {'format': 'prism-rush-style-v1', 'short_game_padding': 'terminal-prestige',
                'phase_semantics': 'choose_noble-belongs-to-preceding-main', 'terminal_only': True,
                'style_reward_input': 'player-visible-own-prestige-and-terminal-own-prestige'}
    if any(type(value[k]) is not type(v) or value[k] != v for k, v in expected.items()):
        raise ValueError('unsupported rush utility semantics')
    integer(value['window_main_actions'], 1, 256, 'rush window')
    integer(value['score_cap'], 1, 255, 'rush VP cap')
    integer(value['diagnostic_horizon_main_actions'], 1, 256, 'diagnostic horizon')
    integer(value['diagnostic_score_threshold'], 1, 255, 'diagnostic VP threshold')
    return value


def profile_from_after_main(scores, terminal_prestige, config):
    """Scores after each own Main INCLUDING that Main's noble settlement."""
    validate_style_config(config)
    integer(terminal_prestige, 0, 255, 'terminal prestige')
    if not isinstance(scores, list) or not scores:
        raise ValueError('nonempty completed Main score curve required')
    previous = 0
    for score in scores:
        integer(score, previous, terminal_prestige, 'nondecreasing own prestige')
        previous = score
    if scores[-1] != terminal_prestige:
        raise ValueError('final own Main score must equal terminal prestige')
    k, cap = config['window_main_actions'], config['score_cap']
    padded = scores[:k] + [terminal_prestige] * max(0, k - len(scores))
    utility = math.fsum(min(s, cap) / cap for s in padded) / k
    horizon, threshold = config['diagnostic_horizon_main_actions'], config['diagnostic_score_threshold']
    crossing = next((i + 1 for i, score in enumerate(scores[:horizon]) if score >= threshold), None)
    return {'rush_auc': utility, 'main_actions': len(scores), 'after_main_prestige': scores,
            'shorter_than_reward_window': len(scores) < k,
            'vp_threshold_by_horizon': crossing is not None, 'first_main_to_threshold': crossing,
            'terminal_prestige': terminal_prestige}


def extract_rush_profile(game, config):
    """The projected shard is checked by the pinned Arena ingestion contract.

    Opponent actions cannot change our prestige in classic Splendor. Therefore
    the next own Main's pre-score equals the preceding Main's settled post-score.
    Only public own prestige/phase and the actual terminal own score are consumed.
    """
    validate_style_config(config)
    if game.get('terminal') is not True:
        raise ValueError('rush utility requires a real terminal, never a prefix')
    actor = integer(game['actor'], 0, 1, 'rush actor')
    before = []
    for row in game['decisions']:
        obs = row['observation']
        if obs.get('viewer') != actor or type(obs.get('viewer')) is not int:
            raise ValueError('rush projection viewer mismatch')
        public = obs['public']
        if public['current_player'] != actor:
            raise ValueError('rush projected actor mismatch')
        choose = row['chosen_action']['type'] == 'choose_noble'
        if choose:
            if public['phase'] == 'main' or not before:
                raise ValueError('noble decision is not its own Main action')
            continue
        if public['phase'] != 'main':
            raise ValueError('unknown Main/noble phase')
        player = public['players'][actor]
        if player['id'] != actor:
            raise ValueError('rush public player index mismatch')
        before.append(integer(player['prestige'], 0, 255, 'own public prestige'))
    if not before or before[0] != 0:
        raise ValueError('rush requires complete game from the initial Main')
    terminal = integer(game['result']['scores'][actor], 0, 255, 'terminal own prestige')
    profile = profile_from_after_main(before[1:] + [terminal], terminal, config)
    return dict(profile, job_id=game['job_id'], actor=actor,
                replay_sha256=game['replay_sha256'], sidecar_sha256=game['sidecar_sha256'])


def extract_style_targets(games, config):
    profiles = [extract_rush_profile(game, config) for game in games]
    targets = {(p['job_id'], p['actor']): p['rush_auc'] for p in profiles}
    if len(targets) != len(games):
        raise ValueError('duplicate style actor coverage')
    summary = {'format': 'prism-rush-targets-v1', 'style_contract_sha256': canonical_hash(config),
               'games': profiles, 'mean_rush_auc': math.fsum(p['rush_auc'] for p in profiles) / len(profiles),
               'vp_threshold_by_horizon_rate': sum(p['vp_threshold_by_horizon'] for p in profiles) / len(profiles),
               'short_game_fraction': sum(p['shorter_than_reward_window'] for p in profiles) / len(profiles)}
    return targets, summary
