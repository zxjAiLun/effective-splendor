"""M75 immutable finite schedule and capacity validation; zero games."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from training.prism_portable.common import identity
CONFIG='benchmarks/m75-prism-continuation.config.json'
ARMS={'a':dict(games=5120,cycles=20,run_seed=75010001,seed_start=13001000,blueprint='benchmarks/m75-prism-continuation-a.train.json')}
def validate(c,bps):
    if c['format']!='m75-prism-continuation-v1' or c['base_model']['sha256']!='e16bfe0d30168d6ef7ceb067ca4357900f1c09e09d35f5759832dd3d6a9258ad':raise ValueError('parent/contract drift')
    if set(bps)!=set(ARMS) or c['training']['total_games']!=5120:raise ValueError('finite schedule drift')
    bp=bps['a'];r=bp['template']['run'];order=('general','parent','latest-alpha','latest-balance')
    expected=[[dict(job_id=f'm75-a-c{cy+1}-b{b}-s{s}',actor=s,opponent_id=order[b%4],environment_seed=13001000+128*cy+b) for b in range(128) for s in (0,1)] for cy in range(20)]
    if bp['template']['cycles']!=expected or identity(bp)!=c['training']['arms']['a']['blueprint_identity']:raise ValueError('schedule identity drift')
    if r['ppo']!=c['training']['ppo'] or r['seed']!=75010001:raise ValueError('PPO/RNG drift')
    b=r['budget']
    if (b['max_jobs'],b['max_attempts'],b['max_cycles'])!=(5120,5120,20):raise ValueError('budget drift')
    if b['max_storage_bytes']!=c['training']['storage_bytes'] or b['max_run_seconds']!=c['training']['wall_seconds']:raise ValueError('training caps disagree')
    if c['resources']['minimum_free_bytes']<c['resources']['total_storage_bytes']+c['resources']['whole_disk_reserve_bytes']:raise ValueError('capacity reserve missing')
    if c['evaluation']['mode']!='both-greedy' or c['evaluation']['total_games']!=9216 or c['resources']['automatic_retries']!=0:raise ValueError('evaluation/retry drift')
    d=c['development'];e=c['evaluation']
    if d['checkpoints']!=[5,10,15,20] or (d['seed_start'],d['seed_end'],d['total_games'],d['both_sides'],d['opponent'])!=(13040000,13040127,1024,'greedy','parent'):raise ValueError('development curve drift')
    ranges=list(e['common_seed_by_opponent'].values())+list(e['coverage_seed_by_opponent'].values())+[[e['direct_seed_start'],e['direct_seed_end']],[13001000,13003559]]
    if any(max(lo,d['seed_start'])<=min(hi,d['seed_end']) for lo,hi in ranges):raise ValueError('development seed overlap')
    if bp['weight_hashes']!={k:c['assets'][k]['sha256'] for k in order}:raise ValueError('opponent weights drift')
    return c
