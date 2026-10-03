"""M60 readable evaluation tables and descriptive pure-win intervals; no games."""
import argparse
from collections import defaultdict
import copy
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_alpha_cloud_acceptance_m60 as control
from scripts import prism_match_details as details
from scripts import prism_alpha_report as trajectories
from scripts import prism_rush_report as tables

read, write, sha, require = control.read, control.write, control.sha, control.require


def intervals(work, result):
    out = {'format': 'm60-descriptive-win-intervals-v1', 'new_games': 0, 'new_updates': 0,
           'source_sha256': sha(__file__), 'evaluation_result_sha256': sha(work / 'result.json'), 'stages': {}}
    for stage in ('development', 'acceptance'):
        if not isinstance(result.get(stage), dict):
            continue
        groups = defaultdict(list)
        plan = read(work / stage / 'plan.json')
        require(sha(work / stage / 'match-details.json') == result[stage]['match_details_sha256'], 'match detail drift')
        require(sha(work / stage / 'source-ledger.json') == result[stage]['source_ledger_sha256'], 'source ledger drift')
        for shard in plan['shards']:
            require(sha(shard['config']) == shard['config_sha256'], 'shard config drift')
            cfg = read(shard['config'])
            v = control.fixed.validate_config(cfg, shard['config'])
            control.fixed.check_assets(v)
            progress = read(Path(shard['output']) / 'progress.json')
            require(progress['config_sha256'] == control.fixed.canonical_hash(cfg), 'progress config drift')
            for row in control.fixed._rows_from_progress(progress, v):
                game_root = Path(shard['output']) / 'games' / row['candidate'] / row['opponent'] / f"seed-{row['seed']}-seat-{row['candidate_seat']}"
                require(read(game_root / 'game.json')['row'] == row, 'descriptive outcome drift')
                # Pure-win indicator, resampled in the same two-seat seed block.
                record = copy.deepcopy(row)
                record['candidate_score'] = float(row['record'] == 'win')
                groups[(row['candidate'], row['opponent'])].append(record)
        require(sum(map(len, groups.values())) == result[stage]['games'], 'descriptive interval coverage')
        out['stages'][stage] = [{'candidate': m, 'opponent': op, 'games': len(xs),
                                'seed_blocks': len(xs) // 2, 'win_ci': details.score_ci(xs)}
                               for (m, op), xs in sorted(groups.items())]
    write(work / 'descriptive-win-intervals.json', out)
    return out


def pct(x):
    return f'{100*x:.4f}%'


def change(a, b, percent=False):
    d = b - a
    marker = '↑' if d > 0 else '↓' if d < 0 else '→'
    return f'**{marker} {d*100:+.4f} 个百分点**' if percent else f'**{marker} {d:+.6f}**'


def comparisons(result, stage):
    pairs = result[stage]['pairs']
    keyed = {(p['candidate'], p['opponent']): p for p in pairs}
    anchors = result['acceptance_policy']['anchors']
    metrics = [('半平得分率', '%，模型本人', lambda p: p['candidate_metrics']['score_rate'], True),
               ('大牌印刷 VP AUC24', '无量纲，模型本人', lambda p: p['candidate_bigcard']['mean_large_card_vp_auc24'], False),
               ('终局大牌印刷分', 'VP / 局，模型本人', lambda p: p['candidate_bigcard']['mean_terminal_large_card_printed_vp'], False),
               ('购入4 VP牌', '张 / 局，模型本人', lambda p: p['candidate_metrics']['mean_cards_by_vp']['4'], False),
               ('购入5 VP牌', '张 / 局，模型本人', lambda p: p['candidate_metrics']['mean_cards_by_vp']['5'], False),
               ('终局VP', 'VP / 局，模型本人', lambda p: p['candidate_metrics']['mean_prestige'], False),
               ('自身Main得分速度', 'VP / Main，模型本人', lambda p: p['candidate_metrics']['vp_per_main_action'], False)]
    rows = []
    for label, unit, getter, percent in metrics:
        a, b = (math.fsum(getter(keyed[(m, op)]) for op in anchors) / len(anchors)
                for m in ('base', 'candidate'))
        fmt = pct if percent else lambda x: f'{x:.6f}'
        rows.append([label, unit, fmt(a), fmt(b), change(a, b, percent)])
    text = tables.table(['共同三锚点等权平均', '单位 / 归属', '父模型 Prism Alpha v0.1.2',
                         control.DISPLAY['candidate'], '匹配变化'], rows)
    text += '\n三个对手都用同批新种子和双座。↑/↓ 只表示变化方向；显著增强必须看校正下界。VP/Main 先各组按总VP/总Main计算，再按三个锚点等权描述。\n\n'
    rows = []
    for op in anchors:
        a, b = keyed[('base', op)], keyed[('candidate', op)]
        rows.append([control.DISPLAY[op], pct(a['candidate_metrics']['score_rate']),
                     pct(b['candidate_metrics']['score_rate']),
                     change(a['candidate_metrics']['score_rate'], b['candidate_metrics']['score_rate'], True),
                     change(a['candidate_bigcard']['mean_large_card_vp_auc24'], b['candidate_bigcard']['mean_large_card_vp_auc24'])])
    return text + tables.table(['同种子共同对手', '父模型得分率', '候选得分率', '得分率变化', '大牌AUC24变化'], rows)


def report(work):
    result = read(work / 'result.json')
    execution = read(work / 'execution.json')
    require(sha(work / 'execution.json') == result['execution_sha256'], 'execution receipt drift')
    extra = intervals(work, result)
    completed = result.get('status') in ('ACCEPTED_BIGCARD_CONTINUATION', 'NOT_ACCEPTED_BIGCARD_CONTINUATION')
    accepted = completed and result['all_three_gates_passed']
    display = dict(control.DISPLAY)
    if accepted:
        display['candidate'] = 'Prism Alpha v0.1.3（M60 最终 c4）'
    control.DISPLAY = tables.DISPLAY = trajectories.DISPLAY = display
    competitive = '独立验收尚在执行，当前开发数据仅描述。'
    style = '独立大牌风格检验尚未完成。'
    if completed:
        m = result['measurements']
        competitive = ('棋力保护与直接父模型两项底线均通过。' if result['gates']['strength_pool'] and result['gates']['direct_parent']
                       else '棋力保留底线至少一项未通过，具体含义见三门表。')
        competitive += f"共同锚点半平得分率变化 {m['strength_pool']['mean']*100:+.4f} 个百分点；直接父模型得分率 {pct(m['direct_parent']['mean'])}。"
        competitive += '总体增强' + ('有' if m['strength_pool']['simultaneous_one_sided_lower'] > 0 else '无') + '校正下界证据；直接父模型优势' + ('有' if m['direct_parent']['simultaneous_one_sided_lower'] > .5 else '无') + '校正下界证据。'
        style = f"大牌印刷 VP AUC24 变化 {m['bigcard_auc24']['mean']:+.6f}，保留门 {'PASS' if result['gates']['bigcard_auc24'] else 'FAIL'}；风格增强" + ('有' if m['bigcard_auc24']['simultaneous_one_sided_lower'] > 0 else '无') + '校正下界证据。'
    out = ['# M60 Prism Alpha：最终 c4 对战评测与验收',
           '**产物：**四轮 1,024 局、216 次更新、27,398 次训练决策，最终 c4 已提交；32 policy/value 导出张量与 checkpoint 逐元素相同（36 AdamW slots），Rust/Python 边界 68/68 PASS（max abs 0.00012456）。本轮监督器 **STOPPED_COMMITTED**：收尾单实例化修复后首次全程跑通，自有 tree 墙钟 2,835.466626 s、slice OOM 计数 0。原 M59 4 GiB 收尾 OOM / FAILED 历史保留。本次评测使用独立 8 GiB 资源合同，0 重试。',
           '**竞技：**' + competitive, '**风格：**' + style,
           '**版本身份：**' + ('三项原定底线全部通过，可将本实验产物登记为 **Prism Alpha v0.1.3**。' if accepted else
                                'M60 最终 c4 仍为**未发布训练候选**；Prism Alpha v0.1.3 是验收后预留名称。'),
           '父模型是 **Prism Alpha v0.1.2**：本轮继承它的 policy/value 权重继续 PPO，产生不同的新权重；通用 **Prism v0.1.1** 是共同对手，二者不是同一条版本线。所有表中的候选均为固定最终 c4，训练 c0..c3 不计入本报告。',
           '[本轮设计与历史](../m60-prism-alpha-cloud-ppo.md)；[原训练双方表](prism-alpha-cloud-m60-training-matches.md)。默认模型、共享池、Studio 和 Elo 未变。']
    latest = 'acceptance' if completed else 'development'
    if isinstance(result.get(latest), dict):
        out += ['## 一眼看变化：父模型 → 固定最终候选',
                ('以下为独立验收数据。' if completed else '以下为开发数据，独立验收尚无结论。'), comparisons(result, latest)]
    gates = {'strength_pool': ('防止共同锚点总体棋力明显退步', '配对得分率Δ校正下界 ≥ −0.05（−5个百分点）',
                              '未能排除超过5个百分点的退步；不等于候选每组输了'),
             'direct_parent': ('保证对父模型的直接竞争力', '候选半平得分率校正下界 ≥ 0.45',
                               '未能确认对父模型得分率至少45%；不要求下界超过50%'),
             'bigcard_auc24': ('保留大牌冲分画像', '配对大牌印刷VP AUC24 Δ校正下界 ≥ −0.015',
                              '未能排除大牌AUC降低超过0.015；经济指标可有取舍')}
    rows = []
    for gate, (purpose, threshold, meaning) in gates.items():
        if completed:
            m = result['measurements'][gate]
            values = [f"{m['mean']:.6f}", '[' + ', '.join(f'{x:.6f}' for x in m['ci95']) + ']',
                      f"{m['simultaneous_one_sided_lower']:.6f}", '**PASS**' if result['gates'][gate] else '**FAIL**']
        else:
            values = ['NOT_RUN'] * 4
        rows.append([gate, purpose, threshold, *values, meaning])
    out += ['## 三项冻结保留门', tables.table(['gate', '目的', '冻结阈值', '估计', '普通配对95%区间',
              '三门校正单侧下界', '结论', 'FAIL 的具体含义'], rows),
            '三门是允许取舍的保留底线，不要求所有描述指标上升。20,000 次配对 seed 块 bootstrap，RNG 59039999，family α=0.05，单侧下界分位 0.05/3；共同锚点 256 个匹配块，直接父模型 512 块。相同下界分别 >0、>0.5、>0 才能确认相应增强；通过底线不自动证明更强。每个对手的结果、折扣、贵族、预留和早期总VP均为描述，不另加否决门。独立样本只作一次三门分析，不延长样本或挑权重。']
    for stage, label in (('development', '开发评测（仅描述）'), ('acceptance', '独立验收')):
        record = result.get(stage)
        if not isinstance(record, dict):
            out += ['## ' + label, 'NOT_RUN / 正在执行；不填零、不由开发数据推断。']
            continue
        out += ['## ' + label, f"{record['games']} 局全部完成并经 Rust 规则回放验证。各组按模型身份与物理座位分别聚合后合并；比例按总计数/总分母计算。"]
        ci = {(r['candidate'], r['opponent']): r for r in extra['stages'][stage]}
        out.append(tables.table(['被测玩家（T=1）', '固定对手 / 模式', '局数 / 双座 seed块',
                                '纯胜率：配对95%区间', '半平得分率：配对95%区间'],
                               [[control.DISPLAY[p['candidate']], control.DISPLAY[p['opponent']],
                                 f"{p['macro']['total_games']} / {p['macro']['total_games']//2}",
                                 '[' + ', '.join(pct(x) for x in ci[(p['candidate'], p['opponent'])]['win_ci']['ordinary_95_ci']) + ']',
                                 '[' + ', '.join(pct(x) for x in p['score_uncertainty']['ordinary_95_ci']) + ']'] for p in record['pairs']]))
        for op in (*result['acceptance_policy']['anchors'], 'base-t1'):
            pairs = [p for p in record['pairs'] if p['opponent'] == op]
            if not pairs:
                continue
            body = tables.detailed_tables(pairs, control.DISPLAY[op] + '：完整双方数据')
            body = body.replace('Rush AUC', '总VP AUC24').replace('短于16自身Main', '短于24自身Main')
            out += [body, trajectories.trajectory_tables(pairs)]
        out.append('上述每组纯胜/半平区间均为描述性双座 seed 块 bootstrap，20,000 次、RNG 54049999（沿用 M56/M57/M59 固定描述实现，不改冻结 helper）；不是额外晋级门。计时为 cloud1 ARM64 两个并行 worker、CPUQuota 200%，每个 worker 串行执行 run-match，内存总上限8 GiB。')
        out.append(tables.table(['本阶段来源', '云端路径 / SHA256'], [
            [name, str(work / stage / filename) + ' / ' + record[key]]
            for name, filename, key in (('分片计划', 'plan.json', 'plan_sha256'),
                                        ('逐局来源账本', 'source-ledger.json', 'source_ledger_sha256'),
                                        ('规则回放与大牌画像', 'style-metrics.json', 'style_metrics_sha256'),
                                        ('双方完整指标', 'match-details.json', 'match_details_sha256'))]))
    usage = result.get('resources') or {}
    out += ['## 资源、时钟与来源', tables.table(['项目', '实测 / 合同'], [
        ['固定最终c4 SHA256', result['candidate_sha256']], ['评测执行合同 SHA256', result['execution_sha256']],
        ['本轮训练', '4×256=1,024局 / 216次更新 / 27,398决策 / 0重试；tree墙钟2,835.466626s；STOPPED_COMMITTED（收尾修复后首次全程PASS；slice oom=0）'],
        ['本次评测', '384开发 + 4,096独立 = 4,480逻辑局；2并行 / 8GiB / 8h截止 / 40,000CPU秒 / 32GiB；0重试'],
        ['本次开始到结束间隔', f"{result['elapsed_wall_seconds']:.3f}s" if completed else '尚未结束'],
        ['评测cgroup累计CPU / 内存峰值', f"{usage.get('cpu_seconds', 'NOT_MEASURED')}s / {usage.get('memory_peak_bytes', 'NOT_MEASURED')} bytes"],
        ['逐决策 / 逐推理时延', 'NOT_MEASURED / NOT_MEASURED'],
        ['完成状态', result.get('status', 'DEVELOPMENT_VERIFIED / ACCEPTANCE_RUNNING')]]),
        '单局时钟涵盖启动、比赛、输出；累计单局秒数包含并行重叠，不能当作监督墙钟。评测墙钟与训练墙钟分别记录。game-wall60s、握手/动作各10s、关闭宽限1s。无失败重赛。',
        tables.table(['冻结来源', '路径 / SHA256'], [
            ['本轮配置', '../../benchmarks/m60-prism-alpha-cloud-ppo.config.json / ' + control.CONFIG_SHA],
            ['本轮蓝图', '../../benchmarks/m60-prism-alpha-cloud-ppo.train.json / ' + control.TRAIN_SHA],
            ['评测执行合同', str(work / 'execution.json') + ' / ' + result['execution_sha256']],
            ['评测结果', str(work / 'result.json') + ' / ' + sha(work / 'result.json')],
            ['描述性纯胜区间', str(work / 'descriptive-win-intervals.json') + ' / ' + sha(work / 'descriptive-win-intervals.json')]]),
        'cloud1 原始逐局配置、report/replay/process-result/握手、26个分片进度、source-ledger 和 Rust style/economy manifest 在 /home/ubuntu/splendor-ppo-m60/evaluation。共同开发 seed9596000..9596031，独立共同 seed9601000..9601255，直接父模型 seed9601000..9601511；T=1 action seed59032001。native/权重/源文件完整 hash 见执行合同；固定305文件 Rust snapshot/数值身份见原配置（numerical identity 与 M59 相同）。初代 greedy seed51000001，便携 Heuristic greedy seed20260926。',
        '本轮保持单候选、有限对手池与一次训练 RNG；对其他风格、采样温度或运行平台不外推。不存在本机与 cloud1 同负载正式比赛计时对照，不能由本次时间声称固定速度倍数。']
    cfg = read(read(work / 'development/plan.json')['shards'][0]['config'])
    identity_rows = []
    for category in ('candidates', 'opponents'):
        for name, desc in cfg[category].items():
            weights = '; '.join(a['path'] + ' / ' + a['sha256'] for a in desc['files']) or '无权重文件（固定源码启发式）'
            identity_rows.append([control.DISPLAY[name], ' '.join(desc['args']), weights])
    out += ['## 固定玩家与运行程序身份',
            tables.table(['模型 / 固定对手', '字面启动参数（动作模式）', '权重文件 / SHA256'], identity_rows),
            tables.table(['原生 ARM 程序', '路径 / SHA256'], [[kind, desc['path'] + ' / ' + desc['sha256']]
                for kind, desc in execution['binaries'].items()]),
            'Prism 推理 runtime 的 Hello 为 prism-sample / 0.1.0（T=1）或 prism-v0.1 / 0.1.0（greedy）；这些是程序协议版本。模型身份由上表冻结权重 SHA区分，不能把 runtime 的0.1.0当作所有模型的模型版本。启发式 Hello 为 splendor-cli-heuristic-v02 / 0.2.9。']
    if completed:
        out += ['## 本轮决定', '三门全部通过，完成本轮独立验收；收尾修复与探针证据保留。' if accepted else
                '本轮训练与正式独立检验均已完成，至少一项冻结底线未通过；保留最终c4及完整负结果，不追加对局或PPO。']
    text = '\n\n'.join(out) + '\n'
    path = work / 'readable-evaluation.md'
    path.write_text(text, encoding='utf-8')
    print(f'PASS: {path}; zero games/updates; verified stages={list(extra["stages"])}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    report(parser.parse_args().work.resolve())
