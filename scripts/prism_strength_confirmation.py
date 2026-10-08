"""Run the single bounded M54 second-look confirmation, preserving the v1 analyzer.
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



def confirmation_seeds(contract):
    """Fail closed on an extra look, enlarged budget or weakened confidence gate."""
    require(contract['format']=='m54-prism-strength-confirmation-v2','confirmation format')
    holdout=contract['holdout'];stats=contract['statistics'];budget=contract['budget']
    require(holdout['seed_start']==9470000 and holdout['seed_end']==9470511 and holdout['seeds']==512,'frozen confirmation seeds')
    require(holdout['total_formal_games']==5120 and holdout['direct_duel_games']==1024 and holdout['anchor_total_games']==4096,'frozen confirmation grid size')
    require(stats['family_alpha']==0.05 and stats['evaluation_look']==2 and stats['maximum_evaluation_looks']==2 and stats['one_sided_gate_count']==4,'two-look confidence family')
    require(stats['bonferroni_lower_quantile']==0.00625,'four gates times two looks: alpha/8')
    require(stats['samples']==20000 and stats['seed']==54049999 and stats['single_final_analysis_no_optional_stopping'] is True,'frozen bootstrap')
    require(budget['max_formal_games']==5120 and budget['max_physical_attempts']==5120 and budget['infra_retries']==0 and budget['local_match_workers']==4 and budget['campaign_wall_hours']==6,'frozen finite budget')
    require(contract['gates']['pooled_anchor_delta_lower_gt']==0 and contract['gates']['direct_duel_candidate_score_lower_gt']==0.5 and contract['gates']['per_anchor_delta_lower_gte']==-0.05 and contract['gates']['all_four_strength_gates_required'] is True,'unchanged strength thresholds')
    require(contract['sampling']['action_seed']==54030001 and contract['sampling']['no_inference_overlay'] is True,'same learned sampling')
    return list(range(holdout['seed_start'],holdout['seed_end']+1))


def expected_grid(seeds):
    keys={(candidate,opponent,seed,seat) for candidate in ('parent','c8') for opponent in ('heuristic-v031','prism-v01') for seed in seeds for seat in (0,1)}
    keys|={('c8','parent-t1',seed,seat) for seed in seeds for seat in (0,1)}
    return keys


def validate_confirmation_plan(contract_path,plan_path):
    contract=read(contract_path);plan=read(plan_path);seeds=confirmation_seeds(contract)
    require(plan['contract_sha256']==fixed.sha256_file(contract_path),'frozen contract drift')
    require(plan['workers']==4 and len(plan['shards'])==20,'frozen four-worker twenty-shard plan')
    require(plan['deadline_unix']==Path(contract_path).stat().st_mtime+21600,'deadline cannot be extended')
    for pin in contract['source_pins']:
        require(fixed.sha256_file(ROOT/pin['path'])==pin['sha256'],'source drift: '+pin['path'])
    require(fixed.sha256_file(__file__)==plan['runner_sha256'],'confirmation analyzer drift')
    prior=contract['previous_acceptance'];previous_path=ROOT/prior['path']
    require(fixed.sha256_file(previous_path)==prior['sha256'],'original v1 result drift')
    previous=read(previous_path)
    require(previous['status']=='NOT_ACCEPTED' and previous['model_version'] is None and not previous['all_strength_gates_passed'],'previous look must remain unaccepted')
    require(previous['statistics']['bonferroni_lower_quantile']==0.0125 and previous['measurements']['direct_duel']['simultaneous_one_sided_lower']==0.5,'v1 strict direct gate must remain inconclusive')
    require(not previous['gates']['direct_parent_superiority'],'v1 gate history')
    for who in ('candidate','parent'):
        require(contract[who]==previous[who],'same single frozen candidate and parent')
        require(fixed.sha256_file(ROOT/contract[who]['weights_path'])==contract[who]['sha256'],'model weight drift')
    templates={}
    for kind,pin in contract['execution_templates'].items():
        require(fixed.sha256_file(ROOT/pin['path'])==pin['sha256'],'original execution template drift')
        templates[kind]=read(ROOT/pin['path'])
    keys=set();labels=set();outputs=set();slots=0
    for shard in plan['shards']:
        require(shard['label'] not in labels and shard['output'] not in outputs,'duplicate shard/output');labels.add(shard['label']);outputs.add(shard['output'])
        require(fixed.sha256_file(shard['config'])==shard['config_sha256'],'shard config drift')
        cfg=read(shard['config']);kind='anchors' if set(cfg['opponents'])=={'heuristic-v031','prism-v01'} else 'duel'
        template=templates[kind]
        require({k:v for k,v in cfg.items() if k!='seeds'}=={k:v for k,v in template.items() if k!='seeds'},'execution descriptors changed')
        validated=fixed.validate_config(cfg,shard['config']);fixed.check_assets(validated)
        shard_keys={(c,o,s,seat) for c in cfg['candidates'] for o in cfg['opponents'] for s in cfg['seeds'] for seat in (0,1)}
        require(len(shard_keys)==256 and not keys.intersection(shard_keys),'duplicate or oversized shard')
        keys.update(shard_keys);slots+=len(shard_keys)
    require(slots==5120 and keys==expected_grid(seeds),'exact confirmation grid; no prior seed reuse')
    return {'games':slots,'seed_blocks':len(seeds),'shards':len(labels),'contract':fingerprint(contract_path),'plan':fingerprint(plan_path),'previous_acceptance':fingerprint(previous_path),'original_v1_decision_preserved':True,'prior_look_cannot_pass_stricter_direct_gate':True}

def run_plan(plan_path, receipt_path):
    plan_path=Path(plan_path).resolve()
    plan=read(plan_path)
    validate_confirmation_plan(plan['contract_path'],plan_path)
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
    sequence=validate_confirmation_plan(contract_path,plan_path)
    require(plan['contract_sha256']==fixed.sha256_file(contract_path),'frozen contract drift')
    seeds=list(range(contract['holdout']['seed_start'],contract['holdout']['seed_end']+1))
    require(seeds==confirmation_seeds(contract),'frozen block count')
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
    require(len(rows)==5120 and len(keyed)==5120 and set(keyed)==expected_grid(seeds),'exact 5120-game confirmation grid')
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
    record={'format':'m54-prism-strength-confirmation-result-v2','status':'ACCEPTED_MODEL_ITERATION' if passed else 'NOT_ACCEPTED','model_version':contract['candidate']['prospective_model_version'] if passed else None,'observed_utc':datetime.now(timezone.utc).isoformat(),'contract':fingerprint(contract_path),'plan':fingerprint(plan_path),'analyzer':fingerprint(__file__),'candidate':contract['candidate'],'parent':contract['parent'],'complete_grid_terminal_no_failures':True,'games':len(rows),'seed_blocks':len(seeds),'anchor_results':candidates,'direct_duel_wdl':fixed._summarize_rows([r for r in rows if r['opponent']=='parent-t1']),'statistics':stats,'measurements':measures,'gates':gates,'all_strength_gates_passed':passed,'evidence':artifacts,'no_training_updates':True,'production_default_changed':False,'shared_pool_changed':False,'independent_holdout':True,'independent_review_performed':False,'not_style_cohort_acceptance':True}
    record['second_look_policy']=sequence
    record['prior_games_pooled_into_current_measurements']=False
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
