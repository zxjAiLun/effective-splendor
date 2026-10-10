"""Human report projection. Audit provenance stays in separate files."""
import copy
import html
import json
from pathlib import Path


def clean_pair(pair, candidate_mode='sample', opponent_mode=None):
    keep=('candidate','opponent','candidate_metrics','opponent_metrics','macro','seats','score_uncertainty','win_uncertainty')
    p={k:copy.deepcopy(pair[k]) for k in keep}
    for k in ('candidate_trajectory','opponent_trajectory'):
        if k in pair:p[k]=copy.deepcopy(pair[k])
    p.update(candidate_mode=candidate_mode,opponent_mode=opponent_mode or ('greedy' if 'greedy' in pair.get('opponent_display','') else 'sample'))
    return p


def supplement(root,spec):
    records={};timing=None;cohorts={}
    diagnostic=None
    if spec.get('greedy_trajectory'):
        import hashlib
        ref=spec['greedy_trajectory'];path=root/ref['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==ref['sha256'],'greedy trajectory drift'
        diagnostic=json.loads(path.read_text(encoding='utf-8'))
        assert diagnostic['new_games']==0,'trajectory must not dispatch games'
        assert len({(p['candidate'],p['opponent']) for p in diagnostic['pairs']})==len(diagnostic['pairs']),'duplicate trajectory pair'
    for item in spec.get('greedy_results',[]):
        path=root/item['result'];raw=json.loads(path.read_text(encoding='utf-8'))
        import hashlib
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],'greedy result drift'
        plan=json.loads((root/item['plan']).read_text(encoding='utf-8'))
        config=json.loads((root/item['config']).read_text(encoding='utf-8'))
        assert hashlib.sha256((root/item['plan']).read_bytes()).hexdigest()==item['plan_sha256'],'greedy plan drift'
        assert hashlib.sha256((root/item['config']).read_bytes()).hexdigest()==item['config_sha256'],'greedy config drift'
        assert raw['config_sha256']==plan['config_sha256']==item['config_sha256']
        assert raw['plan_sha256']==item['plan_sha256']
        if diagnostic:
            assert raw['source_ledger_sha256']==diagnostic['source_ledger_sha256'][path.parent.name],'trajectory source cohort drift'
        pairs=[]
        for source in raw['pairs']:
            m,o=source['candidate'],source['opponent']
            assert plan['candidates'][m]['mode']==plan['opponents'][o]['mode']=='greedy'
            assert config['candidates'][m]['args'][0]=='agent-prism'
            assert config['opponents'][o]['args'][0] in ('agent-prism','agent-heuristic-v02')
            assert source['candidate_metrics']['games'] <= 2 * len(config['seeds'])
            assert config['candidates'][m]['files'][0]['sha256']==spec['greedy_weight_sha256'][m],'greedy candidate weight drift'
            assert sum(source['candidate_metrics'][k] for k in ('wins','ties','losses'))==source['candidate_metrics']['games']
            p=copy.deepcopy(source)
            for old,new in [('score_ci','score_uncertainty'),('win_ci','win_uncertainty')]:
                ci=p.pop(old);p[new]=dict(ordinary_95_ci=ci['ci95'],seed_blocks=ci['seed_blocks'])
            if diagnostic:
                trajectory=next(t for t in diagnostic['pairs'] if (t['candidate'],t['opponent'])==(m,o))
                for role in ('candidate','opponent'):
                    profile=trajectory[role+'_trajectory'];assert profile['games']==p[role+'_metrics']['games'],'trajectory actor coverage drift'
                    p[role+'_trajectory']=profile
            p.update(candidate_mode='greedy',opponent_mode='greedy');pairs.append(clean_pair(p,'greedy','greedy'))
        key=item['stage']
        cohort=(config['seeds'],config['action_seed'],config['engine'])
        if key in cohorts:assert cohorts[key]==cohort,'cannot combine different greedy cohorts'
        cohorts[key]=cohort
        record=records.setdefault(key,dict(label=item['label'],pairs=[],games=0))
        assert not {(p['candidate'],p['opponent']) for p in record['pairs']}.intersection((p['candidate'],p['opponent']) for p in pairs),'duplicate supplementary pair'
        record['pairs'].extend(pairs);record['games']+=raw['games']
    return records,timing


def write_markdown(path,payload):
    s=payload['story'];lines=['# '+s['title'],'',payload['history_headline'] if payload['view']=='history' else s['headline'],'']
    lines += [f"**{c['label']}：{c['value']}。** {c['explanation']}\n" for c in s['conclusions']]
    lines += ['',s['identity'],'','模式：'+('历史采样，候选T=1。' if payload['view']=='history' else '双方greedy。'),'']
    names=payload['names'];focus=payload['focus'];base=payload['comparison_baseline']
    def table(heads,rows):return ['| '+' | '.join(heads)+' |','| '+' | '.join(['---']*len(heads))+' |',*['| '+' | '.join(map(str,r))+' |' for r in rows],'']
    def compare(a,b,d=4,direction='more',scale=1):
        texts=[f'{a*scale:.{d}f}',f'{b*scale:.{d}f}'];winner=(0 if (a<b if direction=='low' else a>b) else 1) if a!=b and texts[0]!=texts[1] else -1
        return [f'**{t} {"✓" if direction!="more" else "↑"}**' if i==winner else t for i,t in enumerate(texts)]
    for stage,record in payload['result'].items():
        lines+=['## '+record['label'],''];by={(p['candidate'],p['opponent']):p for p in record['pairs']}
        matrix=[]
        for p in record['pairs']:
            if p['candidate']!=focus:continue
            a=by.get((base,p['opponent']));b=p['candidate_metrics']
            values=compare(a['candidate_metrics']['score_rate'],b['score_rate'],2,'high',100) if a else ['未测',f'{b["score_rate"]*100:.2f}']
            matrix.append([names.get(p['opponent'],p['opponent']),*values,f'{(b["score_rate"]-a["candidate_metrics"]["score_rate"])*100:+.2f}' if a else '未测'])
        lines+=table(['对手',names.get(base,base)+' 半平得分%',names[focus]+' 半平得分%','变化（百分点）'],matrix)
        for p in record['pairs']:
            a,b=p['candidate_metrics'],p['opponent_metrics'];cn=names.get(p['candidate'],p['candidate']);on=names.get(p['opponent'],p['opponent'])
            lines+=['### '+cn+' 对阵 '+on,'',f"双方归属：{cn}本人 / {on}本人。{a['games']}局，{p['score_uncertainty']['seed_blocks']}个双座种子块；候选{p['candidate_mode']}，对手{p['opponent_mode']}。",'']
            rows=[]
            keys=[('胜局','wins','high'),('平局','ties','more'),('负局','losses','low'),('纯胜率%','win_rate_percent','high'),('半平得分','score_rate','high'),('最终VP/局','mean_prestige','high'),('VP/本人Main','vp_per_main_action','high'),('VP/本人决策','vp_per_turn','high'),('VP/全局步','vp_per_ply','high'),('贵族/局','mean_nobles','high'),('贵族覆盖率%','games_with_nobles_percent','high'),('永久折扣/局','mean_permanent_bonuses','more'),('预留获得/局','mean_reserves_acquired','more'),('预留买回/局','mean_reserves_bought','more'),('终局未买回预留/局','mean_reserves_stranded','low'),('预留买回率%','reserve_redemption_rate_percent','high')]
            rows += [[label,*compare(a[k],b[k],d=0 if k in ('wins','ties','losses') else 2 if k.endswith('_percent') else 4,direction=direction)] for label,k,direction in keys]
            rows += [[f'{vp} VP牌/局',*compare(a['mean_cards_by_vp'][str(vp)],b['mean_cards_by_vp'][str(vp)])] for vp in range(6)]
            colors={'White':'白','Blue':'蓝','Green':'绿','Red':'红','Black':'黑'}
            rows += [[colors[color]+'折扣/局',*compare(a['mean_bonuses_by_color'][color],b['mean_bonuses_by_color'][color])] for color in a['mean_bonuses_by_color']]
            lines+=table(['个人指标',cn,on],rows)
            actions={'buy_market':'买公开牌','buy_reserved':'买回预留牌','take_tokens':'拿宝石','reserve_market':'预留公开牌','reserve_deck':'盲预留','choose_noble':'选择贵族','pass':'跳过'}
            lines+=table(['动作',cn+' 次数',on+' 次数',cn+' 占比%',on+' 占比%'],[[actions[k],*compare(a['action_distribution'][k],b['action_distribution'][k],0),*compare(a['action_percentages'][k],b['action_percentages'][k],2)] for k in a['action_distribution']])
            lines+=table(['模型物理座位','局数','模型胜/平/负','模型纯胜%','模型半平得分','模型VP/局','对手VP/局'],[[str(s['candidate_seat']),str(s['candidate']['games']),'/'.join(str(s['candidate'][k]) for k in ('wins','ties','losses')),f"{s['candidate']['win_rate_percent']:.4f}",f"{s['candidate']['score_rate']:.4f}",*compare(s['candidate']['mean_prestige'],s['opponent']['mean_prestige'],direction='high')] for s in p['seats']])
            interval=lambda key:' ～ '.join('NOT_MEASURED' if v is None else f'{v*100:.2f}%' for v in p[key]['ordinary_95_ci'])
            lines += ['纯胜率配对95%区间：'+interval('win_uncertainty')+'；半平得分配对95%区间：'+interval('score_uncertainty')+'。','']
            macro={'mean_plies':'平均全局步数','mean_turns':'平均轮数','min_turns':'最少轮数','median_turns':'中位轮数','max_turns':'最多轮数','std_turns':'轮数标准差','mean_victory_margin':'终局绝对分差VP','close_games_margin_le_2_percent':'分差≤2的对局%','process_wall_seconds_mean':'单局进程墙钟平均秒','process_wall_seconds_p95':'单局进程墙钟P95秒'}
            lines+=table(['整局指标（两人共同）','值'],[[label,str(p['macro'].get(k,'NOT_MEASURED'))] for k,label in macro.items()]+[['决策 / 推理耗时','NOT_MEASURED / NOT_MEASURED']])
            if p.get('candidate_trajectory'):
                ca,ob=p['candidate_trajectory'],p['opponent_trajectory']
                lines+=table(['个人实战节奏',cn,on],[['20Main内达到8分%',*compare(ca['vp8_by_main20_rate'],ob['vp8_by_main20_rate'],2,'high',100)],['首张4–5 VP牌时点（本人Main，条件均值）',*compare(ca['first_4plus_card_main']['conditional_mean'],ob['first_4plus_card_main']['conditional_mean'],3,'low')],['购到4–5 VP牌的局数比例%',*compare(ca['first_4plus_card_main']['coverage_rate'],ob['first_4plus_card_main']['coverage_rate'],2,'more',100)]])
                lines += ['首张4–5 VP牌时点仅统计实际买到该类牌的对局，覆盖率另列；20Main内达到8分比例 = 达到该分数的局数 / 全部局数。','']
    if not payload['result']:lines+=['双方greedy战绩：NOT_RUN。','']
    if payload.get('timing'):
        t=payload['timing'];lines+=['实测并发：'+str(t['workers'])+'路；每分钟'+f"{t['games_per_minute']:.1f}"+'局；1000局'+f"{t['minutes_per_1000']:.2f}"+'分钟。时钟：'+t['clock_scope']+'。','']
    lines+=['得分效率 = 累计终局VP ÷ 本人Main总数；贵族覆盖率 = 至少获得一个贵族的局数 ÷ 总局数；低分牌占比 = 0–1 VP购牌张数 ÷ 全部购牌张数；预留买回率 = 总买回 ÷ 总获得。','',s['interpretation'],'',s['next'],'']
    path.write_text('\n'.join(lines),encoding='utf-8')


def build_human(root,templates,spec,result,output,safe_json,relative):
    history=output.with_suffix('.sampling.html');audit=output.with_suffix('.audit.html');names=dict(spec['names'])
    names.update(spec.get('greedy_names',{}))
    records,_=supplement(root,spec)
    historic={k:dict(label='历史'+('独立评测' if k=='acceptance' else '开发评测')+' · 候选T=1',pairs=[clean_pair(p) for p in result[k]['pairs']]) for k in ('acceptance','development') if result.get(k)}
    base=spec.get('comparison_baseline',spec.get('_practical_review',{}).get('parent_key',spec['baseline']))
    story=copy.deepcopy(spec['story'])
    story.update(spec.get('human_story',{}))
    template=(templates/'prism-reading.html').read_text(encoding='utf-8');css=(templates/'prism-reading.css').read_text(encoding='utf-8');js=(templates/'prism-human.js').read_text(encoding='utf-8')
    for target,view,rows in [(history,'history',historic),(output,'greedy',records)]:
        selected_story=copy.deepcopy(story)
        if view=='history':selected_story.update(spec.get('history_story',{}))
        elif not rows:
            selected_story['headline']='双方 greedy 对照尚未生成；历史采样复盘已单独保留。'
            selected_story['conclusions']=[dict(label='产物',value='权重已固定',explanation='原训练和历史评测完成。',tone='good'),dict(label='greedy实战',value='未测完',explanation='本页不把历史采样胜率冒充 greedy。',tone='warn'),dict(label='路线',value='暂定，未发布',explanation='待得分效率、贵族覆盖与购牌倾向对照。',tone='warn')]
        selected_story={k:selected_story[k] for k in ('round','title','headline','identity','conclusions','interpretation','next')}
        payload=dict(schema='prism-human-report-v2',view=view,story=selected_story,focus=spec['focus'],baseline=spec['baseline'],comparison_baseline=base,names=names,result=rows,
            history_headline='历史采样复盘：与原实验相同的数据和动作模式。',timing=spec.get('human_timing') if view=='greedy' else None,
            links=dict(main=output.name,history=history.name,audit=audit.name,markdown=target.with_suffix('.reading.md').name,related=spec.get('related_reports',[])))
        document=template.replace('@@TITLE@@',html.escape(selected_story['title'])).replace('@@CSS@@',css).replace('@@DATA@@',safe_json(payload)).replace('@@JS@@',js)
        target.write_text(document,encoding='utf-8');write_markdown(target.with_suffix('.reading.md'),payload)
    return history
