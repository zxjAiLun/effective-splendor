"""Add owner-readable M56 conclusions while preserving every measured result."""
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'local-artifacts/prism/alpha-v0.1.1'
RESULT = ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.result.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join('---' for _ in headers) + ' |'] +
                     ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])


def main():
    assert read(ART / 'controller-status.json')['state'] == 'COMPLETE'
    assert not (ART / 'readability-review.json').exists()
    r = read(RESULT)
    assert r['all_three_gates_passed'] and r['confirmed_enhancement'] == {
        'bigcard_auc24': True, 'direct_parent': False, 'strength_pool': False}
    result_sha = sha(RESULT)
    primary = ROOT / 'docs/prism/prism-alpha-v0.1.1-evaluation-summary.md'
    page = ROOT / 'docs/prism/prism-alpha-v0.1.1-comparison.html'
    model = ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.model.json'
    documents = [ROOT / x for x in ('docs/m56-prism-alpha-bigcard-ppo.md',
        'docs/aran-model-evolution-matrix.md', 'docs/m51-prism-model-line.md')]
    handoff = ROOT / 'handoff.md'
    previous_milestone = ROOT / 'docs/m55-prism-rush-style-model.md'
    changed = [primary, page, model, *documents, handoff, previous_milestone]
    control = read(ART / 'controller-contract.json')
    assert all(str(p.relative_to(ROOT)).replace('\\', '/') not in control['files'] for p in changed)
    snapshot = ART / 'readability-review-snapshot'
    snapshot.mkdir()
    originals = {}
    for p in changed + [ART / 'browser-validation.json',
                       ROOT / 'docs/prism/prism-alpha-v0.1.1-comparison.png', ART / 'comparison-mobile.png']:
        originals[str(p.relative_to(ROOT))] = sha(p)
        shutil.copyfile(p, snapshot / p.name)
    common = [p for p in r['acceptance']['pairs'] if p['opponent'] != 'base-t1']
    means = {}
    for who in ('base', 'candidate'):
        pairs = [p for p in common if p['candidate'] == who]
        means[who] = sum(p['candidate_bigcard']['mean_large_card_vp_auc24'] * p['candidate_metrics']['games']
                         for p in pairs) / sum(p['candidate_metrics']['games'] for p in pairs)
    relative = 100 * (means['candidate'] / means['base'] - 1)
    conclusion = (f'本轮可读结论：**大牌取分风格增强，整体棋力保持，尚未证明胜过Alpha父模型。** '
                  f'三个共同对手的匹配样本中，前24次自身主行动的大牌累计分数曲线面积从{means["base"]:.6f}升至{means["candidate"]:.6f}，'
                  f'相对提高**{relative:.2f}%**；预设配对检验的三门校正下界仍大于0。这是大牌兑现指标的增强证据，'
                  '不是终局VP或胜率提高同样百分比。总体得分率与直接对父模型的增强均未获得统计确认。')
    names = {'heuristic-v031': 'Heuristic v0.3.1（greedy）', 'prism-v01': '初代 Prism v0.1.0（greedy）',
             'prism-v0.1.1': 'Prism v0.1.1（T=1）', 'base-t1': '父模型 Prism Alpha v0.1.0（T=1）'}
    summary_rows = []
    for opponent in ('heuristic-v031', 'prism-v01', 'prism-v0.1.1', 'base-t1'):
        p = next(p for p in r['acceptance']['pairs'] if p['candidate'] == 'candidate' and p['opponent'] == opponent)
        m = p['candidate_metrics']
        summary_rows.append([names[opponent], f"{m['games']} / {m['games']//2}",
                             f"{m['win_rate_percent']:.2f}%", f"{100*m['score_rate']:.2f}%"])
    summary = ('## 独立战绩摘要：Prism Alpha v0.1.1（T=1，被测玩家）\n\n' +
               table(['对手 / 动作模式', '局数 / 双座seed块', '纯胜率', '含半平得分率'], summary_rows) +
               '\n\n此处便于速读；完整胜/平/负、配对区间、双方个人指标和物理双座表在后文。直接父模型组是同1,024局的双方；共同对手组各模型512局。')
    old_text = primary.read_text(encoding='utf-8')
    old_intro = next(line for line in old_text.splitlines() if line.startswith('“通过本轮保留底线”与“证明更强”分开：'))
    text = old_text.replace(old_intro, conclusion + '\n\n' + summary, 1)
    next_step = ('本有限轮到此停止。下一步建议仍沿大牌取分方向：先profile目录扫描及外层监督开销，降低每轮实验成本；'
                 '再以Prism Alpha v0.1.1为起点设计一次有限PPO，优先把更强对手加入预设训练配比，争取棋力增益并保留大牌兑现优势。'
                 '训练对手配比应是一个主要变化，暂不加大风格奖励或另开基建/其他风格。上述为PROPOSED；性能实现、新训练、种子与预算尚未执行。')
    old_next = '本有限轮到此停止。下一轮先据本次大牌时点、分段得分与棋力结果判断目标代理是否合适；新训练或其他风格需另定预算/种子/验收。'
    assert old_next in text
    text = text.replace(old_next, next_step, 1)
    primary.write_text(text, encoding='utf-8')
    body = text.split('\n\n', 1)[1]
    begin, end = '<!-- M56 VERIFIED RESULTS BEGIN -->', '<!-- M56 VERIFIED RESULTS END -->'
    for p in documents:
        s = p.read_text(encoding='utf-8')
        assert s.count(begin) == s.count(end) == 1
        a, b = s.index(begin), s.index(end) + len(end)
        old_body = s[a + len(begin):b - len(end)].strip()
        prefix = old_body.split('\n', 1)[0] + '\n\n' if old_body.startswith('## M56 ') else ''
        p.write_text(s[:a] + begin + '\n\n' + prefix + body + '\n\n' + end + s[b:], encoding='utf-8')
    html = page.read_text(encoding='utf-8')
    payload = re.search(r'const data=(.*?);let stage=', html, re.S).group(1)
    assert json.loads(payload) == {stage: r[stage]['pairs'] for stage in ('development', 'acceptance')}
    html, replacements = re.subn(r'<p class="note">通过保留底线与确认增强分别报告。.*?</p>',
                  f'<p class="note">本轮：大牌得分曲线面积提高约{relative:.2f}%（共同对手匹配样本，有统计增强证据）。整体棋力保持，尚未证明胜过Alpha父模型。三条保留底线全部通过。</p>',
                  html, count=1)
    assert replacements == 1
    html = html.replace('<th>父模型</th>', '<th>Prism Alpha v0.1.0</th>', 1)
    html = html.replace("'base-t1':'直接父模型（T=1）'", "'base-t1':'Prism Alpha v0.1.0（T=1，直接对战）'", 1)
    assert re.search(r'const data=(.*?);let stage=', html, re.S).group(1) == payload
    page.write_text(html, encoding='utf-8')
    s = handoff.read_text(encoding='utf-8')
    s = s.replace('### M56 正在执行 — 四轮训练VERIFIED，对战评测进行中', '### M56 历史执行快照 — 已被上方终局结果替代', 1)
    s = s.replace('最新状态以本段及M56执行回执为准。', '最新状态以上方M56终局段与正式结果为准。', 1)
    s = s.replace('### M56 终局 — Prism Alpha v0.1.1\n\n', '### M56 终局 — Prism Alpha v0.1.1\n\n' + conclusion + '\n\n', 1)
    s += '\n\n### M56 完成后的方向建议（2026-10-03，PROPOSED）\n\n' + next_step + '\n'
    handoff.write_text(s, encoding='utf-8')
    p = previous_milestone
    p.write_text(p.read_text(encoding='utf-8') + '\n\n### M56后续结果更正（2026-10-03）\n\n'
                 '此前的大牌方向续训授权已由[M56](m56-prism-alpha-bigcard-ppo.md)完成。固定新实验身份Prism Alpha v0.1.1：'
                 '三项保留底线PASS，大牌AUC24有校正下界增强证据，整体棋力尚未证明胜过Prism Alpha v0.1.0。'
                 '旧M55六门、原负结果与权重保持原记录。下一步建议见M56，当前有限轮停止。\n', encoding='utf-8')
    identity = read(model)
    identity['readable_report_sha256'] = sha(primary)
    identity['colored_comparison_sha256'] = sha(page)
    model.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert sha(RESULT) == result_sha
    assert all(sha(ROOT / name) == digest for name, digest in control['files'].items())
    receipt = {'status': 'PASS', 'scope': 'plain-language outcome, front-page actual win rates, full parent names, proposed next-step order',
               'new_games': 0, 'new_training_steps': 0, 'formal_result_sha256_unchanged': result_sha,
               'original_snapshots': originals, 'relative_large_card_auc24_percent': relative,
               'result_payload_in_html_unchanged': True,
               'report_sha256': sha(primary), 'html_sha256': sha(page), 'model_sha256': sha(model)}
    (ART / 'readability-review.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'PASS：读者结论、大牌AUC24 +{relative:.2f}%、真实胜率摘要及完整父模型名称已收口；结果和76冻结输入不变。')


if __name__ == '__main__':
    main()
