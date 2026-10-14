"""Isolated finite M79 controller. Numeric core and historical executions stay pinned."""
from __future__ import annotations
import argparse, copy, gc, hashlib, importlib.metadata, inspect, json, os
from pathlib import Path
import platform, shutil, subprocess, sys, textwrap, time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,identity,lock,numerical_identity
from scripts.prism_dsw_ppo_process import ProcessTree,same_process,install as process_install
PLAN='benchmarks/m79-prism-mainline.execution-plan.json'
BP='benchmarks/m79-prism-mainline.a-train.json'

def environment():
    return dict(python=sys.version,executable=str(Path(sys.executable).resolve()),
                packages={k:importlib.metadata.version(k) for k in ('torch','numpy','psutil','Markdown')},
                affinity=sorted(os.sched_getaffinity(0)),node=platform.node())

def verify():
    p=read(ROOT/'execution.json'); c=read(ROOT/PLAN)
    if digest(ROOT/PLAN)!=p['plan_sha256'] or digest(ROOT/'host.json')!=p['host_sha256']:raise ValueError('contract/host drift')
    if numerical_identity()!=p['numeric_source_identity']:raise ValueError('numeric source drift')
    for path,h in p['files'].items():
        if digest(ROOT/path)!=h:raise ValueError('bound member drift: '+path)
    actual=environment(); expected=p['environment']
    if any(actual[k]!=expected[k] for k in ('python','executable','packages')):raise ValueError('runtime drift')
    if actual['node']!=expected['node']:
        revisions=read(ROOT/'runtime-revisions.json') if (ROOT/'runtime-revisions.json').exists() else []
        if not any(r['node']==actual['node'] and r['execution_sha256']==digest(ROOT/'execution.json') and r['environment']['packages']==actual['packages'] for r in revisions):raise ValueError('unqualified replacement node')
    return c,p

def bounds():
    p=read(ROOT/'round-budget.json')
    if p['execution_sha256']!=digest(ROOT/'execution.json'):raise ValueError('budget execution drift')
    left=p['deadline']-time.time()
    if left<=0:raise ValueError('finite deadline exhausted')
    return left

def preflight():
    from scripts.prism_m79_prepare import validate
    c=read(ROOT/PLAN);validate(c,read(ROOT/BP))
    binding=read(ROOT/'node-binding.json'); capacity=shutil.disk_usage(ROOT)
    if capacity.free<c['resources']['dsw_minimum_free_bytes']:raise ValueError('training role storage reserve insufficient')
    expected={'torch':'2.6.0+cpu','numpy':'2.2.4','psutil':'7.0.0','Markdown':'3.7'}
    if environment()['packages']!=expected:raise ValueError('numeric dependencies do not match prior training')
    if len(os.sched_getaffinity(0))<4 or binding['cpu_quota_cores']<4:raise ValueError('training allocation insufficient')
    os.sched_setaffinity(0,binding['training_affinity'])
    from training.prism_portable.provision import provision
    host,parity=provision(ROOT,ROOT,ROOT/'bin/splendor',ROOT/'bin/s4_batch_metrics',ROOT/'inputs/parent.json',ROOT/'inputs/initial.json',ROOT/'inputs/fixtures.jsonl','m79-'+platform.node())
    for k,v in c['assets'].items():
        f=ROOT/f'inputs/{k}.json'
        if digest(f)!=v['sha256']:raise ValueError('asset drift: '+k)
        host['assets'][k]={'path':str(f),'sha256':v['sha256']}
    if parity['boundary_inputs']!=68:raise ValueError('boundary fixture count drift')
    write(ROOT/'host.json',host)
    from training.prism_portable.protocol import bind
    bind(read(ROOT/BP),host)
    source=read(ROOT/'source-members.json')
    for k,h in source.items():
        if digest(ROOT/k)!=h:raise ValueError('deployment member drift '+k)
    files=dict(source,**{'node-binding.json':digest(ROOT/'node-binding.json')})
    engineering=read(ROOT/'engineering-acceptance.json')
    if engineering['status']!='PASS' or engineering['new_games']!=0:raise ValueError('engineering zero-game acceptance missing')
    receipt=dict(format='prism-m79-execution-v1',status='PASS_NUMERIC_SOURCE_ZERO_GAME_PREFLIGHT',plan_sha256=digest(ROOT/PLAN),
                 source_archive_sha256=read(ROOT/'source-receipt.json')['sha256'],files=files,
                 host_sha256=digest(ROOT/'host.json'),numeric_source_identity=numerical_identity(),environment=environment(),
                 capacity=dict(free=capacity.free,minimum_free=c['resources']['dsw_minimum_free_bytes']),
                 binding=binding,parity=parity,created_at=time.time(),new_games=0,
                 engineering_acceptance_sha256=digest(ROOT/'engineering-acceptance.json'),
                 initialization='fresh AdamW and RNG warm-start; full-state only for subsequent recovery')
    write(ROOT/'execution.json',receipt)
    return dict(status=receipt['status'],execution_sha256=digest(ROOT/'execution.json'),new_games=0,parity=parity)

def validate_cap(spec,job,row,report,prefix,resources,*,sidecar_count,replay_exists):
    # This helper has no M75 paths, constants, policy or writes. Its source is pinned.
    from scripts.prism_m75_resume import validate_cap as checked_cap
    return checked_cap(spec,job,row,report,prefix,resources,sidecar_count=sidecar_count,replay_exists=replay_exists)

def cap_files(campaign,number):
    _,ledger=campaign._load(); row=ledger['attempts'][str(number)];job=row['job']
    p=campaign.root/'attempts'/f'{number:03d}'
    evidence=validate_cap(campaign.spec,job,row,read(p/'report.json'),read(p/'prefix.json'),read(p/'process-result.json'),
        sidecar_count=sum(1 for _ in (p/'sidecar.jsonl').open('rb')),replay_exists=(p/'replay.json').exists())
    return dict(evidence,attempt=number,job=job,files={n:digest(p/n) for n in ('report.json','prefix.json','sidecar.jsonl','process-result.json','arena-config.json')})

def adopt_cap(campaign,number):
    from training.prism_portable.protocol import state_fingerprints
    proof=cap_files(campaign,number);head,ledger=campaign._load()
    before=state_fingerprints(campaign.run.state)
    if ledger['attempts'][str(number)]['status']=='TRUNCATED':return proof
    caps=sum(x['status']=='TRUNCATED' for x in ledger['attempts'].values())
    if caps>=8:raise ValueError('ninth scientific training truncation; finite stop')
    job=proof['job']
    if campaign.run.state['jobs'][job['job_id']]!={'status':'RUNNING','attempt':number}:raise ValueError('cap adoption state drift')
    with campaign.ledger.lock():
        fixed=copy.deepcopy(ledger);fixed['attempts'][str(number)].update(status='TRUNCATED',cap_evidence=proof)
        # No other fatal evidence may be erased.
        if any(r['status']=='FATAL' for n,r in fixed['attempts'].items() if n!=str(number)):raise ValueError('unrelated fatal evidence')
        fixed['failed']=False;fixed['recoveries'].append(dict(event='m79_retained_scientific_cap',attempt=number,previous_commit=head))
        campaign.ledger.commit(fixed,expected_parent=head)
    campaign._ledger_cache=None
    with campaign.run._transaction():
        campaign.run.state['jobs'][job['job_id']]={'status':'TRUNCATED','attempt':number,'cap_evidence':proof}
        campaign.run.state['paused']=False
        campaign.run.state['metrics'].append(dict(event='retained_cap_excluded_from_training',cycle=campaign.run.state['cycle'],attempt=number))
        campaign.run._commit()
    after=state_fingerprints(campaign.run.state)
    if any(before[k]!=after[k] for k in ('model','optimizer','rng')):raise ValueError('cap altered numeric state')
    return proof

def resolved_jobs(state):
    jobs=state['schedule']
    if any(state['jobs'].get(j['job_id'],{}).get('status') not in ('COMPLETE','TRUNCATED') for j in jobs):raise ValueError('unresolved job cannot seal')
    return [j for j in jobs if state['jobs'][j['job_id']]['status']=='COMPLETE']

def adapted(method,changes,extra=None):
    source=textwrap.dedent(inspect.getsource(method));ns=dict(method.__globals__,**(extra or {}))
    for old,new in changes:
        if source.count(old)!=1:raise ValueError('adapter target drift '+method.__name__)
        source=source.replace(old,new)
    exec(compile(source,str(Path(__file__))+'::'+method.__name__,'exec'),ns)
    return ns[method.__name__]

def publish_progress(campaign):
    _,ledger=campaign._load();s=campaign.run.state
    write(campaign.root/'control/live-progress.json',dict({k:s[k] for k in ('phase','cycle','attempts','global_step','update_attempts')},
        completed_games=sum(x['status']=='COMPLETE' for x in ledger['attempts'].values()),
        truncated_games=sum(x['status']=='TRUNCATED' for x in ledger['attempts'].values()),
        infrastructure_aborts=sum(x['status']=='INFRA_ABORT' for x in ledger['attempts'].values()),
        observed_at=time.time(),execution_sha256=digest(ROOT/'execution.json')))

def install():
    from scripts.prism_m67_storage import install as storage_install
    storage_install();process_install()
    from training.prism_portable.engine.ppo import arena
    from training.prism_portable.engine.ppo.coordinator import Run
    if getattr(arena,'_m79_adapter',False):return
    native_launch=arena.Campaign.launch;native_recover=arena.Campaign.recover_running
    def launch(self,*args,**kw):
        bounds();job=args[0];_,ledger=self._load()
        previous=[r for r in ledger['attempts'].values() if r.get('job',{}).get('job_id')==job['job_id']]
        if sum(r['status']=='INFRA_ABORT' for r in previous)>1:raise ValueError('one infrared retry exhausted for job')
        if any(r['status'] in ('COMPLETE','TRUNCATED') for r in previous):raise ValueError('resolved job must never replay')
        try:result=native_launch(self,*args,**kw)
        except ValueError:
            _,ledger=self._load();n=self.run.state['attempts'];row=ledger['attempts'].get(str(n),{})
            if row.get('status')!='FATAL' or row.get('outcome',{}).get('status')!='truncated':raise
            adopt_cap(self,n);result=True
        _,ledger=self._load()
        if sum(r['status']=='INFRA_ABORT' for r in ledger['attempts'].values())>64:raise ValueError('global infrastructure budget exhausted')
        if not result and sum(r['status']=='INFRA_ABORT' and r.get('job',{}).get('job_id')==job['job_id'] for r in ledger['attempts'].values())>1:raise ValueError('per-job infrastructure retry exhausted')
        publish_progress(self);return result
    def recover(self,job,snapshot):
        if self.run.state['jobs'].get(job['job_id'],{}).get('status')=='TRUNCATED':return
        return native_recover(self,job,snapshot)
    arena.Campaign.launch=launch;arena.Campaign.recover_running=recover
    arena.Campaign.work=adapted(arena.Campaign.work,[("!= 'COMPLETE':","not in ('COMPLETE','TRUNCATED'):")])
    patched_seal=adapted(Run.seal,[
        ('if s["phase"] != "COLLECTING" or any(s["jobs"].get(j["job_id"], {}).get("status") != "COMPLETE" for j in s["schedule"]):','if s["phase"] != "COLLECTING":'),
        ('games = [self.store.get_json(s["jobs"][j["job_id"]]["artifact"]) for j in s["schedule"]]','valid = resolved_jobs(s)\n        if not valid: raise ValueError("no terminal data in cycle")\n        games = [self.store.get_json(s["jobs"][j["job_id"]]["artifact"]) for j in valid]')],{'resolved_jobs':resolved_jobs})
    def sealed(self):
        result=patched_seal(self)
        record_batch(self)
        return result
    Run.seal=sealed
    arena.Campaign.cycle_summary=adapted(arena.Campaign.cycle_summary,[("if record['status'] != 'COMPLETE':","if record['status'] == 'TRUNCATED': continue\n        if record['status'] != 'COMPLETE':")])
    arena._m79_adapter=True

def record_batch(run):
    s=run.state
    if s['phase']!='UPDATING':raise ValueError('batch binding requires actual sealed state')
    batch=run.store.get_json(s['batch'])
    from training.prism_portable.engine.ppo.learner import validate_batch
    validate_batch(batch,run.ppo)
    dest=run.root.parent/f'cycle-{s["cycle"]}-batch-binding.json'
    row=dict(cycle=s['cycle'],batch_id=batch['batch_id'],batch_object_sha256=s['batch'],behavior_id=batch['behavior_id'],cursor=s['cursor'],run_commit=run.parent)
    if dest.exists():
        old=read(dest)
        if any(old[k]!=row[k] for k in ('cycle','batch_id','batch_object_sha256','behavior_id')):raise ValueError('batch binding drift')
    else:
        if s['cursor']!=0:raise ValueError('sealed batch binding missing after update cursor advanced')
        write(dest,row)

def worker():
    c,p=verify();bounds();os.sched_setaffinity(0,p['binding']['training_affinity']);install()
    from training.prism_portable.protocol import create,assert_owner,state_fingerprints,state_digest
    from training.prism_portable.engine.ppo.arena import Campaign
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.ppo.runtime import capture_rng
    from training.prism_portable.engine.export import load_weights
    import torch
    camp=ROOT/'campaigns/a';host=read(ROOT/'host.json')
    if not camp.exists():
        owner=create(camp,read(ROOT/BP),host,'m79-a')
        run=Run.open(camp/'run');parent=load_weights(ROOT/'inputs/parent.json',expected_catalog_fingerprint=run.config['catalog_fingerprint'])
        if run.state['optimizer']['state'] or run.state['attempts'] or run.state['cycle']:raise ValueError('optimizer not fresh')
        if any(not torch.equal(t,run.state['model']['policy.'+k]) for k,t in parent.state_dict().items()):raise ValueError('initial parent tensor mismatch')
        write(camp/'initialization-verification.json',dict(status='PASS',exact_parent_tensors=32,optimizer_slots=0,run_seed=79010001,
            parent_sha256=digest(ROOT/'inputs/parent.json'),torch_rng_sha256=hashlib.sha256(bytes(run.state['rng']['torch'].tolist())).hexdigest()))
        del run,parent;gc.collect()
    owner=assert_owner(camp,host['host_id']);os.environ.update(PRISM_PPO_HOST_ID=owner['host_id'],PRISM_PPO_OWNER_NONCE=owner['nonce'],PRISM_PPO_CONTROL_DIR=str(camp/'control'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    campaign=Campaign(camp,read(camp/'contract.json'))
    if state_digest(capture_rng())!=state_fingerprints(campaign.run.state)['rng']:raise ValueError('restored RNG mismatch')
    if campaign.run.state['paused']:
        if campaign._load()[1]['failed'] or campaign.run.state['phase']=='FAILED':raise ValueError('scientific failure cannot resume')
        campaign.run.pause(False)
    if campaign.run.state['phase']=='UPDATING':record_batch(campaign.run)
    while not (campaign.run.state['phase']=='COMMITTED' and campaign.run.state['cycle']==20):
        campaign.work(stop_after_cycle=True);publish_progress(campaign)
    _,ledger=campaign._load();s=campaign.run.state
    from scripts.prism_m79_audit import validate_ledger
    validate_ledger(ledger,s,campaign.spec)
    export=camp/'cycle-20-export/weights.json'
    result=dict(status='STOPPED_COMMITTED',logical_attempts=5120,physical_attempts=s['attempts'],
                games=sum(r['status']=='COMPLETE' for r in ledger['attempts'].values()),truncated_games=sum(r['status']=='TRUNCATED' for r in ledger['attempts'].values()),
                cycle=20,global_step=s['global_step'],update_attempts=s['update_attempts'],weights=str(export),weights_sha256=digest(export),execution_sha256=digest(ROOT/'execution.json'))
    write(camp/'worker-completion.json',result);return result

def pipeline():
    c,p=verify();control=ROOT/'pipeline';control.mkdir(exist_ok=True)
    import psutil
    with lock(control):
        budget=read(ROOT/'round-budget.json');journal=read(control/'resources.json') if (control/'resources.json').exists() else [dict(category='audit_transfer_control',mode='engineering_preparation',state='FINISHED',cpu_seconds=10000.,accounting_scope='conservative reservation for pre-dispatch engineering, dependency install and transfer; actual CPU unmeasured')]
        # Reconcile immutable relay snapshots; unknown interval costs its CPU reservation.
        for r in journal:
            if r['state']=='RUNNING':
                records=list((control/'relay').glob('*.json'))
                matching=[read(f) for f in records if read(f).get('pid')==r.get('relay_pid')]
                charge=r['cpu_reserved']
                if matching:charge=min(charge,matching[-1]['cpu_seconds']+max(0,time.time()-matching[-1]['observed_at'])*r['cpu_capacity'])
                r.update(state='INTERRUPTED',cpu_seconds=charge)
        write(control/'resources.json',journal)
        status=dict(state='RUNNING',pid=os.getpid(),create_time=psutil.Process().create_time(),node=platform.node(),execution_sha256=digest(ROOT/'execution.json'),deadline=budget['deadline'])
        write(control/'status.json',status)
        stages=[('train','training',150000,8*1024**3),('audit','audit_transfer_control',30000,8*1024**3),('candidates','audit_transfer_control',30000,8*1024**3),('curve','evaluation_development',120000,16*1024**3),('evaluate','evaluation_development',120000,16*1024**3),('report','audit_transfer_control',30000,16*1024**3)]
        try:
            for mode,category,cap,rss in stages:
                done=control/f'{mode}.completion.json'
                if done.exists() and read(done)['status']=='PASS':continue
                verify();remaining=bounds()
                spent=sum(r.get('cpu_seconds',0) for r in journal if r['category']==category)
                allspent=sum(r.get('cpu_seconds',0) for r in journal)
                left=min(cap-spent,300000-allspent)
                if left<=0:raise ValueError(category+' CPU budget exhausted')
                if mode=='train':
                    from training.prism_portable.processes import directory_bytes
                    if (ROOT/'campaigns/a').exists() and directory_bytes(ROOT/'campaigns/a')>=34359738368:raise ValueError('training storage budget exhausted')
                affinity=p['binding']['training_affinity'] if mode in ('train','audit') else p['binding']['evaluation_affinity'];os.sched_setaffinity(0,affinity)
                wall=remaining
                if mode=='train':wall=min(wall,64800-(time.time()-budget['started_at']))
                if wall<=0:raise ValueError('training finite wall exhausted')
                os.environ.update(PRISM_PPO_CONTROL_DIR=str(control),PRISM_DSW_REMAINING_WALL=str(wall),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2' if mode in ('train','audit') else '1',MKL_NUM_THREADS='2' if mode in ('train','audit') else '1')
                module='prism_m79_run' if mode=='train' else 'prism_m79_audit' if mode=='audit' else 'prism_m79_report' if mode=='report' else 'prism_m79_evaluate'
                args=['worker'] if mode=='train' else [] if mode in ('audit','report') else [mode]
                argv=[sys.executable,'-B',str(ROOT/f'scripts/{module}.py'),*args]
                row=dict(category=category,mode=mode,state='RUNNING',started_at=time.time(),cpu_reserved=left,cpu_capacity=len(affinity))
                journal.append(row);write(control/'resources.json',journal)
                status.update(phase=mode.upper(),observed_at=time.time());write(control/'status.json',status)
                with (control/f'{mode}-{len(journal)}.log').open('wb') as log:
                    with ProcessTree(cpu_seconds=left,memory_bytes=rss,max_processes=128) as tree:
                        process=tree.start(argv,cwd=ROOT,stdout=log,stderr=log);row['relay_pid']=process.pid;write(control/'resources.json',journal)
                        next_train_scan=[0.]
                        def training_storage_guard():
                            if mode!='train' or time.monotonic()<next_train_scan[0]:return None
                            next_train_scan[0]=time.monotonic()+60
                            from training.prism_portable.processes import directory_bytes
                            return 'training_storage_deadline' if (ROOT/'campaigns/a').exists() and directory_bytes(ROOT/'campaigns/a')>=34359738368 else None
                        def publish(counters):
                            row.update(snapshot=counters);write(control/'resources.json',journal)
                            write(control/'status.json',dict(status,resources=counters,observed_at=time.time()))
                        resources=tree.wait(wall_seconds=wall,storage_root=ROOT,max_storage_bytes=40802189312,storage_interval=60,snapshot=publish,
                            stop_checker=training_storage_guard)
                row.update(state='FINISHED',cpu_seconds=resources['cpu_seconds'],resources=resources,finished_at=time.time());write(control/'resources.json',journal)
                receipt=dict(status='PASS' if resources['returncode']==0 and not resources['stop_reason'] else 'FAIL',resources=resources,execution_sha256=digest(ROOT/'execution.json'))
                write(done,receipt)
                if receipt['status']!='PASS':raise ValueError('stage hard failure '+mode+': '+str(resources))
            status.update(state='RESULTS_READY_PENDING_VISUAL_AND_ARCHIVE',phase='REPORT_DELIVERED',finished_at=time.time());write(control/'completion.json',status)
        except BaseException as error:
            status.update(state='STOPPED_REQUIRES_RECONCILIATION',error=repr(error),finished_at=time.time());raise
        finally:write(control/'status.json',status)
        return status

def ensure():
    c,p=verify();import psutil
    gate=read(ROOT/'zero-game-preflight.json')
    if gate['status']!='PASS_R3_ZERO_GAMES' or gate['execution_sha256']!=digest(ROOT/'execution.json'):raise ValueError('full R3 recovery/source/engineering gate not passed')
    control=ROOT/'pipeline';control.mkdir(exist_ok=True)
    with lock(ROOT/'launch-control'):
        if (control/'completion.json').exists():return read(control/'completion.json')
        if (control/'status.json').exists():
            s=read(control/'status.json')
            if same_process(s['pid'],s['create_time']):return dict(s,action='LIVE_OWNER_KEEP')
            # A failed scientific stage is a stop, never a restart trigger.
            for mode in ('audit','candidates','report'):
                f=control/f'{mode}.completion.json'
                if f.exists() and read(f)['status']=='FAIL':raise ValueError('retained hard stage failure '+mode)
            train=control/'train.completion.json'
            if train.exists() and read(train)['status']=='FAIL':raise ValueError('retained training stop; reconcile before resume')
        launches=read(control/'launches.json') if (control/'launches.json').exists() else []
        if len(launches)>=7:raise ValueError('six coordinator restarts exhausted')
        budgetpath=ROOT/'round-budget.json'
        if not budgetpath.exists():
            from datetime import datetime
            now=time.time();latest=datetime.fromisoformat(c['resources']['launch_no_later_than']).timestamp()
            if now>=latest:raise ValueError('first dispatch deadline exhausted')
            deadline=min(now+108000,datetime.fromisoformat(c['resources']['absolute_stop']).timestamp())
            write(budgetpath,dict(started_at=now,deadline=deadline,execution_sha256=digest(ROOT/'execution.json')))
        bounds()
        if shutil.disk_usage(ROOT).free<8589934592:raise ValueError('whole disk reserve exhausted')
        with (control/f'supervisor-{len(launches)}.log').open('wb') as log:
            proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'pipeline'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        receipt=dict(status='STARTED_M79_COORDINATOR',pid=proc.pid,create_time=psutil.Process(proc.pid).create_time(),node=platform.node(),path=str(ROOT),execution_sha256=digest(ROOT/'execution.json'),deadline=read(budgetpath)['deadline'],observed_at=time.time())
        launches.append(receipt);write(control/'launches.json',launches);write(control/'launch.json',receipt);return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['environment','preflight','worker','pipeline','ensure']);args=parser.parse_args()
    print(json.dumps(globals()[args.mode](),ensure_ascii=False),flush=True)
