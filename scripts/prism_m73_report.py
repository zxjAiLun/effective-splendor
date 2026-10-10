"""Read-only M73 bounded-grid audit, statistics and result-bound reading layer."""
from collections import Counter,defaultdict
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest
from scripts.prism_m73_prepare import CONFIG,ARMS
from scripts.prism_m70_report import measure
from scripts import prism_bounded_eval as bounded,prism_match_details as details,prism_notebook_report as notebook

def blocks(rows,model,opp,expected):
    pairs={}
    for r in rows:
        if (r['candidate'],r['opponent'])!=(model,opp):continue
        seats=pairs.setdefault(r['seed'],{})
        if r['candidate_seat'] in seats:raise ValueError('duplicate block/seat')
        seats[r['candidate_seat']]=r['candidate_score']
    if set(pairs)!=set(expected) or any(set(p)!=set((0,1)) for p in pairs.values()):return None
    return np.array([sum(pairs[s].values())/2 for s in sorted(pairs)])

def competitive(c,rows):
    e=c['evaluation'];out={}
    common={o:list(range(lo,hi+1)) for o,(lo,hi) in e['common_seed_by_opponent'].items()}
    direct=list(range(e['direct_seed_start'],e['direct_seed_end']+1))
    for a in ARMS:
        deltas=[];coverage={}
        for o,seeds in common.items():
            base=blocks(rows,'base',o,seeds);new=blocks(rows,a,o,seeds)
            if base is None or new is None:deltas=None;break
            deltas.append(new-base)
        common_m=measure(np.mean(deltas,axis=0),e['bootstrap_seed'],e['bootstrap_samples'],e['lower_quantile']) if deltas is not None else None
        d=blocks(rows,a,'parent',direct);direct_m=measure(d,e['bootstrap_seed'],e['bootstrap_samples'],e['lower_quantile']) if d is not None else None
        for o,(lo,hi) in e['coverage_seed_by_opponent'].items():
            base=blocks(rows,'base',o,range(lo,hi+1));new=blocks(rows,a,o,range(lo,hi+1))
            coverage[o]=measure(new-base,e['bootstrap_seed'],e['bootstrap_samples'],e['lower_quantile']) if base is not None and new is not None else None
        out[a]=dict(common_delta=common_m,direct_parent=direct_m,coverage_delta=coverage,
            retention_common=common_m['simultaneous_one_sided_lower']>=-.05 if common_m else 'INCOMPLETE',
            retention_direct=direct_m['simultaneous_one_sided_lower']>=.45 if direct_m else 'INCOMPLETE',
            enhancement_common=(common_m['mean']>=.02 and common_m['simultaneous_one_sided_lower']>0) if common_m else 'INCOMPLETE',
            enhancement_direct=(direct_m['mean']>=.52 and direct_m['simultaneous_one_sided_lower']>.5) if direct_m else 'INCOMPLETE',
            coverage_retention={o:(v['simultaneous_one_sided_lower']>=-.03 if v else 'INCOMPLETE') for o,v in coverage.items()})
    return out

def build():
    c=read(ROOT/CONFIG);reg=read(ROOT/'candidate-registry.json');plan=read(ROOT/'evaluation-plan.json');done=read(ROOT/'evaluation-completion.json')
    if done['plan_sha256']!=digest(ROOT/'evaluation-plan.json') or plan['candidate_registry_sha256']!=digest(ROOT/'candidate-registry.json'):raise ValueError('evaluation plan/identity drift')
    rows=[];groups=defaultdict(list);sources=[];missing=[];progress=[]
    for shard in plan['shards']:
        dest=Path(shard['output']);grid=bounded.inspect(dest)
        if digest(dest/'manifest.json')!=shard['manifest_sha256']:raise ValueError('shard drift')
        ledger=read(dest/'ledger.json')
        for key,entry in ledger['entries'].items():
            progress.append(entry.get('metrics',{}))
            if entry['state']!='COMPLETED':missing.append(dict(shard=shard['label'],key=key,kind=entry.get('kind','UNKNOWN')));continue
            row=dict(entry['row']);path=dest/'games'/row['candidate']/row['opponent']/f"seed-{row['seed']}-seat-{row['candidate_seat']}"
            replay=read(path/'replay.json');row['_candidate_actions']=Counter();row['_opponent_actions']=Counter()
            for step in replay['steps']:row['_candidate_actions' if step['actor']==row['candidate_seat'] else '_opponent_actions'][step['action']['type']]+=1
            row['_replay_path']=str(path/'replay.json');row['_wall_seconds']=read(path/'process-result.json')['wall_seconds']
            rows.append(row);groups[row['candidate'],row['opponent'],row['candidate_seat']].append(row)
            sources.append(dict(key=key,shard=shard['label'],hashes=entry['evidence_sha256']))
    if len(rows)+len(missing)!=19456 or len(rows)!=done['completed_games']:raise ValueError('physical ledger mismatch')
    out=ROOT/'analysis';out.mkdir(exist_ok=False);write(out/'rows.json',rows);write(out/'source-ledger.json',sources)
    metrics={};clocks=[]
    for i,(key,rs) in enumerate(sorted(groups.items())):
        manifest=out/f'metrics-{i}.manifest.json';target=out/f'metrics-{i}.json';write(manifest,dict(rows=[dict(replay_path=r['_replay_path']) for r in rs]));start=time.time()
        cmd=[str(ROOT/'bin/s4_batch_metrics'),str(manifest),str(target)];r=subprocess.run(cmd,capture_output=True,text=True,timeout=300)
        write(out/f'metrics-{i}.receipt.json',dict(argv=cmd,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr,wall_seconds=time.time()-start))
        if r.returncode:raise ValueError('saved Rust replay audit failed: '+str(key))
        metrics[key]=read(target);clocks.append(time.time()-start)
    pairs=[]
    for model,opp in sorted({(m,o) for m,o,_ in groups}):
        rs=groups.get((model,opp,0),[])+groups.get((model,opp,1),[]);cb=[];ob=[];seats=[]
        for seat in (0,1):
            sub=groups.get((model,opp,seat),[])
            if not sub:continue
            raw=metrics[model,opp,seat];a=raw['seat_p0_first' if seat==0 else 'seat_p1_second'];b=raw['seat_p1_second' if seat==0 else 'seat_p0_first']
            cb.append((a,len(sub)));ob.append((b,len(sub)));seats.append(dict(candidate_seat=seat,candidate=details.merge_player([(a,len(sub))],sub,True),opponent=details.merge_player([(b,len(sub))],sub,False)))
        complete=all(sum(r['seed']==s for r in rs)==2 for s in {r['seed'] for r in rs})
        interval=notebook.interval(rs)['ci95'] if complete else [None,None]
        win=notebook.interval(rs,True)['ci95'] if complete else [None,None]
        pairs.append(dict(candidate=model,opponent=opp,candidate_metrics=details.merge_player(cb,rs,True),opponent_metrics=details.merge_player(ob,rs,False),macro=details.macro(rs),seats=seats,
            score_uncertainty=dict(ordinary_95_ci=interval,seed_blocks=len(rs)//2 if complete else None,status='DESCRIPTIVE' if complete else 'NOT_MEASURED_UNPAIRED'),win_uncertainty=dict(ordinary_95_ci=win,status='DESCRIPTIVE' if complete else 'NOT_MEASURED_UNPAIRED'),candidate_mode='greedy',opponent_mode='greedy'))
    science=competitive(c,rows);length=np.array([r['plies'] for r in rows]);deltas=[v['common_delta']['mean'] for v in science.values() if v['common_delta']]
    result=dict(format='m73-bounded-repeat-result-v1',games=len(rows),planned_games=19456,action_mode='both-greedy',grid_status='COMPLETE' if not missing else 'INCOMPLETE',missing=missing,
        candidate_sha256=dict(base=c['base_model']['sha256'],**{a:v['sha256'] for a,v in reg['models'].items()}),source_config_sha256=digest(ROOT/CONFIG),candidate_registry_sha256=digest(ROOT/'candidate-registry.json'),acceptance_policy=c['evaluation'],per_training_seed=science,
        training_seed_summary=dict(count=len(deltas),common_delta_mean=float(np.mean(deltas)) if deltas else None,common_delta_range=[min(deltas),max(deltas)] if deltas else None,limitation='only three training units; no universal robustness or equivalence claim'),
        pairs=pairs,progression=dict(ply_quantiles=np.quantile(length,[0,.5,.9,.95,.99,1]).tolist(),truncated_games=len(missing),longest_no_purchase=max((p.get('longest_main_without_purchase',0) for p in progress),default=0),legal_purchase_opportunities='NOT_MEASURED',early_investment_redemption='NOT_MEASURED_DEFERRED',first_large_card_and_fixed_main='NOT_MEASURED_DEFERRED'),
        rule_replay_audit='PASS_ALL_COMPLETED_SAVED_REPLAYS',style='DESCRIPTIVE; timing/redemption incomplete, route undetermined',published=False,default_replaced=False,automatic_retries=0)
    dest=ROOT/'benchmarks/m73-prism-repeat.result.json'
    if dest.exists():raise ValueError('result already published; no overwrite')
    write(dest,result)
    from scripts.prism_human_report import write_markdown
    names=dict(c['names'],base=c['names']['parent'],**{a:c['names']['candidate-'+a] for a in ARMS})
    story=dict(title='M73 固定B的三次短程PPO重复',headline='三个最终c4全部报告；模型资格与继续研究的判断分开。',identity='同一个Balance v0.2.0父代，三个fresh AdamW/RNG，M70配方不变。',conclusions=[dict(label='产物',value='三个最终c4审计通过，未发布',explanation='独立训练重复全部保留。'),dict(label='竞技',value='逐seed估计与区间见下表',explanation='有限精度；不以六端点全部显著作为唯一研究继续条件。'),dict(label='风格',value='描述画像，路线未确认',explanation='重要时点与兑现尚未测量，不能强贴标签。')],interpretation='完整终局、截断及错误分开。普通区间仅描述；模型增强按六项单侧校正判定。三训练seed不能证明普适稳定；最新对手代价单列。',next='先评审重复与最新覆盖，再决定独立的旧池/新池对照；不自动追加预算或发布。')
    payload=dict(story=story,view='greedy',focus='a',baseline='base',comparison_baseline='base',names=names,result={'all':dict(label='本轮独立双方greedy；截断不计胜负',pairs=pairs,games=len(rows))})
    md=ROOT/'docs/prism/m73-prism-repeat-evidence.md';md.parent.mkdir(parents=True,exist_ok=True);write_markdown(md,payload)
    with md.open('a',encoding='utf-8') as f:f.write('\n\n## 冻结统计与逐seed判定\n\n```json\n'+json.dumps(science,ensure_ascii=False,indent=2)+'\n```\n\n完整性：'+result['grid_status']+'；缺项不填平局。\n')
    spec=dict(format='prism-m73-bounded-reading-v1',result=dest.relative_to(ROOT).as_posix(),result_sha256=digest(dest),markdown=md.relative_to(ROOT).as_posix(),markdown_sha256=digest(md),contract=CONFIG,contract_sha256=digest(ROOT/CONFIG),output='docs/prism/m73-prism-repeat-comparison.html',payload=payload)
    path=ROOT/'benchmarks/reports/m73-reading.json';write(path,spec)
    from scripts.prism_round_report import build as render
    receipt=render(path);write(out/'report-verification.json',dict(status='PASS_SOURCE_COUNTS_STATS_REPLAY_AND_RENDER_BINDINGS',reading=receipt,pixel_visual='NOT_VERIFIED',new_games=0))
    return dict(status='RESULTS_AND_REPORTS_READY',completed_games=len(rows),missing=len(missing),result_sha256=digest(dest))

if __name__=='__main__':print(json.dumps(build()))
