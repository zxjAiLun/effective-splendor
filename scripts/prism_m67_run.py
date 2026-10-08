"""M67 finite once-only DSW controller: preflight, train, audit, greedy, report.

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
from scripts.prism_m67_prepare import CONFIG,ARMS,blueprint,validate
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
    env=environment()
    for k,v in c['runtime']['training_environment'].items():
        if k!='cpu_threads' and env['packages'].get(k)!=v:raise ValueError('training dependency mismatch: '+k)
    if env['affinity']!=[0,1,2,3]:raise ValueError('DSW allocation changed')
    from training.prism_portable.provision import provision
    host,parity=provision(ROOT,ROOT,ROOT/'bin/splendor',ROOT/'bin/s4_batch_metrics',ROOT/'inputs/parent.json',ROOT/'inputs/initial.json',ROOT/'inputs/fixtures.jsonl','dsw-m67')
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
    p={'format':'m67-execution-v1','status':'VERIFIED_ZERO_GAMES','config_sha256':digest(ROOT/CONFIG),
       'files':pin_files(),'host_sha256':digest(ROOT/'host.json'),'training_environment':env,'arena_environment':arena_env,
       'parity':parity,'created_at':time.time(),'storage_adapter':'M67 gzip at rest; original raw object SHA; original commits/HEAD',
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
    engineering=arm=='engineering';bp=blueprint(read(ROOT/'benchmarks/m63-prism-control-building.train.json'),{k:v['sha256'] for k,v in c['assets'].items()},engineering=True) if engineering else read(ROOT/ARMS[arm]['blueprint'])
    camp=ROOT/'campaigns'/arm;host=read(ROOT/'host.json');host['_path']=str(ROOT/'host.json')
    owner=create(camp,bp,host,'m67-'+arm)
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.export import load_weights
    from training.prism_portable.engine.ppo.store import json_bytes
    import torch,hashlib,gc
    initial=Run.open(camp/'run');parent=load_weights(ROOT/'inputs/parent.json',expected_catalog_fingerprint=initial.config['catalog_fingerprint'])
    if initial.state['optimizer']['state'] or initial.state['attempts']!=0 or initial.state['cycle']!=0:raise ValueError('optimizer not fresh')
    if any(not torch.equal(t,initial.state['model']['policy.'+k]) for k,t in parent.state_dict().items()):raise ValueError('initial tensors differ from parent')
    rng_sha=hashlib.sha256(bytes(initial.state['rng']['torch'].tolist())).hexdigest()
    write(camp/'initialization-verification.json',{'status':'PASS','exact_parent_tensors':32,'optimizer_slots':0,'run_seed':bp['template']['run']['seed'],'torch_rng_sha256':rng_sha,'parent_sha256':digest(ROOT/'inputs/parent.json')})
    if arm=='b' and rng_sha==read(ROOT/'campaigns/a/initialization-verification.json')['torch_rng_sha256']:raise ValueError('independent RNG states identical')
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
    cycles=1 if engineering else 20;games=8 if engineering else 5120
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
           'completed_games':0,'total_games':8 if engineering else 5120,'execution_sha256':digest(ROOT/'execution.json')}
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
                resources=tree.wait(wall_seconds=wall,storage_root=ROOT/'campaigns'/arm,max_storage_bytes=(4 if engineering else 16)*1024**3,snapshot=publish)
        if resources['returncode'] or resources['stop_reason']:raise ValueError('training failed: '+str(resources))
        result=read(ROOT/'campaigns'/arm/'worker-completion.json')
        if result['games']!=state['total_games']:raise ValueError('completion count mismatch')
        state.update(state='STOPPED_COMMITTED',phase='AWAITING_AUDIT',completed_games=result['games'],completion=result,resources=resources,finished_at=time.time())
        write(control/'completion.json',state);write(control/'status.json',state)
        return state
    except BaseException as error:
        state.update(state='FAILED_STOPPED_NO_RETRY',error=repr(error),finished_at=time.time());write(control/'status.json',state);raise

def arena_stage(arm):
    c,_=verify(False);e=c['evaluation'];from_scripts=__import__('scripts.prism_notebook_arena',fromlist=['prepare']);arena=from_scripts
    engine=ROOT/'bin/splendor';names=c['names'];reference=arm=='reference';direct=arm.endswith('-direct')
    if reference:model_id='base';weights=ROOT/'inputs/parent.json';name=names['parent']
    else:
        key=arm.split('-')[0];model_id='candidate-'+key;weights=ROOT/'campaigns'/key/'cycle-20-export/weights.json';name=names[model_id]
        audited=read(ROOT/'audits'/key/'audit.json')
        if audited['status']!='PASS_TRAINING_ARTIFACT_AUDIT' or digest(weights)!=audited['weights_sha256']:raise ValueError('c20 audit mismatch')
    candidates={model_id:arena.model(weights,name,engine,mode='greedy',action_seed=e['action_seed'])}
    keys=['parent'] if direct else e['common_opponents']
    opponents={k:(arena.heuristic(engine,names[k],e['action_seed']) if k=='heuristic' else arena.model(ROOT/f'inputs/{k}.json',names[k],engine,mode='greedy',action_seed=e['action_seed'])) for k in keys}
    start=e['direct_seed_start' if direct else 'common_seed_start'];end=e['direct_seed_end' if direct else 'common_seed_end'];work=ROOT/'evaluation'/arm
    plan=arena.prepare(work,engine,ROOT/'bin/s4_batch_metrics',candidates,opponents,list(range(start,end+1)),workers=4,
        action_seed=e['action_seed'],shard_seed_blocks=32,memory_gib=8,wall_hours=min(e['wall_seconds_per_arena'],bounds()-10)/3600,
        cpu_hours=e['cpu_seconds_per_arena']/3600,storage_gib=8)
    if plan['total_games']!=(10000 if direct else 30000):raise ValueError('arena grid count mismatch')
    arena.verify(work);owner=arena.start(work)
    while True:
        bounds();s=arena.status(work)
        if s['state']=='COMPLETED_DEVELOPMENT_ONLY':return {'games':s['completed_games'],'work':str(work)}
        if s['state'].startswith('FAILED') or not arena.alive(owner):raise ValueError('arena failed/stopped; no retry')
        time.sleep(1)

def pipeline():
    c,_=verify();root=ROOT/'pipeline';root.mkdir(exist_ok=True)
    with (root/'once-only.lock').open('x'):pass
    import psutil
    me=psutil.Process();s={'state':'RUNNING','phase':'ENGINEERING','pid':me.pid,'create_time':me.create_time(),'started_at':time.time(),
        'total_training_games':10240,'total_evaluation_games':110000,'execution_sha256':digest(ROOT/'execution.json')}
    def publish(**fields):s.update(fields,observed_at=time.time());write(root/'status.json',s)
    phases=[('train','engineering'),('audit','engineering'),('train','a'),('audit','a'),('train','b'),('audit','b'),
            ('arena','reference'),('arena','a-common'),('arena','a-direct'),('arena','b-common'),('arena','b-direct'),('report',None)]
    try:
        for mode,arm in phases:
            verify();remaining=bounds();publish(phase=mode.upper()+('_'+arm if arm else ''))
            py=c['runtime']['arena_python'] if mode=='arena' else sys.executable
            script=ROOT/'scripts'/('prism_m67_report.py' if mode=='report' else 'prism_m67_audit.py' if mode=='audit' else 'prism_m67_run.py')
            argv=[py,'-B',str(script)]+([] if mode=='report' else ['--arm',arm] if mode=='audit' else [mode,'--arm',arm])
            label=mode+('-'+arm if arm else '')
            wall=min(remaining,25200 if mode=='train' else 18000)
            cpu=100000 if mode=='train' else 72000
            os.environ.update(PRISM_PPO_CONTROL_DIR=str(root),PRISM_DSW_REMAINING_WALL=str(wall),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
            with (root/(label+'.stdout.log')).open('wb') as out,(root/(label+'.stderr.log')).open('wb') as err:
                with ProcessTree(cpu_seconds=cpu,memory_bytes=8*1024**3,max_processes=48) as tree:
                    tree.start(argv,cwd=ROOT,stdout=out,stderr=err)
                    resources=tree.wait(wall_seconds=wall,storage_root=ROOT,max_storage_bytes=c['resources']['total_storage_bytes'],
                        storage_interval=60,snapshot=lambda counters:publish(resources=counters))
            if resources['returncode'] or resources['stop_reason']:raise ValueError('phase failed '+label+': '+str(resources))
            write(root/(label+'.completion.json'),{'status':'PASS','resources':resources,'finished_at':time.time()})
        publish(state='COMPLETED',phase='COMPLETE_RESULTS_AND_REPORTS',finished_at=time.time());write(root/'completion.json',s)
        return s
    except BaseException as error:
        publish(state='FAILED_STOPPED_NO_RETRY',error=repr(error),finished_at=time.time());raise

def start():
    c,_=verify();root=ROOT/'pipeline';root.mkdir(exist_ok=True)
    with (root/'launch-once.lock').open('x'):pass
    if (ROOT/'round-budget.json').exists():raise ValueError('round already started; never reset deadline')
    write(ROOT/'round-budget.json',{'started_at':time.time(),'deadline':time.time()+c['resources']['round_wall_seconds'],'config_sha256':digest(ROOT/CONFIG)})
    with (root/'supervisor.log').open('wb') as log:
        p=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'pipeline'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    import psutil
    result={'status':'STARTED_BOUNDED_M67','pid':p.pid,'create_time':psutil.Process(p.pid).create_time(),'execution_sha256':digest(ROOT/'execution.json'),
            'training_games':10240,'evaluation_games':110000,'deadline':read(ROOT/'round-budget.json')['deadline']}
    write(root/'launch.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('preflight','environment','worker','train','arena','pipeline','start'));p.add_argument('--arm');a=p.parse_args()
    value=environment() if a.mode=='environment' else globals()[a.mode](a.arm) if a.mode in ('worker','train') else arena_stage(a.arm) if a.mode=='arena' else globals()[a.mode]()
    print(json.dumps(value,ensure_ascii=False))
