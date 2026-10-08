"""M61 report regression checks use old measured data only as synthetic fixtures."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('m61_report', ROOT / 'scripts/prism_balance_ab_report_m61.py')
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def measurements(pool=(-.02, .02), direct=(.48, .52)):
    out = {}
    for key, (_, threshold, _, _, _) in report.MEASURES.items():
        lower, upper = ((threshold + .01, threshold + .03) if key in report.FLOORS
                        else pool if key.endswith('strength_pool') else direct)
        out[key] = {'mean': (lower + upper) / 2, 'ci95': [lower, upper],
                    'simultaneous_two_sided_ci': [lower, upper],
                    'simultaneous_lower': lower, 'simultaneous_upper': upper, 'seed_blocks': 256}
    return out


def fixture():
    # Historical frozen artifacts are never changed or used as M61 evidence.
    source = json.loads((ROOT / 'benchmarks/m60-prism-alpha-cloud-ppo.evaluation-result.json').read_text(encoding='utf-8'))
    extra = json.loads((ROOT / 'benchmarks/m60-prism-alpha-cloud-ppo.evaluation-win-intervals.json').read_text(encoding='utf-8'))
    out = {'format': 'm61-balance-ab-evaluation-result-v1', 'status': 'SYNTHETIC_REPORT_TEST',
           'measurements': measurements(), 'gates': {key: True for key in report.FLOORS},
           'arm_verdicts': {'alpha': 'PASS_RETENTION_FLOORS', 'balance': 'PASS_RETENTION_FLOORS'},
           'candidate_sha256': {'alpha': 'a' * 64, 'balance': 'b' * 64},
           'comparison': {'verdict': 'INCONCLUSIVE', 'balance_confirmed': False, 'alpha_confirmed': False}}
    for stage in ('development', 'acceptance'):
        original = source[stage]['pairs']
        cis = {(p['candidate'], p['opponent']): p['win_ci'] for p in extra['stages'][stage]}
        pairs = []
        for p in original:
            if p['opponent'] == 'base-t1':
                continue
            for model in (('base',) if p['candidate'] == 'base' else ('alpha', 'balance')):
                q = copy.deepcopy(p)
                q['win_uncertainty'] = cis[(p['candidate'], p['opponent'])]
                q['win_uncertainty'].update(seed_blocks=q['macro']['total_games'] // 2, rng_seed=61039999, resamples=20000)
                q['score_uncertainty'].update(seed_blocks=q['macro']['total_games'] // 2, rng_seed=61039999, resamples=20000)
                q['candidate'] = model
                if q['opponent'] == 'heuristic-portable-v029':
                    q['opponent'] = 'heuristic-v031'
                pairs.append(q)
        if stage == 'acceptance':
            direct = next(p for p in original if p['opponent'] == 'base-t1')
            for model, opponent in (('alpha', 'base-t1'), ('balance', 'base-t1'), ('balance', 'alpha-t1')):
                q = copy.deepcopy(direct)
                q.update(candidate=model, opponent=opponent,
                         win_uncertainty=cis[('candidate', 'base-t1')])
                q['win_uncertainty'].update(seed_blocks=q['macro']['total_games'] // 2, rng_seed=61039999, resamples=20000)
                q['score_uncertainty'].update(seed_blocks=q['macro']['total_games'] // 2, rng_seed=61039999, resamples=20000)
                pairs.append(q)
        # Force a descriptive dev/acceptance direction reversal for regression.
        for p in pairs:
            if p['candidate'] == 'balance' and p['opponent'] != 'base-t1' and p['opponent'] != 'alpha-t1':
                p['candidate_bigcard']['mean_large_card_vp_auc24'] += -.01 if stage == 'development' else .01
        out[stage] = {'games': sum(p['macro']['total_games'] for p in pairs), 'pairs': pairs}
    execution = {'evaluation': {'acceptance': {
                     'anchors': ['heuristic-v031', 'prism-v01', 'prism-general-v011'],
                     'family_alpha': .05, 'lower_quantile': .05 / 14, 'upper_quantile': 1 - .05 / 14,
                     'bootstrap_samples': 20000, 'bootstrap_rng_seed': 61039999}},
                 'candidate_sha256': {'alpha': 'a' * 64, 'balance': 'b' * 64}}
    return out, execution


class ABReportTests(unittest.TestCase):
    def test_two_directions_need_both_intervals(self):
        self.assertEqual(report.ab_verdict(measurements((.01, .04), (.51, .55))), 'CONFIRMED_BALANCE_SUPERIOR')
        self.assertEqual(report.ab_verdict(measurements((-.04, -.01), (.45, .49))), 'CONFIRMED_ALPHA_SUPERIOR')
        for pool, direct in (((.01, .04), (.48, .55)), ((-.04, -.01), (.45, .52)),
                             ((0, .04), (.51, .55)), ((-.04, 0), (.45, .49))):
            self.assertEqual(report.ab_verdict(measurements(pool, direct)), 'INCONCLUSIVE')

    def test_failures_retained_and_conflicting_verdict_rejected(self):
        result, execution = fixture()
        result['gates']['alpha/bigcard_auc24'] = False
        result['arm_verdicts']['alpha'] = 'FAIL_RETENTION_FLOORS'
        result['measurements']['alpha/bigcard_auc24'].update(simultaneous_lower=-.02)
        text = report.render_report(result, execution)
        self.assertIn('**FAIL**', text)
        self.assertIn('**INCONCLUSIVE**', text)
        result['comparison']['verdict'] = 'CONFIRMED_BALANCE_SUPERIOR'
        with self.assertRaisesRegex(ValueError, 'verdict disagrees'):
            report.render_report(result, execution)

    def test_full_tables_identity_and_opposite_directions(self):
        result, execution = fixture()
        old = report.tables.DISPLAY, report.trajectories.DISPLAY
        text = report.render_report(result, execution)
        self.assertEqual(old, (report.tables.DISPLAY, report.trajectories.DISPLAY))
        for required in ('未发布最终 c4', 'Prism Alpha v0.1.3', 'Heuristic v0.3.1',
                         '通用 Prism v0.1.1', '方向相反；完整保留', '先手 P0', '后手 P1',
                         '局均购入 0 VP卡', '局均购入 5 VP卡', '预留买回 / 获取', '局均 黑 折扣',
                         '选贵族 次数', '跳过 次数', 'NOT_MEASURED / NOT_MEASURED',
                         '0.05/(2×7)', '开发评测（仅描述）', '独立验收'):
            self.assertIn(required, text)
        self.assertNotIn('Prism Alpha v0.1.4', text)
        self.assertNotIn('便携 Heuristic v0.2.9', text)
        self.assertEqual(text.count('：完整双方数据'), 8)

    def test_missing_paired_ci_fails(self):
        result, execution = fixture()
        del result['acceptance']['pairs'][0]['win_uncertainty']
        with self.assertRaisesRegex(ValueError, 'missing paired pure-win CI'):
            report.render_report(result, execution)

    def test_cli_evidence_binding_and_single_output(self):
        result, execution = fixture()
        with tempfile.TemporaryDirectory() as name:
            work = Path(name)
            config_path = work / 'm61-prism-alpha-balance-ab.config.json'
            config_path.write_text('{"status":"SYNTHETIC_TEST_ONLY"}', encoding='utf-8')
            execution['config_sha256'] = result['config_sha256'] = report.sha(config_path)
            audit_path = work / 'audit.json'
            audit_path.write_text(json.dumps({'status': 'PASS_TRAINING_ARTIFACT_AUDIT',
                'arms': {arm: {'candidate_sha256': value} for arm, value in execution['candidate_sha256'].items()}}), encoding='utf-8')
            execution.update(audit_path=str(audit_path), audit_sha256=report.sha(audit_path))
            execution['files'] = {str(config_path): report.sha(config_path), str(audit_path): report.sha(audit_path)}
            for source in (Path(report.__file__), Path(report.tables.__file__), Path(report.trajectories.__file__)):
                execution['files'][str(source.resolve())] = report.sha(source)
            for stage in ('development', 'acceptance'):
                (work / stage).mkdir()
                shards = []
                for index, pair in enumerate(result[stage]['pairs']):
                    path = work / stage / f'config-{index}.json'
                    def descriptor(name):
                        return {'program': 'synthetic-test-engine', 'sha256': 'c' * 64,
                                'args': ['synthetic-test', name], 'files': []}
                    cfg = {'candidates': {pair['candidate']: descriptor(pair['candidate'])},
                           'opponents': {pair['opponent']: descriptor(pair['opponent'])},
                           'seeds': list(range(pair['macro']['total_games'] // 2))}
                    path.write_text(json.dumps(cfg), encoding='utf-8')
                    shards.append({'config': str(path), 'config_sha256': report.sha(path)})
                    execution['files'][str(path)] = report.sha(path)
                (work / stage / 'plan.json').write_text(json.dumps({'shards': shards}), encoding='utf-8')
                for filename, key in (('plan.json', 'plan_sha256'), ('source-ledger.json', 'source_ledger_sha256'),
                                      ('style-metrics.json', 'style_metrics_sha256'), ('match-details.json', 'match_details_sha256')):
                    path = work / stage / filename
                    if filename != 'plan.json':
                        path.write_text('{}', encoding='utf-8')
                    result[stage][key] = report.sha(path)
            (work / 'execution.json').write_text(json.dumps(execution), encoding='utf-8')
            result['execution_sha256'] = report.sha(work / 'execution.json')
            (work / 'result.json').write_text(json.dumps(result), encoding='utf-8')
            before = {p: report.sha(p) for p in work.rglob('*.json')}
            output = work / 'report.md'
            report.report(work, output)
            self.assertEqual(before, {p: report.sha(p) for p in work.rglob('*.json')})
            self.assertTrue(output.is_file())
            (work / 'acceptance/match-details.json').write_text('{"drift":true}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'drift'):
                report.report(work, output)


if __name__ == '__main__':
    unittest.main()
