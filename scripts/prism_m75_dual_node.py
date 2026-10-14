"""M75 r3: serial training on DSW, disjoint blind parent evaluation on DSW2.

Deploy as ROOT/dual-node-r3/dual_node.py. All original pinned bytes stay intact.
The outer r2 dispatcher is suspended while its independently bounded training
relay continues; replacement happens only after that relay finishes successfully.
"""
import argparse,hashlib,importlib.util,json,os,signal,subprocess,sys,time,zipfile
from pathlib import Path
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
REV=ROOT/'dual-node-r3'
from training.prism_portable.common import read,write,digest
from training.prism_portable.processes import directory_bytes
from scripts.prism_dsw_ppo_process import ProcessTree,same_process
from scripts import prism_m75_evaluate as evaluation,prism_bounded_eval as bounded

def policy():
    p=read(REV/'policy.json')
    if digest(__file__)!=p['adapter_sha256']:raise ValueError('r3 source drift')
    if digest(ROOT/'execution.json')!=p['original_execution_sha256']:raise ValueError('original execution drift')
    if any(digest(ROOT/n)!=h for n,h in read(ROOT/'execution.json')['files'].items()):raise ValueError('pinned original source/input drift')
    if time.time()>=p['deadline']:raise ValueError('finite r3 deadline exhausted')
    return p

def assigned(c,model):
    e=c['evaluation'];cohorts={**e['common_seed_by_opponent'],**e['coverage_seed_by_opponent']}
    if model=='a':cohorts['parent']=[e['direct_seed_start'],e['direct_seed_end']]
    result=[]
    for opp,(lo,hi) in cohorts.items():
        for start in range(lo,hi+1,32):result.append((f'{model}-{opp}-{start}',model,opp,list(range(start,min(start+32,hi+1)))))
    return result

def validate_partition(c):
    groups={m:assigned(c,m) for m in ('base','a')}
    keys={m:{(model,opp,s,seat) for _,model,opp,seeds in rows for s in seeds for seat in (0,1)} for m,rows in groups.items()}
    if len(keys['base'])!=4096 or len(keys['a'])!=5120 or keys['base']&keys['a']:raise ValueError('partition overlap/count drift')
    return groups

def freeze(model):
    p=policy();c=read(ROOT/'benchmarks/m75-prism-continuation.config.json');groups=validate_partition(c)
    old=evaluation.read
    def adjusted(path):
        value=old(path)
        return dict(value,deadline=p['deadline']) if Path(path).resolve()==(ROOT/'round-budget.json').resolve() else value
    evaluation.read=adjusted
    try:return [evaluation.freeze_shard(label,evaluation.config([m],[opp],seeds),c['evaluation']['ply_cap']) for label,m,opp,seeds in groups[model]]
    finally:evaluation.read=old

def bounded_stage(mode,cpu,storage,memory,processes):
    p=policy();out=REV/mode;out.mkdir(exist_ok=False)
    os.environ.update(PRISM_PPO_CONTROL_DIR=str(out),PRISM_DSW_REMAINING_WALL=str(p['deadline']-time.time()),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
        with ProcessTree(cpu_seconds=cpu,memory_bytes=memory,max_processes=processes) as tree:
            tree.start([p['arena_python'],'-B',str(Path(__file__).resolve()),'child',mode],cwd=ROOT,stdout=stdout,stderr=stderr)
            resources=tree.wait(wall_seconds=p['deadline']-time.time(),storage_root=ROOT,max_storage_bytes=storage,storage_interval=60,
                snapshot=lambda r:write(out/'status.json',dict(state='RUNNING',resources=r,observed_at=time.time())))
    done=dict(state='PASS' if resources['returncode']==0 and not resources['stop_reason'] else 'FAILED',resources=resources,finished_at=time.time())
    write(out/'completion.json',done)
    if done['state']!='PASS':raise ValueError(mode+' failed: '+str(resources))
    return done

def baseline_child():
    p=policy();plan=read(REV/'baseline-plan.json')
    old=evaluation.read
    evaluation.read=lambda path:dict(old(path),deadline=p['deadline']) if Path(path).resolve()==(ROOT/'round-budget.json').resolve() else old(path)
    done=evaluation.dispatch(plan['shards'],limit=p['dsw2_workers'],truncation_limit=p['independent_truncation_limit'])
    write(REV/'baseline-completion.json',dict(status='FINISHED_WITH_EXPLICIT_MISSINGNESS',shards=done,completed_games=sum(s['grid']['completed_games'] for s in done),truncated_games=sum(s['grid']['truncated_games'] for s in done),plan_sha256=digest(REV/'baseline-plan.json'),finished_at=time.time(),automatic_retries=0))

def baseline():
    p=policy();shards=freeze('base')
    plan=dict(format='m75-r3-baseline-plan-v1',node='dsw2',blind_parent_only=True,shards=shards,total_games=4096,policy_sha256=digest(REV/'policy.json'),parent_sha256=read(ROOT/'inputs/parent.manifest.json')['weights_sha256'] if 'weights_sha256' in read(ROOT/'inputs/parent.manifest.json') else digest(ROOT/'inputs/parent.json'))
    write(REV/'baseline-plan.json',plan)
    stage=bounded_stage('baseline-worker',p['baseline_cpu_reservation'],p['dsw2_storage_bytes'],16*1024**3,128)
    done=read(REV/'baseline-completion.json');members={}
    archive=REV/'baseline-evidence.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for shard in shards:
            for f in Path(shard['output']).rglob('*'):
                if f.is_file():
                    rel=f.relative_to(ROOT).as_posix();members[rel]=digest(f);z.write(f,rel)
        for f in (REV/'baseline-plan.json',REV/'baseline-completion.json',REV/'baseline-worker/completion.json'):
            rel=f.relative_to(ROOT).as_posix();members[rel]=digest(f);z.write(f,rel)
        z.writestr('transfer-manifest.json',json.dumps(members,sort_keys=True))
    receipt=dict(state='BASELINE_READY',archive=str(archive),bytes=archive.stat().st_size,sha256=digest(archive),members=len(members),completed_games=done['completed_games'],truncated_games=done['truncated_games'],cpu_seconds=stage['resources']['cpu_seconds'],policy_sha256=digest(REV/'policy.json'),observed_at=time.time())
    write(REV/'transfer-ready.json',receipt);return receipt

def import_baseline():
    p=policy();receipt=read(REV/'inbox/transfer-ready.json');archive=REV/'inbox/baseline-evidence.zip'
    if receipt['policy_sha256']!=digest(REV/'policy.json') or digest(archive)!=receipt['sha256'] or archive.stat().st_size!=receipt['bytes']:raise ValueError('remote transfer binding drift')
    with zipfile.ZipFile(archive) as z:
        members=json.loads(z.read('transfer-manifest.json'))
        if len(members)!=receipt['members'] or set(z.namelist())!=set(members)|{'transfer-manifest.json'}:raise ValueError('archive member drift')
        for rel,h in members.items():
            path=Path(rel)
            if path.is_absolute() or '..' in path.parts or not (rel.startswith('evaluation/base-') or rel in ('dual-node-r3/baseline-plan.json','dual-node-r3/baseline-completion.json','dual-node-r3/baseline-worker/completion.json')):raise ValueError('unsafe archive member')
            raw=z.read(rel)
            if hashlib.sha256(raw).hexdigest()!=h or (ROOT/rel).exists():raise ValueError('import corruption or existing dispatch')
        for rel in members:
            dest=ROOT/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(rel))
    done=read(REV/'baseline-completion.json');plan=read(REV/'baseline-plan.json')
    if done['plan_sha256']!=digest(REV/'baseline-plan.json'):raise ValueError('baseline plan drift')
    if {s['label'] for s in plan['shards']}!={r[0] for r in assigned(read(ROOT/'benchmarks/m75-prism-continuation.config.json'),'base')}:raise ValueError('remote assignment drift')
    for shard in plan['shards']:
        dest=Path(shard['output']);grid=bounded.inspect(dest)
        if digest(dest/'manifest.json')!=shard['manifest_sha256'] or grid['execution_state']!='FINISHED':raise ValueError('remote shard not finished')
    if receipt['cpu_seconds']>p['baseline_cpu_reservation']:raise ValueError('remote CPU reservation exceeded')
    write(REV/'baseline-import.json',dict(status='PASS_RAW_BYTES_MANIFEST_GRID',receipt=receipt,observed_at=time.time()))
    return receipt,plan,done

def candidate_child():
    p=policy();plan=read(ROOT/'evaluation-plan.json');remote=read(REV/'baseline-completion.json')
    shards=[s for s in plan['shards'] if s['label'].startswith('a-')]
    old=evaluation.read
    evaluation.read=lambda path:dict(old(path),deadline=p['deadline']) if Path(path).resolve()==(ROOT/'round-budget.json').resolve() else old(path)
    done=evaluation.dispatch(shards,limit=4,truncation_limit=p['independent_truncation_limit']-remote['truncated_games'])
    all_done=remote['shards']+done
    write(ROOT/'evaluation-completion.json',dict(status='FINISHED_WITH_EXPLICIT_MISSINGNESS',shards=all_done,completed_games=sum(s['grid']['completed_games'] for s in all_done),truncated_games=sum(s['grid']['truncated_games'] for s in all_done),automatic_retries=0,finished_at=time.time(),plan_sha256=digest(ROOT/'evaluation-plan.json'),execution_revision='dual-node-r3'))

def load_recovery():
    spec=importlib.util.spec_from_file_location('m75_r2',ROOT/'continuation-r2/resume.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def handoff_contract(p,parent,relay,worker):
    if not same_process(parent.pid,p['r2_parent_created']) or parent.cmdline()[-1]!='pipeline':raise ValueError('outer dispatcher identity drift')
    status=read(ROOT/'continuation-r2/status.json')
    if status['phase']!='train' or status['state']!='RUNNING':raise ValueError('cannot transfer after dispatch phase changed')
    if not same_process(relay.pid,p['train_relay_created']) or not same_process(worker.pid,p['train_worker_created']):raise ValueError('training identity drift')
    if worker.ppid()!=relay.pid or relay.ppid()!=parent.pid:raise ValueError('training ownership drift')

def monitor_training(p):
    parent=psutil.Process(p['r2_parent_pid']);relay=psutil.Process(p['train_relay_pid']);worker=psutil.Process(p['train_worker_pid'])
    handoff_contract(p,parent,relay,worker)
    os.kill(parent.pid,signal.SIGSTOP)
    write(REV/'handoff.json',dict(state='OUTER_DISPATCH_HELD_TRAINING_CONTINUES',parent_pid=parent.pid,relay_pid=relay.pid,worker_pid=worker.pid,policy_sha256=digest(REV/'policy.json'),observed_at=time.time()))
    next_scan=0
    while True:
        resources=read(p['train_relay_record'])
        if resources['status']=='FINISHED':break
        if not same_process(parent.pid,p['r2_parent_created']) or parent.status()!=psutil.STATUS_STOPPED or not same_process(relay.pid,p['train_relay_created']):raise ValueError('held dispatcher or training relay lost')
        if time.time()>=p['deadline']:raise ValueError('training deadline')
        if time.time()>=next_scan:
            next_scan=time.time()+60
            if directory_bytes(ROOT)>p['dsw_storage_bytes'] or directory_bytes(ROOT/'campaigns/a')>p['training_storage_bytes']:raise ValueError('training storage exhausted')
        write(REV/'status.json',dict(state='RUNNING',phase='TRAINING_DSW_BASELINE_DSW2',pid=os.getpid(),create_time=psutil.Process().create_time(),observed_at=time.time(),training_resources=resources,progress=read(ROOT/'continuation-r2/live-progress.json')))
        time.sleep(2)
    if resources['returncode']!=0 or resources['stop_reason']:raise ValueError('training relay did not finish safely')
    complete=read(ROOT/'campaigns/a/worker-completion.json')
    if complete['physical_attempts']!=5120 or complete['cycle']!=20 or complete['status']!='STOPPED_COMMITTED':raise ValueError('training final incomplete')
    wait_until=time.time()+15
    while any(c.status()!=psutil.STATUS_ZOMBIE for c in parent.children(recursive=True)):
        if time.time()>=wait_until:raise ValueError('dispatcher children still active')
        time.sleep(.1)
    os.kill(parent.pid,signal.SIGKILL)
    done=dict(state='PASS',resources=resources,finished_at=time.time(),continuation_dispatch_revision='dual-node-r3')
    write(ROOT/'continuation-r2/train/completion.json',done)
    dest=ROOT/'control/a/completion.json'
    if dest.exists():raise ValueError('training completion exists')
    write(dest,dict(state='STOPPED_COMMITTED',completed_games=complete['games'],completion=complete,resources=resources,finished_at=time.time(),continuation_policy_sha256=digest(ROOT/'continuation-r2/policy.json'),dispatch_policy_sha256=digest(REV/'policy.json')))
    write(REV/'handoff-completion.json',dict(state='PASS_TRAINING_FINAL_UNCHANGED_OLD_DISPATCH_SUPERSEDED',resources=resources,training=complete,observed_at=time.time()))
    return resources['cpu_seconds']

def coordinator():
    p=policy();used=p['previous_cpu_seconds']+monitor_training(p);r2=load_recovery()
    for mode in ('audit','candidates','curve'):
        write(REV/'status.json',dict(state='RUNNING',phase=mode,consumed_cpu_seconds=used,pid=os.getpid(),observed_at=time.time()))
        result=r2.stage(mode,p['total_cpu_seconds']-used-p['baseline_cpu_reservation']);used+=result['resources']['cpu_seconds']
    write(REV/'status.json',dict(state='RUNNING',phase='WAIT_BASELINE_TRANSFER',pid=os.getpid(),observed_at=time.time()))
    while not (REV/'inbox/transfer-ready.json').exists() or not (REV/'inbox/baseline-evidence.zip').exists():
        if time.time()>=p['deadline']:raise ValueError('baseline transfer deadline')
        time.sleep(5)
    receipt,remote,done=import_baseline();used+=receipt['cpu_seconds']
    shards=remote['shards']+freeze('a');registry=read(ROOT/'candidate-registry.json')
    for v in registry['models'].values():
        if digest(v['path'])!=v['sha256']:raise ValueError('final candidate drift')
    write(ROOT/'evaluation-plan.json',dict(format='m75-bounded-shards-v1',config_sha256=digest(ROOT/'benchmarks/m75-prism-continuation.config.json'),candidate_registry_sha256=digest(ROOT/'candidate-registry.json'),shards=shards,total_games=9216,workers=4,placement={'dsw2':4096,'dsw':5120},dispatch_policy_sha256=digest(REV/'policy.json')))
    write(REV/'status.json',dict(state='RUNNING',phase='CANDIDATE_EVALUATION_DSW',pid=os.getpid(),observed_at=time.time()))
    result=bounded_stage('candidate-worker',p['total_cpu_seconds']-used,p['dsw_storage_bytes'],8*1024**3,64);used+=result['resources']['cpu_seconds']
    result=r2.stage('report',p['total_cpu_seconds']-used);used+=result['resources']['cpu_seconds']
    state=dict(state='COMPLETED',phase='RESULTS_AND_REPORTS_READY',total_consumed_cpu_seconds=used,finished_at=time.time(),policy_sha256=digest(REV/'policy.json'))
    write(REV/'status.json',state);write(REV/'completion.json',state);return state

def start(role):
    p=policy();policy_path=REV/'policy.json'
    if role=='coordinator':handoff_contract(p,psutil.Process(p['r2_parent_pid']),psutil.Process(p['train_relay_pid']),psutil.Process(p['train_worker_pid']))
    else:
        if read(REV/'preflight.json')['status']!='PASS_DSW2_ZERO_GAME_PREFLIGHT':raise ValueError('DSW2 preflight absent')
        if (ROOT/'evaluation').exists():raise ValueError('baseline was already dispatched')
    with (REV/(role+'-once.lock')).open('x'):pass
    with (REV/(role+'-supervisor.log')).open('xb') as log:
        proc=subprocess.Popen([p['training_python'] if role=='coordinator' else p['arena_python'],'-B',str(Path(__file__).resolve()),role],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    row=dict(state='STARTED',node='dsw' if role=='coordinator' else 'dsw2',role=role,pid=proc.pid,create_time=psutil.Process(proc.pid).create_time(),policy_sha256=digest(policy_path),deadline=p['deadline'],observed_at=time.time())
    write(REV/(role+'-launch.json'),row);return row

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=('start','coordinator','baseline','child'));ap.add_argument('role',nargs='?');a=ap.parse_args()
    os.sched_setaffinity(0,range(8) if a.role=='baseline' or a.mode=='baseline' or a.role=='baseline-worker' else range(4))
    try:
        result=start(a.role) if a.mode=='start' else baseline_child() if a.mode=='child' and a.role=='baseline-worker' else candidate_child() if a.mode=='child' else globals()[a.mode]()
        print(json.dumps(result))
    except BaseException as error:
        if a.mode not in ('start','child'):write(REV/(a.mode+'-failure.json'),dict(state='FAILED',error=repr(error),observed_at=time.time()))
        raise
