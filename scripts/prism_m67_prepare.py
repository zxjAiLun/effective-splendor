"""Freeze M67's enlarged two-seed experiment; no launches and no overwrites."""
import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write, digest, identity, numerical_identity, package_identity
from scripts.prism_m66_prepare import PARENT_SHA, ORDER, NAMES
CONFIG = 'benchmarks/m67-prism-alpha-repeat.config.json'
REMOTE = '/mnt/workspace/splendor-m67-alpha-repeat'
ARMS = {'a': {'games':5120, 'cycles':20, 'run_seed':67010001, 'seed_start':9801000,
              'blueprint':'benchmarks/m67-prism-alpha-repeat-a.train.json'},
        'b': {'games':5120, 'cycles':20, 'run_seed':67010002, 'seed_start':9811000,
              'blueprint':'benchmarks/m67-prism-alpha-repeat-b.train.json'}}
RANGES = [(9800000,9800003,'m67-engineering-not-research'),
          (9801000,9803559,'m67-training-a'),(9811000,9813559,'m67-training-b'),
          (9830000,9832499,'m67-common-independent'),(9840000,9844999,'m67-direct-independent')]

def blueprint(template, hashes, arm='a', engineering=False):
    bp=copy.deepcopy(template);a=ARMS[arm];t=bp['template'];r=t['run']
    bp.update(purpose='enlarged-two-seed-outcome-only-ppo',cancel_fixture=False,
              model_label='M67 engineering unpublished checkpoint' if engineering else f'M67 seed {arm} final c20 unpublished training checkpoint')
    bp['weight_hashes']={k:hashes[k] for k in ('parent','general','alpha','beta')}
    desc=t['opponents']['prism-general-v011'];t['opponents']={}
    for i,key in enumerate(('general','parent','alpha','beta')):
        row=copy.deepcopy(desc);row['args']=['agent-prism','--weights','@'+key,'--seed',str(67011000+i)]
        row['files']={'@'+key:'@'+key+'_sha256'};t['opponents'][key]=row
    r.update(run_id='m67-engineering' if engineering else 'm67-repeat-'+arm,
             seed=67000001 if engineering else a['run_seed'],format='prism-ppo-run-v2',cpu_threads=2)
    r.pop('style',None);r['ppo'].update(style_beta=0.,style_value_weight=0.)
    r['opponents']={k:'' for k in t['opponents']}
    count,cycles,blocks,start=(8,1,4,9800000) if engineering else (5120,20,128,a['seed_start'])
    r['budget'].update(max_cycles=cycles,max_jobs=count,max_attempts=count,max_decisions=count*256,
        max_job_decisions=256,max_optimizer_steps=10000,max_update_attempts=10000,
        max_run_seconds=1200 if engineering else 25200,max_storage_bytes=(4 if engineering else 16)*1024**3)
    t['limits'].update(memory_bytes=8*1024**3,campaign_cpu_seconds=2400 if engineering else 100000,
                       max_physical_decisions=count*256,max_infra_retries=0)
    order=('general','parent','alpha','beta') if engineering else ORDER
    t['cycles']=[[dict(job_id=f'm67-{r["run_id"]}-c{c+1}-b{b}-s{s}',actor=s,
        opponent_id=order[b%len(order)],environment_seed=start+c*blocks+b)
        for b in range(blocks) for s in (0,1)] for c in range(cycles)]
    return bp

def validate(c, blueprints):
    if c['format']!='m67-prism-alpha-repeat-v1' or c['base_model']['sha256']!=PARENT_SHA:
        raise ValueError('M67 contract/parent drift')
    if c['training']['arms']!={k:dict(v,blueprint_identity=identity(blueprints[k])) for k,v in ARMS.items()}:
        raise ValueError('M67 arms/blueprint drift')
    old=read(ROOT/'benchmarks/m66-prism-alpha-dsw.config.json')
    seeds=[]
    for key,bp in blueprints.items():
        t=bp['template'];r=t['run'];jobs=[j for cycle in t['cycles'] for j in cycle]
        if len(t['cycles'])!=20 or any(len(g)!=256 for g in t['cycles']) or len(jobs)!=5120 or r['ppo']!=old['training']['ppo']:
            raise ValueError('M67 cadence/PPO budget drift')
        if r['seed']!=ARMS[key]['run_seed'] or r['budget']['max_jobs']!=5120 or r['budget']['max_cycles']!=20:
            raise ValueError('M67 run budget drift')
        expected=range(ARMS[key]['seed_start'],ARMS[key]['seed_start']+2560)
        actual={j['environment_seed'] for j in jobs}
        if actual!=set(expected):raise ValueError('M67 training seed drift')
        seats={seed:{j['actor'] for j in jobs if j['environment_seed']==seed} for seed in actual}
        if any(s!={0,1} for s in seats.values()):raise ValueError('M67 paired training drift')
        if set(seeds)&actual:raise ValueError('M67 training arm overlap')
        seeds.extend(actual)
    e=c['evaluation']
    if (e['total_games'],e['common_games_per_model'],e['direct_games'],e['mode'],e['lower_quantile'])!=(110000,30000,10000,'both-greedy',.0125):
        raise ValueError('M67 evaluation scope drift')
    if e['gates']!={'candidate/strength_pool':-.05,'candidate/direct_parent':.45}:
        raise ValueError('M67 gate drift')
    if [list(r) for r in c['seed_reservations']]!=[list(r) for r in RANGES]:raise ValueError('M67 reservation drift')
    return c

def freeze():
    targets=[ROOT/CONFIG]+[ROOT/a['blueprint'] for a in ARMS.values()]
    if any(p.exists() for p in targets):raise ValueError('M67 already frozen; no overwrite')
    old=read(ROOT/'benchmarks/m66-prism-alpha-dsw.config.json');assets=old['assets']
    for asset in assets.values():
        if digest(ROOT/asset['local_path'])!=asset['sha256']:raise ValueError('fixed asset drift')
    from scripts.s0_seed_registry import REGISTRY
    prior=list(REGISTRY);sources={}
    for p in sorted((ROOT/'benchmarks').glob('m*.config.json')):
        value=read(p)
        if 'seed_reservations' in value:
            prior.extend(tuple(r) for r in value['seed_reservations']);sources[p.relative_to(ROOT).as_posix()]=digest(p)
    for lo,hi,label in RANGES:
        for a,b,name in prior:
            if max(lo,a)<=min(hi,b):raise ValueError(f'{label} overlaps {name}')
    bps={k:blueprint(read(ROOT/'benchmarks/m63-prism-control-building.train.json'),{k:v['sha256'] for k,v in assets.items()},k) for k in ARMS}
    c={'format':'m67-prism-alpha-repeat-v1','status':'FROZEN_BEFORE_FIRST_GAME','frozen_at':datetime.now(timezone.utc).isoformat(),
       'authorization':{'source':'human_owner','date':'2026-10-05','request':'增大训练量和评测量，5000/10000，允许耗时增加5倍10倍，做一次重复实验'},
       'base_model':old['base_model'],'assets':assets,'names':dict(NAMES,**{'candidate-a':'M67种子A最终c20未发布训练检查点','candidate-b':'M67种子B最终c20未发布训练检查点'}),
       'seed_reservations':RANGES,'seed_check':{'status':'PASS','prior_ranges':len(prior),'configs':sources,'registry_sha256':digest(ROOT/'scripts/s0_seed_registry.py')},
       'training':{'arms':{k:dict(a,blueprint_identity=identity(bps[k])) for k,a in ARMS.items()},'total_games':10240,'games_per_cycle':256,
         'ppo':old['training']['ppo'],'mix_per_arm':{'general':2560,'parent':1280,'alpha':640,'beta':640},
         'initialization':'exact Prism Alpha v0.1.5 weights; independent fresh AdamW/RNG per arm; not full-state resume',
         'selection':'final c20 only for each arm; no intermediate checkpoint evaluation or picking best arm',
         'wall_seconds':25200,'cpu_seconds':100000,'memory_bytes':8*1024**3,'storage_bytes':16*1024**3},
       'engineering':{'games':8,'run_seed':67000001,'wall_seconds':1200,'cpu_seconds':2400,'research_use':False},
       'evaluation':{'mode':'both-greedy','action_seed':67020001,'common_opponents':old['evaluation']['common_opponents'],
         'common_seed_start':9830000,'common_seed_end':9832499,'common_games_per_model':30000,
         'direct_seed_start':9840000,'direct_seed_end':9844999,'direct_games':10000,'total_games':110000,
         'workers':4,'wall_seconds_per_arena':18000,'cpu_seconds_per_arena':72000,'memory_bytes':8*1024**3,'storage_bytes_per_arena':8*1024**3,
         'gates':old['evaluation']['gates'],'enhancement_thresholds':old['evaluation']['enhancement_thresholds'],
         'bootstrap_samples':20000,'bootstrap_seed':67029999,'family_alpha':.05,'lower_quantile':.0125,
         'statistical_unit':'paired two-seat seed block; six equal-weight common opponents; four gates across two arms',
         'repeat_success':'both arms clear adjusted enhancement lower bounds for strength pool and direct parent',
         'style':'descriptive observed route; no style veto','selection':'no extension or arm/checkpoint selection'},
       'resources':{'round_wall_seconds':86400,'automatic_retries':0,'total_storage_bytes':60*1024**3,
         'available_cpu_affinity':[0,1,2,3],'rss_limit_scope':'sampled process-tree soft limit; no owned cgroup'},
       'runtime':{'remote_root':REMOTE,'numeric_source_identity':numerical_identity(),'portable_package_identity':package_identity(),
         'training_python':'/mnt/workspace/envs/splendor-ppo-m67-py312/bin/python',
         'arena_python':'/mnt/workspace/envs/splendor-arena-py312/bin/python',
         'training_environment':{'torch':'2.6.0+cpu','numpy':'2.2.4','psutil':'7.0.0','Markdown':'3.7','cpu_threads':2},
         'arena_environment':{'numpy':'2.2.4','psutil':'7.0.0','Markdown':'3.8'},
         'source_pin_policy':'all dispatched bytes pinned before first launch; never modify active copy'},
       'inference_boundary':'player-view only; referee replay is offline audit only',
       'comparison_limit':'larger budget than M66; not a same-budget repetition or causal budget test; two seeds do not establish population robustness',
       'candidate_status':'NOT_RUN_UNPUBLISHED','default_replaced':False,'pool_deployed':False,'studio_deployed':False,'git_published':False}
    validate(c,bps)
    for k,bp in bps.items():write(ROOT/ARMS[k]['blueprint'],bp)
    write(ROOT/CONFIG,c)
    return {'status':c['status'],'config_sha256':digest(ROOT/CONFIG),'training_games':10240,'evaluation_games':110000,'new_games':0}

if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(freeze(),ensure_ascii=False))
