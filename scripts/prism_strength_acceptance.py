"""Run finite immutable match shards and judge a preregistered Prism holdout.
The existing fixed evaluator owns matches; its development verdict is left intact.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import prism_ppo_fixed_eval as fixed


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return fixed.read_json(path)


def fingerprint(path):
    return {'path':str(Path(path)), 'sha256':fixed.sha256_file(path)}


def run_plan(plan_path, receipt_path):
    plan_path=Path(plan_path).resolve()
    plan=read(plan_path)
    require(plan['format']=='prism-strength-shard-plan-v1','plan format')
    require(1<=plan['workers']<=4,'bounded workers')
    require(len({s['label'] for s in plan['shards']})==len(plan['shards']),'duplicate shard labels')
    started=time.time()
    deadline=plan['deadline_unix']
    require(deadline>started,'campaign deadline expired')
    results=[]
    stopped=threading.Event()
    def execute(shard):
        require(not stopped.is_set(),"campaign stopped after another shard failure")
        config=Path(shard['config']);output=Path(shard['output'])
        require(fixed.sha256_file(config)==shard['config_sha256'],'shard config drift')
        argv=[sys.executable,'-B','-u',str(ROOT/'scripts/prism_ppo_fixed_eval.py'),'--config',str(config),'--output',str(output)]
        log=output.parent/(output.name+'.stdout.log');err=output.parent/(output.name+'.stderr.log')
        begun=time.time()
        remaining=deadline-begun
        require(remaining>0,'campaign deadline expired')
        # Native Windows child priority is inherited by engine/agent processes.
        kwargs={'creationflags':subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name=='nt' else {}
        with log.open('w',encoding='utf-8') as stdout,err.open('w',encoding='utf-8') as stderr:
            try:
                proc=subprocess.run(argv,stdout=stdout,stderr=stderr,timeout=remaining,**kwargs)
                code=proc.returncode
            except subprocess.TimeoutExpired:
                code=124
        row={'label':shard['label'],'argv':argv,'returncode':code,'started_unix':begun,'elapsed_seconds':time.time()-begun,'stdout':str(log),'stderr':str(err)}
        if code!=0:
            stopped.set()
        if code==0:
            row['result']=fingerprint(output/'result.json')
            row['completion']=fingerprint(output/'completion.json')
        fixed.atomic_json(output.parent/(output.name+'.exit.json'),row)
        return row
    with ThreadPoolExecutor(max_workers=plan['workers']) as pool:
        jobs=[pool.submit(execute,s) for s in plan['shards']]
        for job in as_completed(jobs):
            row=job.result();results.append(row)
            print(json.dumps({'finished_shard':row['label'],'returncode':row['returncode'],'elapsed_seconds':row['elapsed_seconds']}),flush=True)
            require(row['returncode']==0,'match shard failed; no retries: '+row['label'])
    record={'format':'prism-strength-shard-run-v1','plan':fingerprint(plan_path),'started_unix':started,'elapsed_seconds':time.time()-started,'returncode':0,'workers':plan['workers'],'results':results,'no_training_updates':True}
    fixed.atomic_json(receipt_path,record)
    return record


def interval(values, samples, seed, lower_q):
    """Resample complete dual-seat environment blocks, with fixed Random seed."""
    rng=random.Random(seed)
    n=len(values)
    draws=sorted(sum(values[rng.randrange(n)] for _ in range(n))/n for _ in range(samples))
    return {'mean':sum(values)/n,'ci95':[fixed._percentile(draws,0.025),fixed._percentile(draws,0.975)],'simultaneous_one_sided_lower':fixed._percentile(draws,lower_q)}


def strength_gates(measures, config):
    gates={'pooled_anchors_superiority':measures['pooled_delta']['simultaneous_one_sided_lower']>config['pooled_anchor_delta_lower_gt'],
           'direct_parent_superiority':measures['direct_duel']['simultaneous_one_sided_lower']>config['direct_duel_candidate_score_lower_gt']}
    for name,value in measures['anchor_deltas'].items():
        gates['anchor_noninferiority/'+name]=value['simultaneous_one_sided_lower']>=config['per_anchor_delta_lower_gte']
    require(len(gates)==4,'expected exactly four strength gates')
    return gates


def analyze(contract_path, plan_path, output):
    contract=read(contract_path);plan=read(plan_path)
    require(plan['contract_sha256']==fixed.sha256_file(contract_path),'frozen contract drift')
    seeds=list(range(contract['holdout']['seed_start'],contract['holdout']['seed_end']+1))
    require(len(seeds)==256,'frozen block count')
    rows=[];artifacts=[]
    for shard in plan['shards']:
        cfg=Path(shard['config']);directory=Path(shard['output'])
        require(fixed.sha256_file(cfg)==shard['config_sha256'],'analyze config drift')
        validated=fixed.validate_config(read(cfg),cfg)
        validated['saved_config']=read(cfg)
        validated['config_sha256']=fixed.canonical_hash(validated['saved_config'])
        fixed.check_assets(validated)
        progress=read(directory/'progress.json');completion=read(directory/'completion.json');result=read(directory/'result.json')
        require(progress['config_sha256']==validated['config_sha256'],'progress binding')
        require(completion['result_sha256']==fixed.sha256_file(directory/'result.json'),'result hash')
        shard_rows=fixed._rows_from_progress(progress,validated)
        for row in shard_rows:
            game_dir=directory/'games'/row['candidate']/row['opponent']/f"seed-{row['seed']}-seat-{row['candidate_seat']}"
            key=fixed._game_key(row['candidate'],row['opponent'],row['seed'],row['candidate_seat'])
            rec=progress['games'][key]
            require(rec['report_sha256']==fixed.sha256_file(game_dir/'report.json') and rec['replay_sha256']==fixed.sha256_file(game_dir/'replay.json'),'raw game hash drift')
            report=read(game_dir/'report.json');replay=read(game_dir/'replay.json')
            actual=fixed._report_result(report,replay,game_id=row['game_id'],seed=row['seed'],seat=row['candidate_seat'],catalog=validated['config']['catalog_fingerprint'])
            require(all(row[k]==v for k,v in actual.items()),'saved aggregate row drift')
            require(report['agents'][row['candidate_seat']]['agent_name']=='prism-sample','candidate runtime handshake')
            desc=validated['candidates'][row['candidate']]
            expected=contract['parent']['sha256'] if row['candidate']=='parent' else contract['candidate']['sha256']
            require(any(x['sha256']==expected for x in desc['files']),'candidate/parent weight contract binding')
        require(result==fixed.aggregate(validated,shard_rows),'full shard aggregate recomputation')
        require(completion['completed_games']==len(shard_rows) and completion['game_keys']==sorted(progress['games']),'shard completion grid')
        rows.extend(shard_rows)
        artifacts.extend([fingerprint(directory/'result.json'),fingerprint(directory/'progress.json'),fingerprint(directory/'completion.json')])
    keyed={(r['candidate'],r['opponent'],r['seed'],r['candidate_seat']):r for r in rows}
    expected_keys={(candidate,opponent,seed,seat) for candidate in ('parent','c8') for opponent in ('heuristic-v031','prism-v01') for seed in seeds for seat in (0,1)}
    expected_keys|={('c8','parent-t1',seed,seat) for seed in seeds for seat in (0,1)}
    require(len(rows)==2560 and len(keyed)==2560 and set(keyed)==expected_keys,'exact 2560-game acceptance grid')
    candidates={};deltas={}
    for candidate in ('parent','c8'):
        candidates[candidate]={}
        for opponent in ('heuristic-v031','prism-v01'):
            candidates[candidate][opponent]=fixed._summarize_rows([keyed[candidate,opponent,seed,seat] for seed in seeds for seat in (0,1)])
    for opponent in ('heuristic-v031','prism-v01'):
        deltas[opponent]=[sum(keyed['c8',opponent,seed,seat]['candidate_score']-keyed['parent',opponent,seed,seat]['candidate_score'] for seat in (0,1))/2 for seed in seeds]
    pooled=[(deltas['heuristic-v031'][i]+deltas['prism-v01'][i])/2 for i in range(len(seeds))]
    duel=[sum(keyed['c8','parent-t1',seed,seat]['candidate_score'] for seat in (0,1))/2 for seed in seeds]
    stats=contract['statistics'];measure=lambda xs:interval(xs,stats['samples'],stats['seed'],stats['bonferroni_lower_quantile'])
    measures={'pooled_delta':measure(pooled),'direct_duel':measure(duel),'anchor_deltas':{k:measure(v) for k,v in deltas.items()}}
    gates=strength_gates(measures,contract['gates'])
    passed=all(gates.values())
    record={'format':'m54-prism-strength-acceptance-result-v1','status':'ACCEPTED_MODEL_ITERATION' if passed else 'NOT_ACCEPTED','model_version':contract['candidate']['prospective_model_version'] if passed else None,'observed_utc':datetime.now(timezone.utc).isoformat(),'contract':fingerprint(contract_path),'plan':fingerprint(plan_path),'analyzer':fingerprint(__file__),'candidate':contract['candidate'],'parent':contract['parent'],'complete_grid_terminal_no_failures':True,'games':len(rows),'seed_blocks':len(seeds),'anchor_results':candidates,'direct_duel_wdl':fixed._summarize_rows([r for r in rows if r['opponent']=='parent-t1']),'statistics':stats,'measurements':measures,'gates':gates,'all_strength_gates_passed':passed,'evidence':artifacts,'no_training_updates':True,'production_default_changed':False,'shared_pool_changed':False,'independent_holdout':True,'independent_review_performed':False,'not_style_cohort_acceptance':True}
    fixed.atomic_json(output,record)
    print(json.dumps({k:record[k] for k in ('status','model_version','games','gates','measurements')}))
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    p=subs.add_parser('run');p.add_argument('--plan',required=True);p.add_argument('--receipt',required=True)
    p=subs.add_parser('analyze');p.add_argument('--contract',required=True);p.add_argument('--plan',required=True);p.add_argument('--output',required=True)
    args=parser.parse_args()
    if args.command=='run':run_plan(args.plan,args.receipt)
    else:analyze(args.contract,args.plan,args.output)


if __name__=='__main__':
    main()
