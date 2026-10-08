"""Owner-authorized M67 storage revision; retain R1 bytes and absolute deadline.

Resource adapters preserve native contracts and all science state. Launch storage
reservation is algebraically translated to the explicit revised cap; process and
checkpoint writes enforce actual bytes. No physical attempt is replayed.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest
from scripts import prism_m67_resume as prior
from scripts.prism_dsw_ppo_process import ProcessTree
R2=ROOT/'continuation-r2'
POLICY=R2/'policy.json'


def remaining():
    p=read(POLICY);budget=read(R2/'budget.json');capacity=read(R2/'capacity-revision.json')
    capacity_budget=read(R2/'capacity-budget.json')
    if capacity_budget['capacity_sha256']!=digest(R2/'capacity-revision.json') or capacity_budget['deadline']!=budget['deadline']:raise ValueError('capacity budget drift')
    if digest(__file__)!=capacity['adapter_sha256'] or digest(POLICY)!=capacity['base_policy_sha256']:raise ValueError('capacity revision drift')
    if digest(R2/'pre-capacity-adapter.py')!=p['adapter_sha256']:raise ValueError('pre-capacity source drift')
    for path,key in [(ROOT/'scripts/prism_m67_resume.py','r1_adapter_sha256'),(ROOT/'continuation-r1/policy.json','r1_policy_sha256'),(ROOT/'execution.json','original_execution_sha256')]:
        if digest(path)!=p[key]:raise ValueError('continuation source/strategy drift: '+str(path))
    if budget['policy_sha256']!=digest(POLICY):raise ValueError('R2 policy drift')
    if budget['deadline']!=read(ROOT/'continuation-r1/budget.json')['deadline']:raise ValueError('absolute deadline changed')
    left=budget['deadline']-time.time()
    if left<=0:raise ValueError('continuation deadline exhausted')
    return left


def resource_policy():
    p=read(POLICY);capacity=read(R2/'capacity-revision.json')
    p['storage_total_bytes']=capacity['storage_total_bytes']
    return p


def reservation_bytes(actual,old_cap,new_cap):
    if new_cap<old_cap:raise ValueError('revision must increase storage cap')
    return max(0,actual-(new_cap-old_cap))


def install_storage_limits():
    from training.prism_portable.engine.ppo import arena
    from training.prism_portable.engine.ppo.coordinator import Run
    cap=read(POLICY)['storage_per_training_bytes']
    if getattr(arena,'_m67_r2_storage',False):return
    actual_bytes=arena.directory_bytes
    def admission_bytes(path):
        actual=actual_bytes(path)
        if Path(path).resolve() in [(ROOT/'campaigns'/arm).resolve() for arm in ['a','b']]:
            old=read(Path(path)/'contract.json')['run']['budget']['max_storage_bytes']
            return reservation_bytes(actual,old,cap)
        return actual
    arena.directory_bytes=admission_bytes
    native_open=Run.open.__func__
    def opened(cls,*args,**kwargs):
        run=native_open(cls,*args,**kwargs)
        if run.store.root.resolve() in [(ROOT/'campaigns'/a/'run').resolve() for a in ['a','b']]:run.store.max_bytes=cap
        return run
    Run.open=classmethod(opened)
    class RevisedTree(ProcessTree):
        def wait(self,**kwargs):
            path=kwargs.get('storage_root')
            if path is not None and Path(path).resolve() in [(ROOT/'campaigns'/a).resolve() for a in ['a','b']]:kwargs['max_storage_bytes']=cap
            return super().wait(**kwargs)
    arena.ProcessTree=RevisedTree
    arena._m67_r2_storage=True


def install_bounds():
    prior.original.bounds=remaining
    from scripts.prism_dsw_ppo_process import install
    from training.prism_portable.engine.ppo import arena
    if not getattr(arena,'_m67_r2_storage',False):install()
    from scripts.prism_m67_storage import install
    install()
    install_storage_limits()


def recovery_view(spec,state,ledger):
    import copy
    s,l=copy.deepcopy(state),copy.deepcopy(ledger)
    expected={'job_id':'m67-m67-repeat-a-c16-b83-s1','event':'fatal','error_type':'ValueError'}
    if not s['paused'] or not l['failed'] or l['recoveries']!=[expected]:raise ValueError('unrecognized failure')
    if expected['job_id'] in {a['job']['job_id'] for a in l['attempts'].values()}:raise ValueError('failed job was launched')
    s['paused']=False;l['failed']=False
    prior.validate_collecting(spec,s,l)
    return s,l


def recover():
    import copy
    configure();prior.original.verify();remaining();install_bounds()
    if (R2/'recovery.json').exists():raise ValueError('recovery already performed')
    from training.prism_portable.engine.ppo.arena import Campaign
    from training.prism_portable.protocol import state_fingerprints,state_digest
    campaign=Campaign(ROOT/'campaigns/a',read(ROOT/'campaigns/a/contract.json'));head,ledger=campaign._load();s=campaign.run.state
    p=read(POLICY);expected=p['failed_state']
    actual={'run_commit':campaign.run.parent,'ledger_commit':head,'state':state_fingerprints(s),'ledger_state_sha256':state_digest(ledger)}
    if actual!=expected:raise ValueError('failed-state identity drift')
    recovery_view(campaign.spec,s,ledger)
    with campaign.ledger.lock():
        fixed=copy.deepcopy(ledger);fixed['failed']=False
        fixed['recoveries'].append({'event':'owner_authorized_storage_admission_recovery','policy_sha256':digest(POLICY),'physical_attempts_replayed':0,'previous_ledger_commit':head})
        campaign.ledger.commit(fixed,expected_parent=head)
    campaign.run.pause(False)
    campaign=Campaign(ROOT/'campaigns/a',read(ROOT/'campaigns/a/contract.json'));head,ledger=campaign._load()
    prior.validate_collecting(campaign.spec,campaign.run.state,ledger)
    after={'run_commit':campaign.run.parent,'ledger_commit':head,'state':state_fingerprints(campaign.run.state),'ledger_state_sha256':state_digest(ledger)}
    if after['state']!=actual['state']:raise ValueError('scientific state changed during recovery')
    proof={'status':'PASS_EXPLICIT_STORAGE_RECOVERY_NO_SCIENCE_CHANGE','before':actual,'resume_state':after,'new_games':0,'new_updates':0,'observed_at':time.time()}
    write(R2/'recovery.json',proof);return proof


NATIVE_VERIFY=prior.verify_resume
def verify_resume(campaign,policy):
    import copy
    selected=copy.deepcopy(policy);selected['resume_state']=read(R2/'recovery.json')['resume_state']
    return NATIVE_VERIFY(campaign,selected)


def configure():
    prior.R1=R2;prior.POLICY=POLICY
    prior.remaining=remaining;prior.install_bounds=install_bounds
    prior.original.process_install=install_bounds
    prior.verify_resume=verify_resume


def child(mode,arm):
    configure();remaining()
    if mode=='arena':
        prior.original.bounds=remaining
        return prior.original.arena_stage(arm)
    install_bounds()
    result=prior.child(mode,arm)
    if mode=='audit':
        result['continuation'].update(adapter_sha256=digest(__file__),r1_adapter_sha256=digest(prior.__file__),resource_storage_override=True)
        write(ROOT/f'audits/{arm}/audit.json',result)
    return result


def stage(mode,arm):
    p=resource_policy();label=mode+('-'+arm if arm else '');out=R2/label;out.mkdir(exist_ok=False)
    wall=min(remaining(),p['training_wall_seconds'][arm] if mode=='train' else 18000)
    cpu=p['training_cpu_seconds'][arm] if mode=='train' else 72000
    py=prior.original.contract()['runtime']['arena_python'] if mode=='arena' else sys.executable
    os.environ.update(PRISM_PPO_CONTROL_DIR=str(out),PRISM_DSW_REMAINING_WALL=str(wall),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    from training.prism_portable.processes import directory_bytes
    total=p['storage_total_bytes'];next_total=[0.];total_reason=[None]
    def check_total():
        if time.monotonic()>=next_total[0]:
            next_total[0]=time.monotonic()+60
            if directory_bytes(ROOT)>total:total_reason[0]='total_storage_deadline'
        return total_reason[0]
    with (out/'stdout.log').open('wb') as stdout,(out/'stderr.log').open('wb') as stderr:
        with ProcessTree(cpu_seconds=cpu,memory_bytes=p['memory_bytes'],max_processes=48) as tree:
            tree.start([py,'-B',str(Path(__file__).resolve()),'child','--stage',mode]+(['--arm',arm] if arm else []),cwd=ROOT,stdout=stdout,stderr=stderr)
            def snapshot(resources):
                row={'state':'RUNNING','phase':label,'resources':resources,'observed_at':time.time()}
                if mode=='train':
                    path=ROOT/f'campaigns/{arm}/control/live-progress.json'
                    if path.exists():row.update(read(path))
                write(out/'status.json',row)
            resources=tree.wait(wall_seconds=wall,storage_root=ROOT/f'campaigns/{arm}' if mode=='train' else ROOT,max_storage_bytes=p['storage_per_training_bytes'] if mode=='train' else total,storage_interval=60,stop_checker=check_total,snapshot=snapshot)
    done={'state':'PASS' if not resources['returncode'] and not resources['stop_reason'] else 'FAILED_STOPPED_NO_RETRY','resources':resources,'finished_at':time.time()}
    write(out/'completion.json',done)
    if done['state']!='PASS':raise ValueError('R2 stage failed '+label+': '+str(resources))
    if mode=='train':
        terminal={'state':'STOPPED_COMMITTED','phase':'AWAITING_AUDIT','completed_games':5120,'completion':read(ROOT/f'campaigns/{arm}/worker-completion.json'),'resources':resources,'finished_at':time.time(),'continuation_policy_sha256':digest(POLICY)}
        write(ROOT/f'control/{arm}/completion.json',terminal)
    return done


def pipeline():
    import psutil
    configure();prior.original.verify();remaining()
    with (R2/'pipeline-once.lock').open('x'):pass
    me=psutil.Process();s={'state':'RUNNING','phase':'RESUME_A','pid':me.pid,'create_time':me.create_time(),'started_at':time.time(),'policy_sha256':digest(POLICY),'execution_sha256':digest(ROOT/'execution.json')}
    def publish(**fields):s.update(fields,observed_at=time.time());write(R2/'status.json',s)
    try:
        for mode,arm in [('train','a'),('audit','a'),('train','b'),('audit','b'),('arena','reference'),('arena','a-common'),('arena','a-direct'),('arena','b-common'),('arena','b-direct'),('report',None)]:
            prior.original.verify();remaining();publish(phase=mode+('-'+arm if arm else ''));stage(mode,arm)
        publish(state='COMPLETED',phase='COMPLETE_RESULTS_AND_REPORTS',finished_at=time.time());write(R2/'completion.json',s)
    except BaseException as error:
        publish(state='FAILED_STOPPED_NO_RETRY',error=repr(error),finished_at=time.time());raise


def preflight():
    import psutil,shutil
    configure();prior.original.verify();remaining();install_bounds()
    for proc in psutil.process_iter(['pid','cmdline']):
        if proc.pid!=os.getpid() and str(ROOT) in ' '.join(proc.info['cmdline'] or []):raise ValueError('project process still active')
    from training.prism_portable.engine.ppo.arena import Campaign
    campaign=Campaign(ROOT/'campaigns/a',read(ROOT/'campaigns/a/contract.json'))
    proof=verify_resume(campaign,read(POLICY))
    from training.prism_portable.processes import directory_bytes
    p=resource_policy();size=directory_bytes(ROOT/'campaigns/a');total=directory_bytes(ROOT)
    # Require room for the remaining cohort; quadratic snapshot growth is only a planning estimate.
    projected=size*(5120/proof['completed_games'])**2
    if projected*1.05>p['storage_per_training_bytes'] or total+2*projected-size+8*1024**3>p['storage_total_bytes']:raise ValueError('insufficient planned capacity')
    if shutil.disk_usage(ROOT).free<2*projected-size+8*1024**3:raise ValueError('insufficient physical free disk')
    proof.update(actual_training_bytes=size,actual_total_bytes=total,planning_projected_training_bytes=projected,checkpoint_cap=campaign.run.store.max_bytes,remaining_wall_seconds=remaining())
    write(R2/'zero-game-resume-verification.json',proof)
    return proof


def start():
    preflight()
    with (R2/'launch-once.lock').open('x'):pass
    with (R2/'supervisor.log').open('xb') as log:
        proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'pipeline'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    import psutil
    receipt={'status':'STARTED_EXPLICIT_CONTINUATION_R2','pid':proc.pid,'create_time':psutil.Process(proc.pid).create_time(),'execution_sha256':digest(ROOT/'execution.json'),'policy_sha256':digest(POLICY),'deadline':read(R2/'budget.json')['deadline']}
    write(R2/'launch.json',receipt);return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['start','pipeline','preflight','recover','child']);parser.add_argument('--stage',choices=['train','audit','arena','report']);parser.add_argument('--arm');args=parser.parse_args()
    result=child(args.stage,args.arm) if args.mode=='child' else globals()[args.mode]()
    if result is not None:print(__import__('json').dumps(result,ensure_ascii=False))
