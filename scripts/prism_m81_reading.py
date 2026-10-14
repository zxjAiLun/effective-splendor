"""Offline M81 report recovery: render saved evidence without executing research."""
import hashlib
import html
import json
import re

import markdown

NAMES = {'heuristic': '启发式 v0.3.1', 'general': 'Prism v0.1.1',
         'balance': 'Balance v0.1.0', 'alpha': 'Alpha v0.1.4', 'beta': 'Beta v0.1.0',
         'released-alpha': 'Alpha v0.1.5', 'latest-alpha': 'Alpha v0.2.0',
         'latest-balance': 'Balance v0.2.1', 'parent': 'M75 c20 父代'}
ACTORS = {'base': 'M75 c20 父代', 'A': 'M81 A 原配比', 'B': 'M81 B 补覆盖'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duration(seconds):
    seconds = round(seconds)
    return f'{seconds // 3600}时{seconds // 60 % 60:02d}分{seconds % 60:02d}秒'


def build(spec_path, root):
    from scripts.prism_m81_report import _markdown
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    loaded = {}
    for key in ('result', 'costs', 'plan'):
        item = spec[key]
        path = root / item['path']
        if sha(path) != item['sha256']:
            raise ValueError(f'{key} input SHA mismatch')
        loaded[key] = json.loads(path.read_text(encoding='utf-8'))
    result, costs = loaded['result'], loaded['costs']
    if result['plan']['sha256'] != spec['plan']['sha256']:
        raise ValueError('result/plan identity mismatch')
    pairs = {(p['candidate'], p['opponent']): p for p in result['pairs']}
    for p in pairs.values():
        n = p['wins'] + p['draws'] + p['losses']
        if n != p['observed_games'] or abs((p['wins'] + .5*p['draws'])/n - p['half_score']) > 1e-12:
            raise ValueError('saved matchup count/score mismatch')
    if sum(p['observed_games'] for p in pairs.values()) != result['grid']['completed_games']:
        raise ValueError('saved grid mismatch')
    output = root / spec['output']
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = ['# M81：流程明显提速，补训练对手尚未解决旧锚点问题', '',
             '两组训练和全部计划评测执行已结束。固定候选 B 对父代的半平得分为 **54.45%**，但增加启发式和旧 Balance 的训练占比，没有显示出预期的针对性收益。**保留 M75 作为主线父候选，M81 B 未晋级。**', '',
             '## 先看三件事', '',
             '- **产物已完成：** A、B 各训练 5,120 局，均产出第 20 周期检查点；14,336 次评测执行产生 14,330 个终局和 6 个截断。',
             '- **棋力目标未达：** B 对启发式、旧 Balance 相对父代分别下降 1.66、2.64 个百分点；受截断影响的正式门还缺完整配对数据。',
             '- **风格仍待定：** 已有回放画像可作描述；当前指标与匹配参照不足以确认 Alpha、Beta 或 Balance 风格。', '',
             '## 这一轮究竟改了什么', '',
             '两组都从 **M75 c20** 权重出发，重新初始化优化器。A 保留原四对手训练配比；B 把 25% 的训练份额换成启发式与旧 Balance。固定最终第 20 周期检查点作为比较对象，B 是预先指定候选。M80 是工程整理轮，不是父模型。', '',
             '每组 20 个周期，每周期 256 局，共 5,120 局。PPO 每批数据训练 2 遍，小批为 256 条本人决策；A 共 1,110 次优化器更新，B 共 1,096 次。只有一组配对训练种子，结论针对本轮候选。', '',
             '## 对父代：两组都占优，但正式增强结论仍缺完整终局', '',
             '| 模型 | 胜 / 平 / 负 | 终局 / 计划 | 半平得分 |',
             '| --- | --- | ---: | ---: |']
    for actor in ('A', 'B'):
        p = pairs[actor, 'parent']
        lines.append(f"| {ACTORS[actor]} | {p['wins']} / {p['draws']} / {p['losses']} | {p['observed_games']} / {p['planned_games']} | {p['half_score']:.2%} |")
    lines += ['', '这里的百分比按已有终局计算。A 对父代有 3 个截断，B 有 1 个，不能把上述点估计当作完整独立增强门通过。', '',
              '## 对八个对手：收益集中在 Alpha，目标旧锚点没有修复', '',
              '双方均 greedy。半平得分 =（胜 + 0.5 × 平）÷ 终局数；差值单位为百分点。较大的数值加粗，显示值相同时不标胜者。', '',
              '| 对手 | M75 父代 | A 原配比 | B 补覆盖 | B − 父代 |',
              '| --- | ---: | ---: | ---: | ---: |']
    for opponent in list(NAMES)[:-1]:
        ps = [pairs[a, opponent] for a in ('base', 'A', 'B')]
        rounded = [round(p['half_score']*100, 2) for p in ps]
        vals = []
        for p, value in zip(ps, rounded):
            label = f'{value:.2f}%'
            if rounded.count(max(rounded)) == 1 and value == max(rounded):
                label = '**' + label + '**'
            if p['observed_games'] != p['planned_games']:
                label += '＊'
            vals.append(label)
        lines.append(f"| {NAMES[opponent]} | {' | '.join(vals)} | {(ps[2]['half_score']-ps[0]['half_score'])*100:+.2f} |")
    lines += ['', '每格计划 512 局；＊为 511 个终局。全部胜平负和先后手在本页末尾的完整 Markdown 中保留。', '',
              '**对照回答的问题：** B 比 A 对启发式高 0.59 个百分点，对旧 Balance 低 0.53 个百分点；对完整种子块配对后，两类目标对手的平均变化约为零。补覆盖的训练方法没有得到本轮结果支持。', '',
              '**退步的统计含义：** B 相对父代，对启发式的配对 95% 差值区间为 −4.98～+1.56 个百分点，对旧 Balance 为 −7.71～+2.54。点估计下降且未通过冻结保留门，但区间跨零，尚不能断言真实棋力退化。', '',
              '## 实际耗时：5,120 局从 11小时07分降到 3小时14分', '',
              '| 时间花在哪里 | A：优化前完整实跑 | B：中途优化完整实跑 |',
              '| --- | ---: | ---: |']
    for key, title in [('game_inner', '游戏子进程活动，含等待出招'), ('ppo', 'PPO 更新阶段，含提交'),
                       ('supervisor_excess', '外层监督额外等待'), ('launch_other', '逐局启动、核验、入库、账本等'),
                       ('cycle_other', '封批、导出、切换及其他'), ('wall_seconds', '总墙钟')]:
        lines.append(f"| {title} | {duration(costs['costs']['A'][key])} | {duration(costs['costs']['B'][key])} |")
    lines += ['', f"**完整实跑提速 {costs['speedup_full_measured']:.2f} 倍，耗时减少 {costs['time_reduction']:.2%}。** 主要节省来自外层等待和逐局管理开销；PPO 更新仍约 40 分钟。B 包含旧实现、两次优化和切换等待，且两组对手不同，因此这不是纯单变量的性能实验。", '',
              f"最终优化版本连续 1,792 局实跑 **{duration(costs['r5_observed_1792']['wall'])}**。按该速率估算 5,120 局为 **{duration(costs['r5_projection_5120']['wall'])}**，这是外推值。", '',
              '更新使用 CPU。A、B 平均占用分别为 1.097 核、1.141 核，约为 4 核额度的 27.4%、28.5%；尚未实现充分并行。DSW 上 A/B 的 10,240 次评测执行耗时 45分10秒，另有 DSW2 提前完成的 4,096 次基线评测。', '',
              '## 6 个截断，以及为什么没有晋级', '',
              '所有计划执行都结束了，6 个对局达到 512-ply 上限而未终局：父代基线 1 个、A 4 个、B 1 个。它们不是尚在排队的比赛，也没有被填成平局。受影响的配对统计与门保持不完整；此外，已完整的旧锚点保留门也没有通过。', '',
              '原报告在统计和画像保存之后，因读取计划哈希的字段错误而中断。本版直接读取已保存结果恢复展示；没有重新训练、补赛或重算冻结判门。', '',
              '## 下一步判断', '',
              '保留 M75 为主线父候选，M81 B 作为比较候选保存。本轮支持保留工程提速改动，不支持将“补入两个旧对手”认定为有效训练改进。下一轮优先利用现有检查点与回放缩小问题，再明确唯一训练变量；不因本轮负结果自动启动新训练。', '',
              '当前已保存的回放画像覆盖 14,330 个终局，包含首次大牌时点及覆盖率、早期低分购牌与折扣兑现。固定 Main 12/24 得分、贵族覆盖和合法购牌机会不在本版原始画像中，因此不作主动偏好或因果机制结论。', '',
              '## 完整表与证据', '',
              f'- [完整 Markdown：逐对手胜平负、双方得分、座位、画像与冻结统计]({output.with_suffix(".md").name})',
              '- [开跑前实验设计](m81-experiment-explained.html)',
              '- [完整轮次记录](../m81-anchor-coverage-pilot.md)', '',
              '本页交付与远端私有归档分别记录；本页不声称归档或 ALL 同步已经完成。']
    reading = '\n'.join(lines) + '\n'
    audit = _markdown(result)
    both = ['## 完整双方胜平负', '', '| 模型 | 对手 | 局数 | 本方胜/平/负 | 对手胜/平/负 | 本方得分 | 对手得分 |', '| --- | --- | ---: | --- | --- | ---: | ---: |']
    for p in result['pairs']:
        both.append(f"| {ACTORS[p['candidate']]} | {NAMES[p['opponent']]} | {p['observed_games']} | {p['wins']}/{p['draws']}/{p['losses']} | {p['losses']}/{p['draws']}/{p['wins']} | {p['half_score']:.2%} | {1-p['half_score']:.2%} |")
    output.with_suffix('.md').write_text(reading + '\n' + '\n'.join(both) + '\n\n' + audit, encoding='utf-8')
    body = markdown.markdown(reading, extensions=['tables'])
    body = re.sub(r'(<table>.*?</table>)', r'<div class="table-wrap">\1</div>', body, flags=re.S)
    css = 'body{margin:0;background:#f4f5f7;color:#182534;font:17px/1.85 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1000px;margin:auto;padding:48px 32px 80px}h1{font-size:36px;line-height:1.4;max-width:900px}h2{font-size:25px;margin-top:48px;border-top:1px solid #d5dce3;padding-top:28px}p,li{max-width:900px}a{color:#175c96}strong{color:#102b46}.eyebrow{font-size:14px;letter-spacing:2px;color:#526b80}table{width:100%;border-collapse:collapse;background:white;font-size:15px;white-space:nowrap}th,td{padding:12px 14px;border-bottom:1px solid #dce3e9;text-align:left}th{background:#e6edf3}td:not(:first-child){font-variant-numeric:tabular-nums}.table-wrap{overflow-x:auto;border:1px solid #dce3e9;border-radius:10px}li{margin:10px 0}@media(max-width:600px){main{padding:24px 18px 50px}h1{font-size:27px}h2{font-size:22px;margin-top:32px}body{font-size:16px}th,td{padding:10px}ul{padding-left:22px}}'
    output.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>M81 结果与实际耗时</title><style>' + css + '</style><main><div class="eyebrow">PRISM RESEARCH / M81 / 2026.10.14</div>' + body + '</main></html>', encoding='utf-8')
    receipt = {'format': 'prism-m81-reading-recovery-receipt-v1', 'result_sha256': spec['result']['sha256'],
               'spec_sha256': sha(spec_path), 'html_sha256': sha(output), 'markdown_sha256': sha(output.with_suffix('.md')),
               'source_sha256': sha(root/'scripts/prism_m81_reading.py'), 'reporter_sha256': sha(root/'scripts/prism_m81_report.py'),
               'original_reporter_sha256': result['source_hashes']['reporter'],
               'matchups': len(pairs), 'terminal_games': result['grid']['completed_games'],
               'games_dispatched': 0, 'gate_values_changed': False, 'visual': 'NOT_VERIFIED'}
    for key in ('result', 'costs', 'plan'):
        if sha(root/spec[key]['path']) != spec[key]['sha256']:
            raise ValueError('source changed during render')
    output.with_suffix('.reading-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return receipt
