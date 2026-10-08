"""Explicitly owner-authorized same-host M67 continuation R1; no automatic retry.

Original failed pipeline/source/config/budget remain intact. Resume A's exact
model/optimizer/RNG/progress and completed ledger; create B once with original
seed. Resource-only wall admission override is pinned, never changes PPO state.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest
from scripts import prism_m67_run as original
from scripts.prism_dsw_ppo_process import ProcessTree,install as process_install
R1=ROOT/'continuation-r1'
POLICY=R1/'policy.json'


def validate_collecting(spec,state,ledger):
    from training.prism_portable.protocol import validate_launch_ledger
    if state['phase']!='COLLECTING' or state['paused']:raise ValueError('expected unpaused collecting state')
    if len(state['consumed'])!=state['cycle']-1:raise ValueError('consumed cycle mismatch')
    if any(a['status']!='COMPLETE' for a in ledger['attempts'].values()):raise ValueError('unfinished physical attempt; no replay')
    prior={j['job_id'] for group in spec['cycles'][:state['cycle']-1] for j in group}
    schedule={j['job_id'] for j in spec['cycles'][state['cycle']-1]}
    current={k for k,v in state['jobs'].items() if v['status']=='COMPLETE'}
    if len(current)!=len(state['jobs']) or not current<=schedule:raise ValueError('uncommitted job')
    completed={a['job']['job_id'] for a in ledger['attempts'].values()}
    if completed!=prior|current or set(state['all_jobs'])!=prior|schedule:raise ValueError('completed/scheduled cohort mismatch')
    checked=copy.copy(state);checked['all_jobs']=sorted(completed)
    validate_launch_ledger(ledger,checked,spec)
    if ledger['retries']!=0:raise ValueError('retry budget unchanged')


def remaining():
    p=read(POLICY)
    if digest(__file__)!=p['adapter_sha256']:raise ValueError('continuation adapter drift')
    budget=read(R1/'budget.json')
    if budget['policy_sha256']!=digest(POLICY):raise ValueError('continuation policy drift')
    if digest(ROOT/'execution.json')!=p['original_execution_sha256']:raise ValueError('original execution drift')
    left=budget['deadline']-time.time()
    if left<=0:raise ValueError('continuation deadline exhausted')
    return left


def install_bounds():
    original.bounds=remaining
    process_install()
    from scripts.prism_m67_storage import install
    install()


def guard_wall(state,deadline):
    if state['paused'] or state['phase']=='FAILED':raise ValueError('run paused/failed')
    if time.time()>=deadline:raise ValueError('explicit continuation wall budget exhausted')


def install_admission():
    from training.prism_portable.engine.ppo.coordinator import Run
    deadline=read(R1/'budget.json')['deadline']
    def admit(self):guard_wall(self.state,deadline)
    Run._admit=admit


def verify_resume(campaign,policy):
    from training.prism_portable.protocol import assert_owner,state_fingerprints,state_digest
    from training.prism_portable.engine.ppo.runtime import capture_rng
    owner=read(campaign.root/'ownership.json')
    assert_owner(campaign.root,read(ROOT/'host.json')['host_id'],owner['nonce'])
    head,ledger=campaign._load();s=campaign.run.state;expected=policy['resume_state']
    validate_collecting(campaign.spec,s,ledger)
    actual={'run_commit':campaign.run.parent,'ledger_commit':head,'state':state_fingerprints(s),'ledger_state_sha256':state_digest(ledger)}
    if any(actual[k]!=expected[k] for k in actual):raise ValueError('exact resume identity drift')
    if state_digest(capture_rng())!=actual['state']['rng']:raise ValueError('RNG restoration mismatch')
    return dict(status='PASS_EXACT_FULL_STATE_SAME_HOST_RESUME',**actual,completed_games=len(ledger['attempts']),new_games=0,new_updates=0)


def worker(arm):
    original.verify();install_bounds();install_admission()
    if arm=='b':return original.worker('b')
    from training.prism_portable.engine.ppo.arena import Campaign
    from training.prism_portable.worker import execute
    camp=ROOT/'campaigns/a';host=read(ROOT/'host.json');host['_path']=str(ROOT/'host.json')
    campaign=Campaign(camp,read(camp/'contract.json'));proof=verify_resume(campaign,read(POLICY))
    write(R1/'a-resume-verification.json',proof)
    owner=read(camp/'ownership.json')
    import gc
    del campaign;gc.collect()
    os.environ.update(PRISM_PPO_HOST_ID=host['host_id'],PRISM_PPO_OWNER_NONCE=owner['nonce'],PRISM_PPO_CONTROL_DIR=str(R1/'train-a'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    track_launch(Campaign,camp)
    # execute's target is capped at the frozen 20 cycles; finishes partial c16 first.
    execute(camp,host,owner['nonce'],20)
    s=read(camp/'control/progress.json')
    if (s['phase'],s['attempts'],s['cycle'])!=('COMMITTED',5120,20):raise ValueError('final A incomplete')
    export=camp/'cycle-20-export/weights.json'
    write(camp/'worker-completion.json',{'status':'STOPPED_COMMITTED','games':5120,'cycle':20,'global_step':s['global_step'],'update_attempts':s['update_attempts'],'weights':str(export),'weights_sha256':digest(export),'execution_sha256':digest(ROOT/'execution.json'),'continuation_policy_sha256':digest(POLICY)})


def track_launch(Campaign,camp):
    previous=Campaign.launch
    def tracked(self,*args,**kwargs):
        result=previous(self,*args,**kwargs);s=self.run.state
        write(camp/'control/live-progress.json',{'observed_at':time.time(),'cycle':s['cycle'],'phase':s['phase'],'completed_games':sum(a['status']=='COMPLETE' for a in self._load()[1]['attempts'].values()),'attempts':s['attempts'],'global_step':s['global_step'],'update_attempts':s['update_attempts']})
        return result
    Campaign.launch=tracked


def child(mode,arm):
    install_bounds();remaining()
    if mode=='train':return worker(arm)
    if mode=='audit':
        from scripts.prism_m67_audit import audit
        result=audit(arm)
        result['continuation']={'policy_path':POLICY.relative_to(ROOT).as_posix(),'policy_sha256':digest(POLICY),'adapter_sha256':digest(__file__),'resource_wall_override':True,'original_failed_pipeline_retained':True,'resume_verification':read(R1/'a-resume-verification.json') if arm=='a' else None}
        write(ROOT/f'audits/{arm}/audit.json',result);return result
    if mode=='arena':return original.arena_stage(arm)
    from scripts.prism_m67_report import build
    return build()


def stage(mode,arm):
    p=read(POLICY);label=mode+('-'+arm if arm else '');out=R1/label;out.mkdir(exist_ok=False)
    wall=min(remaining(),p['training_wall_seconds'][arm] if mode=='train' else 18000)
    cpu=p['training_cpu_seconds'][arm] if mode=='train' else 72000
    py=original.contract()['runtime']['arena_python'] if mode=='arena' else sys.executable
    os.environ.update(PRISM_PPO_CONTROL_DIR=str(out),PRISM_DSW_REMAINING_WALL=str(wall),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    with (out/'stdout.log').open('wb') as stdout,(out/'stderr.log').open('wb') as stderr:
        with ProcessTree(cpu_seconds=cpu,memory_bytes=8*1024**3,max_processes=48) as tree:
            tree.start([py,'-B',str(Path(__file__).resolve()),'child','--stage',mode]+(['--arm',arm] if arm else []),cwd=ROOT,stdout=stdout,stderr=stderr)
            def snapshot(resources):
                row={'state':'RUNNING','phase':label,'resources':resources,'observed_at':time.time()}
                if mode=='train':
                    for name in ['progress.json','live-progress.json']:
                        path=ROOT/f'campaigns/{arm}/control/{name}'
                        if path.exists():row.update(read(path))
                write(out/'status.json',row)
            resources=tree.wait(wall_seconds=wall,storage_root=ROOT/f'campaigns/{arm}' if mode=='train' else ROOT,max_storage_bytes=(16 if mode=='train' else 60)*1024**3,storage_interval=60,snapshot=snapshot)
    done={'state':'PASS' if not resources['returncode'] and not resources['stop_reason'] else 'FAILED_STOPPED_NO_RETRY','resources':resources,'finished_at':time.time()}
    write(out/'completion.json',done)
    if done['state']!='PASS':raise ValueError('continuation stage failed '+label+': '+str(resources))
    if mode=='train':
        (ROOT/f'control/{arm}').mkdir(parents=True,exist_ok=True)
        completion=read(ROOT/f'campaigns/{arm}/worker-completion.json')
        terminal={'state':'STOPPED_COMMITTED','phase':'AWAITING_AUDIT','completed_games':5120,'completion':completion,'resources':resources,'finished_at':time.time(),'continuation_policy_sha256':digest(POLICY)}
        write(ROOT/f'control/{arm}/completion.json',terminal)
    return done


def pipeline():
    import psutil
    original.verify();install_bounds()
    with (R1/'pipeline-once.lock').open('x'):pass
    me=psutil.Process();s={'state':'RUNNING','phase':'RESUME_A','pid':me.pid,'create_time':me.create_time(),'started_at':time.time(),'policy_sha256':digest(POLICY),'execution_sha256':digest(ROOT/'execution.json')}
    def publish(**fields):s.update(fields,observed_at=time.time());write(R1/'status.json',s)
    phases=[('train','a'),('audit','a'),('train','b'),('audit','b'),('arena','reference'),('arena','a-common'),('arena','a-direct'),('arena','b-common'),('arena','b-direct'),('report',None)]
    try:
        for mode,arm in phases:
            original.verify();remaining();publish(phase=mode+('-'+arm if arm else ''));stage(mode,arm)
        publish(state='COMPLETED',phase='COMPLETE_RESULTS_AND_REPORTS',finished_at=time.time());write(R1/'completion.json',s)
    except BaseException as error:
        publish(state='FAILED_STOPPED_NO_RETRY',error=repr(error),finished_at=time.time());raise


def start():
    original.verify();remaining()
    with (R1/'launch-once.lock').open('x'):pass
    with (R1/'supervisor.log').open('xb') as log:
        proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'pipeline'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    import psutil
    receipt={'status':'STARTED_EXPLICIT_CONTINUATION_R1','pid':proc.pid,'create_time':psutil.Process(proc.pid).create_time(),'execution_sha256':digest(ROOT/'execution.json'),'policy_sha256':digest(POLICY),'deadline':read(R1/'budget.json')['deadline']}
    write(R1/'launch.json',receipt);return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['start','pipeline','child']);parser.add_argument('--stage',choices=['train','audit','arena','report']);parser.add_argument('--arm');args=parser.parse_args()
    result=child(args.stage,args.arm) if args.mode=='child' else globals()[args.mode]()
    if result is not None:print(json.dumps(result,ensure_ascii=False))
