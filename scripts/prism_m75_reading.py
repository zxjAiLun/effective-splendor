"""Bound M75 reading revision; immutable inputs and complete primary cohorts."""
import copy,html,json
from pathlib import Path

def build(spec_path,root=None,templates=None):
    root=root or Path(__file__).resolve().parents[1];templates=templates or root/'scripts/templates'
    from training.prism_portable.common import read,digest,write
    from scripts.prism_human_report import write_markdown
    spec=read(spec_path);raw=read(root/spec['result']);contract=read(root/spec['contract'])
    for key in ('result','contract','markdown'):
        if digest(root/spec[key])!=spec[key+'_sha256']:raise ValueError('reading input drift: '+key)
    if raw['source_config_sha256']!=spec['contract_sha256'] or raw['acceptance_policy']!=contract['evaluation']:raise ValueError('statistical policy drift')
    payload=copy.deepcopy(spec['payload']);pairs=payload['result']['all']['pairs']
    if pairs!=raw['pairs'] or sum(p['candidate_metrics']['games'] for p in pairs)!=raw['games']:raise ValueError('reading rows/count drift')
    for p in pairs:
        for side in ('candidate_metrics','opponent_metrics'):
            m=p[side]
            if sum(m[k] for k in ('wins','ties','losses'))!=m['games'] or abs((m['wins']+.5*m['ties'])/m['games']-m['score_rate'])>1e-12:raise ValueError('WDL/rate drift')
    payload['style_opponents']=contract['evaluation']['common_opponents']
    payload['frozen_statistics']=raw['per_training_seed']
    payload['schema']='prism-human-report-v2';payload['story']['round']='M75'
    out=root/spec['output']
    payload['links']={'main':out.name,'history':None,'audit':out.with_suffix('.audit.html').name,'markdown':out.with_suffix('.reading.md').name,
                      'related':[{'href':'m75-prism-continuation-evidence.md','label':'完整证据与原判门'},{'href':'m75-prism-continuation-curve.html','label':'阶段棋力曲线'}]}
    js=(templates/'prism-human.js').read_text(encoding='utf-8')
    def replace(old,new):
        nonlocal js
        if js.count(old)!=1:raise ValueError('template structure changed: '+old[:60])
        js=js.replace(old,new)
    replace("const common=pairs(ss.value).filter(p=>p.candidate===model&&","const common=pairs(ss.value).filter(p=>data.style_opponents.includes(p.opponent)&&p.candidate===model&&")
    helper="""
function seedCoverage(p){return Number.isFinite(p.score_uncertainty.seed_blocks)?p.score_uncertainty.seed_blocks+'双座种子块':'配对不完整';}
function scoreInterval(p,separator){
 const frozen=p.opponent==='parent'?data.frozen_statistics[p.candidate]?.direct_parent:null;
 const ci=frozen?.ci95||p.score_uncertainty.ordinary_95_ci;
 return ci.every(Number.isFinite)?ci.map(pct).join(separator):'未测（配对不完整）';
}
"""
    replace('function strength(){',helper+'\nfunction strength(){')
    replace("p.score_uncertainty.ordinary_95_ci.map(pct).join(' – ')","scoreInterval(p,' – ')")
    replace("p.score_uncertainty.ordinary_95_ci.map(pct).join(' ～ ')","scoreInterval(p,' ～ ')")
    replace("p.score_uncertainty.seed_blocks+'种子块</div>'","seedCoverage(p)+'</div>'")
    replace("a.games+' 局 / '+p.score_uncertainty.seed_blocks+' 双座种子块</p>'","a.games+' 局 · '+seedCoverage(p)+'</p>'")
    replace('const delta=Number.isFinite(am?.score_rate)&&Number.isFinite(bm?.score_rate)?',"const delta=(a&&b&&(!Number.isFinite(a.score_uncertainty.seed_blocks)||!Number.isFinite(b.score_uncertainty.seed_blocks)))?'<span class=\"unavailable\">配对不完整</span>':Number.isFinite(am?.score_rate)&&Number.isFinite(bm?.score_rate)?")
    encoded=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    document=(templates/'prism-reading.html').read_text(encoding='utf-8').replace('@@TITLE@@',html.escape(payload['story']['title'])).replace('@@CSS@@',(templates/'prism-reading.css').read_text(encoding='utf-8')).replace('@@DATA@@',encoded).replace('@@JS@@',js)
    if '@@' in document:raise ValueError('unfilled report token')
    if out.exists():raise ValueError('preserve existing reading revision')
    out.write_text(document,encoding='utf-8');write_markdown(out.with_suffix('.reading.md'),payload)
    import markdown
    audit=(root/spec['markdown']).read_text(encoding='utf-8')
    out.with_suffix('.audit.html').write_text('<!doctype html><meta charset="utf-8">'+markdown.markdown(audit,extensions=['tables','fenced_code']),encoding='utf-8')
    receipt={'format':'prism-reading-receipt-v1','adapter':'m75-bounded-reading-v1','adapter_sha256':digest(Path(__file__)),
             'spec_sha256':digest(spec_path),'result_sha256':digest(root/spec['result']),'contract_sha256':digest(root/spec['contract']),
             'html_sha256':digest(out),'reading_markdown_sha256':digest(out.with_suffix('.reading.md')),'payload_pairs_unchanged':True,'style_cohort':payload['style_opponents'],'games_dispatched':0,'pixel_visual':'NOT_VERIFIED'}
    write(out.with_suffix('.reading-receipt.json'),receipt);return receipt
