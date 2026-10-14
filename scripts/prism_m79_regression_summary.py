"""Summarize the source-bound offline diagnostic; posthoc intervals only."""
import json
import hashlib
from collections import Counter
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / 'local-artifacts/prism/m79-mainline/regression-diagnostic'


def build():
    p = DIR / 'diagnostic.json'
    assert hashlib.sha256(p.read_bytes()).hexdigest() == '73be1af222e4be398b1d40c4014c8e503f5ad29b634b68be6ed6a02605cd6730'
    x = json.loads(p.read_text(encoding='utf-8'))
    report = {'source_sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'new_games': 0,
              'coverage': x['coverage'], 'legal_panel_checks': x['affordability_rust_panel_checks'],
              'bootstrap': {'samples': 20000, 'seed': 81009999, 'unit': 'same environment seed with both seats averaged',
                            'role': 'posthoc descriptive; not a new frozen gate'}, 'opponents': {}, 'examples': []}
    games = {r['game_key']: r for r in x['games']}
    for o in ['heuristic', 'balance']:
        rows = [r for r in x['paired_games'] if r['opponent'] == o]
        seeds = sorted({r['seed'] for r in rows})
        assert len(rows) == 512 and len(seeds) == 256
        assert all({r['seat'] for r in rows if r['seed'] == s} == {0, 1} for s in seeds)
        arr = np.array([np.mean([r['delta'] for r in rows if r['seed'] == s]) for s in seeds])
        rng = np.random.default_rng(81009999)
        ci = np.quantile(arr[rng.integers(0, len(arr), (20000, len(arr)))].mean(axis=1), [.025, .975])
        groups = {}
        for name, subset in [('all', rows), ('worsened', [r for r in rows if r['delta'] < 0]), ('improved', [r for r in rows if r['delta'] > 0])]:
            ds = [r['first_divergence'] for r in subset if r['first_divergence']]
            groups[name] = {'games': len(subset), 'divergent_games': len(ds),
                            'first_divergence_main_le12': sum(d['a']['own_main'] <= 12 for d in ds),
                            'transitions': dict(Counter(d['base']['action']['type'] + '->' + d['a']['action']['type'] for d in ds))}
        report['opponents'][o] = {'delta': float(arr.mean()), 'posthoc_95_ci': ci.tolist(),
                                 'outcome_transitions': x['transitions'][o], 'first_divergence': groups,
                                 'base': x['summary'][f'base/{o}'], 'a': x['summary'][f'a/{o}']}
        # Deterministic illustrative selection, not an estimate or a cause label.
        eligible = [r for r in rows if r['base_score'] == 1 and r['a_score'] == 0
                    and r['first_divergence']['a']['action']['type'] == r['first_divergence']['base']['action']['type'] == 'take_tokens']
        case = min(eligible, key=lambda r: (r['first_divergence']['a']['own_main'], r['seed'], r['seat']))
        report['examples'].append({**case, 'selection_rule': 'earliest first-divergence Main then seed then seat, among win-to-loss and take-to-take pairs',
                                   'trajectories': {k: games[case[k]] for k in ['base_key', 'a_key']}})
    (DIR / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({o: {'delta': r['delta'], 'ci': r['posthoc_95_ci']} for o, r in report['opponents'].items()}))


if __name__ == '__main__': build()
