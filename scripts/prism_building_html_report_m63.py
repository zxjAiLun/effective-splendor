"""Standalone M63 HTML presentation of the immutable full Markdown report."""
import hashlib
import html
import json
import argparse
from pathlib import Path
import re

import markdown

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/prism/m63-prism-beta-timed-building-evaluation.md'
RESULT = ROOT / 'local-artifacts/prism/building-beta-m63/evaluation/result.json'
OUTPUT = ROOT / 'docs/prism/m63-prism-beta-building-comparison.html'

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
            'fail' if '<strong>FAIL</strong>' in m[1] or m[1].strip() == 'NOT_RUN' or m[1].strip() == 'NOT_ACCEPTED_BUILDING_CANDIDATE' else ''
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


def main(markdown_path=SOURCE, result_path=RESULT, output_path=OUTPUT):
    markdown_path, result_path, output_path = Path(markdown_path), Path(result_path), Path(output_path)
    raw = markdown_path.read_bytes()
    source = raw.decode('utf-8')
    result_bytes = result_path.read_bytes()
    result = json.loads(result_bytes)

    parts = re.split(r'^## (.+)$', source, flags=re.M)
    sections = {parts[i].strip(): parts[i + 1] for i in range(1, len(parts), 2)}

    def card(label, value, caption, cls=''):
        return f'<div class="card"><span class="label">{label}</span><b class="{cls}">{value}</b><small>{caption}</small></div>'

    gates = result.get('gates', {})
    control_keys = [key for key in gates if key.startswith('control/')]
    beta_keys = [key for key in gates if key.startswith('beta/')]
    cards = card('Control 保留门', f"{sum(bool(gates[k]) for k in control_keys)} / {len(control_keys)} PASS" if control_keys else 'NOT_RUN', '两项预注册Control门', 'pass' if control_keys and all(gates[k] for k in control_keys) else '')
    cards += card('Beta 验收门', f"{sum(bool(gates[k]) for k in beta_keys)} / {len(beta_keys)} PASS" if beta_keys else 'NOT_RUN', '八项竞争与基建合同门', 'pass' if beta_keys and all(gates[k] for k in beta_keys) else '')
    style = result.get('verdicts', {}).get('beta_style', 'NOT_RUN')
    cards += card('风格实质门', style, '非reward AUC12门；原building效用为单独保留容忍门', 'pass' if style.startswith('PASS') else '')

    out = [
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Prism Beta v0.1.1 candidate / M63 原目标对照 c4 · M63 对战评测</title>',
        f'<style>{CSS}</style></head><body><main>',
        '<header><div class="eyebrow">PRISM / MODEL REPORT / M63</div>',
        '<h1>Prism Beta v0.1.1 candidate / M63 原目标对照 c4</h1>',
        '<p class="lead">同一 Prism Balance v0.1.0 起点，比较原 building-v1 Control 与 timed-building-v1 Beta 风格训练 · training seed 63041001；双方各训练 1,024 局（共 2,048 局），以固定最终 c4 完成 10,304 局评测（576局开发 + 9,728局独立验收）。</p>',
        '<div class="chips"><span class="chip chip-fail">候选未发布 · 最终判定见M63结果</span>',
        '<span class="chip">2,048 训练局</span><span class="chip">576 开发局</span><span class="chip">9,728 独立验收局（共 10,304 局）</span>',
        '<span class="chip">M63评测服务 · 8 GiB · 0 重试</span><span class="chip">十门同时Bootstrap下界</span></div></header>',
        '<nav><a href="#overview">结论</a><a href="#comparison">锚点变化</a><a href="#gates">十项采样前冻结门</a><a href="#acceptance">独立验收 (9,728局)</a><a href="#development">开发评测 (576局)</a><a href="#sources">来源与执行合同</a><a href="m63-prism-beta-timed-building-evaluation.md">Markdown 原文</a></nav>',
        f'<div id="overview" class="cards">{cards}</div>',
        '<div class="note"><strong>M63 独立固定评测。</strong>本页只呈现所绑定的M63结果；每项冻结门的估计、区间与判定见下方表格。未执行时统一显示NOT_RUN。</div>',
        '<details class="intro"><summary>模型身份、产物审计与验收判决</summary>' + re.sub(r'<h1>(.*?)</h1>', r'<h3>\1</h3>', render(parts[0])) + '</details>',
        '<section id="comparison"><h2>匹配共同锚点：父 → M63 原目标对照 → Prism Beta v0.1.1 candidate</h2><p class="legend"><strong>↑ 数值增加 / ↓ 数值减少</strong>：颜色和箭头表示变化方向，不自动代表更好或统计显著。双方指标以表头标注的模型身份为准。</p>' + render(sections.pop('匹配共同锚点：父 → M63 原目标对照 → Prism Beta v0.1.1 candidate')) + '</section>',
        '<section id="gates"><h2>十项采样前冻结门</h2>' + render(sections.pop('十项采样前冻结门')) + '</section>',
        '<section id="direction"><h2>开发与独立方向对比</h2>' + render(sections.pop('开发与独立方向')) + '</section>',
        '<section id="records"><h2>原验收与增强记录</h2>' + render(sections.pop('原验收与增强记录')) + '</section>',
        '<div class="tools"><button id="expand" type="button">展开全部详细表</button><button id="collapse" type="button">收起全部详细表</button></div>',
        stage(sections.pop('独立验收（9,728局）'), '独立验收 · 9,728 局', 'acceptance'),
        stage(sections.pop('开发评测（仅描述，576局）'), '开发评测 · 576 局（仅描述）', 'development'),
        '<details id="sources" class="provenance"><summary>完整来源、计时、执行合同与审计回执</summary>'
    ]

    for title, text in sections.items():
        out += [f'<h2>{html.escape(title)}</h2>', render(text)]

    out += [
        '</details><footer><p>数据来自绑定的M63 Markdown 与独立结果 JSON。本页面不重新计算验收、不运行比赛或训练；执行状态以M63结果JSON为准；未运行时所有测量保持NOT_RUN。</p>',
        f'<p class="source">Markdown: {len(raw):,} bytes · SHA256: {hashlib.sha256(raw).hexdigest()}<br>独立结果: {len(result_bytes):,} bytes · SHA256: {hashlib.sha256(result_bytes).hexdigest()}</p></footer>',
        '</main><script>document.querySelector("#expand").addEventListener("click",()=>document.querySelectorAll("details.match").forEach(d=>d.open=true));document.querySelector("#collapse").addEventListener("click",()=>document.querySelectorAll("details.match").forEach(d=>d.open=false));</script></body></html>'
    ]

    document = '\n'.join(out) + '\n'
    expected = sum(1 for line in source.splitlines() if re.match(r'^\|(?:\s*---\s*\|)+\s*$', line))
    tbl_count = document.count('<table>')
    assert tbl_count == expected, f"Table count mismatch: {tbl_count} vs {expected}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(document.encode('utf-8'))
    print(json.dumps({
        'html': str(output_path),
        'tables': expected,
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'html_sha256': hashlib.sha256(output_path.read_bytes()).hexdigest(),
        'bytes': len(document.encode('utf-8'))
    }, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--markdown', type=Path, default=SOURCE)
    parser.add_argument('--result', type=Path, default=RESULT)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    main(args.markdown, args.result, args.output)
