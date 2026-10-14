"""Independent M75 reading revision: complete descriptive cohort, unchanged matches."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from scripts.prism_candidate_archive import ROOT, digest, read, require, write_json


def build(spec_path):
    from scripts.prism_m75_reading import build as original_build
    spec = read(spec_path)
    directory = ROOT / 'local-artifacts/prism/m75-continuation/artifact-workflow-r1/reading-templates'
    directory.mkdir(parents=True, exist_ok=True)
    for name in ('prism-human.js', 'prism-reading.html', 'prism-reading.css'):
        (directory/name).write_bytes((ROOT/'scripts/templates'/name).read_bytes())
    path = directory/'prism-human.js'
    js = path.read_text(encoding='utf-8')
    old = 'pairs(ss.value).some(q=>q.candidate===data.focus&&q.opponent===p.opponent)&&pairs(ss.value).some(q=>q.candidate===sb.value&&q.opponent===p.opponent)'
    new = 'pairs(ss.value).some(q=>q.candidate===data.focus&&q.opponent===p.opponent&&Number.isFinite(q.score_uncertainty.seed_blocks))&&pairs(ss.value).some(q=>q.candidate===sb.value&&q.opponent===p.opponent&&Number.isFinite(q.score_uncertainty.seed_blocks))'
    require(js.count(old)==1,'pooled template drift')
    js = js.replace(old,new)
    old = "' 局。指标属于模型本人，按总计数计算比例。"
    new = "' 局；排除基线有截断的整个Beta对手。这是事后描述子集，原六对手门保留缺项。指标属于模型本人，按总计数计算比例。"
    require(js.count(old)==1,'style text template drift')
    js = js.replace(old,new)
    path.write_text(js,encoding='utf-8')
    css = directory/'prism-reading.css'
    css.write_text(css.read_text(encoding='utf-8')+'\n#detail-body table{min-width:760px}#detail-body th{min-width:100px}\n',encoding='utf-8')
    receipt = original_build(Path(spec_path), templates=directory)
    out = ROOT/spec['output']
    text = out.read_text(encoding='utf-8')
    match = re.search(r'(<script id="report-data" type="application/json">)(.*?)(</script>)',text,re.S)
    require(match is not None,'report data absent')
    payload = json.loads(match.group(2))
    if 'curve' in spec:
        source = ROOT/spec['curve']['path']
        require(digest(source)==spec['curve']['sha256'],'curve source drift')
        curve = source.with_name('m75-prism-continuation-curve-r2.html')
        curve_text = source.read_text(encoding='utf-8')
        require(curve_text.count('<table>')==curve_text.count('</table>')==1,'curve table drift')
        curve_text = curve_text.replace('<table>','<div class="curve-scroll"><table>').replace('</table>','</table></div>')
        curve_text = curve_text.replace('</style>','.curve-scroll{overflow:auto;max-width:100%}.curve-scroll table{min-width:620px}body{box-sizing:border-box}progress{max-width:35%}</style>')
        curve_text = curve_text.replace('<meta charset="utf-8">','<meta charset="utf-8"><title>M75 阶段棋力曲线</title>')
        curve.write_text(curve_text,encoding='utf-8')
        for item in payload['links']['related']:
            if item['href']=='m75-prism-continuation-curve.html':item['href']=curve.name
    payload['links']['related'].append(dict(href='m75-candidate-card.html',label='身份、时点兑现画像与用途归档'))
    encoded = json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    text = text[:match.start(2)]+encoded+text[match.end(2):]
    out.write_text(text,encoding='utf-8')
    markdown = out.with_suffix('.reading.md')
    md = markdown.read_text(encoding='utf-8')
    # The common Markdown projection prints a numerical delta for unequal grids.
    # Keep both measured rows, while removing that invalid paired comparison.
    md = re.sub(r'^(\| Prism Beta v0\.1\.0 \|.*\| )[^|]+ \|$',r'\1配对不完整（基线511局/候选512局） |',md,count=1,flags=re.M)
    markdown.write_text(md,encoding='utf-8')
    receipt.update(adapter='m75-candidate-reading-r4',adapter_sha256=digest(__file__),
                   parent_adapter_sha256=digest(ROOT/'scripts/prism_m75_reading.py'),
                   template_sha256=digest(path),css_sha256=digest(css),html_sha256=digest(out),
                   reading_markdown_sha256=digest(markdown),
                   descriptive_profile_cohort='five complete common opponents,2560/model; excluded beta',
                   preserved_original_html_sha256=digest(ROOT/'docs/prism/m75-prism-continuation-comparison.html'))
    if 'curve' in spec:
        receipt['curve_source_sha256']=digest(source)
        receipt['curve_revision_sha256']=digest(curve)
        receipt['curve_table_unchanged']=re.search(r'<table>.*?</table>',source.read_text(encoding='utf-8'),re.S).group()==re.search(r'<table>.*?</table>',curve_text,re.S).group()
    write_json(out.with_suffix('.reading-receipt.json'),receipt)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',required=True,type=Path)
    print(json.dumps(build(parser.parse_args().spec),ensure_ascii=False))
