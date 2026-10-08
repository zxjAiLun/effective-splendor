"""Read-only M61 final-c4 A/B Markdown rendering; never dispatches games.

The old render helpers are reused without editing their frozen source files.
Candidate names remain unpublished checkpoint labels, independent of gate results.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_rush_report as tables
from scripts import prism_alpha_report as trajectories

DISPLAY = {
    'base': '父模型 Prism Alpha v0.1.3',
    'alpha': 'Alpha 续训（M61 未发布最终 c4，原 style）',
    'balance': 'Balance（M61 未发布最终 c4，outcome-only）',
    'base-t1': '父模型 Prism Alpha v0.1.3（T=1）',
    'alpha-t1': 'Alpha 续训（M61 未发布最终 c4，T=1）',
    'balance-t1': 'Balance（M61 未发布最终 c4，T=1）',
    'heuristic-v031': 'Heuristic v0.3.1（greedy）',
    'prism-v01': '初代 Prism v0.1.0（greedy）',
    'prism-general-v011': '通用 Prism v0.1.1（T=1）',
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def pct(value):
    return f'{value * 100:.4f}%'


def fmt(value):
    return 'NOT_MEASURED' if value is None else f'{value:.6f}'


def interval(values, percent=False):
    f = pct if percent else fmt
    return '[' + ', '.join(f(x) for x in values) + ']'


def change(a, b, percent=False):
    delta = b - a
    marker = '↑' if delta > 0 else '↓' if delta < 0 else '→'
    value = f'{delta * 100:+.4f} 个百分点' if percent else f'{delta:+.6f}'
    return f'**{marker} {value}**'


@contextmanager
def helper_display(display):
    """Restore imported helper globals so rendering does not leak model names."""
    previous = tables.DISPLAY, trajectories.DISPLAY
    tables.DISPLAY = trajectories.DISPLAY = display
    try:
        yield
    finally:
        tables.DISPLAY, trajectories.DISPLAY = previous


# These are descriptions of model-personal metrics; no additional style gate.
COMPARISON_METRICS = (
    ('半平得分率', '%，模型本人', lambda p: p['candidate_metrics']['score_rate'], True),
    ('大牌印刷 VP AUC24', '无量纲，模型本人', lambda p: p['candidate_bigcard']['mean_large_card_vp_auc24'], False),
    ('总 VP AUC24', '无量纲，模型本人', lambda p: p['candidate_bigcard']['mean_total_vp_auc24'], False),
    ('终局大牌印刷分', 'VP / 局，模型本人', lambda p: p['candidate_bigcard']['mean_terminal_large_card_printed_vp'], False),
    ('购入4 VP牌', '张 / 局，模型本人', lambda p: p['candidate_metrics']['mean_cards_by_vp']['4'], False),
    ('购入5 VP牌', '张 / 局，模型本人', lambda p: p['candidate_metrics']['mean_cards_by_vp']['5'], False),
    ('终局 VP', 'VP / 局，模型本人', lambda p: p['candidate_metrics']['mean_prestige'], False),
    ('自身 Main 得分速度', 'VP / Main，模型本人', lambda p: p['candidate_metrics']['vp_per_main_action'], False),
    ('永久折扣', '个 / 局，模型本人', lambda p: p['candidate_metrics']['mean_permanent_bonuses'], False),
    ('贵族', '个 / 局，模型本人', lambda p: p['candidate_metrics']['mean_nobles'], False),
    ('终局未买回预留', '张 / 局，模型本人', lambda p: p['candidate_metrics']['mean_reserves_stranded'], False),
)


def keyed_pairs(record):
    keyed = {(p['candidate'], p['opponent']): p for p in record['pairs']}
    require(len(keyed) == len(record['pairs']), 'duplicate model/opponent pair')
    return keyed


def comparison_tables(record, anchors, display=None):
    display = display or DISPLAY
    keyed = keyed_pairs(record)
    rows = []
    for label, unit, getter, percent in COMPARISON_METRICS:
        values = [math.fsum(getter(keyed[(model, op)]) for op in anchors) / len(anchors)
                  for model in ('base', 'alpha', 'balance')]
        f = pct if percent else fmt
        a, b, c = values
        rows.append([label, unit, *map(f, values), change(a, b, percent),
                     change(a, c, percent), change(b, c, percent)])
    out = [tables.table(['共同锚点等权平均', '单位 / 归属', display['base'],
                         display['alpha'], display['balance'], 'Alpha − 父模型',
                         'Balance − 父模型', 'Balance − Alpha'], rows),
           '三模型使用同批新 seed 与物理双座。↑/↓ 只表示方向，不代表更好或显著。'
           '各组的速度/比例来自总计数与总分母，再按冻结共同锚点等权描述；直接对战不混入锚点平均。']
    rows = []
    for op in anchors:
        for label, unit, getter, percent in COMPARISON_METRICS[:2]:
            a, b, c = (getter(keyed[(model, op)]) for model in ('base', 'alpha', 'balance'))
            f = pct if percent else fmt
            rows.append([display[op], label + '（' + unit + '）', f(a), f(b), f(c),
                         change(a, b, percent), change(a, c, percent), change(b, c, percent)])
    out.append(tables.table(['匹配共同对手', '本人指标 / 单位', display['base'], display['alpha'],
                             display['balance'], 'Alpha − 父模型', 'Balance − 父模型',
                             'Balance − Alpha'], rows))
    return '\n\n'.join(out)


def detailed_match_tables(record, display=None):
    display = display or DISPLAY
    out = []
    with helper_display(display):
        for op in dict.fromkeys(p['opponent'] for p in record['pairs']):
            pairs = [p for p in record['pairs'] if p['opponent'] == op]
            body = tables.detailed_tables(pairs, display[op] + '：完整双方数据')
            body = body.replace('Rush AUC', '总VP AUC24').replace('短于16自身Main', '短于24自身Main')
            trajectory = trajectories.trajectory_tables(pairs)
            # Balance has no style floor and no style reward; annotate metric meaning.
            trajectory = trajectory.replace('（训练效用）', '（描述指标；Alpha 训练代理）')
            trajectory = trajectory.replace('（风格底线）', '（Alpha 风格底线；Balance 仅描述）')
            out.extend([body, trajectory])
    return '\n\n'.join(out)


def development_direction_table(result, anchors):
    records = [result.get(stage) for stage in ('development', 'acceptance')]
    if not all(isinstance(record, dict) for record in records):
        return '开发 / 独立方向比较：NOT_RUN；缺失阶段不填零。'
    keyed = [keyed_pairs(record) for record in records]
    rows = []
    for label, _, getter, percent in COMPARISON_METRICS:
        for before, after in (('base', 'alpha'), ('base', 'balance'), ('alpha', 'balance')):
            deltas = [math.fsum(getter(p[(after, op)]) - getter(p[(before, op)])
                                for op in anchors) / len(anchors) for p in keyed]
            opposite = deltas[0] * deltas[1] < 0
            rows.append([f'{DISPLAY[after]} − {DISPLAY[before]}', label,
                         change(0, deltas[0], percent), change(0, deltas[1], percent),
                         '**方向相反；完整保留**' if opposite else '同向或有零变化；不合并样本'])
    return tables.table(['本人配对变化', '指标', '开发（仅描述）', '独立验收', '方向说明'], rows)


MEASURES = {
    'alpha/strength_pool': ('Alpha 续训总体保护', -.05, '配对半平得分率 Δ', True,
                            '未能排除总体退步超过5个百分点'),
    'alpha/direct_parent': ('Alpha 续训对父模型竞争力', .45, '直接半平得分率', True,
                            '未能确认对父模型得分率至少45%'),
    'alpha/bigcard_auc24': ('Alpha 续训大牌画像保留', -.015, '大牌印刷 VP AUC24 Δ', False,
                           '未能排除大牌 AUC24 降低超过0.015'),
    'balance/strength_pool': ('Balance 总体保护', -.05, '配对半平得分率 Δ', True,
                              '未能排除总体退步超过5个百分点'),
    'balance/direct_parent': ('Balance 对父模型竞争力', .45, '直接半平得分率', True,
                              '未能确认对父模型得分率至少45%'),
    'balance_vs_alpha/strength_pool': ('A/B 共同锚点竞争差', 0, 'Balance − Alpha 半平得分率 Δ', True,
                                      '未确认两候选共同锚点竞争差的方向'),
    'balance_vs_alpha/direct': ('A/B 直接竞争', .5, 'Balance 对 Alpha 直接半平得分率', True,
                                '未确认 Balance 或 Alpha 的直接优势'),
}
FLOORS = tuple(MEASURES)[:5]


def simultaneous_bounds(measurement):
    # M61 supplies both bounds. Never infer an upper bound from a lower bound.
    for lower, upper in (('simultaneous_two_sided_lower', 'simultaneous_two_sided_upper'),
                         ('simultaneous_lower', 'simultaneous_upper'),
                         ('simultaneous_one_sided_lower', 'simultaneous_one_sided_upper')):
        if lower in measurement and upper in measurement:
            return measurement[lower], measurement[upper]
    if 'simultaneous_ci' in measurement:
        return measurement['simultaneous_ci']
    raise ValueError('missing M61 simultaneous lower AND upper bounds')


def ab_verdict(measurements):
    pool = simultaneous_bounds(measurements['balance_vs_alpha/strength_pool'])
    direct = simultaneous_bounds(measurements['balance_vs_alpha/direct'])
    if pool[0] > 0 and direct[0] > .5:
        return 'CONFIRMED_BALANCE_SUPERIOR'
    if pool[1] < 0 and direct[1] < .5:
        return 'CONFIRMED_ALPHA_SUPERIOR'
    return 'INCONCLUSIVE'


def reported_comparison(result):
    value = result.get('comparison', result.get('comparison_verdict'))
    return value.get('verdict') if isinstance(value, dict) else value


def validate_measurements(result):
    if not result.get('measurements'):
        require(not isinstance(result.get('acceptance'), dict),
                'completed acceptance must include formal measurements')
        return
    measurements = result['measurements']
    require(set(measurements) == set(MEASURES), 'expected frozen seven measurements')
    require(set(result['gates']) == set(FLOORS), 'expected five retention floors')
    for key, measurement in measurements.items():
        lower, upper = simultaneous_bounds(measurement)
        require(all(isinstance(x, (int, float)) and math.isfinite(x)
                    for x in (measurement['mean'], *measurement['ci95'], lower, upper)),
                f'non-finite measurement: {key}')
        require(lower <= upper, f'reversed simultaneous interval: {key}')
        if key in FLOORS:
            require(result['gates'][key] == (lower >= MEASURES[key][1]),
                    f'gate disagrees with confidence floor: {key}')
    require(reported_comparison(result) == ab_verdict(measurements),
            'A/B verdict disagrees with both simultaneous bounds')
    for arm in ('alpha', 'balance'):
        expected = ('PASS_RETENTION_FLOORS' if all(result['gates'][key]
                    for key in FLOORS if key.startswith(arm + '/')) else 'FAIL_RETENTION_FLOORS')
        require(result['arm_verdicts'][arm] == expected, 'arm verdict disagrees: ' + arm)
    comparison = result['comparison']
    require(comparison['balance_confirmed'] == (ab_verdict(measurements) == 'CONFIRMED_BALANCE_SUPERIOR') and
            comparison['alpha_confirmed'] == (ab_verdict(measurements) == 'CONFIRMED_ALPHA_SUPERIOR'),
            'directional confirmation flags disagree')


def gate_table(result):
    measurements = result.get('measurements') or {}
    rows = []
    for key, (purpose, threshold, unit, percent, failure) in MEASURES.items():
        if key in FLOORS:
            threshold_text = f'校正下界 ≥ {threshold:g}'
        else:
            threshold_text = f'Balance: 下界 > {threshold:g}；Alpha: 上界 < {threshold:g}'
        measurement = measurements.get(key)
        if measurement:
            bounds = simultaneous_bounds(measurement)
            f = pct if percent else fmt
            values = [f(measurement['mean']), interval(measurement['ci95'], percent),
                      interval(bounds, percent)]
            verdict = ('**PASS**' if result['gates'][key] else '**FAIL**') if key in FLOORS else reported_comparison(result)
        else:
            values, verdict = ['NOT_RUN'] * 3, 'NOT_RUN'
        rows.append([key, purpose, unit + ('（变化为百分点）' if percent and 'Δ' in unit else ''),
                     threshold_text, *values, verdict, failure])
    return tables.table(['检验', '目的', '估计单位 / 归属', '采样前冻结阈值', '估计',
                         '普通配对95% CI', '七项双侧同时 CI', '原判定', '失败 / 未确认含义'], rows)


def pure_win_ci(pair):
    for key in ('pure_win_uncertainty', 'win_uncertainty', 'pure_win_ci', 'win_ci'):
        if key in pair:
            value = pair[key]
            return value['ordinary_95_ci'] if isinstance(value, dict) else value
    raise ValueError(f"missing paired pure-win CI: {pair['candidate']} / {pair['opponent']}")


def stage_summary(record, display=None):
    display = display or DISPLAY
    rows = []
    for pair in record['pairs']:
        m = pair['candidate_metrics']
        n = pair['macro']['total_games']
        require(n == m['games'] and m['wins'] + m['ties'] + m['losses'] == n,
                'outcome totals disagree')
        seats = pair['seats']
        require({s['candidate_seat'] for s in seats} == {0, 1} and len(seats) == 2,
                'missing physical first/second seats')
        require(sum(s['candidate']['games'] for s in seats) == n, 'seat coverage drift')
        require(math.isclose(m['score_rate'], (m['wins'] + .5 * m['ties']) / n),
                'half-draw score rate drift')
        rows.append([display[pair['candidate']], display[pair['opponent']], f'{n} / {n // 2}',
                     f"{m['wins']} / {m['ties']} / {m['losses']}", f"{m['win_rate_percent']:.4f}%",
                     interval(pure_win_ci(pair), True), pct(m['score_rate']),
                     interval(pair['score_uncertainty']['ordinary_95_ci'], True)])
    require(sum(p['macro']['total_games'] for p in record['pairs']) == record['games'],
            'stage coverage drift')
    return tables.table(['被测玩家（T=1）', '固定对手 / 模式', '局数 / 双座 seed 块',
                         'W / D / L', '纯胜率', '纯胜率配对95% CI', '半平得分率',
                         '半平得分率配对95% CI'], rows)


def flattened(value, prefix=''):
    """Keep every frozen provenance field, including failures and runtime args."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from flattened(child, f'{prefix}/{key}' if prefix else str(key))
    elif isinstance(value, list):
        if all(not isinstance(child, (dict, list)) for child in value):
            yield prefix, json.dumps(value, ensure_ascii=False)
        else:
            for index, child in enumerate(value):
                yield from flattened(child, f'{prefix}/{index}')
    else:
        yield prefix, 'NOT_MEASURED' if value is None else str(value)


def provenance_table(value, key_label='字段', value_label='原始记录'):
    return tables.table([key_label, value_label],
                        [[k.replace('|', '\\|'), v.replace('|', '\\|').replace('\n', '<br>')]
                         for k, v in flattened(value)])


def render_report(result, execution, source_rows=()):
    require(result['format'] == 'm61-balance-ab-evaluation-result-v1', 'wrong result format')
    validate_measurements(result)
    policy = execution['evaluation']
    anchors = policy['acceptance']['anchors']
    frozen = policy['acceptance']
    for field, value in (('family_alpha', .05), ('lower_quantile', .05 / 14),
                         ('upper_quantile', 1 - .05 / 14), ('bootstrap_samples', 20000),
                         ('bootstrap_rng_seed', 61039999)):
        require(frozen[field] == value, f'wrong frozen M61 statistical field: {field}')
    require(set(anchors) == {'heuristic-v031', 'prism-v01', 'prism-general-v011'},
            'wrong M61 common anchors')
    measurements = result.get('measurements') or {}
    verdict = reported_comparison(result) if measurements else 'NOT_RUN'
    floor_text = '五项保留底线尚未检验。'
    style_text = 'Alpha 续训大牌保留检验 NOT_RUN。'
    if measurements:
        floor_text = '；'.join(f"{key}={'PASS' if result['gates'][key] else 'FAIL'}" for key in FLOORS) + '。'
        gate = measurements['alpha/bigcard_auc24']
        style_text = (f"Alpha 续训大牌 AUC24 Δ {gate['mean']:+.6f}；原保留门 "
                      f"{'PASS' if result['gates']['alpha/bigcard_auc24'] else 'FAIL'}；"
                      '风格增强' + ('有' if simultaneous_bounds(gate)[0] > 0 else '无') + '校正下界证据。')
    competitive = f'独立 A/B 判定 **{verdict}**。' + floor_text
    if measurements:
        pool, direct = (measurements[key] for key in ('balance_vs_alpha/strength_pool', 'balance_vs_alpha/direct'))
        competitive += (f"共同锚点 ΔBalance − Alpha {pool['mean'] * 100:+.4f} 个百分点；"
                        f"Balance 对 Alpha 直接半平得分率 {pct(direct['mean'])}。")
    out = ['# M61 同父双候选：Alpha 续训与 Balance 最终 c4 A/B 报告',
           '**产物：**两个被测候选均为未发布最终 c4；父权重固定为 Prism Alpha v0.1.3。'
           '产物审计原状态与 hash 在来源表列出；竞技通过不替代张量、边界和来源审计，也不触发版本登记。',
           '**竞技：**' + competitive,
           '**风格：**' + style_text + ' Balance 没有 style gate；outcome-only / β=0 是训练合同，'
           '不能据此称“均衡风格已证实”。其大牌、折扣、贵族与预留指标仅描述，可在冻结棋力容忍度内取舍。',
           '**身份：**Alpha 续训（原 style）与 Balance（outcome-only）是同父两候选。'
           '所有表只计最终 c4，不把训练 c0..c3 当作候选战绩；通用对手为 Prism v0.1.1。'
           '名称不由 PASS 或 A/B 胜出自动改为 release；后续正式注册须另有真实身份记录。',
           '## 同种子共同锚点：父模型 → Alpha 续训 → Balance']
    latest = 'acceptance' if isinstance(result.get('acceptance'), dict) else 'development'
    if isinstance(result.get(latest), dict):
        out.extend(['以下为' + ('独立验收' if latest == 'acceptance' else '开发，仅描述') + '数据。',
                    comparison_tables(result[latest], anchors)])
    else:
        out.append('NOT_RUN；不填零、不推断任何候选的竞技或风格。')
    out.extend(['## 五项底线与两项 A/B 主检验', gate_table(result),
                '冻结统计家族为 **7项，family α=0.05，双侧同时区间，尾部分位 '
                '**q=0.05/(2×7)**，上分位 1−q；20,000 次匹配双座 seed 块 bootstrap，RNG 61039999。'
                '五项底线使用校正下界。Balance 胜出须共同锚点 Δ 的下界>0且直接得分率下界>0.5；'
                'Alpha 胜出须两项对应上界<0和<0.5。任何方向缺少其中一项确认均为 **INCONCLUSIVE**。'
                '普通95% CI不能替代校正区间。A/B胜出与每候选底线分别记录；Balance无风格否决门。'
                '不扩样本、不挑种子、不选中间检查点，保留所有失败、相反方向和原判定。',
                '## 开发与独立验收方向', development_direction_table(result, anchors)])
    if 'arm_verdicts' in result:
        out.extend(['## 每候选原底线判定', provenance_table(result['arm_verdicts'])])
    if 'comparison' in result:
        out.extend(['## A/B 原判定记录', provenance_table(result['comparison'])])
    for stage, label in (('development', '开发评测（仅描述）'), ('acceptance', '独立验收')):
        record = result.get(stage)
        out.append('## ' + label)
        if not isinstance(record, dict):
            out.append('NOT_RUN；不由开发数据推断验收，不填零。')
            continue
        out.extend([f"{record['games']} 局；每组先按模型身份与候选物理座位聚合再合并。"
                    '个人指标为被测模型 / 对手，节奏为该组整局指标，比例采用总计数/总分母。',
                    stage_summary(record), detailed_match_tables(record),
                    '每组纯胜/半平 CI 为描述性双座 seed 块 bootstrap；不增加晋级门。'
                    '决策轮=ceil(全动作步数/2)，Main排除贵族选择。单局时钟包括启动、比赛、验核和输出；'
                    '并行累计秒数不等于监督墙钟。逐决策 / 逐推理 **NOT_MEASURED / NOT_MEASURED**。',
                    provenance_table({k: v for k, v in record.items() if k != 'pairs'},
                                     '本阶段来源 / 字段', '原始记录 / SHA256')])
    out.extend(['## 时钟、负载与资源',
                provenance_table({k: result[k] for k in ('status', 'resources', 'elapsed_wall_seconds',
                                   'training', 'training_artifact_audit', 'candidate_sha256',
                                   'candidate_sha256s', 'completed_at') if k in result}),
                '训练墙钟与评测墙钟分别记录；cloud1 ARM64/native runtime 与 M60保持同一冻结身份。'
                '实际并行数、CPUQuota、内存上限、deadline及运行负载以执行合同/资源记录为准。'
                '缺少逐推理/逐决策测量时为 NOT_MEASURED，不能由单局或整批耗时倒推。',
                '## 冻结执行合同、模型与运行身份', provenance_table(execution),
                '启发式策略为 **Heuristic v0.3.1**；Hello splendor-cli-heuristic-v02 / 0.2.9 是协议常量，'
                '不作为策略名称。Prism runtime Hello prism-sample / 0.1.0（T=1）或 '
                'prism-v0.1 / 0.1.0（greedy）同样是程序协议身份；模型由冻结权重 SHA区分。'
                '父模型与原始评测根目录为 /home/ubuntu/splendor-ppo-m61；'
                'M60历史报告与失败记录保持原字节，M61不重命名旧模型或旧结果。',
                '## 输入与报告源', tables.table(['证据', '路径 / SHA256'], source_rows),
                '## 结论与限制', f'原结果状态：**{result.get("status", "NOT_RUN")}**；独立 A/B：**{verdict}**。'
                '两个候选均保留未发布最终 c4 身份。有限固定对手池、单一训练 RNG、最终检查点与固定温度'
                '限制外推；开发信号不用于选模型。保留负结果与开发/独立相反方向，'
                '不由本报告自动注册、部署或证明普适均衡风格。'])
    return '\n\n'.join(out) + '\n'


def verified_provenance(work, result, execution):
    """Verify referenced bytes locally, then extract literal participant commands."""
    rows, commands, descriptors = [], [], {}
    for path, digest in execution['files'].items():
        require(sha(path) == digest, 'execution source/asset drift: ' + path)
    for source in (Path(__file__), Path(tables.__file__), Path(trajectories.__file__)):
        require(str(source.resolve()) in execution['files'], 'report renderer source not pinned: ' + str(source))
    require(result['candidate_sha256'] == execution['candidate_sha256'], 'candidate identity drift')
    config_paths = [Path(path) for path in execution['files']
                    if Path(path).name == 'm61-prism-alpha-balance-ab.config.json']
    require(len(config_paths) == 1, 'missing frozen M61 config provenance')
    config = read(config_paths[0])
    require(result['config_sha256'] == execution['config_sha256'] == sha(config_paths[0]),
            'config identity drift')
    audit_path = Path(execution['audit_path'])
    require(sha(audit_path) == execution['audit_sha256'], 'audit binding drift')
    audit = read(audit_path)
    require(audit['status'] == 'PASS_TRAINING_ARTIFACT_AUDIT', 'artifact audit not PASS')
    for arm, digest in execution['candidate_sha256'].items():
        require(audit['arms'][arm]['candidate_sha256'] == digest, 'audit candidate identity drift')
    rows.extend([('训练合同与源码身份', provenance_table(config)),
                 ('最终 c4 产物审计（原记录）', provenance_table(audit))])
    for stage in ('development', 'acceptance'):
        record = result.get(stage)
        if not isinstance(record, dict):
            continue
        plan = read(work / stage / 'plan.json')
        coverage = {}
        for shard in plan['shards']:
            path = Path(shard['config'])
            require(sha(path) == shard['config_sha256'], 'shard config drift: ' + str(path))
            cfg = read(path)
            for category in ('candidates', 'opponents'):
                for name, descriptor in cfg[category].items():
                    require(name in DISPLAY, 'unknown participant identity: ' + name)
                    if name in descriptors:
                        require(descriptors[name] == descriptor, 'participant descriptor drift: ' + name)
                    descriptors[name] = descriptor
            for model in cfg['candidates']:
                for opponent in cfg['opponents']:
                    seats = coverage.setdefault((model, opponent), set())
                    block = {(seed, seat) for seed in cfg['seeds'] for seat in (0, 1)}
                    require(not seats.intersection(block), 'duplicate shard seed/seat')
                    seats.update(block)
        require(set(coverage) == set(keyed_pairs(record)), 'pair/shard coverage drift')
        seed_rows = []
        for pair in record['pairs']:
            seeds = coverage[(pair['candidate'], pair['opponent'])]
            require(len(seeds) == pair['macro']['total_games'], 'pair seed count drift')
            for ci in (pair['win_uncertainty'], pair['score_uncertainty']):
                require(ci['seed_blocks'] == len(seeds) // 2 and ci['rng_seed'] == 61039999 and
                        ci['resamples'] == 20000, 'descriptive CI provenance drift')
            values = sorted({seed for seed, _ in seeds})
            seed_rows.append([DISPLAY[pair['candidate']], DISPLAY[pair['opponent']],
                              f'{values[0]}..{values[-1]}', len(values), 'P0 / P1',
                              f'{work / stage / "plan.json"} / {record["plan_sha256"]}'])
        rows.append((stage + ' 固定 seed 与双座', tables.table(
            ['被测玩家', '固定对手', '环境 seed 范围', 'seed 块', '物理座位', '计划来源'], seed_rows)))
    for name, desc in descriptors.items():
        files = '; '.join(f"{f['path']} / {f['sha256']}" for f in desc['files']) or '无权重文件（固定源码启发式）'
        commands.append([DISPLAY[name], ' '.join([desc['program'], *desc['args']]), desc['sha256'], files])
    rows.insert(0, ('固定玩家字面命令与权重', tables.table(
        ['玩家 / 模式', '字面启动参数', '程序 SHA256', '权重路径 / SHA256'], commands)))
    return '\n\n'.join('## ' + title + '\n\n' + body for title, body in rows)


def report(work, output):
    work, output = Path(work).resolve(), Path(output).resolve()
    result_path, execution_path = work / 'result.json', work / 'execution.json'
    result, execution = read(result_path), read(execution_path)
    require(sha(execution_path) == result['execution_sha256'], 'execution receipt drift')
    source_rows = [['评测结果', f'{result_path} / {sha(result_path)}'],
                   ['执行合同', f'{execution_path} / {sha(execution_path)}'],
                   ['报告源码', f'{Path(__file__).resolve()} / {sha(__file__)}'],
                   ['双方表渲染源码', f'{tables.__file__} / {sha(tables.__file__)}'],
                   ['轨迹表渲染源码', f'{trajectories.__file__} / {sha(trajectories.__file__)}']]
    for stage in ('development', 'acceptance'):
        record = result.get(stage)
        if not isinstance(record, dict):
            continue
        for filename, key in (('plan.json', 'plan_sha256'),
                              ('source-ledger.json', 'source_ledger_sha256'),
                              ('style-metrics.json', 'style_metrics_sha256'),
                              ('match-details.json', 'match_details_sha256')):
            path = work / stage / filename
            require(sha(path) == record[key], f'{stage}/{filename} drift')
            source_rows.append([f'{stage}/{filename}', f'{path} / {record[key]}'])
    require(output.suffix.lower() == '.md', 'output must be Markdown')
    require(output not in {result_path, execution_path}, 'cannot overwrite evidence')
    provenance = verified_provenance(work, result, execution)
    text = render_report(result, execution, source_rows) + '\n' + provenance + '\n'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding='utf-8')
    print(f'PASS: {output}; zero games/updates; report sha256={sha(output)}')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True, help='M61 evaluation directory')
    parser.add_argument('--output', type=Path, required=True, help='Markdown destination')
    args = parser.parse_args()
    report(args.work, args.output)


if __name__ == '__main__':
    main()
