"""Qualified block-storage full-state relocation; immutable r4/r6 stay intact."""
import argparse
import copy
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,lock
from scripts import prism_m79_run as run


def install_platform_compatibility():
    """Keep raw checkpoint identity when only the qualified kernel string differs."""
    from scripts.prism_m67_storage import install
    from training.prism_portable.engine.ppo import coordinator
    from training.prism_portable.engine.ppo.store import CommitStore
    install()
    head=read(ROOT/'campaigns/a/run/HEAD.json')
    store=CommitStore(ROOT/'campaigns/a/run',head['identity'])
    record=read(store.root/'commits'/(head['commit']+'.json'))
    state=store.get_payload(record['payload']);saved=state['runtime']
    native=coordinator.configure
    actual=native('cpu',2)
    if set(saved)!=set(actual) or any(saved[k]!=actual[k] for k in saved if k!='platform'):
        raise ValueError('numeric checkpoint runtime differs beyond platform kernel string')
    source_identity=coordinator.source_identity()
    expected_identity=coordinator.canonical_hash({'config':read(ROOT/'campaigns/a/run/config.json'),'runtime':saved,'source':source_identity})
    if expected_identity!=head['identity']:raise ValueError('checkpoint source/config identity drift')
    def compatible(device,threads):
        found=native(device,threads)
        if any(saved[k]!=found[k] for k in saved if k!='platform'):
            raise ValueError('numeric environment changed after qualified relocation')
        return copy.deepcopy(saved)
    coordinator.configure=compatible
    return dict(saved_runtime=saved,actual_runtime=actual,retained_identity=head['identity'])


def verify_binding():
    revision=read(ROOT/'migration-r7/revision.json')
    if digest(__file__)!=revision['adapter_sha256'] or digest(ROOT/'execution.json')!=revision['execution_sha256']:
        raise ValueError('r7 independent execution binding drift')
    if digest(ROOT/'execution-revisions/r6.json')!=revision['r6_sha256']:
        raise ValueError('original r6 identity drift')
    if digest(ROOT/'scripts/prism_m79_dual_dispatch.py')!=revision['dual_dispatch_sha256']:
        raise ValueError('dual-node adapter source drift')
    if read(ROOT/'round-budget.json')!=revision['original_budget']:
        raise ValueError('original budget or deadline changed')
    return revision


def qualify():
    revision=verify_binding()
    actual=run.environment();expected=read(ROOT/'execution.json')['environment']
    if any(actual[k]!=expected[k] for k in ('python','executable','packages')):
        raise ValueError('relocation numeric environment drift')
    quota=int(Path('/sys/fs/cgroup/cpu/cpu.cfs_quota_us').read_text())/int(Path('/sys/fs/cgroup/cpu/cpu.cfs_period_us').read_text())
    if quota<4 or len(actual['affinity'])<4:
        raise ValueError('training needs actual four-core capacity')
    import shutil
    capacity=shutil.disk_usage(ROOT)
    # The block volume is limited to 100 GB. Shared NAS df capacity is never
    # treated as the capacity of this execution or of the auxiliary instance.
    if capacity.free<revision['minimum_free_before_training']:
        raise ValueError('insufficient original training role reservation')
    from training.prism_portable.processes import directory_bytes
    root_bytes=directory_bytes(ROOT)
    remaining_role=max(0,40802189312-root_bytes)+8589934592
    if revision['storage_limit_per_instance_bytes']-capacity.used<remaining_role:
        raise ValueError('owner 100GB limit lacks remaining role and reserve space')
    destination=ROOT/'migration-r7/node-qualification.json'
    if destination.exists() and read(destination)['environment']['node']!=actual['node']:
        destination.rename(destination.with_name('node-qualification-before-'+str(int(time.time()))+'.json'))
    if not destination.exists():
        from training.prism_portable.provision import provision
        os.sched_setaffinity(0,{0,1,2,3})
        staged=ROOT/'migration-r7/numeric-parity.json'
        if staged.exists() and read(staged)['node']==actual['node']:
            parity=read(staged)['parity']
        else:
            _,parity=provision(ROOT/'migration-r7/parity',ROOT,ROOT/'bin/splendor',ROOT/'bin/s4_batch_metrics',ROOT/'inputs/parent.json',ROOT/'inputs/initial.json',ROOT/'inputs/fixtures.jsonl','m79-r7-'+actual['node'])
        if parity['boundary_inputs']!=68:raise ValueError('parity fixture count drift')
        write(destination,dict(status='PASS',environment=actual,quota_cores=quota,parity=parity,new_games=0,observed_at=time.time()))
    rows=read(ROOT/'runtime-revisions.json') if (ROOT/'runtime-revisions.json').exists() else []
    if not any(r['node']==actual['node'] for r in rows):
        rows.append(dict(node=actual['node'],environment=actual,execution_sha256=digest(ROOT/'execution.json'),qualification_sha256=digest(destination),new_games=0,observed_at=time.time()))
        write(ROOT/'runtime-revisions.json',rows)
    run.verify()
    return read(destination)


def reconcile():
    revision=verify_binding();qualify()
    authorization=read(ROOT/'migration-r7/budget-authorization.json')
    if authorization['decision']!='APPROVED_EXPLICIT_USER_REPLY' or authorization['unobserved_cpu_charge']!=10000:
        raise ValueError('finite historical CPU accounting revision needs explicit user approval')
    from scripts.prism_m67_storage import install
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.protocol import state_fingerprints
    install()
    compatibility=install_platform_compatibility()
    with lock(ROOT/'migration-r7/reconciliation-control'):
        done=ROOT/'migration-r7/reconciliation.json'
        if done.exists():return read(done)
        saved=Run.open(ROOT/'campaigns/a/run')
        if state_fingerprints(saved.state)!=revision['source_state_fingerprints'] or saved.parent!=revision['source_run_commit']:
            raise ValueError('full model/optimizer/RNG/progress did not survive relocation')
        journal=read(ROOT/'pipeline/resources.json')
        running=[r for r in journal if r['state']=='RUNNING']
        if len(running)!=1 or running[0]['mode']!='train':raise ValueError('unexpected interrupted stage')
        row=running[0]
        relay=read(ROOT/revision['last_relay_path'])
        if relay['pid']!=row['relay_pid'] or relay['cpu_seconds']!=authorization['measured_cpu_seconds']:
            raise ValueError('historical CPU receipt drift')
        write(ROOT/'migration-r7/resources-before.json',journal)
        row.update(state='INTERRUPTED',cpu_seconds=relay['cpu_seconds']+10000,
                   measured_cpu_seconds=relay['cpu_seconds'],unobserved_cpu_seconds='UNKNOWN',
                   unobserved_cpu_charge=10000,accounting_authorization_sha256=digest(ROOT/'migration-r7/budget-authorization.json'),
                   reason='platform instance replacement; explicit finite accounting revision; original reservation retained',
                   observed_at=time.time())
        if sum(r.get('cpu_seconds',0) for r in journal if r['category']=='training')>=150000:
            raise ValueError('original training CPU cap exhausted')
        write(ROOT/'pipeline/resources.json',journal)
        receipt=dict(status='PASS_FULL_STATE_RELOCATION_AND_AUTHORIZED_ACCOUNTING',state_fingerprints=state_fingerprints(saved.state),run_commit=saved.parent,
                     cycle=saved.state['cycle'],attempts=saved.state['attempts'],updates=saved.state['global_step'],
                     original_budget=revision['original_budget'],budget_authorization_sha256=digest(ROOT/'migration-r7/budget-authorization.json'),platform_compatibility=compatibility,new_games=0,observed_at=time.time())
        write(done,receipt);return receipt


def pipeline():
    verify_binding()
    if not (ROOT/'migration-r7/reconciliation.json').exists():raise ValueError('qualified full-state reconciliation missing')
    native_verify=run.verify
    def local_verify():
        c,p=native_verify();p=copy.deepcopy(p);p['binding']['evaluation_affinity']=[0,1,2,3]
        return c,p
    run.verify=local_verify
    native_start=run.ProcessTree.start
    def relocate_worker(self,argv,**kwargs):
        if argv[-1]=='worker' and argv[-2]==str(ROOT/'scripts/prism_m79_revision_r6.py'):
            argv=[*argv[:-2],str(Path(__file__).resolve()),'worker']
        elif argv[-1]==str(ROOT/'scripts/prism_m79_audit.py'):
            argv=[*argv[:-1],str(Path(__file__).resolve()),'audit']
        return native_start(self,argv,**kwargs)
    run.ProcessTree.start=relocate_worker
    from scripts import prism_m79_dual_dispatch as dual
    return dual.pipeline(ROOT)


def worker():
    verify_binding();install_platform_compatibility()
    from scripts.prism_m79_revision_r6 import patched_worker
    return patched_worker()


def audit():
    verify_binding();install_platform_compatibility()
    from scripts.prism_m79_audit import audit as checked
    return checked()


def ensure():
    verify_binding();reconcile()
    import psutil
    from scripts.prism_dsw_ppo_process import same_process
    with lock(ROOT/'migration-r7/dispatch-control'):
        rows=read(ROOT/'pipeline/launches.json')
        for old in reversed(rows):
            if same_process(old['pid'],old['create_time']):
                if str(Path(__file__).resolve()) not in psutil.Process(old['pid']).cmdline():raise ValueError('other live execution owner')
                return dict(old,action='LIVE_R7_OWNER_KEEP')
        native=run.subprocess.Popen
        def launch(argv,**kwargs):
            if argv[-1]=='pipeline' and argv[-2]==str(ROOT/'scripts/prism_m79_run.py'):
                argv=[*argv[:-2],str(Path(__file__).resolve()),'pipeline']
            return native(argv,**kwargs)
        run.subprocess.Popen=launch
        return run.ensure()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('qualify','reconcile','ensure','pipeline','worker','audit'));args=p.parse_args()
    print(json.dumps(globals()[args.mode]()),flush=True)
