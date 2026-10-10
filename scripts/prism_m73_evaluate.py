"""M73 bounded evaluation shards and once-only engineering acceptance."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,identity
from scripts.prism_m73_prepare import CONFIG,ARMS
from scripts import prism_notebook_arena as arena,prism_bounded_eval as bounded

def config(models,opponents,seeds):
    c=read(ROOT/CONFIG);e=c['evaluation'];engine=ROOT/'bin/splendor'
    def model(key):
        path=ROOT/'inputs/parent.json' if key=='base' else ROOT/'campaigns'/key/'cycle-4-export/weights.json'
        return arena.model(path,c['names']['parent' if key=='base' else 'candidate-'+key],engine,mode='greedy',action_seed=e['action_seed'])['descriptor']
    opp={o:arena.heuristic(engine,c['names'][o],e['action_seed'])['descriptor'] if o=='heuristic' else arena.model(ROOT/f'inputs/{o}.json',c['names'][o],engine,mode='greedy',action_seed=e['action_seed'])['descriptor'] for o in opponents}
    return dict(format='prism-ppo-fixed-eval-v1',engine=dict(program=str(engine),sha256=digest(engine)),catalog_fingerprint=read(ROOT/'inputs/parent.json')['catalog_fingerprint'],action_seed=e['action_seed'],seeds=seeds,candidates={k:model(k) for k in models},opponents=opp,
        timeouts=dict(game_wall_seconds=90,handshake_timeout_ms=10000,move_timeout_ms=10000,shutdown_grace_ms=1000))

def freeze_shard(label,cfg,cap=512):
    p=ROOT/'evaluation-configs'/label;write(p.with_suffix('.json'),cfg)
    jobs=len(cfg['candidates'])*len(cfg['opponents'])*len(cfg['seeds'])*2
    policy=dict(format=bounded.FORMAT,max_games=jobs,max_truncated_games=jobs,ply_cap=cap,deadline_unix=read(ROOT/'round-budget.json')['deadline'],cpu_seconds=4000,memory_bytes=2*1024**3,storage_bytes=128*1024**2,max_processes=12,automatic_game_retries=0)
    write(p.with_suffix('.policy.json'),policy);dest=ROOT/'evaluation'/label
    bounded.prepare(p.with_suffix('.json'),p.with_suffix('.policy.json'),dest)
    return dict(label=label,output=str(dest),planned_games=jobs,manifest_sha256=digest(dest/'manifest.json'))

def dispatch(shards,limit=4,truncation_limit=16):
    pending=list(shards);active={};completed=[];truncated=0
    start=time.time();status=ROOT/'evaluation-progress.json'
    try:
        while pending or active:
            deadline=read(ROOT/'round-budget.json')['deadline']
            if time.time()>=deadline:raise ValueError('original round deadline exhausted')
            while pending and len(active)<limit:
                shard=pending.pop(0);dest=Path(shard['output'])
                log=(dest/'worker.log').open('wb')
                env=dict(os.environ,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
                proc=subprocess.Popen([sys.executable,'-B',str(ROOT/'scripts/prism_bounded_eval.py'),'run','--output',str(dest)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=env)
                active[proc.pid]=(proc,log,shard)
            for pid,(proc,log,shard) in list(active.items()):
                if proc.poll() is None:continue
                log.close();del active[pid]
                if proc.returncode:raise ValueError('bounded shard failed; no retry: '+shard['label'])
                grid=bounded.inspect(Path(shard['output']))
                completed.append(dict(shard,grid=grid));truncated+=grid['truncated_games']
                if truncated>truncation_limit:raise ValueError('whole-grid truncation budget exhausted')
            write(status,dict(observed_at=time.time(),state='RUNNING',completed_shards=len(completed),total_shards=len(shards),completed_games=sum(x['grid']['completed_games'] for x in completed),truncated_games=truncated,active_pids=list(active),elapsed_seconds=time.time()-start))
            time.sleep(.25)
    finally:
        # Kill only this dispatcher's own child groups through normal process exit;
        # bounded children detect loss of their parent. No existing run is adopted.
        for proc,log,shard in active.values():
            proc.terminate()
        for proc,log,shard in active.values():
            try:proc.wait(timeout=15)
            finally:log.close()
    return completed

def candidates():
    models={}
    rng=[]
    for a in ARMS:
        audit=read(ROOT/'audits'/a/'audit.json');path=ROOT/'campaigns'/a/'cycle-4-export/weights.json'
        if audit['status']!='PASS_TRAINING_ARTIFACT_AUDIT' or digest(path)!=audit['weights_sha256']:raise ValueError('final c4 audit mismatch')
        init=audit['checkpoint']['initialization'];rng.append(init['torch_rng_sha256'])
        models[a]=dict(path=str(path),sha256=digest(path),audit_sha256=digest(ROOT/'audits'/a/'audit.json'))
    if len(set(rng))!=3:raise ValueError('training RNGs not independent')
    dest=ROOT/'candidate-registry.json'
    if dest.exists():raise ValueError('candidates already frozen')
    write(dest,dict(status='FROZEN_FINAL_C4_BEFORE_EVALUATION',parent_sha256=read(ROOT/CONFIG)['base_model']['sha256'],models=models,training_rngs=rng,selection='all final c4; no best seed'))
    return dict(status='FROZEN_FINAL_C4_BEFORE_EVALUATION',sha256=digest(dest))

def bounded_engineering():
    if (ROOT/'bounded-linux-acceptance.json').exists():raise ValueError('engineering already attempted')
    start=time.time()
    c=read(ROOT/CONFIG)
    retained=None
    if c.get('execution_predecessor'):
        from scripts.prism_m73_cpu_readback import inspect_retained
        retained=inspect_retained(Path(c['execution_predecessor']['root']))
        write(ROOT/'retained-engineering-readback.json',retained)
        shards=[freeze_shard('engineering-truncated',config(['base'],['general'],[11000012,11000013]),1)]
    else:
        shards=[freeze_shard('engineering-terminal',config(['base'],['general'],[11000010,11000011]),512),freeze_shard('engineering-truncated',config(['base'],['general'],[11000012,11000013]),1)]
    done=dispatch(shards,limit=1,truncation_limit=4)
    if [(x['grid']['completed_games'],x['grid']['truncated_games']) for x in done] != ([(0,4)] if retained else [(4,0),(0,4)]):raise ValueError('Linux terminal/truncation acceptance failed')
    mean=(time.time()-start)/8
    # Pessimistic engineering extrapolation, not a precise ETA.
    if mean*19456/4>read(ROOT/'round-budget.json')['deadline']-time.time()-3*3600:raise ValueError('bounded evaluator throughput insufficient for frozen deadline')
    write(ROOT/'bounded-linux-acceptance.json',dict(status='PASS_TARGET_LINUX_NORMAL_AND_TRUNCATION',new_engineering_games=4 if retained else 8,total_engineering_evaluation_games=8,retained_readback=retained,shards=done,wall_seconds=time.time()-start,extrapolation='eight engineering games include forced truncation; uncertain, not inference throughput',planned_evaluation_games=19456))
    return dict(status='PASS_TARGET_LINUX_NORMAL_AND_TRUNCATION')

def evaluate():
    reg=read(ROOT/'candidate-registry.json');c=read(ROOT/CONFIG);e=c['evaluation']
    for v in reg['models'].values():
        if digest(v['path'])!=v['sha256']:raise ValueError('candidate weight drift')
    shards=[]
    cohorts={**e['common_seed_by_opponent'],**e['coverage_seed_by_opponent'],'parent':[e['direct_seed_start'],e['direct_seed_end']]}
    for model in ['base',*ARMS]:
        for opp,(lo,hi) in cohorts.items():
            if model=='base' and opp=='parent':continue
            for start in range(lo,hi+1,32):
                shards.append(freeze_shard(f'{model}-{opp}-{start}',config([model],[opp],list(range(start,min(start+32,hi+1)))),e['ply_cap']))
    if sum(s['planned_games'] for s in shards)!=19456:raise ValueError('physical evaluation grid drift')
    write(ROOT/'evaluation-plan.json',dict(format='m73-bounded-shards-v1',config_sha256=digest(ROOT/CONFIG),candidate_registry_sha256=digest(ROOT/'candidate-registry.json'),shards=shards,total_games=19456,workers=4))
    done=dispatch(shards,truncation_limit=e['max_truncated_games_total'])
    write(ROOT/'evaluation-completion.json',dict(status='FINISHED_WITH_EXPLICIT_MISSINGNESS',shards=done,completed_games=sum(x['grid']['completed_games'] for x in done),truncated_games=sum(x['grid']['truncated_games'] for x in done),automatic_retries=0,finished_at=time.time(),plan_sha256=digest(ROOT/'evaluation-plan.json')))
    return dict(completed_games=sum(x['grid']['completed_games'] for x in done))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['bounded-engineering','candidates','evaluate']);args=p.parse_args()
    print(json.dumps(globals()[args.mode.replace('-','_')]()))
