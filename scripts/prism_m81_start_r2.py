"""M81 independent ownership-nonce startup correction; preserve initial state."""
import sys,json,subprocess,time,platform,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import prism_m81_run as m
from training.prism_portable.common import read,write,digest,lock
SELF=str(Path(__file__).resolve())
REV=ROOT/'execution-revisions/start-r2'
def install():
    meta=read(REV/'revision.json')
    if meta['adapter_sha256']!=digest(SELF) or meta['execution_sha256']!=digest(ROOT/'execution.json'):raise ValueError('r2 binding drift')
    m.worker=m.adapted(m.worker,[("owner=assert_owner(camp,host['host_id'])","expected=read(camp/'ownership.json');owner=assert_owner(camp,host['host_id'],expected['nonce'])")])
    original=m.ProcessTree.start
    def route(self,argv,**kwargs):
        argv=[SELF if a==str(ROOT/'scripts/prism_m81_run.py') else a for a in argv]
        return original(self,argv,**kwargs)
    m.ProcessTree.start=route
def start():
    m.verify()
    import psutil
    for p in psutil.process_iter(['pid','cmdline']):
        if p.pid!=os.getpid() and any(str(ROOT) in a for a in (p.info['cmdline'] or [])):raise ValueError('owned process still active')
    with lock(REV/'once'):
        if (REV/'launch.json').exists():raise ValueError('r2 launch consumed')
        previous=read(ROOT/'pipeline/train-A.completion.json')
        if previous['status']!='FAIL' or previous['resources']['returncode']!=1:raise ValueError('unexpected failure')
        if 'ownership token mismatch' not in (ROOT/'pipeline/train-A.log').read_text():raise ValueError('failure not classified')
        m.install_resource_mode()
        from training.prism_portable.engine.ppo.coordinator import Run
        from training.prism_portable.protocol import state_fingerprints
        run=Run.open(ROOT/'campaigns/A/run')
        f=state_fingerprints(run.state)
        original=read(ROOT/'fresh-paired-state-preflight.json')['fingerprints'][0]
        if run.state['attempts']!=0 or any(f[k]!=original[k] for k in ('model','optimizer','rng')):raise ValueError('nonfresh or changed state')
        REV.mkdir(parents=True,exist_ok=True)
        for n in ('status.json','resources.json','train-A.completion.json'):write(REV/('prior-'+n),read(ROOT/'pipeline'/n))
        write(REV/'revision.json',dict(adapter_sha256=digest(SELF),execution_sha256=digest(ROOT/'execution.json'),original_failure_cpu_seconds=previous['resources']['cpu_seconds'],fingerprints=f,new_games_on_repair=0,launch_limit=1,observed_at=time.time()))
        with (REV/'supervisor.log').open('xb') as log:p=subprocess.Popen([m.PY,'-B',SELF,'pipeline'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        x=dict(node=platform.node(),pid=p.pid,create_time=psutil.Process(p.pid).create_time(),execution_sha256=digest(ROOT/'execution.json'),adapter_sha256=digest(SELF),observed_at=time.time())
        write(REV/'launch.json',x);print(json.dumps(x))
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('mode');p.add_argument('--stage');p.add_argument('--arm');p.add_argument('--stop-cycle',type=int,default=20);a=p.parse_args()
    if a.mode=='start':start()
    else:
        install()
        if a.mode=='pipeline':m.pipeline('main')
        else:m.execute(a.stage,a.arm,a.stop_cycle)
