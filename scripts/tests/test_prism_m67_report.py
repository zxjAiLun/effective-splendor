"""Synthetic, zero-game tests for M67 statistics, provenance and common reading."""
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scripts import prism_m67_report as report
from scripts import prism_round_report as reader


def config():
    e = dict(common_opponents=report.OPPONENTS, common_seed_start=10, common_seed_end=12,
             direct_seed_start=20, direct_seed_end=22, common_games_per_model=36,
             direct_games=6, total_games=120, action_seed=67020001, bootstrap_samples=200,
             bootstrap_seed=67029999, lower_quantile=.0125, family_alpha=.05,
             gates=dict(zip(report.KEYS, (-.05, .45))),
             enhancement_thresholds=dict(zip(report.KEYS, (0., .5))), mode='both-greedy')
    return dict(format='m67-prism-alpha-repeat-v1', evaluation=e,
                base_model={'sha256': 'parent-sha'},
                assets={o: {'sha256': o + '-sha'} for o in [*report.OPPONENTS, 'parent']},
                runtime={'numeric_source_identity': 'numeric-sha'},
                names=dict(parent='Prism Alpha v0.1.5', **{'candidate-a': 'M67 A c20 unpublished training checkpoint', 'candidate-b': 'M67 B c20 unpublished training checkpoint'}),
                training={a: dict(games=5120, cycles=20, blueprint=a + '.json', run_seed=i, seed_start=i * 10000) for i, a in enumerate(report.ARMS, 1)})


def rows(model, opponents, start, end, score):
    return [dict(candidate=model, opponent=o, seed=seed, candidate_seat=seat,
                 candidate_score=score if not isinstance(score, tuple) else score[seat])
            for o in opponents for seed in range(start, end + 1) for seat in (0, 1)]


def cohorts(c, a=1, b=.5, ad=1, bd=.5):
    e = c['evaluation']
    return [rows('base', e['common_opponents'], 10, 12, .5),
            rows('candidate-a', e['common_opponents'], 10, 12, a),
            rows('candidate-b', e['common_opponents'], 10, 12, b),
            rows('candidate-a', ['parent'], 20, 22, ad),
            rows('candidate-b', ['parent'], 20, 22, bd)]


def metrics(games):
    m = dict(games=games, wins=0, ties=games, losses=0, score_rate=.5,
             mean_cards_by_vp={str(v): 1. for v in range(6)},
             mean_bonuses_by_color={v: 1. for v in ('White', 'Blue', 'Green', 'Red', 'Black')},
             games_with_nobles=games, total_main_actions=games * 20,
             action_distribution={v: games for v in ('buy_market', 'buy_reserved', 'take_tokens', 'reserve_market', 'reserve_deck', 'choose_noble', 'pass')})
    for key in ('win_rate_percent', 'mean_prestige', 'vp_per_main_action', 'vp_per_turn', 'vp_per_ply',
                'mean_nobles', 'games_with_nobles_percent', 'mean_permanent_bonuses',
                'mean_reserves_acquired', 'mean_reserves_bought', 'mean_reserves_stranded',
                'reserve_redemption_rate_percent'):
        m[key] = 1.
    m['action_percentages'] = {key: 100 / 7 for key in m['action_distribution']}
    return m


def pair(model, opponent, games):
    return dict(candidate=model, opponent=opponent, candidate_metrics=metrics(games),
                opponent_metrics=metrics(games), macro={},
                seats=[dict(candidate_seat=seat, candidate=metrics(games // 2), opponent=metrics(games // 2)) for seat in (0, 1)],
                score_ci=dict(ci95=[.4, .6], seed_blocks=games // 2),
                win_ci=dict(ci95=[0., .1], seed_blocks=games // 2))


def fixture(root, c):
    """Five tiny native arena results; shard reads are supplied separately."""
    report.write(root / report.CONFIG, c)
    allrows = {}
    for name, saved in zip(report.WORKS, cohorts(c)):
        work = root / 'evaluation' / name
        direct = name.endswith('direct')
        model = 'base' if name == 'reference' else 'candidate-' + name[0]
        weights = 'parent-sha' if name == 'reference' else name[0] + '-sha'
        opponents = ['parent'] if direct else report.OPPONENTS
        engine = dict(program='engine', sha256='engine-sha')
        def actor(key, weight):
            return dict(engine, args=['agent-heuristic-v02' if key == 'heuristic' else 'agent-prism', '--seed', str(c['evaluation']['action_seed'])],
                        files=[] if key == 'heuristic' else [dict(sha256=weight)])
        conf = dict(engine=engine, action_seed=c['evaluation']['action_seed'],
                    seeds=list(range(20, 23) if direct else range(10, 13)),
                    candidates={model: actor(model, weights)},
                    opponents={o: actor(o, c['assets'][o]['sha256']) for o in opponents})
        report.write(work / 'config.json', conf)
        shard = dict(name='shard-0', games=len(saved), output=str(work / 'shard-0'), config='unused')
        plan = dict(config_sha256=report.digest(work / 'config.json'), action_seed=c['evaluation']['action_seed'],
                    candidates={model: dict(mode='greedy')}, opponents={o: dict(mode='greedy') for o in opponents},
                    metrics_program={'sha256': 'metrics-sha'}, shards=[shard], limits={'workers': 4})
        report.write(work / 'plan.json', plan)
        raw = dict(games=len(saved), config_sha256=report.digest(work / 'config.json'),
                   plan_sha256=report.digest(work / 'plan.json'), pairs=[pair(model, o, 6) for o in opponents])
        for p in raw['pairs']:
            score = next(r['candidate_score'] for r in saved if r['opponent'] == p['opponent'])
            for role, value in [('candidate', score), ('opponent', 1 - score)]:
                for m in [p[role + '_metrics'], *[s[role] for s in p['seats']]]:
                    m.update(wins=m['games'] if value == 1 else 0,
                             ties=m['games'] if value == .5 else 0,
                             losses=m['games'] if value == 0 else 0,
                             score_rate=value, win_rate_percent=100 if value == 1 else 0)
        report.write(work / 'result.json', raw)
        work.joinpath('report.md').write_text('# Saved arena\n\n| actor | games |\n| --- | --- |\n| saved | 6 |\n', encoding='utf-8')
        work.joinpath('report.html').write_text('<p>saved report</p>', encoding='utf-8')
        report.write(work / 'status.json', dict(completed_games=len(saved), elapsed_wall_seconds=3.,
                     plan_sha256=report.digest(work / 'plan.json'), shards={'shard-0': dict(state='COMPLETE', games=len(saved))}))
        report.write(work / 'completion.json', dict(status='COMPLETED_DEVELOPMENT_ONLY', games=len(saved), automatic_game_retries=0,
                     plan_sha256=report.digest(work / 'plan.json'), result_sha256=report.digest(work / 'result.json'),
                     report_sha256=report.digest(work / 'report.md'), html_sha256=report.digest(work / 'report.html')))
        allrows[str(work / 'shard-0')] = saved
    for arm in report.ARMS:
        report.write(root / f'audits/{arm}/audit.json', dict(status='PASS_TRAINING_ARTIFACT_AUDIT', completed_games=5120,
                     weights_sha256=arm + '-sha', checkpoint=dict(cycle=20, games=5120, weights_sha256=arm + '-sha')))
    return allrows


class M67ReportTests(unittest.TestCase):
    def test_four_gates_and_separate_enhancement(self):
        c = config()
        measurements, gates, enhancements = report.competitive(c, *cohorts(c))
        self.assertEqual(len(measurements), 4)
        self.assertTrue(all(gates.values()))
        self.assertEqual(measurements['candidate-a/strength_pool']['mean'], .5)
        self.assertEqual(measurements['candidate-b/strength_pool']['mean'], 0.)
        self.assertTrue(enhancements['candidate-a/direct_parent'])
        self.assertFalse(enhancements['candidate-b/direct_parent'])
        self.assertFalse(all(enhancements.values()))
        self.assertTrue(all(report.competitive(c, *cohorts(c, b=1, bd=1))[2].values()))
        for m in measurements.values():
            self.assertEqual(m['lower_quantile'], .0125)
            self.assertEqual(m['seed_blocks'], 3)
        failed = report.competitive(c, *cohorts(c, a=0, b=0, ad=0, bd=0))
        self.assertFalse(any(failed[1].values()))
        self.assertFalse(any(failed[2].values()))

    def test_ordinary_interval_is_independent_of_simultaneous_lower(self):
        values = np.array([0., .25, .5, .75, 1.])
        m = report.measure(values, seed=9, count=400, lower=.0125)
        draws = np.random.default_rng(9).integers(0, len(values), (400, len(values)))
        means = values[draws].mean(axis=1)
        self.assertEqual(m['ci95'], np.quantile(means, [.025, .975]).tolist())
        self.assertEqual(m['simultaneous_one_sided_lower'], float(np.quantile(means, .0125)))

    def test_reject_incomplete_duplicate_identity_and_cohort(self):
        c = config()
        for kind in ('missing', 'duplicate', 'identity', 'cohort', 'score', 'seat'):
            with self.subTest(kind=kind):
                saved = cohorts(c)
                if kind == 'missing': saved[2].pop()
                if kind == 'duplicate': saved[2][-1] = saved[2][-2].copy()
                if kind == 'identity': saved[2][0]['candidate'] = 'candidate-a'
                if kind == 'cohort': saved[2][0]['seed'] = 99
                if kind == 'score': saved[2][0]['candidate_score'] = .75
                if kind == 'seat': saved[2][0]['candidate_seat'] = 2
                with self.assertRaises(ValueError): report.competitive(c, *saved)
        # Seat orientation is candidate-owned and averaged, not physical P0.
        _, values = report.block_values(rows('c', ['o'], 1, 1, (1, 0)), 'c', 'o')
        self.assertEqual(values.tolist(), [.5])

    def test_identity_and_both_greedy_guards(self):
        c = config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            saved = fixture(root, c)
            with patch.object(report, 'ROOT', root), patch('scripts.prism_notebook_arena.completed_shard', side_effect=lambda shard, receipt: saved[shard['output']]):
                records = {n: report.load_arena(c, n) for n in report.WORKS}
            weights = {'base': 'parent-sha', 'candidate-a': 'a-sha', 'candidate-b': 'b-sha'}
            report.verify_identity(c, records, weights)
            mutations = [('reference', 'config', 'candidates', 'base', 'weight'),
                         ('a-common', 'config', 'candidates', 'candidate-a', 'weight'),
                         ('b-direct', 'config', 'opponents', 'parent', 'weight'),
                         ('a-common', 'plan', 'candidates', 'candidate-a', 'mode'),
                         ('b-common', 'plan', 'opponents', 'alpha', 'mode'),
                         ('a-direct', 'config', 'candidates', 'candidate-a', 'sample')]
            for name, layer, role, model, kind in mutations:
                with self.subTest(name=name, kind=kind):
                    bad = copy.deepcopy(records)
                    actor = bad[name][layer][role][model]
                    if kind == 'weight': actor['files'][0]['sha256'] = 'wrong'
                    elif kind == 'mode': actor['mode'] = 'sample'
                    else: actor['args'].append('--sample')
                    with self.assertRaises(ValueError): report.verify_identity(c, bad, weights)

    def test_completion_provenance_and_report_drift(self):
        c = config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            saved = fixture(root, c)
            with patch.object(report, 'ROOT', root), patch('scripts.prism_notebook_arena.completed_shard', side_effect=lambda shard, receipt: saved[shard['output']]):
                report.load_arena(c, 'reference')
                path = root / 'evaluation/reference/completion.json'
                original = report.read(path)
                for field, value in [('result_sha256', 'wrong'), ('plan_sha256', 'wrong'), ('automatic_game_retries', 1), ('games', 1), ('status', 'RUNNING')]:
                    with self.subTest(field=field):
                        report.write(path, dict(original, **{field: value}))
                        with self.assertRaises(ValueError): report.load_arena(c, 'reference')
                report.write(path, original)
                (root / 'evaluation/reference/report.md').write_text('changed', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'report drift'): report.load_arena(c, 'reference')

    def test_full_common_reader_two_pages_no_mutation_or_overwrite(self):
        c = config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            saved = fixture(root, c)
            before = {p: report.digest(p) for p in root.rglob('*') if p.is_file()}
            with patch.object(report, 'ROOT', root), patch.object(report, 'contract', return_value=c), patch.object(reader, 'ROOT', root), patch('scripts.prism_notebook_arena.completed_shard', side_effect=lambda shard, receipt: saved[shard['output']]):
                built = report.build()
                self.assertEqual(built['games_dispatched'], 0)
                self.assertEqual(built['games'], 120)
                self.assertFalse(built['repeated_efficacy'])
                result = report.read(root / report.RESULT)
                for arm in report.ARMS:
                    spec = report.read(root / f'benchmarks/reports/m67-{arm}-reading.json')
                    projected = report.read(root / spec['result'])
                    self.assertEqual(spec['focus'], 'candidate-' + arm)
                    self.assertEqual(spec['baseline'], 'base')
                    self.assertEqual(projected['aggregate_result_sha256'], built['result_sha256'])
                    self.assertEqual(set(projected['candidate_sha256']), {'base', 'candidate-' + arm})
                    self.assertEqual(projected['measurements'][report.KEYS[0]], result['measurements']['candidate-' + arm + '/strength_pool'])
                    self.assertEqual(built['reading_receipts'][arm]['games_dispatched'], 0)
                    html = (root / spec['output']).read_text(encoding='utf-8')
                    payload = json.loads(re.search(r'<script[^>]*id="report-data"[^>]*>(.*?)</script>', html, re.S).group(1))
                    self.assertEqual(payload['focus'], 'candidate-' + arm)
                    self.assertEqual(payload['result']['common']['games'], 72)
                    self.assertEqual(payload['result']['direct']['games'], 6)
                    self.assertEqual({p['candidate'] for stage in payload['result'].values() for p in stage['pairs']}, {'base', 'candidate-' + arm})
                    md = (root / spec['output']).with_suffix('.reading.md').read_text(encoding='utf-8')
                    self.assertIn('模型物理座位', md)
                    self.assertIn('预留买回率', md)
                    self.assertIn('NOT_MEASURED', md)
                    self.assertIn('两个训练种子', md)
                    self.assertNotIn(built['result_sha256'], md)
                self.assertEqual({p: report.digest(p) for p in before}, before)
                hashes = {p: report.digest(p) for p in report.output_paths()}
                with self.assertRaisesRegex(ValueError, 'already exists'): report.build()
                self.assertEqual({p: report.digest(p) for p in hashes}, hashes)

    def test_contract_uses_m67_only_and_fixed_four_test_policy(self):
        c = config()
        e = c['evaluation']
        e.update(common_seed_start=9830000, common_seed_end=9832499, direct_seed_start=9840000,
                 direct_seed_end=9844999, common_games_per_model=30000, direct_games=10000,
                 total_games=110000, bootstrap_samples=20000)
        with patch.object(report, 'read', return_value=c), patch.object(report, 'numerical_identity', return_value='numeric-sha'), patch('scripts.prism_m66_report.contract', side_effect=AssertionError('M66 must not run')):
            self.assertIs(report.contract(), c)
            e['lower_quantile'] = .025
            with self.assertRaisesRegex(ValueError, 'policy drift'): report.contract()


if __name__ == '__main__':
    unittest.main()
