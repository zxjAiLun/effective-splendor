"""M75 finite once-only DSW controller: preflight, train, audit, greedy, report.

All source bytes pinned before first launch. No automatic retry, resume, release,
or checkpoint/arm selection. Offline compression adapter preserves content hashes.
"""
import argparse
import importlib.metadata
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,numerical_identity
from scripts.prism_m75_prepare import CONFIG,ARMS,validate
from scripts.prism_dsw_ppo_process import ProcessTree,same_process,install as process_install


@lru_cache(maxsize=1)
def contract():
    c=read(ROOT/CONFIG)
    validate(c,{k:read(ROOT/a['blueprint']) for k,a in ARMS.items()})
    if numerical_identity()!=c['runtime']['numeric_source_identity']:raise ValueError('numerical source drift')
    return c

def environment():
    packages=('torch','numpy','psutil','Markdown') if 'torch' in sys.modules or 'ppo-m67' in sys.executable else ('numpy','psutil','Markdown')
    return {'python':sys.version,'executable':str(Path(sys.executable).resolve()),
            'packages':{k:importlib.metadata.version(k) for k in packages},'affinity':sorted(os.sched_getaffinity(0))}

def pin_files():
    paths=list((ROOT/'training/prism_portable').rglob('*.py'))+list((ROOT/'scripts').rglob('*.py'))+list((ROOT/'scripts/templates').glob('*'))+list((ROOT/'benchmarks').glob('*.json'))
    paths += list((ROOT/'inputs').glob('*'))+list((ROOT/'bin').glob('*'))
    return {p.relative_to(ROOT).as_posix():digest(p) for p in sorted(paths) if p.is_file()}

def verify(training=True):
    c=contract();p=read(ROOT/'execution.json')
    if p['config_sha256']!=digest(ROOT/CONFIG):raise ValueError('config pin drift')
    if digest(ROOT/'host.json')!=p['host_sha256']:raise ValueError('host binding drift')
    for path,h in p['files'].items():
        if digest(ROOT/path)!=h:raise ValueError('execution source/input drift: '+path)
    env=environment();expected=p['training_environment'] if training else p['arena_environment']
    if env!=expected:raise ValueError('execution environment drift')
    return c,p

def bounds():
    c=contract();b=read(ROOT/'round-budget.json')
    if b['config_sha256']!=digest(ROOT/CONFIG):raise ValueError('round budget binding changed')
    left=b['deadline']-time.time()
    if left<=0:raise ValueError('original finite round deadline exhausted')
    return left

def preflight():
    c=contract()
    if (ROOT/'execution.json').exists():raise ValueError('execution already pinned')
    import shutil, psutil
    if shutil.disk_usage(ROOT).free < c['resources']['minimum_free_bytes']:
        raise ValueError('insufficient whole-round storage reservation')
    for proc in psutil.process_iter(['pid','cmdline']):
        command=' '.join(proc.info['cmdline'] or [])
        if proc.pid != os.getpid() and ('agent-prism' in command or '/splendor run-match' in command or 'prism_m67_run.py pipeline' in command):
            raise ValueError('another research process remains active')
    env=environment()
    for k,v in c['runtime']['training_environment'].items():
        if k!='cpu_threads' and env['packages'].get(k)!=v:raise ValueError('training dependency mismatch: '+k)
    if env['affinity']!=[0,1,2,3]:raise ValueError('DSW allocation changed')
    from training.prism_portable.provision import provision
    host,parity=provision(ROOT,ROOT,ROOT/'bin/splendor',ROOT/'bin/s4_batch_metrics',ROOT/'inputs/parent.json',ROOT/'inputs/initial.json',ROOT/'inputs/fixtures.jsonl','dsw-m75')
    for k,v in c['assets'].items():
        path=ROOT/'inputs'/(k+('.jsonl' if k=='fixtures' else '.json'))
        if digest(path)!=v['sha256']:raise ValueError('fixed input changed')
        host['assets'][k]={'path':str(path),'sha256':digest(path)}
    write(ROOT/'host.json',host)
    from training.prism_portable.protocol import bind
    for a in ARMS.values():bind(read(ROOT/a['blueprint']),host)
    command=[c['runtime']['arena_python'],'-B',str(Path(__file__).resolve()),'environment']
    ar=subprocess.run(command,capture_output=True,text=True,timeout=30,check=True)
    arena_env=json.loads(ar.stdout)
    if arena_env['packages']!=c['runtime']['arena_environment']:raise ValueError('arena dependencies changed')
    p={'format':'m75-execution-v1','status':'VERIFIED_ZERO_GAMES','config_sha256':digest(ROOT/CONFIG),
       'files':pin_files(),'host_sha256':digest(ROOT/'host.json'),'training_environment':env,'arena_environment':arena_env,
       'parity':parity,'created_at':time.time(),'storage_adapter':'M75 gzip at rest; original raw object SHA; original commits/HEAD',
       'source_numeric_identity':numerical_identity(),'new_games':0}
    write(ROOT/'execution.json',p)
    return {'status':p['status'],'parity':parity,'execution_sha256':digest(ROOT/'execution.json')}

def worker(arm):
    c,_=verify();process_install()
    from scripts.prism_m67_storage import install
    install()
    from training.prism_portable.protocol import create
    from training.prism_portable.worker import execute
    from training.prism_portable.engine.ppo.arena import Campaign
    engineering=False;bp=read(ROOT/ARMS[arm]['blueprint'])
    camp=ROOT/'campaigns'/arm;host=read(ROOT/'host.json');host['_path']=str(ROOT/'host.json')
    owner=create(camp,bp,host,'m75-'+arm)
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.export import load_weights
    from training.prism_portable.engine.ppo.store import json_bytes
    import torch,hashlib,gc
    initial=Run.open(camp/'run');parent=load_weights(ROOT/'inputs/parent.json',expected_catalog_fingerprint=initial.config['catalog_fingerprint'])
    if initial.state['optimizer']['state'] or initial.state['attempts']!=0 or initial.state['cycle']!=0:raise ValueError('optimizer not fresh')
    if any(not torch.equal(t,initial.state['model']['policy.'+k]) for k,t in parent.state_dict().items()):raise ValueError('initial tensors differ from parent')
    rng_sha=hashlib.sha256(bytes(initial.state['rng']['torch'].tolist())).hexdigest()
    write(camp/'initialization-verification.json',{'status':'PASS','exact_parent_tensors':32,'optimizer_slots':0,'run_seed':bp['template']['run']['seed'],'torch_rng_sha256':rng_sha,'parent_sha256':digest(ROOT/'inputs/parent.json')})
    if not engineering:
        for other in ARMS:
            previous=ROOT/'campaigns'/other/'initialization-verification.json'
            if other!=arm and previous.exists() and rng_sha==read(previous)['torch_rng_sha256']:raise ValueError('independent RNG states identical')
    del initial,parent;gc.collect()
    os.environ.update(PRISM_PPO_HOST_ID=host['host_id'],PRISM_PPO_OWNER_NONCE=owner['nonce'],PRISM_PPO_CONTROL_DIR=str(camp/'control'),
                      OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    original=Campaign.launch
    def tracked(self,*args,**kwargs):
        result=original(self,*args,**kwargs);s=self.run.state
        write(camp/'control/live-progress.json',{'observed_at':time.time(),'cycle':s['cycle'],'phase':s['phase'],
              'completed_games':sum(a['status']=='COMPLETE' for a in self._load()[1]['attempts'].values()),
              'attempts':s['attempts'],'global_step':s['global_step'],'update_attempts':s['update_attempts']})
        return result
    Campaign.launch=tracked
    cycles=20;games=5120
    execute(camp,host,owner['nonce'],cycles)
    s=read(camp/'control/progress.json')
    if (s['phase'],s['attempts'],s['cycle'])!=('COMMITTED',games,cycles):raise ValueError('incomplete final committed training')
    export=camp/f'cycle-{cycles}-export/weights.json'
    write(camp/'worker-completion.json',{'status':'STOPPED_COMMITTED','games':games,'cycle':cycles,
          'global_step':s['global_step'],'update_attempts':s['update_attempts'],'weights':str(export),
          'weights_sha256':digest(export),'execution_sha256':digest(ROOT/'execution.json')})

def train(arm):
    c,_=verify();control=ROOT/'control'/arm;control.mkdir(parents=True,exist_ok=True)
    with (control/'once-only.lock').open('x'):pass
    import psutil
    me=psutil.Process();engineering=arm=='engineering';limits=c['engineering'] if engineering else c['training']
    state={'state':'RUNNING','phase':'TRAINING_'+arm,'pid':me.pid,'create_time':me.create_time(),'started_at':time.time(),
           'completed_games':0,'total_games':5120,'execution_sha256':digest(ROOT/'execution.json')}
    def publish(counters):
        state.update(resources=counters,observed_at=time.time(),elapsed_seconds=time.time()-state['started_at'])
        for name in ('live-progress.json','progress.json'):
            p=ROOT/'campaigns'/arm/'control'/name
            if p.exists():
                progress=read(p)
                if name=='live-progress.json':state.update(progress)
                else:state.update(committed_cycle=progress['cycle'],global_step=progress['global_step'])
        write(control/'status.json',state)
    publish({})
    try:
        wall=min(limits['wall_seconds'],bounds());os.environ.update(PRISM_PPO_CONTROL_DIR=str(control),PRISM_DSW_REMAINING_WALL=str(wall),
            OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
        with (control/'stdout.log').open('wb') as out,(control/'stderr.log').open('wb') as err:
            with ProcessTree(cpu_seconds=limits['cpu_seconds'],memory_bytes=8*1024**3,max_processes=32) as tree:
                tree.start([sys.executable,'-B',str(Path(__file__).resolve()),'worker','--arm',arm],cwd=ROOT,stdout=out,stderr=err)
                resources=tree.wait(wall_seconds=wall,storage_root=ROOT/'campaigns'/arm,max_storage_bytes=c['training']['storage_bytes'],snapshot=publish)
        if resources['returncode'] or resources['stop_reason']:raise ValueError('training failed: '+str(resources))
        result=read(ROOT/'campaigns'/arm/'worker-completion.json')
        if result['games']!=state['total_games']:raise ValueError('completion count mismatch')
        state.update(state='STOPPED_COMMITTED',phase='AWAITING_AUDIT',completed_games=result['games'],completion=result,resources=resources,finished_at=time.time())
        write(control/'completion.json',state);write(control/'status.json',state)
        return state
    except BaseException as error:
        state.update(state='FAILED_STOPPED_NO_RETRY',error=repr(error),finished_at=time.time());write(control/'status.json',state);raise

def pipeline():
    c,_=verify();root=ROOT/'pipeline';root.mkdir(exist_ok=True)
    with (root/'once-only.lock').open('x'):pass
    import psutil
    me=psutil.Process();s={'state':'RUNNING','phase':'ENGINEERING','pid':me.pid,'create_time':me.create_time(),'started_at':time.time(),
        'total_training_games':5120,'total_evaluation_games':9216,'execution_sha256':digest(ROOT/'execution.json'),'consumed_cpu_seconds':c.get('execution_predecessor',{}).get('consumed_cpu_seconds',0.)}
    def publish(**fields):s.update(fields,observed_at=time.time());write(root/'status.json',s)
    phases=[]
    phases += [(mode,arm) for arm in ARMS for mode in ('train','audit')]
    phases += [('candidates',None),('curve',None),('evaluate',None),('report',None)]
    try:
        for mode,arm in phases:
            verify();remaining=bounds();publish(phase=mode.upper()+('_'+arm if arm else ''))
            py=c['runtime']['arena_python'] if mode in ('bounded-engineering','curve','evaluate','report') else sys.executable
            script=ROOT/'scripts'/('prism_m75_curve.py' if mode=='curve' else 'prism_m75_audit.py' if mode=='audit' else 'prism_m75_run.py' if mode=='train' else 'prism_m75_report.py' if mode=='report' else 'prism_m75_evaluate.py')
            args=['--arm',arm] if mode=='audit' else ['train','--arm',arm] if mode=='train' else [] if mode in ('report','curve') else [mode]
            argv=[py,'-B',str(script),*args];label=mode+('-'+arm if arm else '')
            left_cpu=c['resources']['total_cpu_seconds']-s['consumed_cpu_seconds']
            if left_cpu<=0:raise ValueError('whole-round CPU exhausted')
            wall=min(remaining,c['training']['wall_seconds'] if mode=='train' else 21600)
            os.environ.update(PRISM_PPO_CONTROL_DIR=str(root),PRISM_DSW_REMAINING_WALL=str(wall),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
            with (root/(label+'.stdout.log')).open('wb') as out,(root/(label+'.stderr.log')).open('wb') as err:
                with ProcessTree(cpu_seconds=min(left_cpu,c['training']['cpu_seconds'] if mode=='train' else 100000),memory_bytes=8*1024**3,max_processes=64) as tree:
                    tree.start(argv,cwd=ROOT,stdout=out,stderr=err)
                    resources=tree.wait(wall_seconds=wall,storage_root=ROOT,max_storage_bytes=c['resources']['total_storage_bytes'],storage_interval=60,snapshot=lambda counters:publish(resources=counters))
            s['consumed_cpu_seconds']+=resources.get('cpu_seconds',resources['user_cpu_seconds']+resources['kernel_cpu_seconds'])
            write(root/(label+'.completion.json'),{'status':'PASS' if resources['returncode']==0 and not resources['stop_reason'] else 'FAIL','resources':resources,'finished_at':time.time()})
            if resources['returncode'] or resources['stop_reason']:raise ValueError('phase failed '+label+': '+str(resources))
        publish(state='COMPLETED',phase='COMPLETE_RESULTS_AND_REPORTS',finished_at=time.time());write(root/'completion.json',s)
        return s
    except BaseException as error:
        publish(state='FAILED_STOPPED_NO_RETRY',error=repr(error),finished_at=time.time());raise

def start():
    c,_=verify();root=ROOT/'pipeline';root.mkdir(exist_ok=True)
    import shutil
    if shutil.disk_usage(ROOT).free < c['resources']['minimum_free_bytes']:
        raise ValueError('capacity changed after preflight')
    with (root/'launch-once.lock').open('x'):pass
    if (ROOT/'round-budget.json').exists():raise ValueError('round already started; never reset deadline')
    prior=c.get('execution_predecessor',{})
    write(ROOT/'round-budget.json',{'started_at':prior.get('started_at',time.time()),'deadline':prior.get('deadline',time.time()+c['resources']['round_wall_seconds']),'config_sha256':digest(ROOT/CONFIG),'predecessor':prior})
    with (root/'supervisor.log').open('wb') as log:
        p=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'pipeline'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    import psutil
    result={'status':'STARTED_BOUNDED_M75','pid':p.pid,'create_time':psutil.Process(p.pid).create_time(),'execution_sha256':digest(ROOT/'execution.json'),
            'training_games':5120,'evaluation_games':9216,'deadline':read(ROOT/'round-budget.json')['deadline']}
    write(root/'launch.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('preflight','environment','worker','train','pipeline','start'));p.add_argument('--arm');a=p.parse_args()
    value=environment() if a.mode=='environment' else globals()[a.mode](a.arm) if a.mode in ('worker','train') else globals()[a.mode]()
    print(json.dumps(value,ensure_ascii=False))
