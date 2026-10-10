"""M74 immutable finite schedule and capacity validation; zero games."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from training.prism_portable.common import identity
CONFIG='benchmarks/m74-prism-scaleup.config.json'
ARMS={'a':dict(games=5120,cycles=20,run_seed=74010001,seed_start=12001000,blueprint='benchmarks/m74-prism-scaleup-a.train.json')}
def validate(c,bps):
    if c['format']!='m74-prism-scaleup-v1' or c['base_model']['sha256']!='15e14e118e8dd5eb45d199e643c185a382ae5d67a503d446d27eaf575de8bed5':raise ValueError('parent/contract drift')
    if set(bps)!=set(ARMS) or c['training']['total_games']!=5120:raise ValueError('finite schedule drift')
    bp=bps['a'];r=bp['template']['run'];order=('general','parent','latest-alpha','latest-balance')
    expected=[[dict(job_id=f'm74-a-c{cy+1}-b{b}-s{s}',actor=s,opponent_id=order[b%4],environment_seed=12001000+128*cy+b) for b in range(128) for s in (0,1)] for cy in range(20)]
    if bp['template']['cycles']!=expected or identity(bp)!=c['training']['arms']['a']['blueprint_identity']:raise ValueError('schedule identity drift')
    if r['ppo']!=c['training']['ppo'] or r['seed']!=74010001:raise ValueError('PPO/RNG drift')
    b=r['budget']
    if (b['max_jobs'],b['max_attempts'],b['max_cycles'])!=(5120,5120,20):raise ValueError('budget drift')
    if b['max_storage_bytes']!=c['training']['storage_bytes'] or b['max_run_seconds']!=c['training']['wall_seconds']:raise ValueError('training caps disagree')
    if c['resources']['minimum_free_bytes']<c['resources']['total_storage_bytes']+c['resources']['whole_disk_reserve_bytes']:raise ValueError('capacity reserve missing')
    if c['evaluation']['mode']!='both-greedy' or c['evaluation']['total_games']!=9216 or c['resources']['automatic_retries']!=0:raise ValueError('evaluation/retry drift')
    if bp['weight_hashes']!={k:c['assets'][k]['sha256'] for k in order}:raise ValueError('opponent weights drift')
    return c
