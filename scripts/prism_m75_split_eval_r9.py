"""Finite M75 placement revision: disjoint, previously unstarted shards only."""
import argparse
import fcntl
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import time
import threading

import psutil

ROOT = Path(__file__).resolve().parents[1]
REV = ROOT / 'split-eval-r9'
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write, digest


def partition(shards, finished):
    pending = [s for s in shards if s['label'] not in finished]
    if len({s['label'] for s in shards}) != len(shards):
        raise ValueError('duplicate shard')
    count = max(1, round(len(pending) / 3)) if pending else 0
    return pending[-count:] if count else []


def policy():
    p = read(REV / 'policy.json')
    if digest(__file__) != p['source_sha256'] or time.time() >= p['deadline']:
        raise ValueError('split source/deadline drift')
    if digest(ROOT / 'candidate-registry.json') != p['registry_sha256']:
        raise ValueError('candidate registry drift')
    if digest(ROOT / 'campaigns/a/cycle-20-export/weights.json') != p['weights_sha256']:
        raise ValueError('candidate weight drift')
    return p


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def recovery():
    # Reuse the hash-verified endpoint's SDK/runtime and actual-arena adapter.
    v2 = load(ROOT / 'reboot-resume-r8/endpoint-v2.py', 'r9_endpoint_base')
    source = inspect.getsource(v2.main)
    target = "return module.endpoint() if sys.argv[1]=='endpoint' else module.ensure()"
    if source.count(target) != 1: raise ValueError('endpoint adapter target drift')
    ns = dict(v2.__dict__)
    exec(compile(source.replace(target, 'return module'), str(__file__)+'::factory', 'exec'), ns)
    r = ns['main']()
    source = inspect.getsource(r.load('r9_original_recovery', ROOT/'reboot-resume-r8/recovery.py').install_adapters)
    target = "str(ROOT/'reboot-resume-r8/recovery.py')"
    if source.count(target) != 1: raise ValueError('stage adapter target drift')
    ns = dict(r.__dict__)
    exec(compile(source.replace(target, "str(ROOT/'split-eval-r9/controller.py')"), str(__file__)+'::install', 'exec'), ns)
    install = ns['install_adapters']
    def adapters(m):
        install(m)
        from scripts import prism_m75_evaluate as e, prism_bounded_eval as b
        native = e.dispatch
        def dispatch(shards, limit=4, truncation_limit=16):
            if not shards or not all(s['label'].startswith('a-') for s in shards):
                return native(shards, limit=limit, truncation_limit=truncation_limit)
            p = policy(); labels = {s['label'] for s in p['dsw_shards']}
            local = [s for s in shards if s['label'] not in labels]
            done = native(local, limit=limit, truncation_limit=truncation_limit)
            while not (REV/'import.json').exists():
                policy()
                if (REV/'import-failure.json').exists():raise ValueError('subset import failed')
                time.sleep(2)
            receipt=read(REV/'import.json')['receipt']
            imported = [dict(s, grid=b.inspect(Path(s['output']))) for s in shards if s['label'] in labels]
            if sum(s['grid']['truncated_games'] for s in done+imported)>truncation_limit:
                raise ValueError('combined cap budget exceeded')
            write(REV/'import.json', dict(state='PASS_EXACT_DISJOINT_SHARDS', labels=sorted(labels), receipt=receipt, observed_at=time.time()))
            return done+imported
        e.dispatch = dispatch
        native_write = m.write
        def recorded(path, value):
            if Path(path)==ROOT/'evaluation-plan.json':
                value=dict(value, execution_revision='split-eval-r9', placement_policy_sha256=digest(REV/'policy.json'), placement={'dsw_candidate':len(policy()['dsw_shards'])*64,'dsw2_candidate':5120-len(policy()['dsw_shards'])*64,'baseline_retained':4096})
            if Path(path)==ROOT/'evaluation-completion.json':
                value=dict(value, execution_revision='split-eval-r9', placement_policy_sha256=digest(REV/'policy.json'))
            native_write(path,value)
        m.write=recorded
        native_stage=m.stage
        def stage(mode,cpu_left,node):
            if mode!='final-evaluation':return native_stage(mode,cpu_left,node)
            def transfer():
                try:
                    archive,receipt=m.receive('split-r9-dsw-output')
                    labels={s['label'] for s in policy()['dsw_shards']}
                    if receipt.get('split_policy_sha256')!=digest(REV/'policy.json'):raise ValueError('split transfer policy drift')
                    m.extract_bound(archive,receipt,lambda rel:any(rel.startswith('evaluation/'+label+'/') or rel in ('evaluation-configs/'+label+'.json','evaluation-configs/'+label+'.policy.json') for label in labels))
                    write(REV/'import.json',dict(state='PASS_SHA_BOUND_SUBSET_IMPORT',receipt=receipt,observed_at=time.time()))
                except BaseException as error:write(REV/'import-failure.json',dict(error_type=type(error).__name__,observed_at=time.time()))
            threading.Thread(target=transfer,daemon=True).start()
            reserve=policy()['dsw_cpu_reservation']
            used=native_stage(mode,cpu_left-reserve,node)
            transferred=read(REV/'import.json')['receipt']['cpu_seconds']
            if transferred>reserve:raise ValueError('DSW subset CPU reservation exceeded')
            receipt=read(m.REV/mode/'completion.json')
            receipt.update(split_policy_sha256=digest(REV/'policy.json'),dsw_subset_cpu_seconds=transferred,dsw2_cpu_seconds=receipt['resources']['cpu_seconds'])
            receipt['resources']['cpu_seconds']+=transferred
            write(m.REV/mode/'completion.json',receipt)
            return used+transferred
        m.stage=stage
    r.install_adapters=adapters
    return r


def subset_status():
    if (REV/'completion.json').exists():return read(REV/'completion.json')
    if (REV/'launch.json').exists():
        row=read(REV/'launch.json')
        try:
            p=psutil.Process(row['pid'])
            if abs(p.create_time()-row['create_time'])<.01 and p.status()!=psutil.STATUS_ZOMBIE:
                return dict(row,state='RUNNING')
        except psutil.NoSuchProcess:pass
    return dict(state='NO_OWNER')


def subset_worker(token):
    p=policy();r=recovery();m=r.load('r9_subset_controller',ROOT/'eval-handoff-r4/controller.py');m.policy();m.TOKEN=token
    r.install_adapters(m)
    m.revised_evaluator()
    from scripts import prism_m75_evaluate as e
    from scripts.prism_dsw_ppo_process import ProcessTree
    # Original numerical runtime, exact prepared config and manifest, four cores.
    os.sched_setaffinity(0,range(4))
    execution=read(ROOT/'execution.json')
    from scripts import prism_m75_run as original
    if original.environment()!=execution['arena_environment']:raise ValueError('DSW arena drift')
    shards=[]
    for s in p['dsw_shards']:
        row=e.freeze_shard(s['label'],s['config'],512)
        if row['manifest_sha256']!=s['manifest_sha256']:raise ValueError('transferred manifest differs')
        shards.append(row)
    # The supervisor is outside the original waiting coordinator. Its complete
    # process-tree cost is carved out of DSW2's existing 60k reservation.
    out=REV/'stage';out.mkdir(exist_ok=True)
    attempts=read(REV/'charges.json') if (REV/'charges.json').exists() else []
    prior=sum(x['cpu_seconds'] for x in attempts)
    if (out/'status.json').exists():
        old=read(out/'status.json');cost=old['resources']['cpu_seconds']+max(0,time.time()-old['observed_at'])*4
        attempts.append(dict(cpu_seconds=cost,accounting='MEASURED_PLUS_OFFLINE_WALL_BOUND'));write(REV/'charges.json',attempts);prior+=cost
    os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',PRISM_PPO_CONTROL_DIR=str(out),PRISM_DSW_REMAINING_WALL=str(p['deadline']-time.time()))
    with (out/'stdout.log').open('ab') as stdout,(out/'stderr.log').open('ab') as stderr:
        with ProcessTree(cpu_seconds=p['dsw_cpu_reservation']-prior,memory_bytes=8*1024**3,max_processes=64) as tree:
            tree.start([sys.executable,'-B',str(__file__),'subset-child'],cwd=ROOT,stdout=stdout,stderr=stderr)
            resources=tree.wait(wall_seconds=p['deadline']-time.time(),storage_root=ROOT,max_storage_bytes=40802189312,snapshot=lambda counters:write(out/'status.json',dict(resources=counters,observed_at=time.time())))
    if resources['returncode'] or resources['stop_reason']:raise ValueError('subset stage failed')
    files=[]
    for s in shards:
        files += [x for x in Path(s['output']).rglob('*') if x.is_file()]
        files += [ROOT/'evaluation-configs'/f"{s['label']}{suffix}" for suffix in ('.json','.policy.json')]
    archive=REV/'evidence.zip';receipt=m.zip_members(archive,files)
    receipt.update(cpu_seconds=prior+resources['cpu_seconds'],split_policy_sha256=digest(REV/'policy.json'),labels=[s['label'] for s in shards])
    m.upload(archive,receipt,'split-r9-dsw-output')
    write(REV/'completion.json',dict(state='COMPLETED',receipt=receipt,observed_at=time.time()))


def ensure_subset(token):
    state=subset_status()
    if state['state'] in ('RUNNING','COMPLETED'):return state
    p=policy()
    with (REV/'owner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        attempts=read(REV/'attempts.json') if (REV/'attempts.json').exists() else []
        if len(attempts)>=2:raise ValueError('subset recovery allowance exhausted')
        child=os.fork()
        if child:
            row=dict(pid=child,create_time=psutil.Process(child).create_time(),state='STARTED',observed_at=time.time(),policy_sha256=digest(REV/'policy.json'))
            write(REV/'launch.json',row);write(REV/'attempts.json',attempts+[row]);return row
        os.setsid();fd=os.open(REV/f'attempt-{len(attempts)+1}.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        os.dup2(fd,1);os.dup2(fd,2);os.dup2(os.open('/dev/null',os.O_RDONLY),0)
        try:subset_worker(token)
        except BaseException as error:
            write(REV/'failure.json',dict(error_type=type(error).__name__,observed_at=time.time()));os._exit(1)
        os._exit(0)


def endpoint(mode):
    policy();r=recovery();role=r.contract()['role'];native_status=r.status;native_ensure=r.ensure
    def status():
        row=native_status();row['execution_revision']='split-eval-r9'
        if role=='dsw':
            subset=subset_status();row['split_subset']=subset
            if subset['state']=='RUNNING':row.update(state='RUNNING',phase='CANDIDATE_SUBSET_DSW')
            elif subset['state']=='NO_OWNER':row.update(state='NO_OWNER',phase='SUBSET_RECOVERY_REQUIRED')
        return row
    def ensure(token=None):
        if role=='dsw':
            if not token:
                from modelscope_hub import HubApi
                token=HubApi().legacy.token
            ensure_subset(token)
            # The original waiting owner remains alive; no duplicate coordinator.
            if native_status()['state'] in ('RUNNING','IDLE_WAIT'):return status()
        r.status=native_status
        try:return native_ensure(token)
        finally:r.status=status
    r.status=status;r.ensure=ensure
    return r.endpoint() if mode=='endpoint' else ensure()


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['endpoint','ensure-local','child','subset-child']);a.add_argument('stage',nargs='?');args=a.parse_args()
    if args.mode=='child':
        policy();r=recovery();m=r.load('r9_child',ROOT/'eval-handoff-r4/controller.py');r.install_adapters(m);m.child(args.stage)
    elif args.mode=='subset-child':
        p=policy();r=recovery();m=r.load('r9_subset_child',ROOT/'eval-handoff-r4/controller.py');m.revised_evaluator()
        from scripts import prism_m75_evaluate as e
        # Call the r8 dispatcher, before the cross-node join adapter.
        rbase=r.load('r9_base_install',ROOT/'reboot-resume-r8/recovery.py');rbase.install_adapters(m)
        shards=[e.freeze_shard(s['label'],s['config'],512) for s in p['dsw_shards']]
        done=e.dispatch(shards,limit=4,truncation_limit=7)
        write(REV/'shards-completion.json',dict(shards=done,observed_at=time.time()))
    else:
        try:print(json.dumps(endpoint(args.mode)))
        except Exception as error:
            print(json.dumps(dict(state='RECOVERY_BLOCKED',error_type=type(error).__name__)));sys.exit(1)
