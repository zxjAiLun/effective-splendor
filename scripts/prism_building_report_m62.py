"""Read-only complete M62 Markdown report; no games, training or model release.

All rendering helpers are imported from frozen M61 sources with a restored
context. Literal execution, raw audit receipts and all stage evidence are checked
before a new, non-overwriting report destination is written.
"""
import argparse
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_balance_ab_report_m61 as legacy
from scripts import prism_building_evaluation_m62 as evaluation

tables, trajectories = legacy.tables, legacy.trajectories
read, sha, require = evaluation.read, evaluation.sha, evaluation.require
DISPLAY = evaluation.DISPLAY
pct, fmt, interval, change = legacy.pct, legacy.fmt, legacy.interval, legacy.change
PROVENANCE = legacy.provenance_table
MEASURES = {
    'control/strength_pool': ('control参照总体保留', '相对Prism Balance v0.1.0半平得分率差', True, '未能排除参照总体退步超过5个百分点'),
    'control/direct_parent': ('control对父竞争力', 'control对Prism Balance v0.1.0半平得分率', True, '未能确认参照对父得分率至少45%'),
    'beta/strength_pool': ('Beta总体代价控制', 'Beta相对control共同锚点半平得分率差', True, '未能排除Beta相对control退步超过5个百分点'),
    'beta/general_anchor': ('关键通用锚点保护', 'Beta相对control对Prism v0.1.1半平得分率差', True, '未能排除关键对手退步超过7.5个百分点'),
    'beta/direct_control': ('同轮直接竞争力', 'Beta对control半平得分率', True, '未能确认Beta对control得分率至少45%'),
    'beta/direct_alpha': ('大牌路线竞争力', 'Beta对Prism Alpha v0.1.4半平得分率', True, '未能确认Beta对固定Alpha得分率至少45%'),
    'beta/direct_parent': ('防共同退化', 'Beta对Prism Balance v0.1.0半平得分率', True, '未能确认Beta对父得分率至少45%'),
    'beta/building_utility': ('真实早期投资使用信号', 'Beta相对control归一化效用差（0..1）', False, '未能确认归一化效用实质差异至少0.015'),
    'beta/early_bonus_auc12': ('非reward早期bonus风格信号', 'Beta相对control前12Main平均永久折扣差（个）', False, '未能确认非reward指标实质差异至少0.25折扣'),
}
COMPARISON_METRICS = (
    ('半平得分率', '%，模型本人', lambda p: p['candidate_metrics']['score_rate'], True),
    ('building效用', '归一化0..1，模型本人', lambda p: p['candidate_building']['mean_building_utility'], False),
    ('早期bonus AUC12', '永久折扣个数，模型本人', lambda p: p['candidate_building']['mean_early_bonus_auc12'], False),
    ('终局VP', 'VP/局，模型本人', lambda p: p['candidate_metrics']['mean_prestige'], False),
    ('自身Main得分速度', 'VP/Main，模型本人', lambda p: p['candidate_metrics']['vp_per_main_action'], False),
    ('永久折扣', '个/局，模型本人', lambda p: p['candidate_metrics']['mean_permanent_bonuses'], False),
    ('贵族', '个/局，模型本人', lambda p: p['candidate_metrics']['mean_nobles'], False),
    ('终局未买回预留', '张/局，模型本人', lambda p: p['candidate_metrics']['mean_reserves_stranded'], False),
    ('Main25..32真实购卡分', '印刷VP/局，模型本人；全局含早败', lambda p: p['candidate_building']['mean_late_scoring_vp_main25to32'], False),
)


def validate_measurements(result):
    if not result.get('measurements'):
        require(not isinstance(result.get('acceptance'), dict), 'completed acceptance missing nine formal measurements')
        return
    require(set(result['measurements']) == set(result['gates']) == set(evaluation.GATES), 'expected exact frozen nine claims')
    for key, measurement in result['measurements'].items():
        values = [measurement['mean'], measurement['simultaneous_one_sided_lower'], *measurement['ci95']]
        require(len(measurement['ci95']) == 2 and all(type(x) in (int, float) and math.isfinite(x) for x in values), 'nonfinite measurement')
        require(measurement['ci95'][0] <= measurement['ci95'][1], 'reversed descriptive CI')
        require(result['gates'][key] is (measurement['simultaneous_one_sided_lower'] >= evaluation.GATES[key]), 'gate/lower bound disagreement: ' + key)
        require(measurement['seed_blocks'] == (512 if '/direct_' in key else 256) and
                measurement['bootstrap_rng_seed'] == evaluation.BOOTSTRAP_SEED and
                measurement['bootstrap_samples'] == 20000 and measurement['lower_quantile'] == evaluation.LOWER_Q,
                'formal bootstrap provenance drift')
    require(result['verdicts'] == evaluation.verdicts(result['measurements'], result['gates']), 'acceptance/enhancement verdict disagreement')


def gate_table(result):
    rows = []
    for key, (purpose, unit, percent, failure) in MEASURES.items():
        threshold = evaluation.GATES[key]; measurement = (result.get('measurements') or {}).get(key)
        if measurement:
            formatter = pct if percent else fmt
            cells = [formatter(measurement['mean']), interval(measurement['ci95'], percent),
                     formatter(measurement['simultaneous_one_sided_lower']), '**PASS**' if result['gates'][key] else '**FAIL**']
        else: cells = ['NOT_RUN'] * 4
        rows.append([key, purpose, unit, f'校正下界 ≥ {threshold:g}', *cells, failure])
    return tables.table(['门', '目的', '本人指标 / 单位（得分差为百分点）', '冻结阈值', '估计',
                         '普通配对95% CI', '九项同时单侧下界', '原判定', '失败含义'], rows)


def comparison_tables(record):
    keyed = legacy.keyed_pairs(record); rows = []
    for label, unit, getter, percent in COMPARISON_METRICS:
        values = [math.fsum(getter(keyed[(model, op)]) for op in evaluation.ANCHORS) / 3 for model in evaluation.MODELS]
        a, b, c = values; formatter = pct if percent else fmt
        rows.append([label, unit, *map(formatter, values), change(a, b, percent), change(b, c, percent), change(a, c, percent)])
    return tables.table(['共同锚点等权平均', '单位/归属', DISPLAY['base'], DISPLAY['control'], DISPLAY['beta'],
                         'control − 父', 'Beta − control', 'Beta − 父'], rows)


def building_tables(pairs):
    headers = ['个人指标（被测模型 / 对手）'] + [DISPLAY[p['candidate']] + ' 对阵 ' + DISPLAY[p['opponent']] for p in pairs]
    metrics = [('building效用（归一化0..1，reward代理）', 'mean_building_utility'),
        ('早期bonus AUC12（原始永久折扣个数；非reward）', 'mean_early_bonus_auc12'),
        ('真实折扣适用使用单位 / 局（全局cap24）', 'mean_building_use_units'),
        ('cap3/投资后、全局cap前使用单位 / 局', 'mean_building_use_units_before_global_cap'),
        ('未截断真实折扣使用单位 / 局', 'mean_building_observed_use_units'),
        ('前12Main真实购卡 / 局', 'mean_early_buys'), ('早期≤1VP投资 / 局', 'mean_early_lowvp_buys'),
        ('兑现投资 / 局', 'mean_redeemed_investments'), ('未兑现投资 / 局', 'mean_unredeemed_investments'),
        ('观察窗口删失投资 / 局', 'mean_censored_investments'), ('未兑现且删失投资 / 局', 'mean_unredeemed_censored_investments'),
        ('Main13..24真实购卡印刷VP / 局', 'mean_late_vp_bought_main13to24'),
        ('Main13..24真实观察Main / 局', 'mean_observed_main13to24'),
        ('Main25..32真实得分购卡印刷VP / 局', 'mean_late_scoring_vp_main25to32'),
        ('Main25..32真实观察Main / 局', 'mean_observed_main25to32'),
        ('Main25..32印刷VP / 真实观察Main（总分母）', 'late_scoring_vp_per_observed_main25to32')]
    rows = [[label] + [' / '.join('NOT_APPLICABLE' if p[side][key] is None else fmt(p[side][key])
                    for side in ('candidate_building', 'opponent_building')) for p in pairs] for label, key in metrics]
    for label, key in [('投资兑现 / 投资总数', 'investment_redemption_rate'), ('未兑现 / 投资总数', 'investment_unredeemed_rate'),
                       ('删失 / 投资总数', 'investment_censored_rate'), ('短于12Main对局比例', 'short_game_fraction'),
                       ('未达24Main对局比例', 'redemption_horizon_censored_fraction'),
                       ('未达32Main对局比例', 'late_scoring_main25to32_censored_fraction')]:
        rows.append([label] + [' / '.join('NOT_APPLICABLE' if p[side][key] is None else pct(p[side][key])
                    for side in ('candidate_building', 'opponent_building')) for p in pairs])
    return tables.table(headers, rows) + '\n\n每格是被测模型 / 对手，包含全部对局、早败和未兑现投资。奖励不padding；AUC12短局终局折扣保持仅作描述。'


def detailed_match_tables(record):
    out = []
    with legacy.helper_display(DISPLAY):
        for opponent in dict.fromkeys(p['opponent'] for p in record['pairs']):
            pairs = [p for p in record['pairs'] if p['opponent'] == opponent]
            body = tables.detailed_tables(pairs, DISPLAY[opponent] + '：完整双方数据')
            body = body.replace('Rush AUC', '总VP AUC24').replace('短于16自身Main', '短于24自身Main')
            body = body.replace('风格两项之外的经济数据为新增描述性指标。', '本表总VP/大牌轨迹是描述性指标；M62九门使用独立building画像。')
            trajectory = trajectories.trajectory_tables(pairs).replace('（训练效用）', '（描述性；非M62奖励）').replace('（风格底线）', '（描述性；非M62门）')
            out.extend([body, trajectory, '### 基建投资与后续兑现（双方完整画像）', building_tables(pairs)])
            seat_pairs = []
            for pair in pairs:
                for seat in pair['seats']:
                    seat_pairs.append(dict(candidate=pair['candidate'], opponent=pair['opponent'],
                        candidate_building=seat['candidate_building'], opponent_building=seat['opponent_building']))
            # Full economy/actions already have both model identities; additionally
            # show each seat's building signal without treating physical P0 as Beta.
            rows = [[DISPLAY[p['candidate']], DISPLAY[p['opponent']], '先手 P0' if s['candidate_seat'] == 0 else '后手 P1',
                     s['candidate']['games'], *[' / '.join(fmt(s[side][key]) for side in ('candidate_building', 'opponent_building'))
                                               for key in ('mean_building_utility', 'mean_early_bonus_auc12')]]
                    for p in pairs for s in p['seats']]
            out.append(tables.table(['被测玩家', '对手', '本模型物理座位', '局数', '效用（模型/对手）', 'AUC12折扣（模型/对手）'], rows))
    return '\n\n'.join(out)


def validate_stage(record, stage):
    keys = legacy.keyed_pairs(record)
    expected = {(m, op) for m in evaluation.MODELS for op in evaluation.ANCHORS}
    if stage == 'acceptance': expected |= set(evaluation.DIRECT_PAIRS)
    require(set(keys) == expected and record['games'] == (576 if stage == 'development' else 8704), 'stage pair/full count mismatch')
    for key, pair in keys.items():
        n = (1024 if key in evaluation.DIRECT_PAIRS else 512) if stage == 'acceptance' else 64
        require(pair['macro']['total_games'] == n, 'pair count mismatch')
        for name in ('win_uncertainty', 'score_uncertainty'):
            ci = pair[name]
            require(ci['seed_blocks'] == n // 2 and ci['rng_seed'] == evaluation.BOOTSTRAP_SEED and ci['resamples'] == 20000,
                    'descriptive CI provenance drift')
        for side in ('candidate_metrics', 'opponent_metrics'):
            m = pair[side]
            require(m['games'] == n and sum(m[k] for k in ('wins', 'ties', 'losses')) == n, 'player outcome conservation')
            require(math.isclose(m['score_rate'], (m['wins'] + .5 * m['ties']) / n), 'player half-draw mismatch')
            require(math.isclose(m['win_rate_percent'], 100 * m['wins'] / n), 'player pure win mismatch')
            require(set(m['action_distribution']) == set(m['action_percentages']) == set(evaluation.alpha.details.ACTIONS), 'missing seven action counts/shares')
            total = sum(m['action_distribution'].values())
            require(total == m['total_actor_decisions'] and total - m['action_distribution']['choose_noble'] == m['total_main_actions'], 'action denominator drift')
            for action, count in m['action_distribution'].items():
                require(math.isclose(m['action_percentages'][action], 100 * count / total), 'action share drift')
            require(set(m['mean_cards_by_vp']) == set(map(str, range(6))) and
                    set(m['mean_bonuses_by_color']) == set(evaluation.alpha.details.COLORS), 'card/colour coverage drift')
        a, b = pair['candidate_metrics'], pair['opponent_metrics']
        require((a['wins'], a['ties'], a['losses']) == (b['losses'], b['ties'], b['wins']), 'both-player outcome mismatch')
        require({s['candidate_seat'] for s in pair['seats']} == {0, 1} and len(pair['seats']) == 2, 'physical seats missing')
        for side in ('candidate_building', 'opponent_building'):
            require(pair[side]['games'] == n and all(s[side]['games'] == n // 2 for s in pair['seats']), 'building coverage drift')


def direction_table(result):
    if not all(isinstance(result.get(s), dict) for s in ('development', 'acceptance')): return 'NOT_RUN'
    keyed = [legacy.keyed_pairs(result[s]) for s in ('development', 'acceptance')]; rows = []
    for label, unit, getter, percent in COMPARISON_METRICS:
        for before, after in (('base', 'control'), ('control', 'beta')):
            values = [math.fsum(getter(p[(after, op)]) - getter(p[(before, op)]) for op in evaluation.ANCHORS) / 3 for p in keyed]
            rows.append([DISPLAY[after] + ' − ' + DISPLAY[before], label, unit, *[change(0, x, percent) for x in values],
                         '**方向相反；原数据保留**' if values[0] * values[1] < 0 else '同向/零变化；不合并样本'])
    return tables.table(['本人匹配变化', '指标', '单位', '开发（描述）', '独立验收', '方向解释'], rows)


def render_report(result, execution, source_rows=()):
    require(result['format'] == 'm62-building-evaluation-result-v1', 'wrong M62 result format')
    evaluation.validate_policy(execution['evaluation']); validate_measurements(result)
    measured = bool(result.get('measurements')); verdict = result.get('verdicts', {})
    artifact = '最终c4是未发布训练候选：Prism Balance v0.1.1 candidate / Prism Beta v0.1.0 candidate；父版Prism Balance v0.1.0和固定Prism Alpha v0.1.4身份另列。'
    competitive = (PROVENANCE({k: verdict[k] for k in ('control_retention', 'beta_seven_gates', 'cohort_qualified', 'beta_acceptance')}) if measured else 'NOT_RUN')
    style = verdict.get('beta_style', 'NOT_RUN')
    out = ['# M62 Prism Beta v0.1.0 candidate / Prism Balance v0.1.1 candidate 固定评测报告',
           '**产物：**' + artifact + '审计有效性不由比赛胜率替代；候选版本名不自动表示发布/部署。',
           '**竞技：**\n\n' + competitive,
           '**风格：**' + style + '；效用差≥0.015与非reward早期bonus AUC12差≥0.25折扣必须同时通过校正下界。',
           '## 匹配共同锚点：父 → control → Beta']
    latest = 'acceptance' if isinstance(result.get('acceptance'), dict) else 'development'
    if isinstance(result.get(latest), dict):
        out.extend([('独立验收' if latest == 'acceptance' else '开发描述') + '数据；所有个人指标按模型身份合并双座。', comparison_tables(result[latest])])
    else: out.append('NOT_RUN；不填零。')
    out.extend(['箭头仅为方向，不代表更好或显著。比例取总计数/总分母；共同锚点等权描述，direct单列。',
        '## 九项采样前冻结门', gate_table(result),
        'family α=0.05，**9项单侧同时下界，q=0.05/9**，20,000次配对双座seed块bootstrap，RNG62049999。'
        '共同锚点先在每个匹配seed块平均三锚点×双座；相同长度向量共享抽样索引。control须自身2门通过；Beta须7门通过且control参照合格。'
        '保留门通过不证明总体更强，也不证明等效。增强证据另按同一校正下界>0（得分差）或>.5（direct）记录；风格实质阈值仍为原门。'
        '全部9,280局完成后只做一次formal分析；0retry/0resume/不偷看/不扩样本/不挑checkpoint，失败候选与原门完整保留。',
        '## 开发与独立方向', direction_table(result)])
    if measured: out.extend(['## 原验收与增强记录', PROVENANCE(verdict)])
    for stage, title in (('development', '开发评测（仅描述）'), ('acceptance', '独立验收')):
        out.append('## ' + title); record = result.get(stage)
        if not isinstance(record, dict): out.append('NOT_RUN；不从开发推断验收。'); continue
        validate_stage(record, stage)
        out.extend([legacy.stage_summary(record, DISPLAY), detailed_match_tables(record),
            '单局时钟含启动、比赛、验证和输出；累计单局秒含并行重叠。legacy决策轮=ceil(全plies/2)，Main排除choose_noble。'
            '每组纯胜/半平CI仅描述，不增加否决门；逐决策 / 推理 **NOT_MEASURED / NOT_MEASURED**。',
            PROVENANCE({k: v for k, v in record.items() if k != 'pairs'})])
    out.extend(['## 时钟、负载和资源', PROVENANCE({k: v for k, v in result.items() if k not in
        ('development', 'acceptance', 'measurements', 'gates', 'verdicts')}),
        '评测服务8GiB/CPU200%/2workers/8h/40,000CPU-s/32GiB。资源账与训练各臂分开；缺失延迟NOT_MEASURED。',
        '## 冻结身份、源码和执行合同', PROVENANCE(execution),
        'Heuristic v0.3.1为策略身份；Hello 0.2.9为协议常量。Prism runtime Hello不替代权重SHA。新projection只读重演保存回放，'
        '独立工具源码/binary分别pin，不将其身份伪称为旧arena。M61原合同、失败与报告保持其历史判定。',
        '## 输入与报告来源', tables.table(['证据', '路径 / SHA256'], source_rows),
        '## 静态策略面板与限制', '固定同局面概率面板：NOT_RUN；可选诊断不增加比赛或新门。'
        '折扣适用使用是结构性代理，不能解释为反事实token节省。单训练RNG/有限固定对手/最终c4限制外推；'
        '未兑现与短局全部计入。风格可在声明竞技容忍内取舍，不要求所有经济指标改善。'])
    return '\n\n'.join(out) + '\n'


def verified_provenance(work, result, execution):
    evaluation.verify(work, execution)
    require(result['candidate_sha256'] == execution['candidate_sha256'] and result['config_sha256'] == execution['config_sha256'], 'result frozen identity drift')
    pilot, _, hashes = evaluation.bindings(work.parent, execution['config_sha256'], Path(execution['audit_path']))
    require(hashes == result['candidate_sha256'], 'audited final-c4 drift')
    require(sha(execution['audit_path']) == execution['audit_sha256'], 'audit binding drift')
    out = ['## 原训练合同与raw审计回执', PROVENANCE(pilot), PROVENANCE(read(execution['audit_path']))]
    descriptors, seed_rows = {}, []
    for stage in ('development', 'acceptance'):
        record = result.get(stage)
        if not isinstance(record, dict): continue
        coverage = {}
        for shard in read(work / stage / 'plan.json')['shards']:
            cfg = read(shard['config'])
            for category in ('candidates', 'opponents'):
                for name, descriptor in cfg[category].items():
                    if name in descriptors: require(descriptors[name] == descriptor, 'participant command drift')
                    descriptors[name] = descriptor
            for m in cfg['candidates']:
                for op in cfg['opponents']:
                    keys = coverage.setdefault((m, op), set()); new = {(s, seat) for s in cfg['seeds'] for seat in (0, 1)}
                    require(not keys.intersection(new), 'duplicate seed/seat'); keys.update(new)
        require(set(coverage) == set(legacy.keyed_pairs(record)), 'report pair/shard mismatch')
        for pair in record['pairs']:
            seeds = coverage[(pair['candidate'], pair['opponent'])]; values = sorted({s for s, _ in seeds})
            require(len(seeds) == pair['macro']['total_games'], 'report seed count mismatch')
            seed_rows.append([stage, DISPLAY[pair['candidate']], DISPLAY[pair['opponent']], f'{values[0]}..{values[-1]}', len(values), 'P0/P1'])
    out.extend(['## 字面模型启动命令', tables.table(['模型/模式', '字面argv', 'native SHA256', 'weights路径/SHA256'],
        [[DISPLAY[name], ' '.join([d['program'], *d['args']]), d['sha256'],
          '; '.join(f"{asset['path']} / {asset['sha256']}" for asset in d['files']) or '固定源码启发式'] for name, d in descriptors.items()]),
        '## 原固定种子与物理座位', tables.table(['阶段', '本人模型', '对手', '环境seed范围', '双座块数', '物理座位'], seed_rows)])
    return '\n\n'.join(out)


def report(work, output):
    work, output = Path(work).resolve(), Path(output).resolve()
    require(output.suffix.lower() == '.md' and not output.exists(), 'new Markdown output required; refuse overwrite')
    require(not output.is_relative_to(work), 'report destination cannot overwrite evaluation evidence')
    result, execution = read(work / 'result.json'), read(work / 'execution.json')
    require(sha(work / 'execution.json') == result['execution_sha256'], 'execution receipt drift')
    rows = [[name, f'{work / name} / {sha(work / name)}'] for name in ('result.json', 'execution.json')]
    rows.append(['report source', f'{Path(__file__).resolve()} / {sha(__file__)}'])
    for stage in ('development', 'acceptance'):
        if not isinstance(result.get(stage), dict): continue
        for name in ('plan', 'source-ledger', 'style-metrics', 'building-metrics', 'match-details'):
            path = work / stage / (name + '.json'); digest = result[stage][name.replace('-', '_') + '_sha256']
            require(sha(path) == digest, 'stage evidence drift: ' + str(path)); rows.append([stage + '/' + name, f'{path} / {digest}'])
            if name == 'match-details': require(read(path)['pairs'] == result[stage]['pairs'], 'result/pair evidence disagreement')
    provenance = verified_provenance(work, result, execution)
    text = render_report(result, execution, rows) + '\n' + provenance + '\n'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream: stream.write(text)
    print('PASS: read-only M62 report; zero games; sha256=' + sha(output))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); report(args.work, args.output)


if __name__ == '__main__': main()
