"""M73 execution contract; freeze once, without dispatching any games."""
import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,identity

CONFIG='benchmarks/m73-prism-repeat.config.json'
PARENT_SHA='e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4'
ARMS={a:dict(games=1024,cycles=4,run_seed=73010001+i,seed_start=11001000+1000*i,
             blueprint=f'benchmarks/m73-prism-repeat-{a}.train.json') for i,a in enumerate('abc')}
ORDER=('general','parent','general','alpha','general','parent','general','beta')
PRIMARY=['heuristic','general','balance','alpha','beta','released-alpha']
RANGES=[(11000000,11000003,'m73-engineering-training'),(11000010,11000013,'m73-engineering-evaluation')]
RANGES += [(v['seed_start'],v['seed_start']+511,'m73-training-'+a) for a,v in ARMS.items()]
RANGES += [(11010000+i*1000,11010255+i*1000,'m73-independent-'+o) for i,o in enumerate(PRIMARY)]
RANGES += [(11020000+i*1000,11020255+i*1000,'m73-coverage-'+o) for i,o in enumerate(['latest-alpha','latest-balance'])]
RANGES += [(11030000,11030511,'m73-direct-B')]

def blueprint(template,hashes,arm='a',engineering=False):
    path='benchmarks/m73-prism-repeat-engineering.train.json' if engineering else ARMS[arm]['blueprint']
    bp=read(ROOT/path)
    if bp['weight_hashes']!={k:hashes[k] for k in ('parent','general','alpha','beta')}:raise ValueError('weight pin drift')
    return bp

def validate(c,bps):
    if c['format']!='m73-prism-repeat-v1' or c['base_model']['sha256']!=PARENT_SHA:raise ValueError('M73 parent/contract drift')
    if set(bps)!=set(ARMS) or c['training']['total_games']!=3072:raise ValueError('arm count/budget drift')
    for a,v in ARMS.items():
        bp=bps[a];run=bp['template']['run'];jobs=[j for group in bp['template']['cycles'] for j in group]
        expected=[dict(job_id=f'm73-{a}-c{cy+1}-b{b}-s{s}',actor=s,opponent_id=ORDER[b%len(ORDER)],environment_seed=v['seed_start']+128*cy+b) for cy in range(4) for b in range(128) for s in (0,1)]
        if jobs!=expected or run['seed']!=v['run_seed'] or identity(bp)!=c['training']['arms'][a]['blueprint_identity']:raise ValueError('training schedule/identity drift')
        if run['ppo']!=c['training']['ppo']:raise ValueError('PPO drift')
        if (run['budget']['max_jobs'],run['budget']['max_attempts'],run['budget']['max_cycles'])!=(1024,1024,4):raise ValueError('training budget drift')
    e=c['evaluation']
    if e['mode']!='both-greedy' or e['total_games']!=19456 or e['common_opponents']!=PRIMARY:raise ValueError('evaluation scope drift')
    if c['resources']['automatic_retries']!=0 or c['seed_reservations']!=[list(r) for r in RANGES]:raise ValueError('retry/seed drift')
    return c

def freeze():
    if (ROOT/CONFIG).exists():raise ValueError('already frozen')
    c=copy.deepcopy(read(ROOT/'benchmarks/m70-prism-b-continuation.config.json'))
    design=read(ROOT/'benchmarks/m73-prism-v020-experiment-design.json')
    for k,model in [('latest-alpha',design['models'][0]),('latest-balance',design['models'][2])]:
        c['assets'][k]=dict(local_path=model['weights_path'],sha256=model['weights_sha256'])
    c['assets']['parent']['local_path']='local-artifacts/prism/balance-v0.2.0/weights.json'
    from scripts.s0_seed_registry import REGISTRY
    prior=list(REGISTRY);sources={}
    for p in (ROOT/'benchmarks').glob('m*.config.json'):
        saved=read(p);prior.extend(tuple(r) for r in saved.get('seed_reservations',[]));sources[p.relative_to(ROOT).as_posix()]=digest(p)
    for lo,hi,label in RANGES:
        if any(max(lo,a)<=min(hi,b) for a,b,_ in prior):raise ValueError('seed conflict: '+label)
    for v in c['assets'].values():
        if digest(ROOT/v['local_path'])!=v['sha256']:raise ValueError('asset drift')
    template=read(ROOT/'benchmarks/m70-prism-b-continuation.train.json');bps={}
    for a,v in list(ARMS.items())+[('engineering',dict(run_seed=73000001,seed_start=11000000,blueprint='benchmarks/m73-prism-repeat-engineering.train.json'))]:
        bp=copy.deepcopy(template);engineering=a=='engineering';bp['purpose']='fixed-B-M70-recipe-independent-repeat';bp['model_label']='M73 '+a+' final c4' if not engineering else 'M73 engineering-only'
        run=bp['template']['run'];run.update(run_id='m73-'+a,seed=v['run_seed'])
        run['budget'].update(max_cycles=1 if engineering else 4,max_jobs=8 if engineering else 1024,max_attempts=8 if engineering else 1024,max_storage_bytes=2*1024**3)
        if engineering:run['budget'].update(max_decisions=8*256,max_run_seconds=1200)
        bp['template']['limits'].update(max_physical_decisions=(8 if engineering else 1024)*256,campaign_cpu_seconds=2400 if engineering else 40000)
        bp['template']['cycles']=[[dict(job_id=f'm73-{a}-c{cy+1}-b{b}-s{s}',actor=s,opponent_id=('general','parent','alpha','beta')[b%4] if engineering else ORDER[b%8],environment_seed=v['seed_start']+(4 if engineering else 128)*cy+b) for b in range(4 if engineering else 128) for s in (0,1)] for cy in range(1 if engineering else 4)]
        write(ROOT/v['blueprint'],bp)
        if not engineering:bps[a]=bp
    c.update(format='m73-prism-repeat-v1',status='FROZEN_BEFORE_FIRST_GAME',frozen_at=datetime.now(timezone.utc).isoformat(),
             authorization=dict(source='human_owner',request='按刚才的步骤进行迭代',authorized_end='minimum engineering + three B-parent repeats + full fixed evaluation/reports; no next pool experiment or deployment'),
             seed_reservations=[list(r) for r in RANGES],seed_check=dict(status='PASS',prior_ranges=len(prior),configs=sources),base_model=dict(name='Prism Balance v0.2.0',sha256=PARENT_SHA))
    c['names'].update(parent='Prism Balance v0.2.0',**{'latest-alpha':'Prism Alpha v0.2.0','latest-balance':'Prism Balance v0.2.1'})
    for a in ARMS:c['names']['candidate-'+a]='M73 seed '+a.upper()+' final c4 (unpublished)'
    c['training'].update(arms={a:dict(v,blueprint_identity=identity(bps[a])) for a,v in ARMS.items()},total_games=3072,storage_bytes=2*1024**3)
    for k in ('blueprint','blueprint_identity','run_seed'):c['training'].pop(k,None)
    c['resources'].update(total_storage_bytes=16*1024**3,minimum_free_bytes=18*1024**3,round_wall_seconds=12*3600,total_cpu_seconds=172800)
    c['runtime']['remote_root']='/mnt/workspace/splendor-m73-repeat'
    c['evaluation'].update(total_games=19456,action_seed=73020001,bootstrap_seed=73029999,bootstrap_samples=20000,lower_quantile=.05/6,mode='both-greedy',
        common_seed_by_opponent={o:[11010000+i*1000,11010255+i*1000] for i,o in enumerate(PRIMARY)},coverage_seed_by_opponent={o:[11020000+i*1000,11020255+i*1000] for i,o in enumerate(['latest-alpha','latest-balance'])},direct_seed_start=11030000,direct_seed_end=11030511,
        max_truncated_games_total=16,ply_cap=512,workers=4,shard_seed_blocks=32,
        enhancement_point_min=dict(common_delta=.02,direct_score=.52),retention_coverage_delta=-.03,
        inference='six-endpoint Bonferroni one-sided model enhancement; separate six-coverage retention family; ordinary CI descriptive; not sole research-continuation rule')
    c['evaluation']['gates']={'candidate/strength_pool':-.05,'candidate/direct_parent':.45}
    c['sample_size_rationale']='Finite three-training-seed estimates; direct single-endpoint approximate power 27%; no extension or best-seed selection.'
    c['failure_policy']='No research retries; explicit 512-ply retained truncation budget16 across19456; incomplete qualification withheld; unknown/resource failures stop.'
    c['measurement_contract']='m73-progress-and-style-v1; terminal/truncated/error split, ply quantiles, no-buy and unchanged-token windows; first large-card Main/coverage, Main12/20/24 VP if reconstructible; legal opportunities NOT_MEASURED without full actions; FIFO redemption deferred NOT_MEASURED.'
    validate(c,bps);write(ROOT/CONFIG,c)
    return dict(status=c['status'],sha256=digest(ROOT/CONFIG),new_games=0)

if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args();print(freeze())
