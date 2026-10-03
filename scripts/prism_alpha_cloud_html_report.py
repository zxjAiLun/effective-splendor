"""Standalone M59 HTML presentation of the immutable full Markdown report."""
import hashlib
import html
import json
from pathlib import Path
import re

import markdown

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/prism/prism-alpha-cloud-m59-evaluation.md'
RESULT = ROOT / 'benchmarks/m59-prism-alpha-cloud-ppo.evaluation-result.json'
OUTPUT = ROOT / 'docs/prism/prism-alpha-v0.1.2-comparison.html'

CSS = '''
:root{color-scheme:light;--ink:#192e33;--muted:#5a6c70;--line:#d9e3e0;--up:#087f71;--down:#9a661d}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:80px}body{margin:0;background:#f4f7f5;color:var(--ink);font:16px/1.65 "Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:1200px;margin:auto;padding:42px 30px 80px}header{margin-bottom:30px}.eyebrow{font-size:13px;letter-spacing:.15em;color:var(--muted)}h1{font-size:clamp(30px,4vw,46px);line-height:1.2;margin:14px 0}h2{font-size:25px;margin:0 0 20px}h3{font-size:20px}h4{font-size:17px;margin-top:28px}
.lead{max-width:880px;color:var(--muted)}.chips{display:flex;flex-wrap:wrap;gap:8px}.chip{border:1px solid var(--line);border-radius:20px;padding:4px 13px;font-size:13px;background:white}
nav{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:10px;background:#f4f7f5ef;backdrop-filter:blur(10px);padding:14px 0;margin-bottom:20px;border-bottom:1px solid var(--line)}a{color:#126c68;text-underline-offset:3px}nav a{font-size:14px;text-decoration:none;border:1px solid var(--line);padding:6px 12px;border-radius:6px;background:white}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:22px 0}.card{padding:23px;border-radius:12px;background:#fff;border:1px solid var(--line)}.card .label{color:var(--muted);font-size:14px}.card b{display:block;font-size:32px;color:var(--up);margin:8px 0}.card small{color:var(--muted);display:block}.note{background:#fff6e7;border-left:4px solid #b78235;padding:14px 18px;border-radius:5px;margin:24px 0}
section,.stage,.provenance{background:#fff;border:1px solid var(--line);border-radius:12px;padding:25px;margin:22px 0}.table-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin:16px 0}table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}th{background:#edf4f1;color:#274a48;text-align:left;vertical-align:bottom}th,td{padding:12px 14px;border-bottom:1px solid #e3ebe8;vertical-align:top}td{min-width:85px}td:first-child{min-width:140px;font-weight:500}tbody tr:nth-child(even){background:#fafcfb}tbody tr:hover{background:#f0f7f4}.up{color:var(--up);background:#e9f7f2}.down{color:var(--down);background:#fff5e3}.pass{color:var(--up);font-weight:700}.fail{color:#ad3232;font-weight:700}
details>summary{cursor:pointer;list-style-position:inside;font-weight:650;line-height:1.5}details>summary:hover{color:var(--up)}details[open]>summary{padding-bottom:18px;border-bottom:1px solid var(--line);margin-bottom:20px}.match{border:1px solid var(--line);border-radius:8px;padding:17px;margin:15px 0;background:#fafcfb}.match[open]{background:white}.match>summary{font-size:16px}.source{color:var(--muted);font-size:13px;overflow-wrap:anywhere}code{font-size:.9em;overflow-wrap:anywhere}button{font:inherit;font-size:14px;border:1px solid var(--line);background:white;color:var(--ink);padding:7px 12px;border-radius:6px;cursor:pointer}.tools{display:flex;gap:10px;margin-bottom:18px}.legend{color:var(--muted);font-size:14px}.intro{font-size:14px;color:var(--muted)}footer{color:var(--muted);font-size:13px;margin-top:32px}
@media(max-width:700px){main{padding:24px 14px 50px}.cards{grid-template-columns:1fr;gap:10px}.card{padding:18px}.card b{font-size:28px}section,.stage,.provenance{padding:17px}nav{gap:6px}th,td{padding:9px 10px}h2{font-size:21px}}
@media print{nav,.tools{display:none}body{background:white}main{max-width:none;padding:0}.table-scroll{overflow:visible}details{break-inside:auto}.card{break-inside:avoid}th,td{font-size:10px;padding:5px}section,.stage{border:0;padding:10px 0}details>summary{font-size:14px}}
'''


def render(text):
    result = markdown.markdown(text, extensions=['tables', 'fenced_code'])
    result = re.sub(r'<td>(.*?)</td>', lambda m: '<td class="' +
                    ('up' if '↑' in m[1] else 'down' if '↓' in m[1] else
                     'pass' if '<strong>PASS</strong>' in m[1] else 'fail' if '<strong>FAIL</strong>' in m[1] else '') +
                    '">' + m[1] + '</td>', result, flags=re.S)
    return result.replace('<table>', '<div class="table-scroll"><table>').replace('</table>', '</table></div>')


def stage(text, title, stage_id):
    chunks = re.split(r'^### (.+)$', text, flags=re.M)
    intro = render(chunks[0])
    matches = []
    for i in range(1, len(chunks), 2):
        if chunks[i].startswith('大牌购入时点'):
            matches.append('<h3>' + html.escape(chunks[i]) + '</h3>' + render(chunks[i + 1]))
        else:
            if matches:
                matches.append('</details>')
            matches.append('<details class="match"><summary>' + html.escape(chunks[i]) + '</summary>' + render(chunks[i + 1]))
    if matches:
        matches.append('</details>')
    matches = ''.join(matches)
    return '<section id="' + stage_id + '" class="stage"><h2>' + html.escape(title) + '</h2>' + intro + matches + '</section>'


def main():
    raw = SOURCE.read_bytes()
    source = raw.decode('utf-8')
    result = json.loads(RESULT.read_text(encoding='utf-8'))
    identity = json.loads((ROOT / 'benchmarks/m59-prism-alpha-v0.1.2.model.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(raw).hexdigest() == identity['readable_report_sha256']
    assert hashlib.sha256(RESULT.read_bytes()).hexdigest() == identity['independent_acceptance']['result_sha256']
    assert all(result['gates'].values())
    parts = re.split(r'^## (.+)$', source, flags=re.M)
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}
    m = result['measurements']
    def card(label, value, caption):
        return '<div class="card"><span class="label">' + label + '</span><b>' + value + '</b><small>' + caption + '</small></div>'
    cards = card('本轮保留底线', '3 / 3 PASS', '棋力保护 · 直接竞争力 · 大牌风格')
    cards += card('对父模型 · 半平得分率', f"{m['direct_parent']['mean']*100:.2f}%", f"校正下界 {m['direct_parent']['simultaneous_one_sided_lower']*100:.2f}% · 已确认直接优势")
    cards += card('大牌印刷 VP · AUC24 变化', f"+{m['bigcard_auc24']['mean']:.6f}", f"校正下界 +{m['bigcard_auc24']['simultaneous_one_sided_lower']:.6f} · 已确认风格增强")
    out = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
           '<title>Prism Alpha v0.1.2 · M59 对战评测</title><style>' + CSS + '</style></head><body><main>',
           '<header><div class="eyebrow">PRISM / MODEL REPORT / M59</div><h1>Prism Alpha v0.1.2</h1><p class="lead">大牌冲分模型 · 从 Prism Alpha v0.1.1 继续四轮 PPO，固定最终 c4，以新种子完成独立对战验收。</p><div class="chips"><span class="chip">实验版本已固定</span><span class="chip">1,024 训练局</span><span class="chip">384 开发局</span><span class="chip">4,096 独立验收局</span><span class="chip">cloud1 · 8 GiB · 已停止</span></div></header>',
           '<nav><a href="#overview">结论</a><a href="#comparison">父模型 → 新版本</a><a href="#gates">三项验收门</a><a href="#acceptance">独立完整数据</a><a href="#development">开发完整数据</a><a href="#sources">来源与修复记录</a><a href="prism-alpha-cloud-m59-evaluation.md">Markdown 原文</a></nav>',
           '<div id="overview" class="cards">' + cards + '</div>',
           '<div class="note"><strong>总体棋力增强尚未确认。</strong> 共同三锚点得分率提升 ' + f"{m['strength_pool']['mean']*100:.4f}" + ' 个百分点，但校正下界仍低于 0；本轮确认的是棋力保留底线、直接对父模型优势和大牌风格增强。</div>',
           '<details class="intro"><summary>模型身份、训练产物与工程异常</summary>' + re.sub(r'<h1>(.*?)</h1>', r'<h3>\1</h3>', render(parts[0])) + '</details>',
           '<section id="comparison"><h2>一眼看变化：父模型 → 新版本</h2><p class="legend"><strong>↑ 数值增加 / ↓ 数值减少</strong>：颜色和箭头表示变化方向，不自动代表更好或统计显著。双方指标以表头标注的模型身份为准。</p>' + render(sections.pop('一眼看变化：父模型 → 固定最终候选')) + '</section>',
           '<section id="gates"><h2>三项冻结保留门</h2>' + render(sections.pop('三项冻结保留门')) + '</section>',
           '<div class="tools"><button id="expand" type="button">展开全部详细表</button><button id="collapse" type="button">收起全部详细表</button></div>',
           stage(sections.pop('独立验收'), '独立验收 · 4,096 局', 'acceptance'),
           stage(sections.pop('开发评测（仅描述）'), '开发评测 · 384 局 · 仅描述', 'development'),
           '<details id="sources" class="provenance"><summary>完整来源、计时、运行身份与两局执行修复</summary>']
    for title, text in sections.items():
        out += ['<h2>' + html.escape(title) + '</h2>', render(text)]
    out += ['</details><footer><p>数据来自已冻结 Markdown 和结果 JSON。本页面不重新计算验收、不运行比赛或训练；原训练 OOM 与原评测监控失败保留，仅两局中断重试获用户授权。</p>',
            '<p class="source">Markdown SHA256: ' + hashlib.sha256(raw).hexdigest() + '<br>独立结果 SHA256: ' + hashlib.sha256(RESULT.read_bytes()).hexdigest() + '</p></footer>',
            '</main><script>document.querySelector("#expand").addEventListener("click",()=>document.querySelectorAll("details.match").forEach(d=>d.open=true));document.querySelector("#collapse").addEventListener("click",()=>document.querySelectorAll("details.match").forEach(d=>d.open=false));</script></body></html>']
    document = '\n'.join(out) + '\n'
    expected = sum(1 for line in source.splitlines() if re.match(r'^\|(?:\s*---\s*\|)+\s*$', line))
    assert document.count('<table>') == expected, (document.count('<table>'), expected)
    OUTPUT.write_bytes(document.encode('utf-8'))
    print(json.dumps({'html': str(OUTPUT), 'tables': expected, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                      'html_sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
