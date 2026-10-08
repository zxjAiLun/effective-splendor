"""M66 DSW training entrypoint: explicit preflight, isolated engineering, once-only train.

Does not resume failed campaigns, register models, or change numerical sources.
Training stops at final c4; subsequent read-only audit/evaluation has a separate pin.
"""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,identity,package_identity,numerical_identity
from scripts.prism_m66_prepare import CONFIG,BLUEPRINT,build_blueprint,validate
from scripts.prism_dsw_ppo_process import ProcessTree,same_process,install

CONFIG_SHA='1770d3635149f5df7b4f06630457c329604971adb98afb4c81355c93027572aa'


def contract():
    if digest(ROOT/CONFIG)!=CONFIG_SHA:raise ValueError('frozen M66 contract drift')
    c=read(ROOT/CONFIG);validate(c,read(ROOT/BLUEPRINT))
    if numerical_identity()!=c['runtime']['numeric_source_identity']:raise ValueError('PPO numerical source drift')
    return c


def source_hashes():
    paths=[p for p in (ROOT/'training/prism_portable').rglob('*.py') if 'tests' not in p.parts]
    paths += [ROOT/'scripts'/name for name in ('prism_m66_prepare.py','prism_m66_train.py','prism_dsw_ppo_process.py')]
    return {p.relative_to(ROOT).as_posix():digest(p) for p in sorted(paths)}


def environment():
    return {'python':sys.version,'executable':str(Path(sys.executable).resolve()),
            'packages':{k:importlib.metadata.version(k) for k in ('torch','numpy','psutil','Markdown')},
            'affinity':sorted(os.sched_getaffinity(0))}


def verify():
    c=contract();p=read(ROOT/'training-execution.json')
    if p['config_sha256']!=CONFIG_SHA or p['source_hashes']!=source_hashes():raise ValueError('training execution/source pin drift')
    if p['environment']!=environment():raise ValueError('pinned training environment drift')
    if p['host_sha256']!=digest(ROOT/'host.json') or p['blueprint_sha256']!=digest(ROOT/BLUEPRINT):raise ValueError('host/blueprint drift')
    return c,p


def preflight():
    c=contract()
    if (ROOT/'training-execution.json').exists():raise ValueError('training execution already pinned')
    env=environment()
    for key,expected in c['runtime']['training_environment'].items():
        if key!='cpu_threads' and env['packages'][key]!=expected:raise ValueError('unexpected dependency: '+key)
    if env['affinity']!=[0,1,2,3]:raise ValueError('DSW allocation changed')
    from training.prism_portable.provision import provision
    host,parity=provision(ROOT,ROOT,ROOT/'bin/splendor',ROOT/'bin/s4_batch_metrics',
                         ROOT/'inputs/parent.json',ROOT/'inputs/initial.json',ROOT/'inputs/fixtures.jsonl','dsw-m66')
    for key,asset in c['assets'].items():
        path=ROOT/'inputs'/(key+('.jsonl' if key=='fixtures' else '.json'))
        if digest(path)!=asset['sha256']:raise ValueError('fixed input drift: '+key)
        host['assets'][key]={'path':str(path),'sha256':digest(path)}
    write(ROOT/'host.json',host)
    from training.prism_portable.protocol import bind
    bind(read(ROOT/BLUEPRINT),host)
    p={'format':'m66-training-execution-v1','status':'VERIFIED_ZERO_GAMES',
       'config_sha256':CONFIG_SHA,'source_hashes':source_hashes(),'environment':env,
       'host_sha256':digest(ROOT/'host.json'),'blueprint_sha256':digest(ROOT/BLUEPRINT),
       'package_identity':package_identity(),'numerical_identity':numerical_identity(),
       'parity':parity,'created_at':datetime.now(timezone.utc).isoformat(),
       'process_scope':'separate DSW relays/process groups; sampled RSS soft limit plus per-process AS/CPU caps',
       'games':0,'training_started':False}
    write(ROOT/'training-execution.json',p)
    return {'status':p['status'],'boundary_inputs':parity['boundary_inputs'],'max_abs_error':parity['max_abs_error'],
            'execution_sha256':digest(ROOT/'training-execution.json')}


def worker(engineering):
    c,_=verify();install()
    from training.prism_portable.protocol import create
    from training.prism_portable.worker import execute
    from training.prism_portable.engine.ppo.arena import Campaign
    bp=read(ROOT/BLUEPRINT)
    if engineering:
        bp=build_blueprint(read(ROOT/'benchmarks/m63-prism-control-building.train.json'),
                           {k:v['sha256'] for k,v in c['assets'].items()},True)
    name='engineering' if engineering else 'training'
    camp=ROOT/'campaigns'/name;host=read(ROOT/'host.json');host['_path']=str(ROOT/'host.json')
    owner=create(camp,bp,host,'m66-'+name)
    os.environ.update(PRISM_PPO_HOST_ID=host['host_id'],PRISM_PPO_OWNER_NONCE=owner['nonce'],
                      PRISM_PPO_CONTROL_DIR=str(camp/'control'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    original=Campaign.launch
    def tracked(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        s=self.run.state
        write(camp/'control/live-progress.json',{'observed_at':time.time(),'cycle':s['cycle'],'phase':s['phase'],
              'completed_games':sum(1 for a in self._load()[1]['attempts'].values() if a['status']=='COMPLETE'),
              'attempts':s['attempts'],'global_step':s['global_step'],'update_attempts':s['update_attempts']})
        return result
    Campaign.launch=tracked  # monitoring only; the frozen launch/update body is unchanged
    execute(camp,host,owner['nonce'],1 if engineering else 4)
    s=read(camp/'control/progress.json')
    expected=8 if engineering else 1024
    if s['phase']!='COMMITTED' or s['attempts']!=expected:raise ValueError('incomplete committed training')
    export=camp/f'cycle-{1 if engineering else 4}-export/weights.json'
    write(camp/'worker-completion.json',{'status':'STOPPED_COMMITTED','games':expected,'cycle':s['cycle'],
          'global_step':s['global_step'],'update_attempts':s['update_attempts'],
          'weights':str(export),'weights_sha256':digest(export),'execution_sha256':digest(ROOT/'training-execution.json')})


def supervise(engineering):
    c,p=verify();name='engineering' if engineering else 'training';control=ROOT/'control'/name
    control.mkdir(parents=True,exist_ok=True)
    with (control/'once-only.lock').open('x'):pass
    import psutil
    me=psutil.Process()
    state={'state':'RUNNING','phase':name.upper(),'pid':me.pid,'create_time':me.create_time(),
           'started_at':time.time(),'execution_sha256':digest(ROOT/'training-execution.json'),
           'completed_games':0,'total_games':8 if engineering else 1024}
    write(control/'status.json',state)
    round_budget=read(ROOT/'round-budget.json')
    limits=c['engineering'] if engineering else c['training']
    wall=min(limits['wall_seconds'],round_budget['deadline']-time.time())
    if wall<=0:raise ValueError('original round deadline exhausted')
    os.environ.update(PRISM_PPO_CONTROL_DIR=str(control),PRISM_DSW_REMAINING_WALL=str(wall),
                      OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    argv=[sys.executable,'-B',str(Path(__file__).resolve()),'worker']+(['--engineering'] if engineering else [])
    def snapshot(counters):
        state['resources']=counters;state['observed_at']=time.time();state['elapsed_seconds']=time.time()-state['started_at']
        live=ROOT/'campaigns'/name/'control/live-progress.json'
        progress=ROOT/'campaigns'/name/'control/progress.json'
        if live.exists():state.update(read(live))
        if progress.exists():
            committed=read(progress)
            state['committed_cycle']=committed['cycle'];state['global_step']=committed['global_step']
        write(control/'status.json',state)
    try:
        with (control/'stdout.log').open('wb') as out,(control/'stderr.log').open('wb') as err:
            with ProcessTree(cpu_seconds=limits['cpu_seconds'],memory_bytes=8*1024**3,max_processes=32) as tree:
                child=tree.start(argv,cwd=ROOT,stdout=out,stderr=err);state['worker_relay_pid']=child.pid
                resources=tree.wait(wall_seconds=wall,storage_root=ROOT/'campaigns'/name,
                    max_storage_bytes=(4 if engineering else 32)*1024**3,snapshot=snapshot)
        if resources['returncode']!=0 or resources['stop_reason']:raise RuntimeError('bounded worker failed: '+str(resources))
        result=read(ROOT/'campaigns'/name/'worker-completion.json')
        if result['games']!=state['total_games']:raise ValueError('completion count mismatch')
        state.update(state='STOPPED_COMMITTED',phase='AWAITING_SEPARATE_AUDIT' if not engineering else 'ENGINEERING_COMPLETE',
                     completed_games=result['games'],resources=resources,completion=result,finished_at=time.time())
        write(control/'completion.json',state);write(control/'status.json',state)
        return state
    except BaseException as error:
        state.update(state='FAILED_STOPPED_NO_RETRY',error=repr(error),finished_at=time.time())
        write(control/'status.json',state);raise


def start():
    verify()
    engineering=read(ROOT/'control/engineering/completion.json')
    if engineering['state']!='STOPPED_COMMITTED' or engineering['completed_games']!=8:raise ValueError('engineering did not pass')
    if read(ROOT/'evaluation/reference/status.json')['state']!='COMPLETED_DEVELOPMENT_ONLY':raise ValueError('reference still using DSW allocation')
    root=ROOT/'control/training';root.mkdir(parents=True,exist_ok=True)
    with (root/'launch-once.lock').open('x'):pass
    with (root/'supervisor.log').open('wb') as log:
        p=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'supervise'],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    import psutil
    row={'pid':p.pid,'create_time':psutil.Process(p.pid).create_time(),'execution_sha256':digest(ROOT/'training-execution.json'),
         'status':'STARTED_BOUNDED_TRAINING','games':1024,'cycles':4}
    write(root/'launch.json',row)
    return row


def status():
    rows={}
    for name in ('engineering','training'):
        p=ROOT/'control'/name/'status.json'
        if p.exists():
            s=read(p);s['alive']=same_process(s['pid'],s['create_time']);rows[name]=s
    return rows


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('preflight','supervise','worker','start','status'))
    p.add_argument('--engineering',action='store_true');a=p.parse_args()
    result=worker(a.engineering) if a.mode=='worker' else supervise(a.engineering) if a.mode=='supervise' else globals()[a.mode]()
    print(json.dumps(result,ensure_ascii=False))
