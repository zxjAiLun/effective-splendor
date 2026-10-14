"""Offline editorial view of frozen M79 evidence; never dispatches research."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'benchmarks/reports/m79-reading-r3.json'
NAMES = {'a': 'M79 c20', 'base': 'M75 c20', 'style-reference': 'Balance v0.2.0',
         'parent': 'M75 c20', 'heuristic': '启发式', 'general': 'Prism v0.1.1',
         'balance': 'Balance v0.1.0', 'alpha': 'Alpha v0.1.4', 'beta': 'Beta v0.1.0',
         'released-alpha': 'Alpha v0.1.5', 'latest-alpha': 'Alpha v0.2.0',
         'latest-balance': 'Balance v0.2.1'}
COMMON = ['heuristic', 'general', 'balance', 'alpha', 'beta', 'released-alpha']
OPPONENTS = COMMON + ['latest-alpha', 'latest-balance']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pct(value):
    return f'{value * 100:.2f}%'


def pp(value):
    return f'{value * 100:+.2f}'


def score(m):
    return (m['wins'] + m['ties'] / 2) / m['games']


def wdl(m):
    return f"{m['wins']} 胜 / {m['ties']} 平 / {m['losses']} 负"


def table(headers, rows, cls='plain-table'):
    return '<table class="' + cls + '"><thead><tr>' + ''.join(f'<th scope="col">{x}</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{x}</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table>'


def mdtable(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |'] + ['| ' + ' | '.join(str(x).replace('\n', ' ') for x in row) + ' |' for row in rows])


def build():
    spec = json.loads(SPEC.read_text(encoding='utf-8'))
    for source in spec['sources'].values():
        assert sha(ROOT / source['path']) == source['sha256'], source['path']
    def load(key):
        return json.loads((ROOT / spec['sources'][key]['path']).read_text(encoding='utf-8'))
    result, profile = load('result'), load('profile')
    pairs = {(p['candidate'], p['opponent']): p for p in result['pairs']}
    assert len(pairs) == 23
    assert result['completed_games'] == result['planned_games'] == 12288
    for p in pairs.values():
        a, b = p['candidate_metrics'], p['opponent_metrics']
        assert a['games'] == b['games'] == p['planned_games'] == p['completed_games']
        assert p['missing_games'] == 0
        for m in [a, b]:
            assert m['wins'] + m['ties'] + m['losses'] == m['games']
            assert abs(score(m) - m['score_rate']) < 1e-12
        assert (a['wins'], a['ties'], a['losses']) == (b['losses'], b['ties'], b['wins'])
        for key in ['games', 'wins', 'ties', 'losses', 'games_with_nobles', 'total_main_actions']:
            for actor, metrics in [('candidate', a), ('opponent', b)]:
                assert sum(s[actor][key] for s in p['seats']) == metrics[key]
    assert sum(p['completed_games'] for p in pairs.values()) == 12288
    endpoints = result['statistics']['endpoints']
    def metric(model, opponent):
        return pairs[model, opponent]['candidate_metrics']
    def pool(model):
        ms = [metric(model, o) for o in COMMON]
        return sum(m['wins'] + m['ties'] / 2 for m in ms) / sum(m['games'] for m in ms)
    assert abs(pool('a') - pool('base') - endpoints['common_delta']['estimate']) < 1e-12
    assert abs(score(metric('a', 'parent')) - endpoints['direct_parent']['estimate']) < 1e-12
    for key in ['heuristic', 'released-alpha', 'latest-alpha', 'latest-balance']:
        assert abs(score(metric('a', key)) - score(metric('base', key)) - endpoints[key]['estimate']) < 1e-12
    assert result['statistics']['mainline_recommendation']['status'] == 'FAIL'
    models = {k: profile['profile']['models'][k]['metrics'] for k in ['a', 'base', 'style-reference']}
    corrected_nobles = {}
    for k, m in models.items():
        n = sum(metric(k, o)['games'] for o in COMMON)
        count = sum(metric(k, o)['games_with_nobles'] for o in COMMON)
        assert n == m['games'] == 3072
        corrected_nobles[k] = {'games_with_nobles': count, 'games': n, 'coverage': count / n,
                               'previous_profile_coverage': m['noble_coverage']}
        assert abs(m['first_big_coverage'] - m['first_big_games'] / n) < 1e-12
        assert abs(m['big_printed_vp_per_game'] - sum(int(v) * c for v, c in m['cards_by_vp'].items() if int(v) >= 3) / n) < 1e-12

    rows, mdrows = [], []
    for o in OPPONENTS:
        a, b = metric('a', o), metric('base', o)
        delta = score(a) - score(b)
        group = 'common' if o in COMMON else 'coverage'
        color = 'pos' if delta > 0 else 'neg'
        width = abs(delta) * 100 / 8 * 50
        left = 50 if delta >= 0 else 50 - width
        def cell(m, label, higher):
            tag = 'strong' if higher else 'span'
            return f'<td class="score" data-label="{label}"><{tag}>{pct(score(m))}</{tag}><small>{wdl(m)}</small></td>'
        rows.append(f'<tr data-group="{group}"><td class="opponent">{NAMES[o]}<small>{"六对手共同池" if group == "common" else "新增覆盖对手"}</small></td>'
                    + cell(b, '父代 M75', score(b) > score(a)) + cell(a, '本轮 M79', score(a) > score(b))
                    + f'<td class="change {color}" data-label="变化">{pp(delta)}<small>个百分点</small></td><td class="chart-col"><div class="delta-track" aria-hidden="true"><i class="delta-bar {color}" style="left:{left:.4f}%;width:{width:.4f}%"></i></div></td></tr>')
        mdrows.append([NAMES[o], pct(score(b)), pct(score(a)), pp(delta) + ' 个百分点', wdl(b), wdl(a)])

    gate_rows = []
    labels = {'common_delta': '六对手共同池', 'direct_parent': '直接对父代', 'latest-alpha': 'Alpha v0.2.0', 'latest-balance': 'Balance v0.2.1', 'heuristic': '启发式', 'released-alpha': 'Alpha v0.1.5'}
    requirements = {'common_delta': '增益 ≥ 2 个百分点，且下界 > 0；保留下界 ≥ −5',
                    'direct_parent': '得分 ≥ 52%，且下界 > 50%；保留下界 ≥ 45%',
                    'latest-alpha': '增益下界 ≥ −3 个百分点', 'latest-balance': '增益下界 ≥ −3 个百分点',
                    'heuristic': '增益下界 ≥ −3 个百分点', 'released-alpha': '增益下界 ≥ −3 个百分点'}
    for key, e in endpoints.items():
        ci = e['interval']['ordinary_95']
        f = pct if key == 'direct_parent' else pp
        gate_rows.append([labels[key], f(e['estimate']), f"{f(ci['lower'])} ～ {f(ci['upper'])}", requirements[key], '；'.join(('增强' if k == 'enhancement' else '保留') + ('通过' if v == 'PASS' else '未通过') for k, v in e['gates'].items())])

    def profile_panel(reference, panel):
        a, b = models['a'], models[reference]
        data = [
            ['大牌贡献的印刷分 / 局<span class="metric-note">3–5 分牌；不含贵族分</span>', f"{b['big_printed_vp_per_game']:.2f}", f"{a['big_printed_vp_per_game']:.2f}"],
            ['首次买到 4–5 分牌<span class="metric-note">仅在买到的对局中，取本人行动步数均值</span>', f"第 {b['first_big_main']:.2f} 步<span class='metric-note'>{b['first_big_games']}/3072 局 · {pct(b['first_big_coverage'])}</span>", f"第 {a['first_big_main']:.2f} 步<span class='metric-note'>{a['first_big_games']}/3072 局 · {pct(a['first_big_coverage'])}</span>"],
            ['0–1 分牌购买量 / 局<span class="metric-note">小牌投资的实际数量</span>', f"{b['low_cards_per_game']:.2f} 张", f"{a['low_cards_per_game']:.2f} 张"],
            ['获得贵族的对局比例<span class="metric-note">至少获得一位贵族；已更正旧画像口径</span>', f"{pct(corrected_nobles[reference]['coverage'])}<span class='metric-note'>{corrected_nobles[reference]['games_with_nobles']}/3072 局</span>", f"{pct(corrected_nobles['a']['coverage'])}<span class='metric-note'>888/3072 局</span>"],
            ['每步得到的最终分数<span class="metric-note">总终局分 ÷ 本人常规行动总步数</span>', f"{b['vp_per_own_main']:.3f}", f"{a['vp_per_own_main']:.3f}"],
        ]
        return f'<div data-profile-panel="{panel}" {"hidden" if panel != "parent" else ""}>' + table(['行为指标', NAMES[reference], 'M79 c20'], data) + '</div>'

    detail_html, full_md = [], []
    stat_fields = [('局数', 'games'), ('胜', 'wins'), ('平', 'ties'), ('负', 'losses'), ('纯胜率 %', 'win_rate_percent'),
                   ('平均终局分', 'mean_prestige'), ('平均贵族数', 'mean_nobles'), ('获贵族局数', 'games_with_nobles'),
                   ('贵族覆盖 %', 'games_with_nobles_percent'), ('平均折扣数', 'mean_permanent_bonuses'),
                   ('平均预留数', 'mean_reserves_acquired'), ('平均买回数', 'mean_reserves_bought'),
                   ('平均未买回数', 'mean_reserves_stranded'), ('预留兑现 %', 'reserve_redemption_rate_percent'),
                   ('本人常规行动总数', 'total_main_actions'), ('本人决策总数', 'total_actor_decisions'),
                   ('分数 / 本人常规行动', 'vp_per_main_action')]
    def fmt(v):
        return f'{v:.4f}' if isinstance(v, float) else str(v)
    for (actor, opponent), pair in pairs.items():
        a, b = pair['candidate_metrics'], pair['opponent_metrics']
        title = NAMES[actor] + ' 对 ' + NAMES[opponent]
        hdr = ['指标', NAMES[actor], NAMES[opponent]]
        all_rows = [[label, fmt(a[key]), fmt(b[key])] for label, key in stat_fields]
        all_rows.insert(4, ['半平得分', pct(score(a)), pct(score(b))])
        for v in range(6):
            all_rows.append([f'{v} 分牌 / 局', fmt(a['mean_cards_by_vp'][str(v)]), fmt(b['mean_cards_by_vp'][str(v)])])
        for color in a['mean_bonuses_by_color']:
            all_rows.append([color + ' 折扣 / 局', fmt(a['mean_bonuses_by_color'][color]), fmt(b['mean_bonuses_by_color'][color])])
        action_names = {'buy_market': '购买公开牌', 'buy_reserved': '购买预留牌', 'take_tokens': '拿取宝石', 'reserve_market': '预留公开牌', 'reserve_deck': '盲预留', 'choose_noble': '贵族选择动作', 'pass': '跳过'}
        for key, label in action_names.items():
            all_rows.append([label + ' 次数（占决策 %）', f"{a['action_distribution'][key]} ({a['action_percentages'][key]:.2f}%)", f"{b['action_distribution'][key]} ({b['action_percentages'][key]:.2f}%)"])
        for seat in pair['seats']:
            all_rows.append([f"候选座位 {seat['candidate_seat']} · 胜平负", wdl(seat['candidate']), wdl(seat['opponent'])])
            all_rows.append([f"候选座位 {seat['candidate_seat']} · 半平得分", pct(score(seat['candidate'])), pct(score(seat['opponent']))])
        full_md.append('### ' + title + '\n\n' + mdtable(hdr, all_rows))
        detail_html.append('<details class="detail-pair"><summary>' + title + f' · {a["games"]} 局</summary><div class="table-wrap">' + table(hdr, all_rows) + '</div></details>')

    extra_profile_rows = []
    for label, key in [('0–1 分牌占全部购牌', 'low_share'), ('前 12 步买入小牌 / 局', 'early_low_cards_per_game'), ('早期折扣的后续兑现计数 / 局', 'early_discount_redemptions_per_game'), ('本人第 12 步得分', 'own_main_12_vp_mean'), ('本人第 24 步得分（仍有该步的对局）', 'own_main_24_vp_mean')]:
        extra_profile_rows.append([label] + [pct(models[k][key]) if key == 'low_share' else f'{models[k][key]:.3f}' for k in ['base', 'a', 'style-reference']])
    extra_profile_rows.append(['第 24 步覆盖'] + [f"{models[k]['own_main_24_survival_coverage_games']}/3072 · {pct(models[k]['own_main_24_survival_coverage'])}" for k in ['base', 'a', 'style-reference']])
    extra_profile = table(['补充指标', 'M75 c20', 'M79 c20', 'Balance v0.2.0'], extra_profile_rows)
    css = (ROOT / 'scripts/templates/m79-reading-r3.css').read_text(encoding='utf-8')
    js = (ROOT / 'scripts/templates/m79-reading-r3.js').read_text(encoding='utf-8')
    page = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="M79 对父代取得优势，但共同池增益不足，启发式对局退步。查看完整对照与下一步判断。"><title>M79：赢了父代，暂不替换 M75 · Prism 研究报告</title><style>{css}</style></head>
<body><header class="topbar"><div class="shell"><a class="brand" href="reports.html" style="text-decoration:none"><em>P</em> PRISM / RESEARCH</a><nav class="toplinks" aria-label="文档"><a href="#matches">看对战结果</a><a href="#evidence">完整证据</a></nav></div></header>
<main class="shell"><div class="masthead"><p class="eyebrow">M79 / 有限追加训练 / 2026.10.14</p><h1>赢了父代，<span class="title-phrase">够不够接班？</span></h1><p class="intro">从 M75 c20 出发，再训练 5,120 局。本轮要回答：棋力能否继续提高，同时守住对旧对手的表现。</p></div>
<section class="hero" aria-label="本轮结论"><div class="hero-main"><div><p class="eyebrow">先看结论</p><h2>对父代有优势，<br>整体提升还不够。</h2><p>M79 与 M75 直接交手占优；换一组对手，收益与退步并存。共同池增益未达到约定标准，对启发式的退步也超出容忍门。</p></div><aside class="decision"><span>当前选择</span><strong>保留 M75 作为主线父候选</strong><p>M79 权重有效，留作后续比较候选。<br>本轮不晋级；行为路线仍待定。</p></aside></div>
<div class="hero-facts"><div class="hero-fact"><span class="label">M79 直接对父代</span><b class="positive">54.35<small>% 半平得分</small></b><span class="foot">1,024 局 · 直接增强门通过</span></div><div class="hero-fact"><span class="label">六对手共同池增益</span><b>+1.61<small>个百分点</small></b><span class="foot">要求至少 +2，且统计下界大于 0</span></div><div class="hero-fact"><span class="label">对启发式的变化</span><b class="negative">−5.18<small>个百分点</small></b><span class="foot">旧锚点保留门未通过</span></div></div></section>
<p class="reading-note"><strong>这页的“得分”：</strong>赢一局记 1，平局记 0.5，输局记 0。全部对局双方均选各自评分最高的动作（greedy）；表中变化为 M79 减 M75。</p>
<nav class="jumpnav" aria-label="报告目录"><a href="#matches"><span>01</span> 哪些对手涨跌</a><a href="#gates"><span>02</span> 为什么没过门</a><a href="#profile"><span>03</span> 下法变了多少</a><a href="#decision"><span>04</span> 产物与建议</a><a href="#evidence"><span>05</span> 查完整数据</a></nav>
<section class="section" id="matches"><div class="section-head"><span class="number">01</span><h2>八个对手，六升两降</h2></div><p class="lede">提升最多的是 <strong>Alpha v0.1.5（+7.32 个百分点）</strong>；代价集中在<strong>启发式（−5.18）</strong>和 Balance v0.1.0（−2.25）。对较新 Alpha、Balance 的得分也提高了。</p>
<div class="tabletop"><div class="segmented js-only" aria-label="选择对手集合"><button data-filter="all" aria-pressed="true">全部 8 个</button><button data-filter="common" aria-pressed="false">共同池 6 个</button><button data-filter="coverage" aria-pressed="false">新增覆盖 2 个</button></div><div class="legend"><i></i>提高<i class="bad"></i>降低 · 粗体为较高得分</div></div>
<table id="opponent-table" class="match-table"><thead><tr><th scope="col">对手</th><th scope="col">父代 M75 c20</th><th scope="col">本轮 M79 c20</th><th scope="col">变化 / 百分点</th><th scope="col" class="chart-col">← 降低　提高 →</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<div class="pooled"><div class="description"><strong>六对手共同池</strong><br>这是原合同指定的总体比较；每个模型 3,072 局。</div><div class="total">75.67% → 77.28%<small>父代 M75 → M79</small></div><div class="total pos">+1.61<small>个百分点</small></div></div>
<p class="subnote" id="filter-summary" aria-live="polite">显示 8 个对手 · 每个模型对每个对手 512 局</p><p class="subnote">此表全部来自本轮匹配评测。M75 在 M79 这轮测得的数值，与上一轮报告使用的种子集合不同，不能直接拿旧百分比相减。</p>
<div class="direct"><div class="direct-head"><h3>直接交手：M79 对 M75</h3><span class="tag">直接增强门通过</span></div><p><strong>551 胜 · 11 平 · 462 负</strong>，半平得分 54.35%，95% 区间 51.27%–57.37%。纯胜率为 53.81%。</p><div class="record" aria-hidden="true"><div></div><div></div><div></div></div><div class="record-labels"><span>M79 胜 551</span><span>平 11</span><span>M75 胜 462</span></div></div></section>
<section class="section" id="gates"><div class="section-head"><span class="number">02</span><h2>两个条件没过，所以暂不接班</h2></div><p class="lede">“增强推荐”需要同时满足直接交手、共同池提升和关键对手保留。<strong>赢父代只是其中一项。</strong>以下门槛在评测前已经约定。</p>
<div class="gate-grid"><article class="gate"><span class="tag">通过</span><h3>① 能不能赢父代</h3><div class="gvalue pos">54.35%</div><p>区间整体高于 50%，直接对战的优势得到支持。</p><div class="ci-label">95% 区间：51.27%–57.37%</div><div class="requirement">约定：得分至少 52%，且统计下界高于 50%。</div></article>
<article class="gate"><span class="tag warn">未通过</span><h3>② 总体增益够不够</h3><div class="gvalue">+1.61 <small>个百分点</small></div><p>点估计未达到 +2；区间也跨过了 0，尚不能确认共同池整体增强。</p><div class="ci-label">95% 区间：−0.31 ～ +3.53 个百分点</div><div class="requirement">约定：共同池至少提高 2 个百分点，且统计下界大于 0。</div></article>
<article class="gate"><span class="tag warn">未通过</span><h3>③ 旧对手守住没有</h3><div class="gvalue neg">−5.18 <small>个百分点</small></div><p>对启发式从 91.50% 降到 86.33%；区间整体低于 0，退步值得单独诊断。</p><div class="ci-label">95% 区间：−8.79 ～ −1.56 个百分点</div><div class="requirement">约定：启发式增益的统计下界不低于 −3 个百分点；实际为 −8.79。</div></article></div>
<div class="meaning"><strong>该怎么理解：</strong>M79 有局部优势，也付出了可见代价。本轮足以保留这个候选，尚不足以按原标准推荐它替代 M75；不等于认定 M79 对所有对手都更弱。</div>
<details class="details"><summary>展开全部判定：其他保留条件与区间计算</summary><div class="inside table-wrap">{table(['比较项', '实测', '95% 区间', '预先门槛', '结论'], gate_rows, 'plain-table method-table')}<p class="subnote">除直接交手外，估计与区间单位均为百分点。按相同环境种子、双座位配对，以种子块重采样 20,000 次；共同池六个对手等权。表中 95% 区间沿用冻结统计结果，本轮判门所用下界与所示下界一致。逐对手升降表是点估计，不把每一项都称作已确认提升。</p></div></details></section>
<section class="section" id="profile"><div class="section-head"><span class="number">03</span><h2>下法接近父代，没有形成清晰新路线</h2></div><p class="lede">以下只比较六对手共同池，各模型 3,072 局。相对 M75，M79 的大牌贡献、首次大牌时点和小牌购买量都很接近。</p>
<div class="tabletop"><div class="segmented js-only" aria-label="画像参照"><button data-reference="parent" aria-pressed="true">与父代 M75 比</button><button data-reference="style" aria-pressed="false">与固定 Balance 比</button></div><span class="legend">描述行为 · 不按高低判优劣</span></div>
<div class="profile-layout"><div class="profile-table">{profile_panel('base', 'parent')}{profile_panel('style-reference', 'style')}</div><aside class="profile-aside"><h3>路线仍待定</h3><p>新增训练没有带来足以区分新路线的画像变化。不能因为赢了父代，就把它归入 Alpha；也不能因路线未定就否定全部竞技价值。</p><p>与固定 Balance v0.2.0 比，M79 的大牌贡献更高、首次大牌更早，但贵族覆盖更低。这些是当前对手集上的描述，尚未构成风格确认。</p><div class="mini-stats"><div><b>+0.03</b><span>大牌印刷分 / 局，较父代</span></div><div><b>−0.02</b><span>首次大牌步数，较父代</span></div></div></aside></div>
<details class="details"><summary>展开早期投资、兑现、得分时点与口径</summary><div class="inside table-wrap">{extra_profile}<p class="subnote">“步”指本人常规行动（Main），贵族选择不额外计一步。首次大牌时点只对实际买到 4–5 分牌的局求均值，覆盖率另列。前 12 步统计覆盖全部对局；第 24 步均分只含仍有该步的局，提前结束局不补终局分。</p><p class="subnote">兑现计数沿用原画像：前 12 步买入的低分牌折扣，在随后至第 24 步的真实购牌中被使用；每次投资最多计 3、每局最多计 24。它描述实际折扣使用，不等同于节省宝石的因果估计。</p><p class="subnote">本版贵族覆盖使用已审计比赛汇总中的“获得贵族局数 ÷ 总局数”，纠正旧画像字段与该定义不符的问题。原文件、原路线结论保留；更正明细见审计说明。</p></div></details></section>
<section class="section" id="decision"><div class="section-head"><span class="number">04</span><h2>模型留档，下一步先解释退步</h2></div><p class="lede">本轮已完成训练、评测和交付；研究结果是<strong>未通过增强推荐门</strong>。有效权重和完整对战证据都有保留。</p>
<div class="lineage"><div class="node"><small>上一代</small><b>M75 c20</b><p>本轮固定训练父候选</p></div><div class="arrow">→</div><div class="node"><small>本轮追加</small><b>5,120 局</b><p>沿用架构与既定训练方案</p></div><div class="arrow">→</div><div class="node"><small>固定最终产物</small><b>M79 c20</b><p>审计通过 · 留作比较候选</p></div></div>
<div class="recommendation"><div><h3>现在怎么用</h3><p><strong>M75 继续作为主线父候选。</strong>M79 留档用于对照和后续研究；没有发布、默认替换或应用部署。</p></div><div><h3>后续优先做什么</h3><p><strong>先用已有回放诊断启发式与旧 Balance 的退步。</strong>查清损失集中在哪些局面，再决定是否调整训练方案；目前证据不足以支持无差别继续加训。</p></div></div>
<div class="inventory"><span>训练 5,120 / 5,120</span><span>独立评测 12,288 / 12,288</span><span>独立评测 0 缺局 · 0 截断</span><span>固定 c20 审计通过</span></div><p class="subnote">独立评测构成：共同池 3 模型 × 6 对手 × 512 局，加 M75/M79 的新增覆盖 2 × 2 × 512 局，再加父子直接对战 1,024 局。开发评测另有 1,023 个终局和 1 个保留的历史截断，不混入以上独立结论。ALL 同步仍待处理。</p></section>
<section class="section" id="evidence"><div class="section-head"><span class="number">05</span><h2>完整数据与核验入口</h2></div><p class="lede">日常阅读到这里即可。需要复算时，下面保留全部 23 组对战的双方数据、原始判门和来源绑定。</p>
<div class="library"><a href="m79-prism-mainline-comparison-r3.reading.md"><span>↗</span>本版完整 Markdown<small>主结论、23 组双方表、座位与动作</small></a><a href="m79-prism-mainline-comparison-r3.audit.md"><span>↗</span>本版审计与更正<small>来源 SHA、贵族覆盖修正与验证边界</small></a><a href="m79-prism-mainline-comparison.audit.html"><span>↗</span>原始竞技审计<small>冻结门槛、逐局证据和执行记录</small></a><a href="m79-prism-mainline-evidence.md"><span>↗</span>原始完整证据<small>保留旧结果与原有统计表</small></a><a href="m79-prism-mainline-candidate-profile-r37.json"><span>↗</span>原画像数据<small>含旧贵族字段；采用本版审计更正值</small></a><a href="../m79-prism-mainline.md"><span>↗</span>轮次记录<small>设计、执行修订与交付过程</small></a></div>
<details class="details" id="full-data"><summary>在本页展开全部 23 组双方数据</summary><div class="inside"><p class="scroll-note">每组可单独展开。窄屏内的完整表可以横向滚动；贵族选择动作次数与获得贵族局数是不同指标。</p>{''.join(detail_html)}</div></details></section>
</main><footer class="shell">M79 · 阅读修订 r3 · 仅重写报告，0 新对局。原竞技结果与判门保持不变。<br>候选权重 <code>ecb5d3a3e371…60a17b</code> · <a href="m79-prism-mainline-comparison-r2.html">保留的 r2 旧版</a> · <a href="reports.html">全部研究报告</a></footer><script>{js}</script></body></html>'''
    markdown = '''# M79：赢了父代，暂不替换 M75

M79 对父代半平得分 54.35%，直接增强门通过；六对手共同池只提高 1.61 个百分点，未达到预先要求；启发式下降 5.18 个百分点，旧锚点保留门未通过。保留 M75 作为主线父候选，M79 留作比较候选，路线待定，不晋级。

双方 greedy。半平得分 = (胜 + 0.5 × 平) / 局数；变化 = M79 − M75。

## 匹配对手比较

''' + mdtable(['对手', 'M75 得分', 'M79 得分', '变化', 'M75 胜平负', 'M79 胜平负'], mdrows) + '''

共同池 M75 75.67%，M79 77.28%，各 3072 局。直接交手 M79 551 胜、11 平、462 负，半平得分 54.35%，95% 区间 51.27%–57.37%。

## 原冻结判定

''' + mdtable(['比较项', '实测', '95% 区间', '预先门槛', '结论'], gate_rows) + '''

除直接交手外，估计与区间单位为百分点。区间来自冻结的同种子、双座位配对重采样 20000 次。共同池六对手等权。直接赢父代不代表覆盖面全部通过；本轮也不支持“对所有对手都更弱”。

## 行为画像

各模型在六共同对手上 3072 局。M79 对比 M75：大牌印刷分 8.49 vs 8.46 / 局；首次 4–5 分牌第 19.71 vs 19.72 步，购入覆盖 2657/3072 vs 2637/3072；小牌购买量 6.74 vs 6.75 / 局。贵族覆盖更正为 888/3072（28.91%）vs 899/3072（29.26%）；固定 Balance v0.2.0 为 1209/3072（39.36%）。行为路线仍待定，以上描述不构成风格确认。

''' + mdtable(['补充指标', 'M75 c20', 'M79 c20', 'Balance v0.2.0'], extra_profile_rows) + '''

步指本人常规行动，贵族选择不额外计步。第24步均分仅含仍有该步的局，覆盖率另列。早期兑现指前12步低分牌折扣在之后至第24步的真实购牌中被使用，每投资最多计3、每局最多计24；不是因果宝石节省量。

## 产物与建议

训练5120/5120、固定c20审计通过；独立评测12288/12288，无缺局、无截断。开发评测1023终局及1历史截断另列。权重有效，未晋级、未发布、未部署。ALL仍待同步。

建议保留M75主线父候选，先用已有回放诊断启发式和旧Balance退步，再决定训练调整。本报告任务不启动新训练或对局。

## 完整双方数据

纯胜率与半平得分分别列出；购牌、折扣为每局均值，动作次数及占比按双方各自的决策总数计算。每组包含双方座位胜平负。更完整原始座位指标和宏观时钟见保留的原始证据。

''' + '\n\n'.join(full_md) + '\n\n[原始完整证据](m79-prism-mainline-evidence.md) · [本版审计更正](m79-prism-mainline-comparison-r3.audit.md)\n'
    audit = '# M79 阅读修订 r3：证据与更正\n\n仅离线读取现有结果，0 新对局、0 模型前向。竞技判门、冻结结果、原画像和 r2 均未改写。\n\n## 输入绑定\n\n' + mdtable(['来源', '文件', 'SHA256'], [[k, v['path'], v['sha256']] for k, v in spec['sources'].items()])
    audit += '\n\n## 贵族覆盖更正\n\n原画像 noble_coverage 与“获得贵族局数/总局数”的定义不符。本阅读修订从结果 pairs 中六共同对手的 candidate_metrics.games_with_nobles 求和，再除以3072；双方座位计数加总核对一致。不修改原画像或重判原风格政策。此处只更正描述值。\n\n' + mdtable(['模型', '旧字段值', '获得贵族局数', '分母', '更正覆盖'], [[NAMES[k], v['previous_profile_coverage'], v['games_with_nobles'], v['games'], pct(v['coverage'])] for k, v in corrected_nobles.items()])
    audit += '\n\n## 检查范围\n\n生成时验证6项输入SHA；23组胜平负、双方互补、座位加总、局数网格；共同池与直接对战及4个单对手端点估计复算；画像样本数、大牌印刷分和首次大牌覆盖复算。置信区间复用原冻结统计，未重新bootstrap或审计全部原始回放。原始完整Markdown保留所有宏观/座位细节。\n\n视觉与交互检查单独记录在 reading-receipt.json；生成文件不代表视觉通过。\n\n## 原统计（完整保留）\n\n```json\n' + json.dumps({'bootstrap': result['statistics']['bootstrap'], 'endpoints': endpoints, 'mainline_recommendation': result['statistics']['mainline_recommendation']}, ensure_ascii=False, indent=2) + '\n```\n'
    for key, text in [('output', page), ('markdown', markdown), ('audit', audit)]:
        (ROOT / spec[key]).write_text(text, encoding='utf-8')
    receipt = {'format': 'prism-m79-editorial-reading-receipt-v1', 'revision': 'r3', 'new_games': 0,
               'source_spec_sha256': sha(SPEC), 'data_checks': 'PASS', 'visual': 'NOT_VERIFIED',
               'checks': ['source_hashes', '23_pair_counts_and_actor_reciprocity', 'seat_sums', '12288_grid', 'six_endpoint_point_estimates', 'profile_counts_and_formulas'],
               'noble_coverage_correction': corrected_nobles,
               'outputs': {k: {'path': spec[k], 'sha256': sha(ROOT / spec[k])} for k in ['output', 'markdown', 'audit']},
               'generator': {'path': str(Path(__file__).relative_to(ROOT)), 'sha256': sha(Path(__file__))},
               'assets': {str(p.relative_to(ROOT)): sha(p) for p in [ROOT / 'scripts/templates/m79-reading-r3.css', ROOT / 'scripts/templates/m79-reading-r3.js']}}
    (ROOT / spec['receipt']).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': spec['output'], 'data_checks': 'PASS', 'visual': 'NOT_VERIFIED', 'pairs': len(pairs), 'new_games': 0}, ensure_ascii=False))


if __name__ == '__main__':
    build()
