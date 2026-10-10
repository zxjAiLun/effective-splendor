"""Owner-authorized M73 r7 resource recovery. Original pinned files stay intact.

Resume exact A model/optimizer/RNG/partial c4, then frozen B/C and evaluation.
Keep original absolute deadline, scientific budgets, admission failure and locks.
Deploy this file as ROOT/continuation-r7/resume.py, outside the old source pins.
"""
import argparse
import copy
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest
from scripts import prism_m73_run as original
from scripts.prism_m67_resume import validate_collecting,track_launch
from scripts.prism_dsw_ppo_process import ProcessTree,install as process_install
REV=ROOT/'continuation-r7'
POLICY=REV/'policy.json'


def reservation_bytes(actual,old_cap,new_cap):
    if new_cap<old_cap:raise ValueError('storage revision must increase cap')
    return max(0,actual-(new_cap-old_cap))


def recovery_view(spec,state,ledger,expected_job):
    s,l=copy.deepcopy(state),copy.deepcopy(ledger)
    expected={'job_id':expected_job,'event':'fatal','error_type':'ValueError'}
    if s['phase']!='COLLECTING' or not s['paused'] or not l['failed'] or l['recoveries']!=[expected]:
        raise ValueError('unrecognized storage admission failure')
    if expected_job in {a['job']['job_id'] for a in l['attempts'].values()}:
        raise ValueError('admission-failed job already attempted')
    if expected_job not in {j['job_id'] for j in spec['cycles'][s['cycle']-1]}:
        raise ValueError('admission-failed job outside current schedule')
    s['paused']=False;l['failed']=False
    validate_collecting(spec,s,l)
    return s,l


def policy():
    p=read(POLICY)
    if digest(__file__)!=p['adapter_sha256']:raise ValueError('recovery source drift')
    if digest(ROOT/'execution.json')!=p['original_execution_sha256']:raise ValueError('original source binding drift')
    if digest(ROOT/'round-budget.json')!=p['original_budget_sha256']:raise ValueError('original round budget drift')
    if p['deadline']!=read(ROOT/'round-budget.json')['deadline']:raise ValueError('absolute deadline changed')
    for name,sha in p.get('predecessor_control_recovery_files',{}).items():
        if digest(ROOT/name)!=sha:raise ValueError('predecessor recovery evidence drift')
    for name,sha in p.get('pending_saved_terminal_files',{}).items():
        if digest(ROOT/name)!=sha:raise ValueError('saved terminal raw data drift')
    return p


def remaining():
    left=policy()['deadline']-time.time()
    if left<=0:raise ValueError('original absolute deadline exhausted')
    return left


def install():
    from scripts.prism_m67_storage import install as storage_install
    storage_install()
    from training.prism_portable.engine.ppo import arena
    from training.prism_portable.engine.ppo.coordinator import Run
    p=policy();cap=p['storage_per_training_bytes']
    camps={str((ROOT/'campaigns'/a).resolve()) for a in 'abc'}
    if not getattr(arena,'_m73_r5_limits',False):
        process_install()
        native_bytes=arena.directory_bytes
        def admission_bytes(path):
            actual=native_bytes(path)
            if str(Path(path).resolve()) in camps:
                old=read(Path(path)/'contract.json')['run']['budget']['max_storage_bytes']
                return reservation_bytes(actual,old,cap)
            return actual
        arena.directory_bytes=admission_bytes
        native_open=Run.open.__func__
        def opened(cls,*args,**kwargs):
            run=native_open(cls,*args,**kwargs)
            if str(run.store.root.resolve().parent) in camps:run.store.max_bytes=cap
            return run
        Run.open=classmethod(opened)
        native_admit=Run._admit
        def admit(self):
            if str(self.store.root.resolve().parent) not in camps:return native_admit(self)
            if self.state['paused'] or self.state['phase']=='FAILED':raise ValueError('run paused/failed')
            if time.time()<self.state['started_at'] or time.time()>=p['deadline']:raise ValueError('recovery wall exhausted or clock moved backwards')
        Run._admit=admit
        class ResourceTree(ProcessTree):
            def wait(self,**kwargs):
                path=kwargs.get('storage_root')
                if path is not None and str(Path(path).resolve()) in camps:kwargs['max_storage_bytes']=cap
                return super().wait(**kwargs)
        arena.ProcessTree=ResourceTree
        arena._m73_r5_limits=True
    original.bounds=remaining
    original.process_install=install


def identity(campaign):
    from training.prism_portable.protocol import state_fingerprints,state_digest
    head,ledger=campaign._load()
    return {'run_commit':campaign.run.parent,'ledger_commit':head,'state':state_fingerprints(campaign.run.state),'ledger_state_sha256':state_digest(ledger)}


def campaign_a():
    from training.prism_portable.engine.ppo.arena import Campaign
    return Campaign(ROOT/'campaigns/a',read(ROOT/'campaigns/a/contract.json'))


def require_saved_terminal(row):
    resources=row['resources']
    if row['status']!='FATAL' or resources['returncode']!=0 or resources['stop_reason']!='storage_deadline' or row.get('outcome',{}).get('status')!='completed':
        raise ValueError('only natural terminal with mistaken old storage cap can be adopted')


def saved_terminal_package(campaign,p):
    from training.prism_portable.engine.ppo.execution import verify_report
    from training.prism_portable.engine.ppo.sampling import Behavior
    number=p['pending_saved_terminal_attempt'];head,ledger=campaign._load();row=ledger['attempts'][str(number)]
    require_saved_terminal(row);job=row['job'];directory=campaign.root/'attempts'/f'{number:03d}'
    if (directory/'completion.json').exists():raise ValueError('saved terminal completion already published')
    if campaign.run.state['jobs'][job['job_id']]!={'status':'RUNNING','attempt':number}:raise ValueError('saved terminal progress mismatch')
    report=read(directory/'report.json');replay=read(directory/'replay.json')
    if verify_report(campaign.spec,job,report,replay)['status']!='completed':raise ValueError('saved true terminal verification failed')
    if read(directory/'process-result.json')!=row['resources']:raise ValueError('original process result drift')
    # Read the actual pre-failure RUNNING record; retain its argv/pid/config.
    cursor=head;launch=None
    for _ in range(8):
        record=json.loads(campaign.ledger._get('commits',cursor,'.json'))
        previous=campaign.ledger.get_payload(record['payload'])['attempts'].get(str(number),{})
        if previous.get('status')=='RUNNING' and 'pid' in previous:launch=previous;break
        cursor=record['parent']
        if cursor is None:break
    if launch is None:raise ValueError('actual original launch provenance missing')
    snapshot=campaign.run.state['snapshot'];behavior=Behavior.from_payload(campaign.run.store.get_payload(snapshot),runtime=campaign.run.runtime)
    config=read(directory/'arena-config.json');endpoint=config['agents'][job['actor']]['args'][2]
    corrected=copy.deepcopy(row['resources']);corrected['stop_reason']=None
    corrected['resource_correction']={'original_process_result_sha256':digest(directory/'process-result.json'),'original_stop_reason':'storage_deadline','revised_storage_bytes':p['storage_per_training_bytes'],'policy_sha256':digest(POLICY),'physical_game_replayed':False}
    return {'format':'prism-ppo-arena-completion-v1','contract':campaign.spec,'job':job,'attempt':number,'behavior_id':behavior.identity,'snapshot_sha256':snapshot,'endpoint':endpoint,'cwd':str(ROOT),'arena_config':config,'arena_argv':launch['argv'],'pid':launch['pid'],'resources':corrected,'files':{name:{'path':str(directory/file),'sha256':digest(directory/file)} for name,file in [('report','report.json'),('replay','replay.json'),('sidecar','sidecar.jsonl')]}}


def assert_idle():
    import psutil
    me=psutil.Process();excluded={me.pid,*[p.pid for p in me.parents()]}
    for proc in psutil.process_iter(['pid','cmdline','cwd']):
        if proc.pid in excluded:continue
        cmd=' '.join(proc.info['cmdline'] or [])
        cwd=proc.info['cwd'] or ''
        if str(ROOT) in cmd or cwd.startswith(str(ROOT)) or '/splendor run-match' in cmd or 'agent-prism' in cmd:
            raise ValueError('research process already active: '+str(proc.pid))


def verify_resume(campaign):
    from training.prism_portable.protocol import assert_owner,state_digest
    from training.prism_portable.engine.ppo.runtime import capture_rng
    owner=read(campaign.root/'ownership.json')
    assert_owner(campaign.root,read(ROOT/'host.json')['host_id'],owner['nonce'])
    head,ledger=campaign._load();validate_collecting(campaign.spec,campaign.run.state,ledger)
    actual=identity(campaign);expected=read(REV/'recovery.json')['resume_state']
    if actual!=expected:raise ValueError('full-state recovery identity drift')
    if state_digest(capture_rng())!=actual['state']['rng']:raise ValueError('exact RNG restore mismatch')
    return {'status':'PASS_EXACT_FULL_STATE_RESUME','identity':actual,'completed_games':len(ledger['attempts']),'new_games':0,'new_updates':0}


def preflight():
    import psutil
    from training.prism_portable.processes import directory_bytes
    original.verify();remaining();assert_idle();install()
    p=policy();campaign=campaign_a();actual=identity(campaign)
    if actual!=p['failed_state']:raise ValueError('failure checkpoint or ledger drift')
    if p.get('pending_saved_terminal_attempt'):saved_terminal_package(campaign,p)
    elif p.get('predecessor_control_recovery_files'):validate_collecting(campaign.spec,campaign.run.state,campaign._load()[1])
    else:recovery_view(campaign.spec,campaign.run.state,campaign._load()[1],p['failed_job'])
    if any((ROOT/'campaigns'/a).exists() for a in 'bc'):raise ValueError('B/C already created')
    if len(campaign._load()[1]['attempts'])!=p['physical_attempts_already_completed'] or campaign.run.state['global_step']!=164:raise ValueError('unexpected consumed training budget')
    size=directory_bytes(ROOT/'campaigns/a');total=directory_bytes(ROOT)
    projected=size/p['physical_attempts_already_completed']*1024*1.5
    planned=total-size+3*projected+p['evaluation_storage_reserve_bytes']
    disk=psutil.disk_usage(ROOT)
    if projected+64*1024**2>p['storage_per_training_bytes'] or planned>p['storage_total_bytes']:raise ValueError('revised capacity still insufficient')
    if disk.free<p['storage_total_bytes']-total+p['minimum_free_reserve_bytes']:raise ValueError('whole-disk reservation insufficient')
    if p['consumed_cpu_seconds']>=p['total_cpu_seconds'] or p['a_consumed_wall_seconds']>=p['training_wall_seconds']:raise ValueError('original active budget exhausted')
    result={'status':'PASS_ZERO_GAME_RECOVERY_PREFLIGHT','observed_at':time.time(),'failed_state':actual,'capacity':{'a_bytes':size,'round_bytes':total,'per_arm_projected_bytes':projected,'total_projected_bytes':planned,'free_bytes':disk.free},'remaining_wall_seconds':remaining(),'new_games':0,'new_updates':0}
    write(REV/'preflight.json',result);return result


def recover():
    original.verify();remaining();assert_idle();install()
    if (REV/'recovery.json').exists():raise ValueError('recovery already performed')
    if read(REV/'preflight.json')['status']!='PASS_ZERO_GAME_RECOVERY_PREFLIGHT':raise ValueError('preflight missing')
    p=policy();campaign=campaign_a();before=identity(campaign)
    if before!=p['failed_state']:raise ValueError('failure identity changed before recovery')
    head,ledger=campaign._load()
    if p.get('pending_saved_terminal_attempt'):
        from training.prism_portable.engine.ppo.execution import verify_completion
        number=p['pending_saved_terminal_attempt'];package=saved_terminal_package(campaign,p)
        directory=campaign.root/'attempts'/f'{number:03d}'
        write(directory/'completion.json',package)
        verify_completion(campaign.run.config,package['job'],number,directory/'completion.json',replay=directory/'replay.json',sidecar=directory/'sidecar.jsonl',behavior_id=package['behavior_id'])
        campaign.run.submit(package['job']['job_id'],number,executable=campaign.spec['arena']['program'],replay=directory/'replay.json',sidecar=directory/'sidecar.jsonl',completion=directory/'completion.json')
        with campaign.ledger.lock():
            fixed=copy.deepcopy(ledger);fixed['failed']=False
            fixed['attempts'][str(number)]={'job':package['job'],'status':'COMPLETE','charged_decisions':ledger['attempts'][str(number)]['charged_decisions'],'retry_charged':False,'completion_sha256':digest(directory/'completion.json'),'resource_recovery_policy_sha256':digest(POLICY)}
            fixed['recoveries'].append({'event':'verified_saved_terminal_resource_correction','attempt':number,'physical_games_replayed':0,'original_process_result_sha256':digest(directory/'process-result.json'),'policy_sha256':digest(POLICY)})
            campaign.ledger.commit(fixed,expected_parent=head)
        campaign.run.pause(False)
    elif p.get('predecessor_control_recovery_files'):
        validate_collecting(campaign.spec,campaign.run.state,ledger)
    else:
        recovery_view(campaign.spec,campaign.run.state,ledger,p['failed_job'])
        with campaign.ledger.lock():
            fixed=copy.deepcopy(ledger);fixed['failed']=False
            fixed['recoveries'].append({'event':'owner_authorized_storage_admission_recovery','policy_sha256':digest(POLICY),'physical_attempts_replayed':0,'previous_ledger_commit':head})
            campaign.ledger.commit(fixed,expected_parent=head)
        campaign.run.pause(False)
    after=identity(campaign_a())
    keys=['model','optimizer','rng'] if p.get('pending_saved_terminal_attempt') else list(before['state'])
    if any(after['state'][k]!=before['state'][k] for k in keys):raise ValueError('science state changed during resource recovery')
    if p.get('pending_saved_terminal_attempt'):validate_collecting(campaign.spec,campaign_a().run.state,campaign_a()._load()[1])
    result={'status':'PASS_SAVED_TERMINAL_AUDITED_AND_INGESTED_NO_RESAMPLING' if p.get('pending_saved_terminal_attempt') else 'PASS_STORAGE_RECOVERY_WITHOUT_SCIENCE_CHANGE','before':before,'resume_state':after,'accepted_saved_terminal_attempt':p.get('pending_saved_terminal_attempt'),'new_games':0,'new_updates':0,'observed_at':time.time()}
    write(REV/'recovery.json',result);return result


def finish_partial_final(campaign):
    """A saved cycle number denotes entry; c4 collecting still has work left."""
    s=campaign.run.state
    if s['phase']!='COLLECTING' or s['cycle']!=4:raise ValueError('expected partial final c4')
    campaign.work(stop_after_cycle=True)
    if campaign.run.state['phase']!='COMMITTED' or campaign.run.state['cycle']!=4:raise ValueError('partial final did not commit')


def worker(arm):
    original.verify();remaining();install()
    if arm in 'bc':return original.worker(arm)
    if arm!='a':raise ValueError('unknown arm')
    from training.prism_portable.engine.ppo.arena import Campaign
    campaign=campaign_a();proof=verify_resume(campaign);write(REV/'a-resume-verification.json',proof)
    owner=read(campaign.root/'ownership.json');camp=campaign.root
    host=read(ROOT/'host.json');host['_path']=str(ROOT/'host.json')
    os.environ.update(PRISM_PPO_HOST_ID=host['host_id'],PRISM_PPO_OWNER_NONCE=owner['nonce'],PRISM_PPO_CONTROL_DIR=str(REV/'train-a'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    track_launch(Campaign,camp)
    start=time.perf_counter();finish_partial_final(campaign)
    summary=read(camp/'cycle-4-summary.json');summary['portable_cycle_wall_seconds']=time.perf_counter()-start
    write(camp/'cycle-4-portable-summary.json',summary)
    run=campaign.run
    write(camp/'control/progress.json',{**run.status(),'observed_at':time.time(),'run_identity':run.identity})
    del campaign,run;gc.collect()
    s=read(camp/'control/progress.json')
    if (s['phase'],s['attempts'],s['cycle'])!=('COMMITTED',1024,4):raise ValueError('A final c4 incomplete')
    export=camp/'cycle-4-export/weights.json'
    write(camp/'worker-completion.json',{'status':'STOPPED_COMMITTED','games':1024,'cycle':4,'global_step':s['global_step'],'update_attempts':s['update_attempts'],'weights':str(export),'weights_sha256':digest(export),'execution_sha256':digest(ROOT/'execution.json'),'continuation_policy_sha256':digest(POLICY)})


def child(mode,arm):
    training=mode in ('train','audit')
    original.verify(training=training);remaining()
    if training:install()
    else:original.bounds=remaining
    if mode=='train':return worker(arm)
    if mode=='audit':
        from scripts.prism_m73_audit import audit
        result=audit(arm)
        result['continuation']={'policy_sha256':digest(POLICY),'adapter_sha256':digest(__file__),'original_failed_pipeline_retained':True,'resource_override_only':True,'resume_verification':read(REV/'a-resume-verification.json') if arm=='a' else None}
        write(ROOT/f'audits/{arm}/audit.json',result);return result
    if mode in ('candidates','evaluate'):
        from scripts import prism_m73_evaluate as evaluation
        return getattr(evaluation,mode)()
    if mode=='report':
        from scripts.prism_m73_report import build
        result=build()
        write(REV/'report-execution-binding.json',{'original_execution_sha256':digest(ROOT/'execution.json'),'recovery_policy_sha256':digest(POLICY),'adapter_sha256':digest(__file__),'final_candidates_sha256':digest(ROOT/'candidate-registry.json'),'evaluation_completion_sha256':digest(ROOT/'evaluation-completion.json'),'original_failed_source_and_pipeline_retained':True})
        return result
    raise ValueError('unknown stage')


def stage(mode,arm,cpu_remaining):
    from training.prism_portable.processes import directory_bytes
    p=policy();label=mode+('-'+arm if arm else '');out=REV/label;out.mkdir(exist_ok=False)
    wall=min(remaining(),p['training_wall_seconds']-(p['a_consumed_wall_seconds'] if arm=='a' else 0) if mode=='train' else remaining())
    cpu=min(cpu_remaining,p['training_cpu_seconds']-(p['a_consumed_cpu_seconds'] if arm=='a' else 0) if mode=='train' else cpu_remaining)
    py=original.contract()['runtime']['arena_python'] if mode in ('candidates','evaluate','report') else sys.executable
    os.environ.update(PRISM_PPO_CONTROL_DIR=str(out),PRISM_DSW_REMAINING_WALL=str(wall),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    last_total=[0.]
    def stop_total():
        if time.monotonic()<last_total[0]:return None
        last_total[0]=time.monotonic()+60
        return 'whole_round_storage_limit' if directory_bytes(ROOT)>p['storage_total_bytes'] else None
    def snapshot(counters):
        row={'state':'RUNNING','phase':label,'resources':counters,'observed_at':time.time(),'policy_sha256':digest(POLICY)}
        if mode=='train':
            for name in ['progress.json','live-progress.json']:
                path=ROOT/f'campaigns/{arm}/control/{name}'
                if path.exists():row.update(read(path))
        write(out/'status.json',row)
    with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
        with ProcessTree(cpu_seconds=cpu,memory_bytes=8*1024**3,max_processes=64) as tree:
            tree.start([py,'-B',str(Path(__file__).resolve()),'child','--stage',mode]+(['--arm',arm] if arm else []),cwd=ROOT,stdout=stdout,stderr=stderr)
            resources=tree.wait(wall_seconds=wall,storage_root=ROOT/f'campaigns/{arm}' if mode=='train' else ROOT,max_storage_bytes=p['storage_per_training_bytes'] if mode=='train' else p['storage_total_bytes'],storage_interval=60,stop_checker=stop_total,snapshot=snapshot)
    done={'state':'PASS' if resources['returncode']==0 and not resources['stop_reason'] else 'FAILED_STOPPED_NO_RETRY','resources':resources,'finished_at':time.time()}
    write(out/'completion.json',done)
    if done['state']!='PASS':raise ValueError('recovery stage failed '+label+': '+str(resources))
    if mode=='train':
        dest=ROOT/f'control/{arm}/completion.json'
        if dest.exists():raise ValueError('training completion already exists')
        completion=read(ROOT/f'campaigns/{arm}/worker-completion.json')
        write(dest,{'state':'STOPPED_COMMITTED','phase':'AWAITING_AUDIT','completed_games':1024,'completion':completion,'resources':resources,'finished_at':time.time(),'continuation_policy_sha256':digest(POLICY)})
    return done


def pipeline():
    import psutil
    original.verify();remaining();install()
    with (REV/'pipeline-once.lock').open('x'):pass
    p=policy();me=psutil.Process();s={'state':'RUNNING','phase':'RESUME_A','pid':me.pid,'create_time':me.create_time(),'started_at':time.time(),'execution_sha256':digest(POLICY),'original_execution_sha256':digest(ROOT/'execution.json'),'consumed_cpu_seconds':p['consumed_cpu_seconds'],'deadline':p['deadline']}
    def publish(**fields):s.update(fields,observed_at=time.time());write(REV/'status.json',s)
    try:
        for mode,arm in [(mode,arm) for arm in 'abc' for mode in ('train','audit')]+[('candidates',None),('evaluate',None),('report',None)]:
            original.verify();remaining();publish(phase=mode+('-'+arm if arm else ''))
            left=p['total_cpu_seconds']-s['consumed_cpu_seconds']
            if left<=0:raise ValueError('whole-round CPU exhausted')
            result=stage(mode,arm,left)
            s['consumed_cpu_seconds']+=result['resources']['cpu_seconds'];publish()
        publish(state='COMPLETED',phase='COMPLETE_RESULTS_AND_REPORTS',finished_at=time.time());write(REV/'completion.json',s)
        return s
    except BaseException as error:
        publish(state='FAILED_STOPPED_NO_RETRY',error=repr(error),finished_at=time.time());raise


def start():
    import psutil
    original.verify();remaining();assert_idle();install()
    campaign=campaign_a();proof=verify_resume(campaign);del campaign;gc.collect()
    write(REV/'zero-game-resume-verification.json',proof)
    with (REV/'launch-once.lock').open('x'):pass
    with (REV/'supervisor.log').open('xb') as log:
        proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'pipeline'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    receipt={'status':'STARTED_AUTHORIZED_M73_RECOVERY_R7','pid':proc.pid,'create_time':psutil.Process(proc.pid).create_time(),'execution_sha256':digest(POLICY),'original_execution_sha256':digest(ROOT/'execution.json'),'deadline':policy()['deadline'],'remaining_training_games':policy()['remaining_training_games'],'evaluation_games':19456,'automatic_retries':0}
    write(REV/'launch.json',receipt);return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['preflight','recover','start','pipeline','child']);parser.add_argument('--stage',choices=['train','audit','candidates','evaluate','report']);parser.add_argument('--arm');args=parser.parse_args()
    result=child(args.stage,args.arm) if args.mode=='child' else globals()[args.mode]()
    if result is not None:print(json.dumps(result,ensure_ascii=False))
