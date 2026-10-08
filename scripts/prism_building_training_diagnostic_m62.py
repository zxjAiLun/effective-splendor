"""Read frozen M62 trajectories without opening or mutating a PPO Run.

Outputs a gzip JSON stream to stdout. No arena, optimizer, store writer or model
forward is invoked. Hash-checked trusted Torch payloads supply historical metrics.
The opportunity panel contains existing player-visible states, never rollouts.
"""
import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def distribution(values):
    if not values:
        return {'n': 0, 'mean': None, 'std': None}
    ordered = sorted(values)
    def quantile(p):
        at = (len(ordered) - 1) * p
        lo = int(at)
        return ordered[lo] + (ordered[min(lo + 1, len(ordered) - 1)] - ordered[lo]) * (at - lo)
    return {'n': len(values), 'mean': statistics.fmean(values),
            'std': statistics.pstdev(values), 'min': ordered[0],
            'p10': quantile(.1), 'median': quantile(.5),
            'p90': quantile(.9), 'max': ordered[-1]}


def covariance(left, right):
    if not left or len(left) != len(right):
        raise ValueError('aligned nonempty values required')
    lm, rm = statistics.fmean(left), statistics.fmean(right)
    return math.fsum((x - lm) * (y - rm) for x, y in zip(left, right)) / len(left)


def advantage_summary(outcome, residual, beta):
    if len(outcome) != len(residual) or not outcome:
        raise ValueError('advantage alignment')
    weighted = [beta * x for x in residual]
    combined = [x + y for x, y in zip(outcome, weighted)]
    om, osd = statistics.fmean(outcome), statistics.pstdev(outcome)
    cm, csd = statistics.fmean(combined), statistics.pstdev(combined)
    normal_outcome = [(x - om) / (osd + 1e-8) for x in outcome]
    normal_combined = [(x - cm) / (csd + 1e-8) for x in combined]
    return {'outcome_gae': distribution(outcome), 'style_residual': distribution(residual),
            'weighted_style': distribution(weighted), 'combined': distribution(combined),
            'covariance_outcome_weighted_style': covariance(outcome, weighted),
            'centered_style_std_over_combined_std': statistics.pstdev(weighted) / csd if csd else None,
            'normalized_change': distribution([c - o for c, o in zip(normal_combined, normal_outcome)]),
            'normalized_mean_absolute_change': statistics.fmean(abs(c - o) for c, o in zip(normal_combined, normal_outcome)),
            'centered_sign_flip_count': sum((c > 0) != (o > 0) for c, o in zip(normal_combined, normal_outcome)),
            'interpretation': 'decision advantage inputs; not parameter gradients or causal attribution'}


def action_classes(row, purchase_target):
    classes = []
    for action in row['legal_actions']:
        kind = action['type']
        if kind in ('buy_market', 'buy_reserved'):
            _, card = purchase_target(row['observation'], action)
            classes.append('buy_lowvp' if card[2] <= 1 else 'buy_scoring')
        else:
            classes.append(kind)
    if len(classes) != len(row['request']['input']['actions']):
        raise ValueError('semantic/input action mismatch')
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    # Finite read-only process. The host has two CPUs; bind to at most two.
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['OMP_NUM_THREADS'] = '1'
    import resource
    import signal
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024 ** 3, 4 * 1024 ** 3))
    resource.setrlimit(resource.RLIMIT_CPU, (1200, 1200))
    signal.alarm(600)
    affinity = sorted(os.sched_getaffinity(0))[:2]
    os.sched_setaffinity(0, affinity)
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    root = args.root.resolve()
    pins = {
        'training/prism_portable/engine/ppo/building.py': '7b57fd996ec497b8e7332e62f8a466e4a4d04f77a883b5c768c3f59b4399d8b8',
        'training/prism_portable/engine/ppo/learner.py': '1942662bb7e0bb16d1ef4b436f52eb8beee656ab4e59ace4f6728af54c53879c',
        'benchmarks/m62-prism-beta-building.config.json': '4f3ff90c89b017ad4b1fdb0f344b1ca84bc55ea641d5a1aee3b0bb50463eb408'}
    for name, expected in pins.items():
        if sha(root / name) != expected:
            raise ValueError('frozen source drift: ' + name)
    sys.path.insert(0, str(root))
    from training.prism_portable.engine.ppo.building import default_building_config, profile_from_own_decisions, _purchase_target
    from training.prism_portable.engine.ppo.learner import terminal_gae
    from training.prism_portable.engine.ppo.contract import validate_audit
    payloads = {'control': 'aedd82178117b4fca0a37dc2f92a86be713eb1e0b02ad6ff8a22cdbef4828323',
                'beta': 'fc86f14270a6925c085addd75b554866d793a294848e816cf041368f37205350'}
    output = {'format': 'm62-readonly-training-diagnostic-v1', 'new_games': 0,
              'optimizer_updates': 0, 'arms': {}, 'panel': [], 'pins': pins,
              'panel_selection': 'first 32 eligible games by seed/job per arm/cycle/actor; first own Main<=12 low-VP buy opportunity with another action class'}
    verified = 0
    original_hashes = {}
    for arm, payload in payloads.items():
        run = root / 'campaigns' / f'm62-{arm}-building-g0' / 'run'
        ledger_path = root / f'audit-{arm}' / 'training-source-ledger.json'
        ledger = json.loads(ledger_path.read_text())
        original_hashes[str(ledger_path)] = sha(ledger_path)
        for path in (run / 'HEAD.json', run / 'writer.lock'):
            original_hashes[str(path)] = sha(path)
        state_path = run / 'objects' / (payload + '.pt')
        if sha(state_path) != payload:
            raise ValueError('trusted checkpoint hash mismatch')
        state = torch.load(state_path, map_location='cpu', weights_only=False)
        sealed = {x['cycle']: x for x in state['metrics'] if x['event'] == 'sealed'}
        historical_profiles = {}
        for metric in state['metrics']:
            if metric['event'] == 'style_extracted':
                p = run / 'objects' / (metric['artifact'] + '.json')
                if sha(p) != metric['artifact']:
                    raise ValueError('style target object drift')
                historical_profiles.update({(x['job_id'], x['actor']): x for x in json.loads(p.read_text())['games']})
        config = json.loads((run / 'config.json').read_text())
        ppo = config['ppo']
        cycles = {}
        profiles = []
        panel_counts = {}
        eligible_counts = {}
        hashes = []
        for source in sorted(ledger['rows'], key=lambda x: (x['cycle'], x['actor'], x['seed'], x['job_id'])):
            folder = Path(source['local_replay']).parent
            for name, digest in source['hashes'].items():
                if sha(folder / name) != digest:
                    raise ValueError('saved trajectory drift: ' + str(folder / name))
                verified += 1
            hashes.append({'job_id': source['job_id'], 'actor': source['actor'], 'cycle': source['cycle'],
                           'seed': source['seed'], 'hashes': source['hashes']})
            replay = json.loads((folder / 'replay.json').read_text())
            rows = [json.loads(line) for line in (folder / 'sidecar.jsonl').read_text().splitlines() if line]
            actor = source['actor']
            game = {'format': 'prism-ppo-game-v1', 'job_id': source['job_id'], 'actor': actor,
                    'game_id': rows[0]['request']['game_id'], 'behavior_id': source['behavior_id'],
                    'catalog_fingerprint': rows[0]['request']['catalog_fingerprint'], 'terminal': True,
                    'result': replay['result'], 'replay_sha256': source['hashes']['replay.json'],
                    'sidecar_sha256': source['hashes']['sidecar.jsonl'], 'decisions': rows}
            outcome = validate_audit(game, behavior_id=source['behavior_id'],
                                     catalog_fingerprint=game['catalog_fingerprint'], max_decisions=128)
            if replay['seed'] != source['seed']:
                raise ValueError('ledger replay seed mismatch')
            profile = profile_from_own_decisions(rows, actor, default_building_config())
            if arm == 'beta':
                old_profile = historical_profiles[(source['job_id'], actor)]
                if any(old_profile[k] != v for k, v in profile.items()):
                    raise ValueError('recomputed style profile differs from training target')
            profiles.append(dict(profile, cycle=source['cycle'], actor=actor, job_id=source['job_id'], seed=source['seed'], outcome=outcome))
            values = [r['response']['value'] for r in rows]
            style_values = [r['response']['style_value'] for r in rows]
            style_return = profile['building_utility'] if arm == 'beta' else 0.0
            residual = [style_return - v for v in style_values]
            cycle = cycles.setdefault(source['cycle'], {'outcome': [], 'residual': [], 'style_values': [], 'games': 0})
            cycle['outcome'].extend(terminal_gae(values, outcome, ppo['gae_lambda']))
            cycle['residual'].extend(residual)
            cycle['style_values'].extend(style_values)
            cycle['games'] += 1
            key = (source['cycle'], actor)
            own_main = 0
            for row in rows:
                if row['chosen_action']['type'] == 'choose_noble':
                    continue
                own_main += 1
                if own_main > 12:
                    break
                classes = action_classes(row, _purchase_target)
                if 'buy_lowvp' in classes and any(c != 'buy_lowvp' for c in classes):
                    eligible_counts[key] = eligible_counts.get(key, 0) + 1
                    if panel_counts.get(key, 0) < 32:
                        output['panel'].append({'arm': arm, 'cycle': source['cycle'], 'actor': actor,
                                                'job_id': source['job_id'], 'seed': source['seed'], 'own_main': own_main,
                                                'sidecar_sha256': source['hashes']['sidecar.jsonl'],
                                                'decision_index': row['request']['decision_index'],
                                                'input': row['request']['input'], 'action_classes': classes,
                                                'chosen_index': row['response']['chosen_index']})
                        panel_counts[key] = panel_counts.get(key, 0) + 1
                    break
        summaries = []
        for index, cycle in sorted(cycles.items()):
            summary = advantage_summary(cycle['outcome'], cycle['residual'], ppo['style_beta'])
            if cycle['games'] != 256 or len(cycle['outcome']) != sealed[index]['decisions']:
                raise ValueError('cycle coverage mismatch')
            for k, value in [('advantage_mean', summary['combined']['mean']), ('advantage_std', summary['combined']['std'])]:
                if abs(value - sealed[index][k]) > 1e-12:
                    raise ValueError('recomputed sealed advantage mismatch')
            steps = [m for m in state['metrics'] if m['event'] == 'optimizer_step' and m['cycle'] == index]
            total_samples = sum(m['samples'] for m in steps)
            losses = {k: math.fsum(m[k] * m['samples'] for m in steps) / total_samples
                      for k in ('policy_loss', 'outcome_bce', 'style_mse', 'entropy', 'normalized_entropy', 'kl', 'clip_fraction')}
            summaries.append(dict(summary, cycle=index, games=cycle['games'],
                                  old_style_value=distribution(cycle['style_values']),
                                  historical_sealed=sealed[index], optimizer_steps=len(steps),
                                  historical_sample_weighted_losses=losses,
                                  profile_utility=distribution([p['building_utility'] for p in profiles if p['cycle'] == index]),
                                  profile_auc12=distribution([p['early_bonus_auc12'] for p in profiles if p['cycle'] == index])))
        output['arms'][arm] = {'final_payload_sha256': payload, 'source_ledger_sha256': sha(ledger_path),
                               'ppo': ppo, 'cycles': summaries, 'profiles': profiles, 'sources': hashes,
                               'panel_coverage': [{'cycle': c, 'actor': a, 'eligible': eligible_counts.get((c,a), 0),
                                                   'selected': panel_counts.get((c,a), 0)} for c in range(1,5) for a in (0,1)]}
        del state
    if len(output['panel']) > 512 or verified != 12288:
        raise ValueError('bounded complete source coverage mismatch')
    if any(sha(Path(path)) != digest for path, digest in original_hashes.items()):
        raise ValueError('historical HEAD/lock/ledger changed during diagnostic')
    output['receipt'] = {'status': 'VERIFIED_SAVED_FORMULAS', 'source_files_verified': verified,
                         'source_sha256': hashlib.sha256(SOURCE_BYTES).hexdigest() if 'SOURCE_BYTES' in globals() else None,
                         'original_control_hashes': original_hashes, 'original_control_drift': 0,
                         'wall_seconds_before_serialization': time.perf_counter() - started,
                         'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                         'torch': torch.__version__, 'python': sys.version, 'cpu_affinity': affinity,
                         'memory_limit_bytes': 4 * 1024**3, 'wall_limit_seconds': 600,
                         'new_games': 0, 'optimizer_updates': 0, 'panel_states': len(output['panel'])}
    sys.stdout.buffer.write(gzip.compress(json.dumps(output, allow_nan=False, separators=(',', ':')).encode(), mtime=0))


if __name__ == '__main__':
    main()
