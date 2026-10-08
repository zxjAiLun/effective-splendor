"""Standalone interactive M72 reading page from result-bound descriptive delivery."""
import json
from pathlib import Path
from scripts.prism_style_atlas import ROOT, read, digest


def release_labels(value,aliases):
    if isinstance(value,str):return aliases.get(value,value)
    if isinstance(value,list):return [release_labels(v,aliases) for v in value]
    if isinstance(value,dict):return {k:v if k=='original_checkpoint' else release_labels(v,aliases) for k,v in value.items()}
    return value


def build_page():
    data=read('benchmarks/prism-style-delivery-2026-10-08.json')
    history=read('benchmarks/prism-style-history-2026-10-08.json')
    data['groups']=history['groups']+data['groups']
    data['records']=history['records']+data['records']
    for item in data['inventory']:
        item['profile_groups']+=list(dict.fromkeys(r['group'] for r in history['records'] if r['model']==item['model']))
    registry=read('benchmarks/prism-v020-model-registry.json')
    baseline=read('benchmarks/prism-balance-data-baseline-v0.2.0.json')
    aliases={r['original_checkpoint']:r['display_name'] for r in registry['models']}
    for item in data['inventory']:
        entry=next((r for r in registry['models'] if r['original_checkpoint']==item['model']),None)
        if entry:
            record=read(entry['record_path']);item.update(original_checkpoint=item['model'],fixed_version=True,release_state=record['status'],identity_source=entry['record_path'],identity_source_sha256=digest(entry['record_path']),weights_path=record['weights_path'],parent=record['parent'],parent_label=record['parent']['display_name'],assigned_route=record['route'])
    data['fixed_versions']=registry;data['data_baseline']=baseline
    template=(ROOT/'scripts/templates/prism-style-atlas.html').read_text('utf-8')
    path=ROOT/'docs/prism/style-atlas-2026-10-08.html'
    template=template.replace('模型身份方案 JSON</a>','模型身份方案 JSON</a><a href="style-atlas-method-2026-10-08.html">分类与身份流程图</a>')
    distribution=read('benchmarks/prism-style-distributions-2026-10-08.json')
    distribution['model_groups']=[dict(**g,records=[r for r in history['records'] if r['group']==g['id']]) for g in history['groups']]+distribution['model_groups']
    for group in distribution['model_groups']:
        if any(r['model']=='M67 B-c20' for r in group['records']):
            group.update(reference_model='M67 B-c20',reference_label='Balance v0.2.0基线')
        elif group.get('reference_model'):group['reference_label']='历史Balance v0.1.0'
    data=release_labels(data,aliases);history=release_labels(history,aliases);distribution=release_labels(distribution,aliases)
    payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    distribution_payload=json.dumps(distribution,ensure_ascii=False).replace('<','\\u003c')
    distribution_script=(ROOT/'scripts/templates/prism-style-distributions.js').read_text('utf-8')
    template=template.replace('__DISTRIBUTIONS__',distribution_payload).replace('__DISTRIBUTION_SCRIPT__',distribution_script)
    template=template.replace('__HISTORY__',json.dumps(history,ensure_ascii=False).replace('<','\\u003c')).replace('__HISTORY_SCRIPT__',(ROOT/'scripts/templates/prism-style-history.js').read_text('utf-8'))
    template=template.replace('6 个可比组、25 份画像快照','16 个分组、54 份画像快照').replace('早期 Alpha v0.1.0–v0.1.3 已纳入身份清单；旧 sampling 数据独立保留。','早期Balance、初代、通用版和Alpha v0.1.0–v0.1.3均已纳入数值画像，模式与cohort分别展示。')
    path.write_text(template.replace('__DATA__',payload),encoding='utf-8')
    index=ROOT/'docs/prism/reports.html';index_text=index.read_text('utf-8')
    if 'style-atlas-2026-10-08.html' not in index_text:
        entry='<article><h2><a href="style-atlas-2026-10-08.html">M72 · 模型统计画像、区间分类与v0.2.0身份方案</a></h2><p>14份神经权重核实，25个分cohort画像、184行逐对手座位数据及24张Excel柱状图。A更偏大牌；B的Beta/Balance归属证据不足。型号为绑定权重提案，未发布。</p><a href="style-atlas-2026-10-08.md">完整双方表</a> · <a href="style-atlas-2026-10-08.audit.md">Agent审计</a></article>\n'
        index.write_text(index_text.replace('<article>',entry+'<article>',1),encoding='utf-8')
    print(str(path))


if __name__=='__main__':build_page()
