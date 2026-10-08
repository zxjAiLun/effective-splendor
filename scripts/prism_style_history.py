"""M72 historical reference revision. Saved aggregates only; no inference or games."""
import csv
import json
from pathlib import Path

from scripts.prism_style_atlas import ROOT, aggregate, digest, midrank, read
from scripts.prism_style_delivery import validate_metrics

TARGET='benchmarks/prism-style-history-2026-10-08.json'
OUT=ROOT/'local-artifacts/prism/style-atlas-20261008/history-r3'
FIELDS=['low_share','big_printed_vp','noble_coverage','vp_main']
EARLY=[
 ('M55','benchmarks/m55-prism-rush-v0.1.0.result.json','local-artifacts/prism/rush-v0.1.0/acceptance/configs/anchors-0.json',{'base':'Prism v0.1.1','rush':'Prism Alpha v0.1.0'},['heuristic-v031','prism-v01']),
 ('M56','benchmarks/m56-prism-alpha-v0.1.1.result.json','local-artifacts/prism/alpha-v0.1.1/acceptance/configs/anchors-0.json',{'base':'Prism Alpha v0.1.0','candidate':'Prism Alpha v0.1.1'},['heuristic-v031','prism-v01','prism-v0.1.1']),
 ('M59','benchmarks/m59-prism-alpha-cloud-ppo.evaluation-result.json','benchmarks/m59-prism-alpha-cloud-ppo.config.json',{'base':'Prism Alpha v0.1.1','candidate':'Prism Alpha v0.1.2'},['heuristic-portable-v029','prism-v01','prism-general-v011']),
 ('M60','benchmarks/m60-prism-alpha-cloud-ppo.evaluation-result.json','benchmarks/m60-prism-alpha-cloud-ppo.config.json',{'base':'Prism Alpha v0.1.2','candidate':'Prism Alpha v0.1.3'},['heuristic-portable-v029','prism-v01','prism-general-v011']),
 ('M61','local-artifacts/prism/balance-ab-m61/result.json','local-artifacts/prism/balance-ab-m61/execution.json',{'base':'Prism Alpha v0.1.3','alpha':'Prism Alpha v0.1.4','balance':'Prism Balance v0.1.0'},['heuristic-v031','prism-v01','prism-general-v011']),
 ('M62','local-artifacts/prism/building-beta-m62/evaluation/result.json','local-artifacts/prism/building-beta-m62/evaluation/execution.json',{'base':'Prism Balance v0.1.0','beta':'Prism Beta v0.1.0'},['heuristic-v031','prism-v01','prism-general-v011']),
]
OPPONENTS={'heuristic-v031':'Heuristic v0.3.1','heuristic-portable-v029':'Heuristic portable v0.2.9',
           'prism-v01':'Prism v0.1.0','prism-v0.1.1':'Prism v0.1.1','prism-general-v011':'Prism v0.1.1'}


def conditional_timing(pairs,role):
    timing=[]
    for p in pairs:
        big=p.get(role+'_bigcard')
        if not big or 'first_4plus_card_main' not in big:return dict(first_big_main=None,first_big_coverage=None,first_big_games=None)
        assert big['games']==p[role+'_metrics']['games']
        t=big['first_4plus_card_main'];n=t['coverage_games'];v=t['conditional_mean']
        assert 0<=n<=big['games'] and (v is not None or n==0)
        timing.append((n,v,big['games']))
    count=sum(n for n,_,_ in timing)
    return dict(first_big_main=sum(n*v for n,v,_ in timing if n)/count if count else None,
                first_big_coverage=count/sum(n for _,_,n in timing),first_big_games=count)


def row(model,group,pairs,role,source,mode,known,fixture):
    metrics=[p[role+'_metrics'] for p in pairs]
    for m in metrics:validate_metrics(m)
    d=aggregate(metrics);timing=conditional_timing(pairs,role)
    building=[p.get(role+'_building') for p in pairs]
    early=None
    if all(b and 'mean_early_lowvp_buys' in b for b in building):
        early=sum(b['mean_early_lowvp_buys']*b['games'] for b in building)/d['games']
    d.update(timing,early_low_cards=early)
    return dict(model=model,group=group,round=group.split('-')[1],kind='historical',sha256=known.get(model,'non-neural heuristic'),
                mode=mode,actor_mode=mode,opponent_fixture=fixture,source=source,source_sha256=digest(source),
                source_pairs=[dict(candidate=p['candidate'],opponent=p['opponent'],role=role,games=p[role+'_metrics']['games']) for p in pairs],
                **d,classification={'route':'undetermined','evidence_level':'DESCRIPTIVE','reason':'historical reference; no new confirmatory policy'})


def build():
    OUT.mkdir(parents=True,exist_ok=True)
    delivery=read('benchmarks/prism-style-delivery-2026-10-08.json')
    known={i['model']:i['sha256'] for i in delivery['inventory']}
    for i in delivery['inventory']:assert digest(i['weights_path'])==i['sha256']
    records=[];groups=[];sources={'benchmarks/prism-style-delivery-2026-10-08.json':digest('benchmarks/prism-style-delivery-2026-10-08.json')}
    for rnd,source,contract,models,pool in EARLY:
        d=read(source);c=read(contract);sources[source]=digest(source);sources[contract]=digest(contract)
        pairs=[p for p in d['acceptance']['pairs'] if p['candidate'] in models and p['opponent'] in pool]
        assert len(pairs)==len(models)*len(pool)
        if rnd in ('M55','M56'):
            for key,model in models.items():
                cmd=c['candidates'][key];assert cmd['args'][0]=='agent-prism-sample' and cmd['files'][0]['sha256']==known[model]
        else:
            assert 'agent-prism-sample T1' in c['evaluation']['candidate_and_parent_mode']
            if isinstance(d.get('candidate_sha256'),str):assert d['candidate_sha256']==known[models['candidate']]
            else:
                for key,sha in d['candidate_sha256'].items():
                    if key in models:assert sha==known[models[key]]
            parent=c.get('base_model',c.get('assets',{}).get('parent',{}))
            if parent:assert parent['sha256']==known[models['base']]
        group='H-'+rnd+'-T1';fixture=[OPPONENTS[o]+(' · T1' if 'general' in o or o=='prism-v0.1.1' else ' · greedy') for o in pool]
        for key,model in models.items():records.append(row(model,group,[p for p in pairs if p['candidate']==key],'candidate',source,'T1',known,fixture))
        groups.append(dict(id=group,title=rnd+'早期共同池 · 本方T1',fixture=fixture,note='本方T1，按该轮共同池汇总；不同轮seed/对手实现可能不同，不是greedy路线确认。'))
        if rnd=='M55':
            group='H-M55-anchors';fixture=list(models.values())
            for op in pool:records.append(row(OPPONENTS[op],group,[p for p in pairs if p['opponent']==op],'opponent',source,'greedy',known,fixture))
            groups.append(dict(id=group,title='M55最初代与启发式 · 本方greedy',fixture=fixture,note='本方greedy，对手是通用版/Alpha初版的T1模式；与双方greedy分开。'))
    for rnd,top_path,key in [('M63','benchmarks/m63-greedy-report-supplement.result.json','sources'),('M65','benchmarks/m65-prism-version-release.result.json','release_support')]:
        top=read(top_path);sources[top_path]=digest(top_path)
        source=next(s for s in top[key] if s['stage']=='greedy');path=source['result'];d=read(path);c=read(source['config']);plan=read(source['plan'])
        assert digest(path)==source['sha256'] and digest(source['config'])==source['config_sha256']==d['config_sha256']
        assert digest(source['plan'])==source['plan_sha256']==d['plan_sha256']
        for p in [path,source['config'],source['plan']]:sources[p]=digest(p)
        models={k:next(name for name,sha in known.items() if sha==v['files'][0]['sha256']) for k,v in c['candidates'].items()}
        assert all(v['args'][0]=='agent-prism' and plan['candidates'][k]['mode']=='greedy' for k,v in c['candidates'].items())
        fixture=[next((name for name,sha in known.items() if v.get('files') and sha==v['files'][0]['sha256']),'Heuristic v0.3.1') for v in c['opponents'].values()]
        group='H-'+rnd+'-greedy'
        for actor,name in models.items():records.append(row(name,group,[p for p in d['pairs'] if p['candidate']==actor],'candidate',path,'greedy',known,fixture))
        groups.append(dict(id=group,title=rnd+'早期Balance共同池 · 双方greedy',fixture=fixture,note='相同轮对手与seed；版本名称按精确SHA恢复，旧Beta实验标签没有当成发布名。',reference_model='Prism Balance v0.1.0'))
    # A shared exact opponent allows descriptive historical positioning, not paired inference.
    shared=[]
    for r in delivery['actor_match_rows']:
        if r['other']!='Prism Alpha v0.1.5':continue
        if r['round']=='M67' or (r['round']=='M66' and r['actor']=='M66 c4') or (r['round']=='M70' and r['actor']=='M70 c4'):
            assert r['mode']=='both-greedy' and r['missing_games']==0
            s=dict(r['derived']);shared.append(dict(**s,model=r['actor'],sha256=r['sha256'] or 'non-neural heuristic',group='H-Greedy-Alpha15',round=r['round'],kind='historical-common-opponent',mode='both-greedy',actor_mode='greedy',opponent_fixture=['Prism Alpha v0.1.5'],source=r['source'],source_sha256=r['source_sha256'],seed_start=r['seed_start'],seed_end=r['seed_end'],first_big_games=None,classification={'route':'undetermined','evidence_level':'DESCRIPTIVE'},source_pairs=[dict(candidate=r['actor'],opponent=r['other'],role=r['role'],games=r['metrics']['games'])]))
    order=['Prism v0.1.0','Prism v0.1.1','Prism Alpha v0.1.4','Prism Balance v0.1.0','Prism Beta v0.1.0','Heuristic v0.3.1','M66 c4','M70 c4','M67 A-c20','M67 B-c20']
    shared.sort(key=lambda r:order.index(r['model']));assert len(shared)==10 and len({r['sha256'] for r in shared})==10
    group=dict(id='H-Greedy-Alpha15',title='早期到当前 · 同一Alpha v0.1.5对手',fixture=['Prism Alpha v0.1.5'],reference_model='Prism Balance v0.1.0',note='双方greedy、同一精确对手；M67旧模型与A/B是不同seed范围，M66/M70另轮。仅描述历史位置，不是同seed配对确认。')
    groups.insert(0,group);records=shared+records
    for g in groups:
        rows=[r for r in records if r['group']==g['id']];g['models']=len(rows)
        if any(r['model']=='Prism Balance v0.1.0' for r in rows):g['reference_model']='Prism Balance v0.1.0'
        for r in rows:r['within_group_percentiles']={k:midrank(r[k],[s[k] for s in rows]) for k in FIELDS}
    balance=next(r for r in shared if r['model']=='Prism Balance v0.1.0')
    comparisons=[dict(model=r['model'],reference=balance['model'],scope=group['note'],deltas={k:r[k]-balance[k] for k in FIELDS}) for r in shared if r['model'] in ['M67 A-c20','M67 B-c20','M70 c4']]
    payload=dict(format='prism-style-history-v1',status='DESCRIPTIVE_NOT_STYLE_CONFIRMATION',groups=groups,records=records,source_hashes=sources,weight_hashes=known,comparisons=comparisons,new_games=0,new_training=0,
                 scope='All 14 inventoried neural identities now have numerical historical profiles; older intermediate/control checkpoints are not exhaustive.',
                 notes=['Separate actor mode, opposite mode, fixture, seed cohort and exact identity. Do not pool all snapshots into a global percentile.','Shared-opponent history uses one selected cohort per exact model; cross-seed/round deltas are descriptive.','Old conditional first-big timings use purchased printed4–5VP coverage denominator, never all-game mean.','M62 early lowVP purchases are first12 ownMain from original building schema; current M67/M70 still unmeasured.'])
    assert set(known).issubset({r['model'] for r in records}|{r['model'] for r in delivery['records']})
    (ROOT/TARGET).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    csv_path=ROOT/'outputs/01a11805-prism-style/prism-historical-profiles.csv'
    fields=['group','model','sha256','round','actor_mode','games','low_cards','low_share','big_printed_vp','noble_coverage','vp_main','first_big_main','first_big_coverage','early_low_cards']+[f'cards_{i}vp' for i in range(6)]+['source','opponent_fixture']
    with csv_path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in records:w.writerow({**{k:r.get(k) for k in fields if k not in ['opponent_fixture']},**{f'cards_{i}vp':v for i,v in enumerate(r['cards_by_vp'])},'opponent_fixture':' | '.join(r['opponent_fixture'])})
    report(payload)
    receipt=dict(status='PASS',historical_groups=len(groups),historical_snapshots=len(records),neural_identities_with_statistics=14,shared_opponent_models=len(shared),sources=len(sources),new_games=0,output_sha256=digest(TARGET))
    (OUT/'data-validation.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8');print(json.dumps(receipt))
    return payload


def report(data):
    fmt=lambda v,p=False:'未测' if v is None else f'{v*100:.2f}%' if p else f'{v:.4f}'
    md=['# M72 早期模型历史画像与当前A/B对照','','产物：早期Balance、初代、通用版及Alpha v0.1.0–v0.1.3均有实际数字并纳入对比。竞技：沿用冻结结论。风格：描述性参考，不用不同模式/seed历史范围证明路线确认。','',
        '## 与同一Alpha v0.1.5对手比赛：历史位置','','每个精确模型仅选一组记录。双方greedy、同一精确对手，seed和轮次不同。旧模型采用M67父代与其对战中的opponent侧，A/B采用M67直接父对战的candidate侧；M66/M70使用各自对应记录。无需把不同对手池百分比硬合并。','',
        '| 模型 | 来源轮 | N | seed范围 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main |','| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |']
    for r in data['records']:
        if r['group']=='H-Greedy-Alpha15':md.append(f"| {r['model']} | {r['round']} | {r['games']} | {r['seed_start']}–{r['seed_end']} | {fmt(r['low_share'],True)} | {fmt(r['big_printed_vp'])} | {fmt(r['noble_coverage'],True)} | {fmt(r['vp_main'])} |")
    md+=['','| 当前−历史Balance | 低VP占比pp | 大牌VP/局 | 贵族覆盖pp | VP/Main |','| --- | ---: | ---: | ---: | ---: |']
    for c in data['comparisons']:
        d=c['deltas'];md.append(f"| {c['model']} | {d['low_share']*100:+.2f} | {d['big_printed_vp']:+.4f} | {d['noble_coverage']*100:+.2f} | {d['vp_main']:+.4f} |")
    md+=['','A在这个相同对手视角下，小牌占比低于历史Balance而大牌印刷分更高；B小牌占比也略低，贵族覆盖和效率更高。B比A更重小牌/贵族，但仅凭这些终局数据仍不能确认Beta或Balance。','']
    for g in data['groups'][1:]:
        md += [f"## {g['title']}",'',g['note'],'','对手：'+ ' / '.join(g['fixture']),'',
               '| 模型 | N | 本方模式 | 低VP张/局 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main | 首4–5VP本人Main | 购入覆盖 | 12Main低VP张/局 |',
               '| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
        rows=[r for r in data['records'] if r['group']==g['id']]
        for r in rows:md.append(f"| {r['model']} | {r['games']} | {r['actor_mode']} | {fmt(r['low_cards'])} | {fmt(r['low_share'],True)} | {fmt(r['big_printed_vp'])} | {fmt(r['noble_coverage'],True)} | {fmt(r['vp_main'])} | {fmt(r['first_big_main'])} | {fmt(r['first_big_coverage'],True)} | {fmt(r['early_low_cards'])} |")
        md += ['','| 模型 | 0VP张/局 | 1VP | 2VP | 3VP | 4VP | 5VP |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
        for r in rows:md.append('| '+r['model']+' | '+' | '.join(fmt(v) for v in r['cards_by_vp'])+' |')
        md.append('')
    md+=['## 计算与来源','','低VP占比=Σ0–1VP张数/Σ购牌数；大牌VP/局=Σ3–5VP印刷分/N；贵族覆盖=有贵族局数/N；VP/Main=Σ最终VP/Σ本人Main。首大牌Main仅在实际购入局求均值，按购入覆盖局数合并。首次时点/覆盖缺项不填0。','',
         '模式来源：M55/M56保存的实际anchors配置；M59/M60冻结evaluation模式与已完成结果，M61/M62保存execution模式与结果；M63/M65保存greedy配置/plan/结果SHA一致。模式声明审计未重新执行历史回放或Rust规则。完整双方逐对手数据仍保留在原结果，CSV为此次派生画像。','',
         '历史模式不混合成统一风格阈值。所有新分类政策仍为事后描述性；未发布/晋级任何新版本。','', '### 来源SHA','']
    for p,h in data['source_hashes'].items():md.append(f'- `{p}` SHA `{h}`')
    (ROOT/'docs/prism/style-history-2026-10-08.md').write_text('\n'.join(md)+'\n',encoding='utf-8')


if __name__=='__main__':build()
