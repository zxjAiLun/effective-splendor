"""M72: bind existing descriptive atlas to identities and complete evidence tables.

No agent inference, games, training or release operations. Original inputs stay read-only.
"""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path

from scripts.prism_style_atlas import ROOT, aggregate, build, digest, read

OUT = ROOT / 'local-artifacts/prism/style-atlas-20261008'
ROUNDS = {
    'M66': ('benchmarks/m66-prism-alpha-dsw.result.json', 'benchmarks/m66-prism-alpha-dsw.config.json', {'base':'Prism Alpha v0.1.5','candidate':'M66 c4'}),
    'M67': ('benchmarks/m67-prism-alpha-repeat.result.json', 'benchmarks/m67-prism-alpha-repeat.config.json', {'base':'Prism Alpha v0.1.5','candidate-a':'M67 A-c20','candidate-b':'M67 B-c20'}),
    'M70': ('benchmarks/m70-prism-b-continuation.result.json', 'benchmarks/m70-prism-b-continuation.config.json', {'base':'M67 B-c20','candidate':'M70 c4'}),
}
LABELS={'alpha':'Prism Alpha v0.1.4','balance':'Prism Balance v0.1.0','beta':'Prism Beta v0.1.0','general':'Prism v0.1.1','initial':'Prism v0.1.0','heuristic':'Heuristic v0.3.1','released-alpha':'Prism Alpha v0.1.5'}
METRICS=[('low_share','0–1VP购牌占比','%'),('low_cards','0–1VP张/局','张'),('big_printed_vp','3–5VP印刷分/局','VP'),('noble_coverage','贵族覆盖','%'),('vp_main','VP/本人Main','VP/Main')]


def require(ok, reason):
    if not ok: raise ValueError(reason)


def write_json(path, obj):
    (ROOT/path).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def identities():
    inventory=[]
    for old in read('benchmarks/prism-model-catalog-2026-10-05.json')['models']:
        label=old['display_name']
        if label.startswith('M66'): label='M66 c4'
        inventory.append(dict(model=label,weights_path=old['weights_path'],sha256=old['weights_sha256'],
                              parent=old.get('parent'),historical_route=old.get('route','Alpha lineage'),
                              release_state=old['status'],identity_source=old['identity_record']))
    for source in ['benchmarks/m55-prism-alpha-v0.1.0.model.json','benchmarks/m56-prism-alpha-v0.1.1.model.json','benchmarks/m59-prism-alpha-v0.1.2.model.json','benchmarks/m60-prism-alpha-v0.1.3.model.json']:
        old=read(source); w=old.get('weights',{})
        inventory.append(dict(model=old['display_name'],weights_path=old.get('weights_path',w.get('path')).replace('\\','/'),
                              sha256=old.get('weights_sha256',w.get('sha256')),parent=old.get('parent'),historical_route='Alpha',
                              release_state=old.get('status',old.get('identity_status')),identity_source=source,
                              statistics_scope='Historical sampling results excluded from current both-greedy cohorts; no matched greedy row located'))
    parent_alpha=read(ROUNDS['M67'][0])['candidate_sha256']['base']
    for arm in ['a','b']:
        inventory.append(dict(model=f'M67 {arm.upper()}-c20',weights_path=f'local-artifacts/prism/m67-alpha-repeat/r2-failure-harvest-20261007/campaigns/{arm}/cycle-20-export/weights.json',
                              sha256=read(ROUNDS['M67'][0])['candidate_sha256'][f'candidate-{arm}'],
                              parent={'display_name':'Prism Alpha v0.1.5','sha256':parent_alpha},historical_route='Alpha research lineage',
                              training_arm=arm.upper(),training_target='outcome-only PPO, independent training seed',
                              release_state='VERIFIED_UNPUBLISHED_TRAINING_CHECKPOINT',identity_source=ROUNDS['M67'][0]))
    inventory.append(dict(model='M70 c4',weights_path='local-artifacts/prism/m70-b-continuation/result-review/harvest/campaigns/a/cycle-4-export/weights.json',
                          sha256=read(ROUNDS['M70'][0])['candidate_sha256']['candidate'],parent={'display_name':'M67 B-c20','sha256':read(ROUNDS['M70'][0])['candidate_sha256']['base']},
                          historical_route='Alpha research lineage',training_target='outcome-only PPO continuation',
                          release_state='VERIFIED_UNPUBLISHED_TRAINING_CHECKPOINT',identity_source=ROUNDS['M70'][0]))
    require(len({x['sha256'] for x in inventory})==len(inventory),'duplicate weights in inventory')
    for item in inventory:
        require(digest(item['weights_path'])==item['sha256'],f"weight drift: {item['model']}")
        item['weights_verified']=True; item['identity_source_sha256']=digest(item['identity_source'])
        parent=item['parent'] or {};item['parent_label']=parent.get('display_name',parent.get('label',parent.get('model_version','UNKNOWN')))
    return inventory


def validate_metrics(m):
    n=m['games'];require(n>0,'no games')
    require(m['wins']+m['ties']+m['losses']==n,'WDL total')
    require(abs((m['wins']+.5*m['ties'])/n-m['score_rate'])<1e-10,'score mismatch')
    require(abs(m['wins']/n*100-m['win_rate_percent'])<1e-8,'win mismatch')
    require(abs(m['mean_prestige']*n/m['total_main_actions']-m['vp_per_main_action'])<1e-10,'Main denominator mismatch')
    require(sum(m['action_distribution'].values())==m['total_actor_decisions'],'action counts mismatch')


def details(inventory):
    known={x['model']:x['sha256'] for x in inventory}; rows=[]; configs={}
    for rnd,(source,config_path,models) in ROUNDS.items():
        result=read(source);config=read(config_path);configs[config_path]=digest(config_path)
        require(result['action_mode']=='both-greedy','mode mismatch')
        require(result['source_config_sha256']==digest(config_path),'config source drift')
        for pair in result['pairs']:
            cand=models[pair['candidate']];opp=LABELS.get(pair['opponent'],models.get('base') if pair['opponent'] in ['parent','base'] else pair['opponent'])
            require(opp in known or opp=='Heuristic v0.3.1',f'unknown opponent {opp}')
            common=pair['opponent'] in LABELS
            ev=config['evaluation']; prefix='common' if common else 'direct'
            seed_start=ev[f'{prefix}_seed_start']; seed_end=ev[f'{prefix}_seed_end']
            expected=2*(seed_end-seed_start+1)
            for role,label,key in [('candidate',cand,'candidate_metrics'),('opponent',opp,'opponent_metrics')]:
                m=pair[key];validate_metrics(m)
                require(m['games']==pair['macro']['total_games'],'both actor game count')
                seats=[dict(physical_seat=s['candidate_seat'] if role=='candidate' else 1-s['candidate_seat'],metrics=s[role]) for s in pair['seats']]
                require(sum(s['metrics']['games'] for s in seats)==m['games'],'seat games mismatch')
                for field in ['wins','ties','losses','games_with_nobles','total_main_actions','total_actor_decisions']:
                    require(sum(s['metrics'][field] for s in seats)==m[field],f'seat total {field}')
                for s in seats: validate_metrics(s['metrics'])
                ci=pair['score_ci']['ci95']; win_ci=pair['win_ci']['ci95']
                if role=='opponent':ci=[1-ci[1],1-ci[0]];win_ci=None
                rows.append(dict(round=rnd,cohort=prefix,actor=label,other=opp if role=='candidate' else cand,role=role,
                                 sha256=known.get(label),source=source,source_sha256=digest(source),mode='both-greedy',
                                 seed_start=seed_start,seed_end=seed_end,expected_games=expected,missing_games=expected-m['games'],
                                 score_ci95=ci,win_ci95=win_ci,metrics=m,derived=aggregate([m]),seats=seats,macro=pair['macro']))
    return rows,configs


def deliver():
    OUT.mkdir(exist_ok=True,parents=True)
    atlas=build();inventory=identities();rows,configs=details(inventory)
    known={x['model']:x for x in inventory}
    for row in atlas['records']:
        if row['model'] in known:require(row['sha256']==known[row['model']]['sha256'],'atlas identity mismatch')
        row['measured_missing']=['first_big_main','first_big_coverage','early_low_cards','early_discount_redemptions']
        row['identity_state']=known[row['model']]['release_state'] if row['model'] in known else 'NON_NEURAL_REFERENCE'
    a,b,parent=[next(r for r in atlas['records'] if r['group']=='M67-main' and r['model']==name) for name in ['M67 A-c20','M67 B-c20','Prism Alpha v0.1.5']]
    comparisons=[]
    for left,right in [(a,parent),(b,parent),(b,a)]:
        comparisons.append(dict(model=left['model'],reference=right['model'],group='M67-main',
                                matching='near-matched, five original A omissions; descriptive aggregates, no paired style CI',
                                deltas={k:left[k]-right[k] for k,_,_ in METRICS}))
    for item in inventory:
        item['profile_groups']=[r['group'] for r in atlas['records'] if r['model']==item['model']]
        item['route_evidence']='INSUFFICIENT for current v1 policy; historical route names retained'
    proposal={
        'format':'prism-generation-identity-proposal-v1','status':'DESIGNED_NOT_RELEASED','generation':'v0.2.0',
        'authorization':'Owner proposed synchronized v0.2.0 route names, requested screening first; current continuation is statistics and identity work',
        'historical_names_preserved':True,'automatic_release':False,'default_replaced':False,'deployed':False,
        'slots':[
            dict(proposed_name='Prism Alpha v0.2.0',candidate='M67 A-c20',weights_sha256=a['sha256'],state='BOUND_PROPOSAL',rationale='More big-card printed VP and fewer low-VP purchases than matched Alpha parent; timing unmeasured; A retains five evaluation omissions'),
            dict(proposed_name='Prism Beta v0.2.0',candidate='M67 B-c20',weights_sha256=b['sha256'],state='CONDITIONAL_PROPOSAL',rationale='More low-VP cards and nobles than A; does not establish more building than matched Balance; Beta/Balance remains unresolved'),
            dict(proposed_name='Prism Balance v0.2.0',candidate=None,weights_sha256=None,state='UNASSIGNED',rationale='No positive balanced-region evidence; B is an unresolved alternative, not assigned to both slots'),
        ],
        'successor':dict(candidate='M70 c4',weights_sha256=known['M70 c4']['sha256'],parent='M67 B-c20',state='SEPARATE_UNPUBLISHED_CANDIDATE',rationale='Different exact checkpoint, not an alias for B; common pool enhancement passes, direct-parent enhancement unconfirmed'),
        'next_allowed_action':'Review existing-data proposal; owner-directed research publication is separate. No automatic matches, training, deployment or Git push.',
    }
    sources={**atlas['source_hashes'],**configs,'benchmarks/prism-model-catalog-2026-10-05.json':digest('benchmarks/prism-model-catalog-2026-10-05.json')}
    for item in inventory:sources[item['identity_source']]=item['identity_source_sha256']
    payload=dict(format='prism-style-delivery-v2',status='DESCRIPTIVE_SCREENING_NOT_RELEASE',inventory=inventory,
                 groups=atlas['groups'],records=atlas['records'],actor_match_rows=rows,comparisons=comparisons,
                 source_hashes=sources,policy_sha256=digest('benchmarks/prism-style-bands-v1.policy.json'),
                 notes=atlas['notes'],new_games=0,new_training=0)
    write_json('benchmarks/prism-style-delivery-2026-10-08.json',payload)
    write_json('benchmarks/prism-v020-identity-proposal.json',proposal)
    columns=['round','cohort','actor','other','role','physical_seat','games','seed_start','seed_end','sha256','wins','ties','losses','low_share','low_cards','big_printed_vp','noble_coverage','vp_main']
    with (ROOT/'outputs/01a11805-prism-style/prism-style-per-opponent-seat.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
        for r in rows:
            for s in r['seats']:
                m=s['metrics'];d=aggregate([m]);w.writerow({**{k:r[k] for k in ['round','cohort','actor','other','role','seed_start','seed_end','sha256']},'physical_seat':s['physical_seat'],**{k:m[k] for k in ['games','wins','ties','losses']},**{k:d[k] for k,_,_ in METRICS}})
    human=human_markdown(payload,proposal)
    (ROOT/'docs/prism/style-atlas-2026-10-08.md').write_text(human,encoding='utf-8')
    audit=['# M72 Agent审计','',f"来源{len(sources)}份，神经权重{len(inventory)}份已逐字节SHA复核。新局0，训练0。",'', '## 输入绑定','']
    for p,h in sources.items():audit.append(f'- `{p}` SHA `{h}`')
    audit+=['','## 权重身份','']
    for item in inventory:audit.append(f"- {item['model']}: `{item['weights_path']}` SHA `{item['sha256']}`；来源 `{item['identity_source']}`；parent `{item['parent_label']}`。")
    audit+=['','## 统计审计范围','','每对手双方W+D+L=N、半平和纯胜、VP/Main、动作总数与座位计数复算；已有置信区间照录，没有重算研究bootstrap或Rust规则。原source/config SHA验证。购牌总量由完整精度均值×N还原，不从显示值复算。缺项不作为平局。画像percentile仅25模型×cohort快照内的midrank，单个cohort最多6模型。大样本局数不能充当独立模型样本数。','', '## 原结果与失败','','M67 A共同池29995/30000，缺5（原2安全错误+3孤立缺项），其共同池正式门未确认；B完整40000局增强门通过。M70双保留通过，共同池增强通过，直接对父增强未确认；总体增强未确认。M66原保留通过、增强未确认。历史Alpha0.1.0未达旧Rush目标仍保留注册研究身份。任何分类器输出均不改变这些原门。','', '## 适配边界','','本轮不是新竞技轮，未修改pin evaluator或使用空模型结果。独立prism-style-delivery-v2适配现有三份result；原报告/结果只读。完整双方表留在人类Markdown，本审计集中完整SHA与技术来源。v1政策为事后设计，不设旧验收PASS。','', '## 检查回执','','分类测试、Excel公式/原生图表、桌面与窄屏像素、DOM交互、链接和Git检查见 `local-artifacts/prism/style-atlas-20261008/closeout.json`。完成前状态IN_PROGRESS，不把HTML存在算视觉PASS。']
    (ROOT/'docs/prism/style-atlas-2026-10-08.audit.md').write_text('\n'.join(audit)+'\n',encoding='utf-8')
    write_json('local-artifacts/prism/style-atlas-20261008/data-validation.json',dict(status='PASS',neural_weights_verified=len(inventory),actor_match_rows=len(rows),actor_seat_rows=2*len(rows),groups=len(atlas['groups']),group_records=len(atlas['records']),source_hashes=sources,original_result_hashes=atlas['source_hashes'],new_games=0))
    print(json.dumps({'weights':len(inventory),'actor_match_rows':len(rows),'seat_rows':2*len(rows),'comparisons':comparisons},ensure_ascii=False))


def fmt(v,unit='%'):
    if v is None:return 'NOT_MEASURED'
    return f'{100*v:.2f}%' if unit=='%' else f'{v:.4f}' if unit=='VP/Main' else f'{v:.3f}'


def human_markdown(data,proposal):
    md=['# Prism 模型统计画像与 v0.2.0 身份方案','','产物：14份神经权重身份逐项核实；6个cohort、25份模型画像、逐对手/座位表与24张Excel图。','',
        '竞技：沿用原证据。M67 B增强通过；A有5缺项，共同池正式增强未确认。M70共同池增强通过，直接父代增强未确认。','',
        '风格：M67 A相对父代更偏大牌；B相对A更多小牌和贵族。B相对Alpha父代的小牌占比反而略低，不能仅据A/B差异把B确认为Beta。匹配Balance及必要时点/兑现证据不足。','',
        '分布修订：[真实分布与模型位置](style-atlas-2026-10-08.html#distributions) / [完整分布统计](style-distributions-2026-10-08.md)。模型均值分布按cohort分开；M70逐局分布复用B/c4各3,072局，均值口径与原合并比率分别说明。','',
        '历史补充：[早期模型实际统计](style-history-2026-10-08.md) / [历史对照CSV](../../outputs/01a11805-prism-style/prism-historical-profiles.csv)。新增10组29份画像，连同原资料共16组54份；包含初代、通用、早期Alpha及Balance/Beta。互动分布增加历史Balance参照线。T1/greedy和不同对手池分组保存，同一精确对手下的跨seed历史差值仍为描述性。原Excel未改，此新增数据可通过CSV导入。','',
        '## A、B与父代：同一组中比较','','双方greedy，M67共同六对手，父/B各30000局、A29995局。未对缺5局填值；下表为近匹配描述性汇总。购牌分组为印刷VP，实体卡层级是1–3，不是“1费到5费”。','',
        '| 模型 | 0–1VP张/局 | 低VP占比 | 大牌印刷VP/局 | 贵族覆盖 | VP/本人Main |','| --- | ---: | ---: | ---: | ---: | ---: |']
    main=[r for r in data['records'] if r['group']=='M67-main']
    for r in main:md.append('| '+r['model']+' | '+' | '.join(fmt(r[k],u) for k,_,u in [METRICS[1],METRICS[0],*METRICS[2:]])+' |')
    md+=['','| 比较（当前−参照） | 低VP占比pp | 低VP张/局 | 大牌VP/局 | 贵族覆盖pp | VP/Main |','| --- | ---: | ---: | ---: | ---: | ---: |']
    for c in data['comparisons']:
        d=c['deltas'];md.append(f"| {c['model']} − {c['reference']} | {100*d['low_share']:+.2f} | {d['low_cards']:+.3f} | {d['big_printed_vp']:+.3f} | {100*d['noble_coverage']:+.2f} | {d['vp_main']:+.4f} |")
    md+=['','## 如何自动分类','','政策是事后描述性v1，数值为可解释的工程起点，尚未用独立数据校准为统计总体分界。先查精确权重/规则/实际网格digest/模式/种子/座次和完整度，再分别检查三路线必要字段；缺项列清单。多路线同时达区间为mixed；未知路线不能被默认排除。完整数据落区间也只有DESCRIPTIVE。','',
        '| 路线 | 相对精确匹配Balance的区间组合 |','| --- | --- |',
        '| Alpha | 大牌印刷VP/局≥+0.5、低VP占比≤−2pp；首张4–5VP早≥1本人Main，购入覆盖降幅≤5pp |',
        '| Beta | 低VP占比≥+2pp、低VP张/局≥+0.3；12Main内低VP购牌≥+0.3张，24Main内真实折扣兑现≥+0.3单位 |',
        '| Balance | 低VP占比±2pp、大牌VP±0.5、早期低VP张数±0.3；首大牌±1Main、购入覆盖和贵族覆盖±5pp |','',
        '这里的Balance仅表示落入描述区间；确认性均衡仍须预先冻结正向定义及等效区间政策。早期投资兑现沿用M62：Main≤12购0–1VP牌，后续Main≤24按实际购买成本与购前折扣识别被使用，每投资最多3次、每局总最多24次；不是终局折扣总量。首次4–5VP时点只在实际购入局求均值，并同时报告覆盖。','',
        '百分位公式：`(低于该值的模型数 + 0.5×同值模型数)/本组模型数`。只在固定同cohort模型名单内排序；M67候选组仅3个模型，大量对局提高画像精度，不把名单变成大型模型总体。','',
        '## 版本身份：统一新代际，保留旧历史','','| 拟用型号 | 精确候选 | 当前方案状态 |','| --- | --- | --- |']
    for slot in proposal['slots']:md.append(f"| {slot['proposed_name']} | {slot['candidate'] or '尚未指定'} | {slot['state']} |")
    md+=['','A优先对应Alpha v0.2.0提案；B的Beta/Balance归属待证据；Balance空位保持未指定。M70 c4是B的后代且权重不同，不默默替换B或与它共用一个身份。旧v0.1.x登记保留，下一代可统一从v0.2.0开始。此轮交付身份方案，未实际发布、默认替换或部署。','',
        '## 模型身份与血缘','','| 模型 | 来源父代 | 既有身份 | 本轮可比画像 |','| --- | --- | --- | --- |']
    for i in data['inventory']:md.append(f"| {i['model']} | {i['parent_label']} | {i['release_state']} | {', '.join(i['profile_groups']) or '当前greedy cohort无数据；旧sampling另存'} |")
    md+=['','Heuristic v0.3.1是非神经锚点，其运行身份由各轮冻结config绑定，不伪造权重SHA。早期Alpha0.1.0–0.1.3已纳入身份清单；其旧sampling/不同启发式对手不并入本轮greedy排名。中间所有checkpoint未穷尽。','',
        '## 分组画像与公式','','`低VP占比=Σ0–1VP购牌数/Σ全部购牌数`；`贵族覆盖=有贵族局数/N`；`大牌印刷分/局=Σ3–5VP牌数×印刷VP/N`；`VP/Main=Σ最终VP/Σ本人Main`。贵族选择不新增Main。显示值高不表示实际更优。','']
    for g in data['groups']:
        md += [f"### {g['id']}",'', '对手组合：'+ '、'.join(g['fixture'])+'。本组分别排序，跨组不合并。','', '| 模型 | 局数 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main |','| --- | ---: | ---: | ---: | ---: | ---: |']
        for r in data['records']:
            if r['group']==g['id']:md.append(f"| {r['model']} | {r['games']} | {fmt(r['low_share'])} | {fmt(r['big_printed_vp'],'VP')} | {fmt(r['noble_coverage'])} | {fmt(r['vp_main'],'VP/Main')} |")
    md += ['','## 完整逐对手双方表','','下列均双方greedy。半平=(W+0.5D)/N，纯胜=W/N；CI沿用原paired-seed结果，未重新估计风格CI。双方高显示值加粗仅表示数量更高，持平无标记。共局宏观时钟不是纯推理延迟。未测时点/早期兑现/推理延迟为NOT_MEASURED。','']
    for pos in range(0,len(data['actor_match_rows']),2):
        c,o=data['actor_match_rows'][pos:pos+2];cm=c['metrics'];om=o['metrics'];macro=c['macro']
        md += [f"### {c['round']} {c['cohort']}：{c['actor']} 对 {o['actor']}",'',f"计划seed {c['seed_start']}–{c['seed_end']}双座；实际{cm['games']}/{c['expected_games']}局，缺项{c['missing_games']}。双方各自指标如下。",'',f"| 指标 | {c['actor']} | {o['actor']} |",'| --- | ---: | ---: |']
        values=[('W / D / L',f"{cm['wins']} / {cm['ties']} / {cm['losses']}",f"{om['wins']} / {om['ties']} / {om['losses']}")]
        vals=[('纯胜率',cm['wins']/cm['games'],om['wins']/om['games'],'%'),('半平得分',cm['score_rate'],om['score_rate'],'%'),('最终VP/局',cm['mean_prestige'],om['mean_prestige'],'VP'),('VP/本人Main',cm['vp_per_main_action'],om['vp_per_main_action'],'VP/Main'),('贵族数量/局',cm['mean_nobles'],om['mean_nobles'],'张'),('贵族覆盖',cm['games_with_nobles']/cm['games'],om['games_with_nobles']/om['games'],'%')]
        vals += [(f'{v}VP购牌张/局',cm['mean_cards_by_vp'][str(v)],om['mean_cards_by_vp'][str(v)],'张') for v in range(6)]
        vals += [(f'{color}折扣/局',cm['mean_bonuses_by_color'][color],om['mean_bonuses_by_color'][color],'单位') for color in cm['mean_bonuses_by_color']]
        vals += [(f'预留{key}',cm['mean_reserves_'+key],om['mean_reserves_'+key],'张') for key in ['acquired','bought','stranded']]
        vals += [('预留兑现率',cm['reserve_redemption_rate_percent']/100,om['reserve_redemption_rate_percent']/100,'%')]
        for label,x,y,u in vals:
            xs,ys=fmt(x,u),fmt(y,u)
            if xs!=ys:
                if x>y:xs='**'+xs+'** ↑'
                else:ys='**'+ys+'** ↑'
            values.append((label,xs,ys))
        for action in cm['action_distribution']:
            values.append((action+' 次数/占全部动作%',f"{cm['action_distribution'][action]} / {cm['action_percentages'][action]:.2f}%",f"{om['action_distribution'][action]} / {om['action_percentages'][action]:.2f}%"))
        for label,x,y in values:md.append(f'| {label} | {x} | {y} |')
        md+=['',f"半平配对95%区间：{c['actor']} {fmt(c['score_ci95'][0])}–{fmt(c['score_ci95'][1])}；{o['actor']} {fmt(o['score_ci95'][0])}–{fmt(o['score_ci95'][1])}。纯胜率配对95%区间：{c['actor']} {fmt(c['win_ci95'][0])}–{fmt(c['win_ci95'][1])}；{o['actor']} NOT_MEASURED（有平局时不能取1−候选纯胜区间）。",'', '| 本人身份 | 物理座位 | 局数 | W/D/L | 半平 | VP/Main | 贵族覆盖 | 低VP占比 |','| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |']
        for r in [c,o]:
            for s in r['seats']:
                m=s['metrics']; d=aggregate([m]); md.append(f"| {r['actor']} | P{s['physical_seat']} | {m['games']} | {m['wins']}/{m['ties']}/{m['losses']} | {fmt(m['score_rate'])} | {fmt(d['vp_main'],'VP/Main')} | {fmt(d['noble_coverage'])} | {fmt(d['low_share'])} |")
        md+=['',f"全局时长（turns）：均值{macro['mean_turns']:.3f}、中位{macro['median_turns']:.3f}、标准差{macro['std_turns']:.3f}、范围{macro['min_turns']}–{macro['max_turns']}。进程墙钟合计{macro['process_wall_seconds_sum']:.3f}s，平均{macro['process_wall_seconds_mean']:.4f}s，P95 {macro['process_wall_seconds_p95']:.4f}s。决策/纯推理时延NOT_MEASURED。",'']
    md += ['## 可下载产物与后续','','[Excel统计与原生柱状图](../../outputs/01a11805-prism-style/Prism-模型画像与分组柱状图.xlsx) · [逐对手座位CSV](../../outputs/01a11805-prism-style/prism-style-per-opponent-seat.csv) · [机器统计](../../benchmarks/prism-style-delivery-2026-10-08.json) · [身份方案](../../benchmarks/prism-v020-identity-proposal.json) · [Agent审计](style-atlas-2026-10-08.audit.md)。','', '下一允许动作是评审既有画像与精确身份方案。若要求正式Beta/Balance确认，须另冻结匹配评测政策；本轮不因缺项追加研究。若用户指定研究版本发布，可按既有证据说明局限，发布动作与冠军/部署分开。']
    registry_path=ROOT/'benchmarks/prism-v020-model-registry.json'
    if registry_path.exists():
        latest=['# Prism 模型统计画像与固定研究版本','','2026-10-08当前登记：M67 A-c20 = **Prism Alpha v0.2.0**；M67 B-c20 = **Prism Balance v0.2.0**（当前数据基线）；M70 c4 = **Prism Balance v0.2.1**。', '',
                '[固定版本、父代和完整SHA](prism-v020-fixed-models.md) · [版本目录](../../benchmarks/prism-v020-model-registry.json) · [B数据基线](../../benchmarks/prism-balance-data-baseline-v0.2.0.json) · [三模型发布包](../../outputs/01a11805-prism-style/Prism-v0.2-fixed-models.zip)。','',
                '这是用户指定的固定研究版本。原竞技结果、5个缺项、未测时点与统计风格证据等级不变；B路线登记为Balance，不自动升级为“均衡风格已确认”。原Excel保留发布前统计快照。','',
                '## 发布前统计与命名提案历史','','以下原数值和当时命名提案保留；其中未发布/待定措辞属于发布前历史，当前身份以上方固定版本为准。','']
        md=latest+md[2:]
    return '\n'.join(md)+'\n'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--classify-input',help='JSON containing candidate/reference; no games')
    parser.add_argument('--policy',default='benchmarks/prism-style-bands-v020.policy.json',help='Current B baseline policy; pass original v1 policy explicitly for historical replay')
    arg=parser.parse_args()
    if arg.classify_input:
        from scripts.prism_style_atlas import classify_profiles
        request=json.loads(Path(arg.classify_input).read_text('utf-8'))
        print(json.dumps(classify_profiles(request['candidate'],request['reference'],read(arg.policy)),ensure_ascii=False))
    else:deliver()
