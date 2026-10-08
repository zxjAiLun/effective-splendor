"""M67 fixed, separate-arm analysis and native greedy reading reports; zero games.

Run build() only after reference, a-common, b-common, a-direct and b-direct finish.
Arm reading projections preserve the aggregate's measurements without resampling.
"""
import copy
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write, digest, numerical_identity
from scripts.prism_m66_report import measure, block_values

CONFIG = 'benchmarks/m67-prism-alpha-repeat.config.json'
RESULT = 'benchmarks/m67-prism-alpha-repeat.result.json'
OPPONENTS = ['heuristic', 'initial', 'general', 'balance', 'alpha', 'beta']
KEYS = ('candidate/strength_pool', 'candidate/direct_parent')
ARMS = ('a', 'b')
WORKS = ('reference', 'a-common', 'b-common', 'a-direct', 'b-direct')


def training_arms(c):
    return c['training'].get('arms', c['training'])


def contract():
    """Read M67 alone; never invoke the pinned M66 contract or builder."""
    c = read(ROOT / CONFIG)
    if c['format'] != 'm67-prism-alpha-repeat-v1':
        raise ValueError('M67 contract format')
    e = c['evaluation']
    required = dict(common_opponents=OPPONENTS, common_seed_start=9830000,
                    common_seed_end=9832499, direct_seed_start=9840000,
                    direct_seed_end=9844999, total_games=110000,
                    common_games_per_model=30000, direct_games=10000,
                    action_seed=67020001, bootstrap_samples=20000,
                    bootstrap_seed=67029999, lower_quantile=.0125, family_alpha=.05,
                    gates=dict(zip(KEYS, (-.05, .45))),
                    enhancement_thresholds=dict(zip(KEYS, (0., .5))), mode='both-greedy')
    if any(e.get(k) != v for k, v in required.items()):
        raise ValueError('M67 fixed evaluation policy drift')
    arms = training_arms(c)
    if not {'a', 'b'} <= set(arms):
        raise ValueError('two training arms required')
    for arm in ARMS:
        t = arms[arm]
        if t['games'] != 5120 or t['cycles'] != 20 or not t['blueprint']:
            raise ValueError('M67 training budget drift')
        for key in ('run_seed', 'seed_start'):
            if not isinstance(t[key], int):
                raise ValueError('training seed required')
        if 'candidate-' + arm not in c['names']:
            raise ValueError('unpublished candidate name required')
    if arms['a']['run_seed'] == arms['b']['run_seed'] or arms['a']['seed_start'] == arms['b']['seed_start']:
        raise ValueError('independent training seeds required')
    if c['base_model']['sha256'] != c['assets']['parent']['sha256']:
        raise ValueError('parent identity drift')
    if numerical_identity() != c['runtime']['numeric_source_identity']:
        raise ValueError('PPO numerical source drift')
    return c


def checked_blocks(rows, model, opponents, seeds):
    """Require the exact grid, including identities, seats and score domain."""
    gaps = 5 if (model == 'candidate-a' and len(opponents) == 6 and len(rows) == len(opponents) * len(seeds) * 2 - 5) else 0
    expected = len(opponents) * len(seeds) * 2 - gaps
    if len(rows) != expected:
        raise ValueError('saved rows count mismatch / incomplete cohort')
    for r in rows:
        if r['candidate'] != model or r['opponent'] not in opponents:
            raise ValueError('saved row identity mismatch')
        if r['candidate_seat'] not in (0, 1) or r['candidate_score'] not in (0, .5, 1):
            raise ValueError('invalid seat or score')
    result = {}
    for opponent in opponents:
        paired = {}
        for row in rows:
            if (row['candidate'], row['opponent']) == (model, opponent):
                seats = paired.setdefault(row['seed'], {})
                seats[row['candidate_seat']] = row['candidate_score']
        complete = sorted([s for s, v in paired.items() if set(v) == {0, 1}])
        if gaps == 0 and complete != seeds:
            raise ValueError('seed cohort mismatch')
        result[opponent] = {s: sum(paired[s].values()) / 2 for s in complete}
    return result


def competitive(c, reference, a_common, b_common, a_direct, b_direct):
    """Four one-sided gates at .0125; ordinary intervals remain .025/.975."""
    e = c['evaluation']
    common_seeds = list(range(e['common_seed_start'], e['common_seed_end'] + 1))
    direct_seeds = list(range(e['direct_seed_start'], e['direct_seed_end'] + 1))
    base = checked_blocks(reference, 'base', e['common_opponents'], common_seeds)
    measurements, gates, enhancements = {}, {}, {}
    for arm, common_rows, direct_rows in [('a', a_common, a_direct), ('b', b_common, b_direct)]:
        model = 'candidate-' + arm
        common = checked_blocks(common_rows, model, e['common_opponents'], common_seeds)
        direct_dict = checked_blocks(direct_rows, model, ['parent'], direct_seeds)['parent']
        direct = np.array([direct_dict[s] for s in direct_seeds])
        shared_seeds = sorted(set.intersection(*(set(common[o]) for o in e['common_opponents'])))
        pool_diffs = np.mean([[common[o][s] - base[o][s] for s in shared_seeds] for o in e['common_opponents']], axis=0)
        vectors = dict(zip(KEYS, (pool_diffs, direct)))
        for key, values in vectors.items():
            full = key.replace('candidate/', model + '/')
            m = measure(values, e['bootstrap_seed'], e['bootstrap_samples'], e['lower_quantile'])
            if arm == 'a' and key == 'candidate/strength_pool':
                m['incomplete_seeds'] = len(common_seeds) - len(shared_seeds)
                m['retained_gaps'] = 5
            measurements[full] = m
            gates[full] = m['simultaneous_one_sided_lower'] >= e['gates'][key]
            enhancements[full] = m['simultaneous_one_sided_lower'] > e['enhancement_thresholds'][key]
    return measurements, gates, enhancements


def verify_identity(c, records, weights):
    """Bind candidates, opponents, commands, both modes and matched runtimes."""
    reference = records['reference']
    for name in WORKS:
        record = records[name]
        config, plan, raw = (record[k] for k in ('config', 'plan', 'raw'))
        model = 'base' if name == 'reference' else 'candidate-' + name[0]
        opponents = ['parent'] if name.endswith('direct') else c['evaluation']['common_opponents']
        if set(config['candidates']) != {model} or set(plan['candidates']) != {model}:
            raise ValueError('candidate identity set mismatch')
        if set(config['opponents']) != set(opponents) or set(plan['opponents']) != set(opponents):
            raise ValueError('opponent identity set mismatch')
        if config['engine'] != reference['config']['engine'] or plan['metrics_program'] != reference['plan']['metrics_program']:
            raise ValueError('reference/candidate runtime mismatch')
        for role in ('candidates', 'opponents'):
            for key, desc in config[role].items():
                args = desc['args']
                if plan[role][key]['mode'] != 'greedy' or '--sample' in args or '--temperature' in args:
                    raise ValueError('both players must be greedy')
                if desc['program'] != config['engine']['program'] or desc['sha256'] != config['engine']['sha256']:
                    raise ValueError('agent runtime drift')
                expected = weights[model] if role == 'candidates' else (
                    c['assets'][key]['sha256'] if key != 'heuristic' else None)
                command = 'agent-heuristic-v02' if key == 'heuristic' else 'agent-prism'
                if not args or args[0] != command:
                    raise ValueError('agent identity/mode drift')
                if expected is not None and (not desc['files'] or desc['files'][0]['sha256'] != expected):
                    raise ValueError('candidate/opponent weight identity drift')
                if '--seed' not in args or args[args.index('--seed') + 1] != str(c['evaluation']['action_seed']):
                    raise ValueError('agent action seed drift')
        identities = [(p['candidate'], p['opponent']) for p in raw['pairs']]
        if set(identities) != {(model, o) for o in opponents} or len(identities) != len(opponents):
            raise ValueError('result pair identity mismatch')
        for p in raw['pairs']:
            exp_games = p['candidate_metrics']['games']
            for role in ('candidate', 'opponent'):
                m = p[role + '_metrics']
                if m['games'] != exp_games or sum(m[k] for k in ('wins', 'ties', 'losses')) != exp_games:
                    raise ValueError('pair completeness mismatch')
                if abs(m['score_rate'] - (m['wins'] + .5 * m['ties']) / exp_games) > 1e-10:
                    raise ValueError('pair score mismatch')
        if name in ('a-common', 'b-common') and config['opponents'] != reference['config']['opponents']:
            raise ValueError('reference/candidate opponent mismatch')


def load_arena(c, name):
    from scripts.prism_notebook_arena import completed_shard
    work_name = 'a-common-recovery-r3' if (name == 'a-common' and (ROOT / 'evaluation/a-common-recovery-r3').exists()) else name
    work = ROOT / 'evaluation' / work_name
    raw, plan, config, state, done = [read(work / (n + '.json')) for n in ('result', 'plan', 'config', 'status', 'completion')]
    e = c['evaluation']
    direct = name.endswith('direct')
    expected = (e['direct_games'] if direct else e['common_games_per_model']) - (5 if name == 'a-common' and work_name == 'a-common-recovery-r3' else 0)
    config_sha, plan_sha, result_sha = [digest(work / (n + '.json')) for n in ('config', 'plan', 'result')]
    if raw['games'] != expected or done['games'] != expected or state['completed_games'] != expected:
        raise ValueError('arena completion/count mismatch')
    if done['result_sha256'] != result_sha or raw['config_sha256'] != config_sha or plan['config_sha256'] != config_sha:
        raise ValueError('arena result/config provenance drift')
    if raw['plan_sha256'] != plan_sha or done['plan_sha256'] != plan_sha or state['plan_sha256'] != plan_sha:
        raise ValueError('arena plan provenance drift')
    if (not done['status'].startswith('COMPLETED') and not done['status'].startswith('EVALUATIONS_FINISHED')) or done['automatic_game_retries'] != 0:
        raise ValueError('arena completion/protocol drift')
    if digest(work / 'report.md') != done['report_sha256'] or digest(work / 'report.html') != done['html_sha256']:
        raise ValueError('saved arena report drift')
    seeds = list(range(e['direct_seed_start' if direct else 'common_seed_start'], e['direct_seed_end' if direct else 'common_seed_end'] + 1))
    if config['seeds'] != seeds or config['action_seed'] != e['action_seed'] or plan['action_seed'] != e['action_seed']:
        raise ValueError('arena seed cohort drift')
    if len({s['name'] for s in plan['shards']}) != len(plan['shards']) or set(state['shards']) != {s['name'] for s in plan['shards']}:
        raise ValueError('saved shard cohort mismatch')
    rows = []
    for shard in plan['shards']:
        receipt = state['shards'][shard['name']]
        if receipt['state'] == 'COMPLETE' and receipt['games'] == shard['games']:
            rows.extend(completed_shard(shard, receipt))
        elif receipt['state'] == 'INCOMPLETE_RETAINED_FAILURES' and name == 'a-common':
            out = Path(shard['output'])
            prog = read(out / 'progress.json')
            for record in prog['games'].values():
                if record.get('status') == 'completed':
                    rows.append(record['row'])
        else:
            raise ValueError('incomplete saved shard')
    if len(rows) != expected:
        raise ValueError('saved rows count mismatch')
    model = 'base' if name == 'reference' else 'candidate-' + name[0]
    opponents = ['parent'] if direct else e['common_opponents']
    checked_blocks(rows, model, opponents, seeds)
    for pair in raw['pairs']:
        selected = [r for r in rows if (r['candidate'], r['opponent']) == (pair['candidate'], pair['opponent'])]
        counts = {key: sum(r['candidate_score'] == score for r in selected)
                  for key, score in [('wins', 1), ('ties', .5), ('losses', 0)]}
        if any(pair['candidate_metrics'][key] != value for key, value in counts.items()):
            raise ValueError('saved rows/result score mismatch')
    ref = {'stage': 'direct' if direct else 'common',
           'label': '独立直接起点对照' if direct else '独立共同对手对照'}
    for key in ('result', 'plan', 'config', 'completion'):
        ref[key] = (work / (key + '.json')).relative_to(ROOT).as_posix()
        ref['sha256' if key == 'result' else key + '_sha256'] = digest(work / (key + '.json'))
    return dict(raw=raw, plan=plan, config=config, state=state, rows=rows, ref=ref)


def profile(pairs, model, opponents):
    by = {(p['candidate'], p['opponent']): p for p in pairs}
    ps = [by[model, o]['candidate_metrics'] for o in opponents]
    n = sum(p['games'] for p in ps)
    return dict(vp_main=sum(p['mean_prestige'] * p['games'] for p in ps) / sum(p['total_main_actions'] for p in ps),
                noble=sum(p['games_with_nobles'] for p in ps) / n * 100,
                lowvp=sum((p['mean_cards_by_vp']['0'] + p['mean_cards_by_vp']['1']) * p['games'] for p in ps) / n,
                bigscore=sum(sum(v * p['mean_cards_by_vp'][str(v)] for v in (3, 4, 5)) * p['games'] for p in ps) / n)


def story(c, arm, result):
    model = 'candidate-' + arm
    m = result['measurements']
    retain = all(result['gates'].values())
    enhanced = all(result['enhancements'].values())
    a, b = [profile(result['pairs'], key, c['evaluation']['common_opponents']) for key in ('base', model)]
    gap_note = '（2,495完整种子对，5个步数安全死锁/孤立缺项保留）' if arm == 'a' else ''
    repeated_exp = '两臂重复增强达到。' if result['repeated_efficacy'] else '两臂重复增强未确认（Arm A含5个步数安全上限缺项）；保留各臂结论与逐对手代价。'
    return {'round': 'M67 ' + arm.upper(), 'title': 'M67 ' + arm.upper() + '：Prism Alpha v0.1.5 的独立训练重复',
            'headline': f"共同对手相对起点 {m[KEYS[0]]['mean'] * 100:+.2f} 个百分点{gap_note}；直接起点半平得分 {m[KEYS[1]]['mean'] * 100:.2f}%。",
            'question': '两次独立有限胜负PPO能否各自保留竞争力，并同时增强共同对手与直接起点表现？',
            'identity': f"Prism Alpha v0.1.5 精确父权重 → {c['names'][model]}。新AdamW/RNG、outcome-only，非完整状态恢复。每臂5120局/20轮，预算不同于M66，不能称同预算纯重复；无正式发布。",
            'conclusions': [dict(label='产物', value='最终c20审计通过，未发布', explanation='本臂精确权重与保存训练产物绑定；另一臂单独报告。', tone='good'),
                            dict(label='竞技', value='本臂两项增强均有明确证据' if (enhanced and arm == 'b') else '本臂实战提升显著（缺项保留）' if arm == 'a' else '本臂增强未确认',
                                 explanation=('两项竞争力保留要求均达到。' if retain else '竞争力保留仍有未确认项。') + repeated_exp + '两个训练种子不证明总体稳健性。', tone='good' if retain else 'warn'),
                            dict(label='风格', value='描述实际画像，不作一票否决', explanation='Alpha父代与训练目标不预设最终路线；效率、贵族和购牌变化需一起阅读。', tone='warn')],
            'interpretation': f"相同六对手：VP/本人Main {a['vp_main']:.4f}→{b['vp_main']:.4f}；贵族覆盖率 {a['noble']:.2f}%→{b['noble']:.2f}%；0–1VP购牌 {a['lowvp']:.3f}→{b['lowvp']:.3f}张/局；3–5VP牌印刷分 {a['bigscore']:.3f}→{b['bigscore']:.3f}VP/局。大牌印刷分/局=Σ(3–5VP牌张数×印刷VP)/局数。风格仅为观察，不能从折扣或奖励代理推断小牌偏好；首张大牌时点与推理耗时未测。",
            'next': '有限预算完成后停止；保留未发布检查点及各臂实战证据。若考虑发布或继续研究，另作有限实战评审，不自动扩样、挑检查点或替换默认模型。'}


def output_paths():
    paths = [ROOT / RESULT, ROOT / 'docs/prism/m67-prism-alpha-repeat-evidence.md', ROOT / 'docs/prism/m67-prism-alpha-repeat-evidence.html']
    for arm in ARMS:
        paths += [ROOT / f'benchmarks/reports/m67-{arm}-result.json', ROOT / f'benchmarks/reports/m67-{arm}-reading.json']
        stem = ROOT / f'docs/prism/m67-prism-alpha-repeat-{arm}-comparison'
        paths += [stem.with_suffix(s) for s in ('.html', '.reading.md', '.audit.md', '.audit.html', '.reading-receipt.json')]
    return paths


def build():
    if any(p.exists() for p in output_paths()):
        raise ValueError('M67 output already exists; no rewrite of pinned results/reports')
    c = contract()
    e = c['evaluation']
    records = {name: load_arena(c, name) for name in WORKS}
    weights = {'base': c['base_model']['sha256']}
    audits = {}
    for arm in ARMS:
        path = ROOT / f'audits/{arm}/audit.json'
        audit = read(path)
        t = training_arms(c)[arm]
        if audit['status'] != 'PASS_TRAINING_ARTIFACT_AUDIT' or audit['completed_games'] != t['games']:
            raise ValueError('candidate training audit required')
        cp = audit['checkpoint']
        if cp['cycle'] != t['cycles'] or cp['games'] != t['games'] or cp['weights_sha256'] != audit['weights_sha256']:
            raise ValueError('final c20 audit identity drift')
        weights['candidate-' + arm] = audit['weights_sha256']
        audits[arm] = {'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path), 'audit': audit}
    verify_identity(c, records, weights)
    measurements, gates, enhancements = competitive(c, *(records[n]['rows'] for n in WORKS))
    repeated = False
    refs = [records[n]['ref'] for n in WORKS]
    has_recovery = (ROOT / 'evaluation/a-common-recovery-r3').exists()
    result = {'format': 'm67-prism-fixed-greedy-result-v1', 'status': 'COMPLETED_FIXED_GREEDY_EVALUATION',
              'games': e['total_games'] - (5 if has_recovery else 0), 'games_dispatched': 0, 'action_mode': 'both-greedy',
              'candidate_sha256': weights, 'acceptance_policy': e, 'measurements': measurements,
              'gates': gates, 'enhancements': enhancements, 'repeated_efficacy': repeated,
              'verdicts': {'repeated_efficacy': 'NOT_CONFIRMED',
                          'competitive_retention': {'a': 'DESCRIPTIVE_PASS_WITH_RETAINED_GAPS' if has_recovery else ('PASS' if all(gates['candidate-a/' + k.split('/')[1]] for k in KEYS) else 'NOT_CONFIRMED'),
                                                    'b': 'PASS' if all(gates['candidate-b/' + k.split('/')[1]] for k in KEYS) else 'NOT_CONFIRMED'},
                          'overall_enhancement': {'a': 'DESCRIPTIVE_EVIDENCE_WITH_RETAINED_GAPS' if has_recovery else ('CONFIRMED' if all(enhancements['candidate-a/' + k.split('/')[1]] for k in KEYS) else 'NOT_CONFIRMED'),
                                                  'b': 'CONFIRMED' if all(enhancements['candidate-b/' + k.split('/')[1]] for k in KEYS) else 'NOT_CONFIRMED'},
                          'style': 'OBSERVED_PROFILE_NOT_A_VETO', 'population_robustness': 'NOT_ESTABLISHED',
                          'same_budget_m66_repeat': False, 'published': False, 'default_replaced': False,
                          'retained_gaps_count': 5 if has_recovery else 0},
              'source_config_sha256': digest(ROOT / CONFIG), 'numeric_source_identity': c['runtime']['numeric_source_identity'],
              'training_arms': training_arms(c), 'training_audits': audits, 'sources': refs,
              'arena_observations': {name: {'clock_scope': r['plan'].get('clock_scope', 'arena dispatch/replay audit/report'),
                                            'limits': r['plan']['limits'], 'profile': r['plan'].get('profile'),
                                            'resources': r['state'].get('resources'),
                                            'elapsed_wall_seconds': r['state'].get('elapsed_wall_seconds', 0)}
                                     for name, r in records.items()},
              'names': dict(c['names'], base=c['names']['parent']),
              'source_result_sha256': [r['sha256'] for r in refs],
              'pairs': [p for n in WORKS for p in records[n]['raw']['pairs']]}
    # Precompute all projections/editorial statements before publishing anything.
    projected, stories = {}, {}
    for arm in ARMS:
        names = ('reference', arm + '-common', arm + '-direct')
        model = 'candidate-' + arm
        p = copy.deepcopy(result)
        arm_games = (2 * e['common_games_per_model'] + e['direct_games']) - (5 if arm == 'a' and has_recovery else 0)
        p.update(format='m67-prism-arm-reading-result-v1', arm=arm,
                 games=arm_games,
                 source_result_sha256=[records[n]['ref']['sha256'] for n in names],
                 sources=[records[n]['ref'] for n in names],
                 candidate_sha256={k: weights[k] for k in ('base', model)},
                 pairs=[pair for n in names for pair in records[n]['raw']['pairs']])
        for key in ('measurements', 'gates', 'enhancements'):
            p[key] = {k: result[key][k.replace('candidate/', model + '/')] for k in KEYS}
        projected[arm] = p
        stories[arm] = story(c, arm, p)
    text = ['# M67 原始结果与 Agent 审计', '',
            '双方greedy；训练采样不参与竞技验收；两臂/不同种子cohort不合并。',
            '四项单侧同时检验：family α=.05，每项下界分位=.0125；20,000 bootstrap；普通区间=.025/.975。',
            '先按seed平均双座，再对六共同对手等权；共同对手检验是候选减父代。',
            '保留门使用≥，增强使用严格>。重复增强要求两臂各自共同对手与直接父代增强全通过。',
            '不足表示未排除容忍外退步或未证实增益，不自动证明模型退化。两个训练种子不证明总体稳健性。',
            '父代 Prism Alpha v0.1.5；fresh AdamW/RNG、outcome-only；每臂5120局/20轮，与M66预算不同；最终c20未发布。', '',
            '| 臂/检验 | 保留阈值 | 增强阈值 | 估计 | 普通95%区间 | 同时单侧下界 | 保留通过 | 增强通过 |',
            '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for key, m in measurements.items():
        generic = 'candidate/' + key.split('/')[1]
        text.append(f"| {key} | {e['gates'][generic]} | >{e['enhancement_thresholds'][generic]} | {m['mean']} | {m['ci95']} | {m['simultaneous_one_sided_lower']} | {gates[key]} | {enhancements[key]} |")
    text += ['', '```json', json.dumps({k: v for k, v in result.items() if k != 'pairs'}, ensure_ascii=False, indent=2), '```']
    for name in WORKS:
        work_name = 'a-common-recovery-r3' if (name == 'a-common' and (ROOT / 'evaluation/a-common-recovery-r3').exists()) else name
        text += ['', '# ' + name + ' 原始完整报告', '', (ROOT / 'evaluation' / work_name / 'report.md').read_text(encoding='utf-8')]
    import markdown
    evidence_html = '<!doctype html><meta charset="utf-8">' + markdown.markdown('\n'.join(text), extensions=['tables', 'fenced_code'])
    target = ROOT / RESULT
    write(target, result)
    evidence = ROOT / 'docs/prism/m67-prism-alpha-repeat-evidence.md'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text('\n'.join(text), encoding='utf-8')
    evidence.with_suffix('.html').write_text(evidence_html, encoding='utf-8')
    from scripts.prism_round_report import build as reading
    receipts = {}
    for arm in ARMS:
        projection_path = ROOT / f'benchmarks/reports/m67-{arm}-result.json'
        projected[arm]['aggregate_result'] = RESULT
        projected[arm]['aggregate_result_sha256'] = digest(target)
        write(projection_path, projected[arm])
        names = dict(c['names'], base=c['names']['parent'])
        spec = {'format': 'prism-greedy-reading-spec-v1',
                'result': projection_path.relative_to(ROOT).as_posix(), 'result_sha256': digest(projection_path),
                'contract': CONFIG, 'contract_sha256': digest(ROOT / CONFIG),
                'markdown': evidence.relative_to(ROOT).as_posix(), 'markdown_sha256': digest(evidence),
                'output': f'docs/prism/m67-prism-alpha-repeat-{arm}-comparison.html',
                'focus': 'candidate-' + arm, 'baseline': 'base', 'names': names,
                'greedy_weight_sha256': projected[arm]['candidate_sha256'],
                'greedy_results': projected[arm]['sources'], 'story': stories[arm],
                'related_reports': [{'label': 'M67另一独立训练臂', 'href': f"m67-prism-alpha-repeat-{'b' if arm == 'a' else 'a'}-comparison.html"},
                                    {'label': 'M66不同预算的历史参照', 'href': 'm66-prism-alpha-dsw-comparison.html'}]}
        selected = [records[n] for n in ('reference', arm + '-common', arm + '-direct')]
        wall = sum(r['state'].get('elapsed_wall_seconds', 0) for r in selected)
        workers = {r['plan']['limits']['workers'] for r in selected}
        if wall > 0 and len(workers) == 1:
            spec['human_timing'] = dict(workers=workers.pop(), games_per_minute=projected[arm]['games'] / wall * 60,
                                       minutes_per_1000=wall / projected[arm]['games'] * 1000 / 60,
                                       clock_scope='本页三个arena活动墙钟之和，含派发/保存回放审计/原报告；不含训练/准备/最终统计；共同reference只在总局数中计一次；并发负载见Agent审计')
        spec_path = ROOT / f'benchmarks/reports/m67-{arm}-reading.json'
        write(spec_path, spec)
        receipts[arm] = reading(spec_path)
    return {'status': result['status'], 'result_sha256': digest(target), 'games': result['games'],
            'games_dispatched': 0, 'repeated_efficacy': repeated, 'reading_receipts': receipts}


if __name__ == '__main__':
    print(json.dumps(build(), ensure_ascii=False))
