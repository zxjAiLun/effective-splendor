"""M75 r4: preserve DSW training, execute remaining fixed evaluation on DSW2.

Deploy at ROOT/eval-handoff-r4/controller.py. Tokens are injected into the
controller's memory by the launcher, never persisted. Pinned predecessors stay
unchanged. Early c5/c10/c15 development cannot select the fixed final c20.
"""
import argparse,hashlib,importlib.util,json,os,subprocess,sys,time,zipfile
from pathlib import Path
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
REV=ROOT/'eval-handoff-r4'
from training.prism_portable.common import read,write,digest
from scripts.prism_dsw_ppo_process import ProcessTree,same_process
TOKEN=None

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def policy():
    p=read(REV/'policy.json')
    if digest(__file__)!=p['adapter_sha256'] or digest(ROOT/'execution.json')!=p['original_execution_sha256']:
        raise ValueError('r4 execution/source drift')
    for rel,h in p['predecessor_files'].items():
        if digest(ROOT/rel)!=h:raise ValueError('r4 predecessor drift: '+rel)
    for rel,h in read(ROOT/'execution.json')['files'].items():
        if digest(ROOT/rel)!=h:raise ValueError('original pin drift: '+rel)
    if time.time()>=p['deadline']:raise ValueError('r4 deadline exhausted')
    return p

def publish(phase,**kw):
    p=policy();write(REV/'status.json',dict(state='RUNNING',phase=phase,pid=os.getpid(),create_time=psutil.Process().create_time(),observed_at=time.time(),deadline=p['deadline'],policy_sha256=digest(REV/'policy.json'),**kw))

def verify_arena():
    from scripts import prism_m75_run as original
    c=original.contract();execution=read(ROOT/'execution.json');env=original.environment()
    expected=execution['arena_environment']
    # r4 explicitly changes allocation to eight cores; every other field is exact.
    if env['affinity']!=list(range(8)) or dict(env,affinity=expected['affinity'])!=expected:
        raise ValueError('DSW2 arena runtime drift')
    policy();return c,execution

def revised_evaluator():
    from scripts import prism_m75_evaluate as e
    native=e.read
    e.read=lambda path:dict(native(path),deadline=policy()['deadline']) if Path(path).resolve()==(ROOT/'round-budget.json').resolve() else native(path)
    return e

def development_shards(cycles):
    c,_=verify_arena();dev=c['development'];e=revised_evaluator();shards=[]
    for cycle in cycles:
        path=ROOT/f'campaigns/a/cycle-{cycle}-export/weights.json'
        h=digest(path)
        if cycle<20 and h!=policy()['early_export_sha256'][str(cycle)]:raise ValueError('early export drift')
        if cycle==20 and h!=read(ROOT/'candidate-registry.json')['models']['a']['sha256']:raise ValueError('final candidate drift')
        for start in range(dev['seed_start'],dev['seed_end']+1,32):
            label=f'development-curve-c{cycle}-{start}'
            shards.append(e.freeze_shard(label,e.config([f'curve-c{cycle}'],['parent'],list(range(start,min(start+32,dev['seed_end']+1)))),c['evaluation']['ply_cap']))
    if sum(s['planned_games'] for s in shards)!=len(cycles)*256:raise ValueError('development grid drift')
    return shards

def arena_child(mode):
    verify_arena();e=revised_evaluator();p=policy()
    if mode=='early-development':
        shards=development_shards([5,10,15]);write(REV/'early-development-plan.json',dict(shards=shards,total_games=768,selection='fixed final c20; development does not alter training'))
        done=e.dispatch(shards,limit=8,truncation_limit=p['development_truncation_limit'])
        write(REV/'early-development-completion.json',dict(shards=done,completed_games=sum(x['grid']['completed_games'] for x in done),truncated_games=sum(x['grid']['truncated_games'] for x in done),finished_at=time.time()))
        return
    if mode=='final-evaluation':
        early=read(REV/'early-development-completion.json');final=development_shards([20])
        done=e.dispatch(final,limit=8,truncation_limit=p['development_truncation_limit']-early['truncated_games'])
        all_dev=early['shards']+done
        write(REV/'all-development-completion.json',dict(shards=all_dev,completed_games=sum(x['grid']['completed_games'] for x in all_dev),truncated_games=sum(x['grid']['truncated_games'] for x in all_dev)))
        from scripts import prism_m75_curve as curve
        source=curve.__file__
        text=Path(source).read_text()
        old="if out.exists():raise ValueError('development already attempted')\n    out.mkdir()"
        if text.count(old)!=1:raise ValueError('curve adapter target drift')
        ns={'__name__':'m75_r4_curve','__file__':source}
        exec(compile(text.replace(old,'out.mkdir(exist_ok=True)'),str(REV/'controller.py')+'::curve', 'exec'),ns)
        by_label={s['label']:s for s in all_dev}
        def reuse(label,cfg,cap):
            if label not in by_label or read(ROOT/'evaluation-configs'/f'{label}.json')!=cfg:raise ValueError('development reuse/config mismatch')
            return {k:v for k,v in by_label[label].items() if k!='grid'}
        def completed(shards,**kw):
            if {s['label'] for s in shards}!=set(by_label):raise ValueError('development completion set drift')
            return all_dev
        ns.update(verify=lambda training=False:verify_arena(),freeze_shard=reuse,dispatch=completed)
        ns['build']()
        d=load('r4_dual',ROOT/'dual-node-r3/dual_node.py');shards=d.freeze('a');base=read(ROOT/'dual-node-r3/baseline-completion.json')
        registry=read(ROOT/'candidate-registry.json')
        if registry['models']['a']['audit_sha256']!=digest(ROOT/'audits/a/audit.json'):raise ValueError('final audit binding drift')
        write(ROOT/'evaluation-plan.json',dict(format='m75-bounded-shards-v1',config_sha256=digest(ROOT/'benchmarks/m75-prism-continuation.config.json'),candidate_registry_sha256=digest(ROOT/'candidate-registry.json'),shards=base['shards']+shards,total_games=9216,workers=8,placement={'dsw2':9216,'dsw':0},dispatch_policy_sha256=digest(REV/'policy.json'),execution_revision='eval-handoff-r4'))
        done=e.dispatch(shards,limit=8,truncation_limit=p['independent_truncation_limit']-base['truncated_games'])
        all_done=base['shards']+done
        write(ROOT/'evaluation-completion.json',dict(status='FINISHED_WITH_EXPLICIT_MISSINGNESS',shards=all_done,completed_games=sum(x['grid']['completed_games'] for x in all_done),truncated_games=sum(x['grid']['truncated_games'] for x in all_done),automatic_retries=0,finished_at=time.time(),plan_sha256=digest(ROOT/'evaluation-plan.json'),execution_revision='eval-handoff-r4'))
        return
    raise ValueError('unknown evaluation stage')

def stage(mode,cpu_left,node):
    p=policy();out=REV/mode;out.mkdir(exist_ok=False)
    py=p['training_python'] if mode=='audit' else p['arena_python']
    os.environ.update(PRISM_PPO_CONTROL_DIR=str(out),PRISM_DSW_REMAINING_WALL=str(p['deadline']-time.time()),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
        with ProcessTree(cpu_seconds=cpu_left,memory_bytes=(16 if node=='dsw2' else 8)*1024**3,max_processes=128) as tree:
            tree.start([py,'-B',str(Path(__file__).resolve()),'child',mode],cwd=ROOT,stdout=stdout,stderr=stderr)
            resources=tree.wait(wall_seconds=p['deadline']-time.time(),storage_root=ROOT,max_storage_bytes=p[node+'_storage_bytes'],storage_interval=60,snapshot=lambda counters:write(out/'status.json',dict(state='RUNNING',resources=counters,observed_at=time.time())))
    receipt=dict(state='PASS' if resources['returncode']==0 and not resources['stop_reason'] else 'FAILED',resources=resources,finished_at=time.time())
    write(out/'completion.json',receipt)
    if receipt['state']!='PASS':raise ValueError('r4 stage failed: '+mode)
    return resources['cpu_seconds']

def zip_members(archive,files):
    members={}
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for f in sorted(set(files)):
            rel=f.relative_to(ROOT).as_posix();members[rel]=digest(f);z.write(f,rel)
        z.writestr('transfer-manifest.json',json.dumps(members,sort_keys=True))
    return dict(sha256=digest(archive),bytes=archive.stat().st_size,members=len(members),policy_sha256=digest(REV/'policy.json'))

def extract_bound(archive,receipt,allowed):
    if receipt['policy_sha256']!=digest(REV/'policy.json') or archive.stat().st_size!=receipt['bytes'] or digest(archive)!=receipt['sha256']:raise ValueError('r4 archive binding mismatch')
    with zipfile.ZipFile(archive) as z:
        members=json.loads(z.read('transfer-manifest.json'))
        if set(z.namelist())!=set(members)|{'transfer-manifest.json'} or len(members)!=receipt['members']:raise ValueError('r4 member set mismatch')
        for rel,h in members.items():
            path=Path(rel)
            if path.is_absolute() or '..' in path.parts or not allowed(rel):raise ValueError('r4 archive path refused')
            raw=z.read(rel);dest=ROOT/rel
            if hashlib.sha256(raw).hexdigest()!=h or dest.exists():raise ValueError('r4 corrupt/conflicting import')
        for rel in members:
            dest=ROOT/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(rel))
    return members

def hub():
    from modelscope_hub import HubApi
    api=HubApi(token=TOKEN)
    if int(api.get_repo(policy()['repo'],'dataset').visibility)!=1:raise ValueError('cloud privacy drift')
    return api

def upload(archive,receipt,label):
    p=policy();repo=p['repo'];prefix=p['cloud_prefix']+'/'+label
    receipt_path=REV/(label+'-receipt.json');write(receipt_path,receipt)
    for attempt in range(1,p['transport_attempts']+1):
        try:
            api=hub();listed={f.path:f for f in api.list_repo_files(repo,'dataset')}
            for filename,file in (('evidence.zip',archive),('receipt.json',receipt_path)):
                h=digest(file);row=listed.get(prefix+'/'+filename)
                if row is None or row.sha256!=h or row.size!=file.stat().st_size:
                    api.upload_file(repo,'dataset',file,prefix+'/'+filename,commit_message='M75 r4 fixed evaluation handoff '+label,disable_tqdm=True)
            listed={f.path:f for f in api.list_repo_files(repo,'dataset')}
            if listed[prefix+'/evidence.zip'].sha256!=receipt['sha256'] or listed[prefix+'/receipt.json'].sha256!=digest(receipt_path):raise ValueError('cloud metadata drift')
            write(REV/(label+'-cloud.json'),dict(status='PASS_PRIVATE_CLOUD_METADATA',receipt=receipt,attempt=attempt,observed_at=time.time()));return
        except Exception as error:
            write(REV/(label+'-transport.json'),dict(state='RETRY_WAIT',attempt=attempt,error_type=type(error).__name__,observed_at=time.time()))
            if attempt==p['transport_attempts']:raise ValueError('finite cloud upload attempts exhausted') from None
            time.sleep(min(20*attempt,max(0,p['deadline']-time.time())))

def receive(label):
    p=policy();repo=p['repo'];prefix=p['cloud_prefix']+'/'+label
    while time.time()<p['deadline']:
        try:
            api=hub();listed={f.path:f for f in api.list_repo_files(repo,'dataset')}
            if prefix+'/receipt.json' not in listed:
                publish('WAIT_'+label.upper());time.sleep(20);continue
            receipt=read(api.download_file(repo,'dataset',prefix+'/receipt.json',expected_sha256=listed[prefix+'/receipt.json'].sha256,cache_dir=REV/'receipt-cache'))
            if receipt['policy_sha256']!=digest(REV/'policy.json'):raise ValueError('receipt revision drift')
            row=listed[prefix+'/evidence.zip']
            if row.sha256!=receipt['sha256'] or row.size!=receipt['bytes']:raise ValueError('cloud artifact metadata mismatch')
            cached=Path(api.download_file(repo,'dataset',prefix+'/evidence.zip',expected_sha256=receipt['sha256'],cache_dir=REV/'artifact-cache'))
            return cached,receipt
        except (ValueError,KeyError):raise
        except Exception as error:
            publish('TRANSPORT_READ_RETRY_'+label.upper(),last_error_type=type(error).__name__);time.sleep(20)
    raise ValueError('r4 finite receive deadline')

def dsw2():
    p=policy();archive=REV/'early-input.zip';receipt=read(REV/'early-input-receipt.json')
    extract_bound(archive,receipt,lambda rel:rel in {f'campaigns/a/cycle-{c}-export/weights.json' for c in (5,10,15)})
    publish('EARLY_DEVELOPMENT_768_DSW2');used=stage('early-development',p['dsw2_cpu_reservation'],'dsw2')
    publish('WAIT_FINAL_C20_FROM_DSW',consumed_cpu_seconds=used)
    archive,receipt=receive('final-input')
    extract_bound(archive,receipt,lambda rel:rel in {'campaigns/a/cycle-20-export/weights.json','candidate-registry.json','audits/a/audit.json'})
    publish('FINAL_DEVELOPMENT_256_AND_CANDIDATE_5120_DSW2',consumed_cpu_seconds=used)
    used+=stage('final-evaluation',p['dsw2_cpu_reservation']-used,'dsw2')
    files=[]
    for directory in (ROOT/'evaluation',ROOT/'evaluation-configs'):
        for f in directory.rglob('*'):
            if f.is_file() and any(part.startswith(('a-','development-')) for part in f.relative_to(directory).parts):files.append(f)
    files+=list((ROOT/'development').rglob('*'))
    files+=[ROOT/'evaluation-plan.json',ROOT/'evaluation-completion.json',ROOT/'docs/prism/m75-prism-continuation-curve.html',ROOT/'docs/prism/m75-prism-continuation-curve.md',REV/'early-development/completion.json',REV/'final-evaluation/completion.json']
    files=[f for f in files if f.is_file()]
    archive=REV/'evaluation-evidence.zip';receipt=zip_members(archive,files);receipt.update(cpu_seconds=used,evaluation=read(ROOT/'evaluation-completion.json')['completed_games'],development=read(ROOT/'development/completion.json')['completed_games'])
    publish('UPLOADING_COMPLETED_EVALUATION_DSW2',consumed_cpu_seconds=used);upload(archive,receipt,'evaluation-output')
    write(REV/'completion.json',dict(state='PASS_EVALUATION_DELIVERED',receipt=receipt,finished_at=time.time()))
    publish('EVALUATION_DELIVERED_DSW2',consumed_cpu_seconds=used)

def dsw():
    p=policy();h=load('r4_handoff',ROOT/'dual-node-r3/handoff.py');d,b=h.controller()
    native_write=d.write
    def isolated(path,value):
        path=Path(path)
        if path.parent==ROOT/'dual-node-r3' and path.name in ('status.json','handoff.json','handoff-completion.json'):path=REV/path.name
        native_write(path,value)
    d.write=isolated
    publish('TRAINING_UNCHANGED_DSW');used=p['previous_cpu_seconds']+d.monitor_training(d.policy())
    publish('TRAINING_AUDIT_DSW',consumed_cpu_seconds=used)
    budget=lambda:p['total_cpu_seconds']-used-p['baseline_cpu_seconds']-p['dsw2_cpu_reservation']
    used+=stage('audit',budget(),'dsw');used+=stage('candidates',budget(),'dsw')
    files=[ROOT/'campaigns/a/cycle-20-export/weights.json',ROOT/'candidate-registry.json',ROOT/'audits/a/audit.json']
    archive=REV/'final-input.zip';receipt=zip_members(archive,files)
    publish('PUBLISH_FINAL_C20_TO_DSW2',consumed_cpu_seconds=used);upload(archive,receipt,'final-input')
    d.import_baseline()
    publish('WAIT_DSW2_EVALUATION_OUTPUT',consumed_cpu_seconds=used);archive,receipt=receive('evaluation-output')
    def allowed(rel):
        return rel.startswith(('evaluation/a-','evaluation/development-','evaluation-configs/a-','evaluation-configs/development-','development/')) or rel in ('evaluation-plan.json','evaluation-completion.json','docs/prism/m75-prism-continuation-curve.html','docs/prism/m75-prism-continuation-curve.md','eval-handoff-r4/early-development/completion.json','eval-handoff-r4/final-evaluation/completion.json')
    members=extract_bound(archive,receipt,allowed)
    plan=read(ROOT/'evaluation-plan.json');done=read(ROOT/'evaluation-completion.json')
    expected={row[0] for rows in d.validate_partition(read(ROOT/'benchmarks/m75-prism-continuation.config.json')).values() for row in rows}
    if {s['label'] for s in plan['shards']}!=expected or done['plan_sha256']!=digest(ROOT/'evaluation-plan.json') or plan['candidate_registry_sha256']!=digest(ROOT/'candidate-registry.json'):raise ValueError('merged grid/identity drift')
    used+=p['baseline_cpu_seconds']+receipt['cpu_seconds']
    write(REV/'output-import.json',dict(state='PASS_ORIGINAL_BYTES_COMPLETE_SHARD_SET',receipt=receipt,members=len(members),observed_at=time.time()))
    publish('MERGED_REPORT_DSW',consumed_cpu_seconds=used);used+=stage('report',p['total_cpu_seconds']-used,'dsw')
    result=dict(state='COMPLETED',phase='RESULTS_AND_REPORTS_READY',total_consumed_cpu_seconds=used,finished_at=time.time(),policy_sha256=digest(REV/'policy.json'))
    write(REV/'completion.json',result);write(REV/'status.json',result)

def child(mode):
    if mode in ('early-development','final-evaluation'):
        os.sched_setaffinity(0,range(8));arena_child(mode)
    else:
        os.sched_setaffinity(0,range(4));r2=load('r4_resume',ROOT/'continuation-r2/resume.py');r2.child(mode)

def run(role):
    os.sched_setaffinity(0,range(8) if role=='dsw2' else range(4))
    try:globals()[role]()
    except BaseException as error:
        # Errors and immutable stage logs are preserved; research games are not retried.
        write(REV/'failure.json',dict(state='FAILED',error_type=type(error).__name__,error=str(error) if TOKEN is None or TOKEN not in str(error) else 'redacted',observed_at=time.time()));raise

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['child']);ap.add_argument('stage');a=ap.parse_args();child(a.stage)
