"""Standalone M62 HTML presentation of the immutable full Markdown report."""
import hashlib
import html
import json
from pathlib import Path
import re

import markdown

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/prism/m62-prism-beta-building-evaluation.md'
RESULT = ROOT / 'local-artifacts/prism/building-beta-m62/evaluation/result.json'
OUTPUT = ROOT / 'docs/prism/m62-prism-beta-building-comparison.html'

CSS = '''
:root{color-scheme:light;--ink:#192e33;--muted:#5a6c70;--line:#d9e3e0;--up:#087f71;--down:#9a661d;--fail:#b22222;--pass:#087f71}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:80px}body{margin:0;background:#f4f7f5;color:var(--ink);font:16px/1.65 "Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:1240px;margin:auto;padding:42px 30px 80px}header{margin-bottom:30px}.eyebrow{font-size:13px;letter-spacing:.15em;color:var(--muted)}h1{font-size:clamp(28px,3.8vw,44px);line-height:1.2;margin:14px 0}h2{font-size:24px;margin:0 0 20px}h3{font-size:19px;margin:24px 0 14px}h4{font-size:16px;margin-top:24px}
.lead{max-width:920px;color:var(--muted)}.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.chip{border:1px solid var(--line);border-radius:20px;padding:4px 13px;font-size:13px;background:white}.chip-fail{border-color:#e8b5b5;background:#fdf2f2;color:var(--fail);font-weight:600}
nav{position:sticky;top:0;z-index:10;display:flex;flex-wrap:wrap;gap:10px;background:#f4f7f5ef;backdrop-filter:blur(10px);padding:14px 0;margin-bottom:20px;border-bottom:1px solid var(--line)}a{color:#126c68;text-underline-offset:3px}nav a{font-size:14px;text-decoration:none;border:1px solid var(--line);padding:6px 12px;border-radius:6px;background:white;transition:background .15s}nav a:hover{background:#edf4f1}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:22px 0}.card{padding:22px;border-radius:12px;background:#fff;border:1px solid var(--line)}.card .label{color:var(--muted);font-size:14px}.card b{display:block;font-size:30px;color:var(--ink);margin:8px 0}.card b.pass{color:var(--pass)}.card b.fail{color:var(--fail)}.card small{color:var(--muted);display:block;line-height:1.4}.note{background:#fff6e7;border-left:4px solid #b78235;padding:14px 18px;border-radius:5px;margin:24px 0}.note-fail{background:#fdf4f4;border-left:4px solid var(--fail);padding:14px 18px;border-radius:5px;margin:24px 0}
section,.stage,.provenance{background:#fff;border:1px solid var(--line);border-radius:12px;padding:25px;margin:22px 0}.table-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin:16px 0}table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}th{background:#edf4f1;color:#274a48;text-align:left;vertical-align:bottom}th,td{padding:10px 12px;border-bottom:1px solid #e3ebe8;vertical-align:top}td{min-width:80px}td:first-child{min-width:130px;font-weight:500}tbody tr:nth-child(even){background:#fafcfb}tbody tr:hover{background:#f0f7f4}.up{color:var(--up);background:#e9f7f2}.down{color:var(--down);background:#fff5e3}.pass{color:var(--pass);font-weight:700}.fail{color:var(--fail);font-weight:700}
details>summary{cursor:pointer;list-style-position:inside;font-weight:650;line-height:1.5}details>summary:hover{color:var(--up)}details[open]>summary{padding-bottom:16px;border-bottom:1px solid var(--line);margin-bottom:18px}.match{border:1px solid var(--line);border-radius:8px;padding:16px;margin:14px 0;background:#fafcfb}.match[open]{background:white}.match>summary{font-size:15.5px}.source{color:var(--muted);font-size:13px;overflow-wrap:anywhere}code{font-size:.88em;overflow-wrap:anywhere;background:#f3f6f5;padding:2px 4px;border-radius:4px}pre code{display:block;padding:12px;overflow-x:auto}button{font:inherit;font-size:14px;border:1px solid var(--line);background:white;color:var(--ink);padding:7px 12px;border-radius:6px;cursor:pointer;transition:background .15s}button:hover{background:#edf4f1}.tools{display:flex;gap:10px;margin-bottom:18px}.legend{color:var(--muted);font-size:14px}.intro{font-size:14px;color:var(--muted)}footer{color:var(--muted);font-size:13px;margin-top:32px}
@media(max-width:768px){main{padding:24px 14px 50px}.cards{grid-template-columns:1fr;gap:10px}.card{padding:18px}.card b{font-size:26px}section,.stage,.provenance{padding:16px}nav{gap:6px}th,td{padding:8px 9px}h2{font-size:20px}}
@media print{nav,.tools{display:none}body{background:white}main{max-width:none;padding:0}.table-scroll{overflow:visible}details{break-inside:auto}.card{break-inside:avoid}th,td{font-size:10px;padding:5px}section,.stage{border:0;padding:10px 0}details>summary{font-size:14px}}
'''


def render(text):
    result = markdown.markdown(text, extensions=['tables', 'fenced_code'])
    result = re.sub(
        r'<td>(.*?)</td>',
        lambda m: '<td class="' + (
            'up' if '↑' in m[1] else
            'down' if '↓' in m[1] else
            'pass' if '<strong>PASS</strong>' in m[1] or m[1].strip() == 'PASS' else
            'fail' if '<strong>FAIL</strong>' in m[1] or m[1].strip() == 'FAIL' or m[1].strip() == 'NOT_ACCEPTED_BUILDING_CANDIDATE' else ''
        ) + '">' + m[1] + '</td>',
        result,
        flags=re.S
    )
    return result.replace('<table>', '<div class="table-scroll"><table>').replace('</table>', '</table></div>')


def stage(text, title, stage_id):
    chunks = re.split(r'^### (.+)$', text, flags=re.M)
    intro = render(chunks[0])
    matches = []
    inside_match = False
    for i in range(1, len(chunks), 2):
        heading = chunks[i]
        body = chunks[i + 1]
        if heading.endswith('：完整双方数据'):
            if inside_match:
                matches.append('</details>')
            matches.append('<details class="match"><summary>' + html.escape(heading) + '</summary>' + render(body))
            inside_match = True
        else:
            matches.append('<h3>' + html.escape(heading) + '</h3>' + render(body))
    if inside_match:
        matches.append('</details>')
    matches = ''.join(matches)
    return '<section id="' + stage_id + '" class="stage"><h2>' + html.escape(title) + '</h2>' + intro + matches + '</section>'


def main():
    raw = SOURCE.read_bytes()
    source = raw.decode('utf-8')
    result = json.loads(RESULT.read_text(encoding='utf-8'))

    parts = re.split(r'^## (.+)$', source, flags=re.M)
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}

    def card(label, value, caption, cls=''):
        return f'<div class="card"><span class="label">{label}</span><b class="{cls}">{value}</b><small>{caption}</small></div>'

    cards = card('Control 参照保留门', '2 / 2 PASS', '总体棋力保留 · 对父竞争力', 'pass')
    cards += card('Beta 七项核心验收门', '3 PASS / 4 FAIL', '通用锚点 · 直接对决 · 风格门未过', 'fail')
    cards += card('基建风格双重判定', 'FAIL', 'building效用与早期bonus下界未达', 'fail')

    out = [
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Prism Beta v0.1.0 candidate / Prism Balance v0.1.1 candidate · M62 对战评测</title>',
        f'<style>{CSS}</style></head><body><main>',
        '<header><div class="eyebrow">PRISM / MODEL REPORT / M62</div>',
        '<h1>Prism Beta v0.1.0 candidate / Prism Balance v0.1.1 candidate</h1>',
        '<p class="lead">基建风格探索与同起点 Outcome-Only 对照 · 从同一 Prism Balance v0.1.0 (seed 62041001) 分出 Control 与 Beta，各串行训练 1,024 局（共 2,048 局），以固定最终 c4 完成 9,280 局独立双座评测。</p>',
        '<div class="chips"><span class="chip chip-fail">未发布训练候选（NOT_ACCEPTED）</span>',
        '<span class="chip">2,048 训练局</span><span class="chip">576 开发局</span><span class="chip">8,704 独立验收局（共 9,280 局）</span>',
        '<span class="chip">cloud1 · 8 GiB · 0 重试</span><span class="chip">九门同时Bootstrap下界</span></div></header>',
        '<nav><a href="#overview">结论</a><a href="#comparison">锚点变化</a><a href="#gates">九项采样前冻结门</a><a href="#acceptance">独立验收 (8,704局)</a><a href="#development">开发评测 (576局)</a><a href="#sources">来源与执行合同</a><a href="m62-prism-beta-building-evaluation.md">Markdown 原文</a></nav>',
        f'<div id="overview" class="cards">{cards}</div>',
        '<div class="note-fail"><strong>Beta 基建风格候选未通过验收（NOT_ACCEPTED_BUILDING_CANDIDATE）。</strong> 虽然 Beta 在对固定 Alpha 大牌对手（半平得分率 54.98%，下界 50.98% &ge; 45%）和对父模型（51.81%，下界 47.95% &ge; 45%）上保住了底线竞争力，但在关键通用锚点（对 Prism v0.1.1 得分率差 -1.56%，单侧下界 -8.89% &lt; -7.5%）、对 Control 直接对决（48.00%，单侧下界 43.95% &lt; 45.0%）以及两项基建风格门（归一化building效用差 +0.0033，单侧下界 -0.0056 &lt; 0.015；非reward早期bonus AUC12差 +0.0186 折扣，单侧下界 +0.0004 &lt; 0.25）均未能跨过预注册单侧下界。按 fail-closed 契约，两候选均不发布、不登记、不晋升。</div>',
        '<details class="intro"><summary>模型身份、产物审计与验收判决</summary>' + re.sub(r'<h1>(.*?)</h1>', r'<h3>\1</h3>', render(parts[0])) + '</details>',
        '<section id="comparison"><h2>一眼看变化：父 → control → Beta</h2><p class="legend"><strong>↑ 数值增加 / ↓ 数值减少</strong>：颜色和箭头表示变化方向，不自动代表更好或统计显著。双方指标以表头标注的模型身份为准。</p>' + render(sections.pop('匹配共同锚点：父 → control → Beta')) + '</section>',
        '<section id="gates"><h2>九项采样前冻结门</h2>' + render(sections.pop('九项采样前冻结门')) + '</section>',
        '<section id="direction"><h2>开发与独立方向对比</h2>' + render(sections.pop('开发与独立方向')) + '</section>',
        '<section id="records"><h2>原验收与增强记录</h2>' + render(sections.pop('原验收与增强记录')) + '</section>',
        '<div class="tools"><button id="expand" type="button">展开全部详细表</button><button id="collapse" type="button">收起全部详细表</button></div>',
        stage(sections.pop('独立验收'), '独立验收 · 8,704 局', 'acceptance'),
        stage(sections.pop('开发评测（仅描述）'), '开发评测 · 576 局（仅描述）', 'development'),
        '<details id="sources" class="provenance"><summary>完整来源、计时、执行合同与审计回执</summary>'
    ]

    for title, text in sections.items():
        out += [f'<h2>{html.escape(title)}</h2>', render(text)]

    out += [
        '</details><footer><p>数据来自已冻结 Markdown (7.8 MB) 和独立结果 JSON。本页面不重新计算验收、不运行比赛或训练；所有对局均在 cloud1 cgroups (8 GiB) 下 0 重试完成。</p>',
        f'<p class="source">Markdown SHA256: {hashlib.sha256(raw).hexdigest()}<br>独立结果 SHA256: {hashlib.sha256(RESULT.read_bytes()).hexdigest()}</p></footer>',
        '</main><script>document.querySelector("#expand").addEventListener("click",()=>document.querySelectorAll("details.match").forEach(d=>d.open=true));document.querySelector("#collapse").addEventListener("click",()=>document.querySelectorAll("details.match").forEach(d=>d.open=false));</script></body></html>'
    ]

    document = '\n'.join(out) + '\n'
    expected = sum(1 for line in source.splitlines() if re.match(r'^\|(?:\s*---\s*\|)+\s*$', line))
    tbl_count = document.count('<table>')
    assert tbl_count == expected, f"Table count mismatch: {tbl_count} vs {expected}"

    OUTPUT.write_bytes(document.encode('utf-8'))
    print(json.dumps({
        'html': str(OUTPUT),
        'tables': expected,
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'html_sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
        'bytes': len(document.encode('utf-8'))
    }, indent=2))


if __name__ == '__main__':
    main()
