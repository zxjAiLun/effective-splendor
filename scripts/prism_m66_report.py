"""M66 fixed-cohort competitive analysis and common readable report; zero games."""
import copy
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest
from scripts.prism_m66_train import contract


def block_values(rows,model,opponent):
    paired={}
    for row in rows:
        if (row['candidate'],row['opponent'])!=(model,opponent):continue
        seats=paired.setdefault(row['seed'],{})
        if row['candidate_seat'] in seats:raise ValueError('duplicate seed/seat')
        seats[row['candidate_seat']]=row['candidate_score']
    if not paired or any(set(seats)!={0,1} for seats in paired.values()):raise ValueError('incomplete paired blocks')
    return sorted(paired),np.array([sum(paired[s].values())/2 for s in sorted(paired)])


def measure(values,seed=66029999,count=20000,lower=.025):
    values=np.asarray(values,dtype=float)
    if values.ndim!=1 or len(values)==0 or not np.isfinite(values).all():raise ValueError('invalid bootstrap input')
    rng=np.random.default_rng(seed);draws=[]
    for i in range(0,count,256):
        draws.extend(values[rng.integers(0,len(values),(min(256,count-i),len(values)))].mean(1))
    return {'mean':float(values.mean()),'ci95':np.quantile(draws,[.025,.975]).tolist(),
            'simultaneous_one_sided_lower':float(np.quantile(draws,lower)),
            'seed_blocks':len(values),'bootstrap_seed':seed,'bootstrap_samples':count,'lower_quantile':lower}


def competitive(c,reference,candidate,direct):
    e=c['evaluation'];deltas=[]
    for opponent in e['common_opponents']:
        sa,a=block_values(reference,'base',opponent);sb,b=block_values(candidate,'candidate',opponent)
        if sa!=sb or sa!=list(range(e['common_seed_start'],e['common_seed_end']+1)):raise ValueError('common seed cohort mismatch')
        deltas.append(b-a)
    sd,d=block_values(direct,'candidate','parent')
    if sd!=list(range(e['direct_seed_start'],e['direct_seed_end']+1)):raise ValueError('direct seed cohort mismatch')
    vectors={'candidate/strength_pool':np.mean(deltas,axis=0),'candidate/direct_parent':d}
    measurements={k:measure(v,e['bootstrap_seed'],e['bootstrap_samples'],e['lower_quantile']) for k,v in vectors.items()}
    gates={k:v['simultaneous_one_sided_lower']>=e['gates'][k] for k,v in measurements.items()}
    enhancements={k:v['simultaneous_one_sided_lower']>e['enhancement_thresholds'][k] for k,v in measurements.items()}
    return measurements,gates,enhancements


def build():
    c=contract();e=c['evaluation'];base=ROOT/'evaluation';records={};rows={};refs=[];pairs=[]
    from scripts.prism_notebook_arena import completed_shard
    for name,expected in [('reference',3072),('candidate',3072),('direct',1024)]:
        work=base/name;raw=read(work/'result.json');plan=read(work/'plan.json');config=read(work/'config.json')
        state=read(work/'status.json');done=read(work/'completion.json')
        if raw['games']!=expected or done['games']!=expected or done['result_sha256']!=digest(work/'result.json'):raise ValueError('arena completion/result mismatch')
        if raw['config_sha256']!=digest(work/'config.json') or raw['plan_sha256']!=digest(work/'plan.json'):raise ValueError('arena provenance drift')
        if done['automatic_game_retries']!=0 or config['action_seed']!=e['action_seed']:raise ValueError('arena protocol drift')
        expected_seeds=list(range(e['direct_seed_start' if name=='direct' else 'common_seed_start'],e['direct_seed_end' if name=='direct' else 'common_seed_end']+1))
        if config['seeds']!=expected_seeds:raise ValueError('arena seeds drift')
        rows[name]=[r for shard in plan['shards'] for r in completed_shard(shard,state['shards'][shard['name']])]
        if len(rows[name])!=expected:raise ValueError('saved rows count mismatch')
        ref={'stage':'direct' if name=='direct' else 'common','label':'独立直接起点对照' if name=='direct' else '独立共同对手对照',
             'result':(work/'result.json').relative_to(ROOT).as_posix(),'sha256':digest(work/'result.json'),
             'plan':(work/'plan.json').relative_to(ROOT).as_posix(),'plan_sha256':digest(work/'plan.json'),
             'config':(work/'config.json').relative_to(ROOT).as_posix(),'config_sha256':digest(work/'config.json'),
             'completion':(work/'completion.json').relative_to(ROOT).as_posix(),'completion_sha256':digest(work/'completion.json')}
        refs.append(ref);records[name]={'raw':raw,'plan':plan,'config':config,'state':state}
        pairs.extend(raw['pairs'])
    refconf=records['reference']['config'];candconf=records['candidate']['config']
    if refconf['engine']!=candconf['engine'] or refconf['opponents']!=candconf['opponents']:raise ValueError('reference/candidate runtime mismatch')
    audit=read(ROOT/'final-audit/audit.json');candidate_sha=audit['weights_sha256']
    if audit['status']!='PASS_TRAINING_ARTIFACT_AUDIT':raise ValueError('candidate audit required')
    for name,key,expected_sha in [('reference','base',c['base_model']['sha256']),('candidate','candidate',candidate_sha),('direct','candidate',candidate_sha)]:
        desc=records[name]['config']['candidates'][key]
        if desc['args'][0]!='agent-prism' or desc['files'][0]['sha256']!=expected_sha:raise ValueError('candidate identity/mode drift')
        if any(p['mode']!='greedy' for p in records[name]['plan']['opponents'].values()):raise ValueError('opponent not greedy')
    measurements,gates,enhancements=competitive(c,rows['reference'],rows['candidate'],rows['direct'])
    result={'format':'m66-prism-fixed-greedy-result-v1','status':'COMPLETED_FIXED_GREEDY_EVALUATION',
            'games':7168,'action_mode':'both-greedy','candidate_sha256':{'base':c['base_model']['sha256'],'candidate':candidate_sha},
            'acceptance_policy':e,'measurements':measurements,'gates':gates,'enhancements':enhancements,
            'verdicts':{'competitive_retention':'PASS' if all(gates.values()) else 'NOT_CONFIRMED',
                        'overall_enhancement':enhancements['candidate/strength_pool'],'style':'OBSERVED_PROFILE_NOT_A_VETO',
                        'published':False,'default_replaced':False},'source_result_sha256':[r['sha256'] for r in refs],
            'source_config_sha256':digest(ROOT/'benchmarks/m66-prism-alpha-dsw.config.json'),
            'training_audit_sha256':digest(ROOT/'final-audit/audit.json'),'pairs':pairs}
    target=ROOT/'benchmarks/m66-prism-alpha-dsw.result.json'
    if target.exists():raise ValueError('M66 result already exists; no rewrite')
    write(target,result)
    docs=ROOT/'docs/prism';docs.mkdir(parents=True,exist_ok=True)
    evidence=docs/'m66-prism-alpha-dsw-evidence.md'
    text=['# M66 原始结果与Agent审计','', '动作模式：双方greedy；训练采样不参与本表。',
          '本轮结果不等于自动发布；风格不作整体否决。','',
          '| 竞技检验 | 冻结下界阈值 | 估计 | 配对区间 | 校正下界 | 原判定 |',
          '| --- | --- | --- | --- | --- | --- |']
    for k,m in measurements.items():text.append(f"| {k} | {e['gates'][k]} | {m['mean']} | {m['ci95']} | {m['simultaneous_one_sided_lower']} | {'PASS' if gates[k] else 'NOT_CONFIRMED'} |")
    text+=['','阈值未满足表示保留/增强证据不足，不自动证明退化；详情与逐对手代价在完整表。','',
           '```json',json.dumps({k:v for k,v in result.items() if k!='pairs'},ensure_ascii=False,indent=2),'```']
    for name in records:text+=['','# '+name+' 原始完整报告','',(base/name/'report.md').read_text(encoding='utf-8')]
    evidence.write_text('\n'.join(text),encoding='utf-8')
    import markdown
    evidence.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8">'+markdown.markdown(evidence.read_text(encoding='utf-8'),extensions=['tables','fenced_code']),encoding='utf-8')
    delta=measurements['candidate/strength_pool']['mean']*100;direct_score=measurements['candidate/direct_parent']['mean']*100
    by={(p['candidate'],p['opponent']):p for p in pairs}
    def profile(model):
        ps=[by[model,o]['candidate_metrics'] for o in e['common_opponents']];n=sum(p['games'] for p in ps)
        return {'vp_main':sum(p['mean_prestige']*p['games'] for p in ps)/sum(p['total_main_actions'] for p in ps),
            'noble':sum(p['games_with_nobles'] for p in ps)/n*100,
            'lowvp':sum((p['mean_cards_by_vp']['0']+p['mean_cards_by_vp']['1'])*p['games'] for p in ps)/n,
            'bigscore':sum(sum(v*p['mean_cards_by_vp'][str(v)] for v in (3,4,5))*p['games'] for p in ps)/n}
    a,b=profile('base'),profile('candidate')
    interpretation=(f"相同六对手：VP/本人Main {a['vp_main']:.4f}→{b['vp_main']:.4f}；贵族覆盖率 {a['noble']:.2f}%→{b['noble']:.2f}%；"
        f"0–1VP购牌 {a['lowvp']:.3f}→{b['lowvp']:.3f}张/局；3–5VP牌印刷分 {a['bigscore']:.3f}→{b['bigscore']:.3f}VP/局。"
        '这些是观察到的变化，不凭单个指标定风格或因果；本轮暂保留Alpha起点研究候选身份。')
    strength='共同对手增强有证据' if enhancements['candidate/strength_pool'] else '未确认全面增强'
    retention='两项竞争力保留要求均达到' if all(gates.values()) else '竞争力保留尚有未确认项，见Agent审计'
    story={'round':'M66','title':'M66：从 Prism Alpha v0.1.5 继续一次胜负 PPO',
        'headline':f'共同对手相对起点 {delta:+.2f} 个百分点；直接起点半平得分 {direct_score:.2f}%。',
        'question':'固定Alpha起点继续有限胜负PPO，能否保留或改善实战？',
        'identity':'起点 Prism Alpha v0.1.5 → M66最终c4未发布训练检查点。新AdamW/RNG、outcome-only；不是恢复M63全状态，也不是Alpha v0.1.4续训。',
        'conclusions':[{'label':'产物','value':'最终c4核验通过，未发布','explanation':'32导出张量与提交检查点一致，完整保存回放已审计。','tone':'good'},
                      {'label':'竞技','value':strength,'explanation':retention+'；保留逐对手升降和有限种子不确定性。','tone':'good' if all(gates.values()) else 'warn'},
                      {'label':'风格','value':'按实际画像观察，不作一票否决','explanation':'继续比较效率、贵族覆盖、小牌与大牌得分；训练目标不等于风格身份。','tone':'warn'}],
        'interpretation':interpretation,'next':'本轮有限预算完成后停止；是否发布或继续新轮由新的实战评审决定，不自动扩大样本。'}
    wall=sum(v['state']['elapsed_wall_seconds'] for v in records.values())
    spec={'format':'prism-greedy-reading-spec-v1','result':target.relative_to(ROOT).as_posix(),'result_sha256':digest(target),
        'contract':'benchmarks/m66-prism-alpha-dsw.config.json','contract_sha256':digest(ROOT/'benchmarks/m66-prism-alpha-dsw.config.json'),
        'markdown':evidence.relative_to(ROOT).as_posix(),'markdown_sha256':digest(evidence),
        'output':'docs/prism/m66-prism-alpha-dsw-comparison.html','focus':'candidate','baseline':'base',
        'names':dict(c['names'],base=c['names']['parent']),'greedy_weight_sha256':result['candidate_sha256'],
        'greedy_results':refs,'story':story,
        'human_timing':{'workers':4,'games_per_minute':7168/wall*60,'minutes_per_1000':wall/7168*1000/60,
                        'clock_scope':'三个arena活动墙钟之和，含派发、保存回放审计与报告；不含训练/准备/下载/最终M66统计'},
        'related_reports':[{'label':'M65起点来源','href':'m65-prism-version-release-comparison.html'}]}
    spec_path=ROOT/'benchmarks/reports/m66-reading.json';write(spec_path,spec)
    from scripts.prism_round_report import build as reading
    receipt=reading(spec_path)
    return {'status':result['status'],'result_sha256':digest(target),'reading_receipt':receipt,'games':7168}


if __name__=='__main__':print(json.dumps(build(),ensure_ascii=False))
