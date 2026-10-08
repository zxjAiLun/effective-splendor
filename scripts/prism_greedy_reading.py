"""Hash-bound reading adapter for native both-greedy rounds; no fake sampling history."""
import copy
import hashlib
import html
import json
from pathlib import Path
import re

from scripts.prism_human_report import supplement,write_markdown


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(spec_path,root,templates):
    spec=json.loads(Path(spec_path).read_text(encoding='utf-8'))
    if spec['format']!='prism-greedy-reading-spec-v1':raise ValueError('greedy reading format')
    result_path=root/spec['result'];md=root/spec['markdown'];output=root/spec['output']
    if sha(result_path)!=spec['result_sha256'] or sha(md)!=spec['markdown_sha256']:raise ValueError('greedy reading source drift')
    result=json.loads(result_path.read_text(encoding='utf-8'))
    config_path=root/spec['contract']
    if sha(config_path)!=spec['contract_sha256'] or result['source_config_sha256']!=spec['contract_sha256']:
        raise ValueError('frozen competitive contract drift')
    config=json.loads(config_path.read_text(encoding='utf-8'))
    if result['acceptance_policy']!=config['evaluation']:raise ValueError('frozen competitive policy drift')
    if result['action_mode']!='both-greedy':raise ValueError('not a native greedy round')
    if spec['greedy_weight_sha256']!=result['candidate_sha256']:raise ValueError('candidate identity mismatch')
    configs=[];source_games=0
    for ref in spec['greedy_results']:
        raw=json.loads((root/ref['result']).read_text(encoding='utf-8'))
        complete=root/ref['completion']
        if sha(complete)!=ref['completion_sha256']:raise ValueError('greedy completion drift')
        done=json.loads(complete.read_text(encoding='utf-8'))
        if done['result_sha256']!=ref['sha256'] or done['games']!=raw['games'] or done['automatic_game_retries']!=0:
            raise ValueError('greedy completion/result mismatch')
        configs.append(ref['sha256']);source_games+=raw['games']
    if source_games!=result['games'] or configs!=result['source_result_sha256']:raise ValueError('reading result cohort mismatch')
    if set(result['gates'])!=set(result['acceptance_policy']['gates']):raise ValueError('gate set mismatch')
    for key,threshold in result['acceptance_policy']['gates'].items():
        if result['gates'][key]!=(result['measurements'][key]['simultaneous_one_sided_lower']>=threshold):raise ValueError('gate meaning drift')
    records,_=supplement(root,spec)
    output.parent.mkdir(parents=True,exist_ok=True)
    audit=output.with_suffix('.audit.html');audit_md=output.with_suffix('.audit.md')
    story=copy.deepcopy(spec['story'])
    payload={'schema':'prism-human-report-v2','view':'greedy','story':story,'focus':spec['focus'],
        'baseline':spec['baseline'],'comparison_baseline':spec['baseline'],'names':spec['names'],'result':records,
        'history_headline':'本轮只有双方greedy独立验收；训练采样另列，不伪装为历史验收。',
        'timing':spec.get('human_timing'),
        'links':{'main':output.name,'history':None,'audit':audit.name,'markdown':output.with_suffix('.reading.md').name,
                 'related':spec.get('related_reports',[])}}
    template=(templates/'prism-reading.html').read_text(encoding='utf-8')
    encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    document=template.replace('@@TITLE@@',html.escape(story['title'])).replace('@@CSS@@',(templates/'prism-reading.css').read_text(encoding='utf-8'))
    document=document.replace('@@DATA@@',encoded).replace('@@JS@@',(templates/'prism-human.js').read_text(encoding='utf-8'))
    output.write_text(document,encoding='utf-8')
    write_markdown(output.with_suffix('.reading.md'),payload)
    audit_text='# '+story['title']+' — Agent audit\n\n'+md.read_text(encoding='utf-8')
    audit_md.write_text(audit_text,encoding='utf-8')
    import markdown
    body=markdown.markdown(audit_text,extensions=['tables','fenced_code'])
    audit.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>M66 Agent audit</title><style>body{font:15px/1.7 system-ui;max-width:1400px;margin:2rem auto;padding:1rem}table{border-collapse:collapse;display:block;overflow:auto}td,th{border:1px solid #ccd;padding:.4rem}pre{overflow:auto}</style>'+body+'</html>',encoding='utf-8')
    receipt={'format':'prism-reading-receipt-v1','adapter':'native-greedy-v1','spec_sha256':sha(spec_path),
        'result_sha256':sha(result_path),'complete_markdown_sha256':sha(md),'html_sha256':sha(output),
        'reading_markdown_sha256':sha(output.with_suffix('.reading.md')),'audit_html_sha256':sha(audit),
        'audit_markdown_sha256':sha(audit_md),'source_result_sha256':configs,'games_dispatched':0,
        'gate_values_changed':False,'sampling_history':'NOT_RUN','original_html_sha256':None,
        'preserved_source_tables':len(re.findall(r'^\|(?:\s*---\s*\|)+\s*$',md.read_text(encoding='utf-8'),re.M))}
    output.with_suffix('.reading-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return receipt
