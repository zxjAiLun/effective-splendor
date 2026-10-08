"""Frozen exports on identical saved player-visible states; no games or fit."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import time

from prism_building_training_diagnostic_m62 import distribution


def policy_summary(classes, probabilities):
    if len(classes) != len(probabilities) or not classes or any(not math.isfinite(p) or p < 0 for p in probabilities):
        raise ValueError('invalid aligned probabilities')
    if abs(math.fsum(probabilities) - 1) > 1e-10:
        raise ValueError('probability conservation')
    mass = {c: math.fsum(p for c0, p in zip(classes, probabilities) if c0 == c)
            for c in sorted(set(classes))}
    low, high = mass.get('buy_lowvp', 0), mass.get('buy_scoring', 0)
    return {'mass': mass, 'lowvp_mass': low, 'scoring_mass': high,
            'buy_conditional_lowvp': low / (low + high) if low + high else None,
            'greedy_class': classes[max(range(len(probabilities)), key=probabilities.__getitem__)],
            'entropy_nats': -math.fsum(p * math.log(p) for p in probabilities if p),
            'probabilities': probabilities}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('refuse overwrite')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    from training.prism_portable.engine.export import load_weights
    from training.prism_portable.engine.ppo.building import BASE_CATALOG_FINGERPRINT
    from training.prism_portable.engine.io import sha256_file
    with gzip.open(args.training, 'rt', encoding='utf-8') as stream:
        training = json.load(stream)
    states = training['panel']
    if training['receipt']['status'] != 'VERIFIED_SAVED_FORMULAS' or not 1 <= len(states) <= 512:
        raise ValueError('panel provenance/size')
    weights = {'base': (root / 'local-artifacts/prism/balance-v0.1.0/weights.json', '225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1'),
               'control': (root / 'local-artifacts/prism/m62-reception-2026-10-04/harvest/control/weights.json', '1ea1f493993f6930464baf942c0b36cb1f1db025109f458d9d42f746aba5e19f'),
               'beta': (root / 'local-artifacts/prism/m62-reception-2026-10-04/harvest/beta/weights.json', '69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb')}
    models = {}
    for key, (path, digest) in weights.items():
        if sha256_file(path) != digest:
            raise ValueError('weight drift ' + key)
        models[key] = load_weights(path, expected_catalog_fingerprint=BASE_CATALOG_FINGERPRINT)
    result = {'format': 'm62-saved-state-policy-panel-v1', 'status': 'VERIFIED_OFFLINE_POLICY_PREFERENCES',
              'new_games': 0, 'optimizer_updates': 0, 'training_input_sha256': sha256_file(args.training),
              'weights': {k: {'path': str(v[0]), 'sha256': v[1]} for k, v in weights.items()},
              'temperature': 1, 'probability_semantics': 'float32 network, float64 softmax, no action bias',
              'limitation': 'training-state opportunity panel; probabilities and greedy action class, no future return or causal match effect',
              'states': [], 'summaries': []}
    clocks = {key: 0.0 for key in models}
    started = time.perf_counter()
    for state in states:
        row = {k: v for k, v in state.items() if k != 'input'}
        row['policies'] = {}
        for key, model in models.items():
            tick = time.perf_counter()
            prediction = model.predict(state['input'])
            clocks[key] += time.perf_counter() - tick
            probabilities = torch.softmax(torch.tensor(prediction['logits'], dtype=torch.float64), -1).tolist()
            row['policies'][key] = policy_summary(state['action_classes'], probabilities)
        result['states'].append(row)
    groups = [('all', lambda s: True), ('with_scoring_buy', lambda s: 'buy_scoring' in s['action_classes'])]
    groups += [(f'{arm}/cycle{cycle}', lambda s,a=arm,c=cycle: s['arm']==a and s['cycle']==c)
               for arm in ('control','beta') for cycle in range(1,5)]
    groups += [(f'physical_actor{actor}', lambda s,a=actor: s['actor']==a) for actor in (0,1)]
    for name, select in groups:
        selected = [s for s in result['states'] if select(s)]
        if not selected:
            continue
        summaries = {}
        for key in models:
            policies = [s['policies'][key] for s in selected]
            summaries[key] = {metric: distribution([p[metric] for p in policies])
                              for metric in ('lowvp_mass', 'scoring_mass', 'buy_conditional_lowvp', 'entropy_nats')}
            summaries[key]['greedy_lowvp_count'] = sum(p['greedy_class']=='buy_lowvp' for p in policies)
            summaries[key]['greedy_class_counts'] = {c: sum(p['greedy_class']==c for p in policies)
                                                     for c in sorted({p['greedy_class'] for p in policies})}
        result['summaries'].append({'group': name, 'states': len(selected), 'models': summaries,
                                    'beta_minus_control_lowvp_mass': distribution([s['policies']['beta']['lowvp_mass']-s['policies']['control']['lowvp_mass'] for s in selected]),
                                    'beta_minus_control_buy_conditional': distribution([s['policies']['beta']['buy_conditional_lowvp']-s['policies']['control']['buy_conditional_lowvp'] for s in selected])})
    result['clock'] = {'scope': 'offline local CPU, serial model.predict wall including single-state collation; not competitive Arena inference latency',
                       'model_predict_wall_seconds': clocks, 'panel_wall_seconds': time.perf_counter()-started,
                       'torch': torch.__version__, 'python': sys.version, 'threads': 1}
    result['source_hashes'] = {name: sha256_file(root/name) for name in (
        'scripts/prism_building_policy_panel_m62.py', 'training/prism_portable/engine/model.py',
        'training/prism_portable/engine/data.py', 'training/prism_portable/engine/export.py')}
    for key, (path, digest) in weights.items():
        if sha256_file(path) != digest:
            raise ValueError('weights changed during panel')
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({'status': result['status'], 'states': len(states), 'sha256': sha256_file(args.output), 'clock': result['clock']}, indent=2))


if __name__ == '__main__':
    main()
