"""M66 normative contract/blueprint. No process launch or match dispatch."""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import digest, identity, numerical_identity, package_identity, read, write

CONFIG = 'benchmarks/m66-prism-alpha-dsw.config.json'
BLUEPRINT = 'benchmarks/m66-prism-alpha-dsw.train.json'
REMOTE = '/mnt/workspace/splendor-m66-alpha'
PARENT_SHA = '3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12'
ORDER = ('general', 'parent', 'general', 'alpha', 'general', 'parent', 'general', 'beta')
NAMES = {'parent': 'Prism Alpha v0.1.5', 'general': 'Prism v0.1.1', 'initial': 'Prism v0.1.0',
         'alpha': 'Prism Alpha v0.1.4', 'beta': 'Prism Beta v0.1.0', 'balance': 'Prism Balance v0.1.0',
         'heuristic': 'Heuristic v0.3.1', 'candidate': 'M66 final c4 unpublished training checkpoint'}
RANGES = [(9700000, 9700003, 'm66-engineering-not-research'),
          (9701000, 9701511, 'm66-training'), (9711000, 9711511, 'm66-independent-never-train')]


def build_blueprint(template, hashes, engineering=False):
    bp = copy.deepcopy(template)
    bp.update(purpose='finite-alpha-start-outcome-only-ppo', cancel_fixture=False,
              model_label='M66 engineering unpublished checkpoint' if engineering else NAMES['candidate'])
    bp['weight_hashes'] = {k: hashes[k] for k in ('parent', 'general', 'alpha', 'beta')}
    t = bp['template']; run = t['run']
    descriptor = t['opponents']['prism-general-v011']
    t['opponents'] = {}
    for i, key in enumerate(('general', 'parent', 'alpha', 'beta')):
        row = copy.deepcopy(descriptor)
        row['args'] = ['agent-prism', '--weights', '@'+key, '--seed', str(66010002+i)]
        row['files'] = {'@'+key: '@'+key+'_sha256'}
        t['opponents'][key] = row
    run.update(run_id='m66-engineering' if engineering else 'm66-alpha-outcome', seed=66000001 if engineering else 66010001,
               format='prism-ppo-run-v2', cpu_threads=2)
    run.pop('style', None)
    run['ppo'].update(style_beta=0.0, style_value_weight=0.0)
    run['opponents'] = {k: '' for k in t['opponents']}
    count, cycles = (8, 1) if engineering else (1024, 4)
    run['budget'].update(max_cycles=cycles, max_jobs=count, max_attempts=count,
        max_decisions=count*256, max_job_decisions=256, max_optimizer_steps=2048,
        max_update_attempts=2048, max_run_seconds=1200 if engineering else 10800,
        max_storage_bytes=(4 if engineering else 32)*1024**3)
    t['limits'].update(memory_bytes=8*1024**3, campaign_cpu_seconds=2400 if engineering else 40000,
                       max_physical_decisions=count*256, max_infra_retries=0)
    order = ('general','parent','alpha','beta') if engineering else ORDER
    blocks = 4 if engineering else 128
    start = 9700000 if engineering else 9701000
    t['cycles'] = [[dict(job_id=f'm66-{run["run_id"]}-c{c+1}-b{b}-s{s}', actor=s,
                        opponent_id=order[b % len(order)], environment_seed=start+c*blocks+b)
                    for b in range(blocks) for s in (0,1)] for c in range(cycles)]
    return bp


def validate(c, bp):
    if c['format'] != 'm66-prism-alpha-dsw-v1' or c['base_model']['sha256'] != PARENT_SHA:
        raise ValueError('M66 contract/parent drift')
    t = bp['template']; r = t['run']
    if (len(t['cycles']), sum(map(len,t['cycles'])), r['ppo']['style_beta'], r['ppo']['style_value_weight']) != (4,1024,0,0):
        raise ValueError('M66 finite/outcome-only budget drift')
    if [list(x) for x in c['seed_reservations']] != [list(x) for x in RANGES]:
        raise ValueError('M66 seed drift')
    if c['evaluation']['total_games'] != 7168 or c['evaluation']['mode'] != 'both-greedy':
        raise ValueError('M66 evaluation scope drift')
    if c['training']['blueprint_identity'] != identity(bp):
        raise ValueError('M66 blueprint drift')
    if c['evaluation']['gates'] != {'candidate/strength_pool':-.05,'candidate/direct_parent':.45}:
        raise ValueError('M66 gate drift')
    return c


def freeze():
    if (ROOT/CONFIG).exists() or (ROOT/BLUEPRINT).exists():
        raise ValueError('M66 already frozen; never overwrite')
    assets = {key: ROOT/path for key,path in {
        'parent':'local-artifacts/prism/alpha-v0.1.5/weights.json',
        'beta':'local-artifacts/prism/beta-v0.1.0/weights.json',
        'alpha':'local-artifacts/prism/alpha-v0.1.4/weights.json',
        'balance':'local-artifacts/prism/balance-v0.1.0/weights.json',
        'general':'local-artifacts/prism/v0.1.1/weights.json',
        'initial':'local-artifacts/prism/v01/run/weights.json',
        'fixtures':'local-artifacts/prism/portable-m57/inputs/boundary-fixtures.jsonl'}.items()}
    hashes = {k:digest(p) for k,p in assets.items()}
    if hashes['parent'] != PARENT_SHA: raise ValueError('released starting weight changed')
    from scripts.s0_seed_registry import REGISTRY
    ranges = list(REGISTRY); sources = {}
    for p in sorted((ROOT/'benchmarks').glob('m*.config.json')):
        if p.name.startswith('m66-'): continue
        value = read(p)
        if 'seed_reservations' in value:
            ranges.extend(tuple(row) for row in value['seed_reservations'])
            sources[p.relative_to(ROOT).as_posix()] = digest(p)
    for lo,hi,label in RANGES:
        for a,b,name in ranges:
            if max(lo,a) <= min(hi,b): raise ValueError(f'{label} overlaps {name}')
    template = read(ROOT/'benchmarks/m63-prism-control-building.train.json')
    bp = build_blueprint(template, hashes)
    c = {'format':'m66-prism-alpha-dsw-v1','status':'FROZEN_BEFORE_FIRST_GAME',
         'frozen_at':datetime.now(timezone.utc).isoformat(),
         'authorization':{'source':'human_owner','request':'来吧 别让dsw上算力等太久','date':'2026-10-05'},
         'base_model':{'name':NAMES['parent'],'sha256':hashes['parent']},
         'names':NAMES,'seed_reservations':RANGES,
         'seed_check':{'status':'PASS','prior_ranges':len(ranges),'configs':sources,'registry_sha256':digest(ROOT/'scripts/s0_seed_registry.py')},
         'assets':{k:{'local_path':p.relative_to(ROOT).as_posix(),'sha256':hashes[k]} for k,p in assets.items()},
         'training':{'games':1024,'cycles':4,'games_per_cycle':256,'mode':'categorical-T1',
             'mix':{'general':512,'parent':256,'alpha':128,'beta':128},'run_seed':66010001,
             'ppo':bp['template']['run']['ppo'],'blueprint':BLUEPRINT,'blueprint_identity':identity(bp),
             'initialization':'exact exported weights; fresh AdamW/RNG; outcome-only; not full-state resume',
             'selection':'final c4 only; no tuning from reference results',
             'wall_seconds':10800,'cpu_seconds':40000,'memory_bytes':8*1024**3,'storage_bytes':32*1024**3},
         'engineering':{'games':8,'run_seed':66000001,'wall_seconds':1200,'cpu_seconds':2400,'research_use':False},
         'evaluation':{'mode':'both-greedy','action_seed':66020001,'total_games':7168,
             'common_opponents':['heuristic','initial','general','balance','alpha','beta'],
             'common_seed_start':9711000,'common_seed_end':9711255,'common_games_per_model':3072,
             'direct_seed_start':9711000,'direct_seed_end':9711511,'direct_games':1024,
             'workers':4,'wall_seconds_per_arena':7200,'cpu_seconds_per_arena':20000,
             'memory_bytes':8*1024**3,'storage_bytes_per_arena':16*1024**3,
             'gates':{'candidate/strength_pool':-.05,'candidate/direct_parent':.45},
             'enhancement_thresholds':{'candidate/strength_pool':0.,'candidate/direct_parent':.5},
             'bootstrap_samples':20000,'bootstrap_seed':66029999,'family_alpha':.05,'lower_quantile':.025,
             'statistical_unit':'two-seat seed block; equal mean over six opponents; paired candidate minus starting weight',
             'style':'descriptive observed route; no style veto','selection':'no extension/checkpoint selection'},
         'resources':{'round_wall_seconds':21600,'automatic_retries':0,'rss_limit_scope':'sampled process-tree soft limit; no owned cgroup',
                      'available_cpu_affinity':[0,1,2,3]},
         'runtime':{'remote_root':REMOTE,'numeric_source_identity':numerical_identity(),'portable_package_identity':package_identity(),
                    'training_environment':{'torch':'2.6.0+cpu','numpy':'2.2.4','psutil':'7.0.0','cpu_threads':2},
                    'source_pin_policy':'separate exact execution manifest before each first launch; never modify dispatched copies'},
         'candidate_status':'NOT_RUN_UNPUBLISHED','default_replaced':False,'pool_deployed':False,'studio_deployed':False,'git_published':False}
    validate(c,bp)
    write(ROOT/BLUEPRINT,bp); write(ROOT/CONFIG,c)
    return {'status':c['status'],'config_sha256':digest(ROOT/CONFIG),'blueprint_sha256':digest(ROOT/BLUEPRINT),
            'training_games':1024,'evaluation_games':7168,'new_games':0}


if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(freeze(),ensure_ascii=False))
