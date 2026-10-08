"""Owned finite DSW calibration followed by the M62 release-support greedy grid.

Starts no PPO and never changes an existing frozen experiment. All matches are
predeclared; failed/partial shards stop the queue without automatic replay.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import prism_notebook_arena as arena


def semantic_digest(work):
    plan=arena.verify(work);state=arena.status(work);games=[]
    for shard in plan['shards']:
        for row in arena.completed_shard(shard,state['shards'][shard['name']]):
            p=Path(shard['output'])/'games'/row['candidate']/row['opponent']/f"seed-{row['seed']}-seat-{row['candidate_seat']}"
            replay=arena.read(p/'replay.json')
            games.append(dict(seed=row['seed'],seat=row['candidate_seat'],record=row['record'],
                steps=[dict(actor=s['actor'],action=s['action']) for s in replay['steps']]))
    games.sort(key=lambda g:(g['seed'],g['seat']))
    return hashlib.sha256(json.dumps(games,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def run():
    spec=arena.read(ROOT/'queue-config.json')
    fd=os.open(ROOT/'queue-once.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    begun=time.monotonic();records=[]
    def one(work,phase):
        arena.start(work)
        while True:
            state=arena.status(work)
            arena.write(ROOT/'queue-status.json',dict(state='RUNNING',phase=phase,work=str(work),arena=state,
                completed_phases=records,elapsed_seconds=time.monotonic()-begun))
            if state['state']=='COMPLETED_DEVELOPMENT_ONLY':return state
            if state['state'] in ('FAILED_PARTIAL_NO_RETRY','INTERRUPTED_NO_AUTO_RETRY'):
                raise RuntimeError('arena stopped; no retry: '+str(state))
            if time.monotonic()-begun>spec['total_wall_seconds']:
                arena.stop(work,False);raise RuntimeError('queue wall budget; drain requested')
            time.sleep(1)
    try:
        semantic=None
        for workers,repeat in spec['calibration_schedule']:
            work=ROOT/f'calibration/w{workers}-r{repeat}'
            state=one(work,'calibration-'+work.name)
            digest=semantic_digest(work)
            if semantic is None:semantic=digest
            if digest!=semantic:raise RuntimeError('calibration changed actions or outcomes')
            wall=state['elapsed_wall_seconds'];dispatch=state.get('dispatch_wall_seconds')
            records.append(dict(work=str(work),workers=workers,repeat=repeat,games=256,
                active_wall_seconds=wall,games_per_minute=256*60/wall,
                cpu_seconds=state['consumed_cpu_seconds'],peak_rss_bytes=state['resources']['peak_observed_rss_bytes'],
                semantic_sha256=digest,completion_sha256=arena.sha(work/'completion.json')))
        rows=[]
        for workers in (3,4,5,6):
            rs=[r for r in records if r['workers']==workers]
            seconds=sum(r['active_wall_seconds'] for r in rs)
            rows.append(dict(workers=workers,executions=512,games_per_minute=512*60/seconds,
                minutes_per_1000=1000*seconds/512/60,repeat_spread_ratio=abs(rs[0]['active_wall_seconds']-rs[1]['active_wall_seconds'])/max(r['active_wall_seconds'] for r in rs),
                peak_rss_bytes=max(r['peak_rss_bytes'] for r in rs)))
        fastest=max(rows,key=lambda r:r['games_per_minute'])
        eligible=[r for r in rows if r['workers']<=4]
        near=[r for r in eligible if r['games_per_minute']>=fastest['games_per_minute']*.95 and r['repeat_spread_ratio']<=.15]
        chosen=min(near,key=lambda r:r['workers']) if near else max(eligible,key=lambda r:r['games_per_minute'])
        calibration=dict(status='COMPLETED_PERFORMANCE_DIAGNOSTIC',executions=2048,unique_logical_games=256,
            rows=rows,records=records,fastest_workers=fastest['workers'],production_workers=chosen['workers'],
            selection='prefer stable <=4 workers within5% of fastest; otherwise fastest measured within ordinary allocation;5/6 are calibration-only',
            clock_scope='arena active wall includes dispatch, replay audit and reports; excludes preparation and semantic-comparison pass',
            new_strength_samples=0,automatic_retries=0)
        arena.write(ROOT/'calibration-result.json',calibration)
        # Selection changes resource allocation only, before preparing each new
        # fixed grid. The evaluation seeds, models and total were frozen upfront.
        request=spec['release_grid'];engine=Path(request['engine']);metrics=Path(request['metrics'])
        def model(key):
            item=request['models'][key]
            result=arena.model(item['weights'],item['name'],engine,mode='greedy',action_seed=request['action_seed'])
            if result['descriptor']['files'][0]['sha256']!=item['sha256']:raise RuntimeError('weight drift: '+key)
            return result
        models={k:model(k) for k in request['models']}
        opponents={'heuristic-v031':arena.heuristic(engine,'Heuristic v0.3.1'),
            'prism-v01':models['initial'],'prism-general-v011':models['general'],'alpha':models['alpha']}
        kw=dict(workers=chosen['workers'],action_seed=request['action_seed'],memory_gib=8,
            wall_hours=1,cpu_hours=4,storage_gib=8,shard_seed_blocks=8)
        for name,candidates,opps in [('common',{'base':models['base'],'beta':models['beta']},opponents),
            ('direct-parent',{'beta':models['beta']},{'parent':models['base']}),
            ('direct-new-alpha',{'beta':models['beta']},{'new_alpha':models['new_alpha']})]:
            work=ROOT/'release-evaluation'/name
            arena.prepare(work,engine,metrics,candidates,opps,request['seeds'],**kw)
            state=one(work,'release-'+name)
            records.append(dict(phase='release-'+name,games=state['completed_games'],completion_sha256=arena.sha(work/'completion.json')))
        arena.write(ROOT/'queue-completion.json',dict(status='COMPLETED_CALIBRATION_AND_RELEASE_SUPPORT',
            calibration_executions=2048,release_games=2560,automatic_retries=0,new_training=0,
            elapsed_seconds=time.monotonic()-begun,records=records))
        arena.write(ROOT/'queue-status.json',dict(state='COMPLETED',records=records,release_games=2560))
    except BaseException as error:
        arena.write(ROOT/'queue-failure.json',dict(status='FAILED_NO_RETRY',error=str(error),records=records))
        raise


if __name__=='__main__':run()
