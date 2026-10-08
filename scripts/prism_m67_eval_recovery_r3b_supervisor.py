"""Finite total resource supervisor for the prepared R3B successor."""
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import prism_m67_eval_recovery_r3b as child
from scripts.prism_dsw_ppo_process import ProcessTree
from training.prism_portable.common import read,write,digest
BASE=ROOT/'continuation-r3b'


def run():
    import psutil
    p=read(BASE/'supervisor-policy.json')
    if digest(__file__)!=p['source_sha256'] or digest(child.__file__)!=p['child_sha256']:raise ValueError('supervisor source drift')
    child.verify()
    if read(BASE/'prepared.json')['status']!='PASS_ZERO_NEW_GAMES':raise ValueError('not prepared')
    with (BASE/'supervisor-once.lock').open('x'):pass
    me=psutil.Process();write(BASE/'supervisor-launch.json',dict(pid=me.pid,create_time=me.create_time(),at=time.time(),policy_sha256=digest(BASE/'supervisor-policy.json')))
    wall=child.old.verify();os.environ.update(PRISM_PPO_CONTROL_DIR=str(BASE/'total'),PRISM_DSW_REMAINING_WALL=str(wall),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    with (BASE/'stdout.log').open('xb') as out,(BASE/'stderr.log').open('xb') as err:
        with ProcessTree(cpu_seconds=72000,memory_bytes=8*1024**3,max_processes=64) as tree:
            tree.start([sys.executable,'-B',str(Path(child.__file__)),'run'],cwd=ROOT,stdout=out,stderr=err)
            resources=tree.wait(wall_seconds=wall,storage_root=ROOT,max_storage_bytes=64*1024**3,storage_interval=60,snapshot=lambda v:write(BASE/'supervisor-status.json',dict(at=time.time(),resources=v)))
    write(BASE/'supervisor-completion.json',resources)
    if resources['returncode'] or resources['stop_reason']:raise ValueError('successor stopped: '+str(resources))


if __name__=='__main__':run()
