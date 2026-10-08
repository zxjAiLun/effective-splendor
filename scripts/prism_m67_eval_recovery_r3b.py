"""Pinned successor for A partial shards; keep running R3 source unchanged.
Prepare recovery once before old R3 reaches run-a. Old run-a rejects that existing
folder without games. Successor waits for that exact safe failure and old PID exit.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import prism_m67_eval_recovery_r3 as old
from training.prism_portable.common import read,write,digest
from scripts.prism_dsw_ppo_process import ProcessTree,same_process
BASE=ROOT/'continuation-r3b'
WORK=ROOT/'evaluation/a-common-recovery-r3'


def verify():
    old.verify();p=read(BASE/'policy.json')
    if digest(__file__)!=p['adapter_sha256'] or digest(old.__file__)!=p['r3_adapter_sha256']:
        raise ValueError('successor source drift')
    return p


def guard(shard):
    cp,out=Path(shard['config']),Path(shard['output'])
    if digest(cp)!=shard['sha256']:raise ValueError('shard config hash drift')
    v=old.arena.validate_arena_config(read(cp),cp)
    progress=read(out/'progress.json');recovery=read(out/'recovery.json')
    if progress['config_sha256']!=old.fixed.canonical_hash(read(cp)):raise ValueError('progress config drift')
    old.missing_keys(v['config'],progress['games'],recovery['orphan_keys'])
    if not set(recovery['retained_errors']).issubset(old.expected_keys(v['config'])):
        raise ValueError('unexpected retained failure')


def prepare():
    verify();proof=read(old.R3/'preflight.json')
    plan=read(ROOT/'evaluation/a-common/plan.json');orphans=[]
    for shard in plan['shards']:
        _,_,found=old.scan_saved(shard);orphans.extend(found)
    if sorted(orphans)!=sorted(proof['orphan_keys']):raise ValueError('orphan cohort changed after preflight')
    work=old.prepare_a()
    p=read(work/'plan.json')
    if sorted(p['recovery']['deferred_keys'])!=sorted([*proof['original_failure_keys'],*proof['orphan_keys']]):
        raise ValueError('deferred cohort drift')
    for shard in p['shards']:
        if read(work/'status.json')['shards'][shard['name']]['state']=='PENDING':guard(shard)
    write(BASE/'prepared.json',dict(status='PASS_ZERO_NEW_GAMES',plan_sha256=digest(work/'plan.json'),deferred_keys=p['recovery']['deferred_keys'],at=time.time()))


def worker(name):
    verify();plan=read(WORK/'plan.json')
    if digest(WORK/'plan.json')!=read(BASE/'prepared.json')['plan_sha256']:raise ValueError('prepared plan drift')
    shard=next(s for s in plan['shards'] if s['name']==name);guard(shard)
    result=old.a_worker(shard);write(Path(shard['output'])/'worker-receipt.json',result)


def run():
    import psutil
    verify();me=psutil.Process();launch=read(old.R3/'launch.json')
    state=dict(state='WAITING_DOWNSTREAM_SAFE_BOUNDARY',pid=me.pid,create_time=me.create_time(),at=time.time())
    write(BASE/'status.json',state)
    while same_process(launch['pid'],launch['create_time']):
        verify();time.sleep(5)
    stopped=read(old.R3/'status.json')
    if stopped['state']!='FAILED_STOPPED_NO_RETRY' or stopped['phase']!='run-a' or not (old.R3/'run-a/completion.json').exists():
        raise ValueError('old pipeline stopped outside expected prepared-directory boundary')
    for name in ('a-direct','b-common','b-direct'):
        if read(ROOT/f'evaluation/{name}/status.json')['state']!='COMPLETED_DEVELOPMENT_ONLY':
            raise ValueError('downstream incomplete')
    plan=read(WORK/'plan.json');state=read(WORK/'status.json');state.update(state='RUNNING_EXPLICIT_RECOVERY_R3B',pid=me.pid,create_time=me.create_time(),at=time.time());write(WORK/'status.json',state);write(BASE/'status.json',state)
    os.environ['PRISM_PPO_CONTROL_DIR']=str(BASE);os.environ['PRISM_DSW_REMAINING_WALL']=str(min(18000,old.verify()))
    def shard_run(shard):
        folder=BASE/shard['name'];folder.mkdir(exist_ok=False)
        with (folder/'stdout.log').open('xb') as out,(folder/'stderr.log').open('xb') as err:
            with ProcessTree(cpu_seconds=7200,memory_bytes=2*1024**3,max_processes=10) as tree:
                tree.start([sys.executable,'-B',__file__,'worker','--shard',shard['name']],cwd=ROOT,stdout=out,stderr=err)
                resources=tree.wait(wall_seconds=min(1800,old.verify()),storage_root=ROOT,max_storage_bytes=64*1024**3,storage_interval=60)
        write(folder/'process-receipt.json',resources)
        if resources['returncode'] or resources['stop_reason']:raise ValueError('successor shard failure')
        return read(Path(shard['output'])/'worker-receipt.json')
    pending=[s for s in plan['shards'] if state['shards'][s['name']]['state']=='PENDING']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(shard_run,s):s for s in pending}
        for future in concurrent.futures.as_completed(futures):
            shard=futures[future];state['shards'][shard['name']]=future.result()
            state.update(completed_games=sum(s.get('games',s.get('reused_games',0)) for s in state['shards'].values()),observed_at=time.time())
            write(WORK/'status.json',state);write(BASE/'status.json',state)
    state.update(state='EVALUATIONS_FINISHED_WITH_RETAINED_GAPS',finished_at=time.time());write(WORK/'status.json',state);write(BASE/'status.json',state);write(BASE/'completion.json',state)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','run','worker']);parser.add_argument('--shard');args=parser.parse_args()
    worker(args.shard) if args.mode=='worker' else globals()[args.mode]()
