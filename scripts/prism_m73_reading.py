"""Independent reading adapter for the new bounded M73 schema."""
import html,json
from pathlib import Path
from scripts.prism_human_report import write_markdown

def build(spec_path,root,templates):
    from training.prism_portable.common import read,digest,write
    spec=read(spec_path);result=root/spec['result'];md=root/spec['markdown'];contract=root/spec['contract'];out=root/spec['output']
    for path,key in [(result,'result_sha256'),(md,'markdown_sha256'),(contract,'contract_sha256')]:
        if digest(path)!=spec[key]:raise ValueError('reading binding drift: '+key)
    raw=read(result)
    if raw['source_config_sha256']!=digest(contract) or raw['acceptance_policy']!=read(contract)['evaluation']:raise ValueError('frozen statistical contract drift')
    pairs=spec['payload']['result']['all']['pairs']
    if pairs!=raw['pairs'] or sum(p['candidate_metrics']['games'] for p in pairs)!=raw['games']:raise ValueError('reading pair/count drift')
    for p in pairs:
        for side in ['candidate_metrics','opponent_metrics']:
            m=p[side]
            if sum(m[k] for k in ['wins','ties','losses'])!=m['games']:raise ValueError('WDL mismatch')
            if abs((m['wins']+.5*m['ties'])/m['games']-m['score_rate'])>1e-10:raise ValueError('score denominator mismatch')
        if sum(s['candidate']['games'] for s in p['seats'])!=p['candidate_metrics']['games']:raise ValueError('seat count mismatch')
    payload=dict(spec['payload'],schema='prism-human-report-v2',links=dict(main=out.name,history=None,audit=out.with_suffix('.audit.html').name,markdown=out.with_suffix('.reading.md').name,related=[]))
    for seed,stats in raw['per_training_seed'].items():
        common=stats['common_delta'];direct=stats['direct_parent']
        cv=(f"共同池{common['mean']*100:+.2f}pp，95%区间[{common['ci95'][0]*100:+.2f},{common['ci95'][1]*100:+.2f}]pp" if common else '共同池缺项，正式判定不完整')
        dv=(f"直接B半平{direct['mean']*100:.2f}%，95%区间[{direct['ci95'][0]*100:.2f},{direct['ci95'][1]*100:.2f}]%" if direct else '直接B缺项')
        payload['story']['conclusions'].append(dict(label='训练seed '+seed.upper(),value=cv,explanation=dv+'。普通区间为描述；增强另按冻结校正门判断。'))
    template=(templates/'prism-reading.html').read_text(encoding='utf-8')
    encoded=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    document=template.replace('@@TITLE@@',html.escape(payload['story']['title'])).replace('@@CSS@@',(templates/'prism-reading.css').read_text(encoding='utf-8')).replace('@@DATA@@',encoded).replace('@@JS@@',(templates/'prism-human.js').read_text(encoding='utf-8'))
    if '@@' in document:raise ValueError('unfilled template')
    out.write_text(document,encoding='utf-8');write_markdown(out.with_suffix('.reading.md'),payload)
    import markdown
    out.with_suffix('.audit.html').write_text('<!doctype html><meta charset="utf-8">'+markdown.markdown(md.read_text(encoding='utf-8'),extensions=['tables','fenced_code']),encoding='utf-8')
    receipt=dict(format='prism-reading-receipt-v1',adapter='m73-bounded-v1',spec_sha256=digest(spec_path),result_sha256=digest(result),complete_markdown_sha256=digest(md),html_sha256=digest(out),reading_markdown_sha256=digest(out.with_suffix('.reading.md')),games_dispatched=0,pixel_visual='NOT_VERIFIED')
    write(out.with_suffix('.reading-receipt.json'),receipt);return receipt
