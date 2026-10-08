"""Read-only, offline reading reports. Never imports an evaluator or changes evidence.

Usage: python -B scripts/prism_round_report.py --spec benchmarks/reports/m63-reading.json
The spec contains reviewed editorial statements; numeric views use saved JSON only.
"""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMPLATES = ROOT / 'scripts/templates'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_json(value):
    # A literal closing script tag in a model name must not terminate the payload.
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def relative(path, output):
    try:
        return Path(os.path.relpath(path, output.parent)).as_posix()
    except ValueError:
        # Windows can export a reading report onto a different drive.
        return path.resolve().as_uri()


def load(spec_path):
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    assert spec['format'] == 'prism-reading-spec-v1'
    paths = {k: ROOT / spec[k] for k in ('result', 'markdown', 'output')}
    result = json.loads(paths['result'].read_text(encoding='utf-8'))
    assert sha(paths['result']) == spec['result_sha256'], 'editorial spec bound to a different result'
    assert sha(paths['markdown']) == spec['markdown_sha256'], 'complete source report changed'
    # Registration is performed by a separate owner-authorized publication
    # operation. This reader may display it only with exact artifact binding.
    for key,ref in spec.get('model_releases',{}).items():
        record_path=ROOT/ref['path']
        assert sha(record_path)==ref['sha256'], 'release record drift'
        release=json.loads(record_path.read_text(encoding='utf-8'))
        assert release['status']=='RELEASED_EXPERIMENTAL_MODEL', 'release not completed'
        assert release['weights_sha256']==result['candidate_sha256'][key], 'release weight drift'
        assert sha(ROOT/release['weights_path'])==release['weights_sha256'], 'released export drift'
        assert release['original_result_sha256']==spec['result_sha256'], 'release result drift'
        assert release['display_name']==spec['names'][key], 'release display name drift'
        assert release['authorization']['source']=='human_owner' and release['default_replaced'] is False
    if spec.get('practical_review'):
        review = json.loads((ROOT / spec['practical_review']).read_text(encoding='utf-8'))
        assert review['result_sha256'] == spec['result_sha256'], 'practical review result binding drift'
        assert review['weight_sha256'] == result['candidate_sha256'][spec['focus']], 'route alias weight drift'
        assert review['registration_status']=='NOT_REGISTERED' or (
            review['registration_status']=='RELEASED_EXPERIMENTAL_MODEL' and spec['focus'] in spec.get('model_releases',{})), 'reading layer cannot register a model'
        spec['_practical_review'] = review
    assert set(spec['gates']) == set(result['gates']), 'missing or extra gate explanations'
    for key, meta in spec['gates'].items():
        m = result['measurements'][key]
        lower = m.get('simultaneous_one_sided_lower', m.get('simultaneous_lower'))
        assert isinstance(lower, (float, int))
        assert result['gates'][key] == (lower >= meta['threshold']), 'frozen gate threshold drift: ' + key
        if result['acceptance_policy'].get('gates'):
            assert meta['threshold'] == result['acceptance_policy']['gates'][key]
    for stage in ('acceptance', 'development'):
        record = result.get(stage)
        if not isinstance(record, dict):
            continue
        assert sum(p['candidate_metrics']['games'] for p in record['pairs']) == record['games']
        for pair in record['pairs']:
            for side in ('candidate_metrics', 'opponent_metrics'):
                metrics = pair[side]
                assert sum(metrics[k] for k in ('wins', 'ties', 'losses')) == metrics['games']
                assert abs((metrics['wins'] + .5 * metrics['ties']) / metrics['games'] - metrics['score_rate']) < 1e-10
            assert sum(s['candidate']['games'] for s in pair['seats']) == pair['candidate_metrics']['games']
    return spec, result, paths


def build(spec_path):
    header = json.loads(spec_path.read_text(encoding='utf-8'))
    if header.get('format') == 'prism-greedy-reading-spec-v1':
        from scripts.prism_greedy_reading import build as build_greedy
        return build_greedy(spec_path, ROOT, TEMPLATES)
    spec, result, paths = load(spec_path)
    output = paths['output']; output.parent.mkdir(parents=True, exist_ok=True)
    evidence = output.with_suffix('.evidence.html')
    if output.exists() and not evidence.exists() and not any(marker in output.read_text(encoding='utf-8') for marker in ('prism-reading-report-v1','prism-human-report-v2')):
        evidence.write_bytes(output.read_bytes())
    payload = dict(schema='prism-reading-report-v1', story=spec['story'], gates=spec['gates'],
                   focus=spec['focus'], baseline=spec['baseline'], style_metrics=spec['style_metrics'],
                   names=spec['names'], result=result,
                   practical_review=spec.get('_practical_review'),
                   sources=dict(result=relative(paths['result'], output), markdown=relative(paths['markdown'], output),
                                result_sha256=sha(paths['result']), markdown_sha256=sha(paths['markdown']),
                                original_html=relative(evidence, output) if evidence.exists() else None,
                                original_html_sha256=sha(evidence) if evidence.exists() else None))
    document = (TEMPLATES/'prism-reading.html').read_text(encoding='utf-8')
    document = document.replace('@@TITLE@@', html.escape(spec['story']['title']))
    document = document.replace('@@CSS@@', (TEMPLATES/'prism-reading.css').read_text(encoding='utf-8'))
    document = document.replace('@@DATA@@', safe_json(payload))
    document = document.replace('@@JS@@', (TEMPLATES/'prism-reading.js').read_text(encoding='utf-8'))
    assert '@@' not in document
    audit = output.with_suffix('.audit.html')
    formulas = '<aside class="explain"><h2>Agent 审计与历史研究指标</h2><p>旧基建效用 = min(24, Σ min(3, 每张投资牌后续实际使用次数)) / 24。投资牌：本人前12个Main买入的0–1 VP牌；后续购买至Main24时，某色印刷成本达到该色折扣序号即记一次使用，不等同于反事实节省宝石。</p><p>时间加权效用 = min(24, Σ每张投资牌前3次使用的(25−使用Main序号)/24) / 24。前12Main平均折扣 = Σ前12Main末永久折扣 / 12；仅该描述量对早结束局保持终局值。这些是训练研究代理指标，不是小牌流派或晋级判定器。</p></aside>'
    if spec.get('greedy_results'):
        formulas += '<aside class="explain"><h2>Greedy 补充评测：独立数据与基础设施修复</h2><p>固定2816局；零自动比赛重试，保留46局已完成结果，手工补跑被停止的2局。原失败现场与修复计划保留；不改原M63结果和十门。以下完整补充报告含种子、双方所有指标、runtime与逐局来源。</p>'
        for item in spec['greedy_results']:
            supplement_md = (ROOT/item['result']).with_name('report.md')
            formulas += '<p><a href="'+html.escape(relative(supplement_md,audit))+'">'+html.escape(item['label'])+'完整审计Markdown</a></p>'
        formulas += '</aside>'
    if spec.get('greedy_trajectory'):
        path=ROOT/spec['greedy_trajectory']['path']
        formulas += '<aside class="explain"><p>Alpha路线重评：只读重验已有2816局回放，没有新比赛；所有actor轨迹绑定原greedy来源ledger。<a href="'+html.escape(relative(path,audit))+'">完整轨迹核验、公式与逐批回执</a>。路线推荐不等于正式Alpha继任发布。</p></aside>'
    audit.write_text(document.replace('<body>','<body>'+formulas), encoding='utf-8')
    reading_md = output.with_suffix('.audit.md')
    story = spec['story']
    top = ['# '+story['title'], '', story['headline'], '', '本轮目标：'+story['question'], '',
           '| 结论 | 判断 | 解释 |', '| --- | --- | --- |']
    top += [f"| {s['label']} | **{s['value']}** | {s['explanation']} |" for s in story['conclusions']]
    top += ['', '身份关系：'+story['identity'], '', '怎么理解：'+story['interpretation'], '',
            '下一步建议：'+story['next'], '']
    if spec.get('_practical_review'):
        review = spec['_practical_review']
        top += ['## 实战覆盖面与当前路线', '', review['practical_conclusion'], '',
                '当前归类：**'+review['route_label']+'**。'+review['route_caveat'], '',
                '| 相同独立锚点 | 父代半平得分 | 候选半平得分 | 候选 − 父代 | 候选 − 同轮对照 |',
                '| --- | --- | --- | --- | --- |']
        pairs={(p['candidate'],p['opponent']):p for p in result['acceptance']['pairs']}
        for opponent in result['acceptance_policy']['anchors']:
            base=pairs[review['parent_key'],opponent]['candidate_metrics']['score_rate']
            candidate=pairs[spec['focus'],opponent]['candidate_metrics']['score_rate']
            control=pairs[spec['baseline'],opponent]['candidate_metrics']['score_rate']
            top.append(f"| {spec['names'][opponent]} | {base*100:.2f}% | {candidate*100:.2f}% | **{(candidate-base)*100:+.2f}个百分点** | {(candidate-control)*100:+.2f}个百分点 |")
        top += ['', review['coverage_caveat'], '', '旧研究门只回答原训练假设，原值保留在附录；不将风格目标未达当作模型整体晋级否决。', '']
    top += ['## 独立对战速览（模型本人）', '',
            '| 被测模型 | 对手 | 局数 | 胜 / 平 / 负 | 纯胜率 | 半平得分率 | 配对95%区间（半平） |',
            '| --- | --- | --- | --- | --- | --- | --- |']
    for p in result.get('acceptance', {}).get('pairs', []):
        m = p['candidate_metrics']; ci = p['score_uncertainty']['ordinary_95_ci']
        top.append(f"| {spec['names'].get(p['candidate'],p['candidate_display'])} | {spec['names'].get(p['opponent'],p['opponent_display'])} | {m['games']} | {m['wins']} / {m['ties']} / {m['losses']} | {m['win_rate_percent']:.2f}% | {100*m['score_rate']:.2f}% | [{100*ci[0]:.2f}%, {100*ci[1]:.2f}%] |")
    top += ['', '半平得分 = 胜计1、平计0.5、负计0；区间跨50%不代表已证明势均力敌。原门使用校正下界，不由上面的描述区间改判。', '',
            '## 完整原始报告（含所有双方、座位、阶段、来源表）', '',
            '<details>', '<summary>展开完整原文与全部Markdown表</summary>', '',
            paths['markdown'].read_text(encoding='utf-8'), '', '</details>', '']
    reading_md.write_text('\n'.join(top), encoding='utf-8')
    if spec.get('greedy_results'):
        with reading_md.open('a',encoding='utf-8') as stream:
            for item in spec['greedy_results']:
                stream.write('\n\n# '+item['label']+' / independent supplementary audit\n\n')
                stream.write((ROOT/item['result']).with_name('report.md').read_text(encoding='utf-8'))
    from scripts.prism_human_report import build_human
    history = build_human(ROOT,TEMPLATES,spec,result,output,safe_json,relative)
    human_md = output.with_suffix('.reading.md')
    receipt = dict(format='prism-reading-receipt-v1', result_sha256=sha(paths['result']),
                   complete_markdown_sha256=sha(paths['markdown']), spec_sha256=sha(spec_path),
                   html_sha256=sha(output), reading_markdown_sha256=sha(human_md),
                   audit_html_sha256=sha(audit), audit_markdown_sha256=sha(reading_md),
                   sampling_html_sha256=sha(history),
                   original_html_sha256=sha(evidence) if evidence.exists() else None,
                   preserved_source_tables=len(re.findall(r'^\|(?:\s*---\s*\|)+\s*$', paths['markdown'].read_text(encoding='utf-8'), re.M)),
                   games_dispatched=0, gate_values_changed=False)
    if spec.get('_practical_review'):
        receipt['practical_review_sha256'] = sha(ROOT/spec['practical_review'])
        receipt['route_assignment'] = spec['_practical_review']['route_label']
        receipt['original_research_verdict'] = result.get('verdicts')
    if spec.get('greedy_trajectory'):
        receipt['greedy_trajectory_sha256']=spec['greedy_trajectory']['sha256']
    output.with_suffix('.reading-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    print(json.dumps(build(parser.parse_args().spec), ensure_ascii=False, indent=2))
